# Codex × DeepSeek Harness

A Windows setup for Codex-managed, read-only delegation to DeepSeek Harness. Codex chooses the execution mode, model, and reasoning level according to the task, then checks the evidence and result. Typical uses include checking rules, batch-reading files, and reviewing documents.

| Component | Purpose |
|---|---|
| [Worker Skill](skills/deepseek-harness-worker/SKILL.md) | Runs a one-off Headless task and returns a structured result |
| [Orchestrator](launch.py) | Provides a local MCP endpoint for delegation, progress, traces, and follow-up tasks |
| [Delegation policy](codex-delegation-policy.md) | Defines routing, data handoff, and acceptance criteria |
| [Desktop privacy overlay](privacy/desktop.patch.yml) | Optionally disables additional session logs, telemetry, cloud translation of reasoning, and reverse delegation to Codex |

## Before you install

- Use Windows x64 with Python 3.12 or later, Node.js 22 or later with npm.cmd in the same folder, and Git.
- Install and sign in to Codex and [DeepSeek Harness](https://www.deepseek.com/harness/). This setup has been validated with **Harness 0.2.2-rc.5**. Open Harness once to initialize the Desktop profile, sign in, and exit it from the system tray.
- Clone or extract this repository and open PowerShell at its root. Setup fetches the pinned bridge revision and locked dependencies when needed.

## Install

Replace the paths in angle brackets with your own executable paths. Preview the changes first, then apply them.

```powershell
python .\install.py --harness-exe "<absolute path to DeepSeek Harness.exe>" --node-exe "<absolute path to node.exe>"
python .\install.py --harness-exe "<absolute path to DeepSeek Harness.exe>" --node-exe "<absolute path to node.exe>" --apply
```

| Option | Behavior |
|---|---|
| `--desktop-privacy` | Applies the Desktop overlay while the app is closed. An existing patch is backed up locally. |
| `--context-insights` | Installs the optional `dsh-context 0.86.0` plugin in the isolated Web profile. It requests public metadata and queries the configured provider for account balance. |
| `--share-harness-skills` | Links your existing Harness Skill directory into the isolated Web profile. Review that directory before sharing it with tasks. |

Setup installs the Worker Skill and executable locator, registers the `dsh_orchestrator` MCP, and adds a managed delegation section to Codex's user instructions. The default Codex config root is `~/.codex`. Setup also supports `CODEX_HOME`. The isolated Web launcher and local state live under `integrations/dsh-orchestrator` in that root. The launcher uses your installed Harness and its local sign-in. Conflicting custom files are preserved and reported.

## Delegate tasks

Start a new Codex chat and describe the task normally. Codex favors the Worker Skill for one-off tasks. For real-time progress, native traces, or follow-ups, it uses Orchestrator. The supplied policy defaults to Simplified Chinese for titles, handoffs, and results. Specify a different language in the task when needed.

| Task | Harness mode | Model and reasoning |
|---|---|---|
| Look up values or extract specific fields | Standard | Flash / Low |
| Compare documents or summarize logs | Standard | Flash / High |
| Read or summarize independent items in parallel | PTC | Flash / High |
| Resolve conflicting evidence or evaluate multiple interacting constraints | Standard | Pro / High |

Run `codex mcp get dsh_orchestrator` in PowerShell to inspect the Codex registration. During a task, Codex can use `dsh_status`, `dsh_wait`, and `dsh_tail` to observe progress and events.

To open the Harness Web interface, run the following command and keep the launcher window open. If Context Insights is installed, find the session by title under **Context Insights → All Sessions**, then select **Trace**.

```powershell
$codexConfig = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
python (Join-Path $codexConfig 'integrations/dsh-orchestrator/launch.py') --view
```

## Run a three-stage expert team

Codex can supervise separate Harness sessions, assign expert roles and installed Skills as needed, and define each stage's read-only scope and acceptance criteria.

> Supervise this read-only task in three stages. Expert 1 collects facts and cites the source. Expert 2 develops a proposal from the accepted facts. Expert 3 independently verifies the proposal against the original requirements. Check each result before handing the required evidence to the next expert. If Expert 2 or 3 finds missing evidence or a conflict, ask them to report the evidence, its impact, and the requested correction. Decide whether to send a follow-up to the original expert. Have the reporting expert check the correction before moving forward. Report unresolved blockers with the evidence still needed.

Codex manages the handoff across these sessions. The Team Collaboration option in the Harness model menu controls how Harness organizes workers within its own session. Use `dsh_followup` for a correction or additional review in the original task. Keep each handoff to the required summary and evidence references. File writes and permission changes follow the authorization for the task.

## Verify with synthetic data

Generate a temporary workspace and select the printed path when starting a new Codex chat.

```powershell
$fixture = Join-Path $env:TEMP ("harness-smoke-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $fixture -ErrorAction Stop | Out-Null
11..22 | ForEach-Object {
    $state = if ($_ % 2) { "ready" } else { "hold" }
    "item-${_}:${_}:$state" | Set-Content -LiteralPath (Join-Path $fixture "part-$_.txt") -Encoding ASCII
}
$fixture
```

> Read the 12 part-*.txt files in this workspace in parallel with read-only access. Count the ready rows and sum their quantities. Show Harness progress and the native trace, then cross-check two source rows and report the result.

The expected result is **6 ready items totaling 96**. Verify that Codex initiated the delegation, the task completed as read-only, and the trace shows the source files being read. Codex selects the actual mode and model. Verify the input files match their pre-test contents.

## Data handling

Headless and isolated Web profiles disable additional session-log uploads and feedback telemetry by default. Delegated tasks use Harness's native read-only permission. Cloud inference sends the prompt and context needed for the task. Supply only the excerpts that you authorize for that task. Use a local model and offline tools when the content must stay on the machine. [Harness privacy policy](https://www.deepseek.com/harness/privacy/) · [Official session-log documentation](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/session/session-log-deepseek/README.md)

Desktop plugins, desktop MCP servers, external programs, accounts, and chat histories are configured on each machine. After changing versions, use synthetic data to recheck permissions, routing, and privacy behavior.

## Roll back

Exit the relevant Codex chats and Harness windows. Run `codex mcp remove dsh_orchestrator` to remove the registration. Remove the managed delegation block between its start and end markers in `AGENTS.md`. Back up the Worker Skill, executable locator, isolated profile, and sessions before removing any data you no longer need.

If you applied the Desktop privacy overlay, check for subsequent edits before restoring its backup, or undo just the marked privacy block.

## Pinned source

Setup builds Orchestrator from [Fly2Kiana/Codex-DSH-Orchestrator](https://github.com/Fly2Kiana/Codex-DSH-Orchestrator) at commit `428c69f590d569b0c7cfbdb831bfa88beedc938b`. Harness and optional community plugins remain subject to their upstream terms.
