"""
config.py — Memory Vector Service 設定管理

讀取 ~/.claude/workflow/config.json 的 vector_search 區塊。
所有設定都有合理預設值，config.json 不存在時也能正常運作。
"""

import json
from pathlib import Path
from typing import Any, Dict

CLAUDE_DIR = Path.home() / ".claude"
CONFIG_PATH = CLAUDE_DIR / "workflow" / "config.json"
VECTORDB_DIR = CLAUDE_DIR / "memory" / "_vectordb"

DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    "service_port": 3849,
    "embedding_backend": "ollama",          # "ollama" | "sentence-transformers"
    "embedding_model": "qwen3-embedding",   # Ollama model name
    "fallback_backend": "sentence-transformers",
    "fallback_model": "BAAI/bge-m3",
    "ollama_base_url": "http://127.0.0.1:11434",
    "ollama_llm_model": "qwen3:4b",
    "search_top_k": 5,
    "search_min_score": 0.65,
    "search_timeout_ms": 2000,
    "auto_start_service": True,
    "auto_index_on_change": True,
    "index_distant": False,                 # 是否索引 _distant/ 遙遠記憶
    "additional_atom_dirs": [],              # 額外 atom 來源目錄
}


def load_config() -> Dict[str, Any]:
    """Load vector_search config with defaults fallback."""
    config = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                full = json.load(f)
            vs = full.get("vector_search", {})
            config.update({k: v for k, v in vs.items() if k in DEFAULTS or k == "additional_atom_dirs"})
        except (json.JSONDecodeError, OSError):
            pass
    return config


def save_config(config: Dict[str, Any]) -> None:
    """Save vector_search config back to config.json (merge, not overwrite)."""
    full: Dict[str, Any] = {}
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                full = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    full["vector_search"] = {k: v for k, v in config.items() if k in DEFAULTS}
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(full, f, indent=2, ensure_ascii=False)
