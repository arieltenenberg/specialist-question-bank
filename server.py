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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS completed_questions (
                user_id      TEXT NOT NULL,
                question_id  TEXT NOT NULL,
                subject      TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                PRIMARY KEY (user_id, question_id, subject)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS leaderboards (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            )
        """)
        conn.commit()
        try:
            conn.execute("ALTER TABLE users ADD COLUMN funny_popup INTEGER NOT NULL DEFAULT 0")
            conn.commit()
        except Exception:
            pass  # column already exists
        try:
            conn.execute("ALTER TABLE users ADD COLUMN leaderboard INTEGER NOT NULL DEFAULT 0")
            conn.commit()
        except Exception:
            pass  # column already exists
        try:
            conn.execute("ALTER TABLE users ADD COLUMN leaderboard_id INTEGER")
            conn.commit()
            # Migrate existing leaderboard=1 users into a default group
            count = conn.execute("SELECT COUNT(*) FROM users WHERE leaderboard=1").fetchone()[0]
            if count > 0:
                conn.execute("INSERT OR IGNORE INTO leaderboards (name) VALUES ('Leaderboard')")
                conn.commit()
                lb_id = conn.execute("SELECT id FROM leaderboards WHERE name='Leaderboard'").fetchone()[0]
                conn.execute("UPDATE users SET leaderboard_id=? WHERE leaderboard=1", (lb_id,))
                conn.commit()
        except Exception:
            pass  # column already exists
        try:
            conn.execute("ALTER TABLE users ADD COLUMN nickname TEXT")
            conn.commit()
        except Exception:
            pass  # column already exists
        try:
            conn.execute("ALTER TABLE users ADD COLUMN xp INTEGER NOT NULL DEFAULT 0")
            conn.commit()
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE users ADD COLUMN current_streak INTEGER NOT NULL DEFAULT 0")
            conn.commit()
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE users ADD COLUMN longest_streak INTEGER NOT NULL DEFAULT 0")
            conn.commit()
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE users ADD COLUMN last_streak_date TEXT")
            conn.commit()
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE users ADD COLUMN shabbat_proof INTEGER NOT NULL DEFAULT 0")
            conn.commit()
        except Exception:
            pass

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

# ---------------------------------------------------------------------------
# Gamification — constants and helpers
# ---------------------------------------------------------------------------

AEST = datetime.timezone(datetime.timedelta(hours=10))

def today_aest():
    return datetime.datetime.now(AEST).strftime("%Y-%m-%d")

def yesterday_aest():
    return (datetime.datetime.now(AEST) - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

LEVELS = [
    (1, "Novice",      0),
    (2, "Apprentice",  250),
    (3, "Student",     750),
    (4, "Scholar",     1750),
    (5, "Prodigy",     3750),
    (6, "Veteran",     7500),
    (7, "Master",      14000),
    (8, "Grandmaster", 23500),
]

QUESTION_BADGES = [
    {"id": "q_1",    "name": "First Step",        "desc": "Complete your first question",  "threshold": 1},
    {"id": "q_10",   "name": "On a Roll",          "desc": "Complete 10 questions",         "threshold": 10},
    {"id": "q_50",   "name": "Committed",          "desc": "Complete 50 questions",         "threshold": 50},
    {"id": "q_100",  "name": "Dedicated",          "desc": "Complete 100 questions",        "threshold": 100},
    {"id": "q_250",  "name": "Relentless",         "desc": "Complete 250 questions",        "threshold": 250},
    {"id": "q_500",  "name": "Grinder",            "desc": "Complete 500 questions",        "threshold": 500},
    {"id": "q_1000", "name": "Elite",              "desc": "Complete 1,000 questions",      "threshold": 1000},
    {"id": "q_1500", "name": "The Real Deal",      "desc": "Complete 1,500 questions",      "threshold": 1500},
]

STREAK_BADGES = [
    {"id": "s_7",   "name": "Consistent",  "desc": "Reach a 7-day streak",   "threshold": 7},
    {"id": "s_30",  "name": "Disciplined", "desc": "Reach a 30-day streak",  "threshold": 30},
    {"id": "s_100", "name": "Centurion",    "desc": "Reach a 100-day streak", "threshold": 100},
]

# Build question_id → section/marks lookups at startup
_question_lookup = {}  # question_id → section
_marks_lookup = {}     # question_id → effective marks (MC 0→1)
for _q in questions_data + methods_data:
    _question_lookup[_q["id"]] = _q.get("section", "")
    _m = _q.get("marks") or 0
    _marks_lookup[_q["id"]] = _m if _m > 0 else 1

SPECIALIST_HIDDEN_AOS = {0, 8, 9}
METHODS_HIDDEN_AOS = {0, 9}

_specialist_aos_counts = {}
for _q in questions_data:
    _aos = _q.get("aos")
    if _aos not in SPECIALIST_HIDDEN_AOS:
        _specialist_aos_counts[_aos] = _specialist_aos_counts.get(_aos, 0) + 1

_methods_aos_counts = {}
for _q in methods_data:
    _aos = _q.get("aos")
    if _aos not in METHODS_HIDDEN_AOS:
        _methods_aos_counts[_aos] = _methods_aos_counts.get(_aos, 0) + 1

AOS_QUESTION_COUNTS = {"specialist": _specialist_aos_counts, "methods": _methods_aos_counts}

def get_level(xp):
    level = LEVELS[0]
    for lv in LEVELS:
        if xp >= lv[2]:
            level = lv
    return level

def get_next_level(xp):
    for lv in LEVELS:
        if lv[2] > xp:
            return lv
    return None

def get_xp_for_question(question_id):
    return _marks_lookup.get(question_id, 1) * 5

def get_aos_badges_for_subject(subject):
    aos_map = SPECIALIST_AOS if subject == "specialist" else METHODS_AOS
    hidden = SPECIALIST_HIDDEN_AOS if subject == "specialist" else METHODS_HIDDEN_AOS
    return [
        {"id": f"aos_{subject}_{aos_id}", "name": f"Mastered {name}", "desc": f"Complete all {name} questions", "aos_id": aos_id}
        for aos_id, name in sorted(aos_map.items())
        if aos_id not in hidden
    ]

def compute_earned_badge_ids(total_completed, longest_streak, completed_ids_subject, subject):
    earned = set()
    for b in QUESTION_BADGES:
        if total_completed >= b["threshold"]:
            earned.add(b["id"])
    for b in STREAK_BADGES:
        if longest_streak >= b["threshold"]:
            earned.add(b["id"])
    # Use effective questions (overrides applied) so hidden questions don't inflate the target count
    hidden = SPECIALIST_HIDDEN_AOS if subject == "specialist" else METHODS_HIDDEN_AOS
    effective_qs = apply_overrides(get_subject_config(subject)["data"](), subject)
    effective_aos_counts = {}
    effective_qid_aos = {}
    for q in effective_qs:
        aos = q.get("aos")
        effective_qid_aos[q["id"]] = aos
        if aos not in hidden:
            effective_aos_counts[aos] = effective_aos_counts.get(aos, 0) + 1
    aos_done = {}
    for qid in completed_ids_subject:
        aos = effective_qid_aos.get(qid)
        if aos is not None and aos not in hidden:
            aos_done[aos] = aos_done.get(aos, 0) + 1
    for aos_id, total in effective_aos_counts.items():
        if total > 0 and aos_done.get(aos_id, 0) >= total:
            earned.add(f"aos_{subject}_{aos_id}")
    return earned

def migrate_xp_for_existing_users():
    """Recompute XP for all users from their completed questions using current XP rates."""
    with get_db() as conn:
        users = conn.execute("SELECT google_id FROM users").fetchall()
        for row in users:
            uid = row["google_id"]
            completed = conn.execute(
                "SELECT question_id FROM completed_questions WHERE user_id=?", (uid,)
            ).fetchall()
            total_xp = sum(get_xp_for_question(r["question_id"]) for r in completed)
            conn.execute("UPDATE users SET xp=? WHERE google_id=?", (total_xp, uid))
        conn.commit()

migrate_xp_for_existing_users()

if DEV_MODE:
    with get_db() as conn:
        conn.execute("""INSERT OR IGNORE INTO users
            (google_id, email, name, status, created_at, xp, current_streak, longest_streak)
            VALUES ('dev_user','dev@localhost','Dev User','approved',?,0,0,0)""",
            (datetime.datetime.utcnow().isoformat(),))
        conn.commit()

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
<link rel="icon" type="image/x-icon" href="/static/favicon.ico"/>
<link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32x32.png"/>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #f6f3ee;
  --surface: #fdfaf6;
  --border: #e3ddd4;
  --text: #1c1917;
  --text-secondary: #57534e;
  --muted: #78716c;
  --primary: {{ css_primary }};
  --primary-dark: {{ css_primary_dark }};
  --primary-light: {{ css_primary_light }};
  --primary-hover: {{ css_primary_hover }};
  --shadow-sm: 0 1px 3px rgba(60,44,28,.07);
  --shadow-md: 0 4px 12px rgba(60,44,28,.09);
  --radius: 12px;
}

* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'DM Sans',system-ui,sans-serif; background:var(--bg); color:var(--text); min-height:100vh; }
a { color:#1f1f1f; text-decoration:none; }

/* ----- Top bar ----- */
.topbar {
  background:#2d2d2d;
  position:sticky;
  top:0;
  z-index:100;
  box-shadow:0 2px 8px rgba(60,44,28,.15);
}
.topbar-top {
  display:grid;
  grid-template-columns:1fr auto 1fr;
  align-items:center;
  padding:0 28px;
  height:52px;
  border-bottom:1px solid rgba(255,255,255,.1);
}
.topbar-bottom {
  display:flex;
  align-items:stretch;
  justify-content:center;
  padding:0 20px;
  height:44px;
  gap:2px;
  background:#1f1f1f;
}
.back-link {
  color:rgba(255,255,255,.65);
  font-size:.82rem;
  font-weight:500;
  text-decoration:none;
  white-space:nowrap;
  transition:color .15s;
  flex-shrink:0;
}
.back-link:hover { color:#fff; }
.topbar h1 {
  font-size:1.05rem;
  font-weight:700;
  color:#fff;
  letter-spacing:-.01em;
  text-align:center;
  white-space:nowrap;
  overflow:hidden;
  text-overflow:ellipsis;
}
.topbar-right {
  display:flex;
  align-items:center;
  gap:6px;
  justify-self:end;
}
.user-avatar-wrap {
  position:relative;
}
.settings-wrap {
  position:relative;
}
.settings-icon-btn {
  width:34px;
  height:34px;
  border-radius:50%;
  background:rgba(255,255,255,.13);
  border:1.5px solid rgba(255,255,255,.25);
  color:rgba(255,255,255,.85);
  font-size:1rem;
  display:flex;
  align-items:center;
  justify-content:center;
  cursor:pointer;
  transition:background .15s;
  user-select:none;
  padding:0;
  line-height:1;
}
.settings-icon-btn:hover { background:rgba(255,255,255,.25); }
.settings-dropdown {
  display:none;
  position:absolute;
  top:calc(100% + 10px);
  right:0;
  background:var(--surface);
  border:1px solid var(--border);
  border-radius:10px;
  box-shadow:var(--shadow-md);
  min-width:200px;
  z-index:200;
  overflow:hidden;
}
.settings-dropdown.open { display:block; }
.settings-dropdown-title {
  padding:10px 14px 8px;
  font-size:.75rem;
  font-weight:600;
  color:var(--muted);
  text-transform:uppercase;
  letter-spacing:.04em;
  border-bottom:1px solid var(--border);
}
.settings-toggle {
  display:flex;
  align-items:center;
  justify-content:space-between;
  padding:10px 14px;
  cursor:pointer;
  transition:background .15s;
  user-select:none;
}
.settings-toggle + .settings-toggle { border-top:1px solid var(--border); }
.settings-toggle:hover { background:var(--bg); }
.settings-toggle span { font-size:.84rem; color:var(--text); }
.settings-toggle.active .toggle-switch { background:#2d2d2d; }
.settings-toggle.active .toggle-switch::after { transform:translateX(15px); }
.user-avatar {
  width:34px;
  height:34px;
  border-radius:50%;
  background:rgba(255,255,255,.18);
  border:1.5px solid rgba(255,255,255,.35);
  color:#fff;
  font-size:.78rem;
  font-weight:700;
  display:flex;
  align-items:center;
  justify-content:center;
  cursor:pointer;
  transition:background .15s;
  user-select:none;
}
.user-avatar:hover { background:rgba(255,255,255,.28); }
.user-dropdown {
  display:none;
  position:absolute;
  top:calc(100% + 10px);
  right:0;
  background:var(--surface);
  border:1px solid var(--border);
  border-radius:10px;
  box-shadow:var(--shadow-md);
  min-width:190px;
  z-index:200;
  overflow:hidden;
}
.user-dropdown.open { display:block; }
.user-dropdown-header {
  padding:11px 16px;
  font-size:.78rem;
  color:var(--muted);
  border-bottom:1px solid var(--border);
}
.user-dropdown a {
  display:block;
  padding:10px 16px;
  font-size:.84rem;
  color:var(--text);
  text-decoration:none;
  transition:background .15s;
}
.user-dropdown a:hover { background:var(--bg); }
.topbar .tab {
  background:none;
  border:none;
  border-bottom:2px solid transparent;
  color:rgba(255,255,255,.6);
  font-family:inherit;
  font-size:.83rem;
  font-weight:500;
  padding:0 18px;
  cursor:pointer;
  text-decoration:none;
  transition:all .15s;
  white-space:nowrap;
  display:flex;
  align-items:center;
}
.topbar .tab:hover { color:#fff; border-bottom-color:rgba(255,255,255,.4); }
.topbar .tab.active { color:#fff; border-bottom-color:#fff; font-weight:600; }

.toggle-switch {
  width:34px;
  height:19px;
  background:#c5bdb4;
  border-radius:10px;
  position:relative;
  transition:background .2s;
  flex-shrink:0;
}
.toggle-switch::after {
  content:'';
  position:absolute;
  width:15px;
  height:15px;
  background:#fff;
  border-radius:50%;
  top:2px;
  left:2px;
  transition:transform .2s;
  box-shadow:0 1px 3px rgba(60,44,28,.15);
}
/* ----- Leaderboard widget ----- */
.leaderboard-widget {
  border:1px solid var(--border);
  border-radius:8px;
  background:var(--bg);
  margin-top:12px;
  margin-bottom:20px;
  padding:12px 14px;
}
.leaderboard-widget-title {
  font-size:.75rem;
  text-transform:uppercase;
  letter-spacing:.1em;
  color:#1f1f1f;
  font-weight:700;
  margin-bottom:12px;
}
.leaderboard-entry {
  display:flex;
  align-items:baseline;
  gap:8px;
  padding:5px 0;
  font-size:.84rem;
  color:var(--text-secondary);
}
.leaderboard-entry.you { color:var(--text); }
.leaderboard-entry:last-child { padding-bottom:0; }
.leaderboard-rank { min-width:18px; font-size:.75rem; color:var(--muted); flex-shrink:0; }
.leaderboard-name-col { flex:1; min-width:0; }
.leaderboard-name { font-weight:600; color:#1f1f1f; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; display:block; }
.leaderboard-entry.you .leaderboard-name { color:#1f1f1f; }
.leaderboard-right { text-align:right; flex-shrink:0; }
.leaderboard-xp {
  font-size:.82rem;
  font-weight:700;
  color:#1f1f1f;
  display:block;
  white-space:nowrap;
}
.leaderboard-level {
  font-size:.68rem;
  color:var(--muted);
  display:block;
  margin-top:1px;
  white-space:nowrap;
}

/* ----- Sidebar progress widget ----- */
.sidebar-progress {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg);
  margin-bottom: 20px;
  padding: 12px 14px;
}
.sidebar-progress-title {
  font-size: .75rem;
  text-transform: uppercase;
  letter-spacing: .1em;
  color: #1f1f1f;
  font-weight: 700;
  margin-bottom: 8px;
}
.sidebar-progress-level {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-bottom: 7px;
}
.sidebar-level-pill {
  font-size: .7rem;
  font-weight: 700;
  color: #fff;
  background: #2d2d2d;
  border-radius: 6px;
  padding: 2px 8px;
  white-space: nowrap;
}
.sidebar-level-name {
  font-size: .78rem;
  font-weight: 600;
  color: var(--text-secondary);
}
.sidebar-xp-bar-wrap {
  height: 5px;
  background: var(--border);
  border-radius: 99px;
  overflow: hidden;
  margin-bottom: 5px;
}
.sidebar-xp-bar-fill {
  height: 100%;
  background: #3a5c4a;
  border-radius: 99px;
  transition: width .4s ease;
}
.sidebar-xp-label {
  font-size: .72rem;
  color: var(--muted);
  margin-bottom: 8px;
}
.sidebar-streak-row {
  display: flex;
  justify-content: space-between;
  font-size: .75rem;
  color: var(--muted);
  border-top: 1px solid var(--border);
  padding-top: 7px;
  margin-top: 2px;
}
.sidebar-streak-today { font-weight: 600; color: var(--text-secondary); }

/* ----- Layout ----- */
.layout { display:flex; min-height:calc(100vh - 96px); }

/* ----- Sidebar ----- */
.sidebar {
  width:280px;
  min-width:280px;
  background:var(--surface);
  border-right:1px solid var(--border);
  padding:8px 16px 16px;
  overflow-y:auto;
  position:sticky;
  top:96px;
  height:calc(100vh - 96px);
}
.sidebar h3 {
  font-size:.75rem;
  text-transform:uppercase;
  letter-spacing:.1em;
  color:var(--muted);
  margin:20px 0 8px;
  font-weight:600;
}
.filter-group { display:flex; flex-direction:column; gap:3px; }
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
.filter-btn:hover { background:#e8e4dd; color:#1f1f1f; }
.filter-btn.active { background:#2d2d2d; color:#fff; }
.filter-btn.active .badge { color:rgba(255,255,255,.75); }
.filter-btn .badge { font-size:.75rem; color:var(--muted); min-width:24px; text-align:right; }

/* ----- Main ----- */
.main { flex:1; padding:16px 32px; }
.main .toolbar { display:flex; gap:12px; align-items:center; margin-bottom:12px; flex-wrap:wrap; }
.main .toolbar .active-filters { display:flex; gap:6px; flex-wrap:wrap; }
.chip {
  background:#2d2d2d;
  color:#fff;
  font-size:.75rem;
  font-weight:500;
  padding:4px 12px;
  border-radius:99px;
  display:flex;
  align-items:center;
  gap:6px;
  cursor:pointer;
  border:1px solid #2d2d2d;
  transition:background .15s;
}
.chip:hover { background:#2d2d2d; border-color:#2d2d2d; }
.chip .x { font-size:.6rem; opacity:.6; }
.clear-btn {
  font-family:inherit;
  font-size:.78rem;
  color:var(--muted);
  cursor:pointer;
  background:none;
  border:none;
  font-weight:500;
}
.clear-btn:hover { color:#1f1f1f; }

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
.qcard:hover { box-shadow:var(--shadow-md); border-color:#c5bdb4; }
.qcard-header {
  display:flex;
  align-items:center;
  padding:16px 20px;
  gap:12px;
  cursor:pointer;
  user-select:none;
}
.qcard-left { display:flex; align-items:center; flex:1; min-width:0; overflow:hidden; }
.qcard-header .qaos { font-weight:700; font-size:.88rem; color:#1f1f1f; white-space:nowrap; flex-shrink:0; }
.qcard-header .qmeta { font-size:.82rem; color:var(--text-secondary); white-space:nowrap; flex-shrink:0; font-weight:400; }
.qcard-header .qsection { font-size:.82rem; color:var(--muted); white-space:nowrap; flex-shrink:0; }
.qcard-header .toggle-icon { color:var(--muted); font-size:.8rem; transition:transform .2s; }
.qcard.open .toggle-icon { transform:rotate(90deg); }

.qcard-body-outer { display:none; }
.qcard.open .qcard-body-outer { display:block; }
.qcard-body { padding:8px 20px 24px; }

.qimages { display:flex; gap:16px; flex-wrap:wrap; }
.qimg-wrap { flex:1; min-width:280px; }
.qimg-wrap img {
  display:block;
  width:100%;
  border-radius:8px;
  border:1px solid var(--border);
  background:#fff;
}

.sol-hidden { display:none; }
.sol-wrap { margin-top:20px; }
.show-sol-btn {
  font-family:inherit;
  background:#2d2d2d;
  color:#fff;
  border:1px solid #2d2d2d;
  padding:8px 20px;
  border-radius:8px;
  cursor:pointer;
  font-size:.85rem;
  font-weight:500;
  transition:all .15s;
  align-self:flex-start;
}
.show-sol-btn:hover { background:#2d2d2d; border-color:#2d2d2d; }

/* ----- Load More ----- */
.load-more-wrap { display:flex; flex-direction:column; align-items:center; gap:8px; margin-top:28px; }
.load-more-btn {
  font-family:inherit;
  background:var(--surface);
  border:1px solid var(--border);
  color:var(--text-secondary);
  padding:10px 36px;
  border-radius:8px;
  cursor:pointer;
  font-size:.84rem;
  font-weight:500;
  transition:all .15s;
}
.load-more-btn:hover { border-color:#2d2d2d; color:#2d2d2d; }
.load-more-count { font-size:.78rem; color:var(--muted); }

/* ----- Mobile ----- */
.show-sidebar-btn {
  display:none;
  font-family:inherit;
  background:var(--surface);
  border:1px solid var(--border);
  color:#2d2d2d;
  padding:8px 16px;
  border-radius:8px;
  cursor:pointer;
  font-size:.85rem;
  font-weight:500;
}
.sidebar-backdrop {
  display:none;
  position:fixed;
  inset:96px 0 0 0;
  background:rgba(0,0,0,.35);
  z-index:98;
}
.sidebar-backdrop.visible { display:block; }
@media (max-width: 768px) {
  .topbar-top { padding:0 14px; height:46px; }
  .topbar-bottom { padding:0 8px; height:38px; }
  .topbar h1 { font-size:.88rem; }
  .topbar .tab { padding:0 12px; font-size:.76rem; }
  .layout { flex-direction:column; }
  .main { padding:16px; }
  .sidebar { display:none; }
  .show-sidebar-btn { display:block; }
  .sidebar.mobile-open {
    display:block;
    position:fixed;
    top:84px;
    left:0;
    width:280px;
    max-width:calc(100vw - 40px);
    z-index:99;
    height:calc(100vh - 84px);
    box-shadow:4px 0 24px rgba(60,44,28,.15);
  }
  .qcard-header { padding:14px 16px; gap:8px; }
  .qcard-header .marks { font-size:.75rem; }
  .qcard-body { padding:14px 14px 20px; }
  .qimages { flex-direction:column; }
  .qimg-wrap { min-width:0; width:100%; }
  .card-actions { flex-wrap:wrap; }
  .show-sol-btn { padding:10px 20px; }
  .save-btn { padding:10px 20px; }
}
@media (max-width: 480px) {
  .topbar h1 { display:none; }
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
  color:var(--muted);
  font-weight:600;
  padding:2px 6px;
  background:var(--bg);
  border-radius:4px;
}

/* ----- Flag controls ----- */
.flag-btn {
  font-family:inherit;
  font-size:.85rem;
  font-weight:500;
  color:#2d2d2d;
  background:#e8e4dd;
  border:1px solid #d0ccc4;
  padding:8px 20px;
  border-radius:8px;
  cursor:pointer;
  transition:all .15s;
  align-self:flex-start;
}
.flag-btn:hover, .flag-btn:active { background:#c53030; color:#fff; border-color:#c53030; }
.flag-btn.flagged { border-color:#c53030; color:#c53030; background:#fff0f0; cursor:default; }

/* ----- Save controls ----- */
.save-btn {
  font-family:inherit;
  background:#e8e4dd;
  color:#2d2d2d;
  border:1px solid #d0ccc4;
  font-size:.85rem;
  font-weight:500;
  padding:8px 20px;
  border-radius:8px;
  cursor:pointer;
  transition:all .15s;
  align-self:flex-start;
}
.save-btn:hover { background:#2d2d2d; color:#fff; }
.save-btn.saved { background:#2d2d2d; color:#fff; }

/* ----- Complete controls ----- */
.complete-btn {
  font-family:inherit;
  background:#e8e4dd;
  color:#2d2d2d;
  border:1px solid #d0ccc4;
  font-size:.85rem;
  font-weight:500;
  padding:8px 20px;
  border-radius:8px;
  cursor:pointer;
  transition:all .15s;
  align-self:flex-start;
}
.complete-btn:hover { background:#2d2d2d; color:#fff; border-color:#2d2d2d; }
.complete-btn.completed { background:#2d2d2d; color:#fff; border-color:#2d2d2d; }
.qcard.completed { background:#eaeeeb; border-color:#3a5c4a; }
.bookmark-icon { display:none; color:#1f1f1f; font-size:.85rem; flex-shrink:0; margin-left:6px; line-height:1; }
.qcard.saved .bookmark-icon { display:inline; }
.card-actions {
  display:flex;
  align-items:flex-start;
  justify-content:space-between;
  gap:8px;
  margin-top:20px;
  margin-bottom:0;
}
.card-actions-left { display:flex; gap:8px; align-items:flex-start; }

/* ----- Progress button ----- */
.progress-btn-topbar {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: rgba(255,255,255,.13);
  border: 1.5px solid rgba(255,255,255,.25);
  color: rgba(255,255,255,.85);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background .15s;
  user-select: none;
  padding: 0;
  line-height: 1;
}
.progress-btn-topbar:hover { background: rgba(255,255,255,.25); }
.progress-btn-topbar svg,
.achievements-btn-topbar svg,
.settings-icon-btn svg { width: 16px; height: 16px; stroke: currentColor; fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }

/* ----- Achievements button ----- */
.achievements-btn-topbar {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: rgba(255,255,255,.13);
  border: 1.5px solid rgba(255,255,255,.25);
  color: rgba(255,255,255,.85);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background .15s;
  user-select: none;
  padding: 0;
  line-height: 1;
  font-size: 15px;
}
.achievements-btn-topbar:hover { background: rgba(255,255,255,.25); }

/* ----- Achievements modal ----- */
#achievements-modal {
  display: none;
  position: fixed;
  inset: 0;
  z-index: 1000;
  align-items: flex-start;
  justify-content: center;
  padding-top: 80px;
}
#achievements-modal.open { display: flex; }
#achievements-modal-backdrop {
  position: absolute;
  inset: 0;
  background: rgba(0,0,0,.45);
}
#achievements-modal-box {
  position: relative;
  background: var(--surface);
  border-radius: 16px;
  box-shadow: 0 8px 40px rgba(60,44,28,.18);
  width: 100%;
  max-width: 560px;
  max-height: calc(100vh - 120px);
  overflow-y: auto;
  overscroll-behavior: none;
  padding: 28px 28px 24px;
}
#achievements-modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}
#achievements-modal-header h2 {
  font-size: 1.1rem;
  font-weight: 700;
  color: #1f1f1f;
}
.achievements-modal-close {
  background: none;
  border: none;
  font-size: 1.1rem;
  color: var(--muted);
  cursor: pointer;
  line-height: 1;
  padding: 4px;
}
.achievements-modal-close:hover { color: var(--text); }

/* Level hero card */
.ach-level-card {
  background: linear-gradient(135deg, #eaeeeb 0%, #dce8e3 100%);
  border: 1.5px solid #4d7a64;
  border-radius: 14px;
  padding: 20px 20px 16px;
  text-align: center;
  margin-bottom: 8px;
}
.ach-level-num {
  font-size: 2.2rem;
  font-weight: 800;
  color: #2d2d2d;
  line-height: 1;
  letter-spacing: -.03em;
}
.ach-level-name {
  font-size: 1.1rem;
  font-weight: 700;
  color: #2d2d2d;
  margin: 4px 0 14px;
}
.ach-xp-bar-wrap {
  height: 10px;
  background: rgba(0,0,0,.08);
  border-radius: 99px;
  overflow: hidden;
  margin-bottom: 8px;
}
.ach-xp-bar-fill {
  height: 100%;
  border-radius: 99px;
  background: #3a5c4a;
}
.ach-xp-label {
  font-size: .78rem;
  color: var(--muted);
}

/* Section wrapper */
.ach-section { margin-bottom: 24px; }
.ach-section-title {
  font-size: .72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .06em;
  color: var(--muted);
  margin-bottom: 10px;
}

/* Streak section */
.ach-streak-row { display: flex; gap: 12px; }
.ach-streak-stat {
  background: var(--bg);
  border-radius: 10px;
  padding: 12px 10px;
  flex: 1;
  text-align: center;
}
.ach-streak-val {
  font-size: 1.6rem;
  font-weight: 700;
  color: #1f1f1f;
  line-height: 1.1;
}
.ach-streak-lbl {
  font-size: .7rem;
  color: var(--muted);
  margin-top: 3px;
  line-height: 1.3;
}
.ach-streak-hint {
  font-size: .73rem;
  color: var(--muted);
  margin-top: 8px;
  line-height: 1.4;
}
.ach-qtype-row { display: flex; gap: 12px; }
.ach-qtype-stat {
  background: var(--bg);
  border-radius: 10px;
  padding: 12px 10px;
  flex: 1;
  text-align: center;
}
.ach-qtype-val {
  font-size: 1.6rem;
  font-weight: 700;
  color: #1f1f1f;
  line-height: 1.1;
}
.ach-qtype-lbl {
  font-size: .7rem;
  color: var(--muted);
  margin-top: 3px;
  line-height: 1.3;
}

/* Badge grid (questions + streaks) */
.badge-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
  margin-top: 4px;
}
.badge-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 5px;
  padding: 12px 8px 10px;
  border-radius: 12px;
  text-align: center;
  position: relative;
}
.badge-item.earned {
  background: #eaeeeb;
  border: 1.5px solid #4d7a64;
}
.badge-item.locked {
  background: #f2ede6;
  border: 1.5px solid #e5dfd7;
}
.badge-icon-wrap {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
}
.badge-icon { display: flex; align-items: center; justify-content: center; line-height: 1; }
.badge-icon svg { width: 28px; height: 28px; stroke: #2d2d2d; stroke-width: 2; fill: none; }
.badge-item.earned .badge-icon svg { stroke: #243d33; }
.badge-item.locked .badge-icon svg { opacity: .35; }
.badge-lock-pip {
  position: absolute;
  top: 7px;
  right: 7px;
  line-height: 1;
  color: #b5ada5;
}
.badge-name {
  font-size: .7rem;
  font-weight: 600;
  color: #2d2d2d;
  line-height: 1.25;
}
.badge-item.locked .badge-name { color: #a09890; }
.badge-desc {
  font-size: .62rem;
  color: var(--muted);
  line-height: 1.25;
}
.badge-item.locked .badge-desc { color: #b5ada5; }

/* AOS badge list */
.aos-badge-list { display: flex; flex-direction: column; gap: 8px; margin-top: 4px; }
.aos-badge-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  border-radius: 10px;
}
.aos-badge-row.earned { background: #eaeeeb; border: 1.5px solid #4d7a64; }
.aos-badge-row.locked { background: #f2ede6; border: 1.5px solid #e5dfd7; }
.aos-badge-row-icon { flex-shrink: 0; display: flex; align-items: center; }
.aos-badge-row-icon svg { width: 18px; height: 18px; stroke: #243d33; stroke-width: 2; fill: none; }
.aos-badge-row.locked .aos-badge-row-icon svg { opacity: .35; stroke: #2d2d2d; }
.aos-badge-row-text { flex: 1; }
.aos-badge-row-name { font-size: .82rem; font-weight: 600; color: #2d2d2d; }
.aos-badge-row.locked .aos-badge-row-name { color: #a09890; }
.aos-badge-row-desc { font-size: .72rem; color: var(--muted); }
.aos-badge-row.locked .aos-badge-row-desc { color: #b5ada5; }
.aos-badge-row-lock { font-size: .75rem; color: #c5bdb4; flex-shrink: 0; }

/* ----- XP gain card ----- */
@keyframes xp-card-in {
  0%   { opacity: 0; transform: translateY(-14px) scale(.91); }
  65%  { opacity: 1; transform: translateY(3px) scale(1.02); }
  100% { opacity: 1; transform: translateY(0) scale(1); }
}
@keyframes xp-card-out {
  to { opacity: 0; transform: translateY(-8px) scale(.95); }
}
#xp-card {
  position: fixed;
  top: 108px;
  right: 20px;
  z-index: 9999;
  pointer-events: none;
  opacity: 0;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: 0 4px 16px rgba(60,44,28,.13);
  padding: 11px 16px 13px;
  min-width: 190px;
  max-width: 230px;
}
#xp-card.card-in  { animation: xp-card-in  .35s cubic-bezier(.22,1,.36,1) forwards; }
#xp-card.card-out { animation: xp-card-out .5s ease-in forwards; }
.xp-card-gain {
  font-size: .82rem;
  font-weight: 700;
  color: #3a5c4a;
  letter-spacing: .03em;
  margin-bottom: 7px;
}
.xp-card-label {
  font-size: .7rem;
  color: var(--muted);
  margin-bottom: 4px;
  display: flex;
  justify-content: space-between;
}
.xp-card-bar-wrap {
  height: 5px;
  background: var(--border);
  border-radius: 99px;
  overflow: hidden;
}
.xp-card-bar-fill {
  height: 100%;
  background: #3a5c4a;
  border-radius: 99px;
  width: 0%;
  transition: width .6s cubic-bezier(.22,1,.36,1);
}

/* ----- Celebration toasts ----- */
@keyframes toast-in {
  0%   { opacity: 0; transform: translateX(-50%) translateY(-16px) scale(.92); }
  60%  { transform: translateX(-50%) translateY(3px) scale(1.01); }
  100% { opacity: 1; transform: translateX(-50%) translateY(0) scale(1); }
}
#celebration-toast {
  position: fixed;
  top: 108px;
  left: 50%;
  transform: translateX(-50%) translateY(-16px) scale(.92);
  border-radius: 16px;
  padding: 18px 24px 14px;
  z-index: 10000;
  cursor: pointer;
  opacity: 0;
  pointer-events: none;
  min-width: 270px;
  max-width: 380px;
  text-align: center;
}
#celebration-toast.visible {
  pointer-events: auto;
  animation: toast-in .38s cubic-bezier(.22,1,.36,1) forwards;
}
#celebration-toast.toast-levelup {
  background: #2d2d2d;
  box-shadow: 0 4px 24px rgba(60,44,28,.18);
}
#celebration-toast.toast-levelup.visible {
  animation: toast-in .38s cubic-bezier(.22,1,.36,1) forwards;
}
#celebration-toast.toast-badge {
  background: var(--surface);
  box-shadow: 0 8px 36px rgba(60,44,28,.14);
}
#celebration-toast.toast-streak {
  background: var(--surface);
  box-shadow: 0 4px 16px rgba(60,44,28,.12);
  padding: 10px 20px;
  border-radius: 12px;
  min-width: 0;
}
#celebration-toast.toast-streak #celebration-content {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  font-size: .88rem;
  font-weight: 600;
  color: #1c1917;
}
.celebration-levelup-eyebrow {
  font-size: .68rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .1em;
  color: rgba(255,255,255,.55);
  margin-bottom: 8px;
}
.celebration-levelup-num {
  font-size: .85rem;
  font-weight: 600;
  color: rgba(255,255,255,.5);
  margin-bottom: 2px;
}
.celebration-levelup-name {
  font-size: 1.5rem;
  font-weight: 800;
  color: #fff;
  margin-bottom: 2px;
}
.celebration-divider {
  border: none;
  border-top: 1px solid rgba(255,255,255,.25);
  margin: 12px 0 10px;
}
.celebration-badge-row {
  display: flex;
  align-items: center;
  gap: 10px;
  text-align: left;
  padding: 3px 0;
}
.celebration-badge-icon { flex-shrink: 0; display: flex; align-items: center; }
.celebration-badge-icon svg { width: 22px; height: 22px; stroke: #2d2d2d; stroke-width: 2; fill: none; }
.toast-levelup .celebration-badge-icon svg { stroke: #fff; }
.celebration-badge-info { flex: 1; }
.celebration-badge-label {
  font-size: .65rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .06em;
  color: #2d2d2d;
}
.celebration-badge-name { font-size: .88rem; font-weight: 600; color: #1f1f1f; }
.celebration-dismiss-levelup {
  font-size: .68rem;
  color: rgba(255,255,255,.55);
  margin-top: 10px;
}
.celebration-dismiss-badge {
  font-size: .68rem;
  color: #b5ada5;
  margin-top: 10px;
}

/* ----- Progress modal ----- */
#progress-modal {
  display: none;
  position: fixed;
  inset: 0;
  z-index: 1000;
  align-items: flex-start;
  justify-content: center;
  padding-top: 80px;
  overflow: hidden;
  overscroll-behavior: none;
}
#progress-modal.open { display: flex; }
#progress-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,.4);
  z-index: -1;
}
#progress-modal-box {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(60,44,28,.18);
  width: min(680px, calc(100vw - 32px));
  max-height: calc(100vh - 120px);
  overflow-y: auto;
  overscroll-behavior: none;
  padding: 28px 28px 24px;
}
#progress-modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
}
#progress-modal-header h2 {
  font-size: 1rem;
  font-weight: 700;
  color: var(--text);
  margin: 0;
}
.progress-modal-close {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--muted);
  font-size: 1.2rem;
  line-height: 1;
  padding: 4px 6px;
  border-radius: 6px;
  transition: color .15s;
}
.progress-modal-close:hover { color: var(--text); }
.progress-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px 20px;
  margin-bottom: 12px;
}
.progress-card-title {
  font-size: .85rem;
  font-weight: 700;
  color: var(--text);
  margin-bottom: 10px;
}
.progress-bar-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 4px;
}
.progress-bar-label {
  font-size: .76rem;
  color: var(--text-secondary);
  white-space: nowrap;
  min-width: 130px;
}
.progress-bar-track {
  flex: 1;
  height: 9px;
  background: var(--border);
  border-radius: 99px;
  overflow: hidden;
}
.progress-bar-fill {
  height: 100%;
  background: #3a5c4a;
  border-radius: 99px;
  transition: width .4s ease;
}
.progress-bar-count {
  font-size: .76rem;
  color: var(--muted);
  white-space: nowrap;
  min-width: 48px;
  text-align: right;
}
.progress-sub-bars {
  margin-top: 10px;
  padding-left: 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  border-left: 2px solid var(--border);
}
.progress-bar-track.sub { height: 5px; }
.progress-bar-fill.sub { opacity: 0.6; }
.progress-bar-label.sub { font-size: .71rem; color: var(--muted); min-width: 130px; }
.progress-bar-count.sub { font-size: .71rem; }

</style>
</head>
<body class="{{ subject }}">

<div class="topbar">
  <div class="topbar-top">
    <a class="back-link" href="/">← Subjects</a>
    <h1>{{ subject_name }}</h1>
    <div class="topbar-right">
      <button class="achievements-btn-topbar" onclick="openAchievementsModal()" title="Achievements" aria-label="Achievements">
        <i data-lucide="trophy"></i>
      </button>
      <button class="progress-btn-topbar" onclick="openProgressModal()" title="View Progress" aria-label="View Progress">
        <i data-lucide="bar-chart-2"></i>
      </button>
      <div class="settings-wrap" id="settings-btn">
        <button class="settings-icon-btn" onclick="toggleSettingsDropdown()" aria-label="View settings">
          <i data-lucide="sliders-horizontal"></i>
        </button>
        <div class="settings-dropdown" id="settings-dropdown">
          <div class="settings-dropdown-title">View Options</div>
          <div class="settings-toggle" id="hide-completed-btn" onclick="event.stopPropagation(); toggleHideCompleted()">
            <span>Hide Completed</span>
            <div class="toggle-switch"></div>
          </div>
          <div class="settings-toggle" id="hide-saved-btn" onclick="event.stopPropagation(); toggleHideSaved()">
            <span>Hide Saved</span>
            <div class="toggle-switch"></div>
          </div>

        </div>
      </div>
      <div class="user-avatar-wrap" id="user-avatar-btn" onclick="toggleUserDropdown()">
        <div class="user-avatar" id="user-avatar-initials"></div>
        <div class="user-dropdown" id="user-dropdown">
          <div class="user-dropdown-header">Signed in as {{ user_name }}</div>
          <a href="/logout">Sign out</a>
        </div>
      </div>
    </div>
  </div>
  <div class="topbar-bottom">
    <button class="tab active" id="tab-questions" onclick="showAllQuestions()">Questions</button>
    <button class="tab" id="tab-saved" onclick="toggleSavedFilter()">Saved</button>
    <button class="tab" id="tab-completed" onclick="toggleCompletedFilter()">Completed</button>
    {% if is_admin %}<a class="tab" href="/admin?subject={{ subject }}">Admin</a>{% endif %}
  </div>
</div>

<div class="layout">
  <div class="sidebar" id="sidebar">
    {% if show_leaderboard %}
    <div class="leaderboard-widget">
      <div class="leaderboard-widget-title" id="leaderboard-title">Leaderboard</div>
      {% if is_admin %}
      <select id="leaderboard-picker" style="font-family:inherit;font-size:.75rem;padding:4px 6px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);width:100%;margin-bottom:8px;" onchange="loadLeaderboard(this.value)">
        <option value="">— pick a leaderboard —</option>
      </select>
      {% endif %}
      <div id="leaderboard-entries"><span style="font-size:.8rem;color:var(--muted)">{% if is_admin %}Select a leaderboard above{% else %}Loading…{% endif %}</span></div>
    </div>
    {% endif %}
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
    <div class="load-more-wrap" id="load-more-wrap"></div>
  </div>
</div>

<script>
const IS_ADMIN = {{ is_admin|tojson }};
const IS_METHODS = {{ is_methods|tojson }};
const AOS_MAP = {{ aos_map | tojson }};
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
let filters = { aos: new Set(), tag: new Set(), extended: new Set(), year: new Set(), publisher: new Set(), exam_type: new Set(), section: new Set() };
let savedIds = new Set();
let savedOnly = false;
let completedIds = new Set();
let completedOnly = false;
let hideCompleted = localStorage.getItem('hideCompleted') === 'true';
let hideSaved = localStorage.getItem('hideSaved') === 'true';
const funnyPopup = {{ funny_popup | tojson }};
{% if show_leaderboard %}
{% if is_admin %}
fetch('/api/admin/leaderboards')
  .then(r => r.json())
  .then(lbs => {
    const picker = document.getElementById('leaderboard-picker');
    if (!picker) return;
    lbs.forEach(lb => {
      const opt = document.createElement('option');
      opt.value = lb.id;
      opt.textContent = lb.name;
      picker.appendChild(opt);
    });
  });
{% endif %}
function loadLeaderboard(lbId, silent) {
  const el = document.getElementById('leaderboard-entries');
  if (!el) return;
  {% if is_admin %}
  if (!lbId) {
    el.innerHTML = '<span style="font-size:.8rem;color:var(--muted)">Select a leaderboard above</span>';
    document.getElementById('leaderboard-title').textContent = 'Leaderboard';
    return;
  }
  const url = '/api/leaderboard?subject={{ subject }}&leaderboard_id=' + lbId;
  {% else %}
  const url = '/api/leaderboard?subject={{ subject }}';
  {% endif %}
  if (!silent) el.innerHTML = '<span style="font-size:.8rem;color:var(--muted)">Loading…</span>';
  fetch(url)
    .then(r => r.json())
    .then(data => {
      const titleEl = document.getElementById('leaderboard-title');
      if (titleEl && data.leaderboard_name) titleEl.textContent = data.leaderboard_name;
      const entries = data.entries || [];
      if (!entries.length) {
        el.innerHTML = '<span style="font-size:.8rem;color:var(--muted)">No data yet</span>';
        return;
      }
      el.innerHTML = entries.map((entry, i) => {
        const firstName = entry.nickname || (entry.name ? entry.name.split(' ')[0] : entry.name);
        const xpStr = (entry.xp || 0).toLocaleString() + ' XP';
        return `<div class="leaderboard-entry${entry.is_you ? ' you' : ''}">` +
          `<span class="leaderboard-rank">${i + 1}.</span>` +
          `<div class="leaderboard-name-col"><span class="leaderboard-name">${firstName}</span></div>` +
          `<div class="leaderboard-right"><span class="leaderboard-xp">${xpStr}</span><span class="leaderboard-level">${entry.level_name}</span></div>` +
          `</div>`;
      }).join('');
    })
    .catch(() => { el.innerHTML = '<span style="font-size:.8rem;color:var(--muted)">—</span>'; });
}
{% if not is_admin %}loadLeaderboard();{% endif %}
function refreshLeaderboard() {
  {% if is_admin %}
  const picker = document.getElementById('leaderboard-picker');
  if (picker && picker.value) loadLeaderboard(picker.value, true);
  {% else %}
  loadLeaderboard(undefined, true);
  {% endif %}
}
{% endif %}

(function() {
  const name = {{ user_name | tojson }};
  const initials = name.split(' ').map(w => w[0]).filter(Boolean).join('').slice(0,2).toUpperCase();
  document.getElementById('user-avatar-initials').textContent = initials;
})();
function toggleUserDropdown() {
  document.getElementById('user-dropdown').classList.toggle('open');
  document.getElementById('settings-dropdown').classList.remove('open');
}
function toggleSettingsDropdown() {
  document.getElementById('settings-dropdown').classList.toggle('open');
  document.getElementById('user-dropdown').classList.remove('open');
}
document.addEventListener('click', e => {
  const avatarWrap = document.getElementById('user-avatar-btn');
  const settingsWrap = document.getElementById('settings-btn');
  if (avatarWrap && !avatarWrap.contains(e.target)) document.getElementById('user-dropdown').classList.remove('open');
  if (settingsWrap && !settingsWrap.contains(e.target)) document.getElementById('settings-dropdown').classList.remove('open');
});

const sectionLabels = { short_answer: 'Short Answer', multiple_choice: 'Multiple Choice', extended_response: 'Extended Response' };

// Methods tag colours: neutral charcoal
const METHODS_TAG_STYLES = {
  1: { bg:'#e8e4dd', color:'#1f1f1f' },
  2: { bg:'#e8e4dd', color:'#1f1f1f' },
  3: { bg:'#e8e4dd', color:'#1f1f1f' },
  4: { bg:'#e8e4dd', color:'#1f1f1f' },
  5: { bg:'#e8e4dd', color:'#1f1f1f' },
  6: { bg:'#e8e4dd', color:'#1f1f1f' },
  7: { bg:'#e8e4dd', color:'#1f1f1f' },
  8: { bg:'#e8e4dd', color:'#1f1f1f' },
  9: { bg:'#ede9e4', color:'#78716c' },
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
  loadCompletedIds();
  initSidebarGamification();
  document.getElementById('hide-completed-btn').classList.toggle('active', hideCompleted);
  document.getElementById('hide-saved-btn').classList.toggle('active', hideSaved);
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
  if (filters[key].has(value)) {
    filters[key].delete(value);
    btn.classList.remove('active');
  } else {
    filters[key].add(value);
    btn.classList.add('active');
  }
  page = 0;
  applyFilters();
}

function clearAll() {
  filters = { aos: new Set(), tag: new Set(), extended: new Set(), year: new Set(), publisher: new Set(), exam_type: new Set(), section: new Set() };
  document.querySelectorAll('.filter-btn.active').forEach(b => b.classList.remove('active'));
  page = 0;
  applyFilters();
}

function applyFilters() {
  page = 0;
  filtered = allQ.filter(q => {
    if (IS_METHODS) {
      // Tag filter applies to non-extended questions
      if (filters.tag.size > 0) {
        if (q.section === 'extended_response') return false;
        const names = q.tag_names || [q.aos_name];
        if (!names.some(n => filters.tag.has(n))) return false;
      }
      // Extended filter applies to extended response questions only
      if (filters.extended.size > 0) {
        if (q.section !== 'extended_response') return false;
        if (!filters.extended.has(q.aos_name)) return false;
      }
    } else {
      if (filters.aos.size > 0 && !filters.aos.has(q.aos_name)) return false;
    }
    if (filters.year.size > 0 && ![...filters.year].some(y => q.year === Number(y))) return false;
    if (filters.publisher.size > 0 && !filters.publisher.has(q.publisher)) return false;
    if (filters.exam_type.size > 0) {
      const examNums = [...filters.exam_type].map(e => e === 'Exam 1' ? 1 : 2);
      if (!examNums.includes(q.exam_type)) return false;
    }
    if (filters.section.size > 0) {
      const selectedSections = [...filters.section].map(s => { const sl = Object.entries(sectionLabels).find(([k,v]) => v===s); return sl ? sl[0] : null; }).filter(Boolean);
      if (!selectedSections.includes(q.section)) return false;
    }
    if (savedOnly && !savedIds.has(q.id)) return false;
    if (completedOnly && !completedIds.has(q.id)) return false;
    if (hideCompleted && !completedOnly && !savedOnly && completedIds.has(q.id)) return false;
    if (hideSaved && !savedOnly && !completedOnly && savedIds.has(q.id)) return false;
    return true;
  });

  renderActiveFilters();
  renderCards();
  renderLoadMore();
}

function renderActiveFilters() {
  const el = document.getElementById('active-filters');
  const clearBtn = document.getElementById('clear-btn');
  const chips = [];
  Object.entries(filters).forEach(([k, s]) => {
    s.forEach(v => chips.push(`<span class="chip" onclick="removeFilter('${k}', '${v}')">${v} <span class="x">&times;</span></span>`));
  });
  clearBtn.style.display = chips.length ? '' : 'none';
  el.innerHTML = chips.join('');
}

function removeFilter(key, value) {
  filters[key].delete(value);
  const groupMap = { aos:'fg-aos', tag:'fg-tag', extended:'fg-extended', year:'fg-year', publisher:'fg-pub', exam_type:'fg-exam', section:'fg-section' };
  document.querySelectorAll(`#${groupMap[key]} .filter-btn`).forEach(b => {
    if (b.querySelector('span').textContent === value) b.classList.remove('active');
  });
  page = 0;
  applyFilters();
}

function getAosText(q) {
  if (!IS_METHODS) return q.aos_name;
  if (q.section === 'extended_response') return q.aos_name;
  return (q.tag_names || [q.aos_name]).join(', ');
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

function buildCardHtml(q) {
  const aosText = getAosText(q);
  const sLabel = sectionLabels[q.section] || '';
  const solInner = q.solution_image
    ? `<div class="qimg-wrap"><img src="${q.solution_image}" loading="lazy"/></div>`
    : '<div class="qimg-wrap"><p style="color:var(--muted);font-size:.85rem">Not available</p></div>';
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
        <button class="complete-btn" id="complete-btn-${q.id}" onclick="toggleCompleted('${q.id}', this)">Mark as Done</button>
      </div>
      <button class="flag-btn" id="flag-btn-${q.id}" onclick="submitFlag('${q.id}', this)">⚑ Flag as misclassified</button>
    </div>` : solBtn;
  return `<div class="qcard" id="qcard-${q.id}" onclick="this.classList.toggle('open')">
    <div class="qcard-header">
      <div class="qcard-left">
        <span class="qaos">${aosText}</span>
        <span class="qmeta">&nbsp;·&nbsp;${sLabel}</span>
      </div>
      <span class="bookmark-icon">&#9733;</span>
      <span class="qsection">${q.publisher} ${q.year} · Q${q.question_number}</span>
      <span class="toggle-icon">&#9656;</span>
    </div>
    <div class="qcard-body-outer">
      <div class="qcard-body" onclick="event.stopPropagation()">
        <div class="qimg-wrap"><img src="${q.question_image}" loading="lazy"/></div>
        ${cardActions}
        <div class="sol-wrap sol-hidden">${solInner}</div>
        ${adminControls}
      </div>
    </div>
  </div>`;
}

function applyCardStates(questions) {
  questions.forEach(q => {
    if (savedIds.has(q.id)) {
      const btn = document.getElementById('save-btn-' + q.id);
      if (btn) markSaveBtn(btn, true);
    }
    if (completedIds.has(q.id)) {
      const btn = document.getElementById('complete-btn-' + q.id);
      if (btn) markCompleteBtn(btn, true);
      const card = document.getElementById('qcard-' + q.id);
      if (card) card.classList.add('completed');
    }
  });
}

function renderCards() {
  const grid = document.getElementById('qgrid');
  const countEl = document.getElementById('question-count');

  const visible = filtered.slice(0, (page + 1) * PER_PAGE);
  if (!visible.length) {
    if (savedOnly) {
      grid.innerHTML = '<div class="no-results"><p style="font-size:2rem;margin-bottom:12px">★</p><p>No saved questions yet</p><p style="font-size:.88rem;margin-top:6px">Hit <strong>Save</strong> on any question to find it here later</p></div>';
    } else if (completedOnly) {
      grid.innerHTML = '<div class="no-results"><p style="font-size:2rem;margin-bottom:12px">✓</p><p>No completed questions yet</p><p style="font-size:.88rem;margin-top:6px">Mark questions as done to track your progress</p></div>';
    } else {
      grid.innerHTML = '<div class="no-results"><p>No questions match your filters</p><button class="clear-btn" onclick="clearAll()">Clear all filters</button></div>';
    }
    return;
  }
  grid.innerHTML = visible.map(buildCardHtml).join('');
  applyCardStates(visible);
}

function renderLoadMore() {
  const el = document.getElementById('load-more-wrap');
  const shown = (page + 1) * PER_PAGE;
  if (shown >= filtered.length) { el.innerHTML = ''; return; }
  el.innerHTML = `<button class="load-more-btn" onclick="loadMore()">Load more</button><span class="load-more-count">${shown} of ${filtered.length} shown</span>`;
}

function loadMore() {
  const start = (page + 1) * PER_PAGE;
  page++;
  const newQ = filtered.slice(start, (page + 1) * PER_PAGE);
  const grid = document.getElementById('qgrid');
  const tmp = document.createElement('div');
  tmp.innerHTML = newQ.map(buildCardHtml).join('');
  while (tmp.firstChild) grid.appendChild(tmp.firstChild);
  applyCardStates(newQ);
  renderLoadMore();
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
        const aosEl = card.querySelector('.qaos');
        if (aosEl) {
          const updatedQ = allQ.find(q => q.id === id);
          if (updatedQ) aosEl.textContent = getAosText(updatedQ);
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
    if (hideSaved) { applyFilters(); return; }
    savedIds.forEach(id => {
      const btn = document.getElementById('save-btn-' + id);
      if (btn) markSaveBtn(btn, true);
    });
  });
}

function toggleSaved(id, btn) {
  const isUnsaving = savedIds.has(id);
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
    if (isUnsaving && !completedIds.has(id)) {
      showMarkCompletePrompt(id);
    } else {
      if (savedOnly || (hideSaved && !completedOnly && data.marked)) applyFilters();
    }
  });
}

function showMarkCompletePrompt(id) {
  const modal = document.getElementById('mark-complete-prompt');
  modal.dataset.questionId = id;
  modal.style.display = 'flex';
}

function markCompletePromptYes() {
  const modal = document.getElementById('mark-complete-prompt');
  const id = modal.dataset.questionId;
  modal.style.display = 'none';
  if (!completedIds.has(id)) {
    const btn = document.getElementById('complete-btn-' + id);
    fetch('/api/completed', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question_id: id, subject: '{{ subject }}' })
    }).then(r => r.json()).then(data => {
      if (data.marked) {
        completedIds.add(id);
        if (btn) markCompleteBtn(btn, true);
        const card = document.getElementById('qcard-' + id);
        if (card) card.classList.add('completed');
        if (funnyPopup === 'jacaranda_moses' && Math.random() < 0.2) showJacarandaModal();
        if (funnyPopup === 'levick' && Math.random() < 0.2) showLevickModal();
        if (funnyPopup === 'cordo' && Math.random() < 0.2) showCorodoModal();
        if (hideCompleted && !completedOnly && !savedOnly) applyFilters();
        else if (savedOnly || hideSaved) applyFilters();
      }
    });
  }
  if (savedOnly || hideSaved) applyFilters();
}

function markCompletePromptNo() {
  document.getElementById('mark-complete-prompt').style.display = 'none';
  if (savedOnly || hideSaved) applyFilters();
}

function showUnsavePrompt(id) {
  const modal = document.getElementById('unsave-prompt');
  modal.dataset.questionId = id;
  modal.style.display = 'flex';
}

function unsavePromptYes() {
  const modal = document.getElementById('unsave-prompt');
  const id = modal.dataset.questionId;
  modal.style.display = 'none';
  fetch('/api/saved', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question_id: id, subject: '{{ subject }}' })
  }).then(r => r.json()).then(data => {
    if (!data.marked) {
      savedIds.delete(id);
      const btn = document.getElementById('save-btn-' + id);
      if (btn) markSaveBtn(btn, false);
      if (savedOnly || hideSaved) applyFilters();
    }
  });
}

function unsavePromptNo() {
  document.getElementById('unsave-prompt').style.display = 'none';
}

function markSaveBtn(btn, saved) {
  btn.textContent = saved ? 'Saved' : 'Save';
  btn.classList.toggle('saved', saved);
  const card = btn.closest('.qcard');
  if (card) card.classList.toggle('saved', saved);
}

function showAllQuestions() {
  savedOnly = false;
  completedOnly = false;
  document.getElementById('tab-questions').classList.add('active');
  document.getElementById('tab-saved').classList.remove('active');
  document.getElementById('tab-completed').classList.remove('active');
  page = 0;
  applyFilters();
}

function toggleSavedFilter() {
  savedOnly = !savedOnly;
  completedOnly = false;
  document.getElementById('tab-saved').classList.toggle('active', savedOnly);
  document.getElementById('tab-completed').classList.toggle('active', false);
  document.getElementById('tab-questions').classList.toggle('active', !savedOnly);
  page = 0;
  applyFilters();
}

function loadCompletedIds() {
  fetch('/api/completed?subject={{ subject }}').then(r => r.json()).then(data => {
    completedIds = new Set(data.ids);
    if (hideCompleted) { applyFilters(); return; }
    completedIds.forEach(id => {
      const btn = document.getElementById('complete-btn-' + id);
      if (btn) markCompleteBtn(btn, true);
      const card = document.getElementById('qcard-' + id);
      if (card) card.classList.add('completed');
    });
  });
}

function toggleCompleted(id, btn) {
  fetch('/api/completed', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question_id: id, subject: '{{ subject }}' })
  }).then(r => r.json()).then(data => {
    if (data.marked) {
      completedIds.add(id);
    } else {
      completedIds.delete(id);
    }
    markCompleteBtn(btn, data.marked);
    const card = document.getElementById('qcard-' + id);
    if (card) card.classList.toggle('completed', data.marked);
    if (data.marked && savedIds.has(id)) {
      showUnsavePrompt(id);
    } else {
      if (completedOnly || (hideCompleted && !savedOnly && data.marked)) applyFilters();
    }
    if (data.marked && funnyPopup === 'jacaranda_moses' && Math.random() < 0.2) showJacarandaModal();
    if (data.marked && funnyPopup === 'levick' && Math.random() < 0.2) showLevickModal();
    if (data.marked && funnyPopup === 'cordo' && Math.random() < 0.2) showCorodoModal();
    if (data.marked) {
      showXpCard(data.xp_gained, data.new_xp, data.new_level_name, data.level_xp_min, data.next_level_xp, data.next_level_name);
      const leveledUp = data.new_level_num > data.prev_level_num;
      const newBadges = data.newly_earned_badges || [];
      if (leveledUp || newBadges.length > 0) {
        showCelebration(leveledUp, data.new_level_name, data.new_level_num, newBadges);
      } else if (data.new_streak) {
        showStreakToast(data.new_streak);
      }
      if (document.getElementById('achievements-modal').classList.contains('open')) {
        loadGamification();
      }
    }
    if (data.new_xp !== undefined) {
      fetch('/api/gamification?subject={{ subject }}').then(r => r.json()).then(g => {
        updateSidebarGamification(g.xp, g.level_num, g.level_name, g.level_xp_min, g.next_level_xp, g.next_level_name, g.today_count, g.current_streak);
      });
    }
    if (typeof refreshLeaderboard === 'function') refreshLeaderboard();
  });
}

function markCompleteBtn(btn, completed) {
  btn.textContent = completed ? 'Unmark as Done' : 'Mark as Done';
  btn.classList.toggle('completed', completed);
}

function toggleCompletedFilter() {
  completedOnly = !completedOnly;
  savedOnly = false;
  document.getElementById('tab-completed').classList.toggle('active', completedOnly);
  document.getElementById('tab-saved').classList.toggle('active', false);
  document.getElementById('tab-questions').classList.toggle('active', !completedOnly);
  page = 0;
  applyFilters();
}

function toggleHideCompleted() {
  hideCompleted = !hideCompleted;
  localStorage.setItem('hideCompleted', hideCompleted);
  document.getElementById('hide-completed-btn').classList.toggle('active', hideCompleted);
  page = 0;
  applyFilters();
}

function toggleHideSaved() {
  hideSaved = !hideSaved;
  localStorage.setItem('hideSaved', hideSaved);
  document.getElementById('hide-saved-btn').classList.toggle('active', hideSaved);
  page = 0;
  applyFilters();
}

function openProgressModal() {
  renderProgressView();
  document.getElementById('progress-modal').classList.add('open');
  document.addEventListener('keydown', progressModalKeyHandler);
}

function closeProgressModal() {
  document.getElementById('progress-modal').classList.remove('open');
  document.removeEventListener('keydown', progressModalKeyHandler);
}

function progressModalKeyHandler(e) {
  if (e.key === 'Escape') closeProgressModal();
}

// ---------------------------------------------------------------------------
// Celebration toast
// ---------------------------------------------------------------------------
const BADGE_ICONS = {
  q_1:    '<i data-lucide="footprints"></i>',
  q_10:   '<i data-lucide="target"></i>',
  q_50:   '<i data-lucide="key"></i>',
  q_100:  '<i data-lucide="award"></i>',
  q_250:  '<i data-lucide="zap"></i>',
  q_500:  '<i data-lucide="flame"></i>',
  q_1000: '<i data-lucide="gem"></i>',
  q_1500: '<i data-lucide="crown"></i>',
  s_7:    '<i data-lucide="calendar"></i>',
  s_30:   '<i data-lucide="calendar-days"></i>',
  s_100:  '<i data-lucide="medal"></i>',
};

let _popupTimer = null;

function hideAllPopups() {
  clearTimeout(_popupTimer);
  const card = document.getElementById('xp-card');
  const toast = document.getElementById('celebration-toast');
  // Pin opacity at 1 via inline style before removing animations,
  // otherwise the base opacity:0 snaps in before the transition fires
  card.classList.remove('card-in', 'card-out');
  toast.classList.remove('visible', 'toast-levelup', 'toast-badge', 'toast-streak');
  const d = document.getElementById('cel-dismiss');
  if (d) d.remove();
}

function _resetPopupTimer() {
  clearTimeout(_popupTimer);
  _popupTimer = setTimeout(hideAllPopups, 5000);
}

function showXpCard(xpGained, newXp, levelName, levelXpMin, nextLevelXp, nextLevelName) {
  if (!xpGained) return;
  const card = document.getElementById('xp-card');
  card.classList.remove('card-in', 'card-out');
  void card.offsetWidth;

  document.getElementById('xp-card-gain').textContent = '+' + xpGained + ' XP';
  const bar = document.getElementById('xp-card-bar');
  const xpLabel = document.getElementById('xp-card-xp');

  if (nextLevelXp) {
    const range = nextLevelXp - levelXpMin;
    const prevFill = Math.max(0, Math.min(100, ((newXp - xpGained - levelXpMin) / range) * 100));
    const newFill  = Math.max(0, Math.min(100, ((newXp - levelXpMin) / range) * 100));
    const remaining = nextLevelXp - newXp;
    xpLabel.textContent = remaining + ' XP to ' + nextLevelName;
    bar.style.transition = 'none';
    bar.style.width = prevFill + '%';
    requestAnimationFrame(() => requestAnimationFrame(() => {
      bar.style.transition = 'width .65s cubic-bezier(.22,1,.36,1)';
      bar.style.width = newFill + '%';
    }));
  } else {
    // Max level
    xpLabel.textContent = newXp + ' XP';
    bar.style.transition = 'none';
    bar.style.width = '100%';
  }

  card.classList.add('card-in');
  _resetPopupTimer();
}

const CELEBRATION_COLORS = [
  '#e63946','#ff6b6b','#e76f51',
  '#f4a261','#ff9f1c','#ffb703',
  '#ffd166','#f9c74f','#ffd700',
  '#3a5c4a','#2d5040','#5a8f78',
  '#ff6b9d','#e5989b','#ffb3c6',
  '#b5838d','#c9b1bd',
  '#ffffff','#fff8f0','#ffecd2',
];

function launchConfetti() {
  const colors = CELEBRATION_COLORS;
  const shared = {
    colors,
    zIndex: 9997,
    disableForReducedMotion: true,
    shapes: ['star', 'circle', 'square'],
    scalar: 1.3,
    ticks: 400,
    gravity: 0.75,
    decay: 0.93,
  };

  // Wave 1 — immediate: big centre top + both sides
  confetti({ ...shared, particleCount: 140, spread: 100, origin: { x: 0.5, y: 0.0 }, startVelocity: 68 });
  confetti({ ...shared, particleCount: 90, angle: 55, spread: 65, origin: { x: 0.0, y: 0.6 }, startVelocity: 68 });
  confetti({ ...shared, particleCount: 90, angle: 125, spread: 65, origin: { x: 1.0, y: 0.6 }, startVelocity: 68 });

  // Wave 2 — 280ms: inner cannons
  setTimeout(() => {
    confetti({ ...shared, particleCount: 90, angle: 68, spread: 58, origin: { x: 0.15, y: 0.42 }, startVelocity: 62 });
    confetti({ ...shared, particleCount: 90, angle: 112, spread: 58, origin: { x: 0.85, y: 0.42 }, startVelocity: 62 });
  }, 280);

  // Wave 3 — 560ms: second centre top blast
  setTimeout(() => {
    confetti({ ...shared, particleCount: 120, spread: 120, origin: { x: 0.5, y: 0.0 }, startVelocity: 62, scalar: 1.1 });
  }, 560);

  // Wave 4 — 850ms: wide sides again
  setTimeout(() => {
    confetti({ ...shared, particleCount: 70, angle: 60, spread: 55, origin: { x: 0.0, y: 0.5 }, startVelocity: 58 });
    confetti({ ...shared, particleCount: 70, angle: 120, spread: 55, origin: { x: 1.0, y: 0.5 }, startVelocity: 58 });
  }, 850);

  // Wave 5 — 1150ms: upper-left and upper-right finish
  setTimeout(() => {
    confetti({ ...shared, particleCount: 80, spread: 90, origin: { x: 0.25, y: 0.08 }, startVelocity: 55 });
    confetti({ ...shared, particleCount: 80, spread: 90, origin: { x: 0.75, y: 0.08 }, startVelocity: 55 });
  }, 1150);
}

function showStreakToast(streak) {
  const toast = document.getElementById('celebration-toast');
  toast.classList.remove('visible', 'toast-levelup', 'toast-badge', 'toast-streak');
  void toast.offsetWidth;
  document.getElementById('celebration-content').innerHTML =
    `<i data-lucide="zap" style="width:18px;height:18px;stroke:#1c1917;flex-shrink:0"></i><span>${streak} day streak!</span>`;
  lucide.createIcons();
  toast.classList.add('toast-streak', 'visible');
  clearTimeout(_popupTimer);
  _popupTimer = setTimeout(hideAllPopups, 2500);
}

function showCelebration(levelUp, newLevelName, newLevelNum, newBadges) {
  const toast = document.getElementById('celebration-toast');
  toast.classList.remove('visible', 'toast-levelup', 'toast-badge', 'toast-streak');
  void toast.offsetWidth;

  if (levelUp) {
    launchConfetti();
    const badgeSection = (newBadges && newBadges.length > 0) ? `
      <hr class="celebration-divider">
      ${newBadges.map(b => {
        const icon = b.id.startsWith('aos_') ? '<i data-lucide="circle-check"></i>' : (BADGE_ICONS[b.id] || '<i data-lucide="trophy"></i>');
        return `<div class="celebration-badge-row">
          <div class="celebration-badge-icon">${icon}</div>
          <div class="celebration-badge-info">
            <div class="celebration-badge-label" style="color:rgba(255,255,255,.7)">Achievement Unlocked</div>
            <div class="celebration-badge-name" style="color:#fff">${b.name}</div>
          </div>
        </div>`;
      }).join('')}` : '';
    document.getElementById('celebration-content').innerHTML = `
      <div class="celebration-levelup-eyebrow">Level Up</div>
      <div class="celebration-levelup-num">Level ${newLevelNum}</div>
      <div class="celebration-levelup-name">${newLevelName}</div>
      ${badgeSection}`;
    lucide.createIcons();
    document.getElementById('celebration-toast').insertAdjacentHTML('beforeend',
      '<div class="celebration-dismiss-levelup" id="cel-dismiss">Tap to dismiss</div>');
    toast.classList.add('toast-levelup', 'visible');
  } else if (newBadges && newBadges.length > 0) {
    document.getElementById('celebration-content').innerHTML =
      newBadges.map(b => {
        const icon = b.id.startsWith('aos_') ? '<i data-lucide="circle-check"></i>' : (BADGE_ICONS[b.id] || '<i data-lucide="trophy"></i>');
        return `<div class="celebration-badge-row">
          <div class="celebration-badge-icon">${icon}</div>
          <div class="celebration-badge-info">
            <div class="celebration-badge-label">Achievement Unlocked</div>
            <div class="celebration-badge-name">${b.name}</div>
          </div>
        </div>`;
      }).join('');
    lucide.createIcons();
    toast.classList.add('toast-badge', 'visible');
  }
  _resetPopupTimer();
}

// ---------------------------------------------------------------------------
// Achievements modal
// ---------------------------------------------------------------------------
let _gamificationData = null;

function openAchievementsModal() {
  document.getElementById('achievements-modal').classList.add('open');
  document.addEventListener('keydown', achievementsKeyHandler);
  loadGamification();
}

function closeAchievementsModal() {
  document.getElementById('achievements-modal').classList.remove('open');
  document.removeEventListener('keydown', achievementsKeyHandler);
}

function achievementsKeyHandler(e) {
  if (e.key === 'Escape') closeAchievementsModal();
}

function loadGamification() {
  fetch('/api/gamification?subject={{ subject }}')
    .then(r => r.json())
    .then(data => {
      _gamificationData = data;
      renderAchievements(data);
      updateSidebarGamification(data.xp, data.level_num, data.level_name, data.level_xp_min, data.next_level_xp, data.next_level_name, data.today_count, data.current_streak);
    });
}

function updateSidebarGamification(xp, levelNum, levelName, minXp, nextXp, nextName, todayCount, streak) {
  if (!document.getElementById('sp-level-pill')) return;
  document.getElementById('sp-level-name').textContent = levelName;
  let pct;
  if (nextXp === null || nextXp === undefined) {
    pct = 100;
    document.getElementById('sp-xp-label').textContent = xp.toLocaleString() + ' XP · Max level';
  } else {
    pct = Math.max(2, Math.round(((xp - minXp) / (nextXp - minXp)) * 100));
    document.getElementById('sp-xp-label').textContent = xp.toLocaleString() + ' / ' + nextXp.toLocaleString() + ' XP';
  }
  document.getElementById('sp-xp-bar').style.width = pct + '%';
  document.getElementById('sp-today').textContent = todayCount + ' done today';
  const spStreak = document.getElementById('sp-streak');
  if (streak > 0) {
    spStreak.textContent = streak + (streak === 1 ? ' day streak' : ' day streak');
  } else {
    spStreak.textContent = '';
  }
}

function initSidebarGamification() {
  fetch('/api/gamification?subject={{ subject }}')
    .then(r => r.json())
    .then(data => {
      updateSidebarGamification(data.xp, data.level_num, data.level_name, data.level_xp_min, data.next_level_xp, data.next_level_name, data.today_count, data.current_streak);
    });
}

function renderAchievements(data) {
  const earned = new Set(data.earned_badge_ids);

  function badgeHtml(badge, icon) {
    const isEarned = earned.has(badge.id);
    return `<div class="badge-item ${isEarned ? 'earned' : 'locked'}" title="${badge.desc}">
      ${!isEarned ? '<span class="badge-lock-pip"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg></span>' : ''}
      <div class="badge-icon-wrap">
        <span class="badge-icon">${icon}</span>
      </div>
      <div class="badge-name">${badge.name}</div>
      <div class="badge-desc">${badge.desc}</div>
    </div>`;
  }

  function aosBadgeHtml(badge) {
    const isEarned = earned.has(badge.id);
    return `<div class="aos-badge-row ${isEarned ? 'earned' : 'locked'}">
      <div class="aos-badge-row-icon"><i data-lucide="circle-check"></i></div>
      <div class="aos-badge-row-text">
        <div class="aos-badge-row-name">${badge.name}</div>
        <div class="aos-badge-row-desc">${badge.desc}</div>
      </div>
      ${!isEarned ? '<div class="aos-badge-row-lock"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg></div>' : ''}
    </div>`;
  }

  // Level hero card
  const xp = data.xp;
  const minXp = data.level_xp_min;
  const maxXp = data.next_level_xp;
  let barPct, xpLabel;
  if (maxXp === null) {
    barPct = 100;
    xpLabel = `${xp.toLocaleString()} XP · Max level reached`;
  } else {
    barPct = Math.max(2, Math.round(((xp - minXp) / (maxXp - minXp)) * 100));
    const remaining = (maxXp - xp).toLocaleString();
    xpLabel = `${xp.toLocaleString()} / ${maxXp.toLocaleString()} XP · ${remaining} to ${data.next_level_name}`;
  }

  const levelSection = `
    <div class="ach-section">
      <div class="ach-level-card">
        <div class="ach-level-num">Level ${data.level_num}</div>
        <div class="ach-level-name">${data.level_name}</div>
        <div class="ach-xp-bar-wrap"><div class="ach-xp-bar-fill" style="width:${barPct}%"></div></div>
        <div class="ach-xp-label">${xpLabel}</div>
      </div>
    </div>`;

  const mcDone   = allQ.filter(q => q.section === 'multiple_choice'   && completedIds.has(q.id)).length;
  const saDone   = allQ.filter(q => q.section === 'short_answer'      && completedIds.has(q.id)).length;
  const erDone   = allQ.filter(q => q.section === 'extended_response' && completedIds.has(q.id)).length;

  const questionsSection = `
    <div class="ach-section">
      <div class="ach-section-title">Questions Completed</div>
      <div class="ach-qtype-row">
        <div class="ach-qtype-stat">
          <div class="ach-qtype-val">${mcDone}</div>
          <div class="ach-qtype-lbl">Multiple Choice</div>
        </div>
        <div class="ach-qtype-stat">
          <div class="ach-qtype-val">${saDone}</div>
          <div class="ach-qtype-lbl">Short Answer</div>
        </div>
        <div class="ach-qtype-stat">
          <div class="ach-qtype-val">${erDone}</div>
          <div class="ach-qtype-lbl">Extended Response</div>
        </div>
      </div>
    </div>`;

  const streakSection = `
    <div class="ach-section">
      <div class="ach-section-title">Streak</div>
      <div class="ach-streak-row">
        <div class="ach-streak-stat">
          <div class="ach-streak-val">${data.current_streak} ${data.current_streak === 1 ? 'day' : 'days'}</div>
          <div class="ach-streak-lbl">Current streak</div>
        </div>
        <div class="ach-streak-stat">
          <div class="ach-streak-val">${data.longest_streak} ${data.longest_streak === 1 ? 'day' : 'days'}</div>
          <div class="ach-streak-lbl">Best streak</div>
        </div>
      </div>
      <div class="ach-streak-hint">Complete 5 questions per day to maintain your streak. Missing a day resets it to 0.</div>
    </div>`;

  const qBadgesHtml = data.question_badges.map(b => badgeHtml(b, BADGE_ICONS[b.id] || '🏆')).join('');
  const sBadgesHtml = data.streak_badges.map(b => badgeHtml(b, BADGE_ICONS[b.id] || '🔥')).join('');
  const aosBadgesHtml = data.aos_badges.map(b => aosBadgeHtml(b)).join('');

  const badgesSection = `
    <div class="ach-section">
      <div class="ach-section-title">Question Milestones</div>
      <div class="badge-grid">${qBadgesHtml}</div>
    </div>
    <div class="ach-section">
      <div class="ach-section-title">Streaks</div>
      <div class="badge-grid" style="grid-template-columns:repeat(3,1fr)">${sBadgesHtml}</div>
    </div>
    <div class="ach-section">
      <div class="ach-section-title">Areas of Study</div>
      <div class="aos-badge-list">${aosBadgesHtml}</div>
    </div>`;

  document.getElementById('achievements-content').innerHTML = levelSection + questionsSection + streakSection + badgesSection;
  lucide.createIcons();
}

function renderProgressView() {
  const hiddenAos = IS_METHODS ? new Set([0, 9]) : new Set([0, 8, 9]);
  const SECTION_KEYS = ['short_answer', 'multiple_choice', 'extended_response'];
  const SECTION_LABELS = { short_answer: 'Short Answer', multiple_choice: 'Multiple Choice', extended_response: 'Extended Response' };

  const stats = {};
  Object.keys(AOS_MAP).forEach(k => {
    const num = parseInt(k, 10);
    if (hiddenAos.has(num)) return;
    stats[num] = { total: 0, done: 0, name: AOS_MAP[k], sections: {} };
    SECTION_KEYS.forEach(sec => { stats[num].sections[sec] = { total: 0, done: 0 }; });
  });

  allQ.forEach(q => {
    const num = q.aos;
    if (!stats[num]) return;
    const completed = completedIds.has(q.id);
    stats[num].total += 1;
    if (completed) stats[num].done += 1;
    const sec = q.section;
    if (stats[num].sections[sec]) {
      stats[num].sections[sec].total += 1;
      if (completed) stats[num].sections[sec].done += 1;
    }
  });

  const container = document.getElementById('progress-cards');
  const sortedNums = Object.keys(stats).map(Number).sort((a, b) => a - b);

  container.innerHTML = sortedNums.map(num => {
    const s = stats[num];
    const mainPct = s.total === 0 ? 0 : Math.round((s.done / s.total) * 100);
    const subBarsHtml = SECTION_KEYS.map(sec => {
      const ss = s.sections[sec];
      if (ss.total === 0) return '';
      const pct = Math.round((ss.done / ss.total) * 100);
      return `<div class="progress-bar-row">
        <span class="progress-bar-label sub">${SECTION_LABELS[sec]}</span>
        <div class="progress-bar-track sub"><div class="progress-bar-fill sub" style="width:${pct}%"></div></div>
        <span class="progress-bar-count sub">${ss.done} / ${ss.total}</span>
      </div>`;
    }).join('');
    return `<div class="progress-card">
      <div class="progress-card-title">${s.name}</div>
      <div class="progress-bar-row">
        <span class="progress-bar-label">${mainPct}% complete</span>
        <div class="progress-bar-track"><div class="progress-bar-fill" style="width:${mainPct}%"></div></div>
        <span class="progress-bar-count">${s.done} / ${s.total}</span>
      </div>
      ${subBarsHtml ? `<div class="progress-sub-bars">${subBarsHtml}</div>` : ''}
    </div>`;
  }).join('');
}

</script>

<!-- Jacaranda motivational modal -->
<div id="mark-complete-prompt" style="display:none;position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,.5);align-items:center;justify-content:center;">
  <div style="background:#fdfaf6;border-radius:14px;padding:24px;max-width:340px;width:90%;text-align:center;box-shadow:0 16px 48px rgba(60,44,28,.25);">
    <p style="font-family:'DM Sans',system-ui,sans-serif;font-size:.95rem;font-weight:600;color:#1c1917;margin:0 0 6px;">Mark as done?</p>
    <p style="font-family:'DM Sans',system-ui,sans-serif;font-size:.83rem;color:#78716c;margin:0 0 20px;">Would you like to mark this question as completed?</p>
    <div style="display:flex;gap:10px;justify-content:center;">
      <button onclick="markCompletePromptYes()" style="background:#2d2d2d;color:#fff;border:none;border-radius:8px;padding:9px 22px;font-family:'DM Sans',system-ui,sans-serif;font-size:.85rem;font-weight:500;cursor:pointer;">Mark as Done</button>
      <button onclick="markCompletePromptNo()" style="background:#e8e4dd;color:#57534e;border:none;border-radius:8px;padding:9px 22px;font-family:'DM Sans',system-ui,sans-serif;font-size:.85rem;font-weight:500;cursor:pointer;">No thanks</button>
    </div>
  </div>
</div>
<div id="unsave-prompt" style="display:none;position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,.5);align-items:center;justify-content:center;">
  <div style="background:#fdfaf6;border-radius:14px;padding:24px;max-width:340px;width:90%;text-align:center;box-shadow:0 16px 48px rgba(60,44,28,.25);">
    <p style="font-family:'DM Sans',system-ui,sans-serif;font-size:.95rem;font-weight:600;color:#1c1917;margin:0 0 6px;">Unsave this question?</p>
    <p style="font-family:'DM Sans',system-ui,sans-serif;font-size:.83rem;color:#78716c;margin:0 0 20px;">You've marked this as done — would you like to remove it from your saved questions?</p>
    <div style="display:flex;gap:10px;justify-content:center;">
      <button onclick="unsavePromptYes()" style="background:#2d2d2d;color:#fff;border:none;border-radius:8px;padding:9px 22px;font-family:'DM Sans',system-ui,sans-serif;font-size:.85rem;font-weight:500;cursor:pointer;">Unsave</button>
      <button onclick="unsavePromptNo()" style="background:#e8e4dd;color:#57534e;border:none;border-radius:8px;padding:9px 22px;font-family:'DM Sans',system-ui,sans-serif;font-size:.85rem;font-weight:500;cursor:pointer;">Keep Saved</button>
    </div>
  </div>
</div>
<div id="jacaranda-modal" style="display:none;position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,.6);align-items:center;justify-content:center;">
  <div style="background:#fdfaf6;border-radius:16px;padding:28px 24px;max-width:420px;width:90%;text-align:center;box-shadow:0 20px 60px rgba(60,44,28,.3);">
    <img src="/static/jacaranda_moses.jpeg" alt="Motivation" style="width:100%;border-radius:10px;margin-bottom:18px;">
    <p style="font-family:'DM Sans',system-ui,sans-serif;font-size:.9rem;font-weight:500;color:#1c1917;line-height:1.6;margin-bottom:20px;">
      Be like a Jacaranda in exam season — bloom unexpectedly and confuse everyone, including yourself
    </p>
    <button onclick="document.getElementById('jacaranda-modal').style.display='none'" style="background:#2d2d2d;color:#fff;border:none;border-radius:8px;padding:10px 28px;font-family:'DM Sans',system-ui,sans-serif;font-size:.875rem;font-weight:500;cursor:pointer;">Got it</button>
  </div>
</div>
<!-- Cordo modal -->
<div id="cordo-modal" style="display:none;position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,.6);align-items:center;justify-content:center;">
  <div style="background:#fdfaf6;border-radius:16px;padding:28px 24px;max-width:420px;width:90%;text-align:center;box-shadow:0 20px 60px rgba(60,44,28,.3);">
    <img src="/static/cordo.jpeg" alt="Cordo" style="width:100%;border-radius:10px;margin-bottom:18px;">
    <p style="font-family:'DM Sans',system-ui,sans-serif;font-size:.9rem;font-weight:500;color:#1c1917;line-height:1.6;margin-bottom:20px;">
      Not Bad
    </p>
    <button onclick="document.getElementById('cordo-modal').style.display='none'" style="background:#2d2d2d;color:#fff;border:none;border-radius:8px;padding:10px 28px;font-family:'DM Sans',system-ui,sans-serif;font-size:.875rem;font-weight:500;cursor:pointer;">Thanks Cordo!</button>
  </div>
</div>
<!-- Mr Levick modal -->
<div id="levick-modal" style="display:none;position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,.6);align-items:center;justify-content:center;">
  <div style="background:#fdfaf6;border-radius:16px;padding:28px 24px;max-width:420px;width:90%;text-align:center;box-shadow:0 20px 60px rgba(60,44,28,.3);">
    <img src="/static/levick.jpeg" alt="Mr Levick" style="width:100%;border-radius:10px;margin-bottom:18px;">
    <p style="font-family:'DM Sans',system-ui,sans-serif;font-size:.9rem;font-weight:500;color:#1c1917;line-height:1.6;margin-bottom:20px;">
      He is watching...
    </p>
    <button onclick="document.getElementById('levick-modal').style.display='none'" style="background:#2d2d2d;color:#fff;border:none;border-radius:8px;padding:10px 28px;font-family:'DM Sans',system-ui,sans-serif;font-size:.875rem;font-weight:500;cursor:pointer;">Got it</button>
  </div>
</div>
<div id="xp-card">
  <div class="xp-card-gain" id="xp-card-gain"></div>
  <div class="xp-card-label">
    <span id="xp-card-xp"></span>
  </div>
  <div class="xp-card-bar-wrap"><div class="xp-card-bar-fill" id="xp-card-bar"></div></div>
</div>
<div id="celebration-toast" onclick="hideAllPopups()">
  <div id="celebration-content"></div>
</div>

<div id="achievements-modal" role="dialog" aria-modal="true" aria-labelledby="achievements-modal-title">
  <div id="achievements-modal-backdrop" onclick="closeAchievementsModal()"></div>
  <div id="achievements-modal-box">
    <div id="achievements-modal-header">
      <h2 id="achievements-modal-title">Achievements</h2>
      <button class="achievements-modal-close" onclick="closeAchievementsModal()" aria-label="Close">✕</button>
    </div>
    <div id="achievements-content"><span style="font-size:.85rem;color:var(--muted)">Loading…</span></div>
  </div>
</div>

<div id="progress-modal" role="dialog" aria-modal="true" aria-labelledby="progress-modal-title">
  <div id="progress-modal-backdrop" onclick="closeProgressModal()"></div>
  <div id="progress-modal-box">
    <div id="progress-modal-header">
      <h2 id="progress-modal-title">Your Progress — {{ subject_name }}</h2>
      <button class="progress-modal-close" onclick="closeProgressModal()" aria-label="Close">✕</button>
    </div>
    <div id="progress-cards"></div>
  </div>
</div>
<script>
function showJacarandaModal() {
  document.getElementById('jacaranda-modal').style.display = 'flex';
}
function showLevickModal() {
  document.getElementById('levick-modal').style.display = 'flex';
}
function showCorodoModal() {
  document.getElementById('cordo-modal').style.display = 'flex';
}
</script>
<script src="https://unpkg.com/lucide@latest/dist/umd/lucide.min.js"></script>
<script>lucide.createIcons();</script>
<script src="https://cdn.jsdelivr.net/npm/canvas-confetti@1.9.3/dist/confetti.browser.min.js"></script>
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
<link rel="icon" type="image/x-icon" href="/static/favicon.ico"/>
<link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32x32.png"/>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'DM Sans',system-ui,sans-serif; background:#0f1117; color:#e2e8f0; min-height:100vh; }

.topbar {
  background:#2d2d2d;
  padding:0 32px;
  display:flex;
  align-items:center;
  gap:20px;
  height:52px;
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
.qblock.classified { border-color:#2d2d2d; }
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
.aos-btn:hover { border-color:#aaa; color:#e2e8f0; }
.aos-btn.active {
  background:#2d2d2d;
  border-color:#2d2d2d;
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
.exam-nav-btn:hover { border-color:#aaa; color:#e2e8f0; }
.exam-nav-btn.current { background:#2d2d2d; border-color:#2d2d2d; color:#fff; }
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

// Fix Marks
async function saveMarks() {
  const rows = document.querySelectorAll('.fix-marks-row');
  const updates = [];
  rows.forEach(row => {
    const val = parseInt(row.querySelector('input').value);
    if (val > 0) updates.push({id: row.dataset.id, marks: val, subject: row.dataset.subject});
  });
  if (!updates.length) return;
  const res = await fetch('/api/fix_marks', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(updates)});
  const data = await res.json();
  if (data.ok) { alert('Saved ' + data.updated + ' marks.'); location.reload(); }
  else alert('Error: ' + data.error);
}
</script>

{% if missing_marks %}
<div style="max-width:700px;margin:40px auto;padding:24px;background:var(--surface,#fdfaf6);border:1px solid var(--border,#e3ddd4);border-radius:12px;">
  <h3 style="margin:0 0 16px;font-size:1rem;font-weight:600;color:#1c1917;">Fix Missing Marks</h3>
  <p style="margin:0 0 16px;font-size:.85rem;color:#57534e;">These non-MC questions have no marks stored. Enter the correct value from the exam paper.</p>
  {% for q in missing_marks %}
  <div class="fix-marks-row" data-id="{{ q.id }}" data-subject="{{ q.subject }}" style="margin-bottom:20px;border:1px solid var(--border,#e3ddd4);border-radius:8px;overflow:hidden;">
    <div style="display:flex;align-items:center;gap:12px;padding:10px 12px;background:#f6f3ee;">
      <span style="flex:1;font-size:.82rem;color:#1c1917;font-family:monospace;">{{ q.id }}</span>
      <span style="font-size:.8rem;color:#78716c;white-space:nowrap;">{{ q.section.replace('_',' ') }}</span>
      <input type="number" min="1" max="30" placeholder="marks" style="width:70px;padding:5px 8px;border:1px solid #e3ddd4;border-radius:6px;font-size:.85rem;text-align:center;">
    </div>
    {% if q.question_image %}
    <img src="{{ q.question_image }}" style="width:100%;display:block;background:#fff;">
    {% endif %}
  </div>
  {% endfor %}
  <button onclick="saveMarks()" style="margin-top:8px;padding:8px 20px;background:#2d2d2d;color:#fff;border:none;border-radius:8px;font-size:.85rem;cursor:pointer;">Save marks</button>
</div>
{% endif %}

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

def get_funny_popup(user):
    if not user:
        return ""
    with get_db() as conn:
        row = conn.execute("SELECT funny_popup FROM users WHERE google_id=?", (user["id"],)).fetchone()
        return str(row["funny_popup"] or "") if row else ""

def get_show_leaderboard(user):
    if DEV_MODE:
        return True
    if not user:
        return False
    if user.get("is_admin"):
        return True
    with get_db() as conn:
        row = conn.execute("SELECT leaderboard_id FROM users WHERE google_id=?", (user["id"],)).fetchone()
        return bool(row and row["leaderboard_id"] is not None)

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
                                  css_primary_light="#e6f2f2", css_primary_hover="#1a7a7b",
                                  funny_popup=get_funny_popup(user),
                                  show_leaderboard=get_show_leaderboard(user))

@app.route("/methods")
def browse_methods():
    r = check_approved()
    if r: return r
    user = current_user()
    cfg = get_subject_config("methods")
    return render_template_string(BROWSE_HTML, is_admin=admin_required(), user_name=user["name"] if user else "",
                                  subject="methods", subject_name="Mathematical Methods",
                                  aos_map=cfg["aos_map"], is_methods=True,
                                  css_primary="#1e40af", css_primary_dark="#1e3a5f",
                                  css_primary_light="#eff6ff", css_primary_hover="#1e3a8a",
                                  funny_popup=get_funny_popup(user),
                                  show_leaderboard=get_show_leaderboard(user))

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


@app.route("/api/fix_marks", methods=["POST"])
def api_fix_marks():
    if not admin_required():
        return jsonify(error="forbidden"), 403
    updates = request.get_json()  # [{id, marks, subject}, ...]
    if not updates:
        return jsonify(ok=True, updated=0)
    by_subject = {}
    for u in updates:
        by_subject.setdefault(u["subject"], []).append(u)
    updated = 0
    for subj, items in by_subject.items():
        cfg = get_subject_config(subj)
        with open(cfg["file"]) as f:
            data = json.load(f)
        id_map = {u["id"]: u["marks"] for u in items}
        for q in data:
            if q["id"] in id_map:
                q["marks"] = id_map[q["id"]]
                updated += 1
        with open(cfg["file"], "w") as f:
            json.dump(data, f, indent=2)
    return jsonify(ok=True, updated=updated)


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

    # Collect questions with missing marks across both subjects (for the fix-marks widget)
    missing_marks = []
    for subj, fname in [("specialist", "specialist_questions.json"), ("methods", "methods_questions.json")]:
        with open(fname) as f:
            all_qs = json.load(f)
        for q in all_qs:
            if q.get("section") != "multiple_choice" and (q.get("marks") or 0) == 0:
                missing_marks.append({"id": q["id"], "section": q["section"], "subject": subj, "question_image": q.get("question_image", "")})
    missing_marks.sort(key=lambda x: x["id"])

    return render_template_string(CLASSIFY_HTML, questions=questions, publisher=publisher, year=year,
                                  exam_sets=exam_sets, unsorted_mode=unsorted_mode, unsorted_count=unsorted_count,
                                  flagged_mode=flagged_mode, flagged_count=flagged_count, flags_by_qid=flags_by_qid,
                                  subject=subject, aos_map=aos_map, is_methods=is_methods,
                                  methods_aos_exam1=methods_aos_exam1, methods_aos_exam2=methods_aos_exam2,
                                  highlight_qid=highlight_qid, missing_marks=missing_marks)

@app.route("/qimg/<path:filename>")
def serve_qimg(filename):
    r = check_approved()
    if r: return r
    return send_from_directory(QIMG_DIR, filename)

# Keep upload functionality at /upload-page
UPLOAD_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>Upload</title><link rel="icon" type="image/x-icon" href="/static/favicon.ico"/><link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32x32.png"/>
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
<link rel="icon" type="image/x-icon" href="/static/favicon.ico"/>
<link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32x32.png"/>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'DM Sans',system-ui,sans-serif; background:#f6f3ee; color:#1c1917; min-height:100vh; }
.topbar {
  background:#2d2d2d;
  position:sticky; top:0; z-index:100;
  box-shadow:0 2px 8px rgba(60,44,28,.15);
}
.topbar-inner {
  display:grid;
  grid-template-columns:1fr auto 1fr;
  align-items:center;
  padding:0 28px;
  height:52px;
}
.topbar h1 { font-size:1.05rem; font-weight:600; color:#fff; letter-spacing:-.01em; text-align:center; white-space:nowrap; }
.user-avatar-wrap { position:relative; justify-self:end; }
.user-avatar {
  width:34px; height:34px; border-radius:50%;
  background:rgba(255,255,255,.18); border:1.5px solid rgba(255,255,255,.35);
  color:#fff; font-size:.78rem; font-weight:700;
  display:flex; align-items:center; justify-content:center;
  cursor:pointer; transition:background .15s; user-select:none;
}
.user-avatar:hover { background:rgba(255,255,255,.28); }
.user-dropdown {
  display:none; position:absolute; top:calc(100% + 10px); right:0;
  background:#fdfaf6; border:1px solid #e3ddd4; border-radius:10px;
  box-shadow:0 4px 12px rgba(60,44,28,.09); min-width:190px; z-index:200; overflow:hidden;
}
.user-dropdown.open { display:block; }
.user-dropdown-header { padding:11px 16px; font-size:.78rem; color:#78716c; border-bottom:1px solid #e3ddd4; }
.user-dropdown a { display:block; padding:10px 16px; font-size:.84rem; color:#1c1917; text-decoration:none; transition:background .15s; }
.user-dropdown a:hover { background:#f6f3ee; }
.main {
  display:flex; flex-direction:column; align-items:center; justify-content:center;
  min-height:calc(100vh - 56px); padding:40px 24px;
}
.label { font-size:.72rem; font-weight:600; letter-spacing:.1em; text-transform:uppercase; color:#57534e; margin-bottom:28px; }
.subject-grid { display:flex; gap:20px; flex-wrap:wrap; justify-content:center; }
.subject-card {
  background:#fdfaf6; border:1px solid #e3ddd4; border-radius:16px;
  padding:44px 36px 40px; width:280px; text-align:center; cursor:pointer;
  text-decoration:none; color:#1c1917;
  box-shadow:0 1px 3px rgba(60,44,28,.07);
  transition:box-shadow .2s, transform .2s, border-color .2s;
  display:block;
}
.subject-card:hover { border-color:#2d2d2d; box-shadow:0 6px 24px rgba(60,44,28,.12); transform:translateY(-3px); }
.subject-card .icon { font-size:2.2rem; margin-bottom:22px; color:#78716c; display:block; }
.subject-card h2 { font-size:1rem; font-weight:700; color:#1c1917; margin:0; white-space:nowrap; }
@media (max-width:640px) {
  .topbar-inner { padding:0 16px; }
  .subject-grid { flex-direction:column; align-items:center; width:100%; }
  .subject-card { width:100%; max-width:340px; padding:32px; }
  .subject-card h2 { white-space:normal; }
}
</style>
</head>
<body>
<div class="topbar">
  <div class="topbar-inner">
    <div></div>
    <h1>VCE Mathematics Question Bank</h1>
    <div class="user-avatar-wrap" id="user-avatar-btn" onclick="toggleUserDropdown()">
      <div class="user-avatar" id="user-avatar-initials"></div>
      <div class="user-dropdown" id="user-dropdown">
        <div class="user-dropdown-header">Signed in as {{ user_name }}</div>
        {% if is_admin %}<a href="/admin/users">User management</a>{% endif %}
        <a href="/logout">Sign out</a>
      </div>
    </div>
  </div>
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
<script>
(function() {
  const name = {{ user_name | tojson }};
  const initials = name.split(' ').map(w => w[0]).filter(Boolean).join('').slice(0,2).toUpperCase();
  document.getElementById('user-avatar-initials').textContent = initials;
})();
function toggleUserDropdown() {
  document.getElementById('user-dropdown').classList.toggle('open');
}
document.addEventListener('click', e => {
  const wrap = document.getElementById('user-avatar-btn');
  if (wrap && !wrap.contains(e.target)) document.getElementById('user-dropdown').classList.remove('open');
});
</script>
</body>
</html>"""

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Sign In — VCE Mathematics Question Bank</title>
<link rel="icon" type="image/x-icon" href="/static/favicon.ico"/>
<link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32x32.png"/>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'DM Sans',system-ui,sans-serif; background:#f6f3ee; min-height:100vh; display:flex; flex-direction:column; align-items:center; justify-content:center; }
.topbar-strip { background:#2d2d2d; width:100%; height:4px; position:fixed; top:0; left:0; }
.card { background:#fdfaf6; border:1px solid #e3ddd4; border-radius:12px; padding:40px 36px; width:100%; max-width:380px; text-align:center; box-shadow:0 1px 3px rgba(60,44,28,.07); }
h1 { color:#1c1917; font-size:1.1rem; font-weight:700; margin-bottom:8px; }
p { color:#78716c; font-size:.85rem; margin-bottom:28px; line-height:1.6; }
.google-btn {
  display:flex; align-items:center; justify-content:center; gap:12px;
  background:#fdfaf6; color:#1c1917; border:1px solid #e3ddd4; border-radius:8px;
  padding:12px 24px; width:100%; font-family:inherit; font-size:.9rem; font-weight:500;
  cursor:pointer; text-decoration:none; transition:border-color .15s, box-shadow .15s;
  box-shadow:0 1px 3px rgba(60,44,28,.07);
}
.google-btn:hover { border-color:#c5bdb4; box-shadow:0 2px 8px rgba(60,44,28,.1); }
.google-btn svg { width:20px; height:20px; flex-shrink:0; }
.msg { font-size:.82rem; margin-bottom:20px; padding:10px 14px; border-radius:8px; }
.msg.error { color:#c53030; background:#fff0f0; border:1px solid #e8c4c4; }
.msg.info { color:#78716c; background:#f0ede8; border:1px solid #e3ddd4; }
</style>
</head>
<body>
<div class="topbar-strip"></div>
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
<link rel="icon" type="image/x-icon" href="/static/favicon.ico"/>
<link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32x32.png"/>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'DM Sans',system-ui,sans-serif; background:#f6f3ee; min-height:100vh; display:flex; flex-direction:column; align-items:center; justify-content:center; }
.topbar-strip { background:#2d2d2d; width:100%; height:4px; position:fixed; top:0; left:0; }
.card { background:#fdfaf6; border:1px solid #e3ddd4; border-radius:12px; padding:48px 36px; width:100%; max-width:420px; text-align:center; box-shadow:0 1px 3px rgba(60,44,28,.07); }
.icon { font-size:2.4rem; margin-bottom:16px; }
h1 { color:#1c1917; font-size:1.1rem; font-weight:700; margin-bottom:10px; }
p { color:#78716c; font-size:.875rem; line-height:1.7; margin-bottom:28px; }
.email { color:#2d2d2d; font-weight:600; }
a { color:#78716c; font-size:.82rem; text-decoration:underline; }
a:hover { color:#1c1917; }
</style>
</head>
<body>
<div class="topbar-strip"></div>
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
<link rel="icon" type="image/x-icon" href="/static/favicon.ico"/>
<link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32x32.png"/>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root {
  --bg:#f6f3ee; --surface:#fdfaf6; --border:#e3ddd4; --text:#1c1917;
  --text-secondary:#57534e; --muted:#78716c; --accent-green:#3a5c4a; --red:#c53030;
  --shadow-sm:0 1px 3px rgba(60,44,28,.07); --shadow-md:0 4px 12px rgba(60,44,28,.09); --radius:12px;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'DM Sans',system-ui,sans-serif; background:var(--bg); color:var(--text); min-height:100vh; }
.topbar { background:#2d2d2d; padding:0 28px; display:grid; grid-template-columns:1fr auto 1fr; align-items:center; position:sticky; top:0; z-index:100; height:52px; box-shadow:0 2px 8px rgba(60,44,28,.15); }
.topbar h1 { font-size:1.05rem; font-weight:600; color:#fff; white-space:nowrap; text-align:center; }
.back-link { color:rgba(255,255,255,.65); font-size:.82rem; font-weight:500; text-decoration:none; white-space:nowrap; transition:color .15s; flex-shrink:0; }
.back-link:hover { color:#fff; }
.topbar-right { display:flex; justify-content:flex-end; }
.signout { color:rgba(255,255,255,.65); font-size:.78rem; text-decoration:none; padding:5px 12px; border:1px solid rgba(255,255,255,.2); border-radius:6px; white-space:nowrap; transition:all .15s; }
.signout:hover { color:#fff; background:rgba(255,255,255,.1); }
.container { max-width:820px; margin:0 auto; padding:40px 24px; }
.section { margin-bottom:44px; }
.section h2 { font-size:1.05rem; font-weight:600; margin-bottom:14px; color:var(--text); display:flex; align-items:center; gap:8px; }
.badge { font-size:.7rem; font-weight:600; padding:2px 9px; border-radius:99px; color:#fff; background:#555; }
.badge.green { background:var(--accent-green); }
.badge.red { background:var(--red); }
.user-card { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:14px 18px; display:flex; align-items:center; gap:14px; box-shadow:var(--shadow-sm); margin-bottom:8px; }
.info { flex:1; min-width:0; }
.uname { font-size:.9rem; font-weight:500; }
.uemail { font-size:.78rem; color:var(--muted); margin-top:2px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.udate { font-size:.75rem; color:var(--muted); white-space:nowrap; flex-shrink:0; }
.actions { display:flex; gap:8px; flex-shrink:0; }
.btn { padding:7px 16px; border-radius:8px; font-size:.8rem; font-weight:500; cursor:pointer; border:none; font-family:inherit; transition:all .15s; }
.btn-approve { background:#2d2d2d; color:#fff; }
.btn-approve:hover { background:#3d3d3d; }
.btn-reject { background:none; border:1px solid var(--border); color:var(--muted); }
.btn-reject:hover { border-color:var(--red); color:var(--red); }
.btn-revoke { background:none; border:1px solid var(--border); color:var(--muted); font-size:.75rem; padding:5px 12px; }
.btn-revoke:hover { border-color:var(--red); color:var(--red); }
.btn-gear { padding:5px 10px; border-radius:8px; border:1px solid var(--border); background:none; color:var(--muted); cursor:pointer; font-family:inherit; transition:all .15s; line-height:1; display:inline-flex; align-items:center; }
.btn-gear:hover { border-color:#2d2d2d; color:#1c1917; background:var(--bg); }
.btn-prog { padding:5px 10px; border-radius:8px; border:1px solid var(--border); background:none; color:var(--muted); cursor:pointer; font-family:inherit; transition:all .15s; line-height:1; display:inline-flex; align-items:center; }
.btn-prog:hover { border-color:#2d2d2d; color:#1c1917; background:var(--bg); }
/* Admin progress modal */
.prog-tabs { display:flex; gap:4px; margin-bottom:18px; }
.prog-tab { padding:6px 16px; border-radius:7px; border:1px solid var(--border); background:none; color:var(--muted); cursor:pointer; font-family:inherit; font-size:.82rem; font-weight:500; transition:all .15s; }
.prog-tab.active { background:#2d2d2d; color:#fff; border-color:#2d2d2d; }
.progress-card { background:var(--bg); border:1px solid var(--border); border-radius:10px; padding:16px 20px; margin-bottom:10px; }
.progress-card-title { font-size:.85rem; font-weight:700; color:var(--text); margin-bottom:10px; }
.progress-bar-row { display:flex; align-items:center; gap:12px; margin-bottom:4px; }
.progress-bar-label { font-size:.76rem; color:var(--text-secondary); white-space:nowrap; min-width:130px; }
.progress-bar-track { flex:1; height:9px; background:var(--border); border-radius:99px; overflow:hidden; }
.progress-bar-fill { height:100%; background:#3a5c4a; border-radius:99px; }
.progress-bar-count { font-size:.76rem; color:var(--muted); white-space:nowrap; min-width:48px; text-align:right; }
.progress-sub-bars { margin-top:10px; padding-left:14px; display:flex; flex-direction:column; gap:6px; border-left:2px solid var(--border); }
.progress-bar-track.sub { height:5px; }
.progress-bar-fill.sub { opacity:.6; }
.progress-bar-label.sub { font-size:.71rem; color:var(--muted); min-width:130px; }
.progress-bar-count.sub { font-size:.71rem; }
.empty { color:var(--muted); font-size:.85rem; padding:20px; text-align:center; background:var(--surface); border:1px solid var(--border); border-radius:10px; }
/* Leaderboard management section */
.lb-section { margin-bottom:44px; }
.lb-section h2 { font-size:1.05rem; font-weight:600; margin-bottom:14px; color:var(--text); display:flex; align-items:center; gap:8px; }
.lb-list { display:flex; flex-direction:column; gap:8px; margin-bottom:12px; }
.lb-row { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:12px 16px; display:flex; align-items:center; gap:10px; box-shadow:var(--shadow-sm); }
.lb-row-name { flex:1; font-size:.9rem; font-weight:500; }
.lb-row-name input { font-family:inherit; font-size:.9rem; font-weight:500; border:1px solid var(--border); border-radius:6px; padding:4px 8px; width:100%; }
.btn-lb-rename { font-size:.75rem; padding:5px 12px; border-radius:7px; border:1px solid var(--border); background:none; color:var(--muted); cursor:pointer; font-family:inherit; transition:all .15s; }
.btn-lb-rename:hover { border-color:#2d2d2d; color:#1c1917; }
.btn-lb-del { font-size:.75rem; padding:5px 12px; border-radius:7px; border:1px solid var(--border); background:none; color:var(--muted); cursor:pointer; font-family:inherit; transition:all .15s; }
.btn-lb-del:hover { border-color:var(--red); color:var(--red); }
.btn-add-lb { font-size:.82rem; padding:7px 16px; border-radius:8px; border:1px solid var(--text-secondary); background:none; color:var(--text-secondary); cursor:pointer; font-family:inherit; transition:all .15s; }
.btn-add-lb:hover { background:#2d2d2d; color:#fff; border-color:#2d2d2d; }
.lb-members { display:flex; flex-direction:column; gap:3px; margin-top:2px; padding-left:4px; }
.lb-member-chip { font-size:.8rem; color:var(--text-secondary); display:flex; align-items:center; gap:7px; }
.lb-member-chip::before { content:''; width:4px; height:4px; border-radius:50%; background:#c5bdb4; flex-shrink:0; }
/* Student settings modal */
.modal-backdrop { display:none; position:fixed; inset:0; background:rgba(0,0,0,.45); z-index:1000; align-items:center; justify-content:center; }
.modal-backdrop.open { display:flex; }
.modal { background:var(--surface); border-radius:14px; padding:28px 28px 22px; width:100%; max-width:400px; box-shadow:0 8px 32px rgba(60,44,28,.14); }
.modal h3 { font-size:1rem; font-weight:600; margin-bottom:20px; }
.modal-field { margin-bottom:16px; }
.modal-field label { display:block; font-size:.8rem; font-weight:500; color:var(--muted); margin-bottom:6px; }
.modal-select { font-family:inherit; font-size:.875rem; padding:8px 10px; border:1px solid var(--border); border-radius:8px; width:100%; background:var(--surface); color:var(--text); }
.modal-new-lb { margin-top:8px; display:none; flex-direction:column; gap:6px; }
.modal-new-lb input { font-family:inherit; font-size:.875rem; padding:8px 10px; border:1px solid var(--border); border-radius:8px; width:100%; }
.modal-new-lb.visible { display:flex; }
.modal-toggle-field { display:flex; align-items:center; justify-content:space-between; gap:12px; }
.modal-toggle-label { display:flex; flex-direction:column; gap:2px; }
.modal-toggle-title { font-size:.875rem; color:var(--text); font-weight:500; }
.modal-toggle-desc { font-size:.78rem; color:#a09890; }
.modal-toggle-switch { position:relative; display:inline-block; width:36px; height:20px; flex-shrink:0; cursor:pointer; }
.modal-toggle-switch input { opacity:0; width:0; height:0; }
.modal-toggle-knob { position:absolute; inset:0; background:#c5bdb4; border-radius:20px; transition:background .2s; }
.modal-toggle-knob::before { content:''; position:absolute; width:14px; height:14px; left:3px; top:3px; background:#fff; border-radius:50%; transition:transform .2s; }
.modal-toggle-switch input:checked + .modal-toggle-knob { background:#2d2d2d; }
.modal-toggle-switch input:checked + .modal-toggle-knob::before { transform:translateX(16px); }
.modal-actions { display:flex; gap:8px; margin-top:22px; justify-content:flex-end; }
.btn-modal-cancel { padding:8px 18px; border-radius:8px; border:1px solid var(--border); background:none; color:var(--muted); cursor:pointer; font-family:inherit; font-size:.85rem; }
.btn-modal-cancel:hover { border-color:#2d2d2d; color:#1c1917; }
.btn-modal-save { padding:8px 18px; border-radius:8px; border:none; background:#2d2d2d; color:#fff; cursor:pointer; font-family:inherit; font-size:.85rem; }
.btn-modal-save:hover { background:#3d3d3d; }
</style>
</head>
<body>
<div class="topbar">
  <a class="back-link" href="/">← Subjects</a>
  <h1>VCE Mathematics Question Bank</h1>
  <div class="topbar-right"><a class="signout" href="/logout">Sign out</a></div>
</div>
<div class="container">
  <div class="section">
    <h2>Pending Approval <span class="badge">{{ pending|length }}</span></h2>
    {% if pending %}
      {% for u in pending %}
      <div class="user-card" id="card-{{ u['google_id'] }}">
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
        <div class="info">
          <div class="uname">{{ u['name'] }}</div>
          <div class="uemail">{{ u['email'] }}</div>
        </div>
        <div class="actions">
          <button class="btn-prog"
            data-uid="{{ u['google_id'] }}"
            data-name="{{ u['name'] | e }}"
            onclick="openProgress(this)"
            title="View progress"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="12" width="4" height="9"/><rect x="10" y="6" width="4" height="15"/><rect x="17" y="2" width="4" height="19"/></svg></button>
          <button class="btn-gear"
            data-uid="{{ u['google_id'] }}"
            data-name="{{ u['name'] | e }}"
            data-lb="{{ u['leaderboard_id'] if u['leaderboard_id'] is not none else '' }}"
            data-popup="{{ u['funny_popup'] or '' }}"
            data-nickname="{{ u['nickname'] or '' }}"
            data-shabbat="{{ u['shabbat_proof'] or 0 }}"
            onclick="openSettings(this)"
            title="Student settings"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg></button>
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
  <!-- Leaderboard management -->
  <div class="lb-section">
    <h2>Leaderboards</h2>
    <div class="lb-list" id="lb-list">
      {% for lb in leaderboards %}
      <div class="lb-row" id="lb-row-{{ lb['id'] }}" style="flex-direction:column;align-items:stretch;gap:0;">
        <div style="display:flex;align-items:center;gap:10px;">
          <div class="lb-row-name" id="lb-name-{{ lb['id'] }}">{{ lb['name'] }}</div>
          <button class="btn-lb-rename" data-lb-id="{{ lb['id'] }}" data-lb-name="{{ lb['name'] | e }}" onclick="startRename(this)">Rename</button>
          <button class="btn-lb-del" onclick="deleteLeaderboard({{ lb['id'] }})">Delete</button>
        </div>
        {% if lb['members'] %}
        <div class="lb-members" id="lb-members-{{ lb['id'] }}">
          {% for m in lb['members'] %}
          <div class="lb-member-chip" data-uid="{{ m['google_id'] }}">{{ m['nickname'] or m['name'] }}</div>
          {% endfor %}
        </div>
        {% else %}
        <div class="lb-members" id="lb-members-{{ lb['id'] }}"></div>
        {% endif %}
      </div>
      {% endfor %}
    </div>
    <button class="btn-add-lb" onclick="addLeaderboard()">＋ Add Leaderboard</button>
  </div>
</div>

<!-- Student progress modal -->
<div class="modal-backdrop" id="prog-modal" onclick="if(event.target===this)closeProgress()">
  <div class="modal" style="max-width:560px;max-height:80vh;display:flex;flex-direction:column;">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;flex-shrink:0;">
      <h3 id="prog-modal-title">Progress</h3>
      <button class="btn-modal-cancel" style="padding:4px 10px;font-size:1rem;" onclick="closeProgress()">✕</button>
    </div>
    <div class="prog-tabs" style="flex-shrink:0;">
      <button class="prog-tab active" id="prog-tab-specialist" onclick="switchProgTab('specialist')">Specialist</button>
      <button class="prog-tab" id="prog-tab-methods" onclick="switchProgTab('methods')">Methods</button>
    </div>
    <div id="prog-content" style="overflow-y:auto;flex:1;">
      <span style="font-size:.85rem;color:var(--muted)">Loading…</span>
    </div>
  </div>
</div>

<!-- Student settings modal -->
<div class="modal-backdrop" id="settings-modal" onclick="if(event.target===this)closeSettings()">
  <div class="modal">
    <h3 id="modal-title">Student Settings</h3>
    <div class="modal-field">
      <label>Leaderboard</label>
      <select class="modal-select" id="modal-lb-select" onchange="onLbSelectChange()">
        <option value="">None</option>
        {% for lb in leaderboards %}
        <option value="{{ lb['id'] }}">{{ lb['name'] }}</option>
        {% endfor %}
        <option value="__new__">＋ Create new…</option>
      </select>
      <div class="modal-new-lb" id="modal-new-lb">
        <input type="text" id="modal-new-lb-name" placeholder="New leaderboard name…">
      </div>
    </div>
    <div class="modal-field">
      <label>Nickname <span style="font-weight:400;color:#a09890">(shown on leaderboard)</span></label>
      <input type="text" class="modal-select" id="modal-nickname" placeholder="Leave blank to use first name…" style="padding:8px 10px;">
    </div>
    <div class="modal-field">
      <label>Easter Egg</label>
      <select class="modal-select" id="modal-popup-select">
        <option value="">Off</option>
        <option value="jacaranda_moses">Jacaranda Moses</option>
        <option value="levick">Mr Levick</option>
        <option value="cordo">Cordo</option>
      </select>
    </div>
    <div class="modal-field modal-toggle-field">
      <div class="modal-toggle-label">
        <span class="modal-toggle-title">Shabbat Proof</span>
        <span class="modal-toggle-desc">Saturdays don't break or advance streak</span>
      </div>
      <label class="modal-toggle-switch">
        <input type="checkbox" id="modal-shabbat">
        <span class="modal-toggle-knob"></span>
      </label>
    </div>
    <div class="modal-actions">
      <button class="btn-modal-cancel" onclick="closeSettings()">Cancel</button>
      <button class="btn-modal-save" onclick="saveSettings()">Save</button>
    </div>
  </div>
</div>

<script>
const ALL_LEADERBOARDS = {{ leaderboards | tojson }};
let settingsUserId = null;
let settingsGearBtn = null;

function act(id, action) {
  fetch('/admin/users/' + id + '/' + action, {method:'POST'})
    .then(r => r.json()).then(d => { if (d.ok) location.reload(); });
}

function openSettings(btn) {
  settingsUserId = btn.dataset.uid;
  settingsGearBtn = btn;
  const lbId = btn.dataset.lb || '';
  const funnyPopup = btn.dataset.popup || '';
  const nickname = btn.dataset.nickname || '';
  document.getElementById('modal-title').textContent = btn.dataset.name;
  const lbSel = document.getElementById('modal-lb-select');
  lbSel.value = lbId !== '' ? String(lbId) : '';
  document.getElementById('modal-nickname').value = nickname;
  document.getElementById('modal-popup-select').value = funnyPopup;
  document.getElementById('modal-shabbat').checked = btn.dataset.shabbat === '1';
  document.getElementById('modal-new-lb').classList.remove('visible');
  document.getElementById('modal-new-lb-name').value = '';
  document.getElementById('settings-modal').classList.add('open');
}

function closeSettings() {
  document.getElementById('settings-modal').classList.remove('open');
  settingsUserId = null;
  settingsGearBtn = null;
}

function onLbSelectChange() {
  const val = document.getElementById('modal-lb-select').value;
  document.getElementById('modal-new-lb').classList.toggle('visible', val === '__new__');
}

async function saveSettings() {
  if (!settingsUserId) return;
  const lbSel = document.getElementById('modal-lb-select');
  const funnyPopup = document.getElementById('modal-popup-select').value;
  const nickname = document.getElementById('modal-nickname').value.trim();
  const shabbatProof = document.getElementById('modal-shabbat').checked;
  let lbId = lbSel.value === '' ? null : (lbSel.value === '__new__' ? null : parseInt(lbSel.value));

  if (lbSel.value === '__new__') {
    const newName = document.getElementById('modal-new-lb-name').value.trim();
    if (!newName) { alert('Enter a leaderboard name.'); return; }
    const r = await fetch('/api/admin/leaderboards', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: newName})
    });
    const d = await r.json();
    if (!d.ok) { alert(d.error || 'Error creating leaderboard'); return; }
    lbId = d.id;
  }

  const r = await fetch('/admin/users/' + settingsUserId + '/settings', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({leaderboard_id: lbId, funny_popup: funnyPopup, nickname, shabbat_proof: shabbatProof})
  });
  const d = await r.json();
  if (d.ok) {
    const oldLbId = settingsGearBtn ? settingsGearBtn.dataset.lb : '';
    if (settingsGearBtn) {
      settingsGearBtn.dataset.lb = lbId !== null ? String(lbId) : '';
      settingsGearBtn.dataset.popup = funnyPopup;
      settingsGearBtn.dataset.nickname = nickname;
      settingsGearBtn.dataset.shabbat = shabbatProof ? '1' : '0';
    }
    // Update member lists in the leaderboard section without a reload
    const uid = settingsUserId;
    const displayName = nickname || (settingsGearBtn ? settingsGearBtn.dataset.name : '');
    // Remove from old leaderboard list
    if (oldLbId) {
      const oldChip = document.querySelector(`#lb-members-${oldLbId} [data-uid="${uid}"]`);
      if (oldChip) oldChip.remove();
    }
    // Add to new leaderboard list
    if (lbId !== null) {
      const newList = document.getElementById('lb-members-' + lbId);
      if (newList && !newList.querySelector(`[data-uid="${uid}"]`)) {
        const chip = document.createElement('div');
        chip.className = 'lb-member-chip';
        chip.dataset.uid = uid;
        chip.textContent = displayName;
        newList.appendChild(chip);
      }
    }
    closeSettings();
    if (lbSel.value === '__new__') location.reload(); // reload to show new leaderboard in lists
  }
}

function addLeaderboard() {
  const name = prompt('New leaderboard name:');
  if (!name || !name.trim()) return;
  fetch('/api/admin/leaderboards', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name: name.trim()})
  }).then(r => r.json()).then(d => {
    if (d.ok) location.reload();
    else alert(d.error || 'Error');
  });
}

function startRename(btn) {
  const id = btn.dataset.lbId;
  const currentName = btn.dataset.lbName;
  const nameEl = document.getElementById('lb-name-' + id);
  const input = document.createElement('input');
  input.type = 'text';
  input.value = currentName;
  input.id = 'rename-input-' + id;
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') confirmRename(id, btn);
    if (e.key === 'Escape') cancelRename(id, currentName, btn);
  });
  nameEl.innerHTML = '';
  nameEl.appendChild(input);
  btn.textContent = 'Save';
  btn.onclick = () => confirmRename(id, btn);
  input.focus();
}

function cancelRename(id, oldName, btn) {
  document.getElementById('lb-name-' + id).textContent = oldName;
  btn.textContent = 'Rename';
  btn.dataset.lbName = oldName;
  btn.onclick = () => startRename(btn);
}

function confirmRename(id, btn) {
  const input = document.getElementById('rename-input-' + id);
  const name = input ? input.value.trim() : '';
  if (!name) return;
  fetch('/api/admin/leaderboards/' + id, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name})
  }).then(r => r.json()).then(d => {
    if (d.ok) location.reload();
    else alert(d.error || 'Error');
  });
}


function deleteLeaderboard(id) {
  if (!confirm('Delete this leaderboard? Students assigned to it will be moved to None.')) return;
  fetch('/api/admin/leaderboards/' + id, {method: 'DELETE'})
    .then(r => r.json()).then(d => {
      if (d.ok) location.reload();
      else alert(d.error || 'Error');
    });
}

let progData = null;
let progSubject = 'specialist';
const SECTION_LABELS = {short_answer: 'Short Answer', multiple_choice: 'Multiple Choice', extended_response: 'Extended Response'};
const SECTION_KEYS = ['short_answer', 'multiple_choice', 'extended_response'];

function openProgress(btn) {
  const uid = btn.dataset.uid;
  const name = btn.dataset.name;
  document.getElementById('prog-modal-title').textContent = name;
  document.getElementById('prog-content').innerHTML = '<span style="font-size:.85rem;color:var(--muted)">Loading…</span>';
  progData = null;
  progSubject = 'specialist';
  document.getElementById('prog-tab-specialist').classList.add('active');
  document.getElementById('prog-tab-methods').classList.remove('active');
  document.getElementById('prog-modal').classList.add('open');
  document.addEventListener('keydown', progKeyHandler);
  fetch('/api/admin/users/' + uid + '/progress')
    .then(r => r.json())
    .then(data => { progData = data; renderProgView(); })
    .catch(() => { document.getElementById('prog-content').innerHTML = '<span style="font-size:.85rem;color:var(--muted)">Error loading data</span>'; });
}

function closeProgress() {
  document.getElementById('prog-modal').classList.remove('open');
  document.removeEventListener('keydown', progKeyHandler);
}

function progKeyHandler(e) { if (e.key === 'Escape') closeProgress(); }

function switchProgTab(subject) {
  progSubject = subject;
  document.getElementById('prog-tab-specialist').classList.toggle('active', subject === 'specialist');
  document.getElementById('prog-tab-methods').classList.toggle('active', subject === 'methods');
  renderProgView();
}

function renderProgView() {
  const el = document.getElementById('prog-content');
  if (!progData) return;
  const subjectData = progData[progSubject];
  if (!subjectData) { el.innerHTML = '<span style="font-size:.85rem;color:var(--muted)">No data</span>'; return; }
  const byAos = subjectData.by_aos;
  const sortedAos = Object.keys(byAos).map(Number).sort((a, b) => a - b);
  if (!sortedAos.length) { el.innerHTML = '<span style="font-size:.85rem;color:var(--muted)">No questions found</span>'; return; }
  el.innerHTML = sortedAos.map(num => {
    const s = byAos[num];
    const mainPct = s.total === 0 ? 0 : Math.round((s.done / s.total) * 100);
    const subBarsHtml = SECTION_KEYS.map(sec => {
      const ss = s.sections[sec];
      if (!ss || ss.total === 0) return '';
      const pct = Math.round((ss.done / ss.total) * 100);
      return `<div class="progress-bar-row">
        <span class="progress-bar-label sub">${SECTION_LABELS[sec]}</span>
        <div class="progress-bar-track sub"><div class="progress-bar-fill sub" style="width:${pct}%"></div></div>
        <span class="progress-bar-count sub">${ss.done} / ${ss.total}</span>
      </div>`;
    }).join('');
    return `<div class="progress-card">
      <div class="progress-card-title">${s.name}</div>
      <div class="progress-bar-row">
        <span class="progress-bar-label">${mainPct}% complete</span>
        <div class="progress-bar-track"><div class="progress-bar-fill" style="width:${mainPct}%"></div></div>
        <span class="progress-bar-count">${s.done} / ${s.total}</span>
      </div>
      ${subBarsHtml ? `<div class="progress-sub-bars">${subBarsHtml}</div>` : ''}
    </div>`;
  }).join('');
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
<link rel="icon" type="image/x-icon" href="/static/favicon.ico"/>
<link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32x32.png"/>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #f6f3ee;
  --surface: #fdfaf6;
  --border: #e3ddd4;
  --text: #1c1917;
  --text-secondary: #57534e;
  --muted: #78716c;
  --primary: {{ css_primary }};
  --primary-dark: {{ css_primary_dark }};
  --primary-light: {{ css_primary_light }};
  --accent-green: #3a5c4a;
  --red: #c53030;
  --shadow-sm: 0 1px 3px rgba(60,44,28,.07);
  --shadow-md: 0 4px 12px rgba(60,44,28,.09);
  --radius: 12px;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'DM Sans',system-ui,sans-serif; background:var(--bg); color:var(--text); min-height:100vh; }
a { color:#1f1f1f; text-decoration:none; }

.topbar {
  background:#2d2d2d;
  position:sticky; top:0; z-index:100;
  box-shadow:0 2px 8px rgba(60,44,28,.15);
}
.topbar-top {
  display:grid;
  grid-template-columns:1fr auto 1fr;
  align-items:center;
  padding:0 28px;
  height:52px;
  border-bottom:1px solid rgba(255,255,255,.1);
}
.topbar-bottom {
  display:flex;
  align-items:stretch;
  justify-content:center;
  padding:0 20px;
  height:44px;
  gap:2px;
  background:#1f1f1f;
}
.back-link {
  color:rgba(255,255,255,.65); font-size:.82rem; font-weight:500;
  text-decoration:none; white-space:nowrap; transition:color .15s; flex-shrink:0;
}
.back-link:hover { color:#fff; }
.topbar h1 {
  font-size:1.05rem; font-weight:700; color:#fff;
  letter-spacing:-.01em; text-align:center; white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis;
}
.user-avatar-wrap { position:relative; justify-self:end; }
.user-avatar {
  width:34px; height:34px; border-radius:50%;
  background:rgba(255,255,255,.18); border:1.5px solid rgba(255,255,255,.35);
  color:#fff; font-size:.78rem; font-weight:700;
  display:flex; align-items:center; justify-content:center;
  cursor:pointer; transition:background .15s; user-select:none;
}
.user-avatar:hover { background:rgba(255,255,255,.28); }
.user-dropdown {
  display:none; position:absolute; top:calc(100% + 10px); right:0;
  background:var(--surface); border:1px solid var(--border); border-radius:10px;
  box-shadow:var(--shadow-md); min-width:190px; z-index:200; overflow:hidden;
}
.user-dropdown.open { display:block; }
.user-dropdown-header { padding:11px 16px; font-size:.78rem; color:var(--muted); border-bottom:1px solid var(--border); }
.user-dropdown a { display:block; padding:10px 16px; font-size:.84rem; color:var(--text); text-decoration:none; transition:background .15s; }
.user-dropdown a:hover { background:var(--bg); }
.topbar .tab {
  background:none; border:none; border-bottom:2px solid transparent;
  color:rgba(255,255,255,.6); font-family:inherit; font-size:.83rem; font-weight:500;
  padding:0 16px; cursor:pointer; text-decoration:none; transition:all .15s;
  white-space:nowrap; display:flex; align-items:center;
}
.topbar .tab:hover { color:#fff; border-bottom-color:rgba(255,255,255,.4); }
.topbar .tab.active { color:#fff; border-bottom-color:#fff; font-weight:600; }
@media (max-width: 768px) {
  .topbar-top { padding:0 14px; height:46px; }
  .topbar-bottom { padding:0 8px; height:38px; }
  .topbar h1 { font-size:.88rem; }
  .topbar .tab { padding:0 12px; font-size:.76rem; }
}
@media (max-width: 480px) {
  .topbar h1 { display:none; }
}

.container { max-width:700px; margin:0 auto; padding:40px 24px; }

.section { margin-bottom:40px; }
.section h2 { font-size:1.15rem; font-weight:600; margin-bottom:6px; color:#1f1f1f; }
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
#drop.over, #drop2.over { border-color:#2d2d2d; background:var(--bg); }
#drop svg, #drop2 svg { width:44px; height:44px; color:var(--muted); margin-bottom:10px; }
#drop p, #drop2 p { color:var(--muted); font-size:.9rem; }
#drop span, #drop2 span { color:#1f1f1f; text-decoration:underline; cursor:pointer; font-weight:500; }
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
.bar-bg { background:var(--border); border-radius:99px; height:6px; overflow:hidden; }
.bar { height:6px; border-radius:99px; width:0%; background:linear-gradient(90deg,#2d2d2d,var(--accent-green)); transition:width .15s; }
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
.flag-qid { font-weight:600; font-size:.9rem; color:#1f1f1f; }
.flag-tag {
  font-size:.72rem;
  font-weight:500;
  padding:3px 10px;
  border-radius:99px;
  background:#e8e4dd;
  color:#1f1f1f;
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
  background:#e8e4dd;
  color:#2d2d2d;
  border:1px solid #d0ccc4;
  text-decoration:none;
  transition:all .15s;
}
.flag-classify-link:hover { background:#2d2d2d; color:#fff; }
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
.hidden-tag { font-size:.72rem; color:var(--red); font-weight:600; background:rgba(197,48,48,.08); padding:2px 7px; border-radius:99px; }
.toggle { position:relative; display:inline-block; width:44px; height:24px; flex-shrink:0; }
.toggle input { opacity:0; width:0; height:0; }
.slider { position:absolute; cursor:pointer; top:0; left:0; right:0; bottom:0; background:#c5bdb4; border-radius:24px; transition:.2s; }
.slider:before { position:absolute; content:""; height:18px; width:18px; left:3px; bottom:3px; background:#fff; border-radius:50%; transition:.2s; }
input:checked + .slider { background:#2d2d2d; }
input:checked + .slider:before { transform:translateX(20px); }
</style>
</head>
<body>

<div class="topbar">
  <div class="topbar-top">
    <a class="back-link" href="/">← Subjects</a>
    <h1>{{ subject_name }}</h1>
    <div class="user-avatar-wrap" id="user-avatar-btn" onclick="toggleUserDropdown()">
      <div class="user-avatar" id="user-avatar-initials"></div>
      <div class="user-dropdown" id="user-dropdown">
        <div class="user-dropdown-header">Signed in as {{ user_name }}</div>
        <a href="/logout">Sign out</a>
      </div>
    </div>
  </div>
  <div class="topbar-bottom">
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
(function() {
  const name = {{ user_name | tojson }};
  const initials = name.split(' ').map(w => w[0]).filter(Boolean).join('').slice(0,2).toUpperCase();
  document.getElementById('user-avatar-initials').textContent = initials;
})();
function toggleUserDropdown() {
  document.getElementById('user-dropdown').classList.toggle('open');
}
document.addEventListener('click', e => {
  const wrap = document.getElementById('user-avatar-btn');
  if (wrap && !wrap.contains(e.target)) document.getElementById('user-dropdown').classList.remove('open');
});
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
    user = current_user()
    return render_template_string(ADMIN_HTML, publishers=publishers, hidden_publishers=hidden,
                                  subject=subject, subject_name=cfg["name"],
                                  css_primary=cp, css_primary_dark=cpd,
                                  css_primary_light=cpl, css_primary_hover=cph,
                                  aos_map=cfg["aos_map"],
                                  user_name=user["name"] if user else "")

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

@app.route("/api/completed")
def api_get_completed():
    user_id = get_current_user_id()
    subject = request.args.get("subject", "specialist")
    with get_db() as conn:
        rows = conn.execute(
            "SELECT question_id FROM completed_questions WHERE user_id=? AND subject=?",
            (user_id, subject)
        ).fetchall()
    return jsonify({"ids": [r["question_id"] for r in rows]})

@app.route("/api/completed", methods=["POST"])
def api_toggle_completed():
    user_id = get_current_user_id()
    data = request.get_json()
    question_id = data["question_id"]
    subject = data.get("subject", "specialist")
    xp_gained = 0
    new_streak = None
    newly_earned_badges = []
    prev_level_num = 1
    new_level_num = 1
    new_level_name = "Novice"
    new_xp = 0

    with get_db() as conn:
        existing = conn.execute(
            "SELECT 1 FROM completed_questions WHERE user_id=? AND question_id=? AND subject=?",
            (user_id, question_id, subject)
        ).fetchone()
        if existing:
            conn.execute(
                "DELETE FROM completed_questions WHERE user_id=? AND question_id=? AND subject=?",
                (user_id, question_id, subject)
            )
            marked = False
            xp_lost = get_xp_for_question(question_id)
            conn.execute("UPDATE users SET xp = MAX(0, xp - ?) WHERE google_id=?", (xp_lost, user_id))
        else:
            marked = True
            # Snapshot state BEFORE this completion so we can diff
            prev_row = conn.execute(
                "SELECT xp, longest_streak FROM users WHERE google_id=?", (user_id,)
            ).fetchone()
            prev_xp = prev_row["xp"] if prev_row else 0
            prev_longest = prev_row["longest_streak"] if prev_row else 0
            prev_level_num = get_level(prev_xp)[0]
            prev_total = conn.execute(
                "SELECT COUNT(*) FROM completed_questions WHERE user_id=?", (user_id,)
            ).fetchone()[0]
            prev_completed_subject = {r["question_id"] for r in conn.execute(
                "SELECT question_id FROM completed_questions WHERE user_id=? AND subject=?",
                (user_id, subject)
            ).fetchall()}
            prev_earned = compute_earned_badge_ids(prev_total, prev_longest, prev_completed_subject, subject)

            conn.execute(
                "INSERT INTO completed_questions (user_id, question_id, subject, completed_at) VALUES (?,?,?,?)",
                (user_id, question_id, subject, datetime.datetime.utcnow().isoformat())
            )

            xp_gained = get_xp_for_question(question_id)
            conn.execute("UPDATE users SET xp = xp + ? WHERE google_id=?", (xp_gained, user_id))
            # Streak logic
            today = today_aest()
            now_aest = datetime.datetime.now(AEST)
            today_weekday = now_aest.weekday()  # 5=Saturday, 6=Sunday
            shabbat_row = conn.execute("SELECT shabbat_proof FROM users WHERE google_id=?", (user_id,)).fetchone()
            shabbat_proof = bool(shabbat_row and shabbat_row["shabbat_proof"])
            today_count = conn.execute(
                    "SELECT COUNT(*) FROM completed_questions WHERE user_id=? AND date(completed_at, '+10 hours') = ?",
                    (user_id, today)
                ).fetchone()[0]
            user_row = conn.execute(
                "SELECT current_streak, longest_streak, last_streak_date FROM users WHERE google_id=?", (user_id,)
            ).fetchone()
            if user_row and today_count >= 5 and user_row["last_streak_date"] != today:
                last = user_row["last_streak_date"]
                if shabbat_proof and today_weekday == 6:
                    friday = (now_aest - datetime.timedelta(days=2)).strftime("%Y-%m-%d")
                    saturday = (now_aest - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
                    streak_continues = last in (friday, saturday)
                else:
                    streak_continues = last == yesterday_aest()
                streak = (user_row["current_streak"] + 1) if streak_continues else 1
                longest = max(user_row["longest_streak"] or 0, streak)
                conn.execute(
                    "UPDATE users SET current_streak=?, longest_streak=?, last_streak_date=? WHERE google_id=?",
                    (streak, longest, today, user_id)
                )
                new_streak = streak

        conn.commit()

        # Compute new state and diff for celebrations
        if marked:
            new_row = conn.execute("SELECT xp, longest_streak FROM users WHERE google_id=?", (user_id,)).fetchone()
            new_xp = new_row["xp"] if new_row else 0
            new_longest = new_row["longest_streak"] if new_row else 0
            new_level = get_level(new_xp)
            new_level_num = new_level[0]
            new_level_name = new_level[1]
            new_total = conn.execute(
                "SELECT COUNT(*) FROM completed_questions WHERE user_id=?", (user_id,)
            ).fetchone()[0]
            new_completed_subject = {r["question_id"] for r in conn.execute(
                "SELECT question_id FROM completed_questions WHERE user_id=? AND subject=?",
                (user_id, subject)
            ).fetchall()}
            new_earned = compute_earned_badge_ids(new_total, new_longest, new_completed_subject, subject)
            new_badge_ids = new_earned - prev_earned
            badge_map = {b["id"]: b for b in QUESTION_BADGES + STREAK_BADGES + get_aos_badges_for_subject(subject)}
            newly_earned_badges = [badge_map[bid] for bid in new_badge_ids if bid in badge_map]

    with get_db() as conn:
        today = today_aest()
        today_count = conn.execute(
            "SELECT COUNT(*) FROM completed_questions WHERE user_id=? AND date(completed_at, '+10 hours') = ?",
            (user_id, today)
        ).fetchone()[0]
        streak_row = conn.execute(
            "SELECT current_streak FROM users WHERE google_id=?", (user_id,)
        ).fetchone()
        current_streak = streak_row["current_streak"] if streak_row else 0

    new_level_obj = get_level(new_xp)
    next_level_obj = get_next_level(new_xp)
    return jsonify({
        "ok": True, "marked": marked,
        "xp_gained": xp_gained, "new_xp": new_xp,
        "prev_level_num": prev_level_num, "new_level_num": new_level_num, "new_level_name": new_level_name,
        "level_xp_min": new_level_obj[2],
        "next_level_xp": next_level_obj[2] if next_level_obj else None,
        "next_level_name": next_level_obj[1] if next_level_obj else None,
        "new_streak": new_streak, "current_streak": current_streak,
        "today_count": today_count,
        "newly_earned_badges": newly_earned_badges,
    })

@app.route("/api/gamification")
def api_gamification():
    r = check_approved()
    if r: return r
    user_id = get_current_user_id()
    subject = request.args.get("subject", "specialist")

    with get_db() as conn:
        user_row = conn.execute(
            "SELECT xp, current_streak, longest_streak FROM users WHERE google_id=?", (user_id,)
        ).fetchone()
        xp = user_row["xp"] if user_row else 0
        current_streak = user_row["current_streak"] if user_row else 0
        longest_streak = user_row["longest_streak"] if user_row else 0

        total_completed = conn.execute(
            "SELECT COUNT(*) FROM completed_questions WHERE user_id=?", (user_id,)
        ).fetchone()[0]

        completed_ids_subject = {r["question_id"] for r in conn.execute(
            "SELECT question_id FROM completed_questions WHERE user_id=? AND subject=?",
            (user_id, subject)
        ).fetchall()}

        today_count = conn.execute(
            "SELECT COUNT(*) FROM completed_questions WHERE user_id=? AND date(completed_at, '+10 hours') = ?",
            (user_id, today_aest())
        ).fetchone()[0]

    level = get_level(xp)
    next_lv = get_next_level(xp)
    earned = compute_earned_badge_ids(total_completed, longest_streak, completed_ids_subject, subject)

    return jsonify({
        "xp": xp,
        "level_num": level[0],
        "level_name": level[1],
        "level_xp_min": level[2],
        "next_level_num": next_lv[0] if next_lv else None,
        "next_level_name": next_lv[1] if next_lv else None,
        "next_level_xp": next_lv[2] if next_lv else None,
        "current_streak": current_streak,
        "longest_streak": longest_streak,
        "today_count": today_count,
        "total_completed": total_completed,
        "earned_badge_ids": list(earned),
        "question_badges": QUESTION_BADGES,
        "streak_badges": STREAK_BADGES,
        "aos_badges": get_aos_badges_for_subject(subject),
    })

@app.route("/api/leaderboard")
def api_leaderboard():
    r = check_approved()
    if r: return r
    subject = request.args.get("subject", "specialist")
    user_id = get_current_user_id()
    with get_db() as conn:
        if admin_required():
            lb_id = request.args.get("leaderboard_id", type=int)
        else:
            row = conn.execute("SELECT leaderboard_id FROM users WHERE google_id=?", (user_id,)).fetchone()
            if not row or row["leaderboard_id"] is None:
                return jsonify(error="forbidden"), 403
            lb_id = row["leaderboard_id"]
        if lb_id is None:
            return jsonify({"leaderboard_name": None, "entries": []})
        lb = conn.execute("SELECT name FROM leaderboards WHERE id=?", (lb_id,)).fetchone()
        lb_name = lb["name"] if lb else None
        rows = conn.execute("""
            SELECT u.name, u.nickname, u.google_id, u.xp
            FROM users u
            WHERE u.leaderboard_id = ?
            ORDER BY u.xp DESC
        """, (lb_id,)).fetchall()
    def entry_data(r):
        xp = r["xp"] or 0
        lv_num, lv_name, lv_min = get_level(xp)
        next_lv = get_next_level(xp)
        if next_lv:
            pct = int((xp - lv_min) / (next_lv[2] - lv_min) * 100)
            next_name = next_lv[1]
        else:
            pct = 100
            next_name = None
        return {"name": r["name"], "nickname": r["nickname"], "xp": xp,
                "level_num": lv_num, "level_name": lv_name,
                "level_pct": pct, "next_level_name": next_name,
                "is_you": r["google_id"] == user_id}
    entries = [entry_data(r) for r in rows]
    return jsonify({"leaderboard_name": lb_name, "entries": entries})

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
        lb_rows = conn.execute("SELECT * FROM leaderboards ORDER BY name").fetchall()
        leaderboards = []
        for lb in lb_rows:
            lb_dict = dict(lb)
            members = conn.execute(
                "SELECT google_id, name, nickname FROM users WHERE leaderboard_id=? AND status='approved' ORDER BY name",
                (lb_dict["id"],)
            ).fetchall()
            lb_dict["members"] = [dict(m) for m in members]
            leaderboards.append(lb_dict)
    return render_template_string(USERS_HTML, pending=pending, approved=approved, rejected=rejected, leaderboards=leaderboards)

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


@app.route("/admin/users/<google_id>/settings", methods=["POST"])
def admin_user_settings(google_id):
    if not admin_required():
        return jsonify(error="forbidden"), 403
    body = request.get_json()
    leaderboard_id = body.get("leaderboard_id")  # int or None
    funny_popup = body.get("funny_popup", "")
    nickname = body.get("nickname", "").strip()
    shabbat_proof = 1 if body.get("shabbat_proof") else 0
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET leaderboard_id=?, funny_popup=?, nickname=?, shabbat_proof=? WHERE google_id=?",
            (leaderboard_id, funny_popup, nickname or None, shabbat_proof, google_id)
        )
        conn.commit()
    return jsonify(ok=True)

@app.route("/api/admin/leaderboards", methods=["GET"])
def api_list_leaderboards():
    if not admin_required():
        return jsonify(error="forbidden"), 403
    with get_db() as conn:
        rows = conn.execute("SELECT id, name FROM leaderboards ORDER BY name").fetchall()
    return jsonify([{"id": r["id"], "name": r["name"]} for r in rows])

@app.route("/api/admin/leaderboards", methods=["POST"])
def api_create_leaderboard():
    if not admin_required():
        return jsonify(error="forbidden"), 403
    name = (request.get_json() or {}).get("name", "").strip()
    if not name:
        return jsonify(error="name required"), 400
    with get_db() as conn:
        try:
            conn.execute("INSERT INTO leaderboards (name) VALUES (?)", (name,))
            conn.commit()
            lb_id = conn.execute("SELECT id FROM leaderboards WHERE name=?", (name,)).fetchone()["id"]
        except Exception:
            return jsonify(error="name already exists"), 409
    return jsonify(ok=True, id=lb_id, name=name)

@app.route("/api/admin/leaderboards/<int:lb_id>", methods=["PUT"])
def api_rename_leaderboard(lb_id):
    if not admin_required():
        return jsonify(error="forbidden"), 403
    name = (request.get_json() or {}).get("name", "").strip()
    if not name:
        return jsonify(error="name required"), 400
    with get_db() as conn:
        try:
            conn.execute("UPDATE leaderboards SET name=? WHERE id=?", (name, lb_id))
            conn.commit()
        except Exception:
            return jsonify(error="name already exists"), 409
    return jsonify(ok=True, id=lb_id, name=name)


@app.route("/api/admin/leaderboards/<int:lb_id>", methods=["DELETE"])
def api_delete_leaderboard(lb_id):
    if not admin_required():
        return jsonify(error="forbidden"), 403
    with get_db() as conn:
        conn.execute("UPDATE users SET leaderboard_id=NULL WHERE leaderboard_id=?", (lb_id,))
        conn.execute("DELETE FROM leaderboards WHERE id=?", (lb_id,))
        conn.commit()
    return jsonify(ok=True)



@app.route("/api/admin/users/<google_id>/progress")
def api_admin_user_progress(google_id):
    if not admin_required():
        return jsonify(error="forbidden"), 403
    HIDDEN_AOS = {"specialist": {0, 8, 9}, "methods": {0, 9}}
    SECTION_KEYS = ["short_answer", "multiple_choice", "extended_response"]
    with get_db() as conn:
        completed = {}
        for subject in ("specialist", "methods"):
            rows = conn.execute(
                "SELECT question_id FROM completed_questions WHERE user_id=? AND subject=?",
                (google_id, subject)
            ).fetchall()
            completed[subject] = {r["question_id"] for r in rows}
    result = {}
    for subject in ("specialist", "methods"):
        cfg = get_subject_config(subject)
        data = apply_overrides(cfg["data"](), subject)
        hidden = HIDDEN_AOS[subject]
        aos_map = cfg["aos_map"]
        done_ids = completed[subject]
        by_aos = {}
        for q in data:
            aos = q.get("aos", 0)
            if aos in hidden:
                continue
            if aos not in by_aos:
                by_aos[aos] = {
                    "name": aos_map.get(aos, str(aos)),
                    "total": 0, "done": 0,
                    "sections": {k: {"total": 0, "done": 0} for k in SECTION_KEYS}
                }
            is_done = q["id"] in done_ids
            by_aos[aos]["total"] += 1
            if is_done:
                by_aos[aos]["done"] += 1
            sec = q.get("section", "")
            if sec in SECTION_KEYS:
                by_aos[aos]["sections"][sec]["total"] += 1
                if is_done:
                    by_aos[aos]["sections"][sec]["done"] += 1
        result[subject] = {"by_aos": by_aos}
    return jsonify(result)

if __name__ == "__main__":
    import sys
    debug = "--debug" in sys.argv
    app.run(host="0.0.0.0", port=8080, debug=debug)
