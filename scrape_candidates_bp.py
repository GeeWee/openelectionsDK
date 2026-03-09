#!/usr/bin/env python3
# scrape_candidates_bp.py
#
# Run:
#   python3 scrape_candidates_bp.py --format json --output output/candidates_bp
#   python3 scrape_candidates_bp.py --format csv  --output output/candidates_bp

import os
import sys
import argparse
import json
import csv
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from models import Candidate
from utils import find_most_similar_storkreds


BASE_URL = "https://borgernesparti.dk/kandidater/"


def _clean(s: str) -> str:
    return " ".join((s or "").replace("\xa0", " ").split()).strip()


def _get_soup(url: str, headers: dict, timeout: int = 30) -> BeautifulSoup:
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def _extract_profile_urls(list_soup: BeautifulSoup) -> list[str]:
    """
    BP candidate pages are typically:
      https://borgernesparti.dk/person/<slug>/

    We collect all anchors that contain '/person/' and normalize to absolute URLs.
    """
    urls = set()
    for a in list_soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        if not href:
            continue

        if "/person/" not in href:
            continue

        abs_url = urljoin(BASE_URL, href).rstrip("/")
        path = urlparse(abs_url).path

        # keep only /person/<something>
        if path.startswith("/person/") and len(path.split("/")) >= 3:
            urls.add(abs_url)

    return sorted(urls)


def _extract_name(profile_soup: BeautifulSoup) -> str | None:
    # Your example: <div class="... navn"><h1 class="fusion-title-heading ...">Daniel Juhl</h1>
    h1 = profile_soup.select_one(".navn h1")
    if h1:
        return _clean(h1.get_text(" ", strip=True))

    # fallback: first h1 on page
    h1 = profile_soup.select_one("h1")
    return _clean(h1.get_text(" ", strip=True)) if h1 else None


def _extract_storkreds(profile_soup: BeautifulSoup) -> str | None:
    # Your example: <div class="fusion-text ... region"><p>Fyns Storkreds</p>
    p = profile_soup.select_one(".region p")
    if p:
        return _clean(p.get_text(" ", strip=True))

    # fallback: any element containing "Storkreds"
    text = profile_soup.get_text("\n", strip=True)
    for line in text.split("\n"):
        line = _clean(line)
        if "Storkreds" in line:
            return line
    return None


def _extract_email(profile_soup: BeautifulSoup) -> str | None:
    # Your example: <a ... href="mailto:..."></a>
    mailto = profile_soup.select_one('a[href^="mailto:"]')
    if mailto and mailto.get("href"):
        return mailto["href"].replace("mailto:", "").split("?", 1)[0].strip()
    return None


def scrape_candidates() -> int:
    parser = argparse.ArgumentParser(description="Scrape Borgernes Parti (BP) candidates")
    parser.add_argument("--format", choices=["json", "csv"], default="json", help="Output format")
    parser.add_argument("--output", default="output/candidates_bp", help="Output file path (without extension)")
    parser.add_argument("--sleep", type=float, default=0.2, help="Sleep between profile requests (seconds)")
    parser.add_argument("--max_candidates", type=int, default=None, help="Optional cap (debug)")
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

    print(f"Fetching list page: {BASE_URL}")
    list_soup = _get_soup(BASE_URL, headers=headers)

    profile_urls = _extract_profile_urls(list_soup)
    print(f"Found {len(profile_urls)} candidate profile URLs")

    if args.max_candidates is not None:
        profile_urls = profile_urls[: args.max_candidates]
        print(f"DEBUG: limiting to first {len(profile_urls)} profiles")

    candidates: list[Candidate] = []
    seen = set()

    for i, url in enumerate(profile_urls, 1):
        print(f"[{i}/{len(profile_urls)}] Fetching profile: {url}")
        try:
            psoup = _get_soup(url, headers=headers)

            name = _extract_name(psoup)
            storkreds_raw = _extract_storkreds(psoup)
            email = _extract_email(psoup)

            storkreds = find_most_similar_storkreds(storkreds_raw) if storkreds_raw else None

            key = ((name or "").lower(), (email or "").lower(), (storkreds or "").lower())
            if key in seen:
                continue
            seen.add(key)

            c = Candidate(
                name=name or "",
                party="BP",
                email=email,
                storkreds=storkreds,
                additional_info=None,
            )
            candidates.append(c)
            print(f"Candidate: {c.name} - {c.email} - {c.storkreds}")

        except Exception as e:
            print(f"ERROR parsing {url}: {e}")

        if args.sleep:
            time.sleep(args.sleep)

    if not candidates:
        print("No candidates parsed.")
        return 1

    if args.format == "json":
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump([c.model_dump() for c in candidates], f, ensure_ascii=False, indent=2)
    else:
        with open(output_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["name", "party", "email", "storkreds", "additional_info"]
            )
            writer.writeheader()
            writer.writerows([c.model_dump() for c in candidates])

    print(f"\nSuccessfully saved {len(candidates)} candidates to {output_file}")
    return 0


if __name__ == "__main__":
    sys.exit(scrape_candidates())