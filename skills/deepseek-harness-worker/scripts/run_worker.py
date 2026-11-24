"""Delegate one expert task to DeepSeek Harness, with read-only access by default."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from uuid import uuid4


VERSION = "0.2.2-rc.5"
OVERLAY = Path(__file__).resolve().with_name("account.patch.yml")
PROVIDER = "deepseek-account"
ROUTES = {
    "lookup": ("standard", "deepseek-flash", "low"),
    "analysis": ("standard", "deepseek-flash", "high"),
    "batch": ("ptc", "deepseek-flash", "high"),
    "review": ("standard", "deepseek-v4-pro", "high"),
}


def write_overlay(path, mode, model, effort):
    account = OVERLAY.read_text(encoding="utf-8")
    selection = f"""
- id: agent-default-model
  name: '@deepseek-ai/dsh-agent-default-model'
  config:
    provider: {PROVIDER}
    model: {model}
    reasoningEffort: {effort}
"""
    if mode == "ptc":
        # Native rc.5 PTC composition, scoped to this headless process.
        selection += """
- id: tool-executor-native
  disabled: true
- id: tool-executor-ptc
  disabled: false
- id: tool-fs
  config:
    applyPatch: false
"""
    path.write_text(account + selection, encoding="utf-8")


def worker_config():
    codex = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    locator = codex / "deepseek-harness-worker.json"
    return json.loads(locator.read_text(encoding="utf-8-sig")) if locator.is_file() else {}


def runtime(cli_hint, config):
    value = cli_hint or os.environ.get("DSH_HARNESS_EXE") or config.get("harness_exe")
    if not value:
        found = shutil.which("dsh.cmd")
        value = str(Path(found).resolve().parents[4] / "DeepSeek Harness.exe") if found else None
    if not value:
        raise ValueError("Set --harness-exe or DSH_HARNESS_EXE to the local DeepSeek Harness.exe.")
    exe = Path(os.path.expandvars(value)).expanduser().resolve(strict=True)
    resources = exe.parent / "resources"
    manifest = resources / "runtime/primary-runtime/runtime.json"
    build = json.loads(manifest.read_text(encoding="utf-8-sig"))
    if (build["desktopVersion"], build["platform"], build["arch"]) != (VERSION, "win32", "x64"):
        raise ValueError(f"Retest the worker before using it on a build other than Windows x64 {VERSION}.")
    cli = resources / "app.asar/dsh/node_modules/@deepseek-ai/dsh-desktop-host/lib/cli.js"
    if not exe.is_file() or not (resources / "app.asar").is_file():
        raise ValueError("The official DeepSeek Harness executable or app.asar is missing.")
    return exe, cli


def summarize(output, exit_code):
    session_id = None
    tools = {}
    final = None
    for line in output.splitlines():
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        if kind == "session":
            session_id = event.get("sessionId")
        elif kind == "tool_call":
            tools[event["callId"]] = {"tool": event["tool"], "status": "started"}
        elif kind == "tool_result" and event.get("callId") in tools:
            tools[event["callId"]]["status"] = event.get("status")
        elif kind == "final":
            final = event
    reason = ((final or {}).get("reason") or {}).get("kind")
    answer = (final or {}).get("text")
    if exit_code or reason != "completed" or not isinstance(answer, str) or not answer.strip():
        # Raw diagnostics can contain private configuration or bearer URLs.
        detail = re.sub(r"[^a-zA-Z0-9_/-]", "", reason or "unavailable")[:80]
        raise ValueError(f"Worker failed (exit {exit_code}, status {detail}). Session: {session_id or 'unavailable'}.")
    if session_id is None or final.get("sessionId") != session_id:
        raise ValueError("Could not match the completed answer to its Harness session.")
    return {"session_id": session_id, "status": reason, "tools": list(tools.values()), "answer": answer}


def notify_desktop(session_id, env):
    home = Path(env.get("DSH_HOME") or (Path.home() / ".dsh"))
    state = home / "storages" / "dsh-codex-desktop-trace" / "notices"
    state.mkdir(parents=True, exist_ok=True)
    nonce = uuid4().hex
    staging = state / (nonce + ".tmp")
    try:
        staging.write_text(json.dumps({"id": session_id, "nonce": nonce}), encoding="utf-8")
        staging.replace(state / (session_id + ".json"))
    finally:
        staging.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harness-exe", help="Override the path to the native Harness executable")
    parser.add_argument("--cwd", type=Path, required=True, help="Absolute project or fixture directory")
    parser.add_argument("--session-id", help="Continue an existing native Headless session in the same workspace")
    parser.add_argument("--role", help="Expert role for this delegation")
    parser.add_argument("--workspace-write", action="store_true",
                        help="Use native workspace-write for explicitly authorized project edits")
    parser.add_argument("--task-kind", choices=ROUTES, default="analysis",
                        help="Select the Harness mode, account model, and reasoning effort")
    parser.add_argument("--skill", action="append", default=[], help="Installed Harness Skill ID; repeat if needed")
    parser.add_argument("--timeout", type=int, default=300, help="Seconds to allow the local Harness worker")
    parser.add_argument("--task", help="Task text; omit to read UTF-8 text from stdin")
    args = parser.parse_args()
    if not args.cwd.is_absolute():
        raise ValueError("--cwd must be an absolute path.")
    cwd = args.cwd.resolve(strict=True)
    if not cwd.is_dir() or args.timeout <= 0:
        raise ValueError("The working directory must exist and the timeout must be positive.")
    if args.session_id and not re.fullmatch(r"session-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", args.session_id):
        raise ValueError("Use a native Harness session ID from an earlier Headless invocation.")
    for skill_id in args.skill:
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", skill_id):
            raise ValueError("Use the English kebab-case ID for each Harness Skill.")
    task = (args.task if args.task is not None else sys.stdin.buffer.read().decode("utf-8-sig")).strip()
    permission = "workspace-write" if args.workspace_write else "read-only"
    config = worker_config()
    language = config.get("language", "auto")
    if language not in ("auto", "zh-CN", "en"):
        raise ValueError("Use auto, zh-CN, or en for the Harness handoff language.")
    chinese = language == "zh-CN"
    if chinese:
        default_role = "开发实现执行员" if args.workspace_write else "只读资料核对员"
    else:
        default_role = "Implementation specialist" if args.workspace_write else "Read-only reviewer"
    role = (args.role if args.role is not None else default_role).strip()
    if not task or not role:
        raise ValueError("Supply a bounded nonempty task and expert role.")
    exe, cli = runtime(args.harness_exe, config)
    skills = " ".join(f"/{skill_id}" for skill_id in dict.fromkeys(args.skill))
    boundary = (
        "仅在当前工作区和任务明确列出的可写范围内实现，保留既有用户修改。"
        "在授权范围内连续完成任务，结束时统一报告修改文件、检查结果和未解决项。"
        "阻塞时说明缺项。提交、推送、发布、安装及其他副作用遵循本次授权。"
        if args.workspace_write else
        "仅在授权范围内只读核对，不写文件、不产生外部副作用。报告证据及不确定项。"
    )
    if not chinese:
        boundary = (
            "Implement only within the writable scope listed in the current workspace task. Preserve user edits. "
            "Report files, checks and open issues. Treat publishing, commits, installation and external calls as separate authorizations."
            if args.workspace_write else
            "Use only the authorized read-only scope. Report evidence and uncertainties. External calls require separate authorization."
        )
    language_rule = {
        "auto": "Follow the language of the user's task below, ignoring wrapper labels when choosing the language. "
                "Use it for session titles, actual child-agent prompts, and results.",
        "zh-CN": "默认使用简体中文写标题、实际发送给子专家的提示词和回传。用户对语言有明确要求时遵照要求。保留文件名、代码和工具名原文。",
        "en": "Use English for titles, child-agent prompts, and results unless the task explicitly requests another language. Keep filenames, code, and tool names as written.",
    }[language]
    prompt = "\n\n".join(part for part in [
        skills, f"专家角色：{role}" if chinese else f"Expert role: {role}", boundary, language_rule, task,
    ] if part)
    mode, model, effort = ROUTES[args.task_kind]
    env = {**os.environ, "ELECTRON_RUN_AS_NODE": "1", "DSH_PERMISSION_MODE": permission}
    # Codex Sites Git overrides are private to its own transport. Harness filters
    # KEY variables from shell environments, leaving an invalid Git config array.
    sites_keys = {
        f"{section}.https://{host}/backend-api/codex/sites/git/.{option}"
        for host in ("chatgpt.com", "chatgpt-staging.com")
        for section, option in (("credential", "helper"), ("credential", "useHttpPath"),
                                ("http", "proactiveAuth"), ("http", "followRedirects"))
    }
    count = env.get("GIT_CONFIG_COUNT", "")
    if count.isascii() and count.isdecimal() and len(count) < 5:
        indices = range(int(count))
        if indices and all(env.get(f"GIT_CONFIG_KEY_{i}") in sites_keys for i in indices):
            del env["GIT_CONFIG_COUNT"]
            for i in indices:
                env.pop(f"GIT_CONFIG_KEY_{i}")
                env.pop(f"GIT_CONFIG_VALUE_{i}", None)
    with tempfile.TemporaryDirectory(prefix="dsh-worker-") as temporary:
        patch = Path(temporary) / "route.patch.yml"
        write_overlay(patch, mode, model, effort)
        command = [str(exe), "--expose-internals", str(cli), "--profile", "headless",
                   "--patch", str(patch), "--permission-mode", permission, "--approval-policy", "never", "--json"]
        if args.session_id:
            command.extend(["--session-id", args.session_id])
        command.append("-")
        run = subprocess.run(command, cwd=cwd, env=env, input=prompt.encode("utf-8"),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=args.timeout)
    result = summarize(run.stdout.decode("utf-8-sig", errors="replace"), run.returncode)
    try:
        notify_desktop(result["session_id"], env)
    except OSError as error:
        print(f"Desktop trace refresh signal was not sent ({type(error).__name__}).", file=sys.stderr)
    result["route"] = {"task_kind": args.task_kind, "mode": mode, "provider": PROVIDER, "model": model,
                       "reasoning_effort": effort, "permission": permission}
    if args.workspace_write:
        result["workspace"] = str(cwd)
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    try:
        main()
    except subprocess.TimeoutExpired:
        sys.exit("DeepSeek Harness worker timed out before returning its answer.")
    except (OSError, ValueError, KeyError) as error:
        sys.exit(str(error))
