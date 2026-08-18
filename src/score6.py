#!/usr/bin/env python
"""Score docling-graph's output on the four-factor rubric.

The rubric is not re-implemented here. It is imported from `parseeval.metrics`,
the same module and the same weights (completeness .35, similarity .35,
structure .20, cleanliness .10) used for the eleven-parser bake-off, so the
numbers are produced by identical code.

WHAT IS BEING COMPARED, precisely
---------------------------------
Input  (gold): the Landing Markdown for each contract -- `dgwork/in6/<stem>.md`
Output (cand): docling-graph's own re-serialisation -- `docling/document.md`

This is a **round trip**: Markdown in, Markdown out. It is NOT the same task the
eleven parsers were scored on (they converted PDF/DOCX into Markdown, which is
strictly harder), so these scores must not be ranked against that table. What it
measures is the loss docling-graph's own conversion and serialisation inflict on
already-clean Markdown -- and since extraction runs on the result, any loss here
is loss the knowledge graph is then built on top of. A round trip should score
near 100; whatever falls short is damage introduced before any model is involved.

Also reported, because the four factors alone would miss them:
  * DocLang structure fidelity -- headings and tables surviving into the XML the
    extractor actually reads (input Markdown is never shown to it).
  * Provenance grounding -- the verbatim/document/unresolved split, which is where
    the 6-chunk cutoff bites on real contracts whose parties appear on every page.
"""
import csv
import glob
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from parseeval import metrics  # noqa: E402  the bake-off's scorer, unmodified

STEMS = ["micro_crystal", "evolving_solutions", "dell", "jabil",
         "atl_technology", "accenture"]
EXPORT = os.environ.get("DG_EXPORT", "csv")
CLIENT = os.environ.get("DG_CLIENT", "doclang")
TAG = os.environ.get("DG_TAG", "")


def run_dir(stem):
    hits = sorted(glob.glob("out6/%s_direct_%s%s/*/" % (stem, EXPORT, TAG)))
    return hits[-1] if hits else None


def doclang_stats(path):
    """Structure census of the DocLang the extractor is actually handed."""
    if not os.path.exists(path):
        return None
    raw = open(path, encoding="utf-8", errors="replace").read()
    i, k = raw.find("<doclang"), raw.rfind("</doclang>")
    if i < 0 or k <= i:
        return {"parsed": False}
    try:
        root = ET.fromstring(raw[i:k + len("</doclang>")])
    except ET.ParseError as e:
        return {"parsed": False, "error": str(e)[:120]}
    return {"parsed": True,
            "top_level": dict(Counter(c.tag for c in root)),
            "all_tags": dict(Counter(el.tag for el in root.iter())),
            "text_chars": len(" ".join(" ".join(root.itertext()).split()))}


def _find(o, key):
    if isinstance(o, dict):
        if key in o:
            return o[key]
        for v in o.values():
            r = _find(v, key)
            if r is not None:
                return r
    elif isinstance(o, list):
        for v in o:
            r = _find(v, key)
            if r is not None:
                return r
    return None


def provenance_stats(d):
    p = os.path.join(d, "docling_graph", "provenance.json")
    if not os.path.exists(p):
        return None
    try:
        j = json.load(open(p))
    except Exception as e:
        return {"error": str(e)[:120]}
    out = {"bytes": os.path.getsize(p), "bind_stats": _find(j, "bind_stats")}
    chunks = _find(j, "chunks")
    if isinstance(chunks, list):
        out["chunk_count"] = len(chunks)
    matches = []

    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("match"), str):
                matches.append(o["match"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(j)
    if matches:
        out["match_levels"] = dict(Counter(matches))
    return out


def graph_stats(d):
    out = {}
    npath = os.path.join(d, "docling_graph", "nodes.csv")
    epath = os.path.join(d, "docling_graph", "edges.csv")
    if os.path.exists(npath):
        with open(npath, newline="", encoding="utf-8", errors="replace") as fh:
            rows = list(csv.DictReader(fh))
        out["nodes"] = len(rows)
        lab, prov = Counter(), Counter()
        for r in rows:
            lab[r.get("label") or r.get("_labels") or r.get("type") or "?"] += 1
            pj = r.get("__provenance__")
            if pj:
                try:
                    prov[json.loads(pj).get("match", "?")] += 1
                except Exception:
                    prov["unparseable"] += 1
            else:
                prov["absent"] += 1
        out["node_labels"] = dict(lab)
        out["node_provenance_match"] = dict(prov)
    if os.path.exists(epath):
        with open(epath, newline="", encoding="utf-8", errors="replace") as fh:
            out["edges"] = sum(1 for _ in csv.DictReader(fh))
    cy = os.path.join(d, "docling_graph", "graph.cypher")
    if os.path.exists(cy):
        txt = open(cy, encoding="utf-8", errors="replace").read()
        out["cypher_bytes"] = len(txt)
        out["cypher_merge"] = txt.count("MERGE")
        out["cypher_constraints"] = txt.count("CREATE CONSTRAINT")
    gh = os.path.join(d, "docling_graph", "graph.html")
    if os.path.exists(gh):
        h = open(gh, encoding="utf-8", errors="replace").read()
        out["graph_html_bytes"] = len(h)
        out["graph_html_cdn_refs"] = len(re.findall(r"https?://(?:unpkg|cdn)\.", h))
    return out


results = []
for stem in STEMS:
    src = "in6/%s.md" % stem
    d = run_dir(stem)
    rec = {"stem": stem, "in_bytes": os.path.getsize(src), "run_dir": d}
    if not d:
        rec["error"] = "no run dir"
        results.append(rec)
        continue
    gold = open(src, encoding="utf-8", errors="replace").read()
    dm = os.path.join(d, "docling", "document.md")
    if os.path.exists(dm):
        cand = open(dm, encoding="utf-8", errors="replace").read()
        rec["document_md_bytes"] = len(cand)
        # ---- THE FOUR FACTORS, from the bake-off's own scorer ----
        rec["score"] = metrics.score(gold, cand)
    else:
        rec["error"] = "no document.md"
    rec["doclang"] = doclang_stats(os.path.join(d, "docling", "document.dclg"))
    rec["graph"] = graph_stats(d)
    rec["provenance"] = provenance_stats(d)
    ch = os.path.join(d, "docling", "chunks.json")
    if os.path.exists(ch):
        try:
            cj = json.load(open(ch))
            rec["chunks"] = len(cj) if isinstance(cj, list) else len(cj.get("chunks", []))
        except Exception:
            pass
    tot = 0
    for root, _, files in os.walk(d):
        for f in files:
            tot += os.path.getsize(os.path.join(root, f))
    rec["emitted_bytes"] = tot
    results.append(rec)

out = "score6_%s%s_%s.json" % (EXPORT, TAG, CLIENT)
with open(out, "w") as fh:
    json.dump(results, fh, indent=1, default=str)

print("%-20s %7s %7s %7s %7s %7s" % ("doc", "COMPOS", "compl", "simil", "struct", "clean"))
for r in results:
    s = r.get("score")
    if not s or s.get("composite") is None:
        print("%-20s   %s" % (r["stem"], r.get("error") or "not scored"))
        continue
    print("%-20s %7.1f %7.3f %7.3f %7.3f %7.3f" % (
        r["stem"], s["composite"], s["completeness"], s["similarity"],
        s["structure_match"], s["cleanliness"]["score"]))
scored = [r["score"] for r in results if r.get("score", {}).get("composite") is not None]
if scored:
    n = len(scored)
    print("%-20s %7.1f %7.3f %7.3f %7.3f %7.3f" % (
        "MEAN",
        sum(s["composite"] for s in scored) / n,
        sum(s["completeness"] for s in scored) / n,
        sum(s["similarity"] for s in scored) / n,
        sum(s["structure_match"] for s in scored) / n,
        sum(s["cleanliness"]["score"] for s in scored) / n))
print("\n-> %s" % out)
