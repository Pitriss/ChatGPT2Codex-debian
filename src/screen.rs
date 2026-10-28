//! Local-only GNU screen session manager (P0-I prototype).
//!
//! Deliberately NOT available as an MCP tool.  Start and attach are initiated
//! by an explicit local CLI command.  No arbitrary command, `screen -X stuff`,
//! detach/kill, implicit session adoption, or automatic task replay.

use crate::registry::{ProjectRegistry, validate_id};
use crate::workspace;
use serde::{Deserialize, Serialize};
use std::env;
use std::error::Error;
use std::fmt;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::os::unix::fs::{DirBuilderExt, MetadataExt, OpenOptionsExt};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::Duration;

const MAX_SCREEN_OUTPUT: usize = 64 * 1024;
const MAX_RECORD_SIZE: u64 = 16 * 1024;
const MAX_TASK_CHARS: usize = 96;
const RECORD_VERSION: u8 = 1;

#[derive(Debug)]
pub struct ScreenError(pub String);
impl fmt::Display for ScreenError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result { f.write_str(&self.0) }
}
impl Error for ScreenError {}
pub(crate) type Result<T> = std::result::Result<T, ScreenError>;
pub(crate) fn err(message: impl Into<String>) -> ScreenError { ScreenError(message.into()) }

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Target<'a> { Bridge, Project(&'a str) }
impl<'a> Target<'a> {
    pub(crate) fn id(self) -> &'a str { match self { Self::Bridge => "bridge", Self::Project(id) => id } }
    pub(crate) fn screen_name(self) -> Result<String> {
        match self {
            Self::Bridge => Ok("g2c-bridge".into()),
            Self::Project(id) => {
                validate_id(id).map_err(|_| err("invalid project ID"))?;
                if id == "bridge" { return Err(err("bridge is reserved for the manual tab")); }
                Ok(format!("g2c-{id}"))
            }
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Record {
    #[serde(default, skip_serializing_if = "is_screen")]
    pub(crate) multiplexer: crate::multiplexer::Multiplexer,
    pub(crate) version: u8,
    pub(crate) project_id: String,
    pub(crate) screen_name: String,
    pub(crate) task: String,
    pub(crate) root: PathBuf,
    pub(crate) full_id: Option<String>,
    pub(crate) pid: Option<u32>,
    pub(crate) process_start_ticks: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub(crate) tmux: Option<crate::multiplexer::TmuxIdentity>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub(crate) tmux_lifecycle: Option<crate::multiplexer::TmuxLifecycle>,
}
fn is_screen(value: &crate::multiplexer::Multiplexer) -> bool {
    *value == crate::multiplexer::Multiplexer::Screen
}

#[derive(Debug, Clone)]
struct LiveSession { full_id: String, pid: u32, name: String, state: &'static str }

pub struct Status {
    pub project_id: String,
    pub screen_name: String,
    pub full_id: Option<String>,
    pub task: Option<String>,
    pub state: &'static str,
    pub process_start_ticks: Option<u64>,
}

/// A stale screen record that was safely archived, not a new Codex session.
pub struct Recovery {
    pub project_id: String,
    pub old_session_id: String,
    pub archive_path: PathBuf,
}

fn probe_silent() -> Result<()> {
    let output = bounded_screen_output(&["-v"])?;
    if !output.starts_with("Screen version") && !output.starts_with("GNU Screen") {
        return Err(err("unexpected GNU screen version response"));
    }
    Ok(())
}

pub fn probe() -> Result<()> {
    let output = bounded_screen_output(&["-v"])?;
    let line = output.lines().next().unwrap_or("GNU screen");
    if !line.starts_with("Screen version") && !line.starts_with("GNU Screen") {
        return Err(err("unexpected GNU screen version response"));
    }
    println!("screen=available version={}", line.chars().take(100).collect::<String>());
    Ok(())
}

fn bounded_screen_output(args: &[&str]) -> Result<String> {
    // No user-controlled raw command or -X interface is allowed here.
    let mut child = Command::new("screen")
        .args(args)
        .env("LC_ALL", "C")
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|_| err("GNU screen could not be started"))?;
    let mut data = Vec::new();
    let read_result = child.stdout.take().ok_or_else(|| err("GNU screen stdout unavailable"))?
        .take((MAX_SCREEN_OUTPUT + 1) as u64).read_to_end(&mut data);
    if data.len() > MAX_SCREEN_OUTPUT || read_result.is_err() {
        let _ = child.kill();
        let _ = child.wait();
        return Err(err("invalid or oversized GNU screen response"));
    }
    child.wait().map_err(|_| err("GNU screen output unavailable"))?;
    // `screen -ls` returns nonzero when there are no sessions.  Do not
    // interpret that as a protocol error.
    String::from_utf8(data).map_err(|_| err("GNU screen output is not UTF-8"))
}

fn parse_sessions(output: &str) -> Vec<LiveSession> {
    output.lines().filter_map(|line| {
        let line = line.trim();
        let mut fields = line.split_whitespace();
        let session = fields.next()?;
        let (pid, name) = session.split_once('.')?;
        if !pid.bytes().all(|b| b.is_ascii_digit()) || pid.is_empty() || name.is_empty() {
            return None;
        }
        let pid: u32 = pid.parse().ok()?;
        if pid == 0 { return None; }
        let rest = fields.collect::<Vec<_>>().join(" ");
        let state = if rest.contains("(Detached)") { "detached" }
            else if rest.contains("(Attached)") { "attached" }
            else { "unknown" };
        Some(LiveSession { full_id: session.to_owned(), pid, name: name.to_owned(), state })
    }).collect()
}

fn current_sessions() -> Result<Vec<LiveSession>> {
    let output = bounded_screen_output(&["-ls"])?;
    if !output.contains("There is a screen on:")
        && !output.contains("There are screens on:")
        && !output.contains("No Sockets found") {
        return Err(err("GNU screen session listing was not recognized"));
    }
    Ok(parse_sessions(&output))
}

fn euid() -> u32 { unsafe { libc::geteuid() } }

pub(crate) fn state_dir(create: bool) -> Result<PathBuf> {
    let home = PathBuf::from(env::var_os("HOME").ok_or_else(|| err("HOME is unset"))?);
    let base = match env::var_os("XDG_STATE_HOME") {
        Some(value) => PathBuf::from(value),
        None => home.join(".local/state"),
    };
    if !base.is_absolute() { return Err(err("XDG_STATE_HOME must be absolute")); }
    let root = base.join("gpt2codex/screen-sessions");
    if create { fs::DirBuilder::new().recursive(true).mode(0o700).create(&root).map_err(|_| err("cannot create bridge screen state directory"))?; }
    let meta = match fs::symlink_metadata(&root) {
        Ok(meta) => meta,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Err(err("screen state directory not initialized")),
        Err(_) => return Err(err("cannot inspect screen state directory")),
    };
    // This is bridge-owned command-execution metadata, unlike user-controlled
    // .bash_history.  A writable foreign directory would permit session hijack.
    if !meta.is_dir() || meta.file_type().is_symlink() || meta.uid() != euid() || meta.mode() & 0o022 != 0 {
        return Err(err("bridge session state requires an owned, non-symlink, non-writable-by-others directory"));
    }
    Ok(root)
}

pub(crate) fn lock_dir(root: &Path) -> Result<File> {
    let f = File::open(root).map_err(|_| err("cannot open screen state directory"))?;
    let rc = unsafe { libc::flock(std::os::fd::AsRawFd::as_raw_fd(&f), libc::LOCK_EX) };
    if rc != 0 { return Err(err("cannot lock screen state directory")); }
    Ok(f)
}

fn record_path(root: &Path, target: Target<'_>) -> Result<PathBuf> {
    let _ = target.screen_name()?;
    Ok(root.join(format!("{}.json", target.id())))
}

pub(crate) fn read_record(path: &Path) -> Result<Option<Record>> {
    Ok(read_record_snapshot(path)?.map(|(record, _, _)| record))
}

pub(crate) fn read_record_snapshot(path: &Path) -> Result<Option<(Record, Vec<u8>, fs::Metadata)>> {
    let info = match fs::symlink_metadata(path) {
        Ok(value) => value,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(_) => return Err(err("cannot read screen record metadata")),
    };
    if !info.is_file() || info.file_type().is_symlink() || info.uid() != euid()
        || info.mode() & 0o022 != 0 || info.len() > MAX_RECORD_SIZE {
        return Err(err("unsafe bridge-owned screen record"));
    }
    let mut file = OpenOptions::new().read(true).custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path).map_err(|_| err("cannot open screen record safely"))?;
    let opened = file.metadata().map_err(|_| err("screen record metadata unavailable"))?;
    if opened.dev() != info.dev() || opened.ino() != info.ino() || !opened.is_file() || opened.uid() != euid() {
        return Err(err("screen record changed while opening"));
    }
    let mut buf = Vec::new();
    (&mut file).take(MAX_RECORD_SIZE + 1).read_to_end(&mut buf)
        .map_err(|_| err("cannot read screen record"))?;
    if buf.len() as u64 > MAX_RECORD_SIZE { return Err(err("screen record too large")); }
    let record: Record = serde_json::from_slice(&buf).map_err(|_| err("invalid screen record"))?;
    if record.version != RECORD_VERSION { return Err(err("unsupported screen record version")); }
    Ok(Some((record, buf, opened)))
}

pub(crate) fn write_new_record(path: &Path, record: &Record) -> Result<()> {
    let mut file = OpenOptions::new().write(true).create_new(true).mode(0o600)
        .open(path).map_err(|_| err("screen record already exists or cannot be created"))?;
    let content = serde_json::to_vec_pretty(record).map_err(|_| err("cannot encode screen record"))?;
    file.write_all(&content).and_then(|_| file.sync_all())
        .map_err(|_| err("cannot persist screen record"))?;
    Ok(())
}

pub(crate) fn update_record(path: &Path, record: &Record) -> Result<()> {
    let parent = path.parent().ok_or_else(|| err("invalid screen record path"))?;
    let temp = parent.join(format!(".{}-{}.pending", record.project_id, std::process::id()));
    let result = (|| {
        write_new_record(&temp, record)?;
        fs::rename(&temp, path).map_err(|_| err("cannot atomically update screen record"))?;
        Ok(())
    })();
    if result.is_err() { let _ = fs::remove_file(temp); }
    result
}

pub(crate) fn process_start_ticks(pid: u32) -> Option<u64> {
    let stat = fs::read_to_string(format!("/proc/{pid}/stat")).ok()?;
    // `comm` can contain spaces and right parentheses.  The 20th token
    // after the final `)` is /proc/stat field 22, the process start time.
    let fields = stat.rsplit_once(')')?.1.split_whitespace().collect::<Vec<_>>();
    fields.get(19)?.parse().ok()
}

pub(crate) fn process_matches(pid: u32, ticks: u64) -> bool {
    let meta = match fs::metadata(format!("/proc/{pid}")) { Ok(m) => m, Err(_) => return false };
    meta.uid() == euid() && process_start_ticks(pid) == Some(ticks)
}

fn validated_record(target: Target<'_>, record: Record, expected_root: &Path) -> Result<Record> {
    if !is_screen(&record.multiplexer) || record.tmux.is_some() || record.tmux_lifecycle.is_some() || record.project_id != target.id() || record.screen_name != target.screen_name()?
        || record.root != expected_root {
        return Err(err("registered screen metadata differs from current project registry"));
    }
    if let Some(full_id) = &record.full_id {
        let (prefix, name) = full_id.split_once('.').ok_or_else(|| err("invalid stored screen ID"))?;
        if prefix.parse::<u32>().ok() != record.pid || name != record.screen_name {
            return Err(err("invalid stored screen identity"));
        }
    }
    Ok(record)
}

pub(crate) fn target_root(registry: &ProjectRegistry, target: Target<'_>) -> Result<PathBuf> {
    let id = match target { Target::Bridge => "gpt2codex", Target::Project(id) => id };
    Ok(registry.project(id).map_err(|_| err("project is not registered"))?.root.clone())
}

fn inspect_with_list(record: &Record, listed: &[LiveSession]) -> Status {
    let mut result = Status {
        project_id: record.project_id.clone(),
        screen_name: record.screen_name.clone(),
        full_id: record.full_id.clone(),
        task: Some(record.task.clone()),
        process_start_ticks: record.process_start_ticks,
        state: "interrupted",
    };
    if let (Some(full), Some(pid), Some(ticks)) = (&record.full_id, record.pid, record.process_start_ticks) {
        if process_matches(pid, ticks) {
            if let Some(live) = listed.iter().find(|entry| &entry.full_id == full && entry.pid == pid && entry.name == record.screen_name) {
                result.state = live.state;
            }
        }
    } else {
        result.state = "unconfirmed";
    }
    result
}

// Unlike `process_matches`, this refuses recovery when /proc is unreadable:
// a read failure is not evidence that a PID is gone.
pub(crate) fn original_process_is_absent(pid: u32, ticks: u64) -> Result<bool> {
    match fs::metadata(format!("/proc/{pid}")) {
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(true),
        Err(_) => return Err(err("cannot verify old process existence; recovery refused")),
        Ok(meta) if meta.uid() != euid() => {
            return Err(err("old PID is present under another owner; recovery refused"));
        }
        Ok(_) => (),
    }
    match process_start_ticks(pid) {
        Some(current) => Ok(current != ticks),
        None => Err(err("old process start time unavailable; recovery refused")),
    }
}

// Only a fully recorded, absent process can be released. A live process,
// another screen using the reserved name or an incomplete record requires
// manual investigation. Never adopt by screen name alone.
fn check_recoverability(record: &Record, listed: &[LiveSession], old_process_alive: bool) -> Result<(u32, u64)> {
    let (Some(_full), Some(pid), Some(ticks)) = (&record.full_id, record.pid, record.process_start_ticks) else {
        return Err(err("unconfirmed screen record; recovery refused"));
    };
    if old_process_alive {
        return Err(err("original screen process identity still exists; recovery refused"));
    }
    if listed.iter().any(|item| item.name == record.screen_name) {
        return Err(err("GNU screen name is still occupied; recovery refused"));
    }
    if inspect_with_list(record, listed).state != "interrupted" {
        return Err(err("screen record is not interrupted; recovery refused"));
    }
    Ok((pid, ticks))
}

/// Explicit local-only recovery of an interrupted project screen slot.
/// Does not start, attach, terminate or send input to ANY screen session.
/// Preserves the original owned record as an archive in the same private directory.
pub fn recover(config: &Path, id: &str) -> Result<Recovery> {
    let target = Target::Project(id);
    let _ = target.screen_name()?; // reject reserved/unsafe project IDs
    let registry = ProjectRegistry::load(config).map_err(|_| err("cannot load project registry"))?;
    let project_root = target_root(&registry, target)?;
    probe_silent()?;
    let state_root = state_dir(false)?;
    let _lock = lock_dir(&state_root)?;
    let path = record_path(&state_root, target)?;
    let record = read_record(&path)?.ok_or_else(|| err("screen slot is not registered"))?;
    let record = validated_record(target, record, &project_root)?;
    let current = current_sessions()?;
    let (Some(pid), Some(ticks)) = (record.pid, record.process_start_ticks) else {
        return Err(err("unconfirmed screen record; recovery refused"));
    };
    let absent = original_process_is_absent(pid, ticks)?;
    check_recoverability(&record, &current, !absent)?;

    // Verify a second time immediately before archival. Bridge lock excludes
    // other bridge writes, but externally managed screen sessions are independent.
    let latest = current_sessions()?;
    check_recoverability(&record, &latest, !original_process_is_absent(pid, ticks)?)?;

    let old_session_id = record.full_id.clone().ok_or_else(|| err("screen ID missing"))?;
    // A hard link with a fresh, collision-resistant-by-identity file name
    // preserves the exact original bytes without ever overwriting a backup.
    let archive_path = state_root.join(format!(".recovered-{}-{}-{}.json", id, pid, ticks));
    fs::hard_link(&path, &archive_path)
        .map_err(|_| err("cannot archive old screen record without overwriting existing evidence"))?;
    if fs::remove_file(&path).is_err() {
        let _ = fs::remove_file(&archive_path);
        return Err(err("old screen slot could not be freed; no new session authorized"));
    }
    File::open(&state_root).and_then(|dir| dir.sync_all())
        .map_err(|_| err("recovered slot archived but state directory sync failed; inspect status"))?;
    Ok(Recovery { project_id: id.to_owned(), old_session_id, archive_path })
}

pub fn status(config: &Path, target: Target<'_>) -> Result<Status> {
    let registry = ProjectRegistry::load(config).map_err(|_| err("cannot load project registry"))?;
    let root = target_root(&registry, target)?;
    let name = target.screen_name()?;
    let state = match state_dir(false) {
        Ok(path) => path,
        Err(e) if e.0 == "screen state directory not initialized" => return Ok(Status { project_id: target.id().into(), screen_name: name, full_id: None, task: None, state: "not_registered", process_start_ticks: None }),
        Err(e) => return Err(e),
    };
    let record = read_record(&record_path(&state, target)?)?;
    let listed = current_sessions()?;
    match record {
        None => Ok(Status { project_id: target.id().into(), screen_name: name, full_id: None, task: None, state: "not_registered", process_start_ticks: None }),
        Some(record) => Ok(inspect_with_list(&validated_record(target, record, &root)?, &listed)),
    }
}

pub(crate) fn executable(path: &Path) -> bool {
    fs::metadata(path).map(|m| m.is_file() && m.mode() & 0o111 != 0).unwrap_or(false)
}

fn codex_available() -> bool {
    env::var_os("PATH").map(|path| {
        env::split_paths(&path).any(|dir| executable(&dir.join("codex")))
    }).unwrap_or(false)
}

pub(crate) fn validate_task(value: &str) -> Result<()> {
    if value.is_empty() || value.trim() != value || value.chars().count() > MAX_TASK_CHARS
        || value.chars().any(|ch| ch.is_control()) {
        return Err(err("task name must be 1..96 printable characters without leading/trailing whitespace"));
    }
    Ok(())
}

pub fn start(config: &Path, target: Target<'_>, task: &str) -> Result<Status> {
    validate_task(task)?;
    let registry = ProjectRegistry::load(config).map_err(|_| err("cannot load project registry"))?;
    let project_id = match target { Target::Bridge => "gpt2codex", Target::Project(id) => id };
    let root = target_root(&registry, target)?;
    let health = workspace::health(config, project_id).map_err(|_| err("project workspace health failed"))?;
    if !health.ready() { return Err(err("project workspace is not ready")); }
    let screen_name = target.screen_name()?;
    // Reject unsupported client setup without creating a reserved state record.
    let shell = if matches!(target, Target::Bridge) {
        let candidate = env::var("SHELL").unwrap_or_else(|_| "/bin/bash".into());
        if !Path::new(&candidate).is_absolute() || !executable(Path::new(&candidate)) {
            return Err(err("SHELL must be an absolute executable path"));
        }
        Some(candidate)
    } else {
        if !codex_available() { return Err(err("codex executable was not found in PATH")); }
        None
    };
    probe_silent()?;
    let state_root = state_dir(true)?;
    let _lock = lock_dir(&state_root)?;
    let record_file = record_path(&state_root, target)?;
    if read_record(&record_file)?.is_some() {
        return Err(err("screen slot already registered; no automatic restart or takeover"));
    }
    // A matching user-managed name is NOT proof of bridge ownership.
    if current_sessions()?.iter().any(|session| session.name == screen_name) {
        return Err(err("an existing GNU screen session uses the reserved name"));
    }
    let mut record = Record {
        multiplexer: crate::multiplexer::Multiplexer::Screen, tmux: None, tmux_lifecycle: None,
        version: RECORD_VERSION,
        project_id: target.id().into(),
        screen_name: screen_name.clone(),
        task: task.into(),
        root: root.clone(),
        full_id: None,
        pid: None,
        process_start_ticks: None,
    };
    write_new_record(&record_file, &record)?;
    let mut command = Command::new("screen");
    command.arg("-dmS").arg(&screen_name).arg("-t").arg(&screen_name)
        .current_dir(&root)
        .stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
    match target {
        Target::Bridge => {
            command.arg(shell.as_deref().expect("validated shell")).arg("-l");
        }
        Target::Project(_) => { command.arg("codex"); }
    }
    let rc = command.status().map_err(|_| err("GNU screen launch failed; inspect pending session record"))?;
    if !rc.success() { return Err(err("GNU screen exited with error; inspect pending session record")); }
    let mut detected = None;
    for _ in 0..8 {
        thread::sleep(Duration::from_millis(125));
        let matches = current_sessions()?.into_iter()
            .filter(|candidate| candidate.name == screen_name).collect::<Vec<_>>();
        if matches.len() == 1 {
            let found = &matches[0];
            if let Some(ticks) = process_start_ticks(found.pid) {
                if process_matches(found.pid, ticks) {
                    detected = Some((found.clone(), ticks));
                    break;
                }
            }
        } else if matches.len() > 1 {
            return Err(err("ambiguous screen session collision; manual reconciliation required"));
        }
    }
    let (session, ticks) = detected.ok_or_else(|| err("GNU screen session not confirmed; no automatic replay"))?;
    record.full_id = Some(session.full_id);
    record.pid = Some(session.pid);
    record.process_start_ticks = Some(ticks);
    update_record(&record_file, &record)?;
    Ok(inspect_with_list(&record, &current_sessions()?))
}

pub fn attach(config: &Path, target: Target<'_>) -> Result<()> {
    attach_checked(config, target, None, None)
}

pub(crate) fn attach_checked(config: &Path, target: Target<'_>, expected: Option<&str>, expected_ticks: Option<u64>) -> Result<()> {
    let view = status(config, target)?;
    if !matches!(view.state, "attached" | "detached") {
        return Err(err("managed screen session is not running; refusing to attach by guessed name"));
    }
    let full = view.full_id.ok_or_else(|| err("missing managed screen session ID"))?;
    if expected.is_some_and(|id| id != full) { return Err(err("screen identity changed before attach")); }
    if expected_ticks.is_some() && expected_ticks != view.process_start_ticks { return Err(err("screen process generation changed before attach")); }
    let flag = if view.state == "attached" { "-x" } else { "-r" };
    let rc = Command::new("screen").arg(flag).arg(&full).status()
        .map_err(|_| err("cannot attach to GNU screen session"))?;
    if !rc.success() { return Err(err("GNU screen attach failed")); }
    Ok(())
}

pub fn list(config: &Path) -> Result<Vec<Status>> {
    list_impl(config, false)
}

// The combined GUI can still inspect tmux when GNU screen is unavailable.
// Only discovery failure is tolerated; record/registry validation stays strict.
pub(crate) fn list_for_multiplexers(config: &Path) -> Result<Vec<Status>> {
    list_impl(config, true)
}

fn list_impl(config: &Path, tolerate_discovery_failure: bool) -> Result<Vec<Status>> {
    let registry = ProjectRegistry::load(config).map_err(|_| err("cannot load project registry"))?;
    let state = match state_dir(false) {
        Ok(path) => Some(path),
        Err(e) if e.0 == "screen state directory not initialized" => None,
        Err(e) => return Err(e),
    };
    let sessions = match current_sessions() {
        Ok(sessions) => Some(sessions),
        Err(_) if tolerate_discovery_failure => None,
        Err(error) => return Err(error),
    };
    let mut result = Vec::new();
    let mut targets = vec![Target::Bridge];
    targets.extend(registry.projects().filter(|p| p.id != "bridge").map(|p| Target::Project(&p.id)));
    for target in targets {
        let root = target_root(&registry, target)?;
        let name = target.screen_name()?;
        let record = match &state {
            Some(state) => read_record(&record_path(state, target)?)?,
            None => None,
        };
        result.push(match record {
            Some(record) => {
                let record = validated_record(target, record, &root)?;
                let mut info = inspect_with_list(&record, sessions.as_deref().unwrap_or(&[]));
                if sessions.is_none() && record.pid.zip(record.process_start_ticks)
                    .is_some_and(|(pid, ticks)| process_matches(pid, ticks)) { info.state = "unconfirmed"; }
                info
            },
            None => Status { project_id: target.id().into(), screen_name: name, full_id: None, task: None, state: "not_registered", process_start_ticks: None },
        });
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn screen_names_are_derived_only_from_valid_registered_ids() {
        assert_eq!(Target::Bridge.screen_name().unwrap(), "g2c-bridge");
        assert_eq!(Target::Project("k2-smb").screen_name().unwrap(), "g2c-k2-smb");
        assert!(Target::Project("bridge").screen_name().is_err());
        assert!(Target::Project("../evil").screen_name().is_err());
        assert!(Target::Project("UPPERCASE").screen_name().is_err());
        assert!(validate_task("CIFS timeout").is_ok());
        assert!(validate_task("bad\ncommand").is_err());
    }

    #[test]
    fn screen_list_parser_ignores_foreign_or_malformed_lines() {
        let content = "There are screens on:\n\t123.g2c-k2-smb (Detached)\n\t245.my-own (Attached)\n\t1234.g2c-reddit2tg (Attached)\n2 Sockets in /run/screen/S-test.\n";
        let result = parse_sessions(content);
        assert_eq!(result.len(), 3);
        assert_eq!(result[0].full_id, "123.g2c-k2-smb");
        assert_eq!(result[0].state, "detached");
        assert_eq!(result[1].name, "my-own");
        assert_eq!(result[2].state, "attached");
    }

    #[test]
    fn stale_screen_recovery_requires_full_identity_and_absent_session() {
        let mut record = Record {
            multiplexer: crate::multiplexer::Multiplexer::Screen, tmux: None, tmux_lifecycle: None, version: 1, project_id: "k2-smb".into(), screen_name: "g2c-k2-smb".into(),
            task: "Old test".into(), root: PathBuf::from("/tmp/project"),
            full_id: Some("1995497.g2c-k2-smb".into()), pid: Some(1995497),
            process_start_ticks: Some(1234),
        };
        assert!(check_recoverability(&record, &[], false).is_ok());
        assert!(check_recoverability(&record, &[], true).is_err());
        let other = vec![LiveSession {
            full_id: "44.g2c-k2-smb".into(), pid: 44,
            name: "g2c-k2-smb".into(), state: "detached",
        }];
        assert!(check_recoverability(&record, &other, false).is_err());
        record.full_id = None;
        record.pid = None;
        record.process_start_ticks = None;
        assert!(check_recoverability(&record, &[], false).is_err());
    }

    #[test]
    fn registered_record_must_match_current_registry_identity() {
        let mut record = Record {multiplexer: crate::multiplexer::Multiplexer::Screen, tmux: None, tmux_lifecycle: None, version: 1, project_id: "k2-smb".into(), screen_name: "g2c-k2-smb".into(), task: "Diagnostics".into(), root: PathBuf::from("/tmp/project"), full_id: Some("123.g2c-k2-smb".into()), pid: Some(123), process_start_ticks: Some(100)};
        assert!(validated_record(Target::Project("k2-smb"), record.clone(), Path::new("/tmp/project")).is_ok());
        record.screen_name = "g2c-other".into();
        assert!(validated_record(Target::Project("k2-smb"), record, Path::new("/tmp/project")).is_err());
    }

    #[test]
    fn session_identity_does_not_follow_just_matching_name() {
        let record = Record {multiplexer: crate::multiplexer::Multiplexer::Screen, tmux: None, tmux_lifecycle: None, version: 1, project_id: "k2-smb".into(), screen_name: "g2c-k2-smb".into(), task: "Diagnostics".into(), root: PathBuf::from("/tmp/example"), full_id: Some("9876.g2c-k2-smb".into()), pid: Some(9876), process_start_ticks: Some(1)};
        let other = vec![LiveSession {full_id: "4321.g2c-k2-smb".into(), pid: 4321, name: "g2c-k2-smb".into(), state: "detached"}];
        assert_eq!(inspect_with_list(&record, &other).state, "interrupted");
    }
}
