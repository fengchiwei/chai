// PWA 與手機適配：Service Worker 註冊、離線提示條、手機掃碼安裝說明、可視高度（鍵盤彈出時）。
(() => {
  "use strict";
  const byId = id => document.getElementById(id);

  // ---------- Service Worker（離線安心逃生艙） ----------
  // 瀏覽器只允許在 HTTPS 或 localhost 註冊；區網 http 連線時會略過，頁面其他功能不受影響。
  if ("serviceWorker" in navigator && window.isSecureContext) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {});
    });
  }

  // ---------- 離線提示 ----------
  function updateOnline() {
    const banner = byId("offlineBanner");
    if (!banner) return;
    banner.hidden = navigator.onLine !== false;
  }
  window.addEventListener("online", updateOnline);
  window.addEventListener("offline", updateOnline);

  // ---------- 手機可視高度（虛擬鍵盤彈出時跟著縮） ----------
  function updateViewportHeight() {
    const vv = window.visualViewport;
    const height = vv ? vv.height : window.innerHeight;
    if (height) document.documentElement.style.setProperty("--anla-vh", `${Math.round(height)}px`);
  }
  if (window.visualViewport) window.visualViewport.addEventListener("resize", updateViewportHeight);
  window.addEventListener("resize", updateViewportHeight);

  // ---------- 安裝到主畫面 ----------
  let deferredPrompt = null;
  let lastOpener = null;
  window.addEventListener("beforeinstallprompt", event => {
    event.preventDefault();
    deferredPrompt = event;
    const button = byId("installNowButton");
    if (button) button.hidden = false;
  });
  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    const button = byId("installNowButton");
    if (button) button.hidden = true;
  });

  function openInstallDialog(event) {
    const dialog = byId("installDialog");
    if (!dialog) return;
    lastOpener = event?.currentTarget || document.activeElement;
    const img = byId("installQr");
    if (img && !img.getAttribute("src")) {
      img.addEventListener("error", () => {
        img.hidden = true;
        byId("installQrFallback").hidden = false;
      }, { once: true });
      img.src = "/api/qr.svg";
    }
    const url = byId("installUrl");
    if (url) url.textContent = window.location.origin + "/";
    if (typeof dialog.showModal === "function") {
      if (!dialog.open) dialog.showModal();
    } else {
      dialog.setAttribute("open", "");
    }
    byId("installClose")?.focus();
  }

  function closeInstallDialog() {
    const dialog = byId("installDialog");
    if (!dialog) return;
    if (typeof dialog.close === "function" && dialog.open) dialog.close();
    else dialog.removeAttribute("open");
  }

  document.addEventListener("DOMContentLoaded", () => {
    updateOnline();
    updateViewportHeight();
    byId("installButton")?.addEventListener("click", openInstallDialog);
    byId("installClose")?.addEventListener("click", closeInstallDialog);
    const dialog = byId("installDialog");
    if (dialog) {
      dialog.addEventListener("close", () => {
        if (lastOpener && document.contains(lastOpener)) lastOpener.focus();
        lastOpener = null;
      });
      // 點對話框外的暗色區域也可關閉。
      dialog.addEventListener("click", event => { if (event.target === dialog) closeInstallDialog(); });
    }
    byId("installNowButton")?.addEventListener("click", async () => {
      if (!deferredPrompt) return;
      deferredPrompt.prompt();
      try { await deferredPrompt.userChoice; } catch (_) {}
      deferredPrompt = null;
      byId("installNowButton").hidden = true;
    });
    const standalone = window.matchMedia?.("(display-mode: standalone)").matches || window.navigator.standalone === true;
    if (standalone) document.documentElement.classList.add("is-standalone");
  });
})();
