"""Read connector summaries through released sketchkit; oracle is validation only."""
from pathlib import Path
from dataclasses import replace
from datetime import date, timedelta
import hashlib
import json
from llm_sketchkit import summary, hllpp, frequentitems

ROOT = Path(__file__).resolve().parents[1]

def dates_between(start, end):
    start, end = date.fromisoformat(start), date.fromisoformat(end)
    return [(start + timedelta(days=i)).isoformat() for i in range((end-start).days)]

def load(dataset):
    folder = ROOT / 'data' / f'{dataset}-summaries'
    manifest = json.loads((folder / 'manifest.json').read_text())
    dates = dates_between(manifest['Start'], manifest['End'])
    groups = manifest['Groups']
    docs = {g['Name']: [summary.Envelope.parse((folder / g['Directory'] / f'{d}.json').read_bytes()) for d in dates] for g in groups}
    return manifest, dates, groups, docs

def merged(docs, producer, expected):
    result = summary.combine(docs, expected)
    if result.missing or result.partial:
        raise ValueError('incomplete producer coverage')
    return replace(docs[0], producer_id=producer, epoch=hashlib.sha256(producer.encode()).hexdigest()[:32], counters=result.counters, sketches=result.sketches)

def weight(doc):
    return frequentitems.parse(doc.sketches['top_prompts'].data).total_weight()

def build():
    oracle = json.loads((ROOT / 'data/oracle.json').read_text())
    features = {'series': [], 'hierarchies': []}
    checks = {'days_checked': 0, 'counters_checked': 0, 'mismatches': [], 'dataset_totals': {}, 'boundary_exclusions': {}}
    for dataset in ['tracelab', 'burstgpt']:
        manifest, dates, groups, cells = load(dataset)
        nodes = dict(cells)
        if dataset == 'tracelab':
            for provider in sorted({g['Provider'] for g in groups}):
                selected = [g['Name'] for g in groups if g['Provider'] == provider]
                expected = [g['Directory'] for g in groups if g['Provider'] == provider]
                nodes[f'platform:{provider}'] = [merged([cells[n][i] for n in selected], provider, expected) for i in range(len(dates))]
            for model in sorted({g['Model'] for g in groups}):
                selected = [g['Name'] for g in groups if g['Model'] == model]
                pid = 'model-' + hashlib.sha256(model.encode()).hexdigest()[:12]
                expected = [g['Directory'] for g in groups if g['Model'] == model]
                nodes[f'model:{model}'] = [merged([cells[n][i] for n in selected], pid, expected) for i in range(len(dates))]
            nodes['total'] = [merged([nodes['platform:claude'][i], nodes['platform:codex'][i]], 'total', ['claude','codex']) for i in range(len(dates))]
        else:
            nodes['total'] = [merged([cells[n][i] for n in cells], 'total', [g['Directory'] for g in groups]) for i in range(len(dates))]
        analytic = ROOT / 'data/analyst' / dataset
        analytic.mkdir(parents=True, exist_ok=True)
        keep = list(range(len(dates))) if dataset == 'tracelab' else list(range(1, len(dates)-1))
        checks['boundary_exclusions'][dataset] = [d for i,d in enumerate(dates) if i not in keep]
        for name, windows in nodes.items():
            values = []
            for i,doc in enumerate(windows):
                truth = oracle[dataset]['days'][dates[i]]['counts'].get(name, {})
                expected = {k: truth.get(k, 0) for k in ['requests','input_tokens','output_tokens','missing_token_usage']}
                observed = {k: doc.counters[k] for k in expected}
                expected['complete_tokens'] = truth.get('complete_tokens', 0)
                observed['complete_tokens'] = weight(doc)
                checks['days_checked'] += 1; checks['counters_checked'] += len(expected)
                if expected != observed:
                    checks['mismatches'].append({'dataset':dataset,'node':name,'day':dates[i],'expected':expected,'observed':observed})
                values.append(weight(doc))
            series = {'name':dataset+':'+name,'dataset':dataset,'kind':'tokens','dates':[dates[i] for i in keep],'values':[values[i] for i in keep], 'requests':[windows[i].counters['requests'] for i in keep], 'missing_usage':[windows[i].counters['missing_token_usage'] for i in keep]}
            if dataset == 'tracelab' and name == 'total':
                series['users_sketch'] = [hllpp.parse(windows[i].sketches['distinct_users'].data).estimate() for i in keep]
                series['users_exact'] = [len(set(oracle[dataset]['days'][dates[i]]['users']['claude']) | set(oracle[dataset]['days'][dates[i]]['users']['codex'])) for i in keep]
            features['series'].append(series)
        selected_names = ['platform:claude','platform:codex','total'] if dataset == 'tracelab' else list(nodes)
        for name in selected_names:
            dest = analytic / name.replace(':','-');dest.mkdir(exist_ok=True)
            for d,doc in zip(dates,nodes[name]):
                (dest / f'{d}.json').write_bytes(doc.marshal_binary())
        bottom = list(cells)
        order = ['total'] + [n for n in nodes if n != 'total']
        S = []
        for name in order:
            S.append([int(name == 'total' or name == g['Name'] or name == 'platform:'+g['Provider'] or name == 'model:'+g['Model']) for g in groups])
        features['hierarchies'].append({'dataset':dataset,'nodes':[dataset+':'+n for n in order],'bottom':[dataset+':'+n for n in bottom],'S':S})
        checks['dataset_totals'][dataset] = {k:sum(d.counters[k] for d in nodes['total']) for k in ['requests','input_tokens','output_tokens','missing_token_usage']}
        checks['dataset_totals'][dataset]['complete_tokens'] = sum(weight(d) for d in nodes['total'])
        if dataset == 'tracelab':
            sketches = [hllpp.parse(doc.sketches['distinct_users'].data) for doc in nodes['total']]
            for length in [1,7,28]:
                exact, est, naive = [], [], []
                for i in range(length-1,len(dates)):
                    h = sketches[i-length+1].clone(); left=set();right=set()
                    for j in range(i-length+1,i+1):
                        if j != i-length+1:h.merge(sketches[j])
                        left.update(oracle[dataset]['days'][dates[j]]['users']['claude']);right.update(oracle[dataset]['days'][dates[j]]['users']['codex'])
                    est.append(h.estimate());exact.append(len(left|right));naive.append(len(left)+len(right))
                features['series'].append({'name':f'tracelab:users:{length}','dataset':dataset,'kind':'users','dates':dates[length-1:],'values':est,'exact_values':exact,'naive_values':naive})
    (ROOT/'evidence/features-validation.json').write_text(json.dumps(checks,indent=2))
    if checks['mismatches']:raise AssertionError(f"{len(checks['mismatches'])} accounting mismatches; inspect local evidence")
    (ROOT/'evidence/features.json').write_text(json.dumps(features,separators=(',',':')))
    print(json.dumps(checks,indent=2))

if __name__ == '__main__':build()
