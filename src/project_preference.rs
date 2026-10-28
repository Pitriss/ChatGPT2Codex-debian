//! Explicit local project preference edit; no session/process control.
use crate::multiplexer::Multiplexer;
use crate::registry::ProjectRegistry;
use crate::screen::{err, Result};
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt};
use std::path::Path;

fn edited(raw: &str, mux: Multiplexer) -> Result<String> {
    // toml_edit is already used by toml; preserve comments and support both
    // normal and inline/dotted sessions tables accepted by the registry.
    let mut document = raw
        .parse::<toml_edit::DocumentMut>()
        .map_err(|_| err("invalid project preference TOML"))?;
    if document
        .get("sessions")
        .is_some_and(|item| item.as_table_like().is_none())
    {
        return Err(err("sessions must be a TOML table"));
    }
    let mut value = toml_edit::value(mux.as_str());
    if let Some(old) = document
        .get("sessions")
        .and_then(toml_edit::Item::as_table_like)
        .and_then(|table| table.get("multiplexer"))
        .and_then(toml_edit::Item::as_value)
    {
        *value.as_value_mut().unwrap().decor_mut() = old.decor().clone();
    }
    document["sessions"]["multiplexer"] = value;
    Ok(document.to_string())
}

fn read_owned(path: &Path) -> Result<(String, fs::Metadata)> {
    let mut file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)
        .map_err(|_| err("cannot safely open project config"))?;
    let info = file
        .metadata()
        .map_err(|_| err("project config metadata unavailable"))?;
    if !info.is_file() || info.uid() != unsafe { libc::geteuid() } || info.len() > 65536 {
        return Err(err("unsafe project config for preference write"));
    }
    let mut raw = String::new();
    (&mut file)
        .take(65537)
        .read_to_string(&mut raw)
        .map_err(|_| err("cannot read project config"))?;
    if raw.len() > 65536 {
        return Err(err("project config too large"));
    }
    Ok((raw, info))
}

pub fn set(config: &Path, id: &str, mux: Multiplexer) -> Result<()> {
    crate::registry::validate_id(id).map_err(|_| err("invalid project ID"))?;
    let registry =
        ProjectRegistry::load(config).map_err(|_| err("cannot load project registry"))?;
    registry
        .project(id)
        .map_err(|_| err("project not registered"))?;
    let dir = config
        .parent()
        .ok_or_else(|| err("config parent missing"))?
        .join("projects");
    let meta = fs::symlink_metadata(&dir).map_err(|_| err("project config directory missing"))?;
    if !meta.is_dir() || meta.file_type().is_symlink() || meta.uid() != unsafe { libc::geteuid() } {
        return Err(err(
            "project config directory must be owned and not a symlink",
        ));
    }
    let lock = File::open(&dir).map_err(|_| err("cannot lock project config directory"))?;
    use std::os::fd::AsRawFd;
    if unsafe { libc::flock(lock.as_raw_fd(), libc::LOCK_EX) } != 0 {
        return Err(err("preference lock failed"));
    }
    let path = dir.join(format!("{id}.toml"));
    let (raw, info) = read_owned(&path)?;
    let replacement = edited(&raw, mux)?;
    let temporary = dir.join(format!(".{id}-mux-{}.pending", std::process::id()));
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(info.mode() & 0o777)
        .open(&temporary)
        .map_err(|_| err("cannot create preference update"))?;
    let result = (|| {
        file.write_all(replacement.as_bytes())
            .and_then(|_| file.set_permissions(fs::Permissions::from_mode(info.mode() & 0o777)))
            .and_then(|_| file.sync_all())
            .map_err(|_| err("cannot persist preference"))?;
        let (current, metadata) = read_owned(&path)?;
        if current != raw || metadata.dev() != info.dev() || metadata.ino() != info.ino() {
            return Err(err("project config changed concurrently"));
        }
        fs::rename(&temporary, &path).map_err(|_| err("cannot replace project preference"))?;
        lock.sync_all()
            .map_err(|_| err("preference directory sync failed"))?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn preserves_other_configuration_and_comments() {
        assert!(edited("sessions=1", Multiplexer::Tmux).is_err());
        for raw in [
            "# keep\n[project]\nid='demo'\n",
            "[sessions]\n# keep\nname_template='x'\n[git]\nidentity='preserve'\n",
            "[sessions]\n",
            "[sessions]\nmultiplexer='screen' # keep\n",
            "sessions={name_template='x'} # keep\n",
            "sessions.name_template='x' # keep\n",
        ] {
            let changed = edited(raw, Multiplexer::Tmux).unwrap();
            assert!(changed.contains("# keep") || !raw.contains("# keep"));
            assert!(changed.contains("multiplexer"));
            let back = edited(&changed, Multiplexer::Screen).unwrap();
            assert!(back.contains("\"screen\""));
            let parsed: toml::Value = toml::from_str(&changed).unwrap();
            assert_eq!(parsed["sessions"]["multiplexer"].as_str(), Some("tmux"));
        }
    }
}
