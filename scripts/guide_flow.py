# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Check input-first guides and keep executable examples accounted for."""
from html.parser import HTMLParser


class GuideFlow(HTMLParser):
    def __init__(self):
        super().__init__()
        self.nodes = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "attrs": dict(attrs), "parents": list(self.stack)}
        self.nodes.append(node)
        if tag not in {"br", "hr", "img", "input", "meta", "link", "wbr"}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]["tag"] == tag:
                del self.stack[i:]
                break


def check_guide_flow(source, expected_paths=None):
    flow = GuideFlow()
    flow.feed(source)
    nodes = flow.nodes
    ids = [n["attrs"]["id"] for n in nodes if "id" in n["attrs"]]
    assert len(ids) == len(set(ids)), "duplicate guide anchor"
    assert nodes[0]["tag"] == "p" and nodes[0]["attrs"].get("class") == "lead", "lead first"
    indexes = [n for n in nodes if n["attrs"].get("class") == "path-index"]
    assert len(indexes) == 1 and nodes[1] is indexes[0], "index immediately after lead"
    index = indexes[0]
    assert index["tag"] == "nav" and index["attrs"].get("aria-label"), "named navigation"
    links = [n["attrs"].get("href") for n in nodes if n["tag"] == "a" and index in n["parents"]]
    assert links and links[0] == "#run" and links[-1] == "#sample", "own data first, sample last"
    assert len(links) == len(set(links)), "duplicate index path"
    if expected_paths is not None:
        assert links == expected_paths, "required input paths"
    targets = []
    for link in links:
        if link == "litellm-spend.html#access":
            continue
        assert link and link.startswith("#") and link[1:] in ids, "missing path target"
        targets.append(next(n for n in nodes if n["attrs"].get("id") == link[1:]))
    positions = [nodes.index(n) for n in targets]
    assert positions == sorted(positions), "path sections follow index order"
    own, sample = targets[0], targets[-1]
    assert own["attrs"].get("class") == "own-data", "distinct own-data block"
    assert sample["tag"] == "section", "sample section"
    assert not any(n["tag"] in {"section", "aside", "details"} and not n["parents"]
                   for n in nodes[nodes.index(sample) + 1:]), "sample is last section"
    blocks = [n for n in nodes if n["tag"] == "pre"]
    kinds = {"data-own", "data-run", "data-output", "data-review", "data-sql"}
    for block in blocks:
        assert len(kinds.intersection(block["attrs"])) == 1, "unaccounted or ambiguous published block"
        if {"data-run", "data-output"}.intersection(block["attrs"]):
            assert sample in block["parents"], "synthetic sample and output belong only in sample"
        if "data-own" in block["attrs"] or "data-sql" in block["attrs"]:
            assert sample not in block["parents"], "own-data commands outside sample"
    runs = [n for n in blocks if "data-run" in n["attrs"]]
    outputs = [n for n in blocks if "data-output" in n["attrs"]]
    assert len(runs) == 1 and outputs, "one sample command with checked output"
    assert all(nodes.index(runs[0]) < nodes.index(n) for n in outputs), "run sample before output"
    security = [n for n in nodes if n["attrs"].get("class") == "security-note"]
    assert len(security) == 1, "one security section"
    assert all(n["tag"] == "details" and "open" not in n["attrs"] for n in security), "security folded"
