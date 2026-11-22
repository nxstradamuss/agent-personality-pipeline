#!/usr/bin/env python3
"""Tests for scheduled-message-guard.py. Run: python3 -m unittest discover tests"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "scheduled-message-guard.py"
spec = importlib.util.spec_from_file_location("guard", SCRIPT)
assert spec is not None and spec.loader is not None, f"cannot load {SCRIPT}"
guard = importlib.util.module_from_spec(spec)
sys.modules["guard"] = guard
spec.loader.exec_module(guard)

Entry = guard.Entry
NOW = datetime(2026, 11, 22, 9, 0, tzinfo=timezone.utc)


def entry(hours_ago: float, direction: str, text: str) -> Entry:
    return Entry(NOW - timedelta(hours=hours_ago), direction, text)


class IntervalTests(unittest.TestCase):
    def test_blocks_inside_minimum_interval(self):
        history = [entry(2, "out", "pagi nov, kuliahnya jam berapa?"), entry(1.5, "in", "jam 9")]
        verdict = guard.check("malam, udah makan?", history, now=NOW)
        self.assertFalse(verdict.allow)
        self.assertTrue(any("minimum 6h" in b for b in verdict.blockers))

    def test_allows_after_interval(self):
        history = [entry(7, "out", "pagi nov, kuliahnya jam berapa?"), entry(6, "in", "jam 9")]
        verdict = guard.check("disk udah 83%, aku rapikan backup ya", history, now=NOW)
        self.assertTrue(verdict.allow, verdict.blockers)

    def test_first_ever_message_has_no_interval_rule(self):
        verdict = guard.check("cron snapshot hari ini udah jalan", [], now=NOW)
        self.assertTrue(verdict.allow, verdict.blockers)


class PauseTests(unittest.TestCase):
    def test_blocks_after_two_unanswered(self):
        history = [entry(30, "out", "disk naik ke 83%"), entry(12, "out", "load turun ke 0.17")]
        verdict = guard.check("pagi, ada yang mau dikerjain?", history, now=NOW)
        self.assertFalse(verdict.allow)
        self.assertTrue(any("no reply" in b for b in verdict.blockers))

    def test_reply_resets_the_streak(self):
        history = [entry(30, "out", "disk naik ke 83%"), entry(20, "in", "oke"), entry(12, "out", "udah kuberesin")]
        verdict = guard.check("token-radar masih di 499a09e", history, now=NOW)
        self.assertTrue(verdict.allow, verdict.blockers)


class RepeatTests(unittest.TestCase):
    def test_blocks_identical_text(self):
        history = [entry(48, "out", "disk naik ke 83%"), entry(47, "in", "ok")]
        verdict = guard.check("disk naik ke 83%", history, now=NOW)
        self.assertFalse(verdict.allow)
        self.assertTrue(any("identical" in b for b in verdict.blockers))

    def test_blocks_repeated_opener(self):
        history = [entry(48, "out", "pagi nov, kuliahnya jam berapa?"), entry(47, "in", "jam 9")]
        verdict = guard.check("pagi nov, ada kelas hari ini?", history, now=NOW)
        self.assertFalse(verdict.allow)
        self.assertTrue(any("opens the same way" in b for b in verdict.blockers))

    def test_repeat_window_expires(self):
        history = [entry(24 * 8, "out", "pagi nov, kuliahnya jam berapa?"), entry(24 * 8 - 1, "in", "jam 9")]
        verdict = guard.check("pagi nov, ada kelas hari ini?", history, now=NOW)
        self.assertTrue(verdict.allow, verdict.blockers)


class OpenerTests(unittest.TestCase):
    def test_bare_endearment_is_blocked(self):
        verdict = guard.check("sayang~", [], now=NOW)
        self.assertFalse(verdict.allow)
        self.assertTrue(any("bare opener" in b for b in verdict.blockers))

    def test_bare_greeting_plus_name_is_blocked(self):
        verdict = guard.check("hai sayang~~", [], now=NOW)
        self.assertFalse(verdict.allow)

    def test_greeting_with_content_passes(self):
        verdict = guard.check("pagi nov, semoga mudah kuliahnya", [], now=NOW)
        self.assertTrue(verdict.allow, verdict.blockers)

    def test_event_anchored_opener_passes(self):
        verdict = guard.check("cron snapshot selesai, log 22 Nov udah ke-push", [], now=NOW)
        self.assertTrue(verdict.allow, verdict.blockers)


class ForbiddenTermTests(unittest.TestCase):
    def test_forbidden_term_is_blocked(self):
        verdict = guard.check("malu-malu apa sih?", [], now=NOW)
        self.assertFalse(verdict.allow)
        self.assertTrue(any("malu-malu" in b for b in verdict.blockers))


class InputTests(unittest.TestCase):
    def test_empty_candidate_is_rejected(self):
        verdict = guard.check("   ", [], now=NOW)
        self.assertFalse(verdict.allow)

    def test_history_round_trip(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "h.jsonl"
            path.write_text("\n".join(json.dumps(r) for r in [
                {"ts": "2026-11-22T03:00:00Z", "direction": "out", "text": "disk naik ke 83%"},
                {"ts": "2026-11-22T04:00:00Z", "direction": "in", "text": "ok"},
            ]))
            entries = guard.load_history(path)
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0].direction, "out")

    def test_bad_history_line_names_the_line(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "h.jsonl"
            path.write_text('{"ts": "nope", "direction": "out"}\n')
            with self.assertRaises(ValueError) as ctx:
                guard.load_history(path)
            self.assertIn(":1:", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
