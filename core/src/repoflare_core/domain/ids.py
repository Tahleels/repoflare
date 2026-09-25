"""Deterministic id generation.

Ids are content-derived (hash of stable inputs) rather than random, so re-analyzing the same
repository state always produces the same node/edge ids. This is what makes snapshot-to-
snapshot diffing possible without an explicit id-remapping step: an unchanged symbol gets the
same id across snapshots, so "did this node change" reduces to "does this id's content_hash
differ."
"""

from __future__ import annotations

import hashlib


def stable_id(*parts: str) -> str:
    """Deterministic short id from stable string parts. Not cryptographically sensitive —
    truncated to 16 hex chars, which is ample collision resistance for a single repository's
    node/edge count."""
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]
