#!/usr/bin/env python3
# scrape_candidates_konservative.py
#
# Scrapes folketingskandidater from Konservative “lokalt” pages.
# Supports reading from LOCAL HTML files per storkreds directly via STORKREDS_PAGES.
#
# It only scrapes politicians inside the section that matches ALL of:
#   - data-filter-wrapper="politician"
#   - data-acf-roles="folketingskandidat"
#   - data-acf-geography="<geography_slug>"
#
# Run:
#   python3 scrape_candidates_konservative.py --format json --output output/candidates_konservative

import os
import sys
import argparse
import json
import csv
import re
import time
from pathlib import Path
from typing import Optional, Dict, Tuple

import requests
from bs4 import BeautifulSoup

from models import Candidate


EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)

# Storkreds -> (source, data-acf-geography slug)
# "source" can be:
#   - a URL starting with https://
#   - a local file path (e.g. "html/bornholm.html" or "/full/path/bornholm.html")
#
# Put your local files right here:
STORKREDS_PAGES: Dict[str, Tuple[str, str]] = {
    "Bornholm": ("input/kons-bornholm.html", "bornholms-storkreds"),
    "Fyn": ("input/kons-fyn.html", "fyns-storkreds"),
    "Københavns Omegn": ("input/kons-koebenhavns_omegn.html", "koebenhavns-omegns-storkreds"),
    "København": ("input/kons-københavn.html", "koebenhavns-storkreds"),
    "Nordjylland": ("input/kons-nordjylland.html", "nordjyllands-storkreds"),
    "Sjælland": ("input/kons-sjælland.html", "sjaellands-storkreds"),
    "nordsjælland": ("input/kons-nordsjælland.html", "nordsjaellands-storkreds"),
    "Sydjylland": ("input/kons-sydjylland.html", "sydjyllands-storkreds"),
    "Østjylland": ("input/kons-østjylland.html", "oestjyllands-storkreds"),
    "Vestjylland": ("input/kons-vestjylland.html", "vestjyllands-storkreds")
}


def _clean(s: str) -> str:
    return " ".join((s or "").replace("\xa0", " ").split()).strip()


def _load_soup_from_file(filepath: str) -> BeautifulSoup:
    with open(filepath, "r", encoding="utf-8") as f:
        html = f.read()
    print(f"Loaded file: {filepath} ({len(html)} chars)")
    return BeautifulSoup(html, "html.parser")


def _get_soup_from_url(url: str, headers: dict, timeout: int = 30) -> BeautifulSoup:
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def _get_soup(source: str, headers: dict) -> BeautifulSoup:
    """
    If source looks like a URL -> fetch.
    Else treat as local file path -> read.
    """
    if source.startswith("http://") or source.startswith("https://"):
        return _get_soup_from_url(source, headers=headers)
    return _load_soup_from_file(source)


def _extract_email(card: BeautifulSoup) -> Optional[str]:
    mailto = card.select_one('a[href^="mailto:"]')
    if mailto and mailto.get("href"):
        return mailto["href"].replace("mailto:", "").strip()

    m = EMAIL_RE.search(card.get_text(" ", strip=True))
    return m.group(0) if m else None


def _extract_name(card: BeautifulSoup) -> str:
    h3 = card.select_one("h3")
    if h3:
        return _clean(h3.get_text(" ", strip=True))
    return ""


def _extract_additional_info(card: BeautifulSoup) -> Optional[str]:
    """
    Collect <p> texts inside the card, remove email/phone lines, keep the remainder.
    """
    ps = card.select("p")
    lines = [_clean(p.get_text(" ", strip=True)) for p in ps]
    lines = [ln for ln in lines if ln]

    email = _extract_email(card)

    filtered = []
    for ln in lines:
        if email and email in ln:
            continue
        if re.search(r"\+45|\b\d{2}\s*\d{2}\s*\d{2}\s*\d{2}\b|\b\d{8}\b", ln):
            continue
        filtered.append(ln)

    return " | ".join(filtered) if filtered else None


def _find_candidate_sections(soup: BeautifulSoup, geography_slug: str) -> list[BeautifulSoup]:
    selector = (
        'section[data-filter-wrapper="politician"]'
        '[data-acf-roles="folketingskandidat"]'
        f'[data-acf-geography="{geography_slug}"]'
    )
    return soup.select(selector)


def _extract_cards_from_section(section: BeautifulSoup) -> list[BeautifulSoup]:
    cards = section.select('div.flex.flex-col.gap-\\[10px\\]')
    if cards:
        return cards

    # fallback: find small parent div around mailto links
    mailto_links = section.select('a[href^="mailto:"]')
    out = []
    for a in mailto_links:
        node = a
        for _ in range(6):
            if node is None:
                break
            if getattr(node, "name", None) == "div":
                txt = node.get_text(" ", strip=True)
                if txt and len(txt) < 800:
                    out.append(node)
                    break
            node = node.parent

    seen = set()
    uniq = []
    for d in out:
        sig = _clean(d.get_text(" ", strip=True))[:250]
        if sig in seen:
            continue
        seen.add(sig)
        uniq.append(d)

    return uniq


def scrape_candidates() -> int:
    parser = argparse.ArgumentParser(
        description="Scrape Konservative folketingskandidater by storkreds sources (URL or local files)"
    )
    parser.add_argument("--format", choices=["json", "csv"], default="json", help="Output format")
    parser.add_argument("--output", default="output/candidates_konservative", help="Output file path (no extension)")
    parser.add_argument("--sleep", type=float, default=0.2, help="Sleep between URL requests (ignored for local files)")
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

    candidates: list[Candidate] = []
    seen = set()  # dedupe by (name,email,storkreds)

    for storkreds_name, (source, geography_slug) in STORKREDS_PAGES.items():
        is_url = source.startswith("http://") or source.startswith("https://")
        print(f"\nReading {storkreds_name} from {'URL' if is_url else 'FILE'}: {source} (geography={geography_slug})")

        try:
            soup = _get_soup(source, headers=headers)
        except Exception as e:
            print(f"ERROR loading {source}: {e}")
            continue

        sections = _find_candidate_sections(soup, geography_slug)
        print(f"Found {len(sections)} matching candidate sections")

        for si, section in enumerate(sections, 1):
            cards = _extract_cards_from_section(section)
            print(f"  Section {si}: found {len(cards)} candidate cards")

            for card in cards:
                name = _extract_name(card)
                email = _extract_email(card)
                additional_info = _extract_additional_info(card)

                if not name:
                    continue

                key = (name.lower(), (email or "").lower(), storkreds_name.lower())
                if key in seen:
                    continue
                seen.add(key)

                try:
                    c = Candidate(
                        name=name,
                        party="K",
                        email=email,
                        storkreds=storkreds_name,
                        additional_info=additional_info,
                    )
                    candidates.append(c)
                    print(f"Candidate: {c.name} - {c.email} - {c.storkreds}")
                except Exception as e:
                    print(f"Error creating Candidate for name='{name}' email='{email}': {e}")

        if is_url and args.sleep:
            time.sleep(args.sleep)

    if not candidates:
        print("No candidates found.")
        return 1

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