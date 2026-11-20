# Codex + DeepSeek Harness

**English** · [简体中文](README.zh-CN.md)

Give Codex a task in plain language. It can handle a quick check, delegate a focused review, or coordinate several DeepSeek Harness experts. When you ask for an implementation, fix, or saved deliverable, Codex can delegate the work to Harness in the current project. Codex sets the scope and verifies the result.

Use it for scoped development work, release checks, document comparisons, and batch file reviews. The setup uses Windows x64, defaults to read-only delegation, and has been tested with **DeepSeek Harness 0.2.2-rc.5**.

> Audit this release packet against the approved rules. Verify the totals and cite the source rows. Choose any specialist reviews you need, keep the inputs read-only, and show me the final decision and its evidence.

In a synthetic run of that workflow, Codex audited the packet locally and assigned one Harness expert to review the same nine files independently. Both found that an approved correction brought one region from 85 to 79 units, one below its release gate. Codex verified the evidence and blocked the release.

## Architecture

![Codex coordinates direct work, Harness read-only reviews, and project edits, then verifies the delivered result](docs/architecture.en.png)

## Quick start

1. Install and sign in to Codex and [DeepSeek Harness](https://www.deepseek.com/harness/). Open Harness Desktop once to initialize its profile, then exit it from the system tray.
2. Install Python 3.12 or later, Node.js 22 or later with `npm.cmd` next to `node.exe`, and Git.
3. Clone or extract this repository and open PowerShell at its root. Replace the placeholders with the full executable paths. Preview the changes with the first command, then run the second to install.

```powershell
python .\install.py --harness-exe "<absolute path to DeepSeek Harness.exe>" --node-exe "<absolute path to node.exe>"
python .\install.py --harness-exe "<absolute path to DeepSeek Harness.exe>" --node-exe "<absolute path to node.exe>" --apply
```

4. Start a new Codex chat in the project you want to work on. Ask for a read-only review or request a [project change](#authorized-project-changes). The [synthetic smoke tests](#verify-with-synthetic-data) cover both routes.

Setup fetches the pinned bridge and its locked dependencies when needed. It uses `~/.codex` or your existing `CODEX_HOME`, backs up the Worker and policy when upgrading known versions, and preserves conflicting custom files. The isolated launcher and its local state live under `integrations/dsh-orchestrator` in that root. The launcher uses your installed Harness and its local sign-in.

| Installed component | What it does |
|---|---|
| [Worker Skill](skills/deepseek-harness-worker/SKILL.md) | Runs a one-off Headless task with read-only access or scoped workspace edits inferred from the request |
| [Orchestrator](launch.py) | Gives Codex a local MCP connection for delegation, progress, traces, and follow-ups |
| [Delegation policy](codex-delegation-policy.md) | Adds task routing, handoff rules, and verification criteria to Codex's user instructions |

### Optional install flags

| Flag | Behavior |
|---|---|
| `--context-insights` | Adds `dsh-context 0.86.0` to the isolated Web profile for browsing sessions and traces. The plugin requests public metadata and queries the configured provider for account balance. |
| `--share-harness-skills` | Links your existing Harness Skill directory into the isolated Web profile. Review the skills before exposing them to delegated tasks. |
| `--desktop-privacy` | Applies the [Desktop privacy overlay](privacy/desktop.patch.yml) while the app is closed and backs up an existing patch. The overlay disables additional session uploads, telemetry, cloud translation of reasoning, and reverse delegation to Codex. |

## How Codex delegates

Codex handles small checks directly and uses the Worker Skill for one-off delegation. It uses Orchestrator for read-only work that needs progress updates, a native trace, or follow-ups. The supplied policy defaults to Simplified Chinese for titles, handoffs, and results. Ask for a different language in your task when needed.

| Task | Harness mode | Model and reasoning |
|---|---|---|
| Look up values or extract specific fields | Standard | Flash / Low |
| Compare documents or summarize logs | Standard | Flash / High |
| Read, filter, or summarize a batch of independent inputs | PTC | Flash / High |
| Resolve conflicting evidence or evaluate interacting constraints | Standard | Pro / High |

### Authorized project changes

An ordinary request to implement a feature, fix a bug, or save a deliverable authorizes the edits needed to complete it within the current project. Codex decides whether to delegate and checks the project rules, existing changes, and allowed files. A separate write confirmation is only needed when the requested scope leaves a material authorization question. It passes the current project's absolute directory to the Headless Worker with `--cwd` and enables Harness's native `workspace-write` for that run. The expert completes the assignment and reports changed files, checks, and any blockers together. After the Worker finishes, Codex checks the files on disk, reviews the diff, and runs the relevant project checks before accepting the result.

Requests to inspect, review, analyze, or propose changes use read-only access by default. A user-specified read-only limit takes precedence. Orchestrator runs read-only and can review the completed work. Installs, commits, and publication each follow the task's authorization.

### Expert handoffs and corrections

Codex chooses the number of experts and their roles. Independent read-only stages can run in parallel. A stage that depends on another expert's findings starts after Codex has checked the supporting evidence. For each expert, Codex matches the role to the project rules and available skills, then defines the inputs, sources, expected deliverable, and checks in the handoff. Use the evidence in the result to verify which sources and skills the expert used.

In a separate synthetic test, the first expert counted 52 eligible units. The reviewer held the result because the release threshold still needed a source citation. Codex sent a follow-up to the first expert's original session, obtained the approved threshold of 50, and had the reviewer clear the correction before dispatching the independent final check. The final verdict passed by two units.

Orchestrator's `dsh_followup` keeps a correction in the original task. Handoffs carry the evidence and references the next expert needs. The Harness **Team Collaboration** switch controls workers within a single Harness session. The Codex-managed workflow coordinates across sessions with this switch off.

### Research when local guidance is missing

When the task permits internet access, Codex uses the available search tools to fill gaps in local rules or installed skills.

1. Look up the official specification or maintainer documentation with a generic public query.
2. Read the relevant community project's original documentation, source, or maintainer discussion. Record the version and license when considering reuse. Keep requirements from the specification distinct from the behavior of a particular implementation.
3. Continue the authorized task with verified sources. Include the links and the checks that support the result. Install, enable, import, or run third-party skills and scripts only with separate authorization.

A synthetic test exercised this path with eight JSON Pointer cases. Codex opened RFC 6901 and delegated an independent review. Harness used native search and page retrieval to inspect the RFC and community repositories. The read-only review matched the five expected values and three expected failures. Community sources were used as references, with the local skill list unchanged. [RFC 6901](https://www.rfc-editor.org/rfc/rfc6901.html)

## See progress and open the trace

To confirm the MCP registration, run `codex mcp get dsh_orchestrator`. While a task runs, Codex can use `dsh_status`, `dsh_wait`, and `dsh_tail` to read progress and events.

Orchestrator starts a Harness Web Host on `127.0.0.1` when needed. You can keep using Harness Desktop normally. Open the browser viewer when you want to inspect native traces from the bridge's separate local profile. Run the following command in PowerShell and keep the terminal open while you review.

```powershell
$codexConfig = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
python (Join-Path $codexConfig 'integrations/dsh-orchestrator/launch.py') --view
```

With Context Insights installed, open **Context Insights → All Sessions**, find the task by its title, and select **Trace**.

## Verify with synthetic data

### Read-only review

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

### Authorized file creation

Create a temporary project with a `requirements.txt` that asks for a Python function `total(count)`. The first three tickets cost 12 cents each, further tickets cost 8 cents each, and negative counts raise `ValueError`. Add an `original.txt` file to check that existing files are preserved. Open that project in a new Codex chat and send this request.

> Use requirements.txt to implement the ticket pricing function in tickets.py. Preserve the existing files. Verify the result and report the path you actually changed.

Check that the Headless Worker used `workspace-write`, Harness created `tickets.py` in that project, and Codex verified the output. In the synthetic test, the only new file was `tickets.py` and all six cases passed. Counts 0, 1, 3, 4, and 9 produced 0, 12, 36, 44, and 84 cents. A negative count raised `ValueError`.

## Data handling

Headless and isolated Web profiles disable additional session-log uploads and feedback telemetry by default. Delegated tasks default to Harness's native read-only permission. Authorized Headless changes use native workspace-write for that run. Cloud inference sends the prompt and context needed for the task. Supply excerpts you have authorized for that task. For work that must stay on the machine, use a verified local inference path and offline tools. [Harness privacy policy](https://www.deepseek.com/harness/privacy/) · [Official session-log documentation](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/session/session-log-deepseek/README.md)

Desktop plugins, desktop MCP servers, external programs, accounts, and chat histories are configured on each machine. After changing versions, use synthetic data to recheck permissions, routing, and privacy behavior.

## Roll back

Exit the relevant Codex chats and Harness windows. Run `codex mcp remove dsh_orchestrator` to remove the registration. Remove the managed delegation block between its start and end markers in `AGENTS.md`. Back up the Worker Skill, executable locator, isolated profile, and sessions before removing any data you no longer need.

To roll back a known upgrade, use the Worker and policy backups printed by setup. If you applied the Desktop privacy overlay, check for subsequent edits before restoring its backup, or undo just the marked privacy block.

## Pinned source

Setup builds Orchestrator from [Fly2Kiana/Codex-DSH-Orchestrator](https://github.com/Fly2Kiana/Codex-DSH-Orchestrator) at commit `428c69f590d569b0c7cfbdb831bfa88beedc938b`. Harness and optional community plugins remain subject to their upstream terms.
