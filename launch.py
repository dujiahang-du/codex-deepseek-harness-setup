"""Start the pinned Orchestrator against an isolated, read-only Harness Web Host."""
import argparse
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import tempfile
from threading import Event as ThreadEvent, Thread
import time
import webbrowser


BASE = Path(__file__).resolve().parent
VERSION = "0.2.2-rc.5"


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def receive_startup(process):
    messages = queue.Queue(maxsize=16)
    found_ready = ThreadEvent()

    def drain():
        for line in process.stdout:
            if found_ready.is_set():
                continue
            try:
                messages.put(line[:8192], timeout=0.1)
            except queue.Full:
                continue

    Thread(target=drain, daemon=True).start()
    ready = time.monotonic() + 60
    while time.monotonic() < ready:
        try:
            line = messages.get(timeout=1)
        except queue.Empty:
            if process.poll() is not None:
                break
            continue
        found = re.search(r"^dsh web:\s+(http://127\.0\.0\.1:[1-9][0-9]*)/\?token=([A-Za-z0-9_-]{43})\s*$", line)
        if found:
            found_ready.set()
            return found.groups()
    raise RuntimeError("Harness did not announce its official loopback connection in time.")


def filtered_env():
    # Preserve Windows process essentials and PATH without forwarding provider credentials to the bridge.
    names = {"SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "PATHEXT", "PATH", "TEMP", "TMP", "USERPROFILE",
             "USERNAME", "HOMEDRIVE", "HOMEPATH", "LOCALAPPDATA", "APPDATA", "PROGRAMDATA", "PROGRAMFILES",
             "PROGRAMFILES(X86)", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE"}
    return {key: val for key, val in os.environ.items() if key.upper() in names}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--view", action="store_true", help="Open the native Harness UI to review stored sessions")
    args = cli.parse_args()
    if os.name != "nt":
        raise ValueError("This managed integration was validated on Windows x64 only.")
    cfg = json.loads((BASE / "settings.json").read_text(encoding="utf-8-sig"))
    exe = Path(cfg["harness_exe"]).resolve(strict=True)
    node = Path(cfg["node_exe"]).resolve(strict=True)
    resources = exe.parent / "resources"
    build = json.loads((resources / "runtime/primary-runtime/runtime.json").read_text(encoding="utf-8-sig"))
    if build["desktopVersion"] != VERSION or build["arch"] != "x64":
        raise ValueError(f"Retest the Gateway setup before using a version other than Windows x64 {VERSION}.")
    native_cli = resources / "app.asar/dsh/node_modules/@deepseek-ai/dsh-desktop-host/lib/cli.js"
    bridge_cli = (BASE / "upstream/dist/index.js").resolve(strict=True)
    dsh_home = BASE / "harness-home"
    shared_agents = Path(cfg["agents_home"]).resolve()
    host_env = {**filtered_env(), "ELECTRON_RUN_AS_NODE": "1", "DSH_HOME": str(dsh_home),
                "DSH_AGENTS_HOME": str(shared_agents), "DSH_PERMISSION_MODE": "read-only"}
    patch_args = []
    if not args.view:
        host_env["DSH_TRACE_PUBLISH_HOME"] = str(Path(cfg.get("desktop_home", Path.home() / ".dsh")).resolve())
        patch_args = ["--patch", str(BASE / "desktop-trace.patch.yml")]
    host = subprocess.Popen(
        [str(exe), "--expose-internals", str(native_cli), "--profile", "web", *patch_args, "--host", "127.0.0.1",
         "--port", "0", "--no-open"], cwd=BASE, env=host_env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf8", errors="replace",
    )
    try:
        origin, token = receive_startup(host)
        if args.view:
            webbrowser.open(origin + "/?token=" + token)
            print("Harness view opened. Keep this window running until you finish reviewing.", flush=True)
            return host.wait()
        with tempfile.TemporaryDirectory(prefix="bridge-") as worker_state:
            bridge_env = {**filtered_env(), "DSH_HOST_PROTOCOL": "gateway", "DSH_HOST_URL": origin,
                          "DSH_CONNECT_ORIGIN": origin, "DSH_CONNECT_TOKEN": token,
                          "DSH_BRIDGE_HOME": worker_state, "DSH_HOME": str(dsh_home), "DSH_HOST_VERSION": VERSION}
            bridge = subprocess.Popen([str(node), str(bridge_cli)], cwd=BASE, env=bridge_env)
            try:
                return bridge.wait()
            finally:
                stop(bridge)
    finally:
        stop(host)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print(f"dsh-orchestrator: {error}", file=sys.stderr)
        sys.exit(1)
