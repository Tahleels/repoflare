"""Static-output rendering — currently just HTML (export/html.py). Kept as its own package
(not folded into cli/) since "render structured data as a page" is a distinct concern from
"parse CLI args and print," and a JSON/Markdown exporter would land here too."""

from repoflare_core.export.html import render_html

__all__ = ["render_html"]
