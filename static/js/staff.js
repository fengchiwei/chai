// 工作臺：去識別化統計（所有人）、修改自己的密碼、帳號管理與操作紀錄（管理員）。
(() => {
  const $ = id => document.getElementById(id);
  const E = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"})[c]);
  const ROLES = {admin: "管理員", counselor: "輔導人員"};

  async function call(url, body) {
    const res = await fetch(url, body === undefined ? {cache: "no-store"} : {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-CSRF-Token": window.ANLA_CSRF_TOKEN},
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "操作失敗，請稍後再試");
    return data;
  }

  // ---------- 去識別化統計 ----------
  async function loadBreakdown() {
    const host = $("statsPanelBody");
    if (!host) return;
    try {
      const data = await call("/api/stats/breakdown");
      host.innerHTML = data.groups.map(group => `<div class="stats-group"><b>${E(group.title)}</b>${
        group.rows.length ? group.rows.map(([label, count]) => `<div class="stats-row"><span>${E(label)}</span><span>${E(count)}</span></div>`).join("")
          : '<span class="explain-meta">尚無資料</span>'}</div>`).join("");
    } catch (error) { host.textContent = error.message; }
  }

  // ---------- 帳號管理 ----------
  function renderUsers(data) {
    const users = data.users || [];
    const builtin = data.builtin_admin === false ? "" :
      '<tr><td>admin</td><td>內建管理員</td><td>管理員</td><td>使用 WORKBENCH_PASSWORD</td><td></td></tr>';
    $("staffList").innerHTML = `<table class="staff-table"><thead><tr><th>帳號</th><th>名字</th><th>角色</th><th>狀態／最後登入</th><th>操作</th></tr></thead>
      <tbody>${builtin}${users.map(u => `<tr data-user="${E(u.username)}">
        <td>${E(u.username)}</td><td>${E(u.display_name)}</td><td>${E(ROLES[u.role] || u.role)}</td>
        <td>${u.active ? "啟用" : "已停用"}${u.last_login ? "<br>" + E(u.last_login) : ""}</td>
        <td><button type="button" data-act="role" data-role="${u.role === "admin" ? "counselor" : "admin"}">改成${u.role === "admin" ? "輔導人員" : "管理員"}</button>
          <button type="button" data-act="active" data-active="${u.active ? "" : "1"}">${u.active ? "停用" : "啟用"}</button>
          <button type="button" data-act="password">重設密碼</button></td></tr>`).join("")}</tbody></table>`;
  }

  async function loadUsers() {
    if (!$("staffList")) return;
    try { renderUsers(await call("/api/staff/users")); }
    catch (error) { $("staffList").textContent = error.message; }
  }

  async function userAction(event) {
    const button = event.target.closest("button[data-act]");
    if (!button) return;
    const username = button.closest("tr").dataset.user;
    let body;
    if (button.dataset.act === "role") body = {role: button.dataset.role};
    if (button.dataset.act === "active") body = {active: Boolean(button.dataset.active)};
    if (button.dataset.act === "password") {
      const password = prompt(`為 ${username} 設定新密碼（至少 10 字元），請另外告訴本人並請他登入後自己再改：`);
      if (!password) return;
      body = {password};
    }
    try {
      renderUsers(await call(`/api/staff/users/${encodeURIComponent(username)}`, body));
      $("staffMessage").textContent = "已更新。";
      loadAudit();
    } catch (error) { $("staffMessage").textContent = error.message; }
  }

  async function createUser(event) {
    event.preventDefault();
    const form = event.currentTarget;
    if (!form.reportValidity()) return;
    const body = Object.fromEntries(new FormData(form));
    try {
      renderUsers(await call("/api/staff/users", body));
      form.reset();
      $("staffMessage").textContent = `已新增帳號 ${body.username}。請把初始密碼私下交給本人。`;
      loadAudit();
    } catch (error) { $("staffMessage").textContent = error.message; }
  }

  // ---------- 操作紀錄 ----------
  async function loadAudit() {
    const host = $("auditBody");
    if (!host) return;
    try {
      const data = await call("/api/audit");
      host.innerHTML = `<p>${data.chain_ok ? "✅ 紀錄鏈完整，沒有被竄改的跡象" : `⚠ 紀錄鏈在第 ${E(data.first_bad_id)} 筆之後不一致，請通知管理員`}</p>
        <table class="audit-table"><thead><tr><th>時間</th><th>誰</th><th>動作</th><th>個案</th><th>說明</th></tr></thead><tbody>${
        data.logs.map(l => `<tr><td>${E(l.timestamp)}</td><td>${E(l.actor)}</td><td>${E(l.action)}</td><td>${E(l.case_id)}</td><td>${E(l.details)}</td></tr>`).join("")}</tbody></table>`;
    } catch (error) { host.textContent = error.message; }
  }

  // ---------- 修改自己的密碼 ----------
  function passwordDialog(open) {
    const dialog = $("passwordDialog");
    if (!dialog) return;
    if (open) {
      $("passwordMessage").textContent = "";
      if (typeof dialog.showModal === "function") dialog.showModal(); else dialog.setAttribute("open", "");
    } else if (typeof dialog.close === "function") dialog.close();
    else dialog.removeAttribute("open");
  }

  async function changePassword(event) {
    event.preventDefault();
    const form = event.currentTarget;
    if (!form.reportValidity()) return;
    try {
      await call("/api/staff/me/password", Object.fromEntries(new FormData(form)));
      form.reset();
      $("passwordMessage").textContent = "密碼已更新。";
    } catch (error) { $("passwordMessage").textContent = error.message; }
  }

  window.addEventListener("DOMContentLoaded", () => {
    loadBreakdown();
    loadUsers();
    loadAudit();
    $("staffList")?.addEventListener("click", userAction);
    $("staffCreateForm")?.addEventListener("submit", createUser);
    $("reloadAudit")?.addEventListener("click", loadAudit);
    $("myPasswordButton")?.addEventListener("click", () => passwordDialog(true));
    document.querySelector("[data-close-password]")?.addEventListener("click", () => passwordDialog(false));
    $("passwordForm")?.addEventListener("submit", changePassword);
  });
})();
