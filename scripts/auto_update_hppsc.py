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
    if not is_http_url(url):
        logging.warning("Skipping invalid request URL: %r", url)
        return None

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

    # Keep None as None: callers use it to detect missing/corrupt files
    # and safely fall back to another database source.
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


def backup_file(path):
    """Create a timestamped backup before replacing an existing data file."""
    try:
        if path.exists() and path.is_file():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            backup = path.with_name(f"{path.name}.{stamp}.bak")
            backup.write_bytes(path.read_bytes())
            logging.info("Backup created: %s", backup)
    except OSError as error:
        raise RuntimeError(f"Could not back up {path}: {error}") from error


def clean_text(value):

    if not value:
        return ""

    value = str(value)
    value = value.replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def normalize_url(url):
    """Normalize a URL safely without raising on malformed values."""
    if not isinstance(url, str):
        return ""
    return url.strip().rstrip("/")


def is_http_url(value):
    """Return True only for absolute HTTP(S) URLs with a host."""
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = urlparse(value.strip())
        return parsed.scheme.lower() in ("http", "https") and bool(parsed.netloc)
    except (TypeError, ValueError):
        return False


def job_url(job):
    # Old preview/review files may contain malformed non-object rows.
    if not isinstance(job, dict):
        return ""

    raw_url = str(
        job.get("notificationUrl")
        or job.get("applyUrl")
        or job.get("applicationUrl")
        or job.get("url")
        or ""
    ).strip()

    markdown_match = re.fullmatch(
        r"\[.*?\]\((https?://[^)]+)\)",
        raw_url
    )

    if markdown_match:
        raw_url = markdown_match.group(1)

    if not is_http_url(raw_url):
        return ""

    return normalize_url(raw_url)


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

    if not isinstance(raw, list):
        logging.warning("sources.json must contain a list or a {sources: [...]} object")
        raw = []

    sources = []

    for source in raw:

        if not isinstance(source, dict):
            continue

        url = source.get("url") or source.get("website") or ""
        name = (
            source.get("name")
            or source.get("source")
            or source.get("organization")
            or "HP Government"
        )

        if not isinstance(url, str) or not is_http_url(url.strip()):
            logging.warning("Skipping source with invalid HTTP(S) URL: %r", url)
            continue

        if not isinstance(name, str):
            name = str(name)

        source = dict(source)
        source["url"] = url.strip()
        source["name"] = clean_text(name) or "HP Government"

        source_type = source.get("type", "")
        source["type"] = source_type.strip().lower() if isinstance(source_type, str) else ""

        keyword_filter = source.get("filter", "")
        source["filter"] = keyword_filter.strip().lower() if isinstance(keyword_filter, str) else ""

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

    jobs_from_json = None

    # First preference: data/jobs.json. A missing file is normal on first run.
    if JOBS_FILE.exists():
        try:
            data = read_json(JOBS_FILE, None)

            if isinstance(data, list):
                jobs_from_json = data

            elif isinstance(data, dict):
                jobs_from_json = data.get("jobs")

            if not isinstance(jobs_from_json, list):
                raise ValueError(
                    "jobs.json exists but has an invalid structure. "
                    "Fix or restore it before scanning; refusing to overwrite."
                )

        except Exception as error:
            logging.warning(
                "Could not load jobs.json: %s",
                error
            )

    # Fallback: preserve jobs already present in jobs.js
    if jobs_from_json is None:

        if not JOBS_JS_FILE.exists():
            raise FileNotFoundError(
                "Neither a valid jobs.json nor jobs.js exists. "
                "Refusing to overwrite the existing job database."
            )

        content = JOBS_JS_FILE.read_text(
            encoding="utf-8-sig"
        )

        match = re.search(
            r"const\s+JOBS\s*=\s*(\[.*\])\s*;",
            content,
            re.DOTALL
        )

        if not match:
            raise ValueError(
                "Could not safely read JOBS array from jobs.js. "
                "Refusing to overwrite existing jobs."
            )

        try:
            jobs_from_json = json.loads(match.group(1))

        except json.JSONDecodeError as error:
            raise ValueError(
                "jobs.js contains invalid JSON. "
                "No existing jobs will be overwritten."
            ) from error

    # Validate every record before returning.
    if not isinstance(jobs_from_json, list):
        raise ValueError(
            "Existing jobs database is not a list."
        )

    # An empty primary database can be legitimate for a first-time install,
    # but must not silently replace a populated jobs.js database.
    if not jobs_from_json and JOBS_FILE.exists() and JOBS_JS_FILE.exists():
        try:
            js_content = JOBS_JS_FILE.read_text(encoding="utf-8-sig")
            js_match = re.search(
                r"const\s+JOBS\s*=\s*(\[.*\])\s*;",
                js_content,
                re.DOTALL,
            )
            if js_match:
                js_jobs = json.loads(js_match.group(1))
                if isinstance(js_jobs, list) and js_jobs:
                    raise ValueError(
                        "jobs.json is empty but jobs.js contains records. "
                        "Refusing to proceed to protect the existing database."
                    )
        except json.JSONDecodeError as error:
            raise ValueError(
                "Could not validate jobs.js while jobs.json is empty; "
                "refusing to proceed."
            ) from error

    valid_jobs = []

    for job in jobs_from_json:

        if not isinstance(job, dict):
            raise ValueError(
                "Existing database contains a non-object job record. "
                "Refusing to proceed to prevent data loss."
            )

        if not job.get("id"):
            # Stable fallback ID preserves manually entered records.
            fallback = job_url(job) or clean_text(job.get("post", ""))
            if not fallback:
                raise ValueError(
                    "Existing job has neither ID, URL nor post title. "
                    "Refusing to discard it."
                )
            job = dict(job)
            job["id"] = "preserved-" + make_id(fallback)

        valid_jobs.append(job)

    logging.info(
        "Existing jobs safely loaded: %s",
        len(valid_jobs)
    )

    return valid_jobs


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

    JOBS_JS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_path = JOBS_JS_FILE.with_suffix(JOBS_JS_FILE.suffix + ".tmp")
    temp_path.write_text(content, encoding="utf-8")
    temp_path.replace(JOBS_JS_FILE)

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


def normalize_deadline(value):
    """Return ISO date for a parseable deadline, otherwise empty string."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if not value:
        return ""
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        parsed = parse_date(value)
        return parsed.isoformat() if parsed else ""


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

        response = fetch(
            pdf_url,
            timeout=120
        )

        if not response:
            return ""

        content = response.content

        # Reject empty responses.
        if not content:
            logging.warning(
                "Empty PDF response: %s",
                pdf_url
            )
            return ""

        # Validate the actual PDF file signature.
        if b"%PDF-" not in content[:1024]:
            logging.warning(
                "Invalid PDF content received: %s",
                pdf_url
            )
            return ""

        # Content-Type is not authoritative: some official portals serve
        # genuine PDF files as application/octet-stream or text/plain.
        # The PDF signature check above is the deciding validation.
        # Save only after basic validation.
        pdf_path.write_bytes(content)

    except Exception as error:

        logging.warning(
            "PDF download failed: %s | %s",
            job_id,
            error
        )

        return ""

    pytesseract.pytesseract.tesseract_cmd = (
        TESSERACT_PATH
    )

    pages_text = []

    try:

        with pdfplumber.open(pdf_path) as pdf:

            if not pdf.pages:
                logging.warning(
                    "PDF contains no pages: %s",
                    pdf_url
                )
                return ""

            for page in pdf.pages:

                text = page.extract_text() or ""

                # Use OCR for scanned or image-based pages.
                if len(text.strip()) < 40:

                    try:

                        image = page.to_image(
                            resolution=200
                        ).original

                        ocr_text = (
                            pytesseract.image_to_string(
                                image
                            )
                        )

                        if ocr_text.strip():
                            text = ocr_text

                    except Exception as error:

                        logging.warning(
                            "OCR warning: %s | %s",
                            pdf_url,
                            error
                        )

                pages_text.append(text)

    except Exception as error:

        logging.warning(
            "PDF reading error: %s | %s",
            pdf_url,
            error
        )

        # Remove corrupt or unreadable downloaded file.
        try:
            pdf_path.unlink(missing_ok=True)
        except OSError:
            pass

        return ""

    return "\n".join(pages_text)

# ============================================================
# QUALIFICATION EXTRACTION
# ============================================================

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
        r"essential educational qualifications?",
        r"essential qualifications?",
        r"educational qualifications?",
        r"minimum qualifications?",
        r"eligibility criteria"
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
                "No publication date found; retaining notification for review: %s",
                title
            )

        # Do not discard older advertisements solely by publication date:
        # a notification may still be open or have an extended deadline.
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
    source_type = source.get("type", "")
    source_type = source_type.lower() if isinstance(source_type, str) else ""
    keyword_filter = source.get("filter", "")
    keyword_filter = keyword_filter.strip().lower() if isinstance(keyword_filter, str) else ""

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

    raw_url = str(link.get("url", "")).strip()

    # Convert Markdown links into plain URLs
    markdown_match = re.fullmatch(
        r"\[.*?\]\((https?://[^)]+)\)",
        raw_url
    )

    if markdown_match:
        raw_url = markdown_match.group(1)

    url = normalize_url(raw_url)

    if not is_http_url(url):
        logging.warning("Skipping invalid notification URL: %r", raw_url)
        return None

    job_id = "job-" + make_id(url)

    title = clean_text(link.get("title", ""))

    text = extract_pdf_text(url, job_id)

    # Extract a title from the notification if the source has no title
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
        "qualification": (
            qualification
            or "Check official notification"
        ),
        "subject": "",
        "criteria": (
            "Verify age, category, domicile, experience "
            "and other eligibility conditions in the "
            "official notification."
        ),
        "deadline": deadline or "",
        "status": "review",
        "reason": (
            "Automatically collected. Official details "
            "and eligibility require verification."
        ),
        "notificationUrl": url,
        "applyUrl": "",
        "publishedDate": link.get("publishedDate", ""),
        "ageLimit": age or "",
        "vacancies": vacancies or "",
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
    """
    Merge scanned data while preserving manual verification.
    New records remain unverified until manually approved.
    """

    existing = existing if isinstance(existing, dict) else {}
    new = new if isinstance(new, dict) else {}

    merged = dict(existing)

    # Refresh fields extracted from official sources.
    refresh_fields = [
        "post",
        "department",
        "source",
        "qualification",
        "subject",
        "criteria",
        "deadline",
        "ageLimit",
        "vacancies",
        "publishedDate",
        "notificationUrl",
    ]

    was_manually_verified = (
        existing.get("verificationStatus") == "verified"
        and existing.get("applyVerified") is True
    )

    # Fields manually confirmed on a verified record are not overwritten by
    # automatic extraction. Store fresh extraction separately for comparison.
    protected_verified_fields = {
        "post", "department", "source", "qualification", "subject",
        "criteria", "deadline", "ageLimit", "vacancies", "publishedDate",
        "notificationUrl",
    }

    for field in refresh_fields:
        value = new.get(field)
        if value in (None, "", [], {}):
            continue
        if was_manually_verified and field in protected_verified_fields:
            if existing.get(field) not in (None, "", [], {}):
                if str(existing.get(field)).strip() != str(value).strip():
                    merged.setdefault("scannerChanges", {})[field] = value
                continue
        merged[field] = value

    # Preserve manually verified information and user-entered notes.
    manual_fields = [
        "verificationStatus", "applyVerified", "applyUrl", "verifiedBy",
        "verifiedAt", "manualNotes",
    ]

    for field in manual_fields:
        if field in existing:
            merged[field] = existing[field]

    # New records must never become verified automatically.
    if not existing:
        merged["verificationStatus"] = "review"
        merged["applyVerified"] = False
        merged["applyUrl"] = ""
        merged["status"] = "review"

    # Never downgrade manually verified records during automated refresh.
    if merged.get("verificationStatus") == "verified":
        merged["status"] = existing.get("status", "active")
        if existing.get("reason"):
            merged["reason"] = existing["reason"]
    else:
        merged["status"] = "review"
        if new.get("reason"):
            merged["reason"] = new["reason"]

    # Preserve original ID whenever available.
    merged["id"] = (
        existing.get("id")
        or new.get("id")
        or ""
    )

    # Unverified records remain under review.
    if merged.get("verificationStatus") != "verified":
        merged["status"] = "review"

    # Update last checked date.
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
    existing_without_url = []

    for job in existing:
        url = job_url(job)

        if not url:
            existing_without_url.append(job)
            continue

        if url not in existing_by_url:
            existing_by_url[url] = job
        else:
            # Preserve manually verified record if duplicate URLs exist.
            current = existing_by_url[url]
            current_verified = (
                current.get("verificationStatus") == "verified"
                and current.get("applyVerified") is True
            )
            incoming_verified = (
                job.get("verificationStatus") == "verified"
                and job.get("applyVerified") is True
            )
            if incoming_verified and not current_verified:
                existing_by_url[url] = job
            logging.warning("Duplicate existing job URL found; merged by retaining verified record: %s", url)

    discovered = {}
    scan_errors = []

    # Always scan HPPSC using its known table.
    try:
        for link in scan_hppsc():
            discovered[
                normalize_url(link["url"])
            ] = link

    except Exception as error:
        scan_errors.append("HPPSC")
        logging.exception(
            "HPPSC scan failed: %s",
            error
        )

    # Scan configured sources, including HPRCA.
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
            scan_errors.append(name)
            logging.exception(
                "Source scan failed: %s",
                name
            )

    if scan_errors:
        raise RuntimeError(
            "One or more configured sources failed (" + ", ".join(scan_errors) +
            "). No database files were changed. Fix the source/network issue and rerun."
        )

    logging.info(
        "Unique notifications discovered: %s",
        len(discovered)
    )

    if not discovered and existing:
        raise RuntimeError(
            "No notifications were discovered from any source while existing jobs exist. "
            "This may be a network/source outage; refusing to rewrite the databases."
        )

    live_jobs = []
    new_candidates = []
    review_jobs = []

    seen = set()

    # --------------------------------------------------------
    # PROCESS EXISTING JOBS
    # --------------------------------------------------------

    for url, job in existing_by_url.items():

        if url in discovered:

            try:
                refreshed = build_job(discovered[url])

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

        deadline = normalize_deadline(job.get("deadline", ""))
        if deadline:
            job["deadline"] = deadline
            try:
                deadline_date = date.fromisoformat(deadline)
                if deadline_date < TODAY:
                    logging.info("Expired job excluded: %s", job.get("post", url))
                    seen.add(url)
                    continue
            except (ValueError, TypeError):
                deadline = ""

        # Only a confirmed expired deadline removes a listing from Live.
        # Missing/invalid dates must not silently demote a manually verified job.
        apply_url = job.get("applyUrl")
        is_verified = (
            job.get("verificationStatus") == "verified"
            and job.get("applyVerified") is True
            and is_http_url(apply_url)
        )

        if is_verified:
            if not deadline:
                job["deadlineNeedsReview"] = True
                job["deadlineReviewNote"] = (
                    "Deadline is missing or invalid; verify the official notice."
                )
            live_jobs.append(job)
        else:
            if not deadline:
                job["reason"] = clean_text(job.get("reason", ""))
                if "deadline" not in job["reason"].lower():
                    job["reason"] = (job["reason"] + " Deadline missing or invalid; verify official notice.").strip()
            logging.info("Unverified job kept out of live database: %s", job.get("post", url))
            review_jobs.append(job)

        seen.add(url)

    # --------------------------------------------------------
    # PROCESS NEWLY DISCOVERED NOTIFICATIONS
    # --------------------------------------------------------

    for url, link in discovered.items():

        if url in seen:
            continue

        try:
            candidate = build_job(link)

            if not candidate:

                logging.warning(
                    "Invalid notification skipped: %s",
                    url
                )

                continue

            deadline = candidate.get("deadline", "")

            if not deadline:

                candidate["status"] = "review"
                candidate["verificationStatus"] = "review"

                candidate["reason"] = (
                    "Deadline not extracted. "
                    "Verify the official notification."
                )

                review_jobs.append(candidate)
                continue

            try:
                deadline_date = date.fromisoformat(
                    deadline
                )

            except (ValueError, TypeError):

                candidate["status"] = "review"
                candidate["verificationStatus"] = "review"

                candidate["reason"] = (
                    "Invalid deadline format. "
                    "Verify the official notification."
                )

                review_jobs.append(candidate)
                continue

            if deadline_date < TODAY:

                logging.info(
                    "Closed notification skipped: %s",
                    candidate.get("post")
                )

                continue

            # New notifications always require manual review.
            candidate["status"] = "review"
            candidate["verificationStatus"] = "review"
            candidate["applyVerified"] = False
            candidate["applyUrl"] = ""

            new_candidates.append(candidate)

        except Exception as error:

            logging.exception(
                "Candidate processing failed: %s | %s",
                url,
                error
            )

            review_jobs.append({
                "id": url,
                "post": link.get("title", ""),
                "source": link.get("source", ""),
                "notificationUrl": url,
                "deadline": "",
                "status": "review",
                "verificationStatus": "review",
                "applyVerified": False,
                "applyUrl": "",
                "reason": (
                    "Scanner encountered an extraction error."
                )
            })

    # Preserve manually maintained legacy records that have no URL.
    # They cannot be matched to a source reliably, so keep them in review.
    for legacy_job in existing_without_url:
        legacy_copy = dict(legacy_job)
        legacy_copy.setdefault("status", "review")
        legacy_copy.setdefault("verificationStatus", "review")
        legacy_copy.setdefault("reason", "Preserved existing record without a valid notification URL; verify manually.")
        review_jobs.append(legacy_copy)

    # Back up all current outputs before replacing any of them. If a backup
    # fails, the run stops before modifying the persisted databases.
    for output_path in (JOBS_FILE, JOBS_JS_FILE, PREVIEW_FILE, REVIEW_FILE):
        backup_file(output_path)

    # --------------------------------------------------------
    # PRESERVE AND UPDATE PREVIEW ENTRIES
    # --------------------------------------------------------

    old_preview = read_json(
        PREVIEW_FILE,
        []
    )

    preview_by_url = {}

    if isinstance(old_preview, list):

        for job in old_preview:
            if not isinstance(job, dict):
                logging.warning("Skipping malformed preview record.")
                continue

            url = job_url(job)

            if url:
                preview_by_url[url] = job

    # Add new candidates without overwriting manual details.
    for job in new_candidates:

        url = job_url(job)

        if url:

            preview_by_url[url] = merge_existing(
                preview_by_url.get(url, {}),
                job
            )

    # Remove preview entries that have expired or are now live.
    live_urls = {job_url(job) for job in live_jobs if job_url(job)}
    for old_url, old_job in list(preview_by_url.items()):
        old_deadline = old_job.get("deadline", "")
        if old_url in live_urls:
            preview_by_url.pop(old_url, None)
            continue
        if old_deadline:
            try:
                if date.fromisoformat(old_deadline) < TODAY:
                    preview_by_url.pop(old_url, None)
            except (ValueError, TypeError):
                pass

    # A URL currently routed to review must not also remain in preview.
    current_review_urls = {
        job_url(job) for job in review_jobs
        if isinstance(job, dict) and job_url(job)
    }
    for review_url in current_review_urls:
        preview_by_url.pop(review_url, None)

    # Reconcile all buckets globally, including stale entries not rediscovered
    # in this scan. Live wins over review, and review wins over preview.
    current_live_urls = {job_url(job) for job in live_jobs if job_url(job)}
    for bucket_url in current_live_urls:
        preview_by_url.pop(bucket_url, None)

    # Candidates remain separate from live/review jobs.
    save_json(
        PREVIEW_FILE,
        list(preview_by_url.values())
    )

    # --------------------------------------------------------
    # PRESERVE AND UPDATE REVIEW ENTRIES
    # --------------------------------------------------------

    old_review = read_json(
        REVIEW_FILE,
        []
    )

    review_by_url = {}

    if isinstance(old_review, list):

        for job in old_review:
            if not isinstance(job, dict):
                logging.warning("Skipping malformed review record.")
                continue

            url = job_url(job)

            if url:
                review_by_url[url] = job

    # Add review jobs without overwriting existing details.
    for job in review_jobs:

        url = job_url(job)

        if url:

            review_by_url[url] = merge_existing(
                review_by_url.get(url, {}),
                job
            )

    # Remove expired review records and records already promoted to live.
    live_urls = {job_url(job) for job in live_jobs if job_url(job)}
    for old_url, old_job in list(review_by_url.items()):
        if old_url in live_urls:
            review_by_url.pop(old_url, None)
            continue
        old_deadline = old_job.get("deadline", "")
        if old_deadline:
            try:
                if date.fromisoformat(old_deadline) < TODAY:
                    review_by_url.pop(old_url, None)
            except (ValueError, TypeError):
                pass

    # A URL currently routed to preview must not also remain in review.
    current_preview_urls = {
        job_url(job) for job in new_candidates
        if isinstance(job, dict) and job_url(job)
    }
    for preview_url in current_preview_urls:
        review_by_url.pop(preview_url, None)

    # Live and preview are mutually exclusive with Review across the full
    # persisted buckets, not merely records discovered during this run.
    all_live_urls = {job_url(job) for job in live_jobs if job_url(job)}
    all_preview_urls = {job_url(job) for job in preview_by_url.values() if job_url(job)}
    for bucket_url in all_live_urls | all_preview_urls:
        review_by_url.pop(bucket_url, None)

    save_json(
        REVIEW_FILE,
        list(review_by_url.values())
    )

    # --------------------------------------------------------
    # SAVE LIVE JOBS
    # --------------------------------------------------------

    # Canonical jobs.json contains all records from live, preview and review.
    # jobs.js remains the front-end LIVE/verified-only feed.
    canonical_by_key = {}

    def canonical_key(record):
        url_key = job_url(record)
        if url_key:
            return "url:" + url_key
        return "id:" + str(record.get("id", ""))

    for bucket in (
        live_jobs,
        list(preview_by_url.values()),
        list(review_by_url.values()),
    ):
        for record in bucket:
            if not isinstance(record, dict):
                continue
            key = canonical_key(record)
            if key and key not in ("id:",):
                current = canonical_by_key.get(key)
                if current is None:
                    canonical_by_key[key] = record
                else:
                    # Preserve manually verified fields if duplicate bucket entries exist.
                    if (
                        record.get("verificationStatus") == "verified"
                        and record.get("applyVerified") is True
                    ):
                        canonical_by_key[key] = record

    # Include URL-less preserved records too.
    for record in existing_without_url:
        key = canonical_key(record)
        if key != "id:":
            canonical_by_key.setdefault(key, record)

    save_json(JOBS_FILE, list(canonical_by_key.values()))
    save_jobs_js(live_jobs)

    logging.info("----------------------------------")
    logging.info("Scanner completed successfully")
    logging.info("Existing/live jobs: %s", len(live_jobs))
    logging.info("New candidates: %s", len(new_candidates))
    logging.info("Needs review: %s", len(review_jobs))
    logging.info("----------------------------------")


if __name__ == "__main__":
    main()
