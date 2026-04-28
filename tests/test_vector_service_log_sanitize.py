"""test_vector_service_log_sanitize.py — Vector Service log_message sanitize (2026-04-28)

對應檔案: tools/memory-vector-service/service.py:VectorServiceHandler.log_message
對應議題: #6（service.log 隱私衛生 — 砍 request line 的 query string）

不啟動實 HTTP server；以最小 mock 直接呼叫 log_message 觀察 stderr。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest  # noqa: F401

SERVICE_DIR = Path(__file__).resolve().parent.parent / "tools" / "memory-vector-service"
sys.path.insert(0, str(SERVICE_DIR))
# wg_paths import side-effect 需要
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

import importlib  # noqa: E402

service = importlib.import_module("service")  # type: ignore[attr-defined]
VectorServiceHandler = service.VectorServiceHandler


class _FakeHandler:
    """Minimal stand-in to call log_message as unbound method without a real socket."""

    client_address = ("127.0.0.1", 12345)


def _call_log_message(format_str, *args):
    """Invoke VectorServiceHandler.log_message on a fake instance."""
    VectorServiceHandler.log_message(_FakeHandler(), format_str, *args)


# ─── 4 必要 test ────────────────────────────────────────────────────


def test_sanitize_strips_query_string(capsys):
    """request line 含 query string → stderr 不得出現 q=secret / top_k。"""
    _call_log_message('"%s" %s %s', 'GET /search?q=secret&top_k=1 HTTP/1.1', '200', '-')
    err = capsys.readouterr().err
    assert "q=secret" not in err, f"query string leaked: {err!r}"
    assert "top_k" not in err, f"top_k leaked: {err!r}"
    assert "/search" in err, f"path missing: {err!r}"
    assert "200" in err, f"status missing: {err!r}"


def test_passthrough_when_no_query(capsys):
    """無 query string 的 request line → 完整保留。"""
    _call_log_message('"%s" %s %s', 'GET /health HTTP/1.1', '200', '-')
    err = capsys.readouterr().err
    assert "/health" in err, err
    assert "200" in err, err
    assert "-" in err, err
    # 確保 HTTP/1.1 也保留
    assert "HTTP/1.1" in err, err


def test_passthrough_non_request_format(capsys):
    """format 不是 log_request 樣式（如直呼 log_message） → 原樣輸出。"""
    _call_log_message('%s', 'some debug message')
    err = capsys.readouterr().err
    assert "some debug message" in err, err


def test_fail_open_malformed_request_line(capsys):
    """args[0] 不像 request line（單 token）→ 不 crash。"""
    # 不應 raise；輸出可接受任何內容（fail-open 保留 garbage）
    _call_log_message('"%s" %s %s', 'GARBAGE', '500', '-')
    err = capsys.readouterr().err
    # 至少有 stderr 輸出（fail-open 應保留訊息或退化為原 format）
    assert err.strip() != "", "expected some stderr output even on malformed input"
