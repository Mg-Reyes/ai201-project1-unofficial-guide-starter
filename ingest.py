"""Milestone 3 — Ingestion and Chunking.

Fetches every source in sources.py, cleans the raw content based on its type
(Reddit thread / website / PDF), then splits the cleaned text into overlapping
token-based chunks ready for embedding in Milestone 4.

Chunking parameters come straight from planning.md:
    Chunk size: 200 tokens
    Overlap:    50 tokens
Tokens are counted with the SAME tokenizer as the embedding model
(all-MiniLM-L6-v2), so a "200-token chunk" here means 200 tokens to the model.
That matters because MiniLM only reads the first 256 tokens of any input —
200 keeps every chunk safely inside that window.

Outputs:
    documents/clean/<id>_<type>.txt   one cleaned text file per source (for inspection)
    documents/chunks.jsonl            one JSON object per chunk, with metadata

Run:
    python ingest.py
"""

import io
import json
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

from sources import SOURCES

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"  # used for tokenizing

# Per-type chunk settings. planning.md specifies a single 200/50 strategy, so
# every type uses it here — but keeping them separate makes it easy to tune one
# source type (e.g. shrink Reddit chunks) without touching the others.
CHUNK_CONFIG = {
    "reddit":  {"chunk_size": 200, "overlap": 50},
    "website": {"chunk_size": 200, "overlap": 50},
    "pdf":     {"chunk_size": 200, "overlap": 50},
}
DEFAULT_CHUNK = {"chunk_size": 200, "overlap": 50}

# Reddit blocks the default python-requests user agent, so we set a descriptive one.
HEADERS = {
    "User-Agent": "AI201-UnofficialGuide/1.0 (educational project; contact: student)"
}
REQUEST_TIMEOUT = 30

DOCS_DIR = Path(__file__).parent / "documents"
CLEAN_DIR = DOCS_DIR / "clean"
RAW_DIR = DOCS_DIR / "raw"          # manually-saved Reddit .json files live here
CHUNKS_PATH = DOCS_DIR / "chunks.jsonl"


# ---------------------------------------------------------------------------
# Cleaning helpers
# ---------------------------------------------------------------------------

def normalize_whitespace(text: str) -> str:
    """Collapse runs of spaces/newlines so chunks aren't padded with noise."""
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)        # collapse spaces/tabs
    text = re.sub(r"\n{3,}", "\n\n", text)     # cap blank lines at one
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Per-type fetchers — each returns (title, clean_text)
# ---------------------------------------------------------------------------

def fetch_reddit(url: str, local_path: Path = None):
    """Pull a Reddit thread from its public .json data.

    Reddit blocks unauthenticated programmatic requests to its .json endpoint
    (HTTP 403), so the normal path is to read a JSON file you saved manually
    from your browser: documents/raw/<id>.json. If that file is missing we
    fall back to a live request, which will usually 403 — that's expected and
    just means you still need to save the file.

    The JSON gives us the post title, the self-text, and every comment body
    directly. We drop deleted/removed comments and the AutoModerator bot, which
    are pure noise for retrieval.
    """
    if local_path and local_path.exists():
        data = json.loads(local_path.read_text(encoding="utf-8"))
    else:
        json_url = url.rstrip("/") + ".json"
        resp = requests.get(json_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

    # data[0] = the post listing, data[1] = the comment listing
    post = data[0]["data"]["children"][0]["data"]
    title = post.get("title", "").strip()
    parts = [title]
    if post.get("selftext"):
        parts.append(post["selftext"].strip())

    def walk_comments(children):
        for child in children:
            if child.get("kind") != "t1":      # t1 = comment (skip "more" stubs)
                continue
            c = child["data"]
            body = (c.get("body") or "").strip()
            author = c.get("author") or ""
            if body and body not in ("[deleted]", "[removed]") and author != "AutoModerator":
                parts.append(f"Comment: {body}")
            replies = c.get("replies")
            if isinstance(replies, dict):       # nested replies
                walk_comments(replies["data"]["children"])

    walk_comments(data[1]["data"]["children"])
    return title, normalize_whitespace("\n\n".join(parts))


def fetch_website(url: str):
    """Fetch an HTML page and strip everything that isn't readable content."""
    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    # Remove non-content tags so nav menus / scripts don't pollute the chunks.
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form", "noscript"]):
        tag.decompose()

    title = soup.title.get_text(strip=True) if soup.title else url
    # Prefer <main> / <article> when present; fall back to the whole body.
    container = soup.find("main") or soup.find("article") or soup.body or soup
    text = container.get_text(separator="\n")
    return title, normalize_whitespace(text)


def fetch_pdf(url: str):
    """Download a PDF and extract its text page by page with pdfplumber."""
    import pdfplumber  # imported lazily so the script still loads without it

    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()

    pages = []
    with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            if page_text.strip():
                pages.append(page_text)
    title = url.rsplit("/", 1)[-1]
    return title, normalize_whitespace("\n\n".join(pages))


FETCHERS = {
    "reddit": fetch_reddit,
    "website": fetch_website,
    "pdf": fetch_pdf,
}


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def load_tokenizer():
    """Load the embedding model's tokenizer so token counts match the model."""
    from transformers import AutoTokenizer  # ships with sentence-transformers
    return AutoTokenizer.from_pretrained(EMBEDDING_MODEL)


def chunk_text(text: str, tokenizer, chunk_size: int, overlap: int):
    """Split text into overlapping windows of `chunk_size` tokens.

    Each new window starts `chunk_size - overlap` tokens after the previous one,
    so consecutive chunks share `overlap` tokens. The overlap keeps a fact that
    lands on a boundary (e.g. "$295 | per semester") from being lost.
    """
    ids = tokenizer.encode(text, add_special_tokens=False)
    if not ids:
        return []

    step = chunk_size - overlap
    chunks = []
    for start in range(0, len(ids), step):
        window = ids[start:start + chunk_size]
        if not window:
            break
        piece = tokenizer.decode(window, skip_special_tokens=True).strip()
        if piece:
            chunks.append(piece)
        if start + chunk_size >= len(ids):  # last window reached the end
            break
    return chunks


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def main():
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading tokenizer for", EMBEDDING_MODEL, "...")
    tokenizer = load_tokenizer()

    all_chunks = []
    per_source_counts = {}

    for src in SOURCES:
        sid, stype, url = src["id"], src["type"], src["url"]
        fetcher = FETCHERS.get(stype)
        if fetcher is None:
            print(f"[{sid}] SKIP — unknown type {stype!r}")
            continue

        try:
            if stype == "reddit":
                raw_path = RAW_DIR / f"{sid}.json"
                src_label = "local" if raw_path.exists() else "network (likely 403)"
                print(f"[{sid}] fetching ({stype}, {src_label}) {url}")
                title, clean = fetch_reddit(url, raw_path)
            else:
                print(f"[{sid}] fetching ({stype}) {url}")
                title, clean = fetcher(url)
        except Exception as exc:  # one bad source shouldn't kill the whole run
            print(f"[{sid}] ERROR fetching: {exc}")
            continue

        if not clean:
            print(f"[{sid}] WARNING — no text extracted, skipping")
            continue

        # Save the cleaned text so you can eyeball what the model will see.
        (CLEAN_DIR / f"{sid}_{stype}.txt").write_text(clean, encoding="utf-8")

        cfg = CHUNK_CONFIG.get(stype, DEFAULT_CHUNK)
        pieces = chunk_text(clean, tokenizer, cfg["chunk_size"], cfg["overlap"])
        per_source_counts[sid] = len(pieces)

        for i, piece in enumerate(pieces):
            all_chunks.append({
                "chunk_id": f"{sid}-{i}",
                "source_id": sid,
                "source_type": stype,
                "url": url,
                "title": title,
                "chunk_index": i,
                "token_count": len(tokenizer.encode(piece, add_special_tokens=False)),
                "char_count": len(piece),
                "text": piece,
            })
        print(f"[{sid}] -> {len(pieces)} chunks")
        time.sleep(1)  # be polite to Reddit / the web servers between requests

    # Write all chunks as JSON Lines (one object per line) for Milestone 4.
    with CHUNKS_PATH.open("w", encoding="utf-8") as f:
        for chunk in all_chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    print("\n" + "=" * 50)
    print(f"Sources processed: {len(per_source_counts)} / {len(SOURCES)}")
    print(f"Total chunks:      {len(all_chunks)}")
    print(f"Chunks per source: {per_source_counts}")
    print(f"Saved chunks ->    {CHUNKS_PATH}")
    print(f"Saved clean text-> {CLEAN_DIR}/")
    print("=" * 50)
    print("\nRecord the 'Total chunks' number in the Chunking Strategy "
          "section of planning.md / README.md.")
    
    print(all_chunks[0].get("text"))
    print(all_chunks[1].get("text"))
    print(all_chunks[2].get("text"))
    print(all_chunks[3].get("text"))
    print(all_chunks[4].get("text"))
    


if __name__ == "__main__":
    sys.exit(main())
