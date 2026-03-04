#!/usr/bin/env python3
# scrape_candidates_alternativet.py
#
# Run:
#   python3 scrape_candidates_alternativet.py --input alternativet.html --format json --output output/candidates_alternativet
# In this chat environment, your uploaded file is at:
#   /mnt/data/alternativet.html

import os
import sys
import argparse
import json
import csv
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from models import Candidate
from utils import find_most_similar_storkreds
import re

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)

def decode_cfemail(cfhex: str) -> str | None:
    """
    Cloudflare email protection decoder.
    cfhex is the hex string from data-cfemail (or from the href hash part).
    """
    try:
        cfhex = cfhex.strip()
        key = int(cfhex[:2], 16)
        chars = []
        for i in range(2, len(cfhex), 2):
            b = int(cfhex[i:i+2], 16) ^ key
            chars.append(chr(b))
        email = "".join(chars)
        return email if "@" in email else None
    except Exception:
        return None


def _load_soup_from_file(filepath: str) -> BeautifulSoup:
    with open(filepath, "r", encoding="utf-8") as f:
        html = f.read()
    print(f"Loaded file: {filepath} ({len(html)} chars)")
    return BeautifulSoup(html, "html.parser")


def _get_soup(url: str, headers: dict, timeout: int = 30) -> BeautifulSoup:
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def _clean(s: str) -> str:
    return " ".join((s or "").replace("\xa0", " ").split()).strip()


def _extract_email_from_profile(profile_soup: BeautifulSoup) -> str | None:
    # 1) Cloudflare protected span: <span class="__cf_email__" data-cfemail="...">
    cf_span = profile_soup.select_one("span.__cf_email__[data-cfemail]")
    if cf_span:
        cfhex = (cf_span.get("data-cfemail") or "").strip()
        email = decode_cfemail(cfhex)
        if email:
            return email

    # 2) Cloudflare protected link: href="/cdn-cgi/l/email-protection#..."
    for a in profile_soup.select('a[href*="/cdn-cgi/l/email-protection"]'):
        href = (a.get("href") or "").strip()
        if "#" in href:
            cfhex = href.split("#", 1)[1]
            email = decode_cfemail(cfhex)
            if email:
                return email
        # sometimes cfhex is stored as data-cfemail on the <a>
        cfhex2 = (a.get("data-cfemail") or "").strip()
        if cfhex2:
            email = decode_cfemail(cfhex2)
            if email:
                return email

    # 3) Normal mailto (if present)
    for a in profile_soup.select('a[href^="mailto:"]'):
        href = (a.get("href") or "").strip()
        email = href.split("mailto:", 1)[1].split("?", 1)[0].strip()
        if email:
            return email

    # 4) Regex fallback (rarely works when CF protection is used)
    m = EMAIL_RE.search(profile_soup.get_text(" ", strip=True))
    return m.group(0) if m else None

def _extract_candidates_from_list(list_soup: BeautifulSoup) -> list[dict]:
    """
    From the list file:
      - each storkreds is a <section class="team-section ..."> with an <h2> header
      - each candidate is in a "team-member-card" with:
          <a href="/personer/folketingskandidater/...">
          <h3 ...>NAME</h3>
          <p class="text-gray-600 text-sm">...bio...</p>  (optional)
    """
    rows: list[dict] = []

    sections = list_soup.select("section.team-section")
    print(f"Found {len(sections)} storkreds sections")

    for sec in sections:
        h2 = sec.select_one("h2")
        storkreds_raw = _clean(h2.get_text(" ", strip=True)) if h2 else None
        if not storkreds_raw:
            continue

        # Normalize to canonical storkreds names using your helper
        storkreds = find_most_similar_storkreds(storkreds_raw) if storkreds_raw else None

        cards = sec.select("div.team-member-card")
        print(f"  {storkreds_raw}: {len(cards)} candidate cards")

        for card in cards:
            # profile link (relative)
            a = card.select_one('a[href^="/personer/folketingskandidater/"]')
            href = (a.get("href") or "").strip() if a else ""
            if not href:
                continue

            # name
            h3 = card.select_one("h3")
            name = _clean(h3.get_text(" ", strip=True)) if h3 else ""
            if not name:
                continue

            # additional info (bio snippet) if present
            bio = None
            p = card.select_one('p.text-gray-600.text-sm')
            if p:
                bio = _clean(p.get_text(" ", strip=True)) or None

            rows.append(
                {
                    "name": name,
                    "profile_path": href,
                    "storkreds": storkreds,
                    "storkreds_raw": storkreds_raw,
                    "additional_info": bio,
                }
            )

    return rows


def scrape_candidates() -> int:
    parser = argparse.ArgumentParser(description="Scrape Alternativet folketingskandidater (local list + profile pages)")
    parser.add_argument("--input", default="alternativet.html", help="Path to saved list HTML from browser")
    parser.add_argument("--base-url", default="https://alternativet.dk", help="Base domain for candidate pages")
    parser.add_argument("--format", choices=["json", "csv"], default="json", help="Output format")
    parser.add_argument("--output", default="output/candidates_alternativet", help="Output file path (no extension)")
    parser.add_argument("--party", default="Å", help="Party code to store in Candidate.party (default: Å)")
    parser.add_argument("--sleep", type=float, default=0.2, help="Sleep between profile requests (seconds)")
    parser.add_argument("--max_candidates", type=int, default=None, help="Optional cap (debug)")
    args = parser.parse_args()

    print("STARTING scrape_candidates()")

    output_dir = os.path.dirname(args.output)
    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
    output_file = f"{args.output}.{args.format}"

    list_soup = _load_soup_from_file(args.input)
    rows = _extract_candidates_from_list(list_soup)

    if args.max_candidates is not None:
        rows = rows[: args.max_candidates]
        print(f"DEBUG: limiting to first {len(rows)} candidates")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
        )
    }

    candidates: list[Candidate] = []
    seen = set()

    for idx, row in enumerate(rows, 1):
        name = row["name"]
        profile_url = urljoin(args.base_url, row["profile_path"])
        storkreds = row.get("storkreds")
        additional_info = row.get("additional_info")

        try:
            print(f"[{idx}/{len(rows)}] Fetching profile: {profile_url}")
            psoup = _get_soup(profile_url, headers=headers)

            email = _extract_email_from_profile(psoup)

            key = (name.lower(), (email or "").lower(), (storkreds or "").lower())
            if key in seen:
                continue
            seen.add(key)

            c = Candidate(
                name=name,
                party=args.party,
                email=email,
                storkreds=storkreds,
                additional_info=additional_info,
            )
            candidates.append(c)
            print(f"Candidate: {c.name} - {c.email} - {c.storkreds}")

            if args.sleep:
                time.sleep(args.sleep)

        except Exception as e:
            print(f"ERROR on {profile_url}: {e}")

    if not candidates:
        print("No candidates parsed.")
        return 1

    # Save results
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