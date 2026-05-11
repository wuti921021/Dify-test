import urllib.parse
from flask import request, render_template_string

from config import PUBLIC_BASE_URL, NEO4J_GRAPH_URI, NEO4J_USER, NEO4J_PASSWORD


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

    for word in remove_words:
        target = target.replace(word, "")

    return target.strip()


def generate_cypher_query(search_target):
    search_target = (search_target or "").strip()

    # ===== 完整圖譜模式 =====
    if search_target in ["全圖", "全部", "整張圖", "完整圖譜", "所有圖譜"]:
        query = """
        MATCH (n)-[r]->(m)
        RETURN n, r, m
        LIMIT 300
        """
        return query, "完整圖譜"

    # ===== 沒有輸入目標：概覽模式 =====
    if not search_target:
        query = """
        MATCH (n)-[r]->(m)
        RETURN n, r, m
        LIMIT 100
        """
        return query, "圖譜概覽"

    safe_target = search_target.replace("'", "\\'")

    # ===== 單一中心節點一階關係 =====
    query = f"""
    MATCH (n)
    WHERE any(lbl IN labels(n) WHERE toLower(lbl) = toLower('{safe_target}'))
       OR toLower(coalesce(n.name, n.title, n.issue_id, '')) CONTAINS toLower('{safe_target}')
    WITH n
    LIMIT 1
    MATCH (n)-[r]-(m)
    RETURN n, r, m
    LIMIT 80
    """

    return query, f"{search_target} 的圖譜"


def build_graph_url(user_text):
    target = extract_graph_target(user_text)
    cypher, label = generate_cypher_query(target)

    encoded_q = urllib.parse.quote(cypher)
    encoded_target = urllib.parse.quote(target)

    url = f"{PUBLIC_BASE_URL}/graph?q={encoded_q}&target={encoded_target}"

    return url, label


GRAPH_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Neo4j Dynamic Graph</title>

    <script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
    <script src="https://unpkg.com/neo4j-driver"></script>

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
            line-height: 1.5;
        }
    </style>
</head>

<body onload="draw()">
    <div id="info">狀態：正在準備查詢數據...</div>
    <div id="viz"></div>

    <script>
        function shortenText(text, maxLen = 18) {
            if (!text) return "";
            text = String(text);
            if (text.length <= maxLen) return text;
            return text.substring(0, maxLen) + "...";
        }

        function getNodeCaption(node) {
            const p = node.properties || {};
            return (
                p.name ||
                p.title ||
                p.issue ||
                p.issue_id ||
                node.labels?.[0] ||
                "Unknown"
            );
        }

        async function draw() {
            const info = document.getElementById("info");

            const urlParams = new URLSearchParams(window.location.search);
            const cypherFromUrl = urlParams.get("q");
            const targetFromUrl = urlParams.get("target") || "";

            const cypher = cypherFromUrl
                ? decodeURIComponent(cypherFromUrl)
                : "MATCH (n)-[r]->(m) RETURN n, r, m LIMIT 100";

            console.log("執行查詢:", cypher);
            console.log("中心目標:", targetFromUrl);

            const driver = neo4j.driver(
                "{{ neo4j_uri }}",
                neo4j.auth.basic("{{ neo4j_user }}", "{{ neo4j_password }}"),
                { encrypted: "ENCRYPTION_ON" }
            );

            const session = driver.session();

            const labelColorMap = {
                "Project": "#00D9E9",
                "Component": "#CDEFC2",
                "Material": "#B7B78D",
                "Process": "#D9F5C7",
                "Certification": "#A9A9A9",
                "Department": "#74B9FF",
                "Partner": "#FF7675",
                "Lesson_Learned": "#00D9E9"
            };

            const nodes = new Map();
            const edges = new Map();

            try {
                const result = await session.run(cypher);

                if (result.records.length === 0) {
                    info.innerHTML = "⚠️ 找不到相關數據，請嘗試其他關鍵字。";
                    return;
                }

                result.records.forEach(record => {
                    const n = record.get("n");
                    const r = record.get("r");
                    const m = record.get("m");

                    [n, m].forEach(node => {
                        const id = node.identity.toString();
                        const label = node.labels[0] || "Unknown";
                        const fullName = getNodeCaption(node);

                        const isCenter =
                            targetFromUrl &&
                            String(fullName).toLowerCase().includes(String(targetFromUrl).toLowerCase());

                        if (!nodes.has(id)) {
                            nodes.set(id, {
                                id: id,
                                label: shortenText(fullName, isCenter ? 22 : 16),
                                title:
                                    "類型: " + label +
                                    "<br>名稱: " + fullName,
                                size: isCenter ? 42 : 24,
                                color: {
                                    background: labelColorMap[label] || "#CCCCCC",
                                    border: isCenter ? "#FFFFFF" : "#777777",
                                    highlight: {
                                        background: "#FFFFFF",
                                        border: "#FFD700"
                                    }
                                },
                                borderWidth: isCenter ? 4 : 2,
                                font: {
                                    size: isCenter ? 18 : 14,
                                    color: "#ffffff",
                                    strokeWidth: 4,
                                    strokeColor: "#000000",
                                    multi: "md"
                                },
                                mass: isCenter ? 6 : 1
                            });
                        }
                    });

                    const rid = r.identity.toString();

                    edges.set(rid, {
                        id: rid,
                        from: r.start.toString(),
                        to: r.end.toString(),
                        label: r.type,
                        title: r.type,
                        font: {
                            size: 10,
                            color: "#666666",
                            strokeWidth: 2,
                            strokeColor: "#ffffff",
                            align: "middle"
                        },
                        width: 1.6,
                        color: {
                            color: "#9AA0A6",
                            highlight: "#333333",
                            hover: "#333333",
                            opacity: 0.75
                        },
                        arrows: {
                            to: {
                                enabled: true,
                                scaleFactor: 0.55
                            }
                        },
                        smooth: {
                            enabled: true,
                            type: "continuous",
                            roundness: 0.35
                        }
                    });
                });

                const data = {
                    nodes: Array.from(nodes.values()),
                    edges: Array.from(edges.values())
                };

                const options = {
                    nodes: {
                        shape: "dot",
                        shadow: true
                    },

                    edges: {
                        smooth: {
                            enabled: true,
                            type: "continuous"
                        }
                    },

                    layout: {
                        improvedLayout: true
                    },

                    physics: {
                        enabled: true,
                        solver: "forceAtlas2Based",
                        forceAtlas2Based: {
                            gravitationalConstant: -450,
                            centralGravity: 0.015,
                            springLength: 230,
                            springConstant: 0.025,
                            damping: 0.9,
                            avoidOverlap: 1.2
                        },
                        stabilization: {
                            enabled: true,
                            iterations: 1200,
                            updateInterval: 50
                        }
                    },

                    interaction: {
                        hover: true,
                        tooltipDelay: 200,
                        dragNodes: true,
                        dragView: true,
                        zoomView: true
                    }
                };

                const network = new vis.Network(
                    document.getElementById("viz"),
                    data,
                    options
                );

                network.once("stabilizationIterationsDone", function () {
                    network.setOptions({ physics: false });
                    network.fit({
                        animation: {
                            duration: 800,
                            easingFunction: "easeInOutQuad"
                        }
                    });
                });

                info.innerHTML =
                    "<b>圖譜已生成</b><br>" +
                    "節點數：" + data.nodes.length + "<br>" +
                    "關係數：" + data.edges.length + "<br>" +
                    "可拖曳節點、滾輪縮放。";

            } catch (error) {
                console.error(error);
                info.innerHTML = "❌ 圖形渲染失敗：<br>" + error.message;
            } finally {
                await session.close();
                await driver.close();
            }
        }
    </script>
</body>
</html>
"""


def render_graph_page():
    return render_template_string(
        GRAPH_HTML,
        neo4j_uri=NEO4J_GRAPH_URI,
        neo4j_user=NEO4J_USER,
        neo4j_password=NEO4J_PASSWORD
    )
