import requests

from config import DIFY_API_KEY, DIFY_BASE_URL


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

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=180
    )

    print("[DIFY][STATUS]", response.status_code)
    print("[DIFY][BODY]", response.text[:500])

    response.raise_for_status()

    data = response.json()

    return data.get("answer") or data.get("message") or str(data)
