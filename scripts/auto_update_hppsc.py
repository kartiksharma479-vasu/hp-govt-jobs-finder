import json
import re
import ssl
import hashlib
import logging
from pathlib import Path
from datetime import datetime, date, timedelta
from urllib.parse import urljoin, urlparse

import requests
import pdfplumber
import pytesseract
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter


# ============================================================
# HP GOVERNMENT JOBS FINDER — AUTOMATED SCANNER
# ============================================================

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

SOURCES_FILE = DATA / "sources.json"
JOBS_FILE = DATA / "jobs.json"
JOBS_JS_FILE = ROOT / "jobs.js"
PREVIEW_FILE = DATA / "jobs_preview.json"
REVIEW_FILE = DATA / "jobs_review.json"

PDF_DIR = DATA / "hppsc_pdfs"
TEMP_HTML = DATA / "hppsc_live.html"

TODAY = date.today()
RECENT_DAYS = 120

TABLE_URL = (
    "https://hppsc.hp.gov.in/CommonControls/"
    "CMSContinuousLinkPagePV?qs=mhlKjiXMMItGo46f60VBXX8%2B1SQ83OzVLj9MfDScpvboDSdMygkK4iLV47Bu%2FJzMpJLanI%2BihrK9p8W6JsSQUgHTy39NyiuO%2BFtbEmiPQyc%3D"
)

BASE_URL = "https://hppsc.hp.gov.in"

TESSERACT_PATH = "tesseract"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
    )
}


# ============================================================
# HTTP SESSION
# ============================================================

class LegacySSLAdapter(HTTPAdapter):

    def init_poolmanager(self, *args, **kwargs):
        context = ssl.create_default_context()
        context.options |= 0x4

        kwargs["ssl_context"] = context

        return super().init_poolmanager(*args, **kwargs)


def create_session():
    session = requests.Session()

    session.mount("https://", LegacySSLAdapter())
    session.headers.update(HEADERS)

    return session


SESSION = create_session()


def fetch(url, timeout=60):
    try:
        response = SESSION.get(url, timeout=timeout)
        response.raise_for_status()

        return response

    except Exception as error:
        logging.warning("Download failed: %s | %s", url, error)

        return None


# ============================================================
# JSON HELPERS
# ============================================================

def read_json(path, default=None):

    if default is None:
        default = []

    if not path.exists():
        return default

    try:
        with open(path, "r", encoding="utf-8-sig") as file:
            return json.load(file)

    except Exception as error:
        logging.error("JSON read failed: %s | %s", path, error)

        return default


def save_json(path, data):

    path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = path.with_suffix(path.suffix + ".tmp")

    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            indent=2,
            ensure_ascii=False
        )

    temp_path.replace(path)


def clean_text(value):

    if not value:
        return ""

    value = str(value)
    value = value.replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def normalize_url(url):

    return (url or "").strip().rstrip("/")


def job_url(job):

    return normalize_url(
        job.get("notificationUrl")
        or job.get("applyUrl")
        or job.get("applicationUrl")
        or job.get("url")
        or ""
    )


def make_id(url):

    return hashlib.sha256(
        normalize_url(url).lower().encode("utf-8")
    ).hexdigest()[:16]


# ============================================================
# SOURCE CONFIGURATION
# ============================================================

def load_sources():

    raw = read_json(SOURCES_FILE, [])

    if isinstance(raw, dict):
        raw = raw.get("sources", [])

    sources = []

    for source in raw:

        if not isinstance(source, dict):
            continue

        url = (
            source.get("url")
            or source.get("website")
            or ""
        )

        if not url:
            continue

        source = dict(source)
        source["url"] = url.strip()

        source["name"] = (
            source.get("name")
            or source.get("source")
            or source.get("organization")
            or "HP Government"
        )

        sources.append(source)

    # HPPSC is always scanned using the known official
    # advertisement table, even if it is absent from sources.json.
    if not any(
        "hppsc" in s["name"].lower()
        for s in sources
    ):
        sources.append({
            "name": "HPPSC",
            "url": TABLE_URL,
            "type": "hppsc"
        })

    return sources


# ============================================================
# EXISTING JOBS
# ============================================================

def load_existing_jobs():

    if JOBS_FILE.exists():

        data = read_json(JOBS_FILE, [])

        if isinstance(data, list):
            return data

        if isinstance(data, dict):
            return data.get("jobs", [])

    if not JOBS_JS_FILE.exists():
        logging.warning("jobs.js not found.")
        return []

    content = JOBS_JS_FILE.read_text(encoding="utf-8-sig")

    match = re.search(
        r"const\s+JOBS\s*=\s*(\[.*?\])\s*;",
        content,
        re.DOTALL
    )

    if not match:
        raise ValueError(
            "Cannot find const JOBS array in jobs.js"
        )

    return json.loads(match.group(1))


def save_jobs_js(jobs):

    content = (
        "const JOBS = "
        + json.dumps(
            jobs,
            ensure_ascii=False,
            indent=2
        )
        + ";\n"
    )

    JOBS_JS_FILE.write_text(
        content,
        encoding="utf-8"
    )

    logging.info("jobs.js saved: %s jobs", len(jobs))


# ============================================================
# DATE EXTRACTION
# ============================================================

MONTHS = (
    "January|February|March|April|May|June|July|August|"
    "September|October|November|December|"
    "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
)

DATE_PATTERN = (
    r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}"
    r"|\d{1,2}\s+(?:" + MONTHS + r")\s+\d{4}"
    r"|(?:" + MONTHS + r")\s+\d{1,2},?\s+\d{4}"
)


def parse_date(value):

    value = clean_text(value)

    formats = [
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%d.%m.%Y",
        "%Y-%m-%d",
        "%d-%m-%y",
        "%d/%m/%y",
        "%d.%m.%y",
        "%d %B %Y",
        "%d %b %Y",
        "%B %d, %Y",
        "%B %d %Y",
        "%b %d, %Y",
        "%b %d %Y"
    ]

    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass

    return None


def extract_deadline(text):

    if not text:
        return ""

    text = text.replace("\xa0", " ")

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    patterns = [
        r"last\s+date\s+for\s+submission",
        r"last\s+date\s+for\s+receipt",
        r"last\s+date\s+to\s+apply",
        r"closing\s+date\s+for\s+application",
        r"closing\s+date",
        r"last\s+date",
        r"deadline"
    ]

    for label in patterns:

        pattern = (
            r"(?is)"
            + label
            + r"[^.]{0,200}?"
            + r"(" + DATE_PATTERN + r")"
        )

        matches = re.finditer(
            pattern,
            text
        )

        for match in matches:

            parsed = parse_date(
                match.group(1)
            )

            if parsed:
                return parsed.isoformat()

    return ""


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


# ============================================================
# PDF EXTRACTION AND OCR
# ============================================================

def extract_pdf_text(pdf_url, job_id):

    PDF_DIR.mkdir(parents=True, exist_ok=True)

    pdf_path = PDF_DIR / f"{job_id}.pdf"

    try:

        response = fetch(pdf_url, timeout=120)

        if not response:
            return ""

        pdf_path.write_bytes(response.content)

    except Exception as error:

        logging.warning(
            "PDF download failed: %s | %s",
            job_id,
            error
        )

        return ""

    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

    pages_text = []

    try:

        with pdfplumber.open(pdf_path) as pdf:

            for page in pdf.pages:

                text = page.extract_text() or ""

                if len(text.strip()) < 40:

                    try:

                        image = page.to_image(
                            resolution=200
                        ).original

                        text = pytesseract.image_to_string(
                            image
                        )

                    except Exception as error:

                        logging.warning(
                            "OCR warning: %s",
                            error
                        )

                pages_text.append(text)

    except Exception as error:

        logging.warning(
            "PDF reading error: %s | %s",
            pdf_url,
            error
        )

        return ""

    return "\n".join(pages_text)


# ============================================================
# QUALIFICATION EXTRACTION
# ============================================================

def extract_qualification(text):

    if not text:
        return ""

    pattern = (
        r"(?is)"
        r"(essential qualifications?.*?)"
        r"(?=\n\s*(?:desirable qualifications?|"
        r"age limit|application fee|how to apply|"
        r"closing date|last date|important instructions)"
        r"\b)"
    )

    match = re.search(pattern, text)

    if match:
        return clean_text(match.group(1))[:12000]

    # Alternative wording used in some notifications.
    pattern = (
        r"(?is)"
        r"(educational qualifications?.*?)"
        r"(?=\n\s*(?:age limit|application fee|"
        r"how to apply|closing date|last date)"
        r"\b)"
    )

    match = re.search(pattern, text)

    if match:
        return clean_text(match.group(1))[:12000]

    return ""


def extract_qualification(text):

    if not text:
        return ""

    text = text.replace("\xa0", " ")

    text = re.sub(
        r"\r\n?",
        "\n",
        text
    )

    headings = [
        r"essential qualifications?",
        r"educational qualifications?",
        r"minimum qualifications?",
        r"eligibility criteria",
        r"essential educational qualifications?"
    ]

    end_headings = (
        r"desirable qualifications?|"
        r"age limit|"
        r"application fee|"
        r"how to apply|"
        r"closing date|"
        r"last date|"
        r"important instructions|"
        r"selection process|"
        r"general instructions"
    )

    for heading in headings:

        pattern = (
            r"(?is)"
            r"(?<!\w)"
            r"(" + heading + r")"
            r"\s*[:\-]?\s*"
            r"(.*?)"
            r"(?="
            r"\n\s*(?:" + end_headings + r")\b"
            r"|$"
            r")"
        )

        match = re.search(
            pattern,
            text
        )

        if match:

            qualification = clean_text(
                match.group(2)
            )

            if len(qualification) >= 20:
                return qualification[:12000]

    return ""


# ============================================================
# HPPSC SCANNER
# ============================================================

def scan_hppsc():

    logging.info("Reading HPPSC advertisement table")

    response = fetch(TABLE_URL, timeout=90)

    if not response:
        logging.error("HPPSC table could not be downloaded")
        return []

    TEMP_HTML.parent.mkdir(parents=True, exist_ok=True)

    TEMP_HTML.write_text(
        response.text,
        encoding="utf-8"
    )

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    rows = soup.select("#cpdatatables tbody tr")

    if not rows:
        logging.warning(
            "HPPSC table returned no rows"
        )

        return []

    links = []

    cutoff = TODAY - timedelta(days=RECENT_DAYS)

    for row in rows:

        link = row.select_one(
            "a[href*='CMSFileView']"
        )

        if not link:
            continue

        pdf_url = urljoin(
            BASE_URL,
            link["href"]
        )

        title = clean_text(
            link.get_text(" ", strip=True)
        )

        if not title:
            continue

        row_date = get_row_date(row)

        if not row_date:
            logging.info(
                "No publication date found: %s",
                title
            )
            continue

        if row_date < cutoff:
            continue

        links.append({
            "title": title,
            "url": pdf_url,
            "source": "HPPSC",
            "sourceUrl": TABLE_URL,
            "publishedDate": row_date.isoformat()
        })

    return links


# ============================================================
# OTHER SOURCE SCANNER
# ============================================================

def scan_generic_source(source):

    source_url = source["url"]
    source_name = source["name"]
    source_type = source.get("type", "").lower()
    keyword_filter = source.get("filter", "").strip().lower()

    response = fetch(source_url)

    if not response:
        return []

    soup = BeautifulSoup(
        response.content,
        "html.parser"
    )

    results = []

    for anchor in soup.find_all("a", href=True):

        href = anchor.get("href", "").strip()

        if not href:
            continue

        full_url = urljoin(source_url, href)

        title = clean_text(
            anchor.get_text(" ", strip=True)
        )

        combined = (
            title + " " + full_url
        ).lower()

        # Only accept HTTP/HTTPS links.
        if not full_url.startswith(("http://", "https://")):
            continue

        # Apply configured source filter.
        if keyword_filter and keyword_filter not in combined:
            continue

        # Identify recruitment-related links.
        relevant = (
            ".pdf" in urlparse(full_url).path.lower()
            or any(
                word in combined
                for word in [
                    "recruitment",
                    "advertisement",
                    "vacancy",
                    "notification",
                    "career",
                    "application",
                    "selection",
                    "constable",
                    "teacher",
                    "assistant",
                    "post",
                    "job"
                ]
            )
        )

        if not relevant:
            continue

        results.append({
            "title": title,
            "url": full_url,
            "source": source_name,
            "sourceUrl": source_url,
            "publishedDate": "",
            "sourceType": source_type
        })

    unique = {}

    for item in results:
        unique[normalize_url(item["url"])] = item

    logging.info(
        "%s: found %s relevant links",
        source_name,
        len(unique)
    )

    return list(unique.values())


# ============================================================
# BUILD CANDIDATE RECORD
# ============================================================
def extract_vacancies(text):

    if not text:
        return ""

    patterns = [
        r"total\s+number\s+of\s+vacancies\s*[:\-]?\s*(\d{1,5})",
        r"total\s+vacancies\s*[:\-]?\s*(\d{1,5})",
        r"total\s+posts\s*[:\-]?\s*(\d{1,5})",
        r"number\s+of\s+posts\s*[:\-]?\s*(\d{1,5})"
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE
        )

        if match:

            try:
                number = int(match.group(1))

                if 1 <= number <= 50000:
                    return str(number)

            except ValueError:
                pass

    return ""


def extract_age(text):

    if not text:
        return ""

    patterns = [
        r"(?:age limit|age should be|age must be)"
        r".{0,100}?(\d{2})\s*(?:to|–|-|and)\s*(\d{2})\s*years",

        r"(?:between|from)\s+(\d{2})\s*(?:to|and|-)\s*"
        r"(\d{2})\s*years"
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE
        )

        if match:

            lower = int(match.group(1))
            upper = int(match.group(2))

            if 18 <= lower < upper <= 70:
                return f"{lower}-{upper} years"

    return ""

def build_job(link):

    url = normalize_url(link["url"])

    job_id = (
        "job-"
        + make_id(url)
    )

    title = clean_text(
        link.get("title", "")
    )

    text = extract_pdf_text(
        url,
        job_id
    )

    if not title:
        lines = [
            clean_text(line)
            for line in text.splitlines()
            if clean_text(line)
        ]

        for line in lines[:30]:

            if any(
                word in line.lower()
                for word in [
                    "recruitment",
                    "advertisement",
                    "vacancy",
                    "post of"
                ]
            ):
                title = line[:250]
                break

    deadline = extract_deadline(text)
    qualification = extract_qualification(text)

    age = extract_age(text)
    vacancies = extract_vacancies(text)

    job = {
        "id": job_id,
        "post": title or "Check official notification",
        "department": link.get("source", ""),
        "source": link.get("source", ""),
        "qualification": qualification or "Check official notification",
        "subject": "",
        "criteria": (
            "Verify age, category and other eligibility "
            "conditions in the official notification."
        ),
        "deadline": deadline,
        "status": "review",
        "reason": (
            "Automatically collected. Verify official "
            "notification before publishing."
        ),
        "notificationUrl": url,
        "applyUrl": "",
        "publishedDate": link.get("publishedDate", ""),
        "ageLimit": age,
        "vacancies": vacancies,
        "verificationStatus": "review",
        "lastChecked": TODAY.isoformat()
    }

    if not deadline:
        job["reason"] += " Deadline not extracted."

    if not qualification:
        job["reason"] += " Qualification not extracted."

    if not vacancies:
        job["reason"] += " Vacancy count not extracted."

    return job


# ============================================================
# MERGE EXISTING JOBS SAFELY
# ============================================================

def merge_existing(existing, new):

    merged = dict(existing)

    # Only update extracted information if the old field
    # is empty. Preserve manually verified data and status.
    fields = [
        "qualification",
        "deadline",
        "ageLimit",
        "vacancies",
        "publishedDate"
    ]

    for field in fields:

        new_value = new.get(field)

        if new_value and not existing.get(field):
            merged[field] = new_value

    merged["lastChecked"] = TODAY.isoformat()

    return merged


# ============================================================
# MAIN
# ============================================================

def main():

    logging.info("HP Government Jobs scanner started")

    sources = load_sources()

    existing = load_existing_jobs()

    existing_by_url = {}

    for job in existing:

        url = job_url(job)

        if url:
            existing_by_url[url] = job

    discovered = {}

    # Always scan HPPSC using its known table.
    try:

        for link in scan_hppsc():

            discovered[
                normalize_url(link["url"])
            ] = link

    except Exception as error:

        logging.exception(
            "HPPSC scan failed: %s",
            error
        )

    # Scan configured sources, including HPRCA and other
    # sources supplied through sources.json.
    for source in sources:

        name = source["name"]

        if "hppsc" in name.lower():
            continue

        logging.info("Scanning source: %s", name)

        try:

            for link in scan_generic_source(source):

                url = normalize_url(link["url"])

                if url:
                    discovered[url] = link

        except Exception as error:

            logging.exception(
                "Source scan failed: %s",
                name
            )

    logging.info(
        "Unique notifications discovered: %s",
        len(discovered)
    )

    live_jobs = []
    new_candidates = []
    review_jobs = []

    seen = set()

    # Process existing jobs first.
    for url, job in existing_by_url.items():

        if url in discovered:

            try:

                refreshed = build_job(
                    discovered[url]
                )

                job = merge_existing(
                    job,
                    refreshed
                )

                logging.info(
                    "Existing job rechecked: %s",
                    job.get("post", url)
                )

            except Exception as error:

                logging.warning(
                    "Existing job refresh failed: %s | %s",
                    url,
                    error
                )

        live_jobs.append(job)
        seen.add(url)

    # Process newly discovered notifications.
    for url, link in discovered.items():

        if url in seen:
            continue

        try:

            candidate = build_job(link)

            deadline = candidate.get("deadline", "")

            if deadline:

                deadline_date = date.fromisoformat(deadline)

                if deadline_date >= TODAY:

                    new_candidates.append(candidate)

                else:

                    logging.info(
                        "Closed notification skipped: %s",
                        candidate.get("post")
                    )

            else:

                review_jobs.append(candidate)

        except Exception as error:

            logging.exception(
                "Candidate processing failed: %s | %s",
                url,
                error
            )

            review_jobs.append({
                "post": link.get("title", ""),
                "source": link.get("source", ""),
                "notificationUrl": url,
                "status": "review",
                "reason": "Scanner encountered an extraction error."
            })

    # Preserve existing preview entries, avoiding duplicates.
    old_preview = read_json(
        PREVIEW_FILE,
        []
    )

    preview_by_url = {}

    if isinstance(old_preview, list):

        for job in old_preview:

            url = job_url(job)

            if url:
                preview_by_url[url] = job

    for job in new_candidates:

        url = job_url(job)

        if url:
            preview_by_url[url] = job

    # Do not add new candidates to live jobs.
    save_json(
        PREVIEW_FILE,
        list(preview_by_url.values())
    )

    # Preserve old review jobs and avoid duplicates.
    old_review = read_json(REVIEW_FILE, [])
    review_by_url = {}

    if isinstance(old_review, list):
        for job in old_review:
            url = job_url(job)
            if url:
                review_by_url[url] = job

    for job in review_jobs:
        url = job_url(job)
        if url:
            review_by_url[url] = job

    save_json(
        REVIEW_FILE,
        list(review_by_url.values())
    )

    save_json(
        JOBS_FILE,
        live_jobs
    )

    save_jobs_js(live_jobs)

    logging.info("----------------------------------")
    logging.info("Scanner completed successfully")
    logging.info("Existing/live jobs: %s", len(live_jobs))
    logging.info("New candidates: %s", len(new_candidates))
    logging.info("Needs review: %s", len(review_jobs))
    logging.info("----------------------------------")


if __name__ == "__main__":
    main()
