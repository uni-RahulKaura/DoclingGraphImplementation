#!/usr/bin/env python
"""Draw what the tool pulled out of each contract, for a non-specialist reader.

Written plainly on purpose. An earlier version of this page used the schema's own
label names (Obligation, PaymentTerm) and the graph's own edge names (OBLIGATES,
PARTY_TO) with no explanation, plus graph-theory wording ("strict tree", "no
cycles", "force layout"). The first question back was "what is obligation?", which
is the correct response to a page that never says. Every label is now defined in
ordinary words with a real example, and the machine names are translated.
"""
import csv, glob, html, json
from collections import defaultdict

DOCS = ["micro_crystal", "evolving_solutions", "dell", "jabil", "atl_technology", "accenture"]

# What each contract actually is, in plain words.
ABOUT = {
 "micro_crystal": ("Micro Crystal AG", "A one-page amendment that extends an existing "
    "supply agreement with Medtronic. Signed January 2018, effective April 2018."),
 "evolving_solutions": ("Evolving Solutions", "A Statement of Work under a Master Services "
    "Agreement with Medtronic, covering IT services."),
 "dell": ("Dell / EMC", "A short letter confirming Medtronic will return equipment to Dell, "
    "with a DocuSign signing certificate attached."),
 "jabil": ("Jabil / Nypro", "A one-page letter agreement with Medtronic, with a DocuSign "
    "signing certificate attached."),
 "atl_technology": ("ATL Technology", "A letter agreement with Medtronic about product "
    "feedback, with a DocuSign signing certificate attached."),
 "accenture": ("Accenture", "A 38-page Statement of Work for a Financial Planning & Analysis "
    "centre of excellence. The largest and most complex of the six."),
}

# Plain-English name, colour, one-sentence meaning.
KIND = {
 "Contract":        ("The document",  "#3D5A80", "The contract itself. Everything hangs off this."),
 "Party":           ("A side",        "#A32235", "A company named in the contract."),
 "ContractSection": ("A section",     "#2F6B4F", "A numbered clause or headed part of the document."),
 "Permission":      ("Allowed / not allowed", "#8A6410",
                     "Something a side may do, or may not do."),
 "Obligation":      ("Must do",       "#6B4E8A", "Something a side is required to do."),
 "Term":            ("Dates",         "#1F6F7A", "When the agreement starts and ends."),
 "PaymentTerm":     ("Money",         "#7A5C1F", "Amounts, currency, and when payment is due."),
}
# Real examples, quoted from these contracts, so the definitions are concrete.
EXAMPLE = {
 "Party": "Medtronic, Inc",
 "Obligation": "“Company will provide the Services described herein to Medtronic”",
 "Permission": "“Company shall not engage in any out of scope Services without first "
               "obtaining Medtronic’s written approval”",
 "ContractSection": "“3. SERVICES”",
 "Term": "starts 29 April 2018",
 "PaymentTerm": "“net 30”",
 "Contract": "the Statement of Work",
}
# Translate the machine edge names into ordinary words.
EDGE = {"PARTY_TO": "is between", "CONTAINS": "contains", "GRANTS": "allows",
        "OBLIGATES": "requires", "term": "runs", "payment": "pays"}

ROW, INDENT, PAD = 18, 24, 14


def load(stem):
    d = sorted(glob.glob("out6/%s_direct_csv/*/" % stem))[-1]
    nodes = {r["id"]: r for r in csv.DictReader(open(d + "docling_graph/nodes.csv"))}
    edges = [(r["source"], r["target"], r["label"])
             for r in csv.DictReader(open(d + "docling_graph/edges.csv"))]
    return nodes, edges


def placed_rows(nodes, edges):
    kids, indeg = defaultdict(list), defaultdict(int)
    for s, t, l in edges:
        kids[s].append((t, l))
        indeg[t] += 1
    out, y = [], [0]

    def walk(nid, depth, elabel):
        out.append((nid, depth, y[0], elabel))
        y[0] += 1
        for t, l in sorted(kids.get(nid, []),
                           key=lambda kl: (kl[1], nodes.get(kl[0], {}).get("label", ""))):
            walk(t, depth + 1, l)

    for r in sorted(n for n in nodes if indeg[n] == 0):
        walk(r, 0, "")
    return out


def value_of(n):
    for k in ("name", "heading", "title", "text"):
        if n.get(k):
            return n[k]
    bits = [n[k] for k in ("effective_date", "expiry_date", "duration",
                           "amount", "currency", "net_days") if n.get(k)]
    # An empty value is a real result -- the tool created the slot and found nothing to
    # put in it. Saying so beats rendering a label with blank space after it, which
    # reads as a broken page rather than an empty finding.
    return " · ".join(bits) if bits else "(nothing found)"


def svg(stem):
    nodes, edges = load(stem)
    rows = placed_rows(nodes, edges)
    maxd = max(r[1] for r in rows)
    W = 100 + INDENT * maxd + 640
    H = PAD * 2 + ROW * len(rows)
    o = ['<svg viewBox="0 0 %d %d" width="%d" height="%d" role="img" '
         'aria-label="what was pulled out of the %s contract" '
         'xmlns="http://www.w3.org/2000/svg">' % (W, H, W, H, ABOUT[stem][0])]
    rowy = {r[2]: PAD + ROW * r[2] + ROW / 2 for r in rows}
    for nid, depth, row, elabel in rows:
        if depth == 0:
            continue
        parent = max((r for r in rows if r[1] == depth - 1 and r[2] < row),
                     key=lambda r: r[2], default=None)
        if not parent:
            continue
        x1 = PAD + INDENT * (depth - 1) + 4
        x2 = PAD + INDENT * depth
        o.append('<path d="M%d %.1f V%.1f H%d" fill="none" stroke="currentColor" '
                 'stroke-opacity=".2" stroke-width="1"/>'
                 % (x1, rowy[parent[2]], rowy[row], x2))
    for nid, depth, row, elabel in rows:
        n = nodes[nid]
        plain, col, _ = KIND.get(n.get("label", ""), (n.get("label", "?"), "#888", ""))
        x, y = PAD + INDENT * depth, rowy[row]
        o.append('<circle cx="%d" cy="%.1f" r="3.6" fill="%s"/>' % (x + 4, y, col))
        rel = (' <tspan opacity=".5">%s</tspan>' % html.escape(EDGE.get(elabel, elabel))) if elabel else ""
        o.append('<text x="%d" y="%.1f" font-size="11" '
                 'font-family="-apple-system,system-ui,sans-serif" fill="currentColor">'
                 '<tspan fill="%s" font-weight="600">%s</tspan>%s '
                 '<tspan opacity=".8">%s</tspan></text>'
                 % (x + 13, y + 3.6, col, html.escape(plain), rel,
                    html.escape(value_of(n)[:92])))
    o.append("</svg>")
    return len(rows), "\n".join(o)


rendered = [(s,) + svg(s) for s in DOCS]

legend_rows = "".join(
    '<tr><td><span class="dot" style="background:%s"></span><b>%s</b></td>'
    '<td>%s</td><td class="eg">%s</td></tr>'
    % (col, plain, meaning, html.escape(EXAMPLE.get(k, "")))
    for k, (plain, col, meaning) in KIND.items())

D = []
A = D.append
A('<title>What the Tool Found in Six Contracts</title>')
A('<style>')
A(':root{--paper:#FAFAF8;--card:#fff;--ink:#16191D;--muted:#5A6169;--faint:#8B929B;'
  '--rule:#E3E3DC;--rule2:#EFEFE9;--accent:#A32235}')
A('@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--paper:#0F1216;'
  '--card:#161A1F;--ink:#E9EAE6;--muted:#98A0AA;--faint:#767E88;--rule:#262B32;'
  '--rule2:#1D2228;--accent:#E8808F}}')
A(':root[data-theme="dark"]{--paper:#0F1216;--card:#161A1F;--ink:#E9EAE6;--muted:#98A0AA;'
  '--faint:#767E88;--rule:#262B32;--rule2:#1D2228;--accent:#E8808F}')
A('*{box-sizing:border-box}')
A('body{margin:0;background:var(--paper);color:var(--ink);'
  'font-family:-apple-system,system-ui,"Segoe UI",sans-serif;font-size:16.5px;line-height:1.65}')
A('.wrap{max-width:70rem;margin:0 auto;padding:0 1.5rem 5rem}')
A('header{padding:3rem 0 1.2rem;border-bottom:2px solid var(--ink);margin-bottom:1.8rem}')
A('h1{font-weight:650;font-size:clamp(1.7rem,3.6vw,2.4rem);margin:0 0 .7rem;letter-spacing:-.02em}')
A('.lede{font-size:1.08rem;color:var(--muted);max-width:40rem;margin:0}')
A('h2{font-size:1.22rem;font-weight:650;margin:3rem 0 .1rem}')
A('.sub{color:var(--muted);font-size:.95rem;margin:.15rem 0 .9rem;max-width:44rem}')
A('h3{font-size:1rem;font-weight:650;margin:2rem 0 .5rem}')
A('p{max-width:44rem}')
A('table{border-collapse:collapse;width:100%;font-size:.93rem}')
A('td,th{text-align:left;padding:.5rem .7rem;border-bottom:1px solid var(--rule2);'
  'vertical-align:top}')
A('th{font-size:.78rem;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);'
  'background:var(--rule2);border-bottom:1px solid var(--rule)}')
A('.key{border:1px solid var(--rule);background:var(--card);margin:1.4rem 0}')
A('.key td.eg{color:var(--faint);font-style:italic}')
A('.dot{width:.62rem;height:.62rem;border-radius:50%;display:inline-block;margin-right:.45rem}')
A('.frame{overflow:auto;max-height:32rem;border:1px solid var(--rule);background:var(--card);'
  'padding:.5rem;margin:.7rem 0 0}')
A('svg{display:block}')
A('.count{font-size:.85rem;color:var(--faint);margin:.2rem 0 0}')
A('.callout{border:1px solid var(--rule);border-left:3px solid var(--accent);'
  'background:var(--card);padding:1rem 1.15rem;margin:1.6rem 0;max-width:46rem}')
A('.callout b{display:block;margin-bottom:.3rem}')
A('footer{margin-top:3.5rem;padding-top:1rem;border-top:1px solid var(--rule);'
  'font-size:.85rem;color:var(--muted)}')
A('</style>')
A('<div class="wrap">')
A('<header><h1>What the tool found in six contracts</h1>')
A('<p class="lede">We ran six real contracts through docling-graph. This page shows, for each '
  'one, every piece of information it pulled out.</p></header>')

A('<h2>How to read this</h2>')
A('<p class="sub">Each contract below is shown as an outline. The document is at the top, and '
  'everything it found sits underneath, indented. The coloured dot tells you what kind of thing '
  'each line is:</p>')
A('<table class="key"><tr><th>Kind</th><th>What it means</th><th>Example from these contracts</th></tr>'
  + legend_rows + '</table>')
A('<p>So a line reading <b>Must do</b> &nbsp;requires&nbsp; &ldquo;Company will provide the '
  'Services&rdquo; means: the tool found a sentence in the contract saying one side has to do '
  'something, and that is the sentence.</p>')

A('<div class="callout"><b>One thing to know before you read the lists</b>'
  '<p style="margin:0">Nothing here was produced by an AI model. We drove the tool with '
  'fixed search patterns instead, so the results are repeatable. That is also why the lists '
  'below contain mistakes &mdash; a search pattern cannot tell the difference between a company '
  'that signed the contract and a company merely mentioned in it. Where a list looks wrong, it '
  'usually is, and the companion page <b>DG6-SUMMARIES.md</b> says exactly how for each '
  'contract.</p></div>')

for stem, n, s in rendered:
    name, desc = ABOUT[stem]
    A('<h2>%s</h2>' % html.escape(name))
    A('<p class="sub">%s</p>' % html.escape(desc))
    A('<p class="count">%d items found</p>' % n)
    A('<div class="frame">%s</div>' % s)

A('<footer><p>Six contracts, %d items in total. Source files and the full per-contract '
  'breakdown are in the companion pages.</p></footer>' % sum(r[1] for r in rendered))
A('</div>')
open("../DG6-GRAPHS.html", "w").write("\n".join(D))
print("-> DG6-GRAPHS.html")
for stem, n, s in rendered:
    print("   %-20s %4d items" % (stem, n))
