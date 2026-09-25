"""Pure domain entities and value objects. No I/O, no third-party dependencies beyond stdlib.

Mirrors the schema in docs/GRAPH_MODEL.md and docs/DATA_MODEL.md 1:1, so the storage layer
(repoflare_core.graph) can round-trip these objects without a separate mapping/ORM layer.
"""

from repoflare_core.domain.entities import (
    AIContextPackage,
    AnalysisJob,
    AnalysisJobStatus,
    ChangeSet,
    Edge,
    EdgeType,
    ImpactCategory,
    ImpactResult,
    Node,
    NodeKind,
    Repository,
    Snapshot,
    VerificationResult,
)

__all__ = [
    "AIContextPackage",
    "AnalysisJob",
    "AnalysisJobStatus",
    "ChangeSet",
    "Edge",
    "EdgeType",
    "ImpactCategory",
    "ImpactResult",
    "Node",
    "NodeKind",
    "Repository",
    "Snapshot",
    "VerificationResult",
]
