# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Build the small static documentation site using only the standard library."""
import html
import json
from datetime import datetime
from pathlib import Path
import re
import shutil
from string import Template
import xml.etree.ElementTree as ET
import summary_evidence

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://llm-measurement.github.io/"
PAGES = json.loads((ROOT / "pages.json").read_text())
STATIC_ROOT_FILES = ("googled831a5845f87080c.html", "1fcb3191597647daa6285898dc9171b1.txt")
NAV_LABELS = dict(zip(
    ("index", "token-spike", "tokenmaxxing", "litellm-spend", "langfuse-spend", "agent-spend",
     "row-coverage", "routing", "what-if", "session-budget", "cache-check", "cardinality",
     "anomalies", "traces-usage", "distinct-users", "summaries", "security"),
    ("All guides", "A token spike", "Tokenmaxxing", "LiteLLM spend", "Langfuse costs", "Agent spend",
     "Row coverage", "Routing audit", "Model what-if", "Session budget", "Cache check", "Per-user metrics",
     "Unusual windows", "Trace check", "Distinct users", "Why summaries", "Security review"),
))
CONTACT = '''<a href="mailto:evijay+fleetdiff@gmail.com" data-contact="email">evijay+fleetdiff@gmail.com</a> ·
<a href="https://github.com/llm-measurement/fleetdiff/discussions/categories/q-a" data-contact="questions">Questions</a> ·
<a href="https://github.com/llm-measurement/fleetdiff/discussions/categories/show-and-tell" data-contact="show-and-tell">Ran it on your data? Tell us what it found</a> ·
<a href="https://github.com/llm-measurement/fleetdiff/security/advisories/new">Security issues (private)</a>'''
FRAME = Template('''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>$document_title</title><meta name="description" content="$description">
<link rel="canonical" href="$canonical"><link rel="stylesheet" href="assets/site.css">
<link rel="icon" href="assets/favicon.svg" type="image/svg+xml">
<link rel="icon" href="assets/favicon-32.png" sizes="32x32" type="image/png">
<link rel="apple-touch-icon" href="assets/apple-touch-icon.png">
$metadata
<!-- Privacy-friendly analytics by Plausible -->
<script async src="https://plausible.io/js/pa-XxJJVAxJMHffrJ0MqBrpF.js"></script>
<script>
  window.plausible=window.plausible||function(){(plausible.q=plausible.q||[]).push(arguments)},plausible.init=plausible.init||function(i){plausible.o=i||{}};
  plausible.init()
</script>
<script defer src="assets/site.js"></script>
</head><body><a class="skip" href="#main">Skip to content</a>
<header><a class="brand" href="index.html">$header_mark LLM Measurement</a><a href="https://github.com/llm-measurement">GitHub</a></header>
<div class="layout"><div class="desktop-guides"><nav aria-label="Guides">$nav</nav></div><details class="mobile-guides"><summary>Guides</summary><nav aria-label="Guides">$nav</nav></details><main id="main"><h1>$title</h1>$body$guide_contact</main></div>
<footer>Local tools. Open source. <a href="https://github.com/llm-measurement/fleetdiff">fleetdiff</a> · <a href="https://github.com/llm-measurement/otelcol-genai-sketches">Collector</a> · <a href="https://github.com/llm-measurement/llm-sketchkit">llm-sketchkit</a><br>
$measurement_link<a href="llms.txt">Text index</a> · <a href="sitemap.xml">Sitemap</a> · <a href="security.html#verify-fleetdiff">Manual release verification</a><br>
<p class="contact-links">$contact</p>
Privacy-friendly analytics by <a href="https://plausible.io/data-policy">Plausible</a>: no cookies, no personal data</footer></body></html>
''')


def canonical(page):
    return BASE + ("" if page["slug"] == "index" else page["slug"] + ".html")


def article_date(value):
    if not isinstance(value, str) or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
            r"(?:\.[0-9]+)?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])", value):
        raise ValueError("article dates require ISO8601 timestamps with a timezone")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("invalid ISO8601 article date") from None


def article_head(page, *, published=None, modified=None):
    published = page.get("published") if published is None else published
    modified = page.get("modified") if modified is None else modified
    if article_date(modified) < article_date(published):
        raise ValueError("article modified date precedes published date")
    title = html.escape(page.get("document_title", page["title"] + " | LLM Measurement"))
    description = html.escape(page["description"], quote=True)
    url = html.escape(canonical(page), quote=True)
    data = {
        "@context": "https://schema.org", "@type": "BlogPosting",
        "headline": page["title"], "description": page["description"],
        "datePublished": published, "dateModified": modified,
        "author": {"@type": "Person", "name": "Vijay"},
        "publisher": {"@type": "Organization", "name": "LLM Measurement"},
        "mainEntityOfPage": {"@type": "WebPage", "@id": canonical(page)},
    }
    # JSON strings must not terminate their containing HTML script element.
    structured = json.dumps(data, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return (f'<meta property="og:title" content="{title}"><meta property="og:description" content="{description}">\n'
            f'<meta property="og:type" content="article"><meta property="og:url" content="{url}">\n'
            '<meta property="og:site_name" content="LLM Measurement">\n'
            f'<meta property="article:published_time" content="{html.escape(published, quote=True)}">'
            f'<meta property="article:modified_time" content="{html.escape(modified, quote=True)}">\n'
            f'<meta name="twitter:card" content="summary"><meta name="twitter:title" content="{title}">\n'
            f'<meta name="twitter:description" content="{description}"><meta name="twitter:url" content="{url}">\n'
            f'<script type="application/ld+json">{structured}</script>')


def metadata(page):
    if page.get("article") is True:
        return article_head(page)
    return (f'<meta property="og:title" content="{html.escape(page["title"])}">'
            f'<meta property="og:description" content="{html.escape(page["description"], quote=True)}">\n'
            f'<meta property="og:type" content="article"><meta property="og:url" content="{canonical(page)}">')


def navigation(page, pages):
    current = "studies" if page.get("article") is True else page["slug"]
    ordered = [item for item in pages if item["slug"] != "studies"]
    position = next((i + 1 for i, item in enumerate(ordered) if item["slug"] == "index"), len(ordered))
    ordered[position:position] = [item for item in pages if item["slug"] == "studies"]
    links = []
    for item in ordered:
        if item.get("navigation") is False:
            continue
        label = item.get("nav_label", NAV_LABELS.get(item["slug"]))
        if label is None:
            raise ValueError("every navigation page needs a navigation label")
        links.append(f'<a href="{html.escape(item["slug"], quote=True)}.html"' +
                     (' aria-current="page"' if item["slug"] == current else '') +
                     f'>{html.escape(label)}</a>')
    return "".join(links)


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
    for page in PAGES:
        rendered = FRAME.substitute(
            contact=CONTACT,
            guide_contact=('<p class="guide-contact">' + CONTACT + '</p>'
                           if page["slug"] != "index" and not page.get("kind") and not page.get("article") else ""),
            measurement_link=('<a href="summaries.html#measurement-notes">Measurement notes</a> · '
                              if page["slug"] == "index" or page.get("kind") in {"evidence", "reference", "study"} else ""),
            header_mark=ET.tostring(header_mark, encoding="unicode"),
            document_title=html.escape(page.get("document_title", page["title"] + " | LLM Measurement")),
            title=html.escape(page["title"]), description=html.escape(page["description"], quote=True),
            canonical=canonical(page), metadata=metadata(page),
            nav=navigation(page, PAGES), body=(summary_evidence.render(ROOT) if page["slug"] == "summaries"
                           else (ROOT / "pages" / (page["slug"] + ".html")).read_text()),
        )
        (out / (page["slug"] + ".html")).write_text(rendered)
    urls = [canonical(p) for p in PAGES]
    (out / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + ''.join(f'<url><loc>{u}</loc></url>\n' for u in urls) + '</urlset>\n')
    studies = [p for p in PAGES[1:] if p.get("kind") == "study" or p["slug"] == "studies"]
    guides = [p for p in PAGES[1:] if p not in studies]
    listing = lambda pages: ''.join(f'- [{p["title"]}]({canonical(p)}): {p["description"]}\n' for p in pages)
    (out / "llms.txt").write_text("# LLM Measurement\n\n> Local open-source tools for LLM usage investigations and measurement.\n\n## Guides\n\n" + listing(guides) + ("\n## Studies\n\n" + listing(studies) if studies else "") + "\n## Released tools used in these examples\n\n- fleetdiff v0.14.1 in all fleetdiff guides; v0.15.0 in the Haiku and Sonnet study\n- llm-sketchkit v0.4.0 on the home page; v0.3.0 in the existing Python guides\n- Collector configuration guidance: v0.7.4; Helm chart 0.7.5\n\nCommand guides use synthetic inputs. The summaries evidence page separates released coding-agent records from synthetic scale workloads and pins its experimental source. See each page for its methods and limits.\n")
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {BASE}sitemap.xml\n")
    (out / ".nojekyll").write_text("")


if __name__ == "__main__":
    build()
