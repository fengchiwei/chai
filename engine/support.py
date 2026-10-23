"""一般對話的資源邀請時機；不判定風險、不建立案件，也不對外聯絡。"""
import re


def choose_support_offer(message: str, level: str, previous: dict | None = None, dialogue_state=None):
    state = dict(previous or {})
    if level not in ("green", "yellow"):
        return None, state
    state["turns"] = state.get("turns", 0) + 1
    decision = dialogue_state or {}
    compact = re.sub(r"[^\w\u3400-\u9fff]", "", message).lower()
    declined = bool(re.search(
        r"(?:不要|不想|不需要|不用|不願意)[^，。！？,;；\n]{0,12}(?:資源|求助|找人|找老師|輔導|專線|字條|建議)"
        r"|(?:資源|專線|字條|建議)(?:先|暫時)?(?:不要|不用)"
        r"|只想(?:先)?聊|先(?:繼續)?聊就好|只要.{0,4}(?:聽|陪)", message))
    declined = declined or compact in ("先不要", "暫時不要", "先不用", "不用了")
    if declined:
        # Recorded before the boundary check below: 「我只想有人陪，不要給我建議」 is itself a boundary turn.
        state["declined"] = True
        return None, state
    if (decision.get("safety_check_required") or decision.get("emotion_intensity") == "high"
            or decision.get("current_goal") in ("respect_boundary", "establish_safety", "configure_role", "clarify_identity")
            or decision.get("role_changed")):
        return None, state
    wants_note = bool(re.search(r"(?:幫|想|請|可以).{0,8}(?:寫|字條)|字條.{0,8}(?:怎麼|如何|寫)", message)
                      and re.search(r"字條|老師|輔導", message))
    wants_resources = bool(re.search(
        r"(?:想|要|請|可以|能不能|給我|有哪些|有什麼|哪裡|怎麼|如何).{0,18}(?:資源|專線|電話|求助|輔導室|輔諮|心衛)"
        r"|(?:資源|專線|電話|輔導室).{0,12}(?:在哪|有哪些|怎麼|如何|能做|可以做|能幫|可以幫)"
        r"|可以找誰|找誰(?:幫忙|聊)", message))
    state["has_concern"] = state.get("has_concern", False) or bool(re.search(
        r"心情不好|低落|難過|不開心|心慌|緊張|壓力|煩|擔心|怕|不敢|睡不著|睡不好|很累|困擾|委屈|孤單|想哭|告白被打槍|被拒絕|失戀", message))
    brief = compact in ("嗯", "嗯嗯", "好", "好喔", "好啊", "好吧", "喔", "哦", "不是", "不對", "沒有", "謝謝", "ok") or compact.isdigit()
    if wants_note or wants_resources:
        kind = "draft" if wants_note else "resources"
        proactive = False
    elif (state["turns"] >= 4 and state.get("has_concern") and not brief
          and not state.get("offered") and not state.get("declined")
          and (dialogue_state is None or decision.get("current_goal") == "integrate")
          and not decision.get("advice_request")
          and not decision.get("safety_denied")
          and not re.search(r"活著|人生|生命|傷害|自殺|自殘|想死|不想.{0,6}(?:活|醒)", message)):
        kind, proactive = "resources", True
    else:
        return None, state
    state["offered"] = True
    if kind == "draft":
        label = "寫一張給老師的小字條"
        # The student asked for the note: the link makes it (2026-10-23 live test: the model wrote one in the reply
        # and the offer then proposed writing another).
        text = f"點「{label}」就會出現一張可以修改的字條，要不要傳由你決定。"
    else:
        label = "附近的輔導資源"
        text = (f"想找真人聊時，學校輔導室與{label}可以點開看看，要不要聯絡由你決定。"
                if proactive else f"你要的{label}放在這裡，要不要聯絡由你決定。")
    return {"kind": kind, "proactive": proactive, "label": label, "text": text}, state


def support_turn_instruction(offer: dict | None) -> str:
    safety = ("以下邀請節奏僅適用一般困擾；若訊息透露自傷或立即危險，安全優先，"
              "直接關心安全並提供適當急救資訊，不受輪數或先前拒絕資源的限制。")
    if offer and offer.get("kind") == "draft":
        return (safety + "【本輪字條】學生想要一張給老師的字條。網站會在你的文字末尾接上可點選的連結，點了就會產生字條。"
                "你不要自己在回覆裡寫字條內容、範本或格式，也不要引用資料來源；用 1–2 個短句接住學生想找老師談的這一步就好。")
    if offer:
        return (safety + "【本輪資源邀請】這一輪的文字末尾會由網站接上一句可點選的求助邀請。"
                "你的部分用 1–3 個短句、120 字以內接住學生，依本輪決策最多一問或完全不問；"
                "不要再加另一個方法或重複資源邀請，也不要聲稱已轉介。")
    return (safety + "【本輪陪伴節奏】這一輪先承接學生說的事，不主動加上找老師、轉介、專線或資源建議。"
            "學生談到對求助的擔心時可以回應那份擔心，不急著勸他行動。")


def include_support_offer(response: dict, offer: dict | None) -> dict:
    if not offer:
        return response
    reply = response["reply"].rstrip()
    separator = "\n" if reply.count("\n\n") >= 2 else "\n\n"
    return {**response, "reply": reply + separator + offer["text"]}
