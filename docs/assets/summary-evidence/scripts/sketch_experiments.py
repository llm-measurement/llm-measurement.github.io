"""Private B1/B2/B4/B5/B6 measurements, using released summary/sketch APIs."""
from dataclasses import replace
from pathlib import Path
import gzip
import hashlib
import json
from collections import defaultdict
import statistics
import time
from llm_sketchkit import summary, hllpp, minhash, frequentitems, canonicalize_text_v1
from llm_sketchkit.hash import Secret, hash64
from features import ROOT, weight, merged

SECRET = Secret(b'forecast-phase0-public-test-key-20261010')

def stats(values):
    if not values:return {'n':0}
    ordered=sorted(values)
    return {'n':len(values),'mean':statistics.mean(values),'median':statistics.median(values),'p95':ordered[min(len(ordered)-1,int(.95*len(ordered)))],'max':max(values)}

def load_windows(dataset, node):
    files=sorted((ROOT/'data/analyst'/dataset/node).glob('*.json'))
    return [p.stem for p in files],[summary.Envelope.parse(p.read_bytes()) for p in files]

def merge_states(states, start, end):
    result=states[start].clone()
    for s in states[start+1:end]:result.merge(s)
    return result

def run():
    oracle=json.loads((ROOT/'data/oracle.json').read_text())
    dates,total=load_windows('tracelab','total')
    _,left=load_windows('tracelab','platform-claude');_,right=load_windows('tracelab','platform-codex')
    users={p:[set(oracle['tracelab']['days'][d]['users'][p]) for d in dates] for p in ['claude','codex']}
    hs={p:[hllpp.parse(w.sketches['distinct_users'].data) for w in windows] for p,windows in [('claude',left),('codex',right)]}
    combined=[hllpp.parse(w.sketches['distinct_users'].data) for w in total]
    ms={p:[] for p in users}
    for p in users:
        for values in users[p]:
            sketch=minhash.new('small','user:v1')
            for value in sorted(values):sketch.add_hash(hash64(SECRET,'user:v1',canonicalize_text_v1(value)))
            ms[p].append(sketch)
    b1=[]
    for length in [1,7,28]:
        for end in range(length,len(dates)+1):
            start=end-length;a=set().union(*users['claude'][start:end]);b=set().union(*users['codex'][start:end])
            ha=merge_states(hs['claude'],start,end);hb=merge_states(hs['codex'],start,end);union=ha.clone();union.merge(hb)
            ma=merge_states(ms['claude'],start,end);mb=merge_states(ms['codex'],start,end)
            j=ma.jaccard_estimate(mb)
            b1.append({'days':length,'end':dates[end-1],'exact_union':len(a|b),'estimate_union':union.estimate(),'union_abs_error':abs(union.estimate()-len(a|b)),'naive_sum':len(a)+len(b),'naive_overcount':len(a&b),'exact_overlap':len(a&b),'minhash_overlap':j*union.estimate(),'inclusion_exclusion_overlap':ha.estimate()+hb.estimate()-union.estimate(),'minhash_overlap_abs_error':abs(j*union.estimate()-len(a&b)),'hll_exchange_bytes':len(ha.marshal_binary())+len(hb.marshal_binary()),'hll_plus_minhash_exchange_bytes':sum(len(s.marshal_binary()) for s in [ha,hb,ma,mb]),'raw_user_lists_json_bytes':len(json.dumps([sorted(a),sorted(b)],separators=(',',':')).encode())})
    b2=[]
    for length in [7,28,90]:
        errors=[];timings=[]
        for end in range(length,len(dates)+1):
            start=end-length;exact=len(set().union(*(users['claude'][j]|users['codex'][j] for j in range(start,end))))
            errors.append(abs(merge_states(combined,start,end).estimate()-exact))
        for _ in range(5):
            begin=time.perf_counter()
            for end in range(length,len(dates)+1):merge_states(combined,end-length,end).estimate()
            timings.append(time.perf_counter()-begin)
        b2.append({'days':length,'queries':len(errors),'absolute_error':stats(errors),'batch_seconds':timings,'median_ms_per_query':1000*statistics.median(timings)/len(errors),'slowest_batch_seconds':max(timings)})
    storage={}
    for dataset in ['tracelab','burstgpt']:
        paths=list((ROOT/'data/analyst'/dataset).glob('*/*.json'))
        if dataset=='tracelab':paths=[p for p in paths if p.parent.name!='total']
        else:paths=[p for p in paths if p.parent.name!='total']
        summary_bytes=sum(p.stat().st_size for p in paths)
        packed=gzip.compress(b''.join(p.read_bytes()+b'\n' for p in sorted(paths)),mtime=0)
        if dataset=='tracelab':
            raw_path=ROOT/'data/syfi_coding_trace.jsonl.gz';raw_compressed=raw_path.stat().st_size
            with gzip.open(raw_path,'rb') as stream:raw_bytes=sum(len(chunk) for chunk in iter(lambda:stream.read(1<<20),b''))
            days=len(dates)
        else:
            raw_bytes=sum(p.stat().st_size for p in (ROOT/'data').glob('BurstGPT_*.csv'));raw_compressed=None;days=len(load_windows('burstgpt','total')[0])
        storage[dataset]={'days':days,'summary_bytes':summary_bytes,'summary_gzip_bytes':len(packed),'raw_bytes':raw_bytes,'raw_compressed_bytes':raw_compressed,'summary_bytes_per_day':summary_bytes/days,'summary_years_per_decimal_GB':1e9/(summary_bytes/days*365.25),'raw_years_per_decimal_GB':1e9/(raw_bytes/days*365.25),'summary_files':len(paths)}
    b4=[]
    for field,oracle_field in [('top_users','top_users'),('top_sessions','top_sessions')]:
        states=[frequentitems.parse(w.sketches[field].data) for w in total]
        for i in range(1,len(dates)):
            before=states[i-1];after=states[i];a=oracle['tracelab']['days'][dates[i-1]][oracle_field];b=oracle['tracelab']['days'][dates[i]][oracle_field]
            keys=set(a)|set(b);viols=0;share_checks=0;growth_share_checks=0;deltas=[];lower=[]
            growth=weight(total[i])-weight(total[i-1])
            for key in keys:
                k=int(key,16);av=a.get(key,0);bv=b.get(key,0)
                lo=after.lower_bound_hash(k)-before.upper_bound_hash(k);hi=after.upper_bound_hash(k)-before.lower_bound_hash(k)
                if not lo<=bv-av<=hi:viols+=1
                if growth>0:
                    growth_share_checks+=1
                    if not lo/growth<=(bv-av)/growth<=hi/growth:viols+=1
                for state,truth in [(before,av),(after,bv)]:
                    if state.total_weight():
                        share_checks+=1
                        if not state.lower_bound_hash(k)/state.total_weight()<=truth/state.total_weight()<=state.upper_bound_hash(k)/state.total_weight():viols+=1
                deltas.append(max(0,bv-av))
            candidates={item.hash for state in [before,after] for item in state.items()}
            for k in candidates:lower.append(max(0,after.lower_bound_hash(k)-before.upper_bound_hash(k)))
            growth=weight(total[i])-weight(total[i-1]);exact_flag=growth>0 and sum(sorted(deltas,reverse=True)[:2])>.5*growth
            sketch_flag=growth>0 and sum(sorted(lower,reverse=True)[:2])>.5*growth
            reversal=None if i+1==len(dates) or growth<=0 else weight(total[i])-weight(total[i+1])>.5*growth
            b4.append({'field':field,'day':dates[i],'growth':growth,'keys_checked':len(keys),'share_checks':share_checks,'growth_share_checks':growth_share_checks,'growth_share_defined':growth>0,'bound_violations':viols,'exact_fragile':exact_flag,'sketch_fragile':sketch_flag,'next_day_reversal':reversal})
    b6=[]
    index=max(range(len(total)),key=lambda i:weight(total[i]));pair=[left[index],right[index]];expected=[w.producer_id for w in pair]
    for name,docs in [('complete',pair),('missing_producer',pair[:1]),('partial_window',[replace(pair[0],observed_start_unix_nano=pair[0].observed_start_unix_nano+1_000_000_000),pair[1]])]:
        result=summary.combine(docs,expected);refused=False
        try:merged(docs,'total',expected)
        except ValueError:refused=True
        b6.append({'case':name,'missing':result.missing,'partial':result.partial,'forecast_guard_refused':refused})
    _,burst=load_windows('burstgpt','total')
    missing=sum(w.counters['missing_token_usage'] for w in burst)
    known=sum(w.counters['input_tokens']+w.counters['output_tokens'] for w in burst)
    complete=sum(weight(w) for w in burst)
    truth=[day['counts']['total'] for day in oracle['burstgpt']['days'].values()]
    expected_missing=sum(day['missing_token_usage'] for day in truth)
    expected_partial=sum(day['input_tokens']+day['output_tokens']-day['complete_tokens'] for day in truth)
    assert missing==expected_missing==99666 and known-complete==expected_partial==11731
    b6.append({'case':'failed_burst_requests','requests':sum(w.counters['requests'] for w in burst),'missing_usage':missing,'complete_attempt_tokens':complete,'known_tokens_including_partial_input':known,'partial_input_tokens':known-complete,'missing_usage_preserved':True})
    raw_ids=oracle['tracelab']['raw_identity_values']
    hits=[];files=list((ROOT/'data/analyst').glob('*/*/*.json'))
    prefixes=defaultdict(list)
    for identity in raw_ids:
        if len(identity)>=6:
            pattern=identity.encode();prefixes[pattern[:6]].append(pattern)
    for path in files:
        data=path.read_bytes()
        found=set()
        for i in range(len(data)-5):
            candidates=prefixes.get(data[i:i+6])
            if candidates:
                for pattern in candidates:
                    if data.startswith(pattern,i):found.add(hashlib.sha256(pattern).hexdigest())
        hits.extend({'file':str(path.relative_to(ROOT/'data/analyst')),'value_sha256':digest} for digest in sorted(found))
    hashed_identifiers=sum(len(p.data) for w in total for p in w.sketches.values())
    results={'B1':{str(n):{'union_abs_error':stats([r['union_abs_error'] for r in b1 if r['days']==n]),'naive_overcount':stats([r['naive_overcount'] for r in b1 if r['days']==n]),'minhash_overlap_abs_error':stats([r['minhash_overlap_abs_error'] for r in b1 if r['days']==n]),'hll_exchange_bytes':stats([r['hll_exchange_bytes'] for r in b1 if r['days']==n]),'hll_plus_minhash_exchange_bytes':stats([r['hll_plus_minhash_exchange_bytes'] for r in b1 if r['days']==n]),'raw_list_bytes':stats([r['raw_user_lists_json_bytes'] for r in b1 if r['days']==n])} for n in [1,7,28]},'B2':{'queries':b2,'storage':storage},'B4':{},'B5':{'files_scanned':len(files),'raw_identity_values':len(raw_ids),'raw_identity_hits':hits,'all_serialized_sketch_bytes_total_view':hashed_identifiers,'note':'Wire bytes include metadata/registers/weights, not only linkable hash bytes. Separate sentinel test required.'},'B6':b6}
    for field in ['top_users','top_sessions']:
        rows=[r for r in b4 if r['field']==field];tp=sum(r['sketch_fragile'] and r['exact_fragile'] for r in rows);fp=sum(r['sketch_fragile'] and not r['exact_fragile'] for r in rows);fn=sum(not r['sketch_fragile'] and r['exact_fragile'] for r in rows);flagged=[r for r in rows if r['sketch_fragile'] and r['next_day_reversal'] is not None]
        results['B4'][field]={'comparisons':len(rows),'keys_checked':sum(r['keys_checked'] for r in rows),'share_checks':sum(r['share_checks'] for r in rows),'growth_share_checks':sum(r['growth_share_checks'] for r in rows),'bound_violations':sum(r['bound_violations'] for r in rows),'true_positive':tp,'false_positive':fp,'false_negative':fn,'precision':tp/(tp+fp) if tp+fp else None,'recall':tp/(tp+fn) if tp+fn else None,'flagged_next_days':len(flagged),'next_day_reversals':sum(r['next_day_reversal'] for r in flagged)}
    for name,obj in [('sketch-results',results),('sketch-b1-windows',b1),('sketch-b4-windows',b4)]:
        (ROOT/'evidence'/f'{name}.json').write_text(json.dumps(obj,indent=2))
    print(json.dumps(results,indent=2))

if __name__=='__main__':run()
