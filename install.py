"""Install the pinned Codex–Harness Orchestrator in a dedicated Windows profile."""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib


SOURCE = "https://github.com/Fly2Kiana/Codex-DSH-Orchestrator.git"
REVISION = "428c69f590d569b0c7cfbdb831bfa88beedc938b"
HERE = Path(__file__).resolve().parent
SERVER = "dsh_orchestrator"
TOOLS = ["dsh_delegate", "dsh_status", "dsh_wait", "dsh_tail", "dsh_followup", "dsh_release_workspace"]
POLICY_START = "<!-- BEGIN local dsh-orchestrator delegation -->"
POLICY_END = "<!-- END local dsh-orchestrator delegation -->"
UPGRADABLE_POLICIES = {
    "fdaf935ed774d1431738ed720645bdb0f2bfb94d2d9815e2f6ac91899b07e9f1",
    "281a075880aca9336a2d8599142989e287b88875fb6f22cdde837b40ee2c5907",
    "3ebbf4fe46e9dbc27a66e9ee578d11d739cf38ae0aca0d5ac870907e0e713213",
    "1589010322b0a70402bb5a8209301a40d2250ead73dae486502cc695a08dec8b",
    "b5725115daf03c8680b9ef240c87696752ff3ad06801012e04fe6d7cc4089b07",
}
WORKER_SOURCE = HERE / "skills/deepseek-harness-worker"
INSIGHTS = "dsh-context"
INSIGHTS_VERSION = "0.86.0"
INSIGHTS_ARCHIVE = f"{INSIGHTS}-{INSIGHTS_VERSION}.tgz"
INSIGHTS_ARCHIVE_HASH = "8792e42b833fc8086ff5605bf11041fdc6d9af1baa753a69781fa42f0d3fee73"
WEB_BUNDLES = ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-web-app"]
TRACE_MODULE = "desktop-trace-catalog.mjs"
TRACE_START = "# BEGIN Codex completed session refresh"
TRACE_END = "# END Codex completed session refresh"
PREVIOUS_LAUNCH_HASH = "6d2ce0f055458693e997e59805ea0d68b1e3543bc81895528b3f2fa3cd663e59"


def run(args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def install_source(target, offline_source, node):
    if not target.exists():
        with tempfile.TemporaryDirectory(prefix="dsh-source-", dir=target.parent) as directory:
            staged = Path(directory) / target.name
            run(["git", "init", "-q", staged])
            run(["git", "-C", staged, "fetch", "--depth", "1", offline_source or SOURCE, REVISION])
            run(["git", "-C", staged, "checkout", "--detach", "--quiet", "FETCH_HEAD"])
            staged.rename(target)
    commit = run(["git", "-C", target, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if commit != REVISION:
        raise ValueError("Existing Orchestrator checkout differs from the audited pin.")
    run(["git", "-C", target, "diff", "--quiet", "HEAD", "--"])
    if not (target / "dist/index.js").exists():
        run([node.with_name("npm.cmd"), "ci", "--ignore-scripts", "--prefer-offline", "--no-audit",
             "--no-fund", "--registry=https://registry.npmjs.org"], cwd=target)
        run([node, target / "node_modules/typescript/bin/tsc", "-p", "tsconfig.json"], cwd=target)


def patch_text(credentials, *, privacy=True):
    base = f"""- id: credentials
  name: '@deepseek-ai/dsh-credentials-local'
  config:
    path: {json.dumps(credentials.as_posix(), ensure_ascii=False)}
    watch: false
- id: agent-default-model
  name: '@deepseek-ai/dsh-agent-default-model'
  config:
    provider: deepseek-account
    model: deepseek-flash
    reasoningEffort: high
- id: ui-settings-general
  name: '@deepseek-ai/dsh-client-ui-settings-general'
  config:
    welcomeNoticeVersion: 2026-09-28.1
- insert:
    - id: client-ui-stats
      name: '@deepseek-ai/dsh-experimental-client-ui-stats'
"""
    return base + """- id: session-log-deepseek
  config:
    enabled: false
- id: session-telemetry-otel
  disabled: true
""" if privacy else base


def keep_or_create(path, text):
    if path.exists() and path.read_text(encoding="utf-8-sig") != text:
        raise ValueError(f"Existing file differs from the requested installation: {path}")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf8", newline="\n") as file:
            file.write(text)


def append(path, text, old):
    if (path.read_bytes() if path.exists() else b"") != old:
        raise ValueError(f"{path.name} changed during installation; retry without concurrent config edits.")
    with path.open("ab") as f:
        f.write(text.encode("utf8"))


def instruction_update(old, policy):
    text = old.decode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    block = newline + policy.replace("\n", newline) + newline
    counts = (text.count(POLICY_START), text.count(POLICY_END))
    if counts == (0, 0):
        return (text + newline * 2 + POLICY_START + block + POLICY_END + newline).encode("utf8")
    if counts != (1, 1) or text.index(POLICY_START) > text.index(POLICY_END):
        raise ValueError("The Codex delegation policy markers are ambiguous; they were kept.")
    before, body = text.split(POLICY_START, 1)
    current, after = body.split(POLICY_END, 1)
    normalized = current.replace("\r\n", "\n").strip()
    if normalized == policy:
        return old
    if sha256(normalized.encode("utf8")).hexdigest() in UPGRADABLE_POLICIES:
        return (before + POLICY_START + block + POLICY_END + after).encode("utf8")
    raise ValueError("The existing Codex delegation policy differs from this package. It was kept.")


def replace_instruction(path, old, updated):
    if (path.read_bytes() if path.exists() else b"") != old:
        raise ValueError(f"{path.name} changed during installation; retry without concurrent config edits.")
    with tempfile.TemporaryDirectory(prefix="dsh-policy-", dir=path.parent) as directory:
        staged = Path(directory) / path.name
        staged.write_bytes(updated)
        if os.name != "nt" or not path.exists():
            staged.replace(path)
            return
        # Windows moves take the replacement's ACL. Keep the destination ACL
        # so existing read-only sandbox access survives a knowledge-base update.
        import ctypes
        from ctypes import wintypes

        replace_file = ctypes.WinDLL("kernel32", use_last_error=True).ReplaceFileW
        replace_file.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                 wintypes.DWORD, wintypes.LPVOID, wintypes.LPVOID)
        replace_file.restype = wintypes.BOOL
        if not replace_file(str(path), str(staged), None, 0, None, None):
            raise ctypes.WinError(ctypes.get_last_error())


PREVIOUS_WORKER_FILE_HASHES = {
    Path("SKILL.md"): {"5a83332458469e3c28a77813484f350d31c84c403140151b0f12792a29af5df4", "783bc2b9a3ecd607258e4aae46fcc93ad933b3401d88473ea7715ec703297d9b", "0306434a78b4e3159e98cfdfebf2898e9da936ea1712b0b435adaa3ad3123815"},
    Path("agents/openai.yaml"): {"82459be0225d90a6716537aad3776e4289159b3b4f211ef67d4041b60dd0865c"},
    Path("scripts/run_worker.py"): {"ec5a16282a9882366bf73cacd9ca934c5cc2b84344dd92cfc7ee1123ce75c0ef", "3607caa5cdfe738804e3d75d01d35745e1f38146e3a989f465837c3740ea4491", "4b7208d6462516fb686540e07c8a68cb83d9d123ceb0f689d20ee5fb1bc6a375"},
}


def worker_files(root):
    paths = list(root.rglob("*"))
    if any(p.is_symlink() or p.is_junction() for p in paths):
        raise ValueError("The Codex worker contains redirected files. It was kept.")
    return {p.relative_to(root): p.read_bytes() for p in paths if p.is_file()}


def worker_plan(source, codex, exe):
    source = source.resolve(strict=True)
    expected = worker_files(source)
    required = {Path("SKILL.md"), Path("agents/openai.yaml"), Path("scripts/run_worker.py"),
                Path("scripts/account.patch.yml")}
    if not required <= expected.keys():
        raise ValueError("The setup package lacks the complete Codex worker Skill.")
    target = codex / "skills/deepseek-harness-worker"
    locator = codex / "deepseek-harness-worker.json"
    if any(p.is_symlink() or p.is_junction() for p in (target.parent, target, locator)):
        raise ValueError("The Codex worker destination or locator is redirected. It was kept.")
    current = worker_files(target) if target.is_dir() else None
    if target.exists() and current != expected:
        if current is None or current.keys() != expected.keys() or any(
            sha256(data.replace(b"\r\n", b"\n")).hexdigest() not in PREVIOUS_WORKER_FILE_HASHES.get(relative, ())
            for relative, data in current.items()
            if data.replace(b"\r\n", b"\n") != expected[relative].replace(b"\r\n", b"\n")
        ):
            raise ValueError("The existing Codex worker Skill differs from the setup package. It was kept.")
    if locator.exists():
        saved_locator = json.loads(locator.read_text(encoding="utf-8-sig"))
        if (not isinstance(saved_locator, dict) or set(saved_locator) != {"harness_exe"}
                or not isinstance(saved_locator["harness_exe"], str)
                or Path(saved_locator["harness_exe"]).resolve() != exe):
            raise ValueError("The existing Codex worker locator differs from the selected Harness. It was kept.")
    return target, locator, expected, current


def restore_worker(plan, exe):
    target, locator, expected, current = plan
    if target.exists() != (current is not None) or (current is not None and worker_files(target) != current):
        raise ValueError("The Codex worker Skill changed during installation. It was kept.")
    if current is None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="dsh-worker-", dir=target.parent) as directory:
            stage = Path(directory) / target.name
            for relative, data in expected.items():
                file = stage / relative
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(data)
            stage.rename(target)
    elif current != expected:
        backup = target.parent.parent / "integrations/dsh-orchestrator" / (
            "backup-worker-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        )
        backup.mkdir(parents=True)
        for relative, data in current.items():
            file = backup / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(data)
        for relative, data in expected.items():
            if data != current[relative]:
                replace_instruction(target / relative, current[relative], data)
        print(f"Previous Codex Worker: {backup}")
    if not locator.exists():
        keep_or_create(locator, json.dumps({"harness_exe": exe.as_posix()}, ensure_ascii=False) + "\n")


def link_skills(target, source):
    if not os.path.lexists(target):
        target.parent.mkdir(parents=True, exist_ok=True)
        for path in (target, source):
            if any(c in str(path) for c in '%!"&|<>^\n\r'):
                raise ValueError("Skill junction paths contain command-shell metacharacters.")
        run(["cmd.exe", "/d", "/c", "mklink", "/J", target, source])
    if target.resolve() != source.resolve():
        raise ValueError("The existing worker Skill directory points somewhere else.")


def install_insights(profile, exe, dsh_home):
    cli = exe.parent / "resources/runtime/cli/bin/dsh.cmd"
    if not cli.is_file():
        raise ValueError("The official bundled CLI is required for Context Insights.")
    bundled = HERE / "vendor" / INSIGHTS_ARCHIVE
    saved = profile / INSIGHTS_ARCHIVE
    spec = f"{INSIGHTS}@{INSIGHTS_VERSION}"
    if bundled.is_file() or saved.is_file():
        if saved.is_symlink():
            raise ValueError("The saved Context Insights package is redirected. It was kept.")
        data = (saved if saved.is_file() else bundled).read_bytes()
        if sha256(data).hexdigest() != INSIGHTS_ARCHIVE_HASH:
            raise ValueError("The Context Insights package checksum differs from the pinned distribution.")
        if not saved.exists():
            replace_instruction(saved, b"", data)
        spec = "./" + INSIGHTS_ARCHIVE
    run([cli, "plugin", "--profile", profile.name, "add", spec,
         "--save-exact", "--ignore-scripts", "--registry=https://registry.npmjs.org"],
        cwd=profile, env={**os.environ, "DSH_HOME": str(dsh_home)})


def pinned_insights_spec(profile, value):
    if value in (None, INSIGHTS_VERSION):
        return True
    if not isinstance(value, str) or not value.startswith("file:"):
        return False
    saved = profile / INSIGHTS_ARCHIVE
    return not saved.is_symlink() and (profile / value[5:]).resolve() == saved.resolve()


def configure_web(profile, exe, dsh_home, add_insights):
    manifest = profile / "package.json"
    if not manifest.exists():
        keep_or_create(manifest, json.dumps({
            "name": "codex-harness-worker-profile", "private": True,
            "dsh": {"profile": {"bundles": WEB_BUNDLES}},
        }, indent=2) + "\n")
    info = json.loads(manifest.read_text(encoding="utf-8-sig"))
    if not set(WEB_BUNDLES) <= set(info["dsh"]["profile"]["bundles"]):
        raise ValueError("The managed Web profile lacks the official base bundles.")
    installed = info.get("dependencies", {}).get(INSIGHTS)
    if add_insights and not pinned_insights_spec(profile, installed):
        raise ValueError("The installed Context Insights version differs from the pin.")
    if add_insights and (installed is None or not (profile / "node_modules" / INSIGHTS / "package.json").is_file()):
        install_insights(profile, exe, dsh_home)


def desktop_insights_plan(profile):
    manifest = profile / "package.json"
    if any(p.is_symlink() or p.is_junction() for p in (profile, manifest)):
        raise ValueError("The Desktop profile is redirected. It was kept.")
    if not manifest.is_file():
        raise ValueError("Open the Desktop app once to initialize its profile.")
    info = json.loads(manifest.read_text(encoding="utf-8-sig"))
    if not set(WEB_BUNDLES) <= set(info["dsh"]["profile"]["bundles"]):
        raise ValueError("The Desktop profile lacks the official base bundles.")
    installed = info.get("dependencies", {}).get(INSIGHTS)
    package = profile / "node_modules" / INSIGHTS / "package.json"
    actual = json.loads(package.read_text(encoding="utf-8-sig"))["version"] if package.is_file() else None
    if not pinned_insights_spec(profile, installed) or actual not in (None, INSIGHTS_VERSION):
        raise ValueError(f"Desktop Context Insights must use {INSIGHTS_VERSION}. The existing plugin was kept.")
    return installed is None or actual is None


def configure_desktop_insights(profile, exe, daily, install_plugin):
    if install_plugin:
        install_insights(profile, exe, daily)
        if desktop_insights_plan(profile):
            raise ValueError("The pinned Desktop Context Insights package did not finish installing.")
    manifest = profile / "package.json"
    original = manifest.read_bytes()
    info = json.loads(original.decode("utf-8-sig"))
    bundles = info["dsh"]["profile"]["bundles"]
    if INSIGHTS not in bundles:
        bundles.append(INSIGHTS)
        replace_instruction(manifest, original, (json.dumps(info, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def desktop_plan(daily):
    path = daily / "profiles/desktop/cordis.patch.yml"
    manifest = path.parent / "package.json"
    if not manifest.is_file():
        raise ValueError("Open the Desktop app once to initialize its profile.")
    if any(p.is_symlink() or p.is_junction() for p in (path.parent, path)):
        raise ValueError("The Desktop configuration is redirected. It was kept.")
    guard = (HERE / "privacy/desktop.patch.yml").read_text(encoding="utf8")
    bundles = json.loads(manifest.read_text(encoding="utf-8-sig"))["dsh"]["profile"]["bundles"]
    optional = {
        "@deepseek-ai/dsh-experimental-cot-translation-bundle": "cot-translation",
        "@deepseek-ai/dsh-subagent-codex": "tool-subagent-codex",
    }
    for bundle, row in optional.items():
        if bundle not in bundles:
            guard = guard.replace(f"- id: {row}\n  disabled: true\n", "")
    old = path.read_bytes() if path.exists() else b""
    text = old.decode("utf-8-sig").replace("\r\n", "\n")
    if text.count(guard) == 1:
        remaining = text.replace(guard, "", 1)
        keys = [line.partition(":")[2].strip() for line in guard.splitlines() if line.startswith("- id:")]
        if any(key in line for key in keys for line in remaining.splitlines() if not line.lstrip().startswith("#")):
            raise ValueError("The Desktop privacy block has a conflicting entry. It was kept.")
        return path, old, old
    if "# BEGIN Harness privacy guard" in text or "# END Harness privacy guard" in text:
        raise ValueError("An existing Desktop privacy block differs. It was kept.")
    keys = [line.partition(":")[2].strip() for line in guard.splitlines() if line.startswith("- id:")]
    for key in keys:
        if any(key in line for line in text.splitlines() if not line.lstrip().startswith("#")):
            raise ValueError("A Desktop privacy entry already exists. Review that entry before applying the overlay.")
    if text.strip() in ("[]", "---\n[]"):
        text = ""
    if text.strip() and not any(line.lstrip().startswith("- ") for line in text.splitlines()):
        if any(line and not line.startswith("#") for line in (l.strip() for l in text.splitlines())):
            raise ValueError("Expected a Desktop Cordis patch sequence.")
    prefix = text.rstrip()
    return path, old, ((prefix + "\n\n" if prefix else "") + guard).encode("utf8")


def trace_overlay(module, plugin_id="codex-desktop-trace-catalog"):
    name = json.dumps(module.as_posix(), ensure_ascii=False)
    return f"- insert:\n  - id: {plugin_id}\n    name: {name}\n"


def trace_plan(daily, managed, settings, privacy):
    module = managed / TRACE_MODULE
    overlay = managed / "desktop-trace.patch.yml"
    launch = managed / "launch.py"
    settings_file = managed / "settings.json"
    desktop = daily / "profiles/desktop/cordis.patch.yml"
    if any(p.is_symlink() or p.is_junction() for p in (managed, desktop.parent, module, overlay, launch, settings_file, desktop)):
        raise ValueError("A trace configuration path is redirected. It was kept.")

    current = trace_overlay(module)
    legacy = {trace_overlay(path, "codex-desktop-trace") for path in (managed / "desktop-trace.mjs", module)}
    settings_text = json.dumps(settings, ensure_ascii=False, indent=2) + "\n"
    previous_settings = {key: value for key, value in settings.items() if key != "desktop_home"}
    files = []
    for path, new in (
        (module, (HERE / TRACE_MODULE).read_bytes()), (launch, (HERE / "launch.py").read_bytes()),
        (overlay, current.encode("utf-8")), (settings_file, settings_text.encode("utf-8")),
    ):
        old = path.read_bytes() if path.exists() else None
        if old == new:
            continue
        if old is not None:
            normalized = old.decode("utf-8-sig").replace("\r\n", "\n")
            known = (
                path == launch and sha256(normalized.encode("utf-8")).hexdigest() == PREVIOUS_LAUNCH_HASH
                or path == overlay and normalized in legacy | {current}
                or path == settings_file and json.loads(normalized) in (settings, previous_settings)
                or path in (launch, module) and normalized.encode("utf-8") == new
            )
            if not known:
                raise ValueError(f"The existing trace setup file differs: {path}. It was kept.")
        files.append((path, old, new))

    old = desktop.read_bytes() if desktop.exists() else None
    source = desktop_plan(daily)[2] if privacy else old or b""
    text = source.decode("utf-8-sig").replace("\r\n", "\n")
    mark = TRACE_START + "\n" + current + TRACE_END
    counts = text.count(TRACE_START), text.count(TRACE_END)
    if counts == (0, 0):
        if "codex-desktop-trace" in text:
            raise ValueError("An unmanaged Desktop trace registration already exists.")
        if text.strip() in ("[]", "---\n[]"):
            text = ""
        if any(line.strip() and not line.lstrip().startswith("#") for line in text.splitlines()):
            visible = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
            if not visible.lstrip().removeprefix("---\n").lstrip().startswith("- ") or "\n..." in visible:
                raise ValueError("Expected a Desktop Cordis patch sequence. It was kept.")
        prefix = text.rstrip()
        updated = (prefix + "\n\n" if prefix else "") + mark + "\n"
    elif counts == (1, 1) and text.index(TRACE_START) < text.index(TRACE_END):
        before, rest = text.split(TRACE_START, 1)
        existing, after = rest.split(TRACE_END, 1)
        if existing.lstrip("\n") not in legacy | {current}:
            raise ValueError("The managed Desktop trace block was customized. It was kept.")
        updated = before + mark + after
    else:
        raise ValueError("The Desktop trace block markers are ambiguous. They were kept.")
    if old and b"\r\n" in old:
        updated = updated.replace("\n", "\r\n")
    new = updated.encode("utf-8-sig" if old and old.startswith(b"\xef\xbb\xbf") else "utf-8")
    if new != old:
        files.append((desktop, old, new))
    return files


def restore_trace(plan, managed):
    backup = managed / ("backup-trace-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    for path, old, _ in plan:
        if (path.read_bytes() if path.exists() else None) != old:
            raise ValueError(f"{path} changed during installation. It was kept.")
        if old is not None:
            backup.mkdir(exist_ok=True)
            shutil.copy2(path, backup / path.name)
    for path, old, new in plan:
        replace_instruction(path, old or b"", new)
    if backup.exists():
        print(f"Previous trace setup and Desktop patch: {backup}", flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--harness-exe", required=True, type=Path)
    p.add_argument("--node-exe", default=shutil.which("node.exe"), type=Path)
    p.add_argument("--audited-checkout", type=Path, help="Optional local Git source with the exact pinned commit")
    p.add_argument("--context-insights", action="store_true", help="Also install Context Insights in the optional Web viewer")
    p.add_argument("--share-harness-skills", action="store_true", help="Expose your existing Harness Skills to the isolated host")
    p.add_argument("--desktop-privacy", action="store_true", help="Also apply the privacy overlay to the signed-in Desktop profile")
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    if os.name != "nt":
        raise ValueError("Use this installation only on Windows x64.")
    if args.node_exe is None:
        raise ValueError("Specify the absolute Node.js executable with --node-exe.")
    exe = args.harness_exe.resolve(strict=True)
    node = args.node_exe.resolve(strict=True)
    runtime = json.loads((exe.parent / "resources/runtime/primary-runtime/runtime.json").read_text(encoding="utf8"))
    if (runtime["desktopVersion"], runtime["platform"], runtime["arch"]) != ("0.2.2-rc.5", "win32", "x64"):
        raise ValueError("This integration was tested only against Windows x64 Harness 0.2.2-rc.5.")
    codex = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    daily = Path(os.environ.get("DSH_HOME") or Path.home() / ".dsh")
    credentials = daily / ".credentials.yaml"
    if not credentials.is_file():
        raise ValueError("Open the Desktop app and complete DeepSeek sign-in first.")
    skills_source = daily / "skills"
    if args.share_harness_skills and not skills_source.is_dir():
        raise ValueError("The requested Desktop Skill folder does not exist.")
    worker = worker_plan(WORKER_SOURCE, codex, exe)
    managed = codex / "integrations/dsh-orchestrator"
    agents = managed / "agents-home"
    dsh_home = managed / "harness-home"
    profile = dsh_home / "profiles/web"
    desktop_profile = daily / "profiles/desktop"
    launch = managed / "launch.py"
    cfg = codex / "config.toml"
    instructions = codex / "AGENTS.md"
    if cfg.is_symlink() or instructions.is_symlink():
        raise ValueError("Codex configuration is redirected; review the target before writing.")
    old_cfg = cfg.read_bytes() if cfg.exists() else b""
    old_instruction = instructions.read_bytes() if instructions.exists() else b""
    existing = tomllib.loads(old_cfg.decode("utf-8-sig")).get("mcp_servers", {}).get(SERVER)
    expected = {"command": Path(sys.executable).as_posix(), "args": [launch.as_posix()],
                "startup_timeout_sec": 70, "tool_timeout_sec": 75, "enabled_tools": TOOLS}
    if existing is not None and existing != expected:
        raise ValueError("The existing dsh_orchestrator MCP configuration differs; it was kept.")
    policy = (HERE / "codex-delegation-policy.md").read_text(encoding="utf8").strip()
    updated_instruction = instruction_update(old_instruction, policy)
    policy_needed = updated_instruction != old_instruction
    settings = {"harness_exe": exe.as_posix(), "node_exe": node.as_posix(), "agents_home": agents.as_posix()}
    if daily.resolve() != (Path.home() / ".dsh").resolve():
        settings["desktop_home"] = daily.resolve().as_posix()
    install_plugin = desktop_insights_plan(desktop_profile)
    trace = trace_plan(daily, managed, settings, args.desktop_privacy)
    print(f"Pin {REVISION}; isolated host and visible sessions: {dsh_home}", flush=True)
    print(f"Targets: {cfg.name} (MCP), {instructions.name} (automatic delegation), {managed}", flush=True)
    print(f"Worker Skill and executable locator: {worker[0]}, {worker[1]}", flush=True)
    print(f"Desktop Context Insights {INSIGHTS_VERSION}: {'install' if install_plugin else 'reuse'}", flush=True)
    print(f"Desktop trace setup: {len(trace)} file update(s); optional Web viewer: {args.context_insights}", flush=True)
    if not args.apply:
        print("Plan only. Use --apply to install.")
        return

    managed.mkdir(parents=True, exist_ok=True)
    agents.mkdir(exist_ok=True)
    install_source(managed / "upstream", args.audited_checkout, node)
    sandbox_skills = dsh_home / "skills"
    if args.share_harness_skills:
        link_skills(sandbox_skills, skills_source)
    elif os.path.lexists(sandbox_skills):
        print("Existing managed Skill directory is present. Review its contents before delegating.")
    configure_web(profile, exe, dsh_home, args.context_insights)
    patch = profile / "cordis.patch.yml"
    current = patch.read_text(encoding="utf-8-sig") if patch.exists() else ""
    configured = patch_text(credentials)
    if current != configured:
        if current != patch_text(credentials, privacy=False) and any(
            line.strip() not in ("", "[]") and not line.lstrip().startswith("#") for line in current.splitlines()
        ):
            raise ValueError("The worker profile patch has other settings and was kept.")
        replace_instruction(patch, patch.read_bytes() if patch.exists() else b"", configured.encode("utf8"))
    configure_desktop_insights(desktop_profile, exe, daily, install_plugin)
    restore_trace(trace, managed)
    restore_worker(worker, exe)
    if existing is None or policy_needed:
        backup = managed / ("backup-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
        backup.mkdir()
        for current_file in [cfg, instructions]:
            if current_file.exists():
                shutil.copy2(current_file, backup / current_file.name)
        if existing is None:
            block = "\n\n" + f"[mcp_servers.{SERVER}]\n" + "\n".join(
                f"{key} = {json.dumps(value, ensure_ascii=False)}" for key, value in expected.items()
            ) + "\n"
            assert tomllib.loads(old_cfg.decode("utf-8-sig") + block)["mcp_servers"][SERVER] == expected
            append(cfg, block, old_cfg)
        if policy_needed:
            replace_instruction(instructions, old_instruction, updated_instruction)
        print(f"Backups: {backup}")
    print("Codex registration and automatic delegation policy are installed.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
