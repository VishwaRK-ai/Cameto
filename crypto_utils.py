from datetime import datetime
import hashlib
import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("transparency-log")

# Strict PyNaCl Import: Insecure fallbacks are strictly prohibited
try:
    import nacl.signing
    import nacl.encoding
    import nacl.exceptions
except ImportError as e:
    raise ImportError(
        "CRITICAL DEPENDENCY ERROR: 'pynacl' is strictly required for Ed25519 cryptographic transparency receipts. "
        "Insecure fallbacks have been removed to comply with cryptographic integrity rules. "
        "Please install via: pip install pynacl"
    ) from e


class TransparencyLog:
    """
    Enterprise-Grade Verifiable Verdict Receipt Transparency Log.
    Uses strictly Ed25519 (via PyNaCl) with persistent seed management via SIGNING_SECRET_SEED.
    Stores public transparency receipts in ChromaDB ('verifiable_receipts').
    Enforces pinned public key verification—never trusts client-supplied public keys.
    """
    def __init__(self, receipts_collection: Optional[Any] = None):
        self.receipts_collection = receipts_collection
        self.algorithm = "Ed25519"
        self.signing_key: nacl.signing.SigningKey = None
        self.verify_key_hex: str = ""
        self._init_signing_key()

    def _init_signing_key(self):
        """
        Loads Ed25519 seed from SIGNING_SECRET_SEED environment variable.
        If missing or invalid, raises ValueError and CRASHES on startup.
        A random seed changes on restart, which would invalidate all past receipts.
        """
        seed_env = (os.getenv("SIGNING_SECRET_SEED") or "").strip().strip('"\'')
        if not seed_env or seed_env == "<GENERATED_ED25519_SEED_HERE>":
            raise ValueError(
                "CRITICAL SECURITY CONFIGURATION ERROR:\n"
                "'SIGNING_SECRET_SEED' is missing or not configured in environment.\n"
                "A persistent 32-byte hexadecimal seed is mandatory for server startup to ensure "
                "cryptographic receipt continuity and anti-forgery verification across restarts.\n"
                "Please add SIGNING_SECRET_SEED to your .env file."
            )

        try:
            seed_bytes = bytes.fromhex(seed_env)
            if len(seed_bytes) != 32:
                raise ValueError(
                    f"SIGNING_SECRET_SEED must be exactly 32 bytes (64 hex characters), got {len(seed_bytes)} bytes."
                )
            self.signing_key = nacl.signing.SigningKey(seed_bytes)
            self.verify_key_hex = self.signing_key.verify_key.encode(
                encoder=nacl.encoding.HexEncoder
            ).decode("utf-8")
        except Exception as e:
            raise ValueError(
                f"CRITICAL ERROR: Failed to parse SIGNING_SECRET_SEED as 32-byte hexadecimal: {e}"
            ) from e

        # Expose and print the server's authoritative public key on startup
        print("\n" + "=" * 76)
        print("[AUTHORITATIVE SERVER KEY] Ed25519 Public Verification Key:")
        print(f"  {self.verify_key_hex}")
        print("Use this pinned public key to independently verify all Cameto receipts.")
        print("=" * 76 + "\n")

    def get_public_key(self) -> str:
        """Returns the server's authoritative pinned public verification key in hex format."""
        return self.verify_key_hex

    def sign_payload(self, payload: Dict[str, Any]) -> str:
        """
        Computes canonical JSON representation and signs it with the server's Ed25519 private key.
        """
        canonical_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signed = self.signing_key.sign(canonical_bytes)
        return signed.signature.hex()

    def verify_signature(
        self,
        payload: Dict[str, Any],
        signature_hex: str
    ) -> bool:
        """
        Cryptographically verifies the Ed25519 signature strictly against the server's
        PINNED authoritative public key.
        DOES NOT trust or accept external public keys to prevent receipt forgery.
        """
        canonical_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        try:
            vk = nacl.signing.VerifyKey(bytes.fromhex(self.verify_key_hex))
            vk.verify(canonical_bytes, bytes.fromhex(signature_hex))
            return True
        except Exception as e:
            logger.debug(f"Signature verification failure against pinned server key: {e}")
            return False

    def verify_receipt(self, receipt_data: Dict[str, Any]) -> bool:
        """
        Verifies receipt payload and signature using the server's pinned public key.
        Ignores any bundled 'public_key' inside the receipt JSON.
        """
        payload = receipt_data.get("payload", {})
        signature = receipt_data.get("signature", "")
        if not payload or not signature:
            return False
        return self.verify_signature(payload, signature)

    def create_and_save_receipt(
        self,
        receipt_id: str,
        claim_text: str,
        retrieved_docs_dict: Dict[str, str],
        atomic_claims: List[Any],
        model_id: str,
        verdict: str,
        confidence_score: float,
        verified_sources: List[str],
        actual_archived_urls: List[str],
        receipts_collection: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Constructs rich cryptographic payload:
        - hash of claim_text
        - individual SHA-256 hash of each evidence text snippet (E1, E2, ...)
        - exact atomic sub-claims breakdown
        - model_id, verdict, confidence, timestamp
        Signs payload with Ed25519 and stores it persistently in the ChromaDB
        'verifiable_receipts' collection. No local disk JSON files are written.
        """
        claim_hash = hashlib.sha256(claim_text.strip().encode("utf-8")).hexdigest()

        # Hash each individual evidence snippet
        evidence_hashes: Dict[str, str] = {}
        for ev_id, ev_text in retrieved_docs_dict.items():
            evidence_hashes[ev_id] = hashlib.sha256(ev_text.strip().encode("utf-8")).hexdigest()

        # Serialize atomic claims
        serialized_atomics = []
        for ac in atomic_claims:
            if hasattr(ac, "model_dump"):
                serialized_atomics.append(ac.model_dump())
            elif hasattr(ac, "dict"):
                serialized_atomics.append(ac.dict())
            elif isinstance(ac, dict):
                serialized_atomics.append(ac)

        timestamp = datetime.utcnow().isoformat() + "Z"

        payload = {
            "receipt_id": receipt_id,
            "claim_hash": claim_hash,
            "evidence_hashes": evidence_hashes,
            "atomic_claims": serialized_atomics,
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
            "verified_sources": verified_sources,
            "archived_sources": actual_archived_urls,
            "created_at": timestamp,
        }

        # Persistent storage pivot: Store in ChromaDB verifiable_receipts collection
        target_collection = receipts_collection or self.receipts_collection
        if target_collection is not None:
            try:
                doc_str = json.dumps(receipt_document)
                target_collection.upsert(
                    ids=[receipt_id],
                    documents=[doc_str],
                    metadatas=[{
                        "receipt_id": receipt_id,
                        "verdict": verdict,
                        "confidence_score": float(confidence_score),
                        "created_at": timestamp,
                    }]
                )
                logger.info(f"Persisted cryptographic receipt to ChromaDB 'verifiable_receipts': {receipt_id}")
            except Exception as e:
                logger.error(f"Failed to upsert receipt to ChromaDB 'verifiable_receipts': {e}")
        else:
            logger.warning("No receipts ChromaDB collection attached. Receipt generated in-memory only.")

        return receipt_document
