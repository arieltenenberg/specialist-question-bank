import os
import json
import uuid
import sqlite3
import datetime
import threading
import subprocess
import zipfile
from authlib.integrations.flask_client import OAuth
from flask import Flask, request, jsonify, send_from_directory, render_template_string, session, redirect, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

DEV_MODE = os.environ.get("DEV_MODE") == "1"

BASE = os.path.dirname(__file__)
UPLOAD_DIR = os.path.join(BASE, "uploads")
ADMIN_UPLOAD_DIR = os.path.join(BASE, "admin_uploads")
QIMG_DIR = os.path.join(BASE, "question_images")
QUESTIONS_JSON = os.path.join(BASE, "specialist_questions.json")
METHODS_QUESTIONS_JSON = os.path.join(BASE, "methods_questions.json")
FLAGS_JSON = os.path.join(BASE, "flags.json")
SETTINGS_JSON = os.path.join(BASE, "settings.json")
OVERRIDES_JSON = os.path.join(BASE, "overrides.json")

def _read_flags():
    if not os.path.exists(FLAGS_JSON):
        return []
    with open(FLAGS_JSON) as f:
        return json.load(f)

def _write_flags(flags):
    with open(FLAGS_JSON, "w") as f:
        json.dump(flags, f, indent=2)

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(ADMIN_UPLOAD_DIR, exist_ok=True)
os.makedirs(os.path.join(UPLOAD_DIR, "specialist"), exist_ok=True)
os.makedirs(os.path.join(UPLOAD_DIR, "methods"), exist_ok=True)

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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS difficult_questions (
                user_id     TEXT NOT NULL,
                question_id TEXT NOT NULL,
                subject     TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                PRIMARY KEY (user_id, question_id, subject)
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

def get_current_user_id():
    if DEV_MODE:
        return session.get("user_id", "dev_user")
    return session.get("user_id")

def check_approved():
    """Return a redirect if user is not logged in or not yet approved, else None."""
    if DEV_MODE:
        return None
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

def load_settings():
    if os.path.exists(SETTINGS_JSON):
        with open(SETTINGS_JSON) as f:
            data = json.load(f)
        # Migrate old flat format to per-subject format
        if "hidden_publishers" in data and not isinstance(data.get("specialist"), dict):
            data = {"specialist": {"hidden_publishers": data["hidden_publishers"]}, "methods": {"hidden_publishers": []}}
            with open(SETTINGS_JSON, "w") as f:
                json.dump(data, f, indent=2)
        return data
    return {"specialist": {"hidden_publishers": []}, "methods": {"hidden_publishers": []}}

def save_settings(settings):
    with open(SETTINGS_JSON, "w") as f:
        json.dump(settings, f, indent=2)

def get_hidden_publishers(subject="specialist"):
    return set(load_settings().get(subject, {}).get("hidden_publishers", []))

def load_overrides():
    if not os.path.exists(OVERRIDES_JSON):
        return {"specialist": {}, "methods": {}}
    with open(OVERRIDES_JSON) as f:
        return json.load(f)

def save_overrides(overrides):
    with open(OVERRIDES_JSON, "w") as f:
        json.dump(overrides, f, indent=2)

def apply_overrides(questions, subject):
    overrides = load_overrides().get(subject, {})
    if not overrides:
        return questions
    return [{**q, **overrides[q["id"]]} if q["id"] in overrides else q for q in questions]

# Load questions once at startup
questions_data = []
if os.path.exists(QUESTIONS_JSON):
    with open(QUESTIONS_JSON) as f:
        questions_data = json.load(f)

methods_data = []
if os.path.exists(METHODS_QUESTIONS_JSON):
    with open(METHODS_QUESTIONS_JSON) as f:
        methods_data = json.load(f)


# AOS maps per subject
SPECIALIST_AOS = {0: "Unsorted", 1: "Logic and Proof", 2: "Functions, Relations and Graphs", 3: "Complex Numbers", 4: "Calculus", 5: "Vectors, Lines and Planes", 6: "Probability and Statistics", 7: "Pseudocode", 8: "Mechanics", 9: "Hidden"}
METHODS_AOS = {
    0: "Unsorted",
    1: "Algebra and Functions",
    2: "Differentiation",
    3: "Integration",
    4: "Discrete Probability",
    5: "Continuous Probability",
    6: "Core Content",                # Exam 2 only
    7: "Probability and Statistics",  # Exam 2 only
    8: "Pseudocode",                  # Exam 1 only
    9: "Hidden",
}

SUBJECT_CONFIG = {
    "specialist": {
        "name": "Specialist Mathematics",
        "data": lambda: questions_data,
        "file": QUESTIONS_JSON,
        "aos_map": SPECIALIST_AOS,
    },
    "methods": {
        "name": "Mathematical Methods",
        "data": lambda: methods_data,
        "file": METHODS_QUESTIONS_JSON,
        "aos_map": METHODS_AOS,
    },
}

def get_subject_config(subject):
    return SUBJECT_CONFIG.get(subject, SUBJECT_CONFIG["specialist"])

# ---------------------------------------------------------------------------
# Browse page HTML — Light theme inspired by maica.com.au
# ---------------------------------------------------------------------------

BROWSE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>{{ subject_name }} Question Bank</title>
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
  --primary: {{ css_primary }};
  --primary-dark: {{ css_primary_dark }};
  --primary-light: {{ css_primary_light }};
  --primary-hover: {{ css_primary_hover }};
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
.sidebar-backdrop {
  display:none;
  position:fixed;
  inset:60px 0 0 0;
  background:rgba(0,0,0,.35);
  z-index:98;
}
.sidebar-backdrop.visible { display:block; }
@media (max-width: 768px) {
  .topbar { padding:0 12px; gap:8px; }
  .topbar h1 { font-size:.9rem; min-width:0; overflow:hidden; text-overflow:ellipsis; }
  .topbar .tabs { margin-left:8px; gap:2px; }
  .topbar .tab { padding:6px 10px; font-size:.78rem; }
  .topbar .count { display:none; }
  .topbar .admin-mode-btn { margin-left:auto; font-size:.75rem; padding:5px 10px; }
  .layout { flex-direction:column; }
  .main { padding:16px; }
  .sidebar { display:none; }
  .show-sidebar-btn { display:block; }
  .sidebar.mobile-open {
    display:block;
    position:fixed;
    top:60px;
    left:0;
    width:280px;
    max-width:calc(100vw - 40px);
    z-index:99;
    height:calc(100vh - 60px);
    box-shadow:4px 0 24px rgba(0,0,0,.2);
  }
  .qcard-header { padding:12px 14px; gap:8px; }
  .qcard-header .marks { font-size:.75rem; }
  .qcard-body { padding:0 12px 16px; }
  .qimages { flex-direction:column; }
  .qimg-wrap { min-width:0; width:100%; }
  .card-actions { flex-wrap:wrap; }
  .pagination { flex-wrap:wrap; }
  .page-btn { padding:9px 12px; }
  .show-sol-btn { padding:10px 20px; }
  .save-btn { padding:10px 20px; }
}
@media (max-width: 480px) {
  .topbar h1 { display:none; }
  .topbar .tabs { margin-left:0; }
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
.admin-hide-btn {
  font-size:.8rem;
  background:none;
  border:1px solid #c53030;
  border-radius:6px;
  padding:4px 10px;
  cursor:pointer;
  color:#c53030;
  transition:background .15s;
}
.admin-hide-btn:hover { background:#fff0f0; }
.hidden-badge {
  font-size:.75rem;
  color:#9ca3af;
  font-weight:600;
  padding:2px 6px;
  background:#f3f4f6;
  border-radius:4px;
}

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

/* ----- Save controls ----- */
.save-btn {
  font-family:inherit;
  background:var(--primary-light);
  color:var(--primary);
  border:1px solid rgba(25,96,97,.2);
  font-size:.85rem;
  font-weight:500;
  padding:8px 20px;
  border-radius:8px;
  cursor:pointer;
  transition:all .15s;
  align-self:flex-start;
  margin-top:4px;
}
.save-btn:hover { background:var(--primary); color:#fff; }
.save-btn.saved { background:var(--primary); color:#fff; }
.card-actions {
  display:flex;
  align-items:flex-start;
  justify-content:space-between;
  gap:8px;
  margin-top:4px;
}
.card-actions-left { display:flex; gap:8px; align-items:flex-start; }

/* ----- Admin FAB (mobile only) ----- */
.admin-fab {
  display:none;
  position:fixed;
  bottom:24px;
  right:20px;
  z-index:200;
  background:var(--primary-dark);
  color:#fff;
  font-family:inherit;
  font-size:.85rem;
  font-weight:600;
  padding:12px 20px;
  border-radius:99px;
  text-decoration:none;
  box-shadow:0 4px 16px rgba(0,0,0,.25);
  transition:background .15s;
}
.admin-fab:hover { background:var(--primary); color:#fff; }
@media (max-width: 768px) {
  .admin-fab { display:block; }
}
</style>
</head>
<body>

<div class="topbar">
  <h1>{{ subject_name }} Question Bank</h1>
  <div class="tabs">
    <a class="tab" href="/">← Subjects</a>
    <a class="tab active" id="tab-questions" href="/{{ subject }}">Questions</a>
    <button class="tab" id="tab-saved" onclick="toggleSavedFilter()">Saved (<span id="saved-count">0</span>)</button>
    {% if is_admin %}<a class="tab" href="/admin?subject={{ subject }}">Admin</a>{% endif %}
  </div>
  <span class="count">{{ user_name }}</span>
  <a class="admin-mode-btn {% if is_admin %}exit{% endif %}" href="/logout">Sign out</a>
</div>

{% if is_admin %}<a class="admin-fab" href="/admin?subject={{ subject }}">⚙ Admin</a>{% endif %}

<div class="layout">
  <div class="sidebar" id="sidebar">
    {% if is_admin %}
    <a class="sort-unsorted-btn" id="sort-unsorted-btn" href="/classify?subject={{ subject }}&unsorted=1">Sort Unsorted (<span id="unsorted-count">…</span>)</a>
    {% endif %}
    {% if is_methods %}
    <h3>Short Answer and Multiple Choice</h3>
    <div class="filter-group" id="fg-tag"></div>
    <h3>Extended Response</h3>
    <div class="filter-group" id="fg-extended"></div>
    {% else %}
    <h3>Area of Study</h3>
    <div class="filter-group" id="fg-aos"></div>
    {% endif %}
    <h3>Year</h3>
    <div class="filter-group" id="fg-year"></div>
    <h3>Publisher</h3>
    <div class="filter-group" id="fg-pub"></div>
    <h3>Exam Type</h3>
    <div class="filter-group" id="fg-exam"></div>
    <h3>Section</h3>
    <div class="filter-group" id="fg-section"></div>
  </div>

  <div class="sidebar-backdrop" id="sidebar-backdrop" onclick="toggleSidebar()"></div>
  <div class="main">
    <div class="toolbar">
      <button class="show-sidebar-btn" onclick="toggleSidebar()">☰ Filters</button>
      <div class="active-filters" id="active-filters"></div>
      <button class="clear-btn" id="clear-btn" style="display:none" onclick="clearAll()">Clear all</button>
    </div>
    <div class="qgrid" id="qgrid"></div>
    <div class="pagination" id="pagination"></div>
  </div>
</div>

<script>
const IS_ADMIN = {{ is_admin|tojson }};
const IS_METHODS = {{ is_methods|tojson }};
const PER_PAGE = 20;

function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  const backdrop = document.getElementById('sidebar-backdrop');
  const open = sidebar.classList.toggle('mobile-open');
  backdrop.classList.toggle('visible', open);
}
let allQ = [];
let filtered = [];
let page = 0;
let filters = { aos: null, tag: null, extended: null, year: null, publisher: null, exam_type: null, section: null };
let savedIds = new Set();
let savedOnly = false;

const sectionLabels = { short_answer: 'Short Answer', multiple_choice: 'Multiple Choice', extended_response: 'Extended Response' };

// Methods tag colours: all topic tags same blue
const METHODS_TAG_STYLES = {
  1: { bg:'#bfdbfe', color:'#1e3a5f' },
  2: { bg:'#bfdbfe', color:'#1e3a5f' },
  3: { bg:'#bfdbfe', color:'#1e3a5f' },
  4: { bg:'#bfdbfe', color:'#1e3a5f' },
  5: { bg:'#bfdbfe', color:'#1e3a5f' },
  6: { bg:'#e5e7eb', color:'#374151' },
  7: { bg:'#e5e7eb', color:'#374151' },
  8: { bg:'#ede9fe', color:'#5b21b6' },
  9: { bg:'#f3f4f6', color:'#9ca3af' },
};

fetch('/api/questions?subject={{ subject }}').then(r => r.json()).then(data => {
  allQ = IS_ADMIN ? data : data.filter(q => q.aos !== 0);
  if (IS_ADMIN) {
    const el = document.getElementById('unsorted-count');
    if (el) el.textContent = data.filter(q => q.aos === 0).length;
  }
  buildFilters();
  applyFilters();
  loadSavedIds();
});

function buildFilters() {
  const counts = (key, labelFn) => {
    const m = {};
    allQ.forEach(q => { const v = labelFn ? labelFn(q) : q[key]; m[v] = (m[v]||0)+1; });
    return m;
  };

  if (IS_METHODS) {
    // Count by each tag (exam 1 only: AOS 1-5)
    const tagCounts = {};
    allQ.filter(q => q.section !== 'extended_response').forEach(q => {
      (q.tags || [q.aos]).forEach(t => {
        const name = (q.tag_names || [q.aos_name])[q.tags ? q.tags.indexOf(t) : 0] || q.aos_name;
        tagCounts[name] = (tagCounts[name] || 0) + 1;
      });
    });
    // Count by extended category (exam 2 only: AOS 6-7)
    const extCounts = {};
    allQ.filter(q => q.section === 'extended_response').forEach(q => {
      extCounts[q.aos_name] = (extCounts[q.aos_name] || 0) + 1;
    });
    buildGroup('fg-tag', tagCounts, 'tag');
    buildGroup('fg-extended', extCounts, 'extended');
  } else {
    buildGroup('fg-aos', counts('aos_name'), 'aos');
  }

  buildGroup('fg-year', counts('year'), 'year');
  buildGroup('fg-pub', counts('publisher'), 'publisher');
  buildGroup('fg-exam', { 'Exam 1': allQ.filter(q=>q.exam_type===1).length, 'Exam 2': allQ.filter(q=>q.exam_type===2).length }, 'exam_type');
  buildGroup('fg-section', counts('section', q => sectionLabels[q.section]||q.section), 'section');
}

function buildGroup(elId, countsObj, filterKey) {
  const el = document.getElementById(elId);
  if (!el) return;
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
  filters = { aos: null, tag: null, extended: null, year: null, publisher: null, exam_type: null, section: null };
  document.querySelectorAll('.filter-btn.active').forEach(b => b.classList.remove('active'));
  savedOnly = false;
  document.getElementById('tab-saved').classList.remove('active');
  document.getElementById('tab-questions').classList.add('active');
  page = 0;
  applyFilters();
}

function applyFilters() {
  filtered = allQ.filter(q => {
    if (IS_METHODS) {
      // Tag filter applies to non-extended questions
      if (filters.tag) {
        if (q.section === 'extended_response') return false;
        const names = q.tag_names || [q.aos_name];
        if (!names.includes(filters.tag)) return false;
      }
      // Extended filter applies to extended response questions only
      if (filters.extended) {
        if (q.section !== 'extended_response') return false;
        if (q.aos_name !== filters.extended) return false;
      }
    } else {
      if (filters.aos && q.aos_name !== filters.aos) return false;
    }
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
    if (savedOnly && !savedIds.has(q.id)) return false;
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
  const groupMap = { aos:'fg-aos', tag:'fg-tag', extended:'fg-extended', year:'fg-year', publisher:'fg-pub', exam_type:'fg-exam', section:'fg-section' };
  document.querySelectorAll(`#${groupMap[key]} .filter-btn`).forEach(b => b.classList.remove('active'));
  page = 0;
  applyFilters();
}

function renderMethodsTagPills(q) {
  if (q.section === 'extended_response') {
    const s = METHODS_TAG_STYLES[q.aos] || METHODS_TAG_STYLES[6];
    return `<span class="qtag" style="background:${s.bg};color:${s.color}">${q.aos_name}</span>`;
  }
  const tags = q.tags || [q.aos];
  const names = q.tag_names || [q.aos_name];
  return tags.map((t, i) => {
    const s = METHODS_TAG_STYLES[t] || { bg:'#e5e7eb', color:'#374151' };
    return `<span class="qtag" style="background:${s.bg};color:${s.color}">${names[i] || t}</span>`;
  }).join('');
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
    const aosPills = IS_METHODS
      ? renderMethodsTagPills(q)
      : `<span class="qtag aos">${q.aos_name}</span>`;
    const tagHtml = aosPills + `<span class="qtag pub">${q.publisher} ${q.year}</span>`;
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
          {% for num, name in aos_map.items() %}{% if num != 0 and num != 9 %}<option value="{{ num }}|{{ name }}">{{ num }} — {{ name }}</option>{% endif %}{% endfor %}
          <option value="0|Unsorted">Unsorted</option>
        </select>
        <button class="admin-hide-btn" onclick="adminHide('${q.id}', ${q.aos === 9 ? 0 : 9}, this)">${q.aos === 9 ? 'Unhide' : 'Hide'}</button>
        ${q.aos === 9 ? '<span class="hidden-badge">HIDDEN</span>' : ''}
      </div>` : '';

    const cardActions = !IS_ADMIN ? `
      <div class="card-actions">
        <div class="card-actions-left">
          ${solBtn}
          <button class="save-btn" id="save-btn-${q.id}" onclick="toggleSaved('${q.id}', this)">Save</button>
        </div>
        <button class="flag-btn" id="flag-btn-${q.id}" onclick="submitFlag('${q.id}', this)">⚑ Flag as misclassified</button>
      </div>` : solBtn;

    return `<div class="qcard" id="qcard-${q.id}" onclick="this.classList.toggle('open')">
      <div class="qcard-header">
        <span class="qnum">Q${q.question_number}</span>
        <div class="qtags">${tagHtml}</div>
        <span class="marks">${sLabel}${marksStr ? ' &middot; '+marksStr : ''}</span>
        <span class="toggle-icon">&#9656;</span>
      </div>
      <div class="qcard-body" onclick="event.stopPropagation()">
        <div class="qimg-wrap"><h4>Question</h4><img src="${q.question_image}" loading="lazy"/></div>
        ${cardActions}
        <div class="sol-wrap sol-hidden">${solInner}</div>
        ${adminControls}
      </div>
    </div>`;
  }).join('');
  savedIds.forEach(id => {
    const btn = document.getElementById('save-btn-' + id);
    if (btn) markSaveBtn(btn, true);
  });
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
  const sol = btn.closest('.qcard-body').querySelector('.sol-wrap');
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
  const aosNum = Number(aos);
  fetch('/api/classify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id, aos: aosNum, aos_name: aosName, subject: '{{ subject }}',
                           tags: [aosNum], tag_names: [aosName] })
  }).then(r => r.json()).then(data => {
    if (data.ok) {
      const q = allQ.find(q => q.id === id);
      if (q) { q.aos = aosNum; q.aos_name = aosName; q.tags = [aosNum]; q.tag_names = [aosName]; }
      sel.value = '';
      // Refresh the tag pills for this card
      const card = document.getElementById('qcard-' + id);
      if (card) {
        const pillContainer = card.querySelector('.qtags');
        if (pillContainer) {
          const updatedQ = allQ.find(q => q.id === id);
          if (updatedQ) {
            const aosPills = IS_METHODS ? renderMethodsTagPills(updatedQ) : `<span class="qtag aos">${aosName}</span>`;
            pillContainer.innerHTML = aosPills + `<span class="qtag pub">${updatedQ.publisher} ${updatedQ.year}</span>`;
          }
        }
      }
    }
  });
}

function adminHide(id, newAos, btn) {
  if (newAos !== 9) {
    // Unhide: restore to original classification
    fetch('/api/classify/restore', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, subject: '{{ subject }}' })
    }).then(r => r.json()).then(data => {
      if (data.ok) {
        const q = allQ.find(q => q.id === id);
        if (q) { q.aos = data.aos; q.aos_name = data.aos_name; q.tags = data.tags; q.tag_names = data.tag_names; }
        renderCards();
      }
    });
  } else {
    fetch('/api/classify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, aos: 9, aos_name: 'Hidden', subject: '{{ subject }}',
                             tags: [9], tag_names: ['Hidden'] })
    }).then(r => r.json()).then(data => {
      if (data.ok) {
        const q = allQ.find(q => q.id === id);
        if (q) { q.aos = 9; q.aos_name = 'Hidden'; q.tags = [9]; q.tag_names = ['Hidden']; }
        renderCards();
      }
    });
  }
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
    body: JSON.stringify({ question_id: id, subject: '{{ subject }}' })
  }).then(r => r.json()).then(data => {
    if (data.ok) {
      btn.textContent = '⚑ Flagged';
      btn.classList.add('flagged');
      btn.onclick = null;
    }
  });
}

function loadSavedIds() {
  fetch('/api/saved?subject={{ subject }}').then(r => r.json()).then(data => {
    savedIds = new Set(data.ids);
    document.getElementById('saved-count').textContent = savedIds.size;
    savedIds.forEach(id => {
      const btn = document.getElementById('save-btn-' + id);
      if (btn) markSaveBtn(btn, true);
    });
  });
}

function toggleSaved(id, btn) {
  fetch('/api/saved', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question_id: id, subject: '{{ subject }}' })
  }).then(r => r.json()).then(data => {
    if (data.marked) {
      savedIds.add(id);
    } else {
      savedIds.delete(id);
    }
    markSaveBtn(btn, data.marked);
    document.getElementById('saved-count').textContent = savedIds.size;
    if (savedOnly) applyFilters();
  });
}

function markSaveBtn(btn, saved) {
  btn.textContent = saved ? 'Unsave' : 'Save';
  btn.classList.toggle('saved', saved);
}

function toggleSavedFilter() {
  savedOnly = !savedOnly;
  document.getElementById('tab-saved').classList.toggle('active', savedOnly);
  document.getElementById('tab-questions').classList.toggle('active', !savedOnly);
  page = 0;
  applyFilters();
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
  <a class="back" href="/{{ subject }}">← Back</a>
  <h1>{% if flagged_mode %}Flagged Questions ({{ questions|length }}){% elif unsorted_mode %}Unsorted Questions ({{ questions|length }}){% else %}Classifying: {{ publisher }} {{ year }}{% endif %}</h1>
  <div class="progress-bar-wrap"><div class="progress-bar" id="progress-bar" style="width:0%"></div></div>
  <span class="progress-label" id="progress-label">0 / {{ questions|length }}</span>
  {% if is_methods %}
  <button id="save-all-btn" onclick="saveAllProgress()" style="font-family:inherit;font-size:.82rem;font-weight:600;padding:7px 18px;border-radius:8px;border:none;background:#4ade80;color:#0a1a0a;cursor:pointer;white-space:nowrap;transition:background .15s">Save All</button>
  {% endif %}
</div>
<div class="exam-nav">
  <a class="exam-nav-btn flagged-tab {% if flagged_mode %}current{% endif %}"
     href="/classify?subject={{ subject }}&flagged=1">⚑ Flagged ({{ flagged_count }})</a>
  <a class="exam-nav-btn unsorted-tab {% if unsorted_mode %}current{% endif %}"
     href="/classify?subject={{ subject }}&unsorted=1">Unsorted ({{ unsorted_count }})</a>
  <span class="exam-nav-label" style="margin-left:8px;">Exam set:</span>
  {% for pub, yr in exam_sets %}
  <a class="exam-nav-btn {% if not unsorted_mode and pub == publisher and yr == year %}current{% endif %}"
     href="/classify?subject={{ subject }}&publisher={{ pub }}&year={{ yr }}">{{ pub }} {{ yr }}</a>
  {% endfor %}
</div>

<div class="container" id="container">
{% for q in questions %}
<div class="qblock {% if q.aos %}classified{% endif %}" id="block-{{ q.id }}" data-id="{{ q.id }}">
  <div class="qblock-header">
    <span class="qnum">{{ q.publisher }} {{ q.year }} — Exam {{ q.exam_type }} Q{{ q.question_number }}</span>
    <span class="qmeta">{{ q.section.replace('_',' ').title() }}{% if q.marks %} · {{ q.marks }} marks{% endif %}</span>
    <span class="status {% if q.aos == 0 %}unsorted-status{% elif q.aos == 7 and not is_methods %}pseudocode-status{% elif q.aos %}saved{% else %}unsaved{% endif %}" id="status-{{ q.id }}">
      {% if q.aos == 0 %}Unsorted{% elif q.aos %}{{ q.aos_name }}{% else %}Unclassified{% endif %}
    </span>
  </div>
  <div class="qblock-img">
    <img src="{{ q.question_image }}" loading="lazy"/>
  </div>
  {% if flags_by_qid.get(q.id) or q.id == highlight_qid %}
  <div class="flag-hints">
    <span class="flag-hint">⚑ Flagged as misclassified{% if flags_by_qid.get(q.id) %} ({{ flags_by_qid[q.id]|length }}×){% endif %}</span>
  </div>
  {% endif %}
  {% if is_methods and q.section != 'extended_response' %}
  {# Methods exam 1 / MCQ: multi-select checkboxes for AOS 1–5 #}
  <div class="aos-buttons" id="btns-{{ q.id }}">
    {% for num, name in methods_aos_exam1.items() %}
    <button class="aos-btn {% if q.tags and num in q.tags %}active{% elif q.aos == num and not q.tags %}active{% endif %}"
            onclick="methodsToggleTag('{{ q.id }}', {{ num }}, '{{ name }}', this)">
      {{ name }}
    </button>
    {% endfor %}
    <button class="aos-btn unsorted {% if q.aos == 0 %}active{% endif %}"
            onclick="methodsSetUnsorted('{{ q.id }}', this)">
      Unsorted
    </button>
  </div>
  {% elif is_methods and q.section == 'extended_response' %}
  {# Methods exam 2: binary radio — Core Content vs Probability and Statistics #}
  <div class="aos-buttons">
    {% for num, name in methods_aos_exam2.items() %}
    <button class="aos-btn {% if q.aos == num %}active{% endif %}"
            onclick="classify('{{ q.id }}', {{ num }}, '{{ name }}', this)">
      {{ name }}
    </button>
    {% endfor %}
    <button class="aos-btn unsorted {% if q.aos == 0 %}active{% endif %}"
            onclick="classify('{{ q.id }}', 0, 'Unsorted', this)">
      Unsorted
    </button>
  </div>
  {% else %}
  {# Specialist: single-select AOS buttons #}
  <div class="aos-buttons">
    {% for num, name in aos_map.items() %}
    {% if num != 0 %}
    <button class="aos-btn {% if q.aos == num %}active{% endif %}"
            onclick="classify('{{ q.id }}', {{ num }}, '{{ name }}', this)">
      {{ name }}
    </button>
    {% endif %}
    {% endfor %}
    <button class="aos-btn unsorted {% if q.aos == 0 %}active{% endif %}"
            onclick="classify('{{ q.id }}', 0, 'Unsorted', this)">
      Unsorted
    </button>
  </div>
  {% endif %}
</div>
{% endfor %}
<div class="done-banner" id="done-banner">All {{ questions|length }} questions classified!</div>
</div>

<script>
const total = {{ questions|length }};
const IS_METHODS_CLASSIFY = {{ is_methods|tojson }};
const METHODS_AOS_EXAM1 = {{ methods_aos_exam1|tojson }};
let classified = document.querySelectorAll('.qblock.classified').length;
// Track pending multi-tags for Methods exam 1: { id: Set of AOS numbers }
const pendingTags = {};
// Track pending single-tag changes (exam 2 + unsorted): { id: {aos, aos_name} }
const pendingSingle = {};
updateProgress();

function classify(id, aos, aosName, btn) {
  const block = document.getElementById('block-' + id);
  const status = document.getElementById('status-' + id);
  block.querySelectorAll('.aos-btn').forEach(b => b.classList.remove('active', 'active-new'));
  btn.classList.add('active-new');
  const wasClassified = block.classList.contains('classified');
  if (!wasClassified) { classified++; block.classList.add('classified'); updateProgress(); }
  status.textContent = aosName;
  status.className = (aos === 0) ? 'status unsorted-status' : (aos === 7 && !IS_METHODS_CLASSIFY) ? 'status pseudocode-status' : 'status saved';

  if (IS_METHODS_CLASSIFY) {
    // Queue for batch save
    pendingSingle[id] = { aos, aos_name: aosName, tags: [aos], tag_names: [aosName] };
    markSaveBtn('unsaved');
  } else {
    fetch('/api/classify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, aos, aos_name: aosName, subject: '{{ subject }}' })
    }).then(r => r.json()).then(data => {
      if (data.ok) { btn.classList.remove('active-new'); btn.classList.add('active'); }
    });
  }
}

// Methods exam 1: toggle a tag on/off
function methodsToggleTag(id, aos, aosName, btn) {
  if (!pendingTags[id]) pendingTags[id] = new Map();
  if (pendingTags[id].has(aos)) {
    pendingTags[id].delete(aos);
    btn.classList.remove('active', 'active-new');
  } else {
    pendingTags[id].set(aos, aosName);
    btn.classList.add('active-new');
    btn.classList.remove('active');
    const block = document.getElementById('block-' + id);
    block.querySelectorAll('.aos-btn.unsorted').forEach(b => b.classList.remove('active', 'active-new'));
  }
  // Mark block as having pending changes
  const block = document.getElementById('block-' + id);
  const wasClassified = block.classList.contains('classified');
  if (!wasClassified && pendingTags[id].size > 0) { classified++; block.classList.add('classified'); updateProgress(); }
  const status = document.getElementById('status-' + id);
  if (pendingTags[id].size > 0) {
    status.textContent = [...pendingTags[id].values()].join(', ') + ' *';
    status.className = 'status unsaved';
  }
  markSaveBtn('unsaved');
}

// Methods exam 1: mark as unsorted (immediate queue)
function methodsSetUnsorted(id, btn) {
  pendingTags[id] = new Map();
  const block = document.getElementById('block-' + id);
  block.querySelectorAll('.aos-btn').forEach(b => b.classList.remove('active', 'active-new'));
  btn.classList.add('active-new');
  pendingSingle[id] = { aos: 0, aos_name: 'Unsorted', tags: [0], tag_names: ['Unsorted'] };
  const status = document.getElementById('status-' + id);
  status.textContent = 'Unsorted *';
  status.className = 'status unsorted-status';
  markSaveBtn('unsaved');
}

function markSaveBtn(state) {
  const btn = document.getElementById('save-all-btn');
  if (!btn) return;
  if (state === 'unsaved') {
    btn.textContent = 'Save All *';
    btn.style.background = '#facc15';
    btn.style.color = '#1a1200';
  } else if (state === 'saving') {
    btn.textContent = 'Saving…';
    btn.style.background = '#60a5fa';
    btn.style.color = '#fff';
  } else {
    btn.textContent = 'Saved ✓';
    btn.style.background = '#4ade80';
    btn.style.color = '#0a1a0a';
  }
}

function saveAllProgress() {
  const updates = [];

  // Collect multi-tag changes (exam 1)
  for (const [id, tagMap] of Object.entries(pendingTags)) {
    if (tagMap.size === 0) continue;
    const tags = [...tagMap.keys()];
    const tag_names = [...tagMap.values()];
    updates.push({ id, aos: tags[0], aos_name: tag_names[0], tags, tag_names });
  }
  // Collect single-tag changes (exam 2 / unsorted)
  for (const [id, u] of Object.entries(pendingSingle)) {
    // Don't double-add if already in multi-tag
    if (!pendingTags[id] || pendingTags[id].size === 0) {
      updates.push({ id, ...u });
    }
  }

  if (!updates.length) { markSaveBtn('saved'); return; }
  markSaveBtn('saving');

  fetch('/api/classify/batch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ subject: '{{ subject }}', updates })
  }).then(r => r.json()).then(data => {
    if (data.ok) {
      // Flip active-new → active on all touched blocks
      updates.forEach(u => {
        const block = document.getElementById('block-' + u.id);
        if (block) {
          block.querySelectorAll('.aos-btn.active-new').forEach(b => {
            b.classList.remove('active-new'); b.classList.add('active');
          });
          const status = document.getElementById('status-' + u.id);
          if (status) {
            const label = u.tag_names ? u.tag_names.join(', ') : u.aos_name;
            status.textContent = label;
            status.className = u.aos === 0 ? 'status unsorted-status' : 'status saved';
          }
        }
      });
      // Clear pending state
      for (const id in pendingTags) delete pendingTags[id];
      for (const id in pendingSingle) delete pendingSingle[id];
      markSaveBtn('saved');
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
    return render_template_string(HOME_HTML, user_name=user["name"] if user else "", is_admin=admin_required())

@app.route("/specialist")
def browse_specialist():
    r = check_approved()
    if r: return r
    user = current_user()
    cfg = get_subject_config("specialist")
    return render_template_string(BROWSE_HTML, is_admin=admin_required(), user_name=user["name"] if user else "",
                                  subject="specialist", subject_name="Specialist Mathematics",
                                  aos_map=cfg["aos_map"], is_methods=False,
                                  css_primary="#196061", css_primary_dark="#042f3a",
                                  css_primary_light="#e6f2f2", css_primary_hover="#1a7a7b")

@app.route("/methods")
def browse_methods():
    r = check_approved()
    if r: return r
    user = current_user()
    cfg = get_subject_config("methods")
    return render_template_string(BROWSE_HTML, is_admin=admin_required(), user_name=user["name"] if user else "",
                                  subject="methods", subject_name="Mathematical Methods",
                                  aos_map=cfg["aos_map"], is_methods=True,
                                  css_primary="#2563eb", css_primary_dark="#1e3a5f",
                                  css_primary_light="#eff6ff", css_primary_hover="#1d4ed8")

@app.route("/api/questions")
def api_questions():
    if check_approved():
        return jsonify(error="unauthorized"), 401
    subject = request.args.get("subject", "specialist")
    cfg = get_subject_config(subject)
    data = cfg["data"]()
    data = apply_overrides(data, subject)
    if admin_required():
        return jsonify(data)
    hidden = get_hidden_publishers(subject)
    filtered = [q for q in data if q["publisher"] not in hidden]
    if subject == "specialist":
        filtered = [q for q in filtered if q.get("aos") != 8]
    filtered = [q for q in filtered if q.get("aos") != 9]
    return jsonify(filtered)

@app.route("/api/classify", methods=["POST"])
def api_classify():
    if not admin_required():
        return jsonify(error="forbidden"), 403
    data = request.get_json()
    qid = data.get("id")
    aos = data.get("aos")
    aos_name = data.get("aos_name")
    subject = data.get("subject", "specialist")
    tags = data.get("tags")       # optional; Methods only
    tag_names = data.get("tag_names")  # optional; Methods only
    if not qid or aos is None:
        return jsonify(error="missing fields"), 400
    cfg = get_subject_config(subject)
    if DEV_MODE:
        # Local: write directly to base JSON and update in-memory cache
        global questions_data, methods_data
        with open(cfg["file"]) as f:
            subject_data = json.load(f)
        for q in subject_data:
            if q["id"] == qid:
                q["aos"] = aos
                q["aos_name"] = aos_name
                if subject == "methods":
                    q["tags"] = tags if tags is not None else [aos]
                    q["tag_names"] = tag_names if tag_names is not None else [aos_name]
                break
        else:
            return jsonify(error="question not found"), 404
        with open(cfg["file"], "w") as f:
            json.dump(subject_data, f, indent=2)
        if subject == "specialist":
            questions_data = subject_data
        else:
            methods_data = subject_data
    else:
        # Server: write to overrides.json (survives git pull)
        override_entry = {"aos": aos, "aos_name": aos_name}
        if subject == "methods":
            override_entry["tags"] = tags if tags is not None else [aos]
            override_entry["tag_names"] = tag_names if tag_names is not None else [aos_name]
        overrides = load_overrides()
        overrides.setdefault(subject, {})[qid] = override_entry
        save_overrides(overrides)
    return jsonify(ok=True)

@app.route("/api/classify/restore", methods=["POST"])
def api_classify_restore():
    if not admin_required():
        return jsonify(error="forbidden"), 403
    data = request.get_json()
    qid = data.get("id")
    subject = data.get("subject", "specialist")
    if not qid:
        return jsonify(error="missing fields"), 400
    cfg = get_subject_config(subject)
    if DEV_MODE:
        # Locally, no overrides — just send to Unsorted
        with open(cfg["file"]) as f:
            subject_data = json.load(f)
        global questions_data, methods_data
        for q in subject_data:
            if q["id"] == qid:
                q["aos"] = 0
                q["aos_name"] = "Unsorted"
                if subject == "methods":
                    q["tags"] = [0]
                    q["tag_names"] = ["Unsorted"]
                break
        else:
            return jsonify(error="question not found"), 404
        with open(cfg["file"], "w") as f:
            json.dump(subject_data, f, indent=2)
        if subject == "specialist":
            questions_data = subject_data
        else:
            methods_data = subject_data
        return jsonify(ok=True, aos=0, aos_name="Unsorted", tags=[0], tag_names=["Unsorted"])
    else:
        # Server: remove override entry — question reverts to base JSON classification
        overrides = load_overrides()
        overrides.get(subject, {}).pop(qid, None)
        save_overrides(overrides)
        # Read original AOS from base JSON
        with open(cfg["file"]) as f:
            subject_data = json.load(f)
        q = next((q for q in subject_data if q["id"] == qid), None)
        if not q:
            return jsonify(error="question not found"), 404
        return jsonify(ok=True, aos=q["aos"], aos_name=q["aos_name"],
                       tags=q.get("tags", [q["aos"]]), tag_names=q.get("tag_names", [q["aos_name"]]))

@app.route("/api/classify/batch", methods=["POST"])
def api_classify_batch():
    if not admin_required():
        return jsonify(error="forbidden"), 403
    data = request.get_json()
    subject = data.get("subject", "specialist")
    updates = data.get("updates", [])  # list of {id, aos, aos_name, tags, tag_names}
    if not updates:
        return jsonify(ok=True, saved=0)
    cfg = get_subject_config(subject)
    if DEV_MODE:
        # Local: write directly to base JSON and update in-memory cache
        global questions_data, methods_data
        with open(cfg["file"]) as f:
            subject_data = json.load(f)
        update_map = {u["id"]: u for u in updates}
        saved = 0
        for q in subject_data:
            if q["id"] in update_map:
                u = update_map[q["id"]]
                q["aos"] = u["aos"]
                q["aos_name"] = u["aos_name"]
                if subject == "methods":
                    q["tags"] = u.get("tags", [u["aos"]])
                    q["tag_names"] = u.get("tag_names", [u["aos_name"]])
                saved += 1
        with open(cfg["file"], "w") as f:
            json.dump(subject_data, f, indent=2)
        if subject == "specialist":
            questions_data = subject_data
        else:
            methods_data = subject_data
    else:
        # Server: write to overrides.json
        overrides = load_overrides()
        overrides.setdefault(subject, {})
        saved = 0
        for u in updates:
            entry = {"aos": u["aos"], "aos_name": u["aos_name"]}
            if subject == "methods":
                entry["tags"] = u.get("tags", [u["aos"]])
                entry["tag_names"] = u.get("tag_names", [u["aos_name"]])
            overrides[subject][u["id"]] = entry
            saved += 1
        save_overrides(overrides)
    return jsonify(ok=True, saved=saved)


@app.route("/classify")
def classify_page():
    if not admin_required():
        return redirect(url_for("admin_login") + "?next=/classify")
    subject = request.args.get("subject", "specialist")
    cfg = get_subject_config(subject)
    with open(cfg["file"]) as f:
        subject_data = json.load(f)
    aos_map = cfg["aos_map"]

    unsorted_mode = request.args.get("unsorted") == "1"
    flagged_mode = request.args.get("flagged") == "1"
    publisher = request.args.get("publisher", subject_data[0]["publisher"] if subject_data else "")
    year = int(request.args.get("year", subject_data[0]["year"] if subject_data else 2025))

    subject_flags = [f for f in _read_flags() if f.get("subject") == subject]

    if flagged_mode:
        flagged_ids = {f["question_id"] for f in subject_flags}
        questions = [q for q in subject_data if q["id"] in flagged_ids]
    elif unsorted_mode:
        questions = [q for q in subject_data if q["aos"] == 0]
    else:
        questions = [q for q in subject_data if q["publisher"] == publisher and q["year"] == year]

    seen = set()
    exam_sets = []
    for q in subject_data:
        key = (q["publisher"], q["year"])
        if key not in seen:
            seen.add(key)
            exam_sets.append(key)
    exam_sets.sort(key=lambda x: (x[0], x[1]))

    unsorted_count = sum(1 for q in subject_data if q["aos"] == 0)
    flagged_count = len({f["question_id"] for f in subject_flags})

    flags_by_qid = {}
    for f in subject_flags:
        flags_by_qid.setdefault(f["question_id"], []).append(f)

    is_methods = subject == "methods"
    # For Methods classify page: split AOS map into exam-1 (1–5) and exam-2 (6–7) groups
    methods_aos_exam1 = {k: v for k, v in aos_map.items() if 1 <= k <= 5 or k == 8} if is_methods else {}
    methods_aos_exam2 = {k: v for k, v in aos_map.items() if k in (6, 7)} if is_methods else {}
    highlight_qid = request.args.get("qid", "")

    return render_template_string(CLASSIFY_HTML, questions=questions, publisher=publisher, year=year,
                                  exam_sets=exam_sets, unsorted_mode=unsorted_mode, unsorted_count=unsorted_count,
                                  flagged_mode=flagged_mode, flagged_count=flagged_count, flags_by_qid=flags_by_qid,
                                  subject=subject, aos_map=aos_map, is_methods=is_methods,
                                  methods_aos_exam1=methods_aos_exam1, methods_aos_exam2=methods_aos_exam2,
                                  highlight_qid=highlight_qid)

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

def _run_pipeline(subject, base_dir):
    log_path = os.path.join(base_dir, f"pipeline_log_{subject}.txt")
    pipeline_dir = os.path.join(base_dir, "pipeline")
    venv_python = os.path.join(base_dir, "venv", "bin", "python3")
    python = venv_python if os.path.exists(venv_python) else "python3"
    steps = [
        [python, os.path.join(pipeline_dir, "01_convert_docx.py"), "--subject", subject],
        [python, os.path.join(pipeline_dir, "02_extract_and_crop.py"), "--subject", subject],
        [python, os.path.join(pipeline_dir, "03_classify.py"), "--subject", subject],
    ]
    with open(log_path, "w") as log:
        for step in steps:
            log.write(f"\n--- {os.path.basename(step[1])} ---\n")
            log.flush()
            result = subprocess.run(step, capture_output=True, text=True, cwd=base_dir)
            log.write(result.stdout)
            if result.stderr:
                log.write(result.stderr)
            log.flush()
            if result.returncode != 0:
                log.write(f"ERROR: step exited with code {result.returncode}\n")
                break


@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify(error="no file"), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify(error="empty filename"), 400
    subject = request.args.get("subject", "specialist")
    if subject not in ("specialist", "methods"):
        subject = "specialist"
    dest_dir = os.path.join(UPLOAD_DIR, subject)
    os.makedirs(dest_dir, exist_ok=True)
    filename = os.path.basename(f.filename)
    save_path = os.path.join(dest_dir, filename)
    try:
        f.save(save_path)
    except Exception as e:
        return jsonify(error=str(e)), 500

    if filename.lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(save_path, "r") as zf:
                zf.extractall(dest_dir)
            os.remove(save_path)
        except Exception as e:
            return jsonify(error=f"zip extract failed: {e}"), 500

    threading.Thread(target=_run_pipeline, args=(subject, BASE), daemon=True).start()
    return jsonify(ok=True, filename=filename, pipeline="started")

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

HOME_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>VCE Mathematics Question Bank</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Poppins',system-ui,sans-serif; background:#f0f0f0; color:#1a202c; min-height:100vh; }
.topbar {
  background:#2d2d2d; padding:0 32px; display:flex; align-items:center;
  gap:20px; position:sticky; top:0; z-index:100; height:60px;
}
.topbar h1 { font-size:1.05rem; font-weight:600; color:#fff; letter-spacing:-.01em; }
.spacer { flex:1; }
.topbar .user-name { color:rgba(255,255,255,.55); font-size:.82rem; }
.signout-btn {
  font-family:inherit; font-size:.78rem; font-weight:500; padding:5px 12px;
  border-radius:6px; border:1px solid rgba(255,255,255,.2);
  background:transparent; color:rgba(255,255,255,.7); cursor:pointer;
  text-decoration:none; transition:all .15s; white-space:nowrap;
}
.signout-btn:hover { background:rgba(255,255,255,.1); color:#fff; }
.main {
  display:flex; flex-direction:column; align-items:center; justify-content:center;
  min-height:calc(100vh - 60px); padding:40px 24px;
}
.label { font-size:.75rem; font-weight:600; letter-spacing:.1em; text-transform:uppercase; color:#999; margin-bottom:32px; }
.subject-grid { display:flex; gap:16px; flex-wrap:wrap; justify-content:center; }
.subject-card {
  background:#fff; border:1px solid #e4e4e4; border-radius:14px;
  padding:40px 44px; width:260px; text-align:center; cursor:pointer;
  text-decoration:none; color:#1a202c;
  box-shadow:0 1px 4px rgba(0,0,0,.06);
  transition:box-shadow .2s, transform .2s, border-color .2s;
  display:block;
}
.subject-card.specialist:hover { border-color:#196061; box-shadow:0 4px 20px rgba(25,96,97,.15); transform:translateY(-2px); }
.subject-card.methods:hover { border-color:#2563eb; box-shadow:0 4px 20px rgba(37,99,235,.15); transform:translateY(-2px); }
.subject-card .icon { font-size:2rem; margin-bottom:20px; color:#555; }
.subject-card h2 { font-size:.95rem; font-weight:600; color:#1a202c; }
@media (max-width:600px) {
  .topbar { padding:0 16px; }
  .topbar .user-name { display:none; }
  .subject-grid { flex-direction:column; align-items:center; width:100%; }
  .subject-card { width:100%; max-width:340px; padding:28px 32px; }
}
</style>
</head>
<body>
<div class="topbar">
  <h1>VCE Mathematics Question Bank</h1>
  <div class="spacer"></div>
  <span class="user-name">{{ user_name }}</span>
  {% if is_admin %}<a class="signout-btn" href="/admin/users">Users</a>{% endif %}
  <a class="signout-btn" href="/logout">Sign out</a>
</div>
<div class="main">
  <div class="label">Select a subject</div>
  <div class="subject-grid">
    <a class="subject-card specialist" href="/specialist">
      <div class="icon">&#x221E;</div>
      <h2>Specialist Mathematics</h2>
    </a>
    <a class="subject-card methods" href="/methods">
      <div class="icon">&#x222B;</div>
      <h2>Mathematical Methods</h2>
    </a>
  </div>
</div>
</body>
</html>"""

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Sign In — VCE Mathematics Question Bank</title>
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
  <h1>VCE Mathematics Question Bank</h1>
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
<title>Awaiting Approval — VCE Mathematics Question Bank</title>
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
<title>Users — VCE Mathematics Question Bank</title>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root {
  --bg:#f0f0f0; --surface:#fff; --border:#e4e4e4; --text:#1a202c;
  --muted:#718096; --accent-green:#38a169; --red:#e53e3e;
  --shadow-sm:0 1px 3px rgba(0,0,0,.06); --radius:12px;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Poppins',system-ui,sans-serif; background:var(--bg); color:var(--text); min-height:100vh; }
.topbar { background:#2d2d2d; padding:0 32px; display:flex; align-items:center; gap:16px; position:sticky; top:0; z-index:100; height:60px; }
.topbar h1 { font-size:1.05rem; font-weight:600; color:#fff; white-space:nowrap; }
.tabs { display:flex; gap:4px; margin-left:24px; }
.tab { background:none; border:none; color:rgba(255,255,255,.55); font-family:inherit; font-size:.875rem; font-weight:500; padding:8px 18px; border-radius:8px; cursor:pointer; text-decoration:none; transition:all .15s; }
.tab:hover { color:#fff; background:rgba(255,255,255,.1); }
.tab.active { color:#fff; background:rgba(255,255,255,.12); }
.spacer { flex:1; }
.signout { color:rgba(255,255,255,.6); font-size:.78rem; text-decoration:none; padding:5px 12px; border:1px solid rgba(255,255,255,.2); border-radius:6px; white-space:nowrap; }
.signout:hover { color:#fff; background:rgba(255,255,255,.1); }
.container { max-width:820px; margin:0 auto; padding:40px 24px; }
.section { margin-bottom:44px; }
.section h2 { font-size:1.05rem; font-weight:600; margin-bottom:14px; color:#1a202c; display:flex; align-items:center; gap:8px; }
.badge { font-size:.7rem; font-weight:600; padding:2px 9px; border-radius:99px; color:#fff; background:#555; }
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
.btn-approve { background:#2d2d2d; color:#fff; }
.btn-approve:hover { background:#444; }
.btn-reject { background:none; border:1px solid var(--border); color:var(--muted); }
.btn-reject:hover { border-color:var(--red); color:var(--red); }
.btn-revoke { background:none; border:1px solid var(--border); color:var(--muted); font-size:.75rem; padding:5px 12px; }
.btn-revoke:hover { border-color:var(--red); color:var(--red); }
.empty { color:var(--muted); font-size:.85rem; padding:20px; text-align:center; background:var(--surface); border:1px solid var(--border); border-radius:10px; }
</style>
</head>
<body>
<div class="topbar">
  <h1>VCE Mathematics Question Bank</h1>
  <div class="tabs">
    <a class="tab" href="/">← Subjects</a>
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
<title>Admin — {{ subject_name }} Question Bank</title>
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
  --primary: {{ css_primary }};
  --primary-dark: {{ css_primary_dark }};
  --primary-light: {{ css_primary_light }};
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
@media (max-width: 768px) {
  .topbar { padding:0 12px; gap:8px; }
  .topbar h1 { font-size:.9rem; min-width:0; overflow:hidden; text-overflow:ellipsis; }
  .topbar .tabs { margin-left:8px; gap:2px; }
  .topbar .tab { padding:6px 10px; font-size:.78rem; }
}
@media (max-width: 480px) {
  .topbar h1 { display:none; }
  .topbar .tabs { margin-left:0; }
}

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
.flag-actions { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
.flag-reclassify { font-family:inherit; font-size:.82rem; padding:6px 8px; border-radius:8px; border:1px solid var(--border); background:var(--surface); color:var(--text); cursor:pointer; }
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
.toggle-row { display:flex; align-items:center; justify-content:space-between; padding:12px 18px; background:var(--surface); border:1px solid var(--border); border-radius:10px; margin-bottom:8px; box-shadow:var(--shadow-sm); }
.toggle-label { font-size:.9rem; font-weight:500; display:flex; align-items:center; gap:8px; }
.hidden-tag { font-size:.72rem; color:var(--red); font-weight:600; background:rgba(229,62,62,.08); padding:2px 7px; border-radius:99px; }
.toggle { position:relative; display:inline-block; width:44px; height:24px; flex-shrink:0; }
.toggle input { opacity:0; width:0; height:0; }
.slider { position:absolute; cursor:pointer; top:0; left:0; right:0; bottom:0; background:#cbd5e0; border-radius:24px; transition:.2s; }
.slider:before { position:absolute; content:""; height:18px; width:18px; left:3px; bottom:3px; background:#fff; border-radius:50%; transition:.2s; }
input:checked + .slider { background:var(--primary); }
input:checked + .slider:before { transform:translateX(20px); }
</style>
</head>
<body>

<div class="topbar">
  <h1>{{ subject_name }} Question Bank</h1>
  <div class="tabs">
    <a class="tab" href="/">← Subjects</a>
    <a class="tab" href="/{{ subject }}">Questions</a>
    <a class="tab active" href="/admin?subject={{ subject }}">Admin</a>
  </div>
</div>

<div class="container">
  <div class="section">
    <h2>Publisher Visibility</h2>
    <p class="desc">Hidden publishers are invisible to students but remain accessible in the classify tool.</p>
    {% for pub in publishers %}
    <div class="toggle-row">
      <span class="toggle-label">
        {{ pub }}
        {% if pub in hidden_publishers %}<span class="hidden-tag">hidden</span>{% endif %}
      </span>
      <label class="toggle">
        <input type="checkbox" {% if pub not in hidden_publishers %}checked{% endif %} onchange="togglePublisher('{{ pub }}', this)">
        <span class="slider"></span>
      </label>
    </div>
    {% endfor %}
  </div>

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
  [...files].forEach(f => uploadFile(f, '/upload?subject={{ subject }}', pw2));
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
      let msg = 'Failed (' + xhr.status + ')';
      try { msg += ': ' + (JSON.parse(xhr.responseText).error || xhr.responseText); } catch(e) {}
      st.textContent = msg;
    }
  };
  xhr.onerror = () => {
    row.classList.add('error');
    st.textContent = 'Network error (connection refused or reset)';
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
  fetch('/api/admin/flags?subject={{ subject }}').then(r => r.json()).then(flags => {
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
          <select class="flag-reclassify" onchange="flagReclassify('${f.id}', '${f.question_id}', '${f.subject}', this)">
            <option value="">Reclassify…</option>
            {% for num, name in aos_map.items() %}{% if num not in (0, 9) %}<option value="{{ num }}|{{ name }}">{{ name }}</option>{% endif %}{% endfor %}
            <option value="0|Unsorted">Unsorted</option>
          </select>
          <button class="flag-classify-link" onclick="flagHide('${f.id}', '${f.question_id}', '${f.subject}')">Hide</button>
          <button class="flag-dismiss-btn" onclick="dismissFlag('${f.id}')">Dismiss</button>
        </div>
      </div>`;
    }).join('');
  });
}

function dismissFlag(id) {
  const el = document.getElementById('flag-item-' + id);
  if (el) { el.style.opacity = '0.3'; el.style.pointerEvents = 'none'; }
  fetch('/api/admin/flags/' + id, { method: 'DELETE' })
    .then(r => r.json()).then(data => {
      if (data.ok) {
        if (el) el.remove();
        const remaining = document.querySelectorAll('#flags-list .flag-item').length;
        const badge = document.getElementById('flags-badge');
        badge.textContent = remaining;
        badge.className = 'flags-count-badge' + (remaining ? '' : ' zero');
        if (!remaining) document.getElementById('flags-list').innerHTML = '<div class="empty">No flagged questions</div>';
      } else {
        if (el) { el.style.opacity = ''; el.style.pointerEvents = ''; }
      }
    });
}

function flagReclassify(flagId, qid, subject, sel) {
  const [aos, aosName] = sel.value.split('|');
  if (!aos && aos !== '0') return;
  const aosNum = Number(aos);
  fetch('/api/classify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: qid, aos: aosNum, aos_name: aosName, subject,
                           tags: [aosNum], tag_names: [aosName] })
  }).then(r => r.json()).then(data => {
    if (data.ok) dismissFlag(flagId);
    else sel.value = '';
  });
}

function flagHide(flagId, qid, subject) {
  fetch('/api/classify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: qid, aos: 9, aos_name: 'Hidden', subject,
                           tags: [9], tag_names: ['Hidden'] })
  }).then(r => r.json()).then(data => {
    if (data.ok) dismissFlag(flagId);
  });
}

loadFlags();

function togglePublisher(publisher, checkbox) {
  fetch('/api/admin/publishers/toggle', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({publisher: publisher, subject: '{{ subject }}'})
  }).then(r => r.json()).then(d => {
    if (!d.ok) checkbox.checked = !checkbox.checked;
    const row = checkbox.closest('.toggle-row');
    const label = row.querySelector('.toggle-label');
    const existing = label.querySelector('.hidden-tag');
    if (d.hidden) {
      if (!existing) { const tag = document.createElement('span'); tag.className = 'hidden-tag'; tag.textContent = 'hidden'; label.appendChild(tag); }
    } else {
      if (existing) existing.remove();
    }
  });
}
</script>
</body>
</html>"""

def admin_required():
    if DEV_MODE:
        return True
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
    subject = request.args.get("subject", "specialist")
    cfg = get_subject_config(subject)
    publishers = sorted(set(q["publisher"] for q in cfg["data"]()))
    hidden = get_hidden_publishers(subject)
    colors = {"specialist": ("#196061", "#042f3a", "#e6f2f2", "#1a7a7b"),
              "methods":    ("#2563eb", "#1e3a5f", "#eff6ff", "#1d4ed8")}
    cp, cpd, cpl, cph = colors.get(subject, colors["specialist"])
    return render_template_string(ADMIN_HTML, publishers=publishers, hidden_publishers=hidden,
                                  subject=subject, subject_name=cfg["name"],
                                  css_primary=cp, css_primary_dark=cpd,
                                  css_primary_light=cpl, css_primary_hover=cph,
                                  aos_map=cfg["aos_map"])

@app.route("/admin/upload", methods=["POST"])
def admin_upload():
    if "file" not in request.files:
        return jsonify(error="no file"), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify(error="empty filename"), 400
    filename = os.path.basename(f.filename)
    try:
        f.save(os.path.join(ADMIN_UPLOAD_DIR, filename))
    except Exception as e:
        return jsonify(error=str(e)), 500
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
    subject = data.get("subject", "specialist")
    cfg = get_subject_config(subject)
    q = next((q for q in apply_overrides(cfg["data"](), subject) if q["id"] == qid), None)
    if not q:
        return jsonify(error="question not found"), 404
    flag = {
        "id": str(uuid.uuid4()),
        "question_id": qid,
        "subject": subject,
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
    flags = _read_flags()
    flags.append(flag)
    _write_flags(flags)
    return jsonify(ok=True)

@app.route("/api/saved")
def api_get_saved():
    user_id = get_current_user_id()
    subject = request.args.get("subject", "specialist")
    with get_db() as conn:
        rows = conn.execute(
            "SELECT question_id FROM difficult_questions WHERE user_id=? AND subject=?",
            (user_id, subject)
        ).fetchall()
    return jsonify({"ids": [r["question_id"] for r in rows]})

@app.route("/api/saved", methods=["POST"])
def api_toggle_saved():
    user_id = get_current_user_id()
    data = request.get_json()
    question_id = data["question_id"]
    subject = data.get("subject", "specialist")
    with get_db() as conn:
        existing = conn.execute(
            "SELECT 1 FROM difficult_questions WHERE user_id=? AND question_id=? AND subject=?",
            (user_id, question_id, subject)
        ).fetchone()
        if existing:
            conn.execute(
                "DELETE FROM difficult_questions WHERE user_id=? AND question_id=? AND subject=?",
                (user_id, question_id, subject)
            )
            marked = False
        else:
            conn.execute(
                "INSERT INTO difficult_questions (user_id, question_id, subject, created_at) VALUES (?,?,?,?)",
                (user_id, question_id, subject, datetime.datetime.utcnow().isoformat())
            )
            marked = True
        conn.commit()
    return jsonify({"ok": True, "marked": marked})

@app.route("/api/admin/publishers/toggle", methods=["POST"])
def toggle_publisher():
    if not admin_required():
        return jsonify(error="forbidden"), 403
    body = request.get_json()
    publisher = body.get("publisher")
    subject = body.get("subject", "specialist")
    settings = load_settings()
    if subject not in settings:
        settings[subject] = {"hidden_publishers": []}
    hidden = set(settings[subject].get("hidden_publishers", []))
    if publisher in hidden:
        hidden.discard(publisher)
        is_hidden = False
    else:
        hidden.add(publisher)
        is_hidden = True
    settings[subject]["hidden_publishers"] = list(hidden)
    save_settings(settings)
    return jsonify(ok=True, hidden=is_hidden)

@app.route("/api/admin/flags")
def api_admin_flags():
    if not admin_required():
        return jsonify(error="forbidden"), 403
    subject = request.args.get("subject", "specialist")
    flags = _read_flags()
    return jsonify([f for f in flags if f.get("subject") == subject])

@app.route("/api/admin/flags/<flag_id>", methods=["DELETE"])
def api_admin_delete_flag(flag_id):
    if not admin_required():
        return jsonify(error="forbidden"), 403
    flags = _read_flags()
    flags = [f for f in flags if f["id"] != flag_id]
    _write_flags(flags)
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
