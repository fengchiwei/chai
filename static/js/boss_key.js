// 一鍵防窺偽裝（Boss Key）：Esc／「📚 單字卡」按鈕／連點兩下標題，立即切換成可真實操作的單字卡與數學公式測驗。
// 只切換顯示，不清除輸入框與對話；返回時若「立即求助」面板仍在，焦點會回到求助電話。
(() => {
  "use strict";
  const byId = id => document.getElementById(id);
  const ESC_GRACE_MS = 600; // 連按兩下 Esc 時，第二下不會立刻又切回來。
  const DISGUISE_TITLE = "高中英文 7000 單字 ‧ 學習卡";

  let overlay = null;
  let active = false;
  let shownAt = 0;
  let savedTitle = "";
  let savedFocus = null;
  let inerted = [];
  let returnButton = null;
  let urgentObserver = null;

  const vocab = Array.isArray(window.ANLA_VOCAB) && window.ANLA_VOCAB.length
    ? window.ANLA_VOCAB.slice() : [{ word: "focus", pos: "v.", zh: "專注；集中" }];
  const quiz = Array.isArray(window.ANLA_MATH_QUIZ) ? window.ANLA_MATH_QUIZ : [];
  const state = { tab: "vocab", index: 0, flipped: false, known: new Set(), q: 0, answers: {} };

  function el(tag, attrs = {}, text = "") {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (key === "class") node.className = value;
      else if (key === "dataset") Object.assign(node.dataset, value);
      else node.setAttribute(key, value);
    }
    if (text) node.textContent = text;
    return node;
  }

  function build() {
    overlay = el("div", { id: "bossOverlay", class: "boss-overlay", role: "dialog", "aria-modal": "true", "aria-labelledby": "bossTitle" });
    overlay.hidden = true;

    const bar = el("header", { class: "boss-bar" });
    const title = el("div", { class: "boss-title", id: "bossTitle" });
    title.append(el("span", { class: "boss-logo", "aria-hidden": "true" }, "📘"), el("span", {}, "高中英文核心 7000 單字 ‧ 數學公式複習"));
    const tabs = el("div", { class: "boss-tabs", role: "tablist", "aria-label": "複習項目" });
    const vocabTab = el("button", { type: "button", role: "tab", id: "bossTabVocab", "aria-controls": "bossVocab", class: "boss-tab" }, "英文單字卡");
    const mathTab = el("button", { type: "button", role: "tab", id: "bossTabMath", "aria-controls": "bossMath", class: "boss-tab" }, "數學公式測驗");
    vocabTab.addEventListener("click", () => switchTab("vocab"));
    mathTab.addEventListener("click", () => switchTab("math"));
    tabs.append(vocabTab, mathTab);
    returnButton = el("button", { type: "button", class: "boss-return", id: "bossReturn", "aria-label": "返回" }, "返回");
    returnButton.addEventListener("click", hide);
    bar.append(title, tabs, returnButton);

    // 單字卡
    const vocabPanel = el("section", { id: "bossVocab", class: "boss-panel", role: "tabpanel", "aria-labelledby": "bossTabVocab" });
    const vocabMeta = el("div", { class: "boss-progress", id: "bossVocabProgress" });
    const card = el("button", { type: "button", class: "flashcard", id: "bossCard", "aria-live": "polite" });
    const inner = el("span", { class: "flashcard-inner" });
    const front = el("span", { class: "flashcard-face flashcard-front" });
    front.append(el("span", { class: "flashcard-word", id: "bossWord" }), el("span", { class: "flashcard-hint" }, "點一下翻面看中文"));
    const back = el("span", { class: "flashcard-face flashcard-back" });
    back.append(el("span", { class: "flashcard-word small", id: "bossWordBack" }), el("span", { class: "flashcard-pos", id: "bossPos" }), el("span", { class: "flashcard-zh", id: "bossZh" }));
    inner.append(front, back);
    card.append(inner);
    card.addEventListener("click", () => { state.flipped = !state.flipped; renderVocab(); });
    const vocabControls = el("div", { class: "boss-controls" });
    const prev = el("button", { type: "button", class: "boss-btn" }, "← 上一張");
    const shuffle = el("button", { type: "button", class: "boss-btn" }, "🔀 打亂順序");
    const known = el("button", { type: "button", class: "boss-btn", id: "bossKnown", "aria-pressed": "false" }, "✓ 記住了");
    const next = el("button", { type: "button", class: "boss-btn boss-btn-primary" }, "下一張 →");
    prev.addEventListener("click", () => stepVocab(-1));
    next.addEventListener("click", () => stepVocab(1));
    shuffle.addEventListener("click", () => {
      for (let i = vocab.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [vocab[i], vocab[j]] = [vocab[j], vocab[i]];
      }
      state.index = 0; state.flipped = false; renderVocab();
    });
    known.addEventListener("click", () => {
      const word = vocab[state.index].word;
      if (state.known.has(word)) state.known.delete(word); else state.known.add(word);
      renderVocab();
    });
    vocabControls.append(prev, shuffle, known, next);
    vocabPanel.append(vocabMeta, card, vocabControls, el("p", { class: "boss-tip" }, "小技巧：← → 鍵切換，空白鍵翻面。"));

    // 數學測驗
    const mathPanel = el("section", { id: "bossMath", class: "boss-panel", role: "tabpanel", "aria-labelledby": "bossTabMath" });
    mathPanel.hidden = true;
    const mathMeta = el("div", { class: "boss-progress", id: "bossMathProgress" });
    const question = el("div", { class: "quiz-question", id: "bossQuestion" });
    const options = el("div", { class: "quiz-options", id: "bossOptions", role: "group", "aria-labelledby": "bossQuestion" });
    const feedback = el("p", { class: "quiz-feedback", id: "bossFeedback", role: "status" });
    const mathControls = el("div", { class: "boss-controls" });
    const qPrev = el("button", { type: "button", class: "boss-btn" }, "← 上一題");
    const qNext = el("button", { type: "button", class: "boss-btn boss-btn-primary", id: "bossNextQuestion" }, "下一題 →");
    qPrev.addEventListener("click", () => stepQuiz(-1));
    qNext.addEventListener("click", () => stepQuiz(1));
    mathControls.append(qPrev, qNext);
    mathPanel.append(mathMeta, question, options, feedback, mathControls);

    const body = el("main", { class: "boss-body" });
    body.append(vocabPanel, mathPanel);
    overlay.append(bar, body);
    overlay.addEventListener("keydown", onOverlayKey);
    document.body.appendChild(overlay);
    switchTab("vocab", false);
  }

  function renderVocab() {
    const item = vocab[state.index];
    byId("bossWord").textContent = item.word;
    byId("bossWordBack").textContent = item.word;
    byId("bossPos").textContent = item.pos;
    byId("bossZh").textContent = item.zh;
    const card = byId("bossCard");
    card.classList.toggle("is-flipped", state.flipped);
    card.setAttribute("aria-label", state.flipped
      ? `${item.word}，${item.pos}，${item.zh}。按一下翻回英文`
      : `${item.word}。按一下翻面看中文`);
    const isKnown = state.known.has(item.word);
    const known = byId("bossKnown");
    known.setAttribute("aria-pressed", String(isKnown));
    known.textContent = isKnown ? "✓ 已記住" : "✓ 記住了";
    byId("bossVocabProgress").textContent = `第 ${state.index + 1} / ${vocab.length} 張 ‧ 已記住 ${state.known.size} 個`;
  }

  function stepVocab(delta) {
    state.index = (state.index + delta + vocab.length) % vocab.length;
    state.flipped = false;
    renderVocab();
  }

  function renderQuiz() {
    if (!quiz.length) return;
    const item = quiz[state.q];
    const chosen = state.answers[state.q];
    const correctCount = Object.entries(state.answers).filter(([i, a]) => quiz[i].answer === a).length;
    byId("bossMathProgress").textContent = `第 ${state.q + 1} / ${quiz.length} 題 ‧ 答對 ${correctCount} 題`;
    byId("bossQuestion").textContent = item.q;
    const options = byId("bossOptions");
    options.replaceChildren();
    item.options.forEach((text, index) => {
      const option = el("button", { type: "button", class: "quiz-option" }, `${"ABCD"[index]}. ${text}`);
      if (chosen !== undefined) {
        option.disabled = true;
        if (index === item.answer) option.classList.add("is-correct");
        else if (index === chosen) option.classList.add("is-wrong");
      }
      option.addEventListener("click", () => {
        state.answers[state.q] = index;
        renderQuiz();
        byId("bossNextQuestion").focus();
      });
      options.appendChild(option);
    });
    const feedback = byId("bossFeedback");
    if (chosen === undefined) feedback.textContent = "";
    else feedback.textContent = (chosen === item.answer ? "答對了！" : `答錯了，正解是 ${"ABCD"[item.answer]}。`) + (item.note ? ` ${item.note}` : "");
  }

  function stepQuiz(delta) {
    if (!quiz.length) return;
    state.q = (state.q + delta + quiz.length) % quiz.length;
    renderQuiz();
  }

  function switchTab(tab, focus = true) {
    state.tab = tab;
    const isVocab = tab === "vocab";
    byId("bossVocab").hidden = !isVocab;
    byId("bossMath").hidden = isVocab;
    byId("bossTabVocab").setAttribute("aria-selected", String(isVocab));
    byId("bossTabMath").setAttribute("aria-selected", String(!isVocab));
    byId("bossTabVocab").tabIndex = isVocab ? 0 : -1;
    byId("bossTabMath").tabIndex = isVocab ? -1 : 0;
    if (isVocab) renderVocab(); else renderQuiz();
    if (focus) (isVocab ? byId("bossCard") : byId("bossOptions").querySelector("button:not([disabled])") || byId("bossTabMath")).focus();
  }

  function focusables() {
    return [...overlay.querySelectorAll("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])")]
      .filter(node => !node.disabled && !node.closest("[hidden]") && node.tabIndex !== -1);
  }

  function onOverlayKey(event) {
    if (event.key === "Tab") {
      const items = focusables();
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      return;
    }
    if (event.target.closest?.(".boss-tabs") && (event.key === "ArrowLeft" || event.key === "ArrowRight")) {
      event.preventDefault();
      switchTab(state.tab === "vocab" ? "math" : "vocab");
      return;
    }
    if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
      const delta = event.key === "ArrowRight" ? 1 : -1;
      event.preventDefault();
      if (state.tab === "vocab") stepVocab(delta); else stepQuiz(delta);
    }
  }

  function urgentVisible() {
    const panel = byId("urgentHelpPanel");
    return Boolean(panel && !panel.hidden);
  }

  function markUrgentPending() {
    // 偽裝中若出現立即求助面板，只在「返回」加一個小提示，不打破偽裝。
    if (!returnButton) return;
    const pending = active && urgentVisible();
    returnButton.classList.toggle("has-alert", pending);
    returnButton.setAttribute("aria-label", pending ? "返回（有新的提醒）" : "返回");
  }

  function show() {
    if (active) return;
    if (!overlay) build();
    active = true;
    shownAt = Date.now();
    savedFocus = document.activeElement;
    savedTitle = document.title;
    // 朗讀與錄音會洩漏畫面內容，先停下來（輸入框文字保留）。
    try { window.speechSynthesis?.cancel(); } catch (_) {}
    try { if (typeof isRecording !== "undefined" && isRecording && typeof stopVoiceRecognition === "function") stopVoiceRecognition(); } catch (_) {}
    overlay.hidden = false;
    document.documentElement.classList.add("boss-active");
    document.title = DISGUISE_TITLE;
    inerted = [];
    for (const child of document.body.children) {
      if (child === overlay || child.tagName === "SCRIPT" || child.hasAttribute("inert")) continue;
      child.setAttribute("inert", "");
      child.setAttribute("data-boss-inert", "");
      inerted.push(child);
    }
    const panel = byId("urgentHelpPanel");
    if (panel && !urgentObserver && "MutationObserver" in window) {
      urgentObserver = new MutationObserver(markUrgentPending);
      urgentObserver.observe(panel, { attributes: true, attributeFilter: ["hidden"] });
    }
    markUrgentPending();
    (state.tab === "vocab" ? byId("bossCard") : byId("bossTabMath")).focus({ preventScroll: true });
  }

  function hide() {
    if (!active) return;
    active = false;
    for (const node of inerted) {
      node.removeAttribute("inert");
      node.removeAttribute("data-boss-inert");
    }
    inerted = [];
    overlay.hidden = true;
    document.documentElement.classList.remove("boss-active");
    document.title = savedTitle || document.title;
    returnButton.classList.remove("has-alert");
    // 立即求助面板永遠優先：返回後若仍在，就把焦點交給求助電話。
    const panel = byId("urgentHelpPanel");
    if (urgentVisible() && !panel.classList.contains("is-compact")) {
      byId("urgent119")?.focus();
    } else if (savedFocus && document.contains(savedFocus) && typeof savedFocus.focus === "function") {
      savedFocus.focus({ preventScroll: true });
    }
    savedFocus = null;
  }

  function toggle() { if (active) hide(); else show(); }

  document.addEventListener("keydown", event => {
    if (event.key !== "Escape" || event.isComposing || event.keyCode === 229) return;
    if (active) {
      event.preventDefault();
      if (Date.now() - shownAt < ESC_GRACE_MS) return; // 第二下 Esc：維持偽裝
      hide();
      return;
    }
    // 其他原生對話框（例如手機安裝說明）先讓 Esc 正常關閉它。
    if (document.querySelector("dialog[open]")) return;
    event.preventDefault();
    show();
  }, true);

  function bindDoubleTap(target) {
    // 用 pointerup 自行判斷連點，滑鼠雙擊與手機連點兩下都適用，也不會觸發兩次。
    let last = 0;
    target.addEventListener("pointerup", event => {
      if (event.button !== undefined && event.button > 0) return;
      const now = Date.now();
      if (now - last < 380) {
        last = 0;
        event.preventDefault();
        window.getSelection?.()?.removeAllRanges?.();
        show();
      } else {
        last = now;
      }
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    build();
    byId("bossKeyButton")?.addEventListener("click", show);
    const brand = byId("brandTitle");
    if (brand) bindDoubleTap(brand);
  });

  window.AnlaBossKey = { show, hide, toggle, isActive: () => active };
})();
