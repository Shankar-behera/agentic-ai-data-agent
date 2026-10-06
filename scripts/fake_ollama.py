"""Fake Ollama for demos and smoke tests: /api/tags + /api/chat with canned replies.

Usage: python scripts/fake_ollama.py [delay_seconds]   (listens on 127.0.0.1:11434)
"""
import json, re, sys, time, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DELAY = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0
CALLS = []

def reply_for(text: str) -> str:
    CALLS.append(text[:60])
    if "Classify the request" in text:
        q = text.split("Request:")[-1].split("\n")[0].lower()
        return json.dumps({"answer": "etl" if "extract" in q else "sql", "comments": "mock"})
    if "Rewrite the question below" in text:
        m = re.search(r"Original: (.*)", text); return m.group(1) if m else "q"
    if "Write ONE PostgreSQL query" in text:
        q = text.split("answers this question:")[-1].split("Rules:")[0].lower()
        if "dropme" in q: return "DROP TABLE users;"
        if "badcol" in q and "Your previous query failed" not in text: return "SELECT nonexistent_col FROM rides"
        if "revenue" in q or "badcol" in q: return "SELECT u.city, ROUND(SUM(p.amount),2) AS revenue FROM payments p JOIN users u ON u.user_id=p.user_id WHERE p.payment_status='completed' GROUP BY u.city ORDER BY revenue DESC LIMIT 3"
        return "SELECT COUNT(*) AS n FROM rides"
    if "Result of the SQL query" in text:
        return "MOCK ANSWER based on: " + text.split("first row is the column names):")[-1].split("Answer the question")[0].strip()[:120].replace("\n"," / ")
    return "ok"

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path == "/calls":
            body = json.dumps(CALLS).encode()
        else:
            body = json.dumps({"models": [{"name": "phi3:mini"}, {"name": "mistral:latest"}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); req = json.loads(self.rfile.read(n) or b"{}")
        if DELAY: time.sleep(DELAY)
        msgs = req.get("messages", []); text = "\n".join(m.get("content", "") for m in msgs)
        out = reply_for(text)
        body = (json.dumps({"model": req.get("model", "m"), "created_at": "2026-01-01T00:00:00Z",
                 "message": {"role": "assistant", "content": out}, "done": True, "done_reason": "stop"}) + "\n").encode()
        self.send_response(200); self.send_header("Content-Type", "application/x-ndjson"); self.end_headers(); self.wfile.write(body)

ThreadingHTTPServer(("127.0.0.1", 11434), H).serve_forever()
