"""
indexer.py — 段落級 Atom 索引器

負責：
1. 發現所有 memory 層的 atom 檔案
2. 解析 atom 結構，切割成段落級 chunk
3. 用 embedding 模型轉成向量
4. 寫入 ChromaDB

支援雙後端：Ollama (qwen3-embedding) + sentence-transformers (bge-m3)
支援增量索引：比對 file_hash，只重新索引有變動的 atom
"""

import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# V2.20: import wg_paths for centralized path logic
sys.path.insert(0, str(Path.home() / ".claude" / "hooks"))
from ollama_client import get_client
from wg_paths import CLAUDE_DIR, MEMORY_DIR, discover_memory_layers
COLLECTION_NAME = "atom_memory"

# Atom 檔案排除清單
SKIP_FILENAMES = {"MEMORY.md", "_CHANGELOG.md", "_CHANGELOG_ARCHIVE.md"}
SKIP_PREFIXES = ("SPEC_", "_")

# 不索引的 section
SKIP_SECTIONS = {"演化日誌"}

# 元資料行 pattern
META_RE = re.compile(r"^-\s+(\w[\w-]*):\s*(.+)$")


# ─── Atom Discovery ─────────────────────────────────────────────────────────


def discover_layers(
    layer_filter: Optional[str] = None,
    include_distant: bool = False,
    additional_dirs: Optional[List[Dict[str, Any]]] = None,
) -> List[Tuple[str, Path, str]]:
    """Discover all memory layers. Returns [(layer_name, memory_dir, kind), ...].

    V4: 用 wg_paths.discover_v4_sublayers / discover_memory_layers，產生
    global + shared:{slug} / role:{slug}:{r} / personal:{slug}:{u} 子層。
    kind ∈ {"recursive","flat-legacy","extra"}：indexer 用來決定是否遞迴。
    """
    from wg_paths import discover_all_project_memory_dirs, discover_v4_sublayers

    layers: List[Tuple[str, Path, str]] = []

    def _accept(label: str) -> bool:
        if not layer_filter or layer_filter == "all":
            return True
        if layer_filter == label:
            return True
        if layer_filter == "global":
            return label == "global"
        if layer_filter == "shared":
            return label.startswith("shared:")
        if layer_filter == "role":
            return label.startswith("role:")
        if layer_filter == "personal":
            return label.startswith("personal:")
        return False

    if _accept("global"):
        layers.append(("global", MEMORY_DIR, "recursive"))

    for slug, mem_dir in discover_all_project_memory_dirs():
        for label, path, kind in discover_v4_sublayers(slug, mem_dir):
            if _accept(label):
                layers.append((label, path, kind))

    # Additional atom directories (config-driven)
    if additional_dirs:
        for entry in additional_dirs:
            name = entry.get("name", "extra")
            dir_path = Path(entry.get("path", ""))
            if dir_path.is_dir():
                label = f"extra:{name}"
                if not layer_filter or layer_filter in ("all", name, label):
                    layers.append((label, dir_path, "extra"))

    return layers


def discover_atoms(
    layers: List[Tuple[str, Path, str]],
    include_distant: bool = False,
    additional_dirs: Optional[List[Dict[str, Any]]] = None,
) -> List[Tuple[str, Path, str]]:
    """Find all atom .md files. Returns [(layer_name, file_path, rel_path), ...].

    Layer 三元組 kind 控制掃描行為：
      - "flat-legacy"：只掃 mem_dir 直下 .md，不進子目錄
      - "recursive" / "extra"：遞迴 **/*.md（仍跳 _-prefixed 目錄）
    """
    atoms: List[Tuple[str, Path, str]] = []

    extra_skip: Dict[str, set] = {}
    if additional_dirs:
        for entry in additional_dirs:
            name = f"extra:{entry.get('name', 'extra')}"
            extra_skip[name] = set(entry.get("skip_files", []))

    # Backward compat：若呼叫者傳的是 2-tuple list，補上 "recursive" kind
    norm_layers: List[Tuple[str, Path, str]] = []
    for item in layers:
        if len(item) == 2:
            norm_layers.append((item[0], item[1], "recursive"))
        else:
            norm_layers.append(item)

    for layer_name, mem_dir, kind in norm_layers:
        layer_skip_files = extra_skip.get(layer_name, set())
        is_extra = layer_name.startswith("extra:")

        if kind == "flat-legacy":
            # 只掃直下 .md，避免重複索引 shared/roles/personal 子目錄
            iter_files = sorted(p for p in mem_dir.iterdir() if p.is_file() and p.suffix == ".md")
            for md_file in iter_files:
                if md_file.name in SKIP_FILENAMES:
                    continue
                if any(md_file.name.startswith(p) for p in SKIP_PREFIXES):
                    continue
                if md_file.stem in layer_skip_files:
                    continue
                rel = str(md_file.relative_to(mem_dir))
                atoms.append((layer_name, md_file, rel))
            continue

        # recursive / extra
        seen_paths: set = set()
        for md_file in sorted(mem_dir.glob("**/*.md")):
            if md_file in seen_paths:
                continue
            seen_paths.add(md_file)
            rel_parts = md_file.relative_to(mem_dir).parts
            if any(part.startswith("_") for part in rel_parts[:-1]):
                continue
            if md_file.name in SKIP_FILENAMES:
                continue
            if any(md_file.name.startswith(p) for p in SKIP_PREFIXES):
                continue
            if md_file.stem in layer_skip_files:
                continue
            rel = str(md_file.relative_to(mem_dir))
            atoms.append((layer_name, md_file, rel))

        if include_distant and not is_extra:
            distant_dir = mem_dir / "_distant"
            if distant_dir.is_dir():
                for sub in sorted(distant_dir.iterdir()):
                    if sub.is_dir():
                        for md_file in sorted(sub.glob("*.md")):
                            rel = str(md_file.relative_to(mem_dir))
                            atoms.append((layer_name, md_file, rel))

    return atoms


# ─── Atom Parsing & Chunking ────────────────────────────────────────────────


def _default_scope_from_layer(layer: str) -> str:
    """舊 atom 無 Scope metadata 時，依所在 layer 推回預設 scope（SPEC §10）。

    - global      → "global"
    - shared:*    → "shared"
    - role:*:{r}  → "role:{r}"
    - personal:*:{u} → "personal:{u}"
    其他（extra:* 等）→ ""
    """
    if layer == "global":
        return "global"
    if layer.startswith("shared:"):
        return "shared"
    if layer.startswith("role:"):
        parts = layer.split(":")
        return f"role:{parts[-1]}" if len(parts) >= 3 else "shared"
    if layer.startswith("personal:"):
        parts = layer.split(":")
        return f"personal:{parts[-1]}" if len(parts) >= 3 else ""
    return ""


def file_hash(path: Path) -> str:
    """MD5 hash of file content for incremental indexing."""
    try:
        return hashlib.md5(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def parse_and_chunk(
    layer_name: str, file_path: Path, rel_path: str
) -> List[Dict[str, Any]]:
    """Parse an atom file and return a list of chunks with metadata.

    Chunking strategy:
    - Skip metadata block and 演化日誌
    - Each top-level bullet (- ...) under ## sections becomes a chunk
    - Sub-bullets (indented) are merged into parent
    - Section headers (##/###) provide context
    """
    try:
        text = file_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return []

    lines = text.splitlines()
    if not lines:
        return []

    # Extract metadata
    atom_name = file_path.stem
    title = ""
    confidence = ""
    last_used = ""
    confirmations = 0
    readhits = 0
    atom_type = "semantic"
    tags_str = ""
    scope_meta = ""      # V4: "shared" | "role:{r}" | "personal:{u}" | "global"
    audience_meta = ""   # V4: 逗號分隔 role 列表
    author_meta = ""     # V4: 寫入者 user
    for line in lines:
        if line.startswith("# ") and not line.startswith("## "):
            title = line[2:].strip()
        m = META_RE.match(line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if key == "Confidence":
                # Extract [固]/[觀]/[臨]
                cm = re.search(r"\[(固|觀|臨)\]", val)
                confidence = f"[{cm.group(1)}]" if cm else val
            elif key == "Last-used":
                last_used = val
            elif key == "ReadHits":
                cm2 = re.search(r"\d+", val)
                readhits = int(cm2.group()) if cm2 else 0
            elif key == "Confirmations":
                cm2 = re.search(r"\d+", val)
                confirmations = int(cm2.group()) if cm2 else 0
            elif key == "Type":
                if val in ("semantic", "episodic", "procedural"):
                    atom_type = val
            elif key == "Tags":
                tags_str = val
            elif key == "Scope":
                scope_meta = val
            elif key == "Audience":
                audience_meta = val
            elif key == "Author":
                author_meta = val

    fhash = file_hash(file_path)
    chunks: List[Dict[str, Any]] = []

    # State machine for parsing sections
    current_section = ""  # ## level
    current_subsection = ""  # ### level
    in_skip_section = False
    in_metadata = True  # Start in metadata block

    current_bullet_lines: List[str] = []
    current_bullet_start = 0

    def flush_bullet():
        nonlocal current_bullet_lines, current_bullet_start
        if current_bullet_lines:
            text_content = "\n".join(current_bullet_lines).strip()
            if text_content and len(text_content) > 5:  # Skip trivially short
                # Build section context
                section_ctx = current_section
                if current_subsection:
                    section_ctx = f"{current_section} > {current_subsection}"
                chunks.append({
                    "text": text_content,
                    "atom_name": atom_name,
                    "title": title,
                    "section": section_ctx or "未分類",
                    "confidence": confidence,
                    "file_path": rel_path,
                    "layer": layer_name,
                    "file_hash": fhash,
                    "line_number": current_bullet_start,
                    "last_used": last_used,
                    "confirmations": confirmations,
                    "readhits": readhits,
                    "atom_type": atom_type,
                    "tags": tags_str,
                    "scope": scope_meta,
                    "audience": audience_meta,
                    "author": author_meta,
                })
            current_bullet_lines = []

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # Detect end of metadata block
        if in_metadata:
            if stripped.startswith("## "):
                in_metadata = False
                # fall through to section handling
            elif stripped == "" and i > 2:
                # Empty line after some content — might be end of metadata
                # but only if we've seen metadata lines
                continue
            elif META_RE.match(stripped) or stripped.startswith("# "):
                continue
            elif stripped == "---":
                continue
            else:
                if not stripped:
                    continue
                in_metadata = False
                # fall through

        # Section headers
        if stripped.startswith("## "):
            flush_bullet()
            section_name = stripped[3:].strip()
            if any(s in section_name for s in SKIP_SECTIONS):
                in_skip_section = True
                continue
            in_skip_section = False
            current_section = section_name
            current_subsection = ""
            continue

        if stripped.startswith("### "):
            flush_bullet()
            current_subsection = stripped[4:].strip()
            continue

        if in_skip_section:
            continue

        # Skip horizontal rules and table headers/separators
        if stripped == "---" or stripped.startswith("|"):
            continue

        # Top-level bullet = new chunk
        if line.startswith("- ") or (len(line) > 2 and line[0] == "-" and line[1] == " "):
            flush_bullet()
            current_bullet_lines = [stripped]
            current_bullet_start = i
        # Sub-bullet or continuation (indented)
        elif (line.startswith("  ") or line.startswith("\t")) and current_bullet_lines:
            current_bullet_lines.append(stripped)
        # Non-bullet text in a section (paragraph)
        elif stripped and current_section and not current_bullet_lines:
            # Treat standalone text as a chunk
            current_bullet_lines = [stripped]
            current_bullet_start = i

    flush_bullet()
    return chunks


# ─── Embedding Backends ─────────────────────────────────────────────────────


class OllamaEmbedder:
    """Embedding via dual-backend Ollama client."""

    def __init__(self):
        self._client = get_client()
        self._dimension: Optional[int] = None

    def is_available(self) -> bool:
        return self._client.is_available("embedding")

    def embed(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of texts via OllamaClient."""
        embeddings = self._client.embed(texts)
        if embeddings and self._dimension is None:
            self._dimension = len(embeddings[0])
        return embeddings

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            vecs = self.embed(["test"])
            if vecs:
                self._dimension = len(vecs[0])
        return self._dimension or 1024


class SentenceTransformerEmbedder:
    """Embedding via sentence-transformers (local GPU/CPU)."""

    def __init__(self, model_name: str = "BAAI/bge-m3"):
        self.model_name = model_name
        self._model = None
        self._dimension: Optional[int] = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
            self._dimension = self._model.get_sentence_embedding_dimension()

    def is_available(self) -> bool:
        try:
            self._load()
            return True
        except Exception:
            return False

    def embed(self, texts: List[str]) -> List[List[float]]:
        self._load()
        embeddings = self._model.encode(texts, normalize_embeddings=True)
        return [e.tolist() for e in embeddings]

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            self._load()
        return self._dimension or 1024

    def unload(self):
        """Release GPU memory."""
        if self._model is not None:
            del self._model
            self._model = None
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass


def create_embedder(config: Dict[str, Any]) -> Any:
    """Create embedder based on config, with fallback.

    When fallback_backend is "none", skip sentence-transformers entirely.
    This prevents accidentally loading a multi-GB model.
    """
    backend = config.get("embedding_backend", "ollama")
    if backend == "ollama":
        emb = OllamaEmbedder()
        if emb.is_available():
            return emb
        # Fallback
        print("[indexer] Ollama unavailable, checking fallback...", file=sys.stderr)

    # Respect fallback_backend: "none" — do NOT try sentence-transformers
    fb_backend = config.get("fallback_backend", "sentence-transformers")
    if fb_backend in ("none", "None", "", None):
        raise RuntimeError(
            "No embedding backend available. Ollama is unreachable and "
            "fallback_backend is set to 'none'."
        )

    fb_model = config.get("fallback_model", "BAAI/bge-m3")
    if fb_model in ("none", "None", "", None):
        raise RuntimeError(
            "No embedding backend available. Ollama is unreachable and "
            "fallback_model is set to 'none'."
        )

    emb = SentenceTransformerEmbedder(model_name=fb_model)
    if emb.is_available():
        return emb

    raise RuntimeError("No embedding backend available. Install Ollama or sentence-transformers.")


# ─── LanceDB Operations ──────────────────────────────────────────────────────


DB_DIR = CLAUDE_DIR / "memory" / "_vectordb"
TABLE_NAME = "atom_chunks"


def _get_db():
    """Get LanceDB connection."""
    import lancedb
    DB_DIR.mkdir(parents=True, exist_ok=True)
    return lancedb.connect(str(DB_DIR))


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def build_index(
    config: Dict[str, Any],
    incremental: bool = False,
    layer_filter: Optional[str] = None,
    verbose: bool = False,
) -> Dict[str, Any]:
    """Build or update the vector index. Returns stats dict."""
    import pyarrow as pa
    t0 = time.time()

    additional_dirs = config.get("additional_atom_dirs", [])
    layers = discover_layers(
        layer_filter=layer_filter,
        include_distant=config.get("index_distant", False),
        additional_dirs=additional_dirs,
    )
    atoms = discover_atoms(
        layers,
        include_distant=config.get("index_distant", False),
        additional_dirs=additional_dirs,
    )

    if verbose:
        print(f"[indexer] Found {len(layers)} layers, {len(atoms)} atom files")

    embedder = create_embedder(config)
    if verbose:
        print(f"[indexer] Using embedder: {embedder.__class__.__name__}")

    db = _get_db()

    # For incremental: load existing hashes
    existing_hashes: Dict[str, str] = {}
    if incremental:
        try:
            table = db.open_table(TABLE_NAME)
            rows = table.search().select(["layer", "atom_name", "file_hash"]).limit(table.count_rows()).to_list()
            for row in rows:
                key = f"{row.get('layer', '')}:{row.get('atom_name', '')}"
                existing_hashes[key] = row.get("file_hash", "")
        except Exception:
            pass

    # Collect all chunks
    records: List[Dict[str, Any]] = []
    skipped = 0
    total_chunks = 0

    for layer_name, file_path, rel_path in atoms:
        atom_name = file_path.stem
        fhash = file_hash(file_path)
        atom_key = f"{layer_name}:{atom_name}"

        if incremental and existing_hashes.get(atom_key) == fhash:
            skipped += 1
            continue

        chunks = parse_and_chunk(layer_name, file_path, rel_path)
        if verbose:
            print(f"  {atom_key}: {len(chunks)} chunks")

        for ci, chunk in enumerate(chunks):
            # V4: 舊 atom 缺 Scope → 依所在 layer 推預設（SPEC §10）
            chunk_scope = chunk.get("scope", "") or _default_scope_from_layer(chunk["layer"])
            records.append({
                "chunk_id": f"{layer_name}:{atom_name}:chunk_{ci}",
                "text": chunk["text"],
                "atom_name": chunk["atom_name"],
                "title": chunk.get("title", ""),
                "section": chunk["section"],
                "confidence": chunk["confidence"],
                "file_path": chunk["file_path"],
                "layer": chunk["layer"],
                "file_hash": chunk["file_hash"],
                "line_number": chunk["line_number"],
                "last_used": chunk.get("last_used", ""),
                "confirmations": chunk.get("confirmations", 0),
                "readhits": chunk.get("readhits", 0),
                "atom_type": chunk.get("atom_type", "semantic"),
                "tags": chunk.get("tags", ""),
                "scope": chunk_scope,
                "audience": chunk.get("audience", ""),
                "author": chunk.get("author", "") or "unknown",
            })
            total_chunks += 1

    # Embed all texts
    if records:
        texts = [r["text"] for r in records]
        if verbose:
            print(f"[indexer] Embedding {len(texts)} chunks...")
        batch_size = 16
        all_vecs: List[List[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            for attempt in range(3):
                try:
                    vecs = embedder.embed(batch)
                    all_vecs.extend(vecs)
                    break
                except Exception as e:
                    if attempt < 2:
                        if verbose:
                            print(f"[indexer] Batch {i//batch_size} retry {attempt+1}: {e}")
                        time.sleep(2)
                    else:
                        raise RuntimeError(f"Embedding batch {i//batch_size} failed after 3 retries: {e}")
            if verbose and (i // batch_size) % 20 == 0:
                print(f"[indexer] Progress: {min(i + batch_size, len(texts))}/{len(texts)}")

        for i, rec in enumerate(records):
            rec["vector"] = all_vecs[i]

    # Write to LanceDB
    if records:
        if incremental:
            # Delete changed atoms first, then add new
            try:
                table = db.open_table(TABLE_NAME)
                changed_atoms = {f"{r['layer']}:{r['atom_name']}" for r in records}
                for ak in changed_atoms:
                    layer_val, atom_val = ak.split(":", 1)
                    # Escape single quotes to prevent query breakage
                    layer_val = layer_val.replace("'", "''")
                    atom_val = atom_val.replace("'", "''")
                    table.delete(f"layer = '{layer_val}' AND atom_name = '{atom_val}'")
                table.add(records)
            except Exception:
                # Table doesn't exist or other error → full write
                db.create_table(TABLE_NAME, records, mode="overwrite")
        else:
            db.create_table(TABLE_NAME, records, mode="overwrite")

    elif not incremental:
        # No records and full rebuild → create empty-ish table or skip
        pass

    elapsed = time.time() - t0
    stats = {
        "atoms_found": len(atoms),
        "atoms_indexed": len(atoms) - skipped,
        "atoms_skipped": skipped,
        "total_chunks": total_chunks,
        "layers": len(layers),
        "elapsed_seconds": round(elapsed, 2),
        "incremental": incremental,
        "embedder": embedder.__class__.__name__,
    }

    if verbose:
        print(f"[indexer] Done: {total_chunks} chunks from {len(atoms) - skipped} atoms in {elapsed:.1f}s")

    return stats


def get_index_status(config: Dict[str, Any]) -> Dict[str, Any]:
    """Get current index status."""
    try:
        db = _get_db()
        table = db.open_table(TABLE_NAME)
        total = table.count_rows()
        # Use to_list() with select to avoid pandas dependency
        rows = table.search().select(["atom_name", "layer"]).limit(total).to_list()
        atoms = set()
        layer_set = set()
        for row in rows:
            atoms.add(f"{row.get('layer', '')}:{row.get('atom_name', '')}")
            layer_set.add(row.get("layer", ""))

        return {
            "total_chunks": total,
            "unique_atoms": len(atoms),
            "layers": sorted(layer_set),
            "table": TABLE_NAME,
            "db_path": str(DB_DIR),
        }
    except Exception as e:
        return {"error": str(e), "total_chunks": 0}


def search_vectors(
    query_vec: List[float],
    top_k: int = 10,
    layer_filter: Optional[str] = None,
    layer_clause: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Search LanceDB table by vector. Returns list of dicts with _distance.

    `layer_clause`（V4）優先於 `layer_filter`：呼叫者已組好 SQL 字串（例如
    role filter combo）就直接傳，搜尋端不再二次解析。
    """
    try:
        db = _get_db()
        table = db.open_table(TABLE_NAME)
        q = table.search(query_vec).limit(top_k).metric("cosine")

        if layer_clause:
            q = q.where(layer_clause)
        elif layer_filter and layer_filter not in ("all", None):
            safe_filter = layer_filter.replace("'", "''")
            if layer_filter == "global":
                q = q.where("layer = 'global'")
            elif layer_filter.startswith("project:"):
                # Legacy V3 label；V4 已淘汰但保留讀相容（index 中若仍有殘餘）
                q = q.where(f"layer = '{safe_filter}'")
            elif layer_filter == "shared":
                q = q.where("layer LIKE 'shared:%'")
            elif layer_filter == "role":
                q = q.where("layer LIKE 'role:%'")
            elif layer_filter == "personal":
                q = q.where("layer LIKE 'personal:%'")
            elif layer_filter.startswith("shared:") or layer_filter.startswith("role:") or layer_filter.startswith("personal:"):
                q = q.where(f"layer = '{safe_filter}'")
        results = q.to_list()
        return results
    except Exception:
        return []


if __name__ == "__main__":
    from config import load_config
    cfg = load_config()
    stats = build_index(cfg, incremental=False, verbose=True)
    print(json.dumps(stats, indent=2, ensure_ascii=False))
