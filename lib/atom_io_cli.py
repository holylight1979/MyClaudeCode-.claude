"""atom_io_cli.py — thin CLI bridge: stdin JSON → write_atom → stdout JSON (S1.3)

供 S3.2 server.js 切 spawn 用：MCP toolAtomWrite/Promote 最終落檔
改 spawn `python -m lib.atom_io_cli`，stdin 餵 JSON 參數，stdout 讀 WriteResult。

Schema:
  stdin:  {"action": "write_atom"|"write_index"|"write_index_full"|"write_raw", ...kwargs}
  stdout: WriteResult.to_dict()  (single-line JSON)
  exit code: 0=ok, 1=error

write_raw / write_index_full 額外參數：caller 端傳 file_path (str)、content (str)。

Wave 2 移除：update_atom_field action（計數類欄位改走 lib/atom_access.py CLI
入口 `python -m lib.atom_access ...`，不再透過此 bridge）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .atom_io import (
    write_atom, write_index, write_index_full, write_raw,
    WriteResult,
)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": f"invalid stdin JSON: {e}"}))
        return 1

    action = payload.pop("action", "write_atom")
    try:
        if action == "write_atom":
            result = write_atom(**payload)
        elif action == "write_index":
            result = write_index(**payload)
        elif action == "write_index_full":
            # JSON 不能傳 Path，caller 用 str；轉成 Path
            payload["index_path"] = Path(payload["index_path"])
            result = write_index_full(**payload)
        elif action == "write_raw":
            payload["file_path"] = Path(payload["file_path"])
            result = write_raw(**payload)
        else:
            result = WriteResult(ok=False, error=f"unknown action: {action}")
    except TypeError as e:
        result = WriteResult(ok=False, error=f"bad params: {e}")
    except KeyError as e:
        result = WriteResult(ok=False, error=f"missing param: {e}")

    print(json.dumps(result.to_dict(), ensure_ascii=False))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
