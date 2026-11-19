# Codex × DeepSeek Harness

在 Windows 上让 Codex 按任务自动选择 DeepSeek Harness 的模式、模型和推理等级，再回核结果。适合规则比对、批量读取和文档审查等只读任务。

| 组件 | 用途 |
|---|---|
| [Worker Skill](skills/deepseek-harness-worker/SKILL.md) | 启动一次性 Headless 任务并返回结构化结果 |
| [Orchestrator](launch.py) | 由 Codex 通过本机 MCP 派活、查看进度、查看轨迹及续聊 |
| [自动分派规则](codex-delegation-policy.md) | 根据任务选择执行入口和选档，限制交接内容并核对证据 |
| [桌面隐私补丁](privacy/desktop.patch.yml) | 可选地关闭桌面额外会话日志、反馈和产品遥测、外部思考过程翻译及反向委派工具 |

## 安装前准备

- Windows x64、Python 3.12+、Node.js 22+（同目录带 npm.cmd）以及 Git。
- 安装并登录 Codex 和官方 [DeepSeek Harness](https://www.deepseek.com/harness/)，本包适用于已验收的 **Harness 0.2.2-rc.5**。先打开 Harness 初始化桌面配置，完成登录后从托盘退出。
- 克隆或解压本仓库，再在仓库根目录打开 PowerShell。依赖缺失时，安装会从固定来源取得桥的指定提交和锁定依赖。

## 安装

先预演，然后添加 `--apply`。用实际可执行文件路径替换尖括号中的值。

```powershell
python .\install.py --harness-exe "<DeepSeek Harness.exe 的绝对路径>" --node-exe "<node.exe 的绝对路径>"
python .\install.py --harness-exe "<DeepSeek Harness.exe 的绝对路径>" --node-exe "<node.exe 的绝对路径>" --apply
```

| 选项 | 作用 |
|---|---|
| `--desktop-privacy` | 一并应用桌面隐私补丁。桌面退出后执行，已有补丁会留存本机备份。 |
| `--context-insights` | 为隔离 Web 安装固定的 `dsh-context 0.86.0`。该界面会查询公开元数据和已配置供应商的余额。 |
| `--share-harness-skills` | 把安装者自己的 Harness Skill 目录链接给隔离 Web。需要先核对该目录中的内容。 |

安装会把 Worker Skill 放入 Codex 用户 Skill 目录，在其配置根添加程序定位、`dsh_orchestrator` MCP 和一段自动分派规则。默认配置根是 `~/.codex`，支持 `CODEX_HOME`。隔离 Web 的启动器和本地数据位于其 `integrations/dsh-orchestrator`。启动器调用本机官方 Harness，复用安装者已登录的账号。遇到同名手改配置时，脚本停止并保留该文件。

## 使用与选档

新开 Codex 会话，正常描述任务。对无需实时观察的一次性任务，Codex 会优先使用 Worker Skill。需要实时进度、原生轨迹或续聊时走 Orchestrator。

| 任务 | 模式 | 模型 / 推理 |
|---|---|---|
| 查值或抽取明确字段 | 标准 | Flash / Low |
| 常规文档比对与日志归纳 | 标准 | Flash / High |
| 可并行的批量读取或汇总 | PTC | Flash / High |
| 多约束推断与证据裁决 | 标准 | Pro / High |

在 PowerShell 运行 `codex mcp get dsh_orchestrator` 可以查看 Codex 的注册。运行中，Codex 可以用 `dsh_status`、`dsh_wait` 和 `dsh_tail` 查状态与事件。需要看 Harness 网页时，运行下列命令，保持启动器窗口打开。启用上下文洞察后，在「上下文洞察 → 全部会话」按标题定位，再打开「轨迹」。

```powershell
$codexConfig = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
python (Join-Path $codexConfig 'integrations/dsh-orchestrator/launch.py') --view
```

## 三段专家协作示例

可以让 Codex 担任主管，用多个独立的 Harness 会话分阶段执行。每段由 Codex 指定角色、已安装的 Skill（需要时）、可读范围和验收要求。进度和证据通过各任务会话查看。

> 请做主管，分三段只读处理这项任务。1 是资料核对员，交付事实与来源。2 是方案专家，基于已验收的事实产出方案。3 是独立验收员，核对方案与原始要求。每段完成后先验收，再把下一段需要的结果交接。2 或 3 发现缺口时，向主管返回证据、影响和要补的内容。由主管决定是否用原会话续派给 1 或 2，原阶段补充后返回发现方复核，复核通过再继续。存在未解决的阻塞时说明原因和缺项。

上面的阶段交接由 Codex 负责。Harness 模型菜单里的「智能体团队协作」用于 Harness 自己会话内的团队调度，可以单独配置。

可在同一任务上使用 `dsh_followup` 补查。每次交接传递所需摘要、结论和证据引用。文件写入与权限升级按任务的实际授权处理。

## 合成验收

以下命令生成独立临时工作区。把输出的路径选为 Codex 新会话的工作区。

```powershell
$fixture = Join-Path $env:TEMP ("harness-smoke-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $fixture -ErrorAction Stop | Out-Null
11..22 | ForEach-Object {
    $state = if ($_ % 2) { "ready" } else { "hold" }
    "item-${_}:${_}:$state" | Set-Content -LiteralPath (Join-Path $fixture "part-$_.txt") -Encoding ASCII
}
$fixture
```

> 并行只读检查当前工作区的 12 个 part-*.txt，统计 ready 的条目数和数量合计。我要看到 Harness 实时进度和原生轨迹。抽查两条原始记录并汇报。

预期得到 **6 项，合计 96**。确认 Codex 主动调用 Orchestrator、执行权限为只读、任务完成且轨迹包含实际读取。模型与模式由 Codex 根据任务选择。验收后原件应与测试前相同。

## 数据边界

Headless 和隔离 Web 默认关闭额外会话日志与反馈遥测，任务权限固定为只读。云模型仍会收到执行所需的任务提示和结果。交接以本次明确授权的最小片段为准。需要内容完全留在本机的任务应使用本地离线模型和工具。[Harness 隐私政策](https://www.deepseek.com/harness/privacy/) · [官方会话日志说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/session/session-log-deepseek/README.md)

桌面插件、桌面 MCP、外部软件、账号和聊天历史由安装者自行配置。软件版本变化后，先用合成数据重验权限、路由和隐私行为。

## 回退

先退出相关 Codex 会话和 Harness 窗口。可通过 `codex mcp remove dsh_orchestrator` 停用注册，并只移除 `AGENTS.md` 中带本包起止标记的分派段。Worker Skill、程序定位、独立执行端和会话目录可以按需备份，确认后再移除。桌面隐私补丁曾被应用时，核对安装后是否有别的改动，再恢复备份或仅还原本包的隐私段。

## 固定来源

Orchestrator 由 [Fly2Kiana/Codex-DSH-Orchestrator](https://github.com/Fly2Kiana/Codex-DSH-Orchestrator) 的提交 `428c69f590d569b0c7cfbdb831bfa88beedc938b` 构建，正式安装由本机获取。Harness 和可选社区插件按各自上游条款使用。
