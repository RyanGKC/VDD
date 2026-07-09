from urllib.parse import urlparse

# Curated allowlist of reliable domains for VDD purposes.
# Seed this from existing structured sources (EDGAR, Companies House, etc.)
# plus major wire services and financial press.
ALLOWLIST: set[str] = {
    "reuters.com", "apnews.com", "bloomberg.com",
    "sec.gov", "gov.uk", "companieshouse.gov.uk",
    "fca.org.uk", "sam.gov", "hmrc.gov.uk",
    "wsj.com", "ft.com", "economist.com", "cnbc.com", "forbes.com",
    "nytimes.com", "bbc.com", "theguardian.com", "washingtonpost.com", "npr.org",
    "hbr.org", "mckinsey.com", "investopedia.com", "yahoo.com",
    "businessinsider.com", "techcrunch.com", "wired.com", "fortune.com",
    "thestar.com.my", "malaymail.com", "nst.com.my", "theedgemalaysia.com",
    "bernama.com", "freemalaysiatoday.com",
}

BLOCKLIST: set[str] = {
    # Paywalled research / spam report sites
    "statista.com", "ibisworld.com", "researchandmarkets.com",
    "gartner.com", "forrester.com", "marketsandmarkets.com",
    "grandviewresearch.com", "mordorintelligence.com",
    "fortunebusinessinsights.com", "globenewswire.com",
    "prnewswire.com", "businesswire.com", "reportlinker.com",
}

# TLDs treated as inherently high-trust regardless of allowlist membership
HIGH_TRUST_TLDS = (".gov", ".gov.uk", ".edu", ".ac.uk")

def get_domain(url: str) -> str:
    netloc = urlparse(url).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc

def check_tier(url: str, company_domain: str | None = None, dynamic_allow: set[str] | None = None, dynamic_block: set[str] | None = None) -> str:
    """Returns 'allow', 'block', or 'unknown'."""
    domain = get_domain(url)
    dynamic_allow = dynamic_allow or set()
    dynamic_block = dynamic_block or set()

    if company_domain and domain == company_domain:
        return "allow"
    
    if domain.endswith(HIGH_TRUST_TLDS):
        return "allow"
        
    parts = domain.split(".")
    for i in range(max(1, len(parts) - 1)):
        suffix = ".".join(parts[i:])
        if suffix in ALLOWLIST or suffix in dynamic_allow:
            return "allow"
        if suffix in BLOCKLIST or suffix in dynamic_block:
            return "block"

    return "unknown"


