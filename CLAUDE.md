# VCE Mathematics Question Bank — Project Standards

## Project Overview
A web-based question bank for VCE Mathematics (Units 3 & 4), covering two subjects:
- **Specialist Mathematics** — at `/specialist`
- **Mathematical Methods** — at `/methods`

Students browse, filter, and practise questions sourced from multiple trial exam publishers.
Questions are classified into Areas of Study (AOS) per subject.

## Tech Stack
- **Backend:** Python / Flask (`server.py`), port 8080
- **Data:** `specialist_questions.json` (Specialist), `methods_questions.json` (Methods)
- **Images:** `question_images/` — PNG crops of each question and solution (not in git)
- **Pipeline:** `pipeline/` — docx → PDF → image crops → classification
- **Local dev:** `DEV_MODE=1 python3 server.py` (bypasses Google OAuth)
- **Production:** `https://ariel.tenenberg.com` (AWS EC2, Sydney)

## Multi-Subject Architecture

### Routes
| Route | Purpose |
|-------|---------|
| `/` | Subject selector landing page (requires login) |
| `/specialist` | Specialist Mathematics browse page |
| `/methods` | Mathematical Methods browse page |
| `/admin?subject=specialist\|methods` | Subject-specific admin (publishers, flags, uploads) |
| `/admin/users` | User approval — shared, linked from landing page only |
| `/classify?subject=specialist\|methods` | Admin classification tool |
| `/api/questions?subject=specialist\|methods` | Questions API |
| `/api/classify` | Classify a question — DEV_MODE writes base JSON, production writes `overrides.json` |
| `/api/classify/restore` | Unhide a question — removes override so it reverts to base JSON AOS |
| `/api/flag` | Flag a question (subject in POST body) |
| `GET /api/saved?subject=specialist\|methods` | Get current user's saved question IDs |
| `POST /api/saved` | Toggle a question saved/unsaved (subject in POST body) |
| `GET /api/completed?subject=specialist\|methods` | Get current user's completed question IDs |
| `POST /api/completed` | Toggle a question completed/uncompleted (subject in POST body) |

### Data & Config
- `specialist_questions.json` — Specialist questions
- `methods_questions.json` — Methods questions
- `raw_questions_methods.json` — Methods raw extracted text (in git — needed for classifier analysis)
- `raw_questions_specialist.json` — Specialist raw extracted text (gitignored — local only)
- `settings.json` — Per-subject publisher visibility (gitignored)
- `overrides.json` — Server-side AOS overrides (gitignored — see below)
- `get_subject_config(subject)` helper returns data, file path, AOS map, and subject name
- Colour themes: Specialist = teal (`#196061`, `#042f3a`), Methods = blue (`#2563eb`, `#1e3a5f`)
- `users.db` — SQLite database for user accounts, saved questions, and completed questions (server-only, not in git)

## Specialist Mathematics — Areas of Study (AOS)
| # | Name |
|---|------|
| 1 | Logic and Proof |
| 2 | Functions, Relations and Graphs |
| 3 | Complex Numbers |
| 4 | Calculus |
| 5 | Vectors, Lines and Planes |
| 6 | Probability and Statistics |
| 7 | Pseudocode |
| 8 | Mechanics (old study design only — hidden from students) |
| 9 | Hidden (admin-only — invisible to students) |
| 0 | Unsorted (flagged for manual review) |

## Mathematical Methods — Areas of Study (AOS)
| # | Name |
|---|------|
| 1 | Algebra and Functions |
| 2 | Differentiation |
| 3 | Integration |
| 4 | Discrete Probability |
| 5 | Continuous Probability |
| 6 | Core Content (Exam 2 only) |
| 7 | Probability and Statistics (Exam 2 only) |
| 8 | Pseudocode (Exam 1 only) |
| 9 | Hidden (admin-only — invisible to students) |
| 0 | Unsorted (flagged for manual review) |

## Specialist Publishers in the Dataset
Heffernan, Insight, Kilbaha, MAV, NEAP, QATs-Janison, Sequoia, TSSM
Years: 2016–2022 (old study design), 2023, 2024, 2025

## Methods Publishers in the Dataset
Imported batch by batch. All pipeline work is done locally.
Years imported so far: 2016–2025 (all years complete)

## Classification Approach
- Text is extracted from PDFs using PyMuPDF (text layer, not OCR)
- Classified via keyword/regex matching in `pipeline/03_classify.py`
- Methods classifier is in `classify_for_methods()` and `METHODS_*` keyword sets at the bottom of that file — do not touch the Specialist logic above it
- When confidence is low, mark as **Unsorted (aos=0)** — never guess
- Manual corrections are the ground truth used to improve the classifier
- Classifier improvements require a deliberate session: commit the sorted JSON, then show corrections to Claude to update keyword rules in `03_classify.py`

### Classifier Preservation Logic (Specialist)
- Any question with a non-zero AOS in the existing `specialist_questions.json` is preserved on re-classification — this includes both auto-classified and manually sorted questions
- The `MANUALLY_REVIEWED` set in `03_classify.py` is now redundant but kept for reference
- Only AOS 0 (Unsorted) questions are ever re-classified when the pipeline runs

### Known Classifier Issues (Methods)
- Normal distribution questions may not trigger Continuous Probability if they use unusual phrasing
- `Pr(` and `X ~ B(n,p)` notation needed for Discrete Probability detection
- "increasing/decreasing" needed for Differentiation detection

---

## Working Standards

### General
- Understand existing code before modifying it — always read first
- Don't build features the user hasn't asked for
- Don't add comments, docstrings, or error handling beyond what's needed
- Keep responses concise and direct
- **At the end of every session, update this file** with any relevant changes to architecture, routes, data files, AOS maps, publishers, UI standards, or workflow. Commit the updated CLAUDE.md to the repo.

### Decision Making
- When unsure about scope or approach, ask before acting
- Explain the plan before implementing significant changes

---

## Local Pipeline Workflow

### Workflow rules
- **Local only:** uploading new exam batches, sorting unsorted questions, classifier improvement sessions
- **Server only (on the go):** reclassify, hide, manage flagged questions, hide/show publishers, approve/reject users
- Server-side changes write to `overrides.json` (gitignored) and are never touched by `git pull` — completely safe to deploy local work at any time

### Per-batch workflow
1. Upload exam zip via `http://localhost:8080/admin?subject=specialist|methods` (with `DEV_MODE=1` server running)
   - Zip must contain folder structure: `2025/Publisher/Exam 1.pdf`, `Exam 1 Solutions.pdf`, etc.
   - This triggers the pipeline automatically
2. Visit `http://localhost:8080/classify?subject=specialist|methods&unsorted=1` and sort Unsorted questions
3. Restart local server to load new data: `kill $(lsof -ti:8080) && DEV_MODE=1 python3 server.py`
4. `git add specialist_questions.json && git commit -m "..." && git push` (or `methods_questions.json raw_questions_methods.json` for Methods)
5. scp new images to server (use `*_<year>_*` to catch all publishers for that year):
   ```bash
   scp -i "/Users/arieltenenberg/Desktop/Specialist Website/specialistquestionbankkey.pem" \
     question_images/*_2022_* ubuntu@3.27.217.188:~/newapp/question_images/
   ```
6. Deploy: SSH to server → `cd ~/newapp && git pull origin master && sudo systemctl restart webapp`

### DEV_MODE
- `DEV_MODE=1 python3 server.py` bypasses Google OAuth for all auth-protected routes
- Only use locally — never set on the server
- Kill any existing process first: `kill $(lsof -ti:8080)`
- To refresh local data (e.g. after a reset or git pull), always restart the server — Flask loads data files at startup, so stale data will show until restarted (note: the admin upload endpoint triggers a reload automatically, so a manual restart is not needed after uploading a new batch):
  ```bash
  kill $(lsof -ti:8080) && DEV_MODE=1 python3 server.py
  ```

### Pipeline scripts (run from project root)
```bash
python3 pipeline/01_convert_docx.py --subject methods      # DOCX → PDF (needs LibreOffice)
python3 pipeline/02_extract_and_crop.py --subject methods  # extract text + crop images
python3 pipeline/03_classify.py --subject methods          # classify → methods_questions.json
```
The admin upload UI triggers all three automatically.

### Important pipeline behaviour
- `03_classify.py` **merges** new questions with existing JSON — previous batches are never lost (applies to both specialist and methods)
- `raw_questions_methods.json` contains the current batch's extracted text and is committed to git so Claude can analyse it
- Do one publisher/year at a time; analyse classifier corrections after each batch
- **Classifier improvement workflow**: after manually sorting unsorted questions, ask Claude to analyse the corrections (via `git diff`) and update keyword rules in `03_classify.py`. Do NOT rerun the classifier — it's slow and unnecessary since questions are already manually fixed. Improvements apply to the next batch.
- **Reclassification commit workflow**: reclassify questions locally via the classify UI, then tell Claude "I have reclassified some questions locally". Claude will run `git diff` to review, commit, and push. Then pull and restart on the server.

### One-time local setup
```bash
brew install --cask libreoffice
pip install pymupdf Pillow
```

---

## Server-Side Overrides (`overrides.json`)

Quick reclassification and hiding can be done directly on the production server via the browse page admin bar. These changes are stored in `overrides.json` (gitignored, server-only) and applied on top of the base JSON at serve time.

### How it works
- **Hide button** — sets AOS 9 on a question; invisible to students immediately
- **Unhide button** — removes the override; question reverts to its original base JSON classification as if nothing happened
- **Reclassify dropdown** — sets any AOS; also writes to overrides on the server
- `git pull` (from local deploys) never touches `overrides.json` — server-side changes are permanent until explicitly changed again

### Two workflows, never conflict
| Workflow | Where | Storage | Survives deploy? |
|----------|-------|---------|-----------------|
| New exam import + batch sort | Local → commit → deploy | Base JSON (git) | Yes (it's the source) |
| Quick fix on existing question | Server browse page | `overrides.json` (gitignored) | Yes (untouched by git) |

### Overrides are the final word
Overrides always take priority over the base JSON. The only ways to change them are:
1. Use the browse page admin bar on the server
2. Ask Claude Code to edit `overrides.json` directly via SSH

### Periodic cleanup of Hidden questions
When asked, Claude Code will delete all AOS 9 questions from both base JSON files and clear them from `overrides.json`, then commit and deploy.

---

## Image Deployment
- `question_images/` is NOT in git (binary files)
- Images live on the server permanently; only new images need to be scp'd per batch
- Key file: `/Users/arieltenenberg/Desktop/Specialist Website/specialistquestionbankkey.pem`

---

## Server Details

| Detail | Value |
|--------|-------|
| **Provider** | AWS EC2 (ap-southeast-2 / Sydney) |
| **Instance** | Specialist Question Bank (i-027bc033117bae0c5) |
| **Public IP** | 3.27.217.188 |
| **Live URL** | https://ariel.tenenberg.com |
| **OS** | Ubuntu 22.04 |
| **Repo on server** | `~/newapp` |
| **Key pair** | `/Users/arieltenenberg/Desktop/Specialist Website/specialistquestionbankkey.pem` |

## Server Stack
- Python / Flask → Gunicorn (2 workers) → Nginx reverse proxy
- Process manager: systemd (`webapp.service`)
- HTTPS: Let's Encrypt / Certbot
- Nginx: `client_max_body_size 500m` in `/etc/nginx/nginx.conf`

## Useful Server Commands
| Task | Command |
|------|---------|
| Restart app | `sudo systemctl restart webapp` |
| View logs | `sudo journalctl -u webapp -f` |
| Pull latest | `cd ~/newapp && git pull origin master` |
| Pull (with local changes) | `cd ~/newapp && git stash && git pull origin master` |

---

## Saved Questions Feature
Students can save questions from the browse page for easy access later.
- **UI:** "Save" / "Unsave" button on each question card; "Saved" tab in the topbar toggles a saved-only filter
- **Storage:** `difficult_questions` table in `users.db` (column name is historical; feature is called "Saved Questions" in the UI)
- **Schema:** `user_id TEXT, question_id TEXT, subject TEXT, created_at TEXT, PRIMARY KEY (user_id, question_id, subject)`
- **Isolation:** Specialist and Methods saved collections are completely separate (scoped by `subject` column)
- **DEV_MODE:** Uses `"dev_user"` as the user ID when no session exists

## Completed Questions Feature
Students can mark questions as done. Completed questions are highlighted light green (Specialist) or light blue (Methods).
- **UI:** "Mark as Done" / "Unmark Done" button on each question card; "Completed" tab filters to completed-only; "Hide Completed" toggle switch at top of sidebar (persists via `localStorage`)
- **Storage:** `completed_questions` table in `users.db`
- **Schema:** `user_id TEXT, question_id TEXT, subject TEXT, completed_at TEXT, PRIMARY KEY (user_id, question_id, subject)`
- **Colour:** `.qcard.completed` — green (`#f6fdf7` / `#d1e8d5`) for Specialist, blue (`#f0f7ff` / `#c9dff7`) for Methods via `body.methods .qcard.completed`
- **Hide Completed:** `hideCompleted` boolean stored in `localStorage`; re-applies after `loadCompletedIds()` resolves on page load

## Topbar Architecture
Two-row topbar (96px total):
- **Row 1 — brand row (52px):** CSS grid (`1fr auto 1fr`) with "← Subjects" back link left, subject name centred, avatar circle right
- **Row 2 — tabs row (44px, darker):** centred tabs (Questions, Saved, Completed, Admin) with underline active indicator
- **Avatar:** initials derived from `{{ user_name }}`; click opens dropdown with "Signed in as X" + Sign out; closes on outside click
- **All tabs are buttons** (no `<a>` links) — switching tabs is instant with no page reload
- **Height references:** sidebar `top: 96px`, `height: calc(100vh - 96px)`; backdrop `inset: 96px 0 0 0`; mobile sidebar `top: 84px`

## Funny Popup Feature

A per-student "funny popup" that fires randomly when a student marks a question as done. Designed to be extensible — new popups can be added easily.

### How it works
- `funny_popup` column on the `users` table stores a text key: `''` = off, or a popup name like `'jacaranda_moses'`
- Admin assigns a popup (or off) per student via a dropdown in `/admin/users` (Approved Students section)
- On the browse page, `funnyPopup` JS variable holds the current user's popup key (read live from DB on each page load via `get_funny_popup()`)
- In `toggleCompleted()`, if `data.marked && funnyPopup === '<key>' && Math.random() < 0.1`, the modal is shown (10% chance)
- The modal HTML lives at the bottom of `BROWSE_HTML`, just before `</body>`

### Current popups
| Key | Description | Image |
|-----|-------------|-------|
| `jacaranda_moses` | Moses holding the Jacaranda Specialist Maths textbook, with motivational quote | `static/jacaranda_moses.jpeg` |

### Adding a new popup
1. **Admin dropdown** (`USERS_HTML`): add `<option value="new_key">Display Name</option>` to the `<select>` in the approved students loop
2. **Modal HTML** (`BROWSE_HTML`): add a new `<div id="new-key-modal" ...>` with image and text, just before `</body>`
3. **JS trigger** (`BROWSE_HTML`, inside `toggleCompleted()`): add `else if (funnyPopup === 'new_key' && Math.random() < 0.1) document.getElementById('new-key-modal').style.display = 'flex';`
4. **Image**: add to `static/` and commit + scp to server (or just commit if small enough for git)
5. Deploy as usual

### Notes
- The DB column was originally integer 0/1, migrated to text in April 2025 — existing `1` values were updated to `'jacaranda_moses'`
- `funny_popup` is NOT stored in the session — it's read fresh from the DB on every browse page load, so admin changes take effect immediately without requiring the student to re-login

## Known Issues
_(none)_

## Future Improvements
- [ ] Set up automated SSL renewal check (Certbot should handle this automatically)
- [ ] Move HTML templates out of server.py into a `templates/` folder
