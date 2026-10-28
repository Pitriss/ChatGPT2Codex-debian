//! Local session facade. Legacy screen slots and safety checks stay intact.
//! Slot identity is (multiplexer, project); preference never selects an attachment.
use crate::multiplexer::{Multiplexer, TmuxIdentity, TmuxLifecycle};
use crate::registry::ProjectRegistry;
use crate::screen::{self, err, Record, Result, Status, Target};
use crate::workspace;
use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::os::fd::AsRawFd;
use std::os::unix::fs::{DirBuilderExt, FileTypeExt, MetadataExt, OpenOptionsExt};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

pub struct ManagedStatus {
    pub multiplexer: Multiplexer,
    pub status: Status,
    pub program: ProgramStatus,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ProgramStatus {
    pub state: &'static str,
    pub exit_code: Option<u32>,
    pub signal: Option<String>,
    pub exited_at: Option<u64>,
}
impl ProgramStatus {
    pub fn unknown() -> Self {
        Self {
            state: "unknown",
            ..Self::default()
        }
    }
}

fn command(socket: &Path) -> Command {
    let mut command = Command::new("tmux");
    command
        .args(["-f", "/dev/null", "-S"])
        .arg(socket)
        .env_remove("TMUX")
        .env_remove("TMUX_PANE");
    command
}

fn output(command: &mut Command) -> Result<String> {
    let mut child = command
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|_| err("tmux unavailable; no fallback or session start"))?;
    let result = (|| {
        let mut stdout = child
            .stdout
            .take()
            .ok_or_else(|| err("tmux stdout missing"))?;
        if unsafe { libc::fcntl(stdout.as_raw_fd(), libc::F_SETFL, libc::O_NONBLOCK) } == -1 {
            return Err(err("cannot bound tmux query"));
        }
        let deadline = Instant::now() + Duration::from_secs(3);
        let mut bytes = Vec::new();
        let mut chunk = [0u8; 4096];
        let mut eof = false;
        loop {
            match stdout.read(&mut chunk) {
                Ok(0) => eof = true,
                Ok(n) => bytes.extend_from_slice(&chunk[..n]),
                Err(e)
                    if matches!(
                        e.kind(),
                        std::io::ErrorKind::WouldBlock | std::io::ErrorKind::Interrupted
                    ) => {}
                Err(_) => return Err(err("cannot read tmux response")),
            }
            if bytes.len() > 65536 {
                return Err(err("oversized tmux response"));
            }
            if eof {
                if let Some(status) = child.try_wait().map_err(|_| err("cannot wait for tmux"))? {
                    if !status.success() {
                        return Err(err("tmux query failed; identity is unconfirmed"));
                    }
                    return String::from_utf8(bytes)
                        .map_err(|_| err("invalid tmux response encoding"));
                }
            }
            if Instant::now() >= deadline {
                return Err(err("tmux query timeout; no automatic retry"));
            }
            std::thread::sleep(Duration::from_millis(5));
        }
    })();
    if result.is_err() {
        let _ = child.kill();
        let _ = child.wait();
    } // Only our query client.
    result
}

pub fn available(mux: Multiplexer) -> bool {
    match mux {
        Multiplexer::Screen => Command::new("screen")
            .arg("-v")
            .output()
            .map(|o| {
                o.status.success()
                    && (o.stdout.starts_with(b"Screen version")
                        || o.stdout.starts_with(b"GNU Screen"))
            })
            .unwrap_or(false),
        Multiplexer::Tmux => output(Command::new("tmux").arg("-V"))
            .map(|s| s.starts_with("tmux "))
            .unwrap_or(false),
    }
}

pub(crate) fn record_path(root: &Path, target: Target<'_>) -> Result<PathBuf> {
    target.screen_name()?;
    Ok(root.join(format!("{}.tmux.json", target.id())))
}

pub(crate) fn socket_path(root: &Path, target: Target<'_>, create: bool) -> Result<PathBuf> {
    target.screen_name()?;
    let dir = root.join("tmux-sockets");
    if create && !dir.exists() {
        fs::DirBuilder::new()
            .mode(0o700)
            .create(&dir)
            .map_err(|_| err("cannot create tmux socket directory"))?;
    }
    let meta = fs::symlink_metadata(&dir).map_err(|_| err("tmux socket directory missing"))?;
    if !meta.is_dir()
        || meta.file_type().is_symlink()
        || meta.uid() != unsafe { libc::geteuid() }
        || meta.mode() & 0o077 != 0
    {
        return Err(err("tmux socket directory must be private and owned"));
    }
    let socket = dir.join(format!("{}.sock", target.id()));
    if socket.as_os_str().len() >= 104 {
        return Err(err("private tmux socket path too long"));
    }
    Ok(socket)
}

pub(crate) fn socket_identity(socket: &Path) -> Result<(u64, u64)> {
    let meta = fs::symlink_metadata(socket).map_err(|_| err("tmux socket unavailable"))?;
    if !meta.file_type().is_socket()
        || meta.uid() != unsafe { libc::geteuid() }
        || meta.mode() & 0o077 != 0
    {
        return Err(err(
            "tmux socket must be an owned private socket, never a symlink",
        ));
    }
    Ok((meta.dev(), meta.ino()))
}

// tmux sanitizes literal tabs to '_' for non-UTF8 clients (LC_ALL=C).
// All identity fields exclude '|', so use a printable ASCII separator.
const FORMAT: &str = "#{pid}|#{session_id}|#{session_created}|#{session_name}|#{session_attached}";
fn parse_identity(value: &str, name: &str, socket: (u64, u64)) -> Result<(TmuxIdentity, bool)> {
    let lines: Vec<_> = value.lines().collect();
    if lines.len() != 1 {
        return Err(err("ambiguous tmux server; refusing adoption"));
    }
    let fields: Vec<_> = lines[0].split('|').collect();
    if fields.len() != 5 {
        return Err(err("invalid tmux identity field count"));
    }
    if fields[3] != name {
        return Err(err("tmux session name differs from registered slot"));
    }
    if !fields[1].starts_with('$')
        || fields[1][1..].is_empty()
        || !fields[1][1..].bytes().all(|b| b.is_ascii_digit())
    {
        return Err(err("invalid tmux session identity"));
    }
    let server_pid = fields[0]
        .parse::<u32>()
        .map_err(|_| err("invalid tmux PID"))?;
    let created = fields[2]
        .parse::<u64>()
        .map_err(|_| err("invalid tmux creation time"))?;
    let attached = fields[4]
        .parse::<u32>()
        .map_err(|_| err("invalid tmux client count"))?
        > 0;
    if server_pid == 0 || created == 0 {
        return Err(err("incomplete tmux identity"));
    }
    Ok((
        TmuxIdentity {
            server_pid,
            session_id: fields[1].into(),
            created,
            socket_dev: socket.0,
            socket_ino: socket.1,
        },
        attached,
    ))
}

fn query(socket: &Path, name: &str) -> Result<(TmuxIdentity, bool)> {
    let identity = socket_identity(socket)?;
    let raw =
        output(
            command(socket)
                .env("LC_ALL", "C")
                .args(["-N", "list-sessions", "-F", FORMAT]),
        )?;
    let result = parse_identity(&raw, name, identity)?;
    if socket_identity(socket)? != identity {
        return Err(err("tmux socket changed during verification"));
    }
    Ok(result)
}

fn full_id(identity: &TmuxIdentity) -> String {
    format!(
        "{}.{}.{}",
        identity.server_pid, identity.session_id, identity.created
    )
}

pub(crate) fn validated(record: Record, target: Target<'_>, root: &Path) -> Result<Record> {
    if record.multiplexer != Multiplexer::Tmux
        || record.project_id != target.id()
        || record.screen_name != target.screen_name()?
        || record.root != root
    {
        return Err(err("tmux record differs from project registry"));
    }
    if let Some(identity) = &record.tmux {
        if identity.server_pid == 0
            || identity.created == 0
            || identity.socket_ino == 0
            || !identity.session_id.starts_with('$')
            || identity.session_id.len() < 2
            || identity.session_id.len() > 22
            || !identity.session_id[1..].bytes().all(|b| b.is_ascii_digit())
        {
            return Err(err("invalid stored tmux identity"));
        }
        if record.pid != Some(identity.server_pid)
            || record.full_id.as_deref() != Some(full_id(identity).as_str())
        {
            return Err(err("tmux record contains inconsistent identity"));
        }
    } else if record.full_id.is_some()
        || record.pid.is_some()
        || record.process_start_ticks.is_some()
    {
        return Err(err("tmux record has incomplete multiplexer identity"));
    }
    if let Some(lifecycle) = &record.tmux_lifecycle {
        if !valid_pane_id(&lifecycle.pane_id)
            || lifecycle.pid_namespace == 0
            || lifecycle.boot_id.len() != 36
            || !lifecycle.boot_id.bytes().enumerate().all(|(i, b)| {
                if [8, 13, 18, 23].contains(&i) {
                    b == b'-'
                } else {
                    b.is_ascii_hexdigit()
                }
            })
        {
            return Err(err("invalid tmux lifecycle identity"));
        }
    }
    Ok(record)
}

fn empty(target: Target<'_>) -> Result<Status> {
    Ok(Status {
        project_id: target.id().into(),
        screen_name: target.screen_name()?,
        full_id: None,
        task: None,
        state: "not_registered",
        process_start_ticks: None,
    })
}

pub fn status(config: &Path, mux: Multiplexer, target: Target<'_>) -> Result<Status> {
    if mux == Multiplexer::Screen {
        return screen::status(config, target);
    }
    let registry =
        ProjectRegistry::load(config).map_err(|_| err("cannot load project registry"))?;
    let root = screen::target_root(&registry, target)?;
    let state = match screen::state_dir(false) {
        Ok(root) => root,
        Err(e) if e.0 == "screen state directory not initialized" => return empty(target),
        Err(e) => return Err(e),
    };
    let record = match screen::read_record(&record_path(&state, target)?)? {
        Some(record) => validated(record, target, &root)?,
        None => return empty(target),
    };
    let mut result = Status {
        project_id: record.project_id.clone(),
        screen_name: record.screen_name.clone(),
        full_id: record.full_id.clone(),
        task: Some(record.task.clone()),
        state: "unconfirmed",
        process_start_ticks: record.process_start_ticks,
    };
    if let (Some(identity), Some(ticks)) = (&record.tmux, record.process_start_ticks) {
        if !screen::process_matches(identity.server_pid, ticks) {
            result.state = "interrupted";
            return Ok(result);
        }
        if let Ok(socket) = socket_path(&state, target, false) {
            if let Ok((current, attached)) = query(&socket, &record.screen_name) {
                if &current == identity {
                    result.state = if attached { "attached" } else { "detached" };
                }
            }
        }
    }
    Ok(result)
}

pub fn list(config: &Path) -> Result<Vec<ManagedStatus>> {
    let registry =
        ProjectRegistry::load(config).map_err(|_| err("cannot load project registry"))?;
    let mut result: Vec<_> = screen::list_for_multiplexers(config)?
        .into_iter()
        .map(|status| ManagedStatus {
            multiplexer: Multiplexer::Screen,
            status,
            program: ProgramStatus::unknown(),
        })
        .collect();
    let mut targets = vec![Target::Bridge];
    targets.extend(
        registry
            .projects()
            .filter(|p| p.id != "bridge")
            .map(|p| Target::Project(&p.id)),
    );
    for target in targets {
        // Do not query a missing tmux executable for an unregistered slot.
        result.push(details(config, Multiplexer::Tmux, target)?);
    }
    Ok(result)
}

pub fn start(config: &Path, mux: Multiplexer, target: Target<'_>, task: &str) -> Result<Status> {
    start_with_options(config, mux, target, task, false)
}

pub fn start_with_options(
    config: &Path,
    mux: Multiplexer,
    target: Target<'_>,
    task: &str,
    remain_on_exit: bool,
) -> Result<Status> {
    if mux == Multiplexer::Screen {
        if remain_on_exit {
            return Err(err("remain-on-exit is a tmux-only start option"));
        }
        return screen::start(config, target, task);
    }
    screen::validate_task(task)?;
    let registry =
        ProjectRegistry::load(config).map_err(|_| err("cannot load project registry"))?;
    let root = screen::target_root(&registry, target)?;
    let project_id = if target == Target::Bridge {
        "gpt2codex"
    } else {
        target.id()
    };
    if !workspace::health(config, project_id)
        .map_err(|_| err("workspace health failed"))?
        .ready()
    {
        return Err(err("workspace is not ready"));
    }
    if !available(mux) {
        return Err(err("tmux unavailable; no fallback"));
    }
    let program = if target == Target::Bridge {
        let shell = std::env::var("SHELL").unwrap_or_else(|_| "/bin/bash".into());
        if !Path::new(&shell).is_absolute() || !screen::executable(Path::new(&shell)) {
            return Err(err("SHELL must be an absolute executable"));
        }
        PathBuf::from(shell)
    } else {
        std::env::split_paths(&std::env::var_os("PATH").unwrap_or_default())
            .map(|p| p.join("codex"))
            .find(|p| screen::executable(p))
            .ok_or_else(|| err("codex executable unavailable"))?
    }
    .canonicalize()
    .map_err(|_| err("cannot resolve executable"))?;
    let state = screen::state_dir(true)?;
    let _lock = screen::lock_dir(&state)?;
    let path = record_path(&state, target)?;
    if screen::read_record(&path)?.is_some() {
        return Err(err("tmux slot already registered; no restart or overwrite"));
    }
    let socket = socket_path(&state, target, true)?;
    if fs::symlink_metadata(&socket).is_ok() {
        return Err(err("tmux socket already occupied; no adoption or takeover"));
    }
    let mut record = Record {
        multiplexer: mux,
        version: 1,
        project_id: target.id().into(),
        screen_name: target.screen_name()?,
        task: task.into(),
        root: root.clone(),
        full_id: None,
        pid: None,
        process_start_ticks: None,
        tmux: None,
        tmux_lifecycle: None,
    };
    screen::write_new_record(&path, &record)?;
    // Multiple argv entries force tmux's direct exec form, including when the
    // executable path contains spaces/metacharacters. No shell command string.
    let start_config = StartConfig::new(&state, target, remain_on_exit)?;
    let mut launch = command(&socket);
    // The dedicated config is parsed before the initial program executes.
    launch.arg("-f").arg(&start_config.path);
    launch
        .args(["new-session", "-d", "-s"])
        .arg(&record.screen_name)
        .arg("-c")
        .arg(&root)
        .arg("--")
        .arg("/usr/bin/env")
        .arg("--")
        .arg(&program);
    if target == Target::Bridge {
        launch.arg("-l");
    }
    output(&mut launch)?;
    let (identity, _) = query(&socket, &record.screen_name)?;
    let ticks = screen::process_start_ticks(identity.server_pid)
        .ok_or_else(|| err("tmux process identity unavailable"))?;
    if !screen::process_matches(identity.server_pid, ticks) {
        return Err(err("tmux process owner mismatch"));
    }
    record.pid = Some(identity.server_pid);
    record.process_start_ticks = Some(ticks);
    record.full_id = Some(full_id(&identity));
    let raw_panes = pane_output(&socket, &identity.session_id)?;
    let pane = raw_panes.lines().collect::<Vec<_>>();
    if pane.len() != 1 {
        return Err(err("initial tmux pane is ambiguous; no adoption"));
    }
    let pane_id = pane[0]
        .split('|')
        .nth(1)
        .ok_or_else(|| err("initial pane identity missing"))?;
    parse_program(&raw_panes, &identity.session_id, pane_id)?;
    let (boot_id, pid_namespace) = host_scope()?;
    record.tmux_lifecycle = Some(TmuxLifecycle {
        pane_id: pane_id.into(),
        remain_on_exit,
        boot_id,
        pid_namespace,
    });
    record.tmux = Some(identity);
    screen::update_record(&path, &record)?;
    status(config, mux, target)
}

pub fn attach(
    config: &Path,
    mux: Multiplexer,
    target: Target<'_>,
    expected: Option<&str>,
    expected_ticks: Option<u64>,
) -> Result<()> {
    if mux == Multiplexer::Screen {
        return screen::attach_checked(config, target, expected, expected_ticks);
    }
    let view = status(config, mux, target)?;
    if !matches!(view.state, "attached" | "detached") {
        return Err(err("tmux identity unconfirmed; attach refused"));
    }
    if expected.is_some_and(|id| Some(id) != view.full_id.as_deref()) {
        return Err(err("tmux identity changed before attach"));
    }
    if expected_ticks.is_some() && expected_ticks != view.process_start_ticks {
        return Err(err("tmux process generation changed before attach"));
    }
    let state = screen::state_dir(false)?;
    let socket = socket_path(&state, target, false)?;
    let record = screen::read_record(&record_path(&state, target)?)?
        .ok_or_else(|| err("tmux record missing"))?;
    let identity = record.tmux.ok_or_else(|| err("tmux identity missing"))?;
    // Recheck immediately before connecting. Never detach other clients (-d).
    let (current, _) = query(&socket, &view.screen_name)?;
    if current != identity
        || view.full_id.as_deref() != Some(full_id(&current).as_str())
        || !screen::process_matches(current.server_pid, record.process_start_ticks.unwrap_or(0))
    {
        return Err(err("tmux identity changed before attach"));
    }
    let rc = command(&socket)
        .args(["-N", "attach-session", "-t"])
        .arg(&identity.session_id)
        .status()
        .map_err(|_| err("cannot attach tmux"))?;
    if !rc.success() {
        return Err(err("tmux attach failed"));
    }
    Ok(())
}

pub fn preferred(config: &Path, target: Target<'_>) -> Result<Multiplexer> {
    let registry =
        ProjectRegistry::load(config).map_err(|_| err("cannot load project registry"))?;
    let id = if target == Target::Bridge {
        "gpt2codex"
    } else {
        target.id()
    };
    Ok(registry
        .project(id)
        .map_err(|_| err("project missing"))?
        .multiplexer)
}

pub(crate) fn host_scope() -> Result<(String, u64)> {
    let boot = fs::read_to_string("/proc/sys/kernel/random/boot_id")
        .map_err(|_| err("boot identity unavailable"))?;
    let namespace = fs::metadata("/proc/self/ns/pid")
        .map_err(|_| err("PID namespace unavailable"))?
        .ino();
    Ok((boot.trim().into(), namespace))
}

struct StartConfig {
    path: PathBuf,
    dev: u64,
    ino: u64,
}
impl StartConfig {
    fn new(state: &Path, target: Target<'_>, remain: bool) -> Result<Self> {
        let path = state.join(format!(
            ".tmux-start-{}-{}.conf",
            target.id(),
            std::process::id()
        ));
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(&path)
            .map_err(|_| err("cannot create private tmux start config"))?;
        let meta = file
            .metadata()
            .map_err(|_| err("start config metadata unavailable"))?;
        let owned = Self {
            path,
            dev: meta.dev(),
            ino: meta.ino(),
        };
        let text = format!("set-option -g exit-unattached off\nset-option -g destroy-unattached off\nset-window-option -g remain-on-exit {}\n", if remain { "on" } else { "off" });
        file.write_all(text.as_bytes())
            .and_then(|_| file.sync_all())
            .map_err(|_| err("cannot write tmux start config"))?;
        Ok(owned)
    }
}
impl Drop for StartConfig {
    fn drop(&mut self) {
        if fs::symlink_metadata(&self.path)
            .is_ok_and(|m| m.is_file() && m.dev() == self.dev && m.ino() == self.ino)
        {
            let _ = fs::remove_file(&self.path);
        }
    }
}

fn valid_pane_id(id: &str) -> bool {
    id.starts_with('%')
        && id.len() > 1
        && id.len() < 22
        && id[1..].bytes().all(|b| b.is_ascii_digit())
}
const PANE_FORMAT: &str = "#{session_id}|#{pane_id}|#{pane_pid}|#{pane_dead}|#{pane_dead_status}|#{pane_dead_signal}|#{pane_dead_time}";
fn pane_output(socket: &Path, session: &str) -> Result<String> {
    output(command(socket).env("LC_ALL", "C").args([
        "-N",
        "list-panes",
        "-s",
        "-t",
        session,
        "-F",
        PANE_FORMAT,
    ]))
}

fn parse_program(raw: &str, session: &str, pane: &str) -> Result<ProgramStatus> {
    if !valid_pane_id(pane) {
        return Err(err("invalid pane identity"));
    }
    let mut found = None;
    for line in raw.lines() {
        let f: Vec<_> = line.split('|').collect();
        if f.len() != 7 || f[0] != session || !valid_pane_id(f[1]) || f[2].parse::<u32>().is_err() {
            return Err(err("unconfirmed pane response"));
        }
        if f[1] != pane {
            continue;
        }
        if found.is_some() {
            return Err(err("ambiguous pane response"));
        }
        let state = match f[3] {
            "0" => "running",
            "1" => "exited",
            _ => return Err(err("invalid pane state")),
        };
        let exit_code = if f[4].is_empty() {
            None
        } else {
            Some(
                f[4].parse::<u32>()
                    .ok()
                    .filter(|n| *n <= 255)
                    .ok_or_else(|| err("invalid exit code"))?,
            )
        };
        let signal = if f[5].is_empty() {
            None
        } else {
            if f[5].len() > 16
                || !f[5]
                    .bytes()
                    .all(|b| b.is_ascii_uppercase() || b.is_ascii_digit())
            {
                return Err(err("invalid exit signal"));
            }
            Some(f[5].into())
        };
        let exited_at = if f[6].is_empty() {
            None
        } else {
            Some(f[6].parse().map_err(|_| err("invalid exit time"))?)
        };
        if state == "running" && (exit_code.is_some() || signal.is_some() || exited_at.is_some()) {
            return Err(err("inconsistent running pane"));
        }
        found = Some(ProgramStatus {
            state,
            exit_code,
            signal,
            exited_at,
        });
    }
    found.ok_or_else(|| err("recorded pane missing; no adoption"))
}

pub fn details(config: &Path, mux: Multiplexer, target: Target<'_>) -> Result<ManagedStatus> {
    let view = status(config, mux, target)?;
    let mut program = ProgramStatus::unknown();
    if mux == Multiplexer::Tmux && matches!(view.state, "attached" | "detached") {
        let state = screen::state_dir(false)?;
        let record = screen::read_record(&record_path(&state, target)?)?
            .ok_or_else(|| err("tmux record missing"))?;
        if record.full_id == view.full_id && record.process_start_ticks == view.process_start_ticks
        {
            if let (Some(identity), Some(lifecycle)) = (&record.tmux, &record.tmux_lifecycle) {
                let socket = socket_path(&state, target, false)?;
                if let Ok(raw) = pane_output(&socket, &identity.session_id) {
                    if query(&socket, &view.screen_name)
                        .is_ok_and(|(current, _)| &current == identity)
                    {
                        program = parse_program(&raw, &identity.session_id, &lifecycle.pane_id)
                            .unwrap_or_else(|_| ProgramStatus::unknown());
                    }
                }
            }
        }
    }
    Ok(ManagedStatus {
        multiplexer: mux,
        status: view,
        program,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn program_state_is_bound_to_original_pane() {
        assert_eq!(
            parse_program("$0|%0|123|0|||\n", "$0", "%0").unwrap().state,
            "running"
        );
        let exited = parse_program("$0|%0|123|1|23||123456\n", "$0", "%0").unwrap();
        assert_eq!(exited.state, "exited");
        assert_eq!(exited.exit_code, Some(23));
        assert_eq!(
            parse_program("$0|%0|123|1||TERM|123456\n", "$0", "%0")
                .unwrap()
                .signal
                .as_deref(),
            Some("TERM")
        );
        for bad in [
            "$1|%0|123|1|0||123456\n",
            "$0|%1|123|1|0||123456\n",
            "$0|%0|123|0|23||123456\n",
            "$0|%0|123|1|999||123456\n",
            "$0|%0|123|1||secret-command!|123456\n",
        ] {
            assert!(parse_program(bad, "$0", "%0").is_err());
        }
        assert!(parse_program("$0|%0|123|0|||\n$0|%0|123|0|||\n", "$0", "%0").is_err());
    }
    #[test]
    fn strict_tmux_identity_includes_server_session_and_socket() {
        let valid = "123|$0|123456|g2c-demo|0\n";
        let (identity, attached) = parse_identity(valid, "g2c-demo", (1, 2)).unwrap();
        assert!(!attached);
        assert_eq!(full_id(&identity), "123.$0.123456");
        assert_ne!(
            identity,
            parse_identity(valid, "g2c-demo", (1, 3)).unwrap().0
        );
        for invalid in [
            valid.repeat(2),
            valid.replace("$0", "0"),
            valid.replace("123456", "0"),
            valid.replace("123|", "0|"),
            valid.replace("g2c-demo", "foreign"),
            valid.replace("|0\n", "|-1\n"),
        ] {
            assert!(parse_identity(&invalid, "g2c-demo", (1, 2)).is_err());
        }
    }
    #[test]
    fn legacy_records_are_screen_and_never_tmux_authority() {
        let raw = r#"{"version":1,"project_id":"demo","screen_name":"g2c-demo","task":"Codex","root":"/tmp/demo","full_id":"123.g2c-demo","pid":123,"process_start_ticks":456}"#;
        let legacy: Record = serde_json::from_str(raw).unwrap();
        assert_eq!(legacy.multiplexer, Multiplexer::Screen);
        assert!(legacy.tmux.is_none());
        assert!(!serde_json::to_string(&legacy)
            .unwrap()
            .contains("multiplexer"));
        assert!(validated(legacy, Target::Project("demo"), Path::new("/tmp/demo")).is_err());
        assert_eq!(
            record_path(Path::new("/state"), Target::Project("demo")).unwrap(),
            Path::new("/state/demo.tmux.json")
        );
        assert!(record_path(Path::new("/state"), Target::Project("../demo")).is_err());
    }
}
#[test]
fn queries_have_a_deadline_and_size_limit() {
    let started = Instant::now();
    assert!(output(Command::new("/bin/sleep").arg("4")).is_err());
    assert!(started.elapsed() < Duration::from_secs(4));
    assert!(output(Command::new("/usr/bin/head").args(["-c", "70000", "/dev/zero"])).is_err());
}
