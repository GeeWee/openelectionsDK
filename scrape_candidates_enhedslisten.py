import json

import requests
from bs4 import BeautifulSoup

from utils import find_most_similar_storkreds

results = []

main_url = "https://enhedslisten.dk/politikere/folketingsvalg-2026/"
response = requests.get(main_url)
response.raise_for_status()
soup = BeautifulSoup(response.text, "html.parser")

urls = set()

for url in soup.select(".wpgb-main")[0].find_all("a", recursive=True):
    href = url["href"]
    if "/profil" in href:
        urls.add(href)

for url in urls:

    response = requests.get(url)
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
    storkreds = None
    location_div = soup.select_one(".location-icon")
    if location_div:
        # Get text but remove extra whitespace
        storkreds = location_div.get_text(strip=True)

    # -----------------------
    # EMAIL (optional)
    # -----------------------
    email = None
    mail_links = soup.select("a")

    for mail_link in mail_links:
        if mail_link and mail_link["href"].startswith("mailto:"):
            email = mail_link["href"].replace("mailto:", "").strip()

    # -----------------------
    # RESULT
    # -----------------------

    results.append({
        "name": name,
        "storkreds": find_most_similar_storkreds(storkreds),
        "email": email,
        "party": "Enhedslisten",
    })

print(json.dumps(results, indent=2, ensure_ascii=False))