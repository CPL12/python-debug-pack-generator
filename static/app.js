const tabs = [
  { id: "lesson", labelKey: "tab.lesson" },
  { id: "master", labelKey: "tab.master" },
  { id: "starter", labelKey: "tab.starter" },
  { id: "buggy", labelKey: "tab.buggy" },
  { id: "cards", labelKey: "tab.cards" },
  { id: "run", labelKey: "tab.run" },
];

const streamingFlowOrder = ["warmUp", "buildActivity", "debugActivity", "wrapUp", "teacherNotes", "runSuggestions"];

let lessonPack = null;
let activeTab = "lesson";
let activeCode = "master";
let highlightedSnippet = "";
let runResult = null;
let runSession = null;
let runPollTimer = null;
let modelStreamText = "";
let lessonFlowRevealCount = null;
let streamingLessonFlowSections = [];

const themeStorageKey = "python-debug-pack-theme";
const languageStorageKey = "python-debug-pack-language";
let currentLanguage = localStorage.getItem(languageStorageKey) || detectBrowserLanguage();

const i18n = {
  "zh-Hant": {
    appTitle: "Python Debug Pack Generator",
    appSubtitle: "三態 Python 教材 + 教師除錯卡",
    languageToggle: "English",
    languageToggleLabel: "Switch language to English",
    darkMode: "深色模式",
    lessonInput: "課堂輸入",
    generatedLessonPack: "生成教材包",
    topicLabel: "課堂主題",
    topicPlaceholder: "例如：猜數字遊戲、BMI 計算機、購物折扣計算",
    levelLabel: "年級難度",
    durationLabel: "課堂時長",
    generate: "生成 Debug Pack",
    generating: "生成中...",
    clear: "清除",
    copyAll: "複製全部",
    copyAllTitle: "複製全部生成內容",
    toggleModelStream: "展開或收起模型輸出",
    waitingGeneration: "等待生成",
    apiChecking: "正在檢查 API",
    apiReady: "API 已就緒 · {model}",
    apiFallback: "API fallback 模式",
    apiOffline: "API 離線",
    ready: "就緒",
    stateGenerating: "生成中",
    emptyTitle: "輸入一個 Python 課堂主題，30 秒內生成可 Demo 嘅教材包。",
    emptyHint: "建議先試「猜數字遊戲」或「BMI 計算機」。",
    topicRequired: "請先輸入課堂主題。",
    generateRequestFailed: "生成請求失敗",
    streamNoPack: "串流完成但沒有教材包",
    generateFailed: "生成失敗，請檢查 API 或稍後再試。",
    jsonUnavailable: "JSON: 無法讀取",
    generatingTitle: "正在生成 debug pack...",
    streamingChip: "模型輸出串流中",
    streamWaiting: "正在根據即時模型回應建立教材包。",
    streamConnecting: "正在連接模型串流...",
    streamComplete: "串流完成，JSON 已驗證。",
    lastGeneratedStreaming: "上次生成：串流中",
    lastGeneratedEmpty: "上次生成：-",
    lastGenerated: "上次生成：{time}",
    jsonStreaming: "JSON: 串流中",
    jsonWaiting: "JSON: 等待中",
    jsonValid: "JSON: 有效 · {source}",
    runIdle: "執行：閒置",
    runRunning: "執行：執行中",
    runUnavailable: "執行：無法使用",
    runStopped: "執行：已停止",
    runSuccess: "執行：成功",
    runError: "執行：{error}",
    tab: {
      lesson: "課堂流程",
      master: "完整程式",
      starter: "學生起始碼",
      buggy: "錯誤程式",
      cards: "除錯卡",
      run: "執行輸出",
    },
    flow: {
      warmUp: "引入活動",
      buildActivity: "建構活動",
      debugActivity: "除錯活動",
      wrapUp: "總結",
      teacherNotes: "教師備註",
      runSuggestions: "執行建議",
    },
    copy: "複製",
    run: "執行",
    teachingFlow: "教學流程",
    guidingQuestions: "引導問題",
    progressiveHints: "漸進提示",
    explanation: "解釋",
    fix: "修正：",
    extension: "延伸",
    copyCard: "複製卡片",
    highlightCode: "標示程式碼",
    runCode: "執行程式",
    stop: "停止",
    enter: "送出",
    inputPlaceholder: "輸入內容，然後按 Enter",
    codeToRun: "要執行的程式碼",
    runCodeTitle: "執行 {kind}",
    pressRun: "按「執行程式」開始互動執行。",
    noOutput: "程式已完成，沒有輸出。",
    errorType: "錯誤類型",
    teachingConcept: "教學概念",
    location: "位置",
    symptom: "現象",
    questions: "問題",
    hints: "提示",
    levels: { "小學": "小學", "初中": "初中", "高中": "高中" },
    durations: { "30 分鐘": "30 分鐘", "1 小時": "1 小時", "90 分鐘": "90 分鐘" },
    codeKinds: { master: "完整程式", starter: "學生起始碼", buggy: "錯誤程式" },
  },
  en: {
    appTitle: "Python Debug Pack Generator",
    appSubtitle: "Three-part Python lessons + Teacher Debug Cards",
    languageToggle: "中文",
    languageToggleLabel: "Switch language to Chinese",
    darkMode: "Dark mode",
    lessonInput: "Lesson input",
    generatedLessonPack: "Generated lesson pack",
    topicLabel: "Lesson topic",
    topicPlaceholder: "Examples: number guessing game, BMI calculator, shopping discount calculator",
    levelLabel: "Grade level",
    durationLabel: "Lesson length",
    generate: "Generate Debug Pack",
    generating: "Generating...",
    clear: "Clear",
    copyAll: "Copy All",
    copyAllTitle: "Copy all generated content",
    toggleModelStream: "Toggle model stream",
    waitingGeneration: "Waiting for generation",
    apiChecking: "API checking",
    apiReady: "API ready · {model}",
    apiFallback: "API fallback mode",
    apiOffline: "API offline",
    ready: "Ready",
    stateGenerating: "Generating",
    emptyTitle: "Enter a Python lesson topic and generate a demo-ready teaching pack.",
    emptyHint: "Try “number guessing game” or “BMI calculator” first.",
    topicRequired: "Please enter a lesson topic first.",
    generateRequestFailed: "Generate request failed",
    streamNoPack: "Stream finished without a lesson pack",
    generateFailed: "Generation failed. Please check the API or try again later.",
    jsonUnavailable: "JSON: unavailable",
    generatingTitle: "Generating debug pack...",
    streamingChip: "Streaming model output",
    streamWaiting: "Building the lesson pack from the live model response.",
    streamConnecting: "Connecting to model stream...",
    streamComplete: "Stream complete. JSON validated.",
    lastGeneratedStreaming: "Last generated: streaming",
    lastGeneratedEmpty: "Last generated: -",
    lastGenerated: "Last generated: {time}",
    jsonStreaming: "JSON: streaming",
    jsonWaiting: "JSON: waiting",
    jsonValid: "JSON: valid · {source}",
    runIdle: "Run: idle",
    runRunning: "Run: running",
    runUnavailable: "Run: unavailable",
    runStopped: "Run: stopped",
    runSuccess: "Run: success",
    runError: "Run: {error}",
    tab: {
      lesson: "Lesson Flow",
      master: "Master Code",
      starter: "Starter Code",
      buggy: "Buggy Code",
      cards: "Debug Cards",
      run: "Run Output",
    },
    flow: {
      warmUp: "Warm-up",
      buildActivity: "Build Activity",
      debugActivity: "Debug Activity",
      wrapUp: "Wrap-up",
      teacherNotes: "Teacher Notes",
      runSuggestions: "Run Suggestions",
    },
    copy: "Copy",
    run: "Run",
    teachingFlow: "Teaching Flow",
    guidingQuestions: "Guiding Questions",
    progressiveHints: "Progressive Hints",
    explanation: "Explanation",
    fix: "Fix:",
    extension: "Extension",
    copyCard: "Copy Card",
    highlightCode: "Highlight Code",
    runCode: "Run Code",
    stop: "Stop",
    enter: "Enter",
    inputPlaceholder: "Type input, then press Enter",
    codeToRun: "Code to run",
    runCodeTitle: "Run {kind}",
    pressRun: "Press Run Code to start an interactive session.",
    noOutput: "Code finished without output.",
    errorType: "Error Type",
    teachingConcept: "Teaching Concept",
    location: "Location",
    symptom: "Symptom",
    questions: "Questions",
    hints: "Hints",
    levels: { "小學": "Primary", "初中": "Junior secondary", "高中": "Senior secondary" },
    durations: { "30 分鐘": "30 minutes", "1 小時": "1 hour", "90 分鐘": "90 minutes" },
    codeKinds: { master: "Master Code", starter: "Starter Code", buggy: "Buggy Code" },
  },
};
const pythonKeywords = new Set([
  "False",
  "None",
  "True",
  "and",
  "as",
  "assert",
  "async",
  "await",
  "break",
  "class",
  "continue",
  "def",
  "del",
  "elif",
  "else",
  "except",
  "finally",
  "for",
  "from",
  "global",
  "if",
  "import",
  "in",
  "is",
  "lambda",
  "nonlocal",
  "not",
  "or",
  "pass",
  "raise",
  "return",
  "try",
  "while",
  "with",
  "yield",
]);
const pythonBuiltins = new Set([
  "abs",
  "bool",
  "dict",
  "enumerate",
  "float",
  "input",
  "int",
  "len",
  "list",
  "max",
  "min",
  "print",
  "range",
  "round",
  "set",
  "str",
  "sum",
  "tuple",
]);

const el = (id) => document.getElementById(id);

function t(key, values = {}) {
  const value = key.split(".").reduce((entry, part) => entry?.[part], i18n[currentLanguage]) ?? key;
  if (typeof value !== "string") return value;
  return value.replace(/\{(\w+)\}/g, (_, name) => values[name] ?? "");
}

function currentLanguageName() {
  return currentLanguage === "en" ? "en" : "zh-Hant";
}

function detectBrowserLanguage() {
  const browserLanguages = navigator.languages?.length ? navigator.languages : [navigator.language];
  const firstSupported = browserLanguages.find((language) => {
    const normalized = String(language || "").toLowerCase();
    return normalized.startsWith("zh") || normalized.startsWith("en");
  });
  return String(firstSupported || "").toLowerCase().startsWith("zh") ? "zh-Hant" : "en";
}

function apiModelLabel(api) {
  if (!api?.model) return "";
  if (api.thinking === "enabled") return `${api.model} | thinking`;
  if (api.thinking === "disabled") return `${api.model} | non-thinking`;
  return api.model;
}

document.addEventListener("DOMContentLoaded", () => {
  initLanguage();
  initTheme();
  el("lessonForm").addEventListener("submit", handleGenerate);
  el("resetBtn").addEventListener("click", resetApp);
  el("copyAllBtn").addEventListener("click", copyAll);
  el("streamToggle")?.addEventListener("click", toggleStreamPanel);
  checkApiStatus();
  renderTabs();
});

function initLanguage() {
  if (!i18n[currentLanguage]) currentLanguage = detectBrowserLanguage();
  el("languageToggle").addEventListener("click", () => {
    currentLanguage = currentLanguage === "zh-Hant" ? "en" : "zh-Hant";
    localStorage.setItem(languageStorageKey, currentLanguage);
    applyLanguage();
    renderTabs();
    if (lessonPack) renderTabContent();
  });
  applyLanguage();
}

function applyLanguage() {
  document.documentElement.lang = currentLanguage === "en" ? "en" : "zh-Hant";
  document.title = t("appTitle");
  document.querySelector(".app-header h1").textContent = t("appTitle");
  el("appSubtitle").textContent = t("appSubtitle");
  el("languageToggle").textContent = t("languageToggle");
  el("languageToggle").setAttribute("aria-label", t("languageToggleLabel"));
  el("themeLabel").textContent = t("darkMode");
  el("themeToggle").setAttribute("aria-label", t("darkMode"));
  el("inputPanel").setAttribute("aria-label", t("lessonInput"));
  el("outputPanel").setAttribute("aria-label", t("generatedLessonPack"));
  el("topicLabel").textContent = t("topicLabel");
  el("topic").setAttribute("placeholder", t("topicPlaceholder"));
  el("levelLabel").textContent = t("levelLabel");
  el("durationLabel").textContent = t("durationLabel");
  updateSelectLabels("level", t("levels"));
  updateSelectLabels("duration", t("durations"));
  el("generateBtn").textContent = el("generateBtn").disabled ? t("generating") : t("generate");
  el("generateState").textContent = el("generateBtn").disabled ? t("stateGenerating") : t("ready");
  el("resetBtn").textContent = t("clear");
  el("copyAllBtn").textContent = t("copyAll");
  el("copyAllBtn").setAttribute("title", t("copyAllTitle"));
  el("streamToggle")?.setAttribute("aria-label", t("toggleModelStream"));
  el("emptyTitle").textContent = t("emptyTitle");
  el("emptyHint").textContent = t("emptyHint");
  if (lessonPack) {
    el("lastGenerated").textContent = t("lastGenerated", { time: new Date(lessonPack.metadata.generated_at).toLocaleString() });
    el("jsonStatus").textContent = t("jsonValid", { source: lessonPack.metadata.source });
    updateStreamStatus(t("streamComplete"));
    updateRunStatus();
  } else if (!modelStreamText) {
    el("apiStatus").textContent = t("apiChecking");
    updateStreamStatus(t("waitingGeneration"));
    el("lastGenerated").textContent = t("lastGeneratedEmpty");
    el("jsonStatus").textContent = t("jsonWaiting");
    el("runStatus").textContent = t("runIdle");
  }
  checkApiStatus();
}

function updateSelectLabels(id, labels) {
  Array.from(el(id).options).forEach((option) => {
    option.textContent = labels[option.value] || option.value;
  });
}

function initTheme() {
  const savedTheme = localStorage.getItem(themeStorageKey);
  const prefersDark = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  const theme = savedTheme || (prefersDark ? "dark" : "light");
  setTheme(theme);

  el("themeToggle").addEventListener("change", (event) => {
    const nextTheme = event.target.checked ? "dark" : "light";
    setTheme(nextTheme);
    localStorage.setItem(themeStorageKey, nextTheme);
  });
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const toggle = el("themeToggle");
  if (toggle) toggle.checked = theme === "dark";
}

async function checkApiStatus() {
  try {
    const response = await fetch("/api/status");
    const data = await response.json();
    const status = el("apiStatus");
    if (data.api.configured) {
      status.textContent = t("apiReady", { model: apiModelLabel(data.api) });
      status.className = "status-pill";
    } else {
      status.textContent = t("apiFallback");
      status.className = "status-pill warning";
    }
  } catch (error) {
    el("apiStatus").textContent = t("apiOffline");
    el("apiStatus").className = "status-pill warning";
  }
}

async function handleGenerate(event) {
  event.preventDefault();
  const topic = el("topic").value.trim();
  if (!topic) {
    el("formError").textContent = t("topicRequired");
    return;
  }

  const payload = {
    topic,
    level: el("level").value,
    duration: el("duration").value,
    language: currentLanguageName(),
    concepts: [],
  };

  setGenerating(true);
  el("formError").textContent = "";
  modelStreamText = "";
  prepareStreamView();

  try {
    await stopRunSession(true);
    const response = await fetch("/api/generate-pack/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(t("generateRequestFailed"));

    await readGenerationStream(response);
    if (!lessonPack) throw new Error(t("streamNoPack"));

    const revealedFlowDuringStream = streamingLessonFlowSections.length > 0;
    activeTab = "lesson";
    activeCode = "master";
    highlightedSnippet = "";
    runResult = null;
    if (revealedFlowDuringStream) {
      lessonFlowRevealCount = null;
      showResult();
    } else {
      await showResultProgressively();
    }
  } catch (error) {
    el("formError").textContent = t("generateFailed");
    el("jsonStatus").textContent = t("jsonUnavailable");
    updateStreamStatus(error.message || t("generateRequestFailed"));
  } finally {
    setGenerating(false);
  }
}

function prepareStreamView() {
  lessonPack = null;
  activeTab = "lesson";
  activeCode = "master";
  highlightedSnippet = "";
  runResult = null;
  lessonFlowRevealCount = 0;
  streamingLessonFlowSections = [];
  el("emptyState").classList.add("hidden");
  el("resultView").classList.remove("hidden");
  el("lessonTitle").textContent = t("generatingTitle");
  el("keyConcepts").innerHTML = `<span class="chip">${escapeHtml(t("streamingChip"))}</span>`;
  renderTabs();
  el("tabContent").innerHTML = `<div class="stream-waiting">${escapeHtml(t("streamWaiting"))}</div>`;
  el("streamPanel")?.classList.add("hidden");
  setStreamCollapsed(true);
  if (el("modelStream")) el("modelStream").textContent = "";
  updateStreamStatus(t("streamConnecting"));
  el("lastGenerated").textContent = t("lastGeneratedStreaming");
  el("jsonStatus").textContent = t("jsonStreaming");
  el("runStatus").textContent = t("runIdle");
}

async function readGenerationStream(response) {
  if (!response.body) {
    lessonPack = await response.json();
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) await handleStreamLine(line);
    if (done) break;
  }

  if (buffer.trim()) await handleStreamLine(buffer);
}

async function handleStreamLine(line) {
  if (!line.trim()) return;
  const event = JSON.parse(line);
  if (event.type === "status") {
    updateStreamStatus(event.message || t("jsonStreaming"));
    return;
  }
  if (event.type === "delta") {
    appendModelStream(event.text || "");
    return;
  }
  if (event.type === "partial") {
    if (event.target === "lesson_flow" && event.section) {
      await handleLessonFlowPartial(event.section);
    }
    return;
  }
  if (event.type === "complete") {
    lessonPack = event.pack;
    updateStreamStatus(t("streamComplete"));
    return;
  }
  if (event.type === "error") {
    throw new Error(event.message || t("generateRequestFailed"));
  }
}

function appendModelStream(text) {
  modelStreamText += text;
  const stream = el("modelStream");
  if (!stream) return;
  stream.textContent = modelStreamText;
  stream.scrollTop = stream.scrollHeight;
}

function updateStreamStatus(message) {
  const target = el("streamStatus");
  if (target) target.textContent = message;
}

async function handleLessonFlowPartial(section) {
  if (!section.id || !streamingFlowOrder.includes(section.id)) return;

  const nextSection = { id: section.id, value: section.value };
  const existingIndex = streamingLessonFlowSections.findIndex((item) => item.id === section.id);
  const isNewSection = existingIndex < 0;
  if (existingIndex >= 0) {
    streamingLessonFlowSections[existingIndex] = nextSection;
  } else {
    streamingLessonFlowSections.push(nextSection);
  }
  streamingLessonFlowSections.sort(
    (left, right) => streamingFlowOrder.indexOf(left.id) - streamingFlowOrder.indexOf(right.id),
  );

  if (!lessonPack && activeTab === "lesson") {
    el("tabContent").innerHTML = renderStreamingLessonFlow();
  }
  if (isNewSection) await sleep(180);
}

function toggleStreamPanel() {
  const panel = el("streamPanel");
  if (!panel) return;
  setStreamCollapsed(!panel.classList.contains("collapsed"));
}

function setStreamCollapsed(isCollapsed) {
  const panel = el("streamPanel");
  const toggle = el("streamToggle");
  if (!panel || !toggle) return;
  panel.classList.toggle("collapsed", isCollapsed);
  toggle.setAttribute("aria-expanded", String(!isCollapsed));
}

function setGenerating(isGenerating) {
  el("generateBtn").disabled = isGenerating;
  el("generateBtn").textContent = isGenerating ? t("generating") : t("generate");
  el("generateState").textContent = isGenerating ? t("stateGenerating") : t("ready");
  el("generateState").className = isGenerating ? "status-pill warning" : "status-pill muted";
}

function showResult() {
  el("emptyState").classList.add("hidden");
  el("resultView").classList.remove("hidden");
  el("lessonTitle").textContent = lessonPack.lesson_title;
  el("keyConcepts").innerHTML = lessonPack.key_concepts.map((item) => `<span class="chip">${escapeHtml(item)}</span>`).join("");
  el("lastGenerated").textContent = t("lastGenerated", { time: new Date(lessonPack.metadata.generated_at).toLocaleString() });
  el("jsonStatus").textContent = t("jsonValid", { source: lessonPack.metadata.source });
  el("runStatus").textContent = t("runIdle");
  el("streamPanel")?.classList.add("hidden");
  renderTabs();
  renderTabContent();
}

async function showResultProgressively() {
  lessonFlowRevealCount = 0;
  showResult();

  const sectionCount = lessonFlowSections().length;
  for (let count = 1; count <= sectionCount; count += 1) {
    lessonFlowRevealCount = count;
    if (activeTab === "lesson") renderTabContent();
    await sleep(160);
  }
  lessonFlowRevealCount = null;
  if (activeTab === "lesson") renderTabContent();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function renderTabs() {
  el("tabs").innerHTML = tabs
    .map(
      (tab) =>
        `<button class="tab-btn ${tab.id === activeTab ? "active" : ""}" data-tab="${tab.id}" type="button">
          ${iconSvg(tab.id)}
          <span>${escapeHtml(t(tab.labelKey))}</span>
        </button>`,
    )
    .join("");
  document.querySelectorAll(".tab-btn").forEach((button) => {
    button.addEventListener("click", () => {
      activeTab = button.dataset.tab;
      renderTabs();
      renderTabContent();
    });
  });
}

function renderTabContent() {
  const target = el("tabContent");
  if (!lessonPack) {
    target.innerHTML = activeTab === "lesson" ? renderStreamingLessonFlow() : `<div class="stream-waiting">${escapeHtml(t("streamWaiting"))}</div>`;
    return;
  }

  if (activeTab === "lesson") target.innerHTML = renderLessonFlow();
  if (activeTab === "master") target.innerHTML = renderCodeView("master", lessonPack.master_code);
  if (activeTab === "starter") target.innerHTML = renderCodeView("starter", lessonPack.starter_code);
  if (activeTab === "buggy") target.innerHTML = renderCodeView("buggy", lessonPack.buggy_code);
  if (activeTab === "cards") target.innerHTML = renderDebugCards();
  if (activeTab === "run") target.innerHTML = renderRunner();

  wireDynamicButtons();
}

function renderStreamingLessonFlow() {
  if (!streamingLessonFlowSections.length) {
    return `<div class="stream-waiting">${escapeHtml(t("streamWaiting"))}</div>`;
  }
  return `
    <div class="flow-grid">
      ${streamingLessonFlowSections.map((section) => flowSection(streamingLessonFlowSection(section))).join("")}
    </div>
  `;
}

function streamingLessonFlowSection(section) {
  return {
    id: section.id,
    title: t(`flow.${section.id}`),
    body: numberedFlow(section.value),
  };
}

function renderLessonFlow() {
  const sections = lessonFlowSections();
  const visibleSections =
    typeof lessonFlowRevealCount === "number" ? sections.slice(0, lessonFlowRevealCount) : sections;
  if (!visibleSections.length) {
    return `<div class="stream-waiting">${escapeHtml(t("streamWaiting"))}</div>`;
  }
  return `
    <div class="flow-grid">
      ${visibleSections.map((section) => flowSection(section)).join("")}
    </div>
  `;
}

function lessonFlowSections() {
  if (!lessonPack) return [];
  const flow = lessonPack.lesson_flow;
  return [
    { id: "warmUp", title: t("flow.warmUp"), body: numberedFlow(flow.warm_up) },
    { id: "buildActivity", title: t("flow.buildActivity"), body: numberedFlow(flow.build_activity) },
    { id: "debugActivity", title: t("flow.debugActivity"), body: numberedFlow(flow.debug_activity) },
    { id: "wrapUp", title: t("flow.wrapUp"), body: numberedFlow(flow.wrap_up) },
    { id: "teacherNotes", title: t("flow.teacherNotes"), body: numberedFlow(flow.teacher_notes) },
    { id: "runSuggestions", title: t("flow.runSuggestions"), body: numberedFlow(lessonPack.run_suggestions.note) },
  ];
}

function flowSection(section) {
  return `
    <section class="flow-section flow-reveal">
      <h3>${iconSvg(section.id)}<span>${escapeHtml(section.title)}</span></h3>
      ${section.body}
    </section>
  `;
}

function renderCodeView(kind, code) {
  activeCode = kind;
  return `
    <div class="code-toolbar">
      <strong>${kindLabel(kind)}</strong>
      <div class="code-actions">
        <button class="secondary-btn" data-copy-code="${kind}" type="button">${escapeHtml(t("copy"))}</button>
        <button class="primary-btn" data-run-code="${kind}" type="button">${escapeHtml(t("run"))}</button>
      </div>
    </div>
    <pre class="code-block">${renderCodeLines(code)}</pre>
  `;
}

function renderCodeLines(code) {
  return code
    .split("\n")
    .map((line, index) => {
      const highlight = highlightedSnippet && line.includes(highlightedSnippet) ? " highlight" : "";
      return `<span class="code-line${highlight}"><span class="line-no">${index + 1}</span><span class="line-text">${highlightPythonLine(line)}</span></span>`;
    })
    .join("");
}

function highlightPythonLine(line) {
  const tokens = [];
  let index = 0;

  while (index < line.length) {
    const char = line[index];

    if (char === "#") {
      tokens.push(token("comment", line.slice(index)));
      break;
    }

    if (char === '"' || char === "'") {
      const stringEnd = readPythonString(line, index);
      tokens.push(token("string", line.slice(index, stringEnd)));
      index = stringEnd;
      continue;
    }

    if (/\d/.test(char)) {
      const match = line.slice(index).match(/^\d(?:[\d_]*\d)?(?:\.\d(?:[\d_]*\d)?)?(?:[eE][+-]?\d+)?/);
      if (match) {
        tokens.push(token("number", match[0]));
        index += match[0].length;
        continue;
      }
    }

    if (/[A-Za-z_]/.test(char)) {
      const match = line.slice(index).match(/^[A-Za-z_][A-Za-z0-9_]*/);
      const word = match[0];
      const nextText = line.slice(index + word.length);
      const previousText = line.slice(0, index);
      const cssClass = pythonTokenClass(word, nextText, previousText);
      tokens.push(cssClass ? token(cssClass, word) : escapeHtml(word));
      index += word.length;
      continue;
    }

    if (/[+\-*/%=<>!&|^~:.,()[\]{}]/.test(char)) {
      tokens.push(token("operator", char));
      index += 1;
      continue;
    }

    tokens.push(escapeHtml(char));
    index += 1;
  }

  return tokens.join("");
}

function readPythonString(line, start) {
  const quote = line[start];
  const isTriple = line.slice(start, start + 3) === quote.repeat(3);
  let index = start + (isTriple ? 3 : 1);

  while (index < line.length) {
    if (line[index] === "\\") {
      index += 2;
      continue;
    }
    if (isTriple && line.slice(index, index + 3) === quote.repeat(3)) return index + 3;
    if (!isTriple && line[index] === quote) return index + 1;
    index += 1;
  }

  return line.length;
}

function pythonTokenClass(word, nextText, previousText) {
  const previousWord = previousText.match(/\b(def|class)\s+$/);
  if (previousWord?.[1] === "def") return "function";
  if (previousWord?.[1] === "class") return "class-name";
  if (/^\s*\(/.test(nextText) && !pythonKeywords.has(word)) return pythonBuiltins.has(word) ? "builtin" : "function";
  if (previousText.trimEnd().endsWith("@")) return "decorator";
  if (pythonKeywords.has(word)) return "keyword";
  if (pythonBuiltins.has(word)) return "builtin";
  return "";
}

function token(type, value) {
  return `<span class="code-${type}">${escapeHtml(value)}</span>`;
}

function renderDebugCards() {
  const tones = assignDebugCardTones(lessonPack.bug_cards);
  return `
    <div class="debug-list">
      ${lessonPack.bug_cards.map((card, index) => renderDebugCard(card, tones[index])).join("")}
    </div>
  `;
}

function renderDebugCard(card, tone) {
  const highlight = highlightedSnippet && card.related_code_snippet.includes(highlightedSnippet) ? " highlight" : "";
  return `
    <article class="debug-card debug-card-${tone}${highlight}" id="${escapeAttr(card.id)}">
      <h3>${escapeHtml(card.title)}</h3>
      <div class="card-meta">
        <span class="meta-badge">${escapeHtml(card.error_type)}</span>
        <span class="meta-badge">${escapeHtml(card.teaching_concept)}</span>
        <span class="meta-badge">${escapeHtml(card.code_location)}</span>
      </div>
      <p>${escapeHtml(card.classroom_symptom)}</p>
      <details open>
        <summary>${escapeHtml(t("teachingFlow"))}</summary>
        <h4>${escapeHtml(t("guidingQuestions"))}</h4>
        ${unorderedList(card.guiding_questions)}
        <h4>${escapeHtml(t("progressiveHints"))}</h4>
        ${unorderedList(card.progressive_hints)}
      </details>
      <details>
        <summary>${escapeHtml(t("explanation"))}</summary>
        <p>${escapeHtml(card.teacher_explanation)}</p>
        <p><strong>${escapeHtml(t("fix"))}</strong> ${escapeHtml(card.fix_summary)}</p>
      </details>
      <details>
        <summary>${escapeHtml(t("extension"))}</summary>
        <p>${escapeHtml(card.extension_activity)}</p>
      </details>
      <div class="button-row">
        <button class="secondary-btn" data-copy-card="${card.id}" type="button">${escapeHtml(t("copyCard"))}</button>
        <button class="secondary-btn" data-highlight="${escapeAttr(card.related_code_snippet)}" type="button">${escapeHtml(t("highlightCode"))}</button>
      </div>
    </article>
  `;
}

function assignDebugCardTones(cards) {
  const used = new Set();
  return cards.map((card, index) => {
    const preferred = preferredDebugCardTone(card, index);
    const tone = [preferred, ...debugCardPalette].find((item) => !used.has(item));
    used.add(tone);
    return tone;
  });
}

const debugCardPalette = ["rose", "amber", "blue", "violet", "green"];

function preferredDebugCardTone(card, index) {
  const errorType = String(card.error_type || "").toLowerCase();
  const text = `${card.error_type} ${card.title} ${card.teaching_concept}`.toLowerCase();

  if (errorType.includes("logic") || errorType.includes("邏輯")) return "green";
  if (errorType.includes("nameerror")) return "rose";
  if (errorType.includes("typeerror")) return "amber";
  if (errorType.includes("valueerror")) return "blue";
  if (errorType.includes("syntax") || errorType.includes("indent") || errorType.includes("語法") || errorType.includes("縮排")) return "violet";

  if (text.includes("邏輯") || text.includes("while") || text.includes("loop") || text.includes("條件")) return "green";
  if (text.includes("nameerror") || text.includes("未定義") || text.includes("變數名稱")) return "rose";
  if (text.includes("typeerror") || text.includes("類型") || text.includes("int")) return "amber";
  if (text.includes("valueerror") || text.includes("輸入")) return "blue";
  if (text.includes("syntax") || text.includes("indent") || text.includes("語法") || text.includes("縮排")) return "violet";

  return debugCardPalette[index % debugCardPalette.length];
}

function renderRunner() {
  const code = getCode(activeCode);
  const suggested = activeCode === "buggy" ? lessonPack.run_suggestions.buggy_input : lessonPack.run_suggestions.master_input;
  const suggestedLines = suggested.split("\n").filter((line) => line.length > 0);
  const output = runSession ? runSession.output : formatRunResult(runResult);
  const running = Boolean(runSession && runSession.running);
  return `
    <section class="runner-panel">
      <h3>${escapeHtml(t("runCodeTitle", { kind: kindLabel(activeCode) }))}</h3>
      <div class="runner-controls">
        <button class="primary-btn" data-run-code="${activeCode}" type="button">${escapeHtml(t("runCode"))}</button>
        <button class="secondary-btn" data-stop-run type="button" ${running ? "" : "disabled"}>${escapeHtml(t("stop"))}</button>
      </div>
      <pre id="terminalOutput" class="output-box terminal-output">${escapeHtml(output)}</pre>
      <div class="terminal-input-row">
        <input id="terminalInput" class="terminal-input" type="text" placeholder="${escapeAttr(t("inputPlaceholder"))}" ${running ? "" : "disabled"} />
        <button class="secondary-btn" data-send-input type="button" ${running ? "" : "disabled"}>${escapeHtml(t("enter"))}</button>
      </div>
      ${
        suggestedLines.length
          ? `<div class="suggestion-row">${suggestedLines
              .map((line) => `<button class="secondary-btn suggestion-btn" data-suggested-input="${escapeAttr(line)}" type="button" ${running ? "" : "disabled"}>${escapeHtml(line)}</button>`)
              .join("")}</div>`
          : ""
      }
      ${runSession && runSession.explanation ? renderErrorExplanation(runSession.explanation) : ""}
      ${runResult && runResult.explanation && !runSession ? renderErrorExplanation(runResult.explanation) : ""}
      <details>
        <summary>${escapeHtml(t("codeToRun"))}</summary>
        <pre class="code-block">${renderCodeLines(code)}</pre>
      </details>
    </section>
  `;
}

function renderErrorExplanation(explanation) {
  return `
    <div class="error-explain">
      <strong>${escapeHtml(explanation.error_type)} · ${escapeHtml(explanation.teaching_concept)}</strong>
      <p>${escapeHtml(explanation.explanation)}</p>
    </div>
  `;
}

function wireDynamicButtons() {
  document.querySelectorAll("[data-copy-code]").forEach((button) => {
    button.addEventListener("click", () => copyText(getCode(button.dataset.copyCode)));
  });

  document.querySelectorAll("[data-run-code]").forEach((button) => {
    button.addEventListener("click", () => runCode(button.dataset.runCode));
  });

  document.querySelectorAll("[data-stop-run]").forEach((button) => {
    button.addEventListener("click", () => stopRunSession());
  });

  document.querySelectorAll("[data-send-input]").forEach((button) => {
    button.addEventListener("click", sendTerminalInput);
  });

  document.querySelectorAll("[data-suggested-input]").forEach((button) => {
    button.addEventListener("click", () => sendTerminalInput(button.dataset.suggestedInput));
  });

  const terminalInput = el("terminalInput");
  if (terminalInput) {
    terminalInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        sendTerminalInput();
      }
    });
  }

  document.querySelectorAll("[data-copy-card]").forEach((button) => {
    button.addEventListener("click", () => {
      const card = lessonPack.bug_cards.find((item) => item.id === button.dataset.copyCard);
      copyText(formatCard(card));
    });
  });

  document.querySelectorAll("[data-highlight]").forEach((button) => {
    button.addEventListener("click", () => {
      highlightedSnippet = button.dataset.highlight;
      activeTab = "buggy";
      renderTabs();
      renderTabContent();
    });
  });
}

async function runCode(kind) {
  activeCode = kind;
  await stopRunSession(true);
  el("runStatus").textContent = t("runRunning");
  activeTab = "run";
  renderTabs();
  renderTabContent();

  const response = await fetch("/api/run-session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code: getCode(kind), language: currentLanguageName() }),
  });
  runSession = await response.json();
  runResult = null;
  updateRunStatus();
  renderTabContent();
  startRunPolling();
}

function formatRunResult(result) {
  if (!result) return t("pressRun");
  const parts = [];
  if (result.stdout) parts.push(`STDOUT\n${result.stdout}`);
  if (result.stderr) parts.push(`STDERR\n${result.stderr}`);
  return parts.join("\n") || t("noOutput");
}

function startRunPolling() {
  if (runPollTimer) clearInterval(runPollTimer);
  runPollTimer = setInterval(pollRunSession, 350);
}

async function pollRunSession() {
  if (!runSession) {
    clearRunPolling();
    return;
  }

  try {
    const response = await fetch(`/api/run-session/${runSession.session_id}`);
    if (!response.ok) throw new Error("Run session missing");
    runSession = await response.json();
    updateRunStatus();
    renderRunnerState();
    if (!runSession.running) clearRunPolling();
  } catch {
    el("runStatus").textContent = t("runUnavailable");
    clearRunPolling();
  }
}

function clearRunPolling() {
  if (runPollTimer) {
    clearInterval(runPollTimer);
    runPollTimer = null;
  }
}

async function sendTerminalInput(value) {
  if (!runSession || !runSession.running) return;

  const input = el("terminalInput");
  const text = value ?? input?.value ?? "";
  if (input) input.value = "";

  runSession.output = `${runSession.output || ""}${text}\n`;
  renderRunnerState();

  const response = await fetch(`/api/run-session/${runSession.session_id}/input`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (response.ok) {
    runSession = await response.json();
    updateRunStatus();
    renderRunnerState();
  }
}

async function stopRunSession(silent = false) {
  clearRunPolling();
  if (!runSession || !runSession.running) {
    runSession = null;
    if (!silent) {
      el("runStatus").textContent = t("runIdle");
      renderTabContent();
    }
    return;
  }

  await fetch(`/api/run-session/${runSession.session_id}`, { method: "DELETE" });
  runSession = null;
  if (!silent) {
    el("runStatus").textContent = t("runStopped");
    renderTabContent();
  }
}

function updateRunStatus() {
  if (!runSession) {
    el("runStatus").textContent = t("runIdle");
  } else if (runSession.running) {
    el("runStatus").textContent = t("runRunning");
  } else if (runSession.exit_code === 0) {
    el("runStatus").textContent = t("runSuccess");
  } else {
    el("runStatus").textContent = t("runError", { error: runSession.error_type || "error" });
  }
}

function renderRunnerState() {
  if (activeTab !== "run") return;

  const output = el("terminalOutput");
  if (output && runSession) {
    output.textContent = runSession.output || "";
    output.scrollTop = output.scrollHeight;
  }

  const input = el("terminalInput");
  if (input && runSession) {
    input.disabled = !runSession.running;
  }

  document.querySelectorAll("[data-send-input], [data-suggested-input], [data-stop-run]").forEach((button) => {
    button.disabled = !runSession || !runSession.running;
  });

  if (runSession && !runSession.running && runSession.explanation) {
    renderTabContent();
  }
}

function getCode(kind) {
  if (kind === "starter") return lessonPack.starter_code;
  if (kind === "buggy") return lessonPack.buggy_code;
  return lessonPack.master_code;
}

function kindLabel(kind) {
  return t(`codeKinds.${kind}`);
}

function iconSvg(name) {
  const paths = {
    lesson: '<path d="M5 5h6v14H5z"/><path d="M13 5h6v14h-6z"/><path d="M8 9h1"/><path d="M16 9h1"/><path d="M8 13h1"/><path d="M16 13h1"/>',
    master: '<path d="m8 9-3 3 3 3"/><path d="m16 9 3 3-3 3"/><path d="m14 5-4 14"/>',
    starter: '<path d="M4 20h16"/><path d="M6 16 17 5l2 2L8 18l-4 1z"/>',
    buggy: '<path d="M12 3 22 20H2z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    cards: '<path d="M7 4h10v16H7z"/><path d="M4 7h3"/><path d="M17 7h3"/><path d="M10 9h4"/><path d="M10 13h4"/>',
    run: '<path d="M4 5h16v14H4z"/><path d="m8 9 3 3-3 3"/><path d="M13 15h4"/>',
    warmUp: '<path d="M12 4v2"/><path d="M12 18v2"/><path d="M4 12h2"/><path d="M18 12h2"/><path d="m6.3 6.3 1.4 1.4"/><path d="m16.3 16.3 1.4 1.4"/><path d="m17.7 6.3-1.4 1.4"/><path d="m7.7 16.3-1.4 1.4"/><circle cx="12" cy="12" r="3"/>',
    buildActivity: '<path d="M14 6 6 14"/><path d="m5 15 4 4"/><path d="m15 5 4 4"/><path d="M9 19 19 9"/>',
    debugActivity: '<path d="M8 8h8v8H8z"/><path d="M12 4v4"/><path d="M12 16v4"/><path d="M4 12h4"/><path d="M16 12h4"/><path d="m9 9 6 6"/><path d="m15 9-6 6"/>',
    wrapUp: '<path d="M5 12 10 17 20 7"/><path d="M4 20h16"/>',
    teacherNotes: '<path d="M6 4h12v16H6z"/><path d="M9 8h6"/><path d="M9 12h6"/><path d="M9 16h3"/>',
    runSuggestions: '<path d="M4 5h16v14H4z"/><path d="m8 9 3 3-3 3"/><path d="M13 15h4"/>',
  };
  return `
    <svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      ${paths[name] || paths.lesson}
    </svg>
  `;
}

function numberedFlow(value) {
  const items = flowItems(value);
  if (!items.length) return "";
  return orderedList(items);
}

function flowItems(value) {
  const source = Array.isArray(value) ? value : [value];
  if (Array.isArray(value)) {
    return source
      .flatMap((item) => {
        const numbered = splitNumberedText(item);
        return numbered.length ? numbered : [stripListMarker(item)];
      })
      .filter(Boolean);
  }

  return source
    .flatMap((item) => {
      const numbered = splitNumberedText(item);
      return numbered.length ? numbered : splitTextBlocks(item);
    })
    .map(stripListMarker)
    .filter(Boolean);
}

function splitNumberedText(value) {
  const text = String(value || "").replace(/\r\n/g, "\n").trim();
  if (!text) return [];

  const markerPattern = /(^|\n|\s)(?:\d+[\.)]|\d+\u3001|[\uff11-\uff19][\.)\u3001\uff0e])\s+/g;
  const matches = Array.from(text.matchAll(markerPattern));
  if (!matches.length) return [];

  return matches
    .map((match, index) => {
      const start = match.index + match[0].length;
      const end = index + 1 < matches.length ? matches[index + 1].index + matches[index + 1][1].length : text.length;
      return stripListMarker(text.slice(start, end));
    })
    .filter(Boolean);
}

function stripListMarker(value) {
  return String(value || "")
    .replace(/^\s*(?:\d+[\.)]|\d+\u3001|[\uff11-\uff19][\.)\u3001\uff0e])\s+/, "")
    .trim();
}

function orderedList(items) {
  return `<ol class="flow-list">${items.map((item) => renderListItem(item)).join("")}</ol>`;
}

function unorderedList(items) {
  return orderedList(items);
}

function renderListItem(item) {
  return `<li>${escapeHtml(stripListMarker(item))}</li>`;
}

function renderTextBlocks(value) {
  const blocks = splitTextBlocks(value);
  if (!blocks.length) return "";
  return blocks.map((block) => `<p>${renderInlineText(block)}</p>`).join("");
}

function renderInlineText(value) {
  return splitSentences(value)
    .map((line) => `<span class="flow-line">${escapeHtml(line)}</span>`)
    .join("");
}

function splitTextBlocks(value) {
  return String(value || "")
    .split(/\r?\n+/)
    .flatMap((line) => splitSentences(line))
    .filter(Boolean);
}

function splitSentences(value) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) return [];

  const sentences = text.match(/[^!?。！？；;]+[!?。！？；;]?/g) || [text];
  return sentences.map((sentence) => sentence.trim()).filter(Boolean);
}

function splitInlineList(value, listTag) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) return { lead: "", children: [] };

  const markerPattern =
    listTag === "ol"
      ? /(^|[\s:：;；])(?:\d+[\.)\u3001\uff0e]|[\uff11-\uff19][\.)\uff0e\u3001])\s+/g
      : /(^|[\s:：;；])[-*•]\s+/g;
  const matches = Array.from(text.matchAll(markerPattern));
  if (!matches.length) return { lead: text, children: [] };

  const lead = text.slice(0, matches[0].index + matches[0][1].length).trim();
  const children = matches
    .map((match, index) => {
      const start = match.index + match[0].length;
      const end = index + 1 < matches.length ? matches[index + 1].index + matches[index + 1][1].length : text.length;
      return text.slice(start, end).trim();
    })
    .filter(Boolean);

  return { lead, children };
}

async function copyAll() {
  await copyText(JSON.stringify(lessonPack, null, 2));
}

async function copyText(text) {
  await navigator.clipboard.writeText(text);
}

function formatCard(card) {
  return [
    card.title,
    `${t("errorType")}: ${card.error_type}`,
    `${t("teachingConcept")}: ${card.teaching_concept}`,
    `${t("location")}: ${card.code_location}`,
    `${t("symptom")}: ${card.classroom_symptom}`,
    `${t("questions")}: ${card.guiding_questions.join(" / ")}`,
    `${t("hints")}: ${card.progressive_hints.join(" / ")}`,
    `${t("explanation")}: ${card.teacher_explanation}`,
    `${t("fix")} ${card.fix_summary}`,
  ].join("\n");
}

async function resetApp() {
  await stopRunSession(true);
  lessonPack = null;
  activeTab = "lesson";
  activeCode = "master";
  highlightedSnippet = "";
  runResult = null;
  modelStreamText = "";
  lessonFlowRevealCount = null;
  el("lessonForm").reset();
  el("topic").value = "";
  el("formError").textContent = "";
  el("resultView").classList.add("hidden");
  el("emptyState").classList.remove("hidden");
  el("streamPanel")?.classList.add("hidden");
  setStreamCollapsed(true);
  if (el("modelStream")) el("modelStream").textContent = "";
  updateStreamStatus(t("waitingGeneration"));
  el("lastGenerated").textContent = t("lastGeneratedEmpty");
  el("jsonStatus").textContent = t("jsonWaiting");
  el("runStatus").textContent = t("runIdle");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("\n", " ");
}
