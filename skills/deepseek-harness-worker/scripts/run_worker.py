"""Delegate one read-only expert task to DeepSeek Harness and return its result."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


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


def runtime(cli_hint):
    locator = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex")) / "deepseek-harness-worker.json"
    value = cli_hint or os.environ.get("DSH_HARNESS_EXE")
    if not value and locator.is_file():
        value = json.loads(locator.read_text(encoding="utf-8-sig"))["harness_exe"]
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harness-exe", help="Override the path to the native Harness executable")
    parser.add_argument("--cwd", type=Path, required=True, help="Absolute project or fixture directory")
    parser.add_argument("--role", default="只读技术核对员", help="Expert role for this delegation")
    parser.add_argument("--task-kind", choices=ROUTES, default="analysis",
                        help="Select the read-only Harness mode, account model, and reasoning effort")
    parser.add_argument("--skill", action="append", default=[], help="Installed Harness Skill ID; repeat if needed")
    parser.add_argument("--timeout", type=int, default=300, help="Seconds to allow the local Harness worker")
    parser.add_argument("--task", help="Task text; omit to read UTF-8 text from stdin")
    args = parser.parse_args()
    if not args.cwd.is_absolute():
        raise ValueError("--cwd must be an absolute path.")
    cwd = args.cwd.resolve(strict=True)
    if not cwd.is_dir() or args.timeout <= 0:
        raise ValueError("The working directory must exist and the timeout must be positive.")
    for skill_id in args.skill:
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", skill_id):
            raise ValueError("Use the English kebab-case ID for each Harness Skill.")
    task = (args.task if args.task is not None else sys.stdin.buffer.read().decode("utf-8-sig")).strip()
    if not task or not args.role.strip():
        raise ValueError("Supply a bounded nonempty task and expert role.")
    exe, cli = runtime(args.harness_exe)
    skills = " ".join(f"/{skill_id}" for skill_id in dict.fromkeys(args.skill))
    prompt = "\n\n".join(part for part in [
        skills, f"专家角色：{args.role.strip()}",
        "仅在授权范围内只读核对，不写文件、不产生外部副作用。报告证据及不确定项。",
        "默认以简体中文回复，自动生成会话标题时用简短中文概括。保留文件和工具的原名。任务指定其他语言时以任务为准。",
        task,
    ] if part)
    mode, model, effort = ROUTES[args.task_kind]
    env = {**os.environ, "ELECTRON_RUN_AS_NODE": "1", "DSH_PERMISSION_MODE": "read-only"}
    with tempfile.TemporaryDirectory(prefix="dsh-worker-") as temporary:
        patch = Path(temporary) / "route.patch.yml"
        write_overlay(patch, mode, model, effort)
        command = [str(exe), "--expose-internals", str(cli), "--profile", "headless",
                   "--patch", str(patch), "--permission-mode", "read-only", "--approval-policy", "never", "--json", "-"]
        run = subprocess.run(command, cwd=cwd, env=env, input=prompt.encode("utf-8"),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=args.timeout)
    result = summarize(run.stdout.decode("utf-8-sig", errors="replace"), run.returncode)
    result["route"] = {"task_kind": args.task_kind, "mode": mode, "provider": PROVIDER, "model": model,
                       "reasoning_effort": effort, "permission": "read-only"}
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    try:
        main()
    except subprocess.TimeoutExpired:
        sys.exit("DeepSeek Harness worker timed out before returning its answer.")
    except (OSError, ValueError, KeyError) as error:
        sys.exit(str(error))
