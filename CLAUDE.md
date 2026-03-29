# VCE Mathematics Question Bank — Project Standards

## Project Overview
A web-based question bank for VCE Mathematics (Units 3 & 4), currently covering two subjects:
- **Specialist Mathematics** — at `/specialist`
- **Mathematical Methods** — at `/methods` (questions to be added)

Students browse, filter, and practise questions sourced from multiple trial exam publishers.
Questions are classified into Areas of Study (AOS) per subject.

## Tech Stack
- **Backend:** Python / Flask (`server.py`), port 8080
- **Data:** `questions.json` (Specialist), `methods_questions.json` (Methods, starts empty)
- **Images:** `question_images/` — PNG crops of each question and solution
- **Pipeline:** `pipeline/` — docx → PDF → image crops → classification
- Start server: `python3 server.py` from project root

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
| `/api/classify` | Classify a question (subject in POST body) |
| `/api/flag` | Flag a question (subject in POST body) |

### Data & Config
- `questions.json` — Specialist questions (do not add a `subject` field; separate files per subject)
- `methods_questions.json` — Methods questions
- `settings.json` — Per-subject publisher visibility: `{"specialist": {"hidden_publishers": []}, "methods": {"hidden_publishers": []}}`
- `get_subject_config(subject)` helper returns data, file path, AOS map, and subject name
- Colour themes: Specialist = teal (`#196061`, `#042f3a`), Methods = blue (`#2563eb`, `#1e3a5f`)

### Workflow for Adding a New Subject's Exams
1. Create an empty `<subject>_questions.json`
2. Add subject config to `SUBJECT_CONFIG` dict in `server.py`
3. Run pipeline to extract and classify questions into that file
4. Add subject card to `HOME_HTML`

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
| 0 | Unsorted (flagged for manual review) |

## Mathematical Methods — Areas of Study (AOS)
| # | Name |
|---|------|
| 1 | Functions and Graphs |
| 2 | Algebra |
| 3 | Calculus |
| 4 | Probability and Statistics |
| 0 | Unsorted (flagged for manual review) |

## Specialist Publishers in the Dataset
Heffernan, Insight, Kilbaha, MAV, NEAP, QATs-Janison, Sequoia, TSSM
Years: 2023, 2024, 2025

## Methods Publishers in the Dataset
To be added — awaiting first exam import.

## Classification Approach
- Text is extracted from PDFs using PyMuPDF (text layer, not OCR)
- Classified via keyword/regex matching in `pipeline/03_classify.py`
- When confidence is low, mark as **Unsorted (aos=0)** — never guess
- Manual review tool: `http://localhost:8080/classify`
- Manual corrections are the ground truth used to improve the classifier

### Known Classifier Issues
- Vector unit vectors `i`, `j`, `k` (e.g. `2i − j + 3k`) falsely trigger Complex Numbers
- `displacement` / `position` of particle in 2D/3D goes to Calculus instead of Vectors
- Publisher copyright headers (especially Heffernan) dominate extracted text, leaving little question content
- `partial fractions` keyword fires Calculus even when the question is a Logic/Proof question
- Stats keywords (`proportion`, `rate`) fire on differential equation / modelling questions
- `rotated about` (volume of revolution) is not in the Calculus keyword list

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
- Flag when something looks wrong (e.g. wrong username in a path)

### Classification Workflow
- Do one publisher/year set at a time
- Analyse corrections after each batch before moving to the next
- Never re-run the classifier on all questions until enough manual data has been collected
- Mark genuinely ambiguous questions as Unsorted (red) — don't force a category
- Methods classifier rules to be defined before first exam import — user will provide sorting instructions

### UI/UX Standards
- Educator perspective: solutions hidden by default, student must reveal
- Keep the interface clean and low cognitive load
- Unsorted questions displayed in red throughout the UI
- Landing page: neutral grey (`#f0f0f0`), dark charcoal topbar (`#2d2d2d`)
- Subject pages use their own colour theme (teal/blue) — passed as Jinja2 CSS variables
- Users page matches the landing page colour scheme (not subject-specific)
- Users tab only accessible from the landing page (not in subject or admin navbars)

### Server
- Restart required after changes to `server.py`
- Kill existing process: `kill $(lsof -ti:8080)`
- Verify after restart: `curl -s -o /dev/null -w "%{http_code}" http://localhost:8080`

---

# Specialist Question Bank — Project Notes

## Server Details

| Detail | Value |
|--------|-------|
| **Provider** | AWS EC2 (ap-southeast-2 / Sydney) |
| **Instance** | Specialist Question Bank (i-027bc033117bae0c5) |
| **Instance type** | t3.small |
| **Public IP** | 3.27.217.188 |
| **Live URL** | https://ariel.tenenberg.com |
| **OS** | Ubuntu 22.04 |
| **Key pair** | specialistquestionbankkey |

## Stack

- **Backend:** Python / Flask (`server.py`)
- **Server:** Gunicorn (2 workers) behind Nginx reverse proxy
- **Process manager:** systemd (`webapp.service`)
- **HTTPS:** Let's Encrypt / Certbot
- **Repo on server:** `~/newapp`

## Deployment Workflow

Every time you make changes to the app:

### 1. Work locally in VS Code as normal

### 2. Push changes to GitHub
```bash
git add .
git commit -m "describe your changes"
git push
```

### 3. Connect to the server
- Go to: https://ap-southeast-2.console.aws.amazon.com/ec2/home?region=ap-southeast-2#Instances:
- Click on **Specialist Question Bank**
- Click **Connect** → **EC2 Instance Connect** → **Connect**

### 4. Pull changes and restart the app
```bash
cd ~/newapp && git pull origin master
sudo systemctl restart webapp
```

### 5. Verify it's running
```bash
sudo systemctl status webapp
```
You should see `Active: active (running)` in green.

### 6. Check the live site
Open https://ariel.tenenberg.com in any browser.

---

## Useful Commands

| Task | Command |
|------|---------|
| Restart app | `sudo systemctl restart webapp` |
| Stop app | `sudo systemctl stop webapp` |
| Start app | `sudo systemctl start webapp` |
| View logs | `sudo journalctl -u webapp -f` |
| View Nginx logs | `sudo tail -f /var/log/nginx/access.log` |
| Reload Nginx | `sudo systemctl reload nginx` |
| Pull latest code | `cd ~/newapp && git pull origin master` |

### Nginx config note
Nginx proxies HTTPS traffic to Gunicorn. `client_max_body_size 500m` is set in the `http {}` block of `/etc/nginx/nginx.conf` to allow large exam file uploads.

---

## Future Improvements
- [ ] Set up automated SSL renewal check (Certbot should handle this automatically)