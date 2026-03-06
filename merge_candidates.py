#!/usr/bin/env python3
import csv
import glob
import json
import os

INPUT_DIR = "output"
OUTPUT_CSV = os.path.join(INPUT_DIR, "all_candidates.csv")

def clean_email(email):
    if not email:
        return None
    return str(email).strip().strip(">")

def main():
    json_files = sorted(glob.glob(os.path.join(INPUT_DIR, "*.json")))
    if not json_files:
        raise SystemExit(f"No .json files found in {INPUT_DIR}/")

    rows = []
    for fp in json_files:
        with open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)

        # support either [...] or {"candidates":[...]}
        if isinstance(data, dict):
            data = data.get("candidates", [])

        if not isinstance(data, list):
            print(f"Skipping {fp}: expected list, got {type(data).__name__}")
            continue

        for c in data:
            if not isinstance(c, dict):
                continue
            rows.append({
                "name": (c.get("name") or "").strip(),
                "party": (c.get("party") or "").strip(),
                "email": clean_email(c.get("email")),
                "storkreds": (c.get("storkreds") or "").strip(),
                "additional_info": (c.get("additional_info") or "").strip(),
            })

    # Deduplicate
    seen = set()
    deduped = []
    for r in rows:
        key = (
            r["name"].lower(),
            (r["email"] or "").lower(),
            r["party"].lower(),
            r["storkreds"].lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    fieldnames = ["name", "party", "email", "storkreds", "additional_info"]
    with open(OUTPUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(deduped)

    print(f"Merged {len(json_files)} files -> {OUTPUT_CSV}")
    print(f"Rows: {len(rows)} (deduped to {len(deduped)})")

if __name__ == "__main__":
    main()