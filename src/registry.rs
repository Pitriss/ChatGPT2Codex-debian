//! Local read-only registry for explicitly configured projects and context files.
//!
//! This is NOT a remote file API. Before an MCP surface is enabled, context
//! reads need kernel-enforced path resolution and outbound content filtering.

use serde::Deserialize;
use std::collections::{BTreeMap, HashSet};
use std::error::Error;
use std::fmt;
use std::fs::{self, File};
use std::io::Read;
#[cfg(target_os = "linux")]
use std::ffi::CString;
#[cfg(target_os = "linux")]
use std::os::unix::ffi::OsStrExt;
#[cfg(target_os = "linux")]
use std::os::unix::fs::OpenOptionsExt;
#[cfg(target_os = "linux")]
use std::os::fd::{AsRawFd, FromRawFd};
use std::path::{Component, Path, PathBuf};

const MAX_CONFIG_BYTES: u64 = 64 * 1024;
const MAX_CONTEXT_BYTES: u64 = 128 * 1024;
const MAX_PROJECTS: usize = 64;
const MAX_CONTEXT_FILES: usize = 32;
const DEFAULT_TEMPLATE: &str = "{project_id} | {codex_name} | {task}";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RegistryError(pub &'static str);

impl fmt::Display for RegistryError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.0)
    }
}
impl Error for RegistryError {}

type Result<T> = std::result::Result<T, RegistryError>;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct GlobalConfig {
    workspace: WorkspaceConfig,
    #[serde(default)]
    codex: GlobalCodex,
    #[serde(default)]
    sessions: GlobalSessions,
    #[serde(default)]
    git: GlobalGit,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct WorkspaceConfig {
    project_dir: PathBuf,
    #[serde(default = "default_rules_dir")]
    rules_dir: PathBuf,
    #[serde(default = "default_global_files")]
    global_context_files: Vec<PathBuf>,
}

fn default_rules_dir() -> PathBuf {
    PathBuf::from(".ai")
}
fn default_global_files() -> Vec<PathBuf> {
    ["CODEX_GLOBAL.md", "BOOTSTRAP.md", "PROJECT_DEFAULTS.md"]
        .into_iter()
        .map(PathBuf::from)
        .collect()
}

#[derive(Debug, Deserialize)]
#[serde(default, deny_unknown_fields)]
struct GlobalCodex {
    name: String,
}
impl Default for GlobalCodex {
    fn default() -> Self {
        Self { name: "Codex".into() }
    }
}

#[derive(Debug, Deserialize)]
#[serde(default, deny_unknown_fields)]
struct GlobalSessions {
    name_template: String,
}
impl Default for GlobalSessions {
    fn default() -> Self {
        Self { name_template: DEFAULT_TEMPLATE.into() }
    }
}

#[derive(Debug, Default, Deserialize)]
#[serde(default, deny_unknown_fields)]
struct GlobalGit {
    user_name: Option<String>,
    user_email: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ProjectConfig {
    project: ProjectIdentity,
    #[serde(default)]
    codex: ProjectCodex,
    #[serde(default)]
    sessions: ProjectSessions,
    #[serde(default)]
    contexts: ContextConfig,
    #[serde(default)]
    git: ProjectGit,
}

/// A newly bootstrapped project inherits the global author identity.
/// Existing checkouts adopted by the bridge preserve their own local Git identity.
#[derive(Debug, Clone, Copy, Default, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
enum GitIdentityMode {
    #[default]
    Global,
    Preserve,
}

#[derive(Debug, Default, Deserialize)]
#[serde(default, deny_unknown_fields)]
struct ProjectGit {
    identity: GitIdentityMode,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ProjectIdentity {
    id: String,
    directory: String,
    #[serde(default)]
    name: Option<String>,
}

#[derive(Debug, Default, Deserialize)]
#[serde(default, deny_unknown_fields)]
struct ProjectCodex {
    name: Option<String>,
}

#[derive(Debug, Default, Deserialize)]
#[serde(default, deny_unknown_fields)]
struct ProjectSessions {
    name_template: Option<String>,
    multiplexer: crate::multiplexer::Multiplexer,
}

#[derive(Debug, Deserialize)]
#[serde(default, deny_unknown_fields)]
struct ContextConfig {
    files: Vec<PathBuf>,
}
impl Default for ContextConfig {
    fn default() -> Self {
        Self {
            files: [
                "AGENTS.md",
                ".ai/.project_codex.md",
                ".ai/PROJECT_CONTEXT.md",
                ".ai/CODEX_RESULTS.md",
            ]
            .into_iter()
            .map(PathBuf::from)
            .collect(),
        }
    }
}

#[derive(Debug, Clone)]
pub struct Project {
    pub id: String,
    pub name: String,
    pub root: PathBuf,
    pub codex_name: String,
    pub name_template: String,
    pub context_files: Vec<PathBuf>,
    pub manage_git_identity: bool,
    pub multiplexer: crate::multiplexer::Multiplexer,
}

#[derive(Debug)]
pub struct ProjectRegistry {
    pub project_dir: PathBuf,
    pub rules_dir: PathBuf,
    pub global_files: Vec<PathBuf>,
    pub git_user_name: Option<String>,
    pub git_user_email: Option<String>,
    projects: BTreeMap<String, Project>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Scope {
    Global,
    Project,
}
impl Scope {
    pub fn parse(s: &str) -> Result<Self> {
        match s {
            "global" => Ok(Self::Global),
            "project" => Ok(Self::Project),
            _ => Err(RegistryError("scope must be global or project")),
        }
    }
    pub fn label(self) -> &'static str {
        match self {
            Self::Global => "global",
            Self::Project => "project",
        }
    }
}

#[derive(Debug)]
pub struct ContextEntry {
    pub scope: Scope,
    pub path: PathBuf,
    pub status: &'static str,
}

fn read_small_utf8(path: &Path, max_bytes: u64) -> Result<String> {
    let info = fs::symlink_metadata(path).map_err(|_| RegistryError("file metadata unavailable"))?;
    if !info.file_type().is_file() || info.len() > max_bytes {
        return Err(RegistryError("file is not regular or exceeds size limit"));
    }
    let mut bytes = Vec::new();
    File::open(path)
        .map_err(|_| RegistryError("cannot open file"))?
        .take(max_bytes + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| RegistryError("cannot read file"))?;
    if bytes.len() as u64 > max_bytes {
        return Err(RegistryError("file exceeds size limit"));
    }
    String::from_utf8(bytes).map_err(|_| RegistryError("file is not UTF-8"))
}

/// A descriptor-anchored read. The pathname must stay below the verified
/// registry root even if directory entries change during the operation.
/// Unsupported kernels fail closed; a checked pathname alone is insufficient.
#[cfg(target_os = "linux")]
fn read_context_confined(root: &Path, relative: &Path) -> Result<String> {
    #[repr(C)]
    struct OpenHow { flags: u64, mode: u64, resolve: u64 }
    const RESOLVE_NO_MAGICLINKS: u64 = 0x02;
    const RESOLVE_NO_SYMLINKS: u64 = 0x04;
    const RESOLVE_BENEATH: u64 = 0x08;
    validate_relative(relative, false)?;
    let base = fs::OpenOptions::new().read(true)
        .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(root).map_err(|_| RegistryError("cannot securely open context root"))?;
    let name = CString::new(relative.as_os_str().as_bytes())
        .map_err(|_| RegistryError("invalid context path"))?;
    let how = OpenHow {
        flags: (libc::O_RDONLY | libc::O_CLOEXEC | libc::O_NOFOLLOW | libc::O_NONBLOCK) as u64,
        mode: 0,
        resolve: RESOLVE_BENEATH | RESOLVE_NO_MAGICLINKS | RESOLVE_NO_SYMLINKS,
    };
    let fd = unsafe { libc::syscall(libc::SYS_openat2, base.as_raw_fd(), name.as_ptr(), &how, std::mem::size_of::<OpenHow>()) };
    if fd < 0 { return Err(RegistryError("context path cannot be opened safely")); }
    // SAFETY: successful openat2 returned a new owned file descriptor.
    let file = unsafe { File::from_raw_fd(fd as i32) };
    let meta = file.metadata().map_err(|_| RegistryError("cannot inspect context descriptor"))?;
    if !meta.is_file() || meta.len() > MAX_CONTEXT_BYTES {
        return Err(RegistryError("context is not a small regular file"));
    }
    let mut bytes = Vec::new();
    file.take(MAX_CONTEXT_BYTES + 1).read_to_end(&mut bytes)
        .map_err(|_| RegistryError("cannot read context"))?;
    if bytes.len() as u64 > MAX_CONTEXT_BYTES { return Err(RegistryError("context exceeds size limit")); }
    String::from_utf8(bytes).map_err(|_| RegistryError("context is not UTF-8"))
}

#[cfg(not(target_os = "linux"))]
fn read_context_confined(_root: &Path, _relative: &Path) -> Result<String> {
    Err(RegistryError("secure context reads require Linux openat2"))
}

pub(crate) fn validate_id(value: &str) -> Result<()> {
    if value.is_empty()
        || value.len() > 64
        || !value.as_bytes()[0].is_ascii_lowercase()
        || !value.bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-' || b == b'_')
    {
        return Err(RegistryError("invalid project id"));
    }
    Ok(())
}

fn check_text(text: &str, max_chars: usize) -> Result<()> {
    if text.trim().is_empty() || text.chars().count() > max_chars || text.chars().any(char::is_control) {
        return Err(RegistryError("invalid display text"));
    }
    Ok(())
}

pub(crate) fn validate_relative(path: &Path, single: bool) -> Result<()> {
    let components: Vec<_> = path.components().collect();
    if components.is_empty() || (single && components.len() != 1) {
        return Err(RegistryError("path must use a permitted relative form"));
    }
    for part in components {
        if let Component::Normal(segment) = part {
            let name = segment.to_str().ok_or(RegistryError("non-UTF-8 path"))?;
            if name.is_empty() || name.chars().any(char::is_control) {
                return Err(RegistryError("invalid path component"));
            }
        } else {
            return Err(RegistryError("path traversal or absolute paths are forbidden"));
        }
    }
    Ok(())
}

fn check_unique(files: &[PathBuf]) -> Result<()> {
    if files.len() > MAX_CONTEXT_FILES {
        return Err(RegistryError("too many context files"));
    }
    let mut seen = HashSet::new();
    for path in files {
        validate_relative(path, false)?;
        if !seen.insert(path) {
            return Err(RegistryError("duplicate context file"));
        }
    }
    Ok(())
}

fn validate_template(template: &str) -> Result<()> {
    check_text(template, 180)?;
    let mut chars = template.chars().peekable();
    let mut has_project_id = false;
    while let Some(ch) = chars.next() {
        if ch == '}' {
            return Err(RegistryError("unmatched name template brace"));
        }
        if ch == '{' {
            let mut key = String::new();
            loop {
                match chars.next() {
                    Some('}') => break,
                    Some('{') | None => return Err(RegistryError("invalid name template braces")),
                    Some(character) => key.push(character),
                }
                if key.len() > 16 {
                    return Err(RegistryError("invalid name template placeholder"));
                }
            }
            match key.as_str() {
                "project_id" => has_project_id = true,
                "codex_name" | "task" => (),
                _ => return Err(RegistryError("unsupported name template placeholder")),
            }
        }
    }
    if !has_project_id {
        return Err(RegistryError("name template must include {project_id}"));
    }
    Ok(())
}

fn context_status(root: &Path, relative: &Path) -> Result<&'static str> {
    validate_relative(relative, false)?;
    // Every existing path component must be a real directory or a regular file.
    // A missing component is reported rather than created in read-only P0-D.
    let mut current = root.to_path_buf();
    let parts: Vec<_> = relative.components().collect();
    for (index, part) in parts.iter().enumerate() {
        current.push(part.as_os_str());
        let info = match fs::symlink_metadata(&current) {
            Ok(info) => info,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok("missing"),
            Err(_) => return Err(RegistryError("cannot inspect context path")),
        };
        if info.file_type().is_symlink() {
            return Err(RegistryError("symlink in context path is forbidden"));
        }
        if index + 1 == parts.len() {
            if !info.is_file() || info.len() > MAX_CONTEXT_BYTES {
                return Err(RegistryError("context is not regular or exceeds size limit"));
            }
        } else if !info.is_dir() {
            return Err(RegistryError("context parent is not a directory"));
        }
    }
    Ok("available")
}

impl ProjectRegistry {
    pub fn load(config_path: &Path) -> Result<Self> {
        let raw = read_small_utf8(config_path, MAX_CONFIG_BYTES)?;
        let config: GlobalConfig = toml::from_str(&raw).map_err(|_| RegistryError("invalid global TOML"))?;
        if !config.workspace.project_dir.is_absolute() {
            return Err(RegistryError("project_dir must be absolute"));
        }
        if fs::symlink_metadata(&config.workspace.project_dir)
            .map_err(|_| RegistryError("project_dir unavailable"))?
            .file_type()
            .is_symlink()
        {
            return Err(RegistryError("project_dir symlink is forbidden"));
        }
        let project_dir = fs::canonicalize(&config.workspace.project_dir)
            .map_err(|_| RegistryError("project_dir unavailable"))?;
        if !project_dir.is_dir() {
            return Err(RegistryError("project_dir is not a directory"));
        }
        validate_relative(&config.workspace.rules_dir, true)?;
        check_unique(&config.workspace.global_context_files)?;
        check_text(&config.codex.name, 80)?;
        validate_template(&config.sessions.name_template)?;
        if let Some(ref name) = config.git.user_name { check_text(name, 100)?; }
        if let Some(ref email) = config.git.user_email {
            check_text(email, 200)?;
            if !email.contains('@') || email.contains(' ') { return Err(RegistryError("invalid configured Git email")); }
        }

        let rules_dir = project_dir.join(config.workspace.rules_dir);
        // Do not follow a symlink at the shared rules directory.
        if let Ok(info) = fs::symlink_metadata(&rules_dir) {
            if info.file_type().is_symlink() || !info.is_dir() {
                return Err(RegistryError("unsafe shared rules directory"));
            }
        }

        let config_parent = config_path.parent().ok_or(RegistryError("invalid config path"))?;
        let projects_path = config_parent.join("projects");
        let project_info = fs::symlink_metadata(&projects_path)
            .map_err(|_| RegistryError("project configs directory unavailable"))?;
        if !project_info.is_dir() || project_info.file_type().is_symlink() {
            return Err(RegistryError("unsafe project configs directory"));
        }
        let mut paths = Vec::new();
        for entry in fs::read_dir(projects_path).map_err(|_| RegistryError("cannot list project configs"))? {
            let entry = entry.map_err(|_| RegistryError("cannot list project configs"))?;
            if entry.path().extension().is_some_and(|extension| extension == "toml") {
                paths.push(entry.path());
                if paths.len() > MAX_PROJECTS {
                    return Err(RegistryError("too many project configs"));
                }
            }
        }
        paths.sort();
        let mut projects = BTreeMap::new();
        let mut registered_roots = HashSet::new();
        for config_path in paths {
            let raw = read_small_utf8(&config_path, MAX_CONFIG_BYTES)?;
            let item: ProjectConfig = toml::from_str(&raw).map_err(|_| RegistryError("invalid project TOML"))?;
            validate_id(&item.project.id)?;
            if config_path.file_stem().and_then(|part| part.to_str()) != Some(item.project.id.as_str()) {
                return Err(RegistryError("project id must match TOML filename"));
            }
            let subdir = PathBuf::from(&item.project.directory);
            validate_relative(&subdir, true)?;
            let target = project_dir.join(&subdir);
            let root_info = fs::symlink_metadata(&target).map_err(|_| RegistryError("project directory missing"))?;
            if root_info.file_type().is_symlink() || !root_info.is_dir() {
                return Err(RegistryError("project directory cannot be a symlink"));
            }
            let root = fs::canonicalize(target).map_err(|_| RegistryError("project directory unavailable"))?;
            if root.parent() != Some(project_dir.as_path()) {
                return Err(RegistryError("project directory escapes project_dir"));
            }
            if !registered_roots.insert(root.clone()) { return Err(RegistryError("project directory registered multiple times")); }
            let git_info = fs::symlink_metadata(root.join(".git"))
                .map_err(|_| RegistryError("project is not a Git checkout"))?;
            if git_info.file_type().is_symlink() || !(git_info.is_dir() || git_info.is_file()) {
                return Err(RegistryError("unsafe Git metadata path"));
            }
            let name = item.project.name.unwrap_or_else(|| item.project.id.clone());
            check_text(&name, 80)?;
            let codex_name = item.codex.name.unwrap_or_else(|| config.codex.name.clone());
            check_text(&codex_name, 80)?;
            let name_template = item.sessions.name_template.unwrap_or_else(|| config.sessions.name_template.clone());
            validate_template(&name_template)?;
            check_unique(&item.contexts.files)?;
            let project = Project {
                id: item.project.id.clone(),
                name,
                root,
                codex_name,
                name_template,
                context_files: item.contexts.files,
                manage_git_identity: item.git.identity == GitIdentityMode::Global,
                multiplexer: item.sessions.multiplexer,
            };
            if projects.insert(item.project.id, project).is_some() {
                return Err(RegistryError("duplicate project id"));
            }
        }
        Ok(Self { project_dir, rules_dir, global_files: config.workspace.global_context_files,
            git_user_name: config.git.user_name, git_user_email: config.git.user_email, projects })
    }

    pub fn projects(&self) -> impl Iterator<Item = &Project> {
        self.projects.values()
    }

    pub fn project(&self, id: &str) -> Result<&Project> {
        self.projects.get(id).ok_or(RegistryError("unknown project id"))
    }

    pub fn contexts(&self, id: &str) -> Result<Vec<ContextEntry>> {
        let project = self.project(id)?;
        let mut entries = Vec::new();
        for path in &self.global_files {
            entries.push(ContextEntry { scope: Scope::Global, path: path.clone(), status: context_status(&self.rules_dir, path)? });
        }
        for path in &project.context_files {
            entries.push(ContextEntry { scope: Scope::Project, path: path.clone(), status: context_status(&project.root, path)? });
        }
        Ok(entries)
    }

    pub fn read_context(&self, id: &str, scope: Scope, file: &str) -> Result<String> {
        let project = self.project(id)?;
        let relative = PathBuf::from(file);
        validate_relative(&relative, false)?;
        let (root, allowlist) = match scope {
            Scope::Global => (&self.rules_dir, &self.global_files),
            Scope::Project => (&project.root, &project.context_files),
        };
        if !allowlist.contains(&relative) {
            return Err(RegistryError("context file is not allowlisted"));
        }
        match context_status(root, &relative)? {
            "available" => read_small_utf8(&root.join(relative), MAX_CONTEXT_BYTES),
            _ => Err(RegistryError("allowlisted context is missing")),
        }
    }

    /// MCP-only, descriptor-confined version of read_context. All paths are
    /// drawn from the configured allowlist; no caller-supplied absolute paths.
    pub fn read_context_mcp(&self, id: &str, scope: Scope, file: &str) -> Result<String> {
        let project = self.project(id)?;
        let relative = PathBuf::from(file);
        validate_relative(&relative, false)?;
        let (root, allowlist) = match scope {
            Scope::Global => (&self.rules_dir, &self.global_files),
            Scope::Project => (&project.root, &project.context_files),
        };
        if !allowlist.contains(&relative) { return Err(RegistryError("context is not allowlisted")); }
        read_context_confined(root, &relative)
    }

    /// Naming preview only. It never calls Codex or creates a session.
    pub fn preview_session_name(&self, id: &str, task: &str) -> Result<String> {
        let project = self.project(id)?;
        check_text(task, 80)?;
        let mut rendered = String::new();
        let mut remaining = project.name_template.as_str();
        while let Some(open) = remaining.find('{') {
            rendered.push_str(&remaining[..open]);
            let tail = &remaining[open + 1..];
            let close = tail.find('}').ok_or(RegistryError("invalid name template"))?;
            let key = &tail[..close];
            rendered.push_str(match key {
                "project_id" => &project.id,
                "codex_name" => &project.codex_name,
                "task" => task,
                _ => return Err(RegistryError("invalid name template")),
            });
            remaining = &tail[close + 1..];
        }
        rendered.push_str(remaining);
        if rendered.chars().count() > 240 {
            return Err(RegistryError("rendered session name too long"));
        }
        Ok(rendered)
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn project_multiplexer_is_optional_and_defaults_to_screen() {
        use crate::multiplexer::Multiplexer;
        assert_eq!(toml::from_str::<ProjectSessions>("").unwrap().multiplexer, Multiplexer::Screen);
        assert_eq!(toml::from_str::<ProjectSessions>("multiplexer='tmux'").unwrap().multiplexer, Multiplexer::Tmux);
        assert!(toml::from_str::<ProjectSessions>("multiplexer='other'").is_err());
    }
    use super::*;
    use std::os::unix::fs::symlink;
    use std::sync::atomic::{AtomicU64, Ordering};

    static SEQUENCE: AtomicU64 = AtomicU64::new(0);
    struct Fixture { root: PathBuf }
    impl Fixture {
        fn new() -> Self {
            let root = std::env::temp_dir().join(format!(
                "chatgpt2codex-registry-test-{}-{}",
                std::process::id(), SEQUENCE.fetch_add(1, Ordering::Relaxed)
            ));
            fs::create_dir_all(root.join("mycode/k2-smb/.ai")).unwrap();
            fs::create_dir_all(root.join("mycode/k2-smb/.git")).unwrap();
            fs::create_dir_all(root.join("mycode/.ai")).unwrap();
            fs::create_dir_all(root.join("cfg/projects")).unwrap();
            fs::write(root.join("mycode/.ai/CODEX_GLOBAL.md"), "Global instructions").unwrap();
            fs::write(root.join("mycode/k2-smb/.ai/.project_codex.md"), "Local instructions").unwrap();
            let global = format!(
                "[workspace]\nproject_dir = {:?}\nrules_dir = '.ai'\nglobal_context_files = ['CODEX_GLOBAL.md']\n[codex]\nname = 'Kodex'\n[sessions]\nname_template = '{{project_id}} | {{codex_name}} | {{task}}'\n",
                root.join("mycode").to_str().unwrap()
            );
            fs::write(root.join("cfg/config.toml"), global).unwrap();
            fs::write(root.join("cfg/projects/k2-smb.toml"),
                "[project]\nid = 'k2-smb'\ndirectory = 'k2-smb'\n[codex]\nname = 'Special'\n[contexts]\nfiles = ['.ai/.project_codex.md', '.ai/CODEX_RESULTS.md']\n").unwrap();
            Self { root }
        }
        fn config(&self) -> PathBuf { self.root.join("cfg/config.toml") }
    }
    impl Drop for Fixture {
        fn drop(&mut self) { let _ = fs::remove_dir_all(&self.root); }
    }

    #[test]
    fn reads_context_and_previews_project_override() {
        let fixture = Fixture::new();
        let registry = ProjectRegistry::load(&fixture.config()).unwrap();
        assert_eq!(registry.projects().count(), 1);
        assert_eq!(registry.project("k2-smb").unwrap().codex_name, "Special");
        assert_eq!(registry.preview_session_name("k2-smb", "Fix KIO").unwrap(), "k2-smb | Special | Fix KIO");
        assert_eq!(registry.read_context("k2-smb", Scope::Global, "CODEX_GLOBAL.md").unwrap(), "Global instructions");
        assert_eq!(registry.read_context("k2-smb", Scope::Project, ".ai/.project_codex.md").unwrap(), "Local instructions");
        assert_eq!(registry.contexts("k2-smb").unwrap()[2].status, "missing");
    }

    #[test]
    fn refuses_arbitrary_paths_and_nonallowlisted_files() {
        let fixture = Fixture::new();
        let registry = ProjectRegistry::load(&fixture.config()).unwrap();
        for name in ["../../etc/passwd", "/etc/passwd", "AGENTS.md"] {
            assert!(registry.read_context("k2-smb", Scope::Project, name).is_err());
        }
        assert!(registry.project("other").is_err());
    }

    #[test]
    fn refuses_symlinked_context_file() {
        let fixture = Fixture::new();
        let fake = fixture.root.join("mycode/k2-smb/.ai/.project_codex.md");
        fs::remove_file(&fake).unwrap();
        symlink("/etc/passwd", &fake).unwrap();
        let registry = ProjectRegistry::load(&fixture.config()).unwrap();
        assert!(registry.read_context("k2-smb", Scope::Project, ".ai/.project_codex.md").is_err());
        assert!(registry.contexts("k2-smb").is_err());
    }

    #[test]
    fn refuses_symlinked_context_parent() {
        let fixture = Fixture::new();
        let context_dir = fixture.root.join("mycode/k2-smb/.ai");
        fs::remove_dir_all(&context_dir).unwrap();
        symlink(fixture.root.join("mycode/.ai"), &context_dir).unwrap();
        let registry = ProjectRegistry::load(&fixture.config()).unwrap();
        assert!(registry.read_context("k2-smb", Scope::Project, ".ai/.project_codex.md").is_err());
    }

    #[test]
    fn rejects_project_directory_symlinks() {
        let fixture = Fixture::new();
        fs::create_dir(fixture.root.join("outside")).unwrap();
        fs::remove_dir_all(fixture.root.join("mycode/k2-smb")).unwrap();
        symlink(fixture.root.join("outside"), fixture.root.join("mycode/k2-smb")).unwrap();
        assert!(ProjectRegistry::load(&fixture.config()).is_err());
    }

    #[test]
    fn rejects_unexpected_global_and_project_keys() {
        let fixture = Fixture::new();
        let path = fixture.root.join("cfg/projects/k2-smb.toml");
        fs::write(path, "[project]\nid='k2-smb'\ndirectory='k2-smb'\nallow_shell=true\n").unwrap();
        assert!(ProjectRegistry::load(&fixture.config()).is_err());
    }

    #[test]
    fn enforces_template_safety_and_project_id_placeholder() {
        let fixture = Fixture::new();
        let registry = ProjectRegistry::load(&fixture.config()).unwrap();
        assert!(registry.preview_session_name("k2-smb", "task\nESC").is_err());
        let path = fixture.root.join("cfg/config.toml");
        let text = fs::read_to_string(&path).unwrap().replace("{project_id} | {codex_name} | {task}", "{task}");
        fs::write(&path, text).unwrap();
        assert!(ProjectRegistry::load(&fixture.config()).is_err());
    }

    #[test]
    fn blocks_context_files_over_size_limit() {
        let fixture = Fixture::new();
        fs::write(fixture.root.join("mycode/.ai/CODEX_GLOBAL.md"), vec![b'x'; MAX_CONTEXT_BYTES as usize + 1]).unwrap();
        let registry = ProjectRegistry::load(&fixture.config()).unwrap();
        assert!(registry.read_context("k2-smb", Scope::Global, "CODEX_GLOBAL.md").is_err());
    }

    #[test]
    fn respects_project_template_override() {
        let fixture = Fixture::new();
        let path = fixture.root.join("cfg/projects/k2-smb.toml");
        fs::write(&path, "[project]\nid='k2-smb'\ndirectory='k2-smb'\n[sessions]\nname_template='{project_id}: {task}'\n").unwrap();
        let registry = ProjectRegistry::load(&fixture.config()).unwrap();
        assert_eq!(registry.preview_session_name("k2-smb", "A").unwrap(), "k2-smb: A");
        assert_eq!(registry.project("k2-smb").unwrap().codex_name, "Kodex");
    }
}
