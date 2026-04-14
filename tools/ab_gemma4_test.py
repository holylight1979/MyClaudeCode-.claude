# ONE-OFF: 一次性測試腳本，非常規工具
"""
ab_gemma4_test.py — 全面 A/B 萃取品質驗證：qwen3.5 vs gemma4 variants (rdchat)

測試維度：
  1. JSON 遵從度（格式正確率 + type enum 合規）
  2. 幻覺偵測（萃取事實是否有原文依據）
  3. 一致性（同輸入跑兩次看 variance）
  4. 不同長度輸入（短文 1000 字 / 長文 4000 字）
  5. bf16 精度（gemma4:e4b-it-bf16）
  6. 空輸入處理（無價值內容是否正確回 []）

用法：python3 tools/ab_gemma4_test.py [rounds=3]
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

# ── 直接呼叫指定模型 ─────────────────────────────────────────────────────

def call_model(client, model_name: str, prompt: str,
               think: bool = True, timeout: int = 240):
    """直接打 rdchat-direct backend，用指定 model。"""
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
        "options": {"temperature": 0.1, "num_predict": 4096},
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

# ── 品質分析（增強版）────────────────────────────────────────────────────

def analyze_items(items, source_text: str = ""):
    if not items:
        return {
            "count": 0, "avg_length": 0, "type_dist": {},
            "specificity": "0/0", "type_compliance": "N/A",
            "grounded": "N/A", "schema_valid": "N/A",
        }
    types = {}
    lengths = []
    specific_count = 0
    valid_type_count = 0
    schema_valid_count = 0
    grounded_count = 0

    for item in items:
        # Schema 合規: 必須有 content + type 兩個欄位
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

        # 具體性：含數字、路徑、版本
        if any(ch.isdigit() for ch in c) or "/" in c or "\\" in c:
            specific_count += 1

        # 幻覺偵測（grounding check）
        # 從 content 中抽取關鍵詞，檢查是否在原文中出現
        if source_text and c:
            grounded = _check_grounding(c, source_text)
            if grounded:
                grounded_count += 1

    n = len(items)
    return {
        "count": n,
        "avg_length": round(sum(lengths) / n, 1),
        "type_dist": types,
        "specificity": f"{specific_count}/{n}",
        "type_compliance": f"{valid_type_count}/{n}",
        "schema_valid": f"{schema_valid_count}/{n}",
        "grounded": f"{grounded_count}/{n}" if source_text else "N/A",
    }


def _check_grounding(content: str, source_text: str) -> bool:
    """檢查萃取的 content 是否有原文依據。
    策略：從 content 抽取可驗證的 token（數字、英文詞、路徑段），
    至少 50% 在原文中能找到即視為有依據。"""
    # 抽取可驗證 token
    tokens = re.findall(r'[a-zA-Z_][\w.-]{2,}|[\d]+(?:\.[\d]+)*|\S+/\S+', content)
    if not tokens:
        return True  # 純中文敘述，無法機械驗證，寬鬆放過
    found = sum(1 for t in tokens if t.lower() in source_text.lower())
    return found / len(tokens) >= 0.4  # 40% 門檻（容許模型摘要改寫）

# ── 一致性分析 ─────────────────────────────────────────────────────────────

def consistency_score(items_a, items_b):
    """比較兩次萃取結果的重疊度。基於 content 關鍵詞 Jaccard 相似度。"""
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

# ── 找測試 transcript ─────────────────────────────────────────────────────

def find_transcripts(max_count: int = 5):
    """找最近的幾個有足夠內容的 transcript（跨專案取樣）。"""
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

# ── 空輸入測試 ────────────────────────────────────────────────────────────

_EMPTY_TEXT = (
    "使用者：你好\n"
    "助手：你好！有什麼需要幫忙的嗎？\n"
    "使用者：沒事，就問問\n"
    "助手：好的，有需要隨時說。\n"
)

# ── Main ──────────────────────────────────────────────────────────────────

def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 3

    # 要測的模型
    models = [
        ("qwen3.5:latest",      True,  "qwen3.5 T"),
        ("gemma4:e4b",           True,  "g4:e4b T"),
        ("gemma4:e4b",           False, "g4:e4b F"),
        ("gemma4:e4b-it-bf16",   True,  "g4:e4b-bf16 T"),
        ("gemma4:26b",           True,  "g4:26b T"),
    ]

    transcripts = find_transcripts(max_count=max(rounds, 3))
    if not transcripts:
        print("找不到可用的 transcript！")
        sys.exit(1)

    print(f"{'='*70}")
    print(f"  A/B 全面萃取品質驗證：qwen3.5 vs Gemma 4")
    print(f"{'='*70}")
    print(f"測試輪數: {rounds} | 模型數: {len(models)}")
    print(f"測試維度: JSON遵從 | 幻覺偵測 | 一致性 | 長短文 | bf16 | 空輸入")
    print(f"\nTranscripts:")
    for t in transcripts:
        print(f"  {t.parent.name}/{t.name} ({t.stat().st_size//1024}KB)")
    print()

    client = get_client()
    print(f"Backends: {[b.name for b in client._backends]}\n")

    # ══════════════════════════════════════════════════════════════════════
    # Phase 1: 標準萃取測試（長文 4000 字）
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("Phase 1: 標準萃取（4000 字輸入）")
    print(f"{'='*70}\n")

    all_results = {label: [] for _, _, label in models}
    all_items = {label: [] for _, _, label in models}  # 保留 items 供一致性分析

    for rd in range(rounds):
        transcript = transcripts[rd % len(transcripts)]
        texts = extract_assistant_texts(transcript)
        merged = "\n---\n".join(texts)
        source_text = merged[:4000]
        prompt = build_prompt(merged, max_input=4000)
        print(f"── Round {rd+1}/{rounds} ── {transcript.name} ({len(merged)} chars) ──")

        for model_name, think, label in models:
            print(f"  [{label:16s}] ", end="", flush=True)
            raw, elapsed, err = call_model(client, model_name, prompt, think=think)
            if err:
                print(f"FAIL: {err}")
                all_results[label].append({"error": err, "elapsed": elapsed})
                all_items[label].append(None)
                continue

            items, parse_err = parse_json_response(raw)
            if parse_err:
                print(f"PARSE FAIL: {parse_err} | {elapsed:.1f}s | raw[:80]={raw[:80]}")
                all_results[label].append({"error": parse_err, "elapsed": elapsed, "raw_preview": raw[:300]})
                all_items[label].append(None)
                continue

            analysis = analyze_items(items, source_text)
            analysis["elapsed"] = round(elapsed, 1)
            analysis["items"] = items
            all_results[label].append(analysis)
            all_items[label].append(items)
            print(f"OK | {elapsed:5.1f}s | {analysis['count']:2d} items | "
                  f"schema={analysis['schema_valid']} | type={analysis['type_compliance']} | "
                  f"grounded={analysis['grounded']} | spec={analysis['specificity']}")

        print()

    # ══════════════════════════════════════════════════════════════════════
    # Phase 2: 短文測試（1000 字）
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("Phase 2: 短文萃取（1000 字輸入）")
    print(f"{'='*70}\n")

    short_results = {label: [] for _, _, label in models}
    transcript = transcripts[0]
    texts = extract_assistant_texts(transcript)
    merged = "\n---\n".join(texts)
    source_short = merged[:1000]
    prompt_short = build_prompt(merged, max_input=1000)

    for model_name, think, label in models:
        print(f"  [{label:16s}] ", end="", flush=True)
        raw, elapsed, err = call_model(client, model_name, prompt_short, think=think)
        if err:
            print(f"FAIL: {err}")
            short_results[label].append({"error": err, "elapsed": elapsed})
            continue
        items, parse_err = parse_json_response(raw)
        if parse_err:
            print(f"PARSE FAIL: {parse_err} | {elapsed:.1f}s")
            short_results[label].append({"error": parse_err, "elapsed": elapsed})
            continue
        analysis = analyze_items(items, source_short)
        analysis["elapsed"] = round(elapsed, 1)
        analysis["items"] = items
        short_results[label].append(analysis)
        print(f"OK | {elapsed:5.1f}s | {analysis['count']:2d} items | grounded={analysis['grounded']}")
    print()

    # ══════════════════════════════════════════════════════════════════════
    # Phase 3: 一致性測試（同輸入跑兩次）
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("Phase 3: 一致性測試（同輸入 × 2 次）")
    print(f"{'='*70}\n")

    consistency_results = {}
    transcript = transcripts[0]
    texts = extract_assistant_texts(transcript)
    merged = "\n---\n".join(texts)
    prompt_cons = build_prompt(merged, max_input=4000)

    for model_name, think, label in models:
        runs = []
        for attempt in range(2):
            print(f"  [{label:16s} run {attempt+1}] ", end="", flush=True)
            raw, elapsed, err = call_model(client, model_name, prompt_cons, think=think)
            if err:
                print(f"FAIL: {err}")
                runs.append(None)
                continue
            items, parse_err = parse_json_response(raw)
            if parse_err:
                print(f"PARSE FAIL: {parse_err} | {elapsed:.1f}s")
                runs.append(None)
                continue
            runs.append(items)
            print(f"OK | {elapsed:5.1f}s | {len(items)} items")

        if runs[0] and runs[1]:
            score = consistency_score(runs[0], runs[1])
            consistency_results[label] = round(score, 3)
            print(f"  → Jaccard 一致性: {score:.1%}")
        else:
            consistency_results[label] = None
            print(f"  → 無法計算（有失敗）")
        print()

    # ══════════════════════════════════════════════════════════════════════
    # Phase 4: 空輸入處理
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("Phase 4: 空輸入測試（應回傳 []）")
    print(f"{'='*70}\n")

    empty_results = {}
    prompt_empty = build_prompt(_EMPTY_TEXT, max_input=4000)

    for model_name, think, label in models:
        print(f"  [{label:16s}] ", end="", flush=True)
        raw, elapsed, err = call_model(client, model_name, prompt_empty, think=think)
        if err:
            print(f"FAIL: {err}")
            empty_results[label] = {"pass": False, "reason": err}
            continue
        items, parse_err = parse_json_response(raw)
        if parse_err:
            # 某些模型可能回空字串或非 JSON，但如果原始回應就是 [] 也算過
            if raw and raw.strip() in ("[]", ""):
                print(f"PASS (raw=[]) | {elapsed:.1f}s")
                empty_results[label] = {"pass": True, "elapsed": round(elapsed, 1)}
            else:
                print(f"FAIL: {parse_err} | raw[:80]={raw[:80]} | {elapsed:.1f}s")
                empty_results[label] = {"pass": False, "reason": parse_err}
            continue
        is_empty = len(items) == 0
        print(f"{'PASS' if is_empty else 'FAIL'} | {elapsed:.1f}s | items={len(items)}")
        empty_results[label] = {"pass": is_empty, "count": len(items), "elapsed": round(elapsed, 1)}
    print()

    # ══════════════════════════════════════════════════════════════════════
    # 彙總報告
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("  彙總報告")
    print(f"{'='*70}\n")

    labels = [label for _, _, label in models]
    header = " | ".join(f"{l:14s}" for l in labels)
    sep = " | ".join("-" * 14 for _ in labels)
    print(f"| {'維度':20s} | {header} |")
    print(f"|{'-'*22}|{sep}|")

    def _safe_avg(rs, key, fmt=".1f"):
        ok = [r for r in rs if "error" not in r]
        if not ok:
            return "FAIL"
        val = sum(r.get(key, 0) for r in ok) / len(ok)
        return f"{val:{fmt}}"

    def _safe_rate(rs, key):
        """Parse 'n/m' strings, aggregate."""
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

    rows = [
        ("成功率",          lambda l: f"{sum(1 for r in all_results[l] if 'error' not in r)}/{len(all_results[l])}"),
        ("平均時間",        lambda l: _safe_avg(all_results[l], "elapsed") + "s"),
        ("平均項目數",      lambda l: _safe_avg(all_results[l], "count", ".1f")),
        ("平均 content 長", lambda l: _safe_avg(all_results[l], "avg_length", ".0f") + "字"),
        ("Schema 合規",     lambda l: _safe_rate(all_results[l], "schema_valid")),
        ("Type enum 合規",  lambda l: _safe_rate(all_results[l], "type_compliance")),
        ("具體性",          lambda l: _safe_rate(all_results[l], "specificity")),
        ("原文依據",        lambda l: _safe_rate(all_results[l], "grounded")),
        ("短文(1K) 項目數", lambda l: _safe_avg(short_results[l], "count", ".0f") if short_results[l] else "N/A"),
        ("短文 時間",       lambda l: _safe_avg(short_results[l], "elapsed") + "s" if short_results[l] else "N/A"),
        ("一致性 Jaccard",  lambda l: f"{consistency_results.get(l, 0):.1%}" if consistency_results.get(l) is not None else "FAIL"),
        ("空輸入 PASS",     lambda l: "PASS" if empty_results.get(l, {}).get("pass") else "FAIL"),
    ]

    for dim_name, calc_fn in rows:
        vals = " | ".join(f"{calc_fn(l):14s}" for l in labels)
        print(f"| {dim_name:20s} | {vals} |")

    # ── 萃取內容抽樣（Round 1 明細）──
    print(f"\n{'='*70}")
    print("  萃取內容抽樣（Round 1）")
    print(f"{'='*70}\n")

    for label in labels:
        if all_results[label] and "items" in all_results[label][0]:
            items = all_results[label][0]["items"]
            print(f"### {label} ({len(items)} 項)")
            for i, item in enumerate(items[:8], 1):  # 最多印 8 項
                t = item.get("type", "?")
                c = item.get("content", "")
                marker = "✓" if t in VALID_TYPES else "✗"
                print(f"  {i}. {marker}[{t}] {c[:120]}")
            if len(items) > 8:
                print(f"  ... 另有 {len(items)-8} 項")
            print()

    # ── 存原始結果 ──
    staging = CLAUDE_DIR / "memory" / "_staging"
    staging.mkdir(parents=True, exist_ok=True)
    out_path = staging / "ab_gemma4_results.json"
    output = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "rounds": rounds,
        "models": [{"model": m, "think": t, "label": l} for m, t, l in models],
        "phase1_standard": {l: all_results[l] for l in labels},
        "phase2_short": {l: short_results[l] for l in labels},
        "phase3_consistency": consistency_results,
        "phase4_empty": empty_results,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n原始結果已存: {out_path}")


if __name__ == "__main__":
    main()
