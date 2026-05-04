"""atom_io_cli.py — thin CLI bridge: stdin JSON → write_atom → stdout JSON (S1.3)

供 S3.2 server.js 切 spawn 用：MCP toolAtomWrite/Promote/Move 主體刪掉，
改 spawn `python -m lib.atom_io_cli`，stdin 餵 JSON 參數，stdout 讀 WriteResult。

Schema:
  stdin:  {"action": "write_atom"|"write_index", ...kwargs}
  stdout: WriteResult.to_dict()  (single-line JSON)
  exit code: 0=ok, 1=error
"""

from __future__ import annotations

import json
import sys

from .atom_io import write_atom, write_index, WriteResult


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
        else:
            result = WriteResult(ok=False, error=f"unknown action: {action}")
    except TypeError as e:
        result = WriteResult(ok=False, error=f"bad params: {e}")

    print(json.dumps(result.to_dict(), ensure_ascii=False))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
