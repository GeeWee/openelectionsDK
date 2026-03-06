import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from utils import find_most_similar_storkreds

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)

headers = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    )
}

def decode_cfemail(cfhex: str) -> str | None:
    """
    Cloudflare email protection decoder.
    cfhex is hex from data-cfemail or from the href hash part (#...).
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

def extract_email(soup: BeautifulSoup) -> str | None:
    # 1) Normal mailto
    for a in soup.select('a[href^="mailto:"]'):
        href = (a.get("href") or "").strip()
        email = href.replace("mailto:", "").split("?", 1)[0].strip()
        if email:
            return email

    # 2) Cloudflare span: <span class="__cf_email__" data-cfemail="...">
    span = soup.select_one("span.__cf_email__[data-cfemail]")
    if span:
        email = decode_cfemail(span.get("data-cfemail"))
        if email:
            return email

    # 3) Cloudflare link: /cdn-cgi/l/email-protection#...
    for a in soup.select('a[href*="/cdn-cgi/l/email-protection"]'):
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

    # 4) Regex fallback (works if email appears in text)
    m = EMAIL_RE.search(soup.get_text(" ", strip=True))
    return m.group(0) if m else None


results = []

main_url = "https://enhedslisten.dk/politikere/folketingsvalg-2026/"
response = requests.get(main_url, headers=headers, timeout=30)
response.raise_for_status()
soup = BeautifulSoup(response.text, "html.parser")

urls = set()

# safer: check .wpgb-main exists
main_blocks = soup.select(".wpgb-main")
if not main_blocks:
    raise RuntimeError("Could not find .wpgb-main on the main page (markup may have changed).")

for a in main_blocks[0].find_all("a", recursive=True):
    href = a.get("href")
    if not href:
        continue
    if "/profil" in href:
        # normalize to absolute URL
        urls.add(urljoin(main_url, href))

for url in sorted(urls):
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    # -----------------------
    # NAME
    # -----------------------
    name_tag = soup.select_one("h1.uagb-heading-text")
    name = name_tag.get_text(strip=True) if name_tag else None

    # -----------------------
    # STORKREDS
    # -----------------------
    storkreds_raw = None
    location_div = soup.select_one(".location-icon")
    if location_div:
        storkreds_raw = location_div.get_text(" ", strip=True)

    # -----------------------
    # EMAIL
    # -----------------------
    email = extract_email(soup)

    results.append({
        "name": name,
        "storkreds": find_most_similar_storkreds(storkreds_raw) if storkreds_raw else None,
        "email": email,
        "party": "Enhedslisten",
        "url": url,
    })

print(json.dumps(results, indent=2, ensure_ascii=False))