#!/usr/bin/env python3
"""What if only the subagents move to Haiku 5.5, the use Anthropic recommends Haiku for?

Same replay and prices as cached_session_cost.py. The main agent stays on Sonnet 5.5; subagent
inner requests are priced on Haiku 5.5 (tier per request). Usage: python3 -I -B subagent_split.py TRACES_JSONL
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cached_session_cost import LONG_PROMPT, flatten, per_call, price

def main(path):
    acc = {"main_sonnet": 0.0, "sub_sonnet": 0.0, "sub_haiku": 0.0}
    n = {"main": 0, "sub": 0, "sub_over_100k": 0, "main_over_100k": 0}
    for line in open(path):
        reqs = [q for q in flatten(json.loads(line)) if q.get("hash_ids")]
        for (p, r, w, o), q in zip(per_call(reqs), reqs):
            def c(m):
                _, pw, pr, po = price(m, p)
                return (r * pr + w * pw + o * po) / 1e6
            if q["agent"] == "main":
                acc["main_sonnet"] += c("sonnet-5.5"); n["main"] += 1; n["main_over_100k"] += p > LONG_PROMPT
            else:
                acc["sub_sonnet"] += c("sonnet-5.5"); acc["sub_haiku"] += c("haiku-5.5"); n["sub"] += 1
                n["sub_over_100k"] += p > LONG_PROMPT
    all_sonnet = acc["main_sonnet"] + acc["sub_sonnet"]
    split = acc["main_sonnet"] + acc["sub_haiku"]
    print(json.dumps({**acc, **n, "subagent_share_of_sonnet_bill": acc["sub_sonnet"] / all_sonnet,
                      "subagent_times_cheaper_on_haiku": acc["sub_sonnet"] / acc["sub_haiku"],
                      "bill_with_subagents_on_haiku_vs_all_sonnet": split / all_sonnet}, indent=2))

if __name__ == "__main__":
    main(sys.argv[1])
