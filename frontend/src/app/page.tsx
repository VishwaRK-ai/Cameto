"use client";

import React, { useState, useEffect, useRef, useMemo } from "react";
import dynamic from "next/dynamic";
import {
  ShieldAlert,
  ShieldCheck,
  AlertTriangle,
  HelpCircle,
  Sparkles,
  Link2,
  Search,
  Image as ImageIcon,
  Flame,
  ArrowRight,
  Clock,
  RefreshCw,
  ExternalLink,
  Activity,
  Database,
  Cpu,
  CheckCircle2,
  XCircle,
  Info,
  Scale,
  Network,
  Maximize2,
  Terminal,
  Globe2,
  Layers,
  Check,
  AlertOctagon,
  Share2,
  Fingerprint,
  Brain,
  FileText,
  Radio,
  Mic,
  UploadCloud,
  Copy,
  Volume2,
  Download
} from "lucide-react";

// Use environment variables for backend endpoints (fallback to localhost for dev)
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
const VISION_BASE_URL = process.env.NEXT_PUBLIC_VISION_URL || "http://127.0.0.1:8001";

// Dynamically import react-force-graph-2d with SSR disabled for Next.js App Router
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), {
  ssr: false,
  loading: () => (
    <div className="h-[380px] w-full flex flex-col items-center justify-center text-slate-500 text-xs font-mono bg-slate-950/80 rounded-xl border border-slate-800">
      <RefreshCw className="w-5 h-5 animate-spin text-cyan-400 mb-2" />
      <span>Initializing Interactive Provenance Graph...</span>
    </div>
  ),
});

interface AtomicClaim {
  sub_claim: string;
  verdict: "True" | "False" | "Misleading" | "Unverified";
  highlight_color: "green" | "red" | "amber" | "gray";
  evidence_id?: string;
  exact_quote?: string;
  quote_verified?: boolean;
}

interface AuditResult {
  verdict: "True" | "False" | "Misleading" | "Unverified";
  confidence_score: number;
  explanation: string;
  counter_message?: string;
  manipulation_tactics?: string[];
  prebunk_lesson?: string;
  radar_count?: number;
  extracted_ocr_text?: string;
  audio_transcription?: string;
  matched_sources: string[];
  sibling_domains?: string[];
  atomic_claims: AtomicClaim[];
  agent_trace: string[];
  detected_language: string;
  deepfake_score: number | null;
  claim_text: string;
  image_url?: string;
  timestamp: string;
  red_team_argument?: string;
  blue_team_argument?: string;
  receipt_id?: string;
  receipt_signature?: string;
  receipt_url?: string;
  action_dossier?: string;
}

interface GraphNode {
  id: string;
  name: string;
  label: string;
  group: "claim" | "source" | "deepfake" | "red_team" | "blue_team" | "sub_claim" | "sibling_domain";
  val: number;
  color: string;
  url?: string;
  detail?: string;
  x?: number;
  y?: number;
}

interface GraphLink {
  source: string;
  target: string;
  label: string;
  color: string;
}

const PRESET_CLAIMS = [
  {
    title: "Sitharaman Crypto Scam (Phishing & Synthetic Media)",
    claim: "Breaking: Finance Minister Nirmala Sitharaman announces government crypto investment platform with 30% monthly return. Deposit funds to official UPI id invest.finance@paytm or visit https://gov-sitharaman-crypto-portal.xyz to claim early access bonus.",
    imageUrl: "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=800",
    platform: "WhatsApp / Reddit",
  },
  {
    title: "CEO Voice Clone Wire Scam (Audio Synthetic Clone)",
    claim: "Urgent WhatsApp voice note from company Director: 'I need an emergency ₹5,00,000 RTGS vendor transfer right away to IFSC HDFC0001234 before the contract expires at 5 PM. Do not call back, I am in a board meeting.'",
    imageUrl: "",
    platform: "WhatsApp Voice Note",
  },
  {
    title: "Viral Moon Asteroid Collision (Synthetic Media)",
    claim: "NASA confirms a rogue asteroid collided with the lunar surface yesterday causing a massive flash visible from Earth.",
    imageUrl: "https://images.unsplash.com/photo-1579783900882-c0d3dad7b119?w=800",
    platform: "Reddit",
  },
  {
    title: "Hinglish Viral Scheme (Multilingual Test)",
    claim: "PM Modi ne launch kiya naya Rozgar Mudra digital portal. Sabhi citizens ko milenge 50000 rupees direct bank account me. Jaldi apply karein https://pm-yojana-offer.site/claim par.",
    imageUrl: "",
    platform: "WhatsApp",
  },
];

export default function Dashboard() {
  const [claimText, setClaimText] = useState("");
  const [imageUrl, setImageUrl] = useState("");
  const [imageFileName, setImageFileName] = useState("");
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [platform, setPlatform] = useState("Reddit");
  const [isLoading, setIsLoading] = useState(false);
  const [loadingStage, setLoadingStage] = useState<string>("");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [liveTrace, setLiveTrace] = useState<string[]>([]);
  const [copiedReceipt, setCopiedReceipt] = useState(false);

  const handleCopyReceipt = (text: string) => {
    if (!text) return;
    navigator.clipboard.writeText(text);
    setCopiedReceipt(true);
    setTimeout(() => setCopiedReceipt(false), 2000);
  };

  const handleDownloadDossier = (dossierMarkdown: string, receiptId?: string) => {
    if (!dossierMarkdown) return;
    const blob = new Blob([dossierMarkdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `Cybercrime_Report_${receiptId || "DigitalScam"}.md`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const [currentResult, setCurrentResult] = useState<AuditResult | null>(null);
  const [auditHistory, setAuditHistory] = useState<AuditResult[]>([]);
  const [activeTab, setActiveTab] = useState<"graph" | "debate" | "atomic" | "sources">("graph");
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);

  // System status states
  const [ragStatus, setRagStatus] = useState<"online" | "offline" | "checking">("checking");
  const [imageApiStatus, setImageApiStatus] = useState<"online" | "offline" | "checking">("checking");

  const graphRef = useRef<any>(null);

  // PWA Web Share Target listener: check if opened via mobile share target from WhatsApp, Twitter, etc.
  useEffect(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const sharedTitle = params.get("title");
      const sharedText = params.get("text");
      const sharedUrl = params.get("url");

      if (sharedTitle || sharedText || sharedUrl) {
        const parts = [sharedTitle, sharedText, sharedUrl].filter(Boolean);
        const combined = parts.join(" ");
        setClaimText(combined);
        // Clean URL search query without triggering page reload
        window.history.replaceState({}, document.title, window.location.pathname);
      }
    }
  }, []);

  // Health checks
  useEffect(() => {
    const checkBackends = async () => {
      try {
        const ragRes = await fetch(`${API_BASE_URL}/health`, { method: "GET" }).catch(() => null);
        setRagStatus(ragRes && ragRes.ok ? "online" : "offline");
      } catch {
        setRagStatus("offline");
      }

      try {
        const imgRes = await fetch(`${VISION_BASE_URL}/health`, { method: "GET" }).catch(() => null);
        setImageApiStatus(imgRes && imgRes.ok ? "online" : "offline");
      } catch {
        setImageApiStatus("offline");
      }
    };

    checkBackends();
    const interval = setInterval(checkBackends, 15000);
    return () => clearInterval(interval);
  }, []);

  const handleRunAudit = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!claimText.trim() && !audioFile && !imageUrl.trim()) {
      setErrorMessage("Please enter a viral claim text, upload an image/screenshot, or upload a voice note audio file (.mp3, .wav, .ogg) to audit.");
      return;
    }

    setIsLoading(true);
    setErrorMessage(null);
    setSelectedNode(null);
    setLoadingStage("Initializing ReAct live agent tools & security scanner...");

    try {
      let deepfakeScore: number | null = null;
      let ocrExtractedText = "";
      let audioTranscription = "";
      const effectiveImageUrl = imageUrl.trim();

      // Step 1A: Audio Voice Note Deepfake Detection & Speech Transcription
      if (audioFile) {
        setLoadingStage("Stage 1/3: Analyzing voice note for AI voice cloning & transcribing speech with Gemini 3.8 Flash...");
        try {
          const formData = new FormData();
          formData.append("file", audioFile);

          const audioRes = await fetch(`${VISION_BASE_URL}/api/detect-audio`, {
            method: "POST",
            body: formData,
          });

          if (audioRes.ok) {
            const audioData = await audioRes.json();
            if (audioData.deepfake_score !== null) {
              deepfakeScore = Number(audioData.deepfake_score);
            }
            if (audioData.transcription) {
              audioTranscription = String(audioData.transcription).trim();
            }
          } else {
            console.warn("Audio API returned non-200, status unavailable");
          }
        } catch (audioErr) {
          console.warn("Could not connect to Audio Detection API:", audioErr);
        }
      }

      // Step 1B: Multimodal Image Deepfake Score & OCR
      if (effectiveImageUrl) {
        setLoadingStage("Stage 2/3: Multimodal image audit & OCR transcription with Gemini 3.8 Flash...");
        try {
          const imgResponse = await fetch(`${VISION_BASE_URL}/api/detect-image`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ image_url: effectiveImageUrl }),
          });

          if (imgResponse.ok) {
            const imgData = await imgResponse.json();
            if (imgData.deepfake_score !== null) {
              const imgScore = Number(imgData.deepfake_score);
              deepfakeScore = deepfakeScore !== null ? Math.max(deepfakeScore, imgScore) : imgScore;
            }
            if (imgData.extracted_text) {
              ocrExtractedText = String(imgData.extracted_text).trim();
            }
          } else {
            console.warn("Image API returned non-200, status unavailable");
          }
        } catch (imgErr) {
          console.warn("Could not connect to Image Detection API:", imgErr);
        }
      }

      // Determine effective claim text: check if claimText is empty but an image is attached
      let effectiveClaim = claimText.trim();
      if (!effectiveClaim && effectiveImageUrl) {
        effectiveClaim = "Analyze the attached image. Extract any text, links, or claims from it and verify if it is a scam.";
      } else if (!effectiveClaim && audioTranscription) {
        effectiveClaim = audioTranscription;
      } else if (!effectiveClaim && ocrExtractedText) {
        effectiveClaim = ocrExtractedText;
      } else if (!effectiveClaim) {
        effectiveClaim = "Analyze the attached image. Extract any text, links, or claims from it and verify if it is a scam.";
      }

      // Step 2: Agentic Live Evidence Retrieval, Crowd Radar & Multi-Agent Debate
      setLoadingStage("Stage 3/3: Streaming ReAct live tools & Multi-Agent Debate...");
      const traceAccumulator: string[] = [];
      setLiveTrace([]);

      const ragResponse = await fetch(`${API_BASE_URL}/api/audit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          claim_text: effectiveClaim,
          deepfake_score: deepfakeScore !== null ? deepfakeScore : 0.0,
          platform: audioFile ? "WhatsApp Voice Note" : platform,
        }),
      });

      if (!ragResponse.ok) {
        const errJson = await ragResponse.json().catch(() => ({}));
        throw new Error(errJson.detail || `Audit failed with HTTP status ${ragResponse.status}`);
      }

      if (!ragResponse.body) {
        throw new Error("No response stream received from backend.");
      }

      const reader = ragResponse.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";
      let auditData: any = null;

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop() || "";

        for (const evt of events) {
          const trimmedEvt = evt.trim();
          if (!trimmedEvt.startsWith("data:")) continue;

          try {
            const rawJson = trimmedEvt.replace(/^data:\s*/, "");
            const parsed = JSON.parse(rawJson);

            if (parsed.type === "trace" && parsed.message) {
              traceAccumulator.push(parsed.message);
              setLiveTrace([...traceAccumulator]);
              setLoadingStage(parsed.message.replace(/^>\s*/, ""));
            } else if (parsed.type === "result" && parsed.payload) {
              auditData = parsed.payload;
            }
          } catch (pe) {
            console.debug("SSE chunk parse notice:", pe);
          }
        }
      }

      if (!auditData) {
        throw new Error("The audit pipeline completed without yielding a final result payload.");
      }

      const newAuditResult: AuditResult = {
        verdict: auditData.verdict || "Unverified",
        confidence_score: Number(auditData.confidence_score) || 50,
        explanation: auditData.explanation || "No explanation provided.",
        counter_message: auditData.counter_message || "",
        manipulation_tactics: auditData.manipulation_tactics || [],
        prebunk_lesson: auditData.prebunk_lesson || "",
        radar_count: Number(auditData.radar_count) || 1,
        receipt_id: auditData.receipt_id || "",
        receipt_signature: auditData.receipt_signature || "",
        receipt_url: auditData.receipt_url || "",
        action_dossier: auditData.action_dossier || "",
        extracted_ocr_text: ocrExtractedText,
        audio_transcription: audioTranscription,
        matched_sources: auditData.matched_sources || [],
        sibling_domains: auditData.sibling_domains || [],
        atomic_claims: auditData.atomic_claims || [],
        agent_trace: auditData.agent_trace || traceAccumulator,
        detected_language: auditData.detected_language || "English",
        deepfake_score: deepfakeScore,
        claim_text: effectiveClaim,
        image_url: effectiveImageUrl || undefined,
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
        red_team_argument: auditData.red_team_argument || "Prosecution argument evaluated by arbitration.",
        blue_team_argument: auditData.blue_team_argument || "Defense argument evaluated by arbitration.",
      };

      setCurrentResult(newAuditResult);
      setAuditHistory((prev) => [newAuditResult, ...prev.slice(0, 9)]);
    } catch (err: any) {
      console.error("Audit error:", err);
      setErrorMessage(err.message || "Failed to execute multi-agent audit. Please verify backend services are active.");
    } finally {
      setIsLoading(false);
      setLoadingStage("");
    }
  };

  const loadPreset = (preset: typeof PRESET_CLAIMS[0]) => {
    setClaimText(preset.claim);
    setImageUrl(preset.imageUrl);
    setImageFileName(preset.imageUrl ? "Preset Image Sample" : "");
    setPlatform(preset.platform);
    setAudioFile(null);
    setErrorMessage(null);
  };

  const getVerdictStyle = (verdict: AuditResult["verdict"]) => {
    switch (verdict) {
      case "True":
        return {
          bg: "bg-emerald-500/15 border-emerald-500/30 text-emerald-400",
          badge: "bg-emerald-500 text-black font-semibold",
          icon: <CheckCircle2 className="w-6 h-6 text-emerald-400" />,
          label: "VERIFIED TRUE",
          color: "#10b981",
        };
      case "False":
        return {
          bg: "bg-rose-500/15 border-rose-500/30 text-rose-400",
          badge: "bg-rose-500 text-white font-semibold",
          icon: <XCircle className="w-6 h-6 text-rose-400" />,
          label: "CONFIRMED FALSE",
          color: "#f43f5e",
        };
      case "Misleading":
        return {
          bg: "bg-amber-500/15 border-amber-500/30 text-amber-300",
          badge: "bg-amber-500 text-black font-semibold",
          icon: <AlertTriangle className="w-6 h-6 text-amber-400" />,
          label: "MISLEADING / SYNTHETIC",
          color: "#f59e0b",
        };
      default:
        return {
          bg: "bg-slate-500/15 border-slate-500/30 text-slate-300",
          badge: "bg-slate-500 text-white font-semibold",
          icon: <HelpCircle className="w-6 h-6 text-slate-400" />,
          label: "UNVERIFIED CONTEXT",
          color: "#94a3b8",
        };
    }
  };

  // Build Interactive Provenance Knowledge Graph Data
  const graphData = useMemo(() => {
    if (!currentResult) {
      return { nodes: [], links: [] };
    }

    const style = getVerdictStyle(currentResult.verdict);
    const nodes: GraphNode[] = [];
    const links: GraphLink[] = [];

    // Center Node: Viral Claim
    nodes.push({
      id: "claim",
      name: "Viral Claim",
      label: currentResult.claim_text.slice(0, 32) + "...",
      detail: currentResult.claim_text,
      group: "claim",
      val: 10,
      color: style.color,
    });

    // Heuristic Synthetic Signal Node
    const dfScore = currentResult.deepfake_score;
    const dfLabel = dfScore !== null ? `Synthetic Signal: ${dfScore.toFixed(1)}%` : "Synthetic Signal: Unavailable";
    nodes.push({
      id: "deepfake",
      name: "Heuristic Synthetic Signal",
      label: dfLabel,
      detail:
        dfScore === null
          ? "Heuristic synthetic signal inspection was unavailable or offline for this media."
          : dfScore > 75
          ? "Computer vision flags high probability of synthetic/AI generation (unvalidated heuristic signal)."
          : dfScore > 30
          ? "Moderate synthetic anomalies detected by heuristic analyzer."
          : "Media passes heuristic synthetic generation authenticity checks.",
      group: "deepfake",
      val: 7.5,
      color: dfScore !== null && dfScore > 75 ? "#f43f5e" : "#c084fc",
    });

    links.push({
      source: "claim",
      target: "deepfake",
      label: "Synthetic Signal Inspection",
      color: "#c084fc",
    });

    // Multi-Agent Debate Nodes
    if (currentResult.red_team_argument) {
      nodes.push({
        id: "red_team",
        name: "Red Team (Prosecutor)",
        label: "Prosecutor Debunk",
        detail: currentResult.red_team_argument,
        group: "red_team",
        val: 6.5,
        color: "#f43f5e",
      });
      links.push({
        source: "claim",
        target: "red_team",
        label: "Prosecution Arg",
        color: "#fb7185",
      });
    }

    if (currentResult.blue_team_argument) {
      nodes.push({
        id: "blue_team",
        name: "Blue Team (Defender)",
        label: "Defender Nuance",
        detail: currentResult.blue_team_argument,
        group: "blue_team",
        val: 6.5,
        color: "#3b82f6",
      });
      links.push({
        source: "claim",
        target: "blue_team",
        label: "Defense Arg",
        color: "#60a5fa",
      });
    }

    // Atomic Sub-Claims Nodes
    if (currentResult.atomic_claims && currentResult.atomic_claims.length > 0) {
      currentResult.atomic_claims.forEach((ac, idx) => {
        const subId = `sub_${idx + 1}`;
        const subColor =
          ac.highlight_color === "green"
            ? "#10b981"
            : ac.highlight_color === "red"
            ? "#f43f5e"
            : ac.highlight_color === "gray"
            ? "#64748b"
            : "#f59e0b";

        nodes.push({
          id: subId,
          name: `Sub-Claim #${idx + 1}`,
          label: ac.sub_claim.slice(0, 24) + "...",
          detail: `[${ac.verdict}] ${ac.sub_claim}${ac.exact_quote ? ` (Citation: "${ac.exact_quote}")` : ""}`,
          group: "sub_claim",
          val: 5.5,
          color: subColor,
        });

        links.push({
          source: "claim",
          target: subId,
          label: "Atomic Fact",
          color: subColor,
        });
      });
    }

    // Scam Lookalike Infrastructure Nodes (Certificate Transparency)
    if (currentResult.sibling_domains && currentResult.sibling_domains.length > 0) {
      currentResult.sibling_domains.forEach((sDom, idx) => {
        const sId = `sibling_${idx + 1}`;
        nodes.push({
          id: sId,
          name: `Lookalike Scam Infrastructure #${idx + 1}`,
          label: sDom,
          detail: `Certificate Transparency discovered sibling scam domain: ${sDom}`,
          group: "sibling_domain",
          val: 5,
          color: "#ef4444",
        });

        links.push({
          source: "claim",
          target: sId,
          label: "Lookalike Infrastructure",
          color: "#f87171",
        });
      });
    }

    // Live Ground-Truth Sources
    const sources = currentResult.matched_sources || [];
    if (sources.length > 0) {
      sources.forEach((src, idx) => {
        let domain = "Verified Fact Source";
        try {
          if (src.startsWith("http")) {
            domain = new URL(src).hostname.replace("www.", "");
          } else {
            domain = src.slice(0, 24);
          }
        } catch {
          domain = src.slice(0, 24);
        }

        const sourceId = `source_${idx + 1}`;
        nodes.push({
          id: sourceId,
          name: `Ground Truth Source #${idx + 1}`,
          label: domain,
          detail: src,
          url: src.startsWith("http") ? src : undefined,
          group: "source",
          val: 5.5,
          color: "#06b6d4",
        });

        links.push({
          source: "claim",
          target: sourceId,
          label: "Ground Truth",
          color: "#22d3ee",
        });
      });
    }

    return { nodes, links };
  }, [currentResult]);

  // Optimize D3 layout physics: Increase charge repulsion and link distance to spread nodes out naturally
  useEffect(() => {
    if (graphRef.current) {
      try {
        const chargeForce = graphRef.current.d3Force("charge");
        if (chargeForce && typeof chargeForce.strength === "function") {
          chargeForce.strength(-350);
        }
        const linkForce = graphRef.current.d3Force("link");
        if (linkForce && typeof linkForce.distance === "function") {
          linkForce.distance(105);
        }
        graphRef.current.d3ReheatSimulation?.();
      } catch (err) {
        console.warn("Could not configure D3 forces:", err);
      }
    }
  }, [graphData]);

  return (
    <div className="min-h-screen bg-[#070b14] text-slate-100 flex flex-col font-sans">
      {/* Top Header Bar */}
      <header className="border-b border-slate-800/80 bg-[#090f1d]/90 backdrop-blur sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-cyan-500 via-indigo-600 to-rose-500 flex items-center justify-center shadow-lg shadow-cyan-500/20">
              <ShieldAlert className="w-6 h-6 text-white" />
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <span className="font-bold text-lg tracking-tight text-white">DigitalScam</span>
                <span className="px-2 py-0.5 text-[10px] font-semibold bg-cyan-500/10 text-cyan-400 border border-cyan-500/30 rounded-full flex items-center space-x-1">
                  <Activity className="w-2.5 h-2.5 mr-1 text-cyan-400" />
                  <span>Forge Buildathon ReAct Engine</span>
                </span>
              </div>
              <p className="text-xs text-slate-400 hidden sm:block">
                Live Evidence Retrieval • WHOIS Forensics • Red vs. Blue Tribunal • Multilingual
              </p>
            </div>
          </div>

          {/* System Status Indicators */}
          <div className="flex items-center space-x-3 text-xs">
            <div className="flex items-center space-x-1.5 px-2.5 py-1 rounded-md bg-slate-900 border border-slate-800">
              <Database className="w-3.5 h-3.5 text-slate-400" />
              <span className="text-slate-400">ReAct Engine:</span>
              <span
                className={`w-2 h-2 rounded-full ${
                  ragStatus === "online" ? "bg-emerald-400 animate-pulse" : "bg-rose-500"
                }`}
              />
              <span className={ragStatus === "online" ? "text-emerald-400 font-medium" : "text-rose-400"}>
                {ragStatus}
              </span>
            </div>

            <div className="flex items-center space-x-1.5 px-2.5 py-1 rounded-md bg-slate-900 border border-slate-800">
              <Cpu className="w-3.5 h-3.5 text-slate-400" />
              <span className="text-slate-400">Vision API:</span>
              <span
                className={`w-2 h-2 rounded-full ${
                  imageApiStatus === "online" ? "bg-emerald-400 animate-pulse" : "bg-rose-500"
                }`}
              />
              <span className={imageApiStatus === "online" ? "text-emerald-400 font-medium" : "text-rose-400"}>
                {imageApiStatus}
              </span>
            </div>

            <div className="hidden sm:flex items-center space-x-1.5 px-2.5 py-1 rounded-md bg-slate-900 border border-slate-800">
              <Share2 className="w-3.5 h-3.5 text-cyan-400" />
              <span className="text-slate-400">PWA Share:</span>
              <span className="text-emerald-400 font-medium">Active</span>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        {/* Preset Demos Pill Bar */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 p-3.5 rounded-xl bg-slate-900/60 border border-slate-800">
          <div className="flex items-center space-x-2 text-xs text-slate-400">
            <Flame className="w-4 h-4 text-amber-400" />
            <span className="font-semibold text-slate-300">Live Scenarios (No Dummy Data):</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {PRESET_CLAIMS.map((preset, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => loadPreset(preset)}
                className="text-xs px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700/80 text-slate-200 border border-slate-700 transition"
              >
                {preset.title}
              </button>
            ))}
          </div>
        </div>

        {/* 2-Column Grid: Left Input + Right Live Feed */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
          {/* Left Column: Input Form & Results (7 cols) */}
          <div className="lg:col-span-7 space-y-6">
            {/* Input Card */}
            <div className="rounded-2xl bg-[#0c1222] border border-slate-800 p-6 shadow-xl">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-base font-semibold text-white flex items-center space-x-2">
                  <Search className="w-4 h-4 text-cyan-400" />
                  <span>Submit Claim to Dynamic Agent Pipeline</span>
                </h2>
                <div className="flex items-center space-x-2">
                  <label htmlFor="platform-select" className="text-xs text-slate-400">
                    Platform:
                  </label>
                  <select
                    id="platform-select"
                    value={platform}
                    onChange={(e) => setPlatform(e.target.value)}
                    className="bg-slate-900 border border-slate-700 rounded-md text-xs px-2 py-1 text-slate-200 focus:outline-none focus:border-cyan-500"
                  >
                    <option value="WhatsApp">WhatsApp</option>
                    <option value="Reddit">Reddit</option>
                    <option value="Twitter/X">Twitter / X</option>
                    <option value="Telegram">Telegram</option>
                    <option value="YouTube">YouTube</option>
                  </select>
                </div>
              </div>

              <form onSubmit={handleRunAudit} className="space-y-4">
                {/* Claim Text Area */}
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1.5 flex items-center justify-between">
                    <span>Viral Social Media Post / Claim Text <span className="text-rose-400">*</span></span>
                    <span className="text-[11px] text-cyan-400 font-mono flex items-center space-x-1">
                      <Globe2 className="w-3 h-3" />
                      <span>Supports English, Hindi & Hinglish</span>
                    </span>
                  </label>
                  <textarea
                    rows={4}
                    value={claimText}
                    onChange={(e) => setClaimText(e.target.value)}
                    placeholder="Paste viral message, scam links, UPI IDs, or social media text here..."
                    className="w-full bg-slate-950/80 border border-slate-800 rounded-xl p-3.5 text-sm text-slate-100 placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-cyan-500/40 focus:border-cyan-500 transition resize-none"
                  />
                </div>

                {/* Attached Image / Screenshot File Upload */}
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1.5 flex items-center justify-between">
                    <span className="flex items-center space-x-1.5">
                      <ImageIcon className="w-3.5 h-3.5 text-cyan-400" />
                      <span>Attached Image / Screenshot (Optional for Vision Audit)</span>
                    </span>
                    {imageUrl && (
                      <span className="text-[10px] text-emerald-400 font-mono">
                        {imageFileName ? imageFileName : "Image attached (Base64)"}
                      </span>
                    )}
                  </label>
                  <div className="flex items-center space-x-2">
                    <label className="flex-1 cursor-pointer flex items-center justify-between px-3.5 py-2.5 rounded-xl bg-slate-950/80 border border-slate-800 hover:border-slate-700 transition text-xs text-slate-300">
                      <div className="flex items-center space-x-2 truncate">
                        <UploadCloud className="w-4 h-4 text-cyan-400 flex-shrink-0" />
                        <span className="truncate">
                          {imageFileName || (imageUrl ? "Image attached (Base64)" : "Upload screenshot or image file (PNG, JPG, WebP)...")}
                        </span>
                      </div>
                      <span className="px-2 py-0.5 rounded bg-slate-800 text-[10px] text-slate-400 font-medium">
                        Browse
                      </span>
                      <input
                        type="file"
                        accept="image/*"
                        onChange={(e) => {
                          if (e.target.files && e.target.files[0]) {
                            const file = e.target.files[0];
                            setImageFileName(file.name);
                            const reader = new FileReader();
                            reader.onload = () => {
                              if (typeof reader.result === "string") {
                                setImageUrl(reader.result);
                              }
                            };
                            reader.readAsDataURL(file);
                          }
                        }}
                        className="hidden"
                      />
                    </label>
                    {imageUrl && (
                      <button
                        type="button"
                        onClick={() => {
                          setImageUrl("");
                          setImageFileName("");
                        }}
                        className="px-3 py-2.5 text-xs text-rose-400 hover:text-rose-300 rounded-xl bg-rose-500/10 border border-rose-500/20"
                      >
                        Clear
                      </button>
                    )}
                  </div>
                </div>

                {/* Voice Note / Audio Synthetic Signal Upload (.mp3, .wav, .ogg) */}
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1.5 flex items-center justify-between">
                    <span className="flex items-center space-x-1.5">
                      <Mic className="w-3.5 h-3.5 text-cyan-400" />
                      <span>WhatsApp Voice Note / Audio File (.mp3, .wav, .ogg)</span>
                    </span>
                    {audioFile && (
                      <span className="text-[10px] text-emerald-400 font-mono">
                        {audioFile.name} ({(audioFile.size / 1024).toFixed(1)} KB)
                      </span>
                    )}
                  </label>
                  <div className="flex items-center space-x-2">
                    <label className="flex-1 cursor-pointer flex items-center justify-between px-3.5 py-2.5 rounded-xl bg-slate-950/80 border border-slate-800 hover:border-slate-700 transition text-xs text-slate-300">
                      <div className="flex items-center space-x-2 truncate">
                        <UploadCloud className="w-4 h-4 text-cyan-400 flex-shrink-0" />
                        <span className="truncate">
                          {audioFile ? audioFile.name : "Upload voice note audio file (.mp3, .wav, .ogg)..."}
                        </span>
                      </div>
                      <span className="px-2 py-0.5 rounded bg-slate-800 text-[10px] text-slate-400 font-medium">
                        Browse
                      </span>
                      <input
                        type="file"
                        accept=".mp3,.wav,.ogg,audio/*"
                        onChange={(e) => {
                          if (e.target.files && e.target.files[0]) {
                            setAudioFile(e.target.files[0]);
                          }
                        }}
                        className="hidden"
                      />
                    </label>
                    {audioFile && (
                      <button
                        type="button"
                        onClick={() => setAudioFile(null)}
                        className="px-3 py-2.5 text-xs text-rose-400 hover:text-rose-300 rounded-xl bg-rose-500/10 border border-rose-500/20"
                      >
                        Clear
                      </button>
                    )}
                  </div>
                </div>

                {/* Error Banner */}
                {errorMessage && (
                  <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-400 text-xs flex items-start space-x-2">
                    <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                    <span>{errorMessage}</span>
                  </div>
                )}

                {/* Submit Action */}
                <div className="pt-2 flex items-center justify-between">
                  <div className="text-[11px] text-slate-500 flex items-center space-x-1.5">
                    <Activity className="w-3.5 h-3.5 text-cyan-400" />
                    <span>Live Google Fact Check Tools + WHOIS + Crowd Radar</span>
                  </div>
                  <button
                    type="submit"
                    disabled={isLoading || (!claimText.trim() && !audioFile && !imageUrl)}
                    className="px-6 py-2.5 rounded-xl bg-gradient-to-r from-cyan-500 via-indigo-600 to-rose-500 hover:opacity-90 text-white font-semibold text-sm shadow-lg shadow-cyan-500/20 disabled:opacity-50 disabled:cursor-not-allowed flex items-center space-x-2 transition"
                  >
                    {isLoading ? (
                      <>
                        <RefreshCw className="w-4 h-4 animate-spin" />
                        <span>Running Agent Pipeline...</span>
                      </>
                    ) : (
                      <>
                        <span>Execute ReAct Audit</span>
                        <ArrowRight className="w-4 h-4" />
                      </>
                    )}
                  </button>
                </div>
              </form>

              {/* Progress Stage Indicator */}
              {isLoading && (
                <div className="mt-4 p-3 rounded-lg bg-cyan-950/30 border border-cyan-800/40 flex items-center space-x-3 text-xs text-cyan-300">
                  <Activity className="w-4 h-4 animate-pulse text-cyan-400 flex-shrink-0" />
                  <span>{loadingStage}</span>
                </div>
              )}
            </div>

            {/* Live Agent Execution Trace Terminal */}
            {((currentResult && currentResult.agent_trace && currentResult.agent_trace.length > 0) || (isLoading && liveTrace.length > 0)) && (
              <div className="rounded-2xl bg-black/90 border border-slate-800 shadow-2xl overflow-hidden animate-fadeIn">
                <div className="bg-slate-900/90 px-4 py-2.5 border-b border-slate-800 flex items-center justify-between">
                  <div className="flex items-center space-x-2">
                    <div className="flex space-x-1.5">
                      <span className="w-2.5 h-2.5 rounded-full bg-rose-500/80 inline-block" />
                      <span className="w-2.5 h-2.5 rounded-full bg-amber-500/80 inline-block" />
                      <span className="w-2.5 h-2.5 rounded-full bg-emerald-500/80 inline-block" />
                    </div>
                    <span className="text-xs font-mono text-slate-400 ml-2 flex items-center space-x-1.5">
                      <Terminal className="w-3.5 h-3.5 text-cyan-400" />
                      <span>ReAct Agent Execution Trail (Live Trace)</span>
                    </span>
                  </div>
                  <span className={`text-[10px] font-mono px-2 py-0.5 rounded border flex items-center space-x-1 ${
                    isLoading
                      ? "text-cyan-400 bg-cyan-950/60 border-cyan-800/40"
                      : "text-emerald-400 bg-emerald-950/60 border-emerald-800/40"
                  }`}>
                    <span className={`w-1.5 h-1.5 rounded-full inline-block ${isLoading ? "bg-cyan-400 animate-ping" : "bg-emerald-400"}`} />
                    <span>{isLoading ? "STREAMING TOOLS LIVE..." : "EXECUTION COMPLETE"}</span>
                  </span>
                </div>
                <div className="p-4 font-mono text-xs text-slate-300 space-y-1.5 max-h-56 overflow-y-auto leading-relaxed bg-[#050811]">
                  {(isLoading && liveTrace.length > 0 ? liveTrace : (currentResult?.agent_trace || [])).map((step, idx) => (
                    <div
                      key={idx}
                      className={`${
                        step.includes("ALERT") || step.includes("HIGH RISK")
                          ? "text-rose-400 font-semibold"
                          : step.includes("LIVE_FACT_CHECK")
                          ? "text-cyan-300"
                          : step.includes("DEBATE")
                          ? "text-indigo-300"
                          : step.includes("JUDGE")
                          ? "text-amber-300"
                          : "text-slate-300"
                      }`}
                    >
                      {step}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Results Panel */}
            {currentResult && (
              <div className="rounded-2xl bg-[#0c1222] border border-slate-800 p-6 shadow-2xl space-y-6 animate-fadeIn">
                <div className="flex items-center justify-between border-b border-slate-800 pb-4">
                  <div className="flex items-center space-x-2">
                    <Sparkles className="w-5 h-5 text-cyan-400" />
                    <h3 className="font-semibold text-lg text-white">Tribunal Adjudication Report</h3>
                  </div>
                  <div className="flex items-center space-x-3">
                    <span className="text-xs text-cyan-400 bg-cyan-950/50 px-2.5 py-1 rounded-md border border-cyan-800/40 flex items-center space-x-1">
                      <Globe2 className="w-3 h-3 mr-1" />
                      <span>Language: {currentResult.detected_language}</span>
                    </span>
                    <span className="text-xs text-slate-500">{currentResult.timestamp}</span>
                  </div>
                </div>

                {/* Main Verdict Card */}
                {(() => {
                  const style = getVerdictStyle(currentResult.verdict);
                  return (
                    <div className={`p-4 rounded-xl border ${style.bg} flex items-center justify-between`}>
                      <div className="flex items-center space-x-3">
                        {style.icon}
                        <div>
                          <div className="text-xs tracking-wider uppercase opacity-75 font-semibold">
                            Judge Arbitrator Final Verdict
                          </div>
                          <div className="text-xl font-black">{style.label}</div>
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="text-xs opacity-75">Confidence Score</div>
                        <div className="text-2xl font-black">
                          {Math.round(currentResult.confidence_score)}%
                        </div>
                      </div>
                    </div>
                  );
                })()}

                {/* Live Crowd Radar Footprint */}
                <div className="p-3.5 rounded-xl bg-cyan-950/30 border border-cyan-800/40 flex items-center justify-between">
                  <div className="flex items-center space-x-2.5">
                    <div className="relative flex items-center justify-center">
                      <span className="w-3 h-3 rounded-full bg-cyan-400 animate-ping absolute opacity-75" />
                      <span className="w-2.5 h-2.5 rounded-full bg-cyan-400 relative" />
                    </div>
                    <div className="text-xs">
                      <span className="font-semibold text-cyan-300">📡 Live Crowd Radar: </span>
                      <span className="text-slate-200">
                        This scam pattern has been checked{" "}
                        <strong className="text-cyan-400 font-bold">{currentResult.radar_count || 1}</strong>{" "}
                        {currentResult.radar_count === 1 ? "time" : "times"} in the last 24 hours.
                      </span>
                    </div>
                  </div>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-400 border border-cyan-500/30 hidden sm:inline-block">
                    ChromaDB Crowd Radar Vector
                  </span>
                </div>

                {/* Rhetorical Manipulation Tactics Fingerprint */}
                {currentResult.manipulation_tactics && currentResult.manipulation_tactics.length > 0 && (
                  <div className="p-3.5 rounded-xl bg-amber-950/20 border border-amber-800/30 space-y-2">
                    <div className="flex items-center space-x-1.5 text-xs text-amber-400">
                      <Fingerprint className="w-3.5 h-3.5 text-amber-400" />
                      <span className="font-semibold uppercase tracking-wider text-[11px]">
                        Detected Manipulation Tactics (Psychological Fingerprint):
                      </span>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {currentResult.manipulation_tactics.map((tactic, idx) => (
                        <span
                          key={idx}
                          className="inline-flex items-center space-x-1.5 px-3 py-1 rounded-full text-xs font-medium bg-amber-500/15 text-amber-300 border border-amber-500/30 shadow-sm"
                        >
                          <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                          <span>{tactic}</span>
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Educational Inoculation (Prebunking) Callout Box */}
                {currentResult.prebunk_lesson && (
                  <div className="p-4 rounded-xl bg-gradient-to-r from-indigo-950/40 via-purple-950/30 to-slate-900 border border-indigo-500/30 space-y-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center space-x-2">
                        <div className="w-6 h-6 rounded-lg bg-indigo-500/20 border border-indigo-500/40 flex items-center justify-center">
                          <Brain className="w-3.5 h-3.5 text-indigo-400" />
                        </div>
                        <h4 className="text-xs font-semibold text-indigo-300 uppercase tracking-wider">
                          Educational Inoculation (Prebunking Analysis)
                        </h4>
                      </div>
                      <span className="text-[10px] text-indigo-400 font-mono bg-indigo-950/60 px-2 py-0.5 rounded border border-indigo-800/40">
                        Cognitive Defense Guard
                      </span>
                    </div>
                    <p className="text-xs text-slate-200 leading-relaxed pl-8 border-l-2 border-indigo-500/40 italic">
                      "{currentResult.prebunk_lesson}"
                    </p>
                  </div>
                )}

                {/* Screenshot OCR Extracted Text Display */}
                {currentResult.extracted_ocr_text && (
                  <div className="p-3.5 rounded-xl bg-slate-900/70 border border-slate-800 text-xs space-y-1.5">
                    <div className="flex items-center space-x-1.5 text-cyan-400 font-semibold text-[11px] uppercase tracking-wider">
                      <FileText className="w-3.5 h-3.5" />
                      <span>Gemini 3.8 Flash Screenshot OCR Extraction:</span>
                    </div>
                    <p className="text-slate-300 text-[11px] leading-relaxed font-mono bg-black/40 p-2.5 rounded border border-slate-800/80">
                      "{currentResult.extracted_ocr_text}"
                    </p>
                  </div>
                )}

                {/* Atomic Claims Highlights Breakdown */}
                {currentResult.atomic_claims && currentResult.atomic_claims.length > 0 && (
                  <div className="p-4 rounded-xl bg-slate-900/90 border border-slate-800 space-y-3">
                    <div className="flex items-center justify-between">
                      <h4 className="text-xs font-semibold text-slate-300 uppercase tracking-wider flex items-center space-x-1.5">
                        <Layers className="w-4 h-4 text-cyan-400" />
                        <span>Atomic Claim Decomposition (Citation-Verified)</span>
                      </h4>
                      <span className="text-[11px] text-slate-500 font-mono">
                        {currentResult.atomic_claims.length} sub-claims analyzed
                      </span>
                    </div>

                    <div className="space-y-2.5">
                      {currentResult.atomic_claims.map((ac, idx) => {
                        const isGreen = ac.highlight_color === "green";
                        const isRed = ac.highlight_color === "red";
                        const isAmber = ac.highlight_color === "amber";

                        return (
                          <div
                            key={idx}
                            className={`p-3.5 rounded-lg border text-xs flex flex-col space-y-2 ${
                              isGreen
                                ? "bg-emerald-950/20 border-emerald-500/30 text-emerald-200"
                                : isRed
                                ? "bg-rose-950/25 border-rose-500/40 text-rose-200"
                                : isAmber
                                ? "bg-amber-950/20 border-amber-500/30 text-amber-200"
                                : "bg-slate-900 border-slate-800 text-slate-300"
                            }`}
                          >
                            <div className="flex items-start justify-between gap-3">
                              <div className="flex items-start space-x-2">
                                {isGreen ? (
                                  <Check className="w-4 h-4 text-emerald-400 flex-shrink-0 mt-0.5" />
                                ) : isRed ? (
                                  <XCircle className="w-4 h-4 text-rose-400 flex-shrink-0 mt-0.5" />
                                ) : isAmber ? (
                                  <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
                                ) : (
                                  <HelpCircle className="w-4 h-4 text-slate-400 flex-shrink-0 mt-0.5" />
                                )}
                                <span className="font-medium text-slate-100">{ac.sub_claim}</span>
                              </div>
                              <span
                                className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider flex-shrink-0 ${
                                  isGreen
                                    ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                                    : isRed
                                    ? "bg-rose-500/20 text-rose-300 border border-rose-500/40"
                                    : isAmber
                                    ? "bg-amber-500/20 text-amber-300 border border-amber-500/40"
                                    : "bg-slate-800 text-slate-400 border border-slate-700"
                                }`}
                              >
                                {ac.verdict}
                              </span>
                            </div>

                            {/* Anti-Hallucination Citation Verification Badge & Ground-Truth Quote */}
                            <div className="pl-6 flex flex-col sm:flex-row sm:items-center justify-between gap-2 pt-1.5 border-t border-slate-800/60">
                              <div className="flex items-center space-x-2">
                                {ac.quote_verified ? (
                                  <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 flex items-center space-x-1">
                                    <Check className="w-3 h-3 text-emerald-400" />
                                    <span>✓ Quote Verified [{ac.evidence_id || "E1"}]</span>
                                  </span>
                                ) : (
                                  <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-rose-500/20 text-rose-300 border border-rose-500/40 flex items-center space-x-1">
                                    <AlertOctagon className="w-3 h-3 text-rose-400" />
                                    <span>⚠️ Hallucination Blocked</span>
                                  </span>
                                )}
                              </div>
                              {ac.exact_quote ? (
                                <span className="text-[11px] text-slate-400 italic truncate max-w-sm" title={ac.exact_quote}>
                                  "{ac.exact_quote}"
                                </span>
                              ) : (
                                <span className="text-[10px] text-slate-500 italic">No source quotation found in verified facts.</span>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* Heuristic Synthetic Signal Bar (0 - 100%) */}
                <div className="p-4 rounded-xl bg-slate-900/80 border border-slate-800 space-y-2.5">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-medium text-slate-300 flex items-center space-x-1.5">
                      <ImageIcon className="w-3.5 h-3.5 text-purple-400" />
                      <span>Heuristic Synthetic Signal (Vision / Audio):</span>
                    </span>
                    {currentResult.deepfake_score !== null ? (
                      <span
                        className={`font-mono font-bold ${
                          currentResult.deepfake_score > 75
                            ? "text-rose-400"
                            : currentResult.deepfake_score > 30
                            ? "text-amber-400"
                            : "text-emerald-400"
                        }`}
                      >
                        {currentResult.deepfake_score.toFixed(1)}% Heuristic Synthetic Signal
                      </span>
                    ) : (
                      <span className="font-mono text-slate-400">Status: Unavailable / Offline</span>
                    )}
                  </div>

                  <div className="w-full bg-slate-950 rounded-full h-3 p-0.5 overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all duration-700 ${
                        currentResult.deepfake_score === null
                          ? "bg-slate-700"
                          : currentResult.deepfake_score > 75
                          ? "bg-gradient-to-r from-amber-500 to-rose-500"
                          : currentResult.deepfake_score > 30
                          ? "bg-gradient-to-r from-emerald-500 to-amber-500"
                          : "bg-emerald-500"
                      }`}
                      style={{ width: `${currentResult.deepfake_score !== null ? Math.max(5, currentResult.deepfake_score) : 0}%` }}
                    />
                  </div>

                  {/* Disclaimers & Heuristic Transparency */}
                  <div className="flex items-start space-x-1.5 text-[11px] text-slate-400 pt-1 border-t border-slate-800/60">
                    <Info className="w-3.5 h-3.5 text-cyan-400 flex-shrink-0 mt-0.5" />
                    <span>
                      Note: AI vision/audio scores are unvalidated heuristic signals, not definitive cryptographic proof.
                    </span>
                  </div>
                </div>

                {/* Multilingual Explanation Card */}
                <div className="p-4 rounded-xl bg-slate-900/90 border border-slate-800 space-y-2">
                  <div className="flex items-center justify-between">
                    <h4 className="text-xs font-semibold text-slate-300 uppercase tracking-wider flex items-center space-x-1.5">
                      <Info className="w-4 h-4 text-cyan-400" />
                      <span>Auditor Explanation ({currentResult.detected_language})</span>
                    </h4>
                  </div>
                  <p className="text-sm text-slate-200 leading-relaxed font-normal">
                    {currentResult.explanation}
                  </p>
                </div>

                {/* Counter-Message & WhatsApp Share Action */}
                <div className="p-4 rounded-xl bg-gradient-to-r from-emerald-950/30 via-slate-900 to-slate-900 border border-emerald-500/30 space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center space-x-2">
                      <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                      <h4 className="text-xs font-semibold text-emerald-300 uppercase tracking-wider flex items-center space-x-1.5">
                        <Share2 className="w-3.5 h-3.5 text-emerald-400" />
                        <span>Debunk Counter-Message (WhatsApp Ready)</span>
                      </h4>
                    </div>
                    <span className="text-[10px] text-slate-400 font-mono">
                      {(currentResult.counter_message || currentResult.explanation).split(/\s+/).length} words
                    </span>
                  </div>

                  <p className="text-xs text-slate-200 leading-relaxed italic bg-black/40 p-3 rounded-lg border border-slate-800">
                    "{currentResult.counter_message || currentResult.explanation}"
                  </p>

                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pt-1">
                    <span className="text-[11px] text-slate-400">
                      Disarm viral misinformation by forwarding this verified clarification.
                    </span>
                    <a
                      href={`https://wa.me/?text=${encodeURIComponent(
                        `${currentResult.counter_message || currentResult.explanation} ${
                          currentResult.matched_sources[0] || ""
                        }`.trim()
                      )}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center space-x-2 px-3.5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold shadow-md shadow-emerald-900/40 transition flex-shrink-0"
                    >
                      <Share2 className="w-3.5 h-3.5" />
                      <span>Share Correction to WhatsApp</span>
                    </a>
                  </div>
                </div>

                {/* Voice Note Audio Transcription (Gemini 3.8 Flash) */}
                {currentResult.audio_transcription && (
                  <div className="p-4 rounded-xl bg-purple-950/20 border border-purple-500/30 text-xs space-y-2 animate-fadeIn">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center space-x-2 text-purple-300 font-semibold uppercase tracking-wider text-[11px]">
                        <Volume2 className="w-4 h-4 text-purple-400" />
                        <span>Voice Note Speech Transcription (Gemini 3.8 Flash)</span>
                      </div>
                      <span className="text-[10px] text-purple-400 font-mono bg-purple-950/60 px-2 py-0.5 rounded border border-purple-800/40">
                        Multimodal Audio Audit
                      </span>
                    </div>
                    <p className="text-slate-200 text-xs leading-relaxed italic bg-black/40 p-3 rounded-lg border border-purple-800/40">
                      "{currentResult.audio_transcription}"
                    </p>
                  </div>
                )}

                {/* Verifiable Verdict Receipt (Ed25519 Transparency Log) */}
                {currentResult.receipt_id && (
                  <div className="p-4 rounded-xl bg-slate-900/90 border border-cyan-500/30 shadow-lg space-y-3 animate-fadeIn">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center space-x-2">
                        <div className="w-6 h-6 rounded-lg bg-cyan-500/20 border border-cyan-500/40 flex items-center justify-center">
                          <CheckCircle2 className="w-4 h-4 text-cyan-400" />
                        </div>
                        <div>
                          <h4 className="text-xs font-bold text-cyan-300 uppercase tracking-wider flex items-center space-x-1.5">
                            <span>Verifiable Verdict Receipt (Transparency Log)</span>
                          </h4>
                          <p className="text-[10px] text-slate-400">
                            Immutable Ed25519 cryptographic proof of claim text, facts corpus, and verdict integrity.
                          </p>
                        </div>
                      </div>
                      <span className="text-[10px] font-mono text-cyan-300 bg-cyan-950/60 px-2 py-0.5 rounded border border-cyan-800/40">
                        Ed25519 Signed
                      </span>
                    </div>

                    <div className="p-3 rounded-lg bg-black/60 border border-slate-800 text-xs font-mono space-y-1.5">
                      <div className="flex items-center justify-between">
                        <span className="text-slate-400 text-[11px]">Receipt ID:</span>
                        <span className="text-cyan-300 font-bold">{currentResult.receipt_id}</span>
                      </div>
                      {currentResult.receipt_signature && (
                        <div className="flex items-center justify-between">
                          <span className="text-slate-400 text-[11px]">Ed25519 Signature:</span>
                          <span className="text-slate-400 text-[11px] truncate max-w-xs" title={currentResult.receipt_signature}>
                            {currentResult.receipt_signature.slice(0, 24)}...
                          </span>
                        </div>
                      )}
                    </div>

                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pt-1">
                      <a
                        href={`${API_BASE_URL}/api/verify/${currentResult.receipt_id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center space-x-1.5 text-xs text-cyan-400 hover:text-cyan-300 hover:underline"
                      >
                        <ExternalLink className="w-3.5 h-3.5" />
                        <span>Inspect & Verify Cryptographic Receipt (API)</span>
                      </a>
                      <button
                        type="button"
                        onClick={() => handleCopyReceipt(`${API_BASE_URL}/api/verify/${currentResult.receipt_id}`)}
                        className="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium border border-slate-700 transition"
                      >
                        {copiedReceipt ? (
                          <>
                            <Check className="w-3.5 h-3.5 text-emerald-400" />
                            <span>Link Copied!</span>
                          </>
                        ) : (
                          <>
                            <Copy className="w-3.5 h-3.5 text-slate-400" />
                            <span>Copy Verification Link</span>
                          </>
                        )}
                      </button>
                    </div>
                  </div>
                )}

                {/* Verdict-to-Action Cybercrime Pre-Fill Report Dossier */}
                {currentResult.action_dossier && (
                  <div className="p-4 rounded-xl bg-gradient-to-r from-rose-950/40 via-slate-900 to-amber-950/20 border border-rose-500/40 shadow-xl space-y-3 animate-fadeIn">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center space-x-2">
                        <div className="w-7 h-7 rounded-lg bg-rose-500/20 border border-rose-500/40 flex items-center justify-center">
                          <ShieldAlert className="w-4 h-4 text-rose-400" />
                        </div>
                        <div>
                          <h4 className="text-xs font-bold text-rose-300 uppercase tracking-wider flex items-center space-x-1.5">
                            <span>Official Cybercrime Pre-Fill Report</span>
                          </h4>
                          <p className="text-[10px] text-slate-400">
                            Pre-formatted dossier ready for cybercrime.gov.in (1930 Helpline) & DoT Sanchar Saathi.
                          </p>
                        </div>
                      </div>
                      <span className="text-[10px] font-mono text-rose-300 bg-rose-950/60 px-2 py-0.5 rounded border border-rose-800/40">
                        Action Required
                      </span>
                    </div>

                    <div className="p-3 rounded-lg bg-black/60 border border-rose-900/30 text-xs space-y-1.5 text-slate-300">
                      <div className="text-[11px] font-semibold text-rose-300 flex items-center space-x-1">
                        <span>🚨 Immediate Reporting Instructions:</span>
                      </div>
                      <p className="text-[11px] leading-relaxed text-slate-300">
                        File this report at <strong className="text-white">cybercrime.gov.in</strong> or call the national <strong className="text-white">1930 Helpline</strong> to freeze fraudulent bank transfers within the golden hour. For SMS/WhatsApp fraud, report via <strong className="text-white">DoT Sanchar Saathi (Chakshu)</strong>.
                      </p>
                    </div>

                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pt-1">
                      <span className="text-[11px] text-slate-400 italic">
                        Download full forensic dossier with WHOIS domain ages, UPI IDs & CT sibling certificates.
                      </span>
                      <button
                        type="button"
                        onClick={() => handleDownloadDossier(currentResult.action_dossier || "", currentResult.receipt_id)}
                        className="inline-flex items-center space-x-2 px-4 py-2 rounded-lg bg-rose-600 hover:bg-rose-500 text-white text-xs font-bold shadow-lg shadow-rose-950/50 transition active:scale-95 flex-shrink-0"
                      >
                        <Download className="w-3.5 h-3.5" />
                        <span>Export Cybercrime Report (.md)</span>
                      </button>
                    </div>
                  </div>
                )}

                {/* Multi-Agent Section Tabs */}
                <div className="border-b border-slate-800 flex items-center space-x-4 text-xs font-semibold">
                  <button
                    type="button"
                    onClick={() => setActiveTab("graph")}
                    className={`pb-2.5 flex items-center space-x-1.5 transition border-b-2 ${
                      activeTab === "graph"
                        ? "border-cyan-500 text-cyan-400"
                        : "border-transparent text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    <Network className="w-4 h-4" />
                    <span>Interactive Provenance Graph</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => setActiveTab("debate")}
                    className={`pb-2.5 flex items-center space-x-1.5 transition border-b-2 ${
                      activeTab === "debate"
                        ? "border-cyan-500 text-cyan-400"
                        : "border-transparent text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    <Scale className="w-4 h-4" />
                    <span>Red vs. Blue Debate</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => setActiveTab("sources")}
                    className={`pb-2.5 flex items-center space-x-1.5 transition border-b-2 ${
                      activeTab === "sources"
                        ? "border-cyan-500 text-cyan-400"
                        : "border-transparent text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    <Link2 className="w-4 h-4" />
                    <span>Live Source Citations ({currentResult.matched_sources.length})</span>
                  </button>
                </div>

                {/* Tab 1: Interactive Provenance Graph */}
                {activeTab === "graph" && (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between text-xs text-slate-400">
                      <div className="flex items-center space-x-3 text-[11px] flex-wrap gap-y-1">
                        <span className="flex items-center space-x-1">
                          <span className="w-2.5 h-2.5 rounded-full bg-cyan-400 inline-block" />
                          <span>Live Sources</span>
                        </span>
                        <span className="flex items-center space-x-1">
                          <span className="w-2.5 h-2.5 rounded-full bg-purple-500 inline-block" />
                          <span>Heuristic Synthetic Signal</span>
                        </span>
                        <span className="flex items-center space-x-1">
                          <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 inline-block" />
                          <span>True Sub-claims</span>
                        </span>
                        <span className="flex items-center space-x-1">
                          <span className="w-2.5 h-2.5 rounded-full bg-rose-500 inline-block" />
                          <span>False Sub-claims</span>
                        </span>
                        {currentResult.sibling_domains && currentResult.sibling_domains.length > 0 && (
                          <span className="flex items-center space-x-1">
                            <span className="w-2.5 h-2.5 rounded-full bg-red-600 inline-block animate-pulse" />
                            <span className="text-red-400 font-semibold">Scam Infrastructure ({currentResult.sibling_domains.length})</span>
                          </span>
                        )}
                      </div>
                      <span className="text-[11px] text-slate-500 hidden sm:inline">
                        Drag, zoom & click nodes
                      </span>
                    </div>

                    {/* 2D Canvas Force Graph */}
                    <div className="flex justify-center items-center w-full overflow-x-auto mx-auto my-6">
                      <div className="h-[440px] w-full max-w-full bg-slate-950 rounded-xl border border-slate-800 overflow-hidden relative flex justify-center items-center">
                        <ForceGraph2D
                          ref={graphRef}
                          graphData={graphData}
                          nodeRelSize={3}
                          nodeLabel={(node: any) => `${node.name}\n${node.detail || ""}`}
                          cooldownTicks={120}
                          d3AlphaDecay={0.02}
                          d3VelocityDecay={0.3}
                          onEngineStop={() => graphRef.current?.zoomToFit(400, 30)}
                          nodeCanvasObject={(node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
                            const label = node.label || node.name;
                            const radius = node.val || 5;

                            // Outer node circle
                            ctx.beginPath();
                            ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI, false);
                            ctx.fillStyle = node.color || "#06b6d4";
                            ctx.fill();

                            // Crisp high-contrast border
                            ctx.lineWidth = 1.2 / globalScale;
                            ctx.strokeStyle = "rgba(255, 255, 255, 0.85)";
                            ctx.stroke();

                            // Inner specular glow highlight
                            ctx.beginPath();
                            ctx.arc(node.x, node.y, radius * 0.45, 0, 2 * Math.PI, false);
                            ctx.fillStyle = "rgba(255, 255, 255, 0.65)";
                            ctx.fill();

                            // Label styling: render below node with semi-transparent dark pill background for ultra-crisp legibility
                            const fontSize = 9.5 / globalScale;
                            ctx.font = `600 ${fontSize}px ui-sans-serif, system-ui, -apple-system, sans-serif`;
                            const yOffset = radius + 6 / globalScale;
                            const textWidth = ctx.measureText(label).width;

                            ctx.fillStyle = "rgba(7, 11, 20, 0.85)";
                            ctx.fillRect(
                              node.x - textWidth / 2 - 3 / globalScale,
                              node.y + yOffset - fontSize / 2 - 1 / globalScale,
                              textWidth + 6 / globalScale,
                              fontSize + 3 / globalScale
                            );

                            ctx.textAlign = "center";
                            ctx.textBaseline = "middle";
                            ctx.fillStyle = "#f1f5f9";
                            ctx.fillText(label, node.x, node.y + yOffset);
                          }}
                          linkColor={(link: any) => link.color || "#22d3ee"}
                          linkWidth={2.5}
                          linkDirectionalParticles={4}
                          linkDirectionalParticleSpeed={0.007}
                          linkDirectionalParticleWidth={3}
                          linkDirectionalParticleColor={() => "#ffffff"}
                          backgroundColor="#070b14"
                          onNodeClick={(node: any) => {
                            setSelectedNode(node);
                            if (node.url && node.url.startsWith("http")) {
                              window.open(node.url, "_blank");
                            }
                          }}
                        />

                        {/* Reset Zoom Button */}
                        <button
                          type="button"
                          onClick={() => graphRef.current?.zoomToFit(400, 30)}
                          className="absolute bottom-3 right-3 p-2 rounded-lg bg-slate-900/80 hover:bg-slate-800 text-slate-300 border border-slate-700 text-xs flex items-center space-x-1"
                          title="Reset Graph Zoom"
                        >
                          <Maximize2 className="w-3.5 h-3.5" />
                          <span>Center</span>
                        </button>
                      </div>
                    </div>

                    {/* Selected Node Details Bar */}
                    {selectedNode && (
                      <div className="p-3 rounded-lg bg-slate-900 border border-slate-800 text-xs space-y-1 animate-fadeIn">
                        <div className="flex items-center justify-between">
                          <span className="font-semibold text-cyan-400">{selectedNode.name}</span>
                          {selectedNode.url && (
                            <a
                              href={selectedNode.url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-cyan-400 hover:underline flex items-center space-x-1"
                            >
                              <span>Open URL</span>
                              <ExternalLink className="w-3 h-3" />
                            </a>
                          )}
                        </div>
                        <p className="text-slate-300 text-[11px] leading-relaxed">
                          {selectedNode.detail || selectedNode.label}
                        </p>
                      </div>
                    )}
                  </div>
                )}

                {/* Tab 2: Red Team vs Blue Team Debate */}
                {activeTab === "debate" && (
                  <div className="space-y-4">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      {/* Red Team Debunker */}
                      <div className="p-4 rounded-xl bg-rose-950/20 border border-rose-800/40 space-y-2">
                        <div className="flex items-center space-x-2 text-rose-400 font-semibold text-xs uppercase tracking-wider">
                          <ShieldAlert className="w-4 h-4" />
                          <span>Red Team (The Prosecutor)</span>
                        </div>
                        <p className="text-xs text-rose-200/90 leading-relaxed italic">
                          "{currentResult.red_team_argument}"
                        </p>
                      </div>

                      {/* Blue Team Advocate */}
                      <div className="p-4 rounded-xl bg-blue-950/20 border border-blue-800/40 space-y-2">
                        <div className="flex items-center space-x-2 text-blue-400 font-semibold text-xs uppercase tracking-wider">
                          <ShieldCheck className="w-4 h-4" />
                          <span>Blue Team (The Defender)</span>
                        </div>
                        <p className="text-xs text-blue-200/90 leading-relaxed italic">
                          "{currentResult.blue_team_argument}"
                        </p>
                      </div>
                    </div>
                  </div>
                )}

                {/* Tab 3: Live Source Citations */}
                {activeTab === "sources" && (
                  <div className="space-y-2">
                    {currentResult.matched_sources.length > 0 ? (
                      <div className="space-y-2">
                        {currentResult.matched_sources.map((sourceUrl, idx) => (
                          <a
                            key={idx}
                            href={sourceUrl.startsWith("http") ? sourceUrl : `#`}
                            target={sourceUrl.startsWith("http") ? "_blank" : undefined}
                            rel="noreferrer"
                            className="flex items-center justify-between p-3 rounded-lg bg-slate-900 hover:bg-slate-800/80 border border-slate-800 text-xs text-cyan-300 transition group"
                          >
                            <span className="truncate max-w-[85%]">{sourceUrl}</span>
                            <ExternalLink className="w-3.5 h-3.5 text-slate-500 group-hover:text-cyan-400 transition" />
                          </a>
                        ))}
                      </div>
                    ) : (
                      <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800/80 text-xs text-slate-500 italic">
                        No direct matching documents found in ChromaDB verified facts collection. Evaluated via multi-agent reasoning and heuristic synthetic signal analysis.
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Right Column: Live Feed & Query Stream (5 cols) */}
          <div className="lg:col-span-5 space-y-6">
            <div className="rounded-2xl bg-[#0c1222] border border-slate-800 p-6 shadow-xl space-y-4">
              <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                <div className="flex items-center space-x-2">
                  <Activity className="w-4 h-4 text-cyan-400" />
                  <h3 className="font-semibold text-sm text-white">Live Audit Stream</h3>
                </div>
                <span className="text-[10px] text-slate-500 font-mono">
                  {auditHistory.length} query recorded
                </span>
              </div>

              {auditHistory.length === 0 ? (
                <div className="text-center py-12 text-slate-500 text-xs space-y-2">
                  <Search className="w-8 h-8 mx-auto text-slate-600 stroke-[1.5]" />
                  <p>No audits run in this session yet.</p>
                  <p className="text-[11px] text-slate-600">
                    Submit a viral claim on the left or click a demo scenario to begin.
                  </p>
                </div>
              ) : (
                <div className="space-y-3 max-h-[640px] overflow-y-auto pr-1">
                  {auditHistory.map((item, idx) => {
                    const style = getVerdictStyle(item.verdict);
                    return (
                      <div
                        key={idx}
                        onClick={() => {
                          setCurrentResult(item);
                          setSelectedNode(null);
                        }}
                        className="p-3.5 rounded-xl bg-slate-900/60 hover:bg-slate-900 border border-slate-800/90 cursor-pointer transition space-y-2 group"
                      >
                        <div className="flex items-center justify-between text-[11px]">
                          <span
                            className={`px-2 py-0.5 rounded-md font-semibold text-[10px] ${style.badge}`}
                          >
                            {item.verdict}
                          </span>
                          <span className="text-slate-500 flex items-center space-x-1">
                            <Clock className="w-3 h-3" />
                            <span>{item.timestamp}</span>
                          </span>
                        </div>

                        <p className="text-xs text-slate-200 line-clamp-2 font-medium">
                          "{item.claim_text}"
                        </p>

                        <div className="flex items-center justify-between text-[10px] text-slate-500 pt-1 border-t border-slate-800/60">
                          <span>Confidence: {Math.round(item.confidence_score)}%</span>
                          <span>Lang: {item.detected_language}</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Architecture Card */}
            <div className="p-4 rounded-xl bg-slate-900/40 border border-slate-800/80 text-xs text-slate-400 space-y-2.5">
              <div className="font-semibold text-slate-300 flex items-center space-x-1.5">
                <Scale className="w-3.5 h-3.5 text-cyan-400" />
                <span>Rubric Highlights: Agentic Execution & Live Data</span>
              </div>
              <p className="text-[11px] leading-relaxed text-slate-400">
                1. <strong>Live Tools</strong>: Queries Google Fact Check Tools API live and checks WHOIS domain age for scam URLs.<br />
                2. <strong>Dynamic Vector Cache</strong>: Live facts are asynchronously embedded and cached into ChromaDB so the database grows organically.<br />
                3. <strong>Parallel Debate</strong>: Red Team Prosecutor vs. Blue Team Defender run concurrently via <code className="text-cyan-300">asyncio.gather</code>.<br />
                4. <strong>Atomic Claim Decomposition</strong>: Deconstructs claims into verifiable sub-facts with individual highlight badges.<br />
                5. <strong>Multilingual Engine</strong>: Identifies Hindi/Hinglish/English input and explains verdicts in the native language.
              </p>
            </div>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-800/60 bg-[#090f1d] py-4 text-center text-xs text-slate-500">
        DigitalScam • Forge Gen AI Buildathon • Dynamic ReAct Multi-Agent Platform
      </footer>
    </div>
  );
}
