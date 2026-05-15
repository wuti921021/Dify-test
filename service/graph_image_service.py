import os
import io
import uuid
import math
from urllib.parse import quote

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import networkx as nx
from matplotlib import font_manager

from config import PUBLIC_BASE_URL
from service.graph_service import run_cypher


# =========================
# Path / Font Config
# =========================

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FONT_PATH = os.path.join(
    BASE_DIR,
    "fonts",
    "NotoSansCJKtc-Regular.otf"
)

FONT_NAME = "DejaVu Sans"

try:
    if os.path.exists(FONT_PATH):
        font_manager.fontManager.addfont(FONT_PATH)
        FONT_NAME = font_manager.FontProperties(fname=FONT_PATH).get_name()
        print("[GRAPH IMAGE][FONT_NAME]", FONT_NAME)
    else:
        print("[GRAPH IMAGE][FONT_MISSING]", FONT_PATH)
except Exception as e:
    print("[GRAPH IMAGE][FONT_LOAD_ERROR]", str(e))


# =========================
# URL Builders
# =========================

def get_public_base_url():
    if not PUBLIC_BASE_URL:
        print("[ERROR][PUBLIC_BASE_URL] PUBLIC_BASE_URL is not set")
        return None

    return PUBLIC_BASE_URL.rstrip("/")


def build_node_graph_image_url(target):
    base_url = get_public_base_url()

    if not base_url or not target:
        return None

    return (
        f"{base_url}/graph/image"
        f"?target={quote(str(target))}"
        f"&v={uuid.uuid4().hex}"
    )


def build_node_graph_image_url_by_id(node_id):
    base_url = get_public_base_url()

    if not base_url or not node_id:
        return None

    return (
        f"{base_url}/graph/image"
        f"?node_id={quote(str(node_id))}"
        f"&v={uuid.uuid4().hex}"
    )


def build_relationship_graph_url(source, relation, target):
    base_url = get_public_base_url()

    if not base_url:
        return None

    return (
        f"{base_url}/graph/relation-image"
        f"?source={quote(str(source))}"
        f"&relation={quote(str(relation))}"
        f"&target={quote(str(target))}"
        f"&v={uuid.uuid4().hex}"
    )


# =========================
# Neo4j Data Loading
# =========================

def fetch_node_graph_data_by_name(target):
    q = """
    MATCH (center)
    WHERE coalesce(center.name, center.title) = $target
    OPTIONAL MATCH (center)-[r]-(neighbor)
    RETURN
        elementId(center) AS center_id,
        coalesce(center.name, center.title) AS center_name,
        labels(center) AS center_labels,
        elementId(neighbor) AS neighbor_id,
        coalesce(neighbor.name, neighbor.title) AS neighbor_name,
        labels(neighbor) AS neighbor_labels,
        type(r) AS relation_type,
        startNode(r) = center AS outgoing
    LIMIT 30
    """

    return run_cypher(q, {"target": target})


def fetch_node_graph_data_by_id(node_id):
    q = """
    MATCH (center)
    WHERE elementId(center) = $node_id
    OPTIONAL MATCH (center)-[r]-(neighbor)
    RETURN
        elementId(center) AS center_id,
        coalesce(center.name, center.title) AS center_name,
        labels(center) AS center_labels,
        elementId(neighbor) AS neighbor_id,
        coalesce(neighbor.name, neighbor.title) AS neighbor_name,
        labels(neighbor) AS neighbor_labels,
        type(r) AS relation_type,
        startNode(r) = center AS outgoing
    LIMIT 30
    """

    return run_cypher(q, {"node_id": node_id})


# =========================
# Style Helpers
# =========================

def wrap_label(text, max_len=14):
    if not text:
        return ""

    text = str(text)

    if len(text) <= max_len:
        return text

    words = text.split()

    if len(words) > 1:
        lines = []
        current = ""

        for word in words:
            if len(current + " " + word) <= max_len:
                current = (current + " " + word).strip()
            else:
                if current:
                    lines.append(current)
                current = word

        if current:
            lines.append(current)

        return "\n".join(lines)

    return "\n".join(
        text[i:i + max_len]
        for i in range(0, len(text), max_len)
    )


def get_node_color(labels, is_center=False):
    if is_center:
        return "#18d7df"

    labels = labels or []

    if "Lesson_Learned" in labels:
        return "#18d7df"

    if "Certification" in labels:
        return "#bdbdbd"

    return "#d7f5cf"


def build_radial_positions(center_name, neighbors):
    pos = {
        center_name: (0, 0)
    }

    if not neighbors:
        return pos

    radius = 2.6
    count = len(neighbors)

    start_angle = math.pi / 2

    for index, neighbor in enumerate(neighbors):
        angle = start_angle + (2 * math.pi * index / count)

        x = radius * math.cos(angle)
        y = radius * math.sin(angle)

        pos[neighbor] = (x, y)

    return pos


# =========================
# Single Node Graph
# =========================

def generate_node_graph_image_bytes(target):
    try:
        rows = fetch_node_graph_data_by_name(target)
        return generate_node_graph_from_rows(rows)

    except Exception as e:
        print("[ERROR][NODE_GRAPH_BY_NAME]", str(e))
        return None


def generate_node_graph_image_bytes_by_id(node_id):
    try:
        rows = fetch_node_graph_data_by_id(node_id)
        return generate_node_graph_from_rows(rows)

    except Exception as e:
        print("[ERROR][NODE_GRAPH_BY_ID]", str(e))
        return None


def generate_node_graph_from_rows(rows):
    if not rows:
        return None

    center_name = rows[0].get("center_name")

    if not center_name:
        return None

    graph = nx.DiGraph()
    edge_labels = {}
    node_colors = {}
    node_labels = {}

    center_labels = rows[0].get("center_labels", [])

    graph.add_node(center_name)
    node_colors[center_name] = get_node_color(center_labels, is_center=True)
    node_labels[center_name] = wrap_label(center_name, max_len=13)

    neighbors = []

    for row in rows:
        neighbor_name = row.get("neighbor_name")
        neighbor_labels = row.get("neighbor_labels", [])
        relation_type = row.get("relation_type")
        outgoing = row.get("outgoing")

        if not neighbor_name or not relation_type:
            continue

        if neighbor_name not in graph:
            graph.add_node(neighbor_name)
            neighbors.append(neighbor_name)

        node_colors[neighbor_name] = get_node_color(neighbor_labels)
        node_labels[neighbor_name] = wrap_label(neighbor_name, max_len=16)

        if outgoing:
            graph.add_edge(center_name, neighbor_name)
            edge_labels[(center_name, neighbor_name)] = relation_type
        else:
            graph.add_edge(neighbor_name, center_name)
            edge_labels[(neighbor_name, center_name)] = relation_type

    pos = build_radial_positions(center_name, neighbors)

    plt.figure(figsize=(10, 6))

    colors = [
        node_colors.get(node, "#d7f5cf")
        for node in graph.nodes()
    ]

    sizes = [
        2300 if node == center_name else 2100
        for node in graph.nodes()
    ]

    nx.draw_networkx_nodes(
        graph,
        pos,
        node_color=colors,
        node_size=sizes,
        edgecolors="none"
    )

    nx.draw_networkx_edges(
        graph,
        pos,
        arrows=False,
        width=1.3,
        edge_color="#8a8a8a",
        connectionstyle="arc3,rad=0.05"
    )

    nx.draw_networkx_labels(
        graph,
        pos,
        labels=node_labels,
        font_size=9,
        font_weight="bold",
        font_family=FONT_NAME
    )

    nx.draw_networkx_edge_labels(
        graph,
        pos,
        edge_labels=edge_labels,
        font_size=7,
        font_family=FONT_NAME,
        rotate=True,
        label_pos=0.52
    )

    plt.title(
        f"{center_name} graph",
        fontsize=16,
        fontweight="bold",
        fontfamily=FONT_NAME
    )

    plt.axis("off")
    plt.tight_layout()

    image_io = io.BytesIO()

    plt.savefig(
        image_io,
        format="png",
        bbox_inches="tight",
        dpi=150,
        facecolor="white"
    )

    plt.close()
    image_io.seek(0)

    return image_io


# =========================
# Two-Node Relationship Graph
# =========================

def generate_relationship_graph_image(source, relation, target):
    try:
        graph = nx.DiGraph()

        graph.add_node(source)
        graph.add_node(target)
        graph.add_edge(source, target)

        pos = {
            source: (-1.6, 0),
            target: (1.6, 0)
        }

        node_labels = {
            source: wrap_label(source, max_len=16),
            target: wrap_label(target, max_len=16)
        }

        edge_labels = {
            (source, target): relation
        }

        plt.figure(figsize=(8, 3))

        nx.draw_networkx_nodes(
            graph,
            pos,
            node_color=["#18d7df", "#d7f5cf"],
            node_size=2600,
            edgecolors="none"
        )

        nx.draw_networkx_edges(
            graph,
            pos,
            arrows=True,
            arrowstyle="-|>",
            arrowsize=18,
            width=1.4,
            edge_color="#8a8a8a"
        )

        nx.draw_networkx_labels(
            graph,
            pos,
            labels=node_labels,
            font_size=10,
            font_weight="bold",
            font_family=FONT_NAME
        )

        nx.draw_networkx_edge_labels(
            graph,
            pos,
            edge_labels=edge_labels,
            font_size=8,
            font_family=FONT_NAME,
            rotate=False
        )

        plt.title(
            f"{source} relation graph",
            fontsize=15,
            fontweight="bold",
            fontfamily=FONT_NAME
        )

        plt.axis("off")
        plt.tight_layout()

        image_io = io.BytesIO()

        plt.savefig(
            image_io,
            format="png",
            bbox_inches="tight",
            dpi=150,
            facecolor="white"
        )

        plt.close()
        image_io.seek(0)

        return image_io

    except Exception as e:
        print("[ERROR][RELATION_GRAPH]", str(e))
        return None
