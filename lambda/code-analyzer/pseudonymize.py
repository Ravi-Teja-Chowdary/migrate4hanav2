"""
pseudonymize.py - Reversible sensitive-token masking for Claude round-trips
==============================================================================
The AI fail-safe sends an ABAP fragment to Claude (via the Anthropic API) for
a localized syntax fix. Because the payload now leaves AWS over the public
internet, we must not let raw passwords, customer hostnames, employee emails,
or IPs leave the process unmasked - corporate InfoSec policies require that
the model **sees only surrogates**, the model preserves them verbatim in its
fix, and the post-processor substitutes the originals back. That is exactly
what this module does.

Approach: deterministic pseudonymization. For every distinct sensitive value we
issue a stable surrogate that is **both** a valid ABAP identifier (letters / digits
/ underscores, starts with a letter) **and** a valid string literal — so the
surrogate parses whether the original sat inside a quoted literal, a function
argument, or a comment. We then walk the mapping (longest surrogate first, to
avoid prefix collisions) to restore the originals on the returned remediation.

What gets masked (categorized regex):
  * EMAIL    — admin@corp.com -> M4H_EMAIL_001
  * IPV4     — 10.0.6.214      -> M4H_IP_001
  * URL      — https://x.y/z   -> M4H_URL_001
  * PASSWORD — passwd = 'pw'   -> passwd = 'M4H_PASSWORD_001'  (heuristic)
  * EXPLICIT — caller-supplied list (e.g. customer hostnames / Z-tables)

A round-trip self-test confirms unmask(mask(x)) == x for every category.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional


# ── regex patterns: anchored on word/string boundaries so we don't catch fragments ──
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_URL = re.compile(r"https?://[^\s'\"<>`]+")

# Password literal — covers BOTH ``key = 'val'`` (Python/JSON-style) AND ABAP
# ``DATA passwd TYPE string VALUE 'val'.`` Statement-scoped (the [^.\n] window
# stops at the next ABAP statement period, preventing false captures across stmts).
_PASSWORD_KV = re.compile(
    r"\b(?P<key>passwd|password|secret|token|api[_-]?key|client[_-]?secret|bearer)\b"
    r"[^.\n]{0,200}?(?P<quote>['\"])(?P<val>[^'\"\n]{1,256})(?P=quote)",
    re.IGNORECASE)


@dataclass
class MaskReport:
    counts: dict = field(default_factory=dict)        # category -> count of unique originals
    mappings: dict = field(default_factory=dict)      # surrogate -> original (so audit can recover)

    def to_dict(self) -> dict:
        return {"counts": dict(self.counts), "mapping_size": len(self.mappings)}


class Pseudonymizer:
    """Deterministic, reversible masker. One instance ⇒ one mapping; use a fresh
    instance per round-trip so surrogates don't leak across requests."""

    SURROGATE = "M4H"           # prefix kept short — keeps masked code compact

    def __init__(self, explicit: Optional[Iterable[str]] = None):
        # Forward (original -> surrogate) so identical originals share a surrogate;
        # reverse (surrogate -> original) for fast longest-first unmasking.
        self._fwd: dict = {}
        self._rev: dict = {}
        self._counters: dict = {}    # category -> next index
        self._explicit = sorted({e for e in (explicit or []) if e}, key=len, reverse=True)
        self.report = MaskReport()

    # ── public API ──────────────────────────────────────────────────────────
    def mask(self, text: str) -> str:
        """Return ``text`` with all sensitive tokens replaced by surrogates,
        populating the mapping. Idempotent for identical originals."""
        if not text:
            return text
        # Mask EXPLICIT first so a hostname like 'corp.com' inside an email is
        # handled coherently (email category later sees the already-masked text
        # and skips it — we re-scan after each pass so masks don't double-fire).
        for literal in self._explicit:
            text = self._replace_all(text, literal, "EXPLICIT")
        # PASSWORD next — it has a structured capture so we only mask the value
        text = _PASSWORD_KV.sub(lambda m: self._mask_password(m), text)
        text = _URL.sub(lambda m: self._issue(m.group(0), "URL"), text)
        text = _EMAIL.sub(lambda m: self._issue(m.group(0), "EMAIL"), text)
        text = _IPV4.sub(lambda m: self._issue(m.group(0), "IPV4"), text)
        return text

    def unmask(self, text: str) -> str:
        """Restore every surrogate back to its original. Walks longest first so
        ``M4H_IP_1`` does not corrupt ``M4H_IP_10``."""
        if not text or not self._rev:
            return text
        # Sort by length descending — prevents prefix-collision corruption.
        for surrogate in sorted(self._rev, key=len, reverse=True):
            text = text.replace(surrogate, self._rev[surrogate])
        return text

    # ── internals ────────────────────────────────────────────────────────────
    def _issue(self, original: str, category: str) -> str:
        if original in self._fwd:
            return self._fwd[original]
        n = self._counters.get(category, 0) + 1
        self._counters[category] = n
        # Zero-padded 3 digits is plenty for typical fragments; rolls naturally.
        surrogate = f"{self.SURROGATE}_{category}_{n:03d}"
        self._fwd[original] = surrogate
        self._rev[surrogate] = original
        self.report.counts[category] = self.report.counts.get(category, 0) + 1
        self.report.mappings[surrogate] = original
        return surrogate

    def _mask_password(self, m: re.Match) -> str:
        # Replace only the captured value span with the surrogate; leave the rest
        # of the matched statement (DATA / TYPE / VALUE / quotes) byte-identical.
        surrogate = self._issue(m.group("val"), "PASSWORD")
        full = m.group(0)
        v0 = m.start("val") - m.start()
        v1 = m.end("val") - m.start()
        return full[:v0] + surrogate + full[v1:]

    def _replace_all(self, text: str, literal: str, category: str) -> str:
        surrogate = self._issue(literal, category)
        return text.replace(literal, surrogate)


# ════════════════════════════════════════════════════════════════════════════
#  Self-test — round-trip on every category + cross-category sample
# ════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 72)
    print("pseudonymize — self-test (mask/unmask round-trip)")
    print("=" * 72)

    sample = (
        "REPORT zsensitive.\n"
        "DATA passwd TYPE string VALUE 'topSecret123!'.\n"
        "DATA api_key TYPE string VALUE 'abcDEF-0987'.\n"
        "* contact admin@corp.example for the run; cc devs@corp.example\n"
        "CALL FUNCTION 'Z_HTTP_GET' EXPORTING url = 'https://api.corp.example/data?x=1'.\n"
        "DATA host TYPE string VALUE '10.0.6.214'.\n"
        "DATA dr TYPE string VALUE '192.168.100.129'.\n"
        "* customer host hint: vhcals4hci.dummy.nodomain\n"
    )

    ps = Pseudonymizer(explicit=["vhcals4hci.dummy.nodomain"])
    masked = ps.mask(sample)
    print("\n--- masked (what Bedrock sees) ---")
    print(masked)
    print(f"\nmapping: {ps.report.to_dict()}")

    # Bedrock returns the same code with a syntax fix. Simulate by inserting a
    # cosmetic edit. The surrogates pass through verbatim.
    fake_bedrock = masked.replace("REPORT zsensitive.", "REPORT zsensitive. \" fixed")
    restored = ps.unmask(fake_bedrock)
    print("\n--- restored (what we put back in the run) ---")
    print(restored)

    # Round-trip: ignoring Bedrock's cosmetic edit, the rest is byte-identical
    expected = sample.replace("REPORT zsensitive.", "REPORT zsensitive. \" fixed")
    assert restored == expected, "round-trip mismatch"

    # No raw secrets in the masked payload
    for leak in ("topSecret123!", "abcDEF-0987", "admin@corp.example", "10.0.6.214",
                 "vhcals4hci.dummy.nodomain", "https://api.corp.example"):
        assert leak not in masked, f"leak: {leak!r} appears unmasked"

    # Idempotent: same email twice gets the SAME surrogate
    assert masked.count("M4H_EMAIL_") >= 2 and \
        len({tok for tok in re.findall(r"M4H_EMAIL_\d+", masked)}) == 2  # two distinct emails
    # And the same email appearing twice would share a surrogate (test that)
    text2 = "x@y.com and again x@y.com"
    ps2 = Pseudonymizer()
    m2 = ps2.mask(text2)
    assert m2.count("M4H_EMAIL_001") == 2, f"identical original must reuse surrogate: {m2}"

    print("\nOK — mask hides every category; unmask is a perfect round-trip; same "
          "original always gets the same surrogate; no leakage in the payload.")
