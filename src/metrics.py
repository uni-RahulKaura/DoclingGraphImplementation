"""
Correctness metrics — how close is a parser's Markdown to Landing's gold?

Deliberately NOT throughput. Four families, combined into one 0-100 score:

  completeness  did every value / line / number survive?   (weight 0.35)
  similarity    overall text closeness to gold              (weight 0.35)
  structure     tables + headings + lists reconstructed?    (weight 0.20)
  cleanliness   no MIME/RTF/markup junk                      (weight 0.10)

Flattened tables (gold emitted HTML tables, candidate emitted pipe tables) are
RECORDED as `flattened_tables` and scored in `table_fidelity`, but neither feeds
the 0-100 composite: cleanliness counts junk patterns only, and table_fidelity
is an HTML-table COUNT RATIO reported alongside, not a term in the score. So a
0.000 table_fidelity means "chose pipe tables", not "tables are broken".

The spec's twin requirements are "no data loss" AND "reads like Landing", so
completeness and similarity are weighted equally highest (0.35 each); within
completeness, recall of numbers/dates/ids is weighted highest.
"""
from __future__ import annotations

import difflib
import html
import re

from . import config


# --------------------------------------------------------------------------
# text normalization
# --------------------------------------------------------------------------
def decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "utf-16", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


_TAG_RE = re.compile(r"<[^>]+>")
_MD_NOISE_RE = re.compile(r"[#>*_`|~\-]{1,}")
_WS_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"[a-z0-9]{2,}")
# Landing's semantic blocks for visual elements it cannot transcribe (signatures,
# stamps, logos, charts). Multi-line and unterminated forms both occur.
_VISUAL_BLOCK_RE = re.compile(r"<::.*?(?:::>|$)", re.S)


def strip_to_text(md: str) -> str:
    """Markdown/HTML -> comparable plain text: no tags, no md syntax, lower, ws-collapsed."""
    t = html.unescape(_TAG_RE.sub(" ", md or ""))
    t = _MD_NOISE_RE.sub(" ", t)
    return _WS_RE.sub(" ", t).strip().lower()


def tokens(text: str) -> set:
    return set(_WORD_RE.findall(text))


def _norm_num(s: str) -> str:
    return s.replace(",", "").replace("$", "").replace(" ", "").lower()


def numbers(text: str) -> set:
    return {_norm_num(m.group(0)) for m in config.NUM_RE.finditer(text)}


def significant_lines(md: str):
    """Content lines worth checking for survival (>=8 non-markup chars).

    Landing's `<::attestation:…::>` / `<::Gantt chart…::>` blocks are dropped
    first. They have to be: `strip_to_text` runs over a whole document, and its
    `<[^>]+>` tag pattern spans newlines, so a multi-line `<::…::>` block is
    deleted wholesale from the *candidate* text every recall test compares
    against. Reading the gold line-by-line without the same removal would keep
    those lines as scoreable content and ask the candidate to contain text the
    metric itself had just deleted — unwinnable by construction, and worst on
    documents whose gold is mostly signature/figure prose. Both sides now lose
    them together. (They are Landing describing pixels anyway: a text twin of a
    scanned contract has no signature image to transcribe.)
    """
    out = []
    for ln in _VISUAL_BLOCK_RE.sub(" ", md or "").splitlines():
        s = strip_to_text(ln)
        if len(s) >= 8:
            out.append(s)
    return out


# --------------------------------------------------------------------------
# structure
# --------------------------------------------------------------------------
_PIPE_DELIM = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")
_H_TAG = re.compile(r"<h[1-6]\b", re.I)


def structure(md: str) -> dict:
    md = md or ""
    lines = md.splitlines()
    html_tables = len(re.findall(r"<table\b", md, re.I))
    pipe_tables = 0
    for i in range(len(lines) - 1):
        if "|" in lines[i] and _PIPE_DELIM.match(lines[i + 1] or ""):
            pipe_tables += 1
    md_headings = sum(1 for l in lines if l.lstrip().startswith("#"))
    headings = md_headings + len(_H_TAG.findall(md))
    list_items = (sum(1 for l in lines if re.match(r"\s*([-*+]|\d+\.)\s+", l))
                  + len(re.findall(r"<li\b", md, re.I)))
    return {
        "chars": len(md),
        "words": len(_WORD_RE.findall(md.lower())),
        "lines": len(lines),
        "html_tables": html_tables,
        "pipe_tables": pipe_tables,
        "tables": html_tables + pipe_tables,
        "headings": headings,
        "list_items": list_items,
        "code_blocks": md.count("```") // 2,
    }


# --------------------------------------------------------------------------
# structure detail — "is the structure close to the original document?"
# --------------------------------------------------------------------------
_ATX = re.compile(r"^\s{0,3}(#{1,6})\s+(.*)$")
_HTAG_TEXT = re.compile(r"<h[1-6][^>]*>(.*?)</h[1-6]>", re.I | re.S)


def headings(md):
    out = []
    for l in (md or "").split("\n"):
        m = _ATX.match(l)
        if m:
            out.append(strip_to_text(m.group(2)))
    for m in _HTAG_TEXT.finditer(md or ""):
        out.append(strip_to_text(m.group(1)))
    return [h for h in out if h]


def _html_table_shapes(md):
    shapes = []
    for m in re.finditer(r"<table\b.*?</table>", md or "", re.I | re.S):
        block = m.group(0)
        rows = len(re.findall(r"<tr\b", block, re.I))
        cols = 0
        for rm in re.finditer(r"<tr\b.*?</tr>", block, re.I | re.S):
            cols = max(cols, len(re.findall(r"<t[dh]\b", rm.group(0), re.I)))
        if rows:
            shapes.append((rows, cols))
    return shapes


def _pipe_table_shapes(md):
    lines = (md or "").split("\n")
    shapes = []
    i, n = 0, len(lines)
    while i < n - 1:
        if "|" in lines[i] and _PIPE_DELIM.match(lines[i + 1] or ""):
            cols = len([c for c in lines[i].split("|") if c.strip()])
            j, rows = i + 2, 1
            while j < n and "|" in lines[j] and lines[j].strip():
                rows += 1
                j += 1
            shapes.append((rows, max(cols, 1)))
            i = j
        else:
            i += 1
    return shapes


def table_shapes(md):
    return _html_table_shapes(md) + _pipe_table_shapes(md)


def skeleton(md):
    """Ordered block-type skeleton: H(eading) T(able) L(ist) C(ode) P(ara)."""
    toks = []
    for l in (md or "").split("\n"):
        s = l.strip()
        if not s:
            continue
        low = s.lower()
        if _ATX.match(l) or low.startswith(("<h1", "<h2", "<h3", "<h4", "<h5", "<h6")):
            t = "H"
        elif ("<table" in low or "<tr" in low or "<td" in low or "</table" in low
              or ("|" in s and set(s) <= set("|-: ") and "-" in s)
              or s.count("|") >= 2):
            t = "T"
        elif re.match(r"([-*+]|\d+\.)\s+", s) or low.startswith("<li"):
            t = "L"
        elif s.startswith("```"):
            t = "C"
        else:
            t = "P"
        if not toks or toks[-1] != t:
            toks.append(t)
    return "".join(toks)


def _shape_fidelity(gsh, csh):
    """For each gold table, best (rows,cols) match among candidate tables; averaged."""
    if not gsh:
        return 1.0
    total = 0.0
    for gr, gc in gsh:
        best = 0.0
        for cr, cc in csh:
            rr = 1 - min(1, abs(gr - cr) / max(gr, cr, 1))
            cco = 1 - min(1, abs(gc - cc) / max(gc, cc, 1))
            best = max(best, (rr + cco) / 2)
        total += best
    return total / len(gsh)


# --------------------------------------------------------------------------
# cleanliness
# --------------------------------------------------------------------------
JUNK_PATTERNS = [
    ("mime/email headers", re.compile(r"(?m)^(Content-Type|MIME-Version|DKIM-Signature|"
                                      r"Message-ID|Received|Return-Path|X-[\w-]+):", re.I)),
    ("rtf control words", re.compile(r"\\(rtf1|par\b|pard|fonttbl|colortbl)|\{\\")),
    ("script/style", re.compile(r"<\s*(script|style)\b", re.I)),
    ("html table junk attrs", re.compile(r'class="dataframe"|<table[^>]*\bborder=')),
    ("form feed / control", re.compile(r"[\x0c\x0b]")),
]


def cleanliness(md: str) -> dict:
    hits = {}
    for name, rx in JUNK_PATTERNS:
        n = len(rx.findall(md or ""))
        if n:
            hits[name] = n
    total = sum(hits.values())
    score = 1.0 if total == 0 else max(0.0, 1.0 - 0.15 * total)
    return {"score": round(score, 3), "hits": hits}


# --------------------------------------------------------------------------
# the score
# --------------------------------------------------------------------------
def _closeness(g, c):
    """1.0 when equal, ->0 as they diverge (symmetric)."""
    m = max(g, c, 1)
    return 1.0 - min(1.0, abs(g - c) / m)


# Words, not characters: at 200k chars a char-level diff is dominated by spaces
# and vowels, and it is slow enough that it forced a truncation cap.
_WORD_CAP = 300_000


def _ratio(a, b) -> float:
    """A sequence similarity ratio that is a measurement, not a speed heuristic.

    `difflib.SequenceMatcher` defaults to `autojunk=True`, which — on any
    sequence of 200 elements or more — declares every element appearing in more
    than 1% of positions to be junk and refuses to match on it. That is a
    reasonable shortcut for diffing source code. It is wrong here, and on two of
    our three comparisons it was catastrophic:

      * character text: the junk list becomes the space and the common letters,
        i.e. most of the document. `marker` scored 0.149 similarity against a
        90-page contract it had reproduced nearly verbatim -- 27.6 composite points
        of pure artifact, enough to rank it last when it belongs near the top.
      * the block skeleton: it is drawn from a five-symbol alphabet (H/T/L/C/P),
        so past 200 blocks *every* symbol clears the 1% threshold and the ratio
        collapses toward zero no matter what the parser produced.

    Turning it off makes the number mean what the report claims it means. Across
    the 255 pairs on disk this moved similarity on 86 of them and the skeleton on
    17, and it runs ~5.6x faster besides.
    """
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def score(gold_md, cand_md: str) -> dict:
    """
    Score cand_md against gold_md.

    `composite` is None in two distinct situations, told apart by the flags:

      * `gold` False  — no answer key yet, so nothing could be scored
        (structure-only, for the harness's gold-pending mode).
      * `empty_output` True — there *is* a key, and the parser returned no text.

    Neither gets a number, on the same rule the harness applies to a crashed
    parse: never fabricate a score for something that did not parse.
    """
    cs = structure(cand_md)
    clean = cleanliness(cand_md)
    cand_text = strip_to_text(cand_md)

    result = {"structure": cs, "cleanliness": clean}

    if gold_md is None:
        result.update({"composite": None, "gold": False})
        return result

    gs = structure(gold_md)
    gold_text = strip_to_text(gold_md)

    # A parser that returned nothing has not scored badly — it has produced
    # nothing, and the report must not render those the same way.
    #
    # Scored normally, an empty output came out at **10.0 / 100**: it trips no junk
    # pattern, so emptiness collected the entire cleanliness weight, and a parser
    # that returned zero bytes outscored one that returned garbled text. That 10.0
    # was on the scanned-contract page — exactly where this report argues that text
    # extraction cannot substitute for OCR. The evidence for the claim was being
    # printed as a low-but-real score.
    if gold_text and not cand_text:
        result.update({
            "gold": True, "empty_output": True, "composite": None,
            "gold_structure": gs,
            "counts": {"gold_numbers": len(numbers(gold_text)),
                       "missing_numbers": len(numbers(gold_text)),
                       "gold_tokens": len(tokens(gold_text)),
                       "missing_tokens": len(tokens(gold_text)),
                       "gold_lines": len(significant_lines(gold_md)),
                       "missing_lines": len(significant_lines(gold_md))},
        })
        return result

    gtok, ctok = tokens(gold_text), tokens(cand_text)
    gnum, cnum = numbers(gold_text), numbers(cand_text)
    glines = significant_lines(gold_md)

    token_recall = len(gtok & ctok) / len(gtok) if gtok else 1.0
    number_recall = len(gnum & cnum) / len(gnum) if gnum else 1.0
    line_recall = (sum(1 for l in glines if l in cand_text) / len(glines)) if glines else 1.0
    extra_ratio = len(ctok - gtok) / len(ctok) if ctok else 0.0

    completeness = 0.5 * number_recall + 0.3 * token_recall + 0.2 * line_recall

    # ---- structure: is the candidate's structure close to the original? ----
    gh, ch = headings(gold_md), headings(cand_md)
    ch_set = set(ch)
    heading_recall = (sum(1 for h in gh if h in ch_set or h in cand_text) / len(gh)) if gh else 1.0
    heading_order_sim = _ratio(gh, ch) if gh else 1.0
    heading_score = 0.5 * heading_recall + 0.5 * heading_order_sim
    skel_sim = _ratio(skeleton(gold_md), skeleton(cand_md))
    gsh, csh = table_shapes(gold_md), table_shapes(cand_md)
    table_shape = _shape_fidelity(gsh, csh)

    terms = [(0.30, skel_sim)]                 # document skeleton (order + block types)
    if gh:
        terms.append((0.40, heading_score))    # heading recall + order
    if gsh:
        terms.append((0.30, table_shape))      # per-table row x col fidelity
    wsum = sum(w for w, _ in terms)
    structure_match = sum(w * v for w, v in terms) / wsum if wsum else (1.0 if cand_text else 0.0)

    # Word-level, not character-level. A char-level ratio on a 200k-char contract
    # spends all its time on spaces and vowels, and autojunk (see _ratio) then
    # discards exactly those, which is why marker used to score 0.149 here on a
    # document it had reproduced almost perfectly. Words also run ~5.6x faster,
    # which is what makes the generous cap below affordable.
    similarity = _ratio(gold_text.split()[:_WORD_CAP], cand_text.split()[:_WORD_CAP])

    # table fidelity: Landing uses HTML tables. Reported separately (not punished
    # in completeness — the data may be fully present as pipes).
    if gs["html_tables"] > 0:
        table_fidelity = min(1.0, cs["html_tables"] / gs["html_tables"])
    else:
        table_fidelity = 1.0
    flattened = gs["html_tables"] > 0 and cs["html_tables"] == 0 and cs["pipe_tables"] > 0

    W = config.SCORE_WEIGHTS
    composite = 100.0 * (W["completeness"] * completeness +
                         W["structure"] * structure_match +
                         W["similarity"] * similarity +
                         W["cleanliness"] * clean["score"])

    result.update({
        "gold": True,
        "composite": round(composite, 1),
        "completeness": round(completeness, 3),
        "token_recall": round(token_recall, 3),
        "number_recall": round(number_recall, 3),
        "line_recall": round(line_recall, 3),
        "extra_ratio": round(extra_ratio, 3),
        "structure_match": round(structure_match, 3),
        "heading_recall": round(heading_recall, 3),
        "heading_order_sim": round(heading_order_sim, 3),
        "skeleton_sim": round(skel_sim, 3),
        "table_shape_fidelity": round(table_shape, 3),
        "similarity": round(similarity, 3),
        "table_fidelity": round(table_fidelity, 3),
        "flattened_tables": flattened,
        "gold_structure": gs,
        "counts": {"gold_numbers": len(gnum), "missing_numbers": len(gnum - cnum),
                   "gold_tokens": len(gtok), "missing_tokens": len(gtok - ctok),
                   "gold_lines": len(glines),
                   "missing_lines": sum(1 for l in glines if l not in cand_text)},
    })
    return result
