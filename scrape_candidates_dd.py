#!/usr/bin/env python3
# scrape_candidates_dd.py
#
# Scrape Danmarksdemokraterne folketingskandidater from:
#   https://danmarksdemokraterne.dk/forside/folketingskandidater/
#
# Extracts: Name, Email (incl. Cloudflare decode), Storkreds (from h4 header)
#
# Run:
#   python3 scrape_candidates_dd.py --format json --output output/candidates_dd
#   python3 scrape_candidates_dd.py --format csv  --output output/candidates_dd

import os
import sys
import argparse
import json
import csv
import re
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup, Tag

# If you have your own Candidate model, you can swap this out.
# This script writes dicts directly, so it does NOT require models.py.
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

def clean(s: Optional[str]) -> str:
    return " ".join((s or "").replace("\xa0", " ").split()).strip()

def normalize_storkreds(raw: Optional[str]) -> Optional[str]:
    """
    Normalize to the 10 standard names you’ve used elsewhere.
    Removes "Storkreds" and genitive 's' except for "Københavns Omegns".
    """
    if not raw:
        return None
    s = clean(raw).lower().replace("storkreds", "").strip()
    s = " ".join(s.split())

    if "københavns omegn" in s or "koebenhavns omegn" in s:
        return "Københavns Omegns"

    if s.endswith("s"):
        s = s[:-1].strip()

    if "københavn" in s or "koebenhavn" in s:
        return "København"
    if "nordsjælland" in s or "nordsjaelland" in s:
        return "Nordsjælland"
    if "bornholm" in s:
        return "Bornholm"
    if "sjælland" in s or "sjaelland" in s:
        return "Sjælland"
    if "fyn" in s:
        return "Fyn"
    if "sydjylland" in s:
        return "Sydjylland"
    if "østjylland" in s or "oestjylland" in s:
        return "Østjylland"
    if "vestjylland" in s:
        return "Vestjylland"
    if "nordjylland" in s:
        return "Nordjylland"

    # fallback
    out = clean(raw).replace("STORKREDS", "").replace("Storkreds", "").replace("storkreds", "")
    out = clean(out).title()
    return out or None

def decode_cfemail(cfhex: str) -> Optional[str]:
    """
    Cloudflare email protection decoder.
    cfhex is the hex string from data-cfemail or from the href hash part (#...).
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

def extract_email_from_fragment(fragment: Tag) -> Optional[str]:
    """
    Tries:
      1) mailto:
      2) Cloudflare span.__cf_email__[data-cfemail]
      3) Cloudflare /cdn-cgi/l/email-protection#... links
      4) regex fallback
    """
    # 1) Normal mailto
    a = fragment.select_one('a[href^="mailto:"]')
    if a and a.get("href"):
        return a["href"].replace("mailto:", "").split("?", 1)[0].strip() or None

    # 2) CF span
    span = fragment.select_one("span.__cf_email__[data-cfemail]")
    if span:
        email = decode_cfemail(span.get("data-cfemail"))
        if email:
            return email

    # 3) CF link
    for a in fragment.select('a[href*="/cdn-cgi/l/email-protection"]'):
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

    # 4) regex in visible text
    m = EMAIL_RE.search(fragment.get_text(" ", strip=True))
    return m.group(0) if m else None

def scrape() -> list[dict]:
    url = "https://danmarksdemokraterne.dk/forside/folketingskandidater/"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
        )
    }

    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # The content is in the main article area; entry-content works on most WP themes.
    content = soup.select_one(".entry-content") or soup.body
    if not content:
        raise RuntimeError("Could not locate page content container.")

    results: list[dict] = []

    current_storkreds_raw: Optional[str] = None
    current_storkreds: Optional[str] = None

    # We walk the DOM in order: h4 marks storkreds, h5 marks candidate name.
    # Candidate "block" = everything until the next h5/h4.
    elements = content.find_all(["h4", "h5", "p", "div", "ul"], recursive=True)

    i = 0
    while i < len(elements):
        el = elements[i]

        if el.name == "h4":
            current_storkreds_raw = clean(el.get_text(" ", strip=True))
            current_storkreds = normalize_storkreds(current_storkreds_raw)
            i += 1
            continue

        if el.name == "h5":
            name = clean(el.get_text(" ", strip=True)).title()
            # Gather a fragment for this candidate: from after this h5 until next h5/h4
            frag_nodes = []
            j = i + 1
            while j < len(elements) and elements[j].name not in ("h4", "h5"):
                frag_nodes.append(elements[j])
                j += 1

            # Create a temporary wrapper soup fragment for easy CSS search
            wrapper = BeautifulSoup("<div></div>", "html.parser").div
            for node in frag_nodes:
                # copy node HTML into wrapper
                wrapper.append(BeautifulSoup(str(node), "html.parser"))

            email = extract_email_from_fragment(wrapper)

            results.append({
                "name": name,
                "email": email,
                "storkreds": current_storkreds,
                "party": "DD",
            })

            i = j
            continue

        i += 1

    # Deduplicate (some pages repeat headings/images)
    seen = set()
    uniq = []
    for r in results:
        key = (r["name"].lower(), (r["email"] or "").lower(), (r["storkreds"] or "").lower())
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)

    return uniq

def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape DD candidates (name/email/storkreds)")
    parser.add_argument("--format", choices=["json", "csv"], default="json")
    parser.add_argument("--output", default="output/candidates_dd", help="Output file path (no extension)")
    args = parser.parse_args()

    output_dir = os.path.dirname(args.output)
    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
    output_file = f"{args.output}.{args.format}"

    rows = scrape()
    if not rows:
        print("No candidates found.")
        return 1

    if args.format == "json":
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
    else:
        with open(output_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["name", "email", "storkreds", "party"])
            writer.writeheader()
            writer.writerows(rows)

    print(f"Saved {len(rows)} candidates to {output_file}")
    return 0

if __name__ == "__main__":
    sys.exit(main())