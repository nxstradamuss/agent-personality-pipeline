#!/usr/bin/env python3
"""Tests for examples/send-guard-wrapper.py.

The wrapper is where the guard's *policy* lives, not just its plumbing:

    infrastructure broken  -> allow and log loudly  (fail-open)
    explicit block verdict -> refuse the send       (fail-closed)

`docs/SCHEDULED_MESSAGE_GUARD.md`, `docs/THREAT_MODEL.md` and the CHANGELOG all
state that split, but until now nothing executed it. A wrapper that silently
inverted the two would look identical from the guard's own test suite — the
guard would still return the right verdict, and the message would still go out.

Every test here swaps the wrapper's module-level paths for a temporary
directory, so nothing touches a real chat history or decision log.

Run: python3 -m unittest discover -s tests
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WRAPPER = REPO / "examples" / "send-guard-wrapper.py"

# A stand-in for history-adapter.py: it accepts the same --out flag and writes
# an empty (but valid) JSONL, which is all build_history() needs to succeed.
FAKE_ADAPTER = """
import sys
out = sys.argv[sys.argv.index("--out") + 1]
open(out, "w", encoding="utf-8").close()
"""


def load_wrapper():
    """Import a fresh module instance so each test gets unpolluted globals."""
    spec = importlib.util.spec_from_file_location("send_guard_wrapper", WRAPPER)
    assert spec is not None and spec.loader is not None, f"cannot load {WRAPPER}"
    module = importlib.util.module_from_spec(spec)
    sys.modules["send_guard_wrapper"] = module
    spec.loader.exec_module(module)
    return module


class WrapperTestCase(unittest.TestCase):
    """Points every path the wrapper knows about at a throwaway directory."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

        self.wrapper = load_wrapper()
        self.wrapper.CACHE = self.tmp / "guard_history.jsonl"
        self.wrapper.CHAT_HISTORY = self.tmp / "chat_history.json"
        self.wrapper.STATE_DB = self.tmp / "state.db"
        self.wrapper.DECISION_LOG = self.tmp / "guard-decisions.log"
        self.wrapper.ADAPTER = self.write_script("adapter.py", FAKE_ADAPTER)
        self.wrapper.CACHE_MAX_AGE_SECONDS = 0  # never reuse a stale cache

    def write_script(self, name: str, body: str) -> Path:
        path = self.tmp / name
        path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
        return path

    def log_lines(self) -> list[str]:
        if not self.wrapper.DECISION_LOG.exists():
            return []
        return self.wrapper.DECISION_LOG.read_text(encoding="utf-8").splitlines()


class InfrastructureFailureFailsOpen(WrapperTestCase):
    """A broken safety filter must never become permanent silence."""

    def test_missing_guard_allows_the_send(self):
        self.wrapper.GUARD = self.tmp / "no-such-guard.py"
        allowed, reason = self.wrapper.allow_send("disk udah 83%, aku rapikan backup ya")
        self.assertTrue(allowed, f"missing guard must fail open, got {reason!r}")
        self.assertEqual(reason, "guard-missing")
        self.assertTrue(any("guard-missing" in line for line in self.log_lines()))

    def test_unbuildable_history_allows_the_send(self):
        self.wrapper.GUARD = self.write_script("guard.py", "raise SystemExit(0)")
        self.wrapper.ADAPTER = self.tmp / "no-such-adapter.py"
        allowed, reason = self.wrapper.allow_send("snapshot 22 Nov udah ke-push")
        self.assertTrue(allowed, f"missing history must fail open, got {reason!r}")
        self.assertEqual(reason, "history-unavailable")

    def test_guard_that_cannot_be_executed_allows_the_send(self):
        self.wrapper.GUARD = self.tmp / "guard-that-is-a-directory"
        self.wrapper.GUARD.mkdir()
        allowed, reason = self.wrapper.allow_send("cron snapshot selesai")
        self.assertTrue(allowed, f"unexecutable guard must fail open, got {reason!r}")

    def test_crashing_guard_allows_the_send(self):
        """A traceback is an infrastructure error, not a verdict.

        An uncaught exception exits 1 — the same code the guard uses for a
        real block. The wrapper has to tell the two apart by looking at the
        payload, otherwise a bug in the rules silently mutes the agent.
        """
        self.wrapper.GUARD = self.write_script(
            "crashing_guard.py",
            """
            raise RuntimeError("guard blew up before it could decide")
            """,
        )
        allowed, reason = self.wrapper.allow_send("pagi nov, kuliahnya jam berapa?")
        self.assertTrue(allowed, f"crashing guard must fail open, got {reason!r}")
        self.assertIn("guard-error", reason)
        self.assertTrue(
            any("guard-error" in line for line in self.log_lines()),
            "a crash must be logged loudly, not swallowed",
        )

    def test_unexpected_exit_code_allows_the_send(self):
        self.wrapper.GUARD = self.write_script("odd_guard.py", "raise SystemExit(3)")
        allowed, reason = self.wrapper.allow_send("load turun ke 0.17")
        self.assertTrue(allowed, f"rc=3 must fail open, got {reason!r}")
        self.assertEqual(reason, "guard-rc-3")


    def test_guard_exit_2_fails_open_and_logs(self):
        """Exit 2 is "bad input", not a verdict — and it must not be silent.

        The guard now rejects a corrupt history line with exit 2, which is the
        documented contract for bad input. The wrapper must read that as
        infrastructure trouble (allow + log) rather than as a block, otherwise a
        single malformed line turns into permanent silence.
        """
        self.wrapper.GUARD = self.write_script(
            "rejecting_guard.py",
            """
            import sys
            print("error: history.jsonl:1: expected a JSON object", file=sys.stderr)
            raise SystemExit(2)
            """,
        )
        allowed, reason = self.wrapper.allow_send("pagi nov, kuliahnya jam berapa?")
        self.assertTrue(allowed, f"rc=2 must fail open, got {reason!r}")
        self.assertIn("2", reason)
        self.assertTrue(
            any("rc=2" in line for line in self.log_lines()),
            f"a bad-input exit must be logged, log was {self.log_lines()}",
        )

    @unittest.expectedFailure
    def test_exit_2_log_carries_the_guard_stderr(self):
        """KNOWN GAP: the rc=2 log line drops the reason.

        The rc=1 branch logs the last stderr line; the catch-all branch logs
        only the code. Since rc=2 now means "a history line is corrupt", the
        operator needs the line number the guard printed. Left unfixed here
        because the wrapper was out of scope for this change.
        """
        self.wrapper.GUARD = self.write_script(
            "rejecting_guard.py",
            """
            import sys
            print("error: history.jsonl:7: expected a JSON object", file=sys.stderr)
            raise SystemExit(2)
            """,
        )
        self.wrapper.allow_send("cron snapshot selesai")
        log = " ".join(self.log_lines())
        self.assertIn("history.jsonl:7", log, "the guard's reason should reach the log")


class ExplicitVerdictFailsClosed(WrapperTestCase):
    """A block that came from working rules is honoured."""

    def test_block_verdict_refuses_the_send(self):
        self.wrapper.GUARD = self.write_script(
            "blocking_guard.py",
            """
            import json
            print(json.dumps({"allow": False, "blockers": ["bare opener: nothing to reply to"], "warnings": []}))
            raise SystemExit(1)
            """,
        )
        allowed, reason = self.wrapper.allow_send("sayang~")
        self.assertFalse(allowed, "an explicit block must be respected")
        self.assertIn("bare opener", reason)
        self.assertTrue(any("BLOCK" in line for line in self.log_lines()))

    def test_allow_verdict_sends(self):
        self.wrapper.GUARD = self.write_script(
            "allowing_guard.py",
            """
            import json
            print(json.dumps({"allow": True, "blockers": [], "warnings": []}))
            raise SystemExit(0)
            """,
        )
        allowed, reason = self.wrapper.allow_send("snapshot 22 Nov udah ke-push, disk 83%")
        self.assertTrue(allowed)
        self.assertEqual(reason, "ok")
        self.assertTrue(any("ALLOW" in line for line in self.log_lines()))

    def test_block_without_a_readable_verdict_is_treated_as_a_crash(self):
        """Exit 1 with no payload cannot be told apart from a dead process.

        The wrapper calls the guard with `--json`, so a guard that decided
        something always prints an object. Silence on exit 1 means the rules
        never ran to completion, so the safe reading is "infrastructure
        broke", not "the rules said no".
        """
        self.wrapper.GUARD = self.write_script(
            "mute_guard.py", "raise SystemExit(1)"
        )
        allowed, reason = self.wrapper.allow_send("disk naik ke 83%")
        self.assertTrue(allowed, f"silent rc=1 must fail open, got {reason!r}")
        self.assertEqual(reason, "guard-error")


class WrapperNeverInvertsTheTwo(unittest.TestCase):
    """Guard the guard: the exit-code contract is the thing that must not drift."""

    def test_exit_one_is_the_only_blocking_code(self):
        source = WRAPPER.read_text(encoding="utf-8")
        self.assertIn("res.returncode == 1", source)
        self.assertIn("return False, reason", source)


if __name__ == "__main__":
    unittest.main()
