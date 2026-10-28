#!/usr/bin/env python3
"""Phase A only: isolated synthetic screen/PTY diagnostics; never use live slots."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pty
import re
import select
import shutil
import struct
import stat
import subprocess
import sys
import tempfile
import termios
import time
import threading

REPO = Path(__file__).resolve().parent
MARKER = "gpt2codex-synthetic-terminal-v1\n"


def terminal_metadata():
    result = {}
    for key in ("TERM", "COLORTERM", "TERM_PROGRAM", "TERM_PROGRAM_VERSION", "COLUMNS", "LINES"):
        value = os.environ.get(key, "")
        if key == "TERM":
            safe = re.fullmatch(r"(?:xterm|screen|tmux|vt100|linux|konsole)(?:[-.][a-zA-Z0-9-]+)*", value)
        elif key == "COLORTERM":
            safe = value in ("truecolor", "24bit")
        elif key == "TERM_PROGRAM":
            safe = value in ("konsole", "kitty", "vscode", "WezTerm", "Apple_Terminal")
        else:
            safe = re.fullmatch(r"[0-9.]{1,20}", value)
        result[key] = value if safe else ("other" if value else "unset")
    return result


def fixture_root(value):
    root = Path(value).resolve(strict=True)
    if root.parent != (REPO / ".tmp").resolve() or not root.name.startswith("terminal-fixture-"):
        raise ValueError("not an owned diagnostic fixture")
    if (root / "marker").read_text() != MARKER:
        raise ValueError("invalid fixture marker")
    sockets = root / "sockets"
    if sockets.is_symlink() or sockets.resolve().parent != root:
        raise ValueError("unsafe diagnostic socket directory")
    return root


def frame(root):
    root = fixture_root(root)
    deadline = time.monotonic() + 30
    previous = None
    samples = []
    # This process only produces fixed synthetic output, never reads input.
    sys.stdout.write("\033[?1049h\033[?25l")
    try:
        while time.monotonic() < deadline and not (root / "stop").exists():
            size = os.get_terminal_size(sys.stdout.fileno())
            if size != previous:
                previous = size
                samples.append({"rows": size.lines, "columns": size.columns})
                (root / "screen-env.json").write_text(json.dumps({"terminal": terminal_metadata(), "sizes": samples}))
                text = "\033[0m\033[H\033[2JG2C SYNTHETIC ANSI — no Codex, no private content\r\n"
                for color in range(30, 38):
                    text += f"\033[{color}mANSI {color}: ABC 0123\033[0m\r\n"
                text += "\033[33;4mYellow underline\033[0m\r\n"
                text += "\033[33m┌─────────┐ │ 漢字 😀\033[0m\r\nreset: plain text\r\n"
                sys.stdout.write(text)
                sys.stdout.flush()
            time.sleep(0.05)
    finally:
        sys.stdout.write("\033[0m\033[?25h\033[?1049l")
        sys.stdout.flush()


def attach(root, full_id):
    root = fixture_root(root)
    if not re.fullmatch(r"[1-9][0-9]*\.g2c-diag", full_id):
        raise ValueError("invalid isolated session ID")
    socket_info = (root / "sockets" / full_id).lstat()
    if not stat.S_ISSOCK(socket_info.st_mode) or socket_info.st_uid != os.getuid():
        raise ValueError("not an owned fixture socket")
    (root / "attach-env.json").write_text(json.dumps(terminal_metadata()))
    environment = os.environ.copy()
    environment["SCREENDIR"] = str(root / "sockets")
    environment["SCREENRC"] = str(root / "screenrc")
    environment["SYSSCREENRC"] = str(root / "screenrc")
    environment.pop("STY", None)
    environment.pop("TMUX", None)
    # Like the Rust CLI, wait for an ordinary child screen attach; never -d/-D.
    flag = "-x" if (root / "shared").exists() else "-r"
    return subprocess.call(["/usr/bin/screen", flag, full_id], env=environment)


def start_reference(root, full_id):
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 28, 90, 0, 0))
    def child_tty():
        os.setsid()
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    env = os.environ.copy()
    env["TERM"] = "xterm-256color"
    env["COLORTERM"] = "truecolor"
    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--attach-fixture", str(root), full_id],
        stdin=slave, stdout=slave, stderr=slave, env=env, preexec_fn=child_tty)
    os.close(slave)
    return master, process


def reference(root, full_id, output):
    master, process = start_reference(root, full_id)
    data = bytearray()
    try:
        for rows, columns in ((28, 90), (35, 110), (28, 90)):
            fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))
            until = time.monotonic() + 0.45
            while time.monotonic() < until:
                if select.select([master], [], [], 0.05)[0]:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        break
                    data.extend(chunk)
                    if len(data) > 1024 * 1024:
                        raise RuntimeError("synthetic output exceeded bound")
        output["bytes"] = len(data)
        output["sha256"] = hashlib.sha256(data).hexdigest()
        output["ansi_csi"] = data.count(b"\x1b[")
    finally:
        os.close(master)  # Detaches only this fixture's client.
        process.wait(timeout=4)
    return len(data) > 100


def main(visual=False):
    if Path.cwd().resolve() != REPO or not (REPO / ".tmp").is_dir() or not (REPO / ".log").is_dir():
        raise RuntimeError("run from ready repository root")
    if not shutil.which("screen"):
        raise RuntimeError("GNU screen missing; no package installation performed")
    if visual and (not sys.stdout.isatty() or os.environ.get("STY") or os.environ.get("TMUX")):
        raise RuntimeError("visual comparison requires a standalone ordinary terminal, outside screen/tmux")
    binary = REPO / "target/release/gpt2codex-backend-tests"
    if not binary.is_file():
        raise RuntimeError("build first: QT_QPA_PLATFORMTHEME=generic bash ./gpt2codex-p0ic-qt6-test-v2.sh")
    output = Path(tempfile.mkdtemp(prefix="terminal-diagnostics-", dir=REPO / ".log"))
    report = {"phase": "A", "host_terminal": terminal_metadata(), "cases": {},
        "live_sessions_accessed": False, "codex_started": False, "private_output_captured": False}
    version = subprocess.run(["/usr/bin/screen", "--version"], capture_output=True, timeout=4).stdout[:200]
    match = re.search(rb"Screen version ([0-9.]+)", version)
    report["screen_version"] = match[1].decode() if match else "unknown"
    success = True
    for case in ("reference", "konsole", "qtermwidget", "konsole-shared", "qtermwidget-shared"):
        root = Path(tempfile.mkdtemp(prefix="terminal-fixture-", dir=REPO / ".tmp"))
        (root / "marker").write_text(MARKER)
        (root / "sockets").mkdir(mode=0o700)
        (root / "screenrc").write_text("startup_message off\ndefscrollback 0\nvbell off\n")
        env = {"PATH": "/usr/bin:/bin", "HOME": str(root), "LANG": "C.UTF-8", "TERM": "xterm-256color",
            "SCREENDIR": str(root / "sockets"), "SCREENRC": str(root / "screenrc"), "SYSSCREENRC": str(root / "screenrc")}
        details = report["cases"][case] = {}
        keeper = None
        try:
            subprocess.run(["/usr/bin/screen", "-dmS", "g2c-diag", "-c", str(root / "screenrc"),
                sys.executable, str(Path(__file__).resolve()), "--frame", str(root)], env=env, check=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4)
            full_id = None
            for _ in range(40):
                sockets = [p.name for p in (root / "sockets").iterdir() if re.fullmatch(r"[1-9][0-9]*\.g2c-diag", p.name)]
                if len(sockets) == 1:
                    full_id = sockets[0]
                    break
                time.sleep(0.05)
            if full_id is None:
                raise RuntimeError("isolated screen did not create exactly one socket")
            if case == "reference":
                if visual:
                    print("Synthetic reference in this terminal for 7 seconds; resize is safe.", flush=True)
                    stop_timer = threading.Timer(7, lambda: (root / "stop").touch())
                    stop_timer.start()
                    try:
                        details["passed"] = attach(str(root), full_id) == 0
                    finally:
                        stop_timer.cancel()
                    details["visual_reference"] = True
                else:
                    details["passed"] = reference(root, full_id, details)
            else:
                if case.endswith("-shared"):
                    keeper = start_reference(root, full_id)
                    time.sleep(0.3)
                    (root / "shared").touch()
                test_env = os.environ.copy()
                test_env.update({"G2C_DIAG_ROOT": str(root), "G2C_DIAG_SESSION": full_id,
                    "G2C_DIAG_PYTHON": sys.executable, "G2C_DIAG_HELPER": str(Path(__file__).resolve()),
                    "G2C_DIAG_BACKEND": case.removesuffix("-shared"), "G2C_DIAG_OUTPUT": str(output)})
                case_output = output / case
                case_output.mkdir()
                test_env["G2C_DIAG_OUTPUT"] = str(case_output)
                if visual:
                    test_env["G2C_DIAG_VISUAL"] = "1"
                else:
                    test_env.update({"QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "generic"})
                with (output / (case + ".log")).open("w") as log:
                    rc = subprocess.run([str(binary), "screenPtyDiagnostics"], env=test_env,
                        stdout=log, stderr=subprocess.STDOUT, timeout=20).returncode
                details["passed"] = rc == 0
        except (RuntimeError, subprocess.SubprocessError, OSError) as error:
            # Never serialize arbitrary exception strings or process output.
            details["passed"] = False
            details["failure_type"] = type(error).__name__
        finally:
            (root / "stop").touch()
            if keeper is not None:
                os.close(keeper[0])
                keeper[1].wait(timeout=4)
            for _ in range(60):
                if not list((root / "sockets").iterdir()):
                    break
                time.sleep(0.05)
            details["fixture_socket_remaining"] = bool(list((root / "sockets").iterdir()))
            for name in ("screen-env.json", "attach-env.json"):
                if (root / name).is_file():
                    details[name] = json.loads((root / name).read_text())
            # Keep fixtures as evidence; never issue a quit/kill against screen.
        success &= details.get("passed", False) and not details["fixture_socket_remaining"]
    (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print("PHASE_A_DIAGNOSTICS=" + ("PASS" if success else "FAIL") + " report=" + str(output / "summary.json"))
    return 0 if success else 1


def safety_tests():
    original = os.environ.copy()
    try:
        os.environ.update({key: "DIAGNOSTIC_SECRET_SENTINEL" for key in
            ("TERM", "COLORTERM", "TERM_PROGRAM", "TERM_PROGRAM_VERSION", "COLUMNS", "LINES")})
        assert set(terminal_metadata().values()) == {"other"}
    finally:
        os.environ.clear()
        os.environ.update(original)
    try:
        fixture_root(str(REPO))
    except ValueError:
        pass
    else:
        raise AssertionError("non-fixture root accepted")
    root = Path(tempfile.mkdtemp(prefix="terminal-fixture-", dir=REPO / ".tmp"))
    (root / "marker").write_text(MARKER)
    (root / "sockets").mkdir(mode=0o700)
    assert fixture_root(str(root)) == root.resolve()
    try:
        attach(str(root), "123.g2c-bridge")
    except ValueError:
        pass
    else:
        raise AssertionError("non-diagnostic session name accepted")
    # Symlinks and regular files cannot substitute for a screen socket.
    (root / "sockets" / "123.g2c-diag").symlink_to(REPO / "AGENTS.md")
    try:
        attach(str(root), "123.g2c-diag")
    except ValueError:
        pass
    else:
        raise AssertionError("non-socket accepted")
    (root / "sockets" / "124.g2c-diag").write_text("not a socket\n")
    try:
        attach(str(root), "124.g2c-diag")
    except ValueError:
        pass
    else:
        raise AssertionError("regular file accepted as a socket")
    print("SAFETY_TESTS=PASS environment=allowlisted scope=fixture_only sockets=validated")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame")
    parser.add_argument("--attach-fixture", nargs=2, metavar=("ROOT", "FULL_ID"))
    parser.add_argument("--visual", action="store_true", help="show only synthetic fixture windows")
    parser.add_argument("--self-test", action="store_true", help="test privacy and fixture guards; no screen start")
    options = parser.parse_args()
    if options.self_test:
        safety_tests()
    elif options.frame:
        frame(options.frame)
    elif options.attach_fixture:
        sys.exit(attach(*options.attach_fixture))
    else:
        sys.exit(main(options.visual))
