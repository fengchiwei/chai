// v1.3-B：虛構對話重播。所有內容以 textContent 等級轉義後才放進頁面。
const LEVEL_LABELS = {green: "綠色 ‧ 一般支持", yellow: "黃色 ‧ 建議求助", orange: "橙色 ‧ 優先覆核", red: "紅色 ‧ 立即危機"};
const TIER_LABELS = {red: "紅色規則", orange: "橙色規則", yellow: "黃色規則"};
const SIGNAL_LABELS = {none: "無", ambiguous: "模糊", indirect: "間接", direct: "直接"};
const SUBJECT_LABELS = {self: "本人", other: "他人", unknown: "未確定"};
const RISK_TYPE_LABELS = {suicide: "自殺意念", self_harm: "自傷", abuse: "受虐／家暴", violence: "暴力", digital_sexual_violence: "數位性暴力", other: "其他"};

function E(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, ch => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"})[ch]);
}
function badge(level) {
  return `<span class="badge-level badge-${E(level)}">${E(LEVEL_LABELS[level] || level)}</span>`;
}

window.addEventListener("DOMContentLoaded", async () => {
  const list = document.getElementById("scenarioList");
  list.addEventListener("click", ev => {
    const button = ev.target.closest("button[data-id]");
    if (button) showScenario(button.dataset.id);
  });
  try {
    const res = await fetch("/api/explain/scenarios", {cache: "no-store"});
    if (!res.ok) throw new Error("請先登入授權工作臺");
    const data = await res.json();
    list.innerHTML = data.scenarios.map(s => `
      <button type="button" class="explain-item" data-id="${E(s.id)}" role="listitem">
        <span class="explain-item-id">${E(s.id)} ‧ ${s.turn_count} 輪</span>
        <span class="explain-item-title">${E(s.title)}</span>
      </button>`).join("") || "<p>沒有虛構情境</p>";
    if (data.scenarios.length) showScenario(data.scenarios[0].id);
  } catch (error) {
    list.innerHTML = `<p class="explain-error">${E(error.message)}</p>`;
  }
});

async function showScenario(id) {
  document.querySelectorAll(".explain-item").forEach(el => el.classList.toggle("active", el.dataset.id === id));
  const main = document.getElementById("explainMain");
  try {
    const res = await fetch(`/api/explain/${encodeURIComponent(id)}`, {cache: "no-store"});
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "重播失敗");
    main.innerHTML = renderSummary(data) + renderDomains(data) + renderTimeline(data);
  } catch (error) {
    main.innerHTML = `<div class="panel-card explain-error">${E(error.message)}</div>`;
  }
}

function renderSummary(d) {
  const expected = d.expected_highest
    ? `<span class="${d.matches_expected ? "explain-ok" : "explain-bad"}">${d.matches_expected ? "符合預期" : "與預期不符：預期 " + E(d.expected_highest)}</span>` : "";
  return `<section class="panel-card">
    <div class="explain-head">
      <div><span class="explain-item-id">${E(d.id)} ‧ 虛構案例</span><h2>${E(d.title)}</h2><p>${E(d.purpose)}</p></div>
      <div class="explain-highest"><span>歷史最高燈號</span>${badge(d.highest_level)}${expected}</div>
    </div>
    <div class="explain-action">
      <div><strong>系統行動</strong><p>${E(d.action.system_action)}</p></div>
      <div><strong>真人角色</strong><p>${E(d.action.human_role)}</p></div>
    </div>
    <p class="explain-meta">${E(d.notice)}｜${E(d.version)}／${E(d.wellbeing_version)}</p>
  </section>`;
}

function renderDomains(d) {
  const cards = d.domains.map(x => `
    <div class="explain-domain ${x.known ? "known" : "unknown"}">
      <div class="explain-domain-head"><strong>${E(x.label)}</strong><span>${E(x.status_label)}</span></div>
      ${x.known && x.evidence ? `<blockquote>「${E(x.evidence)}」</blockquote>
        <span class="explain-meta">第 ${x.turn} 輪原話 ‧ ${x.evidence_verified ? "已核對為逐字片段" : "⚠ 無法對回原話"}</span>`
        : x.known ? `<span class="explain-meta">沿用既有安全狀態，無本輪原話</span>`
        : `<span class="explain-meta">對話中沒有資料；不推測為正常或不存在</span>`}
    </div>`).join("");
  return `<section class="panel-card">
    <h3>六類身心線索 <span class="explain-meta">已知 ${d.known_count} ／ 6，未知 ${6 - d.known_count}</span></h3>
    <div class="explain-domains">${cards}</div>
  </section>`;
}

function renderTimeline(d) {
  const rows = d.turns.map(t => {
    const rules = t.rule_sources.length
      ? t.rule_sources.map(r => `<span class="explain-chip tier-${E(r.tier)}">${E(TIER_LABELS[r.tier])}：${E(r.matched)}</span>`).join("")
      : `<span class="explain-meta">無規則字詞</span>`;
    const s = t.dialogue_safety;
    const safety = s.risk_signal === "none" ? (s.safety_denied ? "學生自述否認（不等於已確認安全）" : "無")
      : `${E(SIGNAL_LABELS[s.risk_signal] || s.risk_signal)}／${E(RISK_TYPE_LABELS[s.risk_type] || s.risk_type)}／對象：${E(SUBJECT_LABELS[s.risk_subject] || s.risk_subject)}`
        + (s.risk_evidence ? `<br><span class="explain-meta">依據：「${E(s.risk_evidence)}」</span>` : "");
    return `<li class="explain-turn">
      <div class="explain-turn-head"><span>第 ${t.turn} 輪</span>${badge(t.level)}
        ${t.highest_level !== t.level ? `<span class="explain-meta">歷史最高：${E(LEVEL_LABELS[t.highest_level])}</span>` : ""}</div>
      <p class="explain-user">學生（虛構）：${E(t.message)}</p>
      <dl>
        <dt>規則來源</dt><dd>${rules}</dd>
        <dt>對話安全核對</dt><dd>${safety}</dd>
        <dt>本輪對話任務</dt><dd>${E(t.goal_label)}</dd>
        <dt>判讀理由</dt><dd>${t.reasons.length ? t.reasons.map(E).join("<br>") : "未偵測到規則警訊；不代表已完成安全評估"}</dd>
      </dl>
      <p class="explain-reply">本機規則回覆：${E(t.reply)}</p>
    </li>`;
  }).join("");
  return `<section class="panel-card">
    <h3>逐輪重播 <span class="explain-meta">${E(d.reply_source)}</span></h3>
    <ol class="explain-timeline">${rows}</ol>
  </section>`;
}
