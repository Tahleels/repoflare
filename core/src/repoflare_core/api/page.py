"""The hosted demo's landing page: a pure state-in / HTML-string-out function.

Same discipline as export/html.py and extension/src/webview.ts — every dynamic value is
escaped, there are no external assets, and the CSP allows nothing but inline styles. The form
is a plain GET form deliberately: it makes every demo run a *linkable, reproducible URL*
(a judge can be sent one), and the page needs no JavaScript at all to work.

`repo` is echoed back into an attribute here, so this function is a real XSS boundary, not a
theoretical one — see tests/test_api_page.py.
"""

from __future__ import annotations

from html import escape as _esc
from urllib.parse import quote as _quote

_EXAMPLE_REPOS: tuple[tuple[str, str], ...] = (
    ("pallets/itsdangerous", "15 files — quickest"),
    ("pallets/flask", "83 files"),
    ("pallets/click", "91 files — slowest"),
)

_STYLES = """<style>
  :root { --gap: 16px; --fg: #1e1e1e; --muted: #6a6a6a; --line: #ddd; --accent: #2b6cb0; }
  body { font-family: -apple-system, "Segoe UI", sans-serif; font-size: 15px; color: var(--fg);
         background: #fff; margin: 0; padding: 28px; line-height: 1.55; max-width: 860px; }
  h1 { font-size: 1.5em; font-weight: 650; margin: 0 0 2px; }
  h2 { font-size: 1.05em; font-weight: 650; margin: 28px 0 8px;
       border-bottom: 1px solid var(--line); padding-bottom: 4px; }
  .muted { color: var(--muted); font-size: 0.9em; }
  form { background: #fafafa; border: 1px solid var(--line); border-radius: 8px;
         padding: 16px; margin: 18px 0; }
  label { display: block; font-size: 0.82em; color: var(--muted); margin-bottom: 4px; }
  .fields { display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end; }
  .field { display: flex; flex-direction: column; }
  input { font: inherit; font-size: 0.92em; padding: 7px 9px; border: 1px solid #c9c9c9;
          border-radius: 5px; background: #fff; }
  input[name="repo"] { min-width: 260px; }
  input[name="from"], input[name="to"] { min-width: 110px; }
  button { font: inherit; font-weight: 600; font-size: 0.92em; color: #fff;
           background: var(--accent); border: 0; border-radius: 5px;
           padding: 9px 18px; cursor: pointer; }
  button:hover { background: #245b96; }
  a { color: var(--accent); }
  code { font-family: ui-monospace, Consolas, monospace; font-size: 0.88em;
         background: #f2f2f2; padding: 1px 5px; border-radius: 4px; }
  table { border-collapse: collapse; width: 100%; margin-top: 6px; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #eee;
           font-size: 0.88em; vertical-align: top; }
  th { color: var(--muted); font-weight: 650; }
  .notice { background: #fff5f5; border: 1px solid #f0b4b4; color: #8a2b2b;
            border-radius: 6px; padding: 10px 14px; margin: 16px 0; font-size: 0.9em; }
  .foot { color: #999; font-size: 0.8em; margin-top: 28px; }
</style>"""


def render_demo_page(
    *,
    repo: str = "",
    from_ref: str = "HEAD~1",
    to_ref: str = "HEAD",
    notice: str | None = None,
) -> str:
    notice_html = f'<div class="notice">{_esc(notice)}</div>' if notice else ""
    examples = "".join(
        f'<li><a href="/report?repo={_quote(slug, safe="")}'
        f'&amp;from=HEAD~1&amp;to=HEAD">{_esc(slug)}</a>'
        f' <span class="muted">{_esc(hint)}</span></li>'
        for slug, hint in _EXAMPLE_REPOS
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy"
      content="default-src 'none'; style-src 'unsafe-inline'; form-action 'self';">
<title>RepoFlare — live demo</title>
{_STYLES}
</head>
<body>
<h1>RepoFlare</h1>
<div class="muted">Repository intelligence: what does a change actually affect?</div>
{notice_html}
<form action="/report" method="get">
  <div class="fields">
    <div class="field">
      <label for="repo">Public GitHub repository</label>
      <input id="repo" name="repo" value="{_esc(repo, quote=True)}"
             placeholder="owner/name" autocomplete="off" spellcheck="false">
    </div>
    <div class="field">
      <label for="from">From ref</label>
      <input id="from" name="from" value="{_esc(from_ref, quote=True)}" autocomplete="off">
    </div>
    <div class="field">
      <label for="to">To ref</label>
      <input id="to" name="to" value="{_esc(to_ref, quote=True)}" autocomplete="off">
    </div>
    <button type="submit">Analyse impact</button>
  </div>
</form>

<p class="muted">This clones the repository shallowly, builds its symbol graph, and traverses
that graph backwards from the changed files to categorise what is affected. The traversal is
deterministic — no AI, no API key, no network calls beyond the clone itself.</p>

<h2>Try one</h2>
<p class="muted">Each request clones, parses and traverses from scratch, so response time grows
with repository size: seconds for the smallest example below, a minute or more for the largest.
Expect this free instance to be several times slower than a laptop.</p>
<ul>{examples}</ul>

<h2>JSON API</h2>
<p class="muted">Every result the demo shows is also available as JSON, so this is a real
endpoint rather than a screenshot.</p>
<table>
  <tr><th>Endpoint</th><th>Returns</th></tr>
  <tr><td><code>/api/v1/analyze?repo=owner/name</code></td>
      <td>Snapshot plus file/symbol/test/edge counts.</td></tr>
  <tr><td><code>/api/v1/impact?repo=owner/name&amp;from=REF&amp;to=REF</code></td>
      <td>Changed files and affected nodes by category.</td></tr>
  <tr><td><code>/report?repo=owner/name&amp;from=REF&amp;to=REF</code></td>
      <td>The same data as a standalone HTML report.</td></tr>
  <tr><td><code>/healthz</code></td><td>Liveness probe.</td></tr>
</table>

<div class="foot">RepoFlare's primary surfaces are the CLI and the VS Code extension; this
page is a hosted view onto the identical Python core (<code>service.py</code>), not a separate
implementation. It runs on a free instance, so the first request after an idle period may take
up to a minute to wake, and very large repositories are refused rather than half-analysed.</div>
</body>
</html>"""
