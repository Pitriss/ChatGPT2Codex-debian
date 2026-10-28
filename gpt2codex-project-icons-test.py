#!/usr/bin/env python3
"""Existing release GUI workflow + CTest, with no user config/session access."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def main():
    root = Path.cwd()
    assert (root / "gui/main.cpp").is_file() and (root / ".tmp").is_dir() and (root / ".log").is_dir()
    os.umask(0o077)
    logs = Path(tempfile.mkdtemp(prefix="project-icons-", dir=root / ".log")).resolve()
    with tempfile.TemporaryDirectory(prefix="project-icons-", dir=root / ".tmp") as scratch:
        fixture = Path(scratch).resolve()
        for name in ["home", "config/chatgpt2codex/projects", "state", "runtime", "screens", "tmp", "repos/bridge/.git"]:
            (fixture / name).mkdir(parents=True, exist_ok=True, mode=0o700)
        config = fixture / "config/chatgpt2codex"
        (config / "config.toml").write_text("[workspace]\nproject_dir=" + json.dumps(str(fixture / "repos")) + "\n")
        (config / "projects/gpt2codex.toml").write_text("[project]\nid='gpt2codex'\ndirectory='bridge'\n")
        env = {
            "PATH": os.environ.get("PATH", os.defpath), "HOME": str(fixture / "home"),
            "XDG_CONFIG_HOME": str(fixture / "config"), "XDG_STATE_HOME": str(fixture / "state"),
            "XDG_RUNTIME_DIR": str(fixture / "runtime"), "TMPDIR": str(fixture / "tmp"),
            "SCREENDIR": str(fixture / "screens"), "SCREENRC": "/dev/null", "SYSSCREENRC": "/dev/null",
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "GIT_OPTIONAL_LOCKS": "0",
            "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "generic",
        }
        built = subprocess.run(["bash", "./gpt2codex-p0ic-qt6-test-v2.sh"], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
        (logs / "build-driver.log").write_bytes(built.stdout)
        assert built.returncode == 0, f"release build failed; {logs}/build-driver.log"
        detail = Path(re.search(rb"^DETAILS=(.+)$", built.stdout, re.M)[1].decode())
        build_dir = re.search(r"Build files have been written to: (.+)", detail.read_text())[1]
        with (logs / "ctest.log").open("w") as output:
            tested = subprocess.run(["ctest", "--test-dir", build_dir, "--output-on-failure"], env=env,
                                    stdout=output, stderr=subprocess.STDOUT, timeout=60)
        summary = {"release_build": "PASS", "build_directory": build_dir, "build_log": str(detail),
                   "ctest": "PASS" if tested.returncode == 0 else "FAIL",
                   "live_user_sessions_accessed": 0, "real_codex_started": 0,
                   "screen_tmux_servers_started": 0}
        (logs / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(f"REPORT={logs}", flush=True)
        assert tested.returncode == 0, f"GUI tests failed; {logs}/ctest.log"
        print("PROJECT_ICONS=PASS release_build=PASS ctest=PASS live_sessions=0 codex_started=0")


if __name__ == "__main__":
    main()
