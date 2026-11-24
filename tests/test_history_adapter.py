#!/usr/bin/env python3
"""Tests for history-adapter.py. Run: python3 -m unittest discover tests"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "history-adapter.py"
spec = importlib.util.spec_from_file_location("adapter", SCRIPT)
assert spec is not None and spec.loader is not None, f"cannot load {SCRIPT}"
adapter = importlib.util.module_from_spec(spec)
sys.modules["adapter"] = adapter
spec.loader.exec_module(adapter)


class ParseWibTests(unittest.TestCase):
    """WIB is UTC+7 and has no DST, so the offset must be exact."""

    def test_converts_wib_to_utc(self):
        got = adapter.parse_wib("2026-11-24 09:34 WIB")
        self.assertEqual(got, datetime(2026, 11, 24, 2, 34, tzinfo=timezone.utc))

    def test_midnight_wraps_to_previous_day(self):
        # 06:00 WIB is 23:00 UTC the day before -- the case that silently
        # shifts a day if the offset is applied with the wrong sign.
        got = adapter.parse_wib("2026-11-24 06:00 WIB")
        self.assertEqual(got, datetime(2026, 11, 23, 23, 0, tzinfo=timezone.utc))

    def test_accepts_missing_wib_suffix(self):
        self.assertIsNotNone(adapter.parse_wib("2026-11-24 09:34"))

    def test_returns_none_on_garbage(self):
        for bad in ("", "bukan tanggal", None, 12345):
            self.assertIsNone(adapter.parse_wib(bad), f"expected None for {bad!r}")


class FromEpochTests(unittest.TestCase):
    def test_converts_float_epoch(self):
        got = adapter.from_epoch(1795495919.05)
        self.assertIsNotNone(got)
        self.assertEqual(got.tzinfo, timezone.utc)

    def test_returns_none_on_garbage(self):
        for bad in ("x", None, {}, float("nan")):
            self.assertIsNone(adapter.from_epoch(bad), f"expected None for {bad!r}")


class LoadOutboundTests(unittest.TestCase):
    def _write(self, payload) -> Path:
        tmp = Path(tempfile.mkdtemp()) / "chat_history.json"
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        return tmp

    def test_maps_rows_to_out_direction(self):
        path = self._write(
            [{"text": "pagi nov, kuliah jam berapa?", "sent_at": "2026-11-24 09:34 WIB"}]
        )
        rows = adapter.load_outbound(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["direction"], "out")
        self.assertEqual(rows[0]["ts"], "2026-11-24T02:34:00Z")
        self.assertEqual(rows[0]["source"], "scheduled")

    def test_skips_rows_without_timestamp_or_text(self):
        path = self._write(
            [
                {"text": "oke", "sent_at": "2026-11-24 09:34 WIB"},
                {"text": "tanpa waktu"},
                {"sent_at": "2026-11-24 09:34 WIB"},
                {"text": "   ", "sent_at": "2026-11-24 09:34 WIB"},
                "bukan dict",
            ]
        )
        self.assertEqual(len(adapter.load_outbound(path)), 1)

    def test_rejects_non_array(self):
        path = self._write({"text": "bukan array"})
        with self.assertRaises(ValueError):
            adapter.load_outbound(path)


class LoadInboundTests(unittest.TestCase):
    def _db(self, rows) -> Path:
        path = Path(tempfile.mkdtemp()) / "state.db"
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE messages (id INTEGER PRIMARY KEY, role TEXT, "
            "content TEXT, timestamp REAL)"
        )
        conn.executemany(
            "INSERT INTO messages (role, content, timestamp) VALUES (?,?,?)", rows
        )
        conn.commit()
        conn.close()
        return path

    def test_only_user_role_becomes_inbound(self):
        path = self._db(
            [
                ("user", "halo nov", 1795495919.0),
                ("assistant", "halo sayang", 1795495920.0),
                ("tool", "output", 1795495921.0),
            ]
        )
        rows = adapter.load_inbound(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["direction"], "in")
        self.assertEqual(rows[0]["text"], "halo nov")

    def test_truncates_quoted_reply_to_first_line(self):
        path = self._db(
            [("user", '[Replying to: "panjang banget"]\nhalo nov', 1795495919.0)]
        )
        text = adapter.load_inbound(path)[0]["text"]
        self.assertTrue(text.startswith("[Replying to:"))
        self.assertNotIn("\n", text)

    def test_null_content_skipped(self):
        path = self._db([("user", None, 1795495919.0)])
        self.assertEqual(adapter.load_inbound(path), [])

    def test_db_opened_read_only(self):
        # A running agent holds the DB; the adapter must never take a write
        # lock or mutate it. mode=ro raises on any write attempt.
        path = self._db([("user", "halo", 1795495919.0)])
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        with self.assertRaises(sqlite3.OperationalError):
            conn.execute("INSERT INTO messages (role, content) VALUES ('user','x')")
        conn.close()


class MergeTests(unittest.TestCase):
    def test_sorted_chronologically_across_sources(self):
        out = [{"ts": "2026-11-24T02:34:00Z", "direction": "out", "text": "a"}]
        inn = [{"ts": "2026-11-24T01:00:00Z", "direction": "in", "text": "b"}]
        merged = adapter.merge(out, inn)
        self.assertEqual([e["text"] for e in merged], ["b", "a"])

    def test_dedupes_identical_entries(self):
        # A retried cron send appears twice in chat_history.json. Two copies
        # would satisfy the guard's "unanswered" counter on their own.
        row = {"ts": "2026-11-24T02:34:00Z", "direction": "out", "text": "sama"}
        self.assertEqual(len(adapter.merge([row], [dict(row)])), 1)


class EndToEndTests(unittest.TestCase):
    def test_cli_writes_jsonl_the_guard_can_read(self):
        tmp = Path(tempfile.mkdtemp())
        chat = tmp / "chat_history.json"
        chat.write_text(
            json.dumps([{"text": "pagi nov", "sent_at": "2026-11-24 09:34 WIB"}]),
            encoding="utf-8",
        )
        out = tmp / "history.jsonl"
        rc = adapter.main(["--chat-history", str(chat), "--out", str(out)])
        self.assertEqual(rc, 0)

        lines = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(lines), 1)
        self.assertEqual(set(lines[0]), {"ts", "direction", "text", "source"})
        # The guard parses ts with its own ISO parser; make sure ours fits.
        self.assertTrue(lines[0]["ts"].endswith("Z"))

    def test_missing_chat_history_exits_2(self):
        tmp = Path(tempfile.mkdtemp())
        rc = adapter.main(
            ["--chat-history", str(tmp / "nope.json"), "--out", str(tmp / "o.jsonl")]
        )
        self.assertEqual(rc, 2)

    def test_missing_state_db_still_produces_outbound(self):
        tmp = Path(tempfile.mkdtemp())
        chat = tmp / "chat_history.json"
        chat.write_text(
            json.dumps([{"text": "pagi nov", "sent_at": "2026-11-24 09:34 WIB"}]),
            encoding="utf-8",
        )
        out = tmp / "history.jsonl"
        rc = adapter.main(
            [
                "--chat-history",
                str(chat),
                "--state-db",
                str(tmp / "absent.db"),
                "--out",
                str(out),
            ]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(len(out.read_text(encoding="utf-8").splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
