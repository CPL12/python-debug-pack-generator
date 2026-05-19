const DEFAULT_BASE_URL = "http://127.0.0.1:8019/";

const TOPIC_POOLS = [
  ["random-game", ["random mine game score loop", "dice guessing game random score", "treasure hunt randint attempts"]],
  ["math-conversion", ["temperature conversion float input", "currency converter percentage fee", "bmi calculator float input"]],
  ["list-average", ["student score list average", "shopping cart list total", "rainfall list maximum average"]],
  ["dictionary-lookup", ["phone book dictionary lookup", "menu price dictionary lookup", "country capital dictionary quiz"]],
  ["string-validation", ["password strength string length", "email username string check", "palindrome string checker"]],
  ["if-elif-menu", ["simple calculator menu if elif", "traffic light decision if elif", "grade classifier if elif"]],
  ["loop-counter", ["quiz attempts loop counter", "countdown while loop", "savings target loop"]],
  ["function-return", ["area calculator function return", "discount function return value", "score bonus function call"]],
  ["text-processing", ["word counter text split", "initials generator string split", "sentence vowel counter"]],
  ["nested-condition", ["ticket price nested condition", "weather advice nested if", "game level unlock condition"]],
];

function shuffle(items, rng = Math.random) {
  const copy = [...items];
  for (let index = copy.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(rng() * (index + 1));
    [copy[index], copy[swapIndex]] = [copy[swapIndex], copy[index]];
  }
  return copy;
}

function seededRandom(seedText) {
  let seed = 0;
  for (const char of String(seedText)) seed = (seed * 31 + char.charCodeAt(0)) >>> 0;
  return () => {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    return seed / 0x100000000;
  };
}

export function chooseDebugPackTopics(count, seed = "") {
  const rng = seed ? seededRandom(seed) : Math.random;
  const pools = shuffle(TOPIC_POOLS, rng);
  const topics = [];
  while (topics.length < count) {
    for (const [domain, variants] of pools) {
      const topic = shuffle(variants, rng)[0];
      topics.push({ domain, topic });
      if (topics.length >= count) break;
    }
  }
  return topics;
}

async function sleep(ms) {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

async function pressAsciiText(tab, locator, text) {
  await locator.click({ timeoutMs: 10000 });
  await locator.press("Control+A", { timeoutMs: 10000 });
  await locator.press("Backspace", { timeoutMs: 10000 });
  for (const char of text) {
    if (char === " ") await locator.press("Space", { timeoutMs: 5000 });
    else await locator.press(char.toLowerCase(), { timeoutMs: 5000 });
  }
  const actual = await tab.playwright.evaluate(
    () => document.querySelector("#topic")?.value || "",
    null,
    { timeoutMs: 5000 },
  );
  if (actual !== text) throw new Error(`topic input mismatch: wanted "${text}", got "${actual}"`);
}

async function waitForGeneration(tab, topic, timeoutMs = 150000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const state = await tab.playwright.evaluate(
      () => ({
        title: document.querySelector("#lessonTitle")?.textContent || "",
        status: document.querySelector("#generateState")?.textContent || "",
        error: document.querySelector("#formError")?.textContent || "",
        tabsText: document.querySelector("#tabs")?.textContent || "",
        json: document.querySelector("#jsonStatus")?.textContent || "",
      }),
      null,
      { timeoutMs: 5000 },
    );
    if (state.error) throw new Error(`${topic}: ${state.error} ${state.json}`);
    if (
      state.status === "Ready" &&
      state.title &&
      state.title !== "Generating debug pack..." &&
      state.tabsText.includes("Debug Cards")
    ) {
      return state;
    }
    await sleep(1000);
  }
  throw new Error(`${topic}: generation timed out`);
}

async function clickTab(tab, name) {
  const button = tab.playwright.getByRole("button", { name, exact: true });
  const count = await button.count();
  if (count !== 1) throw new Error(`${name} tab not unique; count=${count}`);
  await button.click({ timeoutMs: 10000 });
  await sleep(250);
}

async function extractViews(tab) {
  await clickTab(tab, "Buggy Code");
  const code = await tab.playwright.evaluate(
    () => Array.from(document.querySelectorAll(".line-text")).map((node) => node.innerText).join("\n"),
    null,
    { timeoutMs: 5000 },
  );
  const buggyText = await tab.playwright.evaluate(
    () => document.querySelector("#tabContent")?.innerText || "",
    null,
    { timeoutMs: 5000 },
  );
  await clickTab(tab, "Debug Cards");
  const cardsText = await tab.playwright.evaluate(
    () => document.querySelector("#tabContent")?.innerText || "",
    null,
    { timeoutMs: 5000 },
  );
  const title = await tab.playwright.evaluate(
    () => document.querySelector("#lessonTitle")?.textContent || "",
    null,
    { timeoutMs: 5000 },
  );
  return { title, code, buggyText, cardsText };
}

function lineBindsNameWithoutSelfReference(line, name) {
  const match = line.match(new RegExp(`^\\s*${name}\\s*=`));
  if (!match) return false;
  const rhs = line.slice(match[0].length);
  return !new RegExp(`\\b${name}\\b`).test(rhs);
}

function convertedInputNames(code) {
  const inputNames = new Set();
  const convertedNames = new Set();
  for (const line of code.split("\n")) {
    let match = line.match(/^\s*([A-Za-z_]\w*)\s*=\s*input\s*\(/);
    if (match) {
      inputNames.add(match[1]);
      continue;
    }
    match = line.match(/^\s*([A-Za-z_]\w*)\s*=\s*(?:int|float)\s*\(\s*input\s*\(/);
    if (match) {
      convertedNames.add(match[1]);
      continue;
    }
    match = line.match(/^\s*([A-Za-z_]\w*)\s*=\s*(?:int|float)\s*\(\s*([A-Za-z_]\w*)\s*\)/);
    if (match && inputNames.has(match[2])) {
      convertedNames.add(match[1]);
      convertedNames.add(match[2]);
    }
  }
  return convertedNames;
}

function claimsInputMissingParentheses(cards) {
  const blocks = cards.split(/\nCopy Card\nHighlight Code\n?/).filter(Boolean);
  return blocks.some((block) => {
    const lower = block.toLowerCase();
    if (!/input/.test(lower)) return false;
    if (!/(parentheses|bracket|括號)/i.test(block)) return false;
    if (!/(missing|forgot|needs|need|缺少|遺漏|忘記|未加|沒有)/i.test(block)) return false;

    const compact = block.replace(/\s+/g, " ");
    return /input.{0,80}(parentheses|bracket|括號)|(?:parentheses|bracket|括號).{0,80}input/i.test(compact);
  });
}

function analyzeViews(views) {
  const issues = [];
  const code = views.code;
  const cards = views.cardsText;
  const lowerCards = cards.toLowerCase();

  if (!views.buggyText.includes("Buggy Code")) issues.push("Buggy Code tab did not render");
  if (!cards.includes("Teaching Flow")) issues.push("Debug Cards tab did not render");
  if (/bug 唔存在|請忽略|does not exist|ignore this/i.test(cards)) issues.push("card says bug does not exist");

  if (/input\s*\(/.test(code) && claimsInputMissingParentheses(cards)) {
    if (!/\binput\b(?!\s*\()/.test(code)) issues.push("card claims input parentheses issue but code has input(...)");
  }

  if (/(^|\n)\s*import\s+random\b/.test(code) && /import random/i.test(cards) && /(forgot|忘記|沒有|未引入)/i.test(cards)) {
    issues.push("card claims import random missing but code imports random");
  }

  const convertedNames = convertedInputNames(code);
  const conversionClaim = /(未|忘記|沒有|not converted|without converting).*(\bint\s*\(|\bfloat\s*\(|int|float|轉型|轉換)/i.test(cards);
  if (convertedNames.size > 0 && conversionClaim) {
    for (const name of convertedNames) {
      if (new RegExp(`\\b${name}\\b`).test(cards)) {
        issues.push("card claims input not converted but code converts input");
        break;
      }
    }
  }

  const hasIfElif = /(^|\n)\s*if\b[\s\S]*\n\s*elif\b/.test(code);
  const hasElseIf = /(^|\n)\s*else\s+if\b/.test(code);
  const hasInvalidElseCondition = /(^|\n)\s*else\s+\S.*:/.test(code);
  if (hasIfElif && !hasElseIf && !hasInvalidElseCondition && /(兩個訊息|兩個輸出|two messages|both|應該用 elif|should use elif)/i.test(cards)) {
    issues.push("card claims if/elif branches both run or suggests elif when code already uses elif");
  }

  const hasSyntaxCard = /SyntaxError|語法錯誤/.test(cards);
  if (hasSyntaxCard) {
    const runtimeClaim = /(執行(?:時|後)出現 (?!SyntaxError)[A-Za-z]+Error|邏輯錯誤|Logic Error)/.test(cards);
    if (runtimeClaim && !/(修正 SyntaxError 後|修正語法錯誤後)/.test(cards)) {
      issues.push("runtime card is not qualified after SyntaxError");
    }
    if (/缺少右引號|missing quote/i.test(cards) && !/(input\([^\n]*['"][^\n]*$)/.test(code)) {
      issues.push("card claims missing quote but visible code does not show that");
    }
  }

  const cardBlocks = cards.split(/\nCopy Card\nHighlight Code\n?/).filter(Boolean);
  for (const block of cardBlocks) {
    const nameMatch = block.match(/name ['"]([A-Za-z_]\w*)['"] is not defined/);
    if (!nameMatch) continue;
    const name = nameMatch[1];
    for (const line of block.split("\n")) {
      const cleaned = line.trim().replace(/^第\d+行[:：]?\s*/, "").replace(/^line\s*\d+[:：]?\s*/i, "");
      if (lineBindsNameWithoutSelfReference(cleaned, name)) {
        issues.push(`card accuses definition line for ${name}`);
      }
    }
  }

  return [...new Set(issues)];
}

async function clearForm(tab) {
  const clearButton = tab.playwright.getByRole("button", { name: "Clear", exact: true });
  if ((await clearButton.count()) === 1) {
    await clearButton.click({ timeoutMs: 10000 });
    await sleep(250);
  }
}

async function ensureEnglishUi(tab) {
  const language = await tab.playwright.evaluate(
    () => document.documentElement.lang,
    null,
    { timeoutMs: 5000 },
  );
  if (language !== "en") {
    const englishButton = tab.playwright.getByRole("button", { name: "Switch language to English", exact: true });
    if ((await englishButton.count()) !== 1) throw new Error("English language button not unique");
    await englishButton.click({ timeoutMs: 10000 });
    await sleep(250);
  }
}

async function runOne(tab, baseUrl, sample) {
  if ((await tab.url()) !== baseUrl) {
    await tab.goto(baseUrl);
    await tab.playwright.waitForLoadState({ state: "domcontentloaded", timeoutMs: 10000 });
  }
  await ensureEnglishUi(tab);
  await clearForm(tab);
  const topicBox = tab.playwright.locator("#topic");
  if ((await topicBox.count()) !== 1) throw new Error("topic textbox not unique");
  await pressAsciiText(tab, topicBox, sample.topic);
  const generateButton = tab.playwright.getByRole("button", { name: "Generate Debug Pack", exact: true });
  if ((await generateButton.count()) !== 1) throw new Error("Generate button not unique");
  await generateButton.click({ timeoutMs: 10000 });
  await waitForGeneration(tab, sample.topic);
  const views = await extractViews(tab);
  return {
    domain: sample.domain,
    topic: sample.topic,
    title: views.title,
    issues: analyzeViews(views),
    buggyPreview: views.code.slice(0, 600),
    cardsPreview: views.cardsText.slice(0, 1000),
  };
}

export async function runDebugPackBrowserSampler({ tab, count = 5, baseUrl = DEFAULT_BASE_URL, seed = "" }) {
  const samples = chooseDebugPackTopics(count, seed);
  const results = [];
  for (const sample of samples) {
    results.push(await runOne(tab, baseUrl, sample));
  }
  return {
    count,
    baseUrl,
    seed,
    passed: results.every((result) => result.issues.length === 0),
    results,
  };
}
