// 視覺主題：在 <head> 內同步載入，避免頁面先閃一下預設色再換主題。
// 主題只存在本機瀏覽器（localStorage），讀寫失敗時直接使用預設「溫馨暖陽」。
(function () {
  "use strict";
  var THEMES = {
    warm: { label: "🌸 溫馨暖陽", color: "#FDFBF7" },
    forest: { label: "🌲 南投山林", color: "#F2F6F3" },
    midnight: { label: "🌙 靜謐星空", color: "#181C24" },
    paper: { label: "📒 極簡手札", color: "#FFFDF8" }
  };
  var KEY = "anla_theme";
  var DEFAULT = "warm";

  function stored() {
    try {
      var value = window.localStorage.getItem(KEY);
      return Object.prototype.hasOwnProperty.call(THEMES, value) ? value : null;
    } catch (e) {
      return null;
    }
  }

  function apply(theme) {
    if (!Object.prototype.hasOwnProperty.call(THEMES, theme)) theme = DEFAULT;
    document.documentElement.setAttribute("data-theme", theme);
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", THEMES[theme].color);
    var select = document.getElementById("themeSelect");
    if (select && select.value !== theme) select.value = theme;
    return theme;
  }

  function set(theme) {
    // 換主題的瞬間暫停各元件的漸變動畫，避免新舊顏色混在一起閃一下。
    var root = document.documentElement;
    root.classList.add("theme-switching");
    theme = apply(theme);
    if (document.body) void document.body.offsetHeight; // 強制先套用新顏色，再恢復動畫
    window.setTimeout(function () { root.classList.remove("theme-switching"); }, 60);
    try { window.localStorage.setItem(KEY, theme); } catch (e) { /* 私密模式等情況：不記憶也沒關係 */ }
    return theme;
  }

  apply(stored() || DEFAULT);

  window.AnlaTheme = {
    themes: THEMES,
    set: set,
    current: function () { return document.documentElement.getAttribute("data-theme") || DEFAULT; }
  };

  document.addEventListener("DOMContentLoaded", function () {
    apply(window.AnlaTheme.current());
    var select = document.getElementById("themeSelect");
    if (!select) return;
    select.value = window.AnlaTheme.current();
    select.addEventListener("change", function () { set(select.value); });
  });
})();
