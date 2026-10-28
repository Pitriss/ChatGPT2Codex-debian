use chatgpt2codex::mcp::{self, McpOptions};
use chatgpt2codex::codex::{CodexClient, SessionPage};
use chatgpt2codex::registry::{ProjectRegistry, Scope};
use chatgpt2codex::screen::{self, Target as ScreenTarget};
use chatgpt2codex::{session, project_preference, multiplexer::Multiplexer};
use chatgpt2codex::workspace::{self, BootstrapRequest};
use std::env;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

const MAX_PAGES: usize = 10;

#[derive(Debug)]
struct SessionOptions {
    cwd: PathBuf,
    limit: u32,
    pages: usize,
    id: Option<String>,
}

fn usage() {
    eprintln!("Tmux lifecycle:\n  session start --id ID --multiplexer tmux [--remain-on-exit] --approve-start [--program-status] [--config FILE]\n  session list|status [other options] --program-status\n  session archive --id ID --multiplexer tmux --expect-session-id FULL_ID --expect-process-start-ticks TICKS --approve-archive [--config FILE]\nArchive never authorizes a new start; legacy slots without namespace provenance are refused.");
    eprintln!("Local multiplexer commands:\n  gpt2codex session probe|projects|list [--config FILE]\n  gpt2codex session prefer --id ID --multiplexer screen|tmux [--config FILE]\n  gpt2codex session status|attach --bridge|--id ID --multiplexer screen|tmux [--expect-session-id ID (attach only)] [--config FILE]\n  gpt2codex session start --bridge|--id ID [--multiplexer screen|tmux] [--task LABEL] --approve-start [--config FILE]");
    eprintln!(
        "Usage:\n  gpt2codex screen probe [--config FILE]\n  gpt2codex screen list [--config FILE]\n  gpt2codex screen status|attach --bridge|--id PROJECT_ID [--config FILE]\n  gpt2codex screen start --bridge|--id PROJECT_ID [--task LABEL] --approve-start [--config FILE]\n  gpt2codex mcp stdio [--config /absolute/config.toml] [--allow-context-read]\n  gpt2codex codex probe\n  gpt2codex codex diagnostics --id PROJECT_ID [--limit 10] [--config FILE]\n  gpt2codex codex sessions --cwd /absolute/project/path [--limit 25] [--pages 1]\n  gpt2codex codex session --cwd /absolute/project/path --id UUID\n  gpt2codex workspace bootstrap --project-dir ABS --id ID --directory REPO_DIR --git-name NAME --git-email EMAIL [--codex-name NAME] [--config FILE]\n  gpt2codex workspace adopt --id PROJECT_ID --directory REPO_DIR [--dry-run] [--config FILE]\n  gpt2codex workspace health|ensure|sync-policy --id ID [--config FILE]\n  gpt2codex projects list [--config /absolute/config.toml]\n  gpt2codex project info|contexts|sessions|session|read|name --id PROJECT_ID [--config /absolute/config.toml]\n    project sessions: [--limit 25] [--pages 1]\n    project session: --thread UUID\n    project read: --scope global|project --file ALLOWLISTED_PATH\n    project name: --task SHORT_TASK\n\nP0 mode: read-only MCP; workspace writes and screen start/attach require explicit LOCAL CLI invocation, never exposed via MCP."
    );
}

fn parse_options(args: impl Iterator<Item = String>, single: bool) -> Result<SessionOptions, &'static str> {
    let mut cwd = None;
    let mut id = None;
    let mut limit = 25;
    let mut pages = 1;
    let mut args = args;
    while let Some(flag) = args.next() {
        let value = args.next().ok_or("missing value for option")?;
        match flag.as_str() {
            "--cwd" if cwd.is_none() => cwd = Some(PathBuf::from(value)),
            "--id" if single && id.is_none() => id = Some(value),
            "--limit" if !single => limit = value.parse().map_err(|_| "invalid limit")?,
            "--pages" if !single => pages = value.parse().map_err(|_| "invalid pages")?,
            _ => return Err("unknown or repeated option"),
        }
    }
    if !(1..=100).contains(&limit) || !(1..=MAX_PAGES).contains(&pages) {
        return Err("limit must be 1..100 and pages must be 1..10");
    }
    if single && id.is_none() {
        return Err("--id is required for session");
    }
    let cwd = cwd.ok_or("--cwd is required")?;
    if !cwd.is_absolute() || !cwd.is_dir() {
        return Err("--cwd must name an existing absolute directory");
    }
    let cwd = cwd.canonicalize().map_err(|_| "cannot canonicalize project directory")?;
    Ok(SessionOptions { cwd, limit, pages, id })
}

/// Scoped read-only snapshot. A separate app-server process is deliberately
/// not treated as the live event source/controller of a GNU screen Codex TUI.
#[derive(Debug, Default)]
struct DiagnosticOptions {
    id: Option<String>,
    config: Option<PathBuf>,
    limit: Option<u32>,
}

fn parse_diagnostic_options(args: impl Iterator<Item = String>) -> Result<DiagnosticOptions, &'static str> {
    let mut out = DiagnosticOptions::default();
    let mut args = args;
    while let Some(flag) = args.next() {
        let value = args.next().ok_or("missing diagnostics option value")?;
        match flag.as_str() {
            "--id" if out.id.is_none() => out.id = Some(value),
            "--config" if out.config.is_none() => out.config = Some(PathBuf::from(value)),
            "--limit" if out.limit.is_none() => out.limit = Some(value.parse().map_err(|_| "invalid limit")?),
            _ => return Err("unknown or repeated diagnostics option"),
        }
    }
    if out.id.is_none() { return Err("--id is required"); }
    if !(1..=25).contains(&out.limit.unwrap_or(10)) { return Err("limit must be 1..25"); }
    if out.config.as_ref().is_some_and(|path| !path.is_absolute()) {
        return Err("--config must be absolute");
    }
    Ok(out)
}

fn run_codex_diagnostics(args: impl Iterator<Item = String>) -> Result<(), Box<dyn std::error::Error>> {
    let options = parse_diagnostic_options(args)?;
    let config = match options.config { Some(config) => config, None => default_config_path()? };
    let registry = ProjectRegistry::load(&config)?;
    let project_id = options.id.as_deref().ok_or("missing project id")?;
    let project = registry.project(project_id)?;
    let mut client = CodexClient::connect()?;
    let page = client.list_sessions(&project.root, options.limit.unwrap_or(10), None)?;
    // Validate the newest thread against the same project without loading turns
    // or resuming it. A missing state DB must fail, not trigger a filesystem scan.
    if let Some(first) = page.threads.first() {
        client.read_session_metadata(&project.root, &first.id)?;
    }
    let mut active = 0_usize;
    let mut idle = 0_usize;
    let mut unloaded = 0_usize;
    let mut errors = 0_usize;
    for item in &page.threads {
        match item.status {
            "active" => active += 1,
            "idle" => idle += 1,
            "notLoaded" => unloaded += 1,
            "systemError" => errors += 1,
            _ => return Err("unsupported Codex session status".into()),
        }
    }
    let observed = client.observed_events();
    // No text, paths, previews, prompts, conversation IDs or raw error payloads.
    println!("P0J=OK project_id={project_id} protocol=stdio metadata=readonly state_db_only=1");
    println!("P0J_SESSIONS=count:{} active:{} idle:{} not_loaded:{} system_error:{} more:{}",
        page.threads.len(), active, idle, unloaded, errors, if page.next_cursor.is_some() { 1 } else { 0 });
    println!("P0J_EVENTS=thread:{} turn:{} item:{} other:{} scope=diagnostic_connection_only",
        observed.thread, observed.turn, observed.item, observed.other);
    println!("P0J_TUI=separate_process live_attachment=not_verified control=disabled");
    Ok(())
}

fn print_page(page: &SessionPage, cwd: &Path) {
    println!("project={}", cwd.display());
    println!("sessions={} more={}", page.threads.len(), page.next_cursor.is_some());
    for item in &page.threads {
        println!(
            "id={} status={} created={} updated={}",
            item.id, item.status, item.created_at, item.updated_at
        );
    }
}

#[derive(Default)]
struct RegistryOptions {
    config: Option<PathBuf>,
    id: Option<String>,
    file: Option<String>,
    scope: Option<Scope>,
    task: Option<String>,
    thread: Option<String>,
    limit: Option<u32>,
    pages: Option<usize>,
}

fn default_config_path() -> Result<PathBuf, Box<dyn std::error::Error>> {
    if let Ok(base) = env::var("XDG_CONFIG_HOME") {
        let root = PathBuf::from(base);
        if root.is_absolute() {
            return Ok(root.join("chatgpt2codex/config.toml"));
        }
    }
    Ok(PathBuf::from(env::var("HOME")?).join(".config/chatgpt2codex/config.toml"))
}

fn parse_registry_options(args: impl Iterator<Item = String>, scope: &str) -> Result<RegistryOptions, Box<dyn std::error::Error>> {
    let mut opts = RegistryOptions::default();
    let mut args = args;
    while let Some(flag) = args.next() {
        let value = args.next().ok_or("missing value for option")?;
        match flag.as_str() {
            "--config" if opts.config.is_none() => opts.config = Some(PathBuf::from(value)),
            "--id" if scope != "list" && opts.id.is_none() => opts.id = Some(value),
            "--file" if scope == "read" && opts.file.is_none() => opts.file = Some(value),
            "--scope" if scope == "read" && opts.scope.is_none() => opts.scope = Some(Scope::parse(&value)?),
            "--task" if scope == "name" && opts.task.is_none() => opts.task = Some(value),
            "--thread" if scope == "session" && opts.thread.is_none() => opts.thread = Some(value),
            "--limit" if scope == "sessions" && opts.limit.is_none() => opts.limit = Some(value.parse()?),
            "--pages" if scope == "sessions" && opts.pages.is_none() => opts.pages = Some(value.parse()?),
            _ => return Err("unknown, repeated or forbidden registry option".into()),
        }
    }
    if scope != "list" && opts.id.is_none() {
        return Err("--id is required".into());
    }
    match scope {
        "read" if opts.file.is_none() || opts.scope.is_none() => return Err("--scope and --file are required".into()),
        "name" if opts.task.is_none() => return Err("--task is required".into()),
        "session" if opts.thread.is_none() => return Err("--thread is required".into()),
        _ => (),
    }
    if !(1..=100).contains(&opts.limit.unwrap_or(25)) || !(1..=MAX_PAGES).contains(&opts.pages.unwrap_or(1)) {
        return Err("limit must be 1..100 and pages must be 1..10".into());
    }
    Ok(opts)
}

fn run_registry(command: &str, args: impl Iterator<Item = String>) -> Result<(), Box<dyn std::error::Error>> {
    let options = parse_registry_options(args, command)?;
    let config = match options.config {
        Some(path) => path,
        None => default_config_path()?,
    };
    let registry = ProjectRegistry::load(&config)?;
    if command == "list" {
        println!("project_dir={}", registry.project_dir.display());
        for project in registry.projects() {
            println!("id={} name={} root={}", project.id, project.name, project.root.display());
        }
        return Ok(());
    }
    let id = options.id.as_deref().ok_or("--id required")?;
    let project = registry.project(id)?;
    match command {
        "info" => {
            println!("id={}", project.id);
            println!("name={}", project.name);
            println!("root={}", project.root.display());
            println!("codex_name={}", project.codex_name);
            println!("name_template={}", project.name_template);
            println!("git_identity_policy={}", if project.manage_git_identity { "global" } else { "preserve" });
        }
        "contexts" => {
            for entry in registry.contexts(id)? {
                println!("scope={} path={} status={}", entry.scope.label(), entry.path.display(), entry.status);
            }
        }
        "read" => {
            let file = options.file.as_deref().ok_or("--file required")?;
            let scope = options.scope.ok_or("--scope required")?;
            print!("{}", registry.read_context(id, scope, file)?);
        }
        "name" => println!("{}", registry.preview_session_name(id, options.task.as_deref().ok_or("--task required")?)?),
        "sessions" => {
            let mut client = CodexClient::connect()?;
            let mut cursor: Option<String> = None;
            for page_number in 1..=options.pages.unwrap_or(1) {
                let page = client.list_sessions(&project.root, options.limit.unwrap_or(25), cursor.as_deref())?;
                println!("page={page_number} project_id={}", project.id);
                print_page(&page, &project.root);
                if page.next_cursor.is_none() {
                    break;
                }
                if cursor == page.next_cursor {
                    return Err("repeated pagination cursor".into());
                }
                cursor = page.next_cursor;
            }
        }
        "session" => {
            let mut client = CodexClient::connect()?;
            let info = client.read_session_metadata(&project.root, options.thread.as_deref().ok_or("--thread required")?)?;
            println!("project_id={} id={} status={} created={} updated={}", project.id, info.id, info.status, info.created_at, info.updated_at);
        }
        _ => return Err("unknown registry subcommand".into()),
    }
    Ok(())
}


#[derive(Default)]
struct WorkspaceOptions {
    config: Option<PathBuf>,
    project_dir: Option<PathBuf>,
    id: Option<String>,
    directory: Option<String>,
    git_name: Option<String>,
    git_email: Option<String>,
    codex_name: Option<String>,
    dry_run: bool,
}

fn parse_workspace_options(args: impl Iterator<Item = String>, action: &str) -> Result<WorkspaceOptions, &'static str> {
    let mut opts = WorkspaceOptions::default();
    let mut args = args;
    while let Some(flag) = args.next() {
        if flag == "--dry-run" && action == "adopt" && !opts.dry_run {
            opts.dry_run = true;
            continue;
        }
        let value = args.next().ok_or("missing workspace option value")?;
        match flag.as_str() {
            "--config" if opts.config.is_none() => opts.config = Some(PathBuf::from(value)),
            "--id" if opts.id.is_none() => opts.id = Some(value),
            "--project-dir" if action == "bootstrap" && opts.project_dir.is_none() => opts.project_dir = Some(PathBuf::from(value)),
            "--directory" if matches!(action, "bootstrap" | "adopt") && opts.directory.is_none() => opts.directory = Some(value),
            "--git-name" if action == "bootstrap" && opts.git_name.is_none() => opts.git_name = Some(value),
            "--git-email" if action == "bootstrap" && opts.git_email.is_none() => opts.git_email = Some(value),
            "--codex-name" if action == "bootstrap" && opts.codex_name.is_none() => opts.codex_name = Some(value),
            _ => return Err("unknown, duplicate or forbidden workspace option"),
        }
    }
    if opts.id.is_none() { return Err("--id required"); }
    if action == "bootstrap" && (opts.project_dir.is_none() || opts.directory.is_none()
        || opts.git_name.is_none() || opts.git_email.is_none()) {
        return Err("bootstrap requires --project-dir, --directory, --git-name and --git-email");
    }
    if action == "adopt" && opts.directory.is_none() { return Err("adopt requires --directory"); }
    Ok(opts)
}

fn run_workspace(action: &str, args: impl Iterator<Item = String>) -> Result<(), Box<dyn std::error::Error>> {
    let opts = parse_workspace_options(args, action)?;
    let config = match opts.config { Some(value) => value, None => default_config_path()? };
    let id = opts.id.ok_or("--id required")?;
    match action {
        "bootstrap" => {
            let request = BootstrapRequest {
                config_path: config.clone(),
                project_dir: opts.project_dir.ok_or("--project-dir required")?,
                directory: opts.directory.ok_or("--directory required")?,
                id: id.clone(),
                git_name: opts.git_name.ok_or("--git-name required")?,
                git_email: opts.git_email.ok_or("--git-email required")?,
                codex_name: opts.codex_name.unwrap_or_else(|| "Codex".into()),
            };
            workspace::bootstrap(&request)?;
            println!("workspace_bootstrap=ok project_id={id}");
        }
        "adopt" => {
            let request = workspace::AdoptRequest {
                config_path: config.clone(),
                id: id.clone(),
                directory: opts.directory.ok_or("--directory required")?,
            };
            let report = workspace::adopt(&request, opts.dry_run)?;
            println!("workspace_adopt={} project_id={id} root={}", if opts.dry_run { "dry_run_ok" } else { "ok" }, report.root.display());
            println!("existing_agents={} existing_context={} already_registered={} git_identity_policy=preserve",
                report.had_agents, report.had_context, report.already_registered);
            if report.had_agents || report.had_context { println!("context_review=required"); }
            if opts.dry_run { return Ok(()); }
        }
        "ensure" => {
            workspace::ensure(&config, &id)?;
            println!("workspace_ensure=ok project_id={id}");
        }
        "sync-policy" => {
            let changed = workspace::sync_policy(&config)?;
            println!("workspace_policy_sync={} project_id={id}", if changed { "updated" } else { "unchanged" });
        }
        "health" => (),
        _ => return Err("unknown workspace subcommand".into()),
    }
    let state = workspace::health(&config, &id)?;
    println!("project_id={} root={}", state.project_id, state.root.display());
    for (label, status) in &state.checks { println!("{label}={status}"); }
    for notice in &state.history_notices { println!("history_notice={notice}"); }
    println!("workspace_ready={}", state.ready());
    if !state.ready() { return Err("workspace not ready".into()); }
    Ok(())
}

#[derive(Debug, Default)]
struct ScreenOptions {
    config: Option<PathBuf>,
    id: Option<String>,
    bridge: bool,
    task: Option<String>,
    approve_start: bool,
    approve_recover: bool,
}

fn parse_screen_options(args: impl Iterator<Item = String>, action: &str) -> Result<ScreenOptions, &'static str> {
    let mut values = ScreenOptions::default();
    let mut args = args;
    while let Some(flag) = args.next() {
        match flag.as_str() {
            "--bridge" if matches!(action, "start" | "attach" | "status") && !values.bridge => values.bridge = true,
            "--approve-start" if action == "start" && !values.approve_start => values.approve_start = true,
            "--approve-recover" if action == "recover" && !values.approve_recover => values.approve_recover = true,
            "--config" if values.config.is_none() => values.config = Some(PathBuf::from(args.next().ok_or("missing config path")?)),
            "--id" if matches!(action, "start" | "attach" | "status" | "recover") && values.id.is_none() => values.id = Some(args.next().ok_or("missing project ID")?),
            "--task" if action == "start" && values.task.is_none() => values.task = Some(args.next().ok_or("missing task label")?),
            _ => return Err("unknown or repeated screen option"),
        }
    }
    match action {
        "start" | "status" | "attach" => {
            if values.bridge == values.id.is_some() { return Err("specify exactly one of --bridge or --id"); }
            if action == "start" && !values.approve_start { return Err("screen start requires --approve-start"); }
            if action != "start" && (values.task.is_some() || values.approve_start) { return Err("unexpected screen option"); }
            if values.approve_recover { return Err("unexpected recovery approval"); }
        }
        "recover" => {
            if values.bridge || values.id.is_none() { return Err("recovery requires --id; bridge slot is protected"); }
            if !values.approve_recover { return Err("screen recover requires --approve-recover"); }
            if values.task.is_some() || values.approve_start { return Err("unexpected screen option"); }
        }
        "list" | "probe" => {
            if values.bridge || values.id.is_some() || values.task.is_some() || values.approve_start || values.approve_recover {
                return Err("list/probe accepts only --config");
            }
        }
        _ => return Err("unknown screen subcommand"),
    }
    Ok(values)
}

fn print_screen_status(info: screen::Status) {
    println!("project_id={} screen_name={} state={} session_id={} task={}",
        info.project_id, info.screen_name, info.state,
        info.full_id.as_deref().unwrap_or("-"), info.task.as_deref().unwrap_or("-"));
}

fn run_screen(action: &str, args: impl Iterator<Item = String>) -> Result<(), Box<dyn std::error::Error>> {
    let opts = parse_screen_options(args, action)?;
    let config = match opts.config { Some(value) => value, None => default_config_path()? };
    if !config.is_absolute() { return Err("screen config path must be absolute".into()); }
    if action == "probe" { screen::probe()?; return Ok(()); }
    if action == "list" {
        for item in screen::list(&config)? { print_screen_status(item); }
        return Ok(());
    }
    let target = if opts.bridge { ScreenTarget::Bridge } else { ScreenTarget::Project(opts.id.as_deref().ok_or("project required")?) };
    match action {
        "start" => print_screen_status(screen::start(&config, target, opts.task.as_deref().unwrap_or(if opts.bridge { "Bridge" } else { "Codex" }))?),
        "status" => print_screen_status(screen::status(&config, target)?),
        "attach" => screen::attach(&config, target)?,
        "recover" => {
            let id = opts.id.as_deref().ok_or("--id required")?;
            let result = screen::recover(&config, id)?;
            println!("screen_recover=ok project_id={} old_session_id={} archive={} new_state=not_registered", result.project_id, result.old_session_id, result.archive_path.display());
        }
        _ => return Err("unknown screen subcommand".into()),
    }
    Ok(())
}

#[derive(Debug, Default)]
struct MultiplexerOptions {
    config: Option<PathBuf>,
    id: Option<String>,
    bridge: bool,
    mux: Option<Multiplexer>,
    task: Option<String>,
    expected: Option<String>,
    expected_ticks: Option<u64>,
    approved: bool,
    remain_on_exit: bool,
    approve_archive: bool,
    program_status: bool,
}

fn parse_multiplexer_options(action: &str, mut args: impl Iterator<Item = String>) -> Result<MultiplexerOptions, &'static str> {
    if !matches!(action, "probe" | "projects" | "prefer" | "list" | "status" | "attach" | "start" | "archive") {
        return Err("unknown session subcommand");
    }
    let mut opts = MultiplexerOptions::default();
    while let Some(flag) = args.next() {
        match flag.as_str() {
            "--config" if opts.config.is_none() => opts.config = Some(PathBuf::from(args.next().ok_or("missing config")?)),
            "--id" if matches!(action, "prefer" | "start" | "attach" | "status" | "archive") && opts.id.is_none() => opts.id = Some(args.next().ok_or("missing project")?),
            "--bridge" if matches!(action, "start" | "attach" | "status") && !opts.bridge => opts.bridge = true,
            "--multiplexer" if matches!(action, "prefer" | "start" | "attach" | "status" | "archive") && opts.mux.is_none() => opts.mux = Some(Multiplexer::parse(&args.next().ok_or("missing multiplexer")?)?),
            "--task" if action == "start" && opts.task.is_none() => opts.task = Some(args.next().ok_or("missing task")?),
            "--expect-session-id" if matches!(action, "attach" | "archive") && opts.expected.is_none() => opts.expected = Some(args.next().ok_or("missing expected identity")?),
            "--expect-process-start-ticks" if matches!(action, "attach" | "archive") && opts.expected_ticks.is_none() => opts.expected_ticks = Some(args.next().ok_or("missing process generation")?.parse().map_err(|_| "invalid process generation")?),
            "--approve-start" if action == "start" && !opts.approved => opts.approved = true,
            "--remain-on-exit" if action == "start" && !opts.remain_on_exit => opts.remain_on_exit = true,
            "--approve-archive" if action == "archive" && !opts.approve_archive => opts.approve_archive = true,
            "--program-status" if matches!(action, "list" | "status" | "start") && !opts.program_status => opts.program_status = true,
            _ => return Err("unknown or repeated session option"),
        }
    }
    if matches!(action, "prefer" | "start" | "attach" | "status" | "archive") && opts.bridge == opts.id.is_some() {
        return Err("specify exactly one of --bridge or --id");
    }
    if matches!(action, "prefer" | "attach" | "status") && opts.mux.is_none() {
        return Err("actual multiplexer required; attachment never follows project preference");
    }
    if action == "start" && !opts.approved { return Err("session start requires --approve-start"); }
    if action == "archive" && (!opts.approve_archive || opts.mux != Some(Multiplexer::Tmux) || opts.expected.is_none() || opts.expected_ticks.is_none()) {
        return Err("archive requires tmux, --approve-archive and exact expected session ID/start ticks");
    }
    Ok(opts)
}

fn print_managed_status(item: session::ManagedStatus, include_program: bool) {
    let info = item.status;
    if !include_program {
        print!("multiplexer={} generation={} ", item.multiplexer.as_str(), info.process_start_ticks.map(|n| n.to_string()).as_deref().unwrap_or("-"));
        print_screen_status(info);
        return;
    }
    let program = item.program;
    println!("multiplexer={} generation={} project_id={} screen_name={} state={} session_id={} program={} exit_code={} exit_signal={} exited_at={} task={}",
        item.multiplexer.as_str(), info.process_start_ticks.map(|n| n.to_string()).as_deref().unwrap_or("-"),
        info.project_id, info.screen_name, info.state, info.full_id.as_deref().unwrap_or("-"), program.state,
        program.exit_code.map(|n| n.to_string()).as_deref().unwrap_or("-"), program.signal.as_deref().unwrap_or("-"),
        program.exited_at.map(|n| n.to_string()).as_deref().unwrap_or("-"), info.task.as_deref().unwrap_or("-"));
}

fn run_session(action: &str, args: impl Iterator<Item = String>) -> Result<(), Box<dyn std::error::Error>> {
    let opts = parse_multiplexer_options(action, args)?;
    let config = match opts.config { Some(path) => path, None => default_config_path()? };
    if !config.is_absolute() { return Err("session config path must be absolute".into()); }
    if action == "probe" {
        for mux in [Multiplexer::Screen, Multiplexer::Tmux] {
            println!("multiplexer={} available={}", mux.as_str(), u8::from(session::available(mux)));
        }
        return Ok(());
    }
    if action == "projects" {
        for project in ProjectRegistry::load(&config)?.projects() {
            println!("project_id={} preferred={}", project.id, project.multiplexer.as_str());
        }
        return Ok(());
    }
    if action == "list" {
        for item in session::list(&config)? {
            print_managed_status(item, opts.program_status);
        }
        return Ok(());
    }
    let target = if opts.bridge { ScreenTarget::Bridge } else { ScreenTarget::Project(opts.id.as_deref().ok_or("project required")?) };
    let mux = match opts.mux { Some(mux) => mux, None => session::preferred(&config, target)? };
    match action {
        "prefer" => {
            project_preference::set(&config, opts.id.as_deref().ok_or("project required")?, mux)?;
            println!("project_id={} preferred={}", opts.id.as_deref().ok_or("project required")?, mux.as_str());
        }
        "start" | "status" => {
            if action == "start" {
                session::start_with_options(&config, mux, target, opts.task.as_deref().unwrap_or(if opts.bridge { "Bridge" } else { "Codex" }), opts.remain_on_exit)?;
            }
            print_managed_status(session::details(&config, mux, target)?, opts.program_status);
        }
        "attach" => session::attach(&config, mux, target, opts.expected.as_deref(), opts.expected_ticks)?,
        "archive" => {
            let archived = chatgpt2codex::tmux_archive::archive(&config, opts.id.as_deref().ok_or("project required")?,
                opts.expected.as_deref().ok_or("expected identity required")?, opts.expected_ticks.ok_or("expected generation required")?)?;
            println!("tmux_archive=ok project_id={} old_session_id={} archive={} new_state=not_registered", opts.id.as_deref().unwrap(), archived.session_id, archived.path.display());
        }
        _ => return Err("unknown session subcommand".into()),
    }
    Ok(())
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = env::args().skip(1);
    let group = args.next().ok_or("missing command")?;
    if matches!(group.as_str(), "--help" | "-h") {
        if args.next().is_some() { return Err("help does not accept arguments".into()); }
        usage();
        return Ok(());
    }
    if group == "session" {
        let action = args.next().ok_or("missing session subcommand")?;
        return run_session(&action, args);
    }
    if group == "screen" {
        let action = args.next().ok_or("missing screen subcommand")?;
        if !matches!(action.as_str(), "probe" | "list" | "status" | "start" | "attach" | "recover") {
            return Err("unknown screen subcommand".into());
        }
        return run_screen(&action, args);
    }
    if group == "mcp" {
        if args.next().as_deref() != Some("stdio") { return Err("expected mcp stdio".into()); }
        let mut config = None;
        let mut allow_context_read = false;
        while let Some(flag) = args.next() {
            match flag.as_str() {
                "--config" if config.is_none() => config = Some(PathBuf::from(args.next().ok_or("missing config path")?)),
                "--allow-context-read" if !allow_context_read => allow_context_read = true,
                _ => return Err("unknown or repeated MCP option".into()),
            }
        }
        return mcp::run(McpOptions { config: config.unwrap_or(default_config_path()?), allow_context_read });
    }
    if group == "workspace" {
        let subcommand = args.next().ok_or("missing workspace subcommand")?;
        if !matches!(subcommand.as_str(), "bootstrap" | "adopt" | "ensure" | "health" | "sync-policy") {
            return Err("unknown workspace subcommand".into());
        }
        return run_workspace(&subcommand, args);
    }
    if group == "projects" {
        if args.next().as_deref() != Some("list") {
            return Err("expected projects list".into());
        }
        return run_registry("list", args);
    }
    if group == "project" {
        let subcommand = args.next().ok_or("missing project subcommand")?;
        if !matches!(subcommand.as_str(), "info" | "contexts" | "read" | "name" | "sessions" | "session") {
            return Err("unknown project subcommand".into());
        }
        return run_registry(&subcommand, args);
    }
    if group != "codex" {
        usage();
        return Err("expected codex, workspace, project or projects".into());
    }
    let subcommand = args.next().ok_or("missing codex subcommand")?;
    match subcommand.as_str() {
        "diagnostics" => return run_codex_diagnostics(args),
        "probe" => {
            if args.next().is_some() {
                return Err("probe does not accept arguments".into());
            }
            let client = CodexClient::connect()?;
            println!("codex_app_server=ok platform={}", client.platform_os());
        }
        "sessions" => {
            let options = parse_options(args, false)?;
            let mut client = CodexClient::connect()?;
            let mut cursor: Option<String> = None;
            for page_number in 1..=options.pages {
                let page = client.list_sessions(&options.cwd, options.limit, cursor.as_deref())?;
                println!("page={page_number}");
                print_page(&page, &options.cwd);
                if page.next_cursor.is_none() {
                    break;
                }
                if cursor == page.next_cursor {
                    return Err("repeated pagination cursor".into());
                }
                cursor = page.next_cursor;
            }
        }
        "session" => {
            let options = parse_options(args, true)?;
            let id = options.id.ok_or("--id required")?;
            let mut client = CodexClient::connect()?;
            let info = client.read_session_metadata(&options.cwd, &id)?;
            println!("project={}", options.cwd.display());
            println!("id={} status={} created={} updated={}", info.id, info.status, info.created_at, info.updated_at);
        }
        _ => {
            usage();
            return Err("unknown codex subcommand".into());
        }
    }
    Ok(())
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            // All protocol errors are deliberately stripped of remote payload data.
            eprintln!("ERROR: {error}");
            ExitCode::FAILURE
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn workspace_requires_explicit_bootstrap_authorization_arguments() {
        assert!(parse_workspace_options(vec!["--id".into(), "gpt2codex".into()].into_iter(), "bootstrap").is_err());
        assert!(parse_workspace_options(vec!["--id".into(), "gpt2codex".into(), "--shell".into(), "yes".into()].into_iter(), "health").is_err());
        assert!(parse_workspace_options(vec!["--id".into(), "gpt2codex".into(), "--git-email".into(), "injected".into()].into_iter(), "ensure").is_err());
    }

    #[test]
    fn workspace_adopt_requires_explicit_directory_and_supports_flagged_dry_run() {
        assert!(parse_workspace_options(vec!["--id".into(), "k2-smb".into()].into_iter(), "adopt").is_err());
        let values = vec!["--id".into(), "k2-smb".into(), "--directory".into(), "k2-smb".into(), "--dry-run".into()];
        assert!(parse_workspace_options(values.into_iter(), "adopt").unwrap().dry_run);
        assert!(parse_workspace_options(vec!["--id".into(), "k2-smb".into(), "--directory".into(), "k2-smb".into(), "--git-name".into(), "oops".into()].into_iter(), "adopt").is_err());
    }

    #[test]
    fn screen_launch_requires_explicit_project_and_local_approval() {
        assert!(parse_screen_options(vec!["--id".into(), "k2-smb".into()].into_iter(), "start").is_err());
        assert!(parse_screen_options(vec!["--approve-start".into()].into_iter(), "start").is_err());
        assert!(parse_screen_options(vec!["--id".into(), "k2-smb".into(), "--bridge".into(), "--approve-start".into()].into_iter(), "start").is_err());
        assert!(parse_screen_options(vec!["--bridge".into(), "--approve-start".into()].into_iter(), "start").is_ok());
        assert!(parse_screen_options(vec!["--id".into(), "k2-smb".into(), "--approve-start".into()].into_iter(), "start").is_ok());
        assert!(parse_screen_options(vec!["--bridge".into(), "--approve-start".into()].into_iter(), "list").is_err());
        assert!(parse_screen_options(vec!["--bridge".into(), "--cmd".into(), "rm".into(), "--approve-start".into()].into_iter(), "start").is_err());
        assert!(parse_screen_options(vec!["--id".into(), "k2-smb".into()].into_iter(), "recover").is_err());
        assert!(parse_screen_options(vec!["--bridge".into(), "--approve-recover".into()].into_iter(), "recover").is_err());
        assert!(parse_screen_options(vec!["--id".into(), "k2-smb".into(), "--approve-recover".into()].into_iter(), "recover").is_ok());
        assert!(parse_screen_options(vec!["--id".into(), "k2-smb".into(), "--approve-recover".into(), "--task".into(), "oops".into()].into_iter(), "recover").is_err());
    }

    #[test]
    fn diagnostics_require_project_and_reject_unapproved_methods() {
        assert!(parse_diagnostic_options(Vec::<String>::new().into_iter()).is_err());
        assert!(parse_diagnostic_options(vec!["--id".into(), "k2-smb".into()].into_iter()).is_ok());
        assert!(parse_diagnostic_options(vec!["--id".into(), "k2-smb".into(), "--limit".into(), "26".into()].into_iter()).is_err());
        assert!(parse_diagnostic_options(vec!["--id".into(), "k2-smb".into(), "--run".into(), "true".into()].into_iter()).is_err());
        assert!(parse_diagnostic_options(vec!["--id".into(), "k2-smb".into(), "--config".into(), "relative.toml".into()].into_iter()).is_err());
    }

    #[test]
    fn options_require_explicit_cwd() {
        assert!(parse_options(Vec::<String>::new().into_iter(), false).is_err());
    }

    #[test]
    fn options_reject_unknown_fields() {
        let args = vec!["--cmd".into(), "sh".into(), "--cwd".into(), "/tmp".into()];
        assert!(parse_options(args.into_iter(), false).is_err());
    }

    #[test]
    fn registry_options_reject_unapproved_actions() {
        let args = vec!["--id".into(), "k2-smb".into(), "--exec".into(), "ls".into()];
        assert!(parse_registry_options(args.into_iter(), "sessions").is_err());
        let args = vec!["--id".into(), "k2-smb".into(), "--file".into(), "AGENTS.md".into()];
        assert!(parse_registry_options(args.into_iter(), "read").is_err());
    }

    #[test]
    fn registry_options_require_explicit_project() {
        assert!(parse_registry_options(Vec::new().into_iter(), "contexts").is_err());
    }

    #[test]
    fn options_reject_limit_over_maximum() {
        let args = vec!["--cwd".into(), "/tmp".into(), "--limit".into(), "101".into()];
        assert!(parse_options(args.into_iter(), false).is_err());
    }
    #[test]
    fn multiplexer_start_and_attachment_are_explicit() {
        let args = |items: &[&str]| items.iter().map(|s| s.to_string()).collect::<Vec<_>>().into_iter();
        assert!(parse_multiplexer_options("start", args(&["--id", "demo", "--multiplexer", "tmux"])).is_err());
        assert!(parse_multiplexer_options("start", args(&["--id", "demo", "--multiplexer", "tmux", "--approve-start"])).is_ok());
        assert!(parse_multiplexer_options("start", args(&["--id", "demo", "--approve-start", "--cmd", "sh"])).is_err());
        assert!(parse_multiplexer_options("attach", args(&["--id", "demo"])).is_err());
        assert!(parse_multiplexer_options("attach", args(&["--id", "demo", "--multiplexer", "screen", "--expect-session-id", "123.g2c-demo"])).is_ok());
        assert!(parse_multiplexer_options("prefer", args(&["--bridge", "--multiplexer", "tmux"])).is_err());
        assert!(parse_multiplexer_options("prefer", args(&["--id", "demo", "--multiplexer", "tmux"])).is_ok());
        assert!(parse_multiplexer_options("list", args(&["--multiplexer", "tmux"])).is_err());
        assert!(parse_multiplexer_options("list", args(&["--program-status"])).is_ok());
        assert!(parse_multiplexer_options("start", args(&["--id", "demo", "--multiplexer", "tmux", "--remain-on-exit", "--approve-start"])).is_ok());
        let valid = ["--id", "demo", "--multiplexer", "tmux", "--expect-session-id", "123.$0.12345", "--expect-process-start-ticks", "123", "--approve-archive"];
        assert!(parse_multiplexer_options("archive", args(&valid)).is_ok());
        for length in [0, 4, 6, 8] { assert!(parse_multiplexer_options("archive", args(&valid[..length])).is_err()); }
        assert!(parse_multiplexer_options("archive", args(&["--bridge", "--approve-archive"])).is_err());
        assert!(parse_multiplexer_options("archive", args(&["--id", "demo", "--multiplexer", "screen", "--approve-archive"])).is_err());
    }
}
