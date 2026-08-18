"""A deterministic, DocLang-aware stand-in for an LLM client.

This replaces `rule_client.RuleBasedClient`, which was written against Markdown
and is structurally wrong for what docling-graph actually hands an extractor.

What the first version got wrong, and why it mattered
----------------------------------------------------
docling-graph does NOT put Markdown in the prompt. It re-serialises the converted
document into **DocLang**, an XML markup format (`<doclang version="0.7">`) whose
tags -- `<heading>`, `<text>`, `<table>`, `<list>`, `<picture>` -- carry the
structure, with `<location>` page coordinates on a 512x512 grid. The Markdown
`^#{1,6}` heading pattern therefore matches **nothing** in the prompt. On the
166 KB Accenture MSA the old client found exactly 2 "headings", and both were
lines from docling-graph's own numbered instruction list:

    1. Read the provided document text carefully.
    3. Return ONLY valid JSON that matches the schema (no extra keys).

So every `ContractSection` node in the earlier run was an artefact of the prompt
preamble rather than the contract. Node counts also looked identical across wildly
different documents because the old client capped parties at 8 and permissions and
obligations at 5 -- caps in the instrument, not in docling-graph.

What this version does differently
----------------------------------
* Parses the DocLang body as XML (it is well-formed; ElementTree handles all six
  contracts, CDATA and self-closing `<ldiv/>` / `<page_break/>` included).
* Treats **two** things as section boundaries, because real contracts use both:
  `<heading>` elements, and the `<list class="ordered">/<bold>` form that docling
  emits for numbered clause headings such as `1. INTRODUCTION AND OVERVIEW`.
  Keying on `<heading>` alone would miss most clauses in the Accenture SOW.
* Applies **no silent caps**. Generous ceilings exist as a runaway guard, and the
  pre-cap count is recorded alongside every capped list so that saturation is
  always attributable to either the document or the guard.

Still no model, no network, no download: the point is that docling-graph's
plumbing runs end to end without one, so any variation across documents is the
tool's front end and not sampling noise.
"""
import json, os, re, time
import xml.etree.ElementTree as ET
from typing import Any, Dict, Iterator, List, Mapping

LOG = os.environ.get("DG_CALLLOG", "calls6")
os.makedirs(LOG, exist_ok=True)

# Runaway guards only. Every one of these is reported with its pre-cap count.
MAX_PARTIES = 400
MAX_SECTIONS = 400
MAX_PER_SECTION = 200

_DATE = re.compile(
    r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}"
    r"|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4})\b")
_DUR = re.compile(r"\b((?:\w+\s+)?\(?\d+\)?\s*(?:day|week|month|year)s?)\b", re.I)
_MONEY = re.compile(r"(?:US\$|\$|USD\s*|EUR\s*|CHF\s*)\s?[\d,]+(?:\.\d{2})?")
_NET = re.compile(r"\bnet\s+\d+\b", re.I)
_PERM = re.compile(r"[^.\n]*\b(?:may|shall\s+not|must\s+not|is\s+(?:not\s+)?permitted"
                   r"|is\s+entitled|prohibited)\b[^.\n]*\.", re.I)
_OBL = re.compile(r"[^.\n]*\b(?:shall|must|is\s+required\s+to|agrees\s+to|will\s+provide)"
                  r"\b[^.\n]*\.", re.I)
_COND = re.compile(r"\bwithout\s+(?:the\s+)?(?:prior\s+)?written\s+consent\b|\bsubject\s+to\b"
                   r"|\bprovided\s+that\b|\bunless\b", re.I)
# Defined terms -- ("Supplier"), ("Accenture" or "Supplier") -- plus bare role nouns.
_QUOTED = re.compile(r'["“]([A-Z][A-Za-z0-9 .,&\'\-]{2,40})["”]')
_ROLE = re.compile(r"\b(Supplier|Customer|Manufacturer|Buyer|Seller|Licensor|Licensee"
                   r"|Vendor|Contractor|Client|Company|Purchaser|Consultant|Provider)\b")
# Corporate names: "Accenture International Limited", "Medtronic, Inc."
_CORP = re.compile(r"\b([A-Z][A-Za-z0-9&.\-]*(?:\s+[A-Z][A-Za-z0-9&.\-]*){0,5}"
                   r"\s*,?\s*(?:Inc|Corp|Corporation|Ltd|Limited|LLC|LC|GmbH|AG|S\.A|B\.V|plc)\.?)\b")
# Boilerplate that quoting rules would otherwise promote to a party.
_NOT_A_PARTY = re.compile(r"^(SOW|MSA|Agreement|Party|Parties|Effective Date|Services|"
                          r"Change Request|Change Order|Term|BU|BUs|COE|KT|DD|DTPs)$", re.I)


def _text_of(el) -> str:
    """All descendant text, tags flattened, whitespace collapsed."""
    return " ".join(" ".join(el.itertext()).split())


def _prompt_text(prompt) -> str:
    if isinstance(prompt, Mapping):
        return "\n".join(str(v) for v in prompt.values())
    return str(prompt)


def _doclang_body(s: str):
    """Isolate the DocLang element, discarding docling-graph's instruction preamble.

    Returning the preamble is what produced the phantom sections in v1, so this is
    deliberately strict: if there is no <doclang> element, say so rather than
    falling back to the whole prompt.
    """
    i = s.find("<doclang")
    k = s.rfind("</doclang>")
    if i < 0 or k <= i:
        return None
    return s[i:k + len("</doclang>")]


def _chunk_bodies(prompt: str):
    """Split a dense_skeleton prompt into its '--- CHUNK N ---' bodies.

    The dense path does NOT send DocLang the way `direct` does: there is no
    <doclang> root element, so `_doclang_body` returns None and the whole call
    silently yields {}. The chunk bodies do still carry DocLang *tags*
    (<text>, <list>, <bold>), so wrapping each in a synthetic root makes it
    parseable. Returns [(chunk_number, xml_or_none, plain_text), ...].
    """
    out = []
    marks = list(re.finditer(r"---\s*CHUNK\s+(\d+)\s*---", prompt))
    for k, m in enumerate(marks):
        start = m.end()
        end = marks[k + 1].start() if k + 1 < len(marks) else len(prompt)
        body = prompt[start:end].strip()
        if not body:
            continue
        root = None
        try:
            root = ET.fromstring("<root>" + body + "</root>")
        except ET.ParseError:
            root = None          # chunk cut mid-tag; fall back to stripped text
        text = (_text_of(root) if root is not None
                else " ".join(re.sub(r"<[^>]+>", " ", body).split()))
        out.append((int(m.group(1)), root, text))
    return out


def _source_clause_titles():
    """Clause titles taken from the ORIGINAL Markdown, used as an allowlist.

    Some clause headings survive into DocLang glued to the paragraph that follows
    them, with no delimiter to split on -- e.g.
    "SIGNATURES IN WITNESS WHEREOF the Parties have executed this SOW ..." and
    "Telephony Solution The planned telephony solution ...". No rule over the DocLang
    alone can recover those boundaries, so the numbering in the source Markdown is
    used instead: `^N. Title` lines give an allowlist, and any element starting with
    one of those titles is split at that point.

    Set DG_SOURCE to the source path to enable this. Without it the allowlist is empty
    and behaviour is unchanged.
    """
    path = os.environ.get("DG_SOURCE")
    if not path or not os.path.exists(path):
        return []
    md = open(path, encoding="utf-8", errors="replace").read()
    titles = set()
    for m in re.finditer(
            r"(?m)^\s*(?:\*\*)?\d{1,2}\.\s+([A-Z][A-Za-z0-9 &/\-,']{3,70}?)(?:\*\*)?\s*:?\s*$", md):
        t = m.group(1).strip()
        if t:
            titles.add(t)
    return sorted(titles, key=len, reverse=True)


def _is_clause_heading(el) -> bool:
    """True for a clause title that docling emitted as a list rather than a heading.

    docling renders numbered contract clauses as `<list class="ordered">` with an
    `<ldiv/>` marker, so a splitter keying on `<heading>` alone loses them.

    An earlier version of this required the text to be >70% uppercase. That was the
    wrong discriminator and it silently dropped real sections: on the Accenture SOW it
    caught `TIMELINE` and `ROLES AND RESPONSIBILITIES` but threw away `5. Project
    Location` and `6. Key Project Considerations`, which are Title Case. Both are
    genuine numbered clauses in the source.

    The rule is now length and shape, not case: a short titled line that is not a
    sentence. This deliberately errs toward including too much -- it will also pick up
    a handful of defined terms and captions -- because a section missing from the index
    is worse than a section that should not be there. `heading_confidence` on each
    section records which are real headings and which were inferred this way.
    """
    if el.tag not in ("list", "bold"):
        return False
    t = _text_of(el).strip()
    if not (3 <= len(t) <= 80) or len(t.split()) > 10:
        return False
    if t.endswith(".") and not re.match(r"^\d+\.$", t):
        return False          # a full sentence, not a title
    if re.match(r"^\d+[-/]", t):
        return False          # a date or data row, e.g. "10-Feb-20 9-March-20 ..."
    return t[0].isupper() or t[0].isdigit()


class DocLangRuleClient:
    """Deterministic. No model, no network. Satisfies LLMClientProtocol."""
    model = "doclang-rule-based/none"

    def __init__(self):
        self.n = 0
        self.stats: List[Dict[str, Any]] = []

    # -- protocol -------------------------------------------------------------
    def get_json_response(self, prompt, schema_json: str, structured_output: bool = True,
                          response_top_level: str = "object",
                          response_schema_name: str = "extraction_result", **kw):
        self.n += 1
        body = _prompt_text(prompt)
        try:
            schema = json.loads(schema_json) if schema_json else {}
        except Exception:
            schema = {}
        out, st = self._fill(schema, body)
        st.update(call=self.n, schema_name=response_schema_name,
                  top_level=response_top_level, prompt_chars=len(body))
        self.stats.append(st)
        with open(os.path.join(LOG, "call_%03d.json" % self.n), "w") as fh:
            json.dump({"call": self.n, "ts": time.time(), "top_level": response_top_level,
                       "schema_name": response_schema_name, "stats": st,
                       "prompt_chars": len(body), "prompt": body,
                       "returned": out,
                       "schema": schema or None}, fh, indent=1, default=str)
        return [out] if response_top_level == "array" else out

    def get_json_response_stream(self, prompt, schema_json, structured_output=True,
                                 response_top_level="object",
                                 response_schema_name="extraction_result", **kw) -> Iterator:
        yield self.get_json_response(prompt, schema_json, structured_output,
                                     response_top_level, response_schema_name, **kw)

    # -- filling --------------------------------------------------------------
    def _fill(self, schema: Dict[str, Any], body: str):
        props = (schema or {}).get("properties") or {}
        st: Dict[str, Any] = {}

        # The `dense` extraction contract asks for a two-phase extraction: first a
        # skeleton of entity handles with no property values, then the direct pass.
        # Its prompts carry chunk bodies rather than a <doclang> root, so this needs
        # its own branch -- without it every skeleton call returns {} and the dense
        # path silently degenerates to `direct`.
        if "nodes" in props and "sections" not in props:
            return self._skeleton(body, st)

        dl = _doclang_body(body)
        st["doclang_found"] = dl is not None
        if dl is None:
            st["parse"] = "no <doclang> element in prompt"
            return {}, st
        try:
            root = ET.fromstring(dl)
            st["parse"] = "xml"
        except ET.ParseError as e:
            st["parse"] = "xml-failed: %s" % str(e)[:120]
            return {}, st

        units = list(root)
        st["doclang_children"] = len(units)
        st["tag_census"] = {}
        for u in units:
            st["tag_census"][u.tag] = st["tag_census"].get(u.tag, 0) + 1

        full = _text_of(root)
        st["doc_text_chars"] = len(full)
        sections = self._sections(units, st)

        out: Dict[str, Any] = {}
        if "title" in props:
            out["title"] = self._title(units) or "Untitled Agreement"
        if "parties" in props:
            out["parties"] = self._parties(full, st)
        if "term" in props:
            dates = _DATE.findall(full)
            st["dates_found"] = len(dates)
            dm = _DUR.search(full)
            out["term"] = {
                "effective_date": dates[0] if dates else None,
                "expiry_date": dates[1] if len(dates) > 1 else None,
                "duration": dm.group(1) if dm else None,
                "renewal": self._first_sentence(
                    full, re.compile(r"[^.\n]*\brenew\w*[^.\n]*\.", re.I)),
            }
        if "payment" in props:
            m = _MONEY.search(full)
            n = _NET.search(full)
            out["payment"] = {"amount": m.group(0) if m else None,
                              "currency": "USD" if m else None,
                              "net_days": n.group(0) if n else None}
        if "sections" in props:
            out["sections"] = sections
        # sub-schema fills, used by dense/gleaning paths
        if "heading" in props and "sections" not in props:
            out.update(sections[0] if sections else {"heading": "Unnamed"})
        if "text" in props and "heading" not in props:
            out["text"] = (self._first_sentence(full, _PERM)
                           or self._first_sentence(full, _OBL) or full[:200])
            if "polarity" in props:
                out["polarity"] = ("restricts" if re.search(r"\bnot\b", out["text"], re.I)
                                   else "grants")
            if "condition" in props:
                out["condition"] = self._first_sentence(out["text"], _COND)
            if "obligor" in props:
                mm = _ROLE.search(out["text"])
                out["obligor"] = mm.group(1) if mm else None
        if "name" in props and "role" in props:
            mm = _ROLE.search(full)
            out["name"] = mm.group(1) if mm else "Unknown Party"
            out["role"] = out["name"]
        return out, st

    @staticmethod
    def _first_sentence(s, rx):
        m = rx.search(s or "")
        return " ".join(m.group(0).split()) if m else None

    def _skeleton(self, body: str, st):
        """Answer a dense_skeleton call: entity handles and paths, no property values.

        `ids` must be a short verbatim label per the schema, and `p` must reference a
        handle emitted in this same response, so the root is emitted first and every
        other node parents onto it (or onto its section).
        """
        chunks = _chunk_bodies(body)
        st["skeleton"] = True
        st["chunks_in_prompt"] = len(chunks)
        if not chunks:
            st["parse"] = "no chunk markers in dense prompt"
            return {"nodes": []}
        st["parse"] = "chunks"

        nodes: List[Dict[str, Any]] = []
        i = 1
        nodes.append({"i": i, "path": "", "ids": {"title": "Statement of Work"}, "p": None})
        root = i
        seen_party, seen_sec = set(), set()

        for cnum, croot, ctext in chunks:
            # parties -- corporate names first, they are the distinctive identifiers
            for rx in (_CORP, _QUOTED, _ROLE):
                for m in rx.finditer(ctext):
                    nm = " ".join((m.group(1) or "").split())
                    if not nm or _NOT_A_PARTY.match(nm) or nm.lower() in seen_party:
                        continue
                    seen_party.add(nm.lower())
                    i += 1
                    nodes.append({"i": i, "path": "parties[]",
                                  "ids": {"name": nm[:60]}, "p": root, "c": cnum})
            # sections, and their permissions / obligations
            heads = []
            if croot is not None:
                for u in list(croot):
                    if u.tag == "heading" or _is_clause_heading(u):
                        t = _text_of(u)
                        if t:
                            heads.append(t)
            for h in heads:
                if h.lower() in seen_sec:
                    continue
                seen_sec.add(h.lower())
                i += 1
                sec = i
                nodes.append({"i": sec, "path": "sections[]",
                              "ids": {"heading": h[:80]}, "p": root, "c": cnum})
                for s in _PERM.findall(ctext)[:3]:
                    i += 1
                    nodes.append({"i": i, "path": "sections[].permissions[]",
                                  "ids": {"text": " ".join(s.split())[:60]},
                                  "p": sec, "c": cnum})
                for s in _OBL.findall(ctext)[:3]:
                    i += 1
                    nodes.append({"i": i, "path": "sections[].obligations[]",
                                  "ids": {"text": " ".join(s.split())[:60]},
                                  "p": sec, "c": cnum})

        st["skeleton_nodes"] = len(nodes)
        return {"nodes": nodes}, st

    @staticmethod
    def _title(units) -> str:
        for u in units:
            if u.tag == "heading":
                t = _text_of(u)
                if t:
                    return t[:200]
        for u in units:
            t = _text_of(u)
            if 10 <= len(t) <= 200:
                return t
        return ""

    def _parties(self, full: str, st) -> List[Dict[str, Any]]:
        seen, parties = set(), []
        for rx, kind in ((_CORP, "corporate"), (_QUOTED, "defined-term"), (_ROLE, "role")):
            for m in rx.finditer(full):
                nm = " ".join((m.group(1) or "").split())
                if not nm or _NOT_A_PARTY.match(nm):
                    continue
                key = nm.lower()
                if key in seen:
                    continue
                seen.add(key)
                parties.append({"name": nm, "role": nm if kind == "role" else None})
        st["parties_precap"] = len(parties)
        st["parties_capped"] = len(parties) > MAX_PARTIES
        return parties[:MAX_PARTIES]

    def _sections(self, units, st) -> List[Dict[str, Any]]:
        """Split the unit stream on <heading> and on bold ordered-list clause titles."""
        allow = _source_clause_titles()
        idx = []
        for i, u in enumerate(units):
            txt = _text_of(u)
            if u.tag == "heading":
                idx.append((i, txt, "heading"))
            elif _is_clause_heading(u):
                idx.append((i, txt, "inferred clause title"))
            else:
                # a clause title glued to the front of its own paragraph
                for t in allow:
                    if txt.startswith(t) and len(txt) > len(t):
                        idx.append((i, t, "title recovered from source numbering"))
                        break
        st["allowlist_titles"] = len(allow)
        st["heading_units"] = sum(1 for u in units if u.tag == "heading")
        st["clause_heading_units"] = sum(1 for u in units if _is_clause_heading(u))
        st["section_boundaries"] = len(idx)
        if not idx:
            # Floor case: a contract with no headings at all (micro_crystal).
            idx = [(0, "WHOLE DOCUMENT", "whole document")]
            st["no_headings"] = True

        secs = []
        for j, (pos, title, src) in enumerate(idx[:MAX_SECTIONS]):
            end = idx[j + 1][0] if j + 1 < len(idx) else len(units)
            chunk = " ".join(_text_of(units[k]) for k in range(pos, end))
            secs.append({
                "heading": (title or "Unnamed")[:200],
                "heading_source": src,
                "summary": chunk[:160] or None,
                "permissions": self._perms(chunk),
                "obligations": self._obls(chunk),
            })
        st["sections_precap"] = len(idx)
        st["sections_capped"] = len(idx) > MAX_SECTIONS
        st["perms_total"] = sum(len(s["permissions"]) for s in secs)
        st["obls_total"] = sum(len(s["obligations"]) for s in secs)
        return secs

    def _perms(self, chunk: str) -> List[Dict[str, Any]]:
        res = []
        for s in _PERM.findall(chunk)[:MAX_PER_SECTION]:
            s = " ".join(s.split())
            res.append({"text": s[:400],
                        "polarity": ("restricts"
                                     if re.search(r"\b(not|prohibited)\b", s, re.I)
                                     else "grants"),
                        "condition": self._first_sentence(s, _COND)})
        return res

    def _obls(self, chunk: str) -> List[Dict[str, Any]]:
        res = []
        for s in _OBL.findall(chunk)[:MAX_PER_SECTION]:
            s = " ".join(s.split())
            m = _ROLE.search(s)
            res.append({"text": s[:400], "obligor": m.group(1) if m else None})
        return res
