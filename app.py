import os
import json
import threading
from flask import Flask, request, jsonify, send_from_directory

from graph_service import query_graph_by_router, test_neo4j
from line_service import (
    reply_line_text,
    push_line_text,
    call_dify,
    is_bot_mentioned
)

app = Flask(__name__)


# ===== 基本 API =====
@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "ok"}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/test/neo4j", methods=["GET"])
def test_db():
    try:
        return jsonify(test_neo4j()), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 200


# ===== 給 Dify HTTP 節點呼叫的 Neo4j 查詢 API =====
@app.route("/graph/query", methods=["POST"])
def graph_query():
    try:
        payload = request.get_json(force=True) or {}

        if isinstance(payload, str):
            payload = json.loads(payload)

        if isinstance(payload, dict) and "text" in payload and isinstance(payload["text"], str):
            try:
                payload = json.loads(payload["text"])
            except Exception:
                pass

        print("DEBUG payload =", payload)

        result = query_graph_by_router(payload)

        print("DEBUG result =", result)
        return jsonify(result), 200

    except Exception as e:
        print("ERROR /graph/query =", str(e))
        return jsonify({
            "graph_result": [{
                "query_type": "system_error",
                "found": False,
                "message": str(e)
            }]
        }), 200


# ===== 背景執行 Dify，完成後 push 給 LINE =====
def run_dify_background(to_id, user_text):
    try:
        print("背景任務開始:", user_text)

        answer = call_dify(user_text)

        if not answer:
            answer = "查詢完成，但沒有取得有效結果。"

        push_line_text(to_id, answer)

    except Exception as e:
        print("背景任務錯誤:", str(e))
        push_line_text(to_id, "系統查詢時發生錯誤，請稍後再試。")


# ===== 靜態檔案 =====
@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory("/content/test/static", filename)


# ===== LINE Webhook =====
@app.route("/line/webhook", methods=["POST"])
def line_webhook():
    body = request.get_json()
    print("DEBUG event =", body)

    events = body.get("events", [])

    for event in events:
        if event.get("type") != "message":
            continue

        message = event.get("message", {})
        if message.get("type") != "text":
            continue

        reply_token = event.get("replyToken")
        user_text = message.get("text", "")

        source = event.get("source", {})
        source_type = source.get("type")

        to_id = (
            source.get("groupId")
            or source.get("roomId")
            or source.get("userId")
        )

        if not reply_token or not to_id:
            print("缺少 reply_token 或 to_id")
            continue

        # 群組或聊天室：只有標註機器人才回應
        if source_type in ["group", "room"]:
            if not is_bot_mentioned(event):
                print("群組訊息未標註 bot，不回應")
                continue

        # 先立刻回覆，避免 LINE timeout
        reply_line_text(reply_token, "正在查詢資料，稍後回覆結果。")

        # 背景執行 Dify
        thread = threading.Thread(
            target=run_dify_background,
            args=(to_id, user_text),
            daemon=True
        )
        thread.start()

    return "OK", 200


# ===== 主程式入口 =====
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
