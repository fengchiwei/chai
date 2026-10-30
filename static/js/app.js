// 少年仔、安啦會客室 - 前端核心互動腳本
// 特色：可先匿名聊天、聯絡資料選填、融入對話之陪伴邀請、雙向語音對答系統

let conversationHistory = [];
// 登錄資訊只保留於本分頁的工作階段。伺服器還會核對已閱讀資料說明的 session。
let studentEmail = sessionStorage.getItem("anla_student_email") || "";
let studentAlias = sessionStorage.getItem("anla_student_alias") || "匿名同學";
let studentTownship = sessionStorage.getItem("anla_student_township") || "南投市";
let studentSchool = sessionStorage.getItem("anla_student_school") || "";
let isSending = false;
let studentOnboarded = false;

// ==================== AI 回覆風格（記在這台裝置，隨每則訊息送出） ====================
const REPLY_STYLES = ["warm", "lively", "humor", "rational", "listen_only"];
const REPLY_STYLE_KEY = "anla_reply_style";
const SAFETY_STYLE_NOTE = "🛟 目前先以安全為優先，暫時用穩定的語氣陪你。你選的風格會先幫你保留著。";
let replyStyleChosen = false;
let currentReplyStyle = (() => {
  try {
    const saved = localStorage.getItem(REPLY_STYLE_KEY);
    if (REPLY_STYLES.includes(saved)) {
      replyStyleChosen = true;
      return saved;
    }
  } catch (e) { /* 無法讀取本機儲存時使用預設 */ }
  return "warm";
})();

function renderReplyStyle() {
  document.querySelectorAll("#replyStyleBar .style-capsule").forEach(button => {
    button.setAttribute("aria-pressed", String(button.dataset.style === currentReplyStyle));
  });
}

function setReplyStyle(style, remember = true) {
  if (!REPLY_STYLES.includes(style)) return;
  currentReplyStyle = style;
  if (remember) {
    replyStyleChosen = true;
    try { localStorage.setItem(REPLY_STYLE_KEY, style); } catch (e) { /* 不記憶也能使用 */ }
  }
  renderReplyStyle();
}

function applySafetyStyleOverride(overridden) {
  const bar = document.getElementById("replyStyleBar");
  const note = document.getElementById("styleSafetyNote");
  if (bar) {
    bar.classList.toggle("is-overridden", overridden);
    bar.querySelectorAll(".style-capsule").forEach(button => {
      if (overridden) button.setAttribute("aria-describedby", "styleSafetyNote");
      else button.removeAttribute("aria-describedby");
    });
  }
  if (note) {
    note.textContent = overridden ? SAFETY_STYLE_NOTE : "";
    note.hidden = !overridden;
  }
}

function applyReplyStyleResponse(data) {
  if (!data) return;
  // 伺服器回傳的是學生所選風格；只有在本機尚未記憶選擇時才採用，避免覆蓋學生的偏好。
  if (REPLY_STYLES.includes(data.reply_style) && !replyStyleChosen) setReplyStyle(data.reply_style, false);
  if (typeof data.style_overridden_by_safety === "boolean") applySafetyStyleOverride(data.style_overridden_by_safety);
}

document.addEventListener("DOMContentLoaded", () => {
  renderReplyStyle();
  document.querySelectorAll("#replyStyleBar .style-capsule").forEach(button => {
    button.addEventListener("click", () => setReplyStyle(button.dataset.style));
  });
});

function applyCompanionRole(role) {
  const status = document.getElementById("companionRoleStatus");
  if (!status) return;
  status.textContent = role && role.custom
    ? (role.description ? `目前參考的角色：${role.description}` : "目前依你設定的語氣陪伴")
    : "陪伴方式由你描述";
}

function applyStudentProfile(profile) {
  if (!profile) return;
  studentOnboarded = true;
  studentEmail = profile.student_email || "";
  studentAlias = profile.student_alias;
  studentTownship = profile.township;
  studentSchool = profile.student_school || "";
  for (const [key, value] of Object.entries({email: studentEmail, alias: studentAlias, township: studentTownship, school: studentSchool})) {
    sessionStorage.setItem(`anla_student_${key}`, value);
  }
  document.getElementById("onboardingModal").style.display = "none";
}

// 紓壓知識卡：回覆引用的來源（機構與連結），點了用新分頁開啟。
function appendSources(bubble, sources) {
  if (!bubble || !Array.isArray(sources) || !sources.length) return;
  const box = document.createElement("div");
  box.className = "reply-sources";
  box.append("📚 資料來源：");
  sources.forEach((source, i) => {
    if (!/^https:\/\//.test(source.url || "")) return;
    const link = document.createElement("a");
    link.href = source.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = `${source.publisher}〈${source.title}〉`;
    if (i) box.append("、");
    box.appendChild(link);
  });
  bubble.appendChild(box);
}

// ==================== 語音對答系統狀態 (Web Speech API) ====================
let recognition = null;
let isRecording = false;
let isAutoSpeech = localStorage.getItem("anla_auto_speech") === "true"; // 需使用者主動開啟

document.addEventListener("DOMContentLoaded", () => {
  updateTTSButtonUI();
  window.anlaStateReady = fetch("/api/chat/state", {cache: "no-store"}).then(res => res.json()).then(data => {
    if (data.student_profile) applyStudentProfile(data.student_profile);
    else studentOnboarded = false;
    applyCompanionRole(data.companion_role);
    applyReplyStyleResponse(data);
    window.AnlaNextSteps.update(data);
    window.AnlaSchoolReferral.setAvailable(data.school_referral_available);
  }).catch(() => {}).finally(checkOnboardingStatus);
});

// ==================== 資料使用說明與選填聯絡資料 ====================

function checkOnboardingStatus() {
  // 首頁只留名稱、歡迎語與「開始聊聊」。資料說明改到進入對話後再出現。
  if (document.body.classList.contains("show-home")) return;
  var params = new URLSearchParams(location.search);
  // 預覽網址只給畫面截圖，略過資料說明，避免擋住示範狀態。
  if (params.get("demo") || params.get("advanced") === "open") return;
  const badgeAlias = document.getElementById("badgeAlias");
  const badgeEmail = document.getElementById("badgeEmail");

  if (!studentOnboarded) {
    openOnboardingModal(false);
    if (badgeAlias) badgeAlias.innerText = "先用暱稱聊聊";
    if (badgeEmail) badgeEmail.innerText = "請先閱讀資料使用說明";
  } else {
    if (badgeAlias) badgeAlias.innerText = studentAlias;
    if (badgeEmail) {
      badgeEmail.innerText = studentEmail ? "已留聯絡信箱" : "學校／信箱選填";
    }
  }
}

function openOnboardingModal(allowClose) {
  const modal = document.getElementById("onboardingModal");
  if (!modal) return;

  const emailInput = document.getElementById("onboardingEmail");
  const aliasInput = document.getElementById("onboardingAlias");
  const townshipSelect = document.getElementById("onboardingTownship");
  const schoolInput = document.getElementById("onboardingSchool");

  if (emailInput) emailInput.value = studentEmail || sessionStorage.getItem("anla_student_email") || "";
  if (aliasInput && studentAlias) aliasInput.value = studentAlias;
  if (townshipSelect && studentTownship) townshipSelect.value = studentTownship;
  if (schoolInput) schoolInput.value = studentSchool;
  const editing = Boolean(allowClose && studentOnboarded);
  document.getElementById("onboardingClose").hidden = !editing;
  document.getElementById("onboardingContactFields").open = editing;
  document.getElementById("onboardingConsent").checked = studentOnboarded;
  document.getElementById("onboardingSubmit").textContent = editing ? "儲存資料，回到對話" : "先聊聊";

  modal.style.display = "flex";
}

async function submitOnboarding(event) {
  event.preventDefault();

  const emailInput = document.getElementById("onboardingEmail");
  const aliasInput = document.getElementById("onboardingAlias");
  const townshipSelect = document.getElementById("onboardingTownship");

  const email = emailInput.value.trim();
  const acknowledged = document.getElementById("onboardingConsent").checked;
  if ((email && !emailInput.checkValidity()) || !acknowledged) {
    alert("請先閱讀資料使用說明。信箱可以留白；如果填寫，請確認格式正確。");
    return;
  }
  try {
    const res = await fetch("/api/onboarding", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": window.ANLA_CSRF_TOKEN },
      body: JSON.stringify({
        student_email: email,
        student_alias: aliasInput.value.trim() || "匿名同學",
        student_school: document.getElementById("onboardingSchool").value.trim(),
        township: townshipSelect.value,
        privacy_acknowledged: acknowledged
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "登錄失敗");
    applyStudentProfile(data.student_profile);
    window.AnlaNextSteps.update(data);
    checkOnboardingStatus();
  } catch (err) {
    alert(err.message || "登錄失敗，請重新整理頁面後再試。");
  }
}

// ==================== 融入對話內容的身心電力自然盤點 ====================

function startConversationalCheckin() {
  const checkinPrompt = "安啦，我想跟你像知心朋友一樣聊聊這星期的身心電力，最近覺得心裡有點重、身體也滿疲憊的...";
  quickSend(checkinPrompt);
}

// 等待提醒：安啦回覆後 1 分鐘、5 分鐘學生都沒有回應時，在畫面上輕輕提醒。
// 只顯示在這台裝置，不送給 AI、不記進對話紀錄；學生開始打字或送出就取消。安全模式時改提醒求助電話。
const IDLE_REMINDERS = [
  { after: 60 * 1000,
    normal: "慢慢來，不急著回。想到什麼再打就好，一個字也可以。",
    safety: "你還好嗎？不急著回。如果現在有危險，請直接打 119；想找人談可以打 1925，24 小時都有人接。" },
  { after: 5 * 60 * 1000,
    normal: "我還在這裡。先去忙也沒關係，想聊的時候再回來就好。",
    safety: "還沒看到你的回覆，我有點擔心你。如果現在有立即危險，請撥 119 或 110，或請身邊的大人幫忙；想找人談可以打 1925。" },
];
let idleTimers = [];

function clearIdleReminders() {
  idleTimers.forEach(clearTimeout);
  idleTimers = [];
}

function scheduleIdleReminders(safety) {
  clearIdleReminders();
  IDLE_REMINDERS.forEach(reminder => {
    idleTimers.push(setTimeout(() => showIdleReminder(safety ? reminder.safety : reminder.normal), reminder.after));
  });
}

function showIdleReminder(text) {
  const input = document.getElementById("userInput");
  if (input && input.value.trim()) return;  // 學生正在打字
  const chat = document.getElementById("chatMessages");
  const note = document.createElement("div");
  note.className = "idle-reminder";
  note.setAttribute("role", "status");
  note.textContent = "☀️ " + text;
  chat.appendChild(note);
  chat.scrollTop = chat.scrollHeight;
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("userInput")?.addEventListener("input", clearIdleReminders);
});

// 開始新對話：刪除剛才的對話暫存與它的風險狀態，重新整理頁面從頭開始（工作臺既有個案不受影響）。
async function startNewConversation() {
  if (!studentOnboarded) {
    openOnboardingModal(false);
    return;
  }
  const ok = confirm("要開始新對話嗎？\n\n剛才的對話會從這個網站的暫存刪除，安啦也不會再記得。已經送到真人工作臺的資料不會被刪除。\n\n如果現在有立即危險，請先撥 119，或打 1925 安心專線。");
  if (!ok) return;
  if (typeof stopSpeech === "function") stopSpeech();
  try {
    const res = await fetch("/api/chat/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": window.ANLA_CSRF_TOKEN },
      body: "{}",
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "暫時無法開始新對話，請稍後再試。");
    location.reload();
  } catch (error) {
    alert(error.message || "暫時無法開始新對話，請稍後再試。");
  }
}

// Panels added after a reply (safety notice, referral choices, counseling card) used to scroll the reply itself
// out of the chat window (2026-10-23 live test). Show the start of the reply; the panels follow below it.
function keepReplyInView(bubble) {
  const chat = document.getElementById("chatMessages");
  const message = bubble && bubble.closest(".message");
  if (!chat || !message) return;
  chat.scrollTop += message.getBoundingClientRect().top - chat.getBoundingClientRect().top - 8;
  document.querySelector(".chat-card")?.classList.add("is-chatting");
}

// ==================== 發送對話訊息與 AI 最溫暖同理回覆 ====================

async function sendMessage() {
  if (isSending) return;
  // 只確認已閱讀資料說明，不以信箱是否填寫阻擋對話。
  // A message sent while the page is still loading waited for nothing and was dropped (2026-10-23 live test).
  if (!studentOnboarded && window.anlaStateReady) await window.anlaStateReady.catch(() => {});
  if (!studentOnboarded) {
    openOnboardingModal(false);
    return;
  }

  const input = document.getElementById("userInput");
  const text = input.value.trim();
  if (!text) return;
  isSending = true;
  clearIdleReminders();

  // 若正在語音錄音，先停止錄音
  if (isRecording) {
    stopVoiceRecognition();
  }

  appendMessage("user", text);
  input.value = "";
  conversationHistory.push({ role: "user", text: text });

  const typingId = showTypingIndicator();

  // A stuck server must not leave the page in 「傳送中」 forever: the student could not send a crisis message.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 45000);
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": window.ANLA_CSRF_TOKEN },
      body: JSON.stringify({
        message: text,
        reply_style: currentReplyStyle,
        // The server retains bounded dialogue history; do not resend the entire conversation.
      }),
      signal: controller.signal,
    });

    // An HTML error page (413, 500, a proxy) is not JSON; show a plain message instead of a parser error.
    const data = await res.json().catch(() => ({ error: res.status === 413 ? "訊息太長了" : "伺服器暫時沒有回應" }));
    removeTypingIndicator(typingId);
    if (!res.ok) {
      if (res.status === 403) openOnboardingModal(false);
      throw new Error(data.error || "對話暫時無法送出");
    }

    let replyBubble = null;
    applyCompanionRole(data.companion_role);
    applyReplyStyleResponse(data);
    if (data.reply) {
      // 純溫暖回覆，學生端不顯示任何燈號或評判結果 (燈號全數保留至後台由真人覆核)
      replyBubble = appendMessage("ai", data.reply);
      appendSources(replyBubble, data.sources);
      scheduleIdleReminders(Boolean(data.show_support_help || data.style_overridden_by_safety));
      conversationHistory.push({ role: "assistant", text: data.reply });

      updateAiStatusFromReply(data);
    }
    window.AnlaNextSteps.update(data);
    if (replyBubble) window.AnlaNextSteps.suggestInReply(replyBubble, data.support_offer);
    try {  // the counseling-office card must never turn a delivered reply into a send error
      window.AnlaSchoolReferral.setAvailable(data.school_referral_available);
      window.AnlaSchoolReferral.show(data.school_referral);
    } catch (_) { /* the header button still reopens it */ }
    keepReplyInView(replyBubble);
  } catch (err) {
    removeTypingIndicator(typingId);
    const offlineHint = navigator.onLine === false ? "目前沒有網路，可以先點上方提示打開離線呼吸練習與求助電話。" : "";
    const raw = err && err.message ? err.message : "";
    const englishOnly = raw && /[A-Za-z]/.test(raw) && !/[\u4e00-\u9fff]/.test(raw);
    const reason = err.name === "AbortError" ? "等太久沒有回應" : (englishOnly ? "連線中斷" : (raw || "連線中斷"));
    appendMessage("ai", `訊息送出時發生問題：${reason}。剛才打的字已放回輸入框，可以再按一次送出；若現在有立即危險，請直接撥打 119 或找身邊的大人。${offlineHint}`);
    if (!input.value) input.value = text;  // do not lose what the student wrote
    conversationHistory.pop();
  } finally {
    clearTimeout(timer);
    isSending = false;
  }
}

function quickSend(text) {
  const input = document.getElementById("userInput");
  input.value = text;
  sendMessage();
}

function appendMessage(sender, text) {
  const chatMessages = document.getElementById("chatMessages");
  const msgDiv = document.createElement("div");
  msgDiv.className = `message ${sender}`;

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.innerText = sender === "ai" ? "☀️" : "👤";

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  
  // 對話內容是純文字，避免把使用者或模型內容當成 HTML 執行。
  bubble.style.whiteSpace = "pre-wrap";
  bubble.textContent = text;

  // AI 訊息附帶單獨朗讀按鈕
  if (sender === "ai") {
    const voiceBtnDiv = document.createElement("div");
    voiceBtnDiv.style.marginTop = "0.5rem";
    voiceBtnDiv.style.textAlign = "right";
    
    const voiceBtn = document.createElement("button");
    voiceBtn.type = "button";
    voiceBtn.className = "btn-play-voice";
    voiceBtn.innerText = "🔊 朗讀這段話";
    voiceBtn.onclick = function () { speakMessage(this); };
    
    voiceBtnDiv.appendChild(voiceBtn);
    bubble.appendChild(voiceBtnDiv);
  }

  msgDiv.appendChild(avatar);
  msgDiv.appendChild(bubble);
  chatMessages.appendChild(msgDiv);
  chatMessages.scrollTop = chatMessages.scrollHeight;

  // 若開啟自動語音朗讀，且為 AI 回覆，則自動播放語音
  if (sender === "ai" && isAutoSpeech) {
    speakMessage(bubble.querySelector(".btn-play-voice") || text); // 用按鈕朗讀，學生才能暫停
  }
  return bubble;
}

// 雲端 AI 有時要 15 秒以上；文字隨等待時間更新，讓學生知道不是當掉了。
const TYPING_STAGES = [
  [0, "安啦正在認真傾聽中...💭"],
  [6000, "正在想怎麼回你比較好...💭"],
  [15000, "快好了，再等我一下下...⏳"],
  [25000, "網路有點慢，還在努力中；真的很急的話，可以先撥頁面上的求助電話。"],
];
const typingTimers = {};

function showTypingIndicator() {
  const chatMessages = document.getElementById("chatMessages");
  const typingDiv = document.createElement("div");
  const id = "typing-" + Date.now();
  typingDiv.id = id;
  typingDiv.className = "message ai";
  typingDiv.innerHTML = `
    <div class="avatar">☀️</div>
    <div class="bubble typing-bubble" role="status" aria-live="polite"></div>
  `;
  const bubble = typingDiv.querySelector(".typing-bubble");
  typingTimers[id] = TYPING_STAGES.map(([delay, text]) => setTimeout(() => { bubble.textContent = text; }, delay));
  chatMessages.appendChild(typingDiv);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return id;
}

function removeTypingIndicator(id) {
  (typingTimers[id] || []).forEach(clearTimeout);
  delete typingTimers[id];
  const el = document.getElementById(id);
  if (el) el.remove();
}

// ==================== 雙向語音對答系統 (Web Speech API) ====================

// 1. 語音辨識 (Speech-to-Text / STT 麥克風輸入)
function initVoiceRecognition() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    console.warn("當前瀏覽器不支援 Web Speech API 語音辨識");
    return null;
  }

  const recog = new SpeechRecognition();
  recog.lang = "zh-TW";
  recog.continuous = false;
  recog.interimResults = true;

  recog.onstart = () => {
    isRecording = true;
    const micBtn = document.getElementById("micBtn");
    const banner = document.getElementById("recordingBanner");
    if (micBtn) micBtn.classList.add("listening");
    if (banner) banner.style.display = "flex";
  };

  recog.onresult = (event) => {
    let interimTranscript = "";
    let finalTranscript = "";

    for (let i = event.resultIndex; i < event.results.length; ++i) {
      if (event.results[i].isFinal) {
        finalTranscript += event.results[i][0].transcript;
      } else {
        interimTranscript += event.results[i][0].transcript;
      }
    }

    const input = document.getElementById("userInput");
    if (input) {
      input.value = finalTranscript || interimTranscript;
    }
  };

  recog.onerror = (event) => {
    console.warn("語音辨識通知:", event.error);
    stopVoiceRecognition();
    if (event.error === "not-allowed") {
      alert("請允許瀏覽器麥克風使用權限，即可使用語音傾訴功能喔！");
    }
  };

  recog.onend = () => {
    stopVoiceRecognition();
    const input = document.getElementById("userInput");
    if (input && input.value.trim()) {
      input.focus();
    }
  };

  return recog;
}

function toggleVoiceRecognition() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    alert("您的瀏覽器暫不支援麥克風語音輸入（建議使用 Chrome, Edge 或 Safari 瀏覽器）。您也可以直接以打字方式跟安啦聊聊喔！");
    return;
  }

  if (isRecording) {
    stopVoiceRecognition();
  } else {
    try {
      if (!recognition) {
        recognition = initVoiceRecognition();
      }
      recognition.start();
    } catch (e) {
      console.warn("Recognition start retry", e);
      try {
        recognition = initVoiceRecognition();
        recognition.start();
      } catch (err) {
        stopVoiceRecognition();
      }
    }
  }
}

function stopVoiceRecognition() {
  isRecording = false;
  if (recognition) {
    try { recognition.stop(); } catch (e) {}
  }
  const micBtn = document.getElementById("micBtn");
  const banner = document.getElementById("recordingBanner");
  if (micBtn) micBtn.classList.remove("listening");
  if (banner) banner.style.display = "none";
}

// 2. 語音朗讀 (Text-to-Speech)：可暫停／繼續／停止；聲音可選雲端自然語音（伺服器有設定時）或裝置內建語音。
const SPEECH_LABELS = { idle: "🔊 朗讀這段話", loading: "⏳ 準備聲音…", playing: "⏸ 暫停", paused: "▶ 繼續" };
const VOICE_SAMPLE = "嗨，我是安啦會客室的陪伴夥伴。有什麼想說的，都可以慢慢說。";
// Android 的瀏覽器內建語音不支援暫停，在那裡按暫停就直接停止。
const DEVICE_PAUSE_WORKS = !/Android/i.test(navigator.userAgent);
let speech = null; // 目前的朗讀：{ btn, kind: "device" | "audio" | null, audio, paused, cancelled }
let cloudVoices = [];
let voiceChoice = localStorage.getItem("anla_voice") || ""; // "cloud:<id>"、"device:<name>"；空白＝自動
let voiceRate = parseFloat(localStorage.getItem("anla_voice_rate") || "1") || 1;
const audioCache = new Map(); // 同一段話再聽一次不必重新產生

function toggleAutoSpeech() {
  isAutoSpeech = !isAutoSpeech;
  localStorage.setItem("anla_auto_speech", isAutoSpeech ? "true" : "false");
  updateTTSButtonUI();
  if (!isAutoSpeech) stopSpeech();
}

function updateTTSButtonUI() {
  const btn = document.getElementById("ttsToggleBtn");
  if (!btn) return;
  if (isAutoSpeech) {
    btn.innerText = "🔊 語音朗讀：開啟中";
    btn.classList.add("active");
  } else {
    btn.innerText = "🔇 語音朗讀：已關閉";
    btn.classList.remove("active");
  }
}

function speechText(elementOrText) {
  let text = "";
  if (typeof elementOrText === "string") {
    text = elementOrText;
  } else if (elementOrText && elementOrText.nodeType) {
    const bubble = elementOrText.closest(".bubble");
    if (bubble) {
      const clone = bubble.cloneNode(true);
      clone.querySelectorAll(".reply-sources").forEach(el => el.remove());  // links are not read aloud
      clone.querySelectorAll("button").forEach(b => {
        if (b.classList.contains("inline-support-link")) b.replaceWith(document.createTextNode(b.textContent));
        else b.remove();
      });
      text = clone.innerText || clone.textContent;
    }
  }
  // 清除 emoji 與特殊符號使朗讀更加流暢自然
  return (text || "")
    .replace(/[\u{1F300}-\u{1FAFF}]|[\u{2600}-\u{27BF}]|️/gu, "")
    .trim();
}

function deviceVoices() {
  if (!window.speechSynthesis) return [];
  return window.speechSynthesis.getVoices().filter(v => /^(zh|cmn|yue)/i.test(v.lang) || /Chinese|Taiwan|Mandarin/i.test(v.name));
}

function isNaturalVoice(v) {
  return /Natural|Online|Neural|Premium|Enhanced/i.test(v.name);
}

function bestDeviceVoice() {
  const list = deviceVoices();
  const taiwan = v => /zh[-_]TW|Hant|Taiwan|HsiaoChen|HsiaoYu|YunJhe|Mei-Jia/i.test(v.lang + " " + v.name);
  return list.find(v => taiwan(v) && isNaturalVoice(v)) || list.find(taiwan) || list.find(isNaturalVoice) || list[0] || null;
}

function selectedVoice() {
  if (voiceChoice.startsWith("cloud:")) {
    const id = voiceChoice.slice(6);
    if (cloudVoices.some(v => v.id === id)) return { kind: "cloud", id };
  }
  if (voiceChoice.startsWith("device:")) {
    const name = voiceChoice.slice(7);
    return { kind: "device", voice: deviceVoices().find(v => v.name === name) || bestDeviceVoice() };
  }
  // 沒選過：伺服器有雲端語音就用第一個（最自然的台灣華語），否則用裝置內建最好的中文聲音。
  if (cloudVoices.length) return { kind: "cloud", id: cloudVoices[0].id };
  return { kind: "device", voice: bestDeviceVoice() };
}

function setSpeechButton(btn, state) {
  if (!btn || !btn.classList.contains("btn-play-voice")) return;
  btn.textContent = SPEECH_LABELS[state];
  btn.dataset.speech = state;
  btn.setAttribute("aria-label", state === "playing" ? "暫停朗讀" : state === "paused" ? "繼續朗讀" : "朗讀這段話");
  let stop = btn.parentElement && btn.parentElement.querySelector(".btn-stop-voice");
  if (state === "idle") {
    if (stop) stop.remove();
    return;
  }
  if (!stop && btn.parentElement) {
    stop = document.createElement("button");
    stop.type = "button";
    stop.className = "btn-stop-voice";
    stop.textContent = "⏹ 停止";
    stop.setAttribute("aria-label", "停止朗讀");
    stop.onclick = stopSpeech;
    btn.after(stop);
  }
}

function stopSpeech() {
  if (window.speechSynthesis) window.speechSynthesis.cancel();
  if (speech) {
    speech.cancelled = true;
    if (speech.audio) speech.audio.pause();
    setSpeechButton(speech.btn, "idle");
  }
  speech = null;
}

function finishSpeech(s) {
  if (speech !== s) return;
  setSpeechButton(s.btn, "idle");
  speech = null;
}

// 按鈕第一次按是朗讀；朗讀中再按是暫停，暫停時再按是繼續。
function speakMessage(elementOrText) {
  const btn = elementOrText && elementOrText.nodeType ? elementOrText : null;
  if (btn && speech && speech.btn === btn) {
    togglePause();
    return;
  }
  stopSpeech();
  const text = speechText(elementOrText);
  if (!text) return;
  const current = speech = { btn, kind: null, audio: null, paused: false, cancelled: false };
  const choice = selectedVoice();
  if (choice.kind === "cloud") playCloud(current, choice.id, text);
  else playDevice(current, choice.voice, text);
}

function togglePause() {
  const s = speech;
  if (!s || !s.kind) return; // 聲音還在準備中
  if (s.kind === "device" && !DEVICE_PAUSE_WORKS) {
    stopSpeech();
    return;
  }
  if (s.paused) {
    if (s.kind === "audio") s.audio.play().catch(() => {});
    else window.speechSynthesis.resume();
    s.paused = false;
    setSpeechButton(s.btn, "playing");
  } else {
    if (s.kind === "audio") s.audio.pause();
    else window.speechSynthesis.pause();
    s.paused = true;
    setSpeechButton(s.btn, "paused");
  }
}

function playDevice(s, voice, text) {
  if (!window.speechSynthesis) {
    finishSpeech(s);
    alert("這個瀏覽器不支援語音朗讀。");
    return;
  }
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = voice ? voice.lang : "zh-TW";
  if (voice) utterance.voice = voice;
  utterance.rate = 0.95 * voiceRate; // 舒緩溫柔的陪伴語速
  utterance.pitch = 1.05;
  utterance.onend = () => finishSpeech(s);
  utterance.onerror = () => finishSpeech(s);
  s.kind = "device";
  setSpeechButton(s.btn, "playing");
  window.speechSynthesis.speak(utterance);
}

async function playCloud(s, voiceId, text) {
  setSpeechButton(s.btn, "loading");
  const key = `${voiceId}|${voiceRate}|${text}`;
  let url = audioCache.get(key);
  if (!url) {
    try {
      const res = await fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": window.ANLA_CSRF_TOKEN },
        body: JSON.stringify({ text: text.slice(0, 800), voice: voiceId, rate: voiceRate }),
      });
      if (!res.ok) throw new Error(String(res.status));
      url = URL.createObjectURL(await res.blob());
      audioCache.set(key, url);
      if (audioCache.size > 20) {
        const [oldKey, oldUrl] = audioCache.entries().next().value;
        URL.revokeObjectURL(oldUrl);
        audioCache.delete(oldKey);
      }
    } catch (e) {
      if (s.cancelled) return;
      showVoiceNotice("雲端語音暫時無法使用，這次改用裝置內建的聲音。");
      playDevice(s, bestDeviceVoice(), text);
      return;
    }
  }
  if (s.cancelled) return;
  const audio = new Audio(url);
  s.audio = audio;
  s.kind = "audio";
  audio.onended = () => finishSpeech(s);
  setSpeechButton(s.btn, "playing");
  audio.play().catch(() => {
    // 瀏覽器擋下自動播放（例如自動朗讀時頁面還沒被點過）：停在「繼續」，讓學生自己按。
    if (s.cancelled) return;
    s.paused = true;
    setSpeechButton(s.btn, "paused");
  });
}

function showVoiceNotice(text) {
  const notice = document.getElementById("voiceNotice");
  if (notice) notice.textContent = text;
}

// ---------- 朗讀聲音選單 ----------
async function loadCloudVoices() {
  try {
    const res = await fetch("/api/tts/voices", { cache: "no-store" });
    cloudVoices = res.ok ? ((await res.json()).voices || []) : [];
  } catch (e) {
    cloudVoices = [];
  }
  renderVoiceOptions();
}

function renderVoiceOptions() {
  const select = document.getElementById("voiceSelect");
  if (!select) return;
  select.innerHTML = "";
  if (cloudVoices.length) {
    const group = document.createElement("optgroup");
    group.label = "雲端自然語音";
    cloudVoices.forEach(v => group.appendChild(new Option(`${v.label}（${v.service}）`, "cloud:" + v.id)));
    select.appendChild(group);
  }
  const device = document.createElement("optgroup");
  device.label = "這台裝置內建的聲音（不經網路）";
  device.appendChild(new Option("自動挑選中文聲音", "device:"));
  deviceVoices().forEach(v => device.appendChild(new Option(v.name + (isNaturalVoice(v) ? "（自然）" : ""), "device:" + v.name)));
  select.appendChild(device);
  const choice = selectedVoice();
  select.value = choice.kind === "cloud" ? "cloud:" + choice.id
    : (voiceChoice.startsWith("device:") && [...select.options].some(o => o.value === voiceChoice) ? voiceChoice : "device:");
  const rate = document.getElementById("voiceRate");
  if (rate) rate.value = String(voiceRate);
  const note = document.getElementById("voiceCloudNote");
  if (note) note.hidden = !select.value.startsWith("cloud:");
}

function openVoiceDialog() {
  const dialog = document.getElementById("voiceDialog");
  if (!dialog) return;
  renderVoiceOptions();
  showVoiceNotice("");
  if (typeof dialog.showModal === "function") {
    if (!dialog.open) dialog.showModal();
  } else {
    dialog.setAttribute("open", "");
  }
  document.getElementById("voiceSelect")?.focus();
}

function closeVoiceDialog() {
  const dialog = document.getElementById("voiceDialog");
  if (!dialog) return;
  if (typeof dialog.close === "function" && dialog.open) dialog.close();
  else dialog.removeAttribute("open");
}

document.addEventListener("DOMContentLoaded", () => {
  loadCloudVoices();
  if (window.speechSynthesis) window.speechSynthesis.addEventListener("voiceschanged", renderVoiceOptions);
  document.getElementById("voiceSettingsBtn")?.addEventListener("click", openVoiceDialog);
  document.getElementById("voiceClose")?.addEventListener("click", closeVoiceDialog);
  const dialog = document.getElementById("voiceDialog");
  if (dialog) {
    dialog.addEventListener("click", event => { if (event.target === dialog) closeVoiceDialog(); });
    dialog.addEventListener("close", () => document.getElementById("voiceSettingsBtn")?.focus());
  }
  document.getElementById("voiceSelect")?.addEventListener("change", event => {
    voiceChoice = event.target.value;
    localStorage.setItem("anla_voice", voiceChoice);
    stopSpeech();
    renderVoiceOptions();
  });
  document.getElementById("voiceRate")?.addEventListener("change", event => {
    voiceRate = parseFloat(event.target.value) || 1;
    localStorage.setItem("anla_voice_rate", String(voiceRate));
    stopSpeech();
  });
  document.getElementById("voicePreview")?.addEventListener("click", () => speakMessage(VOICE_SAMPLE));
});

// ---------- AI 連線狀態燈：讓使用者看得出雲端 AI 是否正常運作 ----------
// 回覆都來自雲端 AI；AI 無法回覆時，學生會看到誠實的說明與求助電話（危險時改用審過的固定安全文字）。
const AI_REASON_TEXT = {
  timeout: "回應逾時", rate_limited: "額度或流量已用完", auth_error: "API 金鑰無效", api_error: "服務發生錯誤",
  cooldown: "暫停重試中", global_budget: "使用量達上限", model_not_found: "可用的模型都暫停中",
  bad_response: "回應格式錯誤", format_error: "回應格式錯誤", budget_exceeded: "回應太慢",
  incomplete: "內容被服務擋下", empty: "沒有回應內容", unavailable: "服務暫時過載", rejected: "服務不接受這個請求",
};

function setAiStatus(state, label, detail) {
  const el = document.getElementById("aiStatus");
  const text = document.getElementById("aiStatusText");
  if (!el || !text) return;
  el.dataset.state = state;
  text.textContent = label;
  el.title = (detail ? detail + "\n" : "") + "點一下重新檢查";
}

function renderAiStatus(ai) {
  if (!ai) return;
  if (ai.state === "not_configured") {
    setAiStatus("off", "尚未接上 AI", "網站還沒有設定 AI 服務，目前無法聊天；需要協助可直接撥 1925 或 119。");
  } else if (ai.state === "ok") {
    setAiStatus("ok", "AI 連線正常", "雲端 AI 可以正常回覆。");
  } else if (ai.state === "degraded") {
    const reason = AI_REASON_TEXT[ai.reason] || "暫時無法使用";
    const retry = ai.retry_in ? `，約 ${ai.retry_in} 秒後自動重試` : "";
    setAiStatus("warn", `AI 暫時無法使用：${reason}`, `這段時間 AI 沒辦法回覆${retry}；需要協助可直接撥 1925 或 119。`);
  } else {
    setAiStatus("checking", "已設定雲端 AI，尚未連線", "傳出第一則訊息後會更新。");
  }
}

async function checkAiStatus() {
  setAiStatus("checking", "檢查 AI 連線中…", "");
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 12000);  // never spin forever
  try {
    const res = await fetch("/api/status?probe=1", { cache: "no-store", signal: controller.signal });
    if (!res.ok) throw new Error(String(res.status));
    renderAiStatus((await res.json()).ai);
  } catch (err) {
    if (err && err.name === "AbortError") {
      setAiStatus("warn", "AI 連線檢查逾時", "伺服器在 12 秒內沒有回覆檢查結果；可以先繼續聊天，傳出訊息後會再更新。");
    } else {
      setAiStatus("down", "伺服器沒有回應", "可能是網路中斷或伺服器沒有啟動；需要協助可直接撥 1925 或 119。");
    }
  } finally {
    clearTimeout(timer);
  }
}

function updateAiStatusFromReply(data) {
  const reason = data.fallback_reason;
  if (data.reply_source === "ai") {
    setAiStatus("ok", "AI 連線正常", "這一則由雲端 AI 回覆。");
  } else if (reason === "rule_check") {
    setAiStatus("ok", "AI 連線正常", "AI 這一則的回覆沒有通過安全檢查，所以沒有送出。");
  } else if (reason === "builtin" || reason === "no_key") {
    setAiStatus("off", "尚未接上 AI", "網站還沒有設定 AI 服務，目前無法聊天；需要協助可直接撥 1925 或 119。");
  } else if (reason === "cooldown") {
    // Calls are paused; ask the server for the underlying cause (e.g. quota used up) instead of "paused".
    fetch("/api/status", { cache: "no-store" })
      .then(res => (res.ok ? res.json() : null))
      .then(body => body && renderAiStatus(body.ai))
      .catch(() => setAiStatus("warn", `AI 暫時無法使用：${AI_REASON_TEXT.cooldown}`, ""));
  } else if (data.reply_source === "safety") {
    // The student got the reviewed safety text; one empty or slow AI call is not an outage, and a warning badge
    // at that moment only adds worry (2026-10-23 live test). Real outages still show through /api/status.
    setAiStatus("ok", "AI 連線正常", "這一則用審核過的安全文字回覆。");
  } else if (reason && AI_REASON_TEXT[reason]) {
    setAiStatus("warn", `AI 暫時無法使用：${AI_REASON_TEXT[reason]}`, "這一則 AI 沒辦法回覆；需要協助可直接撥 1925 或 119。");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const el = document.getElementById("aiStatus");
  if (!el) return;
  el.addEventListener("click", checkAiStatus);
  checkAiStatus();
  setInterval(checkAiStatus, 5 * 60 * 1000);
});
