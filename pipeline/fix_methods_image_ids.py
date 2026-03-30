#!/usr/bin/env python3
"""
One-time migration: add 'methods_' prefix to all Methods question IDs and image filenames.
Run from the project root.
"""
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
METHODS_JSON = os.path.join(BASE, "methods_questions.json")
RAW_JSON = os.path.join(BASE, "raw_questions_methods.json")
IMG_DIR = os.path.join(BASE, "question_images")

def fix_json(path):
    with open(path) as f:
        questions = json.load(f)

    for q in questions:
        old_id = q["id"]
        if old_id.startswith("methods_"):
            continue  # already fixed
        new_id = f"methods_{old_id}"
        q["id"] = new_id

        for field in ("question_image", "solution_image"):
            if q.get(field):
                q[field] = q[field].replace(f"/qimg/{old_id}_", f"/qimg/{new_id}_")

    with open(path, "w") as f:
        json.dump(questions, f, indent=2)

    print(f"Updated {len(questions)} questions in {os.path.basename(path)}")

def rename_images(questions):
    renamed = 0
    missing = 0
    for q in questions:
        new_id = q["id"]  # already has methods_ prefix after fix_json
        old_id = new_id[len("methods_"):]
        for suffix in ("_question.png", "_solution.png"):
            old_path = os.path.join(IMG_DIR, f"{old_id}{suffix}")
            new_path = os.path.join(IMG_DIR, f"{new_id}{suffix}")
            if os.path.exists(old_path) and not os.path.exists(new_path):
                os.rename(old_path, new_path)
                renamed += 1
            elif not os.path.exists(old_path) and not os.path.exists(new_path):
                missing += 1
    print(f"Renamed {renamed} image files ({missing} not found locally — upload will handle server)")

# Fix JSON files
fix_json(METHODS_JSON)
fix_json(RAW_JSON)

# Rename images
with open(METHODS_JSON) as f:
    questions = json.load(f)
rename_images(questions)

print("Done.")
