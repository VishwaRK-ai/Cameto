# 🛡️ DigitalScam / Cameto
### A Multimodal, Cryptographically Verifiable Agentic Cyber-Fraud Detection Pipeline

[![Forge Gen AI Buildathon](https://img.shields.io/badge/Forge_Gen_AI-Buildathon_2026-6366f1.svg)](https://forgebuildathon.com)
[![Next.js 14](https://img.shields.io/badge/Next.js-14_App_Router-black.svg)](https://nextjs.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com)
[![Ed25519 Cryptography](https://img.shields.io/badge/Ed25519-PyNaCl_Transparency_Log-0284c7.svg)](https://pynacl.readthedocs.io)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-Vector_Store-ff6b6b.svg)](https://www.trychroma.com)
[![Google Gemini](https://img.shields.io/badge/Google_Gemini-3.8_Flash_Multimodal-4285F4.svg)](https://ai.google.dev)
[![Groq](https://img.shields.io/badge/Groq-Ultra_Fast_LPU_Inference-f55036.svg)](https://groq.com)

> **DigitalScam (Cameto)** is an enterprise-grade, autonomous ReAct multi-agent intelligence system designed to combat viral misinformation, financial phishing scams, synthetic deepfake audio/imagery, and fraudulent Indian payment infrastructure. Every audit is backed by **mathematically unforgeable Ed25519 cryptographic receipts**, live OSINT forensic scanning, and automated pre-filled Indian cybercrime incident reporting dossiers.

---

## 🌟 Core Pipeline Features & Innovations

### 1. 🎙️ Multimodal Forensic Ingestion (Text, Audio, Base64 Images)
- **Text & Viral Posts**: Analyzes social media posts across Reddit, Twitter/X, and WhatsApp in English, Hindi, and Hinglish.
- **WhatsApp Voice Notes (`.mp3`, `.wav`, `.ogg`)**: Ingests audio files, performs Gemini 3.8 Flash speech transcription, and calculates synthetic voice-cloning heuristic signals.
- **Image & Screenshot Forensics (Base64 File Upload)**: Accepts screenshot uploads encoded as Base64 Data URLs with Gemini 3.8 Flash Optical Character Recognition (OCR) and visual heuristic synthetic anomaly detection.
- **Zero-Text Fallback Logic**: Allows image-only audits without user-typed text. The frontend automatically injects an authoritative inspection prompt (`"Analyze the attached image. Extract any text, links, or claims from it and verify if it is a scam."`) to satisfy Pydantic schema validation while directing the AI tribunal to rely entirely on visual evidence.

### 2. 🔍 Live OSINT Forensic Tools
- **WHOIS Domain Age Inspection**: Extracts URLs via hardened regex patterns and queries WHOIS registration dates asynchronously. Automatically flags domains younger than 6 months (180 days) as critical phishing vectors.
- **Certificate Transparency (`crt.sh`) Brand Lookalikes**: Scans CT logs for lookalike domains targeting high-profile entities (e.g., SBI, Paytm, Mudra, Nirmala Sitharaman, SEBI). Uses **Levenshtein distance $\le 2$** and token substring matching to filter out noise and expose fraudulent infrastructure clusters.
- **Strict Indian Financial Identifier Extraction**: Hardened regex patterns extract Indian UPI handles (`@ybl`, `@paytm`, `@upi`, `@sbi`, `@icici`, `@okaxis`, `@axl`, `@ibl`) and Indian phone numbers (`+91` / 10-digit mobile) to prevent false-positive email captures.
- **Privacy-Preserving Crowd Radar**: Tracks network-wide viral scam proliferation using SHA-256 claim hashes as document IDs in ChromaDB, preventing count inflation while protecting whistleblower privacy.

### 3. ⚖️ Autonomous Multi-Agent Debate Tribunal
- **Parallel ReAct Debate**: Spawns **Agent A (The Prosecutor)** and **Agent B (The Defender)** concurrently via `asyncio.gather`. Agent A challenges deceptive tactics and flags Indicators of Compromise (IoCs), while Agent B advocates context and assesses possible partial truths.
- **The Judge Arbitrator**: Synthesizes both arguments, deconstructs claims into atomic verifiable sub-claims, detects dialect/language, assigns a calibrated confidence score, and authors a concise WhatsApp counter-misinformation message.
- **Anti-Hallucination Citation Verification**: Verifies quote citations strictly against specific ground-truth evidence snippets before rendering verdicts.

### 4. 🧠 Dynamic Vector Cache (Organic RAG)
- **Living Vector Memory**: Live fact-checks fetched from Google Fact Check Tools API are asynchronously vectorized using Google Gemini's `models/text-embedding-004` (with an ultra-lightweight SHA-256 deterministic fallback) and cached into ChromaDB's `verified_facts` collection.
- **Zero-Bloat Cloud Optimization**: Completely eliminates heavy local ML frameworks (`torch`, `sentence-transformers`) to run reliably with < 50MB RAM on free-tier containers.

### 5. 🔏 Verifiable Verdict Receipts (Ed25519 Transparency Log)
- **Pipeline Integrity Proof**: Receipts mathematically prove the integrity of the LLM pipeline, verifying that input claims, evidence snippets, and sub-claims were not manipulated post-audit.
- **Pinned Key Anti-Forgery Lock**: Verification endpoint `GET /api/verify/{receipt_id}` verifies signatures strictly against the server's pinned public key derived from `SIGNING_SECRET_SEED`, rejecting any client-supplied keys.
- **Persistent Serverless Storage**: Receipts are persisted in ChromaDB's `verifiable_receipts` collection, ensuring receipt permanence across container cold-starts.

### 6. 🚨 Actionable Incident Reporting (Cybercrime Pre-Fill Dossier)
- Generates an official incident dossier formatted for Indian authorities: **cybercrime.gov.in**, the **1930 Financial Fraud Helpline**, and the **DoT Sanchar Saathi (Chakshu)** portal.
- One-click export downloads a structured Markdown report detailing accused UPIs, suspect domains, registrar timestamps, and cryptographic receipt hashes.

---

## 🏗️ System Architecture & Tech Stack

```mermaid
flowchart TD
    subgraph Client["Frontend Client (Next.js 14 App Router - Vercel)"]
        UI["Interactive Dashboard UI\n(page.tsx)"]
        Upload["File Uploaders\n(Base64 Image & Audio)"]
        SSE["SSE Event Stream Reader\n(Live Agent Trace Terminal)"]
        KG["Interactive 2D Knowledge Graph\n(react-force-graph-2d)"]
        DossierBtn["One-Click Export\nCybercrime Dossier (.md)"]
    end

    subgraph Multimodal["Multimodal Perception Engine (:8001)"]
        Vision["Gemini 3.8 Flash Vision\n(Base64 Decode & OCR)"]
        Audio["Gemini 3.8 Flash Audio\n(Voice Note Cloning & Transcription)"]
    end

    subgraph Core["Core Reasoning & Transparency Backend (:8000 - Render)"]
        Main["FastAPI Gateway\n(main.py)"]
        Models["models.py\nPydantic Schemas"]
        Tools["tools.py\nWHOIS, crt.sh, Fact Check, Wayback"]
        Agents["agents.py\nReAct Debate, Judge, GeminiEmbedder"]
        Crypto["crypto_utils.py\nTransparencyLog (PyNaCl Ed25519)"]
    end

    subgraph Registries["External Registries & Storage"]
        Chroma["ChromaDB Vector Storage\n(verified_facts, crowd_radar, receipts)"]
        GoogleFC["Google Fact Check Tools API"]
        CRT["crt.sh Certificate Transparency"]
        Wayback["Wayback Machine Archiver"]
    end

    UI --> Upload
    Upload -->|"Base64 Image / Audio"| Multimodal
    UI -->|"POST /api/audit (SSE Stream)"| Main
    Main --> Tools
    Main --> Agents
    Main --> Crypto
    Agents --> Chroma
    Tools --> GoogleFC
    Tools --> CRT
    Tools --> Wayback
    Main -.->|"Server-Sent Events"| SSE
    SSE -.-> UI
    UI --> KG
    UI --> DossierBtn
```

### Tech Stack Breakdown

| Component | Technology | Role & Deployment |
| :--- | :--- | :--- |
| **Frontend** | Next.js 14, React 18, Tailwind CSS | Reactive dashboard, PWA Web Share Target, deployed on **Vercel** |
| **Visualization** | `react-force-graph-2d` | Dynamic, centered interactive knowledge graph mapping claims to live sources |
| **Backend API** | FastAPI, Uvicorn, Pydantic v2 | High-throughput asynchronous ReAct agent pipeline, deployed on **Render** |
| **LLM Reasoning** | Groq (Llama 3.1 / Qwen) & Gemini 3.8 Flash | Sub-second agent debate and multi-lingual verdict synthesis |
| **Multimodal Engine** | Google Gemini 3.8 Flash SDK | Base64 image OCR, audio voice note cloning detection, and transcription |
| **Vector Storage** | ChromaDB PersistentClient | High-dimensional similarity search for verified facts and crowd footprints |
| **Embeddings** | Gemini `text-embedding-004` | Lightweight API embeddings with deterministic unit-norm fallback (< 50MB RAM) |
| **Cryptography** | PyNaCl (Ed25519) | Deterministic signing and pinned public key receipt verification |
| **Live Forensics** | `python-whois`, `google-api-python-client` | Live domain age queries and Google Fact Check search |

---

## ⚖️ Multi-Agent Debate Tribunal Flow

```mermaid
sequenceDiagram
    autonumber
    actor User as Citizen / WhatsApp User
    participant Frontend as Next.js Dashboard
    participant Multimodal as Gemini Multimodal (:8001)
    participant Core as FastAPI Tribunal (:8000)
    participant Tools as Live Forensic Tools
    participant Debate as Red vs. Blue Team
    participant Judge as Judge Arbitrator
    participant Crypto as Ed25519 Transparency Log

    User->>Frontend: Upload Media / Post Text (or Image-only)
    alt Media Attached
        Frontend->>Multimodal: Send Base64 Image or Audio
        Multimodal-->>Frontend: Deepfake Heuristic Score + OCR / Transcription
    end

    Frontend->>Core: POST /api/audit (SSE Stream)
    Core-->>Frontend: SSE: > [AGENT_START] Initializing ReAct pipeline
    
    Core->>Tools: Regex Scan (URLs, UPIs, Phones) & WHOIS lookup
    Tools-->>Core: Domain age flags & IoCs
    Core-->>Frontend: SSE: > [TOOL: SCANNER] Indicators flagged
    
    Core->>Tools: Query Google Fact Check API & crt.sh Lookalikes
    Tools-->>Core: Verified facts & CT lookalike domains
    Core-->>Frontend: SSE: > [TOOL: LIVE_FACT_CHECK] Ground-truth facts loaded

    par Concurrent Debate Arguments
        Core->>Debate: Agent A (Prosecutor) argues scam/fraud using citations
        Core->>Debate: Agent B (Defender) argues context & partial truths
    end
    Debate-->>Core: Parallel Debate Arguments Collected
    Core-->>Frontend: SSE: > [DEBATE: MULTI_AGENT] Arguments synthesized

    Core->>Judge: Arbitrate debate, decompose atomic claims & verify quotes
    Judge-->>Core: Final verdict, confidence, atomic claims & WhatsApp message
    
    Core->>Crypto: Sign rich payload (claim hash, evidence hashes, verdict)
    Crypto-->>Core: Ed25519 Cryptographic Receipt (rcpt_...)
    Core-->>Frontend: SSE: > [TRANSPARENCY_LOG] Verifiable receipt issued

    Core-->>Frontend: Final AuditResult JSON Payload
    Frontend->>User: Render Interactive Graph, Verdict Card & Cybercrime Dossier
```

---

## 🔑 Authoritative Public Key

DigitalScam enforces a pinned public verification key model. Receipts are cryptographically verified against the server's authoritative key derived from `SIGNING_SECRET_SEED`:

```text
d6c8c17a86a2b613632827424d85cf1bddd2122e9f8ec0aa6883dbcf72c90002
```

Anyone can verify the cryptographic integrity and unforgeable authenticity of any audit receipt independently via the verification endpoint:
```bash
curl -s "https://your-backend-domain.com/api/verify/rcpt_YOUR_RECEIPT_ID" | jq
```

---

## 📁 Modular Codebase Structure

```text
DigitalScam/
├── main.py              # FastAPI app, lifespan, CORS, SSE audit endpoint, /api/verify
├── models.py            # Pydantic schemas (IncomingClaim, AtomicClaim, AuditResult, etc.)
├── crypto_utils.py      # TransparencyLog class, PyNaCl Ed25519 signing & pinned verification
├── tools.py             # Agentic tools (WHOIS, crt.sh lookalikes, Fact Check API, Wayback, Dossier)
├── agents.py            # Unified LLM client, GeminiEmbedder, Red/Blue debate, Judge
├── image_api.py         # Multimodal service: Gemini 3.8 Flash Vision (OCR) & Audio (Voice Notes)
├── seed_db.py           # ChromaDB database hydration from Google Fact Check Tools API
├── requirements.txt     # Clean backend dependencies (FastAPI, PyNaCl, ChromaDB, Groq, etc.)
├── Dockerfile           # Production Dockerfile optimized for Hugging Face Spaces & Render
├── .dockerignore        # Security exclusion rules preventing secret leakage
├── .env.example         # Clean environment configuration template (NO real keys)
├── .gitignore           # Enterprise security gitignore excluding all secrets & keys
└── frontend/            # Next.js 14 App Router dashboard
    ├── src/
    │   └── app/
    │       ├── layout.tsx    # Root layout, PWA meta tags, manifest link
    │       └── page.tsx      # Dashboard, SSE reader, Centered Force Graph, Dossier export
    └── public/
        ├── manifest.json     # PWA Web Share Target manifest (WhatsApp / Twitter share target)
        └── icon.svg          # Vector security badge
```

---

## 🚀 Setup & Execution Guide

### 1. Prerequisites
- **Python**: 3.10 or higher
- **Node.js**: 18.0 or higher & `npm`
- **Git**

### 2. Clone the Repository

```bash
git clone https://github.com/VishwaRK-ai/Cameto.git
cd Cameto
```

### 3. Environment Configuration

Copy the example environment file:
```bash
cp .env.example .env
```

Configure your `.env` file with the following variables:
```env
# Fast LLM Inference (Groq)
GROQ_API_KEY="your_groq_api_key_here"
GROQ_MODEL=llama-3.1-8b-instant

# Multimodal Perception & Embeddings (Google Gemini)
GEMINI_API_KEY="your_gemini_api_key_here"
GEMINI_MODEL=gemini-3.8-flash

# Fact Verification Tools
FACTCHECK_API_KEY="your_google_factcheck_api_key_here"

# Mandatory Ed25519 Cryptographic Signing Seed (64 hex characters)
SIGNING_SECRET_SEED="your_32_byte_hex_seed_here"

# Service Ports
PORT=8000
IMAGE_API_PORT=8001
```

> [!TIP]
> To generate a secure 32-byte hexadecimal `SIGNING_SECRET_SEED`, run:
> ```bash
> python3 -c "import secrets; print(secrets.token_hex(32))"
> ```

Configure the frontend environment in `frontend/.env.local`:
```env
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
NEXT_PUBLIC_VISION_URL=http://127.0.0.1:8001
```

### 4. Backend Setup & Startup

Install Python dependencies:
```bash
pip install -r requirements.txt
```

**Terminal 1 — Core Reasoning & Transparency Tribunal:**
```bash
uvicorn main:app --reload --port 8000
```

**Terminal 2 — Multimodal Vision & Audio Service:**
```bash
uvicorn image_api:app --reload --port 8001
```

*(Optional) Hydrate ChromaDB with genuine verified facts:*
```bash
python seed_db.py
```

### 5. Frontend Setup & Startup

**Terminal 3 — Next.js Dashboard:**
```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

---

## 🔍 Independent Receipt Verification (CLI)

Every completed audit generates an immutable cryptographic receipt stored in ChromaDB. Anyone can verify its cryptographic integrity via `curl`:

```bash
curl -s http://127.0.0.1:8000/api/verify/rcpt_sample_id | jq
```

**Sample Output:**
```json
{
  "receipt_id": "rcpt_d8d185f2de92a487",
  "is_valid": true,
  "verification_status": "cryptographically_verified",
  "algorithm": "Ed25519",
  "public_key": "d6c8c17a86a2b613632827424d85cf1bddd2122e9f8ec0aa6883dbcf72c90002",
  "signature": "8a49c3e210fe58c0e...",
  "receipt": {
    "receipt_id": "rcpt_d8d185f2de92a487",
    "payload": {
      "claim_hash": "b2f8a12903e481c9...",
      "evidence_hashes": {
        "E1": "49c8f0012ba4e..."
      },
      "atomic_claims": [
        {
          "sub_claim": "Finance Minister launched crypto scheme",
          "verdict": "False",
          "highlight_color": "red"
        }
      ],
      "verdict": "False",
      "confidence_score": 96.0,
      "timestamp": "2026-11-01T12:00:00Z"
    },
    "archived_sources": [
      "https://web.archive.org/web/20261101120000/https://pib.gov.in/FactCheck/detail.aspx"
    ]
  }
}
```

---

## 🚨 Official Cybercrime Pre-Fill Incident Report

When an audit completes, clicking **"Export Cybercrime Report (.md)"** produces a structured complaint report formatted for:
1. **National Cyber Crime Reporting Portal**: [cybercrime.gov.in](https://cybercrime.gov.in)
2. **Citizen Financial Cyber Fraud Helpline**: **1930**
3. **Department of Telecommunications Chakshu Portal**: [sancharsaathi.gov.in/sfc](https://sancharsaathi.gov.in/sfc)

The report pre-populates suspect UPI handles, fraudulent phone numbers, WHOIS domain ages, Certificate Transparency brand lookalikes, and the cryptographic receipt hash as digital forensic evidence.

---

## 👥 Contributors & Forge Buildathon Team
- **Project**: DigitalScam (Cameto)
- **Hackathon**: Forge Gen AI Buildathon 2026
- **Repository**: [https://github.com/VishwaRK-ai/Cameto.git](https://github.com/VishwaRK-ai/Cameto.git)
