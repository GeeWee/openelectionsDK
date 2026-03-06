#!/usr/bin/env python3
# scrape_candidates_df.py
#
# DF candidates:
#   list:   https://danskfolkeparti.dk/kandidater/  (+ /page/2/, /page/3/ ...)
#   profile: https://danskfolkeparti.dk/kandidater/<slug>/
#
# Extracts: Name, Email (from profile contact list), Storkreds (normalized)
#
# Run:
#   python3 scrape_candidates_df.py --format json --output output/candidates_df
#   python3 scrape_candidates_df.py --format csv  --output output/candidates_df

import os
import sys
import argparse
import json
import csv
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from models import Candidate


EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)

ALLOWED_STORKREDS = [
    "Københavns Omegns",
    "København",
    "Nordsjælland",
    "Bornholm",
    "Sjælland",
    "Fyn",
    "Sydjylland",
    "Østjylland",
    "Vestjylland",
    "Nordjylland",
]


def _clean(s: str) -> str:
    return " ".join((s or "").replace("\xa0", " ").split()).strip()


def normalize_storkreds_df(raw: Optional[str]) -> Optional[str]:
    """
    Normalize storkreds to EXACTLY one of:
      [
        "Københavns Omegns", "København", "Nordsjælland", "Bornholm", "Sjælland",
        "Fyn", "Sydjylland", "Østjylland", "Vestjylland", "Nordjylland"
      ]

    Rules:
      - Remove "Storkreds"
      - Remove trailing 's' EXCEPT for "Københavns Omegns"
    """
    if not raw:
        return None

    s = _clean(raw)
    s_low = s.lower().replace("storkreds", "").strip()
    s_low = " ".join(s_low.split())

    # Special case
    if "københavns omegn" in s_low or "koebenhavns omegn" in s_low:
        return "Københavns Omegns"

    # Remove trailing genitive 's' for the rest
    if s_low.endswith("s"):
        s_low = s_low[:-1].strip()

    if "københavn" in s_low or "koebenhavn" in s_low:
        return "København"
    if "nordsjælland" in s_low or "nordsjaelland" in s_low:
        return "Nordsjælland"
    if "bornholm" in s_low:
        return "Bornholm"
    if "sjælland" in s_low or "sjaelland" in s_low:
        return "Sjælland"
    if "fyn" in s_low:
        return "Fyn"
    if "sydjylland" in s_low:
        return "Sydjylland"
    if "østjylland" in s_low or "oestjylland" in s_low:
        return "Østjylland"
    if "vestjylland" in s_low:
        return "Vestjylland"
    if "nordjylland" in s_low:
        return "Nordjylland"

    fallback = _clean(s_low).title()
    return fallback or None


def decode_cfemail(cfhex: str) -> Optional[str]:
    """
    Cloudflare email protection decoder.
    """
    try:
        cfhex = (cfhex or "").strip()
        if len(cfhex) < 4:
            return None
        key = int(cfhex[:2], 16)
        chars = []
        for i in range(2, len(cfhex), 2):
            b = int(cfhex[i:i + 2], 16) ^ key
            chars.append(chr(b))
        email = "".join(chars)
        return email if "@" in email else None
    except Exception:
        return None


def _get_soup(url: str, headers: dict, timeout: int = 30) -> BeautifulSoup:
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def _extract_email_from_profile(profile_soup: BeautifulSoup) -> Optional[str]:
    """
    Email is on the profile page in:
      <ul class="member-single__contacts">
        ...
        <a href="mailto:dfalah@ft.dk"> ... </a>
    """
    # Preferred: inside the contacts list
    for a in profile_soup.select('ul.member-single__contacts a[href^="mailto:"]'):
        href = (a.get("href") or "").strip()
        email = href.replace("mailto:", "").split("?", 1)[0].strip()
        if email:
            return email

    # Fallback: any mailto on the page
    a = profile_soup.select_one('a[href^="mailto:"]')
    if a and a.get("href"):
        return a["href"].replace("mailto:", "").split("?", 1)[0].strip()

    # Fallback: CF protected span/link variants
    span = profile_soup.select_one("span.__cf_email__[data-cfemail]")
    if span:
        return decode_cfemail(span.get("data-cfemail"))

    for a in profile_soup.select('a[href*="/cdn-cgi/l/email-protection"]'):
        href = (a.get("href") or "").strip()
        if "#" in href:
            email = decode_cfemail(href.split("#", 1)[1])
            if email:
                return email
        cfhex2 = (a.get("data-cfemail") or "").strip()
        if cfhex2:
            email = decode_cfemail(cfhex2)
            if email:
                return email

    # last fallback: regex
    m = EMAIL_RE.search(profile_soup.get_text(" ", strip=True))
    return m.group(0) if m else None


def _extract_candidates_from_list_page(soup: BeautifulSoup) -> list[dict]:
    """
    From the list page:
      - find candidate profile links
      - derive name from anchor text
      - capture storkreds from nearby text line containing 'Storkreds' (best effort)
    """
    rows: list[dict] = []

    name_links = soup.select('a[href^="https://danskfolkeparti.dk/kandidater/"], a[href^="/kandidater/"]')
    seen = set()

    for a in name_links:
        href = (a.get("href") or "").strip()
        name = _clean(a.get_text(" ", strip=True))
        if not name or not href:
            continue

        profile_url = urljoin("https://danskfolkeparti.dk", href)

        # ignore the index page itself
        if profile_url.rstrip("/") == "https://danskfolkeparti.dk/kandidater":
            continue

        # climb to container to find storkreds text
        card = a
        for _ in range(10):
            if card is None:
                break
            txt = card.get_text(" ", strip=True)
            if "Storkreds" in txt or "Folketingskandidat" in txt or "Spidskandidat" in txt:
                break
            card = card.parent

        if card is None:
            continue

        sig = (profile_url, _clean(card.get_text(" ", strip=True))[:200])
        if sig in seen:
            continue
        seen.add(sig)

        storkreds_raw = None
        for line in card.get_text("\n", strip=True).split("\n"):
            line = _clean(line)
            if "Storkreds" in line:
                storkreds_raw = line
                break

        rows.append(
            {
                "name": name,
                "profile_url": profile_url,
                "storkreds": normalize_storkreds_df(storkreds_raw),
            }
        )

    return rows


def scrape_candidates() -> int:
    parser = argparse.ArgumentParser(description="Scrape DF candidates (name/email/storkreds) with pagination + profile fetch")
    parser.add_argument("--format", choices=["json", "csv"], default="json")
    parser.add_argument("--output", default="output/candidates_df", help="Output file path (no extension)")
    parser.add_argument("--base-url", default="https://danskfolkeparti.dk/kandidater/", help="Start URL")
    parser.add_argument("--max_pages", type=int, default=50, help="Safety cap for pagination")
    parser.add_argument("--sleep", type=float, default=0.2, help="Sleep between requests")
    args = parser.parse_args()

    output_dir = os.path.dirname(args.output)
    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
    output_file = f"{args.output}.{args.format}"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
        )
    }

    # 1) Collect candidates from list pages
    collected: list[dict] = []
    seen_profiles = set()

    for page_no in range(1, args.max_pages + 1):
        url = args.base_url if page_no == 1 else urljoin(args.base_url, f"page/{page_no}/")
        print(f"\nFetching list page {page_no}: {url}")

        try:
            soup = _get_soup(url, headers=headers)
        except requests.RequestException as e:
            print(f"Fetch failed for {url}: {e}")
            break

        rows = _extract_candidates_from_list_page(soup)
        print(f"Found {len(rows)} candidate rows on this list page")

        if not rows:
            print("No candidates found on this list page; stopping pagination.")
            break

        new_added = 0
        for r in rows:
            pu = r["profile_url"]
            if pu in seen_profiles:
                continue
            seen_profiles.add(pu)
            collected.append(r)
            new_added += 1

        print(f"New profiles added: {new_added} (total profiles {len(collected)})")

        if args.sleep:
            time.sleep(args.sleep)

    if not collected:
        print("No candidate profiles found overall.")
        return 1

    # 2) Visit each profile page to extract email
    candidates: list[Candidate] = []
    seen_final = set()

    for idx, r in enumerate(collected, 1):
        name = r["name"]
        storkreds = r.get("storkreds")
        profile_url = r["profile_url"]

        print(f"[{idx}/{len(collected)}] Fetching profile: {profile_url}")
        try:
            psoup = _get_soup(profile_url, headers=headers)
            email = _extract_email_from_profile(psoup)
        except Exception as e:
            print(f"ERROR fetching/parsing profile {profile_url}: {e}")
            email = None

        key = (name.lower(), (email or "").lower(), (storkreds or "").lower())
        if key in seen_final:
            continue
        seen_final.add(key)

        c = Candidate(
            name=name,
            party="DF",
            email=email,
            storkreds=storkreds,
            additional_info=None,
        )
        candidates.append(c)
        print(f"Candidate: {c.name} - {c.email} - {c.storkreds}")

        if args.sleep:
            time.sleep(args.sleep)

    if not candidates:
        print("No candidates produced.")
        return 1

    # Save
    if args.format == "json":
        data = [c.model_dump() for c in candidates]
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    else:
        with open(output_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["name", "email", "storkreds", "additional_info", "party"])
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
