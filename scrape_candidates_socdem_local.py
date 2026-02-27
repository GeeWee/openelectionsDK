#!/usr/bin/env python3
# scrape_candidates_local.py
#
# Parse a locally saved HTML page with "profile-card" entries (new party/site).
# Example:
#  python3 scrape_candidates_socdem_local.py --input input/soc-dem-Politikere.html --format json --output output/candidates_socialdemokratiet --party A
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


def _load_soup_from_file(filepath: str) -> BeautifulSoup:
    with open(filepath, "r", encoding="utf-8") as f:
        html = f.read()
    print(f"Loaded file: {filepath} ({len(html)} chars)")
    print("Contains profile-card?", "profile-card" in html)
    return BeautifulSoup(html, "html.parser")


def _extract_candidates_from_html(soup: BeautifulSoup) -> list[dict]:
    """
    Extract from structure like:

      <div class="profile-card">
        <div class="profile-card__info">
          <h3 class="profile-card__name"><a ...>Anders Kronborg</a></h3>   [Name]
          ...
          <p> ... </p> [additional info - may span multiple lines]
        </div>

        <p class="profile-card__extra"> ... Sydjylland, Esbjerg </p>       [storkreds source]
        <p class="profile-card__extra"><a href="mailto:..."> ... </a></p>  [Email]
      </div>
    """
    cards = soup.select("div.profile-card")
    print("BS4 .profile-card count:", len(cards))

    out: list[dict] = []

    for card in cards:
        # --- Name ---
        name = ""
        name_el = card.select_one(".profile-card__name a, .profile-card__name")
        if name_el:
            name = name_el.get_text(" ", strip=True)
        name = " ".join(name.split())

        # --- Email ---
        email = None
        mailto = card.select_one('a[href^="mailto:"]')
        if mailto and mailto.get("href"):
            email = mailto["href"].replace("mailto:", "").strip()
        else:
            m = EMAIL_RE.search(card.get_text(" ", strip=True))
            if m:
                email = m.group(0)

        # --- Storkreds ---
        # In your example: "Sydjylland, Esbjerg" (region-ish). We map via find_most_similar_storkreds.
        storkreds_raw = None
        extra_ps = card.select("p.profile-card__extra")
        for p in extra_ps:
            # skip the email line
            if p.select_one('a[href^="mailto:"]'):
                continue
            txt = p.get_text(" ", strip=True)
            txt = " ".join(txt.split())
            if txt:
                storkreds_raw = txt
                break

        # --- Additional info (may span multiple lines) ---
        # Take the text content in profile-card__info excluding the name itself, and excluding the "Se mere" line.
        additional_info = None
        info_block = card.select_one(".profile-card__info")
        if info_block:
            # Remove name text if present, then keep remaining lines
            full = info_block.get_text("\n", strip=True)
            lines = [ln.strip() for ln in full.split("\n") if ln.strip()]

            # remove the exact name line(s)
            lines = [ln for ln in lines if ln != name]

            # remove typical CTA line
            lines = [ln for ln in lines if not ln.lower().startswith("se mere")]

            # join remaining lines (keeps multi-line content)
            if lines:
                additional_info = " | ".join(lines)

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
    parser = argparse.ArgumentParser(description="Scrape candidates from a local HTML file (profile-card layout)")
    parser.add_argument("--input", required=True, help="Path to saved HTML from browser")
    parser.add_argument("--party", required=True, help="Party code to store in Candidate.party (e.g., 'S', 'V', 'K')")
    parser.add_argument("--format", choices=["json", "csv"], default="json", help="Output format (json or csv)")
    parser.add_argument("--output", required=True, help="Output file path (without extension)")
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
                party=args.party,
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