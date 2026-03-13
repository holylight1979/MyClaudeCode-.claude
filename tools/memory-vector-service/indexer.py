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
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

CLAUDE_DIR = Path.home() / ".claude"
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
) -> List[Tuple[str, Path]]:
    """Discover all memory layers. Returns [(layer_name, memory_dir), ...]."""
    layers: List[Tuple[str, Path]] = []

    # Global layer
    global_mem = CLAUDE_DIR / "memory"
    if global_mem.is_dir():
        if not layer_filter or layer_filter == "global":
            layers.append(("global", global_mem))

    # Project layers
    projects_dir = CLAUDE_DIR / "projects"
    if projects_dir.is_dir():
        for proj_dir in sorted(projects_dir.iterdir()):
            if not proj_dir.is_dir():
                continue
            if layer_filter and layer_filter not in ("all", "project") and layer_filter != proj_dir.name:
                continue
            mem_dir = proj_dir / "memory"
            if mem_dir.is_dir():
                layers.append((f"project:{proj_dir.name}", mem_dir))

    # Additional atom directories (from config)
    if additional_dirs:
        for entry in additional_dirs:
            name = entry.get("name", "extra")
            dir_path = Path(entry.get("path", ""))
            if dir_path.is_dir():
                if not layer_filter or layer_filter in ("all", name):
                    layers.append((f"extra:{name}", dir_path))

    return layers


def discover_atoms(
    layers: List[Tuple[str, Path]],
    include_distant: bool = False,
    additional_dirs: Optional[List[Dict[str, Any]]] = None,
) -> List[Tuple[str, Path, str]]:
    """Find all atom .md files. Returns [(layer_name, file_path, rel_path), ...]."""
    atoms: List[Tuple[str, Path, str]] = []

    # Build per-layer skip_files from additional_dirs config
    extra_skip: Dict[str, set] = {}
    if additional_dirs:
        for entry in additional_dirs:
            name = f"extra:{entry.get('name', 'extra')}"
            extra_skip[name] = set(entry.get("skip_files", []))

    for layer_name, mem_dir in layers:
        layer_skip_files = extra_skip.get(layer_name, set())
        is_extra = layer_name.startswith("extra:")

        # Recursive scanning for all layers; skip files in _-prefixed directories
        glob_patterns = ["**/*.md"]
        seen_paths: set = set()
        for glob_pattern in glob_patterns:
            for md_file in sorted(mem_dir.glob(glob_pattern)):
                if md_file in seen_paths:
                    continue
                seen_paths.add(md_file)
                # Skip files inside any _-prefixed directory (e.g. _distant, _vectordb)
                rel_parts = md_file.relative_to(mem_dir).parts
                if any(part.startswith("_") for part in rel_parts[:-1]):
                    continue
                if md_file.name in SKIP_FILENAMES:
                    continue
                if any(md_file.name.startswith(p) for p in SKIP_PREFIXES):
                    continue
                # Per-source skip_files (match stem)
                if md_file.stem in layer_skip_files:
                    continue
                rel = str(md_file.relative_to(mem_dir))
                atoms.append((layer_name, md_file, rel))

        # _distant/ 遙遠記憶 (standard layers only)
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
    atom_type = "semantic"
    tags_str = ""
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
            elif key == "Confirmations":
                cm2 = re.search(r"\d+", val)
                confirmations = int(cm2.group()) if cm2 else 0
            elif key == "Type":
                if val in ("semantic", "episodic", "procedural"):
                    atom_type = val
            elif key == "Tags":
                tags_str = val

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
                    "atom_type": atom_type,
                    "tags": tags_str,
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
    """Embedding via Ollama HTTP API."""

    def __init__(self, model: str = "qwen3-embedding", base_url: str = "http://127.0.0.1:11434"):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._dimension: Optional[int] = None

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status == 200
        except Exception:
            return False

    def embed(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of texts. Ollama /api/embed supports batch."""
        payload = json.dumps({"model": self.model, "input": texts}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
        embeddings = result.get("embeddings", [])
        if embeddings and self._dimension is None:
            self._dimension = len(embeddings[0])
        return embeddings

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            # Probe with a dummy text
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
    """Create embedder based on config, with fallback."""
    backend = config.get("embedding_backend", "ollama")
    if backend == "ollama":
        emb = OllamaEmbedder(
            model=config.get("embedding_model", "qwen3-embedding"),
            base_url=config.get("ollama_base_url", "http://127.0.0.1:11434"),
        )
        if emb.is_available():
            return emb
        # Fallback
        print("[indexer] Ollama unavailable, falling back to sentence-transformers", file=sys.stderr)

    fb_model = config.get("fallback_model", "BAAI/bge-m3")
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
                "atom_type": chunk.get("atom_type", "semantic"),
                "tags": chunk.get("tags", ""),
            })
            total_chunks += 1

    # Embed all texts
    if records:
        texts = [r["text"] for r in records]
        if verbose:
            print(f"[indexer] Embedding {len(texts)} chunks...")
        batch_size = 32
        all_vecs: List[List[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            vecs = embedder.embed(batch)
            all_vecs.extend(vecs)

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
) -> List[Dict[str, Any]]:
    """Search LanceDB table by vector. Returns list of dicts with _distance."""
    try:
        db = _get_db()
        table = db.open_table(TABLE_NAME)
        q = table.search(query_vec).limit(top_k).metric("cosine")
        if layer_filter and layer_filter not in ("all", None):
            if layer_filter == "global":
                q = q.where(f"layer = 'global'")
            elif layer_filter.startswith("project:"):
                q = q.where(f"layer = '{layer_filter}'")
        results = q.to_list()
        return results
    except Exception:
        return []


if __name__ == "__main__":
    from config import load_config
    cfg = load_config()
    stats = build_index(cfg, incremental=False, verbose=True)
    print(json.dumps(stats, indent=2, ensure_ascii=False))
