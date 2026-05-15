import os
import json

from flask import Flask, request, jsonify, send_from_directory, send_file

from service.graph_service import query_graph_by_router, test_neo4j
from service.graph_image_service import (
    generate_node_graph_image_bytes,
    generate_node_graph_image_bytes_by_id
)
from service.graph_web_service import render_graph_page
from service.line_flow_service import handle_line_webhook


app = Flask(__name__)


# =========================
# Basic Routes
# =========================

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
        print("[ERROR][TEST_NEO4J]", str(e))
        return jsonify({"error": str(e)}), 200


# =========================
# Dify HTTP Tool API
# =========================

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

        print("[GRAPH QUERY][PAYLOAD]", payload)

        result = query_graph_by_router(payload)

        graph_result = result.get("graph_result", [])

        if graph_result:
            first = graph_result[0]
            print("[GRAPH QUERY][RESULT]", {
                "query_type": first.get("query_type"),
                "query_mode": first.get("query_mode"),
                "found": first.get("found"),
                "node": first.get("node"),
                "relation_count": len(first.get("relations", []))
            })
        else:
            print("[GRAPH QUERY][RESULT] empty")

        return jsonify(result), 200

    except Exception as e:
        print("[ERROR][/graph/query]", str(e))

        return jsonify({
            "graph_result": [{
                "query_type": "system_error",
                "found": False,
                "message": str(e)
            }]
        }), 200


# =========================
# Static Files
# =========================

@app.route("/static/<path:filename>")
def static_files(filename):
    static_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "static"
    )
    return send_from_directory(static_dir, filename)


# =========================
# Graph Image Routes
# =========================

@app.route("/graph/image", methods=["GET"])
def graph_image():
    target = request.args.get("target", "").strip()
    node_id = request.args.get("node_id", "").strip()

    if node_id:
        image_io = generate_node_graph_image_bytes_by_id(node_id)
        filename = "node_graph.png"

    elif target:
        image_io = generate_node_graph_image_bytes(target)
        filename = f"{target}_graph.png"

    else:
        return "missing target or node_id", 400

    if not image_io:
        return "image not found", 404

    return send_file(
        image_io,
        mimetype="image/png",
        as_attachment=False,
        download_name=filename
    )


@app.route("/graph", methods=["GET"])
def graph_page():
    return render_graph_page()


# =========================
# LINE Webhook
# =========================

@app.route("/line/webhook", methods=["POST"])
def line_webhook():
    return handle_line_webhook(request)


# =========================
# Main
# =========================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
