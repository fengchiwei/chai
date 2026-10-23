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

async function loadModels(refresh = false, selection = undefined) {
  const body = $("modelPanelBody");
  if (!body) return;
  const posting = refresh || selection !== undefined;
  body.textContent = selection !== undefined ? "套用中…" : refresh ? "重新偵測中…（只讀取模型清單，不耗用 token）" : "讀取中…";
  try {
    const action = selection !== undefined ? { action: "select_model", model: selection } : { action: "refresh" };
    const res = await fetch("/api/config/llm", posting
      ? { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": window.ANLA_CSRF_TOKEN },
          body: JSON.stringify(action) }
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
    body.innerHTML = "目前沒有設定雲端 AI 金鑰，學生端使用本機規則回覆。用 start.bat 啟動時貼上任一家服務的 API 金鑰"
      + "（或設定 <code>LLM_API_KEY</code>）後重新啟動即可。";
    return;
  }
  const r = data.router || { models: [] };
  const rows = r.models.map(m => {
    const error = E(MODEL_ERROR[m.last_error] || m.last_error || "");
    // The provider's own error text (e.g. 「HTTP 400：temperature: ...」) tells the operator what to fix.
    const detail = m.detail ? `<br><small style="color:#b91c1c">服務回覆：${E(m.detail)}</small>` : "";
    const state = (m.state === "paused" ? `暫停中（${error}，約 ${m.paused_for} 秒後恢復）`
      : m.state === "retry" ? `可再試（上次：${error}）`
      : E(MODEL_STATE[m.state] || m.state)) + (m.state === "ok" ? "" : detail);
    return `<tr${m.active ? ' style="background:#ecfdf5;font-weight:600"' : ""}>
      <td>${m.rank}</td><td><code>${E(m.model)}</code>${m.active ? " ✅ 使用中" : ""}${m.pinned ? (r.pinned_source === "manual" ? "（手動指定）" : "（啟動設定指定）") : ""}</td>
      <td>${state}</td><td>${m.latency == null ? "—" : E(m.latency) + " 秒"}</td><td>${m.ok} / ${m.fail}</td></tr>`;
  }).join("");
  const status = data.status || {};
  const paused = r.models.filter(m => m.state === "paused").length;
  const wasOpen = body.querySelector("details")?.open;  // keep the table open across refreshes
  // One summary line stays visible; the full table is folded so the case list stays near the top.
  const choices = r.choices || [];
  const options = [`<option value="">自動選擇（推薦）</option>`]
    .concat(choices.map(m => `<option value="${E(m)}"${m === r.manual ? " selected" : ""}>${E(m)}</option>`)).join("");
  body.innerHTML = `
    <p>目前使用：<b><code>${E(r.active || "（無）")}</code></b>${r.manual ? "（手動指定）" : r.pinned_source === "env" ? "（啟動設定指定）" : "（自動選擇）"}
      　｜　可用 ${r.models.length - paused} 個、暫停 ${paused} 個
      　｜　連線：${E(CONNECTION_STATE[status.state] || status.state || "")}${status.reason ? "（" + E(MODEL_ERROR[status.reason] || status.reason) + "）" : ""}</p>
    ${r.discovery_error ? `<p style="color:#b91c1c">模型清單讀取失敗：${E(r.discovery_error)}（先使用預設模型）</p>` : ""}
    <p style="display:flex;gap:.5rem;align-items:center;flex-wrap:wrap">
      <label for="modelChoice">使用的模型：</label>
      <select id="modelChoice" ${choices.length ? "" : "disabled"} style="padding:.35rem .5rem;border-radius:8px;border:1px solid var(--border-color)">${options}</select>
      <button type="button" id="applyModel" ${choices.length ? "" : "disabled"} style="padding:.35rem .8rem">套用</button>
      <span style="font-size:.82rem;color:#64748b">${choices.length ? "指定的模型會優先使用；它故障時仍會暫時改用下一個，學生不會沒有回覆。改過設定後按「重新偵測可用模型」，暫停中的模型會立刻重試。"
        : "還沒讀到這把金鑰的模型清單，請先按「重新偵測可用模型」。"}</span>
    </p>
    <details${wasOpen ? " open" : ""}><summary style="cursor:pointer">查看全部模型與排名規則</summary>
    <p>服務商：${E(data.provider_label || data.provider)}${data.base_url ? "（" + E(data.base_url) + "）" : ""}　｜　自動選擇：${data.auto_select ? "開啟" : "關閉（使用設定的模型）"}
      　｜　呼叫方式：${E(CALL_MODE[data.call_mode] || data.call_mode)}</p>
    ${r.discovered ? `<p>已讀取金鑰可用的模型清單（${E(r.discovered_ago)} 秒前）；故障時會自動依序改用下一個。</p>`
                   : "<p>尚未讀取模型清單，先使用預設模型；學生頁開啟或按「重新偵測」時會讀取。</p>"}
    <div style="overflow-x:auto"><table class="cases-table">
      <thead><tr><th>排名</th><th>模型</th><th>狀態</th><th>平均回覆</th><th>成功／失敗</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="5">沒有可用的對話模型</td></tr>'}</tbody></table></div>
    <p>排名規則：${E(r.ranking_rule || "")}</p></details>`;
  $("applyModel")?.addEventListener("click", () => loadModels(false, $("modelChoice").value));
}

window.addEventListener("DOMContentLoaded", () => {
  if ($("modelPanel")) loadModels();  // administrators only
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
  const statuses = {pending: "待覆核", student_requested_referral: "學生提出轉介，待覆核", student_shared_summary: "學生分享摘要，待覆核", auto_safety_alert: "系統安全通報，待覆核", student_requested_help: "學生主動請求協助，待覆核", reviewing: "審查中", contacted: "已聯絡", referred: "已轉介", completed: "已結案"};
  $("casesTableBody").innerHTML = cases.map(c => {
    const done = hasCompleteBsrs(c.bsrs5);
    const bsrs = done ? `${bsrsScore(c.bsrs5)} / 20；附加題 ${c.bsrs5.suicide} 分` : "未施測";
    const consent = c.summary?.student_consent;
    const consentLabel = consent?.kind === "referral" ? "學生同意轉介" : consent?.kind === "summary" ? "學生同意分享摘要"
      : consent?.kind === "request" ? "學生主動請求協助"
      : c.summary?.auto_alert ? "未經同意的必要安全資訊" : "";
    const raised = c.summary?.raised_after_consent;
    return `<tr>
      <td>${escapeHtml(c.case_id)}</td><td>${escapeHtml(c.student_alias)}</td>
      <td>${escapeHtml(c.student_email || "未提供／未驗證")}</td><td>${escapeHtml(c.township)}</td>
      <td>${escapeHtml(levels[c.risk_level] || "待覆核")}${raised ? `<br><span style="color:#b91c1c;font-weight:700">⚠ 同意後升至${escapeHtml(LEVEL_NAMES[raised.level] || raised.level)}</span>` : ""}</td><td>${escapeHtml(c.category)}</td>
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
    document.body.classList.add("case-open");  // print rules apply to the open case only
  } catch (error) { alert(error.message); }
}
function closeSummaryModal() {
  $("summaryModal").style.display = "none";
  document.body.classList.remove("case-open");
}
async function printCase() {
  if (!currentActiveCase) return;
  // Printing student records is logged like viewing them; print even if the log call fails, the view is already logged.
  try {
    await fetch(`/api/cases/${encodeURIComponent(currentActiveCase.case_id)}/printed`, {
      method: "POST", headers: {"Content-Type": "application/json", "X-CSRF-Token": window.ANLA_CSRF_TOKEN}, body: "{}"});
  } catch (error) { console.warn(error); }
  const stamp = $("printStamp");
  if (stamp) stamp.textContent = new Date().toLocaleString("zh-TW", {hour12: false});
  window.print();
}
const SOURCE_LABELS = {ai: "AI 回覆", safety: "固定安全文字", rules: "對話規則", local: "本機回覆", unavailable: "AI 無法回覆的說明"};
function renderTranscript(c, E) {
  const transcript = (c.summary || {}).transcript;
  if (!Array.isArray(transcript)) {
    if ((c.summary || {}).auto_alert) return '<p class="explain-meta">學生尚未同意分享完整對話；這裡只有上方引發警訊的原話。</p>';
    return '<p class="explain-meta">這個個案建立於「完整對話紀錄」功能之前，只有上方的原話節錄。</p>';
  }
  if (!transcript.length) return '<p class="explain-meta">沒有對話紀錄。</p>';
  const rows = transcript.map(t => {
    const student = t.role === "user";
    const who = student ? "學生" : `安啦（${SOURCE_LABELS[t.source] || "回覆"}）`;
    return `<div class="transcript-row ${student ? "student" : "assistant"}">
      <span class="transcript-time">${E((t.at || "").slice(11, 16))}</span>
      <span class="transcript-who">${E(who)}</span>
      <span class="transcript-text">${E(t.text || "")}${Array.isArray(t.cards) && t.cards.length
        ? `<br><span class="explain-meta">📚 引用知識卡：${E(t.cards.join("、"))}</span>` : ""}</span></div>`;
  }).join("");
  const first = (transcript[0].at || "").slice(0, 16), last = (transcript[transcript.length - 1].at || "").slice(0, 16);
  return `<p class="explain-meta">共 ${transcript.length} 則，${E(first)} 到 ${E(last)}；只包含學生按下同意之前的對話。</p>
    <div class="transcript">${rows}</div>`;
}

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
      ${(t.theoretical_basis || []).map(code => `<span class="explain-chip theory" title="${E(code)}">${E(THEORY_LABELS[code] || code)}</span>`).join("")}</p>
    <div class="explain-domains">${cards}</div>
  </div>`;
}

const THEORY_LABELS = {"PSY-01": "C-SSRS 嚴重度", "PSY-02": "IPTS 累贅感／歸屬受挫", "PSY-03": "IMV 困頓感",
  "PSY-04": "NSSI 自傷功能", "LIN-01": "言語行為／否定範疇", "SIG-02": "非對稱損失（啟發式）",
  "ENG-03": "多重防護（燈號只升不降）", "DYN-04": "深夜／情緒累積（啟發式）", "SOC-05": "同儕危機守門",
  "HFE-06": "防警報疲勞／判讀說明"};
const LEVEL_NAMES = {red: "紅色", orange: "橙色", yellow: "黃色", green: "綠色"};
function localTime(value) {
  const date = new Date(value);
  return value && !isNaN(date) ? date.toLocaleString("zh-TW", {hour12: false}) : (value || "");
}

function renderOnePageSummary(c) {
  const sum = c.summary || {};
  const rule = c.triage?.rule_details || {};
  const done = hasCompleteBsrs(c.bsrs5);
  const E = escapeHtml;
  const statusLabels = {pending: "待覆核", student_requested_referral: "學生提出轉介，待覆核", student_shared_summary: "學生分享摘要，待覆核", auto_safety_alert: "系統安全通報，待覆核", student_requested_help: "學生主動請求協助，待覆核", reviewing: "審查中", contacted: "已聯絡", referred: "已轉介", completed: "已結案"};
  const consent = sum.student_consent;
  const fields = done ? ["sleep", "anxiety", "anger", "depression", "inferiority", "suicide"]
    .map((key, i) => `<span>${["睡眠", "緊張", "易怒", "低落", "自我價值", "自殺想法"][i]}：${c.bsrs5[key]}</span>`).join("　") : "未施測（自然對話不等於正式 BSRS-5）";
  const raised = sum.raised_after_consent;
  const staffStatuses = {reviewing: "審查中", contacted: "已聯絡", referred: "已轉介", completed: "已結案"};
  $("summaryModalContent").innerHTML = `
    <div id="printableArea" style="line-height:1.75">
      <div class="print-only print-header" style="border-bottom:2px solid #000;margin-bottom:.6rem;padding-bottom:.3rem">
        <b>安啦會客室｜真人覆核摘要（機密，僅限授權人員閱覽）</b><br>
        列印時間：<span id="printStamp"></span>　本文件含學生輔導資料，請依校內規定保管，用畢銷毀。</div>
      ${raised ? `<p class="risk-raised-banner" style="background:#fee2e2;color:#991b1b;padding:.6rem .8rem;border-radius:8px">
        ⚠ 學生同意分享後，對話燈號在 ${E(raised.at)} 升至<b>${E(LEVEL_NAMES[raised.level] || raised.level)}</b>。新的內容沒有分享給工作臺；
        請依校內流程主動關心，或請學生再次同意分享。</p>` : ""}
      ${sum.auto_alert && !consent ? `<p class="auto-alert-banner" style="background:#fff7ed;color:#9a3412;padding:.6rem .8rem;border-radius:8px">
        🛟 系統安全通報：對話燈號在 ${E(localTime(sum.auto_alert.at))} 達<b>${E(LEVEL_NAMES[sum.auto_alert.level] || sum.auto_alert.level)}</b>，
        依計畫書自動送出必要安全資訊（${E((sum.auto_alert.fields || []).join("、"))}）。學生已在畫面上被告知；
        尚未同意分享暱稱、學校、聯絡方式與完整對話，所以目前無法主動聯絡，請留意學生是否再同意分享。</p>` : ""}
      ${sum.auto_alert && consent ? `<p class="explain-meta">此個案先由系統安全通報建立（${E(localTime(sum.auto_alert.at))}），之後學生同意分享。</p>` : ""}
      <h2>真人覆核摘要：${E(c.case_id)}</h2>
      <p><b>暫定風險：</b>${E((({red:"紅色",orange:"橙色",yellow:"黃色",green:"綠色"})[c.risk_level] || "待確認"))}；
      <b>處理狀態：</b>${E(statusLabels[c.status] || "待覆核")}</p>
      <p><b>暱稱：</b>${E(c.student_alias)}　<b>鄉鎮：</b>${E(c.township)}<br>
      <b>填寫信箱：</b>${E(c.student_email || "未提供")}（未驗證，也未自動通知）</p>
      ${consent?.note ? `<p class="help-note" style="background:#eff6ff;padding:.6rem .8rem;border-radius:8px"><b>學生想先讓老師知道的事：</b>${E(consent.note)}</p>` : ""}
      ${consent ? `<p><b>${consent.kind === "referral" ? "學生同意轉介" : consent.kind === "request" ? "學生主動請求協助" : "學生同意分享摘要"}</b>：${E(localTime(consent.consented_at))}<br>
      <b>學校：</b>${E(sum.student_profile?.student_school || "尚未填寫")}；本次為學生同意的摘要快照，尚未對外轉介。</p>` : ""}
      <h3>對話資訊</h3>
      <p><b>使用者原話節錄：</b><span style="white-space:pre-wrap">${E(c.dialogue_snippet || "無")}</span></p>
      <h3>完整對話紀錄</h3>
      ${renderTranscript(c, E)}
      <p><b>持續時間：</b>${E(c.duration || "尚未確認")}　<b>生活影響：</b>${E(c.life_impact || "尚未確認")}</p>
      <p><b>支持系統：</b>${E(c.support_system || "尚未確認")}</p>
      <p><b>BSRS-5：</b>${done ? E(bsrsScore(c.bsrs5)) + " / 20；" : ""}${fields}${sum.checkin_seconds
        ? `<br><span class="explain-meta">學生自填檢核用時 ${E(Math.floor(sum.checkin_seconds / 60))} 分 ${E(sum.checkin_seconds % 60)} 秒</span>` : ""}</p>
      <p><b>風險訊號：</b>${E((sum.self_harm_signals || []).join("；") || "沒有足夠資料；仍需真人了解")}</p>
      ${renderExplainable(c, E)}
      <p><b>即時安全：</b>${E(sum.current_safety || "尚未確認")}</p>
      <p><b>系統建議：</b>${E(sum.action_recommendation || "由真人覆核")}</p>
      ${(sum.reporting_checklist || []).length ? `<div class="reporting-checklist" style="border:1px solid #fca5a5;border-radius:8px;padding:.6rem .8rem;margin:.5rem 0">
        <b>通報與處理檢核（依類型）</b><ul style="margin:.3rem 0 0 1.1rem">${sum.reporting_checklist.map(item => `<li>${E(item)}</li>`).join("")}</ul></div>` : ""}
      <p style="color:#9a3412">系統判讀可能出錯，僅供受訓人員覆核。任何通報、撥號或轉介都須另行執行；本網站沒有自動聯絡功能。</p>
      <div class="no-print" style="display:flex;gap:.5rem;flex-wrap:wrap">
        <button type="button" onclick="quickApplyDecision('緊急聯繫提議')">擬緊急聯繫</button>
        <button type="button" onclick="quickApplyDecision('聯絡學生／可信任大人提議')">擬聯絡關懷</button>
        <button type="button" onclick="quickApplyDecision('轉介提議')">擬轉介資源</button>
        <a href="tel:119">119</a> <a href="tel:110">110</a> <a href="tel:1925">1925</a>
      </div>
      <div class="print-only">
        <h3>處理紀錄</h3>
        <p><b>處理狀態：</b>${E(statusLabels[c.status] || "待覆核")}　<b>處置摘要：</b>${E(c.decision_action || "無")}</p>
        <pre style="white-space:pre-wrap;font-family:inherit">${E(c.counselor_notes || "尚無紀錄")}</pre>
      </div>
    </div>
    <hr>
    <label>處理狀態：<select id="updateStatusSelect">
      ${Object.entries(staffStatuses).map(([value, label]) => `<option value="${value}" ${c.status === value ? "selected" : ""}>${label}</option>`).join("")}
    </select></label>
    <p><label>處置摘要：<input id="decisionInput" maxlength="200" value="${E(c.decision_action || "")}" style="width:100%"></label></p>
    <p><b>處理紀錄（只能新增，不能修改或刪除）：</b></p>
    <pre style="white-space:pre-wrap;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:.5rem;max-height:10rem;overflow:auto">${E(c.counselor_notes || "尚無紀錄")}</pre>
    <p><label>新增一筆紀錄：<textarea id="updateNotesInput" maxlength="1000" rows="3" style="width:100%" placeholder="例：10/23 14:00 已電話聯絡導師，約明天輔導室晤談"></textarea></label></p>
    <p><label><input type="checkbox" id="contactConfirmed"> 若選「已聯絡／已轉介」，我確認已在本網站以外實際完成，並在備註記錄方式與時間。</label></p>
    <button type="button" class="btn-primary-action" onclick="saveCounselorReview()">儲存真人覆核</button>
    <button type="button" onclick="printCase()">列印摘要</button>
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
