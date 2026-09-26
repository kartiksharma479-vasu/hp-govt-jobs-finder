// HP Govt Jobs Finder - Main App

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

// Safely load data from browser storage
function loadStorage(key, fallback) {
  try {
    const value = JSON.parse(localStorage.getItem(key) || "null");
    return value ?? fallback;
  } catch {
    return fallback;
  }
}

let savedIds = loadStorage("hpjf_saved", []);
let profile = loadStorage("hpjf_profile", {});

if (!Array.isArray(savedIds)) savedIds = [];
if (!profile || typeof profile !== "object" || Array.isArray(profile)) {
  profile = {};
}

// Safely escape text before displaying it
function escapeHtml(value = "") {
  return String(value).replace(/[&<>"']/g, c => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  }[c]));
}

// Only allow valid HTTP/HTTPS URLs for external links
function safeUrl(value) {
  try {
    const url = new URL(String(value || ""));
    return ["http:", "https:"].includes(url.protocol)
      ? url.href
      : "";
  } catch {
    return "";
  }
}

function statusLabel(status) {
  if (status === "eligible") return "Eligible";
  if (status === "noteligible") return "Not eligible";
  return "Needs verification";
}

function isSaved(job) {
  return savedIds.includes(String(job.id));
}

// Safely parse a date stored as YYYY-MM-DD
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

function jobCard(job) {
  const saved = isSaved(job);

  const qualification =
    job.qualification || "Check official notification";

  const qualificationText = String(qualification);

  const deadlineText = formatDate(job.deadline);

  const applyUrl = safeUrl(job.applyUrl);
  const notificationUrl = safeUrl(job.notificationUrl);

  const apply = applyUrl
    ? `<a class="small-btn primary"
          href="${escapeHtml(applyUrl)}"
          target="_blank"
          rel="noopener noreferrer">
          Apply Now ↗
       </a>`
    : `<span class="small-btn disabled"
             title="Official application link not verified">
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
      ? escapeHtml(qualificationText.slice(0, 180)) +
        `...<details>
          <summary>View More</summary>
          <div>${escapeHtml(qualificationText)}</div>
        </details>`
      : escapeHtml(qualificationText);

  const status = [
    "eligible",
    "noteligible",
    "review"
  ].includes(job.status)
    ? job.status
    : "review";

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
        </div>

      </div>

      <p class="job-dept">
        <strong>Criteria:</strong>
        ${escapeHtml(job.criteria || "Check official notification")}
      </p>

      <div class="card-bottom">

        <span class="eligibility ${status}">
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

// Get jobs by their explicitly stored status
function getJobsByStatus(status) {
  return JOBS.filter(job => job.status === status);
}

function render() {
  const eligible = getJobsByStatus("eligible");
  const notEligible = getJobsByStatus("noteligible");
  const review = JOBS.filter(job =>
    !["eligible", "noteligible"].includes(job.status)
  );

  const saved = JOBS.filter(isSaved);

  $("statAll").textContent = JOBS.length;
  $("statEligible").textContent = eligible.length;
  $("statSaved").textContent = saved.length;

  // Count jobs closing today through the next 14 days
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const soon = new Date(today);
  soon.setDate(soon.getDate() + 14);

  const closingCount = JOBS.filter(job => {
    const deadline = parseJobDate(job.deadline);

    return deadline && deadline >= today && deadline <= soon;
  }).length;

  $("statClosing").textContent = closingCount;

  $("eligibleCount").textContent = eligible.length;
  $("savedCount").textContent = saved.length;

  renderGrid(
    "homeJobs",
    eligible.slice(0, 4),
    "No matching jobs yet",
    "Complete your profile or check Explore All Jobs."
  );

  renderGrid(
    "eligibleJobs",
    eligible,
    "No verified eligible jobs",
    "Jobs will appear here when they are explicitly marked eligible."
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
    "No jobs currently marked as not eligible."
  );

  renderGrid(
    "reviewJobs",
    review,
    "No jobs pending review",
    "New jobs requiring verification will appear here."
  );

  filterExplore();
}

// Explore search and filters
function filterExplore() {
  const q = ($("exploreSearch")?.value || "").toLowerCase().trim();
  const source = $("sourceFilter")?.value || "";
  const elig = $("eligibilityFilter")?.value || "";

  const list = JOBS.filter(job => {
    const searchable = [
      job.post,
      job.department,
      job.qualification,
      job.source
    ].join(" ").toLowerCase();

    const matchesSearch = searchable.includes(q);
    const matchesSource = !source || job.source === source;

    let matchesEligibility = true;

    if (elig === "eligible") {
      matchesEligibility = job.status === "eligible";
    } else if (elig === "noteligible") {
      matchesEligibility = job.status === "noteligible";
    } else if (elig === "review") {
      matchesEligibility =
        !["eligible", "noteligible"].includes(job.status);
    }

    return matchesSearch && matchesSource && matchesEligibility;
  });

  $("exploreResults").textContent =
    `${list.length} job${list.length === 1 ? "" : "s"}`;

  renderGrid("exploreJobs", list);
}

// Navigation between pages
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

  $("pageCrumb").textContent = labels[page] || "Home";

  $("sidebar").classList.remove("open");

  window.scrollTo({
    top: 0,
    behavior: "smooth"
  });
}

// Navigation and save buttons
document.addEventListener("click", e => {
  const nav = e.target.closest("[data-page]");

  if (nav) {
    showPage(nav.dataset.page);
    return;
  }

  const save = e.target.closest("[data-save]");

  if (save) {
    const id = save.dataset.save;

    if (savedIds.includes(id)) {
      savedIds = savedIds.filter(x => x !== id);
    } else {
      savedIds.push(id);
    }

    localStorage.setItem(
      "hpjf_saved",
      JSON.stringify(savedIds)
    );

    render();
  }
});

// Mobile sidebar
$("menuToggle").addEventListener("click", () => {
  $("sidebar").classList.toggle("open");
});

// Explore filters
["exploreSearch", "sourceFilter", "eligibilityFilter"]
  .forEach(id => {
    $(id).addEventListener("input", filterExplore);
  });

// Home search
$("homeSearchBtn").addEventListener("click", () => {
  $("exploreSearch").value = $("homeSearch").value;

  showPage("explore");
  filterExplore();
});

$("homeSearch").addEventListener("keydown", e => {
  if (e.key === "Enter") {
    $("homeSearchBtn").click();
  }
});

// Load saved profile into form
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

  $("topName").textContent = name;
  $("sidebarName").textContent = profile.name || "Your Profile";

  const initial = (profile.name || "U")
    .trim()
    .charAt(0)
    .toUpperCase();

  document.querySelectorAll(".avatar").forEach(avatar => {
    avatar.textContent = initial || "U";
  });
}

// Save profile
$("profileForm").addEventListener("submit", e => {
  e.preventDefault();

  const data = new FormData(e.target);

  profile = {};

  for (const [key, value] of data.entries()) {
    profile[key] = value;
  }

  localStorage.setItem(
    "hpjf_profile",
    JSON.stringify(profile)
  );

  fillProfile();

  $("profileSuccess").hidden = false;

  setTimeout(() => {
    $("profileSuccess").hidden = true;
  }, 3000);
});

// Today's date
$("todayDate").textContent = new Date().toLocaleDateString(
  "en-IN",
  {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric"
  }
);

// Initial page setup
fillProfile();
render();
