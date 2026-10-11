# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Build the small static documentation site using only the standard library."""
import html
import json
from pathlib import Path
import shutil
from string import Template
import xml.etree.ElementTree as ET
import summary_evidence

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://llm-measurement.github.io/"
PAGES = json.loads((ROOT / "pages.json").read_text())
STATIC_ROOT_FILES = ("googled831a5845f87080c.html",)
FRAME = Template('''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>$document_title</title><meta name="description" content="$description">
<link rel="canonical" href="$canonical"><link rel="stylesheet" href="assets/site.css">
<link rel="icon" href="assets/favicon.svg" type="image/svg+xml">
<link rel="icon" href="assets/favicon-32.png" sizes="32x32" type="image/png">
<link rel="apple-touch-icon" href="assets/apple-touch-icon.png">
<meta property="og:title" content="$title"><meta property="og:description" content="$description">
<meta property="og:type" content="article"><meta property="og:url" content="$canonical">
<!-- Privacy-friendly analytics by Plausible -->
<script async src="https://plausible.io/js/pa-XxJJVAxJMHffrJ0MqBrpF.js"></script>
<script>
  window.plausible=window.plausible||function(){(plausible.q=plausible.q||[]).push(arguments)},plausible.init=plausible.init||function(i){plausible.o=i||{}};
  plausible.init()
</script>
</head><body><a class="skip" href="#main">Skip to content</a>
<header><a class="brand" href="index.html">$header_mark LLM Measurement</a><a href="https://github.com/llm-measurement">GitHub</a></header>
<div class="layout"><nav aria-label="Guides">$nav</nav><main id="main"><h1>$title</h1>$body</main></div>
<footer>Local tools. Open source. <a href="https://github.com/llm-measurement/fleetdiff">fleetdiff</a> · <a href="https://github.com/llm-measurement/otelcol-genai-sketches">Collector</a> · <a href="https://github.com/llm-measurement/llm-sketchkit">llm-sketchkit</a><br>
$measurement_link<a href="llms.txt">Text index</a> · <a href="sitemap.xml">Sitemap</a></footer></body></html>
''')


def build():
    out = ROOT / "docs"
    out.mkdir(exist_ok=True)
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    header_mark = ET.parse(ROOT / "assets/header-mark.svg").getroot()
    header_mark.attrib.update({"aria-hidden": "true", "width": "20", "height": "20"})
    (ROOT / "assets/summary-evidence/claims.json").write_text(
        json.dumps(summary_evidence.claims(ROOT), indent=2, sort_keys=True) + "\n")
    # Experimental inputs and generated evidence must never become site assets.
    excluded = shutil.ignore_patterns("data", "collector", "evidence", "analyst-inputs",
        "analyst-output", "venv", "wheels", "go-build", "go-mod", "__pycache__",
        "replay", "scale", "DATA_AUDIT.md", "policy.sb", ".gitignore")
    if (out / "assets").exists():
        shutil.rmtree(out / "assets")
    shutil.copytree(ROOT / "assets", out / "assets", ignore=excluded)
    for name in STATIC_ROOT_FILES:
        shutil.copyfile(ROOT / name, out / name)
    names = ["All guides", "A token spike", "Tokenmaxxing", "LiteLLM spend", "Cache check", "Per-user metrics", "Unusual windows", "Trace check", "Distinct users", "Why summaries"]
    for page in PAGES:
        nav = "".join(
            f'<a href="{p["slug"]}.html"' + (' aria-current="page"' if p == page else '') + f'>{label}</a>'
            for p, label in zip(PAGES, names)
        )
        rendered = FRAME.substitute(
            measurement_link=('<a href="summaries.html#measurement-notes">Measurement notes</a> · '
                              if page["slug"] == "index" or page.get("kind") == "evidence" else ""),
            header_mark=ET.tostring(header_mark, encoding="unicode"),
            document_title=html.escape(page.get("document_title", page["title"] + " | LLM Measurement")),
            title=html.escape(page["title"]), description=html.escape(page["description"], quote=True),
            canonical=BASE + ("" if page["slug"] == "index" else page["slug"] + ".html"),
            nav=nav, body=(summary_evidence.render(ROOT) if page["slug"] == "summaries"
                           else (ROOT / "pages" / (page["slug"] + ".html")).read_text()),
        )
        (out / (page["slug"] + ".html")).write_text(rendered)
    urls = [BASE + ("" if p["slug"] == "index" else p["slug"] + ".html") for p in PAGES]
    (out / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + ''.join(f'<url><loc>{u}</loc></url>\n' for u in urls) + '</urlset>\n')
    (out / "llms.txt").write_text("# LLM Measurement\n\n> Local open-source tools for LLM usage investigations and measurement.\n\n## Guides\n\n" + ''.join(f'- [{p["title"]}]({u}): {p["description"]}\n' for p, u in zip(PAGES[1:], urls[1:])) + "\n## Released tools used in these examples\n\n- fleetdiff v0.7.0 (LiteLLM spend, cache check and trace check); v0.5.0 (summary and configuration guides)\n- llm-sketchkit v0.2.2\n- Collector configuration guidance: v0.3.1\n\nCommand guides use synthetic inputs. The summaries evidence page separates released coding-agent records from synthetic scale workloads and pins its experimental source. See each page for its methods and limits.\n")
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {BASE}sitemap.xml\n")
    (out / ".nojekyll").write_text("")


if __name__ == "__main__":
    build()
