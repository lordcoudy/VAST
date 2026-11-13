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
OUTPUT = Path(r"C:\Users\s-a-balashov\.gm2")
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



SESSION = "01a17ad0-d506-76d3-95b3-ddb27d4f3f5e"
PREFLIGHT_STEP = "private_preflight_input_or_shape"
PREFLIGHT_FACTS = {}


def require_route(condition, code):
    global PREFLIGHT_STEP
    if not condition:
        PREFLIGHT_STEP = code
        raise ValueError("fixed route assertion refused")


def read_private_bound(path, maximum):
    before = path.lstat()
    if (not path.is_file() or path.is_symlink() or before.st_nlink != 1
            or getattr(before, "st_file_attributes", 0) & 0x400
            or path.resolve(strict=True) != path or not 0 <= before.st_size <= maximum):
        raise ValueError("private input identity/extent")
    stream = path.open("rb")
    primary = None
    try:
        opened = os.fstat(stream.fileno())
        fields = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
        if fields(opened) != fields(before):
            raise ValueError("private input changed")
        raw = bytearray()
        remaining = before.st_size
        while True:
            part = stream.read(min(65536, remaining + 1))
            if not part:
                break
            if len(part) > remaining:
                raise ValueError("private input grew")
            raw.extend(part)
            remaining -= len(part)
        if remaining or fields(os.fstat(stream.fileno())) != fields(opened):
            raise ValueError("private input changed")
        return bytes(raw)
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            stream.close()
        except BaseException as close_error:
            if primary is not None and close_error is not primary:
                raise primary from close_error
            raise


def closed_json(raw, maximum_nodes):
    import math
    in_string = escaped = False
    depth = 0
    for byte in raw:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                in_string = False
        elif byte == 34:
            in_string = True
        elif byte in (91, 123):
            depth += 1
            if depth > 32:
                raise ValueError("private JSON depth")
        elif byte in (93, 125):
            depth -= 1
            if depth < 0:
                raise ValueError("private JSON framing")
    if depth or in_string:
        raise ValueError("private JSON framing")
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError("duplicate private JSON key")
            result[key] = value
        return result
    result = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=pairs,
                        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    pending = [(result, 0)]
    visited = 0
    while pending:
        value, current = pending.pop()
        visited += 1
        if visited > maximum_nodes or current > 32:
            raise ValueError("private JSON geometry")
        if type(value) is float and not math.isfinite(value):
            raise ValueError("nonfinite decoded JSON number")
        if type(value) is dict:
            children = value.values()
        elif type(value) is list:
            children = value
        else:
            continue
        for child in children:
            if len(pending) >= maximum_nodes:
                raise ValueError("private JSON pending bound")
            pending.append((child, current + 1))
    return result


def resolve_config_warning_path(path, configs):
    import re
    require_route(type(path) is str and 0 < len(path) <= 256, "warning_path_extent")
    require_route(len(path.encode("utf-8", "strict")) <= 256, "warning_path_utf8_extent")
    raw_parts = path.split(".")
    identifier = lambda p: re.fullmatch(r"[a-z_]{1,48}", p) is not None
    PREFLIGHT_FACTS["warning_path_shape"] = {
        "raw_segments": min(len(raw_parts), 17),
        "wrapper_markers": min(sum(p == "?" for p in raw_parts), 17),
        "identifier_segments": min(sum(identifier(p) for p in raw_parts), 17),
        "unsupported_segments": min(sum(p != "?" and not identifier(p) for p in raw_parts), 17),
        "segment_bound_exceeded": len(raw_parts) > 16,
    }
    require_route(len(raw_parts) <= 16 and all(p == "?" or identifier(p) for p in raw_parts),
                  "warning_path_tokens")
    parts = [p for p in raw_parts if p != "?"]
    require_route(bool(parts), "warning_path_no_identifier")
    leaves = []
    for config in configs:
        value = config
        for token in raw_parts:
            if type(value) is dict:
                require_route(not any("." in key or "?" in key for key in value), "warning_path_alias_ambiguity")
            if token != "?":
                require_route(type(value) is dict and token in value, "warning_structural_join")
                value = value[token]
        leaves.append(value)
    return parts, leaves


def diagnose_schema_identifier(original_raw, snapshot_raw, report):
    import re
    warnings = report.get("configWarnings")
    require_route(type(warnings) is list and len(warnings) == 1, "diagnostic_single_warning")
    warning = warnings[0]
    require_route(type(warning) is dict and set(warning) == {"target", "kind", "path", "reason"}
                  and warning["target"] == "configKey" and warning["kind"] == "unknown-field",
                  "diagnostic_warning_category")
    configs = tuple(tomllib.loads(raw.decode("utf-8", "strict")) for raw in (original_raw, snapshot_raw))
    parts, leaves = resolve_config_warning_path(warning["path"], configs)
    raw_shape = PREFLIGHT_FACTS["warning_path_shape"]
    root_key = len(parts) == 1 and raw_shape["raw_segments"] == 1 and raw_shape["wrapper_markers"] == 0
    namespaced = len(parts) == 2 and parts[0] in {"ui", "features", "cli", "session"}
    require_route(root_key or namespaced, "diagnostic_static_namespace")
    kinds = {bool: "Boolean", int: "Integer", float: "Float", str: "String", dict: "Table", list: "Array"}
    PREFLIGHT_FACTS["diagnostic_leaf_kind"] = kinds.get(type(leaves[0]), "Other")
    if root_key and all(type(value) is dict for value in leaves):
        return {"schema_path": parts[0], "present_in_both": True, "value_kind": "Table",
                "requires_primary_source_lookup_and_review": True}
    for value in leaves:
        require_route(type(value) in (bool, int), "diagnostic_scalar_leaf")
    return {"schema_path": ".".join(parts), "present_in_both": True,
            "scalar_kind": "Boolean" if type(leaves[0]) is bool else "Integer",
            "requires_primary_source_lookup_and_review": True}


def validate_pager_acknowledgement(warnings, configs):
    import datetime
    import re
    require_route(type(warnings) is list and len(warnings) == 1, "single_pager_ack_warning")
    warning = warnings[0]
    require_route(type(warning) is dict and set(warning) == {"target", "kind", "path", "reason"}
                  and warning["target"] == "configKey" and warning["kind"] == "unknown-field"
                  and warning["path"] == "privacy" and type(warning["reason"]) is str,
                  "exact_pager_ack_warning")
    for config in configs:
        table = config.get("privacy")
        require_route(type(table) is dict and set(table) == {"privacy_banner_acked"}, "pager_ack_table")
        value = table["privacy_banner_acked"]
        require_route(type(value) is str and len(value.encode("utf-8", "strict")) <= 64
                      and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?(?:Z|\+00:00)", value)
                      is not None, "pager_ack_timestamp")
        try:
            datetime.datetime.fromisoformat(value)
        except ValueError:
            require_route(False, "pager_ack_calendar")
    PREFLIGHT_FACTS["pager_ack_disposition"] = True


def private_route_preflight(diagnostic=False):
    import re
    original = Path(r"C:\Users\s-a-balashov\.grok")
    raw = read_private_bound(HOME / "config.toml", 8192)
    original_raw = read_private_bound(original / "config.toml", 8192)
    require_route(raw == original_raw, "original_configuration_join")
    PREFLIGHT_FACTS["original_configuration_join"] = True
    config = tomllib.loads(raw.decode("utf-8", "strict"))
    report = closed_json(read_private_bound(Path(str(HOME) + "-results") / "inspect.stdout.private", 262144), 2048)
    require_route(type(report) is dict and report.get("grokVersion") == "1.0.62"
                  and report.get("cwd") == str(ROOT), "inspect_identity")
    allowed = {"grokVersion", "channel", "cwd", "projectRoot", "projectTrusted", "projectInstructions",
               "permissions", "loginPolicy", "hooks", "skills", "agents", "plugins", "marketplaces",
               "mcpServers", "lspServers", "configSources", "experiments", "externalCompat",
               "configWarnings", "mcpConfigProblems"}
    require_route(set(report) <= allowed, "inspect_schema")
    if diagnostic:
        return diagnose_schema_identifier(original_raw, raw, report)
    for key in ("hooks", "plugins", "experiments"):
        require_route(type(report.get(key)) is list and not report[key], "extensions_and_experiments_empty")
    require_route("mcpConfigProblems" not in report or report["mcpConfigProblems"] == [], "mcp_diagnostics_empty")
    PREFLIGHT_FACTS["extensions_and_experiments_empty"] = True
    servers = report.get("mcpServers")
    require_route(type(servers) is list and len(servers) <= 128, "mcp_server_shape")
    for server in servers:
        require_route(type(server) is dict and server.get("disabled") is True
                      and server.get("compatibilityStatus", "disabled") == "disabled", "mcp_disabled")
    for mode in ("plugin", "mcp"):
        root = Path(str(HOME) + "-results")
        require_route(closed_json(read_private_bound(root / (mode + ".stdout.private"), 262144), 2048) == [], "standalone_extensions_empty")
    PREFLIGHT_FACTS["mcp_and_plugins_disabled"] = True
    layers = report.get("configSources", {}).get("layers")
    expected = [{"role": "user", "path": str(HOME / "config.toml")},
                {"role": "env_overlay", "path": "$GROK_CONFIG (inline)", "note": "sections: features"}]
    require_route(type(layers) is list and len(layers) == 2 and all(type(v) is dict for v in layers)
                  and sorted(layers, key=lambda v: v.get("role", "")) == sorted(expected, key=lambda v: v["role"]), "reviewed_configuration_layers")
    PREFLIGHT_FACTS["reviewed_configuration_layers"] = True
    validate_pager_acknowledgement(report.get("configWarnings"),
        (tomllib.loads(original_raw.decode("utf-8", "strict")), config))
    models = config.get("models")
    require_route(type(models) is dict and type(models.get("default")) is str
                  and 0 < len(models["default"]) <= 128, "recognized_selected_model")
    selected = models["default"]
    providers = config.get("model_providers", {})
    endpoints = config.get("endpoints", {})
    overrides = config.get("model", {})
    require_route(type(providers) is dict and not providers and type(endpoints) is dict and not endpoints
                  and type(overrides) is dict, "recognized_provider_route")
    for namespace in ("grok_com_config", "auth"):
        auth = config.get(namespace, {})
        require_route(type(auth) is dict and set(auth) <= {"disable_api_key_auth", "force_login_team_uuid"},
                      "recognized_default_oauth_selectors")
    override = overrides.get(selected, {})
    require_route(type(override) is dict and not any(k in override for k in (
        "api_key", "env_key", "api_base_url", "base_url", "auth_provider", "provider", "model_provider",
        "api_backend", "model", "extra_headers", "env_http_headers")), "no_unreviewed_provider_selector")
    PREFLIGHT_FACTS["recognized_model_and_provider_route"] = True
    return selected


def validate_private_response(raw, expected_model):
    import re
    if len(raw) > 524288:
        raise ValueError("private model result extent")
    result = closed_json(raw, 4096)
    if type(result) is not dict:
        raise ValueError("private model result object")
    turns = result.get("num_turns")
    usage = result.get("modelUsage")
    if not (result.get("sessionId") == SESSION and result.get("stopReason") == "end_turn"
            and result.get("usage_is_incomplete", False) is False
            and type(result.get("cwd")) is str and Path(result["cwd"]) == ROOT
            and type(turns) is int and 1 <= turns <= 4 and type(usage) is dict
            and set(usage) == {expected_model} and type(usage[expected_model]) is dict):
        raise ValueError("private model result identity")
    calls = usage[expected_model].get("modelCalls")
    text = result.get("text")
    if not (type(calls) is int and 1 <= calls <= 4 and type(text) is str
            and 0 < len(text.encode("utf-8")) <= 32768):
        raise ValueError("private model result turn/text bound")
    match = re.match(r"\s*(?:\*\*)?(?:Verdict:\s*)?(CLEAR_WITH_NOTES|CLEAR|BLOCK|HOLD)(?:\*\*)?(?:\s|[.:]|$)", text)
    verdict = match.group(1) if match else "unparsed"
    return {"session_and_cwd_match": True, "configured_model_match": True, "stop_reason_end_turn": True,
            "main_turns": turns, "model_calls": calls, "verdict": verdict,
            "private_text_or_thought_emitted": False}


def run_model(helper, owner_definitions, source_pins, deadline, mode):
    global CONTROLLER_STAGE, HOME
    CONTROLLER_STAGE = "runtime"
    if mode not in ("diagnostic04", "preflight04", "preflight06", "review06"):
        raise ValueError("fixed review phase")
    HOME = Path(r"C:\Users\s-a-balashov\.g4\a\p") if mode in ("diagnostic04", "preflight04") else Path(r"C:\Users\s-a-balashov\.g5\a\p")
    review = mode == "review06"
    diagnostic = mode == "diagnostic04"
    if (os.name != "nt" or sys.version_info[:3] != (3, 14, 7) or struct.calcsize("P") != 8
            or not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode
            or Path.cwd().resolve(strict=True) != ROOT or ROOT.resolve(strict=True) != ROOT):
        raise ValueError("fixed model runtime required")
    observation = helper["WindowsObservation"]()
    if type(deadline) is not int or not 0 < deadline - observation.tick() <= (600000 if review else 60000):
        raise ValueError("inherited phase deadline required")
    CONTROLLER_STAGE = "environment"
    environment = static_environment(helper)
    CONTROLLER_STAGE = "startup"
    audit_startup_inputs()
    CONTROLLER_STAGE = "preflight"
    status = {"scope": "model_capture_only" if review else ("readonly_route_diagnostic_only" if diagnostic else "readonly_route_preflight_only"), "mode": mode,
              "source_commit": "605eb02733fe256ad5ef14f358eaa81ee1a0ae44", "source_pins": source_pins,
              "preflight_checks": PREFLIGHT_FACTS, "preflight_complete": False, "capture": None,
              "response_checks": None, "diagnostic_identifier": None, "complete": False, "grok_performed": False,
              "failure_code": None, "independent_verdict_accepted": False, "effective_configuration_accepted": False}
    try:
        selected = private_route_preflight(diagnostic)
        if diagnostic:
            status["diagnostic_identifier"] = selected
            status["complete"] = True
        else:
            status["preflight_complete"] = True
    except BaseException:
        status["failure_code"] = PREFLIGHT_STEP
    if status["preflight_complete"] and review:
        CONTROLLER_STAGE = "owner"
        job_type = helper["load_reviewed_job_definitions"](owner_definitions)
        CONTROLLER_STAGE = "capture"
        result = helper["capture_literal"](
            mode="model_review", executable=EXECUTABLE, cwd=ROOT, environment=environment,
            deadline_tick_ms=deadline, job_type=job_type, observation=observation,
            private_outputs=(OUTPUT / "stdout.private", OUTPUT / "stderr.private"),
        )
        status["grok_performed"] = result["facts"]["resumed"]
        status["capture"] = result["facts"]
        if result["facts"]["complete"]:
            try:
                status["response_checks"] = validate_private_response(result["private_channel_bytes"][0], selected)
                status["complete"] = status["response_checks"]["verdict"] != "unparsed"
            except BaseException:
                status["failure_code"] = "private_response_identity_or_shape"
        else:
            status["failure_code"] = "model_capture_incomplete"
    elif status["preflight_complete"]:
        status["complete"] = True
    CONTROLLER_STAGE = "result"
    raw = json.dumps(status, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii") + b"\n"
    if len(raw) > (8192 if review else 4096):
        raise ValueError("public phase status ceiling")
    if os.write(1, raw) != len(raw):
        return 1
    return 0 if status["complete"] else 1
