import asyncio
from datetime import datetime
import hashlib
import json
import logging
import math
import os
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from fastapi import HTTPException, status
from pydantic import BaseModel

from models import AtomicClaim

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

logger = logging.getLogger("agents")


# ---------------------------------------------------------
# Lightweight Gemini Embedding Client (< 50MB RAM)
# ---------------------------------------------------------
class EmbeddingResult(list):
    """
    Subclass of list that provides .tolist() for drop-in compatibility with numpy arrays.
    """
    def tolist(self):
        return [item.tolist() if isinstance(item, EmbeddingResult) else item for item in self]


class GeminiEmbedder:
    """
    Ultra-lightweight Gemini Embedding client replacing heavy local PyTorch/SentenceTransformers.
    Uses Google Gemini's models/text-embedding-004 API with an ultra-lightweight,
    deterministic pseudo-embedding fallback if the API is offline or unconfigured.
    Guarantees < 50MB RAM footprint, running comfortably on 512MB free tier containers.
    """
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "models/text-embedding-004",
        dimension: int = 768
    ):
        self.api_key = (api_key or os.getenv("GEMINI_API_KEY", "")).strip().strip('"\'')
        self.model_name = model_name
        self.dimension = dimension
        if self.api_key and genai is not None:
            try:
                genai.configure(api_key=self.api_key)
            except Exception as e:
                logger.warning(f"Could not configure Gemini API for embeddings: {e}")

    def _deterministic_fallback(self, text: str) -> List[float]:
        """
        Ultra-lightweight deterministic unit-normalized pseudo-embedding (768-dim)
        using SHA-256 token hashing. Zero RAM, no PyTorch, zero heavy dependencies.
        """
        dim = self.dimension
        tokens = text.lower().split()
        if not tokens:
            tokens = [text or "empty"]
        vec = [0.0] * dim
        for token in tokens:
            h = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16)
            idx = h % dim
            sign = 1.0 if ((h >> 16) & 1) else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [round(x / norm, 6) for x in vec]

    def _embed_single(self, text: str, task_type: str = "retrieval_query") -> List[float]:
        clean = (text or "").strip()
        if not clean:
            return self._deterministic_fallback("")
        if self.api_key and genai is not None:
            try:
                res = genai.embed_content(
                    model=self.model_name,
                    content=clean[:2000],
                    task_type=task_type,
                )
                if isinstance(res, dict) and "embedding" in res:
                    emb = res["embedding"]
                    if isinstance(emb, list) and emb and isinstance(emb[0], (int, float)):
                        return emb
            except Exception as e:
                logger.debug(f"Gemini API embed_content notice ({e}), using deterministic fallback")
        return self._deterministic_fallback(clean)

    def _embed_batch(self, texts: List[str], task_type: str = "retrieval_document") -> List[List[float]]:
        if not texts:
            return []
        clean_texts = [(t or "").strip()[:2000] for t in texts]
        if self.api_key and genai is not None:
            try:
                res = genai.embed_content(
                    model=self.model_name,
                    content=clean_texts,
                    task_type=task_type,
                )
                if isinstance(res, dict) and "embedding" in res:
                    embs = res["embedding"]
                    if isinstance(embs, list) and embs and isinstance(embs[0], list):
                        return embs
            except Exception as e:
                logger.debug(f"Gemini API batch embed_content notice ({e}), using per-item fallback")
        return [self._embed_single(t, task_type=task_type) for t in clean_texts]

    def encode(
        self,
        sentences: Union[str, List[str]],
        *args,
        convert_to_numpy: bool = False,
        **kwargs
    ) -> EmbeddingResult:
        """
        Drop-in replacement for SentenceTransformer.encode.
        Supports both single strings and lists of strings.
        Returns EmbeddingResult list subclass with .tolist() support.
        """
        if isinstance(sentences, str):
            single_vec = self._embed_single(sentences, task_type="retrieval_query")
            return EmbeddingResult(single_vec)
        elif isinstance(sentences, list):
            batch_vecs = self._embed_batch(sentences, task_type="retrieval_document")
            return EmbeddingResult([EmbeddingResult(v) for v in batch_vecs])
        else:
            single_vec = self._embed_single(str(sentences), task_type="retrieval_query")
            return EmbeddingResult(single_vec)


def normalize_text_for_search(text: str) -> str:
    """
    Normalizes text for robust anti-hallucination substring matching
    by lowercasing, stripping punctuation, and collapsing whitespace.
    """
    cleaned = text.lower()
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def clean_json_response(raw_text: str) -> Dict[str, Any]:
    """
    Cleans and parses JSON output from LLMs, handling potential markdown fences.
    """
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*?\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise ValueError(f"Could not parse valid JSON from LLM response: {text[:120]}")


async def query_llm(
    system_prompt: str,
    user_prompt: str,
    as_json: bool = True,
    groq_client: Optional[Any] = None,
) -> Any:
    """
    Executes reasoning queries against Groq, falling back to Gemini 3.8 Flash.
    """
    groq_api_key = (os.getenv("GROQ_API_KEY") or "").strip().strip('"\'')
    gemini_api_key = (os.getenv("GEMINI_API_KEY") or "").strip().strip('"\'')

    # 1. Try Groq Provider
    groq_errors: List[str] = []
    if groq_api_key and groq_client:
        env_groq_model = (os.getenv("GROQ_MODEL") or "llama-3.1-8b-instant").strip().strip('"\'')
        candidate_models = [env_groq_model, "llama-3.3-70b-versatile"]

        for model_name in candidate_models:
            try:
                response = await asyncio.wait_for(
                    groq_client.chat.completions.create(
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        model=model_name,
                        temperature=0.2 if not as_json else 0.1,
                        response_format={"type": "json_object"} if as_json else None,
                    ),
                    timeout=15.0,
                )
                raw_content = response.choices[0].message.content
                return clean_json_response(raw_content) if as_json else raw_content.strip()

            except Exception as e:
                groq_errors.append(f"{model_name}: {str(e)[:80]}")
                continue

    # 2. Try Google Gemini Fallback with gemini-3.8-flash
    gemini_error: Optional[str] = None
    if gemini_api_key and genai:
        gemini_model_name = (os.getenv("GEMINI_MODEL") or "gemini-3.8-flash").strip().strip('"\'')
        try:
            genai.configure(api_key=gemini_api_key)
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
                timeout=18.0,
            )
            return clean_json_response(response.text) if as_json else response.text.strip()
        except Exception as e:
            gemini_error = f"Gemini ({gemini_model_name}): {str(e)[:80]}"

    all_errs = groq_errors + ([gemini_error] if gemini_error else [])
    err_summary = " | ".join(all_errs) if all_errs else "No LLM provider configured or available."
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Fact-Verification reasoning failed: {err_summary}"
    )


async def extract_search_query_with_llm(claim_text: str, groq_client: Optional[Any] = None) -> str:
    """
    Uses a fast LLM call to extract a 3-5 word optimized search query from the claim
    for the Google Fact Check Tools API, rather than blindly taking the first 6 words.
    """
    sys_prompt = "You are a search query optimizer for fact-check search engines."
    user_prompt = (
        f"Extract a 3 to 5 word search query capturing the core subject, person, and action of this claim:\n"
        f"\"{claim_text}\"\n\n"
        f"Return ONLY the 3 to 5 keywords on a single line. No quotes, no markdown, no explanation."
    )
    try:
        keywords = await query_llm(sys_prompt, user_prompt, as_json=False, groq_client=groq_client)
        clean_kw = re.sub(r"[^\w\s]", "", keywords).strip()
        words = clean_kw.split()
        if 2 <= len(words) <= 7:
            return " ".join(words[:5])
    except Exception as e:
        logger.debug(f"LLM search query extraction notice: {e}")

    # Fallback keyword extraction
    salient = [w for w in re.sub(r"[^\w\s]", "", claim_text).split() if len(w) > 3][:5]
    return " ".join(salient) if salient else claim_text[:50]


# ---------------------------------------------------------
# Citation-Verified Quote Checking (Specific Evidence Snippet)
# ---------------------------------------------------------
def verify_atomic_quotes(
    raw_atomics: List[Dict[str, Any]],
    retrieved_docs_dict: Dict[str, str],
    agent_trace: List[str],
) -> List[AtomicClaim]:
    """
    Anti-Hallucination Guard:
    Strictly verifies each extracted quote against the SPECIFIC cited evidence snippet (e.g., E1),
    NOT against a giant concatenated blob.
    If the citation is missing or the quote is not present in that specific snippet,
    the sub-claim is downgraded to Unverified.
    """
    valid_verdicts = {"True": "True", "False": "False", "Misleading": "Misleading", "Unverified": "Unverified"}
    parsed_atomics: List[AtomicClaim] = []

    for item in raw_atomics:
        if not isinstance(item, dict) or "sub_claim" not in item:
            continue

        sub_txt = str(item["sub_claim"]).strip()
        sub_v = valid_verdicts.get(str(item.get("verdict", "Unverified")).capitalize(), "Unverified")
        sub_color = item.get("highlight_color", "amber")
        ev_id = str(item.get("evidence_id", "E0")).strip()
        raw_quote = str(item.get("exact_quote", "")).strip()

        quote_verified = False
        if raw_quote and ev_id in retrieved_docs_dict:
            target_evidence_text = retrieved_docs_dict[ev_id]
            norm_quote = normalize_text_for_search(raw_quote)
            norm_evidence = normalize_text_for_search(target_evidence_text)

            if norm_quote and norm_quote in norm_evidence:
                quote_verified = True

        if quote_verified:
            agent_trace.append(
                f"> [ANTI_HALLUCINATION] ✓ Verified quote for sub-claim '{sub_txt[:35]}' strictly within citation [{ev_id}]."
            )
        else:
            if raw_quote:
                agent_trace.append(
                    f"> [ANTI_HALLUCINATION] ⚠️ Quote for sub-claim '{sub_txt[:35]}' failed verification against [{ev_id}]. Downgraded to Unverified."
                )
            else:
                agent_trace.append(f"> [ANTI_HALLUCINATION] Sub-claim '{sub_txt[:35]}' has no citation quote (marked Unverified).")
            sub_v = "Unverified"
            sub_color = "gray"

        if sub_color not in ("green", "red", "amber", "gray"):
            sub_color = "green" if sub_v == "True" else "red" if sub_v == "False" else "gray"

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

    return parsed_atomics


# ---------------------------------------------------------
# ChromaDB Semantic Facts Retrieval with Strict Distance Cutoff
# ---------------------------------------------------------
async def query_chroma_facts(
    collection: Any,
    embedding_model: Any,
    claim_text: str,
    distance_cutoff: float = 0.40,
) -> Tuple[Dict[str, str], List[str]]:
    """
    Queries ChromaDB verified_facts collection with a strict distance cutoff (< 0.40).
    Filters out semantically distant or irrelevant records.
    Returns (retrieved_docs_dict, matched_sources).
    """
    if collection is None or embedding_model is None:
        return {}, []

    try:
        claim_embedding = await asyncio.to_thread(
            embedding_model.encode,
            claim_text,
            convert_to_numpy=True
        )

        results = await asyncio.to_thread(
            collection.query,
            query_embeddings=[claim_embedding.tolist()],
            n_results=4,
            include=["documents", "metadatas", "distances", "ids"]
        )

        retrieved_docs_dict: Dict[str, str] = {}
        matched_sources: List[str] = []

        if results and results.get("documents") and results["documents"][0]:
            docs = results["documents"][0]
            metadatas = results.get("metadatas", [[]])[0]
            distances = results.get("distances", [[]])[0]

            for idx, (doc, dist) in enumerate(zip(docs, distances)):
                # Strict distance cutoff (< 0.40)
                if dist < distance_cutoff:
                    ev_id = f"E{len(retrieved_docs_dict) + 1}"
                    retrieved_docs_dict[ev_id] = doc
                    if idx < len(metadatas) and isinstance(metadatas[idx], dict):
                        src_url = metadatas[idx].get("url") or metadatas[idx].get("source")
                        if src_url:
                            matched_sources.append(src_url)

        return retrieved_docs_dict, list(dict.fromkeys(matched_sources))

    except Exception as e:
        logger.warning(f"ChromaDB retrieval error: {e}")
        return {}, []


# ---------------------------------------------------------
# Crowd Radar with Anonymization & Hash Document ID
# ---------------------------------------------------------
async def query_and_update_crowd_radar(
    radar_collection: Any,
    embedding_model: Any,
    claim_text: str,
    scam_signals: Dict[str, Any],
) -> int:
    """
    Privacy-Preserving Crowd Radar:
    - Stores only the SHA-256 hash of the claim and anonymized entity metadata.
    - NEVER stores the raw claim text.
    - Uses claim_hash as the document ID to overwrite duplicates instead of inflating count.
    - Returns the semantic crowd footprint count (< 0.35 distance).
    """
    if radar_collection is None or embedding_model is None:
        return 1

    claim_hash = hashlib.sha256(claim_text.strip().encode("utf-8")).hexdigest()

    try:
        claim_embedding = await asyncio.to_thread(
            embedding_model.encode,
            claim_text,
            convert_to_numpy=True
        )

        radar_res = await asyncio.to_thread(
            radar_collection.query,
            query_embeddings=[claim_embedding.tolist()],
            n_results=25,
            include=["distances", "ids"]
        )

        similar_count = 0
        if radar_res and radar_res.get("distances") and radar_res["distances"][0]:
            for dist in radar_res["distances"][0]:
                if dist < 0.35:
                    similar_count += 1

        radar_footprint = similar_count + 1

        # Anonymously upsert using claim_hash as document ID to avoid duplicate inflation
        anon_metadata = {
            "claim_hash": claim_hash,
            "has_urls": len(scam_signals.get("urls", [])) > 0,
            "has_upis": len(scam_signals.get("upis", [])) > 0,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

        await asyncio.to_thread(
            radar_collection.upsert,
            ids=[claim_hash],
            embeddings=[claim_embedding.tolist()],
            documents=[f"hash:{claim_hash}"],
            metadatas=[anon_metadata]
        )

        return radar_footprint

    except Exception as e:
        logger.warning(f"Crowd radar query/update error: {e}")
        return 1


# ---------------------------------------------------------
# Multi-Agent Debate & Judge Tribunal
# ---------------------------------------------------------
async def run_multi_agent_audit(
    claim_text: str,
    retrieved_docs_dict: Dict[str, str],
    deepfake_score: float,
    forensic_signals: Optional[Dict[str, Any]] = None,
    groq_client: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Spawns Red Team (Prosecutor) and Blue Team (Defender) in parallel via asyncio.gather.
    Then invokes the Judge Arbitrator for multilingual decomposition and final verdict.
    """
    if retrieved_docs_dict:
        facts_formatted = "\n".join(
            [f"[{ev_id}] {doc.strip()}" for ev_id, doc in retrieved_docs_dict.items()]
        )
    else:
        facts_formatted = "No relevant verified facts found in the ground-truth database."

    # Format forensic signals
    forensics_formatted = "None detected."
    if forensic_signals:
        lines = []
        if forensic_signals.get("urls"):
            lines.append(f"- Extracted URLs: {', '.join(forensic_signals['urls'])}")
        if forensic_signals.get("domain_risks"):
            for d in forensic_signals["domain_risks"]:
                lines.append(f"- Domain Forensics: {d.get('detail', '')}")
        if forensic_signals.get("upis"):
            lines.append(f"- Strict UPI Payment Handles: {', '.join(forensic_signals['upis'])} (High Scam Correlation)")
        if forensic_signals.get("phones"):
            lines.append(f"- Extracted Phone Numbers: {', '.join(forensic_signals['phones'])}")
        if lines:
            forensics_formatted = "\n".join(lines)

    # 1. Agent A: Red Team (Prosecutor) Prompt
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

    # 2. Agent B: Blue Team (Defender) Prompt
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

    red_future = query_llm(red_team_system, red_team_prompt, as_json=False, groq_client=groq_client)
    blue_future = query_llm(blue_team_system, blue_team_prompt, as_json=False, groq_client=groq_client)

    red_arg, blue_arg = await asyncio.gather(red_future, blue_future)

    # 3. Agent C: The Judge Arbitrator Prompt
    judge_system = (
        "You are the supreme arbitrator and Judge in an advanced Multi-Agent Fact-Verification Tribunal. "
        "Your task is to analyze the viral claim against live evidence, heuristic synthetic signal probability, "
        "and the competing arguments of the Red Team and Blue Team.\n\n"
        "MANDATORY INSTRUCTIONS:\n"
        "1. LANGUAGE DETECTION: Detect the exact language of the input CLAIM (e.g., Hindi, Hinglish, English, etc.). "
        "   You MUST write your entire final 'explanation' AND 'counter_message' in that EXACT SAME LANGUAGE.\n"
        "2. COUNTER MESSAGE: Write a punchy, factual debunking/clarification counter-message (maximum 60 words) "
        "   in the detected language, ready to be forwarded on WhatsApp to debunk the scam/misinformation.\n"
        "3. MANIPULATION FINGERPRINTING & PREBUNKING:\n"
        "   - 'manipulation_tactics': A list of detected tactics, e.g. 'Fake Urgency', 'Guaranteed Returns', 'Fabricated Authority'.\n"
        "   - 'prebunk_lesson': A concise 2-sentence psychological inoculation lesson explaining how this specific manipulation trick operates.\n"
        "4. ATOMIC DECOMPOSITION & EVIDENCE CITATION: Decompose the main claim into 2-4 atomic, verifiable sub-claims.\n"
        "   For each sub-claim, you MUST provide:\n"
        "   - 'sub_claim': Discrete verifiable statement.\n"
        "   - 'verdict': 'True', 'False', 'Misleading', or 'Unverified'.\n"
        "   - 'highlight_color': 'green' for True, 'red' for False, 'amber' for Misleading, 'gray' for Unverified.\n"
        "   - 'evidence_id': EXACT evidence ID matching the cited snippet (e.g. 'E1', 'E2'). If no evidence matches, use 'E0'.\n"
        "   - 'exact_quote': An EXACT, VERBATIM quote copied directly from that specific evidence snippet. Do NOT paraphrase.\n"
        "5. FINAL VERDICT: Must be 'True', 'False', 'Misleading', or 'Unverified'.\n"
        "6. OUTPUT FORMAT: Return strictly valid JSON matching this schema:\n"
        "{\n"
        '  "verdict": "False",\n'
        '  "confidence_score": 90,\n'
        '  "detected_language": "English",\n'
        '  "explanation": "Max 3-sentence explanation in detected language.",\n'
        '  "counter_message": "Punchy <= 60 word debunk in detected language.",\n'
        '  "manipulation_tactics": ["Fake Urgency", "Guaranteed Returns"],\n'
        '  "prebunk_lesson": "Scammers manufacture artificial urgency to bypass analytical scrutiny.",\n'
        '  "atomic_claims": [\n'
        '    {\n'
        '      "sub_claim": "...",\n'
        '      "verdict": "False",\n'
        '      "highlight_color": "red",\n'
        '      "evidence_id": "E1",\n'
        '      "exact_quote": "..."\n'
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

    judge_output = await query_llm(judge_system, judge_prompt, as_json=True, groq_client=groq_client)
    judge_output["red_team_argument"] = red_arg
    judge_output["blue_team_argument"] = blue_arg

    return judge_output

