#!/usr/bin/env python3
"""Convert all .docx files in uploads/ to PDF using LibreOffice headless."""

import os
import subprocess
import glob

UPLOADS = "/home/ubuntu/webpage/uploads"

docx_files = glob.glob(os.path.join(UPLOADS, "**/*.docx"), recursive=True)
docx_files = [f for f in docx_files if "__MACOSX" not in f]

print(f"Found {len(docx_files)} DOCX files to convert")

for docx in sorted(docx_files):
    pdf_path = os.path.splitext(docx)[0] + ".pdf"
    if os.path.exists(pdf_path):
        print(f"  SKIP (PDF exists): {os.path.basename(docx)}")
        continue
    print(f"  Converting: {docx}")
    outdir = os.path.dirname(docx)
    result = subprocess.run(
        ["libreoffice", "--headless", "--convert-to", "pdf", "--outdir", outdir, docx],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        print(f"    ERROR: {result.stderr.strip()}")
    elif os.path.exists(pdf_path):
        print(f"    OK -> {os.path.basename(pdf_path)}")
    else:
        print(f"    WARNING: PDF not created, check output: {result.stdout.strip()}")

print("Done.")
