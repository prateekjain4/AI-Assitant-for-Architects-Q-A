"""
extract_amendment.py
────────────────────
Extracts plain text from a bylaw amendment PDF.
Works for any city — completely city-agnostic.

Usage:
    python city_rules/extract_amendment.py <pdf_path>

Output:
    amendment_text.txt  — extracted text saved in city_rules/
    Also prints a preview to console.
"""

import sys
import pdfplumber
from pathlib import Path

OUT_PATH = Path(__file__).parent / "amendment_text.txt"


def extract_text(pdf_path: str) -> str:
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            text = page.extract_text()
            if text:
                pages.append(f"--- PAGE {i} ---\n{text}")
    return "\n\n".join(pages)


def main():
    if len(sys.argv) < 2:
        print("Usage: python city_rules/extract_amendment.py <pdf_path>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    print(f"Extracting text from: {pdf_path}")

    text = extract_text(pdf_path)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(text)

    print(f"Saved {len(text):,} characters → {OUT_PATH}")
    print("\n── PREVIEW (first 1000 chars) ──────────────────────────")
    print(text[:1000])


if __name__ == "__main__":
    main()
