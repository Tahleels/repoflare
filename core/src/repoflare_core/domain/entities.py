"""Domain entities. See docs/DATA_MODEL.md and docs/GRAPH_MODEL.md for the schema these
mirror, and docs/DECISIONS.md ADR-002 for why nodes/edges are unified rather than one
dataclass per entity kind (File, Symbol, APIEndpoint, ...).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class NodeKind(StrEnum):
    FILE = "FILE"
    MODULE = "MODULE"
    SYMBOL = "SYMBOL"
    API_ENDPOINT = "API_ENDPOINT"
    TEST = "TEST"
    CONFIG_ITEM = "CONFIG_ITEM"
    EXTERNAL_SERVICE = "EXTERNAL_SERVICE"


class SymbolKind(StrEnum):
    """Only meaningful when Node.kind == NodeKind.SYMBOL; stored in
    Node.properties["symbol_kind"]."""

    FUNCTION = "FUNCTION"
    CLASS = "CLASS"
    METHOD = "METHOD"
    VARIABLE = "VARIABLE"
    INTERFACE = "INTERFACE"


class EdgeType(StrEnum):
    IMPORTS = "IMPORTS"
    CALLS = "CALLS"
    USES = "USES"
    INHERITS = "INHERITS"
    IMPLEMENTS = "IMPLEMENTS"
    EXPOSES = "EXPOSES"
    TESTED_BY = "TESTED_BY"
    CONFIGURED_BY = "CONFIGURED_BY"
    CONNECTS_TO = "CONNECTS_TO"
    DEPENDS_ON = "DEPENDS_ON"
    CONTAINS = "CONTAINS"


class ImpactCategory(StrEnum):
    DIRECT = "DIRECT"
    INDIRECT = "INDIRECT"
    RELATED = "RELATED"
    POSSIBLE = "POSSIBLE"


class AnalysisJobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class Repository:
    repository_id: str
    root_path: str
    name: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Snapshot:
    snapshot_id: str
    repository_id: str
    git_commit_sha: str | None
    created_at: datetime
    is_current: bool = True


@dataclass(frozen=True, slots=True)
class Node:
    node_id: str
    snapshot_id: str
    kind: NodeKind
    name: str
    qualified_name: str | None = None
    file_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    content_hash: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Edge:
    edge_id: str
    snapshot_id: str
    src_node_id: str
    dst_node_id: str
    edge_type: EdgeType
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChangeSet:
    change_set_id: str
    snapshot_to_id: str
    changed_files: list[str]
    snapshot_from_id: str | None = None


@dataclass(frozen=True, slots=True)
class ImpactResult:
    impact_id: str
    change_set_id: str
    category: ImpactCategory
    affected_node_ids: list[str]
    provenance: str
    """How this result was derived: 'graph_traversal', 'test_evidence', or 'ai_inference'."""


@dataclass(frozen=True, slots=True)
class AnalysisJob:
    job_id: str
    kind: str
    status: AnalysisJobStatus
    started_at: datetime
    finished_at: datetime | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class VerificationResult:
    verification_id: str
    job_id: str
    tests_run: list[str]
    tests_passed: list[str]
    summary: str


@dataclass(frozen=True, slots=True)
class AIContextPackage:
    """The bounded payload handed to a BobProvider. Never the whole repository — see
    docs/ARCHITECTURE.md §3 and CLAUDE_CODE_MASTER_PROMPT.md §10."""

    context_id: str
    change_set_id: str
    snippets: dict[str, str]
    """file_path -> source snippet"""
    graph_paths: list[list[str]]
    """Each inner list is a chain of node_ids representing one dependency path."""
    direct_dependents: list[str]
    relevant_tests: list[str]
