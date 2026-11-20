import { accessSync, constants } from "node:fs";
import { dirname, join, resolve, win32 } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const resources = join(dirname(process.execPath), "resources");
const bundled = join(resources, "app.asar", "dsh", "node_modules", "@deepseek-ai");
const nativeRunner = join(bundled, "dsh-sandbox-windows-acl", "lib", "runner.js");
const consoleNode = join(resources, "runtime", "primary-runtime", "dependencies", "node", "bin", "node.exe");
const extractedRunner = join(dirname(fileURLToPath(import.meta.url)), "node_modules",
  "@deepseek-ai", "dsh-sandbox-windows-acl", "lib", "runner.js");
const native = pkg => import(pathToFileURL(join(bundled, pkg, "lib", "index.js")).href);
const [{ LocalSubprocessRuntime }, { ENCODING_PREAMBLE }, { PWSH_PROMPT_SETUP }] = await Promise.all([
  native("dsh-subprocess-local"), native("dsh-pwsh-local"), native("dsh-terminal-bash"),
]);
const nativeBootstrap = ENCODING_PREAMBLE + PWSH_PROMPT_SETUP + "\r";
const bootstrap = "Set-Location -LiteralPath $env:DSH_READONLY_PTY_WORKSPACE -ErrorAction Stop; " +
  "function prompt { Write-Host -NoNewline ([char]27 + ']133;D;' + [int]$LASTEXITCODE + [char]7); 'dsh> ' }\r";

export default class CompatibleSandboxedPowerShell extends LocalSubprocessRuntime {
  async spawnTerminal(spec) {
    const argv = spec.argv;
    const boundary = argv.indexOf("--");
    const mode = argv.indexOf("--mode");
    const target = win32.basename(argv[boundary + 1] ?? "").toLowerCase();
    if (process.platform !== "win32" || boundary < 0 || mode < 0 ||
        argv[mode + 1] !== "read-only" || argv[0] !== process.execPath ||
        resolve(argv[1] ?? ".") !== nativeRunner || !["pwsh.exe", "powershell.exe"].includes(target)) {
      return super.spawnTerminal(spec);
    }
    accessSync(consoleNode, constants.R_OK);
    accessSync(extractedRunner, constants.R_OK);
    const shell = join(process.env.SystemRoot ?? "C:/Windows", "System32", "WindowsPowerShell", "v1.0", "powershell.exe");
    accessSync(shell, constants.R_OK);
    const handle = await super.spawnTerminal({
      ...spec,
      argv: [consoleNode, extractedRunner, ...argv.slice(2, boundary + 1), shell, ...argv.slice(boundary + 2)],
      env: { ...spec.env, DSH_READONLY_PTY_WORKSPACE: spec.cwd },
    });
    const write = handle.write.bind(handle);
    let setup = true;
    handle.write = data => {
      if (setup && data === nativeBootstrap) {
        setup = false;
        return write(bootstrap);
      }
      return write(data);
    };
    return handle;
  }
}
