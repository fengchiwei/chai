// 30 筆模擬資料單獨測試，不建立真實個案或發出通知。
let mockCases = [];
function E(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, ch => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"})[ch]);
}
window.addEventListener("DOMContentLoaded", () => {
  loadMockCases();
  document.getElementById("mockTableBody").addEventListener("click", ev => {
    const button = ev.target.closest("button[data-case-id]");
    if (button) injectTestCase(button.dataset.caseId);
  });
});
async function loadMockCases() {
  try {
    const res = await fetch("/api/mock-cases", {cache:"no-store"});
    if (!res.ok) throw new Error("請先登入示範工作臺");
    mockCases = (await res.json()).mock_cases || [];
    renderMockTable(mockCases);
  } catch (error) { alert(error.message); }
}
function renderMockTable(cases) {
  document.getElementById("mockTableBody").innerHTML = cases.map(c => {
    const bsrs = c.bsrs5 || {};
    const complete = ["sleep", "anxiety", "anger", "depression", "inferiority", "suicide"].every(k => Number.isInteger(bsrs[k]));
    const total = complete ? ["sleep", "anxiety", "anger", "depression", "inferiority"].reduce((a, k) => a + bsrs[k], 0) : null;
    return `<tr><td>${E(c.case_id)}</td><td>${E(c.persona)}（${E(c.township)}）</td>
      <td>${E(c.category)}</td><td>${total == null ? "未施測" : `${total} / 20，附加題 ${bsrs.suicide}`}</td>
      <td>${E(c.risk_label)}</td><td data-result-id="${E(c.case_id)}">待驗證</td>
      <td><button type="button" data-case-id="${E(c.case_id)}">執行此案例</button></td></tr>`;
  }).join("") || '<tr><td colspan="7">沒有案例</td></tr>';
}
function filterMockTable(level) {
  renderMockTable(level === "all" ? mockCases : mockCases.filter(c => c.risk_level === level));
}
async function evaluateCase(id) {
  const res = await fetch(`/api/demo/evaluate/${encodeURIComponent(id)}`, {cache:"no-store"});
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "驗證失敗");
  const resultCell = Array.from(document.querySelectorAll("[data-result-id]"))
    .find(el => el.dataset.resultId === id);
  if (resultCell) resultCell.textContent = data.actual_level === data.expected_level
    ? `相符：${data.actual_level}` : `不符：預期 ${data.expected_level}，得到 ${data.actual_level}`;
  return data;
}
async function runAllVerificationTests() {
  let passed = 0, errors = 0;
  const start = performance.now();
  for (const c of mockCases) {
    try {
      const result = await evaluateCase(c.case_id);
      if (result.actual_level === result.expected_level) passed++;
    } catch (_) { errors++; }
  }
  alert(`模擬情境測試：${passed} / ${mockCases.length} 筆符合預期；連線錯誤 ${errors} 筆。耗時 ${Math.round(performance.now() - start)} 毫秒。\n本測試不代表臨床安全或真實通報能力。`);
}
async function injectTestCase(caseId) {
  const c = mockCases.find(item => item.case_id === caseId);
  if (!c) return;
  try {
    const result = await evaluateCase(caseId);
    document.getElementById("demoDetailContent").innerHTML = `
      <h2>模擬情境 ${E(c.case_id)}</h2>
      <p>預期：${E(c.risk_level)}　引擎輸出：${E(result.actual_level)}</p>
      <p>判讀理由（供覆核）：${E(result.explainability)}</p>
      <p>文字節錄：${E(c.dialogue_snippet)}</p>
      <p>沒有建立正式個案，也沒有聯繫任何人。</p>`;
    document.getElementById("demoDetailModal").style.display = "flex";
  } catch (error) { alert(error.message); }
}
function closeDemoModal() {
  document.getElementById("demoDetailModal").style.display = "none";
}
