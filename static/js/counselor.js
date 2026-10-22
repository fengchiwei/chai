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

window.addEventListener("DOMContentLoaded", () => {
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
