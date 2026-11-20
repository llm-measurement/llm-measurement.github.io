#!/usr/bin/env python3
"""Draw wide and narrow cost-ratio SVGs from the same two JSON records."""
import html
import json
from pathlib import Path

STYLE = (
    '.cr-s{fill:#fcfcfb}.cr-p{fill:#2a78d6}.cr-r{fill:#eb6834}'
    '.cr-t1{fill:#1f1f1e}.cr-t2{fill:#5b5a55}'
    '.cr-g{stroke:#e4e3de;stroke-width:1}.cr-a{stroke:#bdbcb5;stroke-width:1}'
    '@media (prefers-color-scheme: dark){.cr-s{fill:#1a1a19}.cr-p{fill:#3987e5}'
    '.cr-r{fill:#d95926}.cr-t1{fill:#f0efec}.cr-t2{fill:#c3c2b7}'
    '.cr-g{stroke:#2f2f2d}.cr-a{stroke:#55544f}}'
)


def rows():
    data = json.loads(Path('cached-session-cost-output.json').read_text())
    tiers = json.loads(Path('tier-analysis-output.json').read_text())
    return [
        ('Opus 5.5 → Sonnet 5.5', 2.0,
         1 / data['pairs']['opus-5.5->sonnet-5.5']['cached']['aggregate_cost_ratio']),
        ('Fable 5.2 → Sonnet 5.5', 4.0,
         1 / data['pairs']['fable-5.2->sonnet-5.5']['cached']['aggregate_cost_ratio']),
        ('Sonnet 5.5 → Haiku 5.5', 20.0,
         1 / data['pairs']['sonnet-5.5->haiku-5.5']['cached']['aggregate_cost_ratio']),
        ('Same, if prompts stayed under 100k', 20.0,
         tiers['times_cheaper_than_sonnet']['haiku-5.5-all-short']),
    ]


def frame(data, width, height, variant):
    title_id, desc_id = f'cr-{variant}-title', f'cr-{variant}-desc'
    description = '; '.join(f'{label}: {a:.1f} on the price sheet, {b:.1f} on the trace'
                            for label, a, b in data) + '.'
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" '
        f'aria-labelledby="{title_id} {desc_id}" font-family="system-ui,-apple-system,Segoe UI,sans-serif">',
        f'<title id="{title_id}">How much cheaper the smaller model is, on the price sheet and on a re-priced Claude Code trace</title>',
        f'<desc id="{desc_id}">{html.escape(description)}</desc>',
        f'<style>{STYLE}</style>', f'<rect class="cr-s" width="{width}" height="{height}"/>',
    ]


def text(x, y, value, size, *, kind='cr-t1', anchor='start', weight=None):
    bold = f' font-weight="{weight}"' if weight else ''
    return (f'<text class="{kind}" x="{x}" y="{y}" font-size="{size}"'
            f' text-anchor="{anchor}"{bold}>{html.escape(value)}</text>')


def bars(output, label, sticker, real, left, top, scale, height, gap, size):
    for index, (value, kind, name) in enumerate(((sticker, 'cr-p', 'price sheet'),
                                               (real, 'cr-r', 'on the trace'))):
        y, width = top + index * (height + gap), scale * value
        output.append(f'<path class="{kind}" d="M{left},{y} h{width-4:.1f} a4,4 0 0 1 4,4 '
                      f'v{height-8} a4,4 0 0 1 -4,4 h-{width-4:.1f} z">'
                      f'<title>{html.escape(label)}, {name}: {value:.1f}× cheaper</title></path>')
        output.append(text(f'{left+width+6:.1f}', y + height - 3, f'{value:.1f}×', size))


def wide(data):
    width, left, right, top, row_height = 680, 236, 56, 78, 56
    height = top + row_height * len(data) + 46
    scale = (width - left - right) / 20
    output = frame(data, width, height, 'wide')
    output.extend([
        text(16, 26, 'How much cheaper is the smaller model?', 15, weight=600),
        '<rect class="cr-p" x="16" y="42" width="12" height="12" rx="3"/>',
        text(34, 52, 'Price sheet (base input price)', 12, kind='cr-t2'),
        '<rect class="cr-r" x="230" y="42" width="12" height="12" rx="3"/>',
        text(248, 52, '233 Claude Code sessions, re-priced with caching', 12, kind='cr-t2'),
    ])
    for value in (0, 5, 10, 15, 20):
        x = left + scale * value
        output.append(f'<line class="cr-g" x1="{x:.1f}" y1="{top-6}" x2="{x:.1f}" y2="{top+row_height*len(data)-6}"/>')
        output.append(text(f'{x:.1f}', top + row_height * len(data) + 12,
                           f'{value}×', 11, kind='cr-t2', anchor='middle'))
    output.append(text(f'{left+scale*10:.1f}', top + row_height * len(data) + 30,
                       'times cheaper than the bigger model', 11, kind='cr-t2', anchor='middle'))
    for index, (label, sticker, real) in enumerate(data):
        y = top + index * row_height
        output.append(text(left - 12, y + 19, label, 12.5, anchor='end'))
        bars(output, label, sticker, real, left, y, scale, 14, 2, 11.5)
    output.append(f'<line class="cr-a" x1="{left}" y1="{top-6}" x2="{left}" y2="{top+row_height*len(data)-6}"/></svg>')
    return '\n'.join(output)


def narrow(data):
    width, left, right, top, row_height = 340, 16, 62, 124, 88
    scale = (width - left - right) / 20
    height = top + row_height * len(data) + 32
    output = frame(data, width, height, 'narrow')
    output.extend([
        text(16, 24, 'How much cheaper is', 18, weight=600),
        text(16, 46, 'the smaller model?', 18, weight=600),
        '<rect class="cr-p" x="16" y="64" width="12" height="12" rx="3"/>',
        text(36, 75, 'Price sheet (base input price)', 15, kind='cr-t2'),
        '<rect class="cr-r" x="16" y="88" width="12" height="12" rx="3"/>',
        text(36, 99, 'Trace, with caching (233 sessions)', 15, kind='cr-t2'),
    ])
    for index, (label, sticker, real) in enumerate(data):
        y = top + index * row_height
        output.append(text(left, y, label, 16, weight=600))
        for value in (0, 5, 10, 15, 20):
            x = left + scale * value
            output.append(f'<line class="cr-g" x1="{x:.1f}" y1="{y+8}" x2="{x:.1f}" y2="{y+56}"/>')
        bars(output, label, sticker, real, left, y + 12, scale, 18, 6, 15)
    for value in (0, 5, 10, 15, 20):
        output.append(text(f'{left+scale*value:.1f}', height - 28,
                           f'{value}×', 14, kind='cr-t2', anchor='middle'))
    output.append(text(width // 2, height - 7, 'times cheaper than the bigger model',
                       14, kind='cr-t2', anchor='middle'))
    output.append('</svg>')
    return '\n'.join(output)


if __name__ == '__main__':
    data = rows()
    Path('cheaper-ratio-chart.svg').write_text(wide(data))
    Path('cheaper-ratio-chart-narrow.svg').write_text(narrow(data))
