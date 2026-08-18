#!/usr/bin/env python
"""Run docling-graph's real pipeline over the SIX REAL CONTRACTS.

Same deterministic rule-based extractor (`rule_client.RuleBasedClient`) and the
same extraction template (`dgtemplates.contract.Contract`) as the earlier mock
run, so the two are directly comparable: anything that differs here is caused by
the documents, not by the extractor.

No LLM. No model weights. Requires a warm HF cache for docling's chunker
tokenizer (all-MiniLM-L6-v2) -- run with HF_HUB_OFFLINE=1 to prove it.
"""
import json, os, sys, time, traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from docling_graph import run_pipeline
from docling_graph.config import PipelineConfig

# DG_CLIENT=doclang (default) uses the DocLang-aware extractor. `markdown` selects
# the original Markdown-regex client, kept switchable so the earlier run's numbers
# can be reproduced and the difference attributed to the instrument.
CLIENT_KIND = os.environ.get("DG_CLIENT", "doclang")
if CLIENT_KIND == "markdown":
    from rule_client import RuleBasedClient as Client
else:
    from rule_client6 import DocLangRuleClient as Client

# Ordered smallest -> largest so failures surface fast and the 166 KB
# Accenture MSA (the "complex doc") runs last.
INPUTS = [
    "in6/micro_crystal.md",
    "in6/evolving_solutions.md",
    "in6/dell.md",
    "in6/jabil.md",
    "in6/atl_technology.md",
    "in6/accenture.md",
]
EXPORT = os.environ.get("DG_EXPORT", "csv")
CONTRACT = os.environ.get("DG_CONTRACT", "direct")
TAG = os.environ.get("DG_TAG", "")  # set to "_run2" for the determinism repeat

summary = []
for src in INPUTS:
    stem = os.path.splitext(os.path.basename(src))[0]
    outdir = "out6/%s_%s_%s%s" % (stem, CONTRACT, EXPORT, TAG)
    # CONTRACT belongs in the call-log path: without it a `dense` run overwrites the
    # `direct` run's prompt logs for the same document, and the prompt-size evidence
    # for whichever ran first is silently lost.
    calldir = "calls6/%s%s_%s_%s" % (stem, TAG, CLIENT_KIND, CONTRACT)
    os.environ["DG_CALLLOG"] = calldir
    if CLIENT_KIND == "markdown":
        import rule_client as _rc
    else:
        import rule_client6 as _rc
    _rc.LOG = calldir
    os.makedirs(_rc.LOG, exist_ok=True)
    client = Client()
    cfg = PipelineConfig(
        source=src,
        template="dgtemplates.contract.Contract",
        backend="llm",
        inference="local",
        processing_mode=os.environ.get("DG_MODE", "many-to-one"),
        extraction_contract=CONTRACT,
        llm_client=client,
        gleaning_enabled=False,
        parallel_workers=1,
        provenance="detailed",
        export_format=EXPORT,
        output_dir=outdir,
        dump_to_disk=True,
        debug=True,
    )
    os.environ["DG_SOURCE"] = src
    rec = {"source": src, "stem": stem, "outdir": outdir, "client": CLIENT_KIND,
           "in_bytes": os.path.getsize(src), "contract": CONTRACT, "export": EXPORT}
    t0 = time.time()
    try:
        ctx = run_pipeline(cfg, mode="api")
        rec["seconds"] = round(time.time() - t0, 2)
        g = getattr(ctx, "knowledge_graph", None)
        rec["llm_calls"] = client.n
        rec["nodes"] = g.number_of_nodes() if g is not None else None
        rec["edges"] = g.number_of_edges() if g is not None else None
        rec["models"] = len(getattr(ctx, "extracted_models", []) or [])
        md = getattr(ctx, "graph_metadata", None)
        rec["graph_metadata"] = md if isinstance(md, dict) else (
            md.model_dump() if hasattr(md, "model_dump") else str(md))
        if g is not None:
            labels, etypes = {}, {}
            for _, d in g.nodes(data=True):
                lab = d.get("label") or d.get("node_type") or d.get("type") or "?"
                labels[lab] = labels.get(lab, 0) + 1
            for _, _, d in g.edges(data=True):
                et = d.get("label") or d.get("edge_label") or d.get("type") or "?"
                etypes[et] = etypes.get(et, 0) + 1
            rec["node_labels"] = labels
            rec["edge_labels"] = etypes
        # What the extractor itself saw -- pre-cap counts included, so any
        # saturation is attributable to the document or to the guard, not guessed at.
        rec["extractor_stats"] = getattr(client, "stats", None)
        rec["ok"] = True
    except Exception as e:
        rec["seconds"] = round(time.time() - t0, 2)
        rec["ok"] = False
        rec["error"] = "%s: %s" % (type(e).__name__, e)
        rec["trace"] = traceback.format_exc()[-2000:]
        rec["llm_calls"] = client.n
    summary.append(rec)
    print(json.dumps({k: v for k, v in rec.items() if k != "trace"}, indent=1, default=str),
          flush=True)
    if not rec["ok"]:
        print(rec.get("trace", ""), flush=True)

out = "run6_summary_%s_%s%s_%s.json" % (CONTRACT, EXPORT, TAG, CLIENT_KIND)
with open(out, "w") as fh:
    json.dump(summary, fh, indent=1, default=str)
print("\n== done: %d/%d ok -> %s ==" % (sum(1 for r in summary if r["ok"]), len(summary), out))
