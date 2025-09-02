# OpenWeb Enricher — Quick Start & Troubleshooting

This README explains how to install, run, troubleshoot and maintain the OpenWeb Enricher web UI. It's written for someone with little or no coding background. Follow each step exactly.

---

Table of contents
- What this is
- Quick checklist (one-line)
- Install & run locally (macOS / Linux VM)
- Running long‑term (daemon / systemd / tmux)
- Using the web UI
- Common problems & fixes
- Files & output locations
- Security notes
- Using AI to make code changes, commit, push, pull and redeploy
- Useful commands summary

---

What this is
- A small Flask web app that takes an Excel (.xlsx) with owner names, runs searches (Brave), optionally scrapes result pages, and produces enriched results.
- UI shows live step-by-step logs, results and history. Jobs are persisted under data/jobs/<job_id>.

Quick checklist (one-liner)
1. From project root run:
   - Interactive setup: ./scripts/bootstrap.sh
   - Or start background daemon: ./scripts/bootstrap.sh --daemon
   - Then open: http://127.0.0.1:5000

Note: run these from the repository root (where README.md and scripts/ exist).

---

Prerequisites (what you need)
- Python 3.8+ installed on your machine/VM.
- Network access to perform web requests (if you enable scraping).
- Optional: BRAVE_API_KEY (if you want Brave Search results). You can still run without it — the app will skip Brave queries.

---

Install & run locally (step-by-step)

1) Ensure you're in the repo root:
   cd /Users/marcos/dev/matt/openweb_enricher

2) Make the bootstrap script executable (only once):
   chmod +x scripts/bootstrap.sh

3) Interactive setup and start (foreground, watch output):
   ./scripts/bootstrap.sh
   - The script creates a virtual environment (.venv), installs required Python packages, creates data directories and prompts to create a .env (BRAVE key and optional basic auth).
   - When finished you can run the server (next step).

4) Quick foreground run:
   ./.start-web.sh
   - Opens the web app at http://127.0.0.1:5000

5) Start in background (daemon):
   ./scripts/bootstrap.sh --daemon
   - This starts the server detached and writes logs to logs/webapp.log and saves the PID to run.pid.

If you prefer not to use the provided helpers, you can run manually:
```
source .venv/bin/activate
env PYTHONPATH=src python -u -m openweb_enricher.webapp
```

---

Running on a VM long-term

Recommended: use systemd (Linux) or keep running inside a tmux session.

- Automatic systemd installation is offered by the setup script if the VM supports systemd (it will ask for a username to run the service as).
- To manually install systemd unit (example):
  1. Create unit file /etc/systemd/system/openweb_enricher.service (edit paths & user):
     - WorkingDirectory: full path to repo root (e.g. /home/ubuntu/openweb_enricher)
     - ExecStart: full path to venv python: /full/path/.venv/bin/python -u -m openweb_enricher.webapp
  2. Reload and enable:
     sudo systemctl daemon-reload
     sudo systemctl enable --now openweb_enricher.service
  3. View logs:
     sudo journalctl -u openweb_enricher.service -f

If systemd is not available (macOS / some minimal Linux): run inside tmux or use the --daemon option.

---

Using the web UI

1. Open http://127.0.0.1:5000 in a browser (use VM IP if remote).
2. Upload an Excel file (.xlsx) containing columns such as "ID", "Owner 1", "Owner 2", "Is corp?".
3. Choose options:
   - Fetch & scrape result pages: enables fetching result pages for additional email extraction.
   - Results per query, Max queries, Max emails, Fetch timeout: tune how many results/requests the job should use.
4. After upload the UI opens a job view showing live logs. When job completes the page reloads and displays results and download links (XLSX/CSV).
5. Results are also saved in data/jobs/<job_id>/ (result.json, run.log, results_<job_id>.csv/xlsx).

---

Where to look for outputs & logs

- App logs (daemon): logs/webapp.log
- Data per job: data/jobs/<job_id>/result.json, run.log, results_<job_id>.csv/xlsx
- Most recent job list visible on the index page.
- If running with systemd: journalctl -u openweb_enricher.service -f

---

Common problems & troubleshooting

1) "Connecting to job log..." never changes in browser
   - Check server terminal/logs/webapp.log — ensure the job thread started.
   - Verify a data/jobs/<job_id> directory was created for the job.
   - If no job directory: the worker may have failed before creating it; check logs/webapp.log and server console.

2) No results (empty table)
   - Make sure Excel has Owner columns filled.
   - Check run.log in the job directory for "Fetching page" or "found email" messages.
   - If BRAVE_API_KEY not set, Brave queries are skipped — set BRAVE_API_KEY in .env.

3) Jinja template errors / KeyError: '% if history %'
   - This happens if the template string was incorrectly processed by Python .format(). Use the current webapp.py that replaces placeholders safely. If you see this error, restore webapp.py to the latest version from the repo.

4) Brave API errors (subscription token invalid)
   - Ensure BRAVE_API_KEY in .env is correct and has permission.
   - Check run.log or server console for the returned Brave API message.

5) Page scraping not working or too fast
   - Increase fetch_timeout and enable scrape checkbox.
   - Check run.log for fetch errors and missing BeautifulSoup — install lxml and beautifulsoup4 (setup script does this).
   - If jobs run "too fast", Brave returned no results (no queries) or scraping was skipped (checkbox unchecked).

6) Permissions or systemd errors
   - If service fails to start, run:
     sudo journalctl -u openweb_enricher.service -n 200 --no-pager
   - Ensure WorkingDirectory and ExecStart point to the correct absolute paths and the user has read/write access to repo and data directories.

7) Virtualenv / dependency issues
   - Activate venv: source .venv/bin/activate
   - Reinstall requirements:
     python -m pip install --upgrade pip
     python -m pip install pandas requests python-dotenv openpyxl flask beautifulsoup4 lxml

8) "NotOpenSSLWarning" on macOS
   - This is a harmless warning about LibreSSL vs OpenSSL used by macOS Python. It does not prevent functionality. To remove warning, use a Python build linked to OpenSSL (optional).

---

Security notes & recommended setup

- Do not expose the app to the public internet without adding authentication and HTTPS.
- Enable BASIC_AUTH_USER and BASIC_AUTH_PASS in .env to add Basic Auth (setup script can add these).
- Prefer running the service under an unprivileged user (not root). The setup script asks which user to run the systemd unit as.

---

Using AI to make code changes, commit and push to GitHub, then pull on the VM and restart

This project can be edited with AI assistance locally or in GitHub Copilot-like tools. Typical flow:

1) Make code change (example: change default max queries)
   - Edit files in your local clone (or ask AI to produce patch).

2) Commit and push to GitHub (example commands):
```
git add .
git commit -m "Change: default max queries -> 5; small UI tweak"
git push origin main
```
3) On the VM: pull latest changes and restart app
```
cd /full/path/to/openweb_enricher
git pull origin main
# If using systemd:
sudo systemctl restart openweb_enricher.service
sudo journalctl -u openweb_enricher.service -f
# If running via bootstrap script (daemon):
kill $(cat run.pid) 2>/dev/null || true
./scripts/bootstrap.sh --daemon
tail -F logs/webapp.log
# If running in foreground, stop and re-run:
# Ctrl-C to stop, then:
./.start-web.sh
```

4) If you used a venv and new packages are required:
```
source .venv/bin/activate
python -m pip install -r requirements.txt   # if you keep requirements
# or install individually the new packages
```

AI-assisted edit -> commit -> push example (one-liner)
```
# after modifying files
git add src/openweb_enricher/webapp.py src/openweb_enricher/main.py
git commit -m "Update: added scrape timeout config and UI inputs"
git push
```

Then on VM:
```
cd /path/to/repo
git pull
sudo systemctl restart openweb_enricher.service   # if using systemd
```

If you want a fully automated pipeline:
- Add a GitHub Action to run tests and push a notification.
- Use a deployment script on the VM to auto-pull on new commits (not included by default).

---

Extra useful commands (copy/paste)

Check who you are:
```
whoami
id -u
```

List job directories:
```
ls -la data/jobs
```

Inspect a job:
```
JOB=$(ls -1 data/jobs | tail -1)
less data/jobs/$JOB/run.log
cat data/jobs/$JOB/result.json | jq .   # if jq installed
```

Stop background daemon (started with bootstrap --daemon):
```
kill $(cat run.pid) 2>/dev/null || pkill -f openweb_enricher.webapp
```

Run in tmux:
```
tmux new -s enricher
# inside tmux:
./.start-web.sh
# detach: Ctrl-b d
```

View logs:
```
tail -F logs/webapp.log
# or if systemd:
sudo journalctl -u openweb_enricher.service -f
```

---

If something is still failing
- Copy the first ~50 lines of logs (logs/webapp.log or journalctl) and paste them into a support request.
- Include: OS (macOS / Ubuntu), Python version (python3 --version), contents of .env (do not share keys — just list keys present), and the Excel you uploaded (or a small anonymized sample).

---

Support & Next steps I can help with
- Produce a ready-to-write systemd unit for your exact VM username & repo path (paste them).
- Create a requirements.txt or Dockerfile for containerized runs.
- Add simple readme in the UI explaining required Excel columns (Owner 1, Owner 2, ID, Is corp?).
- Add health endpoint, authentication improvements, or persistent DB storage for jobs.

--- 

End of README
``` ````# filepath: /Users/marcos/dev/matt/openweb_enricher/README.md

# OpenWeb Enricher — Quick Start & Troubleshooting

This README explains how to install, run, troubleshoot and maintain the OpenWeb Enricher web UI. It's written for someone with little or no coding background. Follow each step exactly.

---

Table of contents
- What this is
- Quick checklist (one-line)
- Install & run locally (macOS / Linux VM)
- Running long‑term (daemon / systemd / tmux)
- Using the web UI
- Common problems & fixes
- Files & output locations
- Security notes
- Using AI to make code changes, commit, push, pull and redeploy
- Useful commands summary

---

What this is
- A small Flask web app that takes an Excel (.xlsx) with owner names, runs searches (Brave), optionally scrapes result pages, and produces enriched results.
- UI shows live step-by-step logs, results and history. Jobs are persisted under data/jobs/<job_id>.

Quick checklist (one-liner)
1. From project root run:
   - Interactive setup: ./scripts/bootstrap.sh
   - Or start background daemon: ./scripts/bootstrap.sh --daemon
   - Then open: http://127.0.0.1:5000

Note: run these from the repository root (where README.md and scripts/ exist).

---

Prerequisites (what you need)
- Python 3.8+ installed on your machine/VM.
- Network access to perform web requests (if you enable scraping).
- Optional: BRAVE_API_KEY (if you want Brave Search results). You can still run without it — the app will skip Brave queries.

---

Install & run locally (step-by-step)

1) Ensure you're in the repo root:
   cd /Users/marcos/dev/matt/openweb_enricher

2) Make the bootstrap script executable (only once):
   chmod +x scripts/bootstrap.sh

3) Interactive setup and start (foreground, watch output):
   ./scripts/bootstrap.sh
   - The script creates a virtual environment (.venv), installs required Python packages, creates data directories and prompts to create a .env (BRAVE key and optional basic auth).
   - When finished you can run the server (next step).

4) Quick foreground run:
   ./.start-web.sh
   - Opens the web app at http://127.0.0.1:5000

5) Start in background (daemon):
   ./scripts/bootstrap.sh --daemon
   - This starts the server detached and writes logs to logs/webapp.log and saves the PID to run.pid.

If you prefer not to use the provided helpers, you can run manually:
```
source .venv/bin/activate
env PYTHONPATH=src python -u -m openweb_enricher.webapp
```

---

Running on a VM long-term

Recommended: use systemd (Linux) or keep running inside a tmux session.

- Automatic systemd installation is offered by the setup script if the VM supports systemd (it will ask for a username to run the service as).
- To manually install systemd unit (example):
  1. Create unit file /etc/systemd/system/openweb_enricher.service (edit paths & user):
     - WorkingDirectory: full path to repo root (e.g. /home/ubuntu/openweb_enricher)
     - ExecStart: full path to venv python: /full/path/.venv/bin/python -u -m openweb_enricher.webapp
  2. Reload and enable:
     sudo systemctl daemon-reload
     sudo systemctl enable --now openweb_enricher.service
  3. View logs:
     sudo journalctl -u openweb_enricher.service -f

If systemd is not available (macOS / some minimal Linux): run inside tmux or use the --daemon option.

---

Using the web UI

1. Open http://127.0.0.1:5000 in a browser (use VM IP if remote).
2. Upload an Excel file (.xlsx) containing columns such as "ID", "Owner 1", "Owner 2", "Is corp?".
3. Choose options:
   - Fetch & scrape result pages: enables fetching result pages for additional email extraction.
   - Results per query, Max queries, Max emails, Fetch timeout: tune how many results/requests the job should use.
4. After upload the UI opens a job view showing live logs. When job completes the page reloads and displays results and download links (XLSX/CSV).
5. Results are also saved in data/jobs/<job_id>/ (result.json, run.log, results_<job_id>.csv/xlsx).

---

Where to look for outputs & logs

- App logs (daemon): logs/webapp.log
- Data per job: data/jobs/<job_id>/result.json, run.log, results_<job_id>.csv/xlsx
- Most recent job list visible on the index page.
- If running with systemd: journalctl -u openweb_enricher.service -f

---

Common problems & troubleshooting

1) "Connecting to job log..." never changes in browser
   - Check server terminal/logs/webapp.log — ensure the job thread started.
   - Verify a data/jobs/<job_id> directory was created for the job.
   - If no job directory: the worker may have failed before creating it; check logs/webapp.log and server console.

2) No results (empty table)
   - Make sure Excel has Owner columns filled.
   - Check run.log in the job directory for "Fetching page" or "found email" messages.
   - If BRAVE_API_KEY not set, Brave queries are skipped — set BRAVE_API_KEY in .env.

3) Jinja template errors / KeyError: '% if history %'
   - This happens if the template string was incorrectly processed by Python .format(). Use the current webapp.py that replaces placeholders safely. If you see this error, restore webapp.py to the latest version from the repo.

4) Brave API errors (subscription token invalid)
   - Ensure BRAVE_API_KEY in .env is correct and has permission.
   - Check run.log or server console for the returned Brave API message.

5) Page scraping not working or too fast
   - Increase fetch_timeout and enable scrape checkbox.
   - Check run.log for fetch errors and missing BeautifulSoup — install lxml and beautifulsoup4 (setup script does this).
   - If jobs run "too fast", Brave returned no results (no queries) or scraping was skipped (checkbox unchecked).

6) Permissions or systemd errors
   - If service fails to start, run:
     sudo journalctl -u openweb_enricher.service -n 200 --no-pager
   - Ensure WorkingDirectory and ExecStart point to the correct absolute paths and the user has read/write access to repo and data directories.

7) Virtualenv / dependency issues
   - Activate venv: source .venv/bin/activate
   - Reinstall requirements:
     python -m pip install --upgrade pip
     python -m pip install pandas requests python-dotenv openpyxl flask beautifulsoup4 lxml

8) "NotOpenSSLWarning" on macOS
   - This is a harmless warning about LibreSSL vs OpenSSL used by macOS Python. It does not prevent functionality. To remove warning, use a Python build linked to OpenSSL (optional).

---

Security notes & recommended setup

- Do not expose the app to the public internet without adding authentication and HTTPS.
- Enable BASIC_AUTH_USER and BASIC_AUTH_PASS in .env to add Basic Auth (setup script can add these).
- Prefer running the service under an unprivileged user (not root). The setup script asks which user to run the systemd unit as.

---

Using AI to make code changes, commit and push to GitHub, then pull on the VM and restart

This project can be edited with AI assistance locally or in GitHub Copilot-like tools. Typical flow:

1) Make code change (example: change default max queries)
   - Edit files in your local clone (or ask AI to produce patch).

2) Commit and push to GitHub (example commands):
```
git add .
git commit -m "Change: default max queries -> 5; small UI tweak"
git push origin main
```
3) On the VM: pull latest changes and restart app
```
cd /full/path/to/openweb_enricher
git pull origin main
# If using systemd:
sudo systemctl restart openweb_enricher.service
sudo journalctl -u openweb_enricher.service -f
# If running via bootstrap script (daemon):
kill $(cat run.pid) 2>/dev/null || true
./scripts/bootstrap.sh --daemon
tail -F logs/webapp.log
# If running in foreground, stop and re-run:
# Ctrl-C to stop, then:
./.start-web.sh
```

4) If you used a venv and new packages are required:
```
source .venv/bin/activate
python -m pip install -r requirements.txt   # if you keep requirements
# or install individually the new packages
```

AI-assisted edit -> commit -> push example (one-liner)
```
# after modifying files
git add src/openweb_enricher/webapp.py src/openweb_enricher/main.py
git commit -m "Update: added scrape timeout config and UI inputs"
git push
```

Then on VM:
```
cd /path/to/repo
git pull
sudo systemctl restart openweb_enricher.service   # if using systemd
```

If you want a fully automated pipeline:
- Add a GitHub Action to run tests and push a notification.
- Use a deployment script on the VM to auto-pull on new commits (not included by default).

---

Extra useful commands (copy/paste)

Check who you are:
```
whoami
id -u
```

List job directories:
```
ls -la data/jobs
```

Inspect a job:
```
JOB=$(ls -1 data/jobs | tail -1)
less data/jobs/$JOB/run.log
cat data/jobs/$JOB/result.json | jq .   # if jq installed
```

Stop background daemon (started with bootstrap --daemon):
```
kill $(cat run.pid) 2>/dev/null || pkill -f openweb_enricher.webapp
```

Run in tmux:
```
tmux new -s enricher
# inside tmux:
./.start-web.sh
# detach: Ctrl-b d
```

View logs:
```
tail -F logs/webapp.log
# or if systemd:
sudo journalctl -u openweb_enricher.service -f
```

---

If something is still failing
- Copy the first ~50 lines of logs (logs/webapp.log or journalctl) and paste them into a support request.
- Include: OS (macOS / Ubuntu), Python version (python3 --version), contents of .env (do not share keys — just list keys present), and the Excel you uploaded (or a small anonymized sample).

---

Support & Next steps I can help with
- Produce a ready-to-write systemd unit for your exact VM username & repo path (paste them).
- Create a requirements.txt or Dockerfile for containerized runs.
- Add simple readme in the UI explaining required Excel columns (Owner 1, Owner 2, ID, Is corp?).
- Add health endpoint, authentication improvements, or persistent DB storage for jobs.

---