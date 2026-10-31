//! Narrow read-only Codex app-server adapter for P0.
//!
//! Uses a dedicated stdio child per CLI operation. It does not create turns,
//! resume sessions, execute shell commands, read conversation contents, or
//! expose a general JSON-RPC passthrough.

use serde_json::{json, Value};
use std::error::Error;
use std::fmt;
use std::io::{self, BufRead, BufReader, Write};
use std::path::Path;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

const MAX_FRAME_BYTES: usize = 2 * 1024 * 1024;
const MAX_NOTIFICATIONS: usize = 1024;
const REQUEST_TIMEOUT: Duration = Duration::from_secs(15);

#[derive(Debug)]
pub enum CodexError {
    Io(io::Error),
    Timeout,
    Closed,
    InvalidFrame,
    Protocol(&'static str),
    Rpc(i64),
}

impl fmt::Display for CodexError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io(error) => write!(f, "Codex subprocess I/O error: {error}"),
            Self::Timeout => write!(f, "Codex app-server request timed out"),
            Self::Closed => write!(f, "Codex app-server closed its output"),
            Self::InvalidFrame => write!(f, "Codex app-server returned invalid JSON"),
            Self::Protocol(msg) => write!(f, "Codex app-server protocol error: {msg}"),
            Self::Rpc(code) => write!(f, "Codex app-server JSON-RPC error code {code}"),
        }
    }
}

impl Error for CodexError {}

impl From<io::Error> for CodexError {
    fn from(error: io::Error) -> Self {
        Self::Io(error)
    }
}

type Result<T> = std::result::Result<T, CodexError>;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SessionSummary {
    pub id: String,
    pub status: &'static str,
    pub created_at: u64,
    pub updated_at: u64,
}

#[derive(Debug, Clone)]
pub struct SessionPage {
    pub threads: Vec<SessionSummary>,
    pub next_cursor: Option<String>,
}

/// Notifications received by this short-lived connection while a read-only
/// request was pending. These are not events from an independent Codex TUI.
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct ObservedEvents {
    pub thread: u32,
    pub turn: u32,
    pub item: u32,
    pub other: u32,
}

impl ObservedEvents {
    fn record(&mut self, method: &str) {
        let counter = if method.starts_with("thread/") {
            &mut self.thread
        } else if method.starts_with("turn/") {
            &mut self.turn
        } else if method.starts_with("item/") {
            &mut self.item
        } else {
            &mut self.other
        };
        *counter = counter.saturating_add(1);
    }
}

pub struct CodexClient {
    child: Child,
    stdin: Option<ChildStdin>,
    frames: Receiver<io::Result<Vec<u8>>>,
    reader: Option<JoinHandle<()>>,
    next_id: u64,
    timeout: Duration,
    platform_os: String,
    observed_events: ObservedEvents,
}

/// Read exactly one bounded JSONL frame without unbounded allocation.
fn read_frame(reader: &mut impl BufRead) -> io::Result<Option<Vec<u8>>> {
    let mut frame = Vec::new();
    loop {
        let available = reader.fill_buf()?;
        if available.is_empty() {
            return if frame.is_empty() {
                Ok(None)
            } else {
                Err(io::Error::new(io::ErrorKind::UnexpectedEof, "partial JSONL frame"))
            };
        }
        let take = available
            .iter()
            .position(|byte| *byte == b'\n')
            .map(|index| index + 1)
            .unwrap_or(available.len());
        if frame.len().saturating_add(take) > MAX_FRAME_BYTES {
            return Err(io::Error::new(io::ErrorKind::InvalidData, "JSONL frame too large"));
        }
        frame.extend_from_slice(&available[..take]);
        reader.consume(take);
        if frame.last() == Some(&b'\n') {
            return Ok(Some(frame));
        }
    }
}

impl CodexClient {
    pub fn connect() -> Result<Self> {
        let mut cmd = Command::new("codex");
        cmd.arg("app-server");
        Self::connect_command(cmd, REQUEST_TIMEOUT)
    }

    fn connect_command(mut command: Command, timeout: Duration) -> Result<Self> {
        let mut child = command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null()) // Do not copy Codex diagnostics or credentials to output.
            .spawn()?;
        let stdin = child
            .stdin
            .take()
            .ok_or(CodexError::Protocol("missing child stdin"))?;
        let stdout = child
            .stdout
            .take()
            .ok_or(CodexError::Protocol("missing child stdout"))?;
        let (tx, frames) = mpsc::sync_channel(16);
        let reader = thread::spawn(move || {
            let mut stream = BufReader::new(stdout);
            loop {
                match read_frame(&mut stream) {
                    Ok(Some(frame)) => {
                        if tx.send(Ok(frame)).is_err() {
                            break;
                        }
                    }
                    Ok(None) => break,
                    Err(err) => {
                        let _ = tx.send(Err(err));
                        break;
                    }
                }
            }
        });
        let mut client = Self {
            child,
            stdin: Some(stdin),
            frames,
            reader: Some(reader),
            next_id: 1,
            timeout,
            platform_os: String::new(),
            observed_events: ObservedEvents::default(),
        };
        let result = client.request(
            "initialize",
            json!({
                "clientInfo": {
                    "name": "chatgpt2codex_debian",
                    "title": "ChatGPT2Codex local read-only probe",
                    "version": env!("CARGO_PKG_VERSION")
                },
                "capabilities": { "experimentalApi": false }
            }),
        )?;
        client.platform_os = result
            .get("platformOs")
            .and_then(Value::as_str)
            .ok_or(CodexError::Protocol("initialize response missing platformOs"))?
            .to_owned();
        client.notify("initialized")?;
        Ok(client)
    }

    pub fn platform_os(&self) -> &str {
        &self.platform_os
    }

    pub fn observed_events(&self) -> ObservedEvents {
        self.observed_events
    }

    fn write(&mut self, data: &Value) -> Result<()> {
        let stdin = self
            .stdin
            .as_mut()
            .ok_or(CodexError::Protocol("subprocess stdin was closed"))?;
        serde_json::to_writer(&mut *stdin, data)
            .map_err(|_| CodexError::Protocol("cannot encode JSON-RPC request"))?;
        stdin.write_all(b"\n")?;
        stdin.flush()?;
        Ok(())
    }

    fn notify(&mut self, method: &'static str) -> Result<()> {
        self.write(&json!({ "method": method }))
    }

    /// Private to this adapter. There is intentionally no user-defined method.
    fn request(&mut self, method: &'static str, params: Value) -> Result<Value> {
        let id = self.next_id;
        self.next_id = self
            .next_id
            .checked_add(1)
            .ok_or(CodexError::Protocol("JSON-RPC request counter overflow"))?;
        self.write(&json!({ "id": id, "method": method, "params": params }))?;
        self.wait_response(id)
    }

    fn wait_response(&mut self, wanted_id: u64) -> Result<Value> {
        let deadline = Instant::now() + self.timeout;
        for _ in 0..MAX_NOTIFICATIONS {
            let remaining = deadline
                .checked_duration_since(Instant::now())
                .ok_or(CodexError::Timeout)?;
            let bytes = match self.frames.recv_timeout(remaining) {
                Ok(Ok(bytes)) => bytes,
                Ok(Err(_)) => return Err(CodexError::Protocol("oversized or broken JSONL frame")),
                Err(RecvTimeoutError::Timeout) => return Err(CodexError::Timeout),
                Err(RecvTimeoutError::Disconnected) => return Err(CodexError::Closed),
            };
            let message: Value = serde_json::from_slice(&bytes).map_err(|_| CodexError::InvalidFrame)?;
            if let Some(method) = message.get("method") {
                // Never reply to approvals or any server-initiated request.
                if message.get("id").is_some() {
                    return Err(CodexError::Protocol("unexpected server-initiated request"));
                }
                let method = method.as_str().ok_or(CodexError::Protocol("invalid notification method"))?;
                // Method family only: do not keep IDs, transcripts or payloads.
                self.observed_events.record(method);
                continue;
            }
            if message.get("id").and_then(Value::as_u64) != Some(wanted_id) {
                return Err(CodexError::Protocol("unexpected JSON-RPC response id"));
            }
            if let Some(error) = message.get("error") {
                let code = error.get("code").and_then(Value::as_i64).unwrap_or(-32000);
                return Err(CodexError::Rpc(code)); // Never disclose error.data or error.message.
            }
            return message
                .get("result")
                .cloned()
                .ok_or(CodexError::Protocol("JSON-RPC response missing result"));
        }
        Err(CodexError::Protocol("too many app-server notifications"))
    }

    /// Returns at most 100 session summaries from the existing state DB.
    /// The server must return only threads whose cwd exactly matches the target.
    pub fn list_sessions(&mut self, cwd: &Path, limit: u32, cursor: Option<&str>) -> Result<SessionPage> {
        if !(1..=100).contains(&limit) {
            return Err(CodexError::Protocol("invalid session page size"));
        }
        let cwd = cwd
            .to_str()
            .ok_or(CodexError::Protocol("non-UTF-8 project path"))?;
        let result = self.request(
            "thread/list",
            json!({
                "cwd": cwd,
                "limit": limit,
                "cursor": cursor,
                "sortKey": "updated_at",
                "sortDirection": "desc",
                "sourceKinds": ["cli", "vscode", "appServer"],
                "useStateDbOnly": true
            }),
        )?;
        let items = result
            .get("data")
            .and_then(Value::as_array)
            .ok_or(CodexError::Protocol("thread/list response missing data"))?;
        if items.len() > limit as usize {
            return Err(CodexError::Protocol("thread/list exceeds requested page size"));
        }
        let mut threads = Vec::with_capacity(items.len());
        for item in items {
            threads.push(parse_summary(item, cwd)?);
        }
        let next_cursor = match result.get("nextCursor") {
            Some(Value::String(value)) => Some(value.clone()),
            Some(Value::Null) | None => None,
            _ => return Err(CodexError::Protocol("invalid pagination cursor")),
        };
        Ok(SessionPage { threads, next_cursor })
    }

    /// Read only metadata; transcript and turns are deliberately excluded.
    pub fn read_session_metadata(&mut self, cwd: &Path, id: &str) -> Result<SessionSummary> {
        if !is_session_id(id) {
            return Err(CodexError::Protocol("invalid Codex session UUID"));
        }
        let cwd = cwd
            .to_str()
            .ok_or(CodexError::Protocol("non-UTF-8 project path"))?;
        let result = self.request("thread/read", json!({ "threadId": id, "includeTurns": false }))?;
        let item = result
            .get("thread")
            .ok_or(CodexError::Protocol("thread/read response missing thread"))?;
        let summary = parse_summary(item, cwd)?;
        if summary.id != id {
            return Err(CodexError::Protocol("thread/read returned wrong thread id"));
        }
        Ok(summary)
    }
}

impl Drop for CodexClient {
    fn drop(&mut self) {
        // Closing stdin signals normal EOF; killing ensures finite cleanup even
        // if a buggy app-server ignores EOF or blocks in another operation.
        self.stdin.take();
        // Close the bounded frame channel before joining the reader. Otherwise
        // a burst of notifications could leave its sender blocked forever.
        let (_, unused_frames) = mpsc::channel();
        let active_frames = std::mem::replace(&mut self.frames, unused_frames);
        drop(active_frames);
        let _ = self.child.kill();
        let _ = self.child.wait();
        if let Some(reader) = self.reader.take() {
            let _ = reader.join();
        }
    }
}

fn is_session_id(id: &str) -> bool {
    let bytes = id.as_bytes();
    if bytes.len() != 36 {
        return false;
    }
    bytes.iter().enumerate().all(|(index, byte)| {
        if matches!(index, 8 | 13 | 18 | 23) {
            *byte == b'-'
        } else {
            byte.is_ascii_hexdigit()
        }
    })
}

fn parse_summary(item: &Value, cwd: &str) -> Result<SessionSummary> {
    let returned_cwd = item
        .get("cwd")
        .and_then(Value::as_str)
        .ok_or(CodexError::Protocol("thread lacks cwd"))?;
    if returned_cwd != cwd {
        return Err(CodexError::Protocol("thread is outside requested project"));
    }
    let id = item
        .get("id")
        .and_then(Value::as_str)
        .filter(|id| is_session_id(id))
        .ok_or(CodexError::Protocol("thread has invalid UUID"))?;
    let status = item
        .get("status")
        .and_then(|status| status.get("type"))
        .and_then(Value::as_str)
        .ok_or(CodexError::Protocol("thread lacks status"))?;
    let status = match status {
        "notLoaded" => "notLoaded",
        "idle" => "idle",
        "active" => "active",
        "systemError" => "systemError",
        _ => return Err(CodexError::Protocol("thread has unknown status")),
    };
    let created_at = item
        .get("createdAt")
        .and_then(Value::as_u64)
        .ok_or(CodexError::Protocol("thread lacks createdAt"))?;
    let updated_at = item
        .get("updatedAt")
        .and_then(Value::as_u64)
        .ok_or(CodexError::Protocol("thread lacks updatedAt"))?;
    Ok(SessionSummary {
        id: id.to_owned(),
        status,
        created_at,
        updated_at,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    fn mock_command(mode: &str) -> Command {
        let mut cmd = Command::new("python3");
        cmd.arg("-u")
            .arg(concat!(env!("CARGO_MANIFEST_DIR"), "/tests/fixtures/mock_app_server.py"))
            .arg(mode);
        cmd
    }

    #[test]
    fn jsonl_frame_is_bounded_and_handles_eof() {
        let mut reader = Cursor::new(b"{\"id\":1}\n".to_vec());
        assert_eq!(read_frame(&mut reader).unwrap().unwrap(), b"{\"id\":1}\n");
        assert!(read_frame(&mut reader).unwrap().is_none());
    }

    #[test]
    fn rejects_truncated_jsonl_frame() {
        let mut reader = Cursor::new(b"{\"id\":1}".to_vec());
        assert!(read_frame(&mut reader).is_err());
    }

    #[test]
    fn validates_uuid_shape() {
        assert!(is_session_id("123e4567-e89b-12d3-a456-426614174000"));
        assert!(!is_session_id("../../other-thread"));
        assert!(!is_session_id("123"));
    }

    #[test]
    fn handshake_list_and_read_metadata() {
        let mut client = CodexClient::connect_command(mock_command("normal"), Duration::from_secs(3)).unwrap();
        assert_eq!(client.platform_os(), "linux");
        let cwd = Path::new("/tmp/mock-project");
        let page = client.list_sessions(cwd, 2, None).unwrap();
        assert_eq!(page.threads.len(), 1);
        assert!(page.next_cursor.is_none());
        let session = client.read_session_metadata(cwd, &page.threads[0].id).unwrap();
        assert_eq!(page.threads[0], session);
    }

    #[test]
    fn diagnostic_counts_only_own_connection_event_families() {
        let mut client = CodexClient::connect_command(mock_command("events"), Duration::from_secs(3)).unwrap();
        let page = client.list_sessions(Path::new("/tmp/mock-project"), 2, None).unwrap();
        assert_eq!(page.threads.len(), 1);
        let events = client.observed_events();
        assert_eq!(events.thread, 1);
        assert_eq!(events.turn, 1);
        assert_eq!(events.item, 1);
        assert_eq!(events.other, 0);
        let session = client.read_session_metadata(Path::new("/tmp/mock-project"), &page.threads[0].id).unwrap();
        assert_eq!(session.id, page.threads[0].id);
    }

    #[test]
    fn observed_events_counts_saturate_without_storing_payloads() {
        let mut events = ObservedEvents { thread: u32::MAX, ..Default::default() };
        events.record("thread/started");
        events.record("unknown/event");
        assert_eq!(events.thread, u32::MAX);
        assert_eq!(events.other, 1);
    }

    #[test]
    fn rejects_unsolicited_server_approval_request() {
        let mut client = CodexClient::connect_command(mock_command("server-request"), Duration::from_secs(3)).unwrap();
        let err = client.list_sessions(Path::new("/tmp/mock-project"), 10, None).unwrap_err();
        assert!(matches!(err, CodexError::Protocol("unexpected server-initiated request")));
    }

    #[test]
    fn rejects_cross_project_thread() {
        let mut client = CodexClient::connect_command(mock_command("wrong-project"), Duration::from_secs(3)).unwrap();
        let err = client.list_sessions(Path::new("/tmp/mock-project"), 10, None).unwrap_err();
        assert!(matches!(err, CodexError::Protocol("thread is outside requested project")));
    }

    #[test]
    fn rejects_mismatched_response_id() {
        let err = match CodexClient::connect_command(mock_command("wrong-id"), Duration::from_secs(3)) {
            Ok(_) => panic!("mismatched id was accepted"),
            Err(err) => err,
        };
        assert!(matches!(err, CodexError::Protocol("unexpected JSON-RPC response id")));
    }

    #[test]
    fn honors_request_deadline() {
        // Starting Python (especially under QEMU) is not the request under test.
        let mut client = CodexClient::connect_command(mock_command("slow"), REQUEST_TIMEOUT).unwrap();
        client.timeout = Duration::from_millis(300);
        let started = Instant::now();
        let err = client.list_sessions(Path::new("/tmp/mock-project"), 10, None).unwrap_err();
        assert!(matches!(err, CodexError::Timeout));
        assert!(started.elapsed() >= client.timeout);
    }

    #[test]
    fn request_deadline_is_independent_of_mock_startup() {
        let mut command = mock_command("slow");
        // Deterministically reproduce startup longer than the request deadline.
        command.arg("0.6");
        let mut client = CodexClient::connect_command(command, REQUEST_TIMEOUT).unwrap();
        client.timeout = Duration::from_millis(300);
        let started = Instant::now();
        let err = client.list_sessions(Path::new("/tmp/mock-project"), 10, None).unwrap_err();
        assert!(matches!(err, CodexError::Timeout));
        assert!(started.elapsed() >= client.timeout);
    }
}
