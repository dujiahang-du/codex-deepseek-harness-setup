"""Compatibility for the installed Windows x64 Harness rc.5 modes."""
from hashlib import sha256
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
RUNNER = Path("windows-readonly-pwsh")
PREVIOUS_SHELL_SHA = "93e6bf9bda0c91968bd0a1904d9f07cf6b4f92c6b6220f218b9444003ffdf930"

VISION_FILE = Path("dist/model-routing.js")
VISION_BASE_SHA = "57635281be49ebc2e37773e6e455543469dc62b79cee8821197e0e029868f30c"
VISION_BEFORE = '    return provider === "deepseek-official" && model.id === "deepseek-v4-flash-vision-exp";'
VISION_AFTER = (
    '    return (provider === "deepseek-account" && model.id === "deepseek-flash") ||\n'
    '        (provider === "deepseek-official" && model.id === "deepseek-v4-flash-vision-exp");'
)


def vision_route(data):
    # The rc.5 Gateway omits modalities. Permit only the verified account Flash pair.
    normalized = data.replace(b"\r\n", b"\n")
    known_base = normalized.replace(VISION_AFTER.encode(), VISION_BEFORE.encode(), 1)
    if sha256(known_base).hexdigest() != VISION_BASE_SHA:
        raise ValueError("The compiled Orchestrator vision route differs from the pinned build. It was kept.")
    return known_base.replace(VISION_BEFORE.encode(), VISION_AFTER.encode(), 1)


def unpack_runner(resources, output):
    versions = json.loads((HERE / RUNNER / "runner-packages.json").read_text(encoding="utf-8"))
    archive = resources / "app.asar"
    with archive.open("rb") as source:
        _, header_size, _, json_size = struct.unpack("<4I", source.read(16))
        tree = json.loads(source.read(json_size))
        packages = tree["files"]["dsh"]["files"]["node_modules"]["files"]

        def copy(entries, path):
            for name, item in entries.items():
                if name in (".", "..") or any(ch in name for ch in "/\\" + ":"):
                    raise ValueError("Invalid file name in installed Harness archive")
                relative = path / name
                if "files" in item:
                    copy(item["files"], relative)
                    continue
                if "link" in item:
                    raise ValueError(f"Unexpected archive link at {relative.as_posix()}")
                target = output / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if item.get("unpacked"):
                    shipped = archive.with_suffix(".asar.unpacked") / "dsh" / relative
                    shutil.copyfile(shipped, target)
                else:
                    source.seek(8 + header_size + int(item["offset"]))
                    target.write_bytes(source.read(item["size"]))

        for package, version in versions.items():
            entries = packages
            for component in package.split("/"):
                entries = entries[component]["files"]
            copy(entries, Path("node_modules") / package)
            version_file = output / "node_modules" / package / "package.json"
            actual = json.loads(version_file.read_text(encoding="utf-8-sig"))["version"]
            if actual != version:
                raise ValueError(f"{package}: expected {version}, found {actual}")



def prepare_shell(managed, exe):
    target = managed / RUNNER
    module = Path("compatible-pwsh.mjs")
    source = HERE / RUNNER / module
    if target.is_symlink() or target.is_junction():
        raise ValueError("The native PowerShell adapter directory is redirected. It was kept.")
    with tempfile.TemporaryDirectory(prefix="dsh-pwsh-stage-", dir=managed) as folder:
        staged = Path(folder) / target.name
        if not target.exists():
            staged.mkdir()
            shutil.copyfile(source, staged / module)
            unpack_runner(exe.parent / "resources", staged)
        selected = target if target.exists() else staged
        old_module = (selected / module).read_bytes()
        new_module = source.read_bytes()
        if old_module != new_module and sha256(old_module.replace(b"\r\n", b"\n")).hexdigest() != PREVIOUS_SHELL_SHA:
            raise ValueError("The existing PowerShell adapter differs from this package. It was kept.")
        node = exe.parent / "resources/runtime/primary-runtime/dependencies/node/bin/node.exe"
        runner = selected / "node_modules/@deepseek-ai/dsh-sandbox-windows-acl/lib/runner.js"
        probe = subprocess.run([node, runner, "--help"], capture_output=True, timeout=15)
        if b"windows-acl-run: missing value after --help" not in probe.stderr:
            raise ValueError("The extracted ACL runner failed its load check.")
        if selected == staged:
            staged.rename(target)
        elif old_module != new_module:
            staged.mkdir()
            updated = staged / module
            updated.write_bytes(new_module)
            updated.replace(target / module)
    return target / module


def shell_overlay(module):
    return (
        "\n# BEGIN Codex read-only persistent PowerShell\n"
        "- id: subprocess\n  disabled: true\n"
        "- insert:\n    - id: compatible-console-subprocess\n"
        f"      name: {json.dumps(module.as_posix(), ensure_ascii=False)}\n"
        "# END Codex read-only persistent PowerShell\n"
    )
