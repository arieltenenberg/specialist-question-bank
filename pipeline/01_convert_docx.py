#!/usr/bin/env python3
"""Convert all .docx files in uploads/<subject>/ to PDF using LibreOffice headless."""

import os
import subprocess
import glob
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--subject", choices=["specialist", "methods"], required=True,
                    help="Which subject's upload folder to process")
args = parser.parse_args()

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOADS = os.path.join(BASE, "uploads", args.subject)

docx_files = glob.glob(os.path.join(UPLOADS, "**/*.docx"), recursive=True)
docx_files = [f for f in docx_files if "__MACOSX" not in f]

print(f"Subject: {args.subject}")
print(f"Found {len(docx_files)} DOCX files to convert")

LIBREOFFICE_CANDIDATES = [
    "libreoffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    "/usr/bin/libreoffice",
    "/usr/local/bin/libreoffice",
]

def find_libreoffice():
    import shutil
    for candidate in LIBREOFFICE_CANDIDATES:
        if shutil.which(candidate) or os.path.exists(candidate):
            return candidate
    return None

LIBREOFFICE = find_libreoffice()

for docx in sorted(docx_files):
    pdf_path = os.path.splitext(docx)[0] + ".pdf"
    if os.path.exists(pdf_path):
        print(f"  SKIP (PDF exists): {os.path.basename(docx)}")
        continue
    if not LIBREOFFICE:
        print(f"  ERROR: LibreOffice not found, cannot convert {os.path.basename(docx)}")
        continue
    print(f"  Converting: {docx}")
    outdir = os.path.dirname(docx)
    result = subprocess.run(
        [LIBREOFFICE, "--headless", "--convert-to", "pdf", "--outdir", outdir, docx],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        print(f"    ERROR: {result.stderr.strip()}")
    elif os.path.exists(pdf_path):
        print(f"    OK -> {os.path.basename(pdf_path)}")
    else:
        print(f"    WARNING: PDF not created, check output: {result.stdout.strip()}")

print("Done.")
