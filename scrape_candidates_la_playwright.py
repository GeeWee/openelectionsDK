#!/usr/bin/env python3
# scrape_candidates_la_playwright.py
#
# Scrape Liberal Alliance folketingskandidater using Playwright (JS-required site),
# paginating via ?_paged=2,3,4...
#
# Extracts: name, email, phone, storkreds (normalized to your 10-name list)
#
# Install:
#   python3 -m pip install playwright
#   python3 -m playwright install chromium
#
# Run:
#   python3 -u scrape_candidates_la_playwright.py --format json --output output/candidates_la
#   python3 -u scrape_candidates_la_playwright.py --headful

import os
import sys
import argparse
import json
import csv
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from models import Candidate


def _clean(s: Optional[str]) -> str:
    return " ".join((s or "").replace("\xa0", " ").split()).strip()


def normalize_storkreds_la(raw: Optional[str]) -> Optional[str]:
    """
    Normalizes LA storkreds labels to EXACTLY one of:
      [
        "Københavns Omegns", "København", "Nordsjælland", "Bornholm", "Sjælland",
        "Fyn", "Sydjylland", "Østjylland", "Vestjylland", "Nordjylland"
      ]
    """
    if not raw:
        return None

    s = _clean(raw).lower()
    s = s.replace("storkreds", "").strip()
    s = " ".join(s.split())

    if "københavns omegn" in s or "koebenhavns omegn" in s:
        return "Københavns Omegns"
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

    # fallback: remove "storkreds" and title-case
    fallback = _clean(raw.replace("STORKREDS", "").replace("Storkreds", "").replace("storkreds", ""))
    return fallback.title() if fallback else None


def _mailto_to_email(href: Optional[str]) -> Optional[str]:
    if not href:
        return None
    href = href.strip()
    if not href.lower().startswith("mailto:"):
        return None
    email = href.split("mailto:", 1)[1].strip()
    email = email.split("?", 1)[0].strip()
    return email or None


def _tel_to_phone(href: Optional[str]) -> Optional[str]:
    if not href:
        return None
    href = href.strip()
    if not href.lower().startswith("tel:"):
        return None
    phone = href.split("tel:", 1)[1].strip()
    return phone or None


def _extract_candidates_from_page(page) -> list[dict]:
    """
    Markup:
      <article class="... grid-item--candidate ...">
        .grid-item-badge   -> storkreds
        .grid-item-title   -> name
        a.email-link[href^="mailto:"] -> email
        a.phone-link[href^="tel:"]    -> phone
    """
    articles = page.locator("article.grid-item--candidate")
    count = articles.count()
    print(f"DOM: found {count} candidate articles")

    rows = []
    for i in range(count):
        art = articles.nth(i)

        storkreds = None
        badge = art.locator(".grid-item-badge").first
        if badge.count() > 0:
            storkreds = normalize_storkreds_la(badge.inner_text())

        name = None
        title = art.locator(".grid-item-title").first
        if title.count() > 0:
            name = _clean(title.inner_text())

        email = None
        email_a = art.locator("a.email-link").first
        if email_a.count() > 0:
            email = _mailto_to_email(email_a.get_attribute("href"))

        phone = None
        phone_a = art.locator("a.phone-link").first
        if phone_a.count() > 0:
            phone = _tel_to_phone(phone_a.get_attribute("href"))

        if name:
            rows.append({"name": name, "storkreds": storkreds, "email": email, "phone": phone})

    return rows


def scrape_candidates() -> int:
    parser = argparse.ArgumentParser(description="Scrape LA folketingskandidater via Playwright and ?_paged=N URLs")
    parser.add_argument("--base-url", default="https://www.liberalalliance.dk/folketingskandidater/", help="Start URL")
    parser.add_argument("--format", choices=["json", "csv"], default="json")
    parser.add_argument("--output", default="output/candidates_la", help="Output file path (no extension)")
    parser.add_argument("--party", default="LA", help="Candidate.party value")
    parser.add_argument("--headful", action="store_true", help="Show browser window")
    parser.add_argument("--max_pages", type=int, default=50, help="Safety cap on page numbers")
    parser.add_argument("--start_page", type=int, default=1, help="Start page number (1 = base URL)")
    parser.add_argument("--sleep_ms", type=int, default=300, help="Small settle time after navigation (ms)")
    args = parser.parse_args()

    output_dir = os.path.dirname(args.output)
    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
    output_file = f"{args.output}.{args.format}"

    seen = set()
    candidates: list[Candidate] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headful)
        context = browser.new_context()
        page = context.new_page()

        for page_no in range(args.start_page, args.max_pages + 1):
            if page_no == 1:
                url = args.base_url
            else:
                joiner = "&" if "?" in args.base_url else "?"
                url = f"{args.base_url}{joiner}_paged={page_no}"

            print(f"\nLoading page {page_no}: {url}")
            page.goto(url, wait_until="domcontentloaded")

            # Allow JS rendering to settle
            try:
                page.wait_for_timeout(args.sleep_ms)
            except Exception:
                pass

            # Stop if no candidates are present on this page
            try:
                page.wait_for_selector("article.grid-item--candidate", timeout=8000)
            except PlaywrightTimeoutError:
                print("No candidate articles found on this page. Stopping pagination.")
                break

            rows = _extract_candidates_from_page(page)
            if not rows:
                print("Extracted 0 candidates from this page. Stopping pagination.")
                break

            new_added = 0
            for r in rows:
                name = r["name"]
                storkreds = r.get("storkreds")
                email = r.get("email")
                phone = r.get("phone")

                key = (name.lower(), (email or "").lower(), (storkreds or "").lower(), (phone or ""))
                if key in seen:
                    continue
                seen.add(key)

                # Your Candidate model likely has no phone field; store phone in additional_info.
                c = Candidate(
                    name=name,
                    party=args.party,
                    email=email,
                    storkreds=storkreds,
                    additional_info=phone,
                )
                candidates.append(c)
                new_added += 1

                print(f"Candidate: {c.name} - {c.email} - {c.storkreds} (phone: {phone})")

            print(f"New candidates added this page: {new_added} (total {len(candidates)})")

        browser.close()

    if not candidates:
        print("No candidates found.")
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