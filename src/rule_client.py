"""A deterministic, rule-based stand-in for an LLM client.

docling_graph.protocols.LLMClientProtocol only requires get_json_response() to
return schema-valid JSON. Nothing in that contract says a language model has to
produce it. This implementation uses regexes over the document text that
docling-graph puts in the prompt, so the whole pipeline -- docling conversion,
chunking, prompt construction, graph conversion, export, visualisation -- runs
end to end with NO model, NO network and NO download.

It also logs every prompt and schema it is handed, which is how the prompt shape
gets characterised.
"""
import json, os, re, time
from typing import Any, Dict, Iterator, List, Mapping

LOG = os.environ.get("DG_CALLLOG", "calls")
os.makedirs(LOG, exist_ok=True)


def _text(prompt) -> str:
    if isinstance(prompt, Mapping):
        return "\n".join(str(v) for v in prompt.values())
    return str(prompt)


_DATE = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
                   r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\b")
_DUR = re.compile(r"\b(?:for\s+)?((?:\w+\s+)?\(?\d+\)?\s*(?:day|week|month|year)s?)\b", re.I)
_MONEY = re.compile(r"(?:US\$|\$|USD\s*)\s?[\d,]+(?:\.\d{2})?")
_NET = re.compile(r"\bnet\s+\d+\b", re.I)
_HEAD = re.compile(r"^\s{0,3}(?:#{1,6}\s+(?P<atx>.+?)|(?P<num>\d+(?:\.\d+)*)\.?\s+(?P<numt>[A-Z][^\n]{3,80})|"
                   r"(?P<caps>[A-Z][A-Z0-9 ,'&/\-]{6,80}))\s*$", re.M)
# a permission is a modal, and the conditional-grant form is what actually matters
_PERM = re.compile(r"[^.\n]*\b(?:may|shall\s+not|must\s+not|is\s+(?:not\s+)?permitted|"
                   r"is\s+entitled|prohibited)\b[^.\n]*\.", re.I)
_OBL = re.compile(r"[^.\n]*\b(?:shall|must|is\s+required\s+to|agrees\s+to)\b[^.\n]*\.", re.I)
_COND = re.compile(r"\bwithout\s+(?:the\s+)?(?:prior\s+)?written\s+consent\b|\bsubject\s+to\b|"
                   r"\bprovided\s+that\b|\bunless\b", re.I)
_PARTY = re.compile(r'"([A-Z][A-Za-z ]{2,30})"|\b(Supplier|Customer|Manufacturer|Buyer|Seller|'
                    r'Licensor|Licensee|Vendor|Contractor|Client|Company)\b')


def _first(rx, s, grp=0):
    m = rx.search(s)
    return m.group(grp).strip() if m else None


class RuleBasedClient:
    """Deterministic. No model, no network."""
    model = "rule-based-regex/none"

    def __init__(self):
        self.n = 0

    def get_json_response(self, prompt, schema_json: str, structured_output: bool = True,
                          response_top_level: str = "object",
                          response_schema_name: str = "extraction_result", **kw):
        self.n += 1
        body = _text(prompt)
        # record exactly what docling-graph asked for
        with open(os.path.join(LOG, "call_%03d.json" % self.n), "w") as fh:
            json.dump({"call": self.n, "ts": time.time(), "top_level": response_top_level,
                       "schema_name": response_schema_name,
                       "structured_output": structured_output,
                       "prompt_chars": len(body), "prompt": body,
                       "schema": json.loads(schema_json) if schema_json else None}, fh, indent=1)

        try:
            schema = json.loads(schema_json) if schema_json else {}
        except Exception:
            schema = {}
        out = self._fill(schema, body)
        return [out] if response_top_level == "array" else out

    def get_json_response_stream(self, prompt, schema_json, structured_output=True,
                                 response_top_level="object",
                                 response_schema_name="extraction_result", **kw) -> Iterator:
        yield self.get_json_response(prompt, schema_json, structured_output,
                                     response_top_level, response_schema_name, **kw)

    # -- schema-aware filling -------------------------------------------------
    def _fill(self, schema: Dict[str, Any], body: str) -> Dict[str, Any]:
        """Only emit keys the handed schema actually declares."""
        props = (schema or {}).get("properties") or {}
        out: Dict[str, Any] = {}

        if "title" in props:
            out["title"] = (_first(re.compile(r"^#\s+(.+)$", re.M), body, 1)
                            or _first(re.compile(r"^([A-Z][A-Z0-9 ,'&/\-]{10,90})$", re.M), body, 1)
                            or "Untitled Agreement")
        if "parties" in props:
            seen, parties = set(), []
            for m in _PARTY.finditer(body):
                nm = (m.group(1) or m.group(2) or "").strip()
                if nm and nm.lower() not in seen:
                    seen.add(nm.lower())
                    parties.append({"name": nm, "role": nm if m.group(2) else None})
                if len(parties) >= 8:
                    break
            out["parties"] = parties
        if "term" in props:
            dates = _DATE.findall(body)
            out["term"] = {"effective_date": dates[0] if dates else None,
                           "expiry_date": dates[1] if len(dates) > 1 else None,
                           "duration": _first(_DUR, body, 1),
                           "renewal": _first(re.compile(r"[^.\n]*\brenew[^.\n]*\.", re.I), body)}
        if "payment" in props:
            amt = _first(_MONEY, body)
            out["payment"] = {"amount": amt, "currency": "USD" if amt else None,
                              "net_days": _first(_NET, body)}
        if "sections" in props:
            out["sections"] = self._sections(body)
        # sub-schemas handed during dense fill
        if "heading" in props and "sections" not in props:
            out.update(self._one_section(body))
        if "text" in props and "heading" not in props:
            out["text"] = (_first(_PERM, body) or _first(_OBL, body) or body[:200].strip())
            if "polarity" in props:
                out["polarity"] = "restricts" if re.search(r"\bnot\b", out["text"], re.I) else "grants"
            if "condition" in props:
                out["condition"] = _first(_COND, body)
            if "obligor" in props:
                out["obligor"] = _first(_PARTY, body)
        if "name" in props and "role" in props:
            out["name"] = _first(_PARTY, body) or "Unknown Party"
            out["role"] = out["name"]
        return out

    def _one_section(self, chunk: str) -> Dict[str, Any]:
        m = _HEAD.search(chunk)
        head = (m.group("atx") or m.group("numt") or m.group("caps")).strip() if m else \
            (chunk.strip().split("\n")[0][:80] or "Unnamed")
        return {"heading": head,
                "summary": " ".join(chunk.split())[:160] or None,
                "permissions": self._perms(chunk), "obligations": self._obls(chunk)}

    def _sections(self, body: str) -> List[Dict[str, Any]]:
        spans, secs = [], []
        for m in _HEAD.finditer(body):
            t = (m.group("atx") or m.group("numt") or m.group("caps") or "").strip()
            if t:
                spans.append((m.start(), t))
        if not spans:
            spans = [(0, "WHOLE DOCUMENT")]
        for i, (pos, title) in enumerate(spans[:60]):
            end = spans[i + 1][0] if i + 1 < len(spans) else len(body)
            chunk = body[pos:end]
            secs.append({"heading": title,
                         "summary": " ".join(chunk.split())[:160] or None,
                         "permissions": self._perms(chunk),
                         "obligations": self._obls(chunk)})
        return secs

    def _perms(self, chunk: str) -> List[Dict[str, Any]]:
        res = []
        for s in _PERM.findall(chunk)[:5]:
            s = " ".join(s.split())
            res.append({"text": s[:400],
                        "polarity": "restricts" if re.search(r"\b(not|prohibited)\b", s, re.I) else "grants",
                        "condition": _first(_COND, s)})
        return res

    def _obls(self, chunk: str) -> List[Dict[str, Any]]:
        res = []
        for s in _OBL.findall(chunk)[:5]:
            s = " ".join(s.split())
            res.append({"text": s[:400], "obligor": _first(_PARTY, s)})
        return res
