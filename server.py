import os
import json
import uuid
import sqlite3
import datetime
from authlib.integrations.flask_client import OAuth
from flask import Flask, request, jsonify, send_from_directory, render_template_string, session, redirect, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

BASE = os.path.dirname(__file__)
UPLOAD_DIR = os.path.join(BASE, "uploads")
ADMIN_UPLOAD_DIR = os.path.join(BASE, "admin_uploads")
QIMG_DIR = os.path.join(BASE, "question_images")
QUESTIONS_JSON = os.path.join(BASE, "questions.json")
FLAGS_JSON = os.path.join(BASE, "flags.json")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(ADMIN_UPLOAD_DIR, exist_ok=True)

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "specialist2025")
ADMIN_EMAIL = "ariel.tenenbergg@gmail.com"
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
DB_PATH = os.path.join(BASE, "users.db")

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.secret_key = os.environ.get("FLASK_SECRET", "change-me-in-production-32chars!")
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024

# ---------------------------------------------------------------------------
# Database & OAuth
# ---------------------------------------------------------------------------

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                google_id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                name TEXT,
                picture TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                approved_at TEXT
            )
        """)
        conn.commit()

init_db()

oauth = OAuth(app)
google_oauth = oauth.register(
    name="google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def load_user_to_session(user_row):
    session["user_id"] = user_row["google_id"]
    session["user_email"] = user_row["email"]
    session["user_name"] = user_row["name"]
    session["user_status"] = user_row["status"]
    session["is_admin"] = (user_row["email"] == ADMIN_EMAIL)

def current_user():
    if "user_id" not in session:
        return None
    return {
        "id": session["user_id"],
        "email": session["user_email"],
        "name": session["user_name"],
        "status": session["user_status"],
        "is_admin": session.get("is_admin", False),
    }

def check_approved():
    """Return a redirect if user is not logged in or not yet approved, else None."""
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    with get_db() as conn:
        row = conn.execute("SELECT status FROM users WHERE google_id=?", (user["id"],)).fetchone()
    if not row:
        session.clear()
        return redirect(url_for("login"))
    session["user_status"] = row["status"]
    if row["status"] == "pending":
        return redirect(url_for("pending_page"))
    if row["status"] == "rejected":
        session.clear()
        return redirect(url_for("login") + "?rejected=1")
    return None

# Load questions once at startup
questions_data = []
if os.path.exists(QUESTIONS_JSON):
    with open(QUESTIONS_JSON) as f:
        questions_data = json.load(f)

flags_data = []
if os.path.exists(FLAGS_JSON):
    with open(FLAGS_JSON) as f:
        flags_data = json.load(f)

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
.main { flex:1; padding:28px 32px; }
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

/* ----- Flag controls ----- */
.flag-btn {
  font-family:inherit;
  font-size:.78rem;
  color:var(--muted);
  background:none;
  border:1px solid var(--border);
  padding:5px 12px;
  border-radius:6px;
  cursor:pointer;
  transition:all .15s;
  align-self:flex-start;
}
.flag-btn:hover { border-color:#dd6b20; color:#dd6b20; }
.flag-btn.flagged { border-color:#dd6b20; color:#dd6b20; background:#fff8f0; cursor:default; }
</style>
</head>
<body>

<div class="topbar">
  <h1>Specialist Maths Question Bank</h1>
  <div class="tabs">
    <a class="tab active" href="/">Questions</a>
    {% if is_admin %}<a class="tab" href="/admin">Admin</a>{% endif %}
    {% if is_admin %}<a class="tab" href="/admin/users">Users</a>{% endif %}
  </div>
  <span class="count">{{ user_name }}</span>
  <a class="admin-mode-btn {% if is_admin %}exit{% endif %}" href="/logout">Sign out</a>
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

    const flagControls = !IS_ADMIN ? `
      <button class="flag-btn" id="flag-btn-${q.id}" onclick="submitFlag('${q.id}', this)">⚑ Flag as misclassified</button>` : '';

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
        ${flagControls}
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

function submitFlag(id, btn) {
  fetch('/api/flag', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question_id: id })
  }).then(r => r.json()).then(data => {
    if (data.ok) {
      btn.textContent = '⚑ Flagged';
      btn.classList.add('flagged');
      btn.onclick = null;
    }
  });
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
<title>{% if flagged_mode %}Classify — Flagged{% elif unsorted_mode %}Classify — Unsorted{% else %}Classify — {{ publisher }} {{ year }}{% endif %}</title>
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
.exam-nav-btn.flagged-tab { border-color:#744210; color:#dd6b20; }
.exam-nav-btn.flagged-tab:hover { border-color:#dd6b20; background:#1a0e00; color:#dd6b20; }
.exam-nav-btn.flagged-tab.current { background:#1a0e00; border-color:#dd6b20; color:#dd6b20; }

.flag-hints { display:flex; flex-direction:column; gap:4px; padding:0 20px 14px; }
.flag-hint {
  font-size:.78rem;
  color:#dd6b20;
  background:#120900;
  border:1px solid #744210;
  border-radius:6px;
  padding:5px 10px;
}

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
  <h1>{% if flagged_mode %}Flagged Questions ({{ questions|length }}){% elif unsorted_mode %}Unsorted Questions ({{ questions|length }}){% else %}Classifying: {{ publisher }} {{ year }}{% endif %}</h1>
  <div class="progress-bar-wrap"><div class="progress-bar" id="progress-bar" style="width:0%"></div></div>
  <span class="progress-label" id="progress-label">0 / {{ questions|length }}</span>
</div>
<div class="exam-nav">
  <a class="exam-nav-btn flagged-tab {% if flagged_mode %}current{% endif %}"
     href="/classify?flagged=1">⚑ Flagged ({{ flagged_count }})</a>
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
  {% if flags_by_qid.get(q.id) %}
  <div class="flag-hints">
    <span class="flag-hint">⚑ Flagged as misclassified ({{ flags_by_qid[q.id]|length }}×)</span>
  </div>
  {% endif %}
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
    r = check_approved()
    if r: return r
    user = current_user()
    return render_template_string(BROWSE_HTML, is_admin=admin_required(), user_name=user["name"] if user else "")

@app.route("/api/questions")
def api_questions():
    if check_approved():
        return jsonify(error="unauthorized"), 401
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
    flagged_mode = request.args.get("flagged") == "1"
    publisher = request.args.get("publisher", "Heffernan")
    year = int(request.args.get("year", 2025))

    if flagged_mode:
        flagged_ids = {f["question_id"] for f in flags_data}
        questions = [q for q in questions_data if q["id"] in flagged_ids]
    elif unsorted_mode:
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
    flagged_count = len({f["question_id"] for f in flags_data})

    flags_by_qid = {}
    for f in flags_data:
        flags_by_qid.setdefault(f["question_id"], []).append(f)

    return render_template_string(CLASSIFY_HTML, questions=questions, publisher=publisher, year=year,
                                  exam_sets=exam_sets, unsorted_mode=unsorted_mode, unsorted_count=unsorted_count,
                                  flagged_mode=flagged_mode, flagged_count=flagged_count, flags_by_qid=flags_by_qid)

@app.route("/qimg/<path:filename>")
def serve_qimg(filename):
    r = check_approved()
    if r: return r
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
<title>Sign In — Specialist Maths Question Bank</title>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Poppins',system-ui,sans-serif; background:#0f1117; min-height:100vh; display:flex; align-items:center; justify-content:center; }
.card { background:#1a1d27; border:1px solid #2d3148; border-radius:16px; padding:40px 36px; width:100%; max-width:380px; text-align:center; }
h1 { color:#e2e8f0; font-size:1.2rem; font-weight:600; margin-bottom:8px; }
p { color:#718096; font-size:.85rem; margin-bottom:32px; line-height:1.6; }
.google-btn {
  display:flex; align-items:center; justify-content:center; gap:12px;
  background:#fff; color:#3c4043; border:none; border-radius:8px;
  padding:12px 24px; width:100%; font-family:inherit; font-size:.9rem; font-weight:500;
  cursor:pointer; text-decoration:none; transition:box-shadow .15s;
  box-shadow:0 1px 3px rgba(0,0,0,.3);
}
.google-btn:hover { box-shadow:0 2px 10px rgba(0,0,0,.45); }
.google-btn svg { width:20px; height:20px; flex-shrink:0; }
.msg { font-size:.82rem; margin-bottom:20px; padding:10px 14px; border-radius:8px; }
.msg.error { color:#fc8181; background:rgba(252,129,129,.1); border:1px solid rgba(252,129,129,.2); }
.msg.info { color:#90cdf4; background:rgba(144,205,244,.1); border:1px solid rgba(144,205,244,.2); }
</style>
</head>
<body>
<div class="card">
  <h1>Specialist Maths Question Bank</h1>
  <p>Sign in with your Google account.</p>
  {% if rejected %}<div class="msg error">Your access request was not approved. Contact Ariel.</div>{% endif %}
  {% if pending %}<div class="msg info">Your account is awaiting approval. Sign in again to check your status.</div>{% endif %}
  <a class="google-btn" href="/oauth/google">
    <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
      <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
      <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z" fill="#FBBC05"/>
      <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
    </svg>
    Sign in with Google
  </a>
</div>
</body>
</html>"""

PENDING_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Awaiting Approval — Specialist Maths Question Bank</title>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Poppins',system-ui,sans-serif; background:#0f1117; min-height:100vh; display:flex; align-items:center; justify-content:center; }
.card { background:#1a1d27; border:1px solid #2d3148; border-radius:16px; padding:48px 36px; width:100%; max-width:420px; text-align:center; }
.icon { font-size:2.8rem; margin-bottom:20px; }
h1 { color:#e2e8f0; font-size:1.15rem; font-weight:600; margin-bottom:10px; }
p { color:#718096; font-size:.875rem; line-height:1.7; margin-bottom:28px; }
.email { color:#a0aec0; font-weight:500; }
a { color:#718096; font-size:.82rem; text-decoration:underline; }
a:hover { color:#a0aec0; }
</style>
</head>
<body>
<div class="card">
  <div class="icon">&#x23F3;</div>
  <h1>Awaiting Approval</h1>
  <p>You're signed in as <span class="email">{{ user.email }}</span>.<br>
  Your account is pending approval from the administrator.<br>
  You'll receive access once Ariel approves your request.</p>
  <a href="/logout">Sign out</a>
</div>
</body>
</html>"""

USERS_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Users — Specialist Maths Question Bank</title>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root {
  --bg:#f5f7fa; --surface:#fff; --border:#e2e8f0; --text:#1a202c;
  --muted:#718096; --primary:#196061; --primary-dark:#042f3a;
  --accent-green:#38a169; --red:#e53e3e;
  --shadow-sm:0 1px 3px rgba(0,0,0,.06); --radius:12px;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Poppins',system-ui,sans-serif; background:var(--bg); color:var(--text); min-height:100vh; }
.topbar { background:var(--primary-dark); padding:0 32px; display:flex; align-items:center; gap:16px; position:sticky; top:0; z-index:100; height:60px; box-shadow:0 2px 8px rgba(0,0,0,.15); }
.topbar h1 { font-size:1.1rem; font-weight:700; color:#fff; white-space:nowrap; }
.tabs { display:flex; gap:4px; margin-left:24px; }
.tab { background:none; border:none; color:rgba(255,255,255,.6); font-family:inherit; font-size:.875rem; font-weight:500; padding:8px 18px; border-radius:8px; cursor:pointer; text-decoration:none; transition:all .15s; }
.tab:hover { color:#fff; background:rgba(255,255,255,.1); }
.tab.active { color:#fff; background:rgba(255,255,255,.15); }
.spacer { flex:1; }
.signout { color:rgba(255,255,255,.6); font-size:.8rem; text-decoration:none; padding:6px 14px; border:1px solid rgba(255,255,255,.2); border-radius:8px; white-space:nowrap; }
.signout:hover { color:#fff; background:rgba(255,255,255,.1); }
.container { max-width:820px; margin:0 auto; padding:40px 24px; }
.section { margin-bottom:44px; }
.section h2 { font-size:1.05rem; font-weight:600; margin-bottom:14px; color:var(--primary-dark); display:flex; align-items:center; gap:8px; }
.badge { font-size:.7rem; font-weight:600; padding:2px 9px; border-radius:99px; color:#fff; background:var(--primary); }
.badge.green { background:var(--accent-green); }
.badge.red { background:var(--red); }
.user-card { background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:14px 18px; display:flex; align-items:center; gap:14px; box-shadow:var(--shadow-sm); margin-bottom:8px; }
.user-card img { width:38px; height:38px; border-radius:50%; object-fit:cover; background:var(--border); flex-shrink:0; }
.info { flex:1; min-width:0; }
.uname { font-size:.9rem; font-weight:500; }
.uemail { font-size:.78rem; color:var(--muted); margin-top:2px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.udate { font-size:.75rem; color:var(--muted); white-space:nowrap; flex-shrink:0; }
.actions { display:flex; gap:8px; flex-shrink:0; }
.btn { padding:7px 16px; border-radius:8px; font-size:.8rem; font-weight:500; cursor:pointer; border:none; font-family:inherit; transition:all .15s; }
.btn-approve { background:var(--primary); color:#fff; }
.btn-approve:hover { background:#1a7a7b; }
.btn-reject { background:none; border:1px solid var(--border); color:var(--muted); }
.btn-reject:hover { border-color:var(--red); color:var(--red); }
.btn-revoke { background:none; border:1px solid var(--border); color:var(--muted); font-size:.75rem; padding:5px 12px; }
.btn-revoke:hover { border-color:var(--red); color:var(--red); }
.empty { color:var(--muted); font-size:.85rem; padding:20px; text-align:center; background:var(--surface); border:1px solid var(--border); border-radius:10px; }
</style>
</head>
<body>
<div class="topbar">
  <h1>Specialist Maths Question Bank</h1>
  <div class="tabs">
    <a class="tab" href="/">Questions</a>
    <a class="tab" href="/admin">Admin</a>
    <a class="tab active" href="/admin/users">Users</a>
  </div>
  <div class="spacer"></div>
  <a class="signout" href="/logout">Sign out</a>
</div>
<div class="container">
  <div class="section">
    <h2>Pending Approval <span class="badge">{{ pending|length }}</span></h2>
    {% if pending %}
      {% for u in pending %}
      <div class="user-card" id="card-{{ u['google_id'] }}">
        <img src="{{ u['picture'] or '' }}" alt="" onerror="this.style.visibility='hidden'">
        <div class="info">
          <div class="uname">{{ u['name'] }}</div>
          <div class="uemail">{{ u['email'] }}</div>
        </div>
        <div class="udate">{{ u['created_at'][:10] }}</div>
        <div class="actions">
          <button class="btn btn-approve" onclick="act('{{ u['google_id'] }}','approve')">Approve</button>
          <button class="btn btn-reject" onclick="act('{{ u['google_id'] }}','reject')">Reject</button>
        </div>
      </div>
      {% endfor %}
    {% else %}
      <div class="empty">No pending requests</div>
    {% endif %}
  </div>
  <div class="section">
    <h2>Approved Students <span class="badge green">{{ approved|length }}</span></h2>
    {% if approved %}
      {% for u in approved %}
      <div class="user-card" id="card-{{ u['google_id'] }}">
        <img src="{{ u['picture'] or '' }}" alt="" onerror="this.style.visibility='hidden'">
        <div class="info">
          <div class="uname">{{ u['name'] }}</div>
          <div class="uemail">{{ u['email'] }}</div>
        </div>
        <div class="udate">{{ u['approved_at'][:10] if u['approved_at'] else '' }}</div>
        <div class="actions">
          <button class="btn btn-revoke" onclick="act('{{ u['google_id'] }}','reject')">Revoke</button>
        </div>
      </div>
      {% endfor %}
    {% else %}
      <div class="empty">No approved students yet</div>
    {% endif %}
  </div>
  {% if rejected %}
  <div class="section">
    <h2>Rejected <span class="badge red">{{ rejected|length }}</span></h2>
    {% for u in rejected %}
    <div class="user-card" id="card-{{ u['google_id'] }}">
      <img src="{{ u['picture'] or '' }}" alt="" onerror="this.style.visibility='hidden'">
      <div class="info">
        <div class="uname">{{ u['name'] }}</div>
        <div class="uemail">{{ u['email'] }}</div>
      </div>
      <div class="actions">
        <button class="btn btn-approve" onclick="act('{{ u['google_id'] }}','approve')">Re-approve</button>
        <button class="btn btn-reject" onclick="act('{{ u['google_id'] }}','delete')">Remove</button>
      </div>
    </div>
    {% endfor %}
  </div>
  {% endif %}
</div>
<script>
function act(id, action) {
  fetch('/admin/users/' + id + '/' + action, {method:'POST'})
    .then(r => r.json()).then(d => { if (d.ok) location.reload(); });
}
</script>
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

/* ----- Flagged questions ----- */
.flags-count-badge {
  display:inline-block;
  background:#dd6b20;
  color:#fff;
  font-size:.72rem;
  font-weight:700;
  padding:2px 9px;
  border-radius:99px;
  margin-left:8px;
  vertical-align:middle;
}
.flags-count-badge.zero { background:var(--border); color:var(--muted); }
.flag-item {
  background:var(--surface);
  border:1px solid #fbd38d;
  border-radius:var(--radius);
  padding:16px 18px;
  margin-bottom:12px;
  box-shadow:var(--shadow-sm);
}
.flag-item-meta {
  display:flex;
  flex-wrap:wrap;
  align-items:center;
  gap:10px;
  margin-bottom:8px;
}
.flag-qid { font-weight:600; font-size:.9rem; color:var(--primary-dark); }
.flag-tag {
  font-size:.72rem;
  font-weight:500;
  padding:3px 10px;
  border-radius:99px;
  background:#e6f2f2;
  color:var(--primary);
}
.flag-time { font-size:.75rem; color:var(--muted); margin-left:auto; }
.flag-img {
  width:100%;
  max-width:600px;
  border-radius:8px;
  border:1px solid var(--border);
  display:block;
  margin-bottom:12px;
}
.flag-actions { display:flex; gap:8px; }
.flag-classify-link {
  font-family:inherit;
  font-size:.82rem;
  font-weight:600;
  padding:7px 16px;
  border-radius:8px;
  background:var(--primary-light);
  color:var(--primary);
  border:1px solid rgba(25,96,97,.2);
  text-decoration:none;
  transition:all .15s;
}
.flag-classify-link:hover { background:var(--primary); color:#fff; }
.flag-dismiss-btn {
  font-family:inherit;
  font-size:.82rem;
  padding:7px 16px;
  border-radius:8px;
  border:1px solid var(--border);
  background:none;
  color:var(--muted);
  cursor:pointer;
  transition:all .15s;
}
.flag-dismiss-btn:hover { border-color:var(--red); color:var(--red); }
</style>
</head>
<body>

<div class="topbar">
  <h1>Specialist Maths Question Bank</h1>
  <div class="tabs">
    <a class="tab" href="/">Questions</a>
    <a class="tab active" href="/admin">Admin</a>
    <a class="tab" href="/admin/users">Users</a>
  </div>
</div>

<div class="container">
  <div class="section">
    <h2>Flagged Questions <span class="flags-count-badge zero" id="flags-badge">0</span></h2>
    <p class="desc">Questions students have flagged as potentially misclassified. Review the image, then reclassify or dismiss the flag.</p>
    <div id="flags-list"><div class="empty">Loading…</div></div>
  </div>

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

// --- Flagged questions ---
function loadFlags() {
  fetch('/api/admin/flags').then(r => r.json()).then(flags => {
    const el = document.getElementById('flags-list');
    const badge = document.getElementById('flags-badge');
    badge.textContent = flags.length;
    badge.className = 'flags-count-badge' + (flags.length ? '' : ' zero');
    if (!flags.length) {
      el.innerHTML = '<div class="empty">No flagged questions</div>';
      return;
    }
    el.innerHTML = flags.map(f => {
      const imgHtml = f.question_image
        ? `<img class="flag-img" src="${f.question_image}" loading="lazy"/>` : '';
      const date = new Date(f.timestamp + 'Z').toLocaleDateString('en-AU', { day:'numeric', month:'short', year:'numeric' });
      return `<div class="flag-item" id="flag-item-${f.id}">
        <div class="flag-item-meta">
          <span class="flag-qid">${f.publisher} ${f.year} — Q${f.question_number}</span>
          <span class="flag-tag">${f.current_aos_name}</span>
          <span class="flag-time">${date}</span>
        </div>
        ${imgHtml}
        <div class="flag-actions">
          <a class="flag-classify-link" href="/classify?publisher=${encodeURIComponent(f.publisher)}&year=${f.year}">Go to Classify</a>
          <button class="flag-dismiss-btn" onclick="dismissFlag('${f.id}')">Dismiss</button>
        </div>
      </div>`;
    }).join('');
  });
}

function dismissFlag(id) {
  fetch('/api/admin/flags/' + id, { method: 'DELETE' })
    .then(r => r.json()).then(data => {
      if (data.ok) loadFlags();
    });
}

loadFlags();
</script>
</body>
</html>"""

def admin_required():
    return session.get("is_admin") is True

@app.route("/login")
def login():
    user = current_user()
    if user and user["status"] == "approved":
        return redirect(url_for("index"))
    rejected = request.args.get("rejected") == "1"
    pending = request.args.get("pending") == "1"
    return render_template_string(LOGIN_HTML, rejected=rejected, pending=pending)

@app.route("/oauth/google")
def oauth_google():
    redirect_uri = "http://ariel.tenenberg.com/oauth/google/callback"
    return google_oauth.authorize_redirect(redirect_uri)

@app.route("/oauth/google/callback")
def oauth_google_callback():
    try:
        token = google_oauth.authorize_access_token()
    except Exception:
        return redirect(url_for("login"))
    user_info = token.get("userinfo")
    if not user_info:
        return redirect(url_for("login"))
    google_id = user_info["sub"]
    email = user_info["email"]
    name = user_info.get("name", email)
    picture = user_info.get("picture", "")
    now = datetime.datetime.utcnow().isoformat()
    status = "approved" if email == ADMIN_EMAIL else "pending"
    with get_db() as conn:
        existing = conn.execute("SELECT * FROM users WHERE google_id=?", (google_id,)).fetchone()
        if existing:
            conn.execute("UPDATE users SET name=?, picture=? WHERE google_id=?", (name, picture, google_id))
            if email == ADMIN_EMAIL and existing["status"] != "approved":
                conn.execute("UPDATE users SET status='approved', approved_at=? WHERE google_id=?", (now, google_id))
        else:
            approved_at = now if status == "approved" else None
            conn.execute(
                "INSERT INTO users (google_id, email, name, picture, status, created_at, approved_at) VALUES (?,?,?,?,?,?,?)",
                (google_id, email, name, picture, status, now, approved_at)
            )
        conn.commit()
        user_row = conn.execute("SELECT * FROM users WHERE google_id=?", (google_id,)).fetchone()
    load_user_to_session(user_row)
    if user_row["status"] == "pending":
        return redirect(url_for("pending_page"))
    return redirect(url_for("index"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/pending")
def pending_page():
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    if user["status"] == "approved":
        return redirect(url_for("index"))
    return render_template_string(PENDING_HTML, user=user)

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    return redirect(url_for("login"))

@app.route("/admin/logout")
def admin_logout():
    return redirect(url_for("logout"))

@app.route("/admin")
def admin_page():
    if not admin_required():
        return redirect(url_for("login"))
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

@app.route("/api/flag", methods=["POST"])
def api_flag():
    data = request.get_json()
    qid = data.get("question_id")
    q = next((q for q in questions_data if q["id"] == qid), None)
    if not q:
        return jsonify(error="question not found"), 404
    flag = {
        "id": str(uuid.uuid4()),
        "question_id": qid,
        "publisher": q["publisher"],
        "year": q["year"],
        "question_number": q["question_number"],
        "current_aos": q["aos"],
        "current_aos_name": q["aos_name"],
        "question_image": q.get("question_image"),
        "suggested_aos": data.get("suggested_aos"),
        "suggested_aos_name": data.get("suggested_aos_name"),
        "note": data.get("note", "").strip(),
        "timestamp": datetime.datetime.utcnow().isoformat()
    }
    flags_data.append(flag)
    with open(FLAGS_JSON, "w") as f:
        json.dump(flags_data, f, indent=2)
    return jsonify(ok=True)

@app.route("/api/admin/flags")
def api_admin_flags():
    if not admin_required():
        return jsonify(error="forbidden"), 403
    return jsonify(flags_data)

@app.route("/api/admin/flags/<flag_id>", methods=["DELETE"])
def api_admin_delete_flag(flag_id):
    if not admin_required():
        return jsonify(error="forbidden"), 403
    global flags_data
    flags_data = [f for f in flags_data if f["id"] != flag_id]
    with open(FLAGS_JSON, "w") as f:
        json.dump(flags_data, f, indent=2)
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


@app.route("/admin/users")
def admin_users():
    if not admin_required():
        return redirect(url_for("login"))
    with get_db() as conn:
        pending = [dict(r) for r in conn.execute("SELECT * FROM users WHERE status='pending' ORDER BY created_at").fetchall()]
        approved = [dict(r) for r in conn.execute("SELECT * FROM users WHERE status='approved' AND email!=? ORDER BY approved_at DESC", (ADMIN_EMAIL,)).fetchall()]
        rejected = [dict(r) for r in conn.execute("SELECT * FROM users WHERE status='rejected' ORDER BY created_at DESC").fetchall()]
    return render_template_string(USERS_HTML, pending=pending, approved=approved, rejected=rejected)

@app.route("/admin/users/<google_id>/approve", methods=["POST"])
def admin_approve_user(google_id):
    if not admin_required():
        return jsonify(error="forbidden"), 403
    now = datetime.datetime.utcnow().isoformat()
    with get_db() as conn:
        conn.execute("UPDATE users SET status='approved', approved_at=? WHERE google_id=?", (now, google_id))
        conn.commit()
    return jsonify(ok=True)

@app.route("/admin/users/<google_id>/reject", methods=["POST"])
def admin_reject_user(google_id):
    if not admin_required():
        return jsonify(error="forbidden"), 403
    with get_db() as conn:
        conn.execute("UPDATE users SET status='rejected' WHERE google_id=?", (google_id,))
        conn.commit()
    return jsonify(ok=True)

@app.route("/admin/users/<google_id>/delete", methods=["POST"])
def admin_delete_user(google_id):
    if not admin_required():
        return jsonify(error="forbidden"), 403
    with get_db() as conn:
        conn.execute("DELETE FROM users WHERE google_id=?", (google_id,))
        conn.commit()
    return jsonify(ok=True)


if __name__ == "__main__":
    import sys
    debug = "--debug" in sys.argv
    app.run(host="0.0.0.0", port=8080, debug=debug)
