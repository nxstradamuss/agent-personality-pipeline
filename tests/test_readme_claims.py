"""README ↔ THREAT_MODEL claim-map integrity tests.

The threat model's contract is stated in the task that produced it: *every
README claim maps to either an enforcing mechanism or "convention only."*
That is a checkable statement, so it is checked here instead of trusted.

The tests parse README.md for claim-bearing structures (architecture nodes,
concept headings, config rows, the non-negotiable guard list, artifact rows),
parse the `## Claim → Control Map` table out of docs/THREAT_MODEL.md, and
assert:

* coverage — no README claim is unmapped, no mapped ID is stale
* fidelity — the claim text in the map matches README verbatim
* vocabulary — status is exactly `enforced` or `convention only`
* substance — an `enforced` row names a mechanism that exists on disk (and,
  for `path#symbol` rows, a symbol that appears in that file) plus a test file
  that exists
* no prompt-laundering — an `enforced` row may not cite a file under
  `prompts/`. A prompt is not a mechanism; that is the whole point.

Run: python3 -m unittest discover -s tests
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
THREAT_MODEL = REPO / "docs" / "THREAT_MODEL.md"

ENFORCED = "enforced"
CONVENTION = "convention only"
VALID_STATUS = {ENFORCED, CONVENTION}

REQUIRED_SECTIONS = (
    "Assets",
    "Trust Boundaries",
    "Threats",
    "Claim → Control Map",
    "Out of Scope",
    "Known Defects",
)


# --------------------------------------------------------------------------
# README parsing
# --------------------------------------------------------------------------

def _sections(text: str) -> dict[str, str]:
    """Split markdown on level-2 headings. Returns {heading: body}."""
    out: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m and not line.startswith("###"):
            current = m.group(1)
            out[current] = []
            continue
        if current is not None:
            out[current].append(line)
    return {k: "\n".join(v) for k, v in out.items()}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _norm(text: str) -> str:
    """Collapse whitespace and unify typographic punctuation for comparison."""
    text = text.replace("→", "->").replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip()


def readme_claims(text: str | None = None) -> dict[str, str]:
    """Extract {claim_id: claim_text} for every claim-bearing README element."""
    if text is None:
        text = README.read_text(encoding="utf-8")
    sections = _sections(text)
    claims: dict[str, str] = {}

    # 1. Architecture mermaid nodes: `A[Personality Review<br/>Weekly Sun 06:00]`
    arch = sections.get("Architecture", "")
    for node, label in re.findall(r"\b([A-Z])\[([^\]]+)\]", arch):
        claims[f"ARCH-{node}"] = _norm(label.replace("<br/>", " "))

    # 2. Core Concepts `###` headings
    for heading in re.findall(r"^###\s+(.+?)\s*$", sections.get("Core Concepts", ""), re.MULTILINE):
        claims[f"CONCEPT-{_slug(heading)}"] = _norm(heading)

    # 3. Configuration table rows keyed by config file name
    for name in re.findall(r"^\|\s*`(config/[^`]+)`", sections.get("Configuration", ""), re.MULTILINE):
        claims[f"CFG-{Path(name).name}"] = _norm(name)

    # 4. Permission Creep Guards numbered list
    guards = sections.get("Permission Creep Guards (Non-Negotiable)", "")
    for idx, item in enumerate(re.findall(r"^\d+\.\s+(.+?)\s*$", guards, re.MULTILINE), start=1):
        claims[f"PCG-{idx}"] = _norm(item.replace("**", ""))

    # 5. File Artifacts table rows keyed by artifact name
    for name in re.findall(r"^\|\s*`([^`]+)`\s*\|", sections.get("File Artifacts", ""), re.MULTILINE):
        claims[f"ART-{name}"] = _norm(name)

    return claims


# --------------------------------------------------------------------------
# THREAT_MODEL parsing
# --------------------------------------------------------------------------

def control_map(text: str | None = None) -> dict[str, dict[str, str]]:
    """Parse the `## Claim → Control Map` table into {id: {claim,status,mechanism,evidence,notes}}."""
    if text is None:
        text = THREAT_MODEL.read_text(encoding="utf-8")
    body = _sections(text).get("Claim → Control Map", "")
    rows: dict[str, dict[str, str]] = {}
    for line in body.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5:
            continue
        ident = cells[0].strip("`")
        if ident in ("ID", "") or set(ident) <= {"-", ":"}:
            continue
        rows[ident] = {
            "claim": cells[1],
            "status": cells[2],
            "mechanism": cells[3],
            "evidence": cells[4],
            "notes": cells[5] if len(cells) > 5 else "",
        }
    return rows


def backticked(cell: str) -> list[str]:
    return re.findall(r"`([^`]+)`", cell)


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

class ThreatModelExists(unittest.TestCase):
    def test_document_exists(self):
        self.assertTrue(THREAT_MODEL.is_file(), f"missing {THREAT_MODEL}")

    def test_required_sections_present(self):
        text = THREAT_MODEL.read_text(encoding="utf-8")
        headings = re.findall(r"^##\s+(.+?)\s*$", text, re.MULTILINE)
        for needed in REQUIRED_SECTIONS:
            self.assertTrue(
                any(needed.lower() in h.lower() for h in headings),
                f"section '{needed}' missing from THREAT_MODEL.md (found: {headings})",
            )


class ClaimMapCoverage(unittest.TestCase):
    def setUp(self):
        self.claims = readme_claims()
        self.mapped = control_map()

    def test_readme_claims_were_actually_parsed(self):
        # Guard against a parser that silently matches nothing and passes.
        self.assertGreaterEqual(len(self.claims), 20, f"only parsed {len(self.claims)} claims")

    def test_every_readme_claim_is_mapped(self):
        missing = sorted(set(self.claims) - set(self.mapped))
        self.assertEqual(missing, [], f"README claims with no threat-model entry: {missing}")

    def test_no_stale_map_entries(self):
        stale = sorted(set(self.mapped) - set(self.claims))
        self.assertEqual(stale, [], f"threat-model entries not backed by a README claim: {stale}")

    def test_claim_text_matches_readme(self):
        for ident, claim in self.claims.items():
            if ident not in self.mapped:
                continue
            with self.subTest(claim=ident):
                self.assertEqual(
                    _norm(self.mapped[ident]["claim"]), claim,
                    f"{ident}: claim text drifted from README",
                )


class ClaimMapSubstance(unittest.TestCase):
    def setUp(self):
        self.mapped = control_map()

    def test_status_vocabulary(self):
        for ident, row in self.mapped.items():
            with self.subTest(claim=ident):
                self.assertIn(row["status"], VALID_STATUS, f"{ident}: bad status {row['status']!r}")

    def test_enforced_claims_cite_existing_mechanism(self):
        for ident, row in self.mapped.items():
            if row["status"] != ENFORCED:
                continue
            refs = backticked(row["mechanism"])
            with self.subTest(claim=ident):
                self.assertTrue(refs, f"{ident}: enforced but cites no mechanism")
                for ref in refs:
                    path = REPO / ref.split("#", 1)[0]
                    self.assertTrue(path.exists(), f"{ident}: mechanism path missing: {ref}")
                    if "#" in ref:
                        symbol = ref.split("#", 1)[1]
                        body = path.read_text(encoding="utf-8", errors="replace")
                        self.assertIn(symbol, body, f"{ident}: symbol {symbol} not in {path.name}")

    def test_enforced_claims_cite_a_real_test(self):
        for ident, row in self.mapped.items():
            if row["status"] != ENFORCED:
                continue
            refs = [r for r in backticked(row["evidence"]) if r.startswith("tests/")]
            with self.subTest(claim=ident):
                self.assertTrue(refs, f"{ident}: enforced but cites no test file")
                for ref in refs:
                    self.assertTrue((REPO / ref).exists(), f"{ident}: test file missing: {ref}")

    def test_enforced_claims_do_not_rest_on_prompt_text(self):
        for ident, row in self.mapped.items():
            if row["status"] != ENFORCED:
                continue
            with self.subTest(claim=ident):
                for ref in backticked(row["mechanism"]):
                    self.assertFalse(
                        ref.startswith("prompts/"),
                        f"{ident}: a prompt file is not an enforcing mechanism ({ref})",
                    )

    def test_convention_only_claims_claim_no_mechanism(self):
        for ident, row in self.mapped.items():
            if row["status"] != CONVENTION:
                continue
            with self.subTest(claim=ident):
                self.assertEqual(
                    backticked(row["mechanism"]), [],
                    f"{ident}: convention-only row must not name a mechanism",
                )


if __name__ == "__main__":
    unittest.main()
