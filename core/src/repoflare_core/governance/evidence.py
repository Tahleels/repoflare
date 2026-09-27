"""EvidenceBuilder: a small helper that makes it easy for every check to build the
`evidence` list on a GovernanceFinding in a consistent shape.

Each evidence entry is a plain dict so it serialises to JSON without extra machinery — the
goal is a stable, inspectable audit trail, not a rich object hierarchy.
"""

from __future__ import annotations

from typing import Any


class EvidenceBuilder:
    """Accumulates evidence items and produces the final list.

    Usage::

        eb = EvidenceBuilder()
        eb.add("pr_number", 142, note="open for 31 days")
        eb.add("last_activity", "2024-01-01T00:00:00Z")
        finding_evidence = eb.build()
    """

    def __init__(self) -> None:
        self._items: list[dict[str, Any]] = []

    def add(self, key: str, value: Any, *, note: str | None = None) -> EvidenceBuilder:
        """Append one evidence atom.

        Args:
            key:   A short, machine-readable label (e.g. ``"pr_number"``, ``"file"``,
                   ``"pattern"``).
            value: The raw evidence value (string, int, list, …).
            note:  An optional human-readable annotation explaining why this matters.

        Returns:
            ``self`` so calls can be chained.
        """
        item: dict[str, Any] = {"key": key, "value": value}
        if note is not None:
            item["note"] = note
        self._items.append(item)
        return self

    def add_many(self, items: list[dict[str, Any]]) -> EvidenceBuilder:
        """Bulk-append pre-built evidence dicts (e.g. from a list comprehension)."""
        self._items.extend(items)
        return self

    def build(self) -> list[dict[str, Any]]:
        """Return a *copy* of the accumulated evidence list."""
        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)
