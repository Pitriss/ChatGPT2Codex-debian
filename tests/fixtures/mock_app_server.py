#!/usr/bin/env python3
"""Synthetic Codex JSON-RPC app-server for cargo test; not used at runtime."""
import json
import sys
import time

MODE = sys.argv[1] if len(sys.argv) > 1 else "normal"
THREAD_ID = "123e4567-e89b-12d3-a456-426614174000"


def reply(payload):
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def thread(cwd):
    return {
        "id": THREAD_ID,
        "cwd": "/private/other-project" if MODE == "wrong-project" else cwd,
        "createdAt": 1730000000,
        "updatedAt": 1730000200,
        "status": {"type": "notLoaded"},
        "preview": "Never display this artificial private content",
        "turns": [],
    }


for line in sys.stdin:
    msg = json.loads(line)
    method = msg.get("method")
    req_id = msg.get("id")
    if method == "initialize":
        reply({
            "id": 99 if MODE == "wrong-id" else req_id,
            "result": {
                "userAgent": "mock-codex",
                "codexHome": "/tmp/mock-codex-home",
                "platformFamily": "unix",
                "platformOs": "linux",
            },
        })
    elif method == "initialized":
        continue
    elif method == "thread/list":
        if MODE == "events":
            reply({"method": "thread/started", "params": {"preview": "SENSITIVE DO NOT OUTPUT"}})
            reply({"method": "turn/started", "params": {"input": "SENSITIVE DO NOT OUTPUT"}})
            reply({"method": "item/agentMessage/delta", "params": {"delta": "SENSITIVE DO NOT OUTPUT"}})
        if MODE == "slow":
            time.sleep(3)
        if MODE == "server-request":
            reply({"id": 450, "method": "item/commandExecution/requestApproval", "params": {"command": "rm -rf /"}})
        cwd = msg.get("params", {}).get("cwd")
        reply({"id": req_id, "result": {"data": [thread(cwd)], "nextCursor": None}})
    elif method == "thread/read":
        reply({"id": req_id, "result": {"thread": thread("/tmp/mock-project")}})
    else:
        reply({"id": req_id, "error": {"code": -32601, "message": "unknown"}})
