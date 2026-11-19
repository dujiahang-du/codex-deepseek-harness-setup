---
name: deepseek-harness-worker
description: 让 Codex 主控并委派 DeepSeek Harness 执行有明确边界的只读分析、规则核对、文档审阅或第二意见，然后由 Codex 独立验收。用户明确要 Codex 把任务交给 DeepSeek Harness 或让其充当执行子智能体时使用。
---

# DeepSeek Harness 只读执行

Codex 拆解任务、判断授权、选择模式和模型、核对证据。默认用简体中文描述角色和任务并回传结果。[run_worker.py](scripts/run_worker.py) 为一次性任务启动新的原生 Harness Headless 会话。

1. 明确授权工作区、可读文件、专家角色及验收依据。需要 Skill 时，用可重复的 `--skill` 指定 Harness 已安装的英文 ID。
2. 根据任务选 `--task-kind`。定点抽取用 `lookup`（标准 / Flash Low），常规比对用 `analysis`（标准 / Flash High，默认），独立批量读取用 `batch`（PTC / Flash High），多约束独立审查用 `review`（标准 / Pro High）。
3. 运行 `python scripts/run_worker.py --cwd "<绝对工作区>" --task-kind analysis --role "<专家角色>" --task "<任务>"`。任务较长或涉及引号时，从 UTF-8 stdin 传入并省略 `--task`。
4. 返回 JSON 包含 `session_id`、完成状态、每次工具调用状态、最终答案和本次配置的 `route`。Codex 核对必要的原始证据。若工作未完成，先根据原会话状态定位问题，再决定是否重试。
5. 原生权限固定 `read-only`，审批固定 `never`。模式和模型通过仅本次进程使用的 overlay 配置。实时进度及 Web 轨迹走单独配置的 Orchestrator。桌面 MCP 由各自的 profile 管理。

Windows x64 Harness `0.2.2-rc.5` 通过 Harness 原生服务复用本机官方登录。程序位置可用 `--harness-exe`、`DSH_HARNESS_EXE` 或 Codex 配置根下的 `deepseek-harness-worker.json` 指定。定位文件只写 `harness_exe` 路径。换机器时先安装并登录，再恢复 Skill 和程序路径。
