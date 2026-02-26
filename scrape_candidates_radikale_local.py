#!/usr/bin/env python3
# scrape_candidates_radikale_local.py
# run with eg... python3 scrape_candidates_radikale_local.py --input rv-candidates.html --format json --output output/candidates_radikale
# first save the HTML from the browser (use developer tools), then run this script to parse and save structured data

import os
import sys
import argparse
import json
import csv
import re
from pathlib import Path

from bs4 import BeautifulSoup

from models import Candidate
from utils import find_most_similar_storkreds


EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
STORKREDS_IN_LINE_RE = re.compile(r"\bi\s+(.+?Storkreds)\b", re.IGNORECASE)


def _load_soup_from_file(filepath: str) -> BeautifulSoup:
    with open(filepath, "r", encoding="utf-8") as f:
        html = f.read()
    print(f"Loaded file: {filepath} ({len(html)} chars)")
    print("Contains c-person-meta?", "c-person-meta" in html)
    return BeautifulSoup(html, "html.parser")


def _extract_candidates_from_html(soup: BeautifulSoup) -> list[dict]:
    """
    Extract from:
      <div class="c-person-meta">
        <a ...>
          <div class="text-32 ...">NAME</div>
          <div class="my-12 ...">
            <div>additional info</div>
            <div>Folketingskandidat i Sydjyllands Storkreds</div>
          </div>
        </a>
        <div class="mt-auto ...">
          <a href="mailto:...">email</a>
        </div>
      </div>
    """
    cards = soup.select("div.c-person-meta")
    print("BS4 .c-person-meta count:", len(cards))

    out: list[dict] = []

    for card in cards:
        # Name
        name_el = card.select_one(".text-32")
        name = name_el.get_text(" ", strip=True) if name_el else ""
        name = " ".join(name.split())

        # Email
        email = None
        mailto = card.select_one('a[href^="mailto:"]')
        if mailto and mailto.get("href"):
            email = mailto["href"].replace("mailto:", "").strip()
        else:
            m = EMAIL_RE.search(card.get_text(" ", strip=True))
            if m:
                email = m.group(0)

        # Info block lines
        additional_info = None
        storkreds_raw = None

        info_block = card.select_one(".my-12")
        if info_block:
            lines = [d.get_text(" ", strip=True) for d in info_block.select("div")]
            lines = [" ".join(x.split()) for x in lines if x]

            if lines:
                additional_info = lines[0]

            for line in lines:
                if "Storkreds" in line:
                    m = STORKREDS_IN_LINE_RE.search(line)
                    if m:
                        storkreds_raw = m.group(1).strip()
                    else:
                        m2 = re.search(r"(.+Storkreds)\b", line, flags=re.IGNORECASE)
                        if m2:
                            storkreds_raw = m2.group(1).strip()
                    break

        out.append(
            {
                "name": name,
                "email": email,
                "storkreds_raw": storkreds_raw,
                "additional_info": additional_info,
            }
        )

    return out


def scrape_candidates() -> int:
    parser = argparse.ArgumentParser(description="Scrape folketingskandidater (Radikale) from a local HTML file")
    parser.add_argument("--input", default="rv-candidates.html", help="Path to saved HTML from browser")
    parser.add_argument("--format", choices=["json", "csv"], default="json", help="Output format (json or csv)")
    parser.add_argument("--output", default="output/candidates_radikale", help="Output file path (without extension)")
    args = parser.parse_args()

    print("STARTING scrape_candidates()")

    # Create output directory if it doesn't exist
    output_dir = os.path.dirname(args.output)
    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
    output_file = f"{args.output}.{args.format}"

    soup = _load_soup_from_file(args.input)
    rows = _extract_candidates_from_html(soup)

    candidates: list[Candidate] = []
    seen = set()

    for row in rows:
        name = (row.get("name") or "").strip()
        email = row.get("email") or None
        storkreds_raw = row.get("storkreds_raw") or None
        additional_info = row.get("additional_info") or None

        storkreds = find_most_similar_storkreds(storkreds_raw) if storkreds_raw else None

        key = (name.lower(), (email or "").lower())
        if key in seen:
            continue
        seen.add(key)

        try:
            c = Candidate(
                name=name,
                party="RV",
                email=email,
                storkreds=storkreds,
                additional_info=additional_info,
            )
            candidates.append(c)
            print(f"Candidate: {c.name} - {c.email} - {c.storkreds}")
        except Exception as e:
            print(f"Error creating Candidate for row={row}: {e}")

    if not candidates:
        print("No candidates found in the local HTML.")
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
    print(f"Candidates parsed: {len(candidates)} (deduped from {len(rows)} cards)")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(scrape_candidates())
    except Exception:
        import traceback
        traceback.print_exc()
        raise
