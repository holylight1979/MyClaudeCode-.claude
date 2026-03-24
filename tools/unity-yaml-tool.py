#!/usr/bin/env python3
"""Unity YAML Asset Tool — parse, generate, modify Unity .asset/.prefab/.unity files.

Unity YAML uses custom `!u!{ClassID}` tags that standard YAML parsers can't handle.
This tool provides a layer that preserves Unity's format while enabling programmatic access.

Usage:
    python unity-yaml-tool.py parse <file>                         # Parse and dump as JSON
    python unity-yaml-tool.py generate-asset <json> <output>       # Generate .asset from JSON spec
    python unity-yaml-tool.py generate-meta <output> [--guid]      # Generate .meta file
    python unity-yaml-tool.py modify <file> <field> <value>        # Modify a field in-place
    python unity-yaml-tool.py template <src> <output> <json>       # Clone asset, replace fields
    python unity-yaml-tool.py generate-prefab <json> <output>      # Generate simple prefab
    python unity-yaml-tool.py generate-ui-prefab <json> <output>   # Generate WndForm UI prefab
    python unity-yaml-tool.py validate <file>                      # Validate prefab integrity
"""

import sys
import json
import re
import uuid
import random
import copy
import os
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple


# ── Unity ClassID constants ──────────────────────────────────────────────────

CLASS_IDS = {
    "GameObject": 1,
    "Transform": 4,
    "Camera": 20,
    "MeshRenderer": 23,
    "MeshFilter": 33,
    "BoxCollider": 65,
    "Animator": 95,
    "SphereCollider": 135,
    "MonoBehaviour": 114,
    "MonoScript": 115,
    "ParticleSystem": 198,
    "ParticleSystemRenderer": 199,
    "CanvasRenderer": 222,
    "Canvas": 223,
    "RectTransform": 224,
    "CanvasGroup": 225,
    "OcclusionCullingSettings": 29,
    "RenderSettings": 104,
    "LightmapSettings": 157,
    "NavMeshSettings": 196,
    "Prefab": 1001,
    "PrefabInstance": 1001480554,
}

# ── Anchor Presets ────────────────────────────────────────────────────────────
# Each preset: (anchorMin, anchorMax, pivot)
# sizeDelta is set separately (0,0 for stretch, explicit for fixed)

ANCHOR_PRESETS = {
    "stretch":       ({"x": 0, "y": 0}, {"x": 1, "y": 1}, {"x": 0.5, "y": 0.5}),
    "top-left":      ({"x": 0, "y": 1}, {"x": 0, "y": 1}, {"x": 0, "y": 1}),
    "top-center":    ({"x": 0.5, "y": 1}, {"x": 0.5, "y": 1}, {"x": 0.5, "y": 1}),
    "top-right":     ({"x": 1, "y": 1}, {"x": 1, "y": 1}, {"x": 1, "y": 1}),
    "middle-left":   ({"x": 0, "y": 0.5}, {"x": 0, "y": 0.5}, {"x": 0, "y": 0.5}),
    "center":        ({"x": 0.5, "y": 0.5}, {"x": 0.5, "y": 0.5}, {"x": 0.5, "y": 0.5}),
    "middle-right":  ({"x": 1, "y": 0.5}, {"x": 1, "y": 0.5}, {"x": 1, "y": 0.5}),
    "bottom-left":   ({"x": 0, "y": 0}, {"x": 0, "y": 0}, {"x": 0, "y": 0}),
    "bottom-center": ({"x": 0.5, "y": 0}, {"x": 0.5, "y": 0}, {"x": 0.5, "y": 0}),
    "bottom-right":  ({"x": 1, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 0}),
    "stretch-top":   ({"x": 0, "y": 1}, {"x": 1, "y": 1}, {"x": 0.5, "y": 1}),
    "stretch-bottom":({"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 0.5, "y": 0}),
    "stretch-left":  ({"x": 0, "y": 0}, {"x": 0, "y": 1}, {"x": 0, "y": 0.5}),
    "stretch-right": ({"x": 1, "y": 0}, {"x": 1, "y": 1}, {"x": 1, "y": 0.5}),
}

# ── UI Component GUIDs (SGI Client project) ──────────────────────────────────
# From .cs.meta and .dll.meta — do NOT hardcode, update from project sources

UI_GUIDS = {
    "ILUIWnd":                "92d84008b0651f44b82b6792322b6551",
    "ILUIWidget":             "c4d39f5c5f9f8b544915a8e00f055d80",
    "ILUIScrollerController": "38afe61accd76f840899fdc078e09ef9",
    "ILUIScrollerView":       "c03f8bb183d633a49986b0e8525f3c4e",
    "UIPerformance":          "e462dac500424c5439978c56da2c7c27",
    "UIButtonCustom":         "89779232b761c444897d167013b46555",
    "UIButton":               "7d12bfc32d0d797428cf0191288caabd",
    "GraphicRaycaster":       "dc42784cf147c0c48a680349fa168899",
    "Image":                  "fe87c0e1cc204ed48ad3b37840f39efc",
    "RawImage":               "1344c3c82d62a2a41a3576d8abb8e3ea",
    "Button":                 "4e29b1a8efbd4b44bb3f3716e73f07ff",
    "EnhancedScroller":       "9c1b74f910281224a8cae6d8e4fc1f43",
    "Text":                   "5f7201a12d95ffc409449d95f23cf332",
    "ScrollRect":             "1aa08ab6e0800fa44ae55d278d1423e3",
}

UNITY_YAML_HEADER = "%YAML 1.1\n%TAG !u! tag:unity3d.com,2011:\n"


# ── Parsing ──────────────────────────────────────────────────────────────────

class UnityDocument:
    """Represents a parsed Unity YAML file as a list of objects."""

    def __init__(self):
        self.objects: List[UnityObject] = []

    def find_by_class(self, class_name: str) -> List['UnityObject']:
        return [o for o in self.objects if o.class_name == class_name]

    def find_by_file_id(self, file_id: str) -> Optional['UnityObject']:
        for o in self.objects:
            if o.file_id == file_id:
                return o
        return None

    def to_dict(self) -> list:
        return [o.to_dict() for o in self.objects]

    def serialize(self) -> str:
        lines = [UNITY_YAML_HEADER]
        for obj in self.objects:
            lines.append(obj.serialize())
        return "".join(lines)


class UnityObject:
    """Single Unity YAML object (one --- !u!{classID} &{fileID} block)."""

    def __init__(self, class_id: int, file_id: str, class_name: str, data: dict):
        self.class_id = class_id
        self.file_id = file_id
        self.class_name = class_name
        self.data = data  # The YAML content under the class_name key

    def get_field(self, path: str) -> Any:
        """Get nested field by dot-separated path. e.g. 'Setting.ChunkNum.x'"""
        parts = path.split(".")
        current = self.data
        for p in parts:
            if isinstance(current, dict) and p in current:
                current = current[p]
            elif isinstance(current, list):
                try:
                    current = current[int(p)]
                except (ValueError, IndexError):
                    return None
            else:
                return None
        return current

    def set_field(self, path: str, value: Any):
        """Set nested field by dot-separated path."""
        parts = path.split(".")
        current = self.data
        for p in parts[:-1]:
            if isinstance(current, dict):
                if p not in current:
                    current[p] = {}
                current = current[p]
            elif isinstance(current, list):
                current = current[int(p)]
        last = parts[-1]
        if isinstance(current, dict):
            current[last] = value
        elif isinstance(current, list):
            current[int(last)] = value

    def to_dict(self) -> dict:
        return {
            "class_id": self.class_id,
            "file_id": self.file_id,
            "class_name": self.class_name,
            "data": self.data,
        }

    def serialize(self) -> str:
        header = f"--- !u!{self.class_id} &{self.file_id}\n"
        body = _serialize_yaml({self.class_name: self.data}, indent=0)
        return header + body


def parse_unity_yaml(filepath: str) -> UnityDocument:
    """Parse a Unity YAML file into a UnityDocument."""
    with open(filepath, "r", encoding="utf-8-sig") as f:
        content = f.read()
    return parse_unity_yaml_string(content)


def parse_unity_yaml_string(content: str) -> UnityDocument:
    """Parse Unity YAML content string."""
    doc = UnityDocument()

    # Split by document separators: --- !u!{classID} &{fileID}
    pattern = r"^--- !u!(\d+) &(\d+)\s*$"
    blocks = []
    current_class_id = None
    current_file_id = None
    current_lines = []

    for line in content.split("\n"):
        m = re.match(pattern, line)
        if m:
            if current_class_id is not None:
                blocks.append((current_class_id, current_file_id, "\n".join(current_lines)))
            current_class_id = int(m.group(1))
            current_file_id = m.group(2)
            current_lines = []
        elif current_class_id is not None:
            current_lines.append(line)

    if current_class_id is not None:
        blocks.append((current_class_id, current_file_id, "\n".join(current_lines)))

    for class_id, file_id, yaml_text in blocks:
        parsed = _parse_yaml_block(yaml_text)
        if isinstance(parsed, dict) and len(parsed) == 1:
            class_name = list(parsed.keys())[0]
            data = parsed[class_name] or {}
        else:
            class_name = _class_name_from_id(class_id)
            data = parsed if parsed else {}
        doc.objects.append(UnityObject(class_id, file_id, class_name, data))

    return doc


def _class_name_from_id(class_id: int) -> str:
    for name, cid in CLASS_IDS.items():
        if cid == class_id:
            return name
    return f"Unknown_{class_id}"


# ── Lightweight YAML parser (Unity subset) ───────────────────────────────────
# We use a custom parser instead of PyYAML because Unity YAML has quirks:
# - Flow mappings: {fileID: 0, guid: abc123, type: 3}
# - Mixed styles in the same file
# - Values that look like numbers but should stay as strings in some contexts

def _parse_yaml_block(text: str) -> dict:
    """Parse a single YAML block (no --- separator) into a dict."""
    lines = text.split("\n")
    return _parse_lines(lines, 0, 0)[0]


def _parse_lines(lines: list, start: int, base_indent: int) -> Tuple[dict, int]:
    """Recursive descent YAML parser for Unity subset."""
    result = {}
    i = start
    while i < len(lines):
        line = lines[i]
        stripped = line.rstrip()

        # Skip empty lines and comments
        if not stripped or stripped.startswith("#") or stripped.startswith("%"):
            i += 1
            continue

        indent = len(line) - len(line.lstrip())
        if indent < base_indent:
            break

        if indent > base_indent and i > start:
            break

        content = stripped.lstrip()

        # Array item: "- key: value" or "- value"
        if content.startswith("- "):
            # This is handled by parent
            break

        # Key-value pair
        colon_match = re.match(r"^([\w.]+)\s*:\s*(.*)", content)
        if colon_match:
            key = colon_match.group(1)
            value_str = colon_match.group(2).rstrip()

            if value_str == "" or value_str is None:
                # Check next lines for nested content
                next_i = i + 1
                # Skip empty lines to find actual next content
                while next_i < len(lines) and not lines[next_i].rstrip():
                    next_i += 1
                if next_i < len(lines):
                    next_line = lines[next_i]
                    next_stripped = next_line.rstrip()
                    if next_stripped:
                        next_indent = len(next_line) - len(next_line.lstrip())
                        next_content = next_stripped.lstrip()
                        # Unity YAML: arrays can be at same indent OR deeper
                        if next_indent >= indent and next_content.startswith("- "):
                            arr, next_i = _parse_array(lines, next_i, next_indent)
                            result[key] = arr
                            i = next_i
                            continue
                        elif next_indent > indent:
                            # Nested map
                            nested, next_i = _parse_lines(lines, next_i, next_indent)
                            result[key] = nested
                            i = next_i
                            continue
                result[key] = None
                i += 1
            else:
                result[key] = _parse_value(value_str)
                i += 1
        else:
            i += 1

    return result, i


def _parse_array(lines: list, start: int, base_indent: int) -> Tuple[list, int]:
    """Parse a YAML array starting at the given position."""
    result = []
    i = start
    while i < len(lines):
        line = lines[i]
        stripped = line.rstrip()
        if not stripped:
            i += 1
            continue

        indent = len(line) - len(line.lstrip())
        if indent < base_indent:
            break

        content = stripped.lstrip()
        if not content.startswith("- "):
            if indent == base_indent:
                break
            i += 1
            continue

        item_content = content[2:]  # Remove "- "
        item_indent = indent + 2

        # Check if it's "- key: value" (map item)
        kv_match = re.match(r"^([\w.]+)\s*:\s*(.*)", item_content)
        if kv_match:
            key = kv_match.group(1)
            val_str = kv_match.group(2).rstrip()
            item = {}
            if val_str:
                item[key] = _parse_value(val_str)
            else:
                # Check for nested content under this key
                next_i = i + 1
                # Skip empty lines
                while next_i < len(lines) and not lines[next_i].rstrip():
                    next_i += 1
                if next_i < len(lines):
                    next_line = lines[next_i]
                    next_stripped = next_line.rstrip()
                    if next_stripped:
                        next_indent = len(next_line) - len(next_line.lstrip())
                        next_content = next_stripped.lstrip()
                        # Unity: arrays can be at same indent as item_indent
                        if next_indent >= item_indent and next_content.startswith("- "):
                            arr, next_i = _parse_array(lines, next_i, next_indent)
                            item[key] = arr
                        elif next_indent > item_indent:
                            nested, next_i = _parse_lines(lines, next_i, next_indent)
                            item[key] = nested
                        if next_indent >= item_indent:
                            # Continue reading sibling keys at item_indent
                            while next_i < len(lines):
                                nl = lines[next_i]
                                ns = nl.rstrip()
                                if not ns:
                                    next_i += 1
                                    continue
                                ni = len(nl) - len(nl.lstrip())
                                if ni < item_indent:
                                    break
                                if ni == item_indent:
                                    nc = ns.lstrip()
                                    skv = re.match(r"^([\w.]+)\s*:\s*(.*)", nc)
                                    if skv:
                                        sk = skv.group(1)
                                        sv = skv.group(2).rstrip()
                                        if sv:
                                            item[sk] = _parse_value(sv)
                                        else:
                                            # Nested under this sibling key
                                            peek_i = next_i + 1
                                            if peek_i < len(lines):
                                                pl = lines[peek_i]
                                                ps = pl.rstrip()
                                                if ps:
                                                    pi = len(pl) - len(pl.lstrip())
                                                    pc = ps.lstrip()
                                                    if pi >= item_indent and pc.startswith("- "):
                                                        arr2, peek_i = _parse_array(lines, peek_i, pi)
                                                        item[sk] = arr2
                                                        next_i = peek_i
                                                        continue
                                                    elif pi > item_indent:
                                                        nested2, peek_i = _parse_lines(lines, peek_i, pi)
                                                        item[sk] = nested2
                                                        next_i = peek_i
                                                        continue
                                            item[sk] = None
                                        next_i += 1
                                    else:
                                        break
                                else:
                                    break
                            i = next_i
                            result.append(item)
                            continue
                item[key] = None

            # Read remaining keys at item_indent level
            i += 1
            while i < len(lines):
                nl = lines[i]
                ns = nl.rstrip()
                if not ns:
                    i += 1
                    continue
                ni = len(nl) - len(nl.lstrip())
                if ni < item_indent:
                    break
                if ni == item_indent:
                    nc = ns.lstrip()
                    if nc.startswith("- "):
                        break
                    skv = re.match(r"^([\w.]+)\s*:\s*(.*)", nc)
                    if skv:
                        sk = skv.group(1)
                        sv = skv.group(2).rstrip()
                        if sv:
                            item[sk] = _parse_value(sv)
                        else:
                            peek_i = i + 1
                            if peek_i < len(lines):
                                pl = lines[peek_i]
                                ps = pl.rstrip()
                                if ps:
                                    pi = len(pl) - len(pl.lstrip())
                                    pc = ps.lstrip()
                                    if pi >= item_indent and pc.startswith("- "):
                                        arr2, peek_i = _parse_array(lines, peek_i, pi)
                                        item[sk] = arr2
                                        i = peek_i
                                        continue
                                    elif pi > item_indent:
                                        nested2, peek_i = _parse_lines(lines, peek_i, pi)
                                        item[sk] = nested2
                                        i = peek_i
                                        continue
                            item[sk] = None
                        i += 1
                    else:
                        break
                elif ni > item_indent:
                    # Skip nested content that was already parsed or belongs to previous key
                    i += 1
                else:
                    break
            result.append(item)
        elif item_content.startswith("{"):
            result.append(_parse_flow_mapping(item_content))
            i += 1
        else:
            result.append(_parse_value(item_content))
            i += 1

    return result, i


def _parse_value(s: str) -> Any:
    """Parse a YAML scalar value."""
    s = s.strip()
    if not s or s == "~":
        return None
    if s.startswith("{"):
        return _parse_flow_mapping(s)
    if s.startswith("["):
        return _parse_flow_sequence(s)
    if s in ("true", "True", "yes", "on"):
        return 1  # Unity uses 1/0 for bools
    if s in ("false", "False", "no", "off"):
        return 0
    # Try int (but preserve leading zeros as strings, e.g. "002")
    try:
        v = int(s)
        if len(s) > 1 and s[0] == "0" and s[1] != "x":
            return s  # Leading zero → keep as string
        return v
    except ValueError:
        pass
    # Try float
    try:
        return float(s)
    except ValueError:
        pass
    # String — strip quotes if present
    if (s.startswith("'") and s.endswith("'")) or (s.startswith('"') and s.endswith('"')):
        return s[1:-1]
    return s


def _parse_flow_mapping(s: str) -> dict:
    """Parse Unity flow mapping like {fileID: 0, guid: abc, type: 3}"""
    s = s.strip()
    if s.startswith("{") and s.endswith("}"):
        s = s[1:-1]
    result = {}
    # Split by comma, but handle nested braces
    parts = _split_flow(s, ",")
    for part in parts:
        part = part.strip()
        if ":" in part:
            key, _, val = part.partition(":")
            result[key.strip()] = _parse_value(val.strip())
    return result


def _parse_flow_sequence(s: str) -> list:
    """Parse flow sequence like [1, 2, 3]"""
    s = s.strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    if not s.strip():
        return []
    parts = _split_flow(s, ",")
    return [_parse_value(p.strip()) for p in parts if p.strip()]


def _split_flow(s: str, delimiter: str) -> list:
    """Split string by delimiter respecting nested braces/brackets."""
    parts = []
    depth = 0
    current = []
    for ch in s:
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
        if ch == delimiter and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current))
    return parts


# ── Serialization ────────────────────────────────────────────────────────────

def _serialize_yaml(data: Any, indent: int = 0) -> str:
    """Serialize data back to Unity YAML format."""
    if isinstance(data, dict):
        lines = []
        prefix = "  " * indent
        for key, value in data.items():
            if value is None:
                lines.append(f"{prefix}{key}: \n")
            elif isinstance(value, dict):
                if _is_flow_mapping(value):
                    lines.append(f"{prefix}{key}: {_serialize_flow_mapping(value)}\n")
                else:
                    lines.append(f"{prefix}{key}:\n")
                    lines.append(_serialize_yaml(value, indent + 1))
            elif isinstance(value, list):
                if not value:
                    lines.append(f"{prefix}{key}: []\n")
                else:
                    lines.append(f"{prefix}{key}:\n")
                    # Unity convention: array items at same indent as key
                    lines.append(_serialize_array(value, indent))
            else:
                lines.append(f"{prefix}{key}: {_serialize_scalar(value)}\n")
        return "".join(lines)
    return ""


def _serialize_array(arr: list, indent: int) -> str:
    """Serialize a YAML array."""
    lines = []
    prefix = "  " * indent
    for item in arr:
        if isinstance(item, dict):
            if _is_flow_mapping(item):
                lines.append(f"{prefix}- {_serialize_flow_mapping(item)}\n")
            else:
                first = True
                for key, value in item.items():
                    if first:
                        marker = "- "
                        first = False
                    else:
                        marker = "  "
                    if value is None:
                        lines.append(f"{prefix}{marker}{key}: \n")
                    elif isinstance(value, dict):
                        if _is_flow_mapping(value):
                            lines.append(f"{prefix}{marker}{key}: {_serialize_flow_mapping(value)}\n")
                        else:
                            lines.append(f"{prefix}{marker}{key}:\n")
                            lines.append(_serialize_yaml(value, indent + 2))
                    elif isinstance(value, list):
                        if not value:
                            lines.append(f"{prefix}{marker}{key}: []\n")
                        else:
                            lines.append(f"{prefix}{marker}{key}:\n")
                            lines.append(_serialize_array(value, indent + 2))
                    else:
                        lines.append(f"{prefix}{marker}{key}: {_serialize_scalar(value)}\n")
        else:
            lines.append(f"{prefix}- {_serialize_scalar(item)}\n")
    return "".join(lines)


def _is_flow_mapping(d: dict) -> bool:
    """Determine if a dict should be serialized as flow mapping {k: v, ...}
    Unity uses flow mappings for references and simple structs like vectors."""
    if not d:
        return True
    # fileID references are always flow
    if "fileID" in d:
        return True
    # Simple vector/color structs
    keys = set(d.keys())
    flow_patterns = [
        {"x", "y"}, {"x", "y", "z"}, {"x", "y", "z", "w"},
        {"r", "g", "b", "a"},
    ]
    if keys in flow_patterns:
        return all(isinstance(v, (int, float)) for v in d.values())
    # All scalar values and small dict
    if len(d) <= 4 and all(isinstance(v, (int, float, str)) for v in d.values() if v is not None):
        return False  # Default to block for other small dicts
    return False


def _serialize_flow_mapping(d: dict) -> str:
    """Serialize as Unity flow mapping."""
    parts = []
    for k, v in d.items():
        parts.append(f"{k}: {_serialize_scalar(v)}")
    return "{" + ", ".join(parts) + "}"


def _serialize_scalar(value: Any) -> str:
    """Serialize a scalar value."""
    if value is None:
        return ""
    if isinstance(value, float):
        # Unity uses specific float formatting
        if value == int(value) and abs(value) < 1e10:
            return str(int(value))
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value
    return str(value)


# ── Generation ───────────────────────────────────────────────────────────────

def generate_guid() -> str:
    """Generate a Unity-compatible GUID (32 hex chars, no dashes)."""
    return uuid.uuid4().hex


def generate_file_id() -> str:
    """Generate a fileID for prefab objects (large random number)."""
    return str(random.randint(1000000000000000, 9999999999999999))


def generate_asset(spec: dict, output_path: str):
    """Generate a ScriptableObject .asset file.

    spec = {
        "name": "MyAsset",
        "script_guid": "abc123...",  # GUID of the MonoScript
        "fields": {
            "myInt": 42,
            "myString": "hello",
            "myList": [1, 2, 3],
            "myStruct": {"x": 1, "y": 2}
        }
    }
    """
    data = OrderedDict()
    data["m_ObjectHideFlags"] = 0
    data["m_CorrespondingSourceObject"] = {"fileID": 0}
    data["m_PrefabInstance"] = {"fileID": 0}
    data["m_PrefabAsset"] = {"fileID": 0}
    data["m_GameObject"] = {"fileID": 0}
    data["m_Enabled"] = 1
    data["m_EditorHideFlags"] = 0
    data["m_Script"] = {"fileID": 11500000, "guid": spec["script_guid"], "type": 3}
    data["m_Name"] = spec["name"]
    data["m_EditorClassIdentifier"] = None

    # Add custom fields
    for key, value in spec.get("fields", {}).items():
        data[key] = value

    obj = UnityObject(114, "11400000", "MonoBehaviour", data)
    doc = UnityDocument()
    doc.objects.append(obj)

    with open(output_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(doc.serialize())

    print(f"Generated: {output_path}")


def generate_meta(output_path: str, guid: str = None, importer: str = "NativeFormatImporter"):
    """Generate a .meta file for an asset.

    Common importers:
    - NativeFormatImporter: .asset (ScriptableObject)
    - PrefabImporter: .prefab
    - DefaultImporter: .unity (scene), folders
    """
    if guid is None:
        guid = generate_guid()

    main_object_id = ""
    if importer == "NativeFormatImporter":
        main_object_id = "\n  mainObjectFileID: 11400000"
    elif importer == "PrefabImporter":
        main_object_id = ""

    content = f"""fileFormatVersion: 2
guid: {guid}
{importer}:
  externalObjects: {{}}{main_object_id}
  userData:
  assetBundleName:
  assetBundleVariant:
"""
    with open(output_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)

    print(f"Generated: {output_path} (guid: {guid})")
    return guid


def generate_prefab(spec: dict, output_path: str):
    """Generate a simple prefab with GameObject hierarchy.

    spec = {
        "name": "MyPrefab",
        "children": [
            {
                "name": "Child1",
                "position": {"x": 0, "y": 0, "z": 0},
                "rotation": {"x": 0, "y": 0, "z": 0, "w": 1},
                "scale": {"x": 1, "y": 1, "z": 1},
                "components": [
                    {
                        "type": "MonoBehaviour",
                        "script_guid": "abc123...",
                        "fields": {"key": "value"}
                    }
                ]
            }
        ]
    }
    """
    doc = UnityDocument()
    id_counter = [0]

    def next_id():
        id_counter[0] += 1
        return str(random.randint(1000000000000000, 9999999999999999))

    def create_gameobject(name, component_ids, layer=0):
        go_id = next_id()
        data = OrderedDict()
        data["m_ObjectHideFlags"] = 0
        data["m_CorrespondingSourceObject"] = {"fileID": 0}
        data["m_PrefabInstance"] = {"fileID": 0}
        data["m_PrefabAsset"] = {"fileID": 0}
        data["serializedVersion"] = 6
        data["m_Component"] = [{"component": {"fileID": int(cid)}} for cid in component_ids]
        data["m_Layer"] = layer
        data["m_Name"] = name
        data["m_TagString"] = "Untagged"
        data["m_Icon"] = {"fileID": 0}
        data["m_NavMeshLayer"] = 0
        data["m_StaticEditorFlags"] = 0
        data["m_IsActive"] = 1
        return UnityObject(1, go_id, "GameObject", data), go_id

    def create_transform(go_id, pos, rot, scale, children_ids, parent_id, root_order):
        tr_id = next_id()
        data = OrderedDict()
        data["m_ObjectHideFlags"] = 0
        data["m_CorrespondingSourceObject"] = {"fileID": 0}
        data["m_PrefabInstance"] = {"fileID": 0}
        data["m_PrefabAsset"] = {"fileID": 0}
        data["m_GameObject"] = {"fileID": int(go_id)}
        data["m_LocalRotation"] = rot or {"x": 0, "y": 0, "z": 0, "w": 1}
        data["m_LocalPosition"] = pos or {"x": 0, "y": 0, "z": 0}
        data["m_LocalScale"] = scale or {"x": 1, "y": 1, "z": 1}
        data["m_ConstrainProportionsScale"] = 0
        data["m_Children"] = [{"fileID": int(cid)} for cid in children_ids]
        data["m_Father"] = {"fileID": int(parent_id) if parent_id else 0}
        data["m_RootOrder"] = root_order
        data["m_LocalEulerAnglesHint"] = {"x": 0, "y": 0, "z": 0}
        return UnityObject(4, tr_id, "Transform", data), tr_id

    # Build hierarchy bottom-up to know child transform IDs
    def build_node(node_spec, parent_transform_id, root_order):
        child_transform_ids = []
        child_objects = []

        # Build children first
        for idx, child_spec in enumerate(node_spec.get("children", [])):
            objs, child_tr_id = build_node(child_spec, None, idx)  # parent set later
            child_transform_ids.append(child_tr_id)
            child_objects.extend(objs)

        # Create transform (need go_id, but don't have it yet — use placeholder)
        tr_id = next_id()

        # Create additional components
        extra_component_ids = []
        extra_objects = []
        for comp_spec in node_spec.get("components", []):
            comp_id = next_id()
            extra_component_ids.append(comp_id)
            if comp_spec.get("type") == "MonoBehaviour":
                comp_data = OrderedDict()
                comp_data["m_ObjectHideFlags"] = 0
                comp_data["m_CorrespondingSourceObject"] = {"fileID": 0}
                comp_data["m_PrefabInstance"] = {"fileID": 0}
                comp_data["m_PrefabAsset"] = {"fileID": 0}
                comp_data["m_GameObject"] = {"fileID": 0}  # Set later
                comp_data["m_Enabled"] = 1
                comp_data["m_EditorHideFlags"] = 0
                comp_data["m_Script"] = {"fileID": 11500000, "guid": comp_spec["script_guid"], "type": 3}
                comp_data["m_Name"] = None
                comp_data["m_EditorClassIdentifier"] = None
                for k, v in comp_spec.get("fields", {}).items():
                    comp_data[k] = v
                extra_objects.append(UnityObject(114, comp_id, "MonoBehaviour", comp_data))

        # Create GameObject
        all_component_ids = [tr_id] + extra_component_ids
        go_obj, go_id = create_gameobject(node_spec.get("name", "GameObject"), all_component_ids)

        # Create Transform
        tr_data = OrderedDict()
        tr_data["m_ObjectHideFlags"] = 0
        tr_data["m_CorrespondingSourceObject"] = {"fileID": 0}
        tr_data["m_PrefabInstance"] = {"fileID": 0}
        tr_data["m_PrefabAsset"] = {"fileID": 0}
        tr_data["m_GameObject"] = {"fileID": int(go_id)}
        tr_data["m_LocalRotation"] = node_spec.get("rotation") or {"x": 0, "y": 0, "z": 0, "w": 1}
        tr_data["m_LocalPosition"] = node_spec.get("position") or {"x": 0, "y": 0, "z": 0}
        tr_data["m_LocalScale"] = node_spec.get("scale") or {"x": 1, "y": 1, "z": 1}
        tr_data["m_ConstrainProportionsScale"] = 0
        tr_data["m_Children"] = [{"fileID": int(cid)} for cid in child_transform_ids]
        tr_data["m_Father"] = {"fileID": int(parent_transform_id) if parent_transform_id else 0}
        tr_data["m_RootOrder"] = root_order
        tr_data["m_LocalEulerAnglesHint"] = {"x": 0, "y": 0, "z": 0}
        tr_obj = UnityObject(4, tr_id, "Transform", tr_data)

        # Fix up component m_GameObject references
        for comp_obj in extra_objects:
            comp_obj.data["m_GameObject"] = {"fileID": int(go_id)}

        # Fix up child parent references
        for child_obj in child_objects:
            if child_obj.class_name == "Transform" and child_obj.data.get("m_Father", {}).get("fileID") == 0:
                # Check if this is a direct child (its fileID is in our child_transform_ids)
                if child_obj.file_id in child_transform_ids:
                    child_obj.data["m_Father"] = {"fileID": int(tr_id)}

        all_objects = [go_obj, tr_obj] + extra_objects + child_objects
        return all_objects, tr_id

    # Build from root spec
    root_spec = {"name": spec.get("name", "Prefab"), "children": spec.get("children", []),
                 "position": spec.get("position"), "rotation": spec.get("rotation"),
                 "scale": spec.get("scale"), "components": spec.get("components", [])}
    all_objs, _ = build_node(root_spec, None, 0)

    doc.objects = all_objs
    with open(output_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(doc.serialize())

    print(f"Generated prefab: {output_path}")


def generate_ui_prefab(spec: dict, output_path: str):
    """Generate a WndForm UI prefab with proper root structure and RefDb.

    spec = {
        "name": "WndForm_UITutorial",
        "children": [
            {"name": "Load_Title", "type": "Text", "anchor": "stretch",
             "size": {"x": 400, "y": 60}},
            {"name": "Confirm", "type": "UIButtonCustom", "anchor": "center",
             "size": {"x": 200, "y": 60}},
            {"name": "Scroller", "type": "Scroller", "anchor": "stretch",
             "scroll_class": "UITutorialScroller"}
        ]
    }

    Supported child types: Text, Image, UIButtonCustom, Scroller, Empty
    """
    doc = UnityDocument()

    def next_id():
        return str(random.randint(1000000000000000, 9999999999999999))

    def make_mono(go_id, guid, fields=None):
        """Create a MonoBehaviour component."""
        cid = next_id()
        data = OrderedDict()
        data["m_ObjectHideFlags"] = 0
        data["m_CorrespondingSourceObject"] = {"fileID": 0}
        data["m_PrefabInstance"] = {"fileID": 0}
        data["m_PrefabAsset"] = {"fileID": 0}
        data["m_GameObject"] = {"fileID": int(go_id)}
        data["m_Enabled"] = 1
        data["m_EditorHideFlags"] = 0
        data["m_Script"] = {"fileID": 11500000, "guid": guid, "type": 3}
        data["m_Name"] = None
        data["m_EditorClassIdentifier"] = None
        if fields:
            for k, v in fields.items():
                data[k] = v
        return UnityObject(114, cid, "MonoBehaviour", data), cid

    def make_rect_transform(go_id, parent_tr_id, children_tr_ids, root_order, anchor="stretch", size=None, pos=None):
        """Create a RectTransform (ClassID 224)."""
        tr_id = next_id()
        preset = ANCHOR_PRESETS.get(anchor, ANCHOR_PRESETS["stretch"])
        anchor_min, anchor_max, pivot = preset

        # For stretch: sizeDelta=0,0. For fixed: use size param
        if anchor == "stretch" and size is None:
            size_delta = {"x": 0, "y": 0}
        else:
            size_delta = size or {"x": 100, "y": 100}

        data = OrderedDict()
        data["m_ObjectHideFlags"] = 0
        data["m_CorrespondingSourceObject"] = {"fileID": 0}
        data["m_PrefabInstance"] = {"fileID": 0}
        data["m_PrefabAsset"] = {"fileID": 0}
        data["m_GameObject"] = {"fileID": int(go_id)}
        data["m_LocalRotation"] = {"x": 0, "y": 0, "z": 0, "w": 1}
        data["m_LocalPosition"] = {"x": 0, "y": 0, "z": 0}
        data["m_LocalScale"] = {"x": 1, "y": 1, "z": 1}
        data["m_ConstrainProportionsScale"] = 0
        data["m_Children"] = [{"fileID": int(c)} for c in children_tr_ids]
        data["m_Father"] = {"fileID": int(parent_tr_id) if parent_tr_id else 0}
        data["m_RootOrder"] = root_order
        data["m_LocalEulerAnglesHint"] = {"x": 0, "y": 0, "z": 0}
        data["m_AnchorMin"] = anchor_min
        data["m_AnchorMax"] = anchor_max
        data["m_AnchoredPosition"] = pos or {"x": 0, "y": 0}
        data["m_SizeDelta"] = size_delta
        data["m_Pivot"] = pivot
        return UnityObject(224, tr_id, "RectTransform", data), tr_id

    def make_canvas(go_id):
        cid = next_id()
        data = OrderedDict()
        data["m_ObjectHideFlags"] = 0
        data["m_CorrespondingSourceObject"] = {"fileID": 0}
        data["m_PrefabInstance"] = {"fileID": 0}
        data["m_PrefabAsset"] = {"fileID": 0}
        data["m_GameObject"] = {"fileID": int(go_id)}
        data["m_Enabled"] = 1
        data["serializedVersion"] = 3
        data["m_RenderMode"] = 2
        data["m_Camera"] = {"fileID": 0}
        data["m_PlaneDistance"] = 100
        data["m_PixelPerfect"] = 0
        data["m_ReceivesEvents"] = 1
        data["m_OverrideSorting"] = 0
        data["m_OverridePixelPerfect"] = 0
        data["m_SortingBucketNormalizedSize"] = 0
        data["m_VertexColorAlwaysGammaSpace"] = 0
        data["m_AdditionalShaderChannelsFlag"] = 25
        data["m_UpdateRectTransformForStandalone"] = 0
        data["m_SortingLayerID"] = 0
        data["m_SortingOrder"] = 0
        data["m_TargetDisplay"] = 0
        return UnityObject(223, cid, "Canvas", data), cid

    def make_canvas_group(go_id):
        cid = next_id()
        data = OrderedDict()
        data["m_ObjectHideFlags"] = 0
        data["m_CorrespondingSourceObject"] = {"fileID": 0}
        data["m_PrefabInstance"] = {"fileID": 0}
        data["m_PrefabAsset"] = {"fileID": 0}
        data["m_GameObject"] = {"fileID": int(go_id)}
        data["m_Enabled"] = 1
        data["m_Alpha"] = 1
        data["m_Interactable"] = 1
        data["m_BlocksRaycasts"] = 1
        data["m_IgnoreParentGroups"] = 0
        return UnityObject(225, cid, "CanvasGroup", data), cid

    def make_canvas_renderer(go_id):
        cid = next_id()
        data = OrderedDict()
        data["m_ObjectHideFlags"] = 0
        data["m_CorrespondingSourceObject"] = {"fileID": 0}
        data["m_PrefabInstance"] = {"fileID": 0}
        data["m_PrefabAsset"] = {"fileID": 0}
        data["m_GameObject"] = {"fileID": int(go_id)}
        data["m_CullTransparentMesh"] = 1
        return UnityObject(222, cid, "CanvasRenderer", data), cid

    def make_gameobject(name, component_ids, layer=5):
        go_id = next_id()
        data = OrderedDict()
        data["m_ObjectHideFlags"] = 0
        data["m_CorrespondingSourceObject"] = {"fileID": 0}
        data["m_PrefabInstance"] = {"fileID": 0}
        data["m_PrefabAsset"] = {"fileID": 0}
        data["serializedVersion"] = 6
        data["m_Component"] = [{"component": {"fileID": int(c)}} for c in component_ids]
        data["m_Layer"] = layer
        data["m_Name"] = name
        data["m_TagString"] = "Untagged"
        data["m_Icon"] = {"fileID": 0}
        data["m_NavMeshLayer"] = 0
        data["m_StaticEditorFlags"] = 0
        data["m_IsActive"] = 1
        return UnityObject(1, go_id, "GameObject", data), go_id

    # ── Build children first (bottom-up) ──
    child_results = []  # list of (objects, tr_id, refdb_entry)
    refdb_objects = []

    for idx, child_spec in enumerate(spec.get("children", [])):
        child_name = child_spec["name"]
        child_type = child_spec.get("type", "Empty")
        child_anchor = child_spec.get("anchor", "stretch")
        child_size = child_spec.get("size")
        child_pos = child_spec.get("position")
        objects = []

        # Placeholder IDs — will be assigned during assembly
        tr_id_placeholder = next_id()
        go_id_placeholder = next_id()

        # Build components based on type
        extra_comp_ids = []
        extra_objs = []
        refdb_comp_id = None
        refdb_type_name = child_type

        if child_type == "Text":
            text_guid = UI_GUIDS.get("Text")
            if text_guid:
                cr_obj, cr_id = make_canvas_renderer(go_id_placeholder)
                extra_objs.append(cr_obj)
                extra_comp_ids.append(cr_id)
                mono_obj, mono_id = make_mono(go_id_placeholder, text_guid, {
                    "m_Text": child_spec.get("text", ""),
                    "m_FontSize": child_spec.get("font_size", 28),
                })
                extra_objs.append(mono_obj)
                extra_comp_ids.append(mono_id)
                refdb_comp_id = mono_id
            else:
                # Fallback: empty child, Text GUID not available
                print(f"Warning: Text GUID not configured, '{child_name}' created as empty", file=sys.stderr)

        elif child_type == "Image":
            img_guid = UI_GUIDS.get("Image")
            if img_guid:
                cr_obj, cr_id = make_canvas_renderer(go_id_placeholder)
                extra_objs.append(cr_obj)
                extra_comp_ids.append(cr_id)
                mono_obj, mono_id = make_mono(go_id_placeholder, img_guid)
                extra_objs.append(mono_obj)
                extra_comp_ids.append(mono_id)
                refdb_comp_id = mono_id

        elif child_type == "UIButtonCustom":
            btn_guid = UI_GUIDS.get("UIButtonCustom")
            img_guid = UI_GUIDS.get("Image")
            if btn_guid:
                cr_obj, cr_id = make_canvas_renderer(go_id_placeholder)
                extra_objs.append(cr_obj)
                extra_comp_ids.append(cr_id)
                # Image background
                if img_guid:
                    img_obj, img_id = make_mono(go_id_placeholder, img_guid)
                    extra_objs.append(img_obj)
                    extra_comp_ids.append(img_id)
                # UIButtonCustom
                mono_obj, mono_id = make_mono(go_id_placeholder, btn_guid)
                extra_objs.append(mono_obj)
                extra_comp_ids.append(mono_id)
                refdb_comp_id = mono_id

        elif child_type == "Scroller":
            scroller_guid = UI_GUIDS.get("EnhancedScroller")
            ctrl_guid = UI_GUIDS.get("ILUIScrollerController")
            if scroller_guid and ctrl_guid:
                # EnhancedScroller
                es_obj, es_id = make_mono(go_id_placeholder, scroller_guid)
                extra_objs.append(es_obj)
                extra_comp_ids.append(es_id)
                # ILUIScrollerController
                scroll_class = child_spec.get("scroll_class", "")
                ctrl_obj, ctrl_id = make_mono(go_id_placeholder, ctrl_guid, {
                    "_scrollClassName": scroll_class,
                })
                extra_objs.append(ctrl_obj)
                extra_comp_ids.append(ctrl_id)
                refdb_comp_id = ctrl_id
                refdb_type_name = "ILUIScrollerController"

        # Assemble child: RectTransform first, then extras
        all_comp_ids = [tr_id_placeholder] + extra_comp_ids
        go_obj, go_id = make_gameobject(child_name, all_comp_ids)

        # Fix go_id references in components
        for obj in extra_objs:
            if "m_GameObject" in obj.data:
                obj.data["m_GameObject"] = {"fileID": int(go_id)}

        # RectTransform (parent set later)
        rt_obj, rt_id = make_rect_transform(go_id, None, [], idx, child_anchor, child_size, child_pos)
        # Overwrite placeholder tr_id in component list
        go_obj.data["m_Component"][0] = {"component": {"fileID": int(rt_id)}}

        objects = [go_obj, rt_obj] + extra_objs

        # RefDb entry
        if refdb_comp_id:
            refdb_objects.append({
                "_key": child_name,
                "_typeName": refdb_type_name,
                "Objs": [{"fileID": int(refdb_comp_id)}],
            })

        child_results.append((objects, rt_id))

    # ── Build root ──
    child_tr_ids = [tr_id for _, tr_id in child_results]

    root_tr_id = next_id()
    root_go_id = next_id()

    # Root components: RectTransform + Canvas + GraphicRaycaster + CanvasGroup + UIPerformance + ILUIWnd
    canvas_obj, canvas_id = make_canvas(root_go_id)
    raycaster_obj, raycaster_id = make_mono(root_go_id, UI_GUIDS["GraphicRaycaster"])
    cg_obj, cg_id = make_canvas_group(root_go_id)
    perf_obj, perf_id = make_mono(root_go_id, UI_GUIDS["UIPerformance"])

    # ILUIWnd with RefDb
    wnd_name = spec.get("name", "WndForm_Unknown")
    wnd_fields = OrderedDict()
    wnd_fields["_refDb"] = OrderedDict()
    wnd_fields["_refDb"]["_objects"] = refdb_objects
    wnd_fields["_refDb"]["_fieldDb"] = {"_fields": []}
    wnd_fields["_uiWndID"] = wnd_name
    wnd_fields["DisableInvokeUpdate"] = 0
    wnd_fields["UsingFrameUpdate"] = 1
    wnd_fields["UpdateFrameRate"] = 0
    wnd_fields["UpdateInterval"] = 1
    wnd_obj, wnd_id = make_mono(root_go_id, UI_GUIDS["ILUIWnd"], wnd_fields)

    root_comp_ids = [root_tr_id, canvas_id, raycaster_id, cg_id, perf_id, wnd_id]
    root_go_obj, actual_root_go_id = make_gameobject(wnd_name, root_comp_ids)
    # Fix root go_id in all root components
    for obj in [canvas_obj, raycaster_obj, cg_obj, perf_obj, wnd_obj]:
        if "m_GameObject" in obj.data:
            obj.data["m_GameObject"] = {"fileID": int(actual_root_go_id)}

    # Root RectTransform
    root_rt_obj, actual_root_tr_id = make_rect_transform(
        actual_root_go_id, None, child_tr_ids, 0, "stretch"
    )
    # Fix component list to use actual tr_id
    root_go_obj.data["m_Component"][0] = {"component": {"fileID": int(actual_root_tr_id)}}

    # Fix child RectTransform parent references
    for child_objs, _ in child_results:
        for obj in child_objs:
            if obj.class_id == 224:  # RectTransform
                obj.data["m_Father"] = {"fileID": int(actual_root_tr_id)}

    # Assemble document: root first, then children
    doc.objects.append(root_go_obj)
    doc.objects.append(root_rt_obj)
    doc.objects.append(canvas_obj)
    doc.objects.append(raycaster_obj)
    doc.objects.append(cg_obj)
    doc.objects.append(perf_obj)
    doc.objects.append(wnd_obj)

    for child_objs, _ in child_results:
        doc.objects.extend(child_objs)

    with open(output_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(doc.serialize())

    print(f"Generated UI prefab: {output_path} ({len(doc.objects)} objects)")


def validate_prefab(filepath: str):
    """Validate a prefab file for common issues.

    Checks:
    1. All fileID cross-references resolve to existing objects
    2. All MonoBehaviour m_Script GUIDs are non-zero
    3. All m_GameObject references resolve
    4. RectTransform parent/child consistency
    """
    doc = parse_unity_yaml(filepath)
    errors = []
    warnings = []

    # Build fileID lookup
    known_ids = {obj.file_id for obj in doc.objects}

    for obj in doc.objects:
        # Check m_Script on MonoBehaviours
        if obj.class_id == 114:  # MonoBehaviour
            script = obj.data.get("m_Script", {})
            if isinstance(script, dict):
                guid = script.get("guid", "")
                if not guid or guid == "0" or guid == 0:
                    errors.append(f"[{obj.file_id}] MonoBehaviour has zero m_Script GUID")

        # Check m_GameObject reference
        go_ref = obj.data.get("m_GameObject", {})
        if isinstance(go_ref, dict):
            fid = str(go_ref.get("fileID", 0))
            if fid != "0" and fid not in known_ids:
                errors.append(f"[{obj.file_id}] m_GameObject references unknown fileID {fid}")

        # Check m_Component references (on GameObjects)
        if obj.class_id == 1:  # GameObject
            for comp_entry in obj.data.get("m_Component", []):
                comp_ref = comp_entry.get("component", {})
                if isinstance(comp_ref, dict):
                    fid = str(comp_ref.get("fileID", 0))
                    if fid != "0" and fid not in known_ids:
                        errors.append(f"[{obj.file_id}] m_Component references unknown fileID {fid}")

        # Check Transform/RectTransform references
        if obj.class_id in (4, 224):
            # Father
            father_ref = obj.data.get("m_Father", {})
            if isinstance(father_ref, dict):
                fid = str(father_ref.get("fileID", 0))
                if fid != "0" and fid not in known_ids:
                    errors.append(f"[{obj.file_id}] m_Father references unknown fileID {fid}")
            # Children
            for child_ref in obj.data.get("m_Children", []):
                if isinstance(child_ref, dict):
                    fid = str(child_ref.get("fileID", 0))
                    if fid != "0" and fid not in known_ids:
                        errors.append(f"[{obj.file_id}] m_Children references unknown fileID {fid}")

    # Check RefDb references (ILUIWnd MonoBehaviours)
    for obj in doc.objects:
        if obj.class_id == 114:
            refdb = obj.data.get("_refDb")
            if refdb and isinstance(refdb, dict):
                for entry in refdb.get("_objects", []):
                    if isinstance(entry, dict):
                        for ref in entry.get("Objs", []):
                            if isinstance(ref, dict):
                                fid = str(ref.get("fileID", 0))
                                if fid != "0" and fid not in known_ids:
                                    errors.append(f"[{obj.file_id}] RefDb '{entry.get('_key')}' references unknown fileID {fid}")

    # Summary
    print(f"Validated: {filepath}")
    print(f"  Objects: {len(doc.objects)}")
    print(f"  Errors: {len(errors)}")
    print(f"  Warnings: {len(warnings)}")
    for e in errors:
        print(f"  ERROR: {e}")
    for w in warnings:
        print(f"  WARN: {w}")

    if errors:
        sys.exit(1)
    return True


def modify_file(filepath: str, field_path: str, value: Any):
    """Modify a field in a Unity YAML file. Uses text-based replacement for safety."""
    doc = parse_unity_yaml(filepath)

    # field_path format: "objectIndex.field.subfield" or "className.field.subfield"
    parts = field_path.split(".", 1)
    target_obj = None

    # Try by class name first
    for obj in doc.objects:
        if obj.class_name == parts[0]:
            target_obj = obj
            field_path = parts[1] if len(parts) > 1 else ""
            break

    # Try by index
    if target_obj is None:
        try:
            idx = int(parts[0])
            target_obj = doc.objects[idx]
            field_path = parts[1] if len(parts) > 1 else ""
        except (ValueError, IndexError):
            # Single object file — modify the first object
            target_obj = doc.objects[0]

    if target_obj is None:
        print(f"Error: Could not find target object for path '{field_path}'", file=sys.stderr)
        sys.exit(1)

    if field_path:
        target_obj.set_field(field_path, value)
    else:
        print(f"Error: No field specified", file=sys.stderr)
        sys.exit(1)

    with open(filepath, "w", encoding="utf-8", newline="\n") as f:
        f.write(doc.serialize())
    print(f"Modified: {filepath} [{field_path} = {value}]")


def template_asset(src_path: str, output_path: str, replacements: dict):
    """Clone an asset file and replace specified fields.

    replacements = {
        "MonoBehaviour.m_Name": "NewName",
        "MonoBehaviour.Setting.ChunkNum.x": 50,
    }
    """
    doc = parse_unity_yaml(src_path)

    for field_path, value in replacements.items():
        parts = field_path.split(".", 1)
        for obj in doc.objects:
            if obj.class_name == parts[0] and len(parts) > 1:
                obj.set_field(parts[1], value)
                break

    with open(output_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(doc.serialize())
    print(f"Templated: {src_path} -> {output_path}")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "parse":
        if len(sys.argv) < 3:
            print("Usage: unity-yaml-tool.py parse <file>", file=sys.stderr)
            sys.exit(1)
        doc = parse_unity_yaml(sys.argv[2])
        print(json.dumps(doc.to_dict(), indent=2, ensure_ascii=False))

    elif cmd == "generate-asset":
        if len(sys.argv) < 4:
            print("Usage: unity-yaml-tool.py generate-asset <json-spec> <output>", file=sys.stderr)
            sys.exit(1)
        spec_arg = sys.argv[2]
        output = sys.argv[3]
        if os.path.isfile(spec_arg):
            with open(spec_arg, "r", encoding="utf-8") as f:
                spec = json.load(f)
        else:
            spec = json.loads(spec_arg)
        generate_asset(spec, output)

    elif cmd == "generate-meta":
        if len(sys.argv) < 3:
            print("Usage: unity-yaml-tool.py generate-meta <output> [--guid GUID] [--importer TYPE]", file=sys.stderr)
            sys.exit(1)
        output = sys.argv[2]
        guid = None
        importer = "NativeFormatImporter"
        i = 3
        while i < len(sys.argv):
            if sys.argv[i] == "--guid" and i + 1 < len(sys.argv):
                guid = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--importer" and i + 1 < len(sys.argv):
                importer = sys.argv[i + 1]
                i += 2
            else:
                i += 1
        generate_meta(output, guid, importer)

    elif cmd == "generate-prefab":
        if len(sys.argv) < 4:
            print("Usage: unity-yaml-tool.py generate-prefab <json-spec> <output>", file=sys.stderr)
            sys.exit(1)
        spec_arg = sys.argv[2]
        output = sys.argv[3]
        if os.path.isfile(spec_arg):
            with open(spec_arg, "r", encoding="utf-8") as f:
                spec = json.load(f)
        else:
            spec = json.loads(spec_arg)
        generate_prefab(spec, output)

    elif cmd == "modify":
        if len(sys.argv) < 5:
            print("Usage: unity-yaml-tool.py modify <file> <field.path> <value>", file=sys.stderr)
            sys.exit(1)
        filepath = sys.argv[2]
        field = sys.argv[3]
        value = _parse_value(sys.argv[4])
        modify_file(filepath, field, value)

    elif cmd == "template":
        if len(sys.argv) < 5:
            print("Usage: unity-yaml-tool.py template <src> <output> <json-replacements>", file=sys.stderr)
            sys.exit(1)
        src = sys.argv[2]
        output = sys.argv[3]
        rep_arg = sys.argv[4]
        if os.path.isfile(rep_arg):
            with open(rep_arg, "r", encoding="utf-8") as f:
                replacements = json.load(f)
        else:
            replacements = json.loads(rep_arg)
        template_asset(src, output, replacements)

    elif cmd == "generate-ui-prefab":
        if len(sys.argv) < 4:
            print("Usage: unity-yaml-tool.py generate-ui-prefab <json-spec> <output>", file=sys.stderr)
            sys.exit(1)
        spec_arg = sys.argv[2]
        output = sys.argv[3]
        if os.path.isfile(spec_arg):
            with open(spec_arg, "r", encoding="utf-8") as f:
                spec = json.load(f)
        else:
            spec = json.loads(spec_arg)
        generate_ui_prefab(spec, output)

    elif cmd == "validate":
        if len(sys.argv) < 3:
            print("Usage: unity-yaml-tool.py validate <file>", file=sys.stderr)
            sys.exit(1)
        validate_prefab(sys.argv[2])

    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
