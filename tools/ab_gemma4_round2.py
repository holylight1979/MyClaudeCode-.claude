# ONE-OFF: 一次性測試腳本，非常規工具
"""
ab_gemma4_round2.py — 第二輪 A/B 驗證：更多輪數 + 新維度

新增測試維度：
  - 溫度敏感度（temp=0.0 / 0.1 / 0.3）
  - 遺漏 vs 幻覺分類（ExtractBench 風格）
  - 中文事實萃取（用中文重的 transcript）
  - 更多輪數（5 rounds 增加統計信心）
  - Ollama think=false + format bug 風險驗證

用法：python3 tools/ab_gemma4_round2.py
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

# ── Transcript 讀取 ──────────────────────────────────────────────────────

def extract_assistant_texts(transcript_path: Path, max_chars: int = 20000):
    texts, total = [], 0
    with open(transcript_path, "r", encoding="utf-8") as f:
        for raw in f:
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if obj.get("type") != "assistant":
                continue
            content = obj.get("message", {}).get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    t = block.get("text", "")
                    if t and len(t) > 30:
                        texts.append(t)
                        total += len(t)
            if total >= max_chars:
                break
    return texts

# ── Prompt ────────────────────────────────────────────────────────────────

_SYSTEM_CONTEXT = (
    "你是「原子記憶系統」的知識萃取器。萃取出的知識會存入長期記憶，供未來 session 引用。\n"
    "只萃取「這個專案/環境特有的」、「下次會用到的」事實。通用程式知識不要。\n\n"
)
_FORMAT_SPEC = (
    "輸出 JSON array: [{\"content\": \"精簡事實，最多150字\", "
    "\"type\": \"factual|procedural|architectural|pitfall|decision\"}]\n\n"
    "範例（值得萃取）:\n"
    '  {{"content": "rdchat Open WebUI LDAP 端點是 /api/v1/auths/ldap，用 user 欄位（非 email）", "type": "factual"}}\n'
    '  {{"content": "GTX 1050 Ti 跑 qwen3:1.7b generate 約 30s，qwen3-embedding embed 約 5s", "type": "factual"}}\n\n'
    "範例（不要萃取）:\n"
    '  ✗ "Python 的 dict 是 hash table" → 通用知識\n'
    '  ✗ "修改了 config.py 第 43 行" → session 進度\n\n'
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

# ── 呼叫模型 ──────────────────────────────────────────────────────────────

def call_model(client, model_name: str, prompt: str,
               think: bool = True, temperature: float = 0.1, timeout: int = 240):
    backend = None
    for b in client._backends:
        if b.name == "rdchat-direct":
            backend = b
            break
    if not backend:
        for b in client._backends:
            if b.name == "rdchat":
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
    content = result.get("message", {}).get("content", "")
    return content, elapsed, None

# ── JSON 解析 ─────────────────────────────────────────────────────────────

def parse_json_response(raw: str):
    if not raw:
        return None, "empty response"
    text = raw.strip()
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        return None, "no JSON array found"
    try:
        arr = json.loads(text[start:end+1])
        if isinstance(arr, list):
            return arr, None
        return None, "parsed but not a list"
    except json.JSONDecodeError as e:
        return None, f"JSON parse error: {e}"

# ── 品質分析 ───────────────────────────────────────────────────────────────

def _check_grounding(content: str, source_text: str) -> bool:
    tokens = re.findall(r'[a-zA-Z_][\w.-]{2,}|[\d]+(?:\.[\d]+)*|\S+/\S+', content)
    if not tokens:
        return True
    found = sum(1 for t in tokens if t.lower() in source_text.lower())
    return found / len(tokens) >= 0.4

def analyze_items(items, source_text: str = ""):
    if not items:
        return {
            "count": 0, "avg_length": 0, "type_dist": {},
            "specificity": "0/0", "type_compliance": "N/A",
            "grounded": "N/A", "schema_valid": "N/A",
            "hallucinated": 0, "content_lengths": [],
        }
    types = {}
    lengths = []
    specific_count = 0
    valid_type_count = 0
    schema_valid_count = 0
    grounded_count = 0
    hallucinated_count = 0

    for item in items:
        has_content = isinstance(item.get("content"), str) and len(item.get("content", "")) > 0
        has_type = isinstance(item.get("type"), str)
        if has_content and has_type:
            schema_valid_count += 1

        t = item.get("type", "unknown")
        types[t] = types.get(t, 0) + 1
        if t in VALID_TYPES:
            valid_type_count += 1

        c = item.get("content", "")
        lengths.append(len(c))

        if any(ch.isdigit() for ch in c) or "/" in c or "\\" in c:
            specific_count += 1

        if source_text and c:
            g = _check_grounding(c, source_text)
            if g:
                grounded_count += 1
            else:
                hallucinated_count += 1

    n = len(items)
    return {
        "count": n,
        "avg_length": round(sum(lengths) / n, 1),
        "content_lengths": lengths,
        "type_dist": types,
        "specificity": f"{specific_count}/{n}",
        "type_compliance": f"{valid_type_count}/{n}",
        "schema_valid": f"{schema_valid_count}/{n}",
        "grounded": f"{grounded_count}/{n}" if source_text else "N/A",
        "hallucinated": hallucinated_count,
    }

# ── 一致性 ────────────────────────────────────────────────────────────────

def consistency_score(items_a, items_b):
    if not items_a or not items_b:
        return 0.0
    def extract_keywords(items):
        kws = set()
        for item in items:
            c = item.get("content", "")
            tokens = re.findall(r'[a-zA-Z_][\w.-]{2,}|[\d]+(?:\.[\d]+)*', c)
            kws.update(t.lower() for t in tokens)
        return kws
    kw_a = extract_keywords(items_a)
    kw_b = extract_keywords(items_b)
    if not kw_a and not kw_b:
        return 1.0
    if not kw_a or not kw_b:
        return 0.0
    return len(kw_a & kw_b) / len(kw_a | kw_b)

# ── Transcript 蒐集 ───────────────────────────────────────────────────────

def find_transcripts(max_count: int = 6):
    candidates = []
    for proj_dir in (CLAUDE_DIR / "projects").iterdir():
        if not proj_dir.is_dir():
            continue
        for f in proj_dir.glob("*.jsonl"):
            if f.stat().st_size > 50000:
                candidates.append(f)
    candidates.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    seen_dirs = set()
    result = []
    for f in candidates:
        d = f.parent.name
        if d not in seen_dirs:
            seen_dirs.add(d)
            result.append(f)
        if len(result) >= max_count:
            break
    if len(result) < max_count:
        for f in candidates:
            if f not in result:
                result.append(f)
            if len(result) >= max_count:
                break
    return result

# ── 手工嵌入事實 ground truth（用於 recall/precision 計算）───────────────

# 已知事實種子（從 Round 1 人工審閱取出的確定事實）
_KNOWN_FACTS_KEYWORDS = [
    # 從本 session transcript 可確定萃取到的事實 keyword sets
    {"gemma4", "e2b", "5.1B"},
    {"gemma4", "e4b", "8.0B"},
    {"gemma4", "26b", "MoE"},
    {"rdchat", "192.168.199.130", "11434"},
    {"RTX", "3090", "24GB"},
    {"qwen3-embedding", "embedding"},
    {"qwen3.5", "9.7B"},
]

def recall_check(items, known_facts):
    """檢查已知事實中有多少被萃取到。"""
    if not items or not known_facts:
        return 0, len(known_facts)
    found = 0
    for fact_kws in known_facts:
        all_content = " ".join(item.get("content", "") for item in items)
        if all(kw.lower() in all_content.lower() for kw in fact_kws):
            found += 1
    return found, len(known_facts)

# ── 空輸入 ────────────────────────────────────────────────────────────────

_EMPTY_TEXT = "使用者：你好\n助手：你好！有什麼需要幫忙的嗎？\n使用者：沒事，就問問\n助手：好的，有需要隨時說。\n"

# 通用知識（應該不萃取）
_GENERIC_TEXT = (
    "助手：Python 的 dict 是用 hash table 實作的，查找時間複雜度是 O(1)。\n"
    "list comprehension 比 for loop 快一些，因為它在底層用 C 實作。\n"
    "git commit -m 'message' 可以提交變更到本地倉庫。\n"
    "JSON 是 JavaScript Object Notation 的縮寫，是一種輕量的資料交換格式。\n"
    "REST API 通常用 GET、POST、PUT、DELETE 四種 HTTP method。\n"
)

# ══════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════

def main():
    # 核心模型組（從 Round 1 結果聚焦）
    core_models = [
        ("qwen3.5:latest",    True,  0.1, "qwen3.5 T"),
        ("gemma4:e4b",         True,  0.1, "g4:e4b T"),
        ("gemma4:e4b",         False, 0.1, "g4:e4b F"),
        ("gemma4:e4b-it-bf16", True,  0.1, "g4:bf16 T"),
        ("gemma4:26b",         True,  0.1, "g4:26b T"),
    ]

    transcripts = find_transcripts(max_count=6)
    if not transcripts:
        print("找不到 transcript！")
        sys.exit(1)

    client = get_client()

    print(f"{'='*70}")
    print(f"  Round 2: 擴充 A/B 驗證（5 輪 + 新維度）")
    print(f"{'='*70}")
    print(f"Backends: {[b.name for b in client._backends]}")
    print(f"Transcripts: {len(transcripts)} 個")
    for t in transcripts:
        print(f"  {t.parent.name}/{t.name} ({t.stat().st_size//1024}KB)")
    print()

    # ══════════════════════════════════════════════════════════════════════
    # Phase A: 5 輪標準萃取（增加統計信心）
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("Phase A: 標準萃取 × 5 輪")
    print(f"{'='*70}\n")

    rounds = 5
    all_results = {label: [] for _, _, _, label in core_models}
    all_items = {label: [] for _, _, _, label in core_models}

    for rd in range(rounds):
        transcript = transcripts[rd % len(transcripts)]
        texts = extract_assistant_texts(transcript)
        merged = "\n---\n".join(texts)
        source_text = merged[:4000]
        prompt = build_prompt(merged, max_input=4000)
        print(f"── Round {rd+1}/{rounds} ── {transcript.name[:20]}... ({len(merged)} chars) ──")

        for model_name, think, temp, label in core_models:
            print(f"  [{label:12s}] ", end="", flush=True)
            raw, elapsed, err = call_model(client, model_name, prompt, think=think, temperature=temp)
            if err:
                print(f"FAIL: {err}")
                all_results[label].append({"error": err, "elapsed": elapsed})
                all_items[label].append(None)
                continue

            items, parse_err = parse_json_response(raw)
            if parse_err:
                print(f"PARSE FAIL: {parse_err} | {elapsed:.1f}s")
                all_results[label].append({"error": parse_err, "elapsed": elapsed})
                all_items[label].append(None)
                continue

            analysis = analyze_items(items, source_text)
            analysis["elapsed"] = round(elapsed, 1)
            analysis["items"] = items
            all_results[label].append(analysis)
            all_items[label].append(items)

            # recall check（只對含已知事實的 transcript）
            rec_found, rec_total = recall_check(items, _KNOWN_FACTS_KEYWORDS)
            analysis["recall"] = f"{rec_found}/{rec_total}"

            print(f"OK | {elapsed:5.1f}s | {analysis['count']:2d} items | "
                  f"grounded={analysis['grounded']} | halluc={analysis['hallucinated']} | "
                  f"recall={rec_found}/{rec_total}")

        print()

    # ══════════════════════════════════════════════════════════════════════
    # Phase B: 溫度敏感度（temp=0.0 / 0.1 / 0.3）
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("Phase B: 溫度敏感度（同一 transcript × 3 溫度）")
    print(f"{'='*70}\n")

    temp_models = [
        ("gemma4:e4b", False, 0.0, "g4:e4b t=0.0"),
        ("gemma4:e4b", False, 0.1, "g4:e4b t=0.1"),
        ("gemma4:e4b", False, 0.3, "g4:e4b t=0.3"),
        ("qwen3.5:latest", True, 0.0, "qwen3.5 t=0.0"),
        ("qwen3.5:latest", True, 0.1, "qwen3.5 t=0.1"),
        ("qwen3.5:latest", True, 0.3, "qwen3.5 t=0.3"),
    ]

    temp_results = {label: [] for _, _, _, label in temp_models}
    transcript = transcripts[0]
    texts = extract_assistant_texts(transcript)
    merged = "\n---\n".join(texts)
    source_text = merged[:4000]

    for run in range(2):  # 跑 2 次看 variance
        print(f"  Run {run+1}/2:")
        prompt = build_prompt(merged, max_input=4000)
        for model_name, think, temp, label in temp_models:
            print(f"    [{label:16s}] ", end="", flush=True)
            raw, elapsed, err = call_model(client, model_name, prompt, think=think, temperature=temp)
            if err:
                print(f"FAIL: {err}")
                temp_results[label].append({"error": err})
                continue
            items, parse_err = parse_json_response(raw)
            if parse_err:
                print(f"PARSE FAIL | {elapsed:.1f}s")
                temp_results[label].append({"error": parse_err, "elapsed": elapsed})
                continue
            analysis = analyze_items(items, source_text)
            analysis["elapsed"] = round(elapsed, 1)
            analysis["items"] = items
            temp_results[label].append(analysis)
            print(f"OK | {elapsed:5.1f}s | {analysis['count']} items | grounded={analysis['grounded']}")
        print()

    # 溫度一致性
    print("  溫度一致性（Jaccard）:")
    for model_name, think, temp, label in temp_models:
        runs = temp_results[label]
        ok_runs = [r for r in runs if "items" in r]
        if len(ok_runs) >= 2:
            score = consistency_score(ok_runs[0]["items"], ok_runs[1]["items"])
            print(f"    {label:16s}: {score:.1%}")
        else:
            print(f"    {label:16s}: N/A (不足 2 次成功)")
    print()

    # ══════════════════════════════════════════════════════════════════════
    # Phase C: 通用知識拒絕測試（不該萃取的都要回 []）
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("Phase C: 拒絕測試（空輸入 + 通用知識）")
    print(f"{'='*70}\n")

    reject_tests = [
        ("空輸入", _EMPTY_TEXT),
        ("通用知識", _GENERIC_TEXT),
    ]

    reject_models = [
        ("qwen3.5:latest", True, "qwen3.5"),
        ("gemma4:e4b", True, "g4:e4b T"),
        ("gemma4:e4b", False, "g4:e4b F"),
        ("gemma4:e4b-it-bf16", True, "g4:bf16 T"),
        ("gemma4:26b", True, "g4:26b T"),
    ]

    reject_results = {}
    for test_name, test_text in reject_tests:
        print(f"  [{test_name}]")
        prompt = build_prompt(test_text, max_input=4000)
        for model_name, think, label in reject_models:
            key = f"{label}|{test_name}"
            print(f"    [{label:12s}] ", end="", flush=True)
            raw, elapsed, err = call_model(client, model_name, prompt, think=think)
            if err:
                print(f"FAIL: {err}")
                reject_results[key] = {"pass": False, "reason": err}
                continue
            items, parse_err = parse_json_response(raw)
            if parse_err:
                is_empty_raw = raw and raw.strip() in ("[]", "")
                if is_empty_raw:
                    print(f"PASS (raw=[]) | {elapsed:.1f}s")
                    reject_results[key] = {"pass": True}
                else:
                    print(f"FAIL parse | {elapsed:.1f}s | raw[:60]={raw[:60]}")
                    reject_results[key] = {"pass": False, "reason": parse_err}
                continue
            is_empty = len(items) == 0
            print(f"{'PASS' if is_empty else 'FAIL'} | {elapsed:.1f}s | items={len(items)}")
            if not is_empty:
                for it in items[:3]:
                    print(f"      → [{it.get('type','?')}] {it.get('content','')[:80]}")
            reject_results[key] = {"pass": is_empty, "count": len(items)}
        print()

    # ══════════════════════════════════════════════════════════════════════
    # Phase D: Ollama format 參數 + think=false bug 驗證
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("Phase D: Ollama format 參數 bug 驗證 (ollama#15260)")
    print(f"{'='*70}\n")

    format_results = {}
    transcript = transcripts[0]
    texts = extract_assistant_texts(transcript)
    merged = "\n---\n".join(texts)
    prompt_text = build_prompt(merged, max_input=2000)

    format_tests = [
        ("g4:e4b think=F + format", "gemma4:e4b", False),
        ("g4:e4b think=T + format", "gemma4:e4b", True),
        ("g4:e4b think=omit + format", "gemma4:e4b", None),  # 不傳 think
    ]

    for label, model_name, think_val in format_tests:
        print(f"  [{label}] ", end="", flush=True)

        backend = None
        for b in client._backends:
            if b.name == "rdchat-direct":
                backend = b
                break

        payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt_text}],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1, "num_predict": 4096},
        }
        if think_val is not None:
            payload["think"] = think_val

        t0 = time.time()
        try:
            result = client._do_request(backend, "/api/chat", payload, 180)
        except Exception as e:
            print(f"ERROR: {e}")
            format_results[label] = {"error": str(e)}
            continue
        elapsed = time.time() - t0

        if result is None:
            print(f"NULL | {elapsed:.1f}s")
            format_results[label] = {"error": "null", "elapsed": elapsed}
            continue

        content = result.get("message", {}).get("content", "")
        # 檢查是否為有效 JSON
        try:
            parsed = json.loads(content)
            is_json = True
        except (json.JSONDecodeError, TypeError):
            is_json = False

        status = "JSON OK" if is_json else "NOT JSON"
        print(f"{status} | {elapsed:.1f}s | len={len(content)} | preview={content[:80]}")
        format_results[label] = {
            "is_json": is_json,
            "elapsed": round(elapsed, 1),
            "preview": content[:200],
        }
    print()

    # ══════════════════════════════════════════════════════════════════════
    # 最終彙總
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("  最終彙總報告")
    print(f"{'='*70}\n")

    labels = [label for _, _, _, label in core_models]

    def _safe_avg(rs, key, fmt=".1f"):
        ok = [r for r in rs if "error" not in r]
        if not ok:
            return "FAIL"
        val = sum(r.get(key, 0) for r in ok) / len(ok)
        return f"{val:{fmt}}"

    def _safe_rate(rs, key):
        ok = [r for r in rs if "error" not in r]
        if not ok:
            return "FAIL"
        num = denom = 0
        for r in ok:
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

    def _total_halluc(rs):
        ok = [r for r in rs if "error" not in r]
        if not ok:
            return "FAIL"
        total = sum(r.get("hallucinated", 0) for r in ok)
        return str(total)

    header = " | ".join(f"{l:14s}" for l in labels)
    sep = " | ".join("-" * 14 for _ in labels)
    print(f"| {'維度':20s} | {header} |")
    print(f"|{'-'*22}|{sep}|")

    rows = [
        ("成功率 (5輪)",       lambda l: f"{sum(1 for r in all_results[l] if 'error' not in r)}/{len(all_results[l])}"),
        ("平均時間",           lambda l: _safe_avg(all_results[l], "elapsed") + "s"),
        ("平均項目數",          lambda l: _safe_avg(all_results[l], "count", ".1f")),
        ("平均 content 長",    lambda l: _safe_avg(all_results[l], "avg_length", ".0f") + "字"),
        ("Schema 合規",        lambda l: _safe_rate(all_results[l], "schema_valid")),
        ("Type enum 合規",     lambda l: _safe_rate(all_results[l], "type_compliance")),
        ("具體性",             lambda l: _safe_rate(all_results[l], "specificity")),
        ("原文依據",            lambda l: _safe_rate(all_results[l], "grounded")),
        ("幻覺總數",            lambda l: _total_halluc(all_results[l])),
        ("Recall (已知事實)",   lambda l: _safe_rate(all_results[l], "recall")),
        ("空輸入拒絕",          lambda l: "PASS" if reject_results.get(f"{l.replace(' T','').replace(' F','')}|空輸入", {}).get("pass") else
                                          ("PASS" if reject_results.get(f"{l}|空輸入", {}).get("pass") else "FAIL")),
        ("通用知識拒絕",        lambda l: "PASS" if reject_results.get(f"{l.replace(' T','').replace(' F','')}|通用知識", {}).get("pass") else
                                          ("PASS" if reject_results.get(f"{l}|通用知識", {}).get("pass") else "FAIL")),
    ]

    for dim_name, calc_fn in rows:
        vals = " | ".join(f"{calc_fn(l):14s}" for l in labels)
        print(f"| {dim_name:20s} | {vals} |")

    # 溫度敏感度彙總
    print(f"\n### 溫度敏感度")
    for _, _, _, label in temp_models:
        runs = temp_results.get(label, [])
        ok = [r for r in runs if "items" in r]
        counts = [r["count"] for r in ok]
        if len(ok) >= 2:
            jac = consistency_score(ok[0]["items"], ok[1]["items"])
            print(f"  {label:16s}: items={counts} | Jaccard={jac:.1%}")
        elif ok:
            print(f"  {label:16s}: items={counts} | (只 1 次成功)")
        else:
            print(f"  {label:16s}: ALL FAIL")

    # format bug
    print(f"\n### Ollama format bug (ollama#15260)")
    for label, result in format_results.items():
        status = "JSON OK" if result.get("is_json") else ("ERROR" if "error" in result else "NOT JSON")
        print(f"  {label:30s}: {status}")

    # ── 存結果 ──
    staging = CLAUDE_DIR / "memory" / "_staging"
    staging.mkdir(parents=True, exist_ok=True)
    out_path = staging / "ab_gemma4_round2_results.json"
    output = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "phase_a": {l: all_results[l] for l in labels},
        "phase_b_temp": {l: temp_results[l] for _, _, _, l in temp_models},
        "phase_c_reject": reject_results,
        "phase_d_format": format_results,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n原始結果已存: {out_path}")


if __name__ == "__main__":
    main()
