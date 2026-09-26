from requests.adapters import HTTPAdapter
import requests
import ssl
import json
import hashlib
import subprocess
import re
from pathlib import Path
from datetime import datetime, date, timedelta
from urllib.parse import urljoin

import pdfplumber
import pytesseract
from bs4 import BeautifulSoup
class LegacySSLAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        context = ssl.create_default_context()
        context.options |= 0x4
        kwargs["ssl_context"] = context
        return super().init_poolmanager(*args, **kwargs)
BASE_URL = "https://hppsc.hp.gov.in"

TABLE_URL = (
    "https://hppsc.hp.gov.in/CommonControls/"
    "CMSContinuousLinkPagePV?qs=mhlKjiXMMItGo46f60VBXX8%2B1SQ83OzVLj9MfDScpvboDSdMygkK4iLV47Bu%2FJzMpJLanI%2BihrK9p8W6JsSQUgHTy39NyiuO%2BFtbEmiPQyc%3D"
)

JOBS_FILE = Path("data/jobs.json")
PREVIEW_FILE = Path("data/jobs_preview.json")
REVIEW_FILE = Path("data/jobs_review.json")
TEMP_HTML = Path("data/hppsc_live.html")
PDF_DIR = Path("data/hppsc_pdfs")

TESSERACT_PATH = "tesseract"

TODAY = date.today()
RECENT_DAYS = 90


def download_page():
    TEMP_HTML.parent.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.mount("https://", LegacySSLAdapter())
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    response = session.get(
        TABLE_URL,
        timeout=90
    )
    response.raise_for_status()

    TEMP_HTML.write_text(
        response.text,
        encoding="utf-8"
    )

    return TEMP_HTML.read_text(encoding="utf-8")


def read_json(path):
    if path.exists():
        return json.loads(
            path.read_text(encoding="utf-8-sig")
        )

    # Fallback: read existing jobs from jobs.js
    jobs_js = Path("jobs.js")

    if not jobs_js.exists():
        print("WARNING: jobs.js not found!")
        return []

    content = jobs_js.read_text(encoding="utf-8-sig")

    match = re.search(
        r"const\s+JOBS\s*=\s*(\[.*?\])\s*;",
        content,
        re.DOTALL
    )

    if not match:
        raise ValueError(
            "Could not read existing JOBS array from jobs.js"
        )

    return json.loads(match.group(1))


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
def save_jobs_js(jobs):
    path = Path("jobs.js")
    content = (
        "const JOBS = "
        + json.dumps(jobs, ensure_ascii=False, indent=2)
        + ";\n"
    )
    path.write_text(content, encoding="utf-8")
    print("Live jobs.js updated:", len(jobs), "jobs")

def parse_date(text):
    formats = [
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%d.%m.%Y",
        "%Y-%m-%d",
        "%d-%m-%y",
        "%d/%m/%y",
        "%d %B %Y",
        "%d %b %Y",
        "%B %d, %Y",
        "%b %d, %Y"
    ]

    for fmt in formats:
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            pass

    return None


def get_row_date(row):
    text = row.get_text(" ", strip=True)

    matches = re.findall(
        r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b",
        text
    )

    for value in matches:
        parsed = parse_date(value)
        if parsed:
            return parsed

    return None


def extract_pdf_text(pdf_url, job_id):
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = PDF_DIR / f"{job_id}.pdf"

    try:
        session = requests.Session()
        session.mount("https://", LegacySSLAdapter())
        session.headers.update({"User-Agent": "Mozilla/5.0"})

        response = session.get(
            pdf_url,
            timeout=120
        )
        response.raise_for_status()
        pdf_path.write_bytes(response.content)

    except Exception as e:
        print("PDF download failed:", job_id, repr(e))
        return ""

    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

    pages_text = []

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""

                if len(text.strip()) < 40:
                    try:
                        image = page.to_image(resolution=200).original
                        text = pytesseract.image_to_string(image)
                    except Exception as e:
                        print("OCR warning:", e)

                pages_text.append(text)

    except Exception as e:
        print("PDF reading error:", e)
        return ""

    return "\n".join(pages_text)


def extract_deadline(text):
    if not text:
        return ""

    # Normalize PDF line breaks and extra spaces
    text = re.sub(r"\s+", " ", text)
    text = text.replace("\u00a0", " ")

    date_pattern = (
        r"(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}"
        r"|\d{1,2}\s+(?:January|February|March|April|May|June|"
        r"July|August|September|October|November|December|"
        r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
        r"\s+\d{4}"
        r"|(?:January|February|March|April|May|June|July|August|"
        r"September|October|November|December|Jan|Feb|Mar|Apr|"
        r"May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
        r"\s+\d{1,2},?\s+\d{4})"
    )

    patterns = [
        r"(?is)(?:closing\s+date\s+for\s+application|"
        r"closing\s+date\s+for\s+fee|"
        r"last\s+date\s+for\s+submission|"
        r"last\s+date\s+for\s+receipt|"
        r"last\s+date|closing\s+date|deadline)"
        r"[^.]{0,200}?" + date_pattern
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            parsed = parse_date(match.group(1))

            if parsed:
                return parsed.isoformat()

    return ""

def extract_qualification(text):
    match = re.search(
        r"(?is)(essential qualification[s]?.*?)"
        r"(?=\n\s*(?:Desirable Qualification|Age Limit|"
        r"Application Fee|How to Apply|Closing Date|"
        r"Last Date|Important Instructions))",
        text
    )

    if match:
        return match.group(1).strip()[:12000]

    return ""


def main():
    print("Reading HPPSC website...")

    html = download_page()
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("#cpdatatables tbody tr")

    if not rows:
        print("No advertisements found. Nothing changed.")
        return

    existing = read_json(JOBS_FILE)

    existing_by_url = {
        job.get("notificationUrl"): job
        for job in existing
        if job.get("notificationUrl")
    }

    other_jobs = [
        job for job in existing
        if job.get("source") != "HPPSC"
    ]

    new_candidates = []
    review_jobs = []
    seen_urls = set()

    cutoff = TODAY - timedelta(days=RECENT_DAYS)

    for row in rows:
        link = row.select_one("a[href*='CMSFileView']")

        if not link:
            continue

        pdf_url = urljoin(BASE_URL, link["href"])
        title = link.get_text(" ", strip=True)

        if not title or pdf_url in seen_urls:
            continue

        seen_urls.add(pdf_url)

        existing_job = existing_by_url.get(pdf_url)
        if existing_job:
            print("Rechecking existing job:", title)

        row_date = get_row_date(row)

        if not row_date:
            continue

        # Skip advertisements older than the recent scan window.
        if row_date < cutoff:
            continue

        job_id = "hppsc-" + hashlib.sha256(
            pdf_url.encode()
        ).hexdigest()[:12]

        print("Recent advertisement:", title)

        text = extract_pdf_text(pdf_url, job_id)
        qualification = extract_qualification(text)

        deadline = extract_deadline(text)

        if "57/7-2026" in title or "58/7-2026" in title:
            deadline = "2026-09-05"

        job = {
            "id": job_id,
            "post": title,
            "department": "Himachal Pradesh",
            "source": "HPPSC",
            "qualification": qualification or "Check official notification",
            "subject": "",
            "criteria": "Verify age, category and other eligibility conditions in the official notification.",
            "deadline": deadline,
            "status": "review",
            "reason": "Automatically collected. Verify official notification before publishing.",
            "notificationUrl": pdf_url,
            "applyUrl": "",
            "publishedDate": row_date.isoformat()
        }

        # Update existing job without creating duplicates.
        if existing_job:
            if qualification:
                existing_job["qualification"] = qualification

            if deadline:
                existing_job["deadline"] = deadline

            existing_job["reason"] = (
                "Details rechecked from official notification."
            )

            existing_job["status"] = "review"

            print("Existing job details refreshed:", title)

        # Update existing job without creating duplicates.
        if existing_job:
            if qualification:
                existing_job["qualification"] = qualification

            if deadline:
                existing_job["deadline"] = deadline

            existing_job["reason"] = (
                "Details rechecked from official notification."
            )
            existing_job["status"] = "review"

            print("Existing job details refreshed:", title)

        else:
            if deadline:
                deadline_date = date.fromisoformat(deadline)

                if deadline_date >= TODAY:
                    new_candidates.append(job)
                else:
                    print("Closed deadline; skipped:", title)

            else:
                review_jobs.append({
                    "post": title,
                    "notificationUrl": pdf_url,
                    "publishedDate": row_date.isoformat(),
                    "reason": (
                        "Deadline could not be extracted. "
                        "Verify official notification."
                    )
                })

    # Preserve every existing job, including non-HPPSC jobs.
    preview = existing.copy()

    existing_urls = {
        job.get("notificationUrl")
        for job in preview
        if job.get("notificationUrl")
    }

    for job in new_candidates:
        if job.get("notificationUrl") not in existing_urls:
            preview.append(job)
            existing_urls.add(job.get("notificationUrl"))

    save_json(PREVIEW_FILE, preview)
    save_json(REVIEW_FILE, review_jobs)
    

    print("\nScan complete.")
    print("Existing jobs preserved:", len(existing))
    print("New future-deadline candidates:", len(new_candidates))
    print("Jobs needing manual review:", len(review_jobs))
    print("Preview saved:", PREVIEW_FILE)
    print("Review list saved:", REVIEW_FILE)
    print("Original jobs.json was NOT changed.")
    print("jobs.js saved with", len(preview), "jobs.")


if __name__ == "__main__":
    main()
