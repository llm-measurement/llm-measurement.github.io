# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Build the small static documentation site using only the standard library."""
import html
import json
from pathlib import Path
import shutil
from string import Template

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://llm-measurement.github.io/"
PAGES = json.loads((ROOT / "pages.json").read_text())
FRAME = Template('''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>$title | LLM Measurement</title><meta name="description" content="$description">
<link rel="canonical" href="$canonical"><link rel="stylesheet" href="assets/site.css">
<meta property="og:title" content="$title"><meta property="og:description" content="$description">
<meta property="og:type" content="article"><meta property="og:url" content="$canonical">
</head><body><a class="skip" href="#main">Skip to content</a>
<header><a class="brand" href="index.html">LLM Measurement</a><a href="https://github.com/llm-measurement">GitHub</a></header>
<div class="layout"><nav aria-label="Guides">$nav</nav><main id="main"><h1>$title</h1>$body</main></div>
<footer>Local tools. Open source. <a href="https://github.com/llm-measurement/fleetdiff">fleetdiff</a> · <a href="https://github.com/llm-measurement/otelcol-genai-sketches">Collector</a> · <a href="https://github.com/llm-measurement/llm-sketchkit">llm-sketchkit</a><br>
<a href="llms.txt">Text index</a> · <a href="sitemap.xml">Sitemap</a></footer></body></html>
''')


def build():
    out = ROOT / "docs"
    out.mkdir(exist_ok=True)
    shutil.copytree(ROOT / "assets", out / "assets", dirs_exist_ok=True)
    names = ["All questions", "Prometheus cardinality", "A token spike", "Unusual windows", "Distinct users"]
    for page in PAGES:
        nav = "".join(
            f'<a href="{p["slug"]}.html"' + (' aria-current="page"' if p == page else '') + f'>{label}</a>'
            for p, label in zip(PAGES, names)
        )
        rendered = FRAME.substitute(
            title=html.escape(page["title"]), description=html.escape(page["description"], quote=True),
            canonical=BASE + ("" if page["slug"] == "index" else page["slug"] + ".html"),
            nav=nav, body=(ROOT / "pages" / (page["slug"] + ".html")).read_text(),
        )
        (out / (page["slug"] + ".html")).write_text(rendered)
    urls = [BASE + ("" if p["slug"] == "index" else p["slug"] + ".html") for p in PAGES]
    (out / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + ''.join(f'<url><loc>{u}</loc></url>\n' for u in urls) + '</urlset>\n')
    (out / "llms.txt").write_text("# LLM Measurement\n\n> Local open-source tools for LLM usage investigations and measurement.\n\n## Guides\n\n" + ''.join(f'- [{p["title"]}]({u}): {p["description"]}\n' for p, u in zip(PAGES[1:], urls[1:])) + "\n## Released tools used in these examples\n\n- fleetdiff v0.5.0\n- llm-sketchkit v0.2.2\n- Collector configuration guidance: v0.3.1\n\nAll numerical examples use synthetic inputs. See each page for its limits and sources.\n")
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {BASE}sitemap.xml\n")
    (out / ".nojekyll").write_text("")


if __name__ == "__main__":
    build()
