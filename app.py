import os
import re
import json
import threading
from flask import Flask, request, jsonify, send_from_directory, send_file
from graph_service import query_graph_by_router, test_neo4j
from line_service import (
    reply_line_text,
    push_line_text,
    push_line_text_and_image,
    call_dify,
    should_reply,
    remove_mention,
    clean_line_text
)
from graph_web_service import (
    is_graph_request,
    build_graph_url,
    render_graph_page, 
    extract_graph_target
)
from graph_image_service import (
    generate_node_graph_image,
    generate_node_graph_image_bytes,
    build_node_graph_image_url
)

app = Flask(__name__)
PENDING_SELECTIONS = {}

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
        
def build_selection_key(to_id, source):
    user_id = source.get("userId", "unknown-user")
    return f"{to_id}:{user_id}"
    
def extract_candidates_from_answer(answer):
    candidates = []

    if not answer:
        return candidates

    for line in answer.splitlines():
        line = line.strip()

        # 格式 1：1. 名稱：BHC212（類型：Project）
        if "名稱：" in line:
            try:
                name_part = line.split("名稱：", 1)[1]
                name = name_part.split("（", 1)[0].strip()
                if name:
                    candidates.append(name)
            except Exception:
                pass

        # 格式 2：1. BHC212 (Project)
        match = re.match(r"^\s*\d+\.\s*([A-Za-z0-9_\-:]+)\s*\(", line)
        if match:
            name = match.group(1).strip()
            if name:
                candidates.append(name)

    return candidates
        
def is_simple_node_query(text):
    if not text:
        return False

    text = text.strip()

    # 太長通常不是單節點
    if len(text) > 40:
        return False

    # 有明顯問句或查詢詞，就不要當成單純節點
    query_words = [
        "有哪些",
        "是什麼",
        "介紹",
        "說明",
        "分析",
        "關係",
        "圖譜",
        "關係圖",
        "知識圖譜",
        "製程",
        "材料",
        "認證",
        "部門",
        "lesson",
        "教訓",
        "原始問題",
        "原因"
    ]

    if any(word in text for word in query_words):
        return False

    # 常見節點格式，例如 BHC212、GB31241:2014、MC1254S-PT02
    return True

# ===== 背景執行 Dify，完成後 push 給 LINE =====
def run_dify_background(to_id, user_text, user_id="line-user", selection_key=None):
    try:
        print("背景任務開始:", user_text)

        # ===== 1. 明確要求圖譜：只回圖片 =====
        if is_graph_request(user_text):
            target = extract_graph_target(user_text)

            if not target:
                push_line_text(to_id, "請指定要產生圖譜的節點，例如：BHC212 圖譜")
                return

            image_url = build_node_graph_image_url(target)

            if not image_url:
                push_line_text(to_id, f"找不到 {target} 的圖譜資料。")
                return

            push_line_text_and_image(
                to_id,
                f"已生成 {target} 的關係圖：",
                image_url=image_url
            )
            return

       # ===== 2. 一般查詢：先取得 Dify 文字回答 =====
        answer = call_dify(user_text, user_id=user_id)
        
        if not answer:
            answer = "查詢完成，但沒有取得有效結果。"
        
        # ===== 抓候選節點 =====
        candidates = extract_candidates_from_answer(answer)
        
        print("DEBUG extracted candidates =", candidates)
        
        if len(candidates) >= 2 and selection_key:
            PENDING_SELECTIONS[selection_key] = {
                "candidates": candidates,
                "original_query": user_text,
                "user_id": user_id
            }
        
            print("DEBUG PENDING_SELECTIONS =", PENDING_SELECTIONS)
        
            push_line_text(
                to_id,
                answer + "\n\n請直接輸入編號，例如：1 或 2。若輸入錯誤，系統會取消本次選擇。"
            )
            return

        # ===== 3. 如果是單節點查詢，同時產生圖片 =====
        if is_simple_node_query(user_text):

            not_found_keywords = [
                "查無相關資料",
                "查無資料",
                "找不到",
                "沒有找到",
                "目前查無"
            ]
        
            if any(keyword in answer for keyword in not_found_keywords):
                push_line_text(to_id, answer)
                return
        
            ambiguous_keywords = [
                "多個可能",
                "請確認",
                "請提供完整名稱",
                "候選節點"
            ]
        
            if any(keyword in answer for keyword in ambiguous_keywords):
                push_line_text(to_id, answer)
                return
        
            image_url = build_node_graph_image_url(user_text)
        # ===== 4. 其他問題只回文字 =====
        push_line_text(to_id, answer)

    except Exception as e:
        print("背景任務錯誤:", str(e))
        push_line_text(to_id, "系統查詢時發生錯誤，請稍後再試。")
        
# ===== 靜態檔案 =====
@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "static"),
        filename
    )
@app.route("/graph/image", methods=["GET"])
def graph_image():
    target = request.args.get("target", "").strip()

    if not target:
        return "missing target", 400

    image_io = generate_node_graph_image_bytes(target)

    if not image_io:
        return "image not found", 404

    return send_file(
        image_io,
        mimetype="image/png",
        as_attachment=False,
        download_name=f"{target}_graph.png"
    )

@app.route("/graph", methods=["GET"])
def graph_page():
    return render_graph_page()

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
        ok, text = should_reply(event)

        if not ok:
            print("群組訊息未標註 bot，不回應")
            continue
        
        cleaned_text = clean_line_text(remove_mention(text, event))
        print("DEBUG cleaned_text =", cleaned_text)

        selection_key = build_selection_key(to_id, source)

        if cleaned_text.isdigit() and selection_key in PENDING_SELECTIONS:
            selection = int(cleaned_text)
            pending = PENDING_SELECTIONS.get(selection_key, {})
            candidates = pending.get("candidates", [])
        
            # 不管選對或選錯，只要進入選擇流程，就先清掉暫存
            del PENDING_SELECTIONS[selection_key]
        
            if 1 <= selection <= len(candidates):
                selected_node = candidates[selection - 1]
                cleaned_text = selected_node
                print("DEBUG selected candidate =", selected_node)
        
            else:
                reply_line_text(
                    reply_token,
                    f"編號 {selection} 不在候選範圍內，本次選擇已取消。請重新查詢。"
                )
                continue
        
        thread = threading.Thread(
            target=run_dify_background,
            args=(
                to_id,
                cleaned_text,
                source.get("userId", "line-user"),
                selection_key
            ),
            daemon=True
        )
        thread.start()

    return "OK", 200


# ===== 主程式入口 =====
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
