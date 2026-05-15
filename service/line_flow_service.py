import re
import threading

from service.graph_service import (
    find_exact_duplicate_nodes,
    query_node_by_element_id
)

from service.graph_web_service import (
    is_graph_request,
    extract_graph_target
)

from service.graph_image_service import (
    build_node_graph_image_url,
    build_node_graph_image_url_by_id,
    build_relationship_graph_url
)

from service.line_service import (
    reply_line_text,
    reply_line_text_and_image,
    push_line_text,
    push_line_text_and_image,
    should_reply,
    remove_mention,
    clean_line_text
)

from service.dify_service import call_dify


PENDING_SELECTIONS = {}


# =========================
# Selection Key
# =========================

def build_selection_key(to_id, source):
    user_id = source.get("userId", "unknown-user")
    return f"{to_id}:{user_id}"


# =========================
# Dify Candidate Extraction
# =========================

def extract_candidates_from_answer(answer):
    candidates = []

    if not answer:
        return candidates

    for line in answer.splitlines():
        line = line.strip()

        # 格式：名稱：BHC212（類型：Project）
        if "名稱：" in line:
            try:
                name_part = line.split("名稱：", 1)[1]
                name = name_part.split("（", 1)[0].strip()

                if name:
                    candidates.append(name)
            except Exception:
                pass

        # 格式：1. BHC212 (Project)
        match = re.match(r"^\s*\d+\.\s*([A-Za-z0-9_\-:]+)\s*\(", line)

        if match:
            name = match.group(1).strip()

            if name:
                candidates.append(name)

    # 去除重複，保留順序
    unique_candidates = []

    for c in candidates:
        if c not in unique_candidates:
            unique_candidates.append(c)

    return unique_candidates

def extract_relationship_from_answer(answer):
    """
    從 Dify 回答中抓出：
    BHC212 --[包含]--> ACP212
    """

    if not answer:
        return None

    pattern = r"([A-Za-z0-9_\-]+)\s*--\[(.*?)\]-->\s*([A-Za-z0-9_\-]+)"
    match = re.search(pattern, answer)

    if not match:
        return None

    source = match.group(1).strip()
    relation = match.group(2).strip()
    target = match.group(3).strip()

    if not source or not relation or not target:
        return None

    return {
        "source": source,
        "relation": relation,
        "target": target
    }

def format_duplicate_candidates_message(user_text, candidates):
    lines = []

    lines.append(f"目前找到多個名稱為「{user_text}」的節點，請選擇要查詢的項目：")
    lines.append("")

    for i, c in enumerate(candidates, start=1):
        name = c.get("name", "")
        label = c.get("label", "Unknown")
        props = c.get("props", {}) or {}

        description_parts = []

        for key in ["title", "issue", "root_cause", "department", "type"]:
            if key in props and props[key]:
                description_parts.append(f"{key}: {props[key]}")

        description = ""

        if description_parts:
            description = "｜" + "；".join(description_parts[:2])

        lines.append(f"{i}. {name}（{label}）{description}")

    lines.append("")
    lines.append("請直接輸入編號，例如：1 或 2。若輸入錯誤，系統會取消本次選擇。")

    return "\n".join(lines)


# =========================
# Query Type Judgment
# =========================

def is_simple_node_query(text):
    if not text:
        return False

    text = text.strip()

    if len(text) > 40:
        return False

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

    return True


# =========================
# Background Dify Flow
# =========================

def run_dify_background(to_id, user_text, user_id="line-user", selection_key=None):
    try:
        print("[BACKGROUND][START]", user_text)

        # 0. 單純節點名稱：先檢查 Neo4j 是否有同名節點
        if is_simple_node_query(user_text):
            duplicate_candidates = find_exact_duplicate_nodes(user_text, limit=10)

            if len(duplicate_candidates) > 1 and selection_key:
                PENDING_SELECTIONS[selection_key] = {
                    "mode": "node_id",
                    "candidates": duplicate_candidates,
                    "original_query": user_text,
                    "user_id": user_id
                }

                message = format_duplicate_candidates_message(
                    user_text,
                    duplicate_candidates
                )

                push_line_text(to_id, message)
                return

        # 1. 使用者明確要求圖譜
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

        # 2. 一般查詢：呼叫 Dify
        answer = call_dify(user_text, user_id=user_id)

        if not answer:
            answer = "查詢完成，但沒有取得有效結果。"
        
        relationship_info = extract_relationship_from_answer(answer)

        if relationship_info:
            image_url = build_relationship_graph_url(
                relationship_info["source"],
                relationship_info["relation"],
                relationship_info["target"]
            )
        
            if image_url:
                push_line_text_and_image(
                    to_id,
                    answer,
                    image_url=image_url
                )
                return
        
        # 3. 從 Dify 回答中抓候選節點
        candidates = extract_candidates_from_answer(answer)

        print("[CANDIDATES][EXTRACTED]", candidates)

        if len(candidates) >= 2 and selection_key:
            PENDING_SELECTIONS[selection_key] = {
                "mode": "name",
                "candidates": candidates,
                "original_query": user_text,
                "user_id": user_id
            }

            push_line_text(
                to_id,
                answer + "\n\n請直接輸入編號，例如：1 或 2。若輸入錯誤，系統會取消本次選擇。"
            )
            return

        # 4. 單節點查詢：如果查得到，補圖
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

            if image_url:
                push_line_text_and_image(
                    to_id,
                    answer,
                    image_url=image_url
                )
                return

        # 5. 其他問題只回文字
        push_line_text(to_id, answer)

    except Exception as e:
        print("[ERROR][BACKGROUND]", str(e))
        push_line_text(to_id, "系統查詢時發生錯誤，請稍後再試。")


# =========================
# Candidate Selection Flow
# =========================

def handle_candidate_selection(reply_token, cleaned_text, selection_key, to_id):
    try:
        selection = int(cleaned_text)

        pending = PENDING_SELECTIONS.get(selection_key)

        if not pending:
            reply_line_text(reply_token, "目前沒有待選擇的查詢項目，請重新輸入問題。")
            return

        candidates = pending.get("candidates", [])
        mode = pending.get("mode", "name")
        user_id = pending.get("user_id", "line-user")

        # 清除暫存，避免下一次誤判
        del PENDING_SELECTIONS[selection_key]

        if not (1 <= selection <= len(candidates)):
            reply_line_text(
                reply_token,
                f"編號 {selection} 不在候選範圍內，本次選擇已取消。請重新查詢。"
            )
            return

        selected = candidates[selection - 1]

        # 情況 A：同名節點，用 node_id 直接查 Neo4j
        if mode == "node_id":
            selected_node_id = selected.get("node_id")
            selected_name = selected.get("name", "")

            result = query_node_by_element_id(selected_node_id)

            if not result.get("found"):
                reply_line_text(reply_token, "查無相關資料")
                return

            lines = []

            lines.append(
                f"已選擇：{selected_name}（{result.get('label', 'Unknown')}）"
            )
            lines.append("")

            props = result.get("properties", {})

            if props:
                lines.append("節點屬性：")

                for k, v in props.items():
                    if v is not None and str(v).strip():
                        lines.append(f"- {k}: {v}")

                lines.append("")

            relations = result.get("relations", [])

            if relations:
                lines.append("相關關係：")

                for r in relations[:10]:
                    lines.append(
                        f"- {r.get('relation')} → "
                        f"{r.get('target_name')}"
                        f"（{r.get('target_label')}）"
                    )

            image_url = build_node_graph_image_url_by_id(selected_node_id)

            if image_url:
                reply_line_text_and_image(
                    reply_token,
                    "\n".join(lines),
                    image_url=image_url
                )
            else:
                reply_line_text(reply_token, "\n".join(lines))

            return

        # 情況 B：Dify 回答中列出的候選名稱
        selected_node = selected

        reply_line_text(
            reply_token,
            f"已選擇：{selected_node}\n系統正在查詢，請稍候。"
        )

        # 關鍵修正：
        # 使用者選擇 1/2 後，要重新啟動查詢流程。
        # selection_key 傳 None，避免再次進入候選選擇循環。
        thread = threading.Thread(
            target=run_dify_background,
            args=(
                to_id,
                selected_node,
                user_id,
                None
            ),
            daemon=True
        )

        thread.start()
        return

    except Exception as e:
        print("[ERROR][CANDIDATE_SELECTION]", str(e))
        reply_line_text(reply_token, "處理選擇時發生錯誤，請重新查詢。")


# =========================
# LINE Webhook Main Flow
# =========================

def handle_line_webhook(request):
    body = request.get_json()

    print("[LINE][EVENT]", body)

    events = body.get("events", [])

    for event in events:
        if event.get("type") != "message":
            continue

        message = event.get("message", {})

        if message.get("type") != "text":
            continue

        reply_token = event.get("replyToken")
        source = event.get("source", {})

        to_id = (
            source.get("groupId")
            or source.get("roomId")
            or source.get("userId")
        )

        if not reply_token or not to_id:
            print("[LINE][SKIP] missing reply_token or to_id")
            continue

        # 群組中需要被標註才回答
        ok, text = should_reply(event)

        if not ok:
            print("[LINE][SKIP] group message without mention")
            continue

        cleaned_text = clean_line_text(
            remove_mention(text, event)
        )

        print("[LINE][CLEANED_TEXT]", cleaned_text)

        if not cleaned_text:
            reply_line_text(reply_token, "請輸入要查詢的內容。")
            continue

        selection_key = build_selection_key(to_id, source)

        # 如果使用者正在選候選項目
        if cleaned_text.isdigit() and selection_key in PENDING_SELECTIONS:
            handle_candidate_selection(
                reply_token,
                cleaned_text,
                selection_key,
                to_id
            )
            continue

        # 一般查詢：先回覆，避免 LINE webhook timeout
        reply_line_text(reply_token, "收到，正在查詢中。")

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
