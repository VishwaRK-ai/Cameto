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
    Uses strictly Ed25519 (via PyNaCl) with seed management from environment variables.
    Does NOT store or persist private keys to local disk files.
    """
    def __init__(self, storage_dir: str = "./receipts"):
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)
        self.algorithm = "Ed25519"
        self.signing_key: nacl.signing.SigningKey = None
        self.verify_key_hex: str = ""
        self._init_signing_key()

    def _init_signing_key(self):
        """
        Loads Ed25519 seed from SIGNING_SECRET_SEED environment variable.
        If missing or invalid, generates a new one, logs setup instructions,
        and uses it in memory without disk persistence.
        """
        seed_env = (os.getenv("SIGNING_SECRET_SEED") or "").strip().strip('"\'')
        if seed_env and seed_env != "<GENERATED_ED25519_SEED_HERE>":
            try:
                seed_bytes = bytes.fromhex(seed_env)
                if len(seed_bytes) == 32:
                    self.signing_key = nacl.signing.SigningKey(seed_bytes)
                    self.verify_key_hex = self.signing_key.verify_key.encode(
                        encoder=nacl.encoding.HexEncoder
                    ).decode("utf-8")
                    logger.info("Loaded Ed25519 signing key from SIGNING_SECRET_SEED.")
                    return
                else:
                    logger.warning(
                        f"SIGNING_SECRET_SEED has invalid length ({len(seed_bytes)} bytes != 32). Generating new seed."
                    )
            except Exception as e:
                logger.warning(f"Error parsing SIGNING_SECRET_SEED: {e}. Generating new seed.")

        # Generate ephemeral seed if missing
        self.signing_key = nacl.signing.SigningKey.generate()
        seed_hex = self.signing_key.encode(encoder=nacl.encoding.HexEncoder).decode("utf-8")
        self.verify_key_hex = self.signing_key.verify_key.encode(
            encoder=nacl.encoding.HexEncoder
        ).decode("utf-8")

        print("\n" + "=" * 76)
        print("[SECURITY NOTICE] SIGNING_SECRET_SEED was not found in environment!")
        print(f"Generated new Ed25519 signing seed for this session:")
        print(f"  SIGNING_SECRET_SEED=\"{seed_hex}\"")
        print("To ensure verdict receipts remain verifiable across restarts, add this to .env")
        print("=" * 76 + "\n")

    def get_public_key(self) -> str:
        """Returns the public verification key in hex format."""
        return self.verify_key_hex

    def sign_payload(self, payload: Dict[str, Any]) -> str:
        """
        Computes the canonical JSON representation and signs it with the Ed25519 private key.
        """
        canonical_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signed = self.signing_key.sign(canonical_bytes)
        return signed.signature.hex()

    def verify_signature(
        self,
        payload: Dict[str, Any],
        signature_hex: str,
        public_key_hex: Optional[str] = None
    ) -> bool:
        """
        Verifies the Ed25519 signature against canonical JSON payload using the given or stored public key.
        """
        canonical_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        pub_key = public_key_hex or self.verify_key_hex
        try:
            vk = nacl.signing.VerifyKey(bytes.fromhex(pub_key))
            vk.verify(canonical_bytes, bytes.fromhex(signature_hex))
            return True
        except Exception as e:
            logger.debug(f"Signature verification failure: {e}")
            return False

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
    ) -> Dict[str, Any]:
        """
        Constructs rich cryptographic payload:
        - hash of claim_text
        - individual SHA-256 hash of each evidence text snippet (E1, E2, ...)
        - exact atomic sub-claims breakdown
        - model_id, verdict, confidence, timestamp
        Signs payload and saves the public verification receipt to ./receipts/{receipt_id}.json
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

        receipt_file = os.path.join(self.storage_dir, f"{receipt_id}.json")
        try:
            with open(receipt_file, "w", encoding="utf-8") as f:
                json.dump(receipt_document, f, indent=2)
            logger.info(f"Cryptographic receipt persisted to '{receipt_file}'.")
        except Exception as e:
            logger.error(f"Failed to persist cryptographic receipt: {e}")

        return receipt_document

