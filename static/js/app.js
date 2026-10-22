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
const REPLY_STYLES = ["warm", "lively", "rational", "listen_only"];
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

// ==================== 語音對答系統狀態 (Web Speech API) ====================
let recognition = null;
let isRecording = false;
let isAutoSpeech = localStorage.getItem("anla_auto_speech") === "true"; // 需使用者主動開啟

document.addEventListener("DOMContentLoaded", () => {
  updateTTSButtonUI();
  fetch("/api/chat/state", {cache: "no-store"}).then(res => res.json()).then(data => {
    if (data.student_profile) applyStudentProfile(data.student_profile);
    else studentOnboarded = false;
    applyCompanionRole(data.companion_role);
    applyReplyStyleResponse(data);
    window.AnlaNextSteps.update(data);
  }).catch(() => {}).finally(checkOnboardingStatus);
});

// ==================== 資料使用說明與選填聯絡資料 ====================

function checkOnboardingStatus() {
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

// ==================== 發送對話訊息與 AI 最溫暖同理回覆 ====================

async function sendMessage() {
  if (isSending) return;
  // 只確認已閱讀資料說明，不以信箱是否填寫阻擋對話。
  if (!studentOnboarded) {
    openOnboardingModal(false);
    return;
  }

  const input = document.getElementById("userInput");
  const text = input.value.trim();
  if (!text) return;
  isSending = true;

  // 若正在語音錄音，先停止錄音
  if (isRecording) {
    stopVoiceRecognition();
  }

  appendMessage("user", text);
  input.value = "";
  conversationHistory.push({ role: "user", text: text });

  const typingId = showTypingIndicator();

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": window.ANLA_CSRF_TOKEN },
      body: JSON.stringify({
        message: text,
        reply_style: currentReplyStyle,
        // The server retains bounded dialogue history; do not resend the entire conversation.
      })
    });

    const data = await res.json();
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
      conversationHistory.push({ role: "assistant", text: data.reply });

      updateAiStatusFromReply(data);
    }
    window.AnlaNextSteps.update(data);
    if (replyBubble) window.AnlaNextSteps.suggestInReply(replyBubble, data.support_offer);
  } catch (err) {
    removeTypingIndicator(typingId);
    const offlineHint = navigator.onLine === false ? "目前沒有網路，可以先點上方提示打開離線呼吸練習與求助電話。" : "";
    appendMessage("ai", `訊息送出時發生問題：${err.message || "連線中斷"}。請稍後再試；若現在有立即危險，請直接撥打 119 或找身邊的大人。${offlineHint}`);
  } finally {
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
    speakMessage(text);
  }
  return bubble;
}

function showTypingIndicator() {
  const chatMessages = document.getElementById("chatMessages");
  const typingDiv = document.createElement("div");
  const id = "typing-" + Date.now();
  typingDiv.id = id;
  typingDiv.className = "message ai";
  typingDiv.innerHTML = `
    <div class="avatar">☀️</div>
    <div class="bubble typing-bubble">
      安啦正在認真傾聽中...💭
    </div>
  `;
  chatMessages.appendChild(typingDiv);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return id;
}

function removeTypingIndicator(id) {
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

// 2. 語音朗讀合成 (Text-to-Speech / TTS 語音發音)
function toggleAutoSpeech() {
  isAutoSpeech = !isAutoSpeech;
  localStorage.setItem("anla_auto_speech", isAutoSpeech ? "true" : "false");
  updateTTSButtonUI();
  if (!isAutoSpeech && window.speechSynthesis) {
    window.speechSynthesis.cancel();
  }
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

function speakMessage(elementOrText) {
  if (!window.speechSynthesis) {
    alert("您的瀏覽器暫不支援語音朗讀功能。");
    return;
  }

  window.speechSynthesis.cancel();

  let textToSpeak = "";
  let targetBtn = null;

  if (typeof elementOrText === "string") {
    textToSpeak = elementOrText;
  } else if (elementOrText && elementOrText.nodeType) {
    targetBtn = elementOrText;
    const bubble = elementOrText.closest(".bubble");
    if (bubble) {
      const clone = bubble.cloneNode(true);
      const buttons = clone.querySelectorAll("button");
      buttons.forEach(b => {
        if (b.classList.contains("inline-support-link")) b.replaceWith(document.createTextNode(b.textContent));
        else b.remove();
      });
      textToSpeak = clone.innerText || clone.textContent;
    }
  }

  if (!textToSpeak || !textToSpeak.trim()) return;

  // 清除 emoji 與特殊符號使朗讀更加流暢自然
  const cleanText = textToSpeak
    .replace(/[\u{1F300}-\u{1F9FF}]|[\u{2600}-\u{26FF}]|[\u{2700}-\u{27BF}]/gu, "")
    .replace(/[🌱☀️🐾👋✨❤️💪💭🚨🚓📞📋⚠️]/g, "")
    .trim();

  const utterance = new SpeechSynthesisUtterance(cleanText);
  utterance.lang = "zh-TW";
  utterance.rate = 0.95; // 舒緩溫柔的陪伴語速
  utterance.pitch = 1.05; // 溫暖親切的聲調

  // 選取繁體中文最佳發音
  const voices = window.speechSynthesis.getVoices();
  const twVoice = voices.find(v => 
    v.lang === "zh-TW" || 
    v.lang === "cmn-Hant-TW" || 
    v.name.includes("Taiwan") || 
    v.name.includes("Mei-Jia") || 
    v.name.includes("HsiaoChen") ||
    v.name.includes("Yating")
  );
  if (twVoice) {
    utterance.voice = twVoice;
  }

  if (targetBtn) {
    const originalText = targetBtn.innerText;
    targetBtn.innerText = "🔊 朗讀中...";
    targetBtn.style.opacity = "0.7";
    
    utterance.onend = () => {
      targetBtn.innerText = originalText;
      targetBtn.style.opacity = "1";
    };
    utterance.onerror = () => {
      targetBtn.innerText = originalText;
      targetBtn.style.opacity = "1";
    };
  }

  window.speechSynthesis.speak(utterance);
}

// ---------- AI 連線狀態燈：讓使用者看得出雲端 AI 是否正常運作 ----------
// 安全提醒與求助資訊由本機規則產生，不受 AI 狀態影響；這裡只顯示「回覆是否來自雲端 AI」。
const AI_REASON_TEXT = {
  timeout: "回應逾時", rate_limited: "額度或流量已用完", auth_error: "API 金鑰無效", api_error: "服務發生錯誤",
  cooldown: "暫停重試中", global_budget: "使用量達上限", model_not_found: "模型名稱設定錯誤",
  bad_response: "回應格式錯誤", format_error: "回應格式錯誤", budget_exceeded: "回應太慢",
  incomplete: "內容被服務擋下", empty: "沒有回應內容",
};
const AI_PROVIDER_NAME = { gemini: "Gemini", openai: "OpenAI" };

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
  const name = AI_PROVIDER_NAME[ai.provider] || "AI";
  if (ai.state === "not_configured") {
    setAiStatus("off", "本機回覆模式（未設定 AI）", "沒有設定雲端 AI 金鑰，回覆由本機規則產生。");
  } else if (ai.state === "ok") {
    setAiStatus("ok", `AI 連線正常（${name}）`, ai.model ? `模型：${ai.model}` : "");
  } else if (ai.state === "degraded") {
    const reason = AI_REASON_TEXT[ai.reason] || "暫時無法使用";
    const retry = ai.retry_in ? `，約 ${ai.retry_in} 秒後自動重試` : "";
    setAiStatus("warn", `AI 暫時無法使用：${reason}`, `這段時間改用本機回覆${retry}；安全提醒與求助資訊不受影響。`);
  } else {
    setAiStatus("checking", `已設定 ${name}，尚未連線`, "傳出第一則訊息後會更新。");
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
  const used = data.model_used || "";
  const reason = data.fallback_reason;
  if (/Gemini|OpenAI/.test(used)) {
    setAiStatus("ok", `AI 連線正常（${/OpenAI/.test(used) ? "OpenAI" : "Gemini"}）`, used);
  } else if (reason === "rule_check") {
    setAiStatus("ok", "AI 連線正常", "這一則改用本機回覆，因為 AI 的回覆沒有通過安全檢查。");
  } else if (reason === "builtin" || reason === "no_key") {
    setAiStatus("off", "本機回覆模式（未設定 AI）", "沒有設定雲端 AI 金鑰，回覆由本機規則產生。");
  } else if (reason && AI_REASON_TEXT[reason]) {
    setAiStatus("warn", `AI 暫時無法使用：${AI_REASON_TEXT[reason]}`, "這一則改用本機回覆；安全提醒與求助資訊不受影響。");
  }
  // 安全回覆、規則回覆這一輪沒有呼叫 AI，維持原本的狀態。
}

document.addEventListener("DOMContentLoaded", () => {
  const el = document.getElementById("aiStatus");
  if (!el) return;
  el.addEventListener("click", checkAiStatus);
  checkAiStatus();
  setInterval(checkAiStatus, 5 * 60 * 1000);
});
