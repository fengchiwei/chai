// 授權人員工作臺：所有資料顯示前先跳脫，處置紀錄由真人確認。
let allCasesCache = [];
let currentActiveCase = null;

const $ = id => document.getElementById(id);
function escapeHtml(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[c]);
}
function hasCompleteBsrs(bsrs) {
  return bsrs && ["sleep", "anxiety", "anger", "depression", "inferiority", "suicide"]
    .every(key => Number.isInteger(bsrs[key]) && bsrs[key] >= 0 && bsrs[key] <= 4);
}
function bsrsScore(bsrs) {
  return ["sleep", "anxiety", "anger", "depression", "inferiority"]
    .reduce((sum, key) => sum + bsrs[key], 0);
}

// ---------- AI 模型面板（僅後台）：金鑰可用的模型、排名、健康狀態與目前使用中的模型 ----------
const MODEL_STATE = { ok: "可用", untested: "尚未使用", paused: "暫停中" };
const MODEL_ERROR = {
  rate_limited: "額度或流量用完", model_not_found: "模型不存在或已停用", rejected: "不接受這個請求",
  unavailable: "服務過載", timeout: "回應逾時", empty: "沒有回應內容", bad_response: "回應格式錯誤",
  auth_error: "金鑰無效或沒有權限", api_error: "網路連線失敗", cooldown: "所有模型都暫停中",
};
const CONNECTION_STATE = { ok: "正常", degraded: "暫時無法使用", unknown: "尚未測試（學生傳訊或開頁後更新）", not_configured: "未設定" };
const CALL_MODE = { single: "一次呼叫（分析＋回覆）", two_stage: "兩段呼叫（先分析再回覆）" };

async function loadModels(refresh = false) {
  const body = $("modelPanelBody");
  if (!body) return;
  body.textContent = refresh ? "重新偵測中…（只讀取模型清單，不耗用 token）" : "讀取中…";
  try {
    const res = await fetch("/api/config/llm", refresh
      ? { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": window.ANLA_CSRF_TOKEN },
          body: JSON.stringify({ action: "refresh" }) }
      : { cache: "no-store" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "讀取失敗");
    renderModels(data);
  } catch (error) {
    body.textContent = `模型資訊讀取失敗：${error.message}`;
  }
}

function renderModels(data) {
  const E = escapeHtml;
  const body = $("modelPanelBody");
  if (!data.configured) {
    body.innerHTML = "目前沒有設定雲端 AI 金鑰，學生端使用本機規則回覆。設定 <code>GEMINI_API_KEY</code> 或 <code>OPENAI_API_KEY</code> 後重新啟動即可。";
    return;
  }
  const r = data.router || { models: [] };
  const rows = r.models.map(m => {
    const error = E(MODEL_ERROR[m.last_error] || m.last_error || "");
    const state = m.state === "paused" ? `暫停中（${error}，約 ${m.paused_for} 秒後恢復）`
      : m.state === "retry" ? `可再試（上次：${error}）`
      : E(MODEL_STATE[m.state] || m.state);
    return `<tr${m.active ? ' style="background:#ecfdf5;font-weight:600"' : ""}>
      <td>${m.rank}</td><td><code>${E(m.model)}</code>${m.active ? " ✅ 使用中" : ""}${m.pinned ? "（管理者指定）" : ""}</td>
      <td>${state}</td><td>${m.latency == null ? "—" : E(m.latency) + " 秒"}</td><td>${m.ok} / ${m.fail}</td></tr>`;
  }).join("");
  const status = data.status || {};
  const paused = r.models.filter(m => m.state === "paused").length;
  const wasOpen = body.querySelector("details")?.open;  // keep the table open across refreshes
  // One summary line stays visible; the full table is folded so the case list stays near the top.
  body.innerHTML = `
    <p>目前使用：<b><code>${E(r.active || "（無）")}</code></b>　｜　可用 ${r.models.length - paused} 個、暫停 ${paused} 個
      　｜　連線：${E(CONNECTION_STATE[status.state] || status.state || "")}${status.reason ? "（" + E(MODEL_ERROR[status.reason] || status.reason) + "）" : ""}</p>
    ${r.discovery_error ? `<p style="color:#b91c1c">模型清單讀取失敗：${E(r.discovery_error)}（先使用預設模型）</p>` : ""}
    <details${wasOpen ? " open" : ""}><summary style="cursor:pointer">查看全部模型與排名規則</summary>
    <p>服務商：${E(data.provider)}　｜　自動選擇：${data.auto_select ? "開啟" : "關閉（使用設定的模型）"}
      　｜　呼叫方式：${E(CALL_MODE[data.call_mode] || data.call_mode)}</p>
    ${r.discovered ? `<p>已讀取金鑰可用的模型清單（${E(r.discovered_ago)} 秒前）；故障時會自動依序改用下一個。</p>`
                   : "<p>尚未讀取模型清單，先使用預設模型；學生頁開啟或按「重新偵測」時會讀取。</p>"}
    <div style="overflow-x:auto"><table class="cases-table">
      <thead><tr><th>排名</th><th>模型</th><th>狀態</th><th>平均回覆</th><th>成功／失敗</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="5">沒有可用的對話模型</td></tr>'}</tbody></table></div>
    <p>排名規則：${E(r.ranking_rule || "")}</p></details>`;
}

window.addEventListener("DOMContentLoaded", () => {
  loadModels();
  $("refreshModels")?.addEventListener("click", () => loadModels(true));
  loadCases();
  $("casesTableBody").addEventListener("click", event => {
    const button = event.target.closest("button[data-case-id]");
    if (button) openSummaryModal(button.dataset.caseId);
  });
});

async function loadStats() {
  try {
    const res = await fetch("/api/stats", {cache: "no-store"});
    if (!res.ok) throw new Error("無法載入統計");
    const data = await res.json();
    for (const [key, id] of [["red", "statRed"], ["orange", "statOrange"], ["yellow", "statYellow"], ["green", "statGreen"]]) {
      $(id).textContent = data[key] ?? "—";
    }
  } catch (error) { console.error(error); }
}
async function loadCases() {
  const query = new URLSearchParams({
    risk: $("filterRisk").value, township: $("filterTownship").value, status: $("filterStatus").value
  });
  try {
    const res = await fetch(`/api/cases?${query}`, {cache: "no-store"});
    if (!res.ok) throw new Error("無法載入個案，請重新登入");
    const data = await res.json();
    allCasesCache = data.cases || [];
    renderCasesTable(allCasesCache);
    loadStats();
  } catch (error) {
    $("casesTableBody").innerHTML = '<tr><td colspan="10">無法讀取工作臺資料，請重新登入。</td></tr>';
  }
}
function renderCasesTable(cases) {
  if (!cases.length) {
    $("casesTableBody").innerHTML = '<tr><td colspan="10" style="text-align:center;padding:2rem">目前沒有符合條件的紀錄。</td></tr>';
    return;
  }
  const levels = {red: "🚨 紅色", orange: "⚠️ 橙色", yellow: "📋 黃色", green: "🌱 綠色"};
  const statuses = {pending: "待覆核", student_requested_referral: "學生提出轉介，待覆核", student_shared_summary: "學生分享摘要，待覆核", reviewing: "審查中", contacted: "已聯絡", referred: "已轉介", completed: "已結案"};
  $("casesTableBody").innerHTML = cases.map(c => {
    const done = hasCompleteBsrs(c.bsrs5);
    const bsrs = done ? `${bsrsScore(c.bsrs5)} / 20；附加題 ${c.bsrs5.suicide} 分` : "未施測";
    const consent = c.summary?.student_consent;
    const consentLabel = consent?.kind === "referral" ? "學生同意轉介" : consent?.kind === "summary" ? "學生同意分享摘要" : "";
    return `<tr>
      <td>${escapeHtml(c.case_id)}</td><td>${escapeHtml(c.student_alias)}</td>
      <td>${escapeHtml(c.student_email || "未提供／未驗證")}</td><td>${escapeHtml(c.township)}</td>
      <td>${escapeHtml(levels[c.risk_level] || "待覆核")}</td><td>${escapeHtml(c.category)}</td>
      <td>${escapeHtml(bsrs)}</td><td>${escapeHtml(statuses[c.status] || "待覆核")}${consentLabel ? `<br><span class="student-consent-label">${escapeHtml(consentLabel)}</span>` : ""}</td>
      <td>${escapeHtml((c.updated_at || "").slice(0, 16))}</td>
      <td><button type="button" class="btn-primary-action" style="padding:.4rem .6rem" data-case-id="${escapeHtml(c.case_id)}">檢視摘要</button></td>
    </tr>`;
  }).join("");
}

async function openSummaryModal(caseId) {
  try {
    const res = await fetch(`/api/cases/${encodeURIComponent(caseId)}`, {cache: "no-store"});
    if (!res.ok) throw new Error("資料讀取失敗");
    currentActiveCase = (await res.json()).case;
    renderOnePageSummary(currentActiveCase);
    $("summaryModal").style.display = "flex";
  } catch (error) { alert(error.message); }
}
function closeSummaryModal() { $("summaryModal").style.display = "none"; }

// v2.3 HFE-06：判讀依據。確認危機（實線）與待消歧（虛線）分開；原話以螢光筆標示，供 3 秒內看懂。
const DOMAIN_LABELS = {duration: "持續時間", sleep: "睡眠", daily_function: "生活／上學功能",
  stress_relationships: "人際與壓力", safety: "安全線索", support_system: "支持系統"};
// Same wording as the 燈號判讀說明 page (engine/explain.py STATUS_LABELS).
const STATUS_LABELS = {time_mentioned: "提到時間", reported_difficulty: "自述困難", reported_ok_or_improving: "自述尚可或改善",
  reported_impact: "自述受影響", reported_maintained: "自述仍能維持", topic_mentioned: "提到相關主題",
  support_mentioned: "提到可求助對象", difficulty_seeking_support: "自述難以求助", requires_human_review: "需真人覆核",
  clarification_needed: "待安全確認", self_reported_denial: "自述否認（不等於已確認安全）"};
function markEvidence(text, spans, E) {
  const marks = new Array(text.length).fill(false);
  spans.filter(Boolean).forEach(span => {
    for (let at = text.indexOf(span); at !== -1; at = text.indexOf(span, at + 1))
      for (let i = at; i < at + span.length; i++) marks[i] = true;
  });
  let html = "", open = false;
  for (let i = 0; i < text.length; i++) {
    if (marks[i] !== open) { html += marks[i] ? "<mark>" : "</mark>"; open = marks[i]; }
    html += E(text[i]);
  }
  return html + (open ? "</mark>" : "");
}
function renderExplainable(c, E) {
  const t = c.triage || {}, rule = t.rule_details || {}, safety = t.dialogue_safety || {};
  const flags = ["red", "orange", "yellow"].flatMap(tier => (rule[tier + "_flags"] || []).map(f => [tier, f]));
  const spans = flags.map(([, f]) => f).concat(rule.hyperbole_flags || [], (safety.risk_evidence || "").split("；"));
  const confirmed = ["orange", "red"].includes(c.risk_level) && !t.pending_disambiguation;
  const domains = (c.summary || {}).wellbeing_signals || {};
  const cards = Object.entries(DOMAIN_LABELS).map(([key, label]) => {
    const d = domains[key] || {status: "unknown"};
    return `<div class="explain-domain ${d.status === "unknown" ? "unknown" : "known"}"><b>${E(label)}</b>：${
      d.status === "unknown" ? "未提及（不代表正常）" : E(STATUS_LABELS[d.status] || d.status)
        + (d.evidence ? `<br>「${E(d.evidence)}」` : "")}</div>`;
  }).join("");
  return `<div class="explain-turn ${confirmed ? "confirmed" : t.pending_disambiguation ? "pending" : ""}" style="margin:.75rem 0">
    <b>判讀依據：系統為什麼亮這個燈</b>
    ${confirmed ? '<span class="explain-tag confirmed">確認危機</span>' : ""}
    ${t.pending_disambiguation ? '<span class="explain-tag pending">待消歧</span>' : ""}
    <p class="explain-user" style="white-space:pre-wrap">${markEvidence(c.dialogue_snippet || "", spans, E) || "無對話節錄"}</p>
    <p>${flags.map(([tier, f]) => `<span class="explain-chip tier-${E(tier)}">${E(f)}</span>`).join("") || "無規則字詞"}
      ${(t.theoretical_basis || []).map(code => `<span class="explain-chip theory">${E(code)}</span>`).join("")}</p>
    <div class="explain-domains">${cards}</div>
  </div>`;
}

function renderOnePageSummary(c) {
  const sum = c.summary || {};
  const rule = c.triage?.rule_details || {};
  const done = hasCompleteBsrs(c.bsrs5);
  const E = escapeHtml;
  const statusLabels = {pending: "待覆核", student_requested_referral: "學生提出轉介，待覆核", student_shared_summary: "學生分享摘要，待覆核", reviewing: "審查中", contacted: "已聯絡", referred: "已轉介", completed: "已結案"};
  const consent = sum.student_consent;
  const fields = done ? ["sleep", "anxiety", "anger", "depression", "inferiority", "suicide"]
    .map((key, i) => `<span>${["睡眠", "緊張", "易怒", "低落", "自我價值", "自殺想法"][i]}：${c.bsrs5[key]}</span>`).join("　") : "未施測（自然對話不等於正式 BSRS-5）";
  $("summaryModalContent").innerHTML = `
    <div id="printableArea" style="line-height:1.75">
      <h2>真人覆核摘要：${E(c.case_id)}</h2>
      <p><b>暫定風險：</b>${E((({red:"紅色",orange:"橙色",yellow:"黃色",green:"綠色"})[c.risk_level] || "待確認"))}；
      <b>處理狀態：</b>${E(statusLabels[c.status] || "待覆核")}</p>
      <p><b>暱稱：</b>${E(c.student_alias)}　<b>鄉鎮：</b>${E(c.township)}<br>
      <b>填寫信箱：</b>${E(c.student_email || "未提供")}（未驗證，也未自動通知）</p>
      ${consent ? `<p><b>${consent.kind === "referral" ? "學生同意轉介" : "學生同意分享摘要"}</b>：${E(consent.consented_at)}<br>
      <b>學校：</b>${E(sum.student_profile?.student_school || "尚未填寫")}；本次為學生同意的摘要快照，尚未對外轉介。</p>` : ""}
      <h3>對話資訊</h3>
      <p><b>使用者原話節錄：</b><span style="white-space:pre-wrap">${E(c.dialogue_snippet || "無")}</span></p>
      <p><b>持續時間：</b>${E(c.duration || "尚未確認")}　<b>生活影響：</b>${E(c.life_impact || "尚未確認")}</p>
      <p><b>支持系統：</b>${E(c.support_system || "尚未確認")}</p>
      <p><b>BSRS-5：</b>${done ? E(bsrsScore(c.bsrs5)) + " / 20；" : ""}${fields}</p>
      <p><b>風險訊號：</b>${E((sum.self_harm_signals || []).join("；") || "沒有足夠資料；仍需真人了解")}</p>
      ${renderExplainable(c, E)}
      <p><b>即時安全：</b>${E(sum.current_safety || "尚未確認")}</p>
      <p><b>系統建議：</b>${E(sum.action_recommendation || "由真人覆核")}</p>
      <p style="color:#9a3412">系統判讀可能出錯，僅供受訓人員覆核。任何通報、撥號或轉介都須另行執行；本網站沒有自動聯絡功能。</p>
      <div style="display:flex;gap:.5rem;flex-wrap:wrap">
        <button type="button" onclick="quickApplyDecision('緊急聯繫提議')">擬緊急聯繫</button>
        <button type="button" onclick="quickApplyDecision('聯絡學生／可信任大人提議')">擬聯絡關懷</button>
        <button type="button" onclick="quickApplyDecision('轉介提議')">擬轉介資源</button>
        <a href="tel:119">119</a> <a href="tel:110">110</a> <a href="tel:1925">1925</a>
      </div>
    </div>
    <hr>
    <label>處理狀態：<select id="updateStatusSelect">
      ${Object.entries(statusLabels).map(([value, label]) => `<option value="${value}" ${c.status === value ? "selected" : ""}>${label}</option>`).join("")}
    </select></label>
    <p><label>處置摘要：<input id="decisionInput" maxlength="200" value="${E(c.decision_action || "")}" style="width:100%"></label></p>
    <p><label>真人備註：<textarea id="updateNotesInput" maxlength="1000" rows="3" style="width:100%">${E(c.counselor_notes || "")}</textarea></label></p>
    <p><label><input type="checkbox" id="contactConfirmed"> 若選「已聯絡／已轉介」，我確認已在本網站以外實際完成，並在備註記錄方式與時間。</label></p>
    <button type="button" class="btn-primary-action" onclick="saveCounselorReview()">儲存真人覆核</button>
    <button type="button" onclick="window.print()">列印</button>
    <button type="button" onclick="closeSummaryModal()">關閉</button>`;
}
function quickApplyDecision(proposal) {
  // 點選只是草擬；絕不將處置標記為已聯絡或已轉介。
  $("decisionInput").value = proposal;
  $("updateStatusSelect").value = "reviewing";
  $("contactConfirmed").checked = false;
}
async function saveCounselorReview() {
  if (!currentActiveCase) return;
  const status = $("updateStatusSelect").value;
  const notes = $("updateNotesInput").value.trim();
  const confirmed = $("contactConfirmed").checked;
  if (["contacted", "referred"].includes(status) && (!confirmed || !notes)) {
    alert("請先在系統外完成聯繫或轉介，勾選確認並記錄處理方式及時間。");
    return;
  }
  try {
    const res = await fetch(`/api/cases/${encodeURIComponent(currentActiveCase.case_id)}/status`, {
      method: "POST",
      headers: {"Content-Type":"application/json", "X-CSRF-Token":window.ANLA_CSRF_TOKEN},
      body: JSON.stringify({status, notes, decision_action: $("decisionInput").value.trim(), contact_confirmed: confirmed})
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "儲存失敗");
    closeSummaryModal();
    await loadCases();
  } catch (error) { alert(error.message); }
}
