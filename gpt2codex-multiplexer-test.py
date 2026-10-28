#!/usr/bin/env python3
"""Isolated CLI/PTY regression: synthetic codex stub, never the real Codex.

All registry/HOME/socket paths belong to a new fixture under .tmp. GNU screen
uses a private SCREENDIR; tmux uses the bridge's private per-project socket.
Only default-prefix detach is sent to our own attached clients. Lifecycle mode
may close a verified fixture session containing an exited synthetic program.
No user-session commands, screen -X/-d/-D, transcript or environment dumps.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import shlex
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import termios
import time


ROOT = Path(__file__).resolve().parent
BIN = ROOT / "target/release/gpt2codex"


def write(path, data, mode=0o600):
    path.write_text(data)
    path.chmod(mode)


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("fixture deadline exceeded")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tmux", type=Path, help="Optional test-only tmux binary; no installation")
    parser.add_argument("--library-path", type=Path, help="Optional private runtime libraries for that binary")
    parser.add_argument("--backends", action="store_true", help="Also test both native GUI backends offscreen")
    parser.add_argument("--lifecycle", action="store_true", help="Test retained panes and guarded archival")
    parser.add_argument("--gui-build", action="store_true", help="Run the existing GUI build helper and CTest with isolated config")
    args = parser.parse_args()
    os.umask(0o077)
    assert (ROOT / ".tmp").is_dir() and (ROOT / ".log").is_dir()
    screen = shutil.which("screen")
    tmux = str(args.tmux.resolve()) if args.tmux else shutil.which("tmux")
    git = shutil.which("git")
    assert screen and git and BIN.is_file(), "build CLI and provide screen/git first"
    fixture = Path(tempfile.mkdtemp(prefix="mux-", dir=ROOT / ".tmp")).resolve()
    # No outputs from the real user's sessions or configuration enter this log.
    logs = Path(tempfile.mkdtemp(prefix="multiplexer-", dir=ROOT / ".log")).resolve()
    results = []
    owned_work = []
    clients = []
    retained = []
    try:
        for name in ["h", "s", "c/projects", "bin", "sockets", "runtime", "repos/demo", "repos/other", "repos/bridge"]:
            (fixture / name).mkdir(parents=True, mode=0o700)
        write(fixture / "fixture.marker", "gpt2codex-isolated-multiplexer-v1\n")
        # Never inherit SCREENDIR/TMUX/Codex credentials/config from the caller.
        env = {"HOME": str(fixture / "h"), "PATH": str(fixture / "bin"),
               "XDG_STATE_HOME": str(fixture / "s"), "XDG_CONFIG_HOME": str(fixture / "c"),
               "XDG_RUNTIME_DIR": str(fixture / "runtime"), "SCREENDIR": str(fixture / "sockets"),
               "SCREENRC": str(fixture / "screenrc"), "SYSSCREENRC": str(fixture / "screenrc"),
               "TERM": "xterm-256color", "COLORTERM": "truecolor", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
               "SHELL": "/bin/bash", "G2C_FIXTURE": str(fixture)}
        write(fixture / "screenrc", "startup_message off\nvbell off\n")
        for name, source in [("screen", screen), ("git", git)]:
            (fixture / "bin" / name).symlink_to(source)
        if tmux:
            library = f"export LD_LIBRARY_PATH={shlex.quote(str(args.library_path.resolve()))}\n" if args.library_path else ""
            write(fixture / "bin/tmux", f"#!/bin/sh\n{library}exec {shlex.quote(tmux)} \"$@\"\n", 0o700)
        # The executable named codex is entirely synthetic and fixture-local.
        write(fixture / "bin/codex", f"#!{sys.executable}\n" + r'''
import os, pathlib, time
root = pathlib.Path(os.environ["G2C_FIXTURE"])
assert (root / "fixture.marker").read_text() == "gpt2codex-isolated-multiplexer-v1\n"
kind = "tmux" if "TMUX" in os.environ else "screen"
import json
term = os.environ.get("TERM", "")
safe_term = term if term in {"screen", "screen-256color", "tmux-256color", "xterm-256color"} else "other"
(root / ("term-" + kind + ".json")).write_text(json.dumps({"term": safe_term, "utf8_locale": os.environ.get("LC_ALL", "").upper().endswith("UTF-8")}))
with (root / "starts").open("a") as f: f.write(kind + "\n")
deadline = time.monotonic() + 120
while time.monotonic() < deadline and not (root / "stop").exists():
    os.write(1, b"\x1b[?25l\x1b[2J\x1b[H\x1b[33mSYNTHETIC ANSI YELLOW\x1b[0m\r\nNormal text\r\n\x1b[31mRED\x1b[32m GREEN\x1b[34m BLUE\x1b[0m\r\n")
    if kind == "tmux" and (root / "stop-tmux").exists(): break
    time.sleep(.2)
if kind == "tmux" and (root / "signal-tmux").exists():
    import signal
    os.kill(os.getpid(), signal.SIGTERM) # Only this fixture process.
if kind == "tmux" and (root / "exit-code").exists():
    raise SystemExit(int((root / "exit-code").read_text()))
''', 0o700)
        literal_program = fixture / "codex fixture;literal"
        (fixture / "bin/codex").rename(literal_program)
        (fixture / "bin/codex").symlink_to(literal_program)

        def run(*arguments, ok=True, extra_env=None):
            child_env = dict(env, **(extra_env or {}))
            if arguments[:2] == ("session", "status"):
                arguments = (*arguments, "--program-status")
            completed = subprocess.run([str(BIN), *arguments, "--config", str(fixture / "c/config.toml")],
                                       env=child_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
            if completed.returncode and ok and arguments[:2] == ("session", "start") and tmux:
                socket_path = fixture / f"s/gpt2codex/screen-sessions/tmux-sockets/{project_id}.sock"
                metadata = subprocess.run([str(fixture / "bin/tmux"), "-S", str(socket_path), "-N", "list-sessions", "-F",
                    "#{pid}\t#{session_id}\t#{session_created}\t#{session_name}\t#{session_attached}"],
                    env=dict(env, LC_ALL="C"), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=3).stdout
                # Only fixed-format metadata from our synthetic private server.
                (logs / "fixture-identity.txt").write_bytes(metadata)
                print(f"FIXTURE_METADATA={logs / 'fixture-identity.txt'}", flush=True)
            assert (completed.returncode == 0) == ok, f"unexpected CLI result: {arguments[:2]}: {completed.stderr.decode(errors='replace')[:160]}"
            return completed.stdout.decode()

        def check(name, condition):
            assert condition, name
            results.append(name)

        def close_own_exited_session(path, rec):
            assert path.parent == fixture / "s/gpt2codex/screen-sessions"
            assert json.loads(path.read_bytes())["full_id"] == rec["full_id"]
            owned_socket = path.parent / f'tmux-sockets/{rec["project_id"]}.sock'
            assert owned_socket.stat().st_ino == rec["tmux"]["socket_ino"]
            # Reject accidental cleanup against a running synthetic program too.
            assert "program=exited" in run("session", "status", "--id", rec["project_id"], "--multiplexer", "tmux")
            subprocess.run([str(fixture / "bin/tmux"), "-S", str(owned_socket), "-N", "kill-session", "-t", rec["tmux"]["session_id"]], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=True)

        subprocess.run([git, "init", "-q", str(fixture / "repos/demo")], env=env, check=True)
        subprocess.run([git, "init", "-q", str(fixture / "repos/other")], env=env, check=True)
        subprocess.run([git, "init", "-q", str(fixture / "repos/bridge")], env=env, check=True)
        project_id = "m" + fixture.name[-8:]
        assert not Path("/tmp", project_id).exists(), "refuse colliding workspace ID"
        run("workspace", "bootstrap", "--project-dir", str(fixture / "repos"), "--id", project_id,
            "--directory", "demo", "--git-name", "Fixture", "--git-email", "fixture@example.invalid")
        project_work = Path("/tmp", project_id)
        owned_work.append((project_work, project_work.stat().st_ino))
        # Bridge is listed read-only, never started; no use of /tmp/gpt2codex.
        write(fixture / "c/projects/gpt2codex.toml", "[project]\nid='gpt2codex'\ndirectory='bridge'\n")
        if args.gui_build:
            gui_config = fixture / "gui-config"
            shutil.copytree(fixture / "c", gui_config / "chatgpt2codex")
            build_env = dict(env, PATH=os.environ["PATH"], XDG_CONFIG_HOME=str(gui_config),
                QT_QPA_PLATFORMTHEME="generic", QT_QPA_PLATFORM="offscreen", GIT_OPTIONAL_LOCKS="0")
            build = subprocess.run(["bash", "./gpt2codex-p0ic-qt6-test-v2.sh"], cwd=ROOT,
                env=build_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
            (logs / "gui-build-driver.log").write_bytes(build.stdout)
            assert build.returncode == 0, f"GUI build failed; inspect {logs}"
            import re
            log_path = Path(re.search(rb"DETAILS=(.+)", build.stdout)[1].decode())
            build_dir = re.search(r"Build files have been written to: (.+)", log_path.read_text())[1]
            with (logs / "gui-ctest.log").open("w") as out:
                tested = subprocess.run(["ctest", "--test-dir", build_dir, "--output-on-failure"],
                    env=build_env, stdout=out, stderr=subprocess.STDOUT, timeout=45)
            check("isolated_gui_release_build_and_ctest", tested.returncode == 0)
        check("legacy_config_defaults_to_screen", f"project_id={project_id} preferred=screen" in run("session", "projects"))
        run("session", "start", "--id", project_id, "--multiplexer", "screen", ok=False)
        check("approval_required_no_process", not (fixture / "starts").exists())
        other_id = project_id + "o"
        assert not Path("/tmp", other_id).exists()
        run("workspace", "bootstrap", "--project-dir", str(fixture / "repos"), "--id", other_id,
            "--directory", "other", "--git-name", "Fixture", "--git-email", "fixture@example.invalid")
        other_work = Path("/tmp", other_id)
        owned_work.append((other_work, other_work.stat().st_ino))
        run("screen", "start", "--id", project_id, "--task", "Synthetic fixture", "--approve-start")
        run("screen", "start", "--id", other_id, "--task", "Other project fixture", "--approve-start")
        wait_for(lambda: (fixture / "starts").exists() and (fixture / "starts").read_text().count("screen") == 2)
        state = fixture / "s/gpt2codex/screen-sessions"
        screen_record = state / f"{project_id}.json"
        legacy = screen_record.read_bytes()
        other_record = state / f"{other_id}.json"
        other_original = other_record.read_bytes()
        original = json.loads(legacy)
        check("legacy_record_unchanged_format", "multiplexer" not in original)
        full = original["full_id"]
        starts = (fixture / "starts").read_bytes()
        run("session", "prefer", "--id", project_id, "--multiplexer", "tmux")
        check("preference_keeps_screen_record_and_processes", screen_record.read_bytes() == legacy and (fixture / "starts").read_bytes() == starts)
        check("screen_still_attachable", "state=detached" in run("session", "status", "--id", project_id, "--multiplexer", "screen"))
        check("fresh_process_keeps_actual_identity", f"session_id={full}" in run("session", "list"))
        run("session", "attach", "--id", project_id, "--multiplexer", "screen", "--expect-session-id", "1.g2c-wrong", ok=False)
        run("session", "attach", "--id", project_id, "--multiplexer", "screen", "--expect-session-id", full,
            "--expect-process-start-ticks", str(original["process_start_ticks"] + 1), ok=False)
        check("screen_reconnect_rejects_replacement", screen_record.read_bytes() == legacy)

        def attach_detach(mux, identity, prefix, finish_program=False):
            record_path = state / f"{project_id}{'.tmux' if mux == 'tmux' else ''}.json"
            generation = str(json.loads(record_path.read_bytes())["process_start_ticks"])
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 28, 90, 0, 0))
            def controlling_tty():
                os.setsid()
                fcntl.ioctl(0, termios.TIOCSCTTY, 0)
            client = subprocess.Popen([str(BIN), "session", "attach", "--id", project_id,
                "--multiplexer", mux, "--expect-session-id", identity, "--expect-process-start-ticks", generation,
                "--config", str(fixture / "c/config.toml")],
                env=env, stdin=slave, stdout=slave, stderr=slave, preexec_fn=controlling_tty)
            os.close(slave)
            clients.append((client, master))
            received = bytearray()
            def visible():
                readable, _, _ = select.select([master], [], [], .1)
                if readable:
                    received.extend(os.read(master, 65536))
                return b"SYNTHETIC ANSI YELLOW" in received
            wait_for(visible)
            # Send only the default detach sequence to this fixture client.
            if finish_program: write(fixture / "stop-tmux", "synthetic exit while attached\n")
            else: os.write(master, prefix + b"d")
            # Keep draining the PTY while waiting: tmux flushes its pending
            # redraw/exit output before disconnecting. A wait without reads
            # can fill the PTY and block an otherwise successful detach.
            def client_finished():
                if client.poll() is not None: return True
                readable, _, _ = select.select([master], [], [], .1)
                if readable:
                    try: os.read(master, 65536) # Discard synthetic bytes, never log.
                    except OSError: pass # Slave closed (EIO).
                return client.poll() is not None
            wait_for(client_finished)
            assert client.wait(timeout=1) == 0
            os.close(master)
            clients.remove((client, master))
            if finish_program:
                wait_for(lambda: "state=interrupted" in run("session", "status", "--id", project_id, "--multiplexer", mux))
                check("last_program_exit_while_attached_closes_default_server", True)
            else:
                check(mux + "_attach_default_detach_preserves_server", "state=detached" in run("session", "status", "--id", project_id, "--multiplexer", mux))
            # Raw terminal bytes are intentionally never written to logs.

        attach_detach("screen", full, b"\x01")
        attach_detach("screen", full, b"\x01")
        check("screen_reconnect_no_duplicate", (fixture / "starts").read_bytes() == starts)
        if tmux:
            # Explicitly approves only the synthetic, fixture-local executable.
            # Uses the saved project preference, still with explicit approval.
            run("session", "start", "--id", project_id, "--approve-start")
            wait_for(lambda: (fixture / "starts").read_text().count("tmux") == 1)
            check("tmux_tui_preserves_utf8_locale", json.loads((fixture / "term-tmux.json").read_text())["utf8_locale"])
            tmux_record = state / f"{project_id}.tmux.json"
            tmux_original = tmux_record.read_bytes()
            record = json.loads(tmux_original)
            check("tmux_has_distinct_durable_identity", record["multiplexer"] == "tmux" and record["full_id"] != full and screen_record.read_bytes() == legacy)
            run("session", "start", "--id", project_id, "--multiplexer", "tmux", "--approve-start", ok=False)
            check("tmux_slot_cannot_overwrite_existing_slot", tmux_record.read_bytes() == tmux_original)
            attach_detach("tmux", record["full_id"], b"\x02")
            attach_detach("tmux", record["full_id"], b"\x02")
            old_record = dict(record)
            old_record.pop("tmux_lifecycle", None)
            write(tmux_record, json.dumps(old_record))
            check("legacy_tmux_identity_remains_attachable", "program=unknown" in run("session", "status", "--id", project_id, "--multiplexer", "tmux"))
            attach_detach("tmux", record["full_id"], b"\x02")
            tmux_record.write_bytes(tmux_original)
            check("tmux_reconnect_no_duplicate", (fixture / "starts").read_text().splitlines() == ["screen", "screen", "tmux"])
            # A socket without a registered identity is never adopted.
            occupied_path = state / f"tmux-sockets/{other_id}.sock"
            with socket.socket(socket.AF_UNIX) as occupied:
                occupied.bind(str(occupied_path))
                run("session", "start", "--id", other_id, "--multiplexer", "tmux", "--approve-start", ok=False)
            occupied_path.unlink()
            check("foreign_socket_not_adopted", not (state / f"{other_id}.tmux.json").exists())
            run("session", "prefer", "--id", project_id, "--multiplexer", "screen")
            check("switch_back_keeps_both_identities", screen_record.read_bytes() == legacy and tmux_record.read_bytes() == tmux_original)
            # Same socket and process but a changed recorded tmux session must fail closed.
            record["tmux"]["session_id"] = "$999999"
            record["full_id"] = f'{record["pid"]}.$999999.{record["tmux"]["created"]}'
            write(tmux_record, json.dumps(record))
            check("tmux_replacement_is_unconfirmed", "state=unconfirmed" in run("session", "status", "--id", project_id, "--multiplexer", "tmux"))
            run("session", "attach", "--id", project_id, "--multiplexer", "tmux", ok=False)
            tmux_record.write_bytes(tmux_original)
            record = json.loads(tmux_original)
            record["tmux"]["socket_ino"] += 1
            write(tmux_record, json.dumps(record))
            check("tmux_socket_identity_mismatch_blocks_attach", "state=unconfirmed" in run("session", "status", "--id", project_id, "--multiplexer", "tmux"))
            run("session", "attach", "--id", project_id, "--multiplexer", "tmux", ok=False)
            tmux_record.write_bytes(tmux_original)
            (fixture / "bin/tmux").rename(fixture / "bin/tmux.disabled")
            check("missing_tmux_preserves_screen_listing", f"session_id={full}" in run("session", "list"))
            check("missing_tmux_disabled_probe", "multiplexer=tmux available=0" in run("session", "probe"))
            run("session", "attach", "--id", project_id, "--multiplexer", "tmux", ok=False)
            attach_detach("screen", full, b"\x01")
            (fixture / "bin/tmux.disabled").rename(fixture / "bin/tmux")
            check("unavailable_tmux_never_falls_back", screen_record.read_bytes() == legacy and (fixture / "starts").read_text().splitlines() == ["screen", "screen", "tmux"])
            (fixture / "bin/screen").rename(fixture / "bin/screen.disabled")
            check("missing_screen_does_not_hide_tmux", f'session_id={json.loads(tmux_original)["full_id"]}' in run("session", "list"))
            (fixture / "bin/screen.disabled").rename(fixture / "bin/screen")
        else:
            run("session", "start", "--id", project_id, "--approve-start", ok=False)
            check("missing_preferred_tmux_never_starts_screen", screen_record.read_bytes() == legacy and not (state / f"{project_id}.tmux.json").exists())
            results.append("SKIP real_tmux_not_available")
        if args.backends:
            for mux in (["screen", "tmux"] if tmux else ["screen"]):
                for backend in ["konsole", "qtermwidget"]:
                    extra = {"QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "generic",
                        "G2C_MUX_FIXTURE": str(fixture), "G2C_MUX_CONFIG": str(fixture / "c/config.toml"),
                        "G2C_MUX_PROJECT": project_id, "G2C_MUX": mux, "G2C_MUX_BACKEND": backend,
                        "G2C_MUX_IDENTITY": full if mux == "screen" else json.loads(tmux_original)["full_id"]}
                    with (logs / f"{mux}-{backend}.log").open("w") as out:
                        cp = subprocess.run([str(ROOT / "target/release/gpt2codex-backend-tests"), "managedMultiplexerAttachment"],
                            env=dict(env, **extra), stdout=out, stderr=subprocess.STDOUT, timeout=20)
                    check(f"{mux}_{backend}_ansi_resize_attach", cp.returncode == 0)
        check("all_actions_preserve_screen_identity", screen_record.read_bytes() == legacy and "state=detached" in run("screen", "status", "--id", project_id))
        if tmux:
            check("gui_detach_keeps_tmux_running", "state=detached" in run("session", "status", "--id", project_id, "--multiplexer", "tmux"))
        check("other_project_screen_unaffected", other_record.read_bytes() == other_original and "state=detached" in run("screen", "status", "--id", other_id))
        check("no_unapproved_extra_process", (fixture / "starts").read_text().splitlines() == (["screen", "screen", "tmux"] if tmux else ["screen", "screen"]))
        if args.lifecycle:
            assert tmux, "lifecycle regression requires an available tmux"
            def archive_args(rec):
                return ("session", "archive", "--id", project_id, "--multiplexer", "tmux",
                    "--expect-session-id", rec["full_id"], "--expect-process-start-ticks", str(rec["process_start_ticks"]))
            original_live = tmux_record.read_bytes()
            rec = json.loads(original_live)
            run(*archive_args(rec), ok=False)
            run(*archive_args(rec), "--approve-archive", ok=False)
            check("archive_requires_approval_and_refuses_live_server", tmux_record.read_bytes() == original_live)
            write(fixture / "stop-tmux", "synthetic exit\n")
            wait_for(lambda: "state=interrupted" in run("session", "status", "--id", project_id, "--multiplexer", "tmux"))
            check("default_last_program_exit_interrupts_server", screen_record.read_bytes() == legacy)
            run(*archive_args(rec), "--approve-start", ok=False)
            wrong = dict(rec, full_id="1.$0.1")
            run(*archive_args(wrong), "--approve-archive", ok=False)
            wrong_generation = dict(rec, process_start_ticks=rec["process_start_ticks"] + 1)
            run(*archive_args(wrong_generation), "--approve-archive", ok=False)
            run("session", "archive", "--id", other_id, "--multiplexer", "tmux", "--expect-session-id", rec["full_id"],
                "--expect-process-start-ticks", str(rec["process_start_ticks"]), "--approve-archive", ok=False)
            check("archive_approval_is_bound_to_project_and_generation", tmux_record.read_bytes() == original_live and other_record.read_bytes() == other_original)
            saved_record = tmux_record.with_suffix(".saved")
            tmux_record.rename(saved_record)
            tmux_record.symlink_to(saved_record)
            run(*archive_args(rec), "--approve-archive", ok=False)
            tmux_record.unlink(); saved_record.rename(tmux_record)
            check("archive_refuses_symlink_record", tmux_record.read_bytes() == original_live)
            # Namespace uncertainty and legacy records cannot authorize deletion.
            changed = json.loads(original_live)
            changed["tmux_lifecycle"]["pid_namespace"] += 1
            write(tmux_record, json.dumps(changed))
            run(*archive_args(rec), "--approve-archive", ok=False)
            changed.pop("tmux_lifecycle")
            write(tmux_record, json.dumps(changed))
            run(*archive_args(rec), "--approve-archive", ok=False)
            tmux_record.write_bytes(original_live)
            check("archive_refuses_namespace_mismatch_and_legacy_provenance", tmux_record.read_bytes() == original_live)
            sock = state / f"tmux-sockets/{project_id}.sock"
            saved = sock.with_suffix(".saved")
            sock.rename(saved)
            with socket.socket(socket.AF_UNIX) as foreign:
                foreign.bind(str(sock)); foreign.listen(1)
                run(*archive_args(rec), "--approve-archive", ok=False)
            sock.unlink(); saved.rename(sock)
            check("archive_refuses_replaced_socket", tmux_record.read_bytes() == original_live)
            destination = state / f'.archived-tmux-{project_id}-{rec["pid"]}-{rec["process_start_ticks"]}-{rec["tmux"]["created"]}'
            destination.mkdir()
            run(*archive_args(rec), "--approve-archive", ok=False)
            destination.rmdir()
            check("archive_never_overwrites_existing_evidence", tmux_record.read_bytes() == original_live)
            before = (fixture / "starts").read_bytes()
            run(*archive_args(rec), "--approve-archive")
            check("archive_preserves_exact_record_and_snapshot", (destination / "record.json").read_bytes() == original_live and (destination / "record.snapshot.json").read_bytes() == original_live)
            check("archive_preserves_socket_identity", (destination / "socket").stat().st_ino == rec["tmux"]["socket_ino"])
            check("archive_is_private_and_records_diagnostics", destination.stat().st_mode & 0o777 == 0o700 and json.loads((destination / "diagnostics.json").read_text())["session_id"] == rec["full_id"])
            check("archive_frees_only_tmux_slot_without_start", not tmux_record.exists() and screen_record.read_bytes() == legacy and other_record.read_bytes() == other_original and (fixture / "starts").read_bytes() == before)
            run(*archive_args(rec), "--approve-archive", ok=False)
            run("session", "start", "--id", project_id, "--multiplexer", "tmux", "--remain-on-exit", ok=False)
            # A fast exit must be retained from the very first instruction.
            write(fixture / "exit-code", "23")
            run("session", "start", "--id", project_id, "--multiplexer", "tmux", "--remain-on-exit", "--approve-start")
            newer = json.loads(tmux_record.read_bytes())
            retained.append((tmux_record, newer))
            wait_for(lambda: "program=exited exit_code=23" in run("session", "status", "--id", project_id, "--multiplexer", "tmux"))
            check("remain_on_exit_applies_before_fast_program_exit", newer["tmux_lifecycle"]["remain_on_exit"] and newer["full_id"] != rec["full_id"])
            count = (fixture / "starts").read_bytes()
            attach_detach("tmux", newer["full_id"], b"\x02")
            for _ in range(3): run("session", "status", "--id", project_id, "--multiplexer", "tmux")
            check("dead_pane_reconnect_never_restarts_codex", (fixture / "starts").read_bytes() == count)
            run(*archive_args(newer), "--approve-archive", ok=False)
            check("dead_program_is_not_dead_server_for_archive", "state=detached" in run("session", "status", "--id", project_id, "--multiplexer", "tmux"))
            check("original_archive_survives_new_start", (destination / "record.json").read_bytes() == original_live)
            if args.backends:
                for backend in ["konsole", "qtermwidget"]:
                    extra = {"QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "generic",
                        "G2C_MUX_FIXTURE": str(fixture), "G2C_MUX_CONFIG": str(fixture / "c/config.toml"),
                        "G2C_MUX_PROJECT": project_id, "G2C_MUX": "tmux", "G2C_MUX_BACKEND": backend,
                        "G2C_MUX_IDENTITY": newer["full_id"]}
                    with (logs / f"dead-tmux-{backend}.log").open("w") as out:
                        cp = subprocess.run([str(ROOT / "target/release/gpt2codex-backend-tests"), "managedMultiplexerAttachment"],
                            env=dict(env, **extra), stdout=out, stderr=subprocess.STDOUT, timeout=20)
                    check(f"dead_tmux_{backend}_reconnect_and_resize", cp.returncode == 0)
            # The legacy listing stays byte compatible for a running older GUI.
            old_listing = run("session", "list")
            new_listing = run("session", "list", "--program-status")
            check("program_metadata_is_opt_in_and_legacy_listing_survives", " program=" not in old_listing and "program=exited exit_code=23" in new_listing)
            close_own_exited_session(tmux_record, newer)
            retained.remove((tmux_record, newer))
            wait_for(lambda: "state=interrupted" in run("session", "status", "--id", project_id, "--multiplexer", "tmux"))
            run(*archive_args(newer), "--approve-archive")
            (fixture / "stop-tmux").unlink()
            (fixture / "exit-code").unlink()
            run("session", "start", "--id", project_id, "--multiplexer", "tmux", "--approve-start")
            third = json.loads(tmux_record.read_bytes())
            check("new_start_requires_separate_approval_and_new_identity", third["full_id"] not in {rec["full_id"], newer["full_id"]})
            attach_detach("tmux", third["full_id"], b"\x02", finish_program=True)
            missing_socket = state / f"tmux-sockets/{project_id}.sock"
            missing_socket.rename(fixture / "inactive-third-socket")
            run(*archive_args(third), "--approve-archive")
            third_archive = state / f'.archived-tmux-{project_id}-{third["pid"]}-{third["process_start_ticks"]}-{third["tmux"]["created"]}'
            check("archive_handles_proven_missing_socket", not json.loads((third_archive / "diagnostics.json").read_text())["socket"]["present"])
            write(fixture / "signal-tmux", "self TERM\n")
            run("session", "start", "--id", project_id, "--multiplexer", "tmux", "--remain-on-exit", "--approve-start")
            fourth = json.loads(tmux_record.read_bytes())
            retained.append((tmux_record, fourth))
            import re
            signal_status = run("session", "status", "--id", project_id, "--multiplexer", "tmux")
            (logs / "retained-signal-status.txt").write_text(signal_status) # Synthetic metadata only.
            wait_for(lambda: re.search(r"program=exited exit_code=- exit_signal=(?:(?:SIG)?TERM|15)(?: |$)", run("session", "status", "--id", project_id, "--multiplexer", "tmux")))
            check("retained_signal_exit_is_distinct_from_server_death", "state=detached" in run("session", "status", "--id", project_id, "--multiplexer", "tmux"))
            check("screen_projects_remain_unchanged_after_all_archives", screen_record.read_bytes() == legacy and other_record.read_bytes() == other_original and "state=detached" in run("screen", "status", "--id", other_id))
        report = {"passed": results, "tmux_tested": bool(tmux), "real_codex_started": 0,
                  "live_user_sessions_accessed": 0, "backend_tests": args.backends,
                  "fixture_terminal": {kind: json.loads(path.read_text()) for kind in ["screen", "tmux"] if (path := fixture / f"term-{kind}.json").exists()}}
    finally:
        # The synthetic programs exit themselves; never kill/detach a server.
        write(fixture / "stop", "stop fixture\n")
        for path, rec in retained:
            # Only fixture-owned, identity-checked servers with exited synthetic
            # programs. Never reach the user's default socket or a live Codex.
            close_own_exited_session(path, rec)
        for client, master in clients:
            try:
                client.wait(timeout=5)
            finally:
                os.close(master)
        if (fixture / "starts").exists():
            wait_for(lambda: not list((fixture / "sockets").iterdir()), timeout=6)
            def server_alive(record):
                try:
                    stat = Path(f'/proc/{record["pid"]}/stat').read_text().rsplit(") ", 1)[1].split()
                    return stat[0] != "Z" and int(stat[19]) == record["process_start_ticks"]
                except FileNotFoundError:
                    return False
            state = fixture / "s/gpt2codex/screen-sessions"
            records = [json.loads(path.read_text()) for path in state.glob("*.json")]
            wait_for(lambda: not any(server_alive(record) for record in records if record.get("pid")), timeout=6)
        # Owned fixture sockets may remain as stale tmux filesystem entries;
        # TemporaryDirectory-style cleanup never contacts a live server.
        for work, inode in owned_work:
            if work.is_dir() and work.stat().st_ino == inode:
                assert {p.name for p in work.iterdir()} <= {"tmp", "log"}
                shutil.rmtree(work)
        shutil.rmtree(fixture)
    report["fixture_servers_exited"] = True
    (logs / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"MULTIPLEXER_TEST=PASS checks={len(results)} logs={logs}")


if __name__ == "__main__":
    main()
