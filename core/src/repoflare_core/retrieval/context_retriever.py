"""ContextRetriever: turns a ChangeSet + its ImpactResults into a bounded AIContextPackage —
the targeted slice of the repository handed to a BobProvider, never the whole repo (see
docs/ARCHITECTURE.md §3 and CLAUDE_CODE_MASTER_PROMPT.md §10: "never send the entire
repository to an LLM for every change").

`relevant_tests` is populated via TESTED_BY edges (see parsing/test_resolver.py) for the
changed and directly-dependent nodes — a naming-convention heuristic, not real coverage
analysis. It stays empty for nodes with no matching TESTED_BY edge, which is correct (not a
gap) when no such test exists or was detected.
"""

from __future__ import annotations

from pathlib import Path

from repoflare_core.domain.entities import (
    AIContextPackage,
    ChangeSet,
    EdgeType,
    ImpactCategory,
    ImpactResult,
    Node,
)
from repoflare_core.domain.ids import stable_id
from repoflare_core.graph.store import GraphStore
from repoflare_core.graph.traversal import GraphTraversalService

_MAX_SNIPPET_NODES = 10
"""Bounds how many symbols get their source text pulled into the context package — the
whole point of this module is staying targeted, not exhaustive."""


class ContextRetriever:
    def __init__(self, store: GraphStore, traversal: GraphTraversalService) -> None:
        self._store = store
        self._traversal = traversal

    def build_context(
        self,
        change_set: ChangeSet,
        impact_results: list[ImpactResult],
        repository_root: Path,
    ) -> AIContextPackage:
        changed_node_ids = sorted(self._changed_node_ids(change_set))
        direct_dependent_ids = self._node_ids_for_category(impact_results, ImpactCategory.DIRECT)

        graph_paths = self._graph_paths(
            change_set.snapshot_to_id, changed_node_ids, direct_dependent_ids
        )

        snippet_candidates = (changed_node_ids + direct_dependent_ids)[:_MAX_SNIPPET_NODES]
        snippets = self._snippets(snippet_candidates, repository_root)
        relevant_tests = self._relevant_tests(
            change_set.snapshot_to_id, changed_node_ids + direct_dependent_ids
        )

        return AIContextPackage(
            context_id=stable_id(change_set.change_set_id, "context"),
            change_set_id=change_set.change_set_id,
            snippets=snippets,
            graph_paths=graph_paths,
            direct_dependents=direct_dependent_ids,
            relevant_tests=relevant_tests,
        )

    def _changed_node_ids(self, change_set: ChangeSet) -> set[str]:
        return {
            node.node_id
            for file_path in change_set.changed_files
            for node in self._store.nodes_for_file(change_set.snapshot_to_id, file_path)
        }

    @staticmethod
    def _node_ids_for_category(
        impact_results: list[ImpactResult], category: ImpactCategory
    ) -> list[str]:
        return next((r.affected_node_ids for r in impact_results if r.category == category), [])

    def _graph_paths(
        self, snapshot_id: str, changed_node_ids: list[str], direct_dependent_ids: list[str]
    ) -> list[list[str]]:
        paths: list[list[str]] = []
        for dependent_id in direct_dependent_ids:
            for changed_id in changed_node_ids:
                path = self._traversal.shortest_reverse_path(
                    snapshot_id, changed_id, dependent_id, max_depth=1
                )
                if path is not None:
                    paths.append(path)
                    break
        return paths

    def _relevant_tests(self, snapshot_id: str, node_ids: list[str]) -> list[str]:
        test_ids: set[str] = set()
        for node_id in node_ids:
            test_ids.update(
                self._traversal.direct_dependents(
                    snapshot_id, node_id, edge_type=EdgeType.TESTED_BY
                )
            )
        return sorted(test_ids)

    def _snippets(self, node_ids: list[str], repository_root: Path) -> dict[str, str]:
        # Keyed by file path (per AIContextPackage.snippets' contract), so two symbols from
        # the same file must be appended, not overwritten — losing one silently would defeat
        # the point of a *targeted* context package.
        snippets: dict[str, str] = {}
        for node_id in node_ids:
            node = self._store.get_node(node_id)
            if node is None:
                continue
            snippet = self._read_snippet(node, repository_root)
            if snippet is None:
                continue
            key = node.file_path or node_id
            snippets[key] = f"{snippets[key]}\n\n{snippet}" if key in snippets else snippet
        return snippets

    @staticmethod
    def _read_snippet(node: Node, repository_root: Path) -> str | None:
        if node.file_path is None or node.start_line is None or node.end_line is None:
            return None
        try:
            lines = (repository_root / node.file_path).read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        return "\n".join(lines[node.start_line - 1 : node.end_line])
