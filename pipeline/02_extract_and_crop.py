#!/usr/bin/env python3
"""
Extract and crop questions from all Specialist Maths exam PDFs.
Outputs: question_images/*.png and raw_questions.json
"""

import fitz  # pymupdf
import json
import os
import re
import glob
from PIL import Image
from io import BytesIO

UPLOADS = "/home/ubuntu/webpage/uploads"
OUT_DIR = "/home/ubuntu/webpage/question_images"
RAW_JSON = "/home/ubuntu/webpage/raw_questions.json"

os.makedirs(OUT_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# 1. Discover and pair exam files
# ---------------------------------------------------------------------------

SOLUTION_ONLY_KEYWORDS = ["solution", "solutions", "solns", "soln"]
SKIP_KEYWORDS = ["formula", "mcq answer sheet", "mc answer sheet", ".ds_store"]
QUESTION_KEYWORDS = ["question", "q&a", "qa", "q&as"]

# Publisher names that should keep specific casing
PUBLISHER_NAMES = {
    "mav": "MAV",
    "tssm": "TSSM",
    "neap": "NEAP",
    "qats-janison": "QATs-Janison",
    "insight": "Insight",
    "insight publications": "Insight Publications",
    "heffernan": "Heffernan",
    "kilbaha": "Kilbaha",
    "sequoia": "Sequoia",
}


def normalise_publisher(name):
    return PUBLISHER_NAMES.get(name.lower(), name.title())


def is_solution_file(fname):
    fl = fname.lower()
    # "Question and Answer Booklet" is a questions file, not solutions
    if "question" in fl:
        return False
    # Files with "solution(s)/solns/soln" are always solution files
    if any(k in fl for k in SOLUTION_ONLY_KEYWORDS):
        return True
    # "answers" / "answer" without "question" → solution file
    # But skip "answer sheet" (handled by is_skip_file)
    if "answer" in fl and "answer sheet" not in fl:
        return True
    return False


def is_skip_file(fname):
    fl = fname.lower()
    # Skip formula sheets and standalone answer sheets (MC bubble sheets)
    if "formula" in fl:
        return True
    if "answer sheet" in fl and "question" not in fl:
        return True
    if fl == ".ds_store":
        return True
    return False


def detect_exam_number(fname):
    fl = fname.lower()
    # "exam 1" / "exam 2" / "exam1"
    m = re.search(r"exam\s*(\d)", fl)
    if m:
        return int(m.group(1))
    # "sm1" / "sm2" (Insight 2023)
    m = re.search(r"sm(\d)", fl)
    if m:
        return int(m.group(1))
    # "Spec Maths 1" / "Spec Maths 2" (Insight 2024)
    m = re.search(r"maths\s*(\d)", fl)
    if m:
        return int(m.group(1))
    return None


def find_exam_pairs():
    """Find all (questions_pdf, solutions_pdf, year, publisher, exam_num) tuples."""
    pairs = []

    for year_dir in sorted(glob.glob(os.path.join(UPLOADS, "[0-9]*"))):
        year = os.path.basename(year_dir)
        if not year.isdigit():
            continue

        for pub_dir in sorted(glob.glob(os.path.join(year_dir, "*"))):
            publisher = os.path.basename(pub_dir)
            if publisher.startswith(".") or publisher == "__MACOSX":
                continue

            # Recursively find all PDFs in this publisher dir
            pdfs = []
            for root, dirs, files in os.walk(pub_dir):
                for f in files:
                    if f.lower().endswith(".pdf") and "__MACOSX" not in root:
                        pdfs.append(os.path.join(root, f))

            # Filter out non-exam files
            pdfs = [p for p in pdfs if not is_skip_file(os.path.basename(p))]

            # Group by exam number
            by_exam = {}
            for p in pdfs:
                en = detect_exam_number(os.path.basename(p))
                if en is None:
                    en = detect_exam_number(os.path.dirname(p))
                if en is not None:
                    by_exam.setdefault(en, []).append(p)

            for exam_num, files in sorted(by_exam.items()):
                q_file = None
                s_file = None
                for f in files:
                    bn = os.path.basename(f)
                    if is_solution_file(bn):
                        s_file = f
                    else:
                        q_file = f

                if q_file:
                    pairs.append({
                        "questions_pdf": q_file,
                        "solutions_pdf": s_file,
                        "year": int(year),
                        "publisher": normalise_publisher(publisher),
                        "exam_num": exam_num,
                    })

    return pairs


# ---------------------------------------------------------------------------
# 2. Detect question boundaries in a PDF
# ---------------------------------------------------------------------------

def find_question_markers(doc):
    """
    Scan the PDF for 'Question N' markers. Returns list of:
    {num, page, y, has_marks, marks, is_mc}
    """
    markers = []
    question_pattern = re.compile(
        r"Question\s+(\d+)\s*(?:\((\d+)\s*marks?\))?", re.IGNORECASE
    )

    for page_idx in range(doc.page_count):
        page = doc[page_idx]
        blocks = page.get_text("dict")["blocks"]

        for block in blocks:
            if block.get("type") != 0:  # text blocks only
                continue
            for line in block.get("lines", []):
                line_text = ""
                line_y0 = line["bbox"][1]
                for span in line.get("spans", []):
                    line_text += span["text"]

                m = question_pattern.search(line_text)
                if m:
                    q_num = int(m.group(1))
                    marks = int(m.group(2)) if m.group(2) else None
                    markers.append({
                        "num": q_num,
                        "page": page_idx,
                        "y": line_y0,
                        "marks": marks,
                        "has_marks": marks is not None,
                    })

    return markers


def detect_sections(markers):
    """
    Detect if this is Exam 1 (all short answer) or Exam 2 (MC + Extended Response).
    For Exam 2, split markers into MC and ER sections.
    Returns list of markers with added 'section' field.
    """
    if not markers:
        return markers

    # Check for numbering reset (Exam 2 has MC Q1-Q20 then ER Q1-Q5)
    nums = [m["num"] for m in markers]

    # Find where numbering resets to 1 after reaching a high number
    reset_idx = None
    max_seen = 0
    for i, n in enumerate(nums):
        if n > max_seen:
            max_seen = n
        if n == 1 and i > 0 and max_seen >= 10:
            reset_idx = i
            break

    if reset_idx is not None:
        # This is Exam 2
        for i, m in enumerate(markers):
            if i < reset_idx:
                m["section"] = "multiple_choice"
            else:
                m["section"] = "extended_response"
    else:
        # Check if questions have marks — Exam 1 questions often do
        has_marks_count = sum(1 for m in markers if m["has_marks"])
        # If most questions have marks and max question num <= 12, it's Exam 1
        # If max num >= 15, it's likely Exam 2 MC-only view
        if max_seen <= 12:
            for m in markers:
                m["section"] = "short_answer"
        else:
            # Likely Exam 2 with only MC (no ER in questions file, ER might be numbered differently)
            for m in markers:
                m["section"] = "multiple_choice"

    return markers


# ---------------------------------------------------------------------------
# 3. Crop questions from PDF
# ---------------------------------------------------------------------------

def get_page_content_bounds(page):
    """Get the content area bounds (excluding headers/footers)."""
    rect = page.rect
    # Generous margins: top 45pt, bottom 30pt for typical headers/footers
    return rect.x0, rect.y0 + 5, rect.x1, rect.y1 - 5


def crop_region(doc, page_idx, y_start, page_idx_end, y_end, scale=2.0):
    """
    Crop a region from the PDF, potentially spanning multiple pages.
    Returns a PIL Image.
    """
    mat = fitz.Matrix(scale, scale)
    images = []

    for pidx in range(page_idx, page_idx_end + 1):
        page = doc[pidx]
        rect = page.rect

        if pidx == page_idx and pidx == page_idx_end:
            # Single page
            clip = fitz.Rect(rect.x0, y_start, rect.x1, y_end)
        elif pidx == page_idx:
            # First page of multi-page
            clip = fitz.Rect(rect.x0, y_start, rect.x1, rect.y1 - 5)
        elif pidx == page_idx_end:
            # Last page of multi-page
            clip = fitz.Rect(rect.x0, rect.y0 + 5, rect.x1, y_end)
        else:
            # Full middle page
            clip = fitz.Rect(rect.x0, rect.y0 + 5, rect.x1, rect.y1 - 5)

        # Ensure clip is valid
        clip = clip & page.rect  # intersect with page
        if clip.is_empty or clip.width < 10 or clip.height < 10:
            continue

        pix = page.get_pixmap(matrix=mat, clip=clip)
        img = Image.open(BytesIO(pix.tobytes("png")))
        images.append(img)

    if not images:
        return None

    if len(images) == 1:
        return images[0]

    # Stitch vertically
    total_h = sum(im.height for im in images)
    max_w = max(im.width for im in images)
    stitched = Image.new("RGB", (max_w, total_h), (255, 255, 255))
    y_offset = 0
    for im in images:
        stitched.paste(im, (0, y_offset))
        y_offset += im.height
    return stitched


def extract_text_in_region(doc, page_idx, y_start, page_idx_end, y_end):
    """Extract text from a specific region of the PDF."""
    text_parts = []
    for pidx in range(page_idx, page_idx_end + 1):
        page = doc[pidx]
        rect = page.rect

        if pidx == page_idx and pidx == page_idx_end:
            clip = fitz.Rect(rect.x0, y_start, rect.x1, y_end)
        elif pidx == page_idx:
            clip = fitz.Rect(rect.x0, y_start, rect.x1, rect.y1)
        elif pidx == page_idx_end:
            clip = fitz.Rect(rect.x0, rect.y0, rect.x1, y_end)
        else:
            clip = fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y1)

        text_parts.append(page.get_text(clip=clip).strip())

    return "\n".join(text_parts)


def process_pdf(doc, markers, exam_info):
    """
    Process a single PDF: crop each question and extract text.
    Returns list of question dicts.
    """
    questions = []

    for i, marker in enumerate(markers):
        # Determine crop region
        page_start = marker["page"]
        y_start = max(0, marker["y"] - 5)  # Small padding above

        if i + 1 < len(markers):
            next_m = markers[i + 1]
            if next_m["page"] == page_start:
                # Same page
                page_end = page_start
                y_end = next_m["y"] - 8  # Stop just before next question
            else:
                # Multi-page: go to the end of pages until next question
                page_end = next_m["page"]
                y_end = next_m["y"] - 8
        else:
            # Last question — go to end of document (or end of page)
            page_end = min(page_start + 3, doc.page_count - 1)
            y_end = doc[page_end].rect.y1 - 20

        # For last question, try to find where content actually ends
        # by looking for empty space at bottom
        if i + 1 >= len(markers):
            # Scan backwards from page_end to find the last page with content
            for pidx in range(page_end, page_start - 1, -1):
                page_text = doc[pidx].get_text().strip()
                # Skip pages that only have headers/copyright
                meaningful_lines = [
                    l for l in page_text.split("\n")
                    if l.strip() and "copyright" not in l.lower()
                    and "kilbaha" not in l.lower()
                    and "mathematical association" not in l.lower()
                    and "page" not in l.lower()[:10]
                    and "https://" not in l.lower()
                    and "end of" not in l.lower()
                ]
                if meaningful_lines:
                    page_end = pidx
                    # Get the y-coordinate of the last meaningful text block
                    blocks = doc[pidx].get_text("dict")["blocks"]
                    max_y = 0
                    for block in blocks:
                        if block.get("type") == 0:
                            by1 = block["bbox"][3]
                            block_text = ""
                            for line in block.get("lines", []):
                                for span in line.get("spans", []):
                                    block_text += span["text"]
                            if block_text.strip() and "copyright" not in block_text.lower():
                                max_y = max(max_y, by1)
                    if max_y > 0:
                        y_end = max_y + 10
                    break

        # Build unique ID
        pub_slug = exam_info["publisher"].lower().replace(" ", "_").replace("-", "_")
        section_code = marker["section"][0]  # s, m, or e
        qid = f"{pub_slug}_{exam_info['year']}_exam{exam_info['exam_num']}_{section_code}_q{marker['num']}"

        # Crop question image
        q_img = crop_region(doc, page_start, y_start, page_end, y_end)
        q_img_path = None
        if q_img:
            q_img_file = f"{qid}_question.png"
            q_img_path = os.path.join(OUT_DIR, q_img_file)
            q_img.save(q_img_path, "PNG", optimize=True)

        # Extract text
        q_text = extract_text_in_region(doc, page_start, y_start, page_end, y_end)

        questions.append({
            "id": qid,
            "year": exam_info["year"],
            "publisher": exam_info["publisher"],
            "exam_type": exam_info["exam_num"],
            "section": marker["section"],
            "question_number": marker["num"],
            "marks": marker["marks"],
            "question_image": f"/qimg/{qid}_question.png" if q_img_path else None,
            "solution_image": None,  # filled later
            "extracted_text": q_text[:3000],  # Limit for API
            "source_pdf": exam_info["questions_pdf"],
        })

    return questions


# ---------------------------------------------------------------------------
# 4. Process solutions PDF (same approach)
# ---------------------------------------------------------------------------

def process_solutions(sol_pdf_path, questions, exam_info):
    """
    Open the solutions PDF, find question markers, crop matching solutions.
    Updates questions in-place with solution_image paths.
    """
    if not sol_pdf_path or not os.path.exists(sol_pdf_path):
        print(f"    No solutions file")
        return

    doc = fitz.open(sol_pdf_path)
    markers = find_question_markers(doc)
    markers = detect_sections(markers)

    if not markers:
        print(f"    WARNING: No question markers found in solutions PDF")
        doc.close()
        return

    # Build a lookup: (section, num) -> marker index
    marker_map = {}
    for i, m in enumerate(markers):
        key = (m["section"], m["num"])
        marker_map[key] = i

    for q in questions:
        key = (q["section"], q["question_number"])
        if key not in marker_map:
            continue

        idx = marker_map[key]
        m = markers[idx]

        page_start = m["page"]
        y_start = max(0, m["y"] - 5)

        if idx + 1 < len(markers):
            next_m = markers[idx + 1]
            page_end = next_m["page"]
            y_end = next_m["y"] - 8
        else:
            page_end = min(page_start + 4, doc.page_count - 1)
            y_end = doc[page_end].rect.y1 - 20
            # Find actual content end
            for pidx in range(page_end, page_start - 1, -1):
                page_text = doc[pidx].get_text().strip()
                meaningful_lines = [
                    l for l in page_text.split("\n")
                    if l.strip() and "copyright" not in l.lower()
                    and len(l.strip()) > 5
                    and "page" not in l.lower()[:10]
                    and "https://" not in l.lower()
                    and "end of" not in l.lower()
                ]
                if meaningful_lines:
                    page_end = pidx
                    blocks = doc[pidx].get_text("dict")["blocks"]
                    max_y = 0
                    for block in blocks:
                        if block.get("type") == 0:
                            block_text = ""
                            for line in block.get("lines", []):
                                for span in line.get("spans", []):
                                    block_text += span["text"]
                            if block_text.strip() and "copyright" not in block_text.lower():
                                max_y = max(max_y, block["bbox"][3])
                    if max_y > 0:
                        y_end = max_y + 10
                    break

        sol_img = crop_region(doc, page_start, y_start, page_end, y_end)
        if sol_img:
            sol_img_file = f"{q['id']}_solution.png"
            sol_img_path = os.path.join(OUT_DIR, sol_img_file)
            sol_img.save(sol_img_path, "PNG", optimize=True)
            q["solution_image"] = f"/qimg/{sol_img_file}"

    doc.close()


# ---------------------------------------------------------------------------
# 5. Main orchestration
# ---------------------------------------------------------------------------

def main():
    pairs = find_exam_pairs()
    print(f"Found {len(pairs)} exam pairs:\n")
    for p in pairs:
        sol = os.path.basename(p['solutions_pdf']) if p['solutions_pdf'] else '(none)'
        print(f"  {p['publisher']} {p['year']} Exam {p['exam_num']}: "
              f"{os.path.basename(p['questions_pdf'])} | Sol: {sol}")

    all_questions = []

    for pair in pairs:
        print(f"\n{'='*60}")
        print(f"Processing: {pair['publisher']} {pair['year']} Exam {pair['exam_num']}")
        print(f"  Q: {pair['questions_pdf']}")

        try:
            doc = fitz.open(pair["questions_pdf"])
        except Exception as e:
            print(f"  ERROR opening PDF: {e}")
            continue

        markers = find_question_markers(doc)
        if not markers:
            print(f"  WARNING: No question markers found — skipping")
            doc.close()
            continue

        markers = detect_sections(markers)

        summary = [f"Q{m['num']}({m['section'][:2]})" for m in markers]
        print(f"  Found {len(markers)} questions: {summary}")

        questions = process_pdf(doc, markers, pair)
        doc.close()

        # Process solutions
        if pair["solutions_pdf"]:
            print(f"  Processing solutions: {os.path.basename(pair['solutions_pdf'])}")
            process_solutions(pair["solutions_pdf"], questions, pair)

        sol_count = sum(1 for q in questions if q["solution_image"])
        print(f"  Extracted {len(questions)} questions, {sol_count} with solutions")

        all_questions.extend(questions)

    # Remove extracted_text source_pdf from final output (keep for classification)
    print(f"\n{'='*60}")
    print(f"Total questions extracted: {len(all_questions)}")

    # Save raw data (with text for classification)
    with open(RAW_JSON, "w") as f:
        json.dump(all_questions, f, indent=2)
    print(f"Saved to {RAW_JSON}")


if __name__ == "__main__":
    main()
