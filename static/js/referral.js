// 下一步只依伺服器回傳的動作顯示；學生頁不呈現分流燈號。
(() => {
  let current = null;
  let urgentActive = false;
  let busy = false;
  const byId = id => document.getElementById(id);
  const node = (tag, text, className = "") => {
    const el = document.createElement(tag);
    el.textContent = text;
    if (className) el.className = className;
    return el;
  };

  function status(text) {
    let el = byId("choiceStatus");
    if (!el) {
      const bubbles = document.querySelectorAll("#chatMessages .message.ai .bubble");
      const bubble = bubbles[bubbles.length - 1];
      if (bubble) {
        el = node("p", "", "choice-note");
        el.id = "choiceStatus";
        el.setAttribute("role", "status");
        bubble.appendChild(el);
      }
    }
    if (el) el.textContent = text;
  }
  function setBusy(value) {
    busy = value;
    // 電話是獨立的連結，任何 API 請求都不會停用它們。
    byId("nextStepChoices")?.querySelectorAll("button[data-consent]").forEach(button => {
      button.disabled = value || Boolean(current?.recorded);
    });
  }
  function showUrgentHelp() {
    if (urgentActive) return;
    urgentActive = true;
    const panel = byId("urgentHelpPanel");
    panel.hidden = false;
    panel.classList.remove("is-compact");
    byId("urgent119").focus();
  }
  function placeChoices() {
    const panel = byId("nextStepChoices");
    if (!panel) return;
    const urgent = byId("urgentHelpPanel");
    if (panel.classList.contains("inline-support-result")) return;
    const host = urgentActive && !urgent.classList.contains("is-compact")
      ? byId("urgentChoices") : byId("chatMessages");
    host.appendChild(panel);
    if (host.id === "chatMessages") host.scrollTop = host.scrollHeight;
  }
  function continueTalking() {
    if (urgentActive) {
      byId("urgentHelpPanel").classList.add("is-compact");
      document.body.classList.add("has-urgent-help");
      adjustUrgentOffset();
    }
    placeChoices();
    byId("userInput").focus();
  }
  function adjustUrgentOffset() {
    const panel = byId("urgentHelpPanel");
    if (panel.classList.contains("is-compact")) {
      document.body.style.setProperty("--urgent-help-height", `${panel.getBoundingClientRect().height}px`);
    }
  }

  function showResources(host, resources = current?.resources || [], inline = false) {
    host.appendChild(node("p", "依你登錄的鄉鎮提供就近公開電話；實際服務範圍與受理方式請向單位確認。"));
    const links = node("div", "", inline ? "inline-resource-links" : "choice-chips");
    for (const resource of resources) {
      const link = node("a", `${resource.name}：${resource.phone}`, inline ? "inline-support-link" : "choice-chip");
      link.href = resource.phone_href;
      links.appendChild(link);
    }
    host.appendChild(links);
    host.appendChild(node("p", "點電話是由你自行撥號，本網站沒有替你接通或送出轉介。", "choice-note"));
  }
  function preview(host, steps) {
    if (!steps.summary_preview) return;
    const details = document.createElement("details");
    details.appendChild(node("summary", "查看這次將分享的摘要與登錄資料"));
    details.appendChild(node("p", steps.summary_preview, "summary-preview"));
    host.appendChild(details);
  }
  function optionalContact(host, steps, afterSave = null) {
    const details = node("details", "", "optional-contact-fields");
    details.appendChild(node("summary", "補充學校／聯絡信箱（選填）"));
    details.appendChild(node("p", "已填的資料會沿用。不填也可以分享摘要；若沒有聯絡方式，工作臺無法主動聯絡你。填寫不代表已通知學校，急需協助請直接打電話。"));
    const fields = {};
    for (const [key, label, type, max] of [
      ["student_school", "學校（選填）", "text", 100],
      ["student_email", "聯絡信箱（選填）", "email", 254]
    ]) {
      const input = document.createElement("input");
      input.id = `referral_${key}`;
      input.type = type;
      input.maxLength = max;
      input.value = steps.contact?.[key] || "";
      const caption = node("label", label);
      caption.htmlFor = input.id;
      details.append(caption, input);
      fields[key] = input;
    }
    const save = button("儲存選填資料，重新查看摘要", async () => {
      if (busy) return;
      if (!fields.student_email.reportValidity()) return;
      const snapshot = current;
      const name = byId("referralPreferredName")?.value;
      setBusy(true);
      save.disabled = true;
      try {
        const data = await post("/api/onboarding", {
          student_alias: studentAlias, township: studentTownship,
          student_email: fields.student_email.value.trim(),
          student_school: fields.student_school.value.trim(), privacy_acknowledged: true
        });
        applyStudentProfile(data.student_profile);
        checkOnboardingStatus();
        if (current !== snapshot) {
          status("資料已儲存；對話也有更新，請查看最新摘要後再決定是否分享。");
          return;
        }
        if (afterSave && data.next_steps?.consent_kind === "summary") afterSave(data.next_steps);
        else render(data.next_steps, true);
        if (name !== undefined && byId("referralPreferredName")) byId("referralPreferredName").value = name;
        status("選填資料已儲存，尚未分享摘要。請查看更新後的摘要，再決定是否同意。");
      } catch (error) {
        status(error.message || "資料未能儲存，你仍可以繼續聊或直接打電話。");
      } finally {
        save.disabled = false;
        setBusy(false);
      }
    });
    details.appendChild(save);
    host.appendChild(details);
  }
  function button(label, handler, consent = false) {
    const el = node("button", label, "choice-chip");
    el.type = "button";
    el.addEventListener("click", handler);
    if (consent) {
      el.dataset.consent = "true";
      el.disabled = busy || Boolean(current?.recorded);
    }
    return el;
  }
  async function copyText(area) {
    try {
      await navigator.clipboard.writeText(area.value);
      status("已複製，你可以自行貼給想聯絡的人。");
    } catch (_) {
      area.focus();
      area.select();
      status("已選取文字，請按 Ctrl+C，或長按選擇複製。");
    }
  }
  function textBox(host, text, label) {
    const area = document.createElement("textarea");
    // The note is the student's own words to send: they can edit it before copying.
    area.readOnly = label !== "字條";
    area.rows = 7;
    area.className = "choice-text";
    area.setAttribute("aria-label", label);
    area.value = text;
    host.appendChild(area);
    host.appendChild(button(`複製${label}`, () => copyText(area)));
    return area;
  }
  async function post(url, body) {
    const response = await fetch(url, {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-CSRF-Token": window.ANLA_CSRF_TOKEN},
      body: JSON.stringify(body)
    });
    const data = await response.json();
    if (data.show_urgent_help) showUrgentHelp();
    if (!response.ok) {
      if (data.next_steps) render(data.next_steps, true);
      throw new Error(data.error || "暫時無法送出，請稍後再試。");
    }
    return data;
  }
  async function consent(agreed) {
    if (busy || !current) return;
    const snapshot = current;
    const preferredName = byId("referralPreferredName")?.value.trim() || snapshot.preferred_name;
    setBusy(true);
    try {
      const data = await post("/api/referral/consent", {
        consent: agreed, preferred_name: preferredName,
        revision: snapshot.revision, consent_kind: snapshot.consent_kind
      });
      if (current !== snapshot) return; // 較新的對話選項不被舊請求覆蓋。
      const output = byId("choiceOutput");
      output.replaceChildren(node("p", data.message));
      if (agreed && data.recorded) {
        current.recorded = true;
        if (data.referral_form) {
          textBox(output, data.referral_form, "轉介單");
          output.appendChild(button("下載轉介單", () => {
            const url = URL.createObjectURL(new Blob([data.referral_form], {type: "text/plain;charset=utf-8"}));
            const link = node("a", "");
            link.href = url;
            link.download = `anla-referral-${data.case_id}.txt`;
            link.click();
            setTimeout(() => URL.revokeObjectURL(url), 1000);
          }));
        }
      }
      showResources(output, data.resources);
      status(agreed && data.recorded ? "已記錄本次同意；尚未對外轉介。" : "你可以繼續聊，也可以先打電話。");
    } catch (error) {
      status(error.message || "送出失敗，尚未確認是否存入工作臺；可重試，電話仍可直接使用。");
    } finally {
      setBusy(false);
    }
  }
  async function teacherNote(bubble) {
    if (busy) return;
    const snapshot = current;
    setBusy(true);
    try {
      const data = await post("/api/generate-draft", {target: "輔導老師"});
      if (current !== snapshot) return;
      if (data.next_steps?.consent_kind === "referral") {
        render(data.next_steps);
        return;
      }
      showTeacherNote(bubble, data);
    } catch (error) {
      status(error.message || "字條暫時無法產生，你仍可以繼續對話。");
    } finally {
      setBusy(false);
    }
  }
  function showTeacherNote(bubble, data) {
    if (data.next_steps) current = data.next_steps;
    byId("nextStepChoices")?.remove();
    byId("choiceStatus")?.remove();
    const panel = node("section", "", "inline-support-result");
    panel.id = "nextStepChoices";
    panel.setAttribute("aria-label", "給老師的字條");
    const result = node("div", "");
    result.id = "choiceOutput";
    const message = node("p", "", "choice-note");
    message.id = "choiceStatus";
    message.setAttribute("role", "status");
    panel.append(result, message);
    bubble.appendChild(panel);
    const output = byId("choiceOutput");
    output.replaceChildren(node("p", "這是可以複製的字條，貼上後可以自行修改，目前尚未寄出。"));
    textBox(output, data.draft, "字條");
    if (current?.consent_kind === "summary" && !current.recorded) {
      preview(output, current);
      optionalContact(output, current, steps => showTeacherNote(bubble, {...data, next_steps: steps}));
      output.appendChild(node("p", "你同意把目前這份摘要和這次的完整對話紀錄交給真人工作臺查看嗎？"));
      output.appendChild(button("我同意分享摘要與對話", () => consent(true), true));
      output.appendChild(button("先不要", () => consent(false)));
    }
  }
  function render(steps, forceOpen = false) {
    if (!steps) return;
    current = steps;
    const needsReferral = steps.consent_kind === "referral";
    byId("headerReferralButton").hidden = !needsReferral;
    byId("urgentReferralButton").hidden = !needsReferral;
    byId("headerDraftButton").hidden = needsReferral;
    // 一般陪伴不顯示固定選單；需要時把單一建議放進回覆裡。
    if (!needsReferral || (!forceOpen && !steps.prompt_referral)) {
      byId("nextStepChoices")?.remove();
      return;
    }
    let panel = byId("nextStepChoices");
    if (!panel) {
      panel = node("section", "", "next-step-panel");
      panel.id = "nextStepChoices";
      byId("chatMessages").appendChild(panel);
    }
    panel.className = "next-step-panel";
    panel.setAttribute("aria-label", "是否同意轉介");
    panel.replaceChildren(node("h3", "如果你願意，可以請真人一起幫忙"));
    if (steps.consent_kind === "referral") {
      panel.appendChild(node("p", "為了你的安全，系統會把必要的安全資訊（不含暱稱、學校、聯絡方式與完整對話）送到真人工作臺。同意後，當前摘要、登錄資料，以及這次的完整對話紀錄（你說的話和安啦的回覆，到按下同意為止）也會存入本網站真人工作臺，產生尚未外送的轉介單，工作人員才有辦法聯絡你。之後再聊的內容不會自動分享。尚未接通輔導中心，也不會自動通知學校。"));
      preview(panel, steps);
      optionalContact(panel, steps);
      const label = node("label", "希望被稱呼的名字（選填）");
      label.htmlFor = "referralPreferredName";
      const input = document.createElement("input");
      input.id = "referralPreferredName";
      input.type = "text";
      input.maxLength = 30;
      input.value = steps.preferred_name || "";
      panel.append(label, input);
    }
    if (steps.recorded) panel.appendChild(node("p", "這一版摘要已經記錄你的同意，尚未對外轉介。"));
    const chips = node("div", "", "choice-chips");
    const output = node("div", "");
    output.id = "choiceOutput";
    const handlers = {
      consent: () => consent(true),
      decline: () => consent(false),
      call: () => { byId("urgent119").focus(); consent(false); },
    };
    for (const choice of steps.choices) {
      if (handlers[choice.action]) chips.appendChild(button(choice.label, handlers[choice.action], choice.action === "consent"));
    }
    const message = node("p", "", "choice-note");
    message.id = "choiceStatus";
    message.setAttribute("role", "status");
    panel.append(chips, message, output);
    placeChoices();
  }
  // The student is told, in the conversation itself, exactly what was sent to the workbench without consent.
  function safetyNotice(text) {
    const note = node("div", "", "system-notice");
    note.setAttribute("role", "status");
    note.append(node("b", "🛟 安全通知"), node("p", text));
    const host = byId("chatMessages");
    host.appendChild(note);
    host.scrollTop = host.scrollHeight;
  }
  function suggestInReply(bubble, offer) {
    if (!current || current.consent_kind === "referral" || !offer) return;
    const {kind, label} = offer;
    if (!["resources", "draft"].includes(kind) || typeof label !== "string" || !label) return;
    if (bubble.querySelector(".inline-support-link")) return;
    const action = text => {
      const link = node("button", text, "inline-support-link");
      link.type = "button";
      link.addEventListener("click", () => {
        if (kind === "draft") {
          if (current?.consent_kind === "referral") {
            status("目前先確認安全；是否分享摘要，請使用最新的轉介選項。");
            return;
          }
          teacherNote(bubble);
          return;
        }
        let output = bubble.querySelector(".inline-resource-detail");
        if (!output) {
          output = node("div", "", "inline-resource-detail");
          output.setAttribute("role", "status");
          bubble.appendChild(output);
        }
        output.replaceChildren();
        output.appendChild(node("p", "學校輔導室可以談課業、人際或生活裡卡住的事，也可以先詢問談話時間、保密方式與例外情況。想從校外資源開始也可以。"));
        showResources(output, current?.resources || [], true);
      });
      return link;
    };
    // 邀請已包含在伺服器回覆、前文及朗讀文字中，前端只加上可點選的連結。
    const text = bubble.firstChild;
    if (text?.nodeType !== Node.TEXT_NODE) return;
    const index = text.textContent.lastIndexOf(label);
    if (index < 0) return;
    const rest = text.splitText(index);
    rest.splitText(label.length);
    rest.replaceWith(action(label));
    byId("chatMessages").scrollTop = byId("chatMessages").scrollHeight;
  }
  window.AnlaNextSteps = {
    suggestInReply,
    safetyNotice,
    openReferral() {
      if (current?.consent_kind === "referral") render(current, true);
    },
    update(data) {
      if (data.safety_alert) safetyNotice(data.safety_alert);
      if (data.show_urgent_help) showUrgentHelp();
      if (data.next_steps) render(data.next_steps);
    }
  };
  document.addEventListener("DOMContentLoaded", () => {
    window.addEventListener("resize", adjustUrgentOffset);
    byId("keepTalkingButton").addEventListener("click", continueTalking);
    if (!byId("urgentHelpPanel").hidden) showUrgentHelp();
  });
})();
