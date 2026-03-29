# Specialist Question Bank — Project Standards

## Project Overview
A web-based question bank for VCE Specialist Mathematics (Units 3 & 4).
Students browse, filter, and practise questions sourced from multiple trial exam publishers.
Questions are classified into the 6 VCE Areas of Study (AOS).

## Tech Stack
- **Backend:** Python / Flask (`server.py`), port 8080
- **Data:** `questions.json` (classified), `raw_questions.json` (with extracted text)
- **Images:** `question_images/` — PNG crops of each question and solution
- **Pipeline:** `pipeline/` — docx → PDF → image crops → classification
- Start server: `python3 server.py` from project root

## Areas of Study (AOS)
| # | Name |
|---|------|
| 1 | Logic and Proof |
| 2 | Functions, Relations and Graphs |
| 3 | Complex Numbers |
| 4 | Calculus |
| 5 | Vectors, Lines and Planes |
| 6 | Probability and Statistics |
| 0 | Unsorted (flagged for manual review) |

## Publishers in the Dataset
Heffernan, Insight, Kilbaha, MAV, NEAP, QATs-Janison, Sequoia, TSSM
Years: 2023, 2024, 2025

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

### Decision Making
- When unsure about scope or approach, ask before acting
- Explain the plan before implementing significant changes
- Flag when something looks wrong (e.g. wrong username in a path)

### Classification Workflow
- Do one publisher/year set at a time
- Analyse corrections after each batch before moving to the next
- Never re-run the classifier on all 747 questions until enough manual data has been collected
- Mark genuinely ambiguous questions as Unsorted (red) — don't force a category

### UI/UX Standards
- Dark/light theme toggle in top-right of navbar (preference saved to localStorage)
- Educator perspective: solutions hidden by default, student must reveal
- Keep the interface clean and low cognitive load
- Unsorted questions displayed in red throughout the UI

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
| **Live URL** | http://3.27.217.188 |
| **OS** | Ubuntu 22.04 |
| **Key pair** | specialistquestionbankkey |

## Stack

- **Backend:** Python / Flask (`server.py`)
- **Server:** Gunicorn (2 workers)
- **Process manager:** systemd (`webapp.service`)
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
Open http://3.27.217.188 in any browser.

---

## Useful Commands

| Task | Command |
|------|---------|
| Restart app | `sudo systemctl restart webapp` |
| Stop app | `sudo systemctl stop webapp` |
| Start app | `sudo systemctl start webapp` |
| View logs | `sudo journalctl -u webapp -f` |
| Pull latest code | `cd ~/newapp && git pull origin master` |

---

## Future Improvements
- [ ] Add a custom domain
- [ ] Set up HTTPS with Let's Encrypt (Certbot)
- [ ] Set up Nginx as a reverse proxy (to serve on port 80)