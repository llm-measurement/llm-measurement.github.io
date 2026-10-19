# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Check guide prose and count what is visible before the sample."""
from html.parser import HTMLParser
import re

INSTALL_PREAMBLE = "Linux or macOS; needs curl, gh, shasum and tar. The installer checks the release before unpacking it."
FORBIDDEN = {
    "sparse logs": r"\bsparse\s+logs\b",
    "do not establish": r"\bdo\s+not\s+establish\b",
    "equal-length": r"\bequal[-\s]+(?:length|duration)\b",
    "nonoverlapping": r"\bnon[-\s]?overlapping\b",
    "approved": r"\bapproved\b",
    "--keep-export": r"--keep-export\b",
    "symlink": r"\bsymlink\w*\b",
    "leave ... unset": r"\bleave\b[^.!?]{0,250}\bunset\b",
    "private snapshot": r"\bprivate\s+snapshot\b",
    "not a substitute": r"\bnot\s+a\s+substitute\b",
    "remains an alternative": r"\bremains\s+an\s+alternative\b",
    "need not be signed in": r"\bneed\s+not\s+be\s+signed\s+in\b",
    "start without an existing folder": r"\bstart\s+without\s+an?\s+existing\b.{0,160}?\bfolder\b",
}
BLOCKS = {"p", "li", "h1", "h2", "h3", "h4", "ul", "ol", "nav", "section", "aside", "pre", "details", "summary", "br"}
VOID = {"br", "hr", "img", "input", "meta", "link", "wbr"}


class Prose(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.all_text = []
        self.visible = []
        self.prose = []
        self.before_sample = True
        self.paragraphs = []
        self.current_paragraph = None

    def hidden(self):
        for i, (tag, attrs) in enumerate(self.stack):
            if tag == "details" and "open" not in attrs:
                if i + 1 == len(self.stack) or self.stack[i + 1][0] != "summary":
                    return True
            if tag in {"script", "style"} or "hidden" in attrs:
                return True
        return False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "p":
            self.current_paragraph = []
            self.paragraphs.append(self.current_paragraph)
        if attrs.get("id") == "sample":
            self.before_sample = False
        if tag in BLOCKS:
            self.handle_data(" ")
        if tag not in VOID:
            self.stack.append((tag, attrs))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break
        if tag in BLOCKS:
            self.handle_data(" ")
        if tag == "p":
            self.current_paragraph = None

    def handle_data(self, data):
        self.all_text.append(data)
        if self.current_paragraph is not None:
            self.current_paragraph.append(data)
        if self.before_sample and not self.hidden():
            self.visible.append(data)
            if not any(tag == "pre" for tag, _ in self.stack):
                self.prose.append(data)

    def handle_comment(self, data):
        self.all_text.append(" " + data + " ")


def count_words(text):
    return len(re.findall(r"\S+", text))


def inspect(source, title):
    parsed = Prose()
    parsed.feed(source)
    all_text = " ".join("".join(parsed.all_text).split())
    preambles = [" ".join("".join(p).split()) for p in parsed.paragraphs
                 if re.search(r"\bcurl\b|\bgh\b|\binstaller\b", "".join(p), re.I)]
    return {
        "visible_words": count_words(title + " " + "".join(parsed.visible)),
        "prose_words": count_words(title + " " + "".join(parsed.prose)),
        "forbidden": [label for label, pattern in FORBIDDEN.items() if re.search(pattern, all_text, re.I)],
        "install_preambles": preambles,
    }


def check(source, title, budget):
    result = inspect(source, title)
    assert 'security.html#verify-fleetdiff' not in source, "manual verification belongs in the footer"
    assert not result["forbidden"], ("removed guide wording", result["forbidden"])
    assert result["visible_words"] <= budget, ("visible word budget", result["visible_words"], budget)
    assert all(p in {INSTALL_PREAMBLE, "1. Install. " + INSTALL_PREAMBLE}
               for p in result["install_preambles"]), "use the reviewed install preamble"
    if "install-fleetdiff.sh" in source or "scripts/install.sh" in source:
        assert result["install_preambles"], "missing install preamble"
    return result
