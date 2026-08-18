# Running docling-graph over contracts, without a language model

An implementation write-up of how we drove
[docling-graph](https://github.com/docling-project/docling-graph) 1.9.1 over six real
contracts and got a knowledge graph out of each, **with no language model and no model
weights loaded at all**.

This repository contains the code, the method, and the aggregate results. The six source
contracts and their graph outputs are deliberately **not** included — see
[What is not here](#what-is-not-here).

---

## The problem

docling-graph's extraction step requires a language model by construction.
`ExtractorFactory` refuses to build its LLM backend without a client
(`core/extractors/factory.py`: *"LLM requires llm_client parameter"*), and the alternative
`vlm` backend is a vision model, not an escape.

Its defaults did not suit us either:

| Default | Value | Why that was a problem |
|---|---|---|
| Remote provider | `mistral` / `mistral-small-latest` | Mistral is already excluded for customer contracts on egress grounds |
| Local provider | `vllm` / `ibm-granite/granite-4.0-1b` | vLLM is not installed, and neither is ollama, llama.cpp or MLX |

With nothing listening, `docling-graph convert -i local` fails as
`ExtractionError ... reason=no_models_extracted` — an error that blames extraction rather
than saying "nothing answered on localhost:8000".

## The way through

`PipelineConfig.llm_client` accepts **any object** satisfying `LLMClientProtocol`, and the
extraction stage prefers it over provider resolution. The protocol needs one real method:

```python
def get_json_response(self, prompt, schema_json, structured_output=True,
                      response_top_level="object",
                      response_schema_name="extraction_result") -> dict | list
```

Nothing in that contract requires a language model. So
[`src/rule_client6.py`](src/rule_client6.py) implements it with **12 regular expressions** —
parties, dates, durations, money, `net N`, headings, and modal-verb clauses for permissions
and obligations — and returns schema-shaped JSON. It even reports itself honestly as
`model = "doclang-rule-based/none"`.

docling-graph could not tell the difference. **Everything else in it ran for real:**

| Component | Who did it |
|---|---|
| document conversion, chunking, DocLang serialisation | docling 2.120.1 |
| graph merge, provenance, CSV/Cypher export, HTML visualiser | docling-graph 1.9.1 |
| the extraction step | **our regexes** |

### Why bother doing it this way

A language model gives different answers on different runs, so you cannot tell the tool's
behaviour apart from the model's randomness. With a deterministic extractor, **three full
runs produced byte-identical node and edge counts on all six documents.** Every difference
between documents is therefore provably docling-graph's doing, not sampling noise.

The cost is real and worth stating: regexes cannot tell a company that *signed* a contract
from one merely *mentioned* in it. The graph content below is a floor, not a ceiling — it is
what the plumbing does when the semantics are as dumb as possible.

## Was a language model involved? No.

- **No weight files** anywhere in the environment — searched for `.safetensors` and
  `pytorch_model.bin`, found none.
- The only download was **700 KB**: `vocab.txt`, `tokenizer.json` and configs for
  `sentence-transformers/all-MiniLM-L6-v2`. That is docling-graph's chunker tokenizer,
  hardcoded at `core/extractors/document_chunker.py:77`, and its own source comment says it
  is used *"only for token counting and chunk splitting, not for the model"*. A tokenizer is
  a word list, not a model.
- Every run used `HF_HUB_OFFLINE=1` against a warm cache and added nothing to it.
- Each run logged `llm_calls=1` — one call to our own regex client, per document.

---

## How to run it

Requires Python **3.10+** (docling-graph declares `>=3.10,<4.0`; on 3.9 pip filters out every
version and reports "no matching distribution", which reads like the package does not exist).

```bash
python -m venv venv-graph && ./venv-graph/bin/pip install docling-graph==1.9.1

# put one or more Markdown files in in6/
mkdir -p in6 && cp sample/mock_supply_agreement.md in6/

# a warm tokenizer cache is a prerequisite -- see the air-gap note below
cd src && HF_HUB_OFFLINE=1 python run_dg6.py            # CSV export
DG_EXPORT=cypher HF_HUB_OFFLINE=1 python run_dg6.py     # Cypher export
DG_CONTRACT=dense HF_HUB_OFFLINE=1 python run_dg6.py    # the chunked path
python score6.py                                        # four-factor scoring
```

`sample/mock_supply_agreement.md` is a synthetic contract written for this repository. It
exercises every path — parties, a term with dates, payment terms, obligations, restrictions,
numbered sections and an HTML table — so the pipeline can be run end to end without any real
document.

### Files

| File | What it is |
|---|---|
| `src/rule_client6.py` | The deterministic `LLMClientProtocol` implementation. **This is the interesting file.** |
| `src/rule_client.py` | The first version, kept deliberately — it was written against Markdown and is *wrong*. See below. |
| `src/run_dg6.py` | Runner: builds `PipelineConfig` per document, injects the client, records graph shape |
| `src/dgtemplates/contract.py` | The extraction template — parties, term, permissions, obligations, payment |
| `src/score6.py` | Four-factor scoring, importing `metrics.py` unmodified |
| `src/metrics.py`, `src/config.py` | The scoring rubric (completeness .35, similarity .35, structure .20, cleanliness .10) |
| `src/build_sections.py` | Splits documents into sections on DocLang headings |
| `src/make_graphs.py` | Draws each graph as self-contained inline SVG |
| `src/make_dg_report.py`, `src/make_deliverables.py` | Generate the reports from the result JSON |

---

## What we found

### The finding that changes how you build against it

**docling-graph does not put Markdown in the prompt.** Its converter re-serialises the
document into **DocLang**, an XML format:

```
The document text is provided in DocLang, an XML markup format. Tags such as
<heading>, <text>, <table>, <list> and <picture> mark document structure;
<location> values are page coordinates on a 512x512 grid.
```

Our largest document's prompt contained **0 Markdown ATX headings** and **25 `<heading>`
elements**. A Markdown-oriented extractor matches nothing.

`src/rule_client.py` is kept in this repo as the cautionary version. It searched for
`^#{1,6}` headings, found two things in a 166 KB contract, and both were lines from
docling-graph's *own numbered instruction list* — "Read the provided document text
carefully." So every `ContractSection` node it produced described the prompt, not the
contract. That failure is worth keeping visible: it is exactly the failure a language model
would have made silently and plausibly.

**Numbered clause headings arrive as lists, not headings.** docling renders
`1. INTRODUCTION AND OVERVIEW` as
`<list class="ordered"><ldiv/><bold>…</bold></list>`. Keying on `<heading>` alone found 24
sections in our largest document and missed two more that carry the same role as bare
all-caps list text. Splitting on both forms found **30**.

### One prompt holds the whole document

In `many-to-one` mode with the `direct` contract, docling-graph makes **exactly one
extraction call per document** and inlines the entire document in it.

| Document size | Prompt chars | ≈ tokens | Fits a 32,768 window? |
|---|---|---|---|
| 2 KB | 5,404 | 1,350 | yes |
| 12–17 KB | 15,204 – 18,362 | 3,800 – 4,590 | yes |
| **166 KB** | **158,931** | **≈39,700** | **no** |

So the default path cannot be served by any 32K-context small model on a large contract.
The exception is docling-graph's own default local model, `ibm-granite/granite-4.0-1b`, which
declares a 131,072-token context and fits it with room to spare.

**The chunked alternative does not fix it.** There is no "many-to-many" setting —
`extraction_contract` is `direct | dense | auto`. Measured:

| Contract | Calls | Phases | Peak prompt | ≈ peak tokens |
|---|---|---|---|---|
| `direct` | 1 | `direct_extraction` | 158,931 | 39,732 |
| `dense` | 55 | `skeleton` 36 · `fill` 18 · `reconcile` 1 | 131,994 | **32,998** |

`dense` buys a 17% reduction in peak prompt for a 55× increase in call count, and still
exceeds a 32,768 window. That 32,998 is likely a **lower bound** — `dense_fill` prompt size
grows with how many entities the skeleton phase proposed, and ours was deliberately sparse.

### Provenance is the best part of the tool

`provenance.json` is a first-class artefact — 249 KB for a 166 KB document — carrying every
chunk with `text_hash`, `token_count` and `doc_item_refs`, plus per-node anchors with exact
character spans. Grounding degrades through declared levels: `verbatim` → `observed` →
`document` → `unresolved`, and the tallies are written to `bind_stats`.

Across 333 nodes from six documents:

| Node label | n | bound verbatim | rate |
|---|---|---|---|
| `Party` | 107 | 87 | 81% |
| `ContractSection` | 57 | 46 | 81% |
| `Obligation` | 81 | 52 | 64% |
| `Permission` | 70 | 44 | 63% |
| `Term` | 6 | 6 | 100% |
| `PaymentTerm` | 6 | 1 | 17% |
| `Contract` | 6 | 1 | 17% |

### A provenance defect worth reporting upstream

On one document the `Term` node carried `effective_date` (correct) and `expiry_date`
(**wrong** — it picked up the *original* agreement's start date instead of the new expiry,
which was present in the source and simply not extracted). The node was stamped
`match: "verbatim"` and carried **one span**, covering only `effective_date`.

Two separable faults. The wrong value is our regex extractor's. But **node-level provenance
granting "verbatim" to a multi-field node when only one field was span-matched is
docling-graph's** — a reviewer trusting that badge trusts both dates. For contract review
that is the promise failing exactly where it matters.

### Every graph is a tree, and that is our template's fault

All six graphs came out with exactly n−1 edges, a single root, no node with in-degree above
1, and no cycles. Nothing cross-references anything.

The cause is in `src/dgtemplates/contract.py`: `Obligation.obligor` is declared
`Optional[str]` — free text — rather than a reference to a `Party`. The template's own
`edge()` helper **supports** `reference=True` (emitting `graph_reference`) and never uses it.
One field change would turn the tree into a real graph.

### Other things that reproduced

- **Determinism.** Three full runs — CSV, Cypher, and a CSV repeat — produced byte-identical
  node and edge counts on all six documents.
- **The two export modes are strictly disjoint.** CSV runs emit no `graph.cypher`; Cypher
  runs emit no `nodes.csv`. Cypher is idempotent, `MERGE`s on node id, and writes 7 uniqueness
  constraints per document. If you want Cypher-with-constraints *and* the `__provenance__`
  column, **no single run gives you both.**
- **Two egress surprises on a nominally offline path.** `graph.html` contains one CDN
  reference per document (cytoscape from unpkg) because the wheel ships without its visualiser
  assets — an air-gapped viewer gets a blank graph, and opening the file makes an outbound
  request. Separately, docling's chunker resolves its tokenizer through the Hugging Face Hub,
  so a **cold cache cannot cold-start offline**: with an empty `HF_HOME` and
  `HF_HUB_OFFLINE=1`, conversion succeeds but the chunker raises
  `OSError: We couldn't connect to 'https://huggingface.co'` before extraction is reached.
  A restricted-egress deployment must pre-seed that tokenizer.
- **The audit trail names a model that never ran.** `metadata.json` records
  `resolved_model: ibm-granite/granite-4.0-1b`, `resolved_provider: vllm` for every run. No
  model was loaded in any of them. `llm_client` is `exclude=True` in the config model, so the
  injected client is invisible to serialisation while the *unused* provider defaults are
  written down as if authoritative.
- **`processing_mode="one-to-one"` silently produces nothing on Markdown.** One-to-one means
  one graph per *page*; Markdown has no pages, so the strategy iterates an empty list and
  fails as `no_models_extracted` without ever calling the extractor.

### Round-trip fidelity of the conversion

Scored with the same rubric and code as our eleven-parser bake-off — completeness .35,
similarity .35, structure .20, cleanliness .10. **This scores `docling`, the converter, not
docling-graph's graph layer**: the file measured is `docling/document.md`, and docling-graph
keeps its own output in a separate `docling_graph/` directory.

Mean composite **95.4**, or **98.9** once a scoring artefact is removed. The artefact is
worth knowing about: `metrics.strip_to_text` strips tags *before* unescaping HTML, and
docling-graph HTML-escapes our source's `<::…::>` semantic markers, so those markers survive
in the candidate while being stripped from the gold. That inflated one small document by 148
words against a 98-word gold.

The escaping itself is a real finding, separate from the artefact: docling-graph rewrites
those markers, silently breaking that convention for any downstream consumer that
special-cases them.

---

## What is not here

The six source contracts, their graph outputs (`nodes.csv`, `edges.csv`,
`provenance.json`), and the prompt logs are **not** in this repository. Those artefacts
reproduce contract text verbatim — the prompt logs contain entire documents, and the graph
nodes carry clauses word-for-word.

Everything needed to reproduce the method is here, and
`sample/mock_supply_agreement.md` is a synthetic stand-in that exercises the full pipeline.

## Recommendation

**Take three things.** The provenance ledger design (separate artefact, four-level grounding
vocabulary, `bind_stats`, per-chunk `text_hash`) — but without the 6-chunk cutoff, and with
the node-level badge fixed so a multi-field node cannot inherit one field's grounding. The
export surface (Cypher-with-constraints plus a provenance column), budgeting for the fact
that no single run emits both. And DocLang as the extraction target rather than Markdown.

**Do not run customer contracts through the extraction path as configured.** The default
remote provider is excluded on egress grounds; the local path wants vLLM plus an
uninstalled model; the `direct` contract overflows a 32K window on a large contract and
`dense` does not fix it; and the cytoscape assets and chunker tokenizer both need pre-seeding
before anyone calls the path offline.

**Cheapest next experiment.** `dense` is measured and is not the answer, so the remaining
lever is segmentation: extract per section using the clause boundaries this run already
recovers. Peak prompt then falls to the largest single section — about 6,500 tokens — which
fits every candidate model. Whether per-section graphs merge back into a coherent
whole-contract graph is a question about our design, not about docling-graph.

---

docling-graph 1.9.1 · docling 2.120.1 · Python 3.12.13 · macOS arm64 · six contracts ·
three full pipeline runs · 333 graph nodes · **0 model weights loaded**
