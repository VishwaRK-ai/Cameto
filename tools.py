import asyncio
from datetime import datetime
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional
import urllib.parse
import urllib.request

try:
    import whois
except ImportError:
    whois = None

try:
    from googleapiclient.discovery import build
except ImportError:
    build = None

logger = logging.getLogger("tools")

# ---------------------------------------------------------
# Strict Indian Forensic Regexes
# ---------------------------------------------------------
# Matches strict Indian payment handles only, avoiding regular email addresses
STRICT_UPI_PATTERN = r"\b[a-zA-Z0-9.\-_]{2,40}@(ybl|paytm|upi|sbi|icici|okaxis|axl|ibl)\b"

# Matches Indian phone numbers: +91 with 10 digits, or standard 10 digits starting with 6-9
STRICT_INDIAN_PHONE_PATTERN = r"(?:\+91[\-\s]?)?[6-9]\d{9}\b"

URL_PATTERN = r"https?://[^\s<>\"']+|www\.[^\s<>\"']+"

FINANCIAL_KEYWORDS = [
    "investment", "returns", "trading", "crypto", "profit",
    "guaranteed", "sebi", "rbi", "deposit", "dividend",
    "forex", "mutual fund", "stocks", "bonus"
]


# ---------------------------------------------------------
# Domain & WHOIS Inspection
# ---------------------------------------------------------
def _sync_check_domain_whois(domain: str) -> Dict[str, Any]:
    """
    Synchronously queries python-whois for domain creation date.
    Flags domains registered < 6 months (< 180 days) ago as high risk.
    """
    clean_domain = re.sub(r"^https?://", "", domain).split("/")[0].split(":")[0].strip().lower()
    if not whois:
        return {
            "domain": clean_domain,
            "status": "unsupported",
            "is_high_risk": False,
            "detail": f"Domain '{clean_domain}' extracted (python-whois module optional)."
        }

    try:
        w = whois.whois(clean_domain)
        creation = w.creation_date
        if isinstance(creation, list):
            creation = creation[0]

        if creation:
            if hasattr(creation, "tzinfo") and creation.tzinfo is not None:
                creation = creation.replace(tzinfo=None)
            now = datetime.now()
            age_days = (now - creation).days
            is_high_risk = age_days < 180
            return {
                "domain": clean_domain,
                "status": "success",
                "creation_date": str(creation.date() if hasattr(creation, "date") else creation),
                "age_days": age_days,
                "is_high_risk": is_high_risk,
                "registrar": str(w.registrar or "Unknown"),
                "detail": f"Domain '{clean_domain}' registered {age_days} days ago ({'CRITICAL RISK: < 6 months old' if is_high_risk else 'Established domain'})."
            }
        return {
            "domain": clean_domain,
            "status": "no_creation_date",
            "is_high_risk": False,
            "detail": f"Domain '{clean_domain}' resolved without creation timestamp."
        }
    except Exception as e:
        return {
            "domain": clean_domain,
            "status": "error",
            "is_high_risk": False,
            "detail": f"WHOIS query for '{clean_domain}': {str(e)[:60]}"
        }


async def check_domain_whois(domain: str) -> Dict[str, Any]:
    """Asynchronously inspects WHOIS domain registration date without blocking."""
    return await asyncio.to_thread(_sync_check_domain_whois, domain)


# ---------------------------------------------------------
# Scam Signal & Entity Extraction
# ---------------------------------------------------------
async def scan_scam_signals(text: str) -> Dict[str, Any]:
    """
    Extracts URLs, strict Indian UPI IDs, and Indian phone numbers using hardened regexes.
    Performs non-blocking WHOIS domain age lookups on extracted URLs.
    """
    # 1. URLs
    urls = list(dict.fromkeys(re.findall(URL_PATTERN, text, re.IGNORECASE)))

    # 2. Strict Indian UPI IDs (only @ybl, @paytm, @upi, @sbi, @icici, @okaxis, @axl, @ibl)
    raw_upis = re.findall(STRICT_UPI_PATTERN, text, re.IGNORECASE)
    # Re-scan to extract the full handle
    upis = list(dict.fromkeys(
        re.findall(r"\b[a-zA-Z0-9.\-_]{2,40}@(ybl|paytm|upi|sbi|icici|okaxis|axl|ibl)\b", text, re.IGNORECASE)
    ))
    # Correctly capture full matched strings
    full_upis = []
    for match in re.finditer(STRICT_UPI_PATTERN, text, re.IGNORECASE):
        full_upis.append(match.group(0))
    upis = list(dict.fromkeys(full_upis))

    # 3. Indian Phone Numbers
    phones = list(dict.fromkeys(re.findall(STRICT_INDIAN_PHONE_PATTERN, text)))

    # 4. Financial Securities & High-Yield Scam Keywords
    found_keywords = [
        kw for kw in FINANCIAL_KEYWORDS
        if re.search(rf"\b{re.escape(kw)}\b", text, re.IGNORECASE)
    ]

    # 5. Non-blocking WHOIS domain inspections
    domain_risks = []
    for u in urls:
        parsed = urllib.parse.urlparse(u if u.startswith("http") else f"http://{u}")
        domain = parsed.netloc or parsed.path
        if domain:
            whois_info = await check_domain_whois(domain)
            domain_risks.append(whois_info)

    return {
        "urls": urls,
        "upis": upis,
        "phones": phones,
        "domain_risks": domain_risks,
        "has_financial_securities": len(found_keywords) > 0,
        "financial_keywords": found_keywords,
    }


# ---------------------------------------------------------
# Certificate Transparency: Brand Lookalike Discovery
# ---------------------------------------------------------
def extract_brand_keyword(domain: str = "", text: str = "") -> str:
    """
    Extracts the core target brand or entity keyword (e.g. 'sitharaman', 'sbi', 'paytm')
    to uncover lookalike infrastructure across Certificate Transparency logs.
    """
    if domain:
        clean_d = re.sub(r"^https?://", "", domain).split("/")[0].split(":")[0].lower()
        clean_d = re.sub(r"^www\.", "", clean_d)
        parts = clean_d.split(".")[0].split("-")
        meaningful = [
            p for p in parts
            if len(p) > 3 and p not in {"portal", "login", "secure", "online", "verify", "update", "service", "claim"}
        ]
        if meaningful:
            return meaningful[0]

    # Search for known high-profile targets in text
    targets = ["sitharaman", "sbi", "paytm", "hdfc", "icici", "sebi", "rbi", "crypto", "mudra", "yojana", "rozgar"]
    for target in targets:
        if re.search(rf"\b{target}\b", text, re.IGNORECASE):
            return target

    return ""


def levenshtein_distance(s1: str, s2: str) -> int:
    """Computes Levenshtein distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def _sync_query_crt_sh_brand_lookalikes(brand_keyword: str) -> List[str]:
    """
    Queries crt.sh using %brand% to discover lookalike scam certificates.
    Filters out noise using strict substring matching or Levenshtein edit distance <= 2.
    Strict 5-second timeout.
    """
    clean_brand = brand_keyword.strip().lower()
    if not clean_brand or len(clean_brand) < 3:
        return []

    # Skip generic words that match millions of certificates
    generic_skips = {"online", "secure", "portal", "update", "service", "google", "apple", "microsoft", "github"}
    if clean_brand in generic_skips:
        return []

    # Query with %brand% wildcard pattern
    url = f"https://crt.sh/?q=%25{urllib.parse.quote(clean_brand)}%25&output=json"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) DigitalScam-CT/2.0"}
    )

    lookalikes: set[str] = set()
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                for entry in data[:40]:
                    name_val = entry.get("name_value", "")
                    if name_val:
                        for item in name_val.split("\n"):
                            cand = item.strip().lower()
                            cand = re.sub(r"^\*\.", "", cand)
                            if cand and not cand.startswith("www.") and "." in cand:
                                lookalikes.add(cand)
                    common_name = entry.get("common_name", "")
                    if common_name:
                        cand = common_name.strip().lower()
                        cand = re.sub(r"^\*\.", "", cand)
                        if cand and not cand.startswith("www.") and "." in cand:
                            lookalikes.add(cand)
    except Exception as e:
        logger.warning(f"Certificate Transparency lookup error for brand '{clean_brand}': {e}")
        return []

    # Exclude common legitimate giant domains
    trusted_giants = {"google.com", "youtube.com", "reddit.com", "twitter.com", "x.com", "github.com", "wikipedia.org"}
    filtered = []
    for d in lookalikes:
        if any(d == g or d.endswith(f".{g}") for g in trusted_giants):
            continue
        clean_cand = d.lower()
        # Direct substring match
        is_match = clean_brand in clean_cand
        if not is_match:
            # Check individual tokens for edit distance <= 2
            tokens = re.split(r"[\.\-_]", clean_cand)
            is_match = any(
                abs(len(t) - len(clean_brand)) <= 2 and levenshtein_distance(t, clean_brand) <= 2
                for t in tokens if len(t) >= 3
            )
        if is_match:
            filtered.append(d)

    return sorted(filtered)[:10]


async def query_crt_sh_brand_lookalikes(brand_keyword: str) -> List[str]:
    """Asynchronously queries crt.sh for Certificate Brand Lookalikes."""
    return await asyncio.to_thread(_sync_query_crt_sh_brand_lookalikes, brand_keyword)


# Alias for backward compatibility
query_crt_sh_siblings = query_crt_sh_brand_lookalikes


# ---------------------------------------------------------
# Live Fact Check Tool (Google Fact Check Tools API)
# ---------------------------------------------------------
def _sync_query_google_fact_check(query_text: str, search_query: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Synchronously queries Google Fact Check Tools API without hardcoded language restrictions.
    """
    api_key = (
        os.getenv("FACTCHECK_API_KEY")
        or os.getenv("GOOGLE_FACTCHECK_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or ""
    ).strip().strip('"\'')

    effective_query = (search_query or query_text).strip()
    if not effective_query:
        return []

    claims_found: List[Dict[str, Any]] = []

    # 1. Try googleapiclient.discovery if available
    if api_key and build:
        try:
            service = build("factchecktools", "v1alpha1", developerKey=api_key)
            # Do NOT restrict to languageCode="en" so multilingual claims are verified
            req = service.claims().search(query=effective_query, pageSize=5)
            res = req.execute()
            for c in res.get("claims", []):
                reviews = c.get("claimReview", [])
                if reviews:
                    rev = reviews[0]
                    source_url = (rev.get("url") or rev.get("publisher", {}).get("site", "") or "").strip()
                    if not source_url or not source_url.startswith("http") or "news.google.com" in source_url:
                        continue
                    claims_found.append({
                        "claim": c.get("text", ""),
                        "rating": rev.get("textualRating", "Unverified"),
                        "publisher": rev.get("publisher", {}).get("name", "Fact-Checker"),
                        "url": source_url,
                        "title": rev.get("title", ""),
                    })
            if claims_found:
                return claims_found
        except Exception as e:
            logger.warning(f"Live googleapiclient search notice: {e}")

    # 2. Try Google Fact Check Tools REST API fallback
    try:
        params = {"query": effective_query, "pageSize": 5}
        if api_key:
            params["key"] = api_key
        url = f"https://factchecktools.googleapis.com/v1alpha1/claims:search?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "DigitalScam-FactCheckLiveAgent/2.0"}
        )
        with urllib.request.urlopen(req, timeout=6) as response:
            data = json.loads(response.read().decode("utf-8"))
            for c in data.get("claims", []):
                reviews = c.get("claimReview", [])
                if reviews:
                    rev = reviews[0]
                    source_url = (rev.get("url") or rev.get("publisher", {}).get("site", "") or "").strip()
                    if not source_url or not source_url.startswith("http") or "news.google.com" in source_url:
                        continue
                    claims_found.append({
                        "claim": c.get("text", ""),
                        "rating": rev.get("textualRating", "Unverified"),
                        "publisher": rev.get("publisher", {}).get("name", "Fact-Checker"),
                        "url": source_url,
                        "title": rev.get("title", ""),
                    })
    except Exception as e:
        logger.warning(f"Live Google REST Fact Check error: {e}")

    return claims_found


async def query_google_fact_check_live(query_text: str, search_query: Optional[str] = None) -> List[Dict[str, Any]]:
    """Asynchronously queries Google Fact Check Tools API with non-blocking I/O."""
    return await asyncio.to_thread(_sync_query_google_fact_check, query_text, search_query)


# ---------------------------------------------------------
# Wayback Machine Snapshot Tool
# ---------------------------------------------------------
def _sync_ping_wayback(target_url: str) -> Optional[str]:
    """
    Pings https://web.archive.org/save/{target_url} with strict 3-second timeout.
    Parses response headers to extract the actual https://web.archive.org/web/... snapshot URL.
    Returns None if failed, timed out, or not captured.
    """
    if not target_url or not target_url.startswith("http"):
        return None

    save_endpoint = f"https://web.archive.org/save/{target_url}"
    try:
        req = urllib.request.Request(
            save_endpoint,
            headers={"User-Agent": "DigitalScam-FactCheck-Archiver/2.0 (Mozilla/5.0)"}
        )
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            # Check Content-Location or Location header
            content_loc = resp.headers.get("Content-Location")
            location = resp.headers.get("Location")
            final_url = resp.geturl()

            for cand in [content_loc, location, final_url]:
                if cand and "/web/" in cand:
                    if cand.startswith("http"):
                        return cand
                    return f"https://web.archive.org{cand}"

            return None
    except Exception as e:
        logger.debug(f"Wayback snapshot ping note for '{target_url}' (ignored): {e}")
        return None


async def snapshot_to_wayback_machine(target_url: str) -> Optional[str]:
    """Asynchronously requests a Wayback Machine snapshot with strict 3s timeout."""
    return await asyncio.to_thread(_sync_ping_wayback, target_url)


async def snapshot_all_sources_to_wayback(source_urls: List[str]) -> List[str]:
    """
    Fires non-blocking snapshot tasks for all verified source URLs.
    Collects and returns only the actual snapshot URLs (no wildcard placeholders).
    """
    valid_urls = [u for u in dict.fromkeys(source_urls) if u.startswith("http")][:4]
    if not valid_urls:
        return []

    tasks = [snapshot_to_wayback_machine(u) for u in valid_urls]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    actual_snapshots: List[str] = []
    for r in results:
        if isinstance(r, str) and r.startswith("https://web.archive.org/web/"):
            actual_snapshots.append(r)

    return actual_snapshots


# ---------------------------------------------------------
# Verdict-to-Action Cybercrime Pre-Fill Report Dossier
# ---------------------------------------------------------
def generate_cybercrime_dossier(
    claim_text: str,
    verdict: str,
    confidence_score: float,
    scam_signals: Dict[str, Any],
    sibling_domains: List[str],
    matched_sources: List[str],
    receipt_id: str,
) -> str:
    """
    Generates structured 'Official Cybercrime Pre-Fill Report' markdown document.
    Includes explicit instructions for cybercrime.gov.in, 1930 Helpline,
    and DoT Sanchar Saathi (Chakshu).
    """
    has_signals = bool(
        scam_signals.get("urls")
        or scam_signals.get("upis")
        or scam_signals.get("phones")
        or sibling_domains
        or scam_signals.get("has_financial_securities")
        or verdict in ("False", "Misleading")
    )
    if not has_signals:
        return ""

    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    urls_str = "\n".join([f"- `{u}`" for u in scam_signals.get("urls", [])]) or "- None detected"
    upis_str = "\n".join([f"- `{upi}` (Strict Indian UPI Payment Handle)" for upi in scam_signals.get("upis", [])]) or "- None detected"
    phones_str = "\n".join([f"- `{p}` (Suspect Contact Number)" for p in scam_signals.get("phones", [])]) or "- None detected"

    domain_forensics = []
    for d in scam_signals.get("domain_risks", []):
        dom = d.get("domain", "")
        age = d.get("age_days", "Unknown")
        reg = d.get("registrar", "Unknown")
        risk = "HIGH RISK (< 6 months old)" if d.get("is_high_risk") else "Established"
        domain_forensics.append(f"- **Domain:** `{dom}` | **Registration Age:** {age} days ({risk}) | **Registrar:** {reg}")
    domain_forensics_str = "\n".join(domain_forensics) or "- No external domains analyzed"

    siblings_str = "\n".join([f"- `{s}`" for s in sibling_domains[:8]]) or "- No lookalike certificates found"
    sources_str = "\n".join([f"- {s}" for s in matched_sources[:5]]) or "- Ground-truth refutations cached in verified_facts"

    dossier = f"""# 🛡️ Official Cybercrime Pre-Fill Report
**Generated by DigitalScam ReAct Verification & Forensic Engine**

> **CRITICAL REPORTING INSTRUCTIONS:**
> 1. **Financial Fraud / Phishing:** File this report at **https://cybercrime.gov.in** or call the national **1930 Helpline** to freeze fraudulent bank transfers within the golden hour.
> 2. **Telecom / SMS / WhatsApp Fraud:** Report the mobile numbers, spoofed headers, or malicious links via **DoT Sanchar Saathi (Chakshu)** at https://sancharsaathi.gov.in.

---

### 1. Incident Metadata
- **Incident Timestamp:** {now_str}
- **Adjudication Verdict:** **{verdict}** (Confidence: {confidence_score:.1f}%)
- **Cryptographic Receipt ID:** `{receipt_id}`
- **Independent Verification URL:** `/api/verify/{receipt_id}`

### 2. Reported Social Media / Phishing Claim Text
```text
{claim_text.strip()}
```

### 3. Forensic Indicators of Compromise (IoCs)
#### A. Financial UPI Payment Handles
{upis_str}

#### B. Suspect Contact Numbers
{phones_str}

#### C. Flagged Phishing & Fraudulent URLs
{urls_str}

### 4. Infrastructure & Domain Forensics
#### A. WHOIS Domain Age & Registration
{domain_forensics_str}

#### B. Certificate Brand Lookalikes (crt.sh)
{siblings_str}

### 5. Verified Ground-Truth Refutations
{sources_str}

### 6. Recommended Legal Provisions (India)
- **Information Technology Act, 2000 (Section 66D):** Punishment for cheating by personation by using computer resource (imprisonment up to 3 years and fine).
- **Bharatiya Nyaya Sanhita, 2023 (Section 318(4) / erstwhile IPC 420):** Cheating and dishonestly inducing delivery of property (imprisonment up to 7 years).
- **DoT & TRAI Directives:** Blacklisting fraudulent caller CLI and immediate IMEI blocking via Sanchar Saathi.

---
*Note: This pre-filled cybercrime dossier is cryptographically anchored by Ed25519 signature in DigitalScam Transparency Log (`{receipt_id}`). Retain this document for your police complaint (FIR) submission.*
"""
    return dossier.strip()

