
import requests
import json
import os
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup

# HPPSC official website
URL = "https://hppsc.hp.gov.in/Home/"

OUTPUT_FILE = "data/jobs.json"

def fetch_jobs():
    print("Checking HPPSC official website...")

    response = requests.get(
        URL,
        timeout=90,
        headers={"User-Agent": "Mozilla/5.0"}
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    jobs = []

    for link in soup.find_all("a", href=True):
        title = link.get_text(" ", strip=True)
        href = link["href"]

        if not title:
            continue

        if ".pdf" not in href.lower():
            continue

        pdf_url = requests.compat.urljoin(URL, href)

        jobs.append({
            "title": title,
            "department": "HPPSC",
            "source": "HPPSC",
            "pdf_url": pdf_url,
            "application_url": URL,
            "last_date": "",
            "qualification": "",
            "age_limit": "",
            "published_date": "",
            "fetched_at": datetime.now(
                timezone.utc
            ).isoformat()
        })

    os.makedirs("data", exist_ok=True)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)

    print(f"Found {len(jobs)} PDF links")
    print(f"Saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    fetch_jobs()
