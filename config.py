import os

# ===== LINE =====
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")

# ===== DIFY =====
DIFY_API_KEY = os.environ.get("DIFY_API_KEY")
DIFY_BASE_URL = os.environ.get("DIFY_BASE_URL")

# ===== Neo4j =====
NEO4J_URI = os.environ.get("NEO4J_URI")
NEO4J_USER = os.environ.get("NEO4J_USER")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD")

# ===== 給 NeoVis 前端用 =====
NEO4J_BROWSER_URI = (
    NEO4J_URI
    .replace("neo4j+s://", "neo4j://")
    .replace("neo4j+ssc://", "neo4j://")
)

# ===== Render URL =====
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL")
