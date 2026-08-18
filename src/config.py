"""
Central config: paths, the Landing endpoint, API-key loading, score weights.

Correctness-first by design: throughput is measured but is NOT part of the
closeness score. The score is completeness + structure + similarity + clean.
"""
from __future__ import annotations

import os
import re

# ---- paths ---------------------------------------------------------------
PARSEEVAL_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(PARSEEVAL_DIR)                       # gap-format-prototype/
INPUTS = os.path.join(PARSEEVAL_DIR, "inputs")
INPUTS_PDF = os.path.join(INPUTS, "pdf")
INPUTS_GAP = os.path.join(INPUTS, "gap")
OUT = os.path.join(PARSEEVAL_DIR, "out")                    # per-file parser outputs + diffs
GOLD = os.path.join(PARSEEVAL_DIR, "gold")                  # cached Landing gold markdown
SECRETS = os.path.join(ROOT, "secrets")
KEY_FILE = os.path.join(SECRETS, "landing_api_key.txt")

# the modern-Python venv that hosts markitdown / docling (created with uv)
VENV_PARSERS_PY = os.path.join(ROOT, "venv-parsers", "bin", "python")
EXT_RUNNER = os.path.join(PARSEEVAL_DIR, "_ext_runner.py")

for d in (INPUTS_PDF, INPUTS_GAP, OUT, GOLD, SECRETS):
    os.makedirs(d, exist_ok=True)

# ---- Landing ADE ---------------------------------------------------------
# US / Virginia endpoint. EU endpoint (api.va.eu-west-1.landing.ai) intentionally ignored.
LANDING_ENDPOINT = "https://api.va.landing.ai/v1/ade/parse"
LANDING_MODEL = os.environ.get("LANDING_MODEL", "dpt-2-latest")
# Formats Landing ADE accepts directly (used to decide when we can auto-generate gold).
LANDING_INPUT_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".webp",
                      ".bmp", ".gif", ".xlsx", ".csv"}
# Skip auto-uploading very large PDFs (slow + credit cost); flag them instead.
MAX_LANDING_MB = float(os.environ.get("MAX_LANDING_MB", "20"))

# ---- score weights (correctness-first; throughput excluded on purpose) ---
SCORE_WEIGHTS = {
    "completeness": 0.35,   # did every value / line survive?  (no content silently dropped)
    "similarity":   0.35,   # overall text closeness to gold   (reads the same as Landing)
    "structure":    0.20,   # tables + headings + lists reconstructed like gold
    "cleanliness":  0.10,   # no MIME/RTF/markup junk, no flattened tables
}


def load_api_key() -> str | None:
    """
    LANDING_API_KEY env var wins; else the first real key line in the key file.
    Skips comments AND the leftover PASTE_YOUR_KEY_HERE placeholder. Tolerant of
    common paste shapes:  bare key  |  key="..."  |  name: "..."  |  export X=...
    """
    import re

    def _extract(raw: str) -> str:
        s = raw.strip()
        if s.lower().startswith("export "):
            s = s[7:].strip()
        # a quoted value is the strongest signal of "the key is in here"
        q = re.search(r'["\']([^"\']{8,})["\']', s)
        if q:
            return q.group(1).strip()
        if "=" in s:                       # env-style assignment
            s = s.split("=")[-1]
        return s.strip().strip('"').strip("'").strip()

    env = _extract(os.environ.get("LANDING_API_KEY", ""))
    if env:
        return env
    if os.path.isfile(KEY_FILE):
        for line in open(KEY_FILE, encoding="utf-8", errors="replace"):
            s = line.strip()
            if not s or s.startswith("#") or s == "PASTE_YOUR_KEY_HERE":
                continue
            k = _extract(s)
            if k and k != "PASTE_YOUR_KEY_HERE":
                return k
    return None


# numeric / currency / date / id tokens — the values that MUST survive in a contract
NUM_RE = re.compile(
    r"""(?xi)
      \$\s?\d[\d,]*(?:\.\d+)?          # $1,234.56
    | \b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b # 1,234,567
    | \b\d+\.\d+\b                     # 175.50
    | \b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b# 04/01/2026
    | \b\d+%\b                         # 12%
    | \b[A-Z]{1,4}\d{4,}\b             # CW1234567, INV2048-style ids
    | \b\d{4,}\b                       # bare long numbers / years / ids
    """,
)
