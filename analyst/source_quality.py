from urllib.parse import urlsplit

GOVERNMENT_SUFFIXES = (".gov", ".gov.in", ".nic.in", ".gov.uk", ".gov.au", ".gc.ca")
REGULATORS = (
    "rbi.org.in",
    "sebi.gov.in",
    "irdai.gov.in",
    "niti.gov.in",
    "mca.gov.in",
    "fada.in",
)
CONSULTING = (
    "mckinsey.com",
    "bain.com",
    "bcg.com",
    "deloitte.com",
    "pwc.com",
    "ey.com",
    "kearney.com",
    "oliverwyman.com",
    "arthur.d.little.com",
)
INDUSTRY = (
    "iea.org",
    "acea.auto",
    "siam.in",
    "fada.in",
    "bnef.com",
    "woodmac.com",
    "s&Pglobal.com",
)
ACADEMIC = (".edu", ".ac.in", ".ac.uk", "researchgate.net", "sciencedirect.com")
# COMPANY = ("tatamotors.com", "olaelectric.com", "atherenergy.com", "mahindra.com", "hyundai.com", "mgmotor.co.in", "tvsmotor.com", "bajajauto.com", "heromotocorp.com")


def classify_source(url: str, verified_company_hosts=()):
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    if any(
        host == x.lower().removeprefix("www.")
        or host.endswith("." + x.lower().removeprefix("www."))
        for x in verified_company_hosts
        if x
    ):
        return "company", "primary"
    if host.endswith(GOVERNMENT_SUFFIXES):
        return "government", "primary"
    if any(host == x or host.endswith("." + x) for x in REGULATORS):
        return "regulator", "primary"
    if any(host == x or host.endswith("." + x) for x in CONSULTING):
        return "consulting", "expert"
    if any(host == x or host.endswith("." + x) for x in INDUSTRY):
        return "industry", "expert"
    # if any(host == x or host.endswith("." + x) for x in COMPANY): return "company", "primary"
    if host.endswith(ACADEMIC):
        return "academic", "expert"
    # Company domains are only classified after retrieval; generic blogs remain secondary.
    return "other", "unclassified"


def quality_score(source: dict):
    return {
        "government": 100,
        "regulator": 98,
        "company": 94,
        "consulting": 90,
        "industry": 86,
        "academic": 84,
        "news": 55,
        "other": 35,
    }.get(source.get("source_tier"), 35)
