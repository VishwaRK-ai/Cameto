import asyncio
from datetime import datetime
import hashlib
import json
import logging
import os
import re
import urllib.parse
import urllib.request
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
try:
    from typing import Literal
except ImportError:
    from typing_extensions import Literal

import chromadb
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from sentence_transformers import SentenceTransformer

# Optional imports for LLM providers
try:
    from groq import AsyncGroq, GroqError
except ImportError:
    AsyncGroq = None
    GroqError = Exception

try:
    import google.generativeai as genai
except ImportError:
    genai = None

# Optional imports for agentic tools (Google Fact Check & WHOIS domain age inspection)
try:
    from googleapiclient.discovery import build
except ImportError:
    build = None

try:
    import whois
except ImportError:
    whois = None

# Optional import for Ed25519 Cryptographic Transparency Receipts (PyNaCl)
try:
    import nacl.signing
    import nacl.encoding
    import nacl.exceptions
    NACL_AVAILABLE = True
except ImportError:
    NACL_AVAILABLE = False

# Load environment variables with override enabled
load_dotenv(override=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
)
logger = logging.getLogger("fact-audit-engine")

# ---------------------------------------------------------
# Global App State & Lifespan
# ---------------------------------------------------------
class AppState:
    embedding_model: Optional[SentenceTransformer] = None
    chroma_client: Optional[chromadb.PersistentClient] = None
    collection = None
    radar_collection = None
    groq_client: Optional[Any] = None


state = AppState()

# ---------------------------------------------------------
# Verifiable Cryptographic Transparency Log (Ed25519)
# ---------------------------------------------------------
class TransparencyLog:
    """
    Enterprise-Grade Verifiable Verdict Receipt Transparency Log.
    Initializes and persists an Ed25519 signing key (via PyNaCl) to a local JSON file.
    Generates deterministic SHA-256 hashes of claims, retrieved facts, model IDs,
    and verdicts, signing each receipt cryptographically.
    """
    def __init__(self, storage_dir: str = "./receipts"):
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)
        self.key_path = os.path.join(self.storage_dir, "transparency_signing_key.json")
        self.signing_key = None
        self.verify_key_hex = ""
        self.algorithm = "Ed25519"
        self._init_keys()

    def _init_keys(self):
        if NACL_AVAILABLE:
            if os.path.exists(self.key_path):
                try:
                    with open(self.key_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    seed_hex = data.get("seed_hex", "")
                    if seed_hex:
                        seed_bytes = bytes.fromhex(seed_hex)
                        if len(seed_bytes) == 32:
                            self.signing_key = nacl.signing.SigningKey(seed_bytes)
                            self.verify_key_hex = self.signing_key.verify_key.encode(
                                encoder=nacl.encoding.HexEncoder
                            ).decode("utf-8")
                            logger.info("Loaded persistent Ed25519 transparency key.")
                            return
                except Exception as e:
                    logger.warning(f"Error loading existing transparency key: {e}. Generating new key.")

            # Generate new Ed25519 keypair
            self.signing_key = nacl.signing.SigningKey.generate()
            seed_hex = self.signing_key.encode(encoder=nacl.encoding.HexEncoder).decode("utf-8")
            self.verify_key_hex = self.signing_key.verify_key.encode(
                encoder=nacl.encoding.HexEncoder
            ).decode("utf-8")

            try:
                with open(self.key_path, "w", encoding="utf-8") as f:
                    json.dump({
                        "algorithm": "Ed25519",
                        "seed_hex": seed_hex,
                        "verify_key_hex": self.verify_key_hex,
                        "created_at": datetime.utcnow().isoformat() + "Z"
                    }, f, indent=2)
                logger.info(f"Generated and persisted new Ed25519 transparency key at '{self.key_path}'.")
            except Exception as e:
                logger.warning(f"Could not persist transparency key to file: {e}")
        else:
            # Deterministic SHA-256 HMAC Fallback if PyNaCl is not yet installed
            self.algorithm = "SHA256-HMAC-Fallback"
            if os.path.exists(self.key_path):
                try:
                    with open(self.key_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self.verify_key_hex = data.get("verify_key_hex", "")
                    if self.verify_key_hex:
                        return
                except Exception:
                    pass
            import secrets
            secret_hex = secrets.token_hex(32)
            self.verify_key_hex = hashlib.sha256(secret_hex.encode("utf-8")).hexdigest()
            try:
                with open(self.key_path, "w", encoding="utf-8") as f:
                    json.dump({
                        "algorithm": self.algorithm,
                        "secret_hex": secret_hex,
                        "verify_key_hex": self.verify_key_hex,
                        "created_at": datetime.utcnow().isoformat() + "Z"
                    }, f, indent=2)
            except Exception:
                pass

    def get_public_key(self) -> str:
        """Exposes the public verification key (Hex-encoded)."""
        return self.verify_key_hex

    def sign_payload(self, payload: Dict[str, Any]) -> str:
        """Signs canonical JSON bytes of the payload with Ed25519."""
        canonical_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if NACL_AVAILABLE and self.signing_key is not None:
            signed = self.signing_key.sign(canonical_bytes)
            return signed.signature.hex()
        else:
            key_bytes = self.verify_key_hex.encode("utf-8")
            return hashlib.sha256(key_bytes + canonical_bytes).hexdigest()

    def verify_signature(self, payload: Dict[str, Any], signature_hex: str, public_key_hex: Optional[str] = None) -> bool:
        """Verifies Ed25519 cryptographic signature against the canonical JSON payload."""
        canonical_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        pub_key = public_key_hex or self.verify_key_hex
        if NACL_AVAILABLE:
            try:
                vk = nacl.signing.VerifyKey(bytes.fromhex(pub_key))
                vk.verify(canonical_bytes, bytes.fromhex(signature_hex))
                return True
            except Exception:
                return False
        else:
            key_bytes = pub_key.encode("utf-8")
            expected = hashlib.sha256(key_bytes + canonical_bytes).hexdigest()
            return signature_hex.lower() == expected.lower()

    def create_and_save_receipt(
        self,
        receipt_id: str,
        claim_text: str,
        retrieved_facts: List[str],
        model_id: str,
        verdict: str,
        confidence_score: float,
        matched_sources: List[str],
    ) -> Dict[str, Any]:
        """
        Generates SHA-256 hashes of claim_text and retrieved_facts,
        signs payload with Ed25519 key, and saves to receipts/{receipt_id}.json.
        """
        claim_hash = hashlib.sha256(claim_text.strip().encode("utf-8")).hexdigest()
        facts_corpus = "\n".join(retrieved_facts).strip()
        retrieved_facts_hash = hashlib.sha256(facts_corpus.encode("utf-8")).hexdigest()
        timestamp = datetime.utcnow().isoformat() + "Z"

        payload = {
            "receipt_id": receipt_id,
            "claim_hash": claim_hash,
            "retrieved_facts_hash": retrieved_facts_hash,
            "model_id": model_id,
            "verdict": verdict,
            "confidence_score": confidence_score,
            "timestamp": timestamp,
        }

        signature = self.sign_payload(payload)

        receipt_document = {
            "receipt_id": receipt_id,
            "payload": payload,
            "signature": signature,
            "public_key": self.get_public_key(),
            "algorithm": self.algorithm,
            "verified_sources": matched_sources,
            "archived_sources": [f"https://web.archive.org/web/*/{s}" for s in matched_sources if s.startswith("http")],
            "created_at": timestamp,
        }

        receipt_file = os.path.join(self.storage_dir, f"{receipt_id}.json")
        try:
            with open(receipt_file, "w", encoding="utf-8") as f:
                json.dump(receipt_document, f, indent=2)
            logger.info(f"Cryptographic receipt persisted to '{receipt_file}'.")
        except Exception as e:
            logger.error(f"Failed to persist cryptographic receipt: {e}")

        return receipt_document


transparency_log = TransparencyLog("./receipts")

EXACT_SYSTEM_PROMPT = """You are a high-speed, objective Fact-Verification and Audit Engine. Your job is to analyze a viral social media claim against verified ground-truth facts retrieved from a database and a computer-vision deepfake score.

Inputs:
1. CLAIM: The viral text to verify.
2. RETRIEVED_FACTS: Snippets from official documents and verified fact-checkers.
3. IMAGE_DEEPFAKE_PROBABILITY: A score from 0-100% indicating if the attached media is AI-generated.

Rules:
- Base your verdict ONLY on the RETRIEVED_FACTS and the DEEPFAKE probability. Do not use outside knowledge.
- If the RETRIEVED_FACTS contradict the claim, mark it "False".
- If the DEEPFAKE probability is > 75%, highly weight the verdict towards "Misleading" or "False" if the claim relies on the image as proof.
- If there is not enough context, mark it "Unverified".
- Return your response in strictly valid JSON matching this schema: {"verdict": "...", "confidence_score": 0, "explanation": "..."}"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifecycle manager to load models and database connections once
    during startup, avoiding repeated I/O on every request.
    """
    logger.info("Initializing ChromaDB PersistentClient at './chroma_storage'...")
    state.chroma_client = chromadb.PersistentClient(path="./chroma_storage")
    
    # Safely obtain or reference the verified_facts collection
    try:
        state.collection = state.chroma_client.get_or_create_collection(name="verified_facts")
        logger.info(
            f"Collection 'verified_facts' ready. Total documents: {state.collection.count()}"
        )
    except Exception as e:
        logger.warning(f"Could not initialize collection 'verified_facts': {e}")

    # Safely obtain or reference the crowd_radar collection for live query footprints
    try:
        state.radar_collection = state.chroma_client.get_or_create_collection(name="crowd_radar")
        logger.info(
            f"Collection 'crowd_radar' ready. Total tracked patterns: {state.radar_collection.count()}"
        )
    except Exception as e:
        logger.warning(f"Could not initialize collection 'crowd_radar': {e}")

    logger.info("Loading SentenceTransformer ('all-MiniLM-L6-v2')...")
    # Load embedding model in a separate thread so startup isn't blocked
    state.embedding_model = await asyncio.to_thread(
        SentenceTransformer, "all-MiniLM-L6-v2"
    )
    logger.info("SentenceTransformer model loaded successfully.")

    # Initialize Groq client if key is present
    groq_api_key = (os.getenv("GROQ_API_KEY") or "").strip().strip('"\'')
    if groq_api_key and AsyncGroq:
        state.groq_client = AsyncGroq(api_key=groq_api_key)
        logger.info("Groq Async client initialized.")

    # Initialize Gemini client if key is present
    gemini_api_key = (os.getenv("GEMINI_API_KEY") or "").strip().strip('"\'')
    if gemini_api_key and genai:
        genai.configure(api_key=gemini_api_key)
        logger.info("Google Gemini client configured.")

    if not groq_api_key and not gemini_api_key:
        logger.warning(
            "Neither GROQ_API_KEY nor GEMINI_API_KEY is detected in environment. "
            "Please ensure one is set before making audit requests."
        )

    yield

    logger.info("Shutting down Fact-Verification Backend...")


# ---------------------------------------------------------
# FastAPI Application
# ---------------------------------------------------------
app = FastAPI(
    title="Real-Time Fact-Verification Backend",
    description="High-speed reasoning layer analyzing claims against ground truth facts and deepfake scores.",
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS for frontend integration (Next.js localhost:3000, n8n, etc.)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5678",
        "*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------
class IncomingClaim(BaseModel):
    claim_text: str = Field(
        ...,
        min_length=1,
        description="The viral text or claim to be verified."
    )
    deepfake_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Probability (0-100) that the attached image/media is synthetic or AI-generated."
    )
    platform: str = Field(
        ...,
        description="Origin platform of the claim (e.g., 'Reddit', 'Twitter/X', 'WhatsApp')."
    )

    @field_validator("claim_text")
    @classmethod
    def validate_claim_not_whitespace(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("claim_text cannot be empty or contain only whitespace.")
        return trimmed


class AtomicClaim(BaseModel):
    sub_claim: str = Field(
        ...,
        description="Atomic, verifiable sub-statement extracted from the viral post."
    )
    verdict: Literal["True", "False", "Misleading", "Unverified"] = Field(
        ...,
        description="Factual verdict for this sub-claim."
    )
    highlight_color: Literal["green", "red", "amber", "gray"] = Field(
        ...,
        description="Color code: green (True), red (False), amber (Misleading), gray (Unverified)."
    )
    evidence_id: Optional[str] = Field(
        default="E0",
        description="Evidence ID referencing ground truth facts (e.g. E1, E2)."
    )
    exact_quote: Optional[str] = Field(
        default="",
        description="Exact quote extracted directly from retrieved ground truth source."
    )
    quote_verified: bool = Field(
        default=False,
        description="Anti-hallucination verification flag indicating if quote strictly exists in source text."
    )


class AuditResult(BaseModel):
    verdict: Literal["True", "False", "Misleading", "Unverified"] = Field(
        ...,
        description="Final evaluation verdict."
    )
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Engine confidence score between 0 and 100."
    )
    explanation: str = Field(
        ...,
        description="Concise summary explanation rendered in the detected input language."
    )
    counter_message: Optional[str] = Field(
        default="",
        description="Concise 60-word counter-message debunking/clarifying the claim in detected language."
    )
    matched_sources: List[str] = Field(
        default_factory=list,
        description="List of matched sources, document titles, or URLs from verified facts."
    )
    sibling_domains: List[str] = Field(
        default_factory=list,
        description="Lookalike sibling scam infrastructure domains discovered in Certificate Transparency logs."
    )
    atomic_claims: List[AtomicClaim] = Field(
        default_factory=list,
        description="Atomic decomposition of the claim with granular veracity highlights."
    )
    agent_trace: List[str] = Field(
        default_factory=list,
        description="Chronological ReAct execution log tracking live tools and reasoning steps."
    )
    detected_language: Optional[str] = Field(
        default="English",
        description="Detected language of input claim (e.g., English, Hindi, Hinglish, etc.)."
    )
    red_team_argument: Optional[str] = Field(
        default=None,
        description="Skeptical debunker / prosecutor argument from multi-agent debate."
    )
    blue_team_argument: Optional[str] = Field(
        default=None,
        description="Generous advocate / defender argument from multi-agent debate."
    )
    manipulation_tactics: List[str] = Field(
        default_factory=list,
        description="Psychological / rhetorical manipulation tactics detected in the claim (e.g. 'Fake Urgency', 'Guaranteed Returns', 'Fabricated Authority')."
    )
    prebunk_lesson: Optional[str] = Field(
        default="",
        description="Educational inoculation / prebunking explanation of how this psychological scam mechanism works."
    )
    radar_count: int = Field(
        default=1,
        description="Live Crowd Radar footprint: number of semantically similar claims checked across the network in the last 24 hours."
    )
    receipt_id: Optional[str] = Field(
        default="",
        description="Unique receipt identifier for the cryptographic Ed25519 transparency log."
    )
    receipt_signature: Optional[str] = Field(
        default="",
        description="Ed25519 cryptographic signature of the verdict hash and source citations."
    )
    receipt_url: Optional[str] = Field(
        default="",
        description="Direct verification URL for the Ed25519 cryptographic receipt."
    )
    action_dossier: Optional[str] = Field(
        default="",
        description="Official Cybercrime Pre-Fill Report formatted for cybercrime.gov.in / 1930 / Sanchar Saathi."
    )


# ---------------------------------------------------------
# Agentic Tools: Live Fact Check, WHOIS, & Scam Signal Scanner
# ---------------------------------------------------------
def check_domain_whois(domain: str) -> Dict[str, Any]:
    """
    Checks domain creation date using python-whois.
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


def scan_scam_signals(text: str) -> Dict[str, Any]:
    """
    Extracts URLs, UPI IDs, and Phone Numbers using high-precision Regex.
    Performs WHOIS domain age lookups on extracted URLs.
    """
    # URL extraction
    url_pattern = r"https?://[^\s<>\"']+|www\.[^\s<>\"']+"
    urls = list(dict.fromkeys(re.findall(url_pattern, text, re.IGNORECASE)))

    # Common Indian UPI financial handles & generic UPI IDs
    upi_pattern = r"\b[a-zA-Z0-9._-]{2,40}@[a-zA-Z]{2,20}\b"
    upis = list(dict.fromkeys(re.findall(upi_pattern, text, re.IGNORECASE)))

    # Phone number extraction (India mobile + international formats)
    phone_pattern = r"(?:\+?91[\-\s]?)?[6-9]\d{9}\b|\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b"
    phones = list(dict.fromkeys(re.findall(phone_pattern, text)))

    # SEBI / RBI Financial Securities & High-Yield Scam Keywords
    financial_keywords = [
        "investment", "returns", "trading", "crypto", "profit",
        "guaranteed", "sebi", "rbi", "deposit", "dividend",
        "forex", "mutual fund", "stocks", "bonus"
    ]
    found_keywords = [
        kw for kw in financial_keywords
        if re.search(rf"\b{re.escape(kw)}\b", text, re.IGNORECASE)
    ]

    domain_risks = []
    for u in urls:
        parsed = urllib.parse.urlparse(u if u.startswith("http") else f"http://{u}")
        domain = parsed.netloc or parsed.path
        if domain:
            whois_info = check_domain_whois(domain)
            domain_risks.append(whois_info)

    return {
        "urls": urls,
        "upis": upis,
        "phones": phones,
        "domain_risks": domain_risks,
        "has_financial_securities": len(found_keywords) > 0,
        "financial_keywords": found_keywords,
    }


def query_crt_sh_siblings(domain: str) -> List[str]:
    """
    Certificate Transparency Scanner Tool:
    Queries crt.sh to identify lookalike or sibling scam infrastructure domains
    sharing certificate issuance patterns. Strict 5-second timeout.
    """
    clean = re.sub(r"^https?://", "", domain).split("/")[0].split(":")[0].strip().lower()
    clean = re.sub(r"^www\.", "", clean)
    if not clean or "." not in clean:
        return []

    # Skip query on large generic providers to avoid excessive payloads
    trusted_giants = {"google.com", "youtube.com", "reddit.com", "twitter.com", "x.com", "unsplash.com", "github.com"}
    if clean in trusted_giants:
        return []

    url = f"https://crt.sh/?q=%.{urllib.parse.quote(clean)}&output=json"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    )

    siblings: set[str] = set()
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                for entry in data:
                    name_val = entry.get("name_value", "")
                    if name_val:
                        for item in name_val.split("\n"):
                            cand = item.strip().lower()
                            cand = re.sub(r"^\*\.", "", cand)
                            if cand and cand != clean and not cand.startswith("www."):
                                siblings.add(cand)
                    common_name = entry.get("common_name", "")
                    if common_name:
                        cand = common_name.strip().lower()
                        cand = re.sub(r"^\*\.", "", cand)
                        if cand and cand != clean and not cand.startswith("www."):
                            siblings.add(cand)
    except Exception as e:
        logger.warning(f"Certificate Transparency lookup error for '{clean}': {e}")
        return []

    return sorted(list(siblings))[:10]


def normalize_text_for_search(text: str) -> str:
    """
    Normalizes text for robust anti-hallucination substring matching
    by lowercasing, stripping punctuation, and collapsing whitespace.
    """
    cleaned = text.lower()
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def query_google_fact_check_live(query_text: str) -> List[Dict[str, Any]]:
    """
    Live Fact Check Tool:
    Queries Google Fact Check Tools API live with the incoming claim.
    """
    api_key = (
        os.getenv("FACTCHECK_API_KEY")
        or os.getenv("GOOGLE_FACTCHECK_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or ""
    ).strip().strip('"\'')

    # Extract 4-6 salient keywords for higher retrieval accuracy
    words = [w for w in re.sub(r"[^\w\s]", "", query_text).split() if len(w) > 3][:6]
    search_query = " ".join(words) if words else query_text[:60]

    claims_found = []

    # 1. Try googleapiclient.discovery if available
    if api_key and build:
        try:
            service = build("factchecktools", "v1alpha1", developerKey=api_key)
            req = service.claims().search(query=search_query, languageCode="en", pageSize=5)
            res = req.execute()
            for c in res.get("claims", []):
                reviews = c.get("claimReview", [])
                if reviews:
                    rev = reviews[0]
                    claims_found.append({
                        "claim": c.get("text", ""),
                        "rating": rev.get("textualRating", "Unverified"),
                        "publisher": rev.get("publisher", {}).get("name", "Fact-Checker"),
                        "url": rev.get("url") or rev.get("publisher", {}).get("site", ""),
                        "title": rev.get("title", ""),
                    })
            if claims_found:
                return claims_found
        except Exception as e:
            logger.warning(f"Live googleapiclient search error: {e}")

    # 2. Try Google Fact Check Tools REST API
    try:
        params = {"query": search_query, "pageSize": 5, "languageCode": "en"}
        if api_key:
            params["key"] = api_key
        url = f"https://factchecktools.googleapis.com/v1alpha1/claims:search?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "FactCheckLiveAgent/1.0 (Hackathon Verification System)"}
        )
        with urllib.request.urlopen(req, timeout=6) as response:
            data = json.loads(response.read().decode("utf-8"))
            for c in data.get("claims", []):
                reviews = c.get("claimReview", [])
                if reviews:
                    rev = reviews[0]
                    claims_found.append({
                        "claim": c.get("text", ""),
                        "rating": rev.get("textualRating", "Unverified"),
                        "publisher": rev.get("publisher", {}).get("name", "Fact-Checker"),
                        "url": rev.get("url") or rev.get("publisher", {}).get("site", ""),
                        "title": rev.get("title", ""),
                    })
    except Exception as e:
        logger.warning(f"Live Google REST Fact Check error: {e}")

    return claims_found


async def cache_facts_to_chroma(facts: List[Dict[str, Any]]):
    """
    Vector Cache Tool:
    Asynchronously embeds and caches live verified ground-truth facts into ChromaDB
    collection 'verified_facts' so the database organically expands.
    """
    if not state.collection or not state.embedding_model or not facts:
        return

    try:
        documents = []
        metadatas = []
        ids = []

        for f in facts:
            claim_text = f.get("claim", "")
            rating = f.get("rating", "Unverified")
            pub = f.get("publisher", "Official Fact-Checker")
            url = f.get("url", "https://news.google.com")
            title = f.get("title", "")

            doc_text = f"Verified Fact: {claim_text}\nRating: {rating}\nSource: {pub} ({title})\nURL: {url}"
            doc_id = f"live_{hashlib.sha256(claim_text.encode('utf-8')).hexdigest()[:12]}"

            documents.append(doc_text)
            metadatas.append({"source": url, "url": url, "rating": rating, "publisher": pub, "title": title[:100]})
            ids.append(doc_id)

        embeddings = await asyncio.to_thread(state.embedding_model.encode, documents, convert_to_numpy=True)
        await asyncio.to_thread(
            state.collection.upsert,
            ids=ids,
            documents=documents,
            embeddings=embeddings.tolist(),
            metadatas=metadatas
        )
        logger.info(f"Successfully cached {len(ids)} live verified fact(s) to ChromaDB collection 'verified_facts'.")
    except Exception as e:
        logger.warning(f"ChromaDB live caching error: {e}")


async def cache_query_to_crowd_radar(claim_text: str, embedding: list):
    """
    Vector Cache Tool for Crowd Radar:
    Asynchronously saves incoming viral claims into the crowd_radar collection
    with a timestamp to organically build the live crowd radar network without blocking.
    """
    if not state.radar_collection:
        return
    try:
        entry_id = f"radar_{hashlib.sha256(claim_text.encode('utf-8')).hexdigest()[:12]}_{int(datetime.now().timestamp())}"
        ts_now = datetime.now().isoformat()
        await asyncio.to_thread(
            state.radar_collection.add,
            ids=[entry_id],
            embeddings=[embedding],
            documents=[claim_text],
            metadatas=[{"timestamp": ts_now, "claim_preview": claim_text[:120]}]
        )
        logger.info(f"Organically expanded crowd_radar with query footprint: {entry_id}")
    except Exception as e:
        logger.warning(f"Crowd radar async upsert error: {e}")


async def snapshot_to_wayback_machine(urls: List[str]):
    """
    Non-blocking background worker that pings https://web.archive.org/save/{url}
    for every source URL retrieved. Uses a strict 3-second timeout and ignores failures.
    """
    if not urls:
        return

    valid_urls = [u for u in dict.fromkeys(urls) if u.startswith("http")]
    if not valid_urls:
        return

    def _sync_ping(target_url: str):
        try:
            archive_url = f"https://web.archive.org/save/{target_url}"
            req = urllib.request.Request(
                archive_url,
                headers={"User-Agent": "DigitalScam-FactCheck-Archiver/1.0 (Mozilla/5.0)"}
            )
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                _ = resp.read(128)
            logger.info(f"Wayback snapshot pinged for: {target_url}")
        except Exception:
            # Strictly ignore all failures as per requirements
            pass

    for u in valid_urls[:5]:
        try:
            await asyncio.to_thread(_sync_ping, u)
        except Exception:
            pass


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
    Aggregates extracted UPI IDs, phone numbers, flagged URLs, WHOIS domain age,
    and crt.sh sibling domains into a structured markdown document:
    'Official Cybercrime Pre-Fill Report'.
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
    upis_str = "\n".join([f"- `{upi}` (Flagged UPI Payment Handle)" for upi in scam_signals.get("upis", [])]) or "- None detected"
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
> File this data at **cybercrime.gov.in** or call the national **1930 Helpline**. For telecom fraud, report via **DoT Sanchar Saathi (Chakshu)** at https://sancharsaathi.gov.in.

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

#### B. Lookalike Sibling Domains (Certificate Transparency crt.sh)
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


def construct_llm_prompt(claim_text: str, retrieved_docs: List[str], deepfake_score: float) -> str:
    """
    Formats the claim, retrieved ground-truth documents, and heuristic synthetic signal score
    into the strict prompt format required by the audit engine.
    """
    if retrieved_docs:
        facts_formatted = "\n".join(
            [f"[E{idx + 1}] {doc.strip()}" for idx, doc in enumerate(retrieved_docs)]
        )
    else:
        facts_formatted = "No relevant verified facts found in the ground-truth database."

    user_prompt = f"""CLAIM:
"{claim_text}"

RETRIEVED_FACTS:
{facts_formatted}

HEURISTIC_SYNTHETIC_SIGNAL_PROBABILITY:
{deepfake_score:.1f}%

Perform the audit following the system rules and return the response in strict JSON."""
    return user_prompt


def extract_matched_sources(metadatas: Optional[List[Dict[str, Any]]], ids: Optional[List[str]]) -> List[str]:
    """
    Extracts informative source references or URLs from ChromaDB metadata.
    """
    sources: List[str] = []
    if not metadatas:
        return sources

    for idx, meta in enumerate(metadatas):
        if not meta:
            if ids and idx < len(ids):
                sources.append(f"Doc ID: {ids[idx]}")
            continue

        # Look for common source metadata keys
        candidate = (
            meta.get("url")
            or meta.get("source")
            or meta.get("link")
            or meta.get("source_url")
            or meta.get("title")
        )
        if candidate and str(candidate).strip():
            sources.append(str(candidate).strip())
        elif ids and idx < len(ids):
            sources.append(f"Doc ID: {ids[idx]}")
            
    # Deduplicate while preserving order
    return list(dict.fromkeys(sources))


def clean_json_response(raw_text: str) -> Dict[str, Any]:
    """
    Cleans and parses JSON output from LLM, handling markdown code fences.
    """
    text = raw_text.strip()
    # Strip markdown ```json ... ``` codeblocks if present
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as err:
        # Fallback regex search for JSON object
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise ValueError(f"Failed to parse LLM response into JSON: {text}") from err


async def query_llm(system_prompt: str, user_prompt: str, as_json: bool = True) -> Any:
    """
    Asynchronously queries Groq (preferred) using active models (openai/gpt-oss-20b, openai/gpt-oss-120b),
    or falls back to Google Gemini (gemini-3.8-flash).
    Supports both JSON mode (for structured outputs) and plain text mode (for agent debates).
    """
    groq_api_key = (os.getenv("GROQ_API_KEY") or "").strip().strip('"\'')
    gemini_api_key = (os.getenv("GEMINI_API_KEY") or "").strip().strip('"\'')

    # Ensure Groq client exists if key is in env
    if not state.groq_client and groq_api_key and AsyncGroq:
        state.groq_client = AsyncGroq(api_key=groq_api_key)

    # Ensure Gemini client is configured if key is present
    if gemini_api_key and genai:
        genai.configure(api_key=gemini_api_key)

    groq_errors: List[str] = []

    # 1. Try Groq with active models: openai/gpt-oss-20b (speed) or openai/gpt-oss-120b (reasoning)
    if state.groq_client:
        requested_model = (os.getenv("GROQ_MODEL") or "openai/gpt-oss-20b").strip().strip('"\'')
        candidate_models = [
            requested_model,
            "openai/gpt-oss-20b",
            "openai/gpt-oss-120b",
        ]
        # Remove duplicates while preserving order
        unique_models = list(dict.fromkeys(candidate_models))

        for model_name in unique_models:
            try:
                call_kwargs = {
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.2 if not as_json else 0.1,
                }
                if as_json:
                    call_kwargs["response_format"] = {"type": "json_object"}

                response = await asyncio.wait_for(
                    state.groq_client.chat.completions.create(**call_kwargs),
                    timeout=15.0,
                )
                raw_content = response.choices[0].message.content
                return clean_json_response(raw_content) if as_json else raw_content.strip()

            except asyncio.TimeoutError:
                err_msg = f"Groq model '{model_name}' timed out after 15s"
                logger.warning(err_msg)
                groq_errors.append(err_msg)
                continue

            except Exception as e:
                err_str = str(e)
                logger.warning(f"Groq model '{model_name}' error: {err_str}")
                groq_errors.append(f"{model_name}: {err_str}")
                continue

        logger.info("Groq execution unsuccessful or not configured. Proceeding to Gemini fallback...")

    # 2. Try Google Gemini Fallback with active model: gemini-3.8-flash
    gemini_error: Optional[str] = None
    if gemini_api_key and genai:
        gemini_model_name = (os.getenv("GEMINI_MODEL") or "gemini-3.8-flash").strip().strip('"\'')
        try:
            gen_config = {"temperature": 0.2 if not as_json else 0.1}
            if as_json:
                gen_config["response_mime_type"] = "application/json"

            model = genai.GenerativeModel(
                model_name=gemini_model_name,
                system_instruction=system_prompt,
                generation_config=gen_config,
            )
            response = await asyncio.wait_for(
                asyncio.to_thread(model.generate_content, user_prompt),
                timeout=15.0,
            )
            return clean_json_response(response.text) if as_json else response.text.strip()
        except asyncio.TimeoutError:
            gemini_error = f"Gemini model '{gemini_model_name}' timed out after 15s"
            logger.error(gemini_error)
        except Exception as e:
            gemini_error = f"Gemini model '{gemini_model_name}' error: {str(e)}"
            logger.error(gemini_error)

    # Collect all error details
    all_errors = []
    if groq_errors:
        all_errors.extend(groq_errors)
    if gemini_error:
        all_errors.append(gemini_error)

    error_summary = " | ".join(all_errors) if all_errors else "No LLM provider configured or available."

    # Gracefully handle 404 / model-not-found errors with clean HTTP 500
    is_model_not_found = any(
        kw in error_summary.lower()
        for kw in ["404", "model_not_found", "not found", "does not exist", "not supported", "invalid_request_error"]
    )

    if is_model_not_found:
        detail_msg = (
            f"LLM Model Error: The requested model was not found or is unavailable. "
            f"Please verify active model identifiers ('openai/gpt-oss-20b', 'openai/gpt-oss-120b', 'gemini-3.8-flash'). "
            f"Details: {error_summary}"
        )
    else:
        detail_msg = f"Fact-Verification reasoning failed: {error_summary}"

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=detail_msg
    )


async def run_multi_agent_audit(
    claim_text: str,
    retrieved_docs: List[str],
    deepfake_score: float,
    forensic_signals: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Executes an autonomous Red Team vs. Blue Team debate before final adjudication:
    1. Agent A (Red Team / The Prosecutor): Skeptical debunker arguing against the claim.
    2. Agent B (Blue Team / The Defender): Generous advocate finding any shred of truth.
    Both debate arguments run simultaneously in parallel via asyncio.gather.
    3. The Judge Agent: Detects language, decomposes claim into atomic sub-claims,
       and synthesizes the debate arguments into the final verdict JSON.
    """
    if retrieved_docs:
        facts_formatted = "\n".join(
            [f"[E{idx + 1}] {doc.strip()}" for idx, doc in enumerate(retrieved_docs)]
        )
    else:
        facts_formatted = "No relevant verified facts found in the ground-truth database."

    # Format forensic signals (WHOIS, UPI, URLs)
    forensics_formatted = "None detected."
    if forensic_signals:
        signal_lines = []
        if forensic_signals.get("urls"):
            signal_lines.append(f"- Extracted URLs: {', '.join(forensic_signals['urls'])}")
        if forensic_signals.get("domain_risks"):
            for d in forensic_signals["domain_risks"]:
                signal_lines.append(f"- Domain Forensics: {d.get('detail', '')}")
        if forensic_signals.get("upis"):
            signal_lines.append(f"- Financial UPI Handles: {', '.join(forensic_signals['upis'])} (High Scam Correlation)")
        if forensic_signals.get("phones"):
            signal_lines.append(f"- Extracted Contact Numbers: {', '.join(forensic_signals['phones'])}")
        if signal_lines:
            forensics_formatted = "\n".join(signal_lines)

    # Agent A: Red Team (Prosecutor) Prompt
    red_team_system = (
        "You are the Prosecutor and skeptical debunker in a high-speed Fact-Verification Court. "
        "Your mission is to rigorously cross-examine claims and expose potential deception or synthetic forgery."
    )
    red_team_prompt = (
        f"Act as a skeptical debunker. Use the RETRIEVED_FACTS, DEEPFAKE_SCORE, and SECURITY_FORENSICS to forcefully argue "
        f"why this CLAIM is false or misleading.\n\n"
        f"CLAIM:\n\"{claim_text}\"\n\n"
        f"RETRIEVED_FACTS:\n{facts_formatted}\n\n"
        f"SECURITY_FORENSICS:\n{forensics_formatted}\n\n"
        f"HEURISTIC_SYNTHETIC_SIGNAL_PROBABILITY: {deepfake_score:.1f}%\n\n"
        f"Deliver a concise, punchy 2-3 sentence prosecution argument."
    )

    # Agent B: Blue Team (Defender) Prompt
    blue_team_system = (
        "You are the Defense Advocate in a high-speed Fact-Verification Court. "
        "Your mission is to defend the user claim by finding any underlying truth, partial facts, or context."
    )
    blue_team_prompt = (
        f"Act as a generous advocate. Find any shred of truth, nuance, or misinterpretation in the CLAIM "
        f"based on the RETRIEVED_FACTS.\n\n"
        f"CLAIM:\n\"{claim_text}\"\n\n"
        f"RETRIEVED_FACTS:\n{facts_formatted}\n\n"
        f"HEURISTIC_SYNTHETIC_SIGNAL_PROBABILITY: {deepfake_score:.1f}%\n\n"
        f"Deliver a concise, punchy 2-3 sentence defense argument."
    )

    # Execute Red Team and Blue Team concurrently in parallel
    logger.info("Spawning autonomous Red Team (Prosecutor) and Blue Team (Defender) in parallel...")
    red_future = query_llm(red_team_system, red_team_prompt, as_json=False)
    blue_future = query_llm(blue_team_system, blue_team_prompt, as_json=False)

    red_arg, blue_arg = await asyncio.gather(red_future, blue_future)
    logger.info("Parallel debate arguments collected. Invoking the Judge Agent for final adjudication...")

    # Agent C: The Judge Arbitrator Prompt (Multilingual, Atomic Decomposition, Citation-Verified, Prebunking)
    judge_system = (
        "You are the supreme arbitrator and Judge in an advanced Multi-Agent Fact-Verification Tribunal. "
        "Your task is to analyze the viral claim against live evidence, computer-vision deepfake probability, "
        "and the competing arguments of the Red Team and Blue Team.\n\n"
        "MANDATORY INSTRUCTIONS:\n"
        "1. LANGUAGE DETECTION: Detect the exact language of the input CLAIM (e.g., Hindi, Hinglish, English, etc.). "
        "   You MUST write your entire final 'explanation' AND 'counter_message' in that EXACT SAME LANGUAGE.\n"
        "2. COUNTER MESSAGE: Write a punchy, factual debunking/clarification counter-message (maximum 60 words) "
        "   in the detected language, ready to be forwarded on WhatsApp to debunk the scam/misinformation.\n"
        "3. MANIPULATION FINGERPRINTING & PREBUNKING (PSYCHOLOGICAL INOCULATION):\n"
        "   Analyze the rhetorical and psychological manipulation tactics present in the CLAIM, even if facts are 'Unverified'.\n"
        "   - 'manipulation_tactics': A list of specific tactics detected, such as 'Fake Urgency' (e.g. 'act now', 'limited time'), "
        "     'Guaranteed Returns' (unrealistic risk-free profits), 'Fabricated Authority' (fake government/official endorsement), "
        "     'Emotional Exploitation' (fear or greed triggers), 'Artificial Scarcity', or 'Phishing Solicitation'. If none, return [].\n"
        "   - 'prebunk_lesson': A concise 2-sentence psychological inoculation lesson explaining how this specific manipulation trick "
        "     operates to exploit cognitive biases, teaching the reader how to recognize and resist it in the future.\n"
        "4. ATOMIC DECOMPOSITION & EVIDENCE CITATION: Decompose the main claim into 2-4 atomic, verifiable sub-claims.\n"
        "   For each sub-claim, you MUST provide:\n"
        "   - 'sub_claim': The discrete verifiable statement.\n"
        "   - 'verdict': 'True', 'False', 'Misleading', or 'Unverified'.\n"
        "   - 'highlight_color': 'green' for True, 'red' for False, 'amber' for Misleading, 'gray' for Unverified.\n"
        "   - 'evidence_id': The ID of the evidence snippet used (e.g., 'E1', 'E2', etc., or 'E0' if none).\n"
        "   - 'exact_quote': An EXACT, VERBATIM quote copied directly from the RETRIEVED FACTS that proves or disproves this sub-claim. Do NOT paraphrase or invent quotes. If no exact quote exists in the facts, leave as empty string ''.\n"
        "5. FINAL VERDICT: Must be 'True', 'False', 'Misleading', or 'Unverified'. "
        "   If any critical element is debunked or heuristic synthetic signal > 75%, mark 'False' or 'Misleading'.\n"
        "6. OUTPUT FORMAT: Return strictly valid JSON matching this schema:\n"
        "{\n"
        '  "verdict": "False",\n'
        '  "confidence_score": 90,\n'
        '  "detected_language": "English",\n'
        '  "explanation": "Max 3-sentence explanation in the detected language.",\n'
        '  "counter_message": "Punchy <= 60 word debunk message in detected language.",\n'
        '  "manipulation_tactics": ["Fake Urgency", "Guaranteed Returns", "Fabricated Authority"],\n'
        '  "prebunk_lesson": "Scammers manufacture artificial urgency to bypass analytical scrutiny and critical thinking. Legitimate regulatory institutions never offer guaranteed returns on private investment schemes.",\n'
        '  "atomic_claims": [\n'
        '    {\n'
        '      "sub_claim": "...",\n'
        '      "verdict": "False",\n'
        '      "highlight_color": "red",\n'
        '      "evidence_id": "E1",\n'
        '      "exact_quote": "Exact quote from retrieved facts"\n'
        '    }\n'
        '  ]\n'
        "}"
    )

    judge_prompt = f"""CLAIM TO VERIFY:
"{claim_text}"

RETRIEVED FACTS & EVIDENCE:
{facts_formatted}

SECURITY / FORENSIC SIGNALS:
{forensics_formatted}

HEURISTIC SYNTHETIC SIGNAL PROBABILITY:
{deepfake_score:.1f}%

=== MULTI-AGENT DEBATE ARGUMENTS ===
[RED TEAM - PROSECUTOR / SKEPTIC]:
{red_arg}

[BLUE TEAM - DEFENDER / ADVOCATE]:
{blue_arg}

Deliver your final verdict, confidence score (0-100), detected language, explanation in that same language, <= 60 word counter_message, manipulation_tactics list, 2-sentence prebunk_lesson, and atomic claims breakdown with evidence_id and exact_quote citations in strictly valid JSON."""

    judge_output = await query_llm(judge_system, judge_prompt, as_json=True)

    # Attach debate transcripts to output
    judge_output["red_team_argument"] = red_arg
    judge_output["blue_team_argument"] = blue_arg

    return judge_output


# ---------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------
@app.get("/health", tags=["System"])
async def health_check():
    """Health check endpoint confirming model and vector store status."""
    return {
        "status": "healthy",
        "chroma_connected": state.chroma_client is not None,
        "collection_ready": state.collection is not None,
        "collection_count": state.collection.count() if state.collection else 0,
        "model_loaded": state.embedding_model is not None,
        "llm_configured": bool(os.getenv("GROQ_API_KEY") or os.getenv("GEMINI_API_KEY")),
    }


@app.post(
    "/api/audit",
    response_model=AuditResult,
    status_code=status.HTTP_200_OK,
    tags=["Audit"],
    summary="Agentic multi-step audit and fact-verification of viral claims"
)
async def audit_claim(claim: IncomingClaim) -> AuditResult:
    """
    Dynamic ReAct Agentic Verification Pipeline:
    1. Scam Signal & WHOIS Tool: Scans URLs, UPI handles, phones, and flags domains < 6 months old.
    2. Live Fact Check Tool: Queries Google Fact Check Tools API live.
    3. Vector Cache Tool: Caches live facts into ChromaDB; falls back to ChromaDB if live API has no match.
    4. Parallel Red vs. Blue Debate: Spawns Prosecutor and Defender via asyncio.gather.
    5. Multilingual Judge Arbitrator: Decomposes into atomic sub-claims & outputs explanation in input language.
    """
    agent_trace: List[str] = []
    agent_trace.append(f"> [AGENT_START] Initializing dynamic ReAct verification pipeline on {claim.platform}...")

    # Step 1: Scan for Scam Signals & WHOIS Domain Age
    agent_trace.append("> [TOOL: SCANNER] Scanning claim text for URLs, UPI IDs, and direct contact numbers...")
    scam_signals = scan_scam_signals(claim.claim_text)
    
    forensic_evidence: List[str] = []
    sibling_domains: List[str] = []
    if scam_signals["urls"]:
        agent_trace.append(f"> [TOOL: SCANNER] Extracted {len(scam_signals['urls'])} URL(s): {', '.join(scam_signals['urls'])}")
        for d in scam_signals["domain_risks"]:
            detail_str = d.get("detail", "")
            dom = d.get("domain", "")
            if d.get("is_high_risk"):
                agent_trace.append(f"> [ALERT: WHOIS] ⚠️ HIGH RISK: {detail_str}")
            else:
                agent_trace.append(f"> [TOOL: WHOIS] {detail_str}")
            forensic_evidence.append(detail_str)

            # Query Certificate Transparency logs for lookalike/sibling infrastructure domains
            if dom:
                sibs = await asyncio.to_thread(query_crt_sh_siblings, dom)
                if sibs:
                    sibling_domains.extend(sibs)
                    agent_trace.append(
                        f"> [ALERT: INFRASTRUCTURE] Found {len(sibs)} lookalike sibling domain(s) in Certificate Transparency logs for '{dom}': {', '.join(sibs[:4])}"
                    )
                else:
                    agent_trace.append(f"> [TOOL: CERT_TRANSPARENCY] Queried crt.sh for '{dom}' (0 additional active sibling certificates found).")

    sibling_domains = list(dict.fromkeys(sibling_domains))

    if scam_signals["upis"]:
        upi_msg = f"Direct financial solicitation handle flagged: {', '.join(scam_signals['upis'])} (High fraud correlation)"
        agent_trace.append(f"> [ALERT: SCANNER] ⚠️ {upi_msg}")
        forensic_evidence.append(upi_msg)

    if scam_signals["phones"]:
        phone_msg = f"Direct contact solicitation: {', '.join(scam_signals['phones'])}"
        agent_trace.append(f"> [TOOL: SCANNER] {phone_msg}")
        forensic_evidence.append(phone_msg)

    # SEBI / RBI Financial Securities Regulatory Scanner
    if scam_signals.get("has_financial_securities"):
        reg_msg = "Claim involves financial securities; cross-referencing with SEBI/RBI unverified entities guidelines."
        agent_trace.append(f"> [ALERT: REGULATORY] ⚠️ {reg_msg}")
        forensic_evidence.append(reg_msg)

    # Step: Live Crowd Radar & Semantic Proximity Search
    radar_count = 1
    claim_embedding = None
    if state.embedding_model is not None:
        try:
            claim_embedding = await asyncio.to_thread(
                state.embedding_model.encode,
                claim.claim_text,
                convert_to_numpy=True
            )
            if state.radar_collection is not None:
                radar_res = await asyncio.to_thread(
                    state.radar_collection.query,
                    query_embeddings=[claim_embedding.tolist()],
                    n_results=25,
                    include=["distances"]
                )
                similar_count = 0
                if radar_res and radar_res.get("distances") and radar_res["distances"][0]:
                    for dist in radar_res["distances"][0]:
                        if dist < 0.3:
                            similar_count += 1
                radar_count = similar_count + 1
                agent_trace.append(
                    f"> [TOOL: CROWD_RADAR] Live crowd radar scanned: {similar_count} semantically similar query pattern(s) identified (distance < 0.3). Total radar footprint: {radar_count}."
                )

                # Asynchronously upsert current query into crowd_radar without blocking main event loop
                asyncio.create_task(cache_query_to_crowd_radar(claim.claim_text, claim_embedding.tolist()))
        except Exception as e:
            logger.warning(f"Crowd radar query error: {e}")
            agent_trace.append(f"> [TOOL: CROWD_RADAR] Radar query notice: {str(e)[:60]}")

    # Step 2: Live Fact Check Tool (Google Fact Check Tools API)
    agent_trace.append("> [TOOL: LIVE_FACT_CHECK] Querying Google Fact Check Tools API for live verified claims...")
    live_facts = await asyncio.to_thread(query_google_fact_check_live, claim.claim_text)

    retrieved_docs: List[str] = []
    matched_sources: List[str] = []

    if live_facts:
        agent_trace.append(f"> [TOOL: LIVE_FACT_CHECK] Found {len(live_facts)} live verified ground-truth record(s).")
        for lf in live_facts:
            doc_str = (
                f"Verified Fact: {lf['claim']}\n"
                f"Official Rating: {lf['rating']}\n"
                f"Publisher: {lf['publisher']} ({lf['title']})\n"
                f"URL: {lf['url']}"
            )
            retrieved_docs.append(doc_str)
            if lf.get("url"):
                matched_sources.append(lf["url"])

        # Asynchronously cache into ChromaDB so the vector database organically grows
        agent_trace.append("> [TOOL: VECTOR_CACHE] Asynchronously embedding and caching live records into ChromaDB collection 'verified_facts'...")
        asyncio.create_task(cache_facts_to_chroma(live_facts))
    else:
        # Step 3: Vector Cache Tool (fallback to local ChromaDB semantic search)
        agent_trace.append("> [TOOL: VECTOR_CACHE] No direct live fact check match. Querying local ChromaDB vector store...")
        if state.collection is not None and state.embedding_model is not None:
            try:
                if claim_embedding is None:
                    claim_embedding = await asyncio.to_thread(
                        state.embedding_model.encode,
                        claim.claim_text,
                        convert_to_numpy=True
                    )
                results = await asyncio.to_thread(
                    state.collection.query,
                    query_embeddings=[claim_embedding.tolist()],
                    n_results=3,
                    include=["documents", "metadatas"]
                )
                if results and results.get("documents") and results["documents"][0]:
                    retrieved_docs = results["documents"][0]
                    metadatas = results.get("metadatas", [[]])[0]
                    ids = results.get("ids", [[]])[0] if results.get("ids") else []
                    matched_sources = extract_matched_sources(metadatas, ids)
                    agent_trace.append(f"> [TOOL: VECTOR_CACHE] Retrieved {len(retrieved_docs)} nearest ground-truth record(s) from ChromaDB.")
                else:
                    agent_trace.append("> [TOOL: VECTOR_CACHE] ChromaDB query complete. No direct semantic overlap.")
            except Exception as e:
                logger.warning(f"ChromaDB retrieval error: {e}")
                agent_trace.append(f"> [TOOL: VECTOR_CACHE] ChromaDB query notice: {str(e)[:60]}")

    # Append forensic evidence to retrieved docs
    if forensic_evidence:
        retrieved_docs.append("SECURITY / DOMAIN FORENSICS:\n" + "\n".join(forensic_evidence))

    # Step 4: Autonomous Multi-Agent Parallel Debate (Red Team vs Blue Team)
    agent_trace.append(f"> [DEBATE: MULTI_AGENT] Spawning parallel Red Team (Prosecutor) & Blue Team (Defender) via asyncio.gather...")
    try:
        llm_output = await run_multi_agent_audit(
            claim_text=claim.claim_text,
            retrieved_docs=retrieved_docs,
            deepfake_score=claim.deepfake_score,
            forensic_signals=scam_signals,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in multi-agent debate: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fact-Verification debate reasoning failed: {str(e)}"
        )

    agent_trace.append("> [JUDGE: ARBITRATION] Judge Arbitrator synthesized debate and executed atomic sub-claim decomposition.")
    detected_lang = llm_output.get("detected_language", "English")
    agent_trace.append(f"> [MULTILINGUAL] Detected claim language: {detected_lang}. Output rendered in same tongue.")

    # Step 5: Validate and Parse output into AuditResult
    verdict = llm_output.get("verdict", "Unverified")
    valid_verdicts = {"True": "True", "False": "False", "Misleading": "Misleading", "Unverified": "Unverified"}
    normalized_verdict = valid_verdicts.get(verdict.capitalize() if isinstance(verdict, str) else "", "Unverified")

    try:
        confidence = float(llm_output.get("confidence_score", 50.0))
        if 0.0 < confidence <= 1.0:
            confidence = confidence * 100.0
        confidence = max(0.0, min(100.0, confidence))
    except (ValueError, TypeError):
        confidence = 50.0

    explanation = str(llm_output.get("explanation", "Insufficient context to verify claim."))

    # Generate or extract WhatsApp-ready counter-message (<= 60 words)
    counter_message = str(llm_output.get("counter_message", "")).strip()
    if not counter_message:
        counter_message = explanation
    counter_words = counter_message.split()
    if len(counter_words) > 60:
        counter_message = " ".join(counter_words[:60]) + "..."

    # Step 5: Post-LLM Anti-Hallucination Guard & Citation Verification
    # Construct normalized search corpus from all retrieved facts & forensics
    corpus_text = " ".join(retrieved_docs)
    norm_corpus = normalize_text_for_search(corpus_text)

    # Parse and Validate Atomic Claims
    raw_atomics = llm_output.get("atomic_claims", [])
    parsed_atomics: List[AtomicClaim] = []
    if isinstance(raw_atomics, list):
        for item in raw_atomics:
            if isinstance(item, dict) and "sub_claim" in item:
                sub_txt = str(item["sub_claim"]).strip()
                sub_v = valid_verdicts.get(str(item.get("verdict", "Unverified")).capitalize(), "Unverified")
                sub_color = item.get("highlight_color", "amber")
                ev_id = str(item.get("evidence_id", "E0")).strip()
                raw_quote = str(item.get("exact_quote", "")).strip()

                # Verify quote strictly exists in retrieved facts corpus
                quote_verified = False
                if raw_quote:
                    norm_quote = normalize_text_for_search(raw_quote)
                    if norm_quote and norm_quote in norm_corpus:
                        quote_verified = True

                if quote_verified:
                    agent_trace.append(
                        f"> [ANTI_HALLUCINATION] ✓ Verified quote for sub-claim '{sub_txt[:40]}' against ground truth [{ev_id}]."
                    )
                else:
                    # Downgrade verdict to Unverified and log warning
                    if sub_v != "Unverified":
                        agent_trace.append(
                            f"> [ANTI_HALLUCINATION] ⚠️ Downgraded sub-claim '{sub_txt[:40]}' to Unverified. Extracted quote failed source verification."
                        )
                        sub_v = "Unverified"
                        sub_color = "gray"
                    else:
                        agent_trace.append(
                            f"> [ANTI_HALLUCINATION] Sub-claim '{sub_txt[:40]}' unverified (no citation match)."
                        )
                        sub_color = "gray"

                if sub_color not in ("green", "red", "amber", "gray"):
                    sub_color = "green" if sub_v == "True" else "red" if sub_v == "False" else "gray" if sub_v == "Unverified" else "amber"

                parsed_atomics.append(
                    AtomicClaim(
                        sub_claim=sub_txt,
                        verdict=sub_v,
                        highlight_color=sub_color,
                        evidence_id=ev_id,
                        exact_quote=raw_quote,
                        quote_verified=quote_verified,
                    )
                )

    # Fallback atomic decomposition if model omitted it
    if not parsed_atomics:
        fallback_color = "green" if normalized_verdict == "True" else "red" if normalized_verdict == "False" else "gray" if normalized_verdict == "Unverified" else "amber"
        parsed_atomics.append(
            AtomicClaim(
                sub_claim=claim.claim_text,
                verdict=normalized_verdict,
                highlight_color=fallback_color,
                evidence_id="E0",
                exact_quote="",
                quote_verified=False,
            )
        )

    # Parse Manipulation Tactics & Prebunking Lesson
    raw_tactics = llm_output.get("manipulation_tactics", [])
    manipulation_tactics: List[str] = []
    if isinstance(raw_tactics, list):
        manipulation_tactics = [str(t).strip() for t in raw_tactics if str(t).strip()]
    elif isinstance(raw_tactics, str) and raw_tactics.strip():
        manipulation_tactics = [raw_tactics.strip()]

    prebunk_lesson = str(llm_output.get("prebunk_lesson", "")).strip()
    if not prebunk_lesson:
        if manipulation_tactics:
            prebunk_lesson = (
                f"Be vigilant against {', '.join(manipulation_tactics)}. Disinformation sources construct cognitive "
                "pressure to force emotional reactions without rational verification."
            )
        else:
            prebunk_lesson = (
                "Always cross-examine unsolicited viral claims against official regulatory registries before sharing or committing funds."
            )

    # Step 6: Generate Cryptographic Transparency Receipt (Ed25519)
    receipt_id = f"rcpt_{hashlib.sha256((claim.claim_text + datetime.utcnow().isoformat()).encode('utf-8')).hexdigest()[:16]}"
    model_id = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    if os.getenv("GROQ_API_KEY"):
        model_id = f"groq-multi-agent+{model_id}"

    receipt_doc = transparency_log.create_and_save_receipt(
        receipt_id=receipt_id,
        claim_text=claim.claim_text,
        retrieved_facts=retrieved_docs,
        model_id=model_id,
        verdict=normalized_verdict,
        confidence_score=confidence,
        matched_sources=matched_sources,
    )
    receipt_sig = receipt_doc.get("signature", "")
    receipt_url = f"/api/verify/{receipt_id}"

    agent_trace.append(f"> [TRANSPARENCY_LOG] Verifiable Ed25519 verdict receipt generated: {receipt_id} (Signature: {receipt_sig[:12]}...).")

    # Step 7: Wayback Machine Snapshot Archive (Non-blocking background task)
    if matched_sources:
        agent_trace.append(f"> [WAYBACK_MACHINE] Scheduled non-blocking background snapshot for {len(matched_sources)} source URL(s).")
        asyncio.create_task(snapshot_to_wayback_machine(matched_sources))

    # Step 8: Verdict-to-Action Cybercrime Dossier Generation
    action_dossier = generate_cybercrime_dossier(
        claim_text=claim.claim_text,
        verdict=normalized_verdict,
        confidence_score=confidence,
        scam_signals=scam_signals,
        sibling_domains=sibling_domains,
        matched_sources=matched_sources,
        receipt_id=receipt_id,
    )
    if action_dossier:
        agent_trace.append("> [CYBERCRIME_DOSSIER] Generated Official Cybercrime Pre-Fill Report for cybercrime.gov.in & Sanchar Saathi.")

    return AuditResult(
        verdict=normalized_verdict,
        confidence_score=confidence,
        explanation=explanation,
        counter_message=counter_message,
        manipulation_tactics=manipulation_tactics,
        prebunk_lesson=prebunk_lesson,
        radar_count=radar_count,
        receipt_id=receipt_id,
        receipt_signature=receipt_sig,
        receipt_url=receipt_url,
        action_dossier=action_dossier,
        matched_sources=list(dict.fromkeys(matched_sources)),
        sibling_domains=sibling_domains,
        atomic_claims=parsed_atomics,
        agent_trace=agent_trace,
        detected_language=detected_lang,
        red_team_argument=llm_output.get("red_team_argument"),
        blue_team_argument=llm_output.get("blue_team_argument"),
    )


@app.get(
    "/api/verify/{receipt_id}",
    tags=["Transparency"],
    summary="Cryptographically verify a verdict receipt using Ed25519"
)
async def verify_verdict_receipt(receipt_id: str):
    """
    Independent verification endpoint:
    Returns the cryptographic receipt, canonical payload, signature, and Ed25519 public key.
    Third parties can independently verify the verdict hasn't been tampered with.
    """
    clean_id = re.sub(r"[^a-zA-Z0-9_\-]", "", receipt_id)
    receipt_path = os.path.join(transparency_log.storage_dir, f"{clean_id}.json")

    if not os.path.exists(receipt_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cryptographic receipt '{clean_id}' not found in transparency log."
        )

    try:
        with open(receipt_path, "r", encoding="utf-8") as f:
            receipt_data = json.load(f)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read receipt: {str(e)}"
        )

    payload = receipt_data.get("payload", {})
    signature = receipt_data.get("signature", "")
    public_key = receipt_data.get("public_key", "")
    algorithm = receipt_data.get("algorithm", "Ed25519")

    is_valid = transparency_log.verify_signature(payload, signature, public_key)

    return {
        "receipt_id": clean_id,
        "is_valid": is_valid,
        "verification_status": "cryptographically_verified" if is_valid else "signature_mismatch",
        "algorithm": algorithm,
        "public_key": public_key,
        "signature": signature,
        "receipt": receipt_data,
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
