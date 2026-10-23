// 性平／霸凌：不管燈號，都提醒可以找學校輔導室，並提供可修改的轉介單。
// 學生願意說學校時，從教育部學校名錄找出學校總機與網站；團隊核對過輔導室信箱的學校，可以用自己的信箱開好草稿（系統不會代寄）。
window.AnlaSchoolReferral = (() => {
  function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text) node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function mailto(email, note) {
    return `mailto:${email}?subject=${encodeURIComponent("想跟輔導室約時間談談")}&body=${encodeURIComponent(note)}`;
  }

  async function lookup(body) {
    const res = await fetch("/api/school-referral", {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-CSRF-Token": window.ANLA_CSRF_TOKEN},
      body: JSON.stringify(body || {}),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "暫時查不到，請稍後再試。");
    return data.school_referral;
  }

  function link(text, href) {
    const a = el("a", text);
    a.href = href;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    return a;
  }

  function schoolPart(card, data, area) {
    const box = el("div", "", "school-referral-school");
    const choices = data.choices || [];
    async function replace(body, button) {
      if (button) button.disabled = true;
      try {
        const next = await lookup(body);
        if (area.value !== data.note) next.note = area.value;  // keep the student's own edits
        card.replaceWith(render(next));
      } catch (error) {
        if (button) button.disabled = false;
        alert(error.message);
      }
    }
    if (data.school) {
      const s = data.school;
      box.appendChild(el("p", `${s.name}（${s.county}）`, "school-referral-name"));
      if (s.email) {
        box.appendChild(el("p", `${s.office}信箱：${s.email}${s.office_phone ? `，電話 ${s.office_phone}` : ""}`));
        const send = el("a", "✉️ 用我自己的信箱開好草稿", "choice-chip");
        send.href = mailto(s.email, area.value);
        area.addEventListener("input", () => { send.href = mailto(s.email, area.value); });
        box.appendChild(send);
        const hint = el("p", "按下去只會打開你的郵件程式，信要不要寄出由你決定；系統不會幫你寄。", "school-referral-hint");
        if (/^https:\/\//.test(s.email_source_url || "")) hint.append(" ", link("信箱來源（學校官網）", s.email_source_url));
        box.appendChild(hint);
      } else {
        box.appendChild(el("p", "這間學校的輔導室信箱我們還沒有核對過。可以打學校總機請他們轉輔導室，或把轉介單印出來、抄下來直接拿去，也可以請導師幫你轉交。"));
      }
      const line = el("p");
      if (s.phone) {
        const tel = el("a", `📞 學校總機 ${s.phone}`);
        tel.href = s.phone_href;
        line.append(tel, "（接通後說要找輔導室）");
      }
      if (/^https?:\/\//.test(s.website || "")) line.append(" ", link("🌐 學校網站", s.website));
      box.appendChild(line);
      const source = el("p", "總機與網站來自 ", "school-referral-hint");
      source.appendChild(link(s.source, s.source_url));
      box.appendChild(source);
    } else if (data.school_asked && !choices.length) {
      box.appendChild(el("p", "找不到這間學校，可以換個寫法再試一次（例如「南投高中」「埔里國中」）。也可以把轉介單印出來或抄下來，直接拿到輔導室，或請導師幫你轉交。"));
    }
    if (choices.length) {
      box.appendChild(el("p", data.school ? "不是這間？" : "有幾間學校名字很像，是哪一間？"));
      choices.forEach(c => {
        const pick = el("button", `${c.name}（${c.county}）`, "choice-chip");
        pick.type = "button";
        pick.addEventListener("click", () => replace({code: c.code}, pick));
        box.appendChild(pick);
      });
    }
    {
      const label = el("label", data.school ? "查別的學校：" :
        "願意的話，告訴我你的學校，我幫你找學校和輔導室的聯絡方式（選填，不會存起來，也不會通知學校）：");
      const input = el("input", "", "choice-text");
      input.type = "text";
      input.maxLength = 100;
      input.placeholder = "例如：南投高中";
      label.appendChild(input);
      const find = el("button", "查學校聯絡方式", "choice-chip");
      find.type = "button";
      find.addEventListener("click", () => {
        if (!input.value.trim()) { input.focus(); return; }
        replace({school: input.value.trim()}, find);
      });
      box.append(label, find);
    }
    return box;
  }

  function render(data) {
    const card = el("section", "", "school-referral-card");
    card.setAttribute("aria-label", "學校輔導室與轉介單");
    card.appendChild(el("h3", "🏫 可以找學校輔導室談談"));
    card.appendChild(el("p", data.message));
    const list = el("ul");
    (data.notices || []).forEach(n => {
      const item = el("li", n.text + " ");
      if (/^https:\/\//.test(n.source?.url || "")) {
        const link = el("a", `${n.source.publisher}〈${n.source.title}〉`);
        link.href = n.source.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        item.appendChild(link);
      }
      list.appendChild(item);
    });
    card.appendChild(list);
    // Folded by default so the card does not push the reply out of the chat window (2026-10-23 live test).
    const notePart = el("details", "", "school-referral-more");
    notePart.open = Boolean(data.school_asked);
    notePart.appendChild(el("summary", "📝 看轉介單（可以修改，還沒有寄出）"));
    const area = el("textarea", "", "choice-text");
    area.rows = 10;
    area.value = data.note;
    area.setAttribute("aria-label", "給輔導室的轉介單");
    notePart.appendChild(area);
    const copy = el("button", "複製轉介單", "choice-chip");
    copy.type = "button";
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(area.value);
        copy.textContent = "已複製";
      } catch (_) {
        area.focus();
        area.select();
      }
    });
    notePart.appendChild(copy);
    card.appendChild(notePart);
    const schoolBox = el("details", "", "school-referral-more");
    schoolBox.open = Boolean(data.school_asked);
    schoolBox.appendChild(el("summary", data.school ? `🏫 ${data.school.name}的聯絡方式` : "🏫 查我的學校聯絡方式"));
    schoolBox.appendChild(schoolPart(card, data, area));
    card.appendChild(schoolBox);
    return card;
  }

  const shownTopics = new Set();  // each topic's card once per page; the header button reopens it

  function show(data) {
    if (!data || !(data.topics || []).some(t => !shownTopics.has(t))) return;
    data.topics.forEach(t => shownTopics.add(t));
    document.getElementById("chatMessages").appendChild(render(data));
  }

  function setAvailable(available) {
    const button = document.getElementById("headerSchoolReferralButton");
    if (button) button.hidden = !available;
  }

  async function open() {
    try {
      const data = await lookup({});
      const chat = document.getElementById("chatMessages");
      chat.appendChild(render(data));
      chat.scrollTop = chat.scrollHeight;
    } catch (error) {
      alert(error.message);
    }
  }

  return {show, setAvailable, open};
})();
