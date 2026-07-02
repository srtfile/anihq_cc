"""
anihq.cc Batch Extractor - v8.3
- Loads URLs from anihq_cc.txt + remote anihq2.json (large file support)
- Processes max 500 URLs per run
- Auto creates new files when size > 500KB
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

# ── CONFIG ─────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
INPUT_FILE = BASE_DIR / "anihq_cc.txt"
REMOTE_JSON_URL = "https://raw.githubusercontent.com/srtfile/anihq_cc/refs/heads/main/anihq2.json"

BATCH_SIZE = 500
DELAY = 1.8
MAX_FILE_SIZE = 500 * 1024  # 500 KB

# Output file bases
OUTPUT_JSON_BASE = "anihq_cc"
OUTPUT_TXT_BASE = "anihq_cc_readable"
PROCESSED_BASE = "already_processed_url"
ERROR_BASE = "anihq_error_faced_url_list"

# Proxy list
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
        SESSION.headers.update({"Accept-Language": "en-US,en;q=0.9"})
    return SESSION

# ── File Helpers ───────────────────────────────────────────
def load_set(filepath):
    p = Path(filepath)
    if not p.exists():
        return set()
    return set(l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip())

def append_line(filepath, text):
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(text.strip() + "\n")

def get_next_output_file(base_name, ext=".txt"):
    counter = 1
    while True:
        path = BASE_DIR / f"{base_name}{ext}" if counter == 1 else BASE_DIR / f"{base_name}_{counter}{ext}"
        if not path.exists() or path.stat().st_size < MAX_FILE_SIZE:
            return path
        counter += 1

# ── Remote JSON Loader (Fixed for large file) ─────────────
def load_remote_urls():
    print("🔄 Fetching remote large JSON file...")
    for attempt in range(1, 6):
        try:
            session = get_session()
            r = session.get(REMOTE_JSON_URL, timeout=90)
            r.raise_for_status()
            data = r.json()
            
            urls = []
            for item in data:
                if isinstance(item, dict) and "url" in item:
                    urls.append(item["url"])
                elif isinstance(item, str) and item.strip():
                    urls.append(item.strip())
            
            print(f"✅ Successfully loaded {len(urls)} URLs from remote JSON")
            return urls
        except Exception as e:
            print(f"   Attempt {attempt}/5 failed: {e}")
            if attempt < 5:
                time.sleep(8 * attempt)
    print("⚠️ Could not load remote JSON. Continuing with local file only.")
    return []

# ── Parsing Helpers ────────────────────────────────────────
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
    found = re.findall(r'https?://[^\s\'"<>]+\.m3u8[^\s\'"<>]*', text)
    for key in ("file", "src", "hls", "source", "url"):
        found += re.findall(r'["\']?' + key + r'["\']?\s*[:=]\s*["\']([^"\']+\.m3u8[^"\']*)["\']', text, re.IGNORECASE)
    seen, out = set(), []
    for u in found:
        u = u.rstrip('.,;:!?)]}\\"\'')
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out

# ── Core Function ──────────────────────────────────────────
def process_url(page_url, serial, proxy):
    meta = parse_url_meta(page_url)
    print(f"[{serial}] {page_url}")
    print(f" {meta['name']} | Ep:{meta['ep']} | {meta['lang']}")
    
    record = {
        "serial": serial,
        "url": page_url,
        "ep": meta["ep"],
        "language": meta["lang"],
        "anime_name": meta["name"],
        "stream_urls": [],
        "m3u8_urls": [],
    }
    
    time.sleep(random.uniform(1.2, 2.5))
    
    session = get_session()
    r = session.get(page_url, timeout=25, proxies={"http": proxy, "https": proxy})
    r.raise_for_status()
    
    soup = BeautifulSoup(r.text, "html.parser")
    for btn in soup.find_all(attrs={"data-embed-id": True}):
        label, voe_url = decode_embed_id(btn.get("data-embed-id", ""))
        if not voe_url:
            continue
        if voe_url not in record["stream_urls"]:
            record["stream_urls"].append(voe_url)
        cdn_url = get_cdn_url(voe_url, proxy)
        if cdn_url and cdn_url not in record["stream_urls"]:
            record["stream_urls"].append(cdn_url)
        print(f" [{label}] voe={voe_url} cdn={cdn_url or '(none)'}")
    
    record["m3u8_urls"] = extract_m3u8(r.text)
    return record

def format_record(rec):
    lines = [
        f"Serial No:{rec['serial']}",
        f"1.url :{rec['url']}",
        f"2:ep:{rec['ep']} Language:{rec['language']}",
        f"3.anime/movie_name: {rec['anime_name']}",
    ]
    for i, u in enumerate(rec["stream_urls"], 1):
        lines.append(f"{3 + i}.stream url_{i}:{u}")
    offset = 3 + len(rec["stream_urls"])
    for i, u in enumerate(rec["m3u8_urls"], 1):
        lines.append(f"{offset + i}.m3u8_url_{i}:{u}")
    lines.append("=" * 84)
    return "\n".join(lines)

def get_next_proxy(idx):
    return PROXIES[idx % len(PROXIES)]

# ── MAIN ───────────────────────────────────────────────────
def main():
    # Load URLs
    local_urls = []
    if INPUT_FILE.exists():
        local_urls = [l.strip() for l in INPUT_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
    
    remote_urls = load_remote_urls()
    all_urls = local_urls + remote_urls
    valid_urls = list(dict.fromkeys([u for u in all_urls if "/watch/" in u and u.startswith("http")]))
    
    # Get log files
    processed_path = get_next_output_file(PROCESSED_BASE, ".txt")
    error_path = get_next_output_file(ERROR_BASE, ".txt")
    
    skip_set = load_set(processed_path) | load_set(error_path)
    pending = [u for u in valid_urls if u not in skip_set]
    
    print("=" * 70)
    print(f"Total URLs     : {len(valid_urls)}")
    print(f"Pending        : {len(pending)}")
    print(f"Batch Size     : {min(BATCH_SIZE, len(pending))}")
    print("=" * 70)

    if not pending:
        print("All URLs already processed!")
        return

    batch = pending[:BATCH_SIZE]
    
    # Output files
    json_path = get_next_output_file(OUTPUT_JSON_BASE, ".json")
    txt_path = get_next_output_file(OUTPUT_TXT_BASE, ".txt")
    
    # Load existing data
    existing = []
    if json_path.exists():
        try:
            existing = json.loads(json_path.read_text(encoding="utf-8"))
        except:
            existing = []
    
    serial = max((r.get("serial", 0) for r in existing), default=0) + 1
    new_records = []
    new_texts = []
    ok_count = err_count = 0
    proxy_index = 0

    for url in batch:
        success = False
        attempts = 0
        max_attempts = len(PROXIES) * 2
        
        while attempts < max_attempts and not success:
            proxy = get_next_proxy(proxy_index)
            print(f" [PROXY] {proxy.split('@')[1] if '@' in proxy else proxy}")
            try:
                rec = process_url(url, serial, proxy)
                new_records.append(rec)
                new_texts.append(format_record(rec))
                append_line(processed_path, url)
                serial += 1
                ok_count += 1
                success = True
                print(" [SAVED]\n")
            except Exception as e:
                attempts += 1
                proxy_index += 1
                print(f" [ERROR] {str(e)}")
                time.sleep(2)
        
        if not success:
            err_count += 1
            append_line(error_path, f"{url} # All proxies failed")
            print(" [ERROR] All proxies failed\n")
        else:
            time.sleep(DELAY)

    # Save results
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(existing + new_records, f, indent=2, ensure_ascii=False)

    if new_texts:
        with open(txt_path, "a", encoding="utf-8") as f:
            f.write("\n\n".join(new_texts) + "\n\n")

    print("=" * 70)
    print(f"Batch Finished → OK: {ok_count} | Errors: {err_count}")
    print("=" * 70)

if __name__ == "__main__":
    main()