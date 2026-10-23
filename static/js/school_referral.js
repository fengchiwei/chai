// 性平／霸凌：不管燈號，都提醒可以找學校輔導室，並提供可修改的轉介單。
// 學生願意說學校、而且團隊有核對過那間學校的輔導室信箱時，可以用自己的信箱開好草稿；系統不會代寄。
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

  async function lookup(school) {
    const res = await fetch("/api/school-referral", {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-CSRF-Token": window.ANLA_CSRF_TOKEN},
      body: JSON.stringify(school === undefined ? {} : {school}),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "暫時查不到，請稍後再試。");
    return data.school_referral;
  }

  function schoolPart(card, data, area) {
    const box = el("div", "", "school-referral-school");
    if (data.school) {
      const s = data.school;
      box.appendChild(el("p", `已找到「${s.name}」${s.office}的信箱：${s.email}${s.phone ? `，電話 ${s.phone}` : ""}。`));
      const send = el("a", "✉️ 用我自己的信箱開好草稿", "choice-chip");
      send.href = mailto(s.email, area.value);
      area.addEventListener("input", () => { send.href = mailto(s.email, area.value); });
      box.appendChild(send);
      const src = el("a", "資料來源（學校官網）");
      src.href = s.source_url;
      src.target = "_blank";
      src.rel = "noopener noreferrer";
      box.appendChild(el("p", "按下去只會打開你的郵件程式，信要不要寄出由你決定；系統不會幫你寄。", "school-referral-hint"));
      box.lastChild.append(" ", src);
    } else {
      if (data.school_asked) {
        box.appendChild(el("p", "目前還沒有這間學校核對過的輔導室信箱。你可以把轉介單印出來或抄下來，直接拿到輔導室，或請導師幫你轉交。"));
      }
      const label = el("label", "願意的話，告訴我你的學校，我幫你找輔導室的信箱（選填，不會存起來，也不會通知學校）：");
      const input = el("input", "", "choice-text");
      input.type = "text";
      input.maxLength = 100;
      input.placeholder = "例如：南投高中";
      label.appendChild(input);
      const find = el("button", "查輔導室信箱", "choice-chip");
      find.type = "button";
      find.addEventListener("click", async () => {
        if (!input.value.trim()) { input.focus(); return; }
        find.disabled = true;
        try {
          const next = await lookup(input.value.trim());
          next.note = area.value === data.note ? next.note : area.value;  // keep the student's own edits
          card.replaceWith(render(next));
        } catch (error) {
          find.disabled = false;
          alert(error.message);
        }
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
    card.appendChild(el("p", "轉介單（可以直接修改，還沒有寄出）：", "school-referral-label"));
    const area = el("textarea", "", "choice-text");
    area.rows = 10;
    area.value = data.note;
    area.setAttribute("aria-label", "給輔導室的轉介單");
    card.appendChild(area);
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
    card.appendChild(copy);
    card.appendChild(schoolPart(card, data, area));
    return card;
  }

  const shownTopics = new Set();  // each topic's card once per page; the header button reopens it

  function show(data) {
    if (!data || !(data.topics || []).some(t => !shownTopics.has(t))) return;
    data.topics.forEach(t => shownTopics.add(t));
    const chat = document.getElementById("chatMessages");
    chat.appendChild(render(data));
    chat.scrollTop = chat.scrollHeight;
  }

  function setAvailable(available) {
    const button = document.getElementById("headerSchoolReferralButton");
    if (button) button.hidden = !available;
  }

  async function open() {
    try {
      const data = await lookup();
      const chat = document.getElementById("chatMessages");
      chat.appendChild(render(data));
      chat.scrollTop = chat.scrollHeight;
    } catch (error) {
      alert(error.message);
    }
  }

  return {show, setAvailable, open};
})();
