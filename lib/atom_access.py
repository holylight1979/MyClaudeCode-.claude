"""atom_access.py — Atom 遙測旁路檔（access.json）讀寫單一通道

設計目標：
  - atom 的 read_hits / last_used / confirmations / last_promoted_at / first_seen
    全部寫到 <atom>.access.json，不再寫 atom .md 檔頭
  - 取代 hooks/workflow-guardian.py:1340-1375 的 raw write_text（funnel 違規修補）
  - 取代 lib/atom_io.py:update_atom_field 對 Confirmations 計數的呼叫

Schema v2（<atom>.access.json）:
  {
    "schema": "atom-access-v2",
    "read_hits": int,
    "last_used": "YYYY-MM-DD",
    "confirmations": int,
    "last_promoted_at": "YYYY-MM-DD" 或 None,
    "first_seen": "YYYY-MM-DD",
    "timestamps": [float epoch ...最多 50 筆],
    "confirmation_events": [{ts, ...} ...]
  }

舊 schema 偵測：confirmations 是陣列 → migrate (陣列→confirmation_events)。

CLI 入口（給 tools/workflow-guardian-mcp/server.js 透過子程序呼叫）：
  python -m lib.atom_access read <path>
  python -m lib.atom_access init <path> --first-seen YYYY-MM-DD --source mcp
  python -m lib.atom_access increment-read-hits <path> --source hook:atom-inject
  python -m lib.atom_access increment-confirmation <path> --source hook:episodic-confirm [--event-json '{...}']
  python -m lib.atom_access record-promotion <path> --target [固] --source mcp
  python -m lib.atom_access set <path> --field NAME --value VAL --source SRC
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# 重用 atom_io 的 audit infra（單一稽核日誌）
from .atom_io import (
    AUDIT_LOG, _gen_audit_id, _audit_log, _atomic_write,
    GLOBAL_MEMORY_DIR,
)

# 本模組合法 source 名單 — atom_io.VALID_SOURCES 的超集（保證任何 atom_io 寫入端皆可呼叫）
ACCESS_VALID_SOURCES = frozenset({
    "mcp",
    "hook:atom-inject",          # workflow-guardian.py atom 注入時 increment_read_hits
    "hook:episodic",             # episodic atom 建立時 init_access
    "hook:episodic-confirm",     # cross-session confirmation
    "hook:user-extract",
    "hook:extract-worker",
    "tool:atom-move",
    "tool:changelog-roll",
    "tool:memory-audit",         # restore_atom 計數歸零
    "tool:migrate",              # 一次性遷移
    "tool:atom-health-audit",    # Phase B 健康診斷
    "tool:sync-atom-index",
    "tool:sync-memory-index",
    "tool:undo",
    "test",
})

SCHEMA_KEY = "schema"
SCHEMA_VERSION = "atom-access-v2"
TIMESTAMPS_MAX = 50


# ─── 路徑 / 基本 IO ──────────────────────────────────────────────────────────


def _access_path(atom_path: Path) -> Path:
    """<atom>.md → <atom>.access.json（同層）"""
    return atom_path.with_suffix(".access.json")


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _audit(op: str, source: str, atom_path: Path, **extra: Any) -> str:
    audit_id = _gen_audit_id()
    entry = {
        "audit_id": audit_id,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "op": op,
        "source": source,
        "path": str(atom_path),
    }
    entry.update(extra)
    _audit_log(entry)
    return audit_id


def _validate_source(source: str) -> None:
    if source not in ACCESS_VALID_SOURCES:
        raise ValueError(f"invalid source for atom_access: {source}")


# ─── Schema 偵測與升級 ───────────────────────────────────────────────────────


def _normalize(data: Dict[str, Any]) -> tuple[Dict[str, Any], bool]:
    """把舊 schema 的資料規整成 v2；回傳 (新 dict, 是否被改寫)。

    舊格式特徵：
      (a) {"timestamps":[], "confirmations":[]}（confirmations 是陣列）
      (b) 缺 schema key
    """
    upgraded = False

    # (a) confirmations 是陣列 → 搬到 confirmation_events
    if isinstance(data.get("confirmations"), list):
        events = data["confirmations"]
        data["confirmation_events"] = events
        data["confirmations"] = len(events)
        upgraded = True

    # 預設值補齊
    defaults = {
        SCHEMA_KEY: SCHEMA_VERSION,
        "read_hits": 0,
        "last_used": None,
        "confirmations": 0,
        "last_promoted_at": None,
        "first_seen": None,
        "timestamps": [],
        "confirmation_events": [],
    }
    for k, v in defaults.items():
        if k not in data:
            data[k] = v
            if k == SCHEMA_KEY:
                upgraded = True

    if data.get(SCHEMA_KEY) != SCHEMA_VERSION:
        data[SCHEMA_KEY] = SCHEMA_VERSION
        upgraded = True

    return data, upgraded


def _read_raw(access_path: Path) -> Optional[Dict[str, Any]]:
    if not access_path.exists():
        return None
    try:
        return json.loads(access_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_raw(access_path: Path, data: Dict[str, Any]) -> bool:
    """寫 access JSON；Win 平台 cross-process 競態時重試 3 次（每次 50ms backoff）。

    回傳 True=成功；False=三次都失敗（呼叫端決定要不要 audit 為 dropped）。

    使用唯一 tmp 後綴（PID + thread id）避免多執行緒共用同一 tmp file 時
    `Path.write_text("w")` truncate 競態（會導致 access.json 落入半空檔）。
    """
    import os as _os
    import threading as _threading
    payload = json.dumps(data, ensure_ascii=False)
    access_path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        # 每次重試也用新的 tmp，避免上次失敗的 tmp 殘留干擾
        tmp = access_path.with_suffix(
            f"{access_path.suffix}.tmp.{_os.getpid()}.{_threading.get_ident()}.{attempt}"
        )
        try:
            tmp.write_text(payload, encoding="utf-8")
            _os.replace(str(tmp), str(access_path))
            return True
        except OSError:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            if attempt == 2:
                return False
            time.sleep(0.05)
    return False


# ─── 公開 API ────────────────────────────────────────────────────────────────


def read_access(atom_path: Path) -> Dict[str, Any]:
    """讀 atom 的 access 資料。

    一律回傳正規化後的 dict（含所有 v2 欄位 default），即使檔不存在或損毀。
    呼叫端如要區分「檔不存在 vs 檔存在但未累積」→ 看 first_seen 是 None。
    若是舊 schema → 正規化後**不寫回**（避免讀操作產生寫副作用）；
    寫回交給 increment / set / migration 觸發。
    """
    access_path = _access_path(atom_path)
    raw = _read_raw(access_path)
    if raw is None:
        # 檔不存在或 JSON 損毀 → 仍回 v2 defaults（callers 不需 KeyError 處理）
        normalized, _ = _normalize({})
        return normalized
    normalized, _upgraded = _normalize(raw)
    return normalized


def init_access(atom_path: Path, *, first_seen: Optional[str] = None, source: str) -> str:
    """為 atom 建立新的 access 檔（覆蓋既存）。

    用於：MCP atom_write create / hook:episodic atom 建立時。
    若已存在 → 不覆蓋既有計數，只補齊缺欄並保留現值。
    """
    _validate_source(source)
    access_path = _access_path(atom_path)
    today = _today_str()
    raw = _read_raw(access_path) or {}
    raw, _ = _normalize(raw)
    if not raw.get("first_seen"):
        raw["first_seen"] = first_seen or today
    if not raw.get("last_used"):
        raw["last_used"] = today
    _write_raw(access_path, raw)
    return _audit("access_init", source, atom_path, first_seen=raw["first_seen"])


def increment_read_hits(atom_path: Path, *, source: str) -> int:
    """read_hits++、刷 last_used=today、append timestamp（最多 50 筆）。

    對拍 hooks/workflow-guardian.py:1350-1375 行為（取代直接 .write_text）。
    """
    _validate_source(source)
    access_path = _access_path(atom_path)
    raw = _read_raw(access_path) or {}
    raw, _ = _normalize(raw)
    raw["read_hits"] = int(raw.get("read_hits") or 0) + 1
    raw["last_used"] = _today_str()
    if not raw.get("first_seen"):
        raw["first_seen"] = raw["last_used"]
    timestamps = list(raw.get("timestamps") or [])
    timestamps.append(time.time())
    raw["timestamps"] = timestamps[-TIMESTAMPS_MAX:]
    if not _write_raw(access_path, raw):
        _audit("access_increment_dropped", source, atom_path,
               field="read_hits", reason="write_contention")
        return int(raw["read_hits"]) - 1  # 視同未生效
    _audit("access_increment", source, atom_path,
           field="read_hits", new_count=raw["read_hits"])
    return raw["read_hits"]


def increment_confirmation(
    atom_path: Path, *, event: Optional[Dict[str, Any]] = None, source: str,
) -> int:
    """confirmations++、append event 到 confirmation_events、刷 last_used。

    對拍 hooks/wg_episodic.py:370-373 cross-session confirmation 行為。
    """
    _validate_source(source)
    access_path = _access_path(atom_path)
    raw = _read_raw(access_path) or {}
    raw, _ = _normalize(raw)
    raw["confirmations"] = int(raw.get("confirmations") or 0) + 1
    raw["last_used"] = _today_str()
    if not raw.get("first_seen"):
        raw["first_seen"] = raw["last_used"]
    events: List[Dict[str, Any]] = list(raw.get("confirmation_events") or [])
    if event is None:
        event = {}
    if "ts" not in event:
        event["ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    events.append(event)
    raw["confirmation_events"] = events
    if not _write_raw(access_path, raw):
        _audit("access_increment_dropped", source, atom_path,
               field="confirmations", reason="write_contention")
        return int(raw["confirmations"]) - 1
    _audit("access_increment", source, atom_path,
           field="confirmations", new_count=raw["confirmations"])
    return raw["confirmations"]


def record_promotion(atom_path: Path, *, target_confidence: str, source: str) -> str:
    """寫 last_promoted_at = today、刷 last_used。

    對拍 tools/workflow-guardian-mcp/server.js:1501 atom_promote 行為。
    """
    _validate_source(source)
    access_path = _access_path(atom_path)
    raw = _read_raw(access_path) or {}
    raw, _ = _normalize(raw)
    today = _today_str()
    raw["last_promoted_at"] = today
    raw["last_used"] = today
    if not raw.get("first_seen"):
        raw["first_seen"] = today
    _write_raw(access_path, raw)
    return _audit("access_promote", source, atom_path,
                  target_confidence=target_confidence)


def write_access_field(
    atom_path: Path, *, field: str, value: Any, source: str,
) -> str:
    """通用單欄位寫入（給 tool:memory-audit restore 等少見場景）。"""
    _validate_source(source)
    allowed = {
        "read_hits", "last_used", "confirmations", "last_promoted_at",
        "first_seen",
    }
    if field not in allowed:
        raise ValueError(f"field not allowed via write_access_field: {field}")
    access_path = _access_path(atom_path)
    raw = _read_raw(access_path) or {}
    raw, _ = _normalize(raw)
    raw[field] = value
    _write_raw(access_path, raw)
    return _audit("access_field", source, atom_path, field=field, value=str(value))


def bulk_read(memory_root: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """掃描 memory 樹下所有 *.access.json，回傳 {atom_id: access_dict}。

    給 hooks/wg_iteration.py 衰退掃描 / tools/memory-audit.py / tools/atom-health-audit.py 用。
    atom_id = access 檔 stem（不含 .access）；跨 scope 統一 namespace。
    """
    root = memory_root or GLOBAL_MEMORY_DIR
    out: Dict[str, Dict[str, Any]] = {}
    for p in root.rglob("*.access.json"):
        # stem = "foo.access" → atom_id = "foo"
        atom_id = p.name[:-len(".access.json")]
        raw = _read_raw(p)
        if raw is None:
            continue
        normalized, _ = _normalize(raw)
        out[atom_id] = normalized
    return out


# ─── CLI 入口（給 server.js 子程序呼叫） ──────────────────────────────────────


def _cli() -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="atom_access")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_read = sub.add_parser("read")
    p_read.add_argument("path")

    p_init = sub.add_parser("init")
    p_init.add_argument("path")
    p_init.add_argument("--first-seen", default=None)
    p_init.add_argument("--source", required=True)

    p_inc_rh = sub.add_parser("increment-read-hits")
    p_inc_rh.add_argument("path")
    p_inc_rh.add_argument("--source", required=True)

    p_inc_cf = sub.add_parser("increment-confirmation")
    p_inc_cf.add_argument("path")
    p_inc_cf.add_argument("--source", required=True)
    p_inc_cf.add_argument("--event-json", default="{}")

    p_promo = sub.add_parser("record-promotion")
    p_promo.add_argument("path")
    p_promo.add_argument("--target", required=True)
    p_promo.add_argument("--source", required=True)

    p_set = sub.add_parser("set")
    p_set.add_argument("path")
    p_set.add_argument("--field", required=True)
    p_set.add_argument("--value", required=True)
    p_set.add_argument("--source", required=True)

    args = parser.parse_args()
    atom_path = Path(args.path)

    try:
        if args.cmd == "read":
            data = read_access(atom_path)
            print(json.dumps(data, ensure_ascii=False))
        elif args.cmd == "init":
            init_access(atom_path, first_seen=args.first_seen, source=args.source)
            print(json.dumps({"ok": True}))
        elif args.cmd == "increment-read-hits":
            n = increment_read_hits(atom_path, source=args.source)
            print(json.dumps({"ok": True, "read_hits": n}))
        elif args.cmd == "increment-confirmation":
            event = json.loads(args.event_json) if args.event_json else {}
            n = increment_confirmation(atom_path, event=event, source=args.source)
            print(json.dumps({"ok": True, "confirmations": n}))
        elif args.cmd == "record-promotion":
            record_promotion(
                atom_path, target_confidence=args.target, source=args.source,
            )
            print(json.dumps({"ok": True}))
        elif args.cmd == "set":
            # value 嘗試解析為 int，失敗則維持 str
            v: Any = args.value
            try:
                v = int(v)
            except (ValueError, TypeError):
                pass
            write_access_field(
                atom_path, field=args.field, value=v, source=args.source,
            )
            print(json.dumps({"ok": True}))
    except (ValueError, OSError) as e:
        print(json.dumps({"ok": False, "error": str(e)}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
