import json

import requests
from bs4 import BeautifulSoup

from utils import find_most_similar_storkreds

results = []

urls = [
    "https://moderaterne.dk/politikere/fv26-kandidat/",
    "https://moderaterne.dk/politikere/fv26-kandidat/page/2/",
    "https://moderaterne.dk/politikere/fv26-kandidat/page/3/"
]

for url in urls:
    response = requests.get(url)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    for item in soup.select(".e-loop-item"):
        # --- NAME ---
        name_tag = item.select_one("h2.elementor-heading-title")
        name = name_tag.get_text(strip=True) if name_tag else None

        # --- STORKREDS ---
        storkreds = None
        storkreds_container = item.select_one(".fa-map-marker-alt")
        if storkreds_container:
            # find the closest parent and then the inner span
            parent = storkreds_container.find_parent("span")
            if parent:
                inner_span = parent.find("span")
                if inner_span:
                    storkreds = inner_span.get_text(strip=True)

        # --- EMAIL ---
        email = None
        email_icon = item.select_one(".fa-envelope")
        if email_icon:
            li = email_icon.find_parent("li")
            if li:
                email_span = li.select_one(".elementor-icon-list-text")
                if email_span:
                    email = email_span.get_text(strip=True)

        results.append({
            "name": name,
            "storkreds": find_most_similar_storkreds(storkreds),
            "email": email,
            "party": "Moderaterne",
        })

print(json.dumps(results, indent=2, ensure_ascii=False))