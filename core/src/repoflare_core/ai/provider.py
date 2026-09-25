"""BobProvider: the interface RepoFlare's semantic-reasoning layer is built against.

Naming note: unrelated to IBM Bob IDE — see docs/DECISIONS.md ADR-004 for the naming
collision explanation. This interface is deliberately minimal (a single prompt -> text
completion) because assembling a prompt from an AIContextPackage (changed symbols, graph
paths, relevant tests) is retrieval/ContextRetriever's job — not yet built, see AGENTS.md —
not this layer's. Keeping the boundary here narrow is what makes providers swappable.
"""

from __future__ import annotations

from typing import Protocol


class BobProviderError(RuntimeError):
    """Raised when a provider call fails (network, auth, rate limit, malformed response).
    Never swallowed silently — see docs/ARCHITECTURE.md's failure-handling boundaries."""


class BobProvider(Protocol):
    def complete(self, prompt: str) -> str:
        """Send prompt, return the model's text completion. Raises BobProviderError on
        any failure."""
        ...
