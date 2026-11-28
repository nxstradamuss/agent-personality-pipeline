#!/usr/bin/env python3
"""Edge-case tests for the history path: timezones, malformed JSONL, empty
history, and retried-send dedupe.

These cover the seam between `scripts/history-adapter.py` and
`scripts/scheduled-message-guard.py`. The adapter writes the JSONL the guard
reads, so a defect on either side of that seam shows up as a wrong verdict —
usually "allow" when the answer should have been "block", because a guard that
cannot read its history either crashes (exit 1, indistinguishable from a block
by code alone) or sees an empty history and allows everything.

Three groups of tests live here:

* **Regression tests** — behaviour that already works and must keep working
  (timezone normalisation, empty history, the exit-code contract).
* **Bug tests** — marked `expectedFailure` in the red-first commit. Each one
  documents a defect that was reproduced before it was fixed.
* **Known gaps** — marked `expectedFailure` and left that way, because fixing
  them is a separate decision. Each says so in its docstring.

`unittest.expectedFailure` is strict: if a marked test starts passing, the run
fails with "unexpected success". That is deliberate — it stops a fix from
silently outrunning the test that documents the bug.

Run: python3 -m unittest discover -s tests
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load(name: str, filename: str):
    path = REPO / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


adapter = _load("adapter_edge", "history-adapter.py")
guard = _load("guard_edge", "scheduled-message-guard.py")

CANDIDATE = "cron snapshot selesai, log 22 Nov udah ke-push"
BASE = datetime(2026, 11, 24, 2, 34, tzinfo=timezone.utc)


def iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def out_entry(ts: datetime, text: str) -> dict:
    return {"ts": iso(ts), "direction": "out", "text": text, "source": "scheduled"}


def in_entry(ts: datetime, text: str) -> dict:
    return {"ts": iso(ts), "direction": "in", "text": text, "source": "telegram"}


class TempDirTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def write_jsonl(self, content: str, name: str = "history.jsonl") -> Path:
        path = self.tmp / name
        path.write_text(content, encoding="utf-8")
        return path


# ==========================================================================
# Timezones
# ==========================================================================

class GuardTimezoneTests(TempDirTestCase):
    """The guard must order by instant, not by the string it was handed."""

    def test_parses_a_positive_offset_to_utc(self):
        # 09:00+07:00 is 02:00 UTC. Getting the sign wrong shifts it to 16:00.
        self.assertEqual(
            guard.parse_ts("2026-11-24T09:00:00+07:00"),
            datetime(2026, 11, 24, 2, 0, tzinfo=timezone.utc),
        )

    def test_parses_a_negative_offset_to_utc(self):
        # 09:00-05:00 is 14:00 UTC, the same calendar day.
        self.assertEqual(
            guard.parse_ts("2026-11-24T09:00:00-05:00"),
            datetime(2026, 11, 24, 14, 0, tzinfo=timezone.utc),
        )

    def test_a_naive_timestamp_is_read_as_utc(self):
        self.assertEqual(
            guard.parse_ts("2026-11-24T09:00:00"),
            datetime(2026, 11, 24, 9, 0, tzinfo=timezone.utc),
        )

    def test_mixed_offsets_are_ordered_by_instant(self):
        """Three representations of increasing instants, written out of order.

        Sorted as strings these come out wrong: "09:00+07:00" sorts before
        "02:00Z" alphabetically while being the same instant. The guard sorts
        parsed datetimes, so the order must follow the clock.
        """
        path = self.write_jsonl("\n".join(json.dumps(r) for r in [
            {"ts": "2026-11-24T14:00:00-05:00", "direction": "out", "text": "ketiga"},
            {"ts": "2026-11-24T02:00:00Z", "direction": "out", "text": "pertama"},
            {"ts": "2026-11-24T09:30:00+07:00", "direction": "in", "text": "kedua"},
        ]))
        entries = guard.load_history(path)
        self.assertEqual([e.text for e in entries], ["pertama", "kedua", "ketiga"])
        self.assertTrue(all(e.ts.tzinfo is timezone.utc for e in entries))


class AdapterTimezoneTests(TempDirTestCase):
    def test_date_only_stamp_is_midnight_wib(self):
        # Midnight WIB is 17:00 UTC the previous day.
        self.assertEqual(
            adapter.parse_wib("2026-11-24"),
            datetime(2026, 11, 23, 17, 0, tzinfo=timezone.utc),
        )

    def test_wib_midnight_crossing_does_not_lose_the_day(self):
        self.assertEqual(
            adapter.parse_wib("2026-11-24 00:30 WIB"),
            datetime(2026, 11, 23, 17, 30, tzinfo=timezone.utc),
        )

    def test_from_epoch_rejects_non_finite_and_absurd_values(self):
        for bad in (float("inf"), float("-inf"), 1e18, -1e18):
            self.assertIsNone(adapter.from_epoch(bad), f"expected None for {bad!r}")

    def test_every_emitted_timestamp_is_utc_z(self):
        chat = self.tmp / "chat_history.json"
        chat.write_text(json.dumps([
            {"text": "pagi nov, kuliah jam berapa?", "sent_at": "2026-11-24 09:34 WIB"},
            {"text": "malam, udah makan?", "sent_at": "2026-11-24"},
        ]), encoding="utf-8")
        rows = adapter.load_outbound(chat)
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertTrue(row["ts"].endswith("Z"), row["ts"])
            self.assertEqual(
                guard.parse_ts(row["ts"]).strftime("%Y-%m-%dT%H:%M:%SZ"), row["ts"]
            )


# ==========================================================================
# Malformed JSONL
# ==========================================================================

class MalformedJsonlTests(TempDirTestCase):
    """A corrupt line must be a *bad input* error, not a crash.

    `load_history` only caught JSONDecodeError/KeyError/ValueError. Anything
    that raised TypeError or AttributeError escaped as a traceback, which exits
    1 — the same code the guard uses for "blocked". The wrapper reads exit 1
    without a JSON verdict as a crash and fails open, so a single corrupt line
    disabled the guard while still letting the message through.
    """

    def assertBadInput(self, content: str, needle: str = ":1:") -> str:
        path = self.write_jsonl(content)
        with self.assertRaises(ValueError) as ctx:
            guard.load_history(path)
        message = str(ctx.exception)
        self.assertIn(needle, message, f"error should name the line: {message}")
        return message

    @unittest.expectedFailure
    def test_a_json_array_line_is_bad_input(self):
        self.assertBadInput("[1,2,3]\n")

    @unittest.expectedFailure
    def test_a_json_string_line_is_bad_input(self):
        self.assertBadInput('"hi"\n')

    @unittest.expectedFailure
    def test_a_json_null_line_is_bad_input(self):
        self.assertBadInput("null\n")

    @unittest.expectedFailure
    def test_a_json_number_line_is_bad_input(self):
        self.assertBadInput("42\n")

    @unittest.expectedFailure
    def test_a_non_string_ts_is_bad_input(self):
        self.assertBadInput('{"ts":123,"direction":"out","text":"x"}\n')

    @unittest.expectedFailure
    def test_a_null_ts_is_bad_input(self):
        self.assertBadInput('{"ts":null,"direction":"out","text":"x"}\n')

    @unittest.expectedFailure
    def test_an_unknown_direction_is_bad_input(self):
        """An unrecognised direction is silently ignored by the streak counter.

        `unanswered_streak` only compares against "out" and "in", so a typo
        like "In" or "OUT" makes the entry invisible to the rule that matters
        most. Reject it instead of dropping it.
        """
        self.assertBadInput('{"ts":"2026-11-24T02:00:00Z","direction":"sideways","text":"x"}\n')

    @unittest.expectedFailure
    def test_a_non_string_text_is_bad_input(self):
        self.assertBadInput('{"ts":"2026-11-24T02:00:00Z","direction":"out","text":123}\n')

    @unittest.expectedFailure
    def test_the_line_number_points_at_the_offending_line(self):
        content = "\n".join([
            json.dumps({"ts": "2026-11-24T02:00:00Z", "direction": "out", "text": "oke"}),
            json.dumps({"ts": "2026-11-24T03:00:00Z", "direction": "in", "text": "sip"}),
            "[1,2,3]",
        ])
        self.assertBadInput(content, needle=":3:")

    def test_blank_lines_and_comments_are_still_skipped(self):
        content = "\n".join([
            "",
            "# catatan manual",
            json.dumps({"ts": "2026-11-24T02:00:00Z", "direction": "out", "text": "oke"}),
            "   ",
        ])
        self.assertEqual(len(guard.load_history(self.write_jsonl(content))), 1)


class ExitCodeContractTests(TempDirTestCase):
    """Exit 2 means "bad input". Exit 1 means "blocked". They must not blur.

    Validating exception types one at a time only postpones the next unhandled
    one, so the fix also adds a top-level net in `main`. These tests pin both
    halves of that contract.
    """

    def good_history(self) -> Path:
        return self.write_jsonl(
            json.dumps({"ts": "2026-11-24T02:00:00Z", "direction": "out", "text": "oke"}) + "\n"
        )

    @unittest.expectedFailure
    def test_a_corrupt_line_exits_2_not_1(self):
        path = self.write_jsonl("[1,2,3]\n")
        self.assertEqual(guard.main(["--history", str(path), "--candidate", CANDIDATE]), 2)

    @unittest.expectedFailure
    def test_an_unexpected_failure_exits_2_not_1(self):
        """The net catches what the per-line validation did not anticipate."""
        def boom(*args, **kwargs):
            raise RuntimeError("something nobody anticipated")

        original = guard.check
        guard.check = boom
        self.addCleanup(setattr, guard, "check", original)
        rc = guard.main(["--history", str(self.good_history()), "--candidate", CANDIDATE])
        self.assertEqual(rc, 2, "an uncaught traceback would exit 1, same as a block")

    def test_a_real_block_still_exits_1(self):
        path = self.good_history()
        self.assertEqual(guard.main(["--history", str(path), "--candidate", "sayang~"]), 1)

    def test_an_allowed_send_still_exits_0(self):
        path = self.good_history()
        self.assertEqual(guard.main(["--history", str(path), "--candidate", CANDIDATE]), 0)

    def test_a_missing_history_file_still_exits_2(self):
        self.assertEqual(
            guard.main(["--history", str(self.tmp / "nope.jsonl"), "--candidate", CANDIDATE]), 2
        )

    def test_the_safety_net_does_not_swallow_help(self):
        """`--help` raises SystemExit(0); the net must re-raise, not convert it."""
        with self.assertRaises(SystemExit) as ctx:
            guard.main(["--help"])
        self.assertEqual(ctx.exception.code, 0)


# ==========================================================================
# Empty history
# ==========================================================================

class EmptyHistoryTests(TempDirTestCase):
    """A first run has no history. That is normal, not an error."""

    def test_a_zero_byte_file_yields_no_entries(self):
        self.assertEqual(guard.load_history(self.write_jsonl("")), [])

    def test_a_comment_only_file_yields_no_entries(self):
        self.assertEqual(guard.load_history(self.write_jsonl("# belum ada pesan\n\n")), [])

    def test_an_empty_history_allows_the_first_send(self):
        path = self.write_jsonl("")
        self.assertEqual(guard.main(["--history", str(path), "--candidate", CANDIDATE]), 0)

    def test_an_empty_history_does_not_warn_about_a_dead_channel(self):
        """No history is not evidence the channel is broken; say nothing."""
        verdict = guard.check(CANDIDATE, [], now=BASE)
        self.assertTrue(verdict.allow, verdict.blockers)
        self.assertEqual(verdict.warnings, [])

    def test_an_empty_chat_history_produces_an_empty_jsonl(self):
        chat = self.tmp / "chat_history.json"
        chat.write_text("[]", encoding="utf-8")
        out = self.tmp / "history.jsonl"
        self.assertEqual(adapter.main(["--chat-history", str(chat), "--out", str(out)]), 0)
        self.assertTrue(out.exists(), "the guard reads this file; it must exist even when empty")
        self.assertEqual(out.read_text(encoding="utf-8"), "")

    def test_an_empty_db_and_empty_chat_history_still_exit_0(self):
        chat = self.tmp / "chat_history.json"
        chat.write_text("[]", encoding="utf-8")
        db = self.tmp / "state.db"
        import sqlite3
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE messages (id INTEGER PRIMARY KEY, role TEXT, content TEXT, timestamp REAL)"
        )
        conn.commit()
        conn.close()
        out = self.tmp / "history.jsonl"
        rc = adapter.main([
            "--chat-history", str(chat), "--state-db", str(db), "--out", str(out),
        ])
        self.assertEqual(rc, 0)
        self.assertEqual(out.read_text(encoding="utf-8"), "")


# ==========================================================================
# Retried-send dedupe
# ==========================================================================

class RetriedSendDedupeTests(unittest.TestCase):
    """A retried cron send can land twice with a re-stamped timestamp.

    `merge` deduped on `(ts, direction, text)`, which only catches an exact
    copy. A retry that writes a fresh `sent_at` a few seconds later survived as
    two entries, and two copies of one message satisfy the guard's
    "N unanswered in a row" counter on their own — pausing a healthy sender.
    """

    TEXT = "pagi nov, kuliah jam berapa?"

    def merged(self, *groups, window=120):
        return adapter.merge(*groups, dedupe_window_seconds=window)

    @unittest.expectedFailure
    def test_a_retry_seven_seconds_later_is_collapsed(self):
        merged = self.merged(
            [out_entry(BASE, self.TEXT)],
            [out_entry(BASE + timedelta(seconds=7), self.TEXT)],
        )
        self.assertEqual(len(merged), 1, "a re-stamped retry is one message, not two")

    @unittest.expectedFailure
    def test_boundary_119_seconds_is_collapsed(self):
        merged = self.merged(
            [out_entry(BASE, self.TEXT)],
            [out_entry(BASE + timedelta(seconds=119), self.TEXT)],
        )
        self.assertEqual(len(merged), 1)

    @unittest.expectedFailure
    def test_boundary_120_seconds_is_collapsed(self):
        """The window is inclusive: "within N seconds" includes N."""
        merged = self.merged(
            [out_entry(BASE, self.TEXT)],
            [out_entry(BASE + timedelta(seconds=120), self.TEXT)],
        )
        self.assertEqual(len(merged), 1)

    @unittest.expectedFailure
    def test_boundary_121_seconds_is_kept(self):
        merged = self.merged(
            [out_entry(BASE, self.TEXT)],
            [out_entry(BASE + timedelta(seconds=121), self.TEXT)],
        )
        self.assertEqual(len(merged), 2, "outside the window is a real second send")

    @unittest.expectedFailure
    def test_identical_texts_hours_apart_are_not_collapsed(self):
        merged = self.merged(
            [out_entry(BASE, self.TEXT)],
            [out_entry(BASE + timedelta(hours=8), self.TEXT)],
        )
        self.assertEqual(len(merged), 2)

    @unittest.expectedFailure
    def test_inbound_duplicates_are_not_collapsed(self):
        """A person can send "ok" twice in five seconds. That is not a retry."""
        merged = self.merged(
            [in_entry(BASE, "ok")],
            [in_entry(BASE + timedelta(seconds=5), "ok")],
        )
        self.assertEqual(len(merged), 2)

    @unittest.expectedFailure
    def test_different_texts_within_the_window_are_not_collapsed(self):
        merged = self.merged(
            [out_entry(BASE, self.TEXT)],
            [out_entry(BASE + timedelta(seconds=7), "malam, udah makan?")],
        )
        self.assertEqual(len(merged), 2)

    @unittest.expectedFailure
    def test_the_earliest_copy_is_the_one_kept(self):
        later = out_entry(BASE + timedelta(seconds=7), self.TEXT)
        earlier = out_entry(BASE, self.TEXT)
        merged = self.merged([later], [earlier])
        self.assertEqual(merged[0]["ts"], iso(BASE))

    @unittest.expectedFailure
    def test_an_out_and_an_in_with_the_same_text_are_both_kept(self):
        merged = self.merged([out_entry(BASE, "ok")], [in_entry(BASE, "ok")])
        self.assertEqual(len(merged), 2)

    @unittest.expectedFailure
    def test_the_default_window_is_two_minutes(self):
        self.assertEqual(adapter.DEFAULT_DEDUPE_WINDOW, 120)

    @unittest.expectedFailure
    def test_the_window_can_be_disabled(self):
        merged = self.merged(
            [out_entry(BASE, self.TEXT)],
            [out_entry(BASE + timedelta(seconds=7), self.TEXT)],
            window=0,
        )
        self.assertEqual(len(merged), 2)

    @unittest.expectedFailure
    def test_the_cli_exposes_the_window(self):
        tmp = Path(tempfile.mkdtemp())
        chat = tmp / "chat_history.json"
        chat.write_text(json.dumps([
            {"text": self.TEXT, "sent_at": "2026-11-24 09:34 WIB"},
            {"text": self.TEXT, "sent_at": "2026-11-24 09:34 WIB"},
        ]), encoding="utf-8")
        out = tmp / "history.jsonl"
        rc = adapter.main([
            "--chat-history", str(chat), "--out", str(out), "--dedupe-window", "0",
        ])
        self.assertEqual(rc, 0)
        self.assertEqual(len(out.read_text(encoding="utf-8").splitlines()), 1,
                         "identical stamps are exact duplicates regardless of the window")

    @unittest.expectedFailure
    def test_a_collapsed_retry_does_not_satisfy_the_pause_rule(self):
        """The point of the dedupe: two copies must not read as two sends."""
        merged = self.merged(
            [out_entry(BASE - timedelta(hours=9), self.TEXT)],
            [out_entry(BASE - timedelta(hours=9) + timedelta(seconds=7), self.TEXT)],
        )
        entries = [
            guard.Entry(guard.parse_ts(e["ts"]), e["direction"], e["text"]) for e in merged
        ]
        self.assertEqual(guard.unanswered_streak(entries), 1)


# ==========================================================================
# Known gaps — documented, not fixed here
# ==========================================================================

class KnownGaps(unittest.TestCase):
    """Defects that are real but belong to a separate decision."""

    @unittest.expectedFailure
    def test_merge_order_is_independent_of_source_order(self):
        """KNOWN GAP: equal timestamps order by source, and the verdict follows.

        `merge` sorts on the timestamp string with a stable sort, so two entries
        stamped the same second keep the order their source happened to be
        passed in. `unanswered_streak` walks the list backwards, so an inbound
        entry that lands *before* an outbound one at the same instant is not
        seen as a reply.

        Measured: `merge([out],[in])` -> streak 0, `merge([in],[out])` -> streak 1.

        It is masked today because the adapter always passes outbound first, so
        no live path is affected. Fixing it means picking a tie-break rule
        (inbound after outbound) — a separate change with its own commit.
        """
        same = BASE
        forward = adapter.merge(
            [out_entry(same, self_text := "pagi nov, kuliah jam berapa?")],
            [in_entry(same, "jam 9")],
        )
        backward = adapter.merge(
            [in_entry(same, "jam 9")],
            [out_entry(same, self_text)],
        )

        def streak(rows):
            entries = [
                guard.Entry(guard.parse_ts(r["ts"]), r["direction"], r["text"]) for r in rows
            ]
            return guard.unanswered_streak(entries)

        self.assertEqual(streak(forward), 0)
        self.assertEqual(streak(backward), 0, "same history, same verdict, either order")


if __name__ == "__main__":
    unittest.main()
