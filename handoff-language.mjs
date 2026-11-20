export const name = "codex-handoff-language";
export const inject = ["systemPrompt"];

const policies = {
  auto: "Follow the user's conversation language, unless the task explicitly requests another language. " +
    "Pass this choice to every child agent, including through retries and follow-ups.",
  "zh-CN": "默认使用简体中文。用户明确指定其他语言时遵照要求。每次派给子智能体时，" +
    "用所选语言编写角色、任务要求和验收条件，并明确要求子智能体用同样语言回传及继续交接。",
  en: "Use English unless the user explicitly requests another language. " +
    "Write each child agent's role, task and acceptance criteria in the selected language, " +
    "and have the child use the same language for its result and any further handoffs.",
};

export function apply(ctx, config = {}) {
  const language = config.language ?? "auto";
  if (!Object.hasOwn(policies, language)) throw new Error("Unsupported Harness handoff language");
  ctx.systemPrompt.section({
    name: "codex:handoff-language",
    order: ctx.systemPrompt.getSectionOrder("TEAM_POLICY") + 1,
    text: () => language === "zh-CN"
      ? policies[language] + " 会话标题、共享任务说明和最终汇报同样使用所选语言。保留工具名、文件名、代码和引用的错误原文。"
      : policies[language] + " Use that language for titles, team tasks, reports, and the actual prompts sent to children. " +
        "Keep tool names, filenames, code, and quoted errors as written.",
  });
}
