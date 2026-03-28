import os
import json
from flask import Flask, request, jsonify, send_from_directory, render_template_string, session, redirect, url_for

BASE = os.path.dirname(__file__)
UPLOAD_DIR = os.path.join(BASE, "uploads")
ADMIN_UPLOAD_DIR = os.path.join(BASE, "admin_uploads")
QIMG_DIR = os.path.join(BASE, "question_images")
QUESTIONS_JSON = os.path.join(BASE, "questions.json")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(ADMIN_UPLOAD_DIR, exist_ok=True)

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "specialist2025")

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "change-me-in-production-32chars!")
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024

# Load questions once at startup
questions_data = []
if os.path.exists(QUESTIONS_JSON):
    with open(QUESTIONS_JSON) as f:
        questions_data = json.load(f)

# ---------------------------------------------------------------------------
# Browse page HTML — Light theme inspired by maica.com.au
# ---------------------------------------------------------------------------

BROWSE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Specialist Maths Question Bank</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&family=Lato:wght@400;700&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #f5f7fa;
  --surface: #ffffff;
  --border: #e2e8f0;
  --text: #1a202c;
  --text-secondary: #4a5568;
  --muted: #718096;
  --primary: #196061;
  --primary-dark: #042f3a;
  --primary-light: #e6f2f2;
  --primary-hover: #1a7a7b;
  --accent-green: #38a169;
  --accent-green-light: #f0fff4;
  --shadow-sm: 0 1px 3px rgba(0,0,0,.06);
  --shadow-md: 0 4px 12px rgba(0,0,0,.08);
  --radius: 12px;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Poppins','Lato',system-ui,sans-serif; background:var(--bg); color:var(--text); min-height:100vh; }
a { color:var(--primary); text-decoration:none; }

/* ----- Top bar ----- */
.topbar {
  background:var(--primary-dark);
  padding:0 32px;
  display:flex;
  align-items:center;
  gap:20px;
  position:sticky;
  top:0;
  z-index:100;
  height:60px;
  box-shadow: 0 2px 8px rgba(0,0,0,.15);
}
.topbar h1 {
  font-size:1.15rem;
  font-weight:700;
  color:#ffffff;
  white-space:nowrap;
  letter-spacing:-.01em;
}
.topbar .tabs { display:flex; gap:4px; margin-left:28px; }
.topbar .tab {
  background:none;
  border:none;
  color:rgba(255,255,255,.6);
  font-family:inherit;
  font-size:.875rem;
  font-weight:500;
  padding:8px 18px;
  border-radius:8px;
  cursor:pointer;
  text-decoration:none;
  transition:all .15s;
}
.topbar .tab:hover { color:#fff; background:rgba(255,255,255,.1); }
.topbar .tab.active { color:#fff; background:rgba(255,255,255,.15); }
.topbar .count {
  color:rgba(255,255,255,.7);
  font-size:.85rem;
  margin-left:auto;
  font-weight:500;
}
.admin-mode-btn {
  font-family:inherit;
  font-size:.8rem;
  font-weight:600;
  padding:6px 14px;
  border-radius:8px;
  border:1px solid rgba(255,255,255,.25);
  background:rgba(255,255,255,.1);
  color:#fff;
  cursor:pointer;
  text-decoration:none;
  transition:background .15s;
  flex-shrink:0;
  white-space:nowrap;
}
.admin-mode-btn:hover { background:rgba(255,255,255,.22); color:#fff; }
.admin-mode-btn.exit { border-color:rgba(252,129,129,.5); background:rgba(197,48,48,.25); }
.admin-mode-btn.exit:hover { background:rgba(197,48,48,.45); }

/* ----- Layout ----- */
.layout { display:flex; min-height:calc(100vh - 60px); }

/* ----- Sidebar ----- */
.sidebar {
  width:280px;
  min-width:280px;
  background:var(--surface);
  border-right:1px solid var(--border);
  padding:20px 16px;
  overflow-y:auto;
  position:sticky;
  top:60px;
  height:calc(100vh - 60px);
}
.sidebar h3 {
  font-size:.7rem;
  text-transform:uppercase;
  letter-spacing:.1em;
  color:var(--muted);
  margin:20px 0 8px;
  font-weight:600;
}
.sidebar h3:first-child { margin-top:4px; }
.filter-group { display:flex; flex-direction:column; gap:2px; }
.filter-btn {
  background:none;
  border:none;
  color:var(--text-secondary);
  font-family:inherit;
  font-size:.84rem;
  padding:7px 12px;
  border-radius:8px;
  cursor:pointer;
  text-align:left;
  display:flex;
  justify-content:space-between;
  align-items:center;
  transition:all .15s;
}
.filter-btn:hover { background:var(--primary-light); color:var(--primary); }
.filter-btn.active { background:var(--primary); color:#fff; }
.filter-btn.active .badge { color:rgba(255,255,255,.75); }
.filter-btn .badge { font-size:.75rem; color:var(--muted); min-width:24px; text-align:right; }

/* ----- Main ----- */
.main { flex:1; padding:28px 32px; max-width:1100px; }
.main .toolbar { display:flex; gap:12px; align-items:center; margin-bottom:20px; flex-wrap:wrap; }
.main .toolbar .active-filters { display:flex; gap:6px; flex-wrap:wrap; }
.chip {
  background:var(--primary-light);
  color:var(--primary);
  font-size:.75rem;
  font-weight:500;
  padding:4px 12px;
  border-radius:99px;
  display:flex;
  align-items:center;
  gap:6px;
  cursor:pointer;
  border:1px solid rgba(25,96,97,.15);
  transition:background .15s;
}
.chip:hover { background:rgba(25,96,97,.12); }
.chip .x { font-size:.6rem; opacity:.5; }
.clear-btn {
  font-family:inherit;
  font-size:.78rem;
  color:var(--muted);
  cursor:pointer;
  background:none;
  border:none;
  font-weight:500;
}
.clear-btn:hover { color:var(--primary); }

/* ----- Question cards ----- */
.qgrid { display:flex; flex-direction:column; gap:12px; }
.qcard {
  background:var(--surface);
  border:1px solid var(--border);
  border-radius:var(--radius);
  overflow:hidden;
  box-shadow:var(--shadow-sm);
  transition:all .2s;
}
.qcard:hover { box-shadow:var(--shadow-md); border-color:#cbd5e0; }
.qcard-header {
  display:flex;
  align-items:center;
  padding:14px 20px;
  gap:12px;
  cursor:pointer;
  user-select:none;
}
.qcard-header .qnum {
  font-weight:600;
  font-size:.88rem;
  color:var(--primary);
  min-width:32px;
}
.qcard-header .qtags { display:flex; gap:6px; flex-wrap:wrap; flex:1; }
.qtag {
  font-size:.7rem;
  font-weight:500;
  padding:3px 10px;
  border-radius:99px;
}
.qtag.aos { background:#e6f2f2; color:var(--primary); }
.qtag.pub { background:#f7fafc; color:var(--text-secondary); border:1px solid var(--border); }
.qcard-header .marks { color:var(--muted); font-size:.8rem; white-space:nowrap; }
.qcard-header .toggle-icon { color:var(--muted); font-size:.8rem; transition:transform .2s; }
.qcard.open .toggle-icon { transform:rotate(90deg); }

.qcard-body { display:none; padding:0 20px 20px; }
.qcard.open .qcard-body { display:block; }

.qimages { display:flex; gap:20px; flex-wrap:wrap; }
.qimg-wrap { flex:1; min-width:280px; }
.qimg-wrap h4 {
  font-size:.72rem;
  color:var(--muted);
  margin-bottom:8px;
  text-transform:uppercase;
  letter-spacing:.06em;
  font-weight:600;
}
.qimg-wrap img {
  width:100%;
  border-radius:8px;
  border:1px solid var(--border);
  background:#fff;
}

.sol-hidden { display:none; }
.show-sol-btn {
  font-family:inherit;
  background:var(--primary-light);
  color:var(--primary);
  border:1px solid rgba(25,96,97,.2);
  padding:9px 20px;
  border-radius:8px;
  cursor:pointer;
  font-size:.82rem;
  font-weight:500;
  transition:all .15s;
  align-self:flex-start;
  margin-top:4px;
}
.show-sol-btn:hover { background:var(--primary); color:#fff; }

/* ----- Pagination ----- */
.pagination { display:flex; justify-content:center; gap:6px; margin-top:28px; }
.page-btn {
  font-family:inherit;
  background:var(--surface);
  border:1px solid var(--border);
  color:var(--text-secondary);
  padding:7px 14px;
  border-radius:8px;
  cursor:pointer;
  font-size:.84rem;
  font-weight:500;
  transition:all .15s;
}
.page-btn:hover { border-color:var(--primary); color:var(--primary); }
.page-btn.active { background:var(--primary); border-color:var(--primary); color:#fff; }
.page-btn:disabled { opacity:.35; cursor:default; }

/* ----- Mobile ----- */
@media (max-width: 768px) {
  .sidebar { display:none; }
  .layout { flex-direction:column; }
  .main { padding:16px; }
  .topbar { padding:0 16px; }
}
.show-sidebar-btn {
  display:none;
  font-family:inherit;
  background:var(--surface);
  border:1px solid var(--border);
  color:var(--primary);
  padding:8px 16px;
  border-radius:8px;
  cursor:pointer;
  font-size:.85rem;
  font-weight:500;
}
@media (max-width: 768px) {
  .show-sidebar-btn { display:block; }
  .sidebar.mobile-open {
    display:block;
    position:fixed;
    top:60px;
    left:0;
    z-index:99;
    height:calc(100vh - 60px);
    box-shadow:4px 0 24px rgba(0,0,0,.12);
  }
}

.no-results { text-align:center; padding:60px 20px; color:var(--muted); }
.no-results p { font-size:1.05rem; margin-bottom:10px; }

.sort-unsorted-btn {
  display:block;
  width:100%;
  text-align:center;
  padding:10px 14px;
  margin-bottom:20px;
  border-radius:8px;
  background:#c53030;
  color:#fff;
  font-size:.85rem;
  font-weight:600;
  text-decoration:none;
  transition:background .15s;
}
.sort-unsorted-btn:hover { background:#9b2c2c; color:#fff; }

.admin-bar {
  display:flex;
  align-items:center;
  gap:8px;
  margin-top:12px;
  padding-top:12px;
  border-top:1px dashed #c53030;
}
.admin-reclassify {
  font-family:inherit;
  font-size:.8rem;
  padding:5px 8px;
  border-radius:6px;
  border:1px solid #c53030;
  background:var(--surface);
  color:var(--text);
  cursor:pointer;
  flex:1;
  max-width:280px;
}
.admin-delete-btn {
  font-size:1.1rem;
  background:none;
  border:1px solid #c53030;
  border-radius:6px;
  padding:4px 8px;
  cursor:pointer;
  color:#c53030;
  line-height:1;
  transition:background .15s;
}
.admin-delete-btn:hover { background:#fff0f0; }
</style>
</head>
<body>

<div class="topbar">
  <h1>Specialist Maths Question Bank</h1>
  <div class="tabs">
    <a class="tab active" href="/">Questions</a>
    {% if is_admin %}<a class="tab" href="/admin">Admin</a>{% endif %}
  </div>
  {% if is_admin %}
  <a class="admin-mode-btn exit" href="/admin/logout">Exit Admin Mode</a>
  {% else %}
  <a class="admin-mode-btn" href="/admin/login?next=/">Admin</a>
  {% endif %}
</div>

<div class="layout">
  <div class="sidebar" id="sidebar">
    {% if is_admin %}
    <a class="sort-unsorted-btn" id="sort-unsorted-btn" href="/classify?unsorted=1">Sort Unsorted (<span id="unsorted-count">…</span>)</a>
    {% endif %}
    <h3>Area of Study</h3>
    <div class="filter-group" id="fg-aos"></div>
    <h3>Year</h3>
    <div class="filter-group" id="fg-year"></div>
    <h3>Publisher</h3>
    <div class="filter-group" id="fg-pub"></div>
    <h3>Exam Type</h3>
    <div class="filter-group" id="fg-exam"></div>
    <h3>Section</h3>
    <div class="filter-group" id="fg-section"></div>
  </div>

  <div class="main">
    <div class="toolbar">
      <button class="show-sidebar-btn" onclick="document.getElementById('sidebar').classList.toggle('mobile-open')">Filters</button>
      <div class="active-filters" id="active-filters"></div>
      <button class="clear-btn" id="clear-btn" style="display:none" onclick="clearAll()">Clear all</button>
    </div>
    <div class="qgrid" id="qgrid"></div>
    <div class="pagination" id="pagination"></div>
  </div>
</div>

<script>
const IS_ADMIN = {{ is_admin|tojson }};
const PER_PAGE = 20;
let allQ = [];
let filtered = [];
let page = 0;
let filters = { aos: null, year: null, publisher: null, exam_type: null, section: null };

const sectionLabels = { short_answer: 'Short Answer', multiple_choice: 'Multiple Choice', extended_response: 'Extended Response' };

fetch('/api/questions').then(r => r.json()).then(data => {
  allQ = IS_ADMIN ? data : data.filter(q => q.aos !== 0);
  if (IS_ADMIN) {
    const el = document.getElementById('unsorted-count');
    if (el) el.textContent = data.filter(q => q.aos === 0).length;
  }
  buildFilters();
  applyFilters();
});

function buildFilters() {
  const counts = (key, labelFn) => {
    const m = {};
    allQ.forEach(q => { const v = labelFn ? labelFn(q) : q[key]; m[v] = (m[v]||0)+1; });
    return m;
  };

  buildGroup('fg-aos', counts('aos_name'), 'aos');
  buildGroup('fg-year', counts('year'), 'year');
  buildGroup('fg-pub', counts('publisher'), 'publisher');
  buildGroup('fg-exam', { 'Exam 1': allQ.filter(q=>q.exam_type===1).length, 'Exam 2': allQ.filter(q=>q.exam_type===2).length }, 'exam_type');
  buildGroup('fg-section', counts('section', q => sectionLabels[q.section]||q.section), 'section');
}

function buildGroup(elId, countsObj, filterKey) {
  const el = document.getElementById(elId);
  el.innerHTML = '';
  const sorted = Object.entries(countsObj).sort((a,b) => {
    if (filterKey === 'year') return a[0]-b[0];
    return b[1]-a[1];
  });
  sorted.forEach(([label, count]) => {
    const btn = document.createElement('button');
    btn.className = 'filter-btn';
    btn.innerHTML = `<span>${label}</span><span class="badge">${count}</span>`;
    btn.onclick = () => toggleFilter(filterKey, label, btn);
    el.appendChild(btn);
  });
}

function toggleFilter(key, value, btn) {
  if (filters[key] === value) {
    filters[key] = null;
    btn.classList.remove('active');
  } else {
    btn.parentElement.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    filters[key] = value;
    btn.classList.add('active');
  }
  page = 0;
  applyFilters();
}

function clearAll() {
  filters = { aos: null, year: null, publisher: null, exam_type: null, section: null };
  document.querySelectorAll('.filter-btn.active').forEach(b => b.classList.remove('active'));
  page = 0;
  applyFilters();
}

function applyFilters() {
  filtered = allQ.filter(q => {
    if (filters.aos && q.aos_name !== filters.aos) return false;
    if (filters.year && q.year !== Number(filters.year)) return false;
    if (filters.publisher && q.publisher !== filters.publisher) return false;
    if (filters.exam_type) {
      const en = filters.exam_type === 'Exam 1' ? 1 : 2;
      if (q.exam_type !== en) return false;
    }
    if (filters.section) {
      const sl = Object.entries(sectionLabels).find(([k,v]) => v===filters.section);
      if (sl && q.section !== sl[0]) return false;
    }
    return true;
  });

  renderActiveFilters();
  renderCards();
  renderPagination();
}

function renderActiveFilters() {
  const el = document.getElementById('active-filters');
  const clearBtn = document.getElementById('clear-btn');
  const active = Object.entries(filters).filter(([k,v]) => v !== null);
  clearBtn.style.display = active.length ? '' : 'none';
  el.innerHTML = active.map(([k,v]) =>
    `<span class="chip" onclick="removeFilter('${k}')">${v} <span class="x">&times;</span></span>`
  ).join('');
}

function removeFilter(key) {
  filters[key] = null;
  const groupMap = { aos:'fg-aos', year:'fg-year', publisher:'fg-pub', exam_type:'fg-exam', section:'fg-section' };
  document.querySelectorAll(`#${groupMap[key]} .filter-btn`).forEach(b => b.classList.remove('active'));
  page = 0;
  applyFilters();
}

function renderCards() {
  const grid = document.getElementById('qgrid');
  const start = page * PER_PAGE;
  const pageQ = filtered.slice(start, start + PER_PAGE);

  if (!pageQ.length) {
    grid.innerHTML = '<div class="no-results"><p>No questions match your filters</p><button class="clear-btn" onclick="clearAll()">Clear all filters</button></div>';
    return;
  }

  grid.innerHTML = pageQ.map(q => {
    const tags = [
      `<span class="qtag aos">${q.aos_name}</span>`,
      `<span class="qtag pub">${q.publisher} ${q.year}</span>`,
    ].join('');
    const sLabel = sectionLabels[q.section] || q.section;
    const marksStr = q.marks ? `${q.marks} marks` : '';
    const solInner = q.solution_image
      ? `<div class="qimg-wrap"><h4>Solution</h4><img src="${q.solution_image}" loading="lazy"/></div>`
      : '<div class="qimg-wrap"><h4>Solution</h4><p style="color:var(--muted);font-size:.85rem">Not available</p></div>';
    const solBtn = q.solution_image
      ? `<button class="show-sol-btn" onclick="toggleSol(this)">Show Solution</button>`
      : '';

    const adminControls = IS_ADMIN ? `
      <div class="admin-bar" onclick="event.stopPropagation()">
        <select class="admin-reclassify" onchange="adminReclassify('${q.id}', this)">
          <option value="">Reclassify…</option>
          <option value="1|Logic and Proof">1 — Logic and Proof</option>
          <option value="2|Functions, Relations and Graphs">2 — Functions, Relations and Graphs</option>
          <option value="3|Complex Numbers">3 — Complex Numbers</option>
          <option value="4|Calculus">4 — Calculus</option>
          <option value="5|Vectors, Lines and Planes">5 — Vectors, Lines and Planes</option>
          <option value="6|Probability and Statistics">6 — Probability and Statistics</option>
          <option value="0|Unsorted">Unsorted</option>
        </select>
        <button class="admin-delete-btn" onclick="adminDelete('${q.id}', this)" title="Delete question">&#128465;</button>
      </div>` : '';

    return `<div class="qcard" id="qcard-${q.id}" onclick="this.classList.toggle('open')">
      <div class="qcard-header">
        <span class="qnum">Q${q.question_number}</span>
        <div class="qtags">${tags}</div>
        <span class="marks">${sLabel}${marksStr ? ' &middot; '+marksStr : ''}</span>
        <span class="toggle-icon">&#9656;</span>
      </div>
      <div class="qcard-body" onclick="event.stopPropagation()">
        <div class="qimg-wrap"><h4>Question</h4><img src="${q.question_image}" loading="lazy"/></div>
        ${solBtn}
        <div class="sol-hidden">${solInner}</div>
        ${adminControls}
      </div>
    </div>`;
  }).join('');
}

function renderPagination() {
  const el = document.getElementById('pagination');
  const total = Math.ceil(filtered.length / PER_PAGE);
  if (total <= 1) { el.innerHTML = ''; return; }

  let html = `<button class="page-btn" ${page===0?'disabled':''} onclick="goPage(${page-1})">&larr; Prev</button>`;

  const start = Math.max(0, page - 3);
  const end = Math.min(total, start + 7);
  for (let i = start; i < end; i++) {
    html += `<button class="page-btn ${i===page?'active':''}" onclick="goPage(${i})">${i+1}</button>`;
  }
  html += `<button class="page-btn" ${page>=total-1?'disabled':''} onclick="goPage(${page+1})">Next &rarr;</button>`;
  el.innerHTML = html;
}

function toggleSol(btn) {
  const sol = btn.nextElementSibling;
  if (sol.classList.contains('sol-hidden')) {
    sol.classList.remove('sol-hidden');
    btn.textContent = 'Hide Solution';
  } else {
    sol.classList.add('sol-hidden');
    btn.textContent = 'Show Solution';
  }
}

function adminReclassify(id, sel) {
  const [aos, aosName] = sel.value.split('|');
  if (!aos && aos !== '0') return;
  fetch('/api/classify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id, aos: Number(aos), aos_name: aosName })
  }).then(r => r.json()).then(data => {
    if (data.ok) {
      const q = allQ.find(q => q.id === id);
      if (q) { q.aos = Number(aos); q.aos_name = aosName; }
      sel.value = '';
      document.getElementById('qcard-' + id)?.querySelector('.qtag.aos')?.replaceWith(
        Object.assign(document.createElement('span'), { className: 'qtag aos', textContent: aosName })
      );
    }
  });
}

function adminDelete(id, btn) {
  if (!confirm('Delete this question?')) return;
  fetch('/api/questions/' + id, { method: 'DELETE' })
    .then(r => r.json()).then(data => {
      if (data.ok) {
        allQ = allQ.filter(q => q.id !== id);
        filtered = filtered.filter(q => q.id !== id);
        document.getElementById('qcard-' + id)?.remove();
      }
    });
}

function goPage(p) {
  page = p;
  renderCards();
  renderPagination();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Classification tool HTML
# ---------------------------------------------------------------------------

CLASSIFY_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>{% if unsorted_mode %}Classify — Unsorted{% else %}Classify — {{ publisher }} {{ year }}{% endif %}</title>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Poppins',system-ui,sans-serif; background:#0f1117; color:#e2e8f0; min-height:100vh; }

.topbar {
  background:#042f3a;
  padding:0 32px;
  display:flex;
  align-items:center;
  gap:20px;
  height:56px;
  position:sticky;
  top:0;
  z-index:100;
  box-shadow:0 2px 8px rgba(0,0,0,.3);
}
.topbar h1 { font-size:1rem; font-weight:700; color:#fff; }
.topbar .back { color:rgba(255,255,255,.6); font-size:.85rem; text-decoration:none; }
.topbar .back:hover { color:#fff; }
.progress-bar-wrap {
  flex:1;
  max-width:300px;
  height:6px;
  background:rgba(255,255,255,.1);
  border-radius:99px;
  overflow:hidden;
}
.progress-bar { height:6px; background:#4ade80; border-radius:99px; transition:width .3s; }
.progress-label { color:rgba(255,255,255,.6); font-size:.8rem; white-space:nowrap; }

.container { max-width:900px; margin:0 auto; padding:32px 24px; display:flex; flex-direction:column; gap:32px; }

.qblock {
  background:#1a1d27;
  border:2px solid #2d3148;
  border-radius:16px;
  overflow:hidden;
  transition:border-color .2s;
  scroll-margin-top:80px;
}
.qblock.classified { border-color:#196061; }
.qblock-header {
  display:flex;
  align-items:center;
  gap:12px;
  padding:14px 20px;
  background:#12151f;
  border-bottom:1px solid #2d3148;
}
.qblock-header .qnum { font-weight:700; font-size:.95rem; color:#60a5fa; }
.qblock-header .qmeta { font-size:.78rem; color:#718096; }
.qblock-header .status {
  margin-left:auto;
  font-size:.75rem;
  font-weight:600;
  padding:3px 10px;
  border-radius:99px;
}
.status.unsaved { background:#2d2d1a; color:#f6e05e; }
.status.saved { background:#1a2e20; color:#4ade80; }

.qblock-img { padding:20px; }
.qblock-img img { width:100%; border-radius:8px; border:1px solid #2d3148; background:#fff; }

.aos-buttons {
  display:flex;
  flex-wrap:wrap;
  gap:8px;
  padding:0 20px 20px;
}
.aos-btn {
  font-family:inherit;
  font-size:.82rem;
  font-weight:500;
  padding:8px 18px;
  border-radius:99px;
  border:2px solid #2d3148;
  background:#12151f;
  color:#a0aec0;
  cursor:pointer;
  transition:all .15s;
}
.aos-btn:hover { border-color:#196061; color:#e2e8f0; }
.aos-btn.active {
  background:#196061;
  border-color:#196061;
  color:#fff;
}
.aos-btn.active-new {
  background:#1a4a2a;
  border-color:#4ade80;
  color:#4ade80;
}
.aos-btn.unsorted {
  border-color:#4a1a1a;
  color:#fc8181;
}
.aos-btn.unsorted:hover { border-color:#fc8181; background:#2a1a1a; }
.aos-btn.unsorted.active, .aos-btn.unsorted.active-new {
  background:#2a1a1a;
  border-color:#fc8181;
  color:#fc8181;
}
.status.unsorted-status { background:#2a1a1a; color:#fc8181; }
.aos-btn.pseudocode { border-color:#2d1a4a; color:#c084fc; }
.aos-btn.pseudocode:hover { border-color:#c084fc; background:#1e1030; }
.aos-btn.pseudocode.active, .aos-btn.pseudocode.active-new { background:#1e1030; border-color:#c084fc; color:#c084fc; }
.status.pseudocode-status { background:#1e1030; color:#c084fc; }

.exam-nav {
  background:#0a0d14;
  border-bottom:1px solid #1e2235;
  padding:8px 32px;
  display:flex;
  gap:8px;
  flex-wrap:wrap;
  align-items:center;
}
.exam-nav-label { font-size:.75rem; color:#4a5568; font-weight:600; text-transform:uppercase; letter-spacing:.05em; margin-right:4px; }
.exam-nav-btn {
  font-family:inherit;
  font-size:.78rem;
  font-weight:500;
  padding:5px 14px;
  border-radius:99px;
  border:1px solid #2d3148;
  background:none;
  color:#a0aec0;
  cursor:pointer;
  text-decoration:none;
  transition:all .15s;
}
.exam-nav-btn:hover { border-color:#196061; color:#e2e8f0; }
.exam-nav-btn.current { background:#196061; border-color:#196061; color:#fff; }
.exam-nav-btn.unsorted-tab { border-color:#4a1a1a; color:#fc8181; }
.exam-nav-btn.unsorted-tab:hover { border-color:#fc8181; background:#2a1a1a; color:#fc8181; }
.exam-nav-btn.unsorted-tab.current { background:#2a1a1a; border-color:#fc8181; color:#fc8181; }

.done-banner {
  display:none;
  text-align:center;
  padding:40px 24px;
  background:#1a2e20;
  border:2px solid #4ade80;
  border-radius:16px;
  color:#4ade80;
  font-size:1.1rem;
  font-weight:600;
}
</style>
</head>
<body>
<div class="topbar">
  <a class="back" href="/">← Back</a>
  <h1>{% if unsorted_mode %}Unsorted Questions ({{ questions|length }}){% else %}Classifying: {{ publisher }} {{ year }}{% endif %}</h1>
  <div class="progress-bar-wrap"><div class="progress-bar" id="progress-bar" style="width:0%"></div></div>
  <span class="progress-label" id="progress-label">0 / {{ questions|length }}</span>
</div>
<div class="exam-nav">
  <a class="exam-nav-btn unsorted-tab {% if unsorted_mode %}current{% endif %}"
     href="/classify?unsorted=1">Unsorted ({{ unsorted_count }})</a>
  <span class="exam-nav-label" style="margin-left:8px;">Exam set:</span>
  {% for pub, yr in exam_sets %}
  <a class="exam-nav-btn {% if not unsorted_mode and pub == publisher and yr == year %}current{% endif %}"
     href="/classify?publisher={{ pub }}&year={{ yr }}">{{ pub }} {{ yr }}</a>
  {% endfor %}
</div>

<div class="container" id="container">
{% for q in questions %}
<div class="qblock {% if q.aos %}classified{% endif %}" id="block-{{ q.id }}" data-id="{{ q.id }}">
  <div class="qblock-header">
    <span class="qnum">{{ q.publisher }} {{ q.year }} — Exam {{ q.exam_type }} Q{{ q.question_number }}</span>
    <span class="qmeta">{{ q.section.replace('_',' ').title() }}{% if q.marks %} · {{ q.marks }} marks{% endif %}</span>
    <span class="status {% if q.aos == 0 %}unsorted-status{% elif q.aos == 7 %}pseudocode-status{% elif q.aos %}saved{% else %}unsaved{% endif %}" id="status-{{ q.id }}">
      {% if q.aos == 0 %}Unsorted{% elif q.aos %}{{ q.aos_name }}{% else %}Unclassified{% endif %}
    </span>
  </div>
  <div class="qblock-img">
    <img src="{{ q.question_image }}" loading="lazy"/>
  </div>
  <div class="aos-buttons">
    {% set options = [
      (1, 'Logic and Proof'),
      (2, 'Functions, Relations and Graphs'),
      (3, 'Complex Numbers'),
      (4, 'Calculus'),
      (5, 'Vectors, Lines and Planes'),
      (6, 'Probability and Statistics'),
      (7, 'Pseudocode')
    ] %}
    {% for num, name in options %}
    <button class="aos-btn {% if q.aos == num %}active{% endif %} {% if num == 7 %}pseudocode{% endif %}"
            onclick="classify('{{ q.id }}', {{ num }}, '{{ name }}', this)">
      {{ name }}
    </button>
    {% endfor %}
    <button class="aos-btn unsorted {% if q.aos == 0 %}active{% endif %}"
            onclick="classify('{{ q.id }}', 0, 'Unsorted', this)">
      Unsorted
    </button>
  </div>
</div>
{% endfor %}
<div class="done-banner" id="done-banner">All {{ questions|length }} questions classified!</div>
</div>

<script>
const total = {{ questions|length }};
let classified = document.querySelectorAll('.qblock.classified').length;
updateProgress();

function classify(id, aos, aosName, btn) {
  const block = document.getElementById('block-' + id);
  const status = document.getElementById('status-' + id);

  // Update button states
  block.querySelectorAll('.aos-btn').forEach(b => {
    b.classList.remove('active', 'active-new');
  });
  btn.classList.add('active-new');

  // Update status badge
  const wasClassified = block.classList.contains('classified');
  if (!wasClassified) {
    classified++;
    block.classList.add('classified');
    updateProgress();
  }
  status.textContent = aosName;
  status.className = aos === 0 ? 'status unsorted-status' : aos === 7 ? 'status pseudocode-status' : 'status saved';

  fetch('/api/classify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id, aos, aos_name: aosName })
  }).then(r => r.json()).then(data => {
    if (data.ok) {
      btn.classList.remove('active-new');
      btn.classList.add('active');
    }
  });
}

function updateProgress() {
  const pct = total === 0 ? 0 : Math.round(classified / total * 100);
  document.getElementById('progress-bar').style.width = pct + '%';
  document.getElementById('progress-label').textContent = classified + ' / ' + total;
  if (classified === total) {
    document.getElementById('done-banner').style.display = 'block';
  }
}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template_string(BROWSE_HTML, is_admin=admin_required())

@app.route("/api/questions")
def api_questions():
    return jsonify(questions_data)

@app.route("/api/classify", methods=["POST"])
def api_classify():
    if not admin_required():
        return jsonify(error="forbidden"), 403
    data = request.get_json()
    qid = data.get("id")
    aos = data.get("aos")
    aos_name = data.get("aos_name")
    if not qid or aos is None:
        return jsonify(error="missing fields"), 400
    for q in questions_data:
        if q["id"] == qid:
            q["aos"] = aos
            q["aos_name"] = aos_name
            break
    else:
        return jsonify(error="question not found"), 404
    with open(QUESTIONS_JSON, "w") as f:
        json.dump(questions_data, f, indent=2)
    return jsonify(ok=True)

@app.route("/classify")
def classify_page():
    if not admin_required():
        return redirect(url_for("admin_login") + "?next=/classify")
    unsorted_mode = request.args.get("unsorted") == "1"
    publisher = request.args.get("publisher", "Heffernan")
    year = int(request.args.get("year", 2025))

    if unsorted_mode:
        questions = [q for q in questions_data if q["aos"] == 0]
    else:
        questions = [q for q in questions_data if q["publisher"] == publisher and q["year"] == year]

    seen = set()
    exam_sets = []
    for q in questions_data:
        key = (q["publisher"], q["year"])
        if key not in seen:
            seen.add(key)
            exam_sets.append(key)
    exam_sets.sort(key=lambda x: (x[0], x[1]))

    unsorted_count = sum(1 for q in questions_data if q["aos"] == 0)

    return render_template_string(CLASSIFY_HTML, questions=questions, publisher=publisher, year=year,
                                  exam_sets=exam_sets, unsorted_mode=unsorted_mode, unsorted_count=unsorted_count)

@app.route("/qimg/<path:filename>")
def serve_qimg(filename):
    return send_from_directory(QIMG_DIR, filename)

# Keep upload functionality at /upload-page
UPLOAD_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>Upload</title>
<style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:'Segoe UI',system-ui,sans-serif;background:#0f0f1a;color:#e0e0f0;min-height:100vh;display:flex;flex-direction:column;align-items:center;padding:48px 16px}h1{font-size:1.8rem;font-weight:700;background:linear-gradient(135deg,#a78bfa,#60a5fa);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:32px}#drop{width:100%;max-width:600px;border:2px dashed #3a3a5a;border-radius:16px;padding:48px 24px;text-align:center;cursor:pointer;transition:all .2s;background:#1a1a2e}#drop.over{border-color:#a78bfa;background:#1e1e35}#drop p{color:#8888aa;font-size:.95rem}#drop span{color:#a78bfa;text-decoration:underline;cursor:pointer}#file-input{display:none}.progress-wrap{width:100%;max-width:600px;display:none;flex-direction:column;gap:10px;margin:24px 0}.file-row{background:#1a1a2e;border:1px solid #2a2a4a;border-radius:10px;padding:12px 16px}.file-row .name{font-size:.85rem;color:#c0c0e0;margin-bottom:6px}.bar-bg{background:#12122a;border-radius:99px;height:6px;overflow:hidden}.bar{height:6px;border-radius:99px;width:0%;background:linear-gradient(90deg,#a78bfa,#60a5fa);transition:width .15s}.status{font-size:.75rem;color:#666688;margin-top:4px}.done .bar{background:#4ade80}.error .bar{background:#f87171}</style></head><body>
<h1>File Upload</h1>
<div id="drop"><p>Drop files here or <span onclick="document.getElementById('file-input').click()">browse</span></p><input type="file" id="file-input" multiple/></div>
<div class="progress-wrap" id="progress-wrap"></div>
<script>
const drop=document.getElementById('drop'),fi=document.getElementById('file-input'),pw=document.getElementById('progress-wrap');
drop.addEventListener('dragover',e=>{e.preventDefault();drop.classList.add('over')});
drop.addEventListener('dragleave',()=>drop.classList.remove('over'));
drop.addEventListener('drop',e=>{e.preventDefault();drop.classList.remove('over');handle(e.dataTransfer.files)});
fi.addEventListener('change',()=>handle(fi.files));
function handle(files){pw.style.display='flex';[...files].forEach(upload)}
function upload(file){const row=document.createElement('div');row.className='file-row';row.innerHTML=`<div class="name">${file.name}</div><div class="bar-bg"><div class="bar" id="b-${CSS.escape(file.name)}"></div></div><div class="status" id="s-${CSS.escape(file.name)}">Uploading…</div>`;pw.appendChild(row);const fd=new FormData();fd.append('file',file);const x=new XMLHttpRequest();x.open('POST','/upload');x.upload.onprogress=e=>{if(e.lengthComputable){const p=(e.loaded/e.total*100).toFixed(0);document.getElementById('b-'+CSS.escape(file.name)).style.width=p+'%';document.getElementById('s-'+CSS.escape(file.name)).textContent=p+'%'}};x.onload=()=>{if(x.status===200){document.getElementById('b-'+CSS.escape(file.name)).style.width='100%';row.classList.add('done');document.getElementById('s-'+CSS.escape(file.name)).textContent='Done'}else{row.classList.add('error')}};x.send(fd)}
</script></body></html>"""

@app.route("/upload-page")
def upload_page():
    return render_template_string(UPLOAD_HTML)

@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify(error="no file"), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify(error="empty filename"), 400
    filename = os.path.basename(f.filename)
    f.save(os.path.join(UPLOAD_DIR, filename))
    return jsonify(ok=True, filename=filename)

@app.route("/files")
def list_files():
    files = []
    for name in sorted(os.listdir(UPLOAD_DIR)):
        path = os.path.join(UPLOAD_DIR, name)
        if os.path.isfile(path):
            files.append({"name": name, "size": os.path.getsize(path)})
    return jsonify(files)

# ---------------------------------------------------------------------------
# Admin page — Light theme
# ---------------------------------------------------------------------------

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Admin Login</title>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Poppins',system-ui,sans-serif; background:#0f1117; min-height:100vh; display:flex; align-items:center; justify-content:center; }
.card { background:#1a1d27; border:1px solid #2d3148; border-radius:16px; padding:40px 36px; width:100%; max-width:380px; }
h1 { color:#e2e8f0; font-size:1.2rem; font-weight:600; margin-bottom:6px; }
p { color:#718096; font-size:.85rem; margin-bottom:28px; }
label { display:block; color:#a0aec0; font-size:.8rem; font-weight:500; margin-bottom:6px; }
input[type=password] {
  width:100%; padding:11px 14px; border-radius:8px; border:1px solid #2d3148;
  background:#12151f; color:#e2e8f0; font-family:inherit; font-size:.9rem;
  margin-bottom:16px; outline:none; transition:border-color .15s;
}
input[type=password]:focus { border-color:#196061; }
button { width:100%; padding:12px; border-radius:8px; border:none; background:#196061; color:#fff; font-family:inherit; font-size:.9rem; font-weight:600; cursor:pointer; transition:background .15s; }
button:hover { background:#1a7a7b; }
.error { color:#fc8181; font-size:.82rem; margin-bottom:14px; }
</style>
</head>
<body>
<div class="card">
  <h1>Admin Login</h1>
  <p>Enter your password to access the admin area.</p>
  {% if error %}<div class="error">{{ error }}</div>{% endif %}
  <form method="POST">
    <input type="hidden" name="next" value="{{ next_url }}"/>
    <label>Password</label>
    <input type="password" name="password" autofocus/>
    <button type="submit">Sign in</button>
  </form>
</div>
</body>
</html>"""

ADMIN_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Admin - Specialist Maths Question Bank</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&family=Lato:wght@400;700&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #f5f7fa;
  --surface: #ffffff;
  --border: #e2e8f0;
  --text: #1a202c;
  --text-secondary: #4a5568;
  --muted: #718096;
  --primary: #196061;
  --primary-dark: #042f3a;
  --primary-light: #e6f2f2;
  --accent-green: #38a169;
  --accent-green-light: #f0fff4;
  --red: #e53e3e;
  --shadow-sm: 0 1px 3px rgba(0,0,0,.06);
  --shadow-md: 0 4px 12px rgba(0,0,0,.08);
  --radius: 12px;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Poppins','Lato',system-ui,sans-serif; background:var(--bg); color:var(--text); min-height:100vh; }
a { color:var(--primary); text-decoration:none; }

.topbar {
  background:var(--primary-dark);
  padding:0 32px;
  display:flex;
  align-items:center;
  gap:20px;
  position:sticky;
  top:0;
  z-index:100;
  height:60px;
  box-shadow: 0 2px 8px rgba(0,0,0,.15);
}
.topbar h1 { font-size:1.15rem; font-weight:700; color:#ffffff; white-space:nowrap; }
.topbar .tabs { display:flex; gap:4px; margin-left:28px; }
.topbar .tab {
  background:none; border:none; color:rgba(255,255,255,.6); font-family:inherit;
  font-size:.875rem; font-weight:500; padding:8px 18px; border-radius:8px;
  cursor:pointer; text-decoration:none; transition:all .15s;
}
.topbar .tab:hover { color:#fff; background:rgba(255,255,255,.1); }
.topbar .tab.active { color:#fff; background:rgba(255,255,255,.15); }

.container { max-width:700px; margin:0 auto; padding:40px 24px; }

.section { margin-bottom:40px; }
.section h2 { font-size:1.15rem; font-weight:600; margin-bottom:6px; color:var(--primary-dark); }
.section p.desc { color:var(--muted); font-size:.88rem; margin-bottom:20px; line-height:1.6; }

#drop, #drop2 {
  border:2px dashed var(--border);
  border-radius:var(--radius);
  padding:48px 24px;
  text-align:center;
  cursor:pointer;
  transition:all .2s;
  background:var(--surface);
  box-shadow:var(--shadow-sm);
}
#drop.over, #drop2.over { border-color:var(--primary); background:var(--primary-light); }
#drop svg, #drop2 svg { width:44px; height:44px; color:var(--muted); margin-bottom:10px; }
#drop p, #drop2 p { color:var(--muted); font-size:.9rem; }
#drop span, #drop2 span { color:var(--primary); text-decoration:underline; cursor:pointer; font-weight:500; }
#file-input, #file-input2 { display:none; }

.progress-wrap { display:none; flex-direction:column; gap:10px; margin-top:16px; }
.file-row {
  background:var(--surface);
  border:1px solid var(--border);
  border-radius:10px;
  padding:12px 16px;
  box-shadow:var(--shadow-sm);
}
.file-row .name { font-size:.85rem; color:var(--text-secondary); margin-bottom:6px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.bar-bg { background:#edf2f7; border-radius:99px; height:6px; overflow:hidden; }
.bar { height:6px; border-radius:99px; width:0%; background:linear-gradient(90deg,var(--primary),var(--accent-green)); transition:width .15s; }
.status { font-size:.75rem; color:var(--muted); margin-top:4px; }
.done .bar { background:var(--accent-green); }
.error .bar { background:var(--red); }

.file-list { display:flex; flex-direction:column; gap:8px; margin-top:16px; }
.fitem {
  display:flex; align-items:center; justify-content:space-between;
  background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:10px 16px;
  box-shadow:var(--shadow-sm);
}
.fitem .fname { font-size:.85rem; color:var(--text-secondary); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.fitem .fmeta { display:flex; align-items:center; gap:12px; }
.fitem .fsize { color:var(--muted); font-size:.75rem; white-space:nowrap; }
.fitem .fdel { background:none; border:none; color:var(--red); cursor:pointer; font-size:.8rem; opacity:.4; transition:opacity .15s; padding:4px; }
.fitem .fdel:hover { opacity:1; }
.empty { color:var(--muted); font-size:.85rem; text-align:center; padding:20px; }
</style>
</head>
<body>

<div class="topbar">
  <h1>Specialist Maths Question Bank</h1>
  <div class="tabs">
    <a class="tab" href="/">Questions</a>
    <a class="tab active" href="/admin">Admin</a>
  </div>
</div>

<div class="container">
  <div class="section">
    <h2>Upload Reference Documents</h2>
    <p class="desc">Upload study designs, curriculum documents, or other reference files here. These will be used to improve question classification.</p>

    <div id="drop">
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5"/></svg>
      <p>Drop files here or <span onclick="document.getElementById('file-input').click()">browse</span></p>
      <input type="file" id="file-input" multiple/>
    </div>
    <div class="progress-wrap" id="progress-wrap"></div>
  </div>

  <div class="section">
    <h2>Uploaded Reference Files</h2>
    <div class="file-list" id="file-list"></div>
  </div>

  <div class="section">
    <h2>Upload New Exam Files</h2>
    <p class="desc">Upload exam PDFs or DOCX files. Place them in the correct year/publisher folder structure, or upload here and reorganise manually on the server.</p>
    <div id="drop2">
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5"/></svg>
      <p>Drop exam files here or <span onclick="document.getElementById('file-input2').click()">browse</span></p>
      <input type="file" id="file-input2" multiple/>
    </div>
    <div class="progress-wrap" id="progress-wrap2"></div>
  </div>
</div>

<script>
function fmt(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024**2) return (bytes/1024).toFixed(1) + ' KB';
  return (bytes/1024**2).toFixed(1) + ' MB';
}

// --- Reference doc upload ---
const drop = document.getElementById('drop');
const fi = document.getElementById('file-input');
const pw = document.getElementById('progress-wrap');

drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('over'); });
drop.addEventListener('dragleave', () => drop.classList.remove('over'));
drop.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('over'); handleRef(e.dataTransfer.files); });
fi.addEventListener('change', () => handleRef(fi.files));

function handleRef(files) {
  pw.style.display = 'flex';
  [...files].forEach(f => uploadFile(f, '/admin/upload', pw));
}

// --- Exam file upload ---
const drop2 = document.getElementById('drop2');
const fi2 = document.getElementById('file-input2');
const pw2 = document.getElementById('progress-wrap2');

drop2.addEventListener('dragover', e => { e.preventDefault(); drop2.classList.add('over'); });
drop2.addEventListener('dragleave', () => drop2.classList.remove('over'));
drop2.addEventListener('drop', e => { e.preventDefault(); drop2.classList.remove('over'); handleExam(e.dataTransfer.files); });
fi2.addEventListener('change', () => handleExam(fi2.files));

function handleExam(files) {
  pw2.style.display = 'flex';
  [...files].forEach(f => uploadFile(f, '/upload', pw2));
}

// --- Shared upload ---
function uploadFile(file, url, container) {
  const row = document.createElement('div');
  row.className = 'file-row';
  const eid = 'u-' + Math.random().toString(36).slice(2);
  row.innerHTML = `<div class="name">${file.name}</div><div class="bar-bg"><div class="bar" id="bar-${eid}"></div></div><div class="status" id="st-${eid}">Uploading...</div>`;
  container.appendChild(row);

  const fd = new FormData();
  fd.append('file', file);
  const xhr = new XMLHttpRequest();
  xhr.open('POST', url);
  xhr.upload.onprogress = e => {
    if (e.lengthComputable) {
      const pct = (e.loaded / e.total * 100).toFixed(0);
      document.getElementById('bar-' + eid).style.width = pct + '%';
      document.getElementById('st-' + eid).textContent = pct + '%';
    }
  };
  xhr.onload = () => {
    const bar = document.getElementById('bar-' + eid);
    const st = document.getElementById('st-' + eid);
    if (xhr.status === 200) {
      bar.style.width = '100%';
      row.classList.add('done');
      st.textContent = 'Done - ' + fmt(file.size);
      if (url === '/admin/upload') loadRefFiles();
    } else {
      row.classList.add('error');
      st.textContent = 'Failed';
    }
  };
  xhr.send(fd);
}

// --- File list ---
function loadRefFiles() {
  fetch('/admin/files').then(r => r.json()).then(files => {
    const el = document.getElementById('file-list');
    if (!files.length) { el.innerHTML = '<div class="empty">No reference files uploaded yet</div>'; return; }
    el.innerHTML = files.map(f =>
      `<div class="fitem">
        <span class="fname">${f.name}</span>
        <div class="fmeta">
          <span class="fsize">${fmt(f.size)}</span>
          <button class="fdel" onclick="delRef('${f.name.replace(/'/g, "\\'")}')" title="Delete">&#x2715;</button>
        </div>
      </div>`
    ).join('');
  });
}

function delRef(name) {
  if (!confirm('Delete ' + name + '?')) return;
  fetch('/admin/files/' + encodeURIComponent(name), { method:'DELETE' })
    .then(() => loadRefFiles());
}

loadRefFiles();
</script>
</body>
</html>"""

def admin_required():
    return session.get("admin_logged_in") is True

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    next_url = request.args.get("next") or request.form.get("next") or url_for("admin_page")
    error = None
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(next_url)
        error = "Incorrect password."
    return render_template_string(LOGIN_HTML, error=error, next_url=next_url)

@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/admin")
def admin_page():
    if not admin_required():
        return redirect(url_for("admin_login"))
    return render_template_string(ADMIN_HTML)

@app.route("/admin/upload", methods=["POST"])
def admin_upload():
    if "file" not in request.files:
        return jsonify(error="no file"), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify(error="empty filename"), 400
    filename = os.path.basename(f.filename)
    f.save(os.path.join(ADMIN_UPLOAD_DIR, filename))
    return jsonify(ok=True, filename=filename)

@app.route("/admin/files")
def admin_files():
    files = []
    for name in sorted(os.listdir(ADMIN_UPLOAD_DIR)):
        path = os.path.join(ADMIN_UPLOAD_DIR, name)
        if os.path.isfile(path):
            files.append({"name": name, "size": os.path.getsize(path)})
    return jsonify(files)

@app.route("/admin/files/<path:filename>", methods=["DELETE"])
def admin_delete_file(filename):
    path = os.path.join(ADMIN_UPLOAD_DIR, os.path.basename(filename))
    if os.path.exists(path):
        os.remove(path)
    return jsonify(ok=True)

@app.route("/api/questions/<qid>", methods=["DELETE"])
def api_delete_question(qid):
    if not admin_required():
        return jsonify(error="forbidden"), 403
    global questions_data
    q = next((q for q in questions_data if q["id"] == qid), None)
    if not q:
        return jsonify(error="not found"), 404
    questions_data = [x for x in questions_data if x["id"] != qid]
    with open(QUESTIONS_JSON, "w") as f:
        json.dump(questions_data, f, indent=2)
    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
