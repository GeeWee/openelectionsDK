#!/usr/bin/env python3
# scrape_candidates_venstre.py
#
# Run:
#   python3 scrape_candidates_venstre.py --input venstre-candidates.html --format json --output output/candidates_venstre
#
# Or with your uploaded file path (from this chat environment):
#   python3 scrape_candidates_venstre.py --input /mnt/data/venstre-candidates.html --format json --output output/candidates_venstre

import os
import sys
import argparse
import json
import csv
import time
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from models import Candidate
from utils import find_most_similar_storkreds


EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)


def _load_html(filepath: str) -> str:
    with open(filepath, "r", encoding="utf-8") as f:
        html = f.read()
    print(f"Loaded file: {filepath} ({len(html)} chars)")
    return html


def _extract_person_urls_from_list_html(html: str) -> list[str]:
    """
    Extracts unique candidate URLs from the list file.

    The list contains anchors like:
      <a href="https://www.venstre.dk/personer/amanda-heitmann">
    (example present in the uploaded list HTML :contentReference[oaicite:2]{index=2})

    We deliberately filter to /personer/ pages.
    """
    soup = BeautifulSoup(html, "html.parser")

    urls = set()
    for a in soup.select('a[href^="https://www.venstre.dk/personer/"]'):
        href = (a.get("href") or "").strip()
        if not href:
            continue

        # Normalize: remove trailing slashes
        href = href.rstrip("/")
        # Keep only the /personer/<slug> form
        path = urlparse(href).path
        if path.startswith("/personer/") and len(path.split("/")) >= 3:
            urls.add(href)

    urls = sorted(urls)
    print(f"Found {len(urls)} unique candidate URLs in list file")
    return urls


def _get_soup(url: str, headers: dict, timeout: int = 30) -> BeautifulSoup:
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def _extract_labeled_value(container: BeautifulSoup, label_text: str) -> Optional[str]:
    """
    Finds blocks like:
      <div><p class="font-bold mb-0">Storkreds:</p><p>Københavns Omegn</p></div>

    Returns the value text.
    """
    # Find a <p> whose text is exactly label_text (or starts with it)
    label_p = None
    for p in container.select("p"):
        t = p.get_text(" ", strip=True)
        if t == label_text or t.startswith(label_text):
            label_p = p
            break

    if not label_p:
        return None

    parent = label_p.parent
    if not parent:
        return None

    # Try: value is the next <p> sibling inside same parent
    # (common structure: label <p> then value <p>)
    ps = parent.find_all("p", recursive=False)
    if len(ps) >= 2:
        # label is usually first; value second
        val = ps[1].get_text(" ", strip=True)
        return val if val else None

    # If email: value might be an <a mailto:> within the parent
    mailto = parent.select_one('a[href^="mailto:"]')
    if mailto and mailto.get("href"):
        return mailto["href"].replace("mailto:", "").strip()

    return None


def _extract_candidate_from_profile(url: str, soup: BeautifulSoup) -> dict:
    """
    Extracts:
      - name: h1.title2...
      - additional_info: first h3.text-lg
      - storkreds: label "Storkreds:"
      - email: label "Email:" (mailto)
    """
    # Name
    name = None
    h1 = soup.select_one("h1.title2")
    if h1:
        name = " ".join(h1.get_text(" ", strip=True).split())

    # Additional info
    additional_info = None
    h3 = soup.select_one("h3.text-lg")
    if h3:
        additional_info = " ".join(h3.get_text(" ", strip=True).split())
        # clean &nbsp; artifacts if any appear as \xa0
        additional_info = additional_info.replace("\xa0", " ").strip()

    # Find storkreds/email using labeled blocks
    storkreds_raw = _extract_labeled_value(soup, "Storkreds:")
    email = _extract_labeled_value(soup, "Email:")

    # Fallbacks (in case label blocks vary slightly)
    if not email:
        mailto = soup.select_one('a[href^="mailto:"]')
        if mailto and mailto.get("href"):
            email = mailto["href"].replace("mailto:", "").strip()
        else:
            m = EMAIL_RE.search(soup.get_text(" ", strip=True))
            if m:
                email = m.group(0)

    return {
        "url": url,
        "name": name,
        "email": email,
        "storkreds_raw": storkreds_raw,
        "additional_info": additional_info,
    }


def scrape_candidates() -> int:
    parser = argparse.ArgumentParser(description="Scrape Venstre candidates from local list HTML + profile pages")
    parser.add_argument("--input", default="venstre-candidates.html", help="Path to saved list HTML from browser")
    parser.add_argument("--format", choices=["json", "csv"], default="json", help="Output format (json or csv)")
    parser.add_argument("--output", default="output/candidates_venstre", help="Output file path (without extension)")
    parser.add_argument("--sleep", type=float, default=0.2, help="Sleep between profile requests (seconds)")
    parser.add_argument("--max_candidates", type=int, default=None, help="Optional cap (debug)")
    args = parser.parse_args()

    print("STARTING scrape_candidates()")

    # Output dir
    output_dir = os.path.dirname(args.output)
    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
    output_file = f"{args.output}.{args.format}"

    # Load list file & get URLs
    html = _load_html(args.input)
    urls = _extract_person_urls_from_list_html(html)

    if args.max_candidates is not None:
        urls = urls[: args.max_candidates]
        print(f"DEBUG: limiting to first {len(urls)} candidates")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
        )
    }

    candidates: list[Candidate] = []
    seen = set()

    for idx, url in enumerate(urls, 1):
        try:
            print(f"[{idx}/{len(urls)}] Fetching: {url}")
            soup = _get_soup(url, headers=headers)

            row = _extract_candidate_from_profile(url, soup)

            name = (row.get("name") or "").strip()
            email = row.get("email") or None
            storkreds_raw = row.get("storkreds_raw") or None
            additional_info = row.get("additional_info") or None

            storkreds = find_most_similar_storkreds(storkreds_raw) if storkreds_raw else None

            key = (name.lower(), (email or "").lower(), (storkreds or "").lower())
            if key in seen:
                continue
            seen.add(key)

            c = Candidate(
                name=name,
                party="V",
                email=email,
                storkreds=storkreds,
                additional_info=additional_info,
            )
            candidates.append(c)
            print(f"Candidate: {c.name} - {c.email} - {c.storkreds}")

            if args.sleep:
                time.sleep(args.sleep)

        except Exception as e:
            print(f"ERROR on {url}: {e}")

    if not candidates:
        print("No candidates parsed.")
        return 1

    # Save
    if args.format == "json":
        data = [c.model_dump() for c in candidates]
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    else:
        with open(output_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["name", "email", "storkreds", "additional_info", "party"]
            )
            writer.writeheader()
            writer.writerows([c.model_dump() for c in candidates])

    print(f"\nSuccessfully saved {len(candidates)} candidates to {output_file}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(scrape_candidates())
    except Exception:
        import traceback
        traceback.print_exc()
        raise