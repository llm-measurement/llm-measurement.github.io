"""Read only shared summaries; run while all raw-data paths and network are denied."""
from pathlib import Path
from datetime import datetime, timezone
import json
from llm_sketchkit import summary, hllpp
from features import merged, weight, ROOT, dates_between

def main():
    folder=ROOT/'analyst-inputs'; output=ROOT/'analyst-output'
    output.mkdir(exist_ok=True)
    series=[];hierarchies=[];inputs=[]
    rosters={'tracelab':{'platform-claude':'claude','platform-codex':'codex'},'burstgpt':{'model-ChatGPT':'g000','model-GPT-4':'g001'}}
    calendars={'tracelab':dates_between('2025-09-23','2026-07-25'),'burstgpt':dates_between('2024-01-01','2024-05-01')}
    for dataset in ['tracelab','burstgpt']:
        expected_dirs=rosters[dataset]
        dirs=sorted((folder/dataset).iterdir());cells={}
        if {d.name for d in dirs} != set(expected_dirs):raise ValueError('incomplete or unexpected producer directory roster')
        for directory in dirs:
            paths=sorted(directory.glob('*.json'));dates=[p.stem for p in paths]
            if dates != calendars[dataset]:raise ValueError('incomplete or misaligned day roster')
            cells[directory.name]=[summary.Envelope.parse(p.read_bytes()) for p in paths]
            if any(doc.producer_id != expected_dirs[directory.name] for doc in cells[directory.name]):raise ValueError('unexpected producer')
            if any(datetime.fromtimestamp(doc.window_start_unix_nano//1_000_000_000,timezone.utc).date().isoformat()!=day for doc,day in zip(cells[directory.name],dates)):raise ValueError('file date and envelope date differ')
            inputs.extend(str(p.relative_to(folder)) for p in paths)
        names=list(cells);expected=[expected_dirs[n] for n in names]
        cells['total']=[merged([cells[n][i] for n in names],'total',expected) for i in range(len(dates))]
        keep=list(range(len(dates))) if dataset=='tracelab' else list(range(1,len(dates)-1))
        for name,docs in cells.items():
            series.append({'name':dataset+':'+name,'dataset':dataset,'kind':'tokens','dates':[dates[i] for i in keep],'values':[weight(docs[i]) for i in keep],'requests':[docs[i].counters['requests'] for i in keep]})
        hierarchy_names=['total']+names
        hierarchies.append({'dataset':dataset,'nodes':[dataset+':'+n for n in hierarchy_names],'bottom':[dataset+':'+n for n in names],'S':[[1]*len(names)]+[[int(i==j) for j in range(len(names))] for i in range(len(names))]})
        if dataset=='tracelab':
            states=[hllpp.parse(d.sketches['distinct_users'].data) for d in cells['total']]
            for length in [1,7,28]:
                vals=[]
                for end in range(length,len(dates)+1):
                    h=states[end-length].clone()
                    for other in states[end-length+1:end]:h.merge(other)
                    vals.append(h.estimate())
                series.append({'name':f'tracelab:users:{length}','dataset':dataset,'kind':'users','dates':dates[length-1:],'values':vals})
    document={'series':series,'hierarchies':hierarchies}
    (output/'features.json').write_text(json.dumps(document,separators=(',',':')))
    (output/'input-files.json').write_text(json.dumps(inputs,indent=2))
    print(json.dumps({'summary_files_read':len(inputs),'series':len(series),'raw_reference_fields_present':False}))

if __name__=='__main__':main()
