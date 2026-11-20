#!/usr/bin/env python3
"""Draw cheaper-ratio-chart.svg from cached-session-cost-output.json and tier-analysis-output.json.
Palette: dataviz reference slots 1 and 2, validated for light and dark surfaces."""
import json
d = json.load(open("cached-session-cost-output.json")); t = json.load(open("tier-analysis-output.json"))
rows = [("Opus 5.5 → Sonnet 5.5", 2.0, 1 / d["pairs"]["opus-5.5->sonnet-5.5"]["cached"]["aggregate_cost_ratio"]),
        ("Fable 5.2 → Sonnet 5.5", 4.0, 1 / d["pairs"]["fable-5.2->sonnet-5.5"]["cached"]["aggregate_cost_ratio"]),
        ("Sonnet 5.5 → Haiku 5.5", 20.0, 1 / d["pairs"]["sonnet-5.5->haiku-5.5"]["cached"]["aggregate_cost_ratio"]),
        ("Same, if prompts stayed under 100k", 20.0, t["times_cheaper_than_sonnet"]["haiku-5.5-all-short"])]
W, left, right, top, rowh, bh, gap, xmax = 680, 236, 56, 78, 56, 14, 2, 20.0
H = top + rowh * len(rows) + 46
x = lambda v: left + (W - left - right) * v / xmax
o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-labelledby="t d" font-family="system-ui,-apple-system,Segoe UI,sans-serif">',
     '<title id="t">How much cheaper the smaller model is, on the price sheet and on a re-priced Claude Code trace</title>',
     '<desc id="d">' + "; ".join(f"{a}: {b:.1f} on the price sheet, {c:.1f} on the trace" for a, b, c in rows) + '.</desc>',
     '<style>.s{fill:#fcfcfb}.p{fill:#2a78d6}.r{fill:#eb6834}.t1{fill:#1f1f1e}.t2{fill:#5b5a55}.g{stroke:#e4e3de;stroke-width:1}.a{stroke:#bdbcb5;stroke-width:1}'
     '@media (prefers-color-scheme: dark){.s{fill:#1a1a19}.p{fill:#3987e5}.r{fill:#d95926}.t1{fill:#f0efec}.t2{fill:#c3c2b7}.g{stroke:#2f2f2d}.a{stroke:#55544f}}</style>',
     f'<rect class="s" width="{W}" height="{H}"/>',
     '<text class="t1" x="16" y="26" font-size="15" font-weight="600">How much cheaper is the smaller model?</text>',
     '<rect class="p" x="16" y="42" width="12" height="12" rx="3"/><text class="t2" x="34" y="52" font-size="12">Price sheet (base input price)</text>',
     '<rect class="r" x="230" y="42" width="12" height="12" rx="3"/><text class="t2" x="248" y="52" font-size="12">233 Claude Code sessions, re-priced with caching</text>']
for v in (0, 5, 10, 15, 20):
    o.append(f'<line class="g" x1="{x(v):.1f}" y1="{top-6}" x2="{x(v):.1f}" y2="{top+rowh*len(rows)-6}"/>')
    o.append(f'<text class="t2" x="{x(v):.1f}" y="{top+rowh*len(rows)+12}" font-size="11" text-anchor="middle">{v}×</text>')
o.append(f'<text class="t2" x="{x(10):.1f}" y="{top+rowh*len(rows)+30}" font-size="11" text-anchor="middle">times cheaper than the bigger model</text>')
for i, (label, sticker, real) in enumerate(rows):
    y0 = top + i * rowh
    o.append(f'<text class="t1" x="{left-12}" y="{y0+bh+gap/2+4}" font-size="12.5" text-anchor="end">{label}</text>')
    for j, (v, cls, name) in enumerate(((sticker, "p", "price sheet"), (real, "r", "on the trace"))):
        yy, w = y0 + j * (bh + gap), x(v) - left
        o.append(f'<path class="{cls}" d="M{left},{yy} h{w-4:.1f} a4,4 0 0 1 4,4 v{bh-8} a4,4 0 0 1 -4,4 h-{w-4:.1f} z"><title>{label}, {name}: {v:.1f}× cheaper</title></path>')
        o.append(f'<text class="t1" x="{left+w+6:.1f}" y="{yy+bh-3}" font-size="11.5">{v:.1f}×</text>')
o.append(f'<line class="a" x1="{left}" y1="{top-6}" x2="{left}" y2="{top+rowh*len(rows)-6}"/></svg>')
open("cheaper-ratio-chart.svg", "w").write("\n".join(o))
