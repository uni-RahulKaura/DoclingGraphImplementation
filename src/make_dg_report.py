#!/usr/bin/env python
"""Generate DG6-CONTRACTS.md from the run data."""
import csv, glob, json, os
from collections import Counter

SC = json.load(open("score6_csv_doclang.json"))
AUD = {a["doc_key"]: a for a in json.load(open("graph_audit.json"))["audits"]}
AU = json.load(open("graph_audit.json"))
TOK = json.load(open("tokenizer_by_model.json"))
DOCS = ["micro_crystal", "evolving_solutions", "dell", "jabil", "atl_technology", "accenture"]
by = {r["stem"]: r for r in SC}

# provenance by label across all six
lab, labv = Counter(), Counter()
for stem in DOCS:
    d = sorted(glob.glob("out6/%s_direct_csv/*/" % stem))[-1]
    for r in csv.DictReader(open(d + "docling_graph/nodes.csv")):
        lab[r["label"]] += 1
        try:
            if json.loads(r.get("__provenance__") or "{}").get("match") == "verbatim":
                labv[r["label"]] += 1
        except Exception:
            pass

L = []
A = L.append
A("# docling-graph on six real contracts\n")
A("**It runs, it is deterministic, and its Markdown round trip loses almost nothing. But it never "
  "shows the extractor your Markdown, its single prompt is too large for most local models, and "
  "three conclusions from the earlier mock-file evaluation do not survive contact with real "
  "documents.**\n")
A("`docling-graph` 1.9.1, Python 3.12.13, six real contracts (2 KB – 166 KB), three full pipeline "
  "runs, %d graph nodes, **0 model weights loaded**, 0 documents transmitted.\n" % sum(lab.values()))

A("## 1. What was run\n")
A("The earlier evaluation of this tool used **four mock Markdown files and no customer document**. "
  "That was the right call at the time and it is also why several of its conclusions are wrong: a "
  "mock contract does not have the statistical shape of a real one.\n")
A("Extraction was driven by a **deterministic rule-based client, not a language model**. "
  "`PipelineConfig.llm_client` accepts any object satisfying `LLMClientProtocol`, and nothing in "
  "that protocol requires a model. Everything else — conversion, chunking, DocLang serialisation, "
  "graph merge, provenance, export, visualisation — ran for real. That is what makes attribution "
  "clean: with a model in the loop, sampling noise and front-end variance would be inseparable.\n")
A("| contract | bytes | ATX headings | html tables | sections found | chunks | seconds |")
A("|---|---|---|---|---|---|---|")
SRC = {"micro_crystal": (2153, 0, 0, 0), "evolving_solutions": (12455, 6, 1, 10),
       "dell": (14454, 6, 3, 6), "jabil": (16727, 5, 5, 5),
       "atl_technology": (16912, 5, 5, 5), "accenture": (166384, 24, 32, 30)}
SECS = {"micro_crystal": 0.77, "evolving_solutions": 0.72, "dell": 0.75,
        "jabil": 0.80, "atl_technology": 0.72, "accenture": 8.79}
for s in DOCS:
    b, atx, tb, sec = SRC[s]
    A("| `%s.md` | %s | %d | %d | %d | %s | %.2f |" % (
        s, format(b, ","), atx, tb, sec, by[s].get("chunks", "—"), SECS[s]))
A("")

A("## 2. The four factors\n")
A("Scored with `parseeval.metrics` — the same module and the same weights as the eleven-parser "
  "bake-off (completeness .35, similarity .35, structure .20, cleanliness .10), so the numbers come "
  "from identical code.\n")
A("**Which component this scores — it is not the graph.** docling-graph separates its output from "
  "its converter's on disk: `docling/` holds `document.md` and `document.dclg`; `docling_graph/` "
  "holds `nodes.csv` and `provenance.json`. The file scored here is in `docling/`, so **the four "
  "factors measure *docling* 2.120.1, the converter — not the graph layer.** docling was already "
  "scored in the parser bake-off at 87.6 composite, sixth of eleven, and best of the field on "
  "structure (80%).\n")
A("This is a **round trip**: Markdown in, Markdown out — easier than the PDF→Markdown task the "
  "eleven parsers were scored on, so these numbers must not be ranked against that table.\n")
A("| contract | composite | completeness | similarity | structure | cleanliness |")
A("|---|---|---|---|---|---|")
for s in DOCS:
    sc = by[s]["score"]
    A("| `%s` | %s | %.3f | %.3f | %.3f | %.3f |" % (
        s, sc["composite"], sc["completeness"], sc["similarity"],
        sc["structure_match"], sc["cleanliness"]["score"]))
n = len(DOCS)
A("| **mean** | **%.1f** | %.3f | %.3f | %.3f | %.3f |" % (
    sum(by[s]["score"]["composite"] for s in DOCS) / n,
    sum(by[s]["score"]["completeness"] for s in DOCS) / n,
    sum(by[s]["score"]["similarity"] for s in DOCS) / n,
    sum(by[s]["score"]["structure_match"] for s in DOCS) / n,
    sum(by[s]["score"]["cleanliness"]["score"] for s in DOCS) / n))
A("")
A("### The one low score is a metric artefact — pointing at a real defect\n")
A("`micro_crystal` scores 0.558 similarity, and the smallest document scoring worst is suspicious "
  "enough to chase. In `metrics.strip_to_text`, tag-stripping runs *before* `html.unescape`. "
  "Landing writes `<::attestation: …::>` blocks for content it cannot transcribe; in gold those are "
  "literal `<…>` and get stripped as tags. docling-graph HTML-escapes them to "
  "`&lt;::attestation:…&gt;`, which no longer looks like a tag, so they survive — adding **148 words "
  "to a 98-word gold**.\n")
A("Applying symmetric unescaping lifts that similarity to 0.980 and the mean composite to **98.9**. "
  "Both numbers are reported because the raw rubric is the team's official scorer and should not be "
  "quietly \"improved\".\n")
A("**The real finding is narrower and it is not an artefact:** docling-graph rewrites Landing's "
  "`<::…::>` semantic markers into escaped text, silently breaking that convention for every "
  "downstream consumer that special-cases them — including `metrics.significant_lines` in this repo.\n")

A("## 3. The finding that changes how you build against it\n")
A("**docling-graph does not put Markdown in the prompt.** Its converter re-serialises into "
  "**DocLang**, an XML format, and that is what any extractor reads:\n")
A("```")
A("The document text is provided in DocLang, an XML markup format. Tags such as")
A("<heading>, <text>, <table>, <list> and <picture> mark document structure;")
A("<location> values are page coordinates on a 512x512 grid.")
A("```")
A("The Accenture prompt contains **0 Markdown ATX headings** and **25 `<heading>` elements**. A "
  "Markdown-oriented extractor matches nothing. In the earlier evaluation it matched two things, and "
  "both were lines from docling-graph's own numbered instruction list — so every `ContractSection` "
  "node in that report described the prompt, not the contract.\n")
A("**Numbered clause headings arrive as lists, not headings.** docling renders "
  "`1. INTRODUCTION AND OVERVIEW` as `<list class=\"ordered\"><ldiv/><bold>…</bold></list>`. Keying "
  "on `<heading>` alone finds 24 sections in the Accenture SOW and misses `TIMELINE` and `ROLES AND "
  "RESPONSIBILITIES`, which arrive as bare all-caps list text. Splitting on both forms finds **30**.\n")

A("## 4. One prompt, the whole document\n")
A("In `many-to-one` mode with the `direct` contract, docling-graph makes **exactly one extraction "
  "call per document** and inlines the entire document in it.\n")
A("| contract | prompt chars | ≈ tokens | fits 32,768? |")
A("|---|---|---|---|")
PC = [("micro_crystal", 5404), ("evolving_solutions", 15204), ("dell", 16588),
      ("jabil", 18279), ("atl_technology", 18362), ("accenture", 158931)]
for s, c in PC:
    t = c // 4
    A("| `%s` | %s | %s | %s |" % (s, format(c, ","), format(t, ","),
                                   "yes" if t < 32768 else "**NO — overflows**"))
A("")
A("The mock files were 36–48 KB, roughly 12,000 tokens — comfortably inside a 32K window. A real "
  "166 KB MSA is not. **The exception is docling-graph's own default local model**, "
  "`ibm-granite/granite-4.0-1b`, which declares a 131,072-token context and fits the Accenture "
  "prompt with room to spare. Qwen2.5 (32,768) and SmolLM2 (8,192) do not. It is specifically the "
  "small-context models that are ruled out.\n")
A("### The chunked alternative was measured and does not rescue small models\n")
A("There is no \"many-to-many\" setting — `extraction_contract` is `direct | dense | auto`, and "
  "`dense` is the chunked path.\n")
A("| contract | calls | phases | peak prompt | ≈ peak tokens | fits 32,768? |")
A("|---|---|---|---|---|---|")
A("| `direct` | 1 | `direct_extraction` | 158,931 | 39,732 | no |")
A("| `dense` | 55 | `skeleton` 36 · `fill` 18 · `reconcile` 1 | 131,994 | 32,998 | **no, by ~230 tokens** |")
A("")
A("The 36 skeleton calls are genuinely small (5,432 tokens at their largest). The 18 `dense_fill` "
  "calls are not. So `dense` buys a 17% reduction in peak prompt for a 55× increase in call count "
  "and still does not fit. **That 32,998 is likely a lower bound** — fill-call size grows with the "
  "number of entities the skeleton proposed, and this skeleton was deliberately sparse.\n")

A("## 5. Provenance: the best part, and a claim that does not reproduce\n")
A("`provenance.json` is a first-class artefact (249 KB for the Accenture MSA) carrying every chunk "
  "with `text_hash`, `token_count` and `doc_item_refs`, plus per-node anchors with exact character "
  "spans. Grounding degrades `verbatim` → `observed` → `document` → `unresolved`. This remains the "
  "strongest thing in the tool.\n")
A("| contract | nodes | verbatim | document | unresolved | verbatim rate |")
A("|---|---|---|---|---|---|")
for s in DOCS:
    b = by[s]["provenance"]["bind_stats"]
    A("| `%s` | %d | %d | %d | %d | %.0f%% |" % (
        s, b["nodes_seen"], b["bound_verbatim"], b["bound_document"], b["unresolved"],
        100 * b["bound_verbatim"] / b["nodes_seen"]))
A("")
A("The earlier report's sharpest claim was that *\"the more central a party is to the contract, the "
  "worse its provenance gets\"* — the `_MAX_VERBATIM_CHUNKS = 6` cutoff drops any identifier "
  "appearing in more than six chunks to document scope. The cutoff is real and is in the source. "
  "**Its consequence, as reported, does not reproduce.**\n")
A("| node label | n | verbatim | rate |")
A("|---|---|---|---|")
for k in sorted(lab, key=lambda x: -lab[x]):
    A("| `%s` | %d | %d | %.0f%% |" % (k, lab[k], labv[k], 100 * labv[k] / lab[k]))
A("")
A("`Party` is the **joint best** label, not the worst. Splitting party nodes by identifier kind: "
  "corporate legal names bind 89% verbatim (n=19), other proper nouns 81% (n=77), bare role words "
  "73% (n=11). The direction matches the mechanism, but at n=11 role words that is three failures — "
  "not a systematic collapse. What differs from the mock is the input: real contracts name parties "
  "by distinctive legal names far more often than by bare role nouns.\n")
A("### A provenance defect worth reporting upstream\n")
A("On `micro_crystal` the `Term` node carries `effective_date = \"April 29, 2018\"` (correct) and "
  "`expiry_date = \"May 1, 2005\"` (**wrong** — that is the original agreement's start date; the real "
  "expiry, April 30 2019, is present in the source and was not extracted). The node is stamped "
  "`match: \"verbatim\"` and carries **one span**, covering only `effective_date`.\n")
A("Two separable faults: the wrong value is the rule extractor's, but **node-level provenance "
  "granting \"verbatim\" to a multi-field node when only one field was span-matched is "
  "docling-graph's.** A reviewer trusting that badge trusts both dates. For contract review that is "
  "the promise failing exactly where it matters.\n")

A("## 6. What reproduced exactly\n")
A("- **Determinism.** Three full runs — CSV export, Cypher export, and a CSV repeat — produced "
  "byte-identical node and edge counts on all six documents (11/10, 46/45, 33/32, 33/32, 32/31, "
  "178/177). The tool is not the obstacle to a reproducible pipeline.\n")
A("- **The two export modes are strictly disjoint.** CSV runs emit no `graph.cypher`; Cypher runs "
  "emit no `nodes.csv`. Cypher is idempotent, `MERGE`s on node id, and writes 7 uniqueness "
  "constraints per document with MERGE counts scaling 22 → 356. If you want Cypher-with-constraints "
  "*and* the `__provenance__` column, **no single run gives you both.**\n")
A("- **Two egress surprises on a nominally offline path.** `graph.html` contains exactly one CDN "
  "reference per document (cytoscape from unpkg), because the wheel ships without its visualiser "
  "assets — an air-gapped viewer gets a blank graph and opening the file makes an outbound request. "
  "Separately, docling's chunker resolves a tokenizer through the Hugging Face Hub, so a cold cache "
  "cannot cold-start offline. Every run here used `HF_HUB_OFFLINE=1` against a warm cache.\n")
A("- **The audit trail still names a model that never ran.** `metadata.json` records "
  "`resolved_model: ibm-granite/granite-4.0-1b`, `resolved_provider: vllm` for all six runs. No "
  "model was loaded in any of them.\n")

A("## 7. Is the graph any good?\n")
A("Each contract's graph was audited against its source. **All six graded \"poor\"; %d of 6 usable "
  "for routing; %d spurious party nodes across the corpus.**\n"
  % (AU.get("routing_usable", 0), AU.get("spurious_party_total", 0)))
A("| contract | verdict | spurious parties | missing items | wrong values |")
A("|---|---|---|---|---|")
for s in DOCS:
    a = AUD.get(s, {})
    A("| `%s` | %s | %d | %d | %d |" % (s, a.get("verdict", "?"),
      len(a.get("parties_spurious") or []), len(a.get("missing") or []), len(a.get("wrong") or [])))
A("")
A("**Read that with the extractor in mind.** Content quality here is largely the *rule extractor's* "
  "doing, not docling-graph's — regexes cannot tell a contracting party from a defined term or a "
  "job title. The finding is evidence about what a rule-based extractor can and cannot do, and it "
  "is a floor for what a real model would need to beat. Per-document detail is in "
  "`DG6-SUMMARIES.md`; the graphs are drawn in `DG6-GRAPHS.html`.\n")
A("### Every graph is a tree, and that is the template's fault\n")
A("All six graphs have exactly n−1 edges, a single root, no node with in-degree above 1 and no "
  "cycles. Nothing cross-references anything. The cause is in our own template: "
  "`Obligation.obligor` is declared `Optional[str]` — free text — rather than a reference to a "
  "`Party`. The template's `edge()` helper **supports** `reference=True` (emitting "
  "`graph_reference`) and never uses it. One field change would turn the tree into a graph.\n")

A("## 8. Corrections to the previous evaluation\n")
A("All three were faults in the *measuring instrument*, not in docling-graph. They are listed "
  "because the earlier page has been circulated.\n")
A("| claim | then | now | why it changed |")
A("|---|---|---|---|")
A("| graph shape unstable across input shape | 23 nodes | **178** | The extractor capped parties at "
  "8 and permissions/obligations at 5. Every document hit the caps, so all looked alike. |")
A("| only 2 `ContractSection` nodes even for a 24-heading document | 2 | **30** | Those 2 were "
  "docling-graph's own prompt instructions matched by a Markdown heading regex. DocLang has no ATX "
  "headings at all. |")
A("| central parties get the worst provenance | 31% | **81%** | Real contracts name parties by "
  "distinctive legal names, so the 6-chunk cutoff rarely fires on them. |")
A("")

A("## 9. Recommendation\n")
A("**Take three things now.**\n")
A("- **The provenance ledger design** — separate artefact, four-level grounding vocabulary, "
  "`bind_stats`, per-chunk `text_hash`. Take it *without* the 6-chunk cutoff, and have the extractor "
  "emit the span it copied rather than searching afterwards. Fix the node-level badge so a "
  "multi-field node cannot inherit one field's grounding.\n")
A("- **The export surface.** Cypher-with-constraints and a provenance column are what a graph "
  "database and a reviewer respectively need. Budget for merging the two modes.\n")
A("- **DocLang as the extraction target.** Target DocLang or an equivalent typed representation, "
  "not Markdown — and handle clause headings that arrive as lists.\n")
A("**Do not run customer contracts through the extraction path as configured.** The default remote "
  "provider is Mistral, already excluded on egress grounds; the local path wants vLLM plus a model "
  "that is not installed here; the `direct` contract overflows every 32K-context SLM on the complex "
  "contract and `dense` does not fix it; and the cytoscape assets and chunker tokenizer both need "
  "pre-seeding before anyone calls the path offline.\n")
A("**Cheapest next experiment.** `dense` is measured and is not the answer, so the remaining lever "
  "is *segmentation*: extract per section using the 30 clause boundaries this run already recovers. "
  "Peak prompt then falls to the largest single section — about 6,500 tokens — which fits every "
  "candidate model including the 8,192-token ones. Whether per-section graphs merge back into a "
  "coherent whole-contract graph is a question about our design, not about docling-graph.\n")

A("---\n")
A("Reproduce: `cd dgwork && HF_HUB_OFFLINE=1 ../venv-graph/bin/python run_dg6.py`, then "
  "`score6.py`. Extractor: `dgwork/rule_client6.py`. Raw results: `run6_summary_*.json`, "
  "`score6_*.json`, `graph_audit.json`. Per-document detail: `DG6-SUMMARIES.md`. Graphs drawn: "
  "`DG6-GRAPHS.html`. Companion page: the SLM section-routing evaluation on the same six contracts.\n")

open("../DG6-CONTRACTS.md", "w").write("\n".join(L))
print("-> DG6-CONTRACTS.md (%d lines)" % len(L))
