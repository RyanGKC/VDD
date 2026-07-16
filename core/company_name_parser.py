"""
Company name normalization and jurisdiction extraction.

Splits a raw company name into (core_name, legal_suffix, jurisdiction) so that
jurisdiction/legal-form information can be used as an explicit comparison
feature instead of being buried inside a single fuzzy-matched string.
"""

import re
from dataclasses import dataclass
from typing import Optional

# Legal suffix -> jurisdiction. Extend as needed; unmatched suffixes fall
# back to jurisdiction=None rather than raising, since coverage will always
# be partial for a global company universe.
LEGAL_SUFFIX_JURISDICTION = {
    "sdn. bhd.": "Malaysia",
    "sdn bhd": "Malaysia",
    "bhd": "Malaysia",
    "pty ltd": "Australia",
    "pty. ltd.": "Australia",
    "gmbh": "Germany",
    "ag": "Germany/Switzerland",
    "s.a.": "France/Spain/Latin America",
    "sa": "France/Spain/Latin America",
    "s.r.l.": "Italy/Romania",
    "srl": "Italy/Romania",
    "b.v.": "Netherlands",
    "bv": "Netherlands",
    "n.v.": "Netherlands/Belgium",
    "nv": "Netherlands/Belgium",
    "co., ltd.": None,  # too generic across CN/JP/KR/TW to assign one country
    "co ltd": None,
    "ltd": None,  # too generic globally (UK, HK, SG, etc.) without more context
    "limited": None,
    "llc": "United States",
    "l.l.c.": "United States",
    "inc": "United States",
    "inc.": "United States",
    "incorporated": "United States",
    "corp": "United States",
    "corporation": "United States",
    "kk": "Japan",
    "k.k.": "Japan",
    "pvt ltd": "India",
    "pvt. ltd.": "India",
    "private limited": "India",
}

# Sorted longest-first so multi-word suffixes match before their substrings
# (e.g. "sdn. bhd." before "bhd").
_SUFFIX_PATTERN = re.compile(
    r"(?i)\b("
    + "|".join(re.escape(s) for s in sorted(LEGAL_SUFFIX_JURISDICTION, key=len, reverse=True))
    + r")\b\.?\s*$"
)

_PAREN_COUNTRY_PATTERN = re.compile(r"\(([^)]+)\)\s*$")


@dataclass
class ParsedCompanyName:
    raw_name: str
    core_name: str
    legal_suffix: Optional[str]
    jurisdiction: Optional[str]
    jurisdiction_source: Optional[str]  # "parenthetical" | "suffix_taxonomy" | None


def parse_company_name(raw_name: str) -> ParsedCompanyName:
    name = raw_name.strip()

    # 1. Parenthetical jurisdiction hint takes priority — it's explicit and
    #    unambiguous when present, e.g. "Huawei Technologies (Malaysia) Sdn. Bhd."
    paren_jurisdiction = None
    paren_match = _PAREN_COUNTRY_PATTERN.search(name)
    working_name = name
    if paren_match:
        candidate = paren_match.group(1).strip()
        if len(candidate.split()) <= 3 and not candidate.lower().startswith("formerly"):
            paren_jurisdiction = candidate
            working_name = name[: paren_match.start()].strip()

    # 2. Strip legal suffix from the end, recording it and its jurisdiction
    #    mapping if the taxonomy has one.
    suffix_match = _SUFFIX_PATTERN.search(working_name)
    legal_suffix = None
    suffix_jurisdiction = None
    core_name = working_name
    if suffix_match:
        legal_suffix = suffix_match.group(1)
        suffix_jurisdiction = LEGAL_SUFFIX_JURISDICTION.get(legal_suffix.lower())
        core_name = working_name[: suffix_match.start()].strip().rstrip(",").strip()

    jurisdiction = paren_jurisdiction or suffix_jurisdiction
    jurisdiction_source = (
        "parenthetical" if paren_jurisdiction else ("suffix_taxonomy" if suffix_jurisdiction else None)
    )

    return ParsedCompanyName(
        raw_name=raw_name,
        core_name=core_name,
        legal_suffix=legal_suffix,
        jurisdiction=jurisdiction,
        jurisdiction_source=jurisdiction_source,
    )
