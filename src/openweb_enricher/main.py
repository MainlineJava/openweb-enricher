import os
import json
import re
import time
import requests
import pandas as pd
import io
from openweb_enricher.config import (
    BRAVE_API_KEY, INPUT_FILE, OUTPUT_FILE, CHECKPOINT_FILE,
    MAX_QUERIES, MAX_EMAILS, GENERIC_PREFIXES
)

def brave_search(query):
    """Perform a search using the Brave Search API (with debug info)."""
    if not BRAVE_API_KEY:
        print("⚠️ BRAVE_API_KEY not set (check .env). brave_search will be skipped.")
        return []

    # prefer the documented Brave Search endpoint and header
    url = "https://api.search.brave.com/res/v1/web/search"
    headers = {"X-Subscription-Token": BRAVE_API_KEY, "Accept": "application/json"}
    params = {"q": query, "count": 10, "result_filter": "web"}

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
    except requests.RequestException as e:
        print(f"⚠️ Brave request failed: {e}")
        return []

    # debug output
    print(f"→ Brave API status: {resp.status_code} for query: {query}")
    if resp.status_code != 200:
        snippet = resp.text[:500].replace("\n", " ")
        print(f"  response: {snippet}")
        return []

    try:
        data = resp.json()
    except Exception as e:
        print(f"⚠️ Failed to parse JSON from Brave response: {e}")
        print("  body snippet:", resp.text[:500])
        return []

    # inspect structure for results
    results = data.get("web", {}).get("results") or data.get("results") or []
    if not results:
        print("  ℹ️ Brave returned no results (empty result set).")
    return results

def extract_emails(text):
    """Extract email addresses from the given text using regex."""
    if not isinstance(text, str):
        return []
    # simple regex for extracting emails
    return re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)

def _col_value(row, df_cols, desired):
    # case-insensitive column lookup (handles small header variations)
    for c in df_cols:
        if isinstance(c, str) and c.strip().lower() == desired.strip().lower():
            return row.get(c)
    return None

def _is_true(val):
    if isinstance(val, bool):
        return val
    if val is None:
        return False
    s = str(val).strip().lower()
    return s in ("true", "yes", "y", "1", "t")

def load_checkpoint():
    """Return a set of processed record IDs from the checkpoint file."""
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, "r") as f:
                data = json.load(f)
            return set(str(x) for x in data)
        except Exception as e:
            print(f"⚠️ Failed to read checkpoint file: {e}")
            return set()
    return set()

def save_checkpoint(processed_set):
    """Persist processed record IDs (set) to the checkpoint file."""
    try:
        # ensure checkpoint directory exists
        ck_dir = os.path.dirname(CHECKPOINT_FILE) or "."
        os.makedirs(ck_dir, exist_ok=True)
        with open(CHECKPOINT_FILE, "w") as f:
            json.dump(list(processed_set), f)
    except Exception as e:
        print(f"⚠️ Failed to save checkpoint: {e}")

def fetch_and_scrape(url, timeout=15):
    """
    Fetch a URL and return a plain-text representation of the page.
    Normalizes URL (adds https:// when missing), prints fetch activity,
    uses BeautifulSoup if available, otherwise falls back to a simple tag-stripper.
    """
    if not url or not isinstance(url, str):
        return ""
    orig = url.strip()
    # normalize scheme
    if orig.startswith("//"):
        norm = "https:" + orig
    elif orig.startswith("http://") or orig.startswith("https://"):
        norm = orig
    else:
        # if it looks like a hostname/path, assume https
        if re.search(r"\.[a-z]{2,}(/|$)", orig):
            norm = "https://" + orig
        else:
            print(f"    ⚠️ Skipping fetch, invalid URL: {orig}")
            return ""

    headers = {"User-Agent": "openweb_enricher/1.0 (+https://example.local)"}
    print(f"    → Fetching page: {norm}")
    try:
        resp = requests.get(norm, headers=headers, timeout=timeout, allow_redirects=True)
    except requests.RequestException as e:
        print(f"    ⚠️ Failed to fetch page {norm}: {e}")
        return ""

    # small polite throttle so you can see activity and avoid burst
    time.sleep(0.5)

    html = resp.text or ""
    ctype = resp.headers.get("Content-Type", "")
    # if not HTML, return raw text
    if "html" not in ctype.lower():
        return html

    # Prefer BeautifulSoup if available for robust extraction
    try:
        from bs4 import BeautifulSoup  # optional dependency
        soup = BeautifulSoup(html, "lxml")
        return soup.get_text(separator=" ", strip=True)
    except Exception:
        # fallback: naive tag removal
        text = re.sub(r"<script.*?>.*?</script>", " ", html, flags=re.S | re.I)
        text = re.sub(r"<style.*?>.*?</style>", " ", text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()

def enrich():
    if not os.path.exists(INPUT_FILE):
        print(f"❌ Input file not found: {INPUT_FILE}")
        return

    try:
        df = pd.read_excel(INPUT_FILE)
    except Exception as e:
        print(f"❌ Failed to read {INPUT_FILE}: {e}")
        return

    # normalize small quirks in column names (strip)
    df.columns = [c.strip() if isinstance(c, str) else c for c in df.columns]
    df_cols = list(df.columns)

    processed = load_checkpoint()
    output_rows = []
    total_records = 0
    total_emails_found = 0

    print(f"Parsed owners for record {record_id}: {owners}")

    for idx, row in df.iterrows():
        total_records += 1
        record_id = row.get("ID")
        if pd.isna(record_id):
            record_id = f"row-{idx}"
        if str(record_id) in processed:
            continue

        # skip if Is corp? column exists and is true
        is_corp_val = _col_value(row, df_cols, "Is corp?")
        if _is_true(is_corp_val):
            processed.add(str(record_id))
            save_checkpoint(processed)
            continue

        # collect owners from possible owner columns, split multiple names
        owners = []
        for desired in ("Owner 1", "Owner 2"):
            raw = _col_value(row, df_cols, desired)
            if isinstance(raw, str) and raw.strip():
                parts = re.split(r'[&/;,]+', raw)
                owners.extend([p.strip() for p in parts if p.strip()])

        if not owners:
            processed.add(str(record_id))
            save_checkpoint(processed)
            continue

        # DEBUG: show parsed owner names
        print(f"Parsed owners for record {record_id}: {owners}")

        for name in owners:
            if "trust" in str(name).lower():
                continue

            print(f"🔍 Searching for {name} (record {record_id})...")
            emails_collected = []
            seen_urls = set()

            for attempt in range(MAX_QUERIES):
                results = brave_search(name)
                for result in results:
                    url = result.get("url", "")
                    snippet = result.get("description", "") or result.get("snippet", "") or ""
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    # Print result details for visibility whether or not it contains emails
                    print(f"  - result: {url}")
                    print(f"    snippet: {snippet[:200].strip() or '<no snippet>'}")
                    combined = f"{result.get('title', '')} {snippet} {url}"
                    emails = extract_emails(combined)
                    if emails:
                        for e in emails:
                            print(f"    found email: {e}")
                    else:
                        print("    no emails found in this result")
                    # If we still need emails, fetch the full page and scrape it
                    if len(emails_collected) < MAX_EMAILS:
                        page_text = fetch_and_scrape(url)
                        if page_text:
                            page_emails = extract_emails(page_text)
                            # only report new ones
                            new_page_emails = [e for e in page_emails if e not in emails and e not in emails_collected]
                            if new_page_emails:
                                for e in new_page_emails:
                                    print(f"    found on page: {e}")
                                emails = emails + new_page_emails
                            else:
                                if page_emails:
                                    print("    page had emails but none new / they were filtered out")
                                else:
                                    print("    no emails found on the fetched page")
                    for email in emails:
                        if email not in emails_collected and len(emails_collected) < MAX_EMAILS:
                            output_rows.append({
                                "input_id": record_id,
                                "name": name,
                                "email": email,
                                "confidence": 1.0,
                                "source": url,
                                "snippet": snippet
                            })
                            emails_collected.append(email)
                            total_emails_found += 1
                if len(emails_collected) >= MAX_EMAILS:
                    break
                time.sleep(0.5)

            # per-name summary
            print(f"  → Collected {len(emails_collected)} emails for {name}")

        processed.add(str(record_id))
        save_checkpoint(processed)

    # ensure output/checkpoint directories exist
    os.makedirs(os.path.dirname(OUTPUT_FILE) or ".", exist_ok=True)
    os.makedirs(os.path.dirname(CHECKPOINT_FILE) or ".", exist_ok=True)

    print(f"Processed {total_records} records, found {total_emails_found} emails in total.")
    if output_rows:
        out_df = pd.DataFrame(output_rows)
        # enforce required column order
        out_df = out_df[["input_id", "name", "email", "confidence", "source", "snippet"]]
        try:
            out_df.to_excel(OUTPUT_FILE, index=False)
            print(f"✅ Saved {len(out_df)} rows to {OUTPUT_FILE}")
        except Exception as e:
            csv_path = OUTPUT_FILE.rsplit(".", 1)[0] + ".csv"
            out_df.to_csv(csv_path, index=False)
            print(f"⚠️ Excel write failed ({e}), saved CSV to {csv_path}")
    else:
        print("❌ No new results found. (output_rows is empty)")

def run_enrich_on_df(df, scrape_pages=True):
    """
    Run enrichment on a pandas DataFrame and return dict with metadata + rows.
    scrape_pages: if False, skip fetching full pages (only use snippets from Brave results).
    """
    # normalize small quirks in column names (strip)
    df = df.copy()
    df.columns = [c.strip() if isinstance(c, str) else c for c in df.columns]
    df_cols = list(df.columns)

    processed = set()
    output_rows = []
    total_records = 0
    total_emails_found = 0

    for idx, row in df.iterrows():
        total_records += 1
        record_id = row.get("ID")
        if pd.isna(record_id):
            record_id = f"row-{idx}"
        if str(record_id) in processed:
            continue

        # skip if Is corp? column exists and is true
        is_corp_val = _col_value(row, df_cols, "Is corp?")
        if _is_true(is_corp_val):
            processed.add(str(record_id))
            continue

        # collect owners from possible owner columns, split multiple names
        owners = []
        for desired in ("Owner 1", "Owner 2"):
            raw = _col_value(row, df_cols, desired)
            if isinstance(raw, str) and raw.strip():
                parts = re.split(r'[&/;,]+', raw)
                owners.extend([p.strip() for p in parts if p.strip()])

        if not owners:
            processed.add(str(record_id))
            continue

        for name in owners:
            if "trust" in str(name).lower():
                continue

            emails_collected = []
            seen_urls = set()

            for attempt in range(MAX_QUERIES):
                results = brave_search(name)
                for result in results:
                    url = result.get("url", "")
                    snippet = result.get("description", "") or result.get("snippet", "") or ""
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    combined = f"{result.get('title', '')} {snippet} {url}"
                    emails = extract_emails(combined)

                    # attempt deeper page scrape only if enabled
                    if scrape_pages and len(emails_collected) < MAX_EMAILS:
                        page_text = fetch_and_scrape(url)
                        if page_text:
                            page_emails = extract_emails(page_text)
                            new_page_emails = [e for e in page_emails if e not in emails and e not in emails_collected]
                            if new_page_emails:
                                emails = emails + new_page_emails

                    for email in emails:
                        if email not in emails_collected and len(emails_collected) < MAX_EMAILS:
                            output_rows.append({
                                "input_id": record_id,
                                "name": name,
                                "email": email,
                                "confidence": 1.0,
                                "source": url,
                                "snippet": snippet
                            })
                            emails_collected.append(email)
                            total_emails_found += 1
                if len(emails_collected) >= MAX_EMAILS:
                    break
                time.sleep(0.3)

        processed.add(str(record_id))

    # return a tuple with metadata + rows
    return {
        "total_records": total_records,
        "total_emails_found": total_emails_found,
        "rows": output_rows
    }

if __name__ == "__main__":
    enrich()