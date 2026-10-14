"""Deterministic company checks; a shared exchange hostname is not an issuer."""

import re
from urllib.parse import urlsplit


def company_key(name):
    name = re.sub(r"\b(?:limited|ltd|and)\b", "", name.casefold())
    return re.sub(r"[^a-z0-9]", "", name)


def matches_company(text, company):
    data = company.get("data", company)
    isin = data.get("isin", "")
    if isin and re.search(r"\b" + re.escape(isin) + r"\b", text, re.I):
        return True
    key = company_key(data.get("name", ""))
    if len(key) >= 6 and key in company_key(text):
        return True
    return key == "larsentoubro" and bool(re.search(r"\bL\s*&\s*T\b", text, re.I))


def report_identity(company, pages):
    # Opening headings/cover, not incidental mentions buried in a report.
    opening = "\n".join(p["text"][:5000] for p in pages[:3])
    issuer = None
    for line in opening.splitlines():
        line = re.sub(r"^(?:to\s+the\s+members\s+of|company\s*:)\s*", "", line.strip(), flags=re.I)
        if re.match(r"^(?:of|the|for|from|by|in|a|an|and)\b", line, re.I):
            continue
        match = re.match(r"^([A-Za-z][A-Za-z &.'’()-]{2,85}?\b(?:Limited|Ltd\.?))\b", line)
        if match and not re.search(r"\b(?:report|statement|audit|financial|notes)\b", match[1], re.I):
            issuer = match[1].strip()
            break
    expected = company_key(company["data"]["name"])
    if issuer and company_key(issuer) != expected:
        return {"status": "mismatch", "issuer": issuer, "company_id": company["id"]}
    if matches_company(opening, company):
        return {"status": "matched", "issuer": issuer or company["data"]["name"], "company_id": company["id"]}
    return {"status": "unverified", "issuer": issuer, "company_id": company["id"]}


def candidate_matches(item, company):
    filing = re.search(r"/AR_\d+_([A-Z0-9]+)_20\d{2}_20\d{2}(?:_|\.)", urlsplit(item.get("url", "")).path, re.I)
    if filing and filing[1].casefold() != company["data"].get("symbol", "").casefold():
        return False
    title = item.get("title", "")
    # Never trust the snippet to override an explicitly different issuer title.
    other = report_identity(company, [{"text": title}])
    if other["status"] == "mismatch":
        return False
    text = title + " " + item.get("content", "")
    if matches_company(text, company):
        return True
    official = urlsplit(company["data"].get("website") or "").hostname
    host = urlsplit(item.get("url", "")).hostname
    return bool(official and host and (host == official or host.endswith("." + official)))


async def validate_company_document(store, doc):
    data = doc["data"]
    identity = data.get("company_identity", {})
    if identity.get("company_id") == data["company_id"] and identity.get("status") in {"matched", "owner_confirmed"}:
        return
    company = await store.record("company", data["company_id"])
    identity = report_identity(company, await store.pages(doc["id"], 1, 3))
    if identity["status"] != "matched":
        raise ValueError(f"Report ‘{data.get('title', 'Report')}’ is not verified as belonging to {company['data']['name']}. Confirm an unidentified report in Library or choose the correct company's filing.")
