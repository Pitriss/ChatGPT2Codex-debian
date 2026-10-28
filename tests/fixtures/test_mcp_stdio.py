#!/usr/bin/env python3
"""Local P0-H smoke tests; synthetic data only, no network or Codex login."""
import json
import os
import select
import subprocess
import sys
import tempfile
from pathlib import Path


def transact(process, method, params=None, request_id=1):
    packet = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        packet["params"] = params
    process.stdin.write((json.dumps(packet, separators=(",", ":")) + "\n").encode())
    process.stdin.flush()
    ready, _, _ = select.select([process.stdout], [], [], 12)
    if not ready:
        raise AssertionError(f"MCP response timeout: {method}")
    line = process.stdout.readline()
    if not line:
        raise AssertionError(f"MCP server exited early: {method}")
    result = json.loads(line)
    assert result.get("id") == request_id, result
    return result


def notify(process, method):
    process.stdin.write((json.dumps({"jsonrpc": "2.0", "method": method}) + "\n").encode())
    process.stdin.flush()


def call(process, name, arguments=None, request_id=10):
    packet = {"name": name, "arguments": arguments or {}}
    response = transact(process, "tools/call", packet, request_id)
    value = response["result"]
    if value.get("isError"):
        return None, value["content"][0]["text"]
    return json.loads(value["content"][0]["text"]), None


def make_fixture(root):
    workspace = root / "mycode"
    shared = workspace / ".ai"
    repo = workspace / "demo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".ai").mkdir()
    shared.mkdir(parents=True)
    (shared / "CODEX_GLOBAL.md").write_text("# Shared global rules\nDo not run arbitrary commands.\n")
    (repo / "AGENTS.md").write_text(
        "# Project demo\n"
        "Run read-only diagnostics.\n"
        "password = SHOULD_NOT_LEAK\n"
        "-----BEGIN OPENSSH PRIVATE KEY-----\n"
        "FAKE_PRIVATE_DATA_SHOULD_NOT_LEAK\n"
        "-----END OPENSSH PRIVATE KEY-----\n"
        "Normal documentation continues.\n",
    )
    # The following file is specifically allowlisted to prove openat2 blocks it.
    (root / "outside.txt").write_text("OUTSIDE_SECRET_SHOULD_NOT_LEAK\n")
    (repo / ".ai" / "UNSAFE.md").symlink_to(root / "outside.txt")
    config_dir = root / "config"
    (config_dir / "projects").mkdir(parents=True)
    config = config_dir / "config.toml"
    config.write_text(f'[workspace]\nproject_dir = {json.dumps(str(workspace))}\nglobal_context_files = ["CODEX_GLOBAL.md"]\n')
    (config_dir / "projects" / "demo.toml").write_text(
        '[project]\nid = "demo"\ndirectory = "demo"\n'
        '[contexts]\nfiles = ["AGENTS.md", ".ai/UNSAFE.md"]\n'
    )
    return config


def run_checks(binary, config, allow_reads):
    cmd = [str(binary), "mcp", "stdio", "--config", str(config)]
    if allow_reads:
        cmd.append("--allow-context-read")
    process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        handshake = transact(process, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "p0h-test", "version": "1"}}, 1)
        assert handshake["result"]["serverInfo"]["name"] == "gpt2codex-readonly"
        notify(process, "notifications/initialized")
        available = transact(process, "tools/list", {}, 2)["result"]["tools"]
        names = {item["name"] for item in available}
        assert "projects_list" in names and "project_health" in names, names
        assert ("project_context_read" in names) == allow_reads, names
        assert not any(word in name for name in names for word in ("exec", "write", "apply", "approve", "screen")), names
        projects, error = call(process, "projects_list", {}, 3)
        assert error is None and [p["project_id"] for p in projects["projects"]] == ["demo"], (projects, error)
        _, error = call(process, "projects_list", {"command": "rm -rf /"}, 4)
        assert error, "forbidden argument must not be accepted"
        _, error = call(process, "project_contexts", {"project_id": "not-registered"}, 5)
        assert error, "unknown project must not be accepted"
        status, error = call(process, "project_health", {"project_id": "demo"}, 6)
        assert error is None and not status["ready"], (status, error)
        _, error = call(process, "screen_exec", {"shell": "true"}, 7)
        assert error, "unimplemented remote actions must not exist"
        if allow_reads:
            result, error = call(process, "project_context_read", {"project_id": "demo", "scope": "project", "file": "AGENTS.md", "start_line": 1, "max_lines": 10}, 8)
            assert error is None, error
            assert "Normal documentation continues" in result["content"]
            assert "SHOULD_NOT_LEAK" not in result["content"], result["content"]
            assert result["redacted_lines"] >= 3, result
            _, error = call(process, "project_context_read", {"project_id": "demo", "scope": "project", "file": ".ai/UNSAFE.md"}, 9)
            assert error, "symlink must be rejected"
            _, error = call(process, "project_context_read", {"project_id": "demo", "scope": "project", "file": "../outside.txt"}, 10)
            assert error, "traversal must be rejected"
            _, error = call(process, "project_context_read", {"project_id": "demo", "scope": "project", "file": "AGENTS.md", "max_lines": 900}, 11)
            assert error, "oversized page must be rejected"
        else:
            _, error = call(process, "project_context_read", {"project_id": "demo", "scope": "project", "file": "AGENTS.md"}, 8)
            assert error, "context read must be disabled by default"
        ping = transact(process, "ping", {}, 12)
        assert ping["result"] == {}, ping
        process.stdin.close()
        code = process.wait(timeout=5)
        assert code == 0, f"MCP server returned {code}"
        return True
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()


def main():
    if len(sys.argv) != 3:
        raise SystemExit("Usage: test_mcp_stdio.py /absolute/gpt2codex /absolute/project-tmp")
    binary, scratch = Path(sys.argv[1]).resolve(strict=True), Path(sys.argv[2]).resolve(strict=True)
    if not scratch.is_dir() or not binary.is_file():
        raise SystemExit("Binary and scratch directory must exist")
    with tempfile.TemporaryDirectory(prefix="p0h-mcp-", dir=scratch) as temporary:
        config = make_fixture(Path(temporary))
        run_checks(binary, config, allow_reads=False)
        run_checks(binary, config, allow_reads=True)
    print("MCP_STDIO=OK default_read=disabled explicit_read=filtered symlink=blocked arbitrary_commands=blocked")


if __name__ == "__main__":
    main()
