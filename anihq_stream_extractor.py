"""
anihq.cc Batch Extractor - v9.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INPUT  (two sources, both optional):
  • anihq_cc.txt          — one URL per line (local)
  • anihq2.json (remote)  — fetched from GitHub; supports:
        - plain JSON array  : ["url1", "url2", ...]
        - array of objects  : [{"url": "..."}, ...]
        - shell-output JSON : {"stdout": "url1\nurl2\n..."}

OUTPUT:
  • anihq_cc.json / anihq_cc_2.json …        — extracted stream data   (≤700 KB each)
  • anihq_cc_readable.txt / _2.txt …         — human-readable mirror   (≤700 KB each)
  • already_processed_url.txt / _2.txt …     — processed URL log       (≤700 KB each)
  • anihq_error_faced_url_list.txt / _2.txt  — failed URL log          (≤700 KB each)
"""

import re
import base64
import sys
import json
import time
import random
from pathlib import Path

# ── Dependency bootstrap ───────────────────────────────────
try:
    from curl_cffi import requests as crequests
    from bs4 import BeautifulSoup
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "curl_cffi", "beautifulsoup4", "-q"])
    from curl_cffi import requests as crequests
    from bs4 import BeautifulSoup

# ══════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════
BASE_DIR     = Path(__file__).parent
INPUT_TXT    = BASE_DIR / "anihq_cc.txt"
REMOTE_URL   = "https://raw.githubusercontent.com/srtfile/anihq_cc/refs/heads/main/anihq2.json"

BATCH_SIZE   = 500
DELAY        = 1.8                  # seconds between successful requests
MAX_SIZE     = 700 * 1024           # 700 KB — auto-split threshold

# Base names (suffix _2, _3 … added automatically when a file hits MAX_SIZE)
OUT_JSON     = "anihq_cc"
OUT_TXT      = "anihq_cc_readable"
PROC_BASE    = "already_processed_url"
ERR_BASE     = "anihq_error_faced_url_list"

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

# ══════════════════════════════════════════════════════════
#  SESSION
# ══════════════════════════════════════════════════════════
_SESSION = None

def get_session() -> crequests.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = crequests.Session(impersonate="chrome120")
        _SESSION.headers.update({"Accept-Language": "en-US,en;q=0.9"})
    return _SESSION

# ══════════════════════════════════════════════════════════
#  FILE HELPERS
# ══════════════════════════════════════════════════════════

def load_set(filepath) -> set:
    """Return all non-empty stripped lines from a file as a set."""
    p = Path(filepath)
    if not p.exists():
        return set()
    return {l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()}


def append_line(filepath, text: str):
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(text.strip() + "\n")


def get_output_path(base_name: str, ext: str) -> Path:
    """
    Return a Path for *base_name* + *ext* that is still under MAX_SIZE.
    If the current file is full (≥ MAX_SIZE) the counter is bumped.
    First file  → base_name.ext
    Second file → base_name_2.ext
    Third file  → base_name_3.ext  … and so on.
    """
    counter = 1
    while True:
        if counter == 1:
            path = BASE_DIR / f"{base_name}{ext}"
        else:
            path = BASE_DIR / f"{base_name}_{counter}{ext}"
        if not path.exists() or path.stat().st_size < MAX_SIZE:
            return path
        counter += 1


def load_all_processed() -> set:
    """Collect every already-processed / errored URL across all split files."""
    combined: set = set()
    for base in (PROC_BASE, ERR_BASE):
        counter = 1
        while True:
            if counter == 1:
                p = BASE_DIR / f"{base}.txt"
            else:
                p = BASE_DIR / f"{base}_{counter}.txt"
            if not p.exists():
                break
            combined |= load_set(p)
            counter += 1
    return combined

# ══════════════════════════════════════════════════════════
#  REMOTE JSON LOADER  (handles all known formats)
# ══════════════════════════════════════════════════════════

def _extract_urls_from_raw(text: str) -> list:
    """
    Parse URLs out of *text* regardless of format:
      1. JSON array of strings / objects with "url" key
      2. JSON object with "stdout" key containing newline-separated URLs
      3. Plain text, one URL per line
    """
    urls = []

    # ── Try JSON first ──────────────────────────────────
    stripped = text.strip()
    if stripped and stripped[0] in ("{", "["):
        try:
            data = json.loads(stripped)

            # Format A: {"stdout": "url1\nurl2\n..."}  ← GitHub Actions shell output
            if isinstance(data, dict):
                stdout_blob = data.get("stdout", "")
                if stdout_blob:
                    for line in stdout_blob.splitlines():
                        line = line.strip()
                        if line.startswith("http"):
                            urls.append(line)
                    if urls:
                        return urls
                # Fallback: any string value that looks like a URL
                for v in data.values():
                    if isinstance(v, str) and v.startswith("http"):
                        urls.append(v)
                return urls

            # Format B: ["url1", "url2", ...]
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, str) and item.strip():
                        urls.append(item.strip())
                    elif isinstance(item, dict) and "url" in item:
                        urls.append(item["url"])
                return urls

        except json.JSONDecodeError:
            pass  # fall through to plain-text parser

    # ── Plain text fallback ─────────────────────────────
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("http"):
            urls.append(line)

    return urls


def load_remote_urls() -> list:
    print("🔄 Fetching remote JSON (may be large – please wait)…")
    session = get_session()
    max_attempts = 5

    for attempt in range(1, max_attempts + 1):
        try:
            # stream=False is fine; curl_cffi buffers internally
            r = session.get(
                REMOTE_URL,
                timeout=120,          # generous timeout for large files
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Cache-Control": "no-cache",
                },
            )
            r.raise_for_status()

            raw = r.text                        # get text regardless of content-type
            if not raw or not raw.strip():
                raise ValueError("Empty response body")

            urls = _extract_urls_from_raw(raw)
            if not urls:
                raise ValueError("No URLs could be parsed from the response")

            print(f"✅ Loaded {len(urls):,} URLs from remote source")
            return urls

        except Exception as exc:
            wait = 8 * attempt
            print(f"   Attempt {attempt}/{max_attempts} failed: {exc}")
            if attempt < max_attempts:
                print(f"   Retrying in {wait}s…")
                time.sleep(wait)

    print("⚠️  All remote fetch attempts failed. Continuing with local file only.")
    return []

# ══════════════════════════════════════════════════════════
#  PARSING HELPERS
# ══════════════════════════════════════════════════════════

def decode_embed_id(raw: str):
    """Base64-decode a 'label:url' embed-id attribute."""
    try:
        parts = raw.split(":", 1)
        label = base64.b64decode(parts[0] + "==").decode("utf-8", errors="ignore").strip()
        url   = (
            base64.b64decode(parts[1] + "==").decode("utf-8", errors="ignore").strip()
            if len(parts) > 1 else ""
        )
        return label, url
    except Exception:
        return "?", ""


def parse_url_meta(url: str) -> dict:
    slug  = url.rstrip("/").split("/watch/")[-1]
    ep_m  = re.search(r"-episode-(\d+)", slug)
    ep    = ep_m.group(1) if ep_m else "?"
    lang  = "Dub" if "dubbed" in slug.lower() else "Sub"
    name  = re.split(r"-episode-", slug, flags=re.IGNORECASE)[0].replace("-", " ").title()
    return {"ep": ep, "lang": lang, "name": name}


def get_cdn_url(voe_url: str, proxy: str) -> str:
    try:
        r = get_session().get(
            voe_url,
            timeout=20,
            headers={"Referer": "https://anihq.cc/"},
            proxies={"http": proxy, "https": proxy},
        )
        m = re.search(
            r"window\.location\.href\s*=\s*['\"]([^'\"]+/e/[a-z0-9]+)['\"]", r.text
        )
        if m:
            cdn = m.group(1)
            return ("https:" + cdn) if cdn.startswith("//") else cdn
    except Exception as exc:
        print(f"   [WARN] voe fetch: {exc}")
    return ""


def extract_m3u8(text: str) -> list:
    found = re.findall(r'https?://[^\s\'"<>]+\.m3u8[^\s\'"<>]*', text)
    for key in ("file", "src", "hls", "source", "url"):
        found += re.findall(
            r'["\']?' + key + r'["\']?\s*[:=]\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
            text, re.IGNORECASE,
        )
    seen, out = set(), []
    for u in found:
        u = u.rstrip('.,;:!?)]}\\"\'')
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out

# ══════════════════════════════════════════════════════════
#  CORE PROCESSING
# ══════════════════════════════════════════════════════════

def process_url(page_url: str, serial: int, proxy: str) -> dict:
    meta = parse_url_meta(page_url)
    print(f"[{serial}] {page_url}")
    print(f"   {meta['name']}  |  Ep {meta['ep']}  |  {meta['lang']}")

    record = {
        "serial":      serial,
        "url":         page_url,
        "ep":          meta["ep"],
        "language":    meta["lang"],
        "anime_name":  meta["name"],
        "stream_urls": [],
        "m3u8_urls":   [],
    }

    time.sleep(random.uniform(1.2, 2.5))

    r = get_session().get(
        page_url, timeout=25,
        proxies={"http": proxy, "https": proxy},
    )
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
        print(f"   [{label}]  voe={voe_url}  cdn={cdn_url or '(none)'}")

    record["m3u8_urls"] = extract_m3u8(r.text)
    return record


def format_record(rec: dict) -> str:
    lines = [
        f"Serial No:{rec['serial']}",
        f"1.url           : {rec['url']}",
        f"2.ep            : {rec['ep']}   Language: {rec['language']}",
        f"3.anime/movie   : {rec['anime_name']}",
    ]
    for i, u in enumerate(rec["stream_urls"], 1):
        lines.append(f"{3 + i}.stream_url_{i} : {u}")
    offset = 3 + len(rec["stream_urls"])
    for i, u in enumerate(rec["m3u8_urls"], 1):
        lines.append(f"{offset + i}.m3u8_url_{i}  : {u}")
    lines.append("─" * 84)
    return "\n".join(lines)


def get_next_proxy(idx: int) -> str:
    return PROXIES[idx % len(PROXIES)]

# ══════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════

def main():
    # ── 1. Collect all input URLs ──────────────────────────
    local_urls: list = []
    if INPUT_TXT.exists():
        local_urls = [
            l.strip()
            for l in INPUT_TXT.read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]
        print(f"📄 Local file   : {len(local_urls):,} lines loaded from {INPUT_TXT.name}")
    else:
        print(f"ℹ️  No local file found at {INPUT_TXT.name}")

    remote_urls = load_remote_urls()

    # Merge, deduplicate, keep only valid watch-page URLs
    all_urls = local_urls + remote_urls
    valid_urls = list(dict.fromkeys(
        u for u in all_urls
        if u.startswith("http") and "/watch/" in u
    ))

    # ── 2. Skip already-processed URLs ────────────────────
    skip_set = load_all_processed()
    pending  = [u for u in valid_urls if u not in skip_set]

    print("=" * 70)
    print(f"  Total unique URLs : {len(valid_urls):,}")
    print(f"  Already processed : {len(skip_set):,}")
    print(f"  Pending           : {len(pending):,}")
    print(f"  This batch        : {min(BATCH_SIZE, len(pending)):,}")
    print("=" * 70)

    if not pending:
        print("✅ All URLs already processed — nothing to do.")
        return

    batch = pending[:BATCH_SIZE]

    # ── 3. Resolve output file paths ──────────────────────
    json_path  = get_output_path(OUT_JSON,  ".json")
    txt_path   = get_output_path(OUT_TXT,   ".txt")
    proc_path  = get_output_path(PROC_BASE, ".txt")
    err_path   = get_output_path(ERR_BASE,  ".txt")

    # Load existing JSON records (so we append, not overwrite)
    existing: list = []
    if json_path.exists():
        try:
            existing = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            existing = []

    serial      = max((r.get("serial", 0) for r in existing), default=0) + 1
    new_records = []
    new_texts   = []
    ok_count    = err_count = 0
    proxy_idx   = 0

    # ── 4. Process batch ──────────────────────────────────
    for url in batch:
        success      = False
        attempts     = 0
        max_attempts = len(PROXIES) * 2

        while attempts < max_attempts and not success:
            proxy = get_next_proxy(proxy_idx)
            proxy_display = proxy.split("@")[1] if "@" in proxy else proxy
            print(f"   [PROXY] {proxy_display}")
            try:
                rec = process_url(url, serial, proxy)
                new_records.append(rec)
                new_texts.append(format_record(rec))
                append_line(proc_path, url)
                serial  += 1
                ok_count += 1
                success  = True
                print("   [SAVED] ✓\n")
            except Exception as exc:
                attempts  += 1
                proxy_idx += 1
                print(f"   [ERROR] {exc}")
                time.sleep(2)

        if not success:
            err_count += 1
            append_line(err_path, f"{url} # all proxies failed")
            print("   [FAILED] All proxies exhausted\n")
        else:
            # Check if output files have crossed the size limit mid-batch
            json_path = get_output_path(OUT_JSON,  ".json")
            txt_path  = get_output_path(OUT_TXT,   ".txt")
            proc_path = get_output_path(PROC_BASE, ".txt")
            err_path  = get_output_path(ERR_BASE,  ".txt")
            time.sleep(DELAY)

    # ── 5. Persist results ────────────────────────────────
    # JSON — resolve path again in case batch pushed us over the limit
    final_json = get_output_path(OUT_JSON, ".json")
    existing2: list = []
    if final_json.exists():
        try:
            existing2 = json.loads(final_json.read_text(encoding="utf-8"))
        except Exception:
            existing2 = []
    with open(final_json, "w", encoding="utf-8") as f:
        json.dump(existing2 + new_records, f, indent=2, ensure_ascii=False)

    # Readable TXT
    if new_texts:
        final_txt = get_output_path(OUT_TXT, ".txt")
        with open(final_txt, "a", encoding="utf-8") as f:
            f.write("\n\n".join(new_texts) + "\n\n")

    print("=" * 70)
    print(f"  Batch complete  →  ✅ OK: {ok_count}   ❌ Errors: {err_count}")
    print("=" * 70)


if __name__ == "__main__":
    main()
