import os
import uuid
import math

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import networkx as nx
from io import BytesIO
import urllib.parse

from graph_service import run_cypher
from config import PUBLIC_BASE_URL

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(STATIC_DIR, exist_ok=True)

def wrap_label(text, max_chars=14):
    if not text:
        return ""

    text = str(text)

    # 英文或混合英文：優先用空白切單字
    if " " in text:
        words = text.split()
        lines = []
        current = ""

        for word in words:
            if len(current) + len(word) + 1 <= max_chars:
                current = f"{current} {word}".strip()
            else:
                if current:
                    lines.append(current)
                current = word

        if current:
            lines.append(current)

        return "\n".join(lines)

    # 中文或無空白字串：固定字數換行
    lines = []
    for i in range(0, len(text), max_chars):
        lines.append(text[i:i + max_chars])

    return "\n".join(lines)


def get_relation_label(label):
    if not label:
        return ""

    # 關係名稱通常很長，這裡保留完整，但用換行避免擠在一起
    return str(label).replace("_", "_\n")

def get_chinese_font():
    font_paths = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.otf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.otf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.otf",
    ]

    for path in font_paths:
        if os.path.exists(path):
            print("DEBUG found Chinese font:", path)
            return fm.FontProperties(fname=path)

    # fallback：掃描整個 /usr/share/fonts
    for root, dirs, files in os.walk("/usr/share/fonts"):
        for file in files:
            if file.endswith((".ttf", ".ttc", ".otf")):
                full_path = os.path.join(root, file)
                if "NotoSansCJK" in full_path or "NotoSerifCJK" in full_path:
                    print("DEBUG found Chinese font by scan:", full_path)
                    return fm.FontProperties(fname=full_path)

    print("WARNING: Chinese font not found")
    return None

def generate_node_graph_image_bytes(target, limit=50):
    rows = query_node_graph_rows(target, limit=limit)

    if not rows:
        return None

    G = nx.DiGraph()

    center = rows[0].get("source") or target
    G.add_node(center, label=rows[0].get("source_label", "Center"))

    for row in rows:
        source = row.get("source")
        target_node = row.get("target")
        relation = row.get("relation")

        if not source or not target_node:
            continue

        G.add_node(source, label=row.get("source_label", "Unknown"))
        G.add_node(target_node, label=row.get("target_label", "Unknown"))
        G.add_edge(source, target_node, label=relation)

    if len(G.nodes) == 0:
        return None

    chinese_font = get_chinese_font()

    pos = {}
    pos[center] = (0, 0)

    neighbors = [n for n in G.nodes if n != center]
    count = len(neighbors)

    radius = 2.45 + min(count, 20) * 0.06

    for i, node in enumerate(neighbors):
        angle = 2 * math.pi * i / max(count, 1)
        pos[node] = (
            radius * math.cos(angle),
            radius * math.sin(angle)
        )

    fig, ax = plt.subplots(figsize=(15, 10))
    ax.set_facecolor("#f7f7f7")

    label_color_map = {
        "Project": "#00D9E9",
        "Component": "#CDEFC2",
        "Material": "#B7B78D",
        "Process": "#D9F5C7",
        "Certification": "#A9A9A9",
        "Department": "#74B9FF",
        "Partner": "#FF7675",
        "Lesson_Learned": "#00D9E9"
    }

    node_colors = []
    node_sizes = []

    for node in G.nodes:
        node_label = G.nodes[node].get("label", "Unknown")
        node_colors.append(label_color_map.get(node_label, "#CCCCCC"))
        node_sizes.append(5200 if node == center else 3600)

    nx.draw_networkx_nodes(
        G,
        pos,
        node_color=node_colors,
        node_size=node_sizes,
        edgecolors="#ffffff",
        linewidths=2.2,
        ax=ax
    )

    nx.draw_networkx_edges(
        G,
        pos,
        arrows=True,
        arrowstyle="-|>",
        arrowsize=16,
        width=1.5,
        edge_color="#999999",
        connectionstyle="arc3,rad=0.06",
        ax=ax
    )

    node_labels = {
        node: wrap_label(node, max_chars=18 if node == center else 13)
        for node in G.nodes
    }

    for node, (x, y) in pos.items():
        is_center = node == center

        ax.text(
            x,
            y,
            node_labels[node],
            fontsize=12 if is_center else 9,
            color="black",
            fontweight="bold",
            fontproperties=chinese_font,
            ha="center",
            va="center",
            linespacing=1.15,
            zorder=10
        )

    for u, v, data in G.edges(data=True):
        if u not in pos or v not in pos:
            continue

        x1, y1 = pos[u]
        x2, y2 = pos[v]

        mx = x1 * 0.43 + x2 * 0.57
        my = y1 * 0.43 + y2 * 0.57

        ax.text(
            mx,
            my,
            data.get("label", ""),
            fontsize=7,
            color="#555555",
            fontweight="bold",
            fontproperties=chinese_font,
            ha="center",
            va="center",
            bbox=dict(
                facecolor="white",
                edgecolor="none",
                alpha=0.65,
                pad=0.4
            ),
            zorder=9
        )

    ax.text(
        0.5,
        1.03,
        f"{center} 關係圖",
        transform=ax.transAxes,
        ha="center",
        va="bottom",
        fontsize=20,
        fontweight="bold",
        fontproperties=chinese_font
    )

    ax.axis("off")
    plt.tight_layout()

    image_io = BytesIO()
    plt.savefig(image_io, format="png", dpi=180, bbox_inches="tight")
    plt.close(fig)

    image_io.seek(0)
    return image_io

def shorten_text(text, max_len=None):
    if not text:
        return ""
    return str(text)


def query_node_graph_rows(target, limit=50):
    safe_target = target.strip()

    q = """
    MATCH (n)
    WHERE toLower(coalesce(n.name, n.title, n.issue_id, "")) = toLower($target)
       OR toLower(coalesce(n.name, n.title, n.issue_id, "")) CONTAINS toLower($target)
    WITH n
    LIMIT 1
    MATCH (n)-[r]-(m)
    RETURN
        coalesce(n.name, n.title, n.issue_id) AS source,
        labels(n)[0] AS source_label,
        type(r) AS relation,
        coalesce(m.name, m.title, m.issue_id) AS target,
        labels(m)[0] AS target_label
    LIMIT $limit
    """

    return run_cypher(q, {
        "target": safe_target,
        "limit": limit
    })
def wrap_text(text, line_len=8):
    if not text:
        return ""

    text = str(text)

    lines = []
    current = ""

    for ch in text:
        current += ch
        if len(current) >= line_len:
            lines.append(current)
            current = ""

    if current:
        lines.append(current)

    return "\n".join(lines)


def generate_node_graph_image(target, limit=50):
    rows = query_node_graph_rows(target, limit=limit)

    if not rows:
        return None

    G = nx.DiGraph()

    center = rows[0].get("source") or target
    G.add_node(center, label=rows[0].get("source_label", "Center"))

    for row in rows:
        source = row.get("source")
        target_node = row.get("target")
        relation = row.get("relation")

        if not source or not target_node:
            continue

        G.add_node(source, label=row.get("source_label", "Unknown"))
        G.add_node(target_node, label=row.get("target_label", "Unknown"))
        G.add_edge(source, target_node, label=relation)

    if len(G.nodes) == 0:
        return None

    # ===== 字型 =====
    chinese_font = get_chinese_font()

    # ===== 放射狀 layout =====
    pos = {}
    pos[center] = (0, 0)

    neighbors = [n for n in G.nodes if n != center]
    count = len(neighbors)

    radius = 2.45 + min(count, 20) * 0.06

    for i, node in enumerate(neighbors):
        angle = 2 * math.pi * i / max(count, 1)
        pos[node] = (
            radius * math.cos(angle),
            radius * math.sin(angle)
        )

    fig, ax = plt.subplots(figsize=(15, 10))
    ax.set_facecolor("#f7f7f7")

    label_color_map = {
        "Project": "#00D9E9",
        "Component": "#CDEFC2",
        "Material": "#B7B78D",
        "Process": "#D9F5C7",
        "Certification": "#A9A9A9",
        "Department": "#74B9FF",
        "Partner": "#FF7675",
        "Lesson_Learned": "#00D9E9"
    }

    node_colors = []
    node_sizes = []

    for node in G.nodes:
        node_label = G.nodes[node].get("label", "Unknown")
        node_colors.append(label_color_map.get(node_label, "#CCCCCC"))

        if node == center:
            node_sizes.append(5200)
        else:
            node_sizes.append(3600)

    # ===== 畫節點圓圈 =====
    nx.draw_networkx_nodes(
        G,
        pos,
        node_color=node_colors,
        node_size=node_sizes,
        edgecolors="#ffffff",
        linewidths=2.2,
        ax=ax
    )

    # ===== 畫線 =====
    nx.draw_networkx_edges(
        G,
        pos,
        arrows=True,
        arrowstyle="-|>",
        arrowsize=16,
        width=1.5,
        edge_color="#999999",
        connectionstyle="arc3,rad=0.06",
        ax=ax
    )

    # ===== 節點文字 =====
    node_labels = {
        node: wrap_label(node, max_chars=18 if node == center else 13)
        for node in G.nodes
    }

    for node, (x, y) in pos.items():
        is_center = node == center

        ax.text(
            x,
            y,
            node_labels[node],
            fontsize=12 if is_center else 9,
            color="black",
            fontweight="bold",
            fontproperties=chinese_font,
            ha="center",
            va="center",
            linespacing=1.15,
            zorder=10
        )

    # ===== 關係文字 HAS_PROCESS / INCLUDES 等 =====
    for u, v, data in G.edges(data=True):
        if u not in pos or v not in pos:
            continue

        x1, y1 = pos[u]
        x2, y2 = pos[v]

        mx = x1 * 0.43 + x2 * 0.57
        my = y1 * 0.43 + y2 * 0.57

        ax.text(
            mx,
            my,
            data.get("label", ""),
            fontsize=7,
            color="#555555",
            fontweight="bold",
            fontproperties=chinese_font,
            ha="center",
            va="center",
            bbox=dict(
                facecolor="white",
                edgecolor="none",
                alpha=0.65,
                pad=0.4
            ),
            zorder=9
        )

    # ===== 標題，不用 plt.title，避免中文字型失效 =====
    ax.text(
        0.5,
        1.03,
        f"{center} graph",
        transform=ax.transAxes,
        ha="center",
        va="bottom",
        fontsize=20,
        fontweight="bold",
        fontproperties=chinese_font
    )

    ax.axis("off")
    plt.tight_layout()

    filename = f"node_graph_{uuid.uuid4().hex}.png"
    filepath = os.path.join(STATIC_DIR, filename)

    plt.savefig(filepath, dpi=180, bbox_inches="tight")
    plt.close()

    return filename


def build_node_graph_image_url(target):
    encoded_target = urllib.parse.quote(target)
    cache_buster = uuid.uuid4().hex

    return f"{PUBLIC_BASE_URL}/graph/image?target={encoded_target}&v={cache_buster}"
