//! Explicit local archival only. Never starts, terminates or adopts a session.
use crate::registry::ProjectRegistry;
use crate::screen::{self, err, Result, Target};
use crate::session;
use serde_json::json;
use std::ffi::CString;
use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::os::fd::FromRawFd;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::{DirBuilderExt, MetadataExt, OpenOptionsExt};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

pub struct Archived {
    pub path: PathBuf,
    pub session_id: String,
}

fn stale_socket(path: &Path, expected: (u64, u64)) -> Result<bool> {
    match fs::symlink_metadata(path) {
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(false),
        Err(_) => return Err(err("cannot inspect tmux socket; archive refused")),
        Ok(_) => (),
    }
    if session::socket_identity(path)? != expected {
        return Err(err("socket identity changed; archive refused"));
    }
    let bytes = path.as_os_str().as_bytes();
    let mut address: libc::sockaddr_un = unsafe { std::mem::zeroed() };
    if bytes.len() >= address.sun_path.len() {
        return Err(err("socket path too long"));
    }
    address.sun_family = libc::AF_UNIX as _;
    for (to, from) in address.sun_path.iter_mut().zip(bytes) {
        *to = *from as _;
    }
    let fd = unsafe {
        libc::socket(
            libc::AF_UNIX,
            libc::SOCK_STREAM | libc::SOCK_CLOEXEC | libc::SOCK_NONBLOCK,
            0,
        )
    };
    if fd < 0 {
        return Err(err("cannot verify socket liveness"));
    }
    let owned = unsafe { File::from_raw_fd(fd) };
    let connected = unsafe {
        libc::connect(
            fd,
            (&address as *const libc::sockaddr_un).cast(),
            std::mem::size_of_val(&address) as _,
        )
    };
    let error = std::io::Error::last_os_error();
    drop(owned);
    if connected == 0 || error.raw_os_error() != Some(libc::ECONNREFUSED) {
        return Err(err("tmux socket live or unconfirmed; archive refused"));
    }
    if session::socket_identity(path)? != expected {
        return Err(err("socket changed during liveness check"));
    }
    Ok(true)
}

fn move_new(from: &Path, to: &Path) -> Result<()> {
    let from =
        CString::new(from.as_os_str().as_bytes()).map_err(|_| err("invalid archive source"))?;
    let to =
        CString::new(to.as_os_str().as_bytes()).map_err(|_| err("invalid archive destination"))?;
    if unsafe {
        libc::renameat2(
            libc::AT_FDCWD,
            from.as_ptr(),
            libc::AT_FDCWD,
            to.as_ptr(),
            libc::RENAME_NOREPLACE,
        )
    } != 0
    {
        return Err(err(
            "archive move refused; no overwrite (inspect retained evidence)",
        ));
    }
    Ok(())
}

fn write_new(path: &Path, data: &[u8]) -> Result<()> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)
        .map_err(|_| err("cannot create archive evidence"))?;
    file.write_all(data)
        .and_then(|_| file.sync_all())
        .map_err(|_| err("cannot persist archive evidence"))
}

/// Requires an exact expected identity from the operator's reviewed status.
/// A live dead-pane server is still live and cannot be archived here.
pub fn archive(
    config: &Path,
    id: &str,
    expected_id: &str,
    expected_ticks: u64,
) -> Result<Archived> {
    let target = Target::Project(id);
    let _ = target.screen_name()?; // Bridge and unsafe IDs are refused.
    let registry =
        ProjectRegistry::load(config).map_err(|_| err("cannot load project registry"))?;
    let root = screen::target_root(&registry, target)?;
    let state = screen::state_dir(false)?;
    let _lock = screen::lock_dir(&state)?;
    let path = session::record_path(&state, target)?;
    let (record, original, meta) =
        screen::read_record_snapshot(&path)?.ok_or_else(|| err("tmux slot is not registered"))?;
    let record = session::validated(record, target, &root)?;
    if record.full_id.as_deref() != Some(expected_id)
        || record.process_start_ticks != Some(expected_ticks)
    {
        return Err(err(
            "archive approval identity differs from registered slot",
        ));
    }
    let identity = record
        .tmux
        .as_ref()
        .ok_or_else(|| err("pending/incomplete identity; archive refused"))?;
    let lifecycle = record
        .tmux_lifecycle
        .as_ref()
        .ok_or_else(|| err("legacy slot lacks PID namespace provenance; archive refused"))?;
    let absent = || -> Result<()> {
        let (boot, namespace) = session::host_scope()?;
        if boot == lifecycle.boot_id {
            if namespace != lifecycle.pid_namespace {
                return Err(err(
                    "different PID namespace; process absence cannot authorize archive",
                ));
            }
            if !screen::original_process_is_absent(identity.server_pid, expected_ticks)? {
                return Err(err("original tmux server is alive; archive refused"));
            }
        }
        Ok(())
    };
    absent()?;
    let socket = session::socket_path(&state, target, false)?;
    let socket_present = stale_socket(&socket, (identity.socket_dev, identity.socket_ino))?;
    // Deterministic by immutable identity; existing evidence is never replaced.
    let destination = state.join(format!(
        ".archived-tmux-{}-{}-{}-{}",
        id, identity.server_pid, expected_ticks, identity.created
    ));
    fs::DirBuilder::new()
        .mode(0o700)
        .create(&destination)
        .map_err(|_| err("archive already exists or cannot be created; slot unchanged"))?;
    write_new(&destination.join("record.snapshot.json"), &original)?;
    let diagnostics = json!({"version":1,"multiplexer":"tmux","project_id":id,"session_id":expected_id,
        "server_pid":identity.server_pid,"process_start_ticks":expected_ticks,"lifecycle":lifecycle,
        "archived_at":SystemTime::now().duration_since(UNIX_EPOCH).map_err(|_| err("clock unavailable"))?.as_secs(),
        "reason":"original_server_absent","program_exit":"unknown_after_server_loss",
        "socket":{"present":socket_present,"device":identity.socket_dev,"inode":identity.socket_ino},
        "record":{"device":meta.dev(),"inode":meta.ino(),"mode":meta.mode() & 0o777,"size":meta.len()}});
    write_new(
        &destination.join("diagnostics.json"),
        &serde_json::to_vec_pretty(&diagnostics).map_err(|_| err("archive encoding failed"))?,
    )?;
    File::open(&destination)
        .and_then(|d| d.sync_all())
        .map_err(|_| err("cannot sync archive evidence"))?;
    let unchanged = || -> Result<()> {
        let (_, bytes, current) = screen::read_record_snapshot(&path)?
            .ok_or_else(|| err("record disappeared during archive"))?;
        if bytes != original || current.dev() != meta.dev() || current.ino() != meta.ino() {
            return Err(err("record changed during archive; retained evidence only"));
        }
        absent()
    };
    unchanged()?;
    if stale_socket(&socket, (identity.socket_dev, identity.socket_ino))? != socket_present {
        return Err(err("socket presence changed during archive"));
    }
    if socket_present {
        move_new(&socket, &destination.join("socket"))?;
    }
    File::open(&state)
        .and_then(|d| d.sync_all())
        .and_then(|_| File::open(&destination)?.sync_all())
        .map_err(|_| err("archive partially prepared; slot remains reserved"))?;
    unchanged()?;
    if fs::symlink_metadata(&socket).is_ok() {
        return Err(err("socket path reoccupied; slot remains reserved"));
    }
    // Slot is freed last, after both byte-exact evidence and the stale socket
    // have been preserved. A crash earlier leaves the original slot reserved.
    move_new(&path, &destination.join("record.json"))?;
    File::open(&destination)
        .and_then(|d| d.sync_all())
        .and_then(|_| File::open(&state)?.sync_all())
        .map_err(|_| {
            err("slot archived; directory sync failed, inspect archive before any new start")
        })?;
    Ok(Archived {
        path: destination,
        session_id: expected_id.into(),
    })
}
