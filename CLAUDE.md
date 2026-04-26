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
- **Icons:** [Lucide](https://lucide.dev/) — loaded via CDN (`unpkg.com/lucide`) at bottom of `BROWSE_HTML`. Call `lucide.createIcons()` after any dynamic `innerHTML` update that contains `<i data-lucide="...">` elements.
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
| `GET /api/leaderboard?subject=specialist\|methods[&leaderboard_id=N]` | Entries for a leaderboard group; returns `{leaderboard_name, entries}` (each entry includes `level_num`) |
| `GET /api/gamification?subject=specialist\|methods` | XP, level, streak, today's count, badge state for current user |
| `GET /api/admin/leaderboards` | List all leaderboards (admin only) |
| `POST /api/admin/leaderboards` | Create a leaderboard `{name}` (admin only) |
| `PUT /api/admin/leaderboards/<id>` | Rename a leaderboard (admin only) |
| `DELETE /api/admin/leaderboards/<id>` | Delete a leaderboard — unassigns all members (admin only) |
| `POST /admin/users/<google_id>/settings` | Set `leaderboard_id`, `funny_popup`, `nickname`, `shabbat_proof` for a student (admin only) |
| `GET /api/admin/users/<google_id>/progress` | Per-student progress breakdown by AOS + section type, both subjects (admin only) |

### Data & Config
- `specialist_questions.json` — Specialist questions
- `methods_questions.json` — Methods questions
- `raw_questions_methods.json` — Methods raw extracted text (in git — needed for classifier analysis)
- `raw_questions_specialist.json` — Specialist raw extracted text (gitignored — local only)
- `settings.json` — Per-subject publisher visibility (gitignored)
- `overrides.json` — Server-side AOS overrides (gitignored — see below)
- `get_subject_config(subject)` helper returns data, file path, AOS map, and subject name
- Colour theme: neutral charcoal for both subjects — subject-specific teal/blue removed entirely. CSS variables (`--primary`, `--primary-dark`, etc.) are still injected per subject but the browse page UI no longer uses them.
- `users.db` — SQLite database for user accounts, saved questions, completed questions, and leaderboard data (server-only, not in git)

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
Heffernan, Insight, Kilbaha, MAV, NEAP
Years: 2012–2022 (old study design), 2023, 2024, 2025
Notes:
- Heffernan 2013 is Exam 2 only (no Exam 1 published). Kilbaha 2013 not imported (incomplete files).
- 2012 marks were entered manually (older PDF format puts marks bottom-right, pipeline cannot extract them). Kilbaha 2012 not imported yet.

## Methods Publishers in the Dataset
Imported batch by batch. All pipeline work is done locally.
Years imported so far: 2016–2025 (all years complete)
Note: If 2012 Methods exams are imported, marks will need to be entered manually (same bottom-right format as Specialist 2012).

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
- **Marks extraction**: the pipeline extracts marks from `"Question N (X marks)"` patterns, including when the mark count appears on a separate line or is spaced apart (e.g. Kilbaha format). MC questions always store `marks=0` — this is expected and correct. If marks are missing after import, use the **Fix Missing Marks** widget at the bottom of `/classify` (visible on any subject page).

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
- **UI:** "Save" button toggles to filled dark "Saved" state; "Saved" tab in the topbar toggles a saved-only filter
- **Popup:** unsaving any saved question (regardless of active tab) prompts "Mark as done?" — `showMarkCompletePrompt(id)` — skipped if the question is already completed
- **Storage:** `difficult_questions` table in `users.db` (column name is historical; feature is called "Saved Questions" in the UI)
- **Schema:** `user_id TEXT, question_id TEXT, subject TEXT, created_at TEXT, note TEXT, PRIMARY KEY (user_id, question_id, subject)`
- **Saved indicator:** ★ star icon in card header (see Completed Questions section for details) — no left border
- **Isolation:** Specialist and Methods saved collections are completely separate (scoped by `subject` column)
- **DEV_MODE:** Uses `"dev_user"` as the user ID when no session exists

### Saved Question Notes
Students can attach a private note to any saved question (e.g. what to ask their tutor).
- **UI:** "Add Note" / "Edit Note" button appears in card actions when a question is saved; opens a modal with a textarea. A red trash icon button (right-aligned) appears in the modal when editing an existing note.
- **Indicator:** ◆ icon (`.note-icon`) in the card header, left of the ★; hidden by default, shown via `.qcard.has-note .note-icon { display:inline }`. Both icons are wrapped in `.card-icons` (flex, `gap:12px`) so the header flex gap doesn't split them apart.
- **Tooltip:** hovering ◆ shows the note text in a floating tooltip (`#_noteTip`) appended to `document.body` and positioned via `getBoundingClientRect` — immune to parent `overflow:hidden`. Centered on the icon.
- **Storage:** `note TEXT` column on `difficult_questions` (added via `ALTER TABLE` migration at startup)
- **API:** `GET /api/saved` returns `{ids, notes}` (notes keyed by question_id). `POST /api/saved/note` with `{question_id, subject, note}` upserts the note. Saving empty string clears the note.
- **JS:** `savedNotes = {}` map; `applyNoteState(id, note)` updates icon, button label, and `data-note` attribute; `openNoteModal(id)`, `saveNote()`, `deleteNote()`, `closeNoteModal()`

## Completed Questions Feature
Students can mark questions as done. Completed questions are highlighted in emerald green for both subjects.
- **UI:** "Mark as Done" / "Unmark as Done" button on each question card; button stays neutral grey in both states (card background is the only visual indicator); "Completed" tab filters to completed-only; "Hide Completed" toggle in settings popover (persists via `localStorage`)
- **Popup:** marking a saved question as done (regardless of active tab) prompts "Unsave?" — `showUnsavePrompt(id)`
- **Storage:** `completed_questions` table in `users.db`
- **Schema:** `user_id TEXT, question_id TEXT, subject TEXT, completed_at TEXT, PRIMARY KEY (user_id, question_id, subject)`
- **Colour:** `.qcard.completed` — `border-left:5px solid #8db370` (sage green, no background fill)
- **Saved indicator:** ★ star icon (`.bookmark-icon`) injected in the card header, left of publisher info; hidden by default, shown via `.qcard.saved .bookmark-icon { display:inline }`. Replaces the old charcoal left bar. When both saved and completed, green bar + star coexist with no conflict.
- **Hide Completed:** `hideCompleted` boolean stored in `localStorage`; re-applies after `loadCompletedIds()` resolves on page load

## Topbar Architecture
Two-row topbar (96px total):
- **Row 1 — brand row (52px):** CSS grid (`1fr auto 1fr`) with "← Subjects" back link left, subject name centred, and three icons right (progress, settings, avatar). Background: `#2d2d2d` (charcoal) for both subjects.
- **Row 2 — tabs row (44px):** centred tabs (Questions, Saved, Completed, Admin) with underline active indicator. Background: `#1f1f1f` (darker charcoal).
- **Right icon row (left→right):** achievements (trophy) → progress (bar-chart-2) → settings (sliders-horizontal) → avatar circle. All three icon buttons are 34×34px circles with `rgba(255,255,255,.13)` background and `1.5px` white border. Icons use Lucide (`<i data-lucide="...">`) at 16×16px. Spacing via `gap:6px` on `.topbar-right`.
- **Avatar:** initials derived from `{{ user_name }}`; click opens dropdown with "Signed in as X" + Sign out; closes on outside click
- **All tabs are buttons** (no `<a>` links) — switching tabs is instant with no page reload
- **Height references:** sidebar `top: 96px`, `height: calc(100vh - 96px)`; backdrop `inset: 96px 0 0 0`; mobile sidebar `top: 84px`

## Colour Scheme

All pages use a unified warm neutral palette. Never introduce cool blue-greys (Tailwind slate/blue-grey family). Every new feature must use these values.

### CSS Variables (defined in each template's `:root`)
| Variable | Value | Usage |
|----------|-------|-------|
| `--bg` | `#f6f3ee` | Page background |
| `--surface` | `#fdfaf6` | Cards, dropdowns, modals |
| `--border` | `#e3ddd4` | All borders |
| `--text` | `#1c1917` | Primary text |
| `--text-secondary` | `#57534e` | Secondary text |
| `--muted` | `#78716c` | Labels, placeholders, icons |
| `--shadow-sm` | `0 1px 3px rgba(60,44,28,.07)` | Card shadows |
| `--shadow-md` | `0 4px 12px rgba(60,44,28,.09)` | Dropdown/modal shadows |
| `--radius` | `12px` | Default border-radius |

### Fixed colours (used directly, not via variables)
| Value | Usage |
|-------|-------|
| `#2d2d2d` | Topbar background, primary buttons, active states |
| `#1f1f1f` | Tabs row background |
| `#1c1917` | Dark text (same as `--text`) |
| `#3a5c4a` | Eucalyptus green — XP bars, progress fills |
| `#eaeeeb` | Eucalyptus tint — completed card bg, earned badge bg |
| `#4d7a64` | Eucalyptus border — completed card border, earned badge border |
| `#243d33` | Dark eucalyptus — earned badge icon strokes |
| `#f2ede6` | Warm locked bg — locked badge background |
| `#e5dfd7` | Warm locked border — locked badge border |
| `#e8e4dd` | Warm off-white — action button default background |
| `#d0ccc4` | Warm border — action button default border |
| `#c53030` | Red — admin bar, flag button, error states |
| `#c5bdb4` | Warm mid-grey — toggle switch inactive |
| `#a09890` | Warm light-grey — locked/disabled element names |
| `#b5ada5` | Warm lighter-grey — locked/disabled descriptions |

### Rules
- **Shadows:** always warm-tinted `rgba(60,44,28,...)`, never `rgba(0,0,0,...)`
- **Surfaces:** modals, cards, dropdowns use `var(--surface)` (`#fdfaf6`), not `#fff`
- **Toggle knobs** (the white circle) are the only exception — keep `#fff` for contrast
- **Image backgrounds** (`.qimg-wrap img`) keep `#fff` — images need a neutral white mat
- **Modal backdrops** keep `rgba(0,0,0,...)` — full-screen overlays are fine as pure black
- **Topbar overlays** (`rgba(255,255,255,...)`) are fine — these sit on charcoal, not warm bg
- Never use: `#718096`, `#4a5568`, `#1a202c`, `#e2e8f0`, `#f5f7fa`, `#cbd5e0`, `#a0aec0`

## Browse Page UI Standards

### Question Card Header Layout
```
[Topic (bold, #1f1f1f) · Question Type]    [Publisher Year · Q#]  ›
```
- Left group (`.qcard-left`): topic bold in `#1f1f1f`, middot + question type in muted grey
- Right (`.qsection`): publisher, year, Q number — muted plain text, `margin-left:auto`
- No pill/bubble styling on any header element

### Action Buttons (inside expanded card)
All four buttons (Show Solution, Save, Mark as Done, Flag as misclassified) share identical proportions:
- `padding:8px 20px; font-size:.85rem; border-radius:8px; margin-top:4px`
- Default: `#d8d8d8` background, `#2d2d2d` text, `#c4c4c4` border
- Hover: fills to `#2d2d2d` with white text
- Saved state: filled `#2d2d2d`; shows "Saved"
- Completed state: filled `#2d2d2d`; shows "Unmark as Done" (card green tint also indicates completion)
- Flag button: same proportions, fills red on hover

### Card List
- 20 questions per page; "Load more" button appends next batch without re-rendering existing cards
- No question counter in toolbar
- Empty states for Saved and Completed tabs when nothing is saved/done yet
- `buildCardHtml(q)` — renders one card; `applyCardStates(questions)` — applies saved/completed visual states

## Easter Egg Feature

A per-student "Easter Egg" (formerly called "funny popup") that fires randomly when a student marks a question as done. Designed to be extensible — new popups can be added easily.

### How it works
- `funny_popup` column on the `users` table stores a text key: `''` = off, or a popup name like `'jacaranda_moses'`
- Admin assigns an Easter Egg (or off) per student via the **student settings modal** in `/admin/users` — open with the ⚙ gear icon next to each student
- On the browse page, `funnyPopup` JS variable holds the current user's popup key (read live from DB on each page load via `get_funny_popup()`)
- In `toggleCompleted()`, if `data.marked && funnyPopup === '<key>' && Math.random() < 0.2`, the modal is shown (20% chance)
- The modal HTML lives at the bottom of `BROWSE_HTML`, just before `</body>`

### Current popups
| Key | Description | Image |
|-----|-------------|-------|
| `jacaranda_moses` | Moses holding the Jacaranda Specialist Maths textbook, with motivational quote | `static/jacaranda_moses.jpeg` |

### Adding a new popup
1. **Settings modal** (`USERS_HTML`): add `<option value="new_key">Display Name</option>` to `#modal-popup-select`
2. **Modal HTML** (`BROWSE_HTML`): add a new `<div id="new-key-modal" ...>` with image and text, just before `</body>`
3. **JS trigger** (`BROWSE_HTML`, inside `toggleCompleted()`): add `else if (funnyPopup === 'new_key' && Math.random() < 0.1) document.getElementById('new-key-modal').style.display = 'flex';`
4. **Image**: add to `static/` and commit + scp to server (or just commit if small enough for git)
5. Deploy as usual

### Notes
- The DB column was originally integer 0/1, migrated to text in April 2025 — existing `1` values were updated to `'jacaranda_moses'`
- `funny_popup` is NOT stored in the session — it's read fresh from the DB on every browse page load, so admin changes take effect immediately without requiring the student to re-login

## Progress Modal Feature

Students can view their completion progress broken down by Area of Study and question type.

- **Trigger:** Bar-chart icon button (`.progress-btn-topbar`) in the topbar brand row, to the left of the settings icon. Styled identically to the settings icon (34×34px circle).
- **UI:** Modal overlay (`#progress-modal`) with one `.progress-card` per visible AOS. Each card shows:
  - Main bar: "X% complete — N / Y" for the full AOS
  - Sub-bars (indented, `border-left` group): Short Answer, Multiple Choice, Extended Response — each showing N / Y. Sub-bars with 0 questions are hidden.
- **Subject-specific:** AOS list comes from `AOS_MAP` (injected from Flask as `{{ aos_map | tojson }}`). Hidden AOS: 0 and 9 always; plus 8 (Mechanics) for Specialist.
- **Client-side only:** Computed from `allQ` + `completedIds` — no new API endpoint.
- **Dismiss:** Click backdrop or press Escape.
- **Key JS:** `openProgressModal()`, `closeProgressModal()`, `renderProgressView()`, `progressModalKeyHandler()`.

## Leaderboard Feature

Named leaderboard groups — students see their own group's completion rankings in the browse page sidebar.

### Storage
- `leaderboards` table: `id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL`
- `users.leaderboard_id INTEGER` (NULL = not on any leaderboard) — replaces the old `leaderboard INTEGER 0/1` boolean (kept in schema but unused)
- `users.nickname TEXT` — optional display name shown on the leaderboard instead of first name

### Visibility
- Students: shown only if their `leaderboard_id IS NOT NULL`. Widget title = group name. See only their own group.
- Admin: always shown; sidebar widget has a dropdown picker to preview any group.
- `get_show_leaderboard(user)` determines this; always `True` in DEV_MODE.

### Browse page widget
- Sits at the top of the sidebar (the sidebar-progress widget is excluded). Title updates dynamically to the leaderboard's name.
- Admin gets a `<select>` dropdown populated via `GET /api/admin/leaderboards` to pick which group to view.
- `loadLeaderboard(lbId)` fetches `/api/leaderboard?subject=<subject>[&leaderboard_id=N]` and renders into `#leaderboard-entries`.
- API returns `{leaderboard_name, entries: [{name, nickname, count, level_num, is_you}]}`. Display uses `nickname` if set, otherwise first name. Level is not shown in the leaderboard widget.

### Admin management (`/admin/users`)
- **⚙ gear button** per student opens a settings modal to assign leaderboard, nickname, and Easter Egg.
- **Leaderboards section** at the bottom of the page lists all groups with inline Rename/Delete and a member list (dot-bulleted, nickname or name).
- **Settings modal** uses `data-*` attributes on the gear button (never `onclick` parameters) to avoid HTML quoting issues — `data-lb`, `data-popup`, `data-nickname`, `data-shabbat` are updated in-place after saving so reopening shows current values.
- Saving calls `POST /admin/users/<id>/settings` with `{leaderboard_id, funny_popup, nickname, shabbat_proof}`.
- Creating a new leaderboard inline (via "＋ Create new…" option) triggers a page reload to refresh all dropdowns.

### Per-student progress modal (`/admin/users`)
- **Bar-chart button** per student opens a progress modal with Specialist / Methods tabs.
- Data fetched from `GET /api/admin/users/<google_id>/progress` — server-side breakdown by AOS + section type for both subjects.
- Same visual style as the student-facing progress modal (`.progress-card`, `.progress-bar-*` CSS).
- Hidden AOS: Specialist hides 0, 8, 9 — Methods hides 0, 9.

## Gamification Feature

Students earn XP for completing questions, level up through named tiers, maintain daily streaks, and unlock badges.

### XP Rates
XP is calculated as **marks × 5**. MC questions are stored with `marks=0` and treated as 1 mark (5 XP). All other questions use their stored `marks` value. `_marks_lookup` at startup maps every question_id to its effective marks (0→1 for MC).

| Example | Marks | XP |
|---|---|---|
| Multiple Choice | 1 | 5 |
| Short Answer (typical) | 3–5 | 15–25 |
| Extended Response (typical) | 8–12 | 40–60 |

Both subjects combined for all XP, streaks, and levels.

### Levels
| # | Name | XP threshold |
|---|------|-------------|
| 1 | Novice | 0 |
| 2 | Apprentice | 250 |
| 3 | Student | 750 |
| 4 | Scholar | 1,750 |
| 5 | Prodigy | 3,750 |
| 6 | Veteran | 7,500 |
| 7 | Master | 14,000 |
| 8 | Grandmaster | 23,500 |

### Streaks
- 5+ questions/day (AEST, UTC+10) keeps the streak alive — counted via `date(completed_at, '+10 hours')` in SQLite
- Missing a day resets streak to 0 (no grace period)
- `longest_streak` is tracked separately; never decreases
- Streaks are only ever updated when a question is marked complete — there is no passive reset job

### Shabbat-Proof Streaks
- Per-student toggle (`shabbat_proof INTEGER` on `users` table, default 0) — set via the student settings modal in `/admin/users`
- **Saturday:** runs the normal streak logic. If the student completes 5+ questions, Saturday counts as a streak day. If they do nothing, `last_streak_date` is untouched — streak is not broken.
- **Sunday:** accepts either Friday or Saturday as "yesterday" (`last in (friday, saturday)`), so the streak continues regardless of whether the student worked on Saturday.
- All other days behave identically to non-Shabbat-proof students.

### Badges
Three categories shown in the Achievements modal:
1. **Question milestones** — 1, 10, 50, 100, 250, 500, 1000, 1500 total completions (both subjects)
2. **Streak milestones** — 7, 30, 100 day longest streak
3. **AOS completion** — 100% of visible questions in a given AOS + subject (e.g. `aos_specialist_7`). Uses `apply_overrides()` dynamically so hidden questions don't inflate the target.

All badge icons use Lucide (`<i data-lucide="...">`) — no emoji. Icon mapping: `q_1` footprints, `q_10` target, `q_50` key, `q_100` award, `q_250` zap, `q_500` flame, `q_1000` gem, `q_1500` crown, `s_7` calendar, `s_30` calendar-days, `s_100` medal, AOS badges circle-check. Locked badges are shown greyed out (opacity .35) with an SVG lock pip.

### DB columns (on `users` table)
- `xp INTEGER DEFAULT 0`
- `current_streak INTEGER DEFAULT 0`
- `longest_streak INTEGER DEFAULT 0`
- `last_streak_date TEXT`
- `shabbat_proof INTEGER DEFAULT 0`

### Key server functions
- `get_level(xp)` — returns `(level_num, level_name, xp_min)`
- `compute_earned_badge_ids(total_completed, longest_streak, completed_ids_subject, subject)` — returns set of earned badge IDs
- `migrate_xp_for_existing_users()` — backfills XP for questions completed before gamification was added; runs at startup
- `AEST = datetime.timezone(datetime.timedelta(hours=10))` — used for streak day calculation

### POST /api/completed response (additional fields)
Returns `prev_level_num`, `new_level_num`, `new_level_name`, `newly_earned_badges`, `today_count`, `current_streak` — used by the client to trigger celebration popups and update the sidebar widget.

### Achievements modal
- Opened via trophy Lucide button in the topbar brand row (same row as progress and settings icons)
- `openAchievementsModal()` / `loadGamification()` / `renderAchievements(data)`
- Canvas confetti fires on level-up celebration
- Celebration toast has three variants: level-up (with level name), badge unlock, and streak increment (`toast-streak` — small, zap icon, auto-dismisses after 2.5s; only shows when no level-up or badge fires)
- Modal sections (top to bottom): Level card (XP bar) → Questions Completed (MC / SA / ER breakdown, computed client-side from `allQ` + `completedIds`) → Streak (current + best, "N days" format) → Question Milestones badges → Streak badges → AOS badges

### Sidebar progress widget
- `.sidebar-progress` CSS and JS exist but the HTML widget is **intentionally excluded** from the sidebar — do not add it
- Shows: level pill (`Level N`, `border-radius:6px` matching card style), level name, sage green XP bar, XP label, today's count, current streak
- Initialised via `initSidebarGamification()` on page load; updated via `updateSidebarGamification(...)` after each `toggleCompleted`
- Widget starts visible with placeholder "Level 1" text (not hidden) — placeholder is accurate for new users

### Colour scheme
All gamification UI uses the existing sage green palette (`#8db370`, `#4a6f32`) — no amber/gold anywhere.

## Marks Sanity Check

After importing a new batch, verify every exam sums to the correct total:
- Exam 1: 40 marks
- Exam 2: 80 marks
- Count MC questions as 1 mark each (they store `None` in the JSON)
- **Include all questions** -- hidden (AOS 9) and Mechanics (AOS 8) must be counted too, otherwise the totals will be wrong

```python
import json
from collections import defaultdict
with open('specialist_questions.json') as f:
    qs = json.load(f)
by_pub_exam = defaultdict(list)
for q in qs:
    by_pub_exam[(q['year'], q['publisher'], q['exam_type'])].append(q)
for (year, pub, exam), questions in sorted(by_pub_exam.items()):
    total = sum((q['marks'] or 0) if (q['marks'] or 0) > 0 else 1 for q in questions)
    expected = 40 if exam == 1 else 80
    if total != expected:
        print(f'ISSUE: {year} {pub} Exam {exam}: {total} (expected {expected})')
```

Known pre-existing issue: **2018 MAV Exam 1 = 36** (4 marks missing, not fixable from PDF).

## Known Issues
_(none)_

## Future Improvements
- [ ] Set up automated SSL renewal check (Certbot should handle this automatically)
- [ ] Move HTML templates out of server.py into a `templates/` folder
