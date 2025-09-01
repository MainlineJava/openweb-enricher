from flask import (
    Flask, request, render_template_string, send_file, redirect, url_for,
    Response, stream_with_context
)
import os
import pandas as pd
import tempfile
import io
import threading
import time
import uuid
from datetime import datetime
from contextlib import redirect_stdout
from collections import deque
import sys

from openweb_enricher.main import run_enrich_on_df

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB uploads

# In-memory stores (simple)
_jobs = {}  # job_id -> {"status": "running|done|error", "started": ts, "finished": ts or None}
_logs = {}  # job_id -> deque of log-chunks
_results = {}  # job_id -> result dict returned by run_enrich_on_df
_history = deque(maxlen=50)  # recent job summaries

# Templates (simple, centered, responsive)
BASE_CSS = """
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial; background:#f6f8fa; color:#111; }
  .wrap { max-width:1000px; margin:40px auto; background:white; padding:24px; border-radius:8px; box-shadow:0 6px 20px rgba(0,0,0,0.06); }
  h1 { margin-top:0; font-size:1.4rem; }
  .center { text-align:center; }
  .upload { display:flex; gap:8px; justify-content:center; align-items:center; margin:18px 0; }
  .btn { background:#0b6cff; color:white; padding:8px 12px; border-radius:6px; text-decoration:none; border:none; cursor:pointer; }
  .btn.secondary { background:#e6eefc; color:#0b6cff; }
  pre.log { background:#0f1720; color:#d6f0ff; padding:12px; border-radius:6px; height:280px; overflow:auto; white-space:pre-wrap; }
  table { width:100%; border-collapse:collapse; margin-top:12px; }
  th, td { border:1px solid #eee; padding:6px 8px; font-size:0.9rem; }
  .meta { display:flex; justify-content:space-between; gap:12px; align-items:center; flex-wrap:wrap; }
  .history { margin-top:18px; }
  a.link { color:#0b6cff; text-decoration:none; }
  .small { font-size:0.9rem; color:#555; }
</style>
"""

INDEX_HTML = BASE_CSS + """
<div class="wrap center">
  <h1>OpenWeb Enricher — Upload & Run</h1>
  <p class="small">Upload an Excel (.xlsx) with Owner columns. The job will run and show live logs below.</p>

  <form action="/upload" method="post" enctype="multipart/form-data" class="upload">
    <input type="file" name="file" accept=".xlsx" required>
    <!-- added scrape checkbox so users can enable page scraping -->
    <label style="display:flex;align-items:center;gap:8px;margin-left:8px">
      <input type="checkbox" name="scrape" checked> Fetch & scrape result pages
    </label>
    <button class="btn" type="submit">Upload & Run</button>
  </form>

  <div class="history">
    <h3>Recent runs</h3>
    {% if history %}
      <table>
        <tr><th>Job ID</th><th>Started</th><th>Status</th><th>Records</th><th>Found</th><th>Actions</th></tr>
        {% for h in history %}
          <tr>
            <td style="font-family:monospace">{{h.job_id}}</td>
            <td>{{h.started}}</td>
            <td>{{h.status}}</td>
            <td>{{h.total_records}}</td>
            <td>{{h.total_emails_found}}</td>
            <td>
              <a class="link" href="/view/{{h.job_id}}">View</a> |
              <a class="link" href="/download/{{h.job_id}}/xlsx">XLSX</a>
            </td>
          </tr>
        {% endfor %}
      </table>
    {% else %}
      <p class="small">No runs yet.</p>
    {% endif %}
  </div>
</div>
"""

VIEW_HTML = BASE_CSS + """
<div class="wrap">
  <div class="meta">
    <div>
      <h1>Job {{job_id}}</h1>
      <div class="small">Started: {{started}} &nbsp; | &nbsp; Status: {{status}}</div>
    </div>
    <div>
      <a class="btn" href="/">← Back</a>
      {% if finished %}
        <a class="btn secondary" href="/download/{{job_id}}/xlsx">Download XLSX</a>
        <a class="btn secondary" href="/download/{{job_id}}/csv">Download CSV</a>
      {% endif %}
    </div>
  </div>

  <h3>Live output</h3>
  <pre id="log" class="log">Connecting to job log...</pre>

  <h3>Results</h3>
  {% if rows %}
    <p class="small">Processed {{meta.total_records}} records, found {{meta.total_emails_found}} emails.</p>
    <table>
      <tr><th>input_id</th><th>name</th><th>email</th><th>confidence</th><th>source</th><th>snippet</th></tr>
      {% for r in rows %}
        <tr>
          <td>{{r.input_id}}</td><td>{{r.name}}</td><td>{{r.email}}</td><td>{{r.confidence}}</td>
          <td><a href="{{r.source}}" target="_blank">{{r.source}}</a></td><td>{{r.snippet[:120]}}</td>
        </tr>
      {% endfor %}
    </table>
  {% else %}
    <p class="small">No results yet (job may still be running).</p>
  {% endif %}
</div>

<script>
(function() {
  const logEl = document.getElementById('log');
  const evtSource = new EventSource('/stream/{{job_id}}');
  evtSource.onmessage = function(e) {
    if (e.data === '__KEEPALIVE__') return;
    if (e.data === '__COMPLETE__') {
      evtSource.close();
      // auto-reload to show fresh results saved on the server
      window.location.reload();
      return;
    }
    // append line
    logEl.textContent += e.data + "\\n";
    logEl.scrollTop = logEl.scrollHeight;
  };
  evtSource.onerror = function() {
    // leave the connection to retry automatically
  };
})();
</script>
"""

# Utilities
def _new_job():
    job_id = uuid.uuid4().hex[:12]
    _jobs[job_id] = {"status": "running", "started": datetime.utcnow().isoformat(), "finished": None}
    _logs[job_id] = deque()
    return job_id

def _append_log(job_id, text):
    # split text into reasonable chunks
    if not text:
        return
    for part in text.splitlines():
        _logs[job_id].append(part)

def _finish_job(job_id, result):
    _jobs[job_id]["status"] = "done"
    _jobs[job_id]["finished"] = datetime.utcnow().isoformat()
    _results[job_id] = result
    # record history entry
    summary = {
        "job_id": job_id,
        "started": _jobs[job_id]["started"],
        "finished": _jobs[job_id]["finished"],
        "status": "done",
        "total_records": result.get("total_records", 0),
        "total_emails_found": result.get("total_emails_found", 0)
    }
    _history.appendleft(summary)

def _error_job(job_id, err_text):
    _jobs[job_id]["status"] = "error"
    _jobs[job_id]["finished"] = datetime.utcnow().isoformat()
    _append_log(job_id, f"ERROR: {err_text}")
    summary = {
        "job_id": job_id,
        "started": _jobs[job_id]["started"],
        "finished": _jobs[job_id]["finished"],
        "status": "error",
        "total_records": 0,
        "total_emails_found": 0
    }
    _history.appendleft(summary)

# Worker runner that captures stdout and streams it into _logs
def _run_job_thread(job_id, df, scrape_flag, job_dir):
    """Run enrichment while streaming stdout into _logs and persisting job files."""
    import sys, json, traceback
    class StreamToLogs:
        def __init__(self, job_id):
            self.job_id = job_id
            self._buf = ""
        def write(self, s):
            if not s:
                return
            self._buf += s
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                _append_log(self.job_id, line)
        def flush(self):
            if self._buf:
                _append_log(self.job_id, self._buf)
                self._buf = ""

    os.makedirs(job_dir, exist_ok=True)
    orig_stdout = sys.stdout
    writer = StreamToLogs(job_id)
    sys.stdout = writer

    try:
        # run the enrichment (prints go to writer -> _append_log)
        result = run_enrich_on_df(df, scrape_pages=scrape_flag)
        writer.flush()

        # persist result JSON
        with open(os.path.join(job_dir, "result.json"), "w") as fjson:
            json.dump(result, fjson, indent=2)

        # persist outputs
        df_out = pd.DataFrame(result.get("rows", []))
        xlsx_path = os.path.join(job_dir, f"results_{job_id}.xlsx")
        csv_path = os.path.join(job_dir, f"results_{job_id}.csv")
        try:
            df_out.to_excel(xlsx_path, index=False)
        except Exception:
            pass
        df_out.to_csv(csv_path, index=False)

        # persist logs: drain current in-memory lines to file
        log_path = os.path.join(job_dir, "run.log")
        with open(log_path, "w") as flog:
            while _logs[job_id]:
                flog.write(_logs[job_id].popleft() + "\n")

        _finish_job(job_id, result)

    except Exception as e:
        tb = traceback.format_exc()
        _append_log(job_id, tb)
        err_path = os.path.join(job_dir, "error.log")
        with open(err_path, "w") as ferr:
            ferr.write(tb)
        _error_job(job_id, str(e))
    finally:
        sys.stdout = orig_stdout

@app.route("/", methods=["GET"])
def index():
    # prepare a history list for the template
    return render_template_string(INDEX_HTML, history=list(_history))

@app.route("/upload", methods=["POST"])
def upload():
    f = request.files.get("file")
    if not f:
        return "No file uploaded", 400
    scrape_flag = request.form.get("scrape") == "on"
    # save to a temp file and read with pandas
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp_path = tmp.name
        f.save(tmp_path)
    try:
        df = pd.read_excel(tmp_path)
    except Exception as e:
        os.unlink(tmp_path)
        return f"Failed to read uploaded file: {e}", 400
    os.unlink(tmp_path)

    job_id = _new_job()
    job_dir = os.path.join("data", "jobs", job_id)
    os.makedirs(job_dir, exist_ok=True)

    thread = threading.Thread(target=_run_job_thread, args=(job_id, df, scrape_flag, job_dir), daemon=True)
    thread.start()
    return redirect(url_for('view', job_id=job_id))

@app.route("/view/<job_id>", methods=["GET"])
def view(job_id):
    meta = _jobs.get(job_id)
    rows = _results.get(job_id, {}).get("rows") if _results.get(job_id) else None
    return render_template_string(
        VIEW_HTML,
        job_id=job_id,
        started=meta.get("started") if meta else "n/a",
        finished=meta.get("finished") if meta else None,
        status=meta.get("status") if meta else "unknown",
        meta=_results.get(job_id, {"total_records": 0, "total_emails_found": 0}),
        rows=rows
    )

@app.route("/stream/<job_id>")
def stream(job_id):
    if job_id not in _jobs:
        return "Unknown job", 404

    def gen():
        # Stream log lines as server-sent events
        # Keep sending keepalive to prevent connection close
        sent = 0
        while True:
            # send any pending log lines
            while _logs[job_id]:
                line = _logs[job_id].popleft()
                # escape newlines; SSE expects one event per message
                yield f"data: {line}\n\n"
                sent += 1
            status = _jobs[job_id]["status"]
            if status in ("done", "error") and not _logs[job_id]:
                # final marker
                yield "data: __COMPLETE__\n\n"
                break
            # keepalive
            yield "data: __KEEPALIVE__\n\n"
            time.sleep(0.8)

    return Response(stream_with_context(gen()), mimetype="text/event-stream")

@app.route("/download/<job_id>/<fmt>")
def download(job_id, fmt):
    res = _results.get(job_id)
    if not res:
        return "No results for job", 404
    df = pd.DataFrame(res["rows"])
    bio = io.BytesIO()
    if fmt == "xlsx":
        df.to_excel(bio, index=False)
        bio.seek(0)
        return send_file(bio, download_name=f"enriched_{job_id}.xlsx", as_attachment=True)
    elif fmt == "csv":
        df.to_csv(bio, index=False)
        bio.seek(0)
        return send_file(bio, download_name=f"enriched_{job_id}.csv", as_attachment=True)
    # run local dev server
    app.run(host="127.0.0.1", port=5000, debug=True)

if __name__ == "__main__":
    # run local dev server
    app.run(host="127.0.0.1", port=5000, debug=True)