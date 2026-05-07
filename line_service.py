import re
import requests

from config import LINE_CHANNEL_ACCESS_TOKEN, DIFY_API_KEY, DIFY_BASE_URL
from graph_image_service import generate_relation_graph_image
from graph_service import query_graph_by_router


from config import PUBLIC_BASE_URL

def push_line_text(to_id, text):
    url = "https://api.line.me/v2/bot/message/push"

    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "to": to_id,
        "messages": [
            {
                "type": "text",
                "text": text[:5000]
            }
        ]
    }

    r = requests.post(url, headers=headers, json=payload, timeout=15)
    print("LINE push status:", r.status_code, r.text)
    return r
def reply_line_text(reply_token, text):
    url = "https://api.line.me/v2/bot/message/reply"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }

    body = {
        "replyToken": reply_token,
        "messages": [
            {
                "type": "text",
                "text": text[:5000]
            }
        ]
    }

    r = requests.post(url, headers=headers, json=body)
    print("LINE reply:", r.status_code, r.text)
    return r

def reply_line_text_and_image(reply_token, text, image_url=None):
    url = "https://api.line.me/v2/bot/message/reply"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }

    messages = [{"type": "text", "text": text}]

    if image_url:
        messages.append({
            "type": "image",
            "originalContentUrl": image_url,
            "previewImageUrl": image_url
        })

    body = {
        "replyToken": reply_token,
        "messages": messages
    }

    r = requests.post(url, headers=headers, json=body)
    print("LINE reply:", r.status_code, r.text)
    return r


def call_dify(user_text, user_id="line-user"):
    url = f"{DIFY_BASE_URL}/chat-messages"

    headers = {
        "Authorization": f"Bearer {DIFY_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "inputs": {},
        "query": user_text,
        "response_mode": "blocking",
        "conversation_id": "",
        "user": user_id
    }

    r = requests.post(url, headers=headers, json=payload, timeout=180)
    print("Dify status:", r.status_code, r.text[:500])
    r.raise_for_status()

    data = r.json()
    return data.get("answer") or data.get("message") or str(data)


def clean_line_text(text):
    if not text:
        return ""
    return text.strip()


def should_reply(event):
    source = event.get("source", {})
    message = event.get("message", {})
    text = message.get("text", "")

    if source.get("type") == "user":
        return True, text

    mention = message.get("mention", {})
    if mention and mention.get("mentionees"):
        return True, text

    return False, text


def remove_mention(text, event):
    if "mention" not in event["message"]:
        return text

    mention = event["message"]["mention"]
    indices = []

    for m in mention.get("mentionees", []):
        start = m["index"]
        end = start + m["length"]
        indices.append((start, end))

    for start, end in sorted(indices, reverse=True):
        text = text[:start] + text[end:]

    return text.strip()


def try_generate_relation_image(user_text):
    """
    偵測兩節點關係查詢，成功時產生 PNG 圖片並回傳 image_url。
    目前支援：
    - A 跟 B 的關係
    - A 和 B 的關係
    - A 與 B 的關係
    """

    pattern = r"(.+?)(?:跟|和|與)(.+?)(?:的)?關係"
    match = re.search(pattern, user_text)

    if not match:
        return None

    source = match.group(1).strip()
    target = match.group(2).strip()

    if not source or not target:
        return None

    payload = {
        "intent": "relation_query",
        "project": None,
        "component": None,
        "material": None,
        "process": None,
        "certification": None,
        "department": None,
        "partner": None,
        "lesson_keyword": None,
        "source_entity": source,
        "target_entity": target,
        "compare_targets": [],
        "requested_fields": [],
        "limit": 5,
        "user_question": user_text
    }

    result = query_graph_by_router(payload)
    print("DEBUG image graph result =", result)

    graph_result = result.get("graph_result", [])
    if not graph_result:
        return None

    item = graph_result[0]

    if not item.get("found"):
        return None

    source_name = item.get("source")
    target_name = item.get("target")
    relation_type = item.get("relation_type")

    if not source_name or not target_name or not relation_type:
        return None

    filename = generate_relation_graph_image(
        source=source_name,
        target=target_name,
        relation_type=relation_type
    )

    return f"{PUBLIC_BASE_URL}/static/{filename}"


def handle_line_event(event):
    print("DEBUG event =", event)

    if event.get("type") != "message":
        return

    message = event.get("message", {})
    if message.get("type") != "text":
        return

    reply_token = event.get("replyToken")
    user_id = event.get("source", {}).get("userId", "line-user")

    ok, text = should_reply(event)
    if not ok:
        print("DEBUG skipped: no mention in group/room")
        return

    cleaned = clean_line_text(remove_mention(text, event))
    print("DEBUG original text =", text)
    print("DEBUG cleaned text =", cleaned)

    try:
        print("REPLY: sending to Dify")
        answer = call_dify(cleaned, user_id=user_id)

        image_url = try_generate_relation_image(cleaned)

        reply_line_text_and_image(
            reply_token,
            answer,
            image_url=image_url
        )

    except Exception as e:
        print("ERROR while calling Dify/LINE:", str(e))
        reply_line_text_and_image(
            reply_token,
            "發生技術錯誤，無法順利讀取。"
        )
