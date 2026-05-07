# ===== imports =====
import json
import re
import os
from neo4j import GraphDatabase
from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
from rapidfuzz import fuzz
from rapidfuzz import process as rf_process
from datetime import date, datetime

# ===== path helper =====
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def load_json(filename):
    path = os.path.join(BASE_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

# ===== load config =====
NODE_SCHEMA = load_json("node_schema.json")
RELATION_META = load_json("relation_data.json")
GENERIC_LOOKUP_CONFIG = load_json("lookup_config.json")
PROJECT_RELATION_QUERY_MAP = load_json("project_relation_query_map.json")

# ==============================================================================
# 2. Schema-Derived Fields
# ==============================================================================
def build_entity_fields_from_schema():
    fields = {}

    for label, meta in NODE_SCHEMA.items():
        field_name = meta.get("payload_field")

        if field_name:
            fields[field_name] = label

    return fields
ENTITY_FIELDS = build_entity_fields_from_schema()


# ==============================================================================
# 3. Global Constants / Config Maps
# ==============================================================================
CHECK_CATEGORY_ALIASES = {
    "project": ["project", "專案", "項目"],
    "component": ["component", "元件", "零件"],
    "material": ["material", "材料", "用料", "膠材"],
    "process": ["process", "製程", "流程", "步驟"],
    "certification": ["certification", "認證", "標準"],
    "department": ["department", "部門", "團隊"],
    "partner": ["partner", "供應商", "廠商", "合作夥伴", "合作對象"],
    "lesson": ["lesson", "lesson learned", "經驗", "教訓", "失敗案例", "案例"],
}
CHECK_LABEL_MAP = {
    "project": "Project",
    "component": "Component",
    "material": "Material",
    "process": "Process",
    "certification": "Certification",
    "department": "Department",
    "partner": "Partner",
    "lesson": "Lesson_Learned",
    "lesson_learned": "Lesson_Learned",
}
ENTITY_CACHE = {
    "Project": None,
    "Component": None,
    "Material": None,
    "Process": None,
    "Certification": None,
    "Partner": None,
    "Department": None,
    "Lesson_Learned": None,
}
RELATION_HINTS = {
    relation_name: meta.get("aliases", [])
    for relation_name, meta in RELATION_META.items()
}


# ==============================================================================
# 4. Neo4j Driver
# ==============================================================================
def get_driver():
    return GraphDatabase.driver(
        NEO4J_URI,
        auth=(NEO4J_USER, NEO4J_PASSWORD)
    )


# ==============================================================================
# 5. Utility Functions
# ==============================================================================
def clean_text(s):
    if s is None:
        return None
    s = str(s).strip()
    return s if s else None
def dedupe_keep_order(items):
    seen = set()
    result = []
    for item in items:
        if item is None:
            continue
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result

def filter_properties_by_schema(label, properties):
    allowed = get_node_properties(label)

    if not allowed:
        return properties or {}

    return {
        key: value
        for key, value in (properties or {}).items()
        if key in allowed
    }

def make_json_safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [make_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: make_json_safe(v) for k, v in value.items()}
    return str(value)
def sanitize_result(rows):
    return [{k: make_json_safe(v) for k, v in row.items()} for row in rows]


# ==============================================================================
# 6. Database / Schema Helper Functions
# ==============================================================================
def run_cypher(query, params=None):
    driver = get_driver()
    with driver.session() as session:
        result = session.run(query, params or {})
        rows = [record.data() for record in result]
    driver.close()
    return sanitize_result(rows)
def get_name_fields(label):
    return NODE_SCHEMA.get(label, {}).get("name_fields", ["name"])
def get_node_properties(label):
    return NODE_SCHEMA.get(label, {}).get("properties", [])
def build_coalesce_name_expr(label, var_name="n"):
    fields = get_name_fields(label)
    props = [f"{var_name}.{field}" for field in fields]
    return "coalesce(" + ", ".join(props) + ")"
def build_name_match_condition(label, var_name="n", param_name="name"):
    fields = get_name_fields(label)
    conditions = [f"{var_name}.{field} = ${param_name}" for field in fields]
    return " OR ".join(conditions)
def get_label_from_category(category):
    for label, meta in NODE_SCHEMA.items():
        if category.lower() in [a.lower() for a in meta.get("aliases", [])]:
            return label
    return None


# ==============================================================================
# 7. Fuzzy Matching / Entity Resolution
# ==============================================================================
def detect_check_category(user_question):
    text = clean_text(user_question) or ""
    text = text.split(":")[0].strip()
    lower_text = text.lower()

    # 明確 check 指令
    if lower_text.startswith("check "):
        category = lower_text.replace("check ", "", 1).strip()
        return category

    # 白話查詢觸發詞
    trigger_words = [
        "有哪些",
        "有那些",
        "列出",
        "查詢",
        "查看",
        "顯示",
        "全部",
        "所有",
        "目前有哪些",
        "現在有哪些"
    ]

    has_trigger = any(word in lower_text for word in trigger_words)

    if not has_trigger:
        return None

    # 找分類
    for category, aliases in CHECK_CATEGORY_ALIASES.items():
        for alias in aliases:
            if alias.lower() in lower_text:
                return category

    return None
def find_candidate_nodes(raw_text, score_cutoff=70, max_results=5):
    candidates = []

    if not raw_text:
        return candidates

    raw = str(raw_text).strip().lower()

    search_labels = [
        "Project",
        "Component",
        "Material",
        "Process",
        "Certification",
        "Department",
        "Partner",
        "Lesson_Learned"
    ]

    for label in search_labels:
        names = get_all_entity_names(label)

        for name in names:
            name_str = str(name).strip()
            name_lower = name_str.lower()

            score = fuzz.WRatio(raw, name_lower)

            # 關鍵：只要名稱包含 raw，就強制視為高分候選
            if raw in name_lower:
                score = max(score, 95)

            if score >= score_cutoff:
                candidates.append({
                    "name": name_str,
                    "label": label,
                    "score": score
                })

    # 去重
    unique = {}
    for c in candidates:
        key = (c["name"], c["label"])
        if key not in unique or c["score"] > unique[key]["score"]:
            unique[key] = c

    candidates = list(unique.values())
    candidates.sort(key=lambda x: x["score"], reverse=True)

    return candidates[:max_results]
def fuzzy_match_one(query, candidates, score_cutoff=60):
    if not query or not candidates:
        return None, 0

    query_str = str(query).strip()

    # 先做大小寫不敏感的完全比對
    for c in candidates:
        if str(c).strip().lower() == query_str.lower():
            return c, 100.0

    # 再做 fuzzy
    result = rf_process.extractOne(
        query_str,
        candidates,
        scorer=fuzz.WRatio,
        score_cutoff=score_cutoff
    )

    if result:
        return result[0], result[1]

    return None, 0
def get_all_entity_names(label):
    if ENTITY_CACHE.get(label) is not None:
        return ENTITY_CACHE[label]

    name_expr = build_coalesce_name_expr(label, "n")

    q = f"""
    MATCH (n:{label})
    WHERE {name_expr} IS NOT NULL
    RETURN DISTINCT {name_expr} AS name
    ORDER BY name
    """

    rows = run_cypher(q)
    names = [r["name"] for r in rows if r.get("name")]

    ENTITY_CACHE[label] = names
    return names
def get_first_resolved_entity(resolved):
    for field, info in resolved.items():
        if info.get("matched"):
            return field, info
    return None, None
def resolve_entities_from_payload(payload):
    resolved = {}

    field_label_map = {
        "project": "Project",
        "component": "Component",
        "material": "Material",
        "process": "Process",
        "certification": "Certification",
        "department": "Department",
        "partner": "Partner",
        "lesson_keyword": "Lesson_Learned",
    }

    for field, label in field_label_map.items():
        raw = clean_text(payload.get(field))
        matched, score = resolve_entity_name(label, raw, 55)

        resolved[field] = {
            "input": raw,
            "matched": matched,
            "score": score,
            "label": label
        }

    return resolved
def resolve_entity_name(label, raw_name, score_cutoff=35):
    raw_name = clean_text(raw_name)
    if not raw_name:
        return None, 0
    candidates = get_all_entity_names(label)
    return fuzzy_match_one(raw_name, candidates, score_cutoff)
def resolve_relation_hint(text):
    text = clean_text(text)
    if not text:
        return None, 0

    # 如果只是單一短詞，例如 RoHS、BHC212，不要硬判 relation
    if len(text) <= 8 and all(ch.isalnum() for ch in text):
        return None, 0

    aliases = []
    alias_to_relation = {}

    for rel, words in RELATION_HINTS.items():
        for w in words:
            aliases.append(w)
            alias_to_relation[w] = rel

    # 先用包含判斷，比 fuzzy 更穩
    lower_text = text.lower()
    for alias in aliases:
        if alias.lower() in lower_text:
            return alias_to_relation[alias], 100

    # 最後才 fuzzy，且門檻拉高
    matched, score = fuzzy_match_one(text, aliases, score_cutoff=70)
    if matched:
        return alias_to_relation[matched], score

    return None, 0


# ==============================================================================
# 8. Query Builder / Query Helper Functions
# ==============================================================================
def build_debug_info(intent, relation_hint, relation_score, resolved):
    return {
        "normalized_intent": intent,
        "relation_hint": relation_hint,
        "relation_score": relation_score,
        "resolved_entities": resolved
    }
def build_generic_lookup_query(config):
    label = config["label"]
    return_key = config["return_key"]
    properties = config.get("properties") or get_node_properties(label)
    relations = config.get("relations", [])

    prop_lines = [f"{prop}: n.{prop}" for prop in properties]
    relation_lines = []

    for idx, rel in enumerate(relations):
        if rel["direction"] == "out":
            relation_lines.append(f"OPTIONAL MATCH (n)-[:{rel['relation']}]->(t{idx}:{rel['target_label']})")
        else:
            relation_lines.append(f"OPTIONAL MATCH (s{idx}:{rel['source_label']})-[:{rel['relation']}]->(n)")

    grouped = {}
    for idx, rel in enumerate(relations):
        field = rel["field"]
        grouped.setdefault(field, [])
        if rel["direction"] == "out":
            grouped[field].append(f"collect(DISTINCT t{idx}.name)")
        else:
            grouped[field].append(f"collect(DISTINCT s{idx}.name)")

    return_items = prop_lines[:]
    for field, exprs in grouped.items():
        return_items.append(f"{field}: {' + '.join(exprs)}")

    return_body = ",\n            ".join(return_items)
    optional_body = "\n    ".join(relation_lines)

    q = f"""
    MATCH (n:{label} {{name:$name}})
    {optional_body}
    RETURN {{
            {return_body}
    }} AS {return_key}
    LIMIT $limit
    """
    return q
def get_resolved_entity_candidates(resolved, exclude_fields=None):
    exclude_fields = set(exclude_fields or [])
    candidates = []

    for field, info in resolved.items():
        if field in exclude_fields:
            continue

        if info.get("matched"):
            candidates.append({
                "field": field,
                "label": info.get("label"),
                "matched": info.get("matched"),
                "score": info.get("score", 0),
                "input": info.get("input")
            })

    candidates.sort(key=lambda x: x.get("score", 0), reverse=True)
    return candidates


def resolve_node_lookup_target(user_question, resolved, relation_hint):
    """
    統一處理 node_lookup 的目標節點與查詢模式。

    規則：
    1. 如果整句本身就是某個節點名稱，優先視為單節點查詢。
    2. 如果不是完整節點名稱，但有 relation_hint，視為「某節點 + 某類關係」查詢。
    3. 如果沒有 relation_hint，視為單節點查詢。
    """
    raw_question = clean_text(user_question) or ""
    raw_question = raw_question.strip()
    
    # 只有在冒號後面是明顯查詢詞時才切
    query_suffixes = ["原始問題", "製程", "流程", "材料", "認證", "標準", "部門", "lesson", "教訓"]
    
    for suffix in query_suffixes:
        marker = ":" + suffix
        if raw_question.endswith(marker):
            raw_question = raw_question[:-len(marker)].strip()
            break

    # 先用整句做全節點比對：處理「FPC Failure due to LPI process change」這種完整 title
    raw_candidates = find_candidate_nodes(
        raw_question,
        score_cutoff=85,
        max_results=5
    ) if raw_question else []

    if raw_candidates:
        best = raw_candidates[0]

        # 完全匹配或高分唯一候選：直接當成單節點查詢
        # ===== 先檢查完全相同 =====
    exact_matches = []
    
    for c in raw_candidates:
        candidate_name = str(c.get("name", "")).strip().lower()
    
        if candidate_name == raw_question.lower():
            exact_matches.append(c)
    
    # ===== 只有一個完全相同：直接使用 =====
    if len(exact_matches) == 1:
        best = exact_matches[0]
    
        return {
            "label": best["label"],
            "matched": best["name"],
            "score": 100,
            "input": raw_question
        }, "single_node_detail", None
    
    # ===== 多個完全相同：才 ambiguous =====
    if len(exact_matches) > 1:
        return None, "ambiguous_node", {
            "query_type": "ambiguous_node",
            "found": False,
            "message": "找到多個完全相同名稱節點，請選擇",
            "input": raw_question,
            "candidates": exact_matches[:5]
        }
    
    # ===== 原本 fuzzy matching 邏輯 =====
    if raw_candidates:
        best = raw_candidates[0]
    
        # 高分唯一候選
        if best["score"] >= 95 and len(raw_candidates) == 1:
            return {
                "label": best["label"],
                "matched": best["name"],
                "score": best["score"],
                "input": raw_question
            }, "single_node_detail", None
    
        # 多候選
        return None, "ambiguous_node", {
            "query_type": "ambiguous_node",
            "found": False,
            "message": "找到多個可能節點，請選擇要查詢的項目",
            "input": raw_question,
            "candidates": raw_candidates[:5]
        }
    # 有 relation_hint 時，代表使用者問的是「某節點的某類關係」
    # 此時不要用 lesson_keyword 當主節點，避免「教訓 / 原始問題」誤導。
    if relation_hint:
        entity_candidates = get_resolved_entity_candidates(
            resolved,
            exclude_fields={"lesson_keyword"}
        )

        if entity_candidates:
            best = entity_candidates[0]
            return {
                "label": best["label"],
                "matched": best["matched"],
                "score": best["score"],
                "input": best["input"]
            }, "node_relation_detail", None

    # 沒有 relation_hint：從 Dify 已解析欄位裡選最高分節點
    entity_candidates = get_resolved_entity_candidates(resolved)

    if entity_candidates:
        best = entity_candidates[0]
        return {
            "label": best["label"],
            "matched": best["matched"],
            "score": best["score"],
            "input": best["input"]
        }, "single_node_detail", None

    # 最後 fallback：拆欄位與原句再跑一次全域候選
    fallback_inputs = []
    for _, data in resolved.items():
        if data.get("input"):
            fallback_inputs.append(data["input"])

    if raw_question:
        fallback_inputs.append(raw_question)

    all_candidates = []
    for raw in fallback_inputs:
        all_candidates.extend(find_candidate_nodes(raw, score_cutoff=70, max_results=5))

    unique = {}
    for c in all_candidates:
        key = (c["name"], c["label"])
        if key not in unique or c["score"] > unique[key]["score"]:
            unique[key] = c

    candidates = sorted(unique.values(), key=lambda x: x["score"], reverse=True)

    if len(candidates) == 1:
        best = candidates[0]
        return {
            "label": best["label"],
            "matched": best["name"],
            "score": best["score"],
            "input": raw_question
        }, "single_node_detail", None

    if len(candidates) > 1:
        return None, "ambiguous_node", {
            "query_type": "ambiguous_node",
            "found": False,
            "message": "找到多個可能節點，請選擇要查詢的項目",
            "input": fallback_inputs,
            "candidates": candidates[:5]
        }

    return None, "single_node_detail", {
        "query_type": "single_node",
        "found": False,
        "message": "無法解析單一節點查詢對象"
    }

def detect_node_query_mode(relation_hint):
    if relation_hint:
        return "node_relation_detail"
    return "single_node_detail"

def build_single_node_result(raw_result, query_mode="single_node_detail"):    
    if not raw_result:
        return {"query_type": "single_node", "found": False, "message": "查無節點資料"}

    node = raw_result[0].get("node_info")
    if not node:
        return {"query_type": "single_node", "found": False, "message": "節點存在但無資料"}

    expand_related_properties = query_mode == "node_relation_detail"
    relations = []

    for r in node.get("outgoing_relations", []):
        rel_type = r.get("relation")
        meta = RELATION_META.get(rel_type, {})

        relation_item = {
            "type": rel_type,
            "display_name": meta.get("display_name", rel_type),
            "category": meta.get("category", "unknown"),
            "description": meta.get("description", ""),
            "direction": "out",
            "target": r.get("target"),
            "target_label": r.get("target_label"),
        }

        if expand_related_properties:
            relation_item["target_properties"] = filter_properties_by_schema(
                r.get("target_label"),
                r.get("target_properties", {})
            )

        relations.append(relation_item)

    for r in node.get("incoming_relations", []):
        rel_type = r.get("relation")
        meta = RELATION_META.get(rel_type, {})

        relation_item = {
            "type": rel_type,
            "display_name": meta.get("display_name", rel_type),
            "category": meta.get("category", "unknown"),
            "description": meta.get("description", ""),
            "direction": "in",
            "target": r.get("source"),
            "target_label": r.get("source_label"),
        }

        if expand_related_properties:
            relation_item["target_properties"] = filter_properties_by_schema(
                r.get("source_label"),
                r.get("source_properties", {})
            )

        relations.append(relation_item)

    categories = sorted(list(set(r["category"] for r in relations if r["category"])))

    return {
        "query_type": "single_node",
        "query_mode": query_mode,
        "found": True,
        "node": {
            "name": node.get("name"),
            "label": node.get("label"),
            "properties": filter_properties_by_schema(
                node.get("label"),
                node.get("properties", {})
            )
        },
        "relations": relations[:15],
        "summary": {
            "relation_count": len(relations),
            "categories": categories
        }
    }
def filter_requested_fields(result, top_key, requested_fields):
    if not requested_fields:
        return result

    for row in result:
        info = row.get(top_key, {})
        if isinstance(info, dict):
            row[top_key] = {k: v for k, v in info.items() if k in requested_fields}
    return result
def query_all_nodes_by_label(label, limit=100):
    q = f"""
    MATCH (n:{label})
    WHERE n.name IS NOT NULL OR n.title IS NOT NULL
    RETURN DISTINCT coalesce(n.name, n.title) AS name
    ORDER BY name
    LIMIT $limit
    """
    return run_cypher(q, {"limit": limit})
def query_node_with_relations(label, name):
    name_condition = build_name_match_condition(label, "n", "name")
    name_expr = build_coalesce_name_expr(label, "n")

    q = f"""
    MATCH (n:{label})
    WHERE {name_condition}
    OPTIONAL MATCH (n)-[r]->(m)
    WITH n, collect(DISTINCT {{
        relation: type(r),
        target: coalesce(m.name, m.title),
        target_label: CASE WHEN m IS NOT NULL THEN head(labels(m)) ELSE NULL END,
        target_properties: CASE WHEN m IS NOT NULL THEN properties(m) ELSE {{}} END
    }}) AS outgoing_relations

    OPTIONAL MATCH (x)-[r2]->(n)
    WITH n,
         outgoing_relations,
         collect(DISTINCT {{
            relation: type(r2),
            source: coalesce(x.name, x.title),
            source_label: CASE WHEN x IS NOT NULL THEN head(labels(x)) ELSE NULL END,
            source_properties: CASE WHEN x IS NOT NULL THEN properties(x) ELSE {{}} END
         }}) AS incoming_relations

    RETURN {{
        name: {name_expr},
        label: head(labels(n)),
        properties: properties(n),
        outgoing_relations: [item IN outgoing_relations WHERE item.target IS NOT NULL],
        incoming_relations: [item IN incoming_relations WHERE item.source IS NOT NULL]
    }} AS node_info
    LIMIT 1
    """

    return run_cypher(q, {"name": name}
    )
    
def query_project_full(project_name):
    q = """
    MATCH (p:Project {name:$project})
    OPTIONAL MATCH (p)-[:HAS_PROCESS]->(pr:Process)
    OPTIONAL MATCH (p)-[:HAS_CERTIFICATION]->(c:Certification)
    OPTIONAL MATCH (p)-[:USES_SPECIFIC_PART]->(m:Material)
    OPTIONAL MATCH (p)-[:USES_MATERIAL]->(m2:Material)
    OPTIONAL MATCH (p)-[:INCLUDES]->(comp:Component)
    OPTIONAL MATCH (p)-[:MUST_DISCUSS_WITH]->(d:Department)
    OPTIONAL MATCH (p)-[:HAS_LESSON]->(l:Lesson_Learned)
    RETURN p.name AS project,
           collect(DISTINCT pr.name) AS processes,
           collect(DISTINCT c.name) AS certifications,
           collect(DISTINCT m.name) + collect(DISTINCT m2.name) AS materials,
           collect(DISTINCT comp.name) AS components,
           collect(DISTINCT d.name) AS departments,
           collect(DISTINCT coalesce(l.title, l.name)) AS lessons
    """
    rows = run_cypher(q, {"project": project_name})
    for row in rows:
        if "materials" in row:
            row["materials"] = dedupe_keep_order(row["materials"])
    return rows
def query_project_lessons(project_name):
    q = """
    MATCH (p:Project {name:$project})-[:HAS_LESSON]->(l)
    RETURN p.name AS project,
           collect(DISTINCT {
               title: coalesce(l.title, l.name),
               issue: l.issue,
               root_cause: l.root_cause,
               detected_phase: l.detected_phase,
               action_items: 
                CASE 
                    WHEN l.action_item IS NOT NULL THEN [l.action_item]
                    ELSE [x IN [l.action_item_1, l.action_item_2, l.action_item_3] WHERE x IS NOT NULL]
                END,
               report_date: l.report_date
           }) AS lessons
    """
    return run_cypher(q, {"project": project_name})
def query_project_related(project_name, relation_name, target_label, return_key):
    q = f"""
    MATCH (p:Project {{name:$project}})-[:{relation_name}]->(t:{target_label})
    RETURN p.name AS project,
           collect(DISTINCT t.name) AS {return_key}
    """
    return run_cypher(q, {"project": project_name})
def run_generic_lookup(config, entity_name, limit, requested_fields):
    q = build_generic_lookup_query(config)
    result = run_cypher(q, {"name": entity_name, "limit": limit})

    top_key = config["return_key"]
    for row in result:
        info = row.get(top_key, {})
        if isinstance(info, dict):
            for k, v in list(info.items()):
                if isinstance(v, list):
                    info[k] = dedupe_keep_order(v)

    return filter_requested_fields(result, top_key, requested_fields)


# ==============================================================================
# 9. Intent Normalization
# ==============================================================================
def normalize_intent(payload):
    intent = clean_text(payload.get("intent"))
    user_question = clean_text(payload.get("user_question")) or ""
    relation_hint, _ = resolve_relation_hint(user_question)

    entity_values = {
        field: clean_text(payload.get(field))
        for field in ENTITY_FIELDS.keys()
    }

    project = entity_values.get("project")
    lesson_keyword = entity_values.get("lesson_keyword")

    if intent in {
        "relation_query",
        "compare_entities",
        "node_lookup",
        "lesson_lookup",
        "project_lookup",
        "process_lookup",
        "check_category"
    }:
        return intent

    if project and relation_hint in {
        "HAS_PROCESS",
        "HAS_CERTIFICATION",
        "USES_SPECIFIC_PART",
        "USES_MATERIAL",
        "MUST_DISCUSS_WITH",
        "INCLUDES",
        "HAS_LESSON"
    }:
        return "project_lookup"

    single_entity_count = sum(1 for v in entity_values.values() if v)

    if single_entity_count == 1 and not relation_hint and not lesson_keyword:
        return "node_lookup"

    for lookup_name, config in GENERIC_LOOKUP_CONFIG.items():
        if entity_values.get(config["payload_field"]):
            return lookup_name

    if entity_values.get("process"):
        return "process_lookup"

    if lesson_keyword:
        return "lesson_lookup"

    return intent or "fallback"


# ==============================================================================
# 10. Main Router
# ==============================================================================
def query_graph_by_router(payload):
    user_question = clean_text(payload.get("user_question")) or ""

    # ===== check / 白話分類查詢 =====
    check_category = detect_check_category(user_question)

    if check_category:
        label = get_label_from_category(check_category)

        if not label:
            return {
                "graph_result": [{
                    "query_type": "check_category",
                    "found": False,
                    "message": f"不支援的分類：{check_category}",
                    "available_categories": list(CHECK_LABEL_MAP.keys())
                }]
            }

        rows = query_all_nodes_by_label(label)

        return {
            "graph_result": [{
                "query_type": "check_category",
                "found": True,
                "category": check_category,
                "label": label,
                "count": len(rows),
                "items": [r["name"] for r in rows]
            }]
        }

    intent = normalize_intent(payload)

    user_question = clean_text(payload.get("user_question")) or ""
    source_entity = clean_text(payload.get("source_entity"))
    target_entity = clean_text(payload.get("target_entity"))
    raw_lesson_keyword = clean_text(payload.get("lesson_keyword"))
    compare_targets = payload.get("compare_targets") or []
    requested_fields = payload.get("requested_fields") or []
    limit = payload.get("limit", 5)

    try:
        limit = int(limit)
    except Exception:
        limit = 5

    if limit <= 0:
        limit = 5
    if limit > 20:
        limit = 20

    relation_hint, relation_score = resolve_relation_hint(user_question)
    resolved = resolve_entities_from_payload(payload)
    debug_info = build_debug_info(intent, relation_hint, relation_score, resolved)

    project = resolved.get("project", {}).get("matched")
    process_name = resolved.get("process", {}).get("matched")

    if intent == "node_lookup":
        info, query_mode, error_result = resolve_node_lookup_target(
            user_question=user_question,
            resolved=resolved,
            relation_hint=relation_hint
        )

        if error_result:
            return {"graph_result": [error_result], "debug": debug_info}

        try:
            query_mode = detect_node_query_mode(relation_hint)

            raw = query_node_with_relations(info["label"], info["matched"])

            structured = build_single_node_result(
                raw,
                query_mode=query_mode
            )

            structured = build_single_node_result(
                raw,
                query_mode=query_mode
            )

            structured["query_mode"] = query_mode

            if relation_hint and info.get("label") != "Lesson_Learned":
                filtered = [r for r in structured.get("relations", []) if r["type"] == relation_hint]
                structured["relations"] = filtered
                structured["summary"]["relation_count"] = len(filtered)
                structured["summary"]["categories"] = sorted(list(set(r["category"] for r in filtered)))
                if not filtered:
                    structured["message"] = "目前沒有符合條件的關係資料"

            return {"graph_result": [structured], "debug": debug_info}

        except Exception as e:
            return {
                "graph_result": [{
                    "query_type": "single_node",
                    "found": False,
                    "message": f"node_lookup 執行失敗: {str(e)}"
                }],
                "debug": debug_info
            }

    if intent == "project_lookup" and project:
        if relation_hint == "HAS_LESSON":
            return {"graph_result": query_project_lessons(project), "debug": debug_info}

        relation_cfg = PROJECT_RELATION_QUERY_MAP.get(relation_hint)
        if relation_cfg:
            result = query_project_related(
                project_name=project,
                relation_name=relation_hint,
                target_label=relation_cfg["target_label"],
                return_key=relation_cfg["return_key"]
            )
            return {"graph_result": result, "debug": debug_info}

        return {"graph_result": query_project_full(project), "debug": debug_info}

    if intent in GENERIC_LOOKUP_CONFIG:
        config = GENERIC_LOOKUP_CONFIG[intent]
        entity_name = resolved[config["payload_field"]]["matched"]

        if entity_name:
            result = run_generic_lookup(config, entity_name, limit, requested_fields)
            return {"graph_result": result, "debug": debug_info}

    if intent == "process_lookup" and process_name:
        q = """
        MATCH (pr:Process {name:$process})
        OPTIONAL MATCH (p:Project)-[:HAS_PROCESS]->(pr)
        OPTIONAL MATCH (pr)-[:REQUIRES_SPEC_ALIGNMENT]->(m:Material)
        OPTIONAL MATCH (pr)-[:MUST_ALIGN_TEST_WITH]->(cert:Certification)
        OPTIONAL MATCH (pr)-[:MUST_DISCUSS_WITH]->(d:Department)
        RETURN pr.name AS process,
               collect(DISTINCT p.name) AS related_projects,
               collect(DISTINCT m.name) AS related_materials,
               collect(DISTINCT cert.name) AS related_certifications,
               collect(DISTINCT d.name) AS departments
        LIMIT $limit
        """
        return {"graph_result": run_cypher(q, {"process": process_name, "limit": limit}), "debug": debug_info}

    if intent == "lesson_lookup" and raw_lesson_keyword:
        q = """
        MATCH (l:Lesson_Learned)
        WHERE coalesce(l.title, l.name, "") CONTAINS $kw
           OR coalesce(l.root_cause, "") CONTAINS $kw
           OR coalesce(l.description, "") CONTAINS $kw
           OR coalesce(l.issue, "") CONTAINS $kw
        RETURN {
            title: coalesce(l.title, l.name),
            issue: l.issue,
            root_cause: l.root_cause,
            detected_phase: l.detected_phase,
            action_items: [x IN [l.action_item_1, l.action_item_2, l.action_item_3] WHERE x IS NOT NULL],
            report_date: l.report_date
        } AS lesson_info
        LIMIT $limit
        """
        result = run_cypher(q, {"kw": raw_lesson_keyword, "limit": limit})
        result = filter_requested_fields(result, "lesson_info", requested_fields)
        return {"graph_result": result, "debug": debug_info}

    if intent == "relation_query" and source_entity and target_entity:

        def resolve_any_entity(raw_name):
            candidates = []
            for label in ["Project", "Component", "Material", "Process", "Certification", "Department", "Partner", "Lesson_Learned"]:
                matched, score = resolve_entity_name(label, raw_name, 45)
                if matched:
                    candidates.append({
                        "label": label,
                        "name": matched,
                        "score": score
                    })

            if not candidates:
                return None

            candidates.sort(key=lambda x: x["score"], reverse=True)
            return candidates[0]

        source_resolved = resolve_any_entity(source_entity)
        target_resolved = resolve_any_entity(target_entity)

        if not source_resolved or not target_resolved:
            return {
                "graph_result": [{
                    "query_type": "relation_query",
                    "found": False,
                    "message": f"無法解析查詢對象：{source_entity} 或 {target_entity}",
                    "source_input": source_entity,
                    "target_input": target_entity,
                    "source_suggestion": source_resolved,
                    "target_suggestion": target_resolved
                }],
                "debug": debug_info
            }

        q = """
        MATCH (a)-[r]-(b)
        WHERE coalesce(a.name, a.title) = $source
        AND coalesce(b.name, b.title) = $target
        WITH a, b, r
        RETURN
            coalesce(a.name, a.title) AS source,
            labels(a) AS source_labels,
            type(r) AS relation_type,
            coalesce(b.name, b.title) AS target,
            labels(b) AS target_labels
        LIMIT $limit
        """

        result = run_cypher(q, {
            "source": source_resolved["name"],
            "target": target_resolved["name"],
            "limit": limit
        })

        enriched = []

        for row in result:
            rel_type = row.get("relation_type")
            meta = RELATION_META.get(rel_type, {})

            enriched.append({
                "query_type": "relation_query",
                "found": True,
                "source_input": source_entity,
                "target_input": target_entity,
                "source_resolved": source_resolved,
                "target_resolved": target_resolved,
                "source": row.get("source"),
                "source_labels": row.get("source_labels"),
                "target": row.get("target"),
                "target_labels": row.get("target_labels"),
                "relation_type": rel_type,
                "display_name": meta.get("display_name", rel_type),
                "category": meta.get("category", "unknown"),
                "description": meta.get("description", ""),
                "sentence": f"{row.get('source')} --[{rel_type}]--> {row.get('target')}（{meta.get('display_name', rel_type)}）"
            })

        if not enriched:
            return {
                "graph_result": [{
                    "query_type": "relation_query",
                    "found": False,
                    "source_input": source_entity,
                    "target_input": target_entity,
                    "source_resolved": source_resolved,
                    "target_resolved": target_resolved,
                    "message": f"已解析為 {source_resolved['name']} 與 {target_resolved['name']}，但查不到兩者之間的直接關係"
                }],
                "debug": debug_info
            }

        return {
            "graph_result": enriched,
            "debug": debug_info
        }
    if intent == "compare_entities" and len(compare_targets) >= 2:
        resolved_targets = []
        for t in compare_targets[:2]:
            for label in ["Project", "Component", "Material", "Process"]:
                matched, _ = resolve_entity_name(label, t, 50)
                if matched:
                    resolved_targets.append(matched)
                    break

        if len(resolved_targets) < 2:
            return {"graph_result": [{"message": "無法解析比較對象"}], "debug": debug_info}

        q = """
        MATCH (n)
        WHERE n.name IN $targets
        OPTIONAL MATCH (n)-[r]-(m)
        RETURN n.name AS entity,
               labels(n) AS labels,
               collect(DISTINCT type(r)) AS relations,
               collect(DISTINCT m.name)[0..10] AS neighbors
        """
        return {"graph_result": run_cypher(q, {"targets": resolved_targets}), "debug": debug_info}

    return {
        "graph_result": [{"message": "查詢條件不足，或此類查詢目前尚未支援。"}],
        "debug": debug_info
    }


# ==============================================================================
# 11. Test Helper
# ==============================================================================
def test_neo4j():
    result = run_cypher("MATCH (n) RETURN count(n) AS node_count")
    rels = run_cypher("MATCH ()-[r]->() RETURN count(r) AS rel_count")
    return {
        "success": True,
        "node_count": result[0]["node_count"],
        "rel_count": rels[0]["rel_count"]
    }
