import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import hashlib
import json
import logging
import os
import re
from typing import Any, AsyncGenerator, Dict, List, Optional
import urllib.parse

import chromadb
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sentence_transformers import SentenceTransformer

# Load environment variables
load_dotenv(override=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
)
logger = logging.getLogger("fact-audit-engine")

# Modular imports
from models import IncomingClaim, AtomicClaim, AuditResult, VerificationResponse
from crypto_utils import TransparencyLog
from tools import (
    scan_scam_signals,
    extract_brand_keyword,
    query_crt_sh_brand_lookalikes,
    query_google_fact_check_live,
    snapshot_all_sources_to_wayback,
    generate_cybercrime_dossier,
)
from agents import (
    query_llm,
    extract_search_query_with_llm,
    verify_atomic_quotes,
    query_chroma_facts,
    query_and_update_crowd_radar,
    run_multi_agent_audit,
)

# Optional LLM imports
try:
    from groq import AsyncGroq
except ImportError:
    AsyncGroq = None

try:
    import google.generativeai as genai
except ImportError:
    genai = None


# ---------------------------------------------------------
# Global Application State & Lifespan
# ---------------------------------------------------------
class AppState:
    embedding_model: Optional[SentenceTransformer] = None
    chroma_client: Optional[chromadb.PersistentClient] = None
    collection = None
    radar_collection = None
    groq_client: Optional[Any] = None
    transparency_log: Optional[TransparencyLog] = None


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Initializes database connections, models, and cryptographic transparency log on startup.
    """
    logger.info("Initializing ChromaDB PersistentClient at './chroma_storage'...")
    state.chroma_client = chromadb.PersistentClient(path="./chroma_storage")

    try:
        state.collection = state.chroma_client.get_or_create_collection(name="verified_facts")
        logger.info(f"Collection 'verified_facts' ready. Total documents: {state.collection.count()}")
    except Exception as e:
        logger.warning(f"Could not initialize collection 'verified_facts': {e}")

    try:
        state.radar_collection = state.chroma_client.get_or_create_collection(name="crowd_radar")
        logger.info(f"Collection 'crowd_radar' ready. Total tracked footprints: {state.radar_collection.count()}")
    except Exception as e:
        logger.warning(f"Could not initialize collection 'crowd_radar': {e}")

    logger.info("Loading SentenceTransformer ('all-MiniLM-L6-v2')...")
    state.embedding_model = await asyncio.to_thread(
        SentenceTransformer, "all-MiniLM-L6-v2"
    )
    logger.info("SentenceTransformer model loaded successfully.")

    # Initialize Groq client
    groq_api_key = (os.getenv("GROQ_API_KEY") or "").strip().strip('"\'')
    if groq_api_key and AsyncGroq:
        state.groq_client = AsyncGroq(api_key=groq_api_key)
        logger.info("Groq Async client initialized.")

    # Initialize Gemini client
    gemini_api_key = (os.getenv("GEMINI_API_KEY") or "").strip().strip('"\'')
    if gemini_api_key and genai:
        genai.configure(api_key=gemini_api_key)
        logger.info("Google Gemini client configured.")

    # Initialize Cryptographic Transparency Log (Ed25519)
    state.transparency_log = TransparencyLog("./receipts")
    logger.info(f"Ed25519 Transparency Log active. Public Key: {state.transparency_log.get_public_key()}")

    yield

    logger.info("Shutting down Fact-Verification Backend...")


# ---------------------------------------------------------
# FastAPI Application & Clean CORS Setup
# ---------------------------------------------------------
app = FastAPI(
    title="DigitalScam Real-Time Fact-Verification Engine",
    description="Agentic multi-modal fact-verification tribunal with Ed25519 verifiable verdict receipts.",
    version="2.0.0",
    lifespan=lifespan,
)

# Fix CORS: Specify allowed origins explicitly to avoid wildcard credentials issues
allowed_origins_env = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5678"
)
allowed_origins = [orig.strip() for orig in allowed_origins_env.split(",") if orig.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------
# Background Vector Cache Task
# ---------------------------------------------------------
async def async_cache_facts_to_chroma(facts: List[Dict[str, Any]]):
    """
    Asynchronously caches live verified facts into ChromaDB verified_facts collection.
    """
    if not state.collection or not state.embedding_model or not facts:
        return

    try:
        documents, metadatas, ids = [], [], []
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

        embeddings = await asyncio.to_thread(
            state.embedding_model.encode, documents, convert_to_numpy=True
        )
        await asyncio.to_thread(
            state.collection.upsert,
            ids=ids,
            embeddings=embeddings.tolist(),
            documents=documents,
            metadatas=metadatas
        )
        logger.info(f"Cached {len(documents)} live ground-truth facts into ChromaDB.")
    except Exception as e:
        logger.warning(f"ChromaDB async fact caching notice: {e}")


# ---------------------------------------------------------
# Streaming Audit Pipeline (Server-Sent Events)
# ---------------------------------------------------------
async def audit_event_stream(claim: IncomingClaim) -> AsyncGenerator[str, None]:
    """
    Executes the dynamic ReAct audit pipeline, yielding SSE trace lines in real time
    as each tool executes, followed by the complete final JSON verdict.
    """
    def make_event(event_type: str, data: Any) -> str:
        if event_type == "trace":
            return f"data: {json.dumps({'type': 'trace', 'message': data})}\n\n"
        return f"data: {json.dumps({'type': event_type, 'payload': data})}\n\n"

    agent_trace: List[str] = []

    # Initial start
    start_msg = f"> [AGENT_START] Initializing dynamic ReAct verification pipeline on {claim.platform}..."
    agent_trace.append(start_msg)
    yield make_event("trace", start_msg)
    await asyncio.sleep(0.02)

    # Step 1: Scan for Scam Signals & WHOIS Domain Age
    scan_msg = "> [TOOL: SCANNER] Scanning claim text for URLs, strict Indian UPI handles, and contact numbers..."
    agent_trace.append(scan_msg)
    yield make_event("trace", scan_msg)

    scam_signals = await scan_scam_signals(claim.claim_text)
    forensic_evidence: List[str] = []
    sibling_domains: List[str] = []

    if scam_signals["urls"]:
        url_msg = f"> [TOOL: SCANNER] Extracted {len(scam_signals['urls'])} URL(s): {', '.join(scam_signals['urls'])}"
        agent_trace.append(url_msg)
        yield make_event("trace", url_msg)

        for d in scam_signals["domain_risks"]:
            detail_str = d.get("detail", "")
            dom = d.get("domain", "")
            if d.get("is_high_risk"):
                alert_msg = f"> [ALERT: WHOIS] ⚠️ HIGH RISK: {detail_str}"
            else:
                alert_msg = f"> [TOOL: WHOIS] {detail_str}"
            agent_trace.append(alert_msg)
            yield make_event("trace", alert_msg)
            forensic_evidence.append(detail_str)

            # Certificate Transparency Lookalikes using %brand% query
            brand_kw = extract_brand_keyword(domain=dom, text=claim.claim_text)
            if brand_kw:
                ct_msg = f"> [TOOL: CERT_TRANSPARENCY] Querying crt.sh for brand lookalikes matching '%{brand_kw}%'..."
                agent_trace.append(ct_msg)
                yield make_event("trace", ct_msg)

                lookalikes = await query_crt_sh_brand_lookalikes(brand_kw)
                if lookalikes:
                    sibling_domains.extend(lookalikes)
                    alert_ct = f"> [ALERT: INFRASTRUCTURE] Found {len(lookalikes)} Certificate Brand Lookalikes for '{brand_kw}': {', '.join(lookalikes[:3])}"
                    agent_trace.append(alert_ct)
                    yield make_event("trace", alert_ct)
                else:
                    agent_trace.append(f"> [TOOL: CERT_TRANSPARENCY] 0 active suspicious brand certificates found for '{brand_kw}'.")

    sibling_domains = list(dict.fromkeys(sibling_domains))

    if scam_signals["upis"]:
        upi_msg = f"Strict Indian UPI payment handle flagged: {', '.join(scam_signals['upis'])} (High Fraud Correlation)"
        alert_upi = f"> [ALERT: SCANNER] ⚠️ {upi_msg}"
        agent_trace.append(alert_upi)
        yield make_event("trace", alert_upi)
        forensic_evidence.append(upi_msg)

    if scam_signals["phones"]:
        phone_msg = f"Contact number solicitation flagged: {', '.join(scam_signals['phones'])}"
        agent_trace.append(f"> [TOOL: SCANNER] {phone_msg}")
        yield make_event("trace", f"> [TOOL: SCANNER] {phone_msg}")
        forensic_evidence.append(phone_msg)

    if scam_signals.get("has_financial_securities"):
        reg_msg = "Claim involves financial securities; cross-referencing SEBI/RBI unverified schemes registry."
        alert_reg = f"> [ALERT: REGULATORY] ⚠️ {reg_msg}"
        agent_trace.append(alert_reg)
        yield make_event("trace", alert_reg)
        forensic_evidence.append(reg_msg)

    # Step 2: Privacy-Preserving Crowd Radar
    yield make_event("trace", "> [TOOL: CROWD_RADAR] Checking privacy-preserving semantic query footprint...")
    radar_count = await query_and_update_crowd_radar(
        state.radar_collection,
        state.embedding_model,
        claim.claim_text,
        scam_signals
    )
    radar_msg = f"> [TOOL: CROWD_RADAR] Anonymized SHA-256 crowd radar scanned. Total radar footprint: {radar_count} query pattern(s)."
    agent_trace.append(radar_msg)
    yield make_event("trace", radar_msg)

    # Step 3: Fast LLM Search Query Extraction
    yield make_event("trace", "> [TOOL: QUERY_OPTIMIZER] Optimizing 3-5 word keyword query for Live Fact Check API...")
    search_keywords = await extract_search_query_with_llm(claim.claim_text, groq_client=state.groq_client)
    kw_msg = f"> [TOOL: QUERY_OPTIMIZER] Extracted search query: '{search_keywords}'"
    agent_trace.append(kw_msg)
    yield make_event("trace", kw_msg)

    # Step 4: Live Fact Check Tool (Google Fact Check Tools API)
    yield make_event("trace", "> [TOOL: LIVE_FACT_CHECK] Querying Google Fact Check Tools API for live verified claims...")
    live_facts = await query_google_fact_check_live(claim.claim_text, search_query=search_keywords)

    retrieved_docs_dict: Dict[str, str] = {}
    matched_sources: List[str] = []

    if live_facts:
        found_msg = f"> [TOOL: LIVE_FACT_CHECK] Found {len(live_facts)} live verified ground-truth record(s)."
        agent_trace.append(found_msg)
        yield make_event("trace", found_msg)

        for lf in live_facts:
            ev_id = f"E{len(retrieved_docs_dict) + 1}"
            doc_str = (
                f"Verified Fact: {lf['claim']}\n"
                f"Official Rating: {lf['rating']}\n"
                f"Publisher: {lf['publisher']} ({lf['title']})\n"
                f"URL: {lf['url']}"
            )
            retrieved_docs_dict[ev_id] = doc_str
            if lf.get("url"):
                matched_sources.append(lf["url"])

        # Asynchronously cache into ChromaDB
        asyncio.create_task(async_cache_facts_to_chroma(live_facts))
        cache_note = "> [TOOL: VECTOR_CACHE] Asynchronously embedding and caching live records into ChromaDB collection 'verified_facts'..."
        agent_trace.append(cache_note)
        yield make_event("trace", cache_note)
    else:
        # Fallback to local ChromaDB semantic search with strict distance cutoff (< 0.40)
        yield make_event("trace", "> [TOOL: VECTOR_CACHE] No direct live fact check match. Querying local ChromaDB with distance cutoff < 0.40...")
        chroma_dict, chroma_sources = await query_chroma_facts(
            state.collection,
            state.embedding_model,
            claim.claim_text,
            distance_cutoff=0.40
        )
        if chroma_dict:
            retrieved_docs_dict.update(chroma_dict)
            matched_sources.extend(chroma_sources)
            crm_msg = f"> [TOOL: VECTOR_CACHE] Retrieved {len(chroma_dict)} ground-truth record(s) meeting strict relevance threshold (< 0.40)."
        else:
            crm_msg = "> [TOOL: VECTOR_CACHE] ChromaDB query complete. No records met the strict distance threshold (< 0.40)."
        agent_trace.append(crm_msg)
        yield make_event("trace", crm_msg)

    # Append forensic evidence
    if forensic_evidence:
        retrieved_docs_dict[f"E{len(retrieved_docs_dict) + 1}"] = "SECURITY / DOMAIN FORENSICS:\n" + "\n".join(forensic_evidence)

    # Step 5: Autonomous Multi-Agent Parallel Debate
    debate_start = "> [DEBATE: MULTI_AGENT] Spawning parallel Red Team (Prosecutor) & Blue Team (Defender) via asyncio.gather..."
    agent_trace.append(debate_start)
    yield make_event("trace", debate_start)

    llm_output = await run_multi_agent_audit(
        claim_text=claim.claim_text,
        retrieved_docs_dict=retrieved_docs_dict,
        deepfake_score=claim.deepfake_score,
        forensic_signals=scam_signals,
        groq_client=state.groq_client,
    )

    judge_msg = "> [JUDGE: ARBITRATION] Judge Arbitrator synthesized debate arguments and decomposed atomic sub-claims."
    agent_trace.append(judge_msg)
    yield make_event("trace", judge_msg)

    detected_lang = llm_output.get("detected_language", "English")
    lang_msg = f"> [MULTILINGUAL] Detected claim language: {detected_lang}. Output rendered in same tongue."
    agent_trace.append(lang_msg)
    yield make_event("trace", lang_msg)

    # Step 6: Anti-Hallucination Citation Verification
    yield make_event("trace", "> [ANTI_HALLUCINATION] Verifying atomic sub-claim quotes against specific cited evidence snippets...")
    raw_atomics = llm_output.get("atomic_claims", [])
    parsed_atomics = verify_atomic_quotes(raw_atomics, retrieved_docs_dict, agent_trace)

    for step in agent_trace[-len(parsed_atomics):]:
        yield make_event("trace", step)

    if not parsed_atomics:
        parsed_atomics.append(
            AtomicClaim(
                sub_claim=claim.claim_text,
                verdict="Unverified",
                highlight_color="gray",
                evidence_id="E0",
                exact_quote="",
                quote_verified=False,
            )
        )

    # Step 7: Parse Verdict and Explanations
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
    counter_message = str(llm_output.get("counter_message", "")).strip() or explanation
    counter_words = counter_message.split()
    if len(counter_words) > 60:
        counter_message = " ".join(counter_words[:60]) + "..."

    # Manipulation tactics & prebunking
    raw_tactics = llm_output.get("manipulation_tactics", [])
    manipulation_tactics = [str(t).strip() for t in raw_tactics if str(t).strip()] if isinstance(raw_tactics, list) else []
    prebunk_lesson = str(llm_output.get("prebunk_lesson", "")).strip()
    if not prebunk_lesson:
        prebunk_lesson = "Always cross-examine unsolicited viral claims against official regulatory registries before sharing."

    # Step 8: Wayback Machine Actual Snapshot Links
    yield make_event("trace", "> [WAYBACK_MACHINE] Capturing immutable snapshots of retrieved sources (3s strict timeout)...")
    actual_snapshots = await snapshot_all_sources_to_wayback(matched_sources)
    if actual_snapshots:
        snap_msg = f"> [WAYBACK_MACHINE] Archived {len(actual_snapshots)} actual snapshot URL(s): {', '.join(actual_snapshots[:2])}"
    else:
        snap_msg = "> [WAYBACK_MACHINE] Source snapshot ping completed (no blocking wait)."
    agent_trace.append(snap_msg)
    yield make_event("trace", snap_msg)

    # Step 9: Ed25519 Cryptographic Receipt Generation
    yield make_event("trace", "> [TRANSPARENCY_LOG] Signing canonical rich payload with Ed25519 private key...")
    receipt_id = f"rcpt_{hashlib.sha256((claim.claim_text + datetime.utcnow().isoformat()).encode('utf-8')).hexdigest()[:16]}"
    model_id = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    if os.getenv("GROQ_API_KEY"):
        model_id = f"groq-multi-agent+{model_id}"

    receipt_doc = state.transparency_log.create_and_save_receipt(
        receipt_id=receipt_id,
        claim_text=claim.claim_text,
        retrieved_docs_dict=retrieved_docs_dict,
        atomic_claims=parsed_atomics,
        model_id=model_id,
        verdict=normalized_verdict,
        confidence_score=confidence,
        verified_sources=matched_sources,
        actual_archived_urls=actual_snapshots,
    )
    receipt_sig = receipt_doc.get("signature", "")
    receipt_url = f"/api/verify/{receipt_id}"

    rcpt_msg = f"> [TRANSPARENCY_LOG] Verifiable Ed25519 receipt generated: {receipt_id} (Sig: {receipt_sig[:12]}...)."
    agent_trace.append(rcpt_msg)
    yield make_event("trace", rcpt_msg)

    # Step 10: Official Cybercrime Pre-Fill Report Dossier
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
        dos_msg = "> [CYBERCRIME_DOSSIER] Generated Official Cybercrime Pre-Fill Report for cybercrime.gov.in & Sanchar Saathi."
        agent_trace.append(dos_msg)
        yield make_event("trace", dos_msg)

    # Final Payload Assembly
    final_audit_result = AuditResult(
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

    yield make_event("result", final_audit_result.model_dump())


# ---------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------
@app.get("/health", tags=["System"])
async def health_check():
    """Health check endpoint confirming model, vector store, and cryptographic key status."""
    return {
        "status": "healthy",
        "chroma_connected": state.chroma_client is not None,
        "collection_ready": state.collection is not None,
        "collection_count": state.collection.count() if state.collection else 0,
        "radar_ready": state.radar_collection is not None,
        "radar_count": state.radar_collection.count() if state.radar_collection else 0,
        "model_loaded": state.embedding_model is not None,
        "groq_configured": state.groq_client is not None,
        "gemini_configured": bool(os.getenv("GEMINI_API_KEY")),
        "transparency_log_active": state.transparency_log is not None,
        "ed25519_public_key": state.transparency_log.get_public_key() if state.transparency_log else None,
    }


@app.post(
    "/api/audit",
    tags=["Audit"],
    summary="Agentic multi-step audit streaming via Server-Sent Events (SSE)"
)
async def audit_claim_endpoint(claim: IncomingClaim, request: Request):
    """
    Server-Sent Events endpoint that streams chronological agent tool executions in real-time,
    concluding with the complete tribunal verdict.
    """
    return StreamingResponse(
        audit_event_stream(claim),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@app.get(
    "/api/verify/{receipt_id}",
    response_model=VerificationResponse,
    tags=["Transparency"],
    summary="Cryptographically verify an Ed25519 verdict receipt"
)
async def verify_verdict_receipt(receipt_id: str) -> VerificationResponse:
    """
    Independent verification endpoint:
    Returns the cryptographic receipt, canonical rich payload, signature, and Ed25519 public key.
    Third parties can independently verify the verdict and evidence hashes haven't been tampered with.
    """
    clean_id = re.sub(r"[^a-zA-Z0-9_\-]", "", receipt_id)
    storage_dir = state.transparency_log.storage_dir if state.transparency_log else "./receipts"
    receipt_path = os.path.join(storage_dir, f"{clean_id}.json")

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
            detail=f"Failed to read receipt document: {str(e)}"
        )

    payload = receipt_data.get("payload", {})
    signature = receipt_data.get("signature", "")
    public_key = receipt_data.get("public_key", "")
    algorithm = receipt_data.get("algorithm", "Ed25519")

    is_valid = False
    if state.transparency_log:
        is_valid = state.transparency_log.verify_signature(payload, signature, public_key)

    return VerificationResponse(
        receipt_id=clean_id,
        is_valid=is_valid,
        verification_status="cryptographically_verified" if is_valid else "signature_mismatch",
        algorithm=algorithm,
        public_key=public_key,
        signature=signature,
        receipt=receipt_data,
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
