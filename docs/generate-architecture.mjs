import { mkdtempSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath, pathToFileURL } from "node:url";
import { spawnSync } from "node:child_process";

const width = 1920;
const height = 1410;
const palette = {
  ink: "#14263f", muted: "#415a77", navy: "#11253b", light: "#b8ccdf",
  background: "#f1f5f9", paper: "#fff", border: "#cbd9e8", line: "#7189a4",
  blue: "#2258a0", blueWash: "#e6effe", focus: "#dceafe", focusBorder: "#89aff0",
  slate: "#435f7e", slateWash: "#e9eff6", green: "#1e6657", greenWash: "#e1f2e9",
};
const en = {
  modeHeading: "Codex selects the Harness mode and sets permissions separately",
  modes: [
    ["Standard", "Routine checks", "and project edits"],
    ["PTC", "Batch tasks"],
    ["Minimal", "Quick checks, images,", "persistent PowerShell"],
    ["Creator", "Harness extension", "design and review"],
  ],
  lang: "en", subtitle: "Delegation, delivery, and Desktop traces", headerNote: "One project · Task-scoped permissions",
  task: "Describe the task in Codex", taskNote: "Implement a feature · Review files · Ask for a plan",
  local: "Local guidance", localLines: ["Project rules, knowledge base,", "and installed skills"],
  sources: "Public sources", sourceLines: ["When local guidance is insufficient", "and online research is allowed"],
  supervisor: "Codex as supervisor", supervisorNote: "Sets scope · Matches skills and experts · Chooses a route",
  languageNote: "Handoff language: Auto / Simplified Chinese / English",
  branches: [
    ["Codex handles it", "Quick tasks or specialized tools", "Uses the tools available in Codex", "Handles small checks or edits", "Direct result"],
    ["Harness read-only", "read-only · Analysis, plans, review", "Headless Worker for one-off Standard / PTC", "Orchestrator for any mode and live progress", "Findings and evidence"],
    ["Harness project edits", "workspace-write · Build, fix, deliver", "Orchestrator · any of the four modes", "Headless Worker · Standard / PTC", "Files in the current project"],
  ],
  check: "Codex verifies the result", checkNote: "Checks evidence and file changes, then runs relevant tests",
  fullAccess: "Full access is available with explicit task authorization.",
  result: "Result in the current chat", resultNote: "Implementation files stay in the project",
  history: "Harness Desktop · Context Insights", indexed: "Completed sessions are indexed locally",
  trace: "Open Trace in Desktop", resume: "Follow-ups add tool calls to the same session's trace.",
};
const zh = {
  modeHeading: "交给 Harness 时，Codex 分别选择模式和工作区权限",
  modes: [
    ["标准", "常规核对及项目修改"],
    ["PTC", "批量处理"],
    ["极简", "轻量核对、图片", "持久 PowerShell"],
    ["创造", "Harness 扩展设计与核对"],
  ],
  lang: "zh-CN", subtitle: "自动分派、交付与桌面轨迹", headerNote: "同一项目 · 按任务授权",
  task: "你在 Codex 提出任务", taskNote: "实现功能 · 复核资料 · 先分析，再给方案",
  local: "本地依据", localLines: ["项目规则、知识库与已安装 Skill", "优先读取任务相关正文"],
  sources: "公开资料补充", sourceLines: ["本地依据不足且允许联网", "核对官方文档和社区原仓库"],
  supervisor: "Codex 主控", supervisorNote: "理解目标 · 判断范围 · 选 Skill、专家和执行方式",
  languageNote: "交接语言可选：自动 / 简体中文 / English",
  branches: [
    ["Codex 直接执行", "简单任务或需专用工具", "用当前 Codex 工具处理", "适合快速核对或小范围操作", "直接处理结果"],
    ["Harness 只读", "read-only · 分析、方案、审阅", "Headless Worker：一次性标准 / PTC 任务", "Orchestrator：四种模式与实时进度", "只读结论与依据"],
    ["Harness 项目内写入", "workspace-write · 实现、修复、产出", "Orchestrator · 四种模式", "Headless Worker · 标准 / PTC", "当前 Codex 项目中的文件"],
  ],
  check: "Codex 最终验收", checkNote: "核对证据、落盘文件和差异，需要时运行检查",
  fullAccess: "用户明确授权的任务可选完全权限。",
  result: "把结果交付到当前聊天", resultNote: "开发产物留在当前项目目录",
  history: "Harness 桌面版 · 上下文洞察", indexed: "任务完成后自动收录本机会话",
  trace: "在桌面打开「轨迹」", resume: "续聊沿用原会话，工具记录追加到同一条轨迹。",
};
const esc = text => text.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
const c = palette;

function render(content) {
  const zhCN = content.lang === "zh-CN";
  const elements = [];
  function rect(x, y, w, h, { fill = c.paper, border, radius = 22 } = {}) {
    elements.push('<rect x="' + x + '" y="' + y + '" width="' + w + '" height="' + h + '" rx="' + radius + '" fill="' + fill + '"' +
      (border ? ' stroke="' + border + '" stroke-width="1.5"' : '') + '/>');
  }
  function text(x, y, value, { size = 26, weight = 400, fill = c.ink, align = "start" } = {}) {
    elements.push('<text x="' + x + '" y="' + y + '" font-size="' + size + '" font-weight="' + weight + '" fill="' + fill +
      '" text-anchor="' + align + '">' + esc(value) + '</text>');
  }
  function path(d, { color = c.line, tip, width = 3 } = {}) {
    elements.push('<path d="' + d + '" fill="none" stroke="' + color + '" stroke-width="' + width +
      '" stroke-linecap="round" stroke-linejoin="round"' + (tip ? ' marker-end="url(#' + tip + ')"' : "") + '/>');
  }
  const center = (x, y, value, options) => text(x, y, value, { ...options, align: "middle" });
  const x = [96, 576, 1386];
  const laneWidths = [438, 768, 438];
  const lanes = x.map((left, i) => left + laneWidths[i] / 2);
  const colors = [c.slate, c.blue, c.green];
  const washes = [c.slateWash, c.blueWash, c.greenWash];

  rect(0, 0, width, height, { fill: c.background, radius: 0 });
  rect(0, 0, width, 155, { fill: c.navy, radius: 0 });
  rect(96, 35, 8, 72, { fill: "#66b8cd", radius: 0 });
  text(129, 73, "Codex × DeepSeek Harness", { size: 54, weight: 700, fill: c.paper });
  text(132, 116, content.subtitle, { size: 30, fill: c.light });
  text(1824, 88, content.headerNote, { size: 26, fill: c.light, align: "end" });

  path("M960 286 V335", { tip: "arrow" });
  path("M474 404 H550", { tip: "arrow" });
  path("M1446 404 H1370", { tip: "arrow" });
  path("M960 582 V615 H315 V644", { tip: "arrow" });
  path("M960 615 V644", { tip: "arrow" });
  path("M960 615 H1605 V644", { tip: "arrow" });
  lanes.forEach((lane, i) => path("M" + lane + " 862 V900", { color: colors[i], tip: ["arrowSlate", "arrowBlue", "arrowGreen"][i] }));
  path("M315 967 V1008 H1605 V967");
  path("M960 967 V1008");
  path("M505 1008 V1048", { tip: "arrow" });
  path("M505 1160 V1215", { tip: "arrow" });

  rect(635, 180, 650, 106, { border: c.border });
  center(960, 232, content.task, { size: 37, weight: 700 });
  center(960, 265, content.taskNote, { size: 23, fill: c.muted });

  rect(550, 335, 820, 247, { fill: c.focus, border: c.focusBorder });
  center(960, 384, content.supervisor, { size: 46, weight: 700, fill: "#19447c" });
  center(960, 417, content.supervisorNote, { size: 26, fill: "#345b85" });
  center(960, 444, content.languageNote, { size: 20, weight: 600, fill: "#345b85" });
  center(960, 477, content.modeHeading, { size: 22, weight: 700, fill: c.blue });
  content.modes.forEach(([mode, ...description], index) => {
    const modeLeft = 571 + index * 197;
    rect(modeLeft, 490, 187, 72, { fill: c.paper, radius: 9 });
    text(modeLeft + 10, 515, mode, { size: 23, weight: 700, fill: c.blue });
    description.forEach((line, i) => text(modeLeft + 10, 536 + i * 18, line, { size: 15.5, fill: c.muted }));
  });

  function side(left, title, lines) {
    rect(left, 338, 378, 132, { fill: "#e8eff7", border: c.border, radius: 20 });
    text(left + 24, 382, title, { size: 29, weight: 700, fill: "#274668" });
    lines.forEach((line, i) => text(left + 24, 414 + i * 30, line, { size: 21, fill: c.muted }));
  }
  side(96, content.local, content.localLines);
  side(1446, content.sources, content.sourceLines);

  content.branches.forEach(([title, badge, first, second, outcome], i) => {
    const left = x[i];
    const laneWidth = laneWidths[i];
    const color = colors[i];
    rect(left, 644, laneWidth, 218, { border: c.border });
    rect(left + 26, 667, 8, 44, { fill: color, radius: 4 });
    text(left + 47, 702, title, { size: i === 1 ? 36 : 33, weight: 700 });
    rect(left + 26, 720, laneWidth - 52, 40, { fill: washes[i], radius: 9 });
    text(left + 41, 747, badge, { size: i === 1 ? 25 : 21, weight: 700, fill: color });
    text(left + 26, 799, first, { size: 22, fill: c.muted });
    text(left + 26, 831, second, { size: 22, fill: c.muted });
    rect(left + 24, 900, laneWidth - 48, 67, { fill: washes[i], radius: 18 });
    center(lanes[i], 943, outcome, { size: 26, weight: 700, fill: color });
  });
  text(1824, 1038, content.fullAccess, { size: 18, fill: c.green, align: "end" });

  rect(96, 1048, 818, 112, { fill: c.focus, border: c.focusBorder });
  center(505, 1099, content.check, { size: 37, weight: 700, fill: "#19447c" });
  center(505, 1133, content.checkNote, { size: 23, fill: "#345b85" });
  rect(96, 1215, 818, 112, { border: c.border });
  center(505, 1267, content.result, { size: 37, weight: 700 });
  center(505, 1301, content.resultNote, { size: 24, fill: c.muted });

  rect(1000, 1048, 824, 284, { fill: "#f7fbff", border: c.focusBorder });
  text(1028, 1091, content.history, { size: zhCN ? 34 : 33, weight: 700, fill: "#19447c" });
  rect(1028, 1111, 245, 43, { fill: c.blueWash, radius: 10 });
  rect(1551, 1111, 245, 43, { fill: c.blueWash, radius: 10 });
  center(1150, 1140, "Headless", { size: 25, weight: 700, fill: c.blue });
  center(1673, 1140, "Orchestrator", { size: 25, weight: 700, fill: c.blue });
  path("M1150 1154 V1172 H1673 V1154", { color: c.blue, width: 2.5 });
  path("M1412 1172 V1188", { color: c.blue, tip: "arrowBlue", width: 2.5 });
  rect(1028, 1188, 768, 43, { fill: c.blueWash, radius: 10 });
  center(1412, 1217, content.indexed, { size: 25, weight: 700, fill: c.blue });
  path("M1412 1231 V1246", { color: c.blue, tip: "arrowBlue", width: 2.5 });
  center(1412, 1275, content.trace, { size: 30, weight: 700, fill: "#19447c" });
  center(1412, 1308, content.resume, { size: 22, fill: c.muted });

  const font = zhCN ? "Segoe UI, Microsoft YaHei UI, Microsoft YaHei, sans-serif" : "Segoe UI, sans-serif";
  const markers = [["arrow", c.line], ["arrowSlate", c.slate], ["arrowBlue", c.blue], ["arrowGreen", c.green]]
    .map(([id, color]) => '<marker id="' + id + '" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10z" fill="' + color + '"/></marker>').join("");
  return '<!doctype html><html lang="' + content.lang + '"><meta charset="utf-8"><style>html,body{margin:0;width:' + width +
    'px;height:' + height + 'px;overflow:hidden}svg{display:block;font-family:' + font + '}</style><body><svg xmlns="http://www.w3.org/2000/svg" width="' +
    width + '" height="' + height + '" viewBox="0 0 ' + width + ' ' + height + '"><defs>' + markers + '</defs>' + elements.join("") + '</svg></body></html>';
}

const browser = [
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
].find(existsSync);
if (!browser) throw new Error("No Chromium executable available.");
const output = resolve(process.argv[2] ?? dirname(fileURLToPath(import.meta.url)));
const work = mkdtempSync(join(tmpdir(), "harness-architecture-source-"));
for (const content of [en, zh]) {
  const name = "architecture." + content.lang;
  const document = join(work, name + ".html");
  const png = join(output, name + ".png");
  writeFileSync(document, render(content), "utf8");
  const proc = spawnSync(browser, [
    "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
    "--disable-background-networking", "--hide-scrollbars", "--force-device-scale-factor=1",
    "--window-size=" + width + "," + height, "--user-data-dir=" + join(work, "browser-" + content.lang),
    "--screenshot=" + png, pathToFileURL(document).href,
  ], { encoding: "utf8", windowsHide: true, timeout: 45000 });
  if (proc.status !== 0 || !existsSync(png)) throw new Error(proc.error?.message ?? proc.stderr ?? "Export failed.");
  console.log(png);
}
