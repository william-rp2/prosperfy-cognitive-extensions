#!/usr/bin/env python3
from __future__ import annotations
import json, os, subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST=os.getenv("BROWSER_WORKER_HTTP_HOST","100.77.177.13")
PORT=int(os.getenv("BROWSER_WORKER_HTTP_PORT","9122"))
TOKEN=os.getenv("BROWSER_WORKER_HTTP_TOKEN","")
WORKER="/opt/browser-worker/worker.py"
MAX_BODY=512*1024

class Handler(BaseHTTPRequestHandler):
    server_version="ProsperfyBrowserWorker/1.0"
    def log_message(self, fmt, *args):
        return
    def _json(self,status,obj):
        raw=json.dumps(obj,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
    def _auth(self):
        return bool(TOKEN) and self.headers.get("Authorization","")==f"Bearer {TOKEN}"
    def do_GET(self):
        if self.path=="/health":
            self._json(200,{"status":"ok","service":"prosperfy-browser-worker"})
        else:
            self._json(404,{"status":"not_found"})
    def do_POST(self):
        if self.path!="/run":
            self._json(404,{"status":"not_found"}); return
        if not self._auth():
            self._json(401,{"status":"unauthorized"}); return
        try:
            n=int(self.headers.get("Content-Length","0"))
        except Exception:
            n=0
        if n<=0 or n>MAX_BODY:
            self._json(413,{"status":"invalid_size"}); return
        raw=self.rfile.read(n)
        try:
            job=json.loads(raw)
        except Exception:
            self._json(400,{"status":"invalid_json"}); return
        if not isinstance(job,dict) or not job.get("job_id") or not job.get("action"):
            self._json(422,{"status":"invalid_job"}); return
        env=dict(os.environ)
        env["PATH"]="/root/.local/bin:"+env.get("PATH","")
        env["BU_CDP_URL"]="http://127.0.0.1:9222"
        try:
            proc=subprocess.run(
                ["python3",WORKER],
                input=json.dumps(job,ensure_ascii=False)+"\n",
                text=True,
                capture_output=True,
                timeout=150,
                env=env,
            )
        except subprocess.TimeoutExpired:
            self._json(504,{"status":"timeout"}); return
        lines=[x for x in (proc.stdout or "").splitlines() if x.strip()]
        if not lines:
            self._json(502,{"status":"worker_no_output"}); return
        try:
            result=json.loads(lines[-1])
        except Exception:
            self._json(502,{"status":"worker_invalid_output"}); return
        # Worker already redacts secrets; return only its structured result.
        self._json(200,result)

if not TOKEN:
    raise SystemExit("BROWSER_WORKER_HTTP_TOKEN missing")
ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
