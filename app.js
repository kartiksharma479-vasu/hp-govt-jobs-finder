
/* =========================================================
   HP GOVT JOBS FINDER — MAIN APP
   Profile matching + jobs + saved jobs + review
   ========================================================= */

const $ = (id) => document.getElementById(id);

const pages = [
  "home",
  "explore",
  "eligible",
  "saved",
  "noteligible",
  "review",
  "profile"
];

/* ---------------- STORAGE ---------------- */

function loadStorage(key, fallback) {
  try {
    const value = JSON.parse(localStorage.getItem(key) || "null");
    return value ?? fallback;
  } catch {
    return fallback;
  }
}

function saveStorage(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch (error) {
    console.error("Storage error:", error);
    return false;
  }
}

let savedIds = loadStorage("hpjf_saved", []);
let profile = loadStorage("hpjf_profile", {});

if (!Array.isArray(savedIds)) savedIds = [];
if (!profile || typeof profile !== "object" || Array.isArray(profile)) {
  profile = {};
}

/* ---------------- SECURITY HELPERS ---------------- */

function escapeHtml(value = "") {
  return String(value).replace(/[&<>"']/g, c => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  }[c]));
}

function safeUrl(value) {
  try {
    const url = new URL(String(value || ""), window.location.href);

    if (!["http:", "https:"].includes(url.protocol)) {
      return "";
    }

    return url.href;
  } catch {
    return "";
  }
}

function normalize(value = "") {
  return String(value)
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s]/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function isSaved(job) {
  return savedIds.includes(String(job.id));
}

/* ---------------- DATE HELPERS ---------------- */

function parseJobDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(value || ""))) {
    return null;
  }

  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(year, month - 1, day);

  if (
    date.getFullYear() !== year ||
    date.getMonth() !== month - 1 ||
    date.getDate() !== day
  ) {
    return null;
  }

  return date;
}

function formatDate(value) {
  const date = parseJobDate(value);

  if (!date) return "Not specified";

  return date.toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric"
  });
}

function isDeadlineOpen(job) {
  const deadline = parseJobDate(job.deadline);

  if (!deadline) return true;

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  return deadline >= today;
}

/* ---------------- PROFILE MATCHING ---------------- */

/*
  IMPORTANT:
  This is a preliminary profile-based match only.
  It does not certify legal eligibility.

  Official age limits, category relaxations, experience,
  domicile, marks and notification-specific conditions
  must be checked by the applicant.
*/

function profileComplete() {
  return Boolean(
    profile.qualification &&
    profile.subject
  );
}

function qualificationLevel(value) {
  const q = normalize(value);

  if (
    q.includes("phd") ||
    q.includes("doctorate")
  ) return 5;

  if (
    q.includes("post graduation") ||
    q.includes("postgraduate") ||
    q.includes("master") ||
    q.includes("m a") ||
    q.includes("m sc") ||
    q.includes("m com") ||
    q.includes("mba") ||
    q.includes("m tech")
  ) return 4;

  if (
    q.includes("graduation") ||
    q.includes("graduate") ||
    q.includes("bachelor") ||
    q.includes("b a") ||
    q.includes("b sc") ||
    q.includes("b com") ||
    q.includes("b tech")
  ) return 3;

  if (
    q.includes("diploma")
  ) return 2;

  if (
    q.includes("12th") ||
    q.includes("10+2") ||
    q.includes("senior secondary")
  ) return 1;

  if (
    q.includes("10th") ||
    q.includes("matric")
  ) return 0;

  return -1;
}

function getJobText(job) {
  return normalize([
    job.post,
    job.department,
    job.qualification,
    job.subject,
    job.criteria,
    job.ageLimit,
    job.reason
  ].join(" "));
}

function getProfileSubject() {
  return normalize(profile.subject || "");
}

function subjectMatch(job) {
  const subject = getProfileSubject();

  if (!subject || subject === "any" || subject === "all") {
    return true;
  }

  const text = getJobText(job);

  const aliases = {
    "political science": [
      "political science",
      "political studies"
    ],
    "economics": [
      "economics",
      "economic"
    ],
    "history": [
      "history",
      "historical"
    ],
    "geography": [
      "geography",
      "geographical"
    ],
    "sociology": [
      "sociology",
      "sociological"
    ],
    "anthropology": [
      "anthropology",
      "anthropological"
    ],
    "agriculture": [
      "agriculture",
      "agricultural"
    ],
    "english": [
      "english"
    ],
    "hindi": [
      "hindi"
    ],
    "commerce": [
      "commerce"
    ],
    "mathematics": [
      "mathematics",
      "mathematical"
    ],
    "physics": [
      "physics",
      "physical sciences"
    ],
    "chemistry": [
      "chemistry",
      "chemical sciences"
    ],
    "botany": [
      "botany",
      "botanical"
    ],
    "zoology": [
      "zoology",
      "zoological"
    ],
    "law": [
      "law",
      "legal"
    ],
    "education": [
      "education",
      "educational"
    ],
    "medical": [
      "medical",
      "medicine",
      "mbbs"
    ]
  };

  const terms = aliases[subject] || [subject];

  return terms.some(term => text.includes(normalize(term)));
}

function qualificationMatch(job) {
  const userLevel = qualificationLevel(profile.qualification);

  if (userLevel < 0) return null;

  const text = getJobText(job);

  /*
    Identify minimum qualifications only where possible.
    Do not assume every mention in the notification is
    the minimum qualification.
  */

  const requiredPatterns = [
    {
      pattern: /\b(phd|doctorate|doctoral degree)\b/i,
      level: 5
    },
    {
      pattern: /\b(post.?graduate|master.?s degree|master degree|m\.?sc|m\.?a\.|m\.?com|mba|m\.?tech)\b/i,
      level: 4
    },
    {
      pattern: /\b(graduation|graduate|bachelor.?s degree|bachelor degree|b\.?sc|b\.?a\.|b\.?com|b\.?tech)\b/i,
      level: 3
    },
    {
      pattern: /\b(diploma)\b/i,
      level: 2
    },
    {
      pattern: /\b(10\+2|12th|senior secondary|higher secondary)\b/i,
      level: 1
    },
    {
      pattern: /\b(10th|matriculation|matric)\b/i,
      level: 0
    }
  ];

  /*
    Use the highest explicit qualification level found.
    This is only a broad filter; subject-specific
    requirements remain subject to official verification.
  */

  const foundLevels = requiredPatterns
    .filter(item => item.pattern.test(text))
    .map(item => item.level);

  if (!foundLevels.length) return null;

  const minimumLevel = Math.min(...foundLevels);

  return userLevel >= minimumLevel;
}

function calculatePotentialMatch(job) {
  if (!profileComplete()) {
    return "review";
  }

  const qualification = qualificationMatch(job);
  const subject = subjectMatch(job);

  /*
    Do not infer a confirmed legal eligibility result
    from incomplete or automatically extracted data.
  */

  if (qualification === false || subject === false) {
    return "noteligible";
  }

  return "review";
}

function getDisplayStatus(job) {
  /*
    Explicit human-reviewed status takes priority.
    Only explicit verified statuses are displayed as such.
  */

  const status = normalize(job.status);

  if (
    status === "eligible" &&
    job.verificationStatus === "verified"
  ) {
    return "eligible";
  }

  if (
    status === "noteligible" &&
    job.verificationStatus === "verified"
  ) {
    return "noteligible";
  }

  return calculatePotentialMatch(job);
}

function statusLabel(status) {
  if (status === "eligible") return "Eligible — verified";
  if (status === "noteligible") return "Not eligible — verified";
  return "Potential match — verify";
}

/* ---------------- JOB CARD ---------------- */

function jobCard(job) {
  const saved = isSaved(job);

  const qualification =
    job.qualification || "Check official notification";

  const qualificationText = String(qualification);

  const deadlineText = formatDate(job.deadline);

  const notificationUrl = safeUrl(job.notificationUrl);

  /*
    Only show Apply Now when an application URL has
    been explicitly marked verified in the job data.
  */

  const applyUrl =
    job.applyVerified === true
      ? safeUrl(job.applyUrl)
      : "";

  const apply = applyUrl
    ? `<a class="small-btn primary"
          href="${escapeHtml(applyUrl)}"
          target="_blank"
          rel="noopener noreferrer">
          Apply Now ↗
       </a>`
    : `<span class="small-btn disabled"
             title="Verified official application link is not available">
             Apply link pending
       </span>`;

  const notice = notificationUrl
    ? `<a class="small-btn"
          href="${escapeHtml(notificationUrl)}"
          target="_blank"
          rel="noopener noreferrer">
          Notification ↗
       </a>`
    : `<span class="small-btn disabled">
          Notice pending
       </span>`;

  const qualificationDisplay =
    qualificationText.length > 180
      ? `${escapeHtml(qualificationText.slice(0, 180))}...
         <details>
           <summary>View More</summary>
           <div>${escapeHtml(qualificationText)}</div>
         </details>`
      : escapeHtml(qualificationText);

  const status = getDisplayStatus(job);

  const statusClass = [
    "eligible",
    "noteligible",
    "review"
  ].includes(status)
    ? status
    : "review";

  const deadlineStatus = isDeadlineOpen(job)
    ? ""
    : `<span class="meta-value">Application deadline passed</span>`;

  return `
    <article class="job-card">

      <div class="job-card-top">
        <span class="source-chip">
          ${escapeHtml(job.source || "Source pending")}
        </span>

        <button
          class="save-btn ${saved ? "saved" : ""}"
          data-save="${escapeHtml(job.id)}"
          aria-label="${saved ? "Remove saved job" : "Save job"}"
          aria-pressed="${saved}">
          ${saved ? "♥" : "♡"}
        </button>
      </div>

      <h3>${escapeHtml(job.post || "Post details pending")}</h3>

      <p class="job-dept">
        ${escapeHtml(job.department || "Department not specified")}
      </p>

      <div class="job-meta">

        <div>
          <span class="meta-label">Qualification</span>
          <span class="meta-value">
            ${qualificationDisplay}
          </span>
        </div>

        <div>
          <span class="meta-label">Last date</span>
          <span class="meta-value">
            ${deadlineText}
          </span>
          ${deadlineStatus}
        </div>

      </div>

      <p class="job-dept">
        <strong>Criteria:</strong>
        ${escapeHtml(job.criteria || "Check official notification")}
      </p>

      <p class="job-dept">
        <strong>Age limit:</strong>
        ${escapeHtml(job.ageLimit || "Check official notification")}
      </p>

      <p class="job-dept">
        <strong>Vacancies:</strong>
        ${escapeHtml(job.vacancies || "Check official notification")}
      </p>

      <div class="card-bottom">

        <span class="eligibility ${statusClass}">
          ${statusLabel(status)}
        </span>

        <div class="card-actions">
          ${notice}
          ${apply}
        </div>

      </div>

    </article>
  `;
}

/* ---------------- RENDER HELPERS ---------------- */

function emptyState(title, desc) {
  return `
    <div class="empty-state">
      <strong>${escapeHtml(title)}</strong>
      <p>${escapeHtml(desc)}</p>
    </div>
  `;
}

function renderGrid(
  id,
  jobs,
  emptyTitle = "No jobs found",
  emptyDesc = "Try changing your search or filters."
) {
  const container = $(id);

  if (!container) return;

  container.innerHTML = jobs.length
    ? jobs.map(jobCard).join("")
    : emptyState(emptyTitle, emptyDesc);
}

function getJobsByStatus(status) {
  return JOBS.filter(job => getDisplayStatus(job) === status);
}

/* ---------------- MAIN RENDER ---------------- */

function render() {
  const openJobs = JOBS.filter(isDeadlineOpen);

  const eligible = getJobsByStatus("eligible")
    .filter(isDeadlineOpen);

  const notEligible = getJobsByStatus("noteligible");

  const review = JOBS.filter(job =>
    getDisplayStatus(job) === "review"
  );

  const saved = JOBS.filter(isSaved);

  if ($("statAll")) {
    $("statAll").textContent = openJobs.length;
  }

  if ($("statEligible")) {
    $("statEligible").textContent = eligible.length;
  }

  if ($("statSaved")) {
    $("statSaved").textContent = saved.length;
  }

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const soon = new Date(today);
  soon.setDate(soon.getDate() + 14);

  const closingCount = JOBS.filter(job => {
    const deadline = parseJobDate(job.deadline);

    return deadline && deadline >= today && deadline <= soon;
  }).length;

  if ($("statClosing")) {
    $("statClosing").textContent = closingCount;
  }

  if ($("eligibleCount")) {
    $("eligibleCount").textContent = eligible.length;
  }

  if ($("savedCount")) {
    $("savedCount").textContent = saved.length;
  }

  renderGrid(
    "homeJobs",
    eligible.slice(0, 4),
    "No verified eligible jobs",
    "Complete your profile and check potential matches under Explore All Jobs."
  );

  renderGrid(
    "eligibleJobs",
    eligible,
    "No verified eligible jobs",
    "Potential matches are shown separately until official conditions are verified."
  );

  renderGrid(
    "savedJobs",
    saved,
    "No saved jobs yet",
    "Use the heart icon on any job card to save it."
  );

  renderGrid(
    "notEligibleJobs",
    notEligible,
    "No jobs in this section",
    "Jobs marked as not eligible after verification will appear here."
  );

  renderGrid(
    "reviewJobs",
    review,
    "No jobs pending verification",
    "New notifications and potential profile matches will appear here."
  );

  filterExplore();
}

/* ---------------- EXPLORE SEARCH ---------------- */

function filterExplore() {
  const q = normalize($("exploreSearch")?.value || "");
  const source = $("sourceFilter")?.value || "";
  const elig = $("eligibilityFilter")?.value || "";

  const list = JOBS.filter(job => {
    const searchable = normalize([
      job.post,
      job.department,
      job.qualification,
      job.source,
      job.subject
    ].join(" "));

    const matchesSearch = searchable.includes(q);
    const matchesSource = !source || job.source === source;

    const status = getDisplayStatus(job);

    let matchesEligibility = true;

    if (elig === "eligible") {
      matchesEligibility = status === "eligible";
    } else if (elig === "noteligible") {
      matchesEligibility = status === "noteligible";
    } else if (elig === "review") {
      matchesEligibility = status === "review";
    }

    return matchesSearch && matchesSource && matchesEligibility;
  });

  if ($("exploreResults")) {
    $("exploreResults").textContent =
      `${list.length} job${list.length === 1 ? "" : "s"}`;
  }

  renderGrid("exploreJobs", list);
}

/* ---------------- NAVIGATION ---------------- */

function showPage(page) {
  if (!pages.includes(page)) return;

  pages.forEach(p => {
    const section = $("page-" + p);

    if (section) {
      section.classList.toggle("active", p === page);
    }
  });

  document.querySelectorAll("[data-page]").forEach(button => {
    button.classList.toggle(
      "active",
      button.dataset.page === page
    );
  });

  const labels = {
    home: "Home",
    explore: "Explore All Jobs",
    eligible: "Eligible Jobs",
    saved: "Saved Jobs",
    noteligible: "Not Eligible",
    review: "Review Jobs",
    profile: "My Profile"
  };

  if ($("pageCrumb")) {
    $("pageCrumb").textContent = labels[page] || "Home";
  }

  $("sidebar")?.classList.remove("open");

  window.scrollTo({
    top: 0,
    behavior: "smooth"
  });
}

/* ---------------- CLICK EVENTS ---------------- */

document.addEventListener("click", e => {
  const nav = e.target.closest("[data-page]");

  if (nav) {
    showPage(nav.dataset.page);
    return;
  }

  const save = e.target.closest("[data-save]");

  if (save) {
    const id = String(save.dataset.save || "");

    if (savedIds.includes(id)) {
      savedIds = savedIds.filter(x => x !== id);
    } else {
      savedIds.push(id);
    }

    saveStorage("hpjf_saved", savedIds);
    render();
  }
});

/* ---------------- MOBILE SIDEBAR ---------------- */

$("menuToggle")?.addEventListener("click", () => {
  $("sidebar")?.classList.toggle("open");
});

/* ---------------- EXPLORE FILTERS ---------------- */

["exploreSearch", "sourceFilter", "eligibilityFilter"]
  .forEach(id => {
    $(id)?.addEventListener("input", filterExplore);
    $(id)?.addEventListener("change", filterExplore);
  });

/* ---------------- HOME SEARCH ---------------- */

$("homeSearchBtn")?.addEventListener("click", () => {
  if ($("exploreSearch") && $("homeSearch")) {
    $("exploreSearch").value = $("homeSearch").value;
  }

  showPage("explore");
  filterExplore();
});

$("homeSearch")?.addEventListener("keydown", e => {
  if (e.key === "Enter") {
    $("homeSearchBtn")?.click();
  }
});

/* ---------------- PROFILE ---------------- */

function fillProfile() {
  [
    "name",
    "qualification",
    "subject",
    "category",
    "dob",
    "bonafide",
    "net",
    "bed"
  ].forEach(key => {
    if ($(key)) {
      $(key).value = profile[key] || "";
    }
  });

  const name = profile.name || "My Profile";

  if ($("topName")) {
    $("topName").textContent = name;
  }

  if ($("sidebarName")) {
    $("sidebarName").textContent = profile.name || "Your Profile";
  }

  const initial = (profile.name || "U")
    .trim()
    .charAt(0)
    .toUpperCase();

  document.querySelectorAll(".avatar").forEach(avatar => {
    avatar.textContent = initial || "U";
  });
}

$("profileForm")?.addEventListener("submit", e => {
  e.preventDefault();

  const data = new FormData(e.target);
  const updatedProfile = {};

  for (const [key, value] of data.entries()) {
    updatedProfile[key] = String(value).trim();
  }

  profile = updatedProfile;

  const success = saveStorage("hpjf_profile", profile);

  fillProfile();
  render();

  if ($("profileSuccess")) {
    $("profileSuccess").textContent = success
      ? "Profile saved successfully."
      : "Could not save profile. Check browser storage settings.";

    $("profileSuccess").hidden = false;

    setTimeout(() => {
      $("profileSuccess").hidden = true;
    }, 3000);
  }
});

/* ---------------- SOURCE FILTER OPTIONS ---------------- */

function populateSourceFilter() {
  const select = $("sourceFilter");

  if (!select) return;

  const currentValue = select.value;

  const sources = [...new Set(
    JOBS.map(job => job.source).filter(Boolean)
  )].sort();

  select.innerHTML = `
    <option value="">All Sources</option>
    ${sources.map(source => `
      <option value="${escapeHtml(source)}">
        ${escapeHtml(source)}
      </option>
    `).join("")}
  `;

  if (sources.includes(currentValue)) {
    select.value = currentValue;
  }
}

/* ---------------- TODAY'S DATE ---------------- */

if ($("todayDate")) {
  $("todayDate").textContent = new Date().toLocaleDateString(
    "en-IN",
    {
      weekday: "short",
      day: "numeric",
      month: "short",
      year: "numeric"
    }
  );
}

/* ---------------- INITIAL SETUP ---------------- */

fillProfile();
populateSourceFilter();
render();
