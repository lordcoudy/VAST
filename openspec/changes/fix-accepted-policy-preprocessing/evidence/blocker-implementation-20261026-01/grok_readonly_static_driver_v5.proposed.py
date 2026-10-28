"""Closed static Grok bridge. Definitions only; no CLI on import."""
from __future__ import annotations

import json
import os
from pathlib import Path
import struct
import sys
import tomllib

ROOT = Path(r"C:\Users\s-a-balashov\.codex\worktrees\fix-accepted-policy-preprocessing\VAST")
HOME = Path(r"C:\Users\s-a-balashov\.g5\a\p")
OUTPUT = Path(str(HOME) + "-results")
EXECUTABLE = r"C:\Users\s-a-balashov\.grok\bin\grok.exe"
CONTROLLER_STAGE = "runtime"
WINDOWS_NAMES = (
    "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "USERPROFILE",
    "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA",
)
NETWORK_NAMES = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
    "NODE_EXTRA_CA_CERTS", "GRPC_DEFAULT_SSL_ROOTS_FILE_PATH",
)
OVERRIDES = (
    "GROK_HOME", "GROK_CONFIG", "GROK_CONFIG_PATH", "GROK_API_KEY", "XAI_API_KEY",
    "GROK_MODEL", "GROK_BASE_URL", "XAI_BASE_URL", "GROK_LOG_FILE", "GROK_LOG_DIR",
    "GROK_TRACE_FILE", "GROK_TRACE_DIR", "GROK_LEADER", "GROK_USE_LEADER",
    "GROK_AUTH_PROVIDER_COMMAND", "GROK_AUTH_PROVIDER_LABEL", "GROK_AGENT",
    "GROK_MODELS_BASE_URL", "GROK_MODELS_LIST_URL",
)
GATES = {
    "GROK_MEMORY": "0", "GROK_WORKFLOWS": "0", "GROK_DISABLE_AUTOUPDATER": "1",
    "GROK_CLAUDE_HOOKS_ENABLED": "0", "GROK_CLAUDE_MCPS_ENABLED": "0",
    "GROK_CURSOR_HOOKS_ENABLED": "0", "GROK_CURSOR_MCPS_ENABLED": "0",
    "GROK_MANAGED_MCPS_ENABLED": "0", "GROK_MANAGED_MCP_GATEWAY_TOOLS_ENABLED": "0",
    "GROK_TELEMETRY_ENABLED": "0", "DISABLE_TELEMETRY": "1",
    "GROK_TELEMETRY_TRACE_UPLOAD": "0", "GROK_TELEMETRY_MIXPANEL_ENABLED": "0",
    "GROK_EXTERNAL_OTEL": "0", "GROK_FEEDBACK_ENABLED": "0",
    "GROK_ERROR_REPORTING": "0", "DISABLE_ERROR_REPORTING": "1",
}


def static_environment(helper):
    if any(name in os.environ for name in OVERRIDES):
        raise ValueError("unreviewed inherited Grok override")
    # No inherited PATH or shell callback is needed by these absolute commands.
    # Network/certificate values are passed unchanged and never serialized.
    environment = {
        name: os.environ[name] for name in WINDOWS_NAMES + NETWORK_NAMES if name in os.environ
    }
    if "SystemRoot" not in environment or "WINDIR" not in environment:
        raise ValueError("Windows environment unavailable")
    environment.update(GATES)
    environment["GROK_HOME"] = str(HOME)
    environment["GROK_CONFIG"] = json.dumps({"features": {
        "managed_config": False, "remote_fetch": False,
        "codebase_indexing": False, "lsp_tools": False,
    }}, separators=(",", ":"))
    environment["TMP"] = environment["TEMP"] = str(HOME / "tmp-denied")
    return helper["bounded_environment"](environment)


def audit_startup_inputs():
    original = Path(r"C:\Users\s-a-balashov\.grok")
    for root in (original, HOME):
        for name in ("managed_config.toml", "requirements.toml", "managed_config.sig.json",
                     "managed_identity.sig.json", "managed_config_cache.json", "hooks.json", "mcp.json"):
            if os.path.lexists(root / name):
                raise ValueError("native policy/hook input needs preservation review")
    for relative in (".grok", ".cursor", ".mcp.json", ".claude/settings.json",
                     ".claude/settings.local.json", ".claude/mcp.json"):
        if os.path.lexists(ROOT / relative):
            raise ValueError("project startup input needs review")
    for relative in ("plugins", "mcp", "hooks", "workflows", "skills", "commands"):
        if os.path.lexists(HOME / relative):
            raise ValueError("unexpected copied discovery root")

    def read(name, maximum):
        with (HOME / name).open("rb") as stream:
            size = os.fstat(stream.fileno()).st_size
            if not 0 <= size <= maximum:
                raise ValueError("startup input extent")
            raw = stream.read(maximum + 1)
            if len(raw) != size or len(raw) > maximum:
                raise ValueError("startup input changed")
            return raw

    config = tomllib.loads(read("config.toml", 8192).decode("utf-8", "strict"))
    if any(name in config for name in ("hooks", "mcp_servers", "managed_config", "requirements")):
        raise ValueError("native executable/policy table needs review")
    agent = config.get("agent", {})
    cli = config.get("cli", {})
    plugins = config.get("plugins", {})
    ui = config.get("ui", {})
    if any(type(table) is not dict for table in (agent, cli, plugins, ui)):
        raise ValueError("unknown startup selector table")
    if any(name in agent for name in ("name", "definition")) or cli.get("use_leader") not in (None, False):
        raise ValueError("agent or leader selector needs review")
    if "paths" in plugins:
        raise ValueError("custom plugin discovery needs review")
    config_pending = [(config, 0)]
    config_nodes = 0
    while config_pending:
        value, depth = config_pending.pop()
        config_nodes += 1
        if config_nodes > 4096 or depth > 32:
            raise ValueError("startup config structural ceiling")
        if type(value) is dict:
            for key, item in value.items():
                if key in {"auth_provider", "auth_provider_command"}:
                    raise ValueError("external authentication helper needs review")
                if len(config_pending) >= 4096:
                    raise ValueError("startup config pending ceiling")
                config_pending.append((item, depth + 1))
        elif type(value) is list:
            for item in value:
                if len(config_pending) >= 4096:
                    raise ValueError("startup config pending ceiling")
                config_pending.append((item, depth + 1))
    ui_pending = [ui]
    while ui_pending:
        value = ui_pending.pop()
        if type(value) is dict:
            for key, item in value.items():
                if key in {"command", "commands", "script", "exec", "notification_command", "notify_command"}:
                    raise ValueError("UI execution selector needs review")
                if type(item) in (dict, list):
                    ui_pending.append(item)
        elif type(value) is list:
            ui_pending.extend(item for item in value if type(item) in (dict, list))
    # SignedSettingsCache is retained byte-for-byte; this checks its closed
    # envelope and absence of executable/policy definitions, not its signature.
    cache = json.loads(read("settings_cache.json", 16384))
    if type(cache) is not dict or set(cache) != {"payload", "signature"}:
        raise ValueError("unknown signed settings envelope")
    payload, signature = cache["payload"], cache["signature"]
    if (type(payload) is not str or len(payload.encode("utf-8")) > 16384
            or type(signature) is not list or len(signature) != 32
            or any(type(value) is not int or not 0 <= value <= 255 for value in signature)):
        raise ValueError("signed settings geometry")
    pending = [(json.loads(payload), 0)]
    visited = 0
    while pending:
        value, depth = pending.pop()
        visited += 1
        if visited > 4096 or depth > 32:
            raise ValueError("signed settings structural ceiling")
        if type(value) is dict:
            for key, item in value.items():
                if key in {"hooks", "mcp_servers", "managed_config", "requirements", "managed_settings", "policy"}:
                    raise ValueError("cached policy definition needs preservation review")
                if key == "campaigns" and item not in (None, [], {}):
                    if type(item) is not list or len(item) != 1:
                        raise ValueError("unknown signed settings campaign roster")
                    campaign = item[0]
                    if (type(campaign) is not dict or set(campaign) != {"id", "models"}
                            or type(campaign["id"]) is not str or not 0 < len(campaign["id"]) <= 128
                            or type(campaign["models"]) is not dict or set(campaign["models"]) != {"default"}
                            or type(campaign["models"]["default"]) is not str
                            or not 0 < len(campaign["models"]["default"]) <= 128):
                        raise ValueError("unknown signed settings campaign definition")
                    if any(not text.isascii() or any(ord(char) < 33 or ord(char) > 126 for char in text)
                           for text in (campaign["id"], campaign["models"]["default"])):
                        raise ValueError("signed settings campaign scalar geometry")
                if key in {"configuration", "experiments"} and item not in (None, [], {}):
                    raise ValueError("cached configuration campaign needs review")
                if len(pending) >= 4096:
                    raise ValueError("signed settings pending ceiling")
                pending.append((item, depth + 1))
        elif type(value) is list:
            for item in value:
                if len(pending) >= 4096:
                    raise ValueError("signed settings pending ceiling")
                pending.append((item, depth + 1))


def run_static(helper, owner_definitions, mode, source_pins, deadline):
    global CONTROLLER_STAGE
    CONTROLLER_STAGE = "runtime"
    if (
        os.name != "nt" or sys.version_info[:3] != (3, 14, 7) or struct.calcsize("P") != 8
        or not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode
        or Path.cwd().resolve(strict=True) != ROOT or ROOT.resolve(strict=True) != ROOT
        or mode not in ("inspect", "plugin", "mcp")
    ):
        raise ValueError("fixed static runtime/mode required")
    observation = helper["WindowsObservation"]()
    if type(deadline) is not int or not 0 < deadline - observation.tick() <= 180000:
        raise ValueError("inherited preparation deadline required")
    CONTROLLER_STAGE = "environment"
    environment = static_environment(helper)
    CONTROLLER_STAGE = "startup"
    audit_startup_inputs()
    CONTROLLER_STAGE = "owner"
    job_type = helper["load_reviewed_job_definitions"](owner_definitions)
    CONTROLLER_STAGE = "capture"
    result = helper["capture_literal"](
        mode=mode, executable=EXECUTABLE, cwd=ROOT, environment=environment,
        deadline_tick_ms=deadline, job_type=job_type, observation=observation,
        private_outputs=(OUTPUT / (mode + ".stdout.private"), OUTPUT / (mode + ".stderr.private")),
    )
    CONTROLLER_STAGE = "result"
    # No private bytes, content hashes, exception strings or config values enter
    # this public status. Shape/effective-config validation remains offline/HOLD.
    status = {
        "scope": "static_capture_only", "mode": mode, "source_pins": source_pins,
        "capture": result["facts"], "complete": result["facts"]["complete"],
        "effective_configuration_accepted": False, "ready_for_model": False,
        "schema_validation": "pending_offline_review", "model_request_admitted": False,
        "environment_geometry": {
            "entries": len(environment), "has_path": "PATH" in environment,
            "max_scalar_chars": max(map(len, environment.values()), default=0),
            "utf16_units": 1 + sum(len((name + "=" + value + "\0").encode("utf-16-le")) // 2
                                    for name, value in environment.items()),
        },
    }
    raw = json.dumps(status, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii") + b"\n"
    if len(raw) > 8192:
        raise ValueError("static public status ceiling")
    if os.write(1, raw) != len(raw):
        return 1
    return 0 if status["complete"] else 1


# Called only by the separately authenticated literal source bootstrap.
