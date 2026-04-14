# ONE-OFF: 一次性測試腳本，非常規工具
"""
ab_gemma4_round3.py — 第三輪 A/B 驗證：多題型測試

題型：
  A. 遊戲 Client 架構知識（ILRuntime、Prefab、元件 GUID）
  B. 踩坑/陷阱記錄（Bug 模式、重入風險、靜態殘留）
  C. 企業流程自動化（eHRM 加班單、CDP、篩選規則）
  D. 記憶系統自身架構（Hooks、模組拆分、管線）
  E. 混合長文（多主題交錯）
  F. 高密度數據（大量數字、路徑、版本號）

每題型：5 模型各跑 1 次，附 ground-truth recall 種子

用法：python3 tools/ab_gemma4_round3.py
"""

import json
import sys
import time
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ollama_client import get_client  # noqa: E402

CLAUDE_DIR = Path.home() / ".claude"
VALID_TYPES = {"factual", "procedural", "architectural", "pitfall", "decision"}

# ── 共用函式 ──────────────────────────────────────────────────────────────

_SYSTEM_CONTEXT = (
    "你是「原子記憶系統」的知識萃取器。萃取出的知識會存入長期記憶，供未來 session 引用。\n"
    "只萃取「這個專案/環境特有的」、「下次會用到的」事實。通用程式知識不要。\n\n"
)
_FORMAT_SPEC = (
    '輸出 JSON array: [{{"content": "精簡事實，最多150字", '
    '"type": "factual|procedural|architectural|pitfall|decision"}}]\n\n'
    "範例（值得萃取）:\n"
    '  {{"content": "PackHandler 66 個僅 2 個有 try-catch，P0 風險", "type": "pitfall"}}\n'
    '  {{"content": "eHRM OT 結束 < 19:00 的加班紀錄跳過不填", "type": "procedural"}}\n\n'
    "範例（不要萃取）:\n"
    '  ✗ "C# 的 static 變數在 AppDomain 卸載前不會被 GC" → 通用知識\n'
    '  ✗ "已修改 config.py 第 43 行" → session 進度\n\n'
)
_RULES_COMMON = (
    "規則:\n"
    "- 只萃取此專案/環境特有的具體事實（含數值、路徑、版本、錯誤碼）\n"
    "- 跳過：程式碼片段、session 進度、隨便 Google 就能查到的知識\n"
    "- 沒有值得萃取的內容就輸出 []\n"
    "- 直接輸出 JSON，不要解釋\n\n"
)

def build_prompt(text: str, max_input: int = 4000) -> str:
    return _SYSTEM_CONTEXT + _FORMAT_SPEC + _RULES_COMMON + f"Session 文字:\n{text[:max_input]}\n\nJSON:"

def call_model(client, model_name, prompt, think=True, temperature=0.0, timeout=240):
    backend = None
    for b in client._backends:
        if b.name == "rdchat-direct":
            backend = b
            break
    if not backend:
        return None, 0.0, "no rdchat backend"
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": think,
        "options": {"temperature": temperature, "num_predict": 4096},
    }
    t0 = time.time()
    try:
        result = client._do_request(backend, "/api/chat", payload, timeout)
    except Exception as e:
        return None, time.time() - t0, str(e)
    elapsed = time.time() - t0
    if result is None:
        return None, elapsed, "null response"
    return result.get("message", {}).get("content", ""), elapsed, None

def parse_json_response(raw):
    if not raw:
        return None, "empty response"
    text = raw.strip()
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        return None, "no JSON array found"
    try:
        arr = json.loads(text[start:end+1])
        return (arr, None) if isinstance(arr, list) else (None, "not a list")
    except json.JSONDecodeError as e:
        return None, f"JSON parse error: {e}"

def _check_grounding(content, source_text):
    tokens = re.findall(r'[a-zA-Z_][\w.-]{2,}|[\d]+(?:\.[\d]+)*|\S+/\S+', content)
    if not tokens:
        return True
    found = sum(1 for t in tokens if t.lower() in source_text.lower())
    return found / len(tokens) >= 0.4

def analyze_items(items, source_text=""):
    if not items:
        return {"count": 0, "avg_length": 0, "type_dist": {}, "specificity": "0/0",
                "type_compliance": "N/A", "grounded": "N/A", "schema_valid": "N/A",
                "hallucinated": 0, "over_150": 0}
    types, lengths = {}, []
    specific_count = valid_type_count = schema_valid_count = 0
    grounded_count = hallucinated_count = over_150 = 0

    for item in items:
        has_c = isinstance(item.get("content"), str) and len(item["content"]) > 0
        has_t = isinstance(item.get("type"), str)
        if has_c and has_t:
            schema_valid_count += 1
        t = item.get("type", "unknown")
        types[t] = types.get(t, 0) + 1
        if t in VALID_TYPES:
            valid_type_count += 1
        c = item.get("content", "")
        lengths.append(len(c))
        if len(c) > 150:
            over_150 += 1
        if any(ch.isdigit() for ch in c) or "/" in c or "\\" in c:
            specific_count += 1
        if source_text and c:
            if _check_grounding(c, source_text):
                grounded_count += 1
            else:
                hallucinated_count += 1

    n = len(items)
    return {
        "count": n,
        "avg_length": round(sum(lengths) / n, 1),
        "type_dist": types,
        "specificity": f"{specific_count}/{n}",
        "type_compliance": f"{valid_type_count}/{n}",
        "schema_valid": f"{schema_valid_count}/{n}",
        "grounded": f"{grounded_count}/{n}" if source_text else "N/A",
        "hallucinated": hallucinated_count,
        "over_150": over_150,
    }

def recall_check(items, known_facts):
    if not items or not known_facts:
        return 0, len(known_facts) if known_facts else 0
    found = 0
    all_content = " ".join(item.get("content", "") for item in items).lower()
    for fact_kws in known_facts:
        if all(kw.lower() in all_content for kw in fact_kws):
            found += 1
    return found, len(known_facts)

# ── 題型定義 ──────────────────────────────────────────────────────────────

def load_file(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except Exception:
        return ""

TOPICS = []

# A: 遊戲 Client 架構
_client_il = load_file(Path.home() / ".claude" / "../../Projects/.claude/memory/client_il.md")
if _client_il:
    TOPICS.append({
        "name": "A: 遊戲Client架構",
        "text": _client_il,
        "recall_seeds": [
            {"PackHandler", "66", "try-catch"},
            {"323", "訂閱", "退訂"},
            {"ModuleQuery", "5355", "反射"},
            {"cellIdentifier", "Key", "null reference"},
            {"ILUIScrollerController", "5", "序列化"},
            {"ShrinkText", "BestFit", "m_BestFit"},
        ],
    })

# B: 踩坑紀錄
_pitfalls = load_file(Path.home() / ".claude" / "../../Projects/.claude/memory/pitfalls.md")
if _pitfalls:
    TOPICS.append({
        "name": "B: 踩坑陷阱",
        "text": _pitfalls,
        "recall_seeds": [
            {"Troops", "Clear", "Re-add"},
            {"SharedScript", "ILToMain", "16"},
            {"DesignGodBeastBuff", "GetNextOrder", "Init"},
            {"_damageBuffInProgress", "static", "殘留"},
            {"ExDamageRate", "ExHealRate", "遺漏"},
        ],
    })

# C: eHRM 加班自動化
_ehrm = load_file(Path(r"C:\tmp\office\.claude\memory\ehrm-overtime.md"))
if _ehrm:
    TOPICS.append({
        "name": "C: eHRM加班自動化",
        "text": _ehrm,
        "recall_seeds": [
            {"CDP", "9222", "Chrome"},
            {"19:00", "跳過"},
            {"MonthRec", "月報"},
            {"5", "倍數", "header"},
            {"補休", "請假日"},
        ],
    })

# D: 記憶系統架構
_arch = load_file(Path.home() / ".claude/_AIDocs/Architecture.md")
if _arch:
    TOPICS.append({
        "name": "D: 記憶系統架構",
        "text": _arch,
        "recall_seeds": [
            {"workflow-guardian", "1480", "dispatcher"},
            {"wg_atoms", "559", "trigger"},
            {"quick-extract", "qwen3", "hot_cache"},
            {"UserPromptSubmit", "RECALL", "intent"},
            {"SessionEnd", "Episodic", "鞏固"},
            {"wg_docdrift", "DocDrift"},
        ],
    })

# E: 混合長文（A + C 交錯）
if _client_il and _ehrm:
    mixed = _client_il[:2000] + "\n---以下是另一個主題---\n" + _ehrm[:2000]
    TOPICS.append({
        "name": "E: 混合長文",
        "text": mixed,
        "recall_seeds": [
            {"PackHandler", "66"},
            {"CDP", "9222"},
            {"cellIdentifier", "Key"},
            {"19:00", "跳過"},
        ],
    })

# F: 高密度數據（手工構造）
_dense = """
以下是系統核心數據摘要：
- workflow-guardian.py 共 1480 行，含 7 個 hook handler
- wg_atoms.py 559 行負責 ACT-R 激活度計算
- wg_extraction.py 295 行處理 per-turn 萃取
- extract-worker.py 806 行，LLM timeout 預設 120s
- vector service 跑在 port 3849，min_score 門檻 0.65
- LanceDB 資料存放 ~/.claude/memory/_vectordb/
- Ollama primary: rdchat 192.168.199.130:11434 (RTX 3090 24GB)
- Ollama fallback: local 127.0.0.1:11434 (GTX 1050 Ti 4GB)
- qwen3.5:latest 9.7B Q4_K_M 用於深度萃取，think=true, num_predict=8192
- qwen3:1.7b 用於 quick-extract，5s 超時
- hot_cache.json 存放 session_id + timestamp + knowledge[]
- SessionStart 去重 TTL: prompt_count=0 working→10m, prompt_count>0→30m
- 跨 session 晉升門檻: 4+ sessions 命中
- self_iteration review_interval: 每 6 個 session
- embedding 維度: qwen3-embedding 產出 1024-dim vector
"""
TOPICS.append({
    "name": "F: 高密度數據",
    "text": _dense,
    "recall_seeds": [
        {"1480", "7", "hook"},
        {"3849", "0.65"},
        {"192.168.199.130", "11434", "3090"},
        {"1.7b", "5s", "quick-extract"},
        {"hot_cache", "session_id", "knowledge"},
        {"1024", "embedding"},
    ],
})

# ── Main ──────────────────────────────────────────────────────────────────

def main():
    models = [
        ("qwen3.5:latest",      True,  0.0, "qwen3.5"),
        ("gemma4:e4b",           True,  0.0, "g4:e4b T"),
        ("gemma4:e4b",           False, 0.0, "g4:e4b F"),
        ("gemma4:e4b-it-bf16",   True,  0.0, "g4:bf16"),
        ("gemma4:26b",           True,  0.0, "g4:26b"),
    ]

    if not TOPICS:
        print("找不到任何題型素材！")
        sys.exit(1)

    client = get_client()

    print(f"{'='*70}")
    print(f"  Round 3: 多題型 A/B 驗證（{len(TOPICS)} 題型 × {len(models)} 模型）")
    print(f"{'='*70}")
    print(f"Backends: {[b.name for b in client._backends]}")
    print(f"溫度: 0.0（Round 2 結論：一致性最佳）\n")
    print(f"題型:")
    for topic in TOPICS:
        print(f"  {topic['name']} | {len(topic['text'])} chars | {len(topic['recall_seeds'])} recall seeds")
    print()

    # 收集結果
    all_data = {}

    for topic in TOPICS:
        tname = topic["name"]
        text = topic["text"]
        seeds = topic["recall_seeds"]
        source_text = text[:4000]
        prompt = build_prompt(text, max_input=4000)

        print(f"\n{'─'*70}")
        print(f"題型: {tname}")
        print(f"{'─'*70}")

        topic_results = {}
        for model_name, think, temp, label in models:
            print(f"  [{label:12s}] ", end="", flush=True)
            raw, elapsed, err = call_model(client, model_name, prompt, think=think, temperature=temp)
            if err:
                print(f"FAIL: {err}")
                topic_results[label] = {"error": err, "elapsed": elapsed}
                continue

            items, parse_err = parse_json_response(raw)
            if parse_err:
                print(f"PARSE FAIL: {parse_err} | {elapsed:.1f}s")
                topic_results[label] = {"error": parse_err, "elapsed": elapsed}
                continue

            analysis = analyze_items(items, source_text)
            analysis["elapsed"] = round(elapsed, 1)
            analysis["items"] = items

            rec_found, rec_total = recall_check(items, seeds)
            analysis["recall"] = f"{rec_found}/{rec_total}"
            analysis["recall_pct"] = round(rec_found / rec_total * 100, 1) if rec_total else 0

            topic_results[label] = analysis
            print(f"OK | {elapsed:5.1f}s | {analysis['count']:2d} items | "
                  f"grnd={analysis['grounded']} | hall={analysis['hallucinated']} | "
                  f"spec={analysis['specificity']} | recall={rec_found}/{rec_total} ({analysis['recall_pct']:.0f}%) | "
                  f"over150={analysis['over_150']}")

        all_data[tname] = topic_results
        print()

    # ══════════════════════════════════════════════════════════════════════
    # 按題型彙總
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print(f"  按題型彙總")
    print(f"{'='*70}\n")

    labels = [l for _, _, _, l in models]

    for topic in TOPICS:
        tname = topic["name"]
        tr = all_data[tname]
        print(f"### {tname}")
        header = " | ".join(f"{l:12s}" for l in labels)
        print(f"| {'維度':14s} | {header} |")
        print(f"|{'-'*16}|" + "|".join("-"*14 for _ in labels) + "|")

        def _val(label, key, default="N/A"):
            r = tr.get(label, {})
            if "error" in r:
                return "FAIL"
            return str(r.get(key, default))

        for dim, key in [
            ("時間", "elapsed"), ("項目數", "count"), ("原文依據", "grounded"),
            ("幻覺數", "hallucinated"), ("具體性", "specificity"),
            ("Recall", "recall"), ("Recall%", "recall_pct"),
            ("超長(>150字)", "over_150"), ("Schema", "schema_valid"),
        ]:
            vals = " | ".join(f"{_val(l, key):12s}" for l in labels)
            print(f"| {dim:14s} | {vals} |")
        print()

    # ══════════════════════════════════════════════════════════════════════
    # 全域彙總（跨題型平均）
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print(f"  全域彙總（跨 {len(TOPICS)} 題型平均）")
    print(f"{'='*70}\n")

    header = " | ".join(f"{l:12s}" for l in labels)
    print(f"| {'維度':14s} | {header} |")
    print(f"|{'-'*16}|" + "|".join("-"*14 for _ in labels) + "|")

    def _cross_avg(label, key, fmt=".1f"):
        vals = []
        for topic in TOPICS:
            r = all_data[topic["name"]].get(label, {})
            if "error" not in r and key in r:
                vals.append(r[key])
        if not vals:
            return "FAIL"
        return f"{sum(vals)/len(vals):{fmt}}"

    def _cross_rate(label, key):
        num = denom = 0
        for topic in TOPICS:
            r = all_data[topic["name"]].get(label, {})
            if "error" in r:
                continue
            v = r.get(key, "0/0")
            if v == "N/A":
                continue
            parts = v.split("/")
            if len(parts) == 2:
                num += int(parts[0])
                denom += int(parts[1])
        if denom == 0:
            return "N/A"
        return f"{num}/{denom} ({num/denom:.0%})"

    def _cross_sum(label, key):
        total = 0
        count = 0
        for topic in TOPICS:
            r = all_data[topic["name"]].get(label, {})
            if "error" not in r:
                total += r.get(key, 0)
                count += 1
        return f"{total}" if count else "FAIL"

    def _success_rate(label):
        ok = sum(1 for t in TOPICS if "error" not in all_data[t["name"]].get(label, {"error": True}))
        return f"{ok}/{len(TOPICS)}"

    for dim, calc in [
        ("成功率",         lambda l: _success_rate(l)),
        ("平均時間",       lambda l: _cross_avg(l, "elapsed") + "s"),
        ("平均項目數",     lambda l: _cross_avg(l, "count")),
        ("原文依據",       lambda l: _cross_rate(l, "grounded")),
        ("幻覺總數",       lambda l: _cross_sum(l, "hallucinated")),
        ("具體性",         lambda l: _cross_rate(l, "specificity")),
        ("Recall",        lambda l: _cross_rate(l, "recall")),
        ("平均Recall%",   lambda l: _cross_avg(l, "recall_pct", ".0f") + "%"),
        ("超長>150字",    lambda l: _cross_sum(l, "over_150")),
        ("Type合規",      lambda l: _cross_rate(l, "type_compliance")),
    ]:
        vals = " | ".join(f"{calc(l):12s}" for l in labels)
        print(f"| {dim:14s} | {vals} |")

    # ── 萃取內容抽樣 ──
    print(f"\n{'='*70}")
    print(f"  萃取內容抽樣（每題型每模型最多 3 項）")
    print(f"{'='*70}\n")

    for topic in TOPICS:
        tname = topic["name"]
        print(f"### {tname}")
        for label in labels:
            r = all_data[tname].get(label, {})
            items = r.get("items", [])
            if not items:
                print(f"  [{label}] (無結果)")
                continue
            print(f"  [{label}] ({len(items)} 項)")
            for i, item in enumerate(items[:3], 1):
                t = item.get("type", "?")
                c = item.get("content", "")
                marker = "✓" if t in VALID_TYPES else "✗"
                print(f"    {i}. {marker}[{t:13s}] {c[:120]}")
            if len(items) > 3:
                print(f"    ... 另有 {len(items)-3} 項")
        print()

    # ── 存結果 ──
    staging = CLAUDE_DIR / "memory" / "_staging"
    staging.mkdir(parents=True, exist_ok=True)
    out_path = staging / "ab_gemma4_round3_results.json"
    output = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "topics": [t["name"] for t in TOPICS],
        "models": [{"model": m, "think": t, "temp": tp, "label": l} for m, t, tp, l in models],
        "results": {tname: {
            label: {k: v for k, v in data.items() if k != "items"}
            for label, data in topic_data.items()
        } for tname, topic_data in all_data.items()},
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n原始結果已存: {out_path}")


if __name__ == "__main__":
    main()
