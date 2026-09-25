from repoflare_core.domain.entities import ImpactCategory, ImpactResult
from repoflare_core.export.html import render_html
from repoflare_core.service import ImpactSummary, NodeSummary, StatusResult


def test_overview_only_report_has_no_impact_section() -> None:
    status = StatusResult(snapshot_id="abc123", node_count=5, edge_count=3)

    html = render_html("/repo", status, impact=None, impact_refs=None)

    assert "abc123" in html
    assert "Nodes" in html
    assert "Changed files" not in html


def test_not_yet_analyzed_shows_placeholder() -> None:
    status = StatusResult(snapshot_id=None, node_count=0, edge_count=0)

    html = render_html("/repo", status)

    assert "not yet analyzed" in html


def test_impact_section_renders_category_badges() -> None:
    status = StatusResult(snapshot_id="abc123", node_count=5, edge_count=3)
    impact = ImpactSummary(
        changed_files=["a.py"],
        results=[
            ImpactResult(
                impact_id="i1",
                change_set_id="cs1",
                category=ImpactCategory.DIRECT,
                affected_node_ids=["n1"],
                provenance="graph_traversal",
            )
        ],
        node_summaries={"n1": NodeSummary(node_id="n1", label="helper", file_path="b.py")},
    )

    html = render_html("/repo", status, impact, ("HEAD~1", "HEAD"))

    assert "badge-direct" in html
    assert "DIRECT" in html
    assert "helper" in html
    assert "b.py" in html


def test_no_changed_files_shows_empty_state() -> None:
    status = StatusResult(snapshot_id="abc123", node_count=0, edge_count=0)
    impact = ImpactSummary(changed_files=[], results=[], node_summaries={})

    html = render_html("/repo", status, impact, ("HEAD", "HEAD"))

    assert "No changed files between these refs." in html


def test_dynamic_values_are_html_escaped() -> None:
    status = StatusResult(snapshot_id="<script>alert(1)</script>", node_count=0, edge_count=0)

    html = render_html("<img src=x onerror=alert(1)>", status)

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<img src=x onerror" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


def test_impact_node_label_and_file_path_are_escaped() -> None:
    status = StatusResult(snapshot_id="abc", node_count=1, edge_count=0)
    impact = ImpactSummary(
        changed_files=["a.py"],
        results=[
            ImpactResult(
                impact_id="i1",
                change_set_id="cs1",
                category=ImpactCategory.DIRECT,
                affected_node_ids=["n1"],
                provenance="graph_traversal",
            )
        ],
        node_summaries={
            "n1": NodeSummary(node_id="n1", label="<b>evil</b>", file_path="<script>x</script>.py")
        },
    )

    html = render_html("/repo", status, impact, ("HEAD~1", "HEAD"))

    assert "<b>evil</b>" not in html
    assert "&lt;b&gt;evil&lt;/b&gt;" in html
    assert "<script>x</script>.py" not in html


def test_content_security_policy_present() -> None:
    status = StatusResult(snapshot_id=None, node_count=0, edge_count=0)

    html = render_html("/repo", status)

    assert "default-src 'none'" in html
