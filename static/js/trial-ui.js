/* 試作單的前端行為：首頁入口、本機氣氛、三種示範狀態。不呼叫對話 API。 */
(function () {
  "use strict";

  var ROOM_KEY = "anla_room";
  var TOY_KEY = "anla_toy";

  function applyRoom(value) {
    var card = document.querySelector(".chat-card");
    if (!card) return;
    ["room-parlor", "room-window", "room-tree", "room-lamp"].forEach(function (name) {
      card.classList.remove(name);
    });
    if (value) card.classList.add(value);
  }

  function applyToy(value) {
    var badge = document.getElementById("toyBadge");
    if (!badge) return;
    badge.textContent = value || "";
    badge.hidden = !value;
  }

  function remember(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { /* 私密模式不記憶 */ }
  }

  function stored(key) {
    try { return localStorage.getItem(key) || ""; } catch (e) { return ""; }
  }

  function enterChat() {
    document.body.classList.remove("show-home");
  }

  function clearDemo() {
    document.querySelectorAll(".demo-state-bubble").forEach(function (node) { node.remove(); });
  }

  function showDemo(kind) {
    clearDemo();
    var text = "";
    if (kind === "waiting") {
      if (typeof showTypingIndicator === "function") {
        var id = showTypingIndicator();
        var node = document.getElementById(id);
        if (node) node.classList.add("demo-state-bubble");
      }
      return;
    }
    if (kind === "disconnected") {
      text = "訊息送出時發生問題：連線中斷。剛才打的字已放回輸入框，可以再按一次送出；若現在有立即危險，請直接撥打 119 或找身邊的大人。";
    } else if (kind === "unavailable") {
      text = "（這個網站目前沒有接上 AI）抱歉，我現在沒辦法好好回覆你，請稍後再傳一次。如果現在有立即危險，請撥 119；想找人談可以打 1925，二十四小時都有人接。";
    } else {
      return;
    }
    if (typeof appendMessage === "function") {
      var bubble = appendMessage("ai", text);
      var message = bubble && bubble.closest(".message");
      if (message) message.classList.add("demo-state-bubble");
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    var start = document.getElementById("startChatButton");
    if (start) {
      start.addEventListener("click", function () {
        enterChat();
        if (typeof checkOnboardingStatus === "function") checkOnboardingStatus();
        var input = document.getElementById("userInput");
        if (input) input.focus();
      });
    }

    var room = document.getElementById("roomSelect");
    var toy = document.getElementById("toySelect");
    if (room) {
      var savedRoom = stored(ROOM_KEY) || "room-parlor";
      if ([].some.call(room.options, function (option) { return option.value === savedRoom; })) {
        room.value = savedRoom;
      }
      applyRoom(room.value);
      room.addEventListener("change", function () {
        applyRoom(room.value);
        remember(ROOM_KEY, room.value);
      });
    }
    if (toy) {
      var savedToy = stored(TOY_KEY);
      if ([].some.call(toy.options, function (option) { return option.value === savedToy; })) {
        toy.value = savedToy;
      }
      applyToy(toy.value);
      toy.addEventListener("change", function () {
        applyToy(toy.value);
        remember(TOY_KEY, toy.value);
      });
    }

    document.querySelectorAll("[data-demo-state]").forEach(function (button) {
      button.addEventListener("click", function () {
        showDemo(button.getAttribute("data-demo-state"));
      });
    });

    var params = new URLSearchParams(location.search);
    var demo = params.get("demo");
    if (demo === "waiting" || demo === "disconnected" || demo === "unavailable" || params.get("advanced") === "open") {
      enterChat();
    }
    if (params.get("advanced") === "open") {
      var panel = document.getElementById("advancedSettings");
      if (panel) panel.open = true;
    }
    if (demo === "waiting" || demo === "disconnected" || demo === "unavailable") {
      showDemo(demo);
      var shown = document.querySelector(".demo-state-bubble");
      if (shown) shown.scrollIntoView({block: "center"});
    }
  });
})();
