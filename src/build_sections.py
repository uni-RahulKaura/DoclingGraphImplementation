#!/usr/bin/env python
"""Build the section corpus for the section-routing benchmark.

The unit of work is a *section of a real contract*, taken from the DocLang that
docling produced -- not from the source Markdown. That is deliberate: it is the
representation an extractor is actually handed, and using anything else would
benchmark a pipeline nobody runs.

The task each model is asked to perform is the one the architecture calls for:
given one section, decide which of five facets it contains, so an agentic search
can decide whether the section is worth opening at all.

  PERM    a permission or prohibition  (may / shall not / must not / entitled / prohibited)
  EXPIRY  a date, term, expiry, renewal or termination trigger
  PARTY   names the contracting parties, or states who contracts with whom
  PAY     payment, pricing, fees, currency or invoicing terms
  OBLIG   an obligation  (shall / must / is required to / agrees to)

Five binary facets over the corpus is enough to separate models on F1 and to
measure run-to-run agreement without a corpus that takes days to label.
"""
import glob
import hashlib
import json
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rule_client6 import _doclang_body, _is_clause_heading, _text_of  # noqa: E402

STEMS = ["micro_crystal", "evolving_solutions", "dell", "jabil",
         "atl_technology", "accenture"]
FACETS = ["PERM", "EXPIRY", "PARTY", "PAY", "OBLIG"]

out = []
for stem in STEMS:
    d = sorted(glob.glob("out6/%s_direct_csv/*/" % stem))[-1]
    root = ET.fromstring(_doclang_body(open(d + "docling/document.dclg").read()))
    units = list(root)
    idx = [(i, _text_of(u)) for i, u in enumerate(units)
           if u.tag == "heading" or _is_clause_heading(u)]
    if not idx:
        idx = [(0, "WHOLE DOCUMENT")]
    # Content BEFORE the first heading needs its own section, or it is silently lost.
    # Measured on this corpus that dropped 19-24% of dell, jabil and atl_technology --
    # and in all three the lost text was the actual agreement letter, while the
    # headings that survived were the appended DocuSign certificate. Capturing the
    # preamble is the difference between routing over the contract and routing over
    # e-signature boilerplate.
    if idx[0][0] > 0:
        idx.insert(0, (0, "[preamble - before first heading]"))
    for j, (pos, title) in enumerate(idx):
        end = idx[j + 1][0] if j + 1 < len(idx) else len(units)
        body = " ".join(_text_of(units[k]) for k in range(pos, end))
        body = " ".join(body.split())
        if len(body) < 40:          # a heading with no body cannot carry a facet
            continue
        out.append({
            # Content-derived id, NOT a positional index. An earlier version used
            # "<doc>#<ordinal>", so inserting the preamble section shifted every
            # later ordinal and silently misaligned the gold labels against the
            # sections they were written for. Hashing the heading keeps a label
            # attached to its section across rebuilds.
            "id": "%s#%s" % (stem, hashlib.sha1(
                ("%s|%s" % (stem, title)).encode("utf-8")).hexdigest()[:8]),
            "ordinal": j,
            "doc": stem,
            "heading": title[:160],
            "text": body,
            "chars": len(body),
            "words": len(body.split()),
        })

with open("sections6.json", "w") as fh:
    json.dump(out, fh, indent=1)

print("sections: %d" % len(out))
print("%-20s %6s %8s %8s" % ("doc", "n", "medianW", "maxW"))
for stem in STEMS:
    ws = sorted(s["words"] for s in out if s["doc"] == stem)
    if ws:
        print("%-20s %6d %8d %8d" % (stem, len(ws), ws[len(ws) // 2], ws[-1]))
allw = sorted(s["words"] for s in out)
print("%-20s %6d %8d %8d" % ("ALL", len(allw), allw[len(allw) // 2], allw[-1]))
print("total words: %d" % sum(allw))
