---
name: debug-pack-browser-sampler
description: Browser-based QA workflow for this Python Debug Pack Generator project. Use when Codex must generate multiple lesson packs from the actual in-app browser UI, let the user choose the sample count, randomize diverse Python lesson topics, and catch false Debug Card accusations where a card claims correct or present buggy code is wrong, missing, undefined, or syntactically invalid.
---

# Debug Pack Browser Sampler

## Purpose

Use this skill to test Debug Card truthfulness through the real browser UI, starting from the topic textarea. The goal is to catch cards that accuse correct code, not just backend schema failures.

## Workflow

1. Ask the user how many samples to run if they did not specify a number. Use 5 only when they asks for the default.
2. Use the Browser skill, not API-only tests. Start from the project app URL, usually `http://127.0.0.1:8019/`.
3. Load `scripts/browser_sampler.mjs` into the Node/browser runtime after `tab` is available.
4. Run `runDebugPackBrowserSampler({ tab, count, baseUrl })`.
5. Treat any non-empty `issues` as a real failure until inspected. Fix the generator or checker, restart the app server, then rerun a fresh randomized set.
6. Report the final sampled topics, domains, titles, and issue counts.

## Required Checks

The sampler must flag these false accusations:

- A card says a defined variable or definition line is `NameError`.
- A card says `import random` is missing when the buggy code imports it.
- A card says `input(...)` is missing parentheses when the code visibly has `input(...)`.
- A card says input was not converted when the code already has `int(name)` or `float(name)` before comparison.
- A card invents `SyntaxError` when the visible code contradicts the claimed missing quote/bracket/colon.
- A card says if/elif branches both run, or suggests using `elif`, when the code already uses an `if/elif/else` chain.
- A runtime/logic card appears beside a SyntaxError card without saying it is observed after fixing the SyntaxError first.
- A card says the bug does not exist or asks the user to ignore the card.

## Diverse Topic Sampling

Use randomized topics across different domains. Include a mix of:

- random game / score loop
- math conversion / numeric input
- list average / aggregation
- dictionary lookup
- string validation
- menu / if-elif-else
- loop counter / attempts
- function call / return value
- file-free text processing
- simple nested condition

Do not reuse the exact same topic list on every run. Shuffle by default; if the user gives a seed, use it.

## Browser Input Rules

Prefer keyboard-style input over `fill()` when the in-app browser clipboard bridge fails. Clear the form first, then type ASCII topics character by character. Verify the textarea value equals the intended topic before clicking Generate.

## Resource

Use [browser_sampler.mjs](scripts/browser_sampler.mjs) for the reusable browser-side helper.
