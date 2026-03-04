#!/usr/bin/env python3
"""
Atomic Memory v2.1 — Ranked Search Evaluation
Compare keyword-only vs hybrid+ranked search on 50 queries.
Target: precision@5 > 0.70 for ranked search.
"""

import json
import sys
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path

SERVICE_URL = "http://127.0.0.1:3849"
VECTORDB_DIR = Path.home() / ".claude" / "memory" / "_vectordb"

# ═══════════════════════════════════════════════════════════════════════════════
# Atom Registry — 15 atoms across 3 layers (copied from MEMORY.md files)
# ═══════════════════════════════════════════════════════════════════════════════

ATOM_REGISTRY = {
    # ── Global Layer ──
    "preferences": {
        "triggers": ["偏好", "風格", "習慣", "style", "preference", "語言", "回應"],
        "layer": "global",
        "raw_name": "preferences",
    },
    "decisions": {
        "triggers": ["全域決策", "工具", "工作流", "workflow", "設定", "config",
                      "記住", "mcp", "瀏覽器", "guardian", "hooks"],
        "layer": "global",
        "raw_name": "decisions",
    },
    "excel-tools": {
        "triggers": ["excel", "xls", "xlsx", "讀取", "試算表", "spreadsheet",
                      "openpyxl", "xlrd"],
        "layer": "global",
        "raw_name": "excel-tools",
    },
    "rag-vector-plan": {
        "triggers": ["rag", "vector", "向量", "embedding", "語意", "semantic",
                      "lancedb", "ollama", "本地llm", "local llm",
                      "sentence-transformers", "qwen3-embedding", "bge-m3"],
        "layer": "global",
        "raw_name": "rag-vector-plan",
    },
    # ── OpenClaw / c-- ──
    "oc-decisions": {
        "triggers": ["config", "安全", "升級", "install", "平台整合", "security", "sandbox"],
        "layer": "project:c--",
        "raw_name": "decisions",
    },
    "oc-pitfalls": {
        "triggers": ["error", "錯誤", "失敗", "異常", "不生效", "crash", "找不到"],
        "layer": "project:c--",
        "raw_name": "pitfalls",
    },
    "bridge": {
        "triggers": ["bridge", "computer-use", "line→claude", "桌面操作", "mcp", "plugin"],
        "layer": "project:c--",
        "raw_name": "bridge",
    },
    # ── SGI / c--Projects ──
    "architecture": {
        "triggers": ["port", "path", "路徑", "build", "建置", "deploy", "部署",
                      "set.xml", "進入點", "架構", "伺服器"],
        "layer": "project:c--Projects",
        "raw_name": "architecture",
    },
    "server_services": {
        "triggers": ["服務", "service", "gmserver", "guild", "navigate", "心跳",
                      "handler數", "微服務清單"],
        "layer": "project:c--Projects",
        "raw_name": "server_services",
    },
    "client_main": {
        "triggers": ["main", "主工程", "framework", "thirdparty", "assetbundle",
                      "map", "passlevel", "scene", "connectorbase"],
        "layer": "project:c--Projects",
        "raw_name": "client_main",
    },
    "client_il": {
        "triggers": ["il", "ilruntime", "熱修", "module", "modulequery", "uiwnd",
                      "packhandler", "sendhandler", "notify"],
        "layer": "project:c--Projects",
        "raw_name": "client_il",
    },
    "sgi-pitfalls": {
        "triggers": ["陷阱", "bug", "重入", "靜態", "crash", "protobuf", "泛型",
                      "handler", "修復", "健檢"],
        "layer": "project:c--Projects",
        "raw_name": "pitfalls",
    },
    "todo": {
        "triggers": ["待辦", "todo", "進度", "排程", "去protobuf", "merge", "偏好", "優先"],
        "layer": "project:c--Projects",
        "raw_name": "todo",
    },
    "sgi-decisions": {
        "triggers": ["決策", "重構", "簡化", "健檢", "風險", "安全", "lambda", "過度工程"],
        "layer": "project:c--Projects",
        "raw_name": "Extra_Efficiently_TokenSafe",
    },
    "tooling": {
        "triggers": ["redmine", "excel", "產檔", "工具", "form", "designdoc",
                      "規格書", "api key", "exceltodata", "資料表", "匯出", "sgi-analysis"],
        "layer": "project:c--Projects",
        "raw_name": "tooling",
    },
}

# Reverse mapping: (layer, raw_name) → unique ID
_LAYER_NAME_TO_ID = {}
for uid, info in ATOM_REGISTRY.items():
    _LAYER_NAME_TO_ID[(info["layer"], info["raw_name"])] = uid

# c--Projects-sgi-server is a subset of c--Projects — map to same IDs
_LAYER_ALIASES = {
    "project:c--Projects-sgi-server": "project:c--Projects",
}
# Also alias sgi-pitfalls (filename differs between the two project layers)
_NAME_ALIASES = {
    "sgi-pitfalls": "pitfalls",  # c--Projects-sgi-server uses sgi-pitfalls.md
}


def _map_api_result(layer: str, atom_name: str) -> str:
    """Map ranked search API result back to unique atom ID."""
    # Direct match
    key = (layer, atom_name)
    if key in _LAYER_NAME_TO_ID:
        return _LAYER_NAME_TO_ID[key]
    # Try layer alias
    aliased_layer = _LAYER_ALIASES.get(layer, layer)
    key2 = (aliased_layer, atom_name)
    if key2 in _LAYER_NAME_TO_ID:
        return _LAYER_NAME_TO_ID[key2]
    # Try name alias
    aliased_name = _NAME_ALIASES.get(atom_name, atom_name)
    key3 = (aliased_layer, aliased_name)
    if key3 in _LAYER_NAME_TO_ID:
        return _LAYER_NAME_TO_ID[key3]
    return f"?{layer}:{atom_name}"


# ═══════════════════════════════════════════════════════════════════════════════
# Intent Classifier (replicated from workflow-guardian.py:268-287)
# ═══════════════════════════════════════════════════════════════════════════════

INTENT_PATTERNS = {
    "debug": ["crash", "error", "bug", "失敗", "壞", "exception", "為什麼",
              "why", "問題", "traceback", "報錯", "修復", "fix"],
    "build": ["build", "deploy", "建置", "部署", "安裝", "install", "啟動",
              "setup", "config", "設定", "配置", "環境"],
    "design": ["設計", "架構", "design", "architecture", "重構", "refactor",
               "新增", "planning", "實作", "implement", "方案"],
    "recall": ["之前", "上次", "記得", "決策", "決定", "為什麼選",
               "remember", "previous", "history"],
}


def classify_intent(prompt: str) -> str:
    prompt_lower = prompt.lower()
    scores = {}
    for intent, keywords in INTENT_PATTERNS.items():
        scores[intent] = sum(1 for kw in keywords if kw in prompt_lower)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"


# ═══════════════════════════════════════════════════════════════════════════════
# 50 Test Queries
# ═══════════════════════════════════════════════════════════════════════════════

QUERIES = [
    # ── debug (10) ──────────────────────────────────────────────────────────
    {"id": "D01", "q": "MapServer crash 重入問題怎麼修", "intent": "debug",
     "ground_truth": ["sgi-pitfalls"], "category": "direct_keyword"},
    {"id": "D02", "q": "OpenClaw 啟動失敗 npm error", "intent": "debug",
     "ground_truth": ["oc-pitfalls"], "category": "direct_keyword"},
    {"id": "D03", "q": "為什麼玩家登入後收到不正確的背包資料", "intent": "debug",
     "ground_truth": ["sgi-pitfalls", "architecture"], "category": "semantic_only"},
    {"id": "D04", "q": "static cache concurrency bug in game server", "intent": "debug",
     "ground_truth": ["sgi-pitfalls"], "category": "cross_language"},
    {"id": "D05", "q": "Protobuf Handler 壞掉 exception 追不到", "intent": "debug",
     "ground_truth": ["sgi-pitfalls"], "category": "direct_keyword"},
    {"id": "D06", "q": "語意搜尋回傳空結果，向量服務連不上", "intent": "debug",
     "ground_truth": ["rag-vector-plan"], "category": "direct_keyword"},
    {"id": "D07", "q": "MCP server 錯誤 JSONL 格式不對 timeout", "intent": "debug",
     "ground_truth": ["decisions", "bridge"], "category": "direct_keyword"},
    {"id": "D08", "q": "React component rendering loop infinite re-render", "intent": "debug",
     "ground_truth": [], "category": "negative"},
    {"id": "D09", "q": "遊戲伺服器記憶體洩漏問題排查", "intent": "debug",
     "ground_truth": ["sgi-pitfalls", "architecture"], "category": "semantic_only"},
    {"id": "D10", "q": "guardian hook 沒有觸發 sync 閘門壞了", "intent": "debug",
     "ground_truth": ["decisions"], "category": "direct_keyword"},

    # ── build (10) ──────────────────────────────────────────────────────────
    {"id": "B01", "q": "SGI server 建置步驟和 deploy 流程", "intent": "build",
     "ground_truth": ["architecture"], "category": "direct_keyword"},
    {"id": "B02", "q": "新機器怎麼安裝 Ollama 環境和 config 設定", "intent": "build",
     "ground_truth": ["rag-vector-plan", "decisions"], "category": "direct_keyword"},
    {"id": "B03", "q": "怎麼讀 .xlsx 試算表 需要裝什麼套件", "intent": "build",
     "ground_truth": ["excel-tools"], "category": "direct_keyword"},
    {"id": "B04", "q": "how to compile and run the .NET Core game server project", "intent": "build",
     "ground_truth": ["architecture"], "category": "cross_language"},
    {"id": "B05", "q": "install OpenClaw 安裝步驟和 npm 設定", "intent": "build",
     "ground_truth": ["oc-decisions"], "category": "direct_keyword"},
    {"id": "B06", "q": "LanceDB vector embedding 索引怎麼建", "intent": "build",
     "ground_truth": ["rag-vector-plan"], "category": "direct_keyword"},
    {"id": "B07", "q": "各服務的 port 號碼和啟動順序", "intent": "build",
     "ground_truth": ["architecture", "server_services"], "category": "direct_keyword"},
    {"id": "B08", "q": "Kubernetes cluster 要怎麼配置 pod auto-scaling", "intent": "build",
     "ground_truth": [], "category": "negative"},
    {"id": "B09", "q": "企劃表轉換產檔流程 ExcelToData", "intent": "build",
     "ground_truth": ["tooling"], "category": "direct_keyword"},
    {"id": "B10", "q": "setup custom MCP server with JSONL protocol transport", "intent": "build",
     "ground_truth": ["decisions"], "category": "cross_language"},

    # ── design (10) ─────────────────────────────────────────────────────────
    {"id": "E01", "q": "SGI 架構設計 微服務之間怎麼溝通", "intent": "design",
     "ground_truth": ["architecture", "server_services"], "category": "direct_keyword"},
    {"id": "E02", "q": "原子記憶系統的 hybrid search 怎麼設計的", "intent": "design",
     "ground_truth": ["rag-vector-plan"], "category": "semantic_only"},
    {"id": "E03", "q": "之前的重構簡化決策 過度工程判斷標準", "intent": "design",
     "ground_truth": ["sgi-decisions", "preferences"], "category": "direct_keyword"},
    {"id": "E04", "q": "design pattern for TCP packet handler in game server", "intent": "design",
     "ground_truth": ["architecture", "sgi-decisions"], "category": "cross_language"},
    {"id": "E05", "q": "session 同步流程的設計邏輯", "intent": "design",
     "ground_truth": ["decisions"], "category": "semantic_only"},
    {"id": "E06", "q": "寫程式的風格規範和框架選擇原則", "intent": "design",
     "ground_truth": ["preferences"], "category": "direct_keyword"},
    {"id": "E07", "q": "MysqlxCache 資料存取層的快取策略", "intent": "design",
     "ground_truth": ["architecture"], "category": "semantic_only"},
    {"id": "E08", "q": "設計 REST API 的 GraphQL schema 遷移", "intent": "design",
     "ground_truth": [], "category": "negative"},
    {"id": "E09", "q": "Unity client 的 ILRuntime 熱修模組怎麼設計", "intent": "design",
     "ground_truth": ["client_il"], "category": "direct_keyword"},
    {"id": "E10", "q": "LINE to Claude Code integration architecture and plugin design", "intent": "design",
     "ground_truth": ["bridge"], "category": "cross_language"},

    # ── recall (10) ─────────────────────────────────────────────────────────
    {"id": "R01", "q": "之前決定 Handler 為什麼不能用 lambda", "intent": "recall",
     "ground_truth": ["sgi-decisions", "preferences"], "category": "direct_keyword"},
    {"id": "R02", "q": "上次怎麼設定 workflow guardian 的", "intent": "recall",
     "ground_truth": ["decisions"], "category": "direct_keyword"},
    {"id": "R03", "q": "記得之前分析過什麼安全問題嗎", "intent": "recall",
     "ground_truth": ["sgi-decisions", "oc-decisions"], "category": "direct_keyword"},
    {"id": "R04", "q": "what was the previous decision about ChromaDB vs LanceDB", "intent": "recall",
     "ground_truth": ["rag-vector-plan"], "category": "cross_language"},
    {"id": "R05", "q": "之前為什麼選 qwen3 不用其他模型", "intent": "recall",
     "ground_truth": ["rag-vector-plan"], "category": "semantic_only"},
    {"id": "R06", "q": "記住的偏好設定有哪些 列出來", "intent": "recall",
     "ground_truth": ["preferences", "decisions"], "category": "direct_keyword"},
    {"id": "R07", "q": "之前遇過什麼坑 處理方式是什麼", "intent": "recall",
     "ground_truth": ["sgi-pitfalls", "oc-pitfalls"], "category": "semantic_only"},
    {"id": "R08", "q": "remember the PostgreSQL migration we did last year", "intent": "recall",
     "ground_truth": [], "category": "negative"},
    {"id": "R09", "q": "之前 browser-use 為什麼換成 playwright", "intent": "recall",
     "ground_truth": ["decisions"], "category": "semantic_only"},
    {"id": "R10", "q": "上次讀取 Excel 用了什麼指令和參數", "intent": "recall",
     "ground_truth": ["excel-tools"], "category": "direct_keyword"},

    # ── general (10) ────────────────────────────────────────────────────────
    {"id": "G01", "q": "workflow guardian 現在的運作方式", "intent": "general",
     "ground_truth": ["decisions"], "category": "direct_keyword"},
    {"id": "G02", "q": "openpyxl 可以做什麼 spreadsheet 操作", "intent": "general",
     "ground_truth": ["excel-tools"], "category": "direct_keyword"},
    {"id": "G03", "q": "原子記憶系統整體概覽和功能", "intent": "general",
     "ground_truth": ["rag-vector-plan"], "category": "semantic_only"},
    {"id": "G04", "q": "what are the coding style preferences for this project", "intent": "general",
     "ground_truth": ["preferences"], "category": "cross_language"},
    {"id": "G05", "q": "MCP 相關的所有知識和設定", "intent": "general",
     "ground_truth": ["decisions", "bridge"], "category": "direct_keyword"},
    {"id": "G06", "q": "GmServer 的 handler 數量和功能", "intent": "general",
     "ground_truth": ["server_services"], "category": "direct_keyword"},
    {"id": "G07", "q": "這個 AI 助手能幫我做什麼事情", "intent": "general",
     "ground_truth": ["preferences", "decisions"], "category": "semantic_only"},
    {"id": "G08", "q": "tell me about the weather in Taipei today", "intent": "general",
     "ground_truth": [], "category": "negative"},
    {"id": "G09", "q": "Redmine API 怎麼查 issue 和規格書在哪", "intent": "general",
     "ground_truth": ["tooling"], "category": "direct_keyword"},
    {"id": "G10", "q": "describe the computer-use MCP and desktop automation capabilities", "intent": "general",
     "ground_truth": ["bridge", "decisions"], "category": "cross_language"},
]


# ═══════════════════════════════════════════════════════════════════════════════
# Keyword-Only Simulator
# ═══════════════════════════════════════════════════════════════════════════════

def simulate_keyword_match(query: str) -> list:
    """Replicate exact keyword trigger logic from workflow-guardian.py."""
    prompt_lower = query.lower()
    matched = []
    for uid, info in ATOM_REGISTRY.items():
        if any(kw in prompt_lower for kw in info["triggers"]):
            matched.append(uid)
    return matched


# ═══════════════════════════════════════════════════════════════════════════════
# Ranked Search HTTP Client
# ═══════════════════════════════════════════════════════════════════════════════

def health_check() -> bool:
    try:
        req = urllib.request.Request(f"{SERVICE_URL}/health")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return data.get("status") == "ok"
    except Exception:
        return False


def ranked_search(query: str, intent: str, top_k: int = 5,
                  min_score: float = 0.50) -> list:
    """Call GET /search/ranked and return list of unique atom IDs."""
    params = urllib.parse.urlencode({
        "q": query, "intent": intent, "top_k": top_k,
        "min_score": min_score, "layer": "all",
    })
    url = f"{SERVICE_URL}/search/ranked?{params}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            results = json.loads(resp.read())
            mapped = []
            seen = set()
            for r in results:
                uid = _map_api_result(r.get("layer", ""), r.get("atom_name", ""))
                if uid not in seen:
                    seen.add(uid)
                    mapped.append({
                        "uid": uid,
                        "final_score": r.get("final_score", 0),
                        "score": r.get("score", 0),
                        "breakdown": r.get("score_breakdown", {}),
                    })
            return mapped
    except Exception as e:
        return [{"error": str(e)}]


# ═══════════════════════════════════════════════════════════════════════════════
# Metrics
# ═══════════════════════════════════════════════════════════════════════════════

def precision_at_k(retrieved: list, relevant: list, k: int = 5) -> float:
    top = retrieved[:k]
    if not top:
        return 1.0 if not relevant else 0.0
    hits = sum(1 for r in top if r in relevant)
    return hits / len(top)


def recall_at_k(retrieved: list, relevant: list, k: int = 5) -> float:
    if not relevant:
        return 1.0
    top = retrieved[:k]
    hits = sum(1 for r in relevant if r in top)
    return hits / len(relevant)


def f1(p: float, r: float) -> float:
    return 2 * p * r / (p + r) if (p + r) > 0 else 0.0


def hit_at_k(retrieved: list, relevant: list, k: int = 5) -> float:
    """1.0 if any relevant item in top-k, else 0.0. For negative cases: 1.0 if empty."""
    if not relevant:
        return 1.0 if not retrieved[:k] else 0.0
    top = set(retrieved[:k])
    return 1.0 if top & set(relevant) else 0.0


def mrr(retrieved: list, relevant: list) -> float:
    """Mean Reciprocal Rank: 1/(rank of first relevant result)."""
    if not relevant:
        return 1.0 if not retrieved else 0.0
    for i, r in enumerate(retrieved):
        if r in relevant:
            return 1.0 / (i + 1)
    return 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Evaluation Runner
# ═══════════════════════════════════════════════════════════════════════════════

def run_evaluation(top_k: int = 5, min_score: float = 0.50) -> dict:
    service_ok = health_check()
    results = []

    for q in QUERIES:
        gt = q["ground_truth"]
        auto_intent = classify_intent(q["q"])

        # Keyword-only
        kw_matched = simulate_keyword_match(q["q"])
        kw_p = precision_at_k(kw_matched, gt, top_k)
        kw_r = recall_at_k(kw_matched, gt, top_k)

        # Ranked search
        if service_ok:
            rk_raw = ranked_search(q["q"], auto_intent, top_k, min_score)
            if rk_raw and "error" in rk_raw[0]:
                rk_names = []
                rk_detail = rk_raw
            else:
                rk_names = [r["uid"] for r in rk_raw]
                rk_detail = rk_raw
        else:
            rk_names = []
            rk_detail = [{"error": "service_unavailable"}]

        rk_p = precision_at_k(rk_names, gt, top_k)
        rk_r = recall_at_k(rk_names, gt, top_k)

        # Hybrid: keyword results first (priority), then ranked supplement (dedup)
        hybrid = list(kw_matched)
        for name in rk_names:
            if name not in hybrid:
                hybrid.append(name)
        hy_p = precision_at_k(hybrid, gt, top_k)
        hy_r = recall_at_k(hybrid, gt, top_k)

        kw_f1 = f1(kw_p, kw_r)
        rk_f1 = f1(rk_p, rk_r)
        hy_f1 = f1(hy_p, hy_r)

        # Winner by F1: hybrid vs keyword vs ranked
        scores = {"KW": kw_f1, "RK": rk_f1, "HY": hy_f1}
        best = max(scores, key=scores.get)
        winner = best if scores[best] > 0 else "TIE"
        if all(v == scores[best] for v in scores.values()):
            winner = "TIE"

        results.append({
            "id": q["id"],
            "query": q["q"],
            "intent_labeled": q["intent"],
            "intent_auto": auto_intent,
            "category": q["category"],
            "ground_truth": gt,
            "keyword": {"retrieved": kw_matched, "P@5": kw_p, "R@5": kw_r, "F1": kw_f1,
                        "Hit@5": hit_at_k(kw_matched, gt, top_k), "MRR": mrr(kw_matched, gt)},
            "ranked": {"retrieved": rk_names, "detail": rk_detail,
                       "P@5": rk_p, "R@5": rk_r, "F1": rk_f1,
                       "Hit@5": hit_at_k(rk_names, gt, top_k), "MRR": mrr(rk_names, gt)},
            "hybrid": {"retrieved": hybrid, "P@5": hy_p, "R@5": hy_r, "F1": hy_f1,
                       "Hit@5": hit_at_k(hybrid, gt, top_k), "MRR": mrr(hybrid, gt)},
            "winner": winner,
        })

    return {"service_healthy": service_ok, "top_k": top_k,
            "min_score": min_score, "results": results}


# ═══════════════════════════════════════════════════════════════════════════════
# Report Formatting
# ═══════════════════════════════════════════════════════════════════════════════

def _avg(values: list) -> float:
    return sum(values) / len(values) if values else 0.0


def print_report(data: dict):
    results = data["results"]
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print(f"\n{'=' * 100}")
    print(f"  Ranked Search Evaluation — {ts}")
    print(f"  Service: {SERVICE_URL}  |  Healthy: {data['service_healthy']}")
    print(f"  Queries: {len(results)}  |  top_k: {data['top_k']}  |  min_score: {data['min_score']}")
    print(f"{'=' * 100}")

    # Per-query table
    hdr = f"{'ID':<5} {'Cat':<10} {'KW R@5':>7} {'RK R@5':>7} {'HY R@5':>7} {'HY Hit':>6} {'HY MRR':>6} {'Win':>4}"
    print(f"\n{hdr}")
    print("─" * len(hdr))
    for r in results:
        kw, rk, hy = r["keyword"], r["ranked"], r["hybrid"]
        print(f"{r['id']:<5} {r['category'][:10]:<10} "
              f"{kw['R@5']:>7.2f} {rk['R@5']:>7.2f} {hy['R@5']:>7.2f} "
              f"{hy['Hit@5']:>6.0f} {hy['MRR']:>6.2f} {r['winner']:>4}")

    # Aggregate — 3 systems
    def _metrics(key):
        return {
            "P@5": _avg([r[key]["P@5"] for r in results]),
            "R@5": _avg([r[key]["R@5"] for r in results]),
            "F1":  _avg([r[key]["F1"] for r in results]),
            "Hit@5": _avg([r[key]["Hit@5"] for r in results]),
            "MRR": _avg([r[key]["MRR"] for r in results]),
        }

    km = _metrics("keyword")
    rm = _metrics("ranked")
    hm = _metrics("hybrid")

    print(f"\n{'═' * 65}")
    print(f"  AGGREGATE ({len(results)} queries)")
    print(f"{'═' * 65}")
    print(f"  {'':12} {'Keyword':>12} {'Ranked':>12} {'Hybrid':>12}")
    for m in ["P@5", "R@5", "F1", "Hit@5", "MRR"]:
        print(f"  {m:12} {km[m]:>12.4f} {rm[m]:>12.4f} {hm[m]:>12.4f}")

    # By intent
    print(f"\n{'═' * 65}")
    print(f"  BY INTENT")
    print(f"{'═' * 65}")
    for intent in ["debug", "build", "design", "recall", "general"]:
        sub = [r for r in results if r["intent_labeled"] == intent]
        kr = _avg([r["keyword"]["R@5"] for r in sub])
        rr = _avg([r["ranked"]["R@5"] for r in sub])
        hr = _avg([r["hybrid"]["R@5"] for r in sub])
        hh = _avg([r["hybrid"]["Hit@5"] for r in sub])
        print(f"  {intent:<10} ({len(sub):>2})   KW R={kr:.2f}  RK R={rr:.2f}  HY R={hr:.2f}  HY Hit={hh:.2f}")

    # By category
    print(f"\n{'═' * 65}")
    print(f"  BY CATEGORY")
    print(f"{'═' * 65}")
    for cat in ["direct_keyword", "semantic_only", "cross_language", "negative"]:
        sub = [r for r in results if r["category"] == cat]
        if not sub:
            continue
        kr = _avg([r["keyword"]["R@5"] for r in sub])
        rr = _avg([r["ranked"]["R@5"] for r in sub])
        hr = _avg([r["hybrid"]["R@5"] for r in sub])
        hh = _avg([r["hybrid"]["Hit@5"] for r in sub])
        print(f"  {cat:<18} ({len(sub):>2})   KW R={kr:.2f}  RK R={rr:.2f}  HY R={hr:.2f}  HY Hit={hh:.2f}")

    # Wins
    kw_wins = sum(1 for r in results if r["winner"] == "KW")
    rk_wins = sum(1 for r in results if r["winner"] == "RK")
    hy_wins = sum(1 for r in results if r["winner"] == "HY")
    ties = sum(1 for r in results if r["winner"] == "TIE")
    print(f"\n{'═' * 65}")
    print(f"  WINS:  KW={kw_wins}  RK={rk_wins}  HY={hy_wins}  TIE={ties}")
    print(f"{'═' * 65}")

    # Target checks
    print(f"\n  TARGETS:")
    hy_hit = hm["Hit@5"]
    hy_r = hm["R@5"]
    hy_mrr = hm["MRR"]
    print(f"    Hybrid Hit@5  > 0.85 — {'PASS' if hy_hit > 0.85 else 'FAIL'} (actual: {hy_hit:.4f})")
    print(f"    Hybrid R@5    > 0.80 — {'PASS' if hy_r > 0.80 else 'FAIL'} (actual: {hy_r:.4f})")
    print(f"    Hybrid MRR    > 0.70 — {'PASS' if hy_mrr > 0.70 else 'FAIL'} (actual: {hy_mrr:.4f})")
    # Semantic-only R@5 improvement (ranked vs keyword)
    sem_sub = [r for r in results if r["category"] == "semantic_only"]
    sem_kw_r = _avg([r["keyword"]["R@5"] for r in sem_sub])
    sem_hy_r = _avg([r["hybrid"]["R@5"] for r in sem_sub])
    print(f"    Semantic-only: KW R@5={sem_kw_r:.2f} → HY R@5={sem_hy_r:.2f} (delta: +{sem_hy_r-sem_kw_r:.2f})")

    # Intent classifier agreement
    agree = sum(1 for r in results if r["intent_labeled"] == r["intent_auto"])
    print(f"    Intent Classifier Agreement: {agree}/{len(results)} ({agree/len(results)*100:.0f}%)")
    print()


def save_json(data: dict, output_path: Path = None):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if output_path is None:
        VECTORDB_DIR.mkdir(parents=True, exist_ok=True)
        output_path = VECTORDB_DIR / f"eval-results-{ts}.json"

    # Clean detail for JSON (remove large breakdowns for readability)
    export = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "service_url": SERVICE_URL,
            "service_healthy": data["service_healthy"],
            "top_k": data["top_k"],
            "min_score": data["min_score"],
            "total_queries": len(data["results"]),
        },
        "per_query": data["results"],
        "aggregate": {
            sys_name: {
                "avg_precision": _avg([r[sys_name]["P@5"] for r in data["results"]]),
                "avg_recall": _avg([r[sys_name]["R@5"] for r in data["results"]]),
                "avg_f1": _avg([r[sys_name]["F1"] for r in data["results"]]),
                "avg_hit5": _avg([r[sys_name]["Hit@5"] for r in data["results"]]),
                "avg_mrr": _avg([r[sys_name]["MRR"] for r in data["results"]]),
            }
            for sys_name in ["keyword", "ranked", "hybrid"]
        },
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(export, f, ensure_ascii=False, indent=2)
    print(f"  Results saved to: {output_path}")
    return output_path


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Evaluate ranked search vs keyword-only")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-score", type=float, default=0.50)
    parser.add_argument("--output", type=str, default=None,
                        help="Output JSON path (default: _vectordb/eval-results-{ts}.json)")
    parser.add_argument("--queries-only", action="store_true",
                        help="Just print the query list and exit")
    args = parser.parse_args()

    if args.queries_only:
        for q in QUERIES:
            print(f"{q['id']:5} [{q['intent']:<7}] [{q['category']:<16}] {q['q']}")
            print(f"      GT: {q['ground_truth']}")
        return

    data = run_evaluation(top_k=args.top_k, min_score=args.min_score)
    print_report(data)
    out = Path(args.output) if args.output else None
    save_json(data, out)


if __name__ == "__main__":
    main()
