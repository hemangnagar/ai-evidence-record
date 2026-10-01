"""AI Evidence Record.

A tamper-evident ledger of what AI did to a clinical record, a gate that
quarantines every AI output until a credentialed human signs it, a rule set that
finds what an inspector would find, and a per-study AI Evidence Datasheet.

Design principle carried over from governed-data-platform: the deterministic
engine (ledger, gate, rules, scorecard) is the sole source of truth. An LLM may
be the *subject* of an event; it is never the author of the record.
"""

__version__ = "0.1.0"
