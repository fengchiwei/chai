// 身心電力檢核：BSRS-5 六題（含自殺想法附加題）＋困擾持續時間、生活影響、壓力來源、支持系統四個結構化問題。
// 計畫書目標：3 分鐘內完成；結果只給學生白話說明，不顯示燈號或分數（分數只給受訓人員看）。
(() => {
  const byId = id => document.getElementById(id);
  const ITEMS = [
    ["sleep", "睡眠困難，譬如難以入睡、容易醒或太早醒"],
    ["anxiety", "感覺緊張或不安"],
    ["anger", "覺得容易苦惱或動怒"],
    ["depression", "感覺憂鬱、心情低落"],
    ["inferiority", "覺得比不上別人"],
    ["suicide", "有自殺的想法"],
  ];
  const LEVELS = ["完全沒有", "輕微", "中等", "厲害", "非常厲害"];
  const QUESTIONS = [
    ["duration", "這些困擾大概持續多久了？", ["不到一週", "1–2 週", "2 週到 1 個月", "超過 1 個月", "說不上來"]],
    ["life_impact", "有影響到上學或日常生活嗎？", ["沒有", "有一點", "明顯影響（例如不想上學、常請假、吃不下）", "說不上來"]],
    ["category", "最近的壓力主要來自哪裡？", ["課業或考試", "同學或朋友", "家裡", "感情", "身體或睡眠", "說不上來"]],
    ["support_system", "有可以說心事的人嗎？", ["有，而且願意找他", "有，但不太想說", "好像沒有", "說不上來"]],
  ];
  let startedAt = 0;
  let busy = false;

  function radioGroup(name, legend, options, values = options) {
    const set = document.createElement("fieldset");
    set.className = "checkin-item";
    const title = document.createElement("legend");
    title.textContent = legend;
    set.appendChild(title);
    const row = document.createElement("div");
    row.className = "checkin-options";
    options.forEach((label, i) => {
      const id = `checkin_${name}_${i}`;
      const input = document.createElement("input");
      Object.assign(input, {type: "radio", name, id, value: String(values[i]), required: true});
      const text = document.createElement("label");
      text.htmlFor = id;
      text.textContent = label;
      row.append(input, text);
    });
    set.appendChild(row);
    return set;
  }

  function build() {
    const form = byId("checkinForm");
    if (!form || form.dataset.built) return;
    form.dataset.built = "true";
    const items = byId("checkinItems");
    ITEMS.forEach(([key, label], i) => {
      const set = radioGroup(key, `${i + 1}. ${label}${key === "suicide" ? "（附加題）" : ""}`, LEVELS, [0, 1, 2, 3, 4]);
      if (key === "suicide") set.classList.add("checkin-sensitive");
      items.appendChild(set);
    });
    const more = byId("checkinQuestions");
    QUESTIONS.forEach(([key, label, options]) => more.appendChild(radioGroup(key, label, options)));
    form.addEventListener("change", progress);
    form.addEventListener("submit", submit);
  }

  function answered() {
    const form = byId("checkinForm");
    return [...ITEMS.map(([k]) => k), ...QUESTIONS.map(([k]) => k)].filter(k => form.querySelector(`input[name="${k}"]:checked`)).length;
  }

  function progress() {
    const total = ITEMS.length + QUESTIONS.length;
    const done = answered();
    byId("checkinProgress").textContent = `已回答 ${done} / ${total} 題`;
    byId("checkinSubmit").disabled = done < total || busy;
  }

  function open() {
    if (typeof studentOnboarded !== "undefined" && !studentOnboarded) {
      openOnboardingModal(false);
      return;
    }
    build();
    const form = byId("checkinForm");
    form.reset();
    form.hidden = false;
    byId("checkinResult").hidden = true;
    byId("checkinError").textContent = "";
    progress();
    startedAt = Date.now();
    const dialog = byId("checkinDialog");
    if (typeof dialog.showModal === "function") { if (!dialog.open) dialog.showModal(); }
    else dialog.setAttribute("open", "");
    dialog.querySelector("input")?.focus();
  }

  function close() {
    const dialog = byId("checkinDialog");
    if (typeof dialog.close === "function" && dialog.open) dialog.close();
    else dialog.removeAttribute("open");
  }

  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    const form = byId("checkinForm");
    const value = name => form.querySelector(`input[name="${name}"]:checked`)?.value;
    const bsrs5 = Object.fromEntries(ITEMS.map(([key]) => [key, Number(value(key))]));
    busy = true;
    progress();
    byId("checkinError").textContent = "";
    try {
      const res = await fetch("/api/assessment", {
        method: "POST",
        headers: {"Content-Type": "application/json", "X-CSRF-Token": window.ANLA_CSRF_TOKEN},
        body: JSON.stringify({
          bsrs5,
          duration: value("duration"), life_impact: value("life_impact"),
          // The stress source becomes the note's topic (「最近因為課業或考試的事情有些困擾」).
          category: value("category") === "說不上來" ? "最近的心情和生活" : value("category"),
          support_system: value("support_system"),
          dialogue_snippet: byId("checkinNote").value.trim(),
          elapsed_seconds: Math.round((Date.now() - startedAt) / 1000),
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "暫時無法送出，請稍後再試。");
      showResult(data);
      window.AnlaNextSteps?.update(data);
    } catch (error) {
      byId("checkinError").textContent = error.message || "暫時無法送出，請稍後再試；需要時可以直接撥 1925。";
    } finally {
      busy = false;
      progress();
    }
  }

  function showResult(data) {
    byId("checkinForm").hidden = true;
    const box = byId("checkinResult");
    box.hidden = false;
    byId("checkinResultText").textContent = data.result?.text || data.message;
    byId("checkinAlert").hidden = !data.safety_alert;
    byId("checkinAlert").textContent = data.safety_alert || "";
    const draft = byId("checkinDraft");
    draft.hidden = !data.help_draft || data.show_urgent_help;
    byId("checkinDraftText").value = data.help_draft || "";
    byId("checkinDone").dataset.askSafety = data.result?.ask_safety ? "true" : "";
    byId("checkinDone").focus();
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-open-checkin]").forEach(el => el.addEventListener("click", open));
    byId("checkinClose")?.addEventListener("click", close);
    byId("checkinDone")?.addEventListener("click", event => {
      close();
      if (event.currentTarget.dataset.askSafety) {
        const input = byId("userInput");
        input.placeholder = "現在安全嗎？想說什麼都可以在這裡打…";
        input.focus();
      }
    });
    byId("checkinCopyDraft")?.addEventListener("click", async () => {
      const area = byId("checkinDraftText");
      try { await navigator.clipboard.writeText(area.value); byId("checkinCopyDraft").textContent = "已複製"; }
      catch (_) { area.focus(); area.select(); }
    });
  });
  window.AnlaCheckin = {open};
})();
