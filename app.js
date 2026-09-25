const $ = (id) => document.getElementById(id);
const pages = ["home","explore","eligible","saved","noteligible","profile"];
let savedIds = JSON.parse(localStorage.getItem("hpjf_saved") || "[]");
let profile = JSON.parse(localStorage.getItem("hpjf_profile") || "{}");

function statusLabel(status){return status==="eligible"?"Eligible":status==="noteligible"?"Not eligible":"Needs verification"}
function isSaved(job){return savedIds.includes(job.id)}
function escapeHtml(value=""){return String(value).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}
function jobCard(job){
  const saved=isSaved(job);
  const deadline=new Date(job.deadline+"T00:00:00");
  const dateText=isNaN(deadline)?"Not specified":deadline.toLocaleDateString("en-IN",{day:"numeric",month:"short",year:"numeric"});
  const apply=job.applyUrl ? `<a class="small-btn primary" href="${escapeHtml(job.applyUrl)}" target="_blank" rel="noopener">Apply Now ↗</a>` : `<span class="small-btn disabled" title="Official application link not verified">Apply link pending</span>`;
  const notice=job.notificationUrl ? `<a class="small-btn" href="${escapeHtml(job.notificationUrl)}" target="_blank" rel="noopener">Notification ↗</a>` : `<span class="small-btn disabled">Notice pending</span>`;
  return `<article class="job-card">
    <div class="job-card-top"><span class="source-chip">${escapeHtml(job.source)}</span><button class="save-btn ${saved?"saved":""}" data-save="${escapeHtml(job.id)}" aria-label="Save job">${saved?"♥":"♡"}</button></div>
    <h3>${escapeHtml(job.post)}</h3><p class="job-dept">${escapeHtml(job.department)}</p>
    <div class="job-meta"><div><span class="meta-label">Qualification</span><span class="meta-value">${escapeHtml(job.qualification.length > 180 ? job.qualification.slice(0, 180) + "..." : job.qualification)}${job.qualification.length > 180 ? '<details><summary>View More</summary><div>' + escapeHtml(job.qualification) + '</div></details>' : ''}</span></div><div><span class="meta-label">Last date (sample)</span><span class="meta-value">${dateText}</span></div></div>
    <p class="job-dept"><strong>Criteria:</strong> ${escapeHtml(job.criteria)}</p>
    <div class="card-bottom"><span class="eligibility ${job.status}">${statusLabel(job.status)}</span><div class="card-actions">${notice}${apply}</div></div>
  </article>`;
}
function emptyState(title,desc){return `<div class="empty-state"><strong>${title}</strong><p>${desc}</p></div>`}
function renderGrid(id,jobs,emptyTitle="No jobs found",emptyDesc="Try changing your search or filters."){$(id).innerHTML=jobs.length?jobs.map(jobCard).join(""):emptyState(emptyTitle,emptyDesc)}
function render(){
  const eligible=JOBS.filter(j=>j.status==="eligible"),notEligible=JOBS.filter(j=>j.status!=="eligible"),saved=JOBS.filter(isSaved);
  $("statAll").textContent=JOBS.length;$("statEligible").textContent=eligible.length;$("statSaved").textContent=saved.length;
  const now=new Date();const soon=new Date();soon.setDate(now.getDate()+14);
  $("statClosing").textContent=JOBS.filter(j=>{const d=new Date(j.deadline+"T00:00:00");return d>=now&&d<=soon}).length;
  $("eligibleCount").textContent=eligible.length;$("savedCount").textContent=saved.length;
  renderGrid("homeJobs",eligible.slice(0,4),"No matching jobs yet","Complete your profile or check Explore All Jobs.");
  renderGrid("eligibleJobs",eligible,"No eligible demo jobs","New matching jobs will appear here when the database is connected.");
  renderGrid("savedJobs",saved,"No saved jobs yet","Use the heart icon on any job card to save it.");
  renderGrid("notEligibleJobs",notEligible,"No jobs in this section","Jobs requiring review or not matching the demo profile will appear here.");
  filterExplore();
}
function filterExplore(){
  const q=($("exploreSearch")?.value||"").toLowerCase(),source=$("sourceFilter")?.value||"",elig=$("eligibilityFilter")?.value||"";
  let list=JOBS.filter(j=>(`${j.post} ${j.department} ${j.qualification} ${j.source}`.toLowerCase().includes(q))&&(!source||j.source===source)&&(!elig||(elig==="eligible"?j.status==="eligible":elig==="noteligible"?j.status==="noteligible":j.status==="review")));
  $("exploreResults").textContent=`${list.length} job${list.length===1?"":"s"}`;
  renderGrid("exploreJobs",list);
}
function showPage(page){
  pages.forEach(p=>$("page-"+p).classList.toggle("active",p===page));
  document.querySelectorAll("[data-page]").forEach(b=>b.classList.toggle("active",b.dataset.page===page));
  $("pageCrumb").textContent=({home:"Home",explore:"Explore All Jobs",eligible:"Eligible Jobs",saved:"Saved Jobs",noteligible:"Not Eligible",profile:"My Profile"})[page]||"Home";
  $("sidebar").classList.remove("open");window.scrollTo({top:0,behavior:"smooth"});
}
document.addEventListener("click",e=>{
  const nav=e.target.closest("[data-page]");if(nav){showPage(nav.dataset.page);return}
  const save=e.target.closest("[data-save]");if(save){const id=save.dataset.save;savedIds=isSaved({id})?savedIds.filter(x=>x!==id):[...savedIds,id];localStorage.setItem("hpjf_saved",JSON.stringify(savedIds));render()}
});
$("menuToggle").addEventListener("click",()=>$("sidebar").classList.toggle("open"));
["exploreSearch","sourceFilter","eligibilityFilter"].forEach(id=>$(id).addEventListener("input",filterExplore));
$("homeSearchBtn").addEventListener("click",()=>{$("exploreSearch").value=$("homeSearch").value;showPage("explore");filterExplore()});
$("homeSearch").addEventListener("keydown",e=>{if(e.key==="Enter"){$("homeSearchBtn").click()}});
function fillProfile(){
  ["name","qualification","subject","category","dob","bonafide","net","bed"].forEach(k=>{if($(k)&&profile[k])$(k).value=profile[k]});
  const name=profile.name||"My Profile";$("topName").textContent=name;$("sidebarName").textContent=profile.name||"Your Profile";
  const initial=(profile.name||"U").trim().charAt(0).toUpperCase();document.querySelectorAll(".avatar").forEach(a=>a.textContent=initial||"U");
}
$("profileForm").addEventListener("submit",e=>{
  e.preventDefault();const data=new FormData(e.target);profile={};for(const [k,v] of data.entries())profile[k]=v;
  localStorage.setItem("hpjf_profile",JSON.stringify(profile));fillProfile();$("profileSuccess").hidden=false;setTimeout(()=>$("profileSuccess").hidden=true,3000);
});
$("todayDate").textContent=new Date().toLocaleDateString("en-IN",{weekday:"short",day:"numeric",month:"short",year:"numeric"});
fillProfile();render();
