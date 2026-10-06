import React, { useState, useEffect } from "react";
import {
  Database,
  FileSpreadsheet,
  ShieldAlert,
  Send,
  Upload,
  CheckCircle2,
  XCircle,
  Terminal,
  Clock,
  RefreshCw,
  Settings,
  Sparkles,
} from "lucide-react";

const PRESETS = [
  {
    category: "SQL Analytics",
    label: "Top 3 Cities by Revenue",
    question: "Which 3 cities have the highest completed-payment revenue?",
  },
  {
    category: "SQL Self-Healing",
    label: "Avg Rating by Vehicle Make (CTE)",
    question: "What is the average rating for each vehicle make?",
  },
  {
    category: "SQL Analytics",
    label: "Top 3 Highest-Spending Users",
    question: "Which 3 users have spent the highest total amount on completed rides?",
  },
  {
    category: "ETL Extract",
    label: "Extract PokeAPI to CSV",
    question: "Extract data from https://pokeapi.co/api/v2/pokemon and save it as csv in the extract folder",
  },
  {
    category: "ETL Transform",
    label: "Transform CSV (First 5 Rows)",
    question: "Transform extract/extracted_data.csv and keep only the first 5 rows, save as csv",
  },
  {
    category: "Security Guardrail",
    label: "Block Destructive SQL (DELETE)",
    question: "Delete all rows from the payments table",
  },
  {
    category: "Security Guardrail",
    label: "Block SSRF (localhost)",
    question: "Extract data from http://localhost:11434/api/tags and save it as csv",
  },
  {
    category: "Security Guardrail",
    label: "Block Path Traversal (../../)",
    question: "Extract data from https://pokeapi.co/api/v2/pokemon and save it as csv in the folder ../../outside",
  },
];

export default function App() {
  const [apiUrl, setApiUrl] = useState(
    import.meta.env.VITE_API_URL || "http://localhost:8000"
  );
  const [apiKey, setApiKey] = useState(import.meta.env.VITE_API_KEY || "");
  const [sessionId, setSessionId] = useState(
    () => "sess-" + Math.random().toString(36).substring(2, 10)
  );
  const [showConfig, setShowConfig] = useState(false);

  const [health, setHealth] = useState({ status: "checking", components: null });
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [history, setHistory] = useState([]);

  const [uploading, setUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState(null);

  const buildHeaders = (isJson = true) => {
    const h = {};
    if (isJson) h["Content-Type"] = "application/json";
    if (apiKey.trim()) h["X-API-Key"] = apiKey.trim();
    return h;
  };

  const checkBackendStatus = async () => {
    setHealth({ status: "checking", components: null });
    try {
      const base = apiUrl.replace(/\/+$/, "");
      const resReady = await fetch(`${base}/ready`);
      if (resReady.ok || resReady.status === 503) {
        const data = await resReady.json();
        setHealth({
          status: data.ready ? "ready" : "degraded",
          components: data.components || null,
        });
        return;
      }
      const resHealth = await fetch(`${base}/health`);
      if (resHealth.ok) {
        setHealth({ status: "healthy", components: null });
      } else {
        setHealth({ status: "offline", components: null });
      }
    } catch {
      setHealth({ status: "offline", components: null });
    }
  };

  useEffect(() => {
    checkBackendStatus();
  }, [apiUrl]);

  const sendQuery = async (customQuestion) => {
    const q = (customQuestion ?? question).trim();
    if (!q || loading) return;

    setLoading(true);
    if (!customQuestion) setQuestion("");

    const userEntry = {
      id: Date.now(),
      question: q,
      pending: true,
    };
    setHistory((prev) => [userEntry, ...prev]);

    try {
      const base = apiUrl.replace(/\/+$/, "");
      const res = await fetch(`${base}/api/v1/query`, {
        method: "POST",
        headers: buildHeaders(true),
        body: JSON.stringify({ question: q, session_id: sessionId }),
      });

      const data = await res.json();
      if (!res.ok) {
        const errMsg =
          data?.error?.message || data?.detail || `HTTP ${res.status}`;
        setHistory((prev) =>
          prev.map((item) =>
            item.id === userEntry.id
              ? {
                  ...item,
                  pending: false,
                  success: false,
                  answer: `Request failed: ${errMsg}`,
                  agent_type: "error",
                  error: errMsg,
                }
              : item
          )
        );
      } else {
        setHistory((prev) =>
          prev.map((item) =>
            item.id === userEntry.id
              ? {
                  ...item,
                  pending: false,
                  ...data,
                }
              : item
          )
        );
      }
    } catch (err) {
      setHistory((prev) =>
        prev.map((item) =>
          item.id === userEntry.id
            ? {
                ...item,
                pending: false,
                success: false,
                answer: `Cannot reach backend at ${apiUrl}. Check CORS or backend URL.`,
                agent_type: "network_error",
                error: err.message,
              }
            : item
        )
      );
    } finally {
      setLoading(false);
    }
  };

  const handleFileUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    setUploadStatus(null);
    const formData = new FormData();
    formData.append("file", file);

    try {
      const base = apiUrl.replace(/\/+$/, "");
      const res = await fetch(`${base}/api/v1/upload`, {
        method: "POST",
        headers: buildHeaders(false),
        body: formData,
      });
      const data = await res.json();
      if (res.ok && data.success) {
        setUploadStatus({
          ok: true,
          text: `Uploaded ${data.filename} (${data.rows ?? 0} rows, cols: ${(
            data.columns || []
          ).join(", ")})`,
          filename: data.filename,
        });
      } else {
        setUploadStatus({
          ok: false,
          text: data?.error?.message || data?.detail || "Upload failed",
        });
      }
    } catch (err) {
      setUploadStatus({ ok: false, text: `Upload error: ${err.message}` });
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      {/* Top Navbar */}
      <header className="border-b border-slate-800 bg-slate-900/70 backdrop-blur sticky top-0 z-20">
        <div className="max-w-7xl mx-auto px-4 py-3 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-indigo-600/20 border border-indigo-500/40 text-indigo-400">
              <Database className="w-6 h-6" />
            </div>
            <div>
              <h1 className="text-lg font-bold tracking-tight flex items-center gap-2">
                Agentic AI Data Agent
                <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 border border-slate-700">
                  v2.1.0
                </span>
              </h1>
              <p className="text-xs text-slate-400">
                LangGraph SQL Analyst (Read-Only) & Sandboxed Pandas ETL
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {/* Status Badge */}
            <button
              onClick={checkBackendStatus}
              title="Click to refresh backend status"
              className="flex items-center gap-2 text-xs px-3 py-1.5 rounded-full border border-slate-800 bg-slate-900 hover:bg-slate-800 transition"
            >
              <span
                className={`w-2 h-2 rounded-full ${
                  health.status === "ready" || health.status === "healthy"
                    ? "bg-emerald-400"
                    : health.status === "degraded"
                    ? "bg-amber-400"
                    : health.status === "checking"
                    ? "bg-sky-400 animate-pulse"
                    : "bg-rose-500"
                }`}
              />
              <span className="capitalize">{health.status}</span>
              <RefreshCw className="w-3.5 h-3.5 text-slate-400" />
            </button>

            <button
              onClick={() => setShowConfig(!showConfig)}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-800 hover:bg-slate-700 transition"
            >
              <Settings className="w-3.5 h-3.5" />
              API Config
            </button>
          </div>
        </div>

        {/* Collapsible API Configuration Bar */}
        {showConfig && (
          <div className="border-t border-slate-800 bg-slate-900 px-4 py-3">
            <div className="max-w-7xl mx-auto grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
              <div>
                <label className="block text-slate-400 mb-1">
                  FastAPI Backend URL (VITE_API_URL)
                </label>
                <input
                  type="text"
                  value={apiUrl}
                  onChange={(e) => setApiUrl(e.target.value)}
                  placeholder="https://your-backend.onrender.com"
                  className="w-full px-3 py-1.5 rounded bg-slate-950 border border-slate-700 text-slate-100"
                />
              </div>
              <div>
                <label className="block text-slate-400 mb-1">
                  X-API-Key (Optional in dev, required in prod)
                </label>
                <input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="Enter API_KEY if enabled..."
                  className="w-full px-3 py-1.5 rounded bg-slate-950 border border-slate-700 text-slate-100"
                />
              </div>
              <div>
                <label className="block text-slate-400 mb-1">Session ID</label>
                <input
                  type="text"
                  value={sessionId}
                  onChange={(e) => setSessionId(e.target.value)}
                  className="w-full px-3 py-1.5 rounded bg-slate-950 border border-slate-700 text-slate-100"
                />
              </div>
            </div>
          </div>
        )}
      </header>

      {/* Main Layout */}
      <main className="max-w-7xl w-full mx-auto px-4 py-6 grid grid-cols-1 lg:grid-cols-12 gap-6 flex-1">
        {/* Left Sidebar: Presets & File Upload */}
        <aside className="lg:col-span-4 space-y-6">
          {/* File Upload Card */}
          <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/60 space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold flex items-center gap-2">
                <Upload className="w-4 h-4 text-indigo-400" />
                Upload Dataset for ETL
              </h2>
              <span className="text-[11px] text-slate-400">
                .csv, .json, .parquet, .xlsx
              </span>
            </div>
            <label className="flex flex-col items-center justify-center border-2 border-dashed border-slate-700 hover:border-indigo-500 rounded-lg p-4 cursor-pointer transition bg-slate-950/50">
              <span className="text-xs text-slate-300 font-medium">
                {uploading ? "Uploading..." : "Click to select a file"}
              </span>
              <span className="text-[11px] text-slate-500 mt-0.5">
                Max 50MB • Saved to data/uploads/
              </span>
              <input
                type="file"
                accept=".csv,.json,.parquet,.xlsx"
                onChange={handleFileUpload}
                disabled={uploading}
                className="hidden"
              />
            </label>
            {uploadStatus && (
              <div
                className={`text-xs p-2.5 rounded-lg border ${
                  uploadStatus.ok
                    ? "bg-emerald-950/40 border-emerald-700/60 text-emerald-300"
                    : "bg-rose-950/40 border-rose-700/60 text-rose-300"
                }`}
              >
                {uploadStatus.text}
              </div>
            )}
          </div>

          {/* One-Click Verification Presets */}
          <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/60 space-y-3">
            <h2 className="text-sm font-semibold flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-indigo-400" />
              1-Click Verification Queries
            </h2>
            <div className="space-y-2">
              {PRESETS.map((preset, idx) => (
                <button
                  key={idx}
                  disabled={loading}
                  onClick={() => sendQuery(preset.question)}
                  className="w-full text-left p-2.5 rounded-lg border border-slate-800 bg-slate-950 hover:border-indigo-500/60 hover:bg-slate-900 transition group disabled:opacity-50"
                >
                  <div className="flex items-center justify-between text-[11px] text-slate-400 mb-0.5">
                    <span className="font-medium text-indigo-400">
                      {preset.category}
                    </span>
                    <span className="group-hover:translate-x-0.5 transition">
                      Run →
                    </span>
                  </div>
                  <div className="text-xs font-medium text-slate-200">
                    {preset.label}
                  </div>
                  <div className="text-[11px] text-slate-400 truncate mt-0.5">
                    {preset.question}
                  </div>
                </button>
              ))}
            </div>
          </div>
        </aside>

        {/* Right Panel: Query Input & Results Stream */}
        <section className="lg:col-span-8 flex flex-col gap-4">
          {/* Prompt Box */}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              sendQuery();
            }}
            className="p-4 rounded-xl border border-slate-800 bg-slate-900/60 space-y-3"
          >
            <label className="block text-xs font-medium text-slate-300">
              Ask a SQL question or trigger an ETL job
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="e.g., Which 5 drivers have earned the most total revenue from completed rides?"
                disabled={loading}
                className="flex-1 px-4 py-2.5 rounded-lg bg-slate-950 border border-slate-700 text-sm text-slate-100 focus:outline-none focus:border-indigo-500"
              />
              <button
                type="submit"
                disabled={loading || !question.trim()}
                className="px-5 py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-sm font-semibold flex items-center gap-2 transition"
              >
                <Send className="w-4 h-4" />
                {loading ? "Running..." : "Ask Agent"}
              </button>
            </div>
          </form>

          {/* Output Feed */}
          <div className="space-y-4 flex-1">
            {history.length === 0 ? (
              <div className="h-72 rounded-xl border border-dashed border-slate-800 flex flex-col items-center justify-center text-center p-6 text-slate-400">
                <Terminal className="w-10 h-10 text-slate-600 mb-2" />
                <p className="text-sm font-medium text-slate-300">
                  No queries executed yet
                </p>
                <p className="text-xs text-slate-500 max-w-md mt-1">
                  Select any preset on the left or type a natural-language SQL or
                  ETL request above to inspect the generated SQL, execution time,
                  and guardrail status.
                </p>
              </div>
            ) : (
              history.map((item) => (
                <div
                  key={item.id}
                  className="p-4 rounded-xl border border-slate-800 bg-slate-900/70 space-y-3"
                >
                  {/* Question Header */}
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-2.5">
                    <p className="text-sm font-semibold text-white">
                      Q: {item.question}
                    </p>
                    {item.pending ? (
                      <span className="text-xs px-2.5 py-0.5 rounded-full bg-indigo-950 text-indigo-300 border border-indigo-700 animate-pulse">
                        Agent thinking...
                      </span>
                    ) : (
                      <div className="flex items-center gap-2 text-xs">
                        {/* Route Badge */}
                        <span className="px-2.5 py-0.5 rounded-full uppercase font-semibold bg-slate-800 text-slate-200 border border-slate-700 flex items-center gap-1">
                          {item.agent_type === "etl" ? (
                            <FileSpreadsheet className="w-3 h-3 text-amber-400" />
                          ) : (
                            <Database className="w-3 h-3 text-indigo-400" />
                          )}
                          {item.agent_type || "unknown"}
                        </span>

                        {/* Success / Guardrail Badge */}
                        {item.success ? (
                          <span className="px-2.5 py-0.5 rounded-full bg-emerald-950/80 text-emerald-300 border border-emerald-700/60 flex items-center gap-1">
                            <CheckCircle2 className="w-3.5 h-3.5" />
                            Success
                          </span>
                        ) : (
                          <span className="px-2.5 py-0.5 rounded-full bg-rose-950/80 text-rose-300 border border-rose-700/60 flex items-center gap-1">
                            <ShieldAlert className="w-3.5 h-3.5" />
                            Blocked / Error
                          </span>
                        )}

                        {/* Execution Time */}
                        {item.execution_time_ms != null && (
                          <span className="text-slate-400 flex items-center gap-1">
                            <Clock className="w-3 h-3" />
                            {(item.execution_time_ms / 1000).toFixed(2)}s
                          </span>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Answer Body */}
                  {!item.pending && (
                    <>
                      <div className="text-sm text-slate-200 whitespace-pre-wrap leading-relaxed">
                        {item.answer}
                      </div>

                      {/* Generated SQL Block */}
                      {item.sql && (
                        <div className="rounded-lg bg-slate-950 border border-slate-800 p-3">
                          <div className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold mb-1">
                            Generated Read-Only PostgreSQL Query
                          </div>
                          <pre className="text-xs text-emerald-300 font-mono overflow-x-auto whitespace-pre-wrap">
                            {item.sql}
                          </pre>
                        </div>
                      )}

                      {/* Error / Security Guardrail Detail */}
                      {item.error && (
                        <div className="text-xs text-rose-300 bg-rose-950/40 border border-rose-800/60 rounded-lg px-3 py-2 flex items-center gap-2">
                          <XCircle className="w-4 h-4 shrink-0" />
                          <span>
                            <strong>Guardrail / Error:</strong> {item.error}
                          </span>
                        </div>
                      )}
                    </>
                  )}
                </div>
              ))
            )}
          </div>
        </section>
      </main>
    </div>
  );
}
