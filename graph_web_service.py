import urllib.parse
from flask import request, render_template_string

from config import PUBLIC_BASE_URL, NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD


def is_graph_request(text):
    if not text:
        return False

    keywords = [
        "圖譜",
        "關係圖",
        "知識圖譜",
        "關聯圖",
        "畫圖",
        "做圖",
        "graph",
        "visualize"
    ]

    return any(k.lower() in text.lower() for k in keywords)


def extract_graph_target(text):
    if not text:
        return ""

    remove_words = [
        "請幫我",
        "幫我",
        "請",
        "畫出",
        "畫",
        "生成",
        "顯示",
        "查詢",
        "看",
        "的圖譜",
        "圖譜",
        "的關係圖",
        "關係圖",
        "的知識圖譜",
        "知識圖譜",
        "關聯圖",
        "做圖",
        "畫圖",
        "graph",
        "visualize"
    ]

    target = text.strip()

    for w in remove_words:
        target = target.replace(w, "")

    return target.strip()


def generate_cypher_query(search_target):
    search_target = (search_target or "").strip()

    if not search_target:
        return """
        MATCH (n)-[r]->(m)
        RETURN n, r, m
        LIMIT 100
        """, "全量概覽"

    # 注意：這裡不要用 f-string 直接塞進 Cypher 的字串內做正式產品
    # 目前是為了快速整合你的專題版本
    safe_target = search_target.replace("'", "\\'")

    query = f"""
    MATCH (n)
    WHERE any(lbl IN labels(n) WHERE toLower(lbl) = toLower('{safe_target}'))
       OR toLower(coalesce(n.name, n.title, n.issue_id, '')) CONTAINS toLower('{safe_target}')
    MATCH (n)-[r]-(m)
    RETURN n, r, m
    LIMIT 100
    """

    return query, f"{search_target} 的圖譜"


def build_graph_url(user_text):
    target = extract_graph_target(user_text)
    cypher, label = generate_cypher_query(target)
    encoded_q = urllib.parse.quote(cypher)
    url = f"{PUBLIC_BASE_URL}/graph?q={encoded_q}"
    return url, label


GRAPH_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Neo4j Knowledge Graph</title>
    <script src="https://unpkg.com/neovis.js@1.5.0/dist/neovis.js"></script>
    <style>
        body, html {
            margin: 0;
            padding: 0;
            background-color: #1a1a1a;
            color: white;
            overflow: hidden;
            font-family: Arial, sans-serif;
        }

        #viz {
            width: 100vw;
            height: 100vh;
        }

        #info {
            position: absolute;
            top: 10px;
            left: 10px;
            background: rgba(0,0,0,0.85);
            padding: 12px;
            z-index: 10;
            border-radius: 6px;
            border: 1px solid #444;
            font-size: 14px;
        }
    </style>
</head>
<body onload="draw()">
    <div id="info">狀態：正在載入圖譜...</div>
    <div id="viz"></div>

    <script>
        function draw() {
            const urlParams = new URLSearchParams(window.location.search);
            const query = urlParams.get("q");
            const finalCypher = query
                ? decodeURIComponent(query)
                : "MATCH (n)-[r]->(m) RETURN n, r, m LIMIT 100";

            const config = {
                container_id: "viz",
                server_url: "{{ neo4j_uri }}",
                server_user: "{{ neo4j_user }}",
                server_password: "{{ neo4j_password }}",
                initial_cypher: finalCypher,

                labels: {
                    "Project": { "caption": "name", "color": "#FFD700" },
                    "Department": { "caption": "name", "color": "#67B7DC" },
                    "Lesson_Learned": { "caption": "title", "color": "#99CC33" },
                    "Certification": { "caption": "name", "color": "#A9A9A9" },
                    "Component": { "caption": "name", "color": "#FF9933" },
                    "Material": { "caption": "name", "color": "#CC99FF" },
                    "Partner": { "caption": "name", "color": "#FF6666" },
                    "Process": { "caption": "name", "color": "#00CCCC" }
                },

                relationships: {
                    "AFFECTS_COMPONENT": { "caption": false },
                    "AFFECTS_SPECIFIC_PART": { "caption": false },
                    "COWORK_ON_TEST_PLAN": { "caption": false },
                    "FINAL_APPROVAL_BY": { "caption": false },
                    "HAS_CERTIFICATION": { "caption": false },
                    "HAS_LESSON": { "caption": false },
                    "HAS_PROCESS": { "caption": false },
                    "INCLUDES": { "caption": false },
                    "MUST_ALIGN_TEST_WITH": { "caption": false },
                    "MUST_DISCUSS_WITH": { "caption": false },
                    "MUST_INVITE_FOR_EVALUATION": { "caption": false },
                    "PROCESS_CHANGED_FROM": { "caption": false },
                    "PROCESS_CHANGED_TO": { "caption": false },
                    "REQUIRES_BEND_TEST_REVIEW": { "caption": false },
                    "REQUIRES_CHAMBER_TEST_BY": { "caption": false },
                    "REQUIRES_DESIGN_CONFIRMATION": { "caption": false },
                    "REQUIRES_EVALUATION_FROM": { "caption": false },
                    "REQUIRES_HW_ADC_SIMULATION_BY": { "caption": false },
                    "REQUIRES_SPEC_ALIGNMENT": { "caption": false },
                    "SUPPLIES": { "caption": false },
                    "USES_MATERIAL": { "caption": false },
                    "USES_SPECIFIC_PART": { "caption": false }
                },

                visConfig: {
                    nodes: {
                        shape: "dot",
                        size: 18,
                        font: {
                            color: "#ffffff",
                            size: 16,
                            strokeWidth: 3,
                            strokeColor: "#000000"
                        }
                    },
                    edges: {
                        arrows: {
                            to: { enabled: true }
                        },
                        font: {
                            size: 10,
                            color: "#ffffff",
                            align: "top"
                        },
                        smooth: {
                            enabled: true,
                            type: "dynamic",
                            roundness: 0.5
                        }
                    },
                    physics: {
                        solver: "forceAtlas2Based",
                        forceAtlas2Based: {
                            gravitationalConstant: -250,
                            springLength: 200,
                            avoidOverlap: 1
                        },
                        stabilization: {
                            enabled: true,
                            iterations: 500
                        }
                    }
                },

                arrows: true
            };

            try {
                const viz = new NeoVis.default(config);
                viz.render();

                document.getElementById("info").innerHTML =
                    "圖譜載入中，請稍候...";

                setTimeout(() => {
                    document.getElementById("info").innerHTML =
                        "圖譜已生成，可拖曳節點查看關係。";
                }, 2500);

            } catch (e) {
                document.getElementById("info").innerText =
                    "圖譜渲染失敗：" + e.message;
                console.error(e);
            }
        }
    </script>
</body>
</html>
"""


def render_graph_page():
    return render_template_string(
        GRAPH_HTML,
        neo4j_uri=NEO4J_URI,
        neo4j_user=NEO4J_USER,
        neo4j_password=NEO4J_PASSWORD
    )
