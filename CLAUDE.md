# VCE Mathematics Question Bank — Project Standards

## Project Overview
A web-based question bank for VCE Mathematics (Units 3 & 4), covering two subjects:
- **Specialist Mathematics** — at `/specialist`
- **Mathematical Methods** — at `/methods`

Students browse, filter, and practise questions sourced from multiple trial exam publishers.
Questions are classified into Areas of Study (AOS) per subject.

## Tech Stack
- **Backend:** Python / Flask (`server.py`), port 8080
- **Data:** `questions.json` (Specialist), `methods_questions.json` (Methods)
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
| `/api/classify` | Classify a question (subject in POST body) |
| `/api/flag` | Flag a question (subject in POST body) |

### Data & Config
- `questions.json` — Specialist questions
- `methods_questions.json` — Methods questions
- `raw_questions_methods.json` — Methods raw extracted text (in git — needed for classifier analysis)
- `settings.json` — Per-subject publisher visibility (gitignored)
- `get_subject_config(subject)` helper returns data, file path, AOS map, and subject name
- Colour themes: Specialist = teal (`#196061`, `#042f3a`), Methods = blue (`#2563eb`, `#1e3a5f`)

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
| 1 | Algebra and Functions |
| 2 | Differentiation |
| 3 | Integration |
| 4 | Discrete Probability |
| 5 | Continuous Probability |
| 6 | Core Content (Exam 2 only) |
| 7 | Probability and Statistics (Exam 2 only) |
| 8 | Pseudocode (Exam 1 only) |
| 0 | Unsorted (flagged for manual review) |

## Specialist Publishers in the Dataset
Heffernan, Insight, Kilbaha, MAV, NEAP, QATs-Janison, Sequoia, TSSM
Years: 2023, 2024, 2025

## Methods Publishers in the Dataset
Being imported batch by batch. All pipeline work is done locally.

## Classification Approach
- Text is extracted from PDFs using PyMuPDF (text layer, not OCR)
- Classified via keyword/regex matching in `pipeline/03_classify.py`
- Methods classifier is in `classify_for_methods()` and `METHODS_*` keyword sets at the bottom of that file — do not touch the Specialist logic above it
- When confidence is low, mark as **Unsorted (aos=0)** — never guess
- Manual corrections are the ground truth used to improve the classifier

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

All Methods work is done locally. The pipeline is fully portable — no server-specific paths.

### Per-batch workflow
1. Upload exam zip via `http://localhost:8080/admin?subject=methods` (with `DEV_MODE=1` server running)
   - Zip must contain folder structure: `2025/Publisher/Exam 1.pdf`, `Exam 1 Solutions.pdf`, etc.
   - This triggers the pipeline automatically
2. Visit `http://localhost:8080/classify?subject=methods&unsorted=1` and sort Unsorted questions
3. Press Save All
4. `git add methods_questions.json raw_questions_methods.json && git commit -m "..." && git push`
5. scp new images to server:
   ```bash
   scp -i "/Users/arieltenenberg/Desktop/Specialist Website/specialistquestionbankkey.pem" \
     question_images/methods_<publisher>_* ubuntu@3.27.217.188:~/newapp/question_images/
   ```
6. Deploy: SSH to server → `cd ~/newapp && git pull origin master && sudo systemctl restart webapp`

### DEV_MODE
- `DEV_MODE=1 python3 server.py` bypasses Google OAuth for all auth-protected routes
- Only use locally — never set on the server
- Kill any existing process first: `kill $(lsof -ti:8080)`
- To refresh local data (e.g. after a reset or git pull), always restart the server — Flask loads data files at startup, so stale data will show until restarted:
  ```bash
  kill $(lsof -ti:8080) && DEV_MODE=1 python3 server.py
  ```

### Pipeline scripts (run from project root)
```bash
python3 pipeline/01_convert_docx.py --subject methods   # DOCX → PDF (needs LibreOffice)
python3 pipeline/02_extract_and_crop.py --subject methods  # extract text + crop images
python3 pipeline/03_classify.py --subject methods          # classify → methods_questions.json
```
The admin upload UI triggers all three automatically.

### Important pipeline behaviour
- `03_classify.py` **merges** new questions with existing `methods_questions.json` — previous batches are never lost
- `raw_questions_methods.json` contains the current batch's extracted text and is committed to git so Claude can analyse it
- Do one publisher/year at a time; analyse classifier corrections after each batch

### One-time local setup
```bash
brew install --cask libreoffice
pip install pymupdf Pillow
```

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

## Future Improvements
- [ ] Set up automated SSL renewal check (Certbot should handle this automatically)
