"""api/page.py is a pure function, but it is a real XSS boundary rather than a theoretical one:
it echoes the repository, both refs and any error notice back into HTML attributes. These
mirror the escaping tests already written for export/html.py and the VS Code webview."""

from repoflare_core.api.page import render_demo_page

_XSS = '"><script>alert(1)</script>'


def test_escapes_the_repository_echoed_into_the_form() -> None:
    html = render_demo_page(repo=_XSS)

    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_escapes_the_ref_inputs() -> None:
    html = render_demo_page(from_ref=_XSS, to_ref=_XSS)

    assert "<script>" not in html


def test_escapes_the_notice() -> None:
    html = render_demo_page(notice=_XSS)

    assert "<script>" not in html


def test_an_attribute_cannot_be_broken_out_of() -> None:
    html = render_demo_page(repo='" onmouseover="alert(1)')

    assert 'onmouseover="alert(1)"' not in html
    assert "&quot;" in html


def test_form_submits_to_the_report_route_as_a_get() -> None:
    html = render_demo_page()

    assert 'action="/report"' in html
    assert 'method="get"' in html


def test_csp_disallows_scripts() -> None:
    html = render_demo_page()

    assert "Content-Security-Policy" in html
    assert "default-src 'none'" in html
    assert "<script" not in html.lower()


def test_has_no_external_assets() -> None:
    """The page must render identically with no network — the same constraint export/html.py
    and the webview are held to."""
    html = render_demo_page()

    for marker in ('src="http', 'href="http', "<iframe", "<link", "@import"):
        assert marker not in html


def test_documents_the_json_endpoints() -> None:
    html = render_demo_page()

    assert "/api/v1/analyze" in html
    assert "/api/v1/impact" in html
    assert "/healthz" in html


def test_form_carries_the_current_values_as_defaults() -> None:
    html = render_demo_page(repo="pallets/flask", from_ref="HEAD~1", to_ref="HEAD")

    assert 'value="pallets/flask"' in html
    assert 'value="HEAD~1"' in html
    assert 'value="HEAD"' in html
