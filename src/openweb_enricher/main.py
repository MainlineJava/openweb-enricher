import os
import re
import time
import json
import requests
import pandas as pd
from typing import List, Dict, Any

from openweb_enricher.config import (
    BRAVE_API_KEY, INPUT_FILE, OUTPUT_FILE, CHECKPOINT_FILE,
    MAX_QUERIES, MAX_EMAILS, GENERIC_PREFIXES
)

def brave_search(query: str, count: int = 10) -> List[Dict[str, Any]]:
    if not BRAVE_API_KEY:
        print("⚠️ BRAVE_API_KEY not set (check .env). brave_search will be skipped.")
        return []
    url = "https://api.search.brave.com/res/v1/web/search"
    headers = {"X-Subscription-Token": BRAVE_API_KEY, "Accept": "application/json"}
    params = {"q": query, "count": count, "result_filter": "web"}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
    except requests.RequestException as e:
        print(f"⚠️ Brave request failed: {e}")
        return []
    print(f"→ Brave API status: {resp.status_code} for query: {query}")
    if resp.status_code != 200:
        snippet = resp.text[:500].replace("\n", " ")
        print(f"  response: {snippet}")
        if resp.status_code == 422 and "SUBSCRIPTION_TOKEN_INVALID" in resp.text:
            print("  ⚠️ Subscription token invalid. Check BRAVE_API_KEY.")
        return []
    try:
        data = resp.json()
    except Exception as e:
        print(f"⚠️ Failed to parse Brave JSON: {e}")
        return []
    results = data.get("web", {}).get("results") or data.get("results") or []
    if not results:
        print("  ℹ️ Brave returned no results.")
    return results

def extract_emails(text: str) -> List[str]:
    if not isinstance(text, str):
        return []
    return list(dict.fromkeys(re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)))

def _col_value(row, df_cols, desired):
    for c in df_cols:
        if isinstance(c, str) and c.strip().lower() == desired.strip().lower():
            return row.get(c)
    return None

def _is_true(val) -> bool:
    if isinstance(val, bool):
        return val
    if val is None:
        return False
    s = str(val).strip().lower()
    return s in ("true", "yes", "y", "1", "t")

def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, "r") as f:
                data = json.load(f)
            return set(str(x) for x in data)
        except Exception as e:
            print(f"⚠️ Failed to read checkpoint: {e}")
            return set()
    return set()

def save_checkpoint(processed_set):
    try:
        ck_dir = os.path.dirname(CHECKPOINT_FILE) or "."
        os.makedirs(ck_dir, exist_ok=True)
        with open(CHECKPOINT_FILE, "w") as f:
            json.dump(list(processed_set), f)
    except Exception as e:
        print(f"⚠️ Failed to save checkpoint: {e}")

def fetch_and_scrape(url: str, timeout: int = 15) -> str:
    if not url or not isinstance(url, str):
        return ""
    orig = url.strip()
    if orig.startswith("//"):
        norm = "https:" + orig
    elif orig.startswith("http://") or orig.startswith("https://"):
        norm = orig
    else:
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
    time.sleep(0.5)
    html = resp.text or ""
    ctype = resp.headers.get("Content-Type", "")
    if "html" not in ctype.lower():
        return html
    try:
        from bs4 import BeautifulSoup  # optional
        soup = BeautifulSoup(html, "lxml")
        return soup.get_text(separator=" ", strip=True)
    except Exception:
        text = re.sub(r"<script.*?>.*?</script>", " ", html, flags=re.S | re.I)
        text = re.sub(r"<style.*?>.*?</style>", " ", text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()

def email_confidence(email: str, name: str) -> float:
    # simple heuristic: exact name parts in email -> higher confidence
    try:
        local = email.split("@", 1)[0].lower()
        tokens = re.findall(r"[a-z]+", name.lower())
        score = 0.5
        for t in tokens:
            if t and t in local:
                score += 0.2
        return min(1.0, score)
    except Exception:
        return 0.5

def enrich():
    if not os.path.exists(INPUT_FILE):
        print(f"❌ Input file not found: {INPUT_FILE}")
        return
    try:
        df = pd.read_excel(INPUT_FILE)
    except Exception as e:
        print(f"❌ Failed to read {INPUT_FILE}: {e}")
        return
    df.columns = [c.strip() if isinstance(c, str) else c for c in df.columns]
    df_cols = list(df.columns)
    processed = load_checkpoint()
    output_rows = []
    for idx, row in df.iterrows():
        record_id = row.get("ID")
        if pd.isna(record_id):
            record_id = f"row-{idx}"
        if str(record_id) in processed:
            continue
        is_corp_val = _col_value(row, df_cols, "Is corp?")
        if _is_true(is_corp_val):
            processed.add(str(record_id))
            save_checkpoint(processed)
            continue
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
        print(f"Parsed owners for record {record_id}: {owners}")
        for name in owners:
            if "trust" in str(name).lower():
                continue
            print(f"🔍 Searching for {name} (record {record_id})...")
            emails_collected = []
            seen_urls = set()
            for attempt in range(MAX_QUERIES):
                results = brave_search(name, count=10)
                for result in results:
                    url = result.get("url", "")
                    snippet = result.get("description", "") or result.get("snippet", "") or ""
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    print(f"  - result: {url}")
                    print(f"    snippet: {snippet[:200].strip() or '<no snippet>'}")
                    combined = f"{result.get('title', '')} {snippet} {url}"
                    emails = extract_emails(combined)
                    if emails:
                        for e in emails:
                            print(f"    found email (snippet): {e}")
                    else:
                        print("    no emails found in this result")
                    if len(emails_collected) < MAX_EMAILS:
                        page_text = fetch_and_scrape(url)
                        if page_text:
                            page_emails = extract_emails(page_text)
                            new_page_emails = [e for e in page_emails if e not in emails and e not in emails_collected]
                            if new_page_emails:
                                for e in new_page_emails:
                                    print(f"    found on page: {e}")
                                emails = emails + new_page_emails
                            else:
                                if page_emails:
                                    print("    page had emails but none new")
                                else:
                                    print("    no emails found on the fetched page")
                    for email in emails:
                        if email not in emails_collected and len(emails_collected) < MAX_EMAILS:
                            output_rows.append({
                                "input_id": record_id,
                                "name": name,
                                "email": email,
                                "confidence": email_confidence(email, name),
                                "source": url,
                                "snippet": snippet
                            })
                            emails_collected.append(email)
                if len(emails_collected) >= MAX_EMAILS:
                    break
                time.sleep(0.3)
        processed.add(str(record_id))
        save_checkpoint(processed)
    if output_rows:
        out_df = pd.DataFrame(output_rows)
        os.makedirs(os.path.dirname(OUTPUT_FILE) or ".", exist_ok=True)
        try:
            out_df.to_excel(OUTPUT_FILE, index=False)
            print(f"✅ Saved {len(out_df)} rows to {OUTPUT_FILE}")
        except Exception as e:
            csv_path = OUTPUT_FILE.rsplit(".", 1)[0] + ".csv"
            out_df.to_csv(csv_path, index=False)
            print(f"⚠️ Excel write failed ({e}), saved CSV to {csv_path}")
    else:
        print("❌ No new results found. (output_rows is empty)")

def run_enrich_on_df(df: pd.DataFrame, scrape_pages: bool = True,
                     max_queries: int = None, max_emails: int = None,
                     results_per_query: int = 10, fetch_timeout: int = 15):
    if max_queries is None:
        max_queries = MAX_QUERIES
    if max_emails is None:
        max_emails = MAX_EMAILS
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
        is_corp_val = _col_value(row, df_cols, "Is corp?")
        if _is_true(is_corp_val):
            processed.add(str(record_id))
            continue
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
            for attempt in range(max_queries):
                results = brave_search(name, count=results_per_query)
                for result in results:
                    url = result.get("url", "")
                    snippet = result.get("description", "") or result.get("snippet", "") or ""
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    combined = f"{result.get('title', '')} {snippet} {url}"
                    emails = extract_emails(combined)
                    if scrape_pages and len(emails_collected) < max_emails:
                        page_text = fetch_and_scrape(url, timeout=fetch_timeout)
                        if page_text:
                            page_emails = extract_emails(page_text)
                            new_page_emails = [e for e in page_emails if e not in emails and e not in emails_collected]
                            if new_page_emails:
                                emails = emails + new_page_emails
                    for email in emails:
                        if email not in emails_collected and len(emails_collected) < max_emails:
                            output_rows.append({
                                "input_id": record_id,
                                "name": name,
                                "email": email,
                                "confidence": email_confidence(email, name),
                                "source": url,
                                "snippet": snippet
                            })
                            emails_collected.append(email)
                            total_emails_found += 1
                if len(emails_collected) >= max_emails:
                    break
                time.sleep(0.3)
        processed.add(str(record_id))
    return {
        "total_records": total_records,
        "total_emails_found": total_emails_found,
        "rows": output_rows,
        "config": {
            "scrape_pages": bool(scrape_pages),
            "max_queries": int(max_queries),
            "max_emails": int(max_emails),
            "results_per_query": int(results_per_query),
            "fetch_timeout": float(fetch_timeout)
        }
    }

if __name__ == "__main__":
    enrich()