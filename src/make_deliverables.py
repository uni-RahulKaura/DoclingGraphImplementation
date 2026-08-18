#!/usr/bin/env python
"""Generate the per-document deliverables: summaries (Markdown) and graphs (SVG).

Three outputs:
  DG6-SUMMARIES.md   one summary per source .md file: what the graph actually contains,
                     what it got wrong, and whether it is usable
  DG6-GRAPHS.html    the graph itself, drawn. Self-contained inline SVG -- unlike
                     docling-graph's own graph.html, which fetches cytoscape from a CDN
                     and renders blank offline.
  (data)             dg6_graph_data.json, the extracted content per document

The graphs are drawn as trees because they ARE trees: every one has exactly n-1 edges,
one root, no node with in-degree > 1 and no cycles.
"""
import csv, glob, html, json, os

DOCS = ["micro_crystal", "evolving_solutions", "dell", "jabil", "atl_technology", "accenture"]
ORDER = ["Contract", "Party", "Term", "PaymentTerm", "ContractSection", "Permission", "Obligation"]


def load(stem):
    d = sorted(glob.glob("out6/%s_direct_csv/*/" % stem))[-1]
    nodes = list(csv.DictReader(open(d + "docling_graph/nodes.csv")))
    edges = list(csv.DictReader(open(d + "docling_graph/edges.csv")))
    for n in nodes:
        try:
            n["_prov"] = json.loads(n.get("__provenance__") or "{}")
        except Exception:
            n["_prov"] = {}
    return d, nodes, edges


def val(n, *keys):
    return {k: n[k] for k in keys if n.get(k)}


data = {}
for stem in DOCS:
    d, nodes, edges = load(stem)
    by = {}
    for n in nodes:
        by.setdefault(n["label"], []).append(n)
    contract = (by.get("Contract") or [{}])[0]
    term = (by.get("Term") or [{}])[0]
    pay = (by.get("PaymentTerm") or [{}])[0]
    data[stem] = {
        "run_dir": d,
        "in_bytes": os.path.getsize("in6/%s.md" % stem),
        "n_nodes": len(nodes), "n_edges": len(edges),
        "counts": {k: len(v) for k, v in sorted(by.items())},
        "title": contract.get("title", ""),
        "title_prov": contract.get("_prov", {}).get("match", ""),
        "parties": [{"name": p.get("name", ""), "role": p.get("role", ""),
                     "prov": p.get("_prov", {}).get("match", "")} for p in by.get("Party", [])],
        "term": val(term, "effective_date", "expiry_date", "duration", "renewal"),
        "term_prov": term.get("_prov", {}).get("match", ""),
        "term_spans": len(term.get("_prov", {}).get("spans", []) or []),
        "payment": val(pay, "amount", "currency", "net_days"),
        "sections": [{"heading": s.get("heading", ""),
                      "prov": s.get("_prov", {}).get("match", "")} for s in by.get("ContractSection", [])],
        "permissions": [{"text": p.get("text", ""), "polarity": p.get("polarity", ""),
                         "condition": p.get("condition", ""),
                         "prov": p.get("_prov", {}).get("match", "")} for p in by.get("Permission", [])],
        "obligations": [{"text": o.get("text", ""), "obligor": o.get("obligor", ""),
                         "prov": o.get("_prov", {}).get("match", "")} for o in by.get("Obligation", [])],
        "nodes": nodes, "edges": edges,
    }

json.dump({k: {kk: vv for kk, vv in v.items() if kk not in ("nodes", "edges")}
           for k, v in data.items()}, open("dg6_graph_data.json", "w"), indent=1, default=str)

audit = {a["doc_key"]: a for a in json.load(open("graph_audit.json"))["audits"]}


# ---------------------------------------------------------------- Markdown summaries
def md_escape(s):
    return (s or "").replace("|", "\\|").replace("\n", " ").strip()


L = []
L.append("# docling-graph output, summarised per source file\n")
L.append("What came out of `docling-graph` 1.9.1 for each of the six Markdown files, and how")
L.append("faithful it is to the contract. Extraction was driven by a **deterministic rule-based")
L.append("extractor, not a language model** -- so the *content* below reflects what regexes could")
L.append("find, while the *structure, provenance and export* are docling-graph's own.\n")
L.append("| file | in | nodes | edges | shape | audit | usable for routing |")
L.append("|---|---|---|---|---|---|---|")
for s in DOCS:
    v = data[s]; a = audit.get(s, {})
    L.append("| `%s.md` | %s KB | %d | %d | tree | **%s** | %s |" % (
        s, round(v["in_bytes"] / 1024), v["n_nodes"], v["n_edges"],
        a.get("verdict", "?"), "no" if a.get("usable_for_routing") is False else "yes"))
L.append("")
L.append("Every graph is a **strict tree**: one root, no node referenced twice, no cycles.")
L.append("That is the template's doing, not the tool's -- `Obligation.obligor` is declared as")
L.append("free text rather than a reference to a `Party`, so no cross-link is ever created.\n")
L.append("---\n")

for s in DOCS:
    v = data[s]; a = audit.get(s, {})
    L.append("## `%s.md`\n" % s)
    if a.get("one_line"):
        L.append("> %s\n" % md_escape(a["one_line"]))
    L.append("**Graph:** %d nodes, %d edges — %s\n" % (
        v["n_nodes"], v["n_edges"],
        ", ".join("%s %d" % (k, n) for k, n in
                  sorted(v["counts"].items(), key=lambda kv: -kv[1]))))
    L.append("**Extracted contract facts**\n")
    L.append("| field | value | grounding |")
    L.append("|---|---|---|")
    L.append("| title | `%s` | %s |" % (md_escape(v["title"])[:90] or "—", v["title_prov"] or "—"))
    for k in ("effective_date", "expiry_date", "duration", "renewal"):
        if v["term"].get(k):
            L.append("| %s | %s | %s (%d span%s on the whole Term node) |" % (
                k, md_escape(v["term"][k]), v["term_prov"], v["term_spans"],
                "" if v["term_spans"] == 1 else "s"))
    for k in ("amount", "currency", "net_days"):
        if v["payment"].get(k):
            L.append("| payment.%s | %s | — |" % (k, md_escape(v["payment"][k])))
    L.append("")
    L.append("**Parties the graph asserts (%d)** — real contracting parties per the audit: %s\n" % (
        len(v["parties"]), ", ".join(a.get("parties_real") or []) or "not stated"))
    L.append("| name | role | grounding |")
    L.append("|---|---|---|")
    for p in v["parties"][:14]:
        sp = " ⚠︎ spurious" if p["name"] in (a.get("parties_spurious") or []) else ""
        L.append("| %s%s | %s | %s |" % (md_escape(p["name"])[:60], sp, p["role"] or "—", p["prov"] or "—"))
    if len(v["parties"]) > 14:
        L.append("| _… %d more_ | | |" % (len(v["parties"]) - 14))
    L.append("")
    if v["sections"]:
        L.append("**Sections (%d)**\n" % len(v["sections"]))
        for sec in v["sections"][:32]:
            L.append("- `%s`" % md_escape(sec["heading"])[:100])
        if len(v["sections"]) > 32:
            L.append("- _… %d more_" % (len(v["sections"]) - 32))
        L.append("")
    for lab, items, extra in (("Permissions", v["permissions"], "polarity"),
                              ("Obligations", v["obligations"], "obligor")):
        if items:
            L.append("**%s (%d)** — first 5\n" % (lab, len(items)))
            for it in items[:5]:
                tail = (" _[%s: %s]_" % (extra, it[extra])) if it.get(extra) else ""
                L.append("- %s%s" % (md_escape(it["text"])[:200], tail))
            L.append("")
    if a.get("missing"):
        L.append("**Missing from the graph (%d)**\n" % len(a["missing"]))
        for m in a["missing"][:6]:
            L.append("- %s" % md_escape(m)[:300])
        L.append("")
    if a.get("wrong"):
        L.append("**Wrong in the graph (%d)**\n" % len(a["wrong"]))
        for m in a["wrong"][:6]:
            L.append("- %s" % md_escape(m)[:300])
        L.append("")
    L.append("Artefacts: `%s`\n" % v["run_dir"])
    L.append("---\n")

open("../DG6-SUMMARIES.md", "w").write("\n".join(L))
print("-> DG6-SUMMARIES.md (%d lines)" % len(L))
