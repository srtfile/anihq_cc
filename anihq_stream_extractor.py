"""
anihq.cc Batch Extractor - v7
- Reads URLs from anihq_cc.txt (same folder as script)
- Accepts any URL containing /watch/
- Skips already-processed and errored URLs
- Processes up to 500 URLs per run then stops
- GitHub Actions compatible
"""
import re
import base64
import sys
import json
import time
import random
from pathlib import Path
try:
    from curl_cffi import requests as crequests
    from bs4 import BeautifulSoup
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "curl_cffi", "beautifulsoup4", "-q"])
    from curl_cffi import requests as crequests
    from bs4 import BeautifulSoup

# ── All paths relative to script location ───────────────────
BASE_DIR = Path(__file__).parent
INPUT_FILE = BASE_DIR / "anihq_cc.txt"
OUTPUT_JSON = BASE_DIR / "anihq_cc.json"
OUTPUT_TXT = BASE_DIR / "anihq_cc_readable.txt"
PROCESSED_FILE = BASE_DIR / "already_processed_url.txt"
ERROR_FILE = BASE_DIR / "anihq_error_faced_url_list.txt"
BATCH_SIZE = 500
DELAY = 1.8  # Increased delay for safety

# Proxy list with auth
PROXIES = [
    "http://ygxmhkcc:n3batopqanpg@31.59.20.176:6754",
    "http://ygxmhkcc:n3batopqanpg@31.56.127.193:7684",
    "http://ygxmhkcc:n3batopqanpg@45.38.107.97:6014",
    "http://ygxmhkcc:n3batopqanpg@38.154.203.95:5863",
    "http://ygxmhkcc:n3batopqanpg@198.105.121.200:6462",
    "http://ygxmhkcc:n3batopqanpg@64.137.96.74:6641",
    "http://ygxmhkcc:n3batopqanpg@198.23.243.226:6361",
    "http://ygxmhkcc:n3batopqanpg@38.154.185.97:6370",
    "http://ygxmhkcc:n3batopqanpg@142.111.67.146:5611",
    "http://ygxmhkcc:n3batopqanpg@191.96.254.138:6185",
]

SESSION = None

def get_session():
    global SESSION
    if SESSION is None:
        SESSION = crequests.Session(impersonate="chrome120")
        SESSION.headers.update({
            "Accept-Language": "en-US,en;q=0.9",
        })
    return SESSION

# ── File helpers ─────────────────────────────────────────────
def load_set(filepath):
    p = Path(filepath)
    if not p.exists():
        return set()
    return set(l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip())

def append_line(filepath, text):
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(text.strip() + "\n")

# ── Parsing helpers ──────────────────────────────────────────
def decode_embed_id(raw):
    try:
        parts = raw.split(":", 1)
        label = base64.b64decode(parts[0] + "==").decode("utf-8", errors="ignore").strip()
        url = base64.b64decode(parts[1] + "==").decode("utf-8", errors="ignore").strip() if len(parts) > 1 else ""
        return label, url
    except Exception:
        return "?", ""

def parse_url_meta(url):
    slug = url.rstrip("/").split("/watch/")[-1]
    ep_m = re.search(r"-episode-(\d+)", slug)
    ep = ep_m.group(1) if ep_m else "?"
    lang = "Dub" if "dubbed" in slug.lower() else "Sub"
    name = re.split(r"-episode-", slug, flags=re.IGNORECASE)[0].replace("-", " ").title()
    return {"ep": ep, "lang": lang, "name": name}

def get_cdn_url(voe_url, proxy):
    try:
        session = get_session()
        r = session.get(voe_url, timeout=20, headers={"Referer": "https://anihq.cc/"}, proxies={"http": proxy, "https": proxy})
        m = re.search(r"window\.location\.href\s*=\s*['\"]([^'\"]+/e/[a-z0-9]+)['\"]", r.text)
        if m:
            cdn = m.group(1)
            return ("https:" + cdn) if cdn.startswith("//") else cdn
    except Exception as e:
        print(" [WARN] voe: " + str(e))
    return ""

def extract_m3u8(text):
    found = []
    found += re.findall(r'https?://[^\s\'"<>]+\.m3u8[^\s\'"<>]*', text)
    for key in ("file", "src", "hls", "source", "url"):
        found += re.findall(
            r'["\']?' + key + r'["\']?\s*[:=]\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
            text, re.IGNORECASE
        )
    seen, out = set(), []
    for u in found:
        u = u.rstrip('.,;:!?)]}\\"\'')
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out

# ── Core processor ───────────────────────────────────────────
def process_url(page_url, serial, proxy):
    meta = parse_url_meta(page_url)
    print("[" + str(serial) + "] " + page_url)
    print(" " + meta["name"] + " | Ep:" + meta["ep"] + " | " + meta["lang"])
    record = {
        "serial": serial,
        "url": page_url,
        "ep": meta["ep"],
        "language": meta["lang"],
        "anime_name": meta["name"],
        "stream_urls": [],
        "m3u8_urls": [],
    }
    
    time.sleep(random.uniform(1.2, 2.5))  # Random delay
    
    session = get_session()
    try:
        r = session.get(page_url, timeout=25, proxies={"http": proxy, "https": proxy})
        r.raise_for_status()
    except Exception as e:
        raise Exception(f"Failed to fetch main page: {str(e)}")
    
    soup = BeautifulSoup(r.text, "html.parser")
    buttons = soup.find_all(attrs={"data-embed-id": True})
    if not buttons:
        print(" [WARN] No player buttons found on page")
    
    for btn in buttons:
        label, voe_url = decode_embed_id(btn.get("data-embed-id", ""))
        if not voe_url:
            continue
        if voe_url not in record["stream_urls"]:
            record["stream_urls"].append(voe_url)
        
        cdn_url = get_cdn_url(voe_url, proxy)
        if cdn_url and cdn_url not in record["stream_urls"]:
            record["stream_urls"].append(cdn_url)
        
        print(" [" + label + "]")
        print(" voe=" + voe_url)
        print(" cdn=" + (cdn_url or "(none)"))
    
    record["m3u8_urls"] = extract_m3u8(r.text)
    return record

def format_record(rec):
    lines = [
        "Serial No:" + str(rec["serial"]),
        "1.url :" + rec["url"],
        "2:ep:" + rec["ep"] + " Language:" + rec["language"],
        "3.anime/movie_name: " + rec["anime_name"],
    ]
    for i, u in enumerate(rec["stream_urls"], 1):
        lines.append(str(3 + i) + ".stream url_" + str(i) + ":" + u)
    offset = 3 + len(rec["stream_urls"])
    for i, u in enumerate(rec["m3u8_urls"], 1):
        lines.append(str(offset + i) + ".m3u8_url_" + str(i) + ":" + u)
    lines.append("=" * 84)
    return "\n".join(lines)

# ── Proxy rotation ───────────────────────────────────────────
def get_next_proxy(current_index):
    return PROXIES[current_index % len(PROXIES)]

# ── Main ─────────────────────────────────────────────────────
def main():
    if not INPUT_FILE.exists():
        print("[ERROR] Input file not found: " + str(INPUT_FILE))
        print(" Please add anihq_cc.txt to the repo root.")
        sys.exit(1)

    all_lines = [l.strip() for l in INPUT_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
    valid_urls = [u for u in all_lines if "/watch/" in u and u.startswith("http")]
    skip_set = load_set(PROCESSED_FILE) | load_set(ERROR_FILE)
    pending = [u for u in valid_urls if u not in skip_set]
    
    print("=" * 60)
    print("Total /watch/ URLs : " + str(len(valid_urls)))
    print("Already done/error : " + str(len(valid_urls) - len(pending)))
    print("Pending : " + str(len(pending)))
    print("This batch : " + str(min(BATCH_SIZE, len(pending))))
    print("=" * 60)

    if not pending:
        print("All URLs already processed. Nothing to do.")
        return

    batch = pending[:BATCH_SIZE]
    
    # Load existing JSON records
    existing = []
    if OUTPUT_JSON.exists():
        try:
            existing = json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))
        except Exception:
            existing = []
    
    serial = max((r.get("serial", 0) for r in existing), default=0) + 1
    new_records = []
    new_texts = []
    ok_count = 0
    err_count = 0
    proxy_index = 0

    for url in batch:
        success = False
        attempts = 0
        max_attempts = len(PROXIES) * 2  # Try each proxy a couple times if needed
        
        while attempts < max_attempts and not success:
            proxy = get_next_proxy(proxy_index)
            print(f" [PROXY] Using {proxy.split('@')[1] if '@' in proxy else proxy}")
            try:
                rec = process_url(url, serial, proxy)
                new_records.append(rec)
                new_texts.append(format_record(rec))
                append_line(PROCESSED_FILE, url)
                serial += 1
                ok_count += 1
                success = True
                print(" [SAVED]\n")
            except Exception as e:
                attempts += 1
                proxy_index += 1
                print(f" [ERROR] Proxy attempt {attempts} failed: {str(e)}")
                time.sleep(2)  # Backoff
        
        if not success:
            err_count += 1
            msg = "All proxies failed"
            print(" [ERROR] " + msg + "\n")
            append_line(ERROR_FILE, url + " # " + msg)
        else:
            # Successful request, slow down
            time.sleep(DELAY)

    # Save JSON
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(existing + new_records, f, indent=2, ensure_ascii=False)

    # Append readable txt
    if new_texts:
        with open(OUTPUT_TXT, "a", encoding="utf-8") as f:
            f.write("\n\n".join(new_texts) + "\n\n")

    remaining = len(pending) - len(batch)
    print("=" * 60)
    print("Batch complete.")
    print(" OK : " + str(ok_count))
    print(" Errors : " + str(err_count))
    print(" Remaining : " + str(remaining))
    if remaining > 0:
        print(" Next run will continue automatically in 10 minutes.")
    else:
        print(" All URLs processed!")
    print("=" * 60)

if __name__ == "__main__":
    main()