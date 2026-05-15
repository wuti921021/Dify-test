import io
import os
import uuid
import math
import urllib.parse
from io import BytesIO

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib import font_manager
import networkx as nx

from service.graph_service import run_cypher
from config import PUBLIC_BASE_URL
from urllib.parse import quote

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

FONT_PATH = os.path.join(
    BASE_DIR,
    "fonts",
    "NotoSansCJKtc-Regular.otf"
)
try:
    font_manager.fontManager.addfont(FONT_PATH)

    CHINESE_FONT = font_manager.FontProperties(fname=FONT_PATH)
    CHINESE_FONT_NAME = CHINESE_FONT.get_name()

    plt.rcParams["font.family"] = CHINESE_FONT_NAME
    plt.rcParams["axes.unicode_minus"] = False

    print("DEBUG FONT_PATH:", FONT_PATH)
    print("DEBUG FONT_EXISTS:", os.path.exists(FONT_PATH))
    print("DEBUG FONT_SIZE:", os.path.getsize(FONT_PATH))
    print("DEBUG FONT_NAME:", CHINESE_FONT_NAME)

except Exception as e:
    print("WARNING: Chinese font load failed")
    print("DEBUG FONT_PATH:", FONT_PATH)
    print("DEBUG FONT_EXISTS:", os.path.exists(FONT_PATH))

    if os.path.exists(FONT_PATH):
        print("WARNING FONT_SIZE:", os.path.getsize(FONT_PATH))

    print("WARNING FONT_ERROR:", repr(e))

    CHINESE_FONT = None
    CHINESE_FONT_NAME = None
    
STATIC_DIR = os.path.join(BASE_DIR, "static")
os.makedirs(STATIC_DIR, exist_ok=True)

def build_relationship_graph_url(source, relation, target):
    if not PUBLIC_BASE_URL:
        print("[ERROR][PUBLIC_BASE_URL] PUBLIC_BASE_URL is not set")
        return None

    base_url = PUBLIC_BASE_URL.rstrip("/")

    source = quote(str(source))
    relation = quote(str(relation))
    target = quote(str(target))

    return (
        f"{base_url}/graph/relation-image"
        f"?source={source}"
        f"&relation={relation}"
        f"&target={target}"
    )

def generate_relationship_graph_image(source, relation, target):
    try:
        G = nx.DiGraph()

        G.add_node(source)
        G.add_node(target)

        G.add_edge(source, target, label=relation)

        pos = {
            source: (-1, 0),
            target: (1, 0)
        }

        plt.figure(figsize=(6, 3))

        nx.draw(
            G,
            pos,
            with_labels=True,
            node_size=4000,
            font_family="sans-serif",
            arrows=True
        )

        edge_labels = {
            (source, target): relation
        }

        nx.draw_networkx_edge_labels(
            G,
            pos,
            edge_labels=edge_labels,
            font_size=10
        )

        img_io = io.BytesIO()

        plt.savefig(
            img_io,
            format="png",
            bbox_inches="tight"
        )

        plt.close()

        img_io.seek(0)

        return img_io

    except Exception as e:
        print("[ERROR][RELATION_GRAPH]", str(e))
        return None


def get_chinese_font():
    return CHINESE_FONT


def wrap_label(text, max_chars=14):
    if not text:
        return ""

    text = str(text)

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

    lines = []
    for i in range(0, len(text), max_chars):
        lines.append(text[i:i + max_chars])

    return "\n".join(lines)

def query_node_graph_rows_by_id(node_id, limit=50):
    q = """
    MATCH (n)
    WHERE elementId(n) = $node_id
    WITH n
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
        "node_id": node_id,
        "limit": limit
    })

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

    chinese_font = get_chinese_font()

    pos = {}
    pos[center] = (0, 0)

    neighbors = [n for n in G.nodes if n != center]
    count = len(neighbors)

    radius = 1.55 + min(count, 20) * 0.035

    for i, node in enumerate(neighbors):
        angle = 2 * math.pi * i / max(count, 1)
        pos[node] = (
            radius * math.cos(angle),
            radius * math.sin(angle)
        )

    fig, ax = plt.subplots(figsize=(16, 10))
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
        node_sizes.append(15000 if node == center else 10500)

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
        arrowsize=24,
        width=3.2,
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
            fontsize=24 if is_center else 17,
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

        edge_label = str(data.get("label", ""))

        ax.text(
            mx,
            my,
            edge_label,
            fontsize=14,
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
        f"{center} graph",
        transform=ax.transAxes,
        ha="center",
        va="bottom",
        fontsize=34,
        fontweight="bold",
        fontproperties=chinese_font
    )

    ax.axis("off")
    plt.tight_layout()

    filename = f"node_graph_{uuid.uuid4().hex}.png"
    filepath = os.path.join(STATIC_DIR, filename)

    plt.savefig(filepath, dpi=220, bbox_inches="tight")
    plt.close(fig)

    return filename

def generate_node_graph_image_by_id(node_id, limit=50):
    rows = query_node_graph_rows_by_id(node_id, limit=limit)

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

    radius = 1.55 + min(count, 20) * 0.035

    for i, node in enumerate(neighbors):
        angle = 2 * math.pi * i / max(count, 1)
        pos[node] = (
            radius * math.cos(angle),
            radius * math.sin(angle)
        )

    fig, ax = plt.subplots(figsize=(16, 10))
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
        node_sizes.append(15000 if node == center else 10500)

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
        arrowsize=24,
        width=3.2,
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
            fontsize=24 if is_center else 17,
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

        edge_label = str(data.get("label", ""))

        ax.text(
            mx,
            my,
            edge_label,
            fontsize=14,
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
        f"{center} graph",
        transform=ax.transAxes,
        ha="center",
        va="bottom",
        fontsize=34,
        fontweight="bold",
        fontproperties=chinese_font
    )

    ax.axis("off")
    plt.tight_layout()

    filename = f"node_graph_{uuid.uuid4().hex}.png"
    filepath = os.path.join(STATIC_DIR, filename)

    plt.savefig(filepath, dpi=220, bbox_inches="tight")
    plt.close(fig)

    return filename

    return generate_graph_image_from_rows(rows)

def build_node_graph_image_url(target):
    encoded_target = urllib.parse.quote(target)
    cache_buster = uuid.uuid4().hex

    return f"{PUBLIC_BASE_URL}/graph/image?target={encoded_target}&v={cache_buster}"

from io import BytesIO

def build_node_graph_image_url_by_id(node_id):
    encoded_node_id = urllib.parse.quote(node_id)
    cache_buster = uuid.uuid4().hex

    return f"{PUBLIC_BASE_URL}/graph/image?node_id={encoded_node_id}&v={cache_buster}"

def generate_node_graph_image_bytes(target, limit=50):
    filename = generate_node_graph_image(target, limit=limit)

    if not filename:
        return None

    filepath = os.path.join(STATIC_DIR, filename)

    with open(filepath, "rb") as f:
        image_io = BytesIO(f.read())

    image_io.seek(0)
    return image_io

def generate_node_graph_image_bytes_by_id(node_id, limit=50):
    filename = generate_node_graph_image_by_id(node_id, limit=limit)

    if not filename:
        return None

    filepath = os.path.join(STATIC_DIR, filename)

    with open(filepath, "rb") as f:
        image_io = BytesIO(f.read())

    image_io.seek(0)
    return image_io
