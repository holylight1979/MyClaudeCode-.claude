#!/usr/bin/env python3
"""
memory-write-gate.py — Atomic Memory Write Gate (v2.1)

寫入前品質評估 + 去重檢查。用於 session-end 同步前過濾低品質知識。

Usage:
    python memory-write-gate.py --content "知識文字" [--classification "[觀]"] [--trigger-context "..."]
    python memory-write-gate.py --content "知識" --explicit-user
    python memory-write-gate.py --batch items.jsonl

Output: JSON {action, quality_score, reason, dedup_match?}

Requirements: Python 3.8+. Vector dedup needs Memory Vector Service @ port 3849.
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ─── Constants ───────────────────────────────────────────────────────────────

CLAUDE_DIR = Path.home() / ".claude"
CONFIG_PATH = CLAUDE_DIR / "workflow" / "config.json"
AUDIT_LOG = CLAUDE_DIR / "memory" / "_vectordb" / "audit.log"

# Quality score components
QUALITY_RULES = {
    "length_20": 0.15,       # content length > 20 chars
    "length_50": 0.10,       # content length > 50 chars
    "tech_terms": 0.15,      # >= 2 technical terms
    "explicit_user": 0.35,   # user explicitly triggered
    "concrete_value": 0.15,  # contains version/path/config value
    "non_transient": 0.10,   # not transient (no timeout/retry/暫時)
    "actionable": 0.15,      # contains action pattern (when X → do Y)
}

# Technical term patterns (common in dev context)
TECH_TERM_PATTERNS = [
    r"\b(?:API|SDK|CLI|HTTP|REST|gRPC|SQL|JSON|YAML|XML|CSV)\b",
    r"\b(?:Git|Docker|Kubernetes|Node|Python|TypeScript|Rust|Go)\b",
    r"\b(?:hook|middleware|endpoint|schema|migration|deploy|build)\b",
    r"\b(?:vector|embedding|LLM|RAG|token|chunk|index)\b",
    r"\b(?:protobuf|flatbuffers|WebSocket|SSE|OAuth|JWT)\b",
    r"\b(?:VRAM|GPU|CUDA|ONNX|model|inference)\b",
    r"(?:版本|設定|路徑|配置|參數|模組|元件|架構|框架)",
]

# Actionable patterns (indicates knowledge that tells you what to do/avoid)
# Note: CJK text has no spaces, so use \s* (optional) for CJK patterns
ACTIONABLE_PATTERNS = [
    r"(?:需要|必須)\s*.{5,}",                                 # CJK directive
    r"(?:不要|避免)\s*.{5,}",                                 # CJK prohibition
    r"(?:否則|不然)\s*.{3,}",                                 # CJK consequence
    r"(?:因為|由於|原因是)\s*.{5,}",                           # CJK causal
    r"(?:如果|when|if)\s*.{3,}(?:就|then|→)",                 # conditional
    r"(?:should|must|need to)\s+.{5,}",                       # EN directive
    r"(?:don't|avoid|never)\s+.{5,}",                         # EN prohibition
    r"(?:because|otherwise)\s+.{5,}",                         # EN causal
    r"→|->|＝>",                                               # arrow = causation
]

# Transient patterns (suggests ephemeral issue, not worth storing)
TRANSIENT_PATTERNS = [
    r"\b(?:timeout|retry|retried|timed?\s*out)\b",
    r"(?:暫時|臨時|偶發|一次性|retry|重試)",
    r"\b(?:pip install .* timeout|npm ERR! network)\b",
]

# Concrete value patterns (version, path, config)
CONCRETE_VALUE_PATTERNS = [
    r"\bv?\d+\.\d+(?:\.\d+)?\b",                    # version numbers
    r"[~/\\][\w./\\-]{5,}",                          # file paths
    r"\b\d{4,5}\b",                                   # port numbers
    r"\b(?:true|false|null|none)\b",                  # config values
    r'["\'][\w./-]+["\']',                            # quoted identifiers
    r"\b\w+=\w+\b",                                   # key=value
]

# Explicit user trigger phrases
EXPLICIT_TRIGGERS = [
    "記住", "以後都這樣", "永遠不要", "永遠", "always", "never",
    "remember", "from now on", "以後",
]


# ─── Config ──────────────────────────────────────────────────────────────────


def load_config() -> Dict[str, Any]:
    """Load write_gate config from workflow config."""
    defaults = {
        "enabled": True,
        "auto_threshold": 0.5,
        "ask_threshold": 0.3,
        "dedup_score": 0.80,
        "skip_on_explicit_user": True,
    }
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            defaults.update(cfg.get("write_gate", {}))
        except (json.JSONDecodeError, OSError):
            pass
    return defaults


# ─── Quality Score ───────────────────────────────────────────────────────────


def compute_quality_score(
    content: str,
    explicit_user: bool = False,
    trigger_context: str = "",
) -> Tuple[float, List[str]]:
    """Compute rule-based quality score. Returns (score, reasons)."""
    score = 0.0
    reasons: List[str] = []

    # Length checks
    if len(content) > 20:
        score += QUALITY_RULES["length_20"]
        reasons.append(f"length>{20}")
    if len(content) > 50:
        score += QUALITY_RULES["length_50"]
        reasons.append(f"length>{50}")

    # Technical terms
    tech_count = 0
    combined = content + " " + trigger_context
    for pattern in TECH_TERM_PATTERNS:
        tech_count += len(re.findall(pattern, combined, re.IGNORECASE))
    if tech_count >= 2:
        score += QUALITY_RULES["tech_terms"]
        reasons.append(f"tech_terms={tech_count}")

    # Explicit user trigger
    if explicit_user:
        score += QUALITY_RULES["explicit_user"]
        reasons.append("explicit_user")
    else:
        # Check if trigger_context contains explicit phrases
        for phrase in EXPLICIT_TRIGGERS:
            if phrase in trigger_context.lower():
                score += QUALITY_RULES["explicit_user"]
                reasons.append(f"explicit_phrase={phrase}")
                break

    # Concrete values
    for pattern in CONCRETE_VALUE_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            score += QUALITY_RULES["concrete_value"]
            reasons.append("concrete_value")
            break

    # Non-transient
    is_transient = False
    for pattern in TRANSIENT_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            is_transient = True
            reasons.append("transient_content")
            break
    if not is_transient:
        score += QUALITY_RULES["non_transient"]
        reasons.append("non_transient")

    # Actionability check
    for pattern in ACTIONABLE_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            score += QUALITY_RULES["actionable"]
            reasons.append("actionable")
            break

    return min(score, 1.0), reasons


# ─── Dedup Check ─────────────────────────────────────────────────────────────


def check_dedup(content: str, config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Check for duplicate knowledge via Vector Service. Returns match info or None."""
    try:
        port = 3849
        # Load vector config from main config
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                full_cfg = json.load(f)
            vs_cfg = full_cfg.get("vector_search", {})
            port = vs_cfg.get("service_port", 3849)
    except Exception:
        pass

    dedup_threshold = config.get("dedup_score", 0.80)

    try:
        params = urllib.parse.urlencode({"q": content, "top_k": 3, "min_score": dedup_threshold})
        url = f"http://127.0.0.1:{port}/search?{params}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            results = json.loads(resp.read())

        if not results:
            return None

        top = results[0]
        score = top.get("score", 0)
        if score < dedup_threshold:
            return None

        return {
            "atom_name": top.get("atom_name", ""),
            "score": round(score, 3),
            "text_preview": top.get("text", "")[:80],
            "verdict": "duplicate" if score > 0.95 else "similar",
        }
    except Exception:
        return None  # Vector service unavailable — skip dedup


# ─── Audit Log ───────────────────────────────────────────────────────────────


def write_audit_log(action: str, content_preview: str, quality: float, **extra: Any) -> None:
    """Append to audit.log (JSONL)."""
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "action": action,
        "content": content_preview[:80],
        "quality": round(quality, 2),
    }
    entry.update(extra)
    try:
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # Log rotation: >10MB → rotate
        if AUDIT_LOG.stat().st_size > 10 * 1024 * 1024:
            _rotate_log()
    except OSError:
        pass


def _rotate_log() -> None:
    """Simple log rotation: keep 3 copies."""
    for i in range(2, 0, -1):
        src = AUDIT_LOG.with_suffix(f".log.{i}")
        dst = AUDIT_LOG.with_suffix(f".log.{i + 1}")
        if src.exists():
            if i == 2:
                try:
                    src.unlink()
                except OSError:
                    pass
            else:
                try:
                    src.rename(dst)
                except OSError:
                    pass
    try:
        AUDIT_LOG.rename(AUDIT_LOG.with_suffix(".log.1"))
    except OSError:
        pass


# ─── Gate Decision ───────────────────────────────────────────────────────────


def evaluate(
    content: str,
    classification: str = "[臨]",
    trigger_context: str = "",
    explicit_user: bool = False,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Main Write Gate evaluation. Returns decision dict."""
    if config is None:
        config = load_config()

    # Fast path: explicit user trigger → always add
    # Note: [固] no longer fast-paths here — 移除反向激勵，[固] 也需過 dedup/quality
    if explicit_user:
        write_audit_log("add", content, 1.0, classification=classification, reason="explicit_user")
        return {
            "action": "add",
            "quality_score": 1.0,
            "reason": "explicit user trigger",
        }

    # Pitfall/trap detection → add with [觀]
    pitfall_keywords = ["陷阱", "坑", "pitfall", "gotcha", "注意", "caution", "bug", "重入"]
    if any(kw in content.lower() or kw in trigger_context.lower() for kw in pitfall_keywords):
        quality = 0.7
        write_audit_log("add", content, quality, classification="[觀]", reason="pitfall_detected")
        return {
            "action": "add",
            "quality_score": quality,
            "reason": "pitfall/trap detected, auto-add as [觀]",
        }

    # Dedup check
    dedup = check_dedup(content, config)
    if dedup:
        if dedup["verdict"] == "duplicate":
            write_audit_log("skip", content, 0, reason="duplicate", dedup_match=dedup["atom_name"])
            return {
                "action": "skip",
                "quality_score": 0,
                "reason": f"duplicate of {dedup['atom_name']} (score={dedup['score']})",
                "dedup_match": dedup,
            }
        else:
            # Similar but not identical → suggest update
            write_audit_log("update", content, 0.6, dedup_match=dedup["atom_name"])
            return {
                "action": "update",
                "quality_score": 0.6,
                "reason": f"similar to {dedup['atom_name']} (score={dedup['score']}), suggest update",
                "dedup_match": dedup,
            }

    # Quality score
    quality, reasons = compute_quality_score(content, explicit_user, trigger_context)

    auto_threshold = config.get("auto_threshold", 0.5)
    ask_threshold = config.get("ask_threshold", 0.3)

    if quality >= auto_threshold:
        action = "add"
    elif quality >= ask_threshold:
        action = "ask"
    else:
        action = "skip"

    write_audit_log(action, content, quality, classification=classification, reasons=reasons)

    return {
        "action": action,
        "quality_score": round(quality, 2),
        "reason": f"quality={quality:.2f} ({'>=auto' if action == 'add' else 'ask' if action == 'ask' else '<skip'} threshold), factors: {', '.join(reasons)}",
    }


# ─── CLI ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Atomic Memory Write Gate (v2.1)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--content", type=str, help="要評估的知識文字")
    parser.add_argument("--classification", type=str, default="[臨]",
                        help="知識分類 [固]/[觀]/[臨]")
    parser.add_argument("--trigger-context", type=str, default="",
                        help="觸發此知識的上下文")
    parser.add_argument("--explicit-user", action="store_true",
                        help="使用者明確要求記住")
    parser.add_argument("--batch", type=str, metavar="FILE",
                        help="批次處理 JSONL 檔案")

    args = parser.parse_args()
    config = load_config()

    if args.batch:
        # Batch mode: process JSONL
        try:
            with open(args.batch, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    item = json.loads(line)
                    result = evaluate(
                        content=item.get("content", ""),
                        classification=item.get("classification", "[臨]"),
                        trigger_context=item.get("trigger_context", ""),
                        explicit_user=item.get("explicit_user", False),
                        config=config,
                    )
                    print(json.dumps(result, ensure_ascii=False))
        except (OSError, json.JSONDecodeError) as e:
            print(json.dumps({"error": str(e)}))
            sys.exit(1)
    elif args.content:
        result = evaluate(
            content=args.content,
            classification=args.classification,
            trigger_context=args.trigger_context,
            explicit_user=args.explicit_user,
            config=config,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        # Read from stdin (for pipe usage)
        raw = sys.stdin.read().strip()
        if raw:
            try:
                item = json.loads(raw)
                result = evaluate(
                    content=item.get("content", ""),
                    classification=item.get("classification", "[臨]"),
                    trigger_context=item.get("trigger_context", ""),
                    explicit_user=item.get("explicit_user", False),
                    config=config,
                )
                print(json.dumps(result, ensure_ascii=False, indent=2))
            except json.JSONDecodeError:
                # Treat as plain text
                result = evaluate(content=raw, config=config)
                print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            parser.print_help()
            sys.exit(1)


if __name__ == "__main__":
    main()
