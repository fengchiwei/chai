(function () {
  "use strict";

  var PRESETS = [
    { id: "chatgpt", name: "ChatGPT", url: "https://chatgpt.com/", color: "#b85c38" },
    { id: "claude", name: "Claude", url: "https://claude.ai/new", color: "#c47b4a" },
    { id: "gemini", name: "Gemini", url: "https://gemini.google.com/app", color: "#3f6f8c" },
    { id: "copilot", name: "Copilot", url: "https://copilot.microsoft.com/", color: "#6d5b8c" },
    { id: "grok", name: "Grok", url: "https://grok.com/", color: "#2f6b4f" }
  ];

  var KEY = "ai_reading_board_v1";
  var windows = new Map();
  var state = load();

  var topicEl = document.getElementById("topic");
  var draftEl = document.getElementById("draft");
  var rosterEl = document.getElementById("roster");
  var boardEl = document.getElementById("board");
  var filtersEl = document.getElementById("filters");
  var currentEl = document.getElementById("currentName");
  var statusEl = document.getElementById("status");

  topicEl.value = state.topic;
  document.getElementById("autoNext").checked = state.autoNext;

  topicEl.addEventListener("input", function () {
    state.topic = topicEl.value;
    save();
  });
  document.getElementById("autoNext").addEventListener("change", function (event) {
    state.autoNext = event.target.checked;
    save();
  });
  document.getElementById("copyTopic").addEventListener("click", copyTopic);
  document.getElementById("openCurrent").addEventListener("click", function () {
    var person = current();
    if (person) openWindow(person);
  });
  document.getElementById("skip").addEventListener("click", function () { advance(); render(); });
  document.getElementById("fromClipboard").addEventListener("click", fromClipboard);
  document.getElementById("fromDraft").addEventListener("click", function () { commit(draftEl.value); });
  document.getElementById("clearBoard").addEventListener("click", clearBoard);
  document.getElementById("addForm").addEventListener("submit", addCustom);
  document.getElementById("taskForm").addEventListener("submit", addTask);
  document.getElementById("downloadTasks").addEventListener("click", downloadTasks);
  draftEl.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) commit(draftEl.value);
  });

  render();

  function load() {
    var saved = null;
    try { saved = JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) { saved = null; }
    var people = PRESETS.map(function (item) {
      return { id: item.id, name: item.name, url: item.url, color: item.color, enabled: true, custom: false };
    });
    if (!saved || !Array.isArray(saved.people)) {
      return { people: people, entries: [], topic: "", cursor: 0, filter: "all", autoNext: true, tasks: [] };
    }
    var known = {};
    people.forEach(function (person) { known[person.id] = person; });
    saved.people.forEach(function (person) {
      if (!person || !person.id || !person.name || !safeUrl(person.url)) return;
      if (known[person.id]) {
        known[person.id].enabled = person.enabled !== false;
      } else {
        people.push({
          id: person.id,
          name: String(person.name).slice(0, 40),
          url: safeUrl(person.url),
          color: person.color || "#6f6258",
          enabled: person.enabled !== false,
          custom: true
        });
      }
    });
    return {
      people: people,
      entries: Array.isArray(saved.entries) ? saved.entries.filter(validEntry) : [],
      topic: typeof saved.topic === "string" ? saved.topic : "",
      cursor: Number.isInteger(saved.cursor) ? saved.cursor : 0,
      filter: typeof saved.filter === "string" ? saved.filter : "all",
      autoNext: saved.autoNext !== false,
      tasks: Array.isArray(saved.tasks) ? saved.tasks.filter(validTask) : []
    };
  }

  function save() {
    var copy = {
      people: state.people.map(function (person) {
        return { id: person.id, name: person.name, url: person.url, color: person.color, enabled: person.enabled, custom: person.custom };
      }),
      entries: state.entries,
      topic: state.topic,
      cursor: state.cursor,
      filter: state.filter,
      autoNext: state.autoNext,
      tasks: state.tasks
    };
    try { localStorage.setItem(KEY, JSON.stringify(copy)); } catch (e) { /* 私密模式不記憶 */ }
  }

  function safeUrl(value) {
    try {
      var url = new URL(value);
      if (url.protocol !== "https:" && url.protocol !== "http:") return "";
      return url.href;
    } catch (e) {
      return "";
    }
  }

  function validEntry(entry) {
    return entry && typeof entry.text === "string" && entry.text.trim() && entry.name;
  }

  function validTask(task) {
    return task && typeof task.title === "string" && task.title.trim() && task.ownerId && task.status;
  }

  function enabledPeople() {
    return state.people.filter(function (person) { return person.enabled; });
  }

  function current() {
    var list = enabledPeople();
    if (!list.length) return null;
    state.cursor = ((state.cursor % list.length) + list.length) % list.length;
    return list[state.cursor];
  }

  function advance() {
    var list = enabledPeople();
    if (!list.length) return;
    state.cursor = (state.cursor + 1) % list.length;
    save();
  }

  function openWindow(person) {
    var existing = windows.get(person.id);
    if (existing && !existing.closed) {
      existing.focus();
      say(person.name + " 的小視窗已在，已把它帶到前面。");
      return;
    }
    var index = state.people.findIndex(function (item) { return item.id === person.id; });
    var left = 32 + (index % 4) * 36;
    var top = 24 + (index % 3) * 28;
    var win = window.open(
      person.url,
      "ai-board-" + person.id,
      "popup=yes,width=480,height=860,left=" + left + ",top=" + top
    );
    if (!win) {
      say("瀏覽器擋住了小視窗。請允許彈出視窗後再按一次。");
      return;
    }
    windows.set(person.id, win);
    say("已打開 " + person.name + "。登入會留在這扇小視窗。");
    renderRoster();
  }

  function commit(text) {
    var body = String(text || "").trim();
    var person = current();
    if (!person) {
      say("請先在發言順序裡勾選至少一位。");
      return;
    }
    if (!body) {
      say("沒有可放入的文字。");
      return;
    }
    state.entries.push({
      id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
      aiId: person.id,
      name: person.name,
      color: person.color,
      text: body,
      at: new Date().toISOString()
    });
    draftEl.value = "";
    if (state.autoNext) advance();
    else save();
    render();
    say("已放入 " + person.name + " 的發言。");
  }

  function fromClipboard() {
    if (!navigator.clipboard || !navigator.clipboard.readText) {
      say("這個瀏覽器不開放剪貼簿。請貼到下方格子，再按「放入上面的文字」。");
      draftEl.focus();
      return;
    }
    navigator.clipboard.readText().then(function (text) {
      if (!text || !text.trim()) {
        say("剪貼簿是空的。請先在小視窗複製回覆。");
        return;
      }
      commit(text);
    }).catch(function () {
      say("讀不到剪貼簿。請貼到下方格子，再按「放入上面的文字」。");
      draftEl.focus();
    });
  }

  function copyTopic() {
    var text = topicEl.value.trim();
    if (!text) {
      say("題目還是空的。");
      return;
    }
    if (!navigator.clipboard || !navigator.clipboard.writeText) {
      topicEl.select();
      say("請用複製鍵複製題目。");
      return;
    }
    navigator.clipboard.writeText(text).then(function () {
      say("題目已複製，可貼進小視窗。");
    }).catch(function () {
      topicEl.select();
      say("請用複製鍵複製題目。");
    });
  }

  function clearBoard() {
    if (!state.entries.length) return;
    if (!window.confirm("清掉看板上的發言？小視窗的登入不會被清掉。")) return;
    state.entries = [];
    save();
    render();
  }

  function addCustom(event) {
    event.preventDefault();
    var name = document.getElementById("addName").value.trim();
    var url = safeUrl(document.getElementById("addUrl").value.trim());
    if (!name || !url) {
      say("請填名稱，以及以 http 或 https 開頭的網址。");
      return;
    }
    state.people.push({
      id: "custom-" + Date.now().toString(36),
      name: name.slice(0, 40),
      url: url,
      color: "#6f6258",
      enabled: true,
      custom: true
    });
    document.getElementById("addForm").reset();
    save();
    render();
  }

  function personById(id) {
    return state.people.find(function (person) { return person.id === id; }) || null;
  }

  function addTask(event) {
    event.preventDefault();
    var title = document.getElementById("taskTitle").value.trim();
    var owner = personById(document.getElementById("taskOwner").value);
    var next = personById(document.getElementById("taskNext").value);
    if (!title || !owner) {
      say("請寫工作內容，並指定負責的人。");
      return;
    }
    state.tasks.push({
      id: "task-" + Date.now().toString(36),
      title: title.slice(0, 120),
      ownerId: owner.id,
      ownerName: owner.name,
      nextId: next ? next.id : "",
      nextName: next ? next.name : "",
      status: "waiting",
      takenAt: null,
      doneAt: null
    });
    document.getElementById("taskForm").reset();
    save();
    render();
    say("已記下這筆工作，尚未領走。");
  }

  function takeTask(task) {
    if (task.status !== "waiting") return;
    task.status = "taken";
    task.takenAt = new Date().toISOString();
    logWork(task.ownerId, task.ownerName, "領走工作：「" + task.title + "」。");
    save();
    render();
    say(task.ownerName + " 已領走，時間已記在看板上。");
  }

  function finishTask(task) {
    if (task.status !== "taken") return;
    task.status = "done";
    task.doneAt = new Date().toISOString();
    logWork(task.ownerId, task.ownerName, "完成工作：「" + task.title + "」。");
    save();
    render();
    if (task.nextName) {
      say("已記下完成。下一手是「" + task.nextName + "」。自動請下一手開始，以後再討論。");
    } else {
      say("已記下完成。這筆還沒有指定下一手。");
    }
  }

  function undoTask(task) {
    if (task.status === "done") {
      task.status = "taken";
      task.doneAt = null;
    } else if (task.status === "taken") {
      task.status = "waiting";
      task.takenAt = null;
    }
    save();
    render();
    say("已改回上一種狀態，時間一併更正。");
  }

  function logWork(aiId, name, text) {
    var person = personById(aiId);
    state.entries.push({
      id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
      aiId: aiId,
      name: name,
      color: person ? person.color : "#6f6258",
      text: text,
      at: new Date().toISOString(),
      kind: "work"
    });
  }

  function downloadTasks() {
    var blob = new Blob([JSON.stringify({
      note: "工作流程尚未定案。這是會議上的分配紀錄，可再修正。",
      tasks: state.tasks
    }, null, 2)], { type: "application/json" });
    var link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "工作分配紀錄.json";
    link.click();
    setTimeout(function () { URL.revokeObjectURL(link.href); }, 1000);
  }

  function render() {
    renderRoster();
    renderFilters();
    renderBoard();
    renderTasks();
    var person = current();
    currentEl.textContent = person ? person.name : "尚未選擇";
  }

  function renderTasks() {
    var host = document.getElementById("tasks");
    var ownerSelect = document.getElementById("taskOwner");
    var nextSelect = document.getElementById("taskNext");
    fillPersonSelect(ownerSelect, false);
    fillPersonSelect(nextSelect, true);
    host.replaceChildren();
    if (!state.tasks.length) {
      var empty = document.createElement("p");
      empty.className = "empty assign-note";
      empty.textContent = "還沒有分配。會議談完後，把工作、負責人與下一手記在這裡。";
      host.append(empty);
      return;
    }
    var list = document.createElement("div");
    list.className = "task-list";
    state.tasks.forEach(function (task) {
      list.append(taskCard(task));
    });
    host.append(list);
  }

  function fillPersonSelect(select, allowEmpty) {
    var currentValue = select.value;
    select.replaceChildren();
    if (allowEmpty) {
      var none = document.createElement("option");
      none.value = "";
      none.textContent = "尚未指定";
      select.append(none);
    }
    state.people.forEach(function (person) {
      var option = document.createElement("option");
      option.value = person.id;
      option.textContent = person.name;
      select.append(option);
    });
    if (currentValue && personById(currentValue)) select.value = currentValue;
  }

  function taskCard(task) {
    var card = document.createElement("article");
    card.className = "task-card";
    var title = document.createElement("input");
    title.type = "text";
    title.value = task.title;
    title.setAttribute("aria-label", "工作內容");
    title.addEventListener("change", function () {
      var next = title.value.trim();
      if (!next) {
        title.value = task.title;
        return;
      }
      task.title = next.slice(0, 120);
      save();
    });

    var owner = document.createElement("select");
    owner.setAttribute("aria-label", "負責人");
    fillPersonSelect(owner, false);
    owner.value = task.ownerId;
    owner.addEventListener("change", function () {
      var person = personById(owner.value);
      if (!person) return;
      task.ownerId = person.id;
      task.ownerName = person.name;
      save();
      renderTasks();
    });

    var next = document.createElement("select");
    next.setAttribute("aria-label", "下一手");
    fillPersonSelect(next, true);
    next.value = task.nextId || "";
    next.addEventListener("change", function () {
      var person = personById(next.value);
      task.nextId = person ? person.id : "";
      task.nextName = person ? person.name : "";
      save();
    });

    var times = document.createElement("p");
    times.className = "times";
    times.textContent = taskTimes(task);

    var row = document.createElement("div");
    row.className = "row";
    row.append(labeled("負責", owner), labeled("下一手", next));
    if (task.status === "waiting") row.append(actionButton("領走", function () { takeTask(task); }));
    if (task.status === "taken") {
      row.append(actionButton("完成", function () { finishTask(task); }));
      row.append(actionButton("收回領走", function () { undoTask(task); }, true));
    }
    if (task.status === "done") row.append(actionButton("收回完成", function () { undoTask(task); }, true));
    row.append(actionButton("刪除", function () {
      state.tasks = state.tasks.filter(function (item) { return item.id !== task.id; });
      save();
      render();
    }, true));

    card.append(title, times, row);
    return card;
  }

  function labeled(text, control) {
    var label = document.createElement("label");
    label.append(document.createTextNode(text), control);
    return label;
  }

  function actionButton(text, onClick, secondary) {
    var button = document.createElement("button");
    button.type = "button";
    button.textContent = text;
    if (secondary) button.className = "secondary";
    button.addEventListener("click", onClick);
    return button;
  }

  function taskTimes(task) {
    var status = task.status === "done" ? "已完成" : task.status === "taken" ? "進行中" : "尚未領走";
    var taken = task.takenAt ? "領走 " + formatTime(task.takenAt) : "尚未領走";
    var done = task.doneAt ? "完成 " + formatTime(task.doneAt) : "尚未完成";
    var next = task.nextName ? "下一手 " + task.nextName : "下一手尚未指定";
    return status + " · " + taken + " · " + done + " · " + next;
  }

  function renderRoster() {
    rosterEl.replaceChildren();
    var active = current();
    state.people.forEach(function (person, index) {
      var item = document.createElement("li");
      item.className = "person" + (active && active.id === person.id ? " current" : "");

      var toggle = document.createElement("input");
      toggle.type = "checkbox";
      toggle.checked = person.enabled;
      toggle.setAttribute("aria-label", person.name + " 參加輪流");
      toggle.addEventListener("change", function () {
        person.enabled = toggle.checked;
        save();
        render();
      });

      var name = document.createElement("button");
      name.type = "button";
      name.textContent = person.name + (windowOpen(person) ? " · 小視窗開著" : "");
      name.addEventListener("click", function () {
        var list = enabledPeople();
        var at = list.findIndex(function (item) { return item.id === person.id; });
        if (at >= 0) state.cursor = at;
        person.enabled = true;
        save();
        render();
      });

      var open = document.createElement("button");
      open.type = "button";
      open.textContent = "小視窗";
      open.addEventListener("click", function () { openWindow(person); });

      item.append(toggle, name, open);
      if (person.custom) {
        var remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "移除";
        remove.addEventListener("click", function () {
          state.people.splice(index, 1);
          windows.delete(person.id);
          save();
          render();
        });
        item.append(remove);
      }
      rosterEl.append(item);
    });
  }

  function windowOpen(person) {
    var win = windows.get(person.id);
    return !!(win && !win.closed);
  }

  function renderFilters() {
    filtersEl.replaceChildren();
    var options = [{ id: "all", name: "全部" }].concat(state.people.map(function (person) {
      return { id: person.id, name: person.name };
    }));
    options.forEach(function (option) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "secondary";
      button.textContent = option.name;
      button.setAttribute("aria-pressed", state.filter === option.id ? "true" : "false");
      button.addEventListener("click", function () {
        state.filter = option.id;
        save();
        renderBoard();
        renderFilters();
      });
      filtersEl.append(button);
    });
  }

  function renderBoard() {
    var entries = state.entries.filter(function (entry) {
      return state.filter === "all" || entry.aiId === state.filter;
    });
    boardEl.replaceChildren();
    if (!entries.length) {
      var empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "會議紀錄還是空的。與會者在小視窗發言後，把內容放到這裡。";
      boardEl.append(empty);
      return;
    }
    entries.forEach(function (entry) {
      var block = document.createElement("section");
      block.className = "entry";
      var head = document.createElement("header");
      var title = document.createElement("h3");
      var mark = document.createElement("span");
      mark.className = "dot";
      mark.style.background = entry.color || "#b85c38";
      title.append(mark, document.createTextNode(" " + entry.name));
      var time = document.createElement("time");
      time.dateTime = entry.at;
      var turn = state.entries.indexOf(entry) + 1;
      time.textContent = "第 " + turn + " 則 · " + formatTime(entry.at);
      head.append(title, time);
      var body = document.createElement("p");
      body.textContent = entry.text;
      block.append(head, body);
      boardEl.append(block);
    });
  }

  function formatTime(value) {
    var date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    return new Intl.DateTimeFormat("zh-TW", {
      timeZone: "Asia/Taipei",
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23"
    }).format(date);
  }

  function say(text) {
    statusEl.textContent = text;
  }
})();
