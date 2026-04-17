import requests
import pdfplumber
import hashlib
import os
import re
import json
import datetime
import difflib
from openai import OpenAI
PDF_URL = "https://www.naredco.in/notification/pdfs/Bangalore-Building-Byelaws.pdf"
PDF_FILE = "Bangalore-Building-Byelaws.pdf"
TEXT_FILE = "Bangalore-Building-Byelaws.txt"
JSON_FILE = "structured_sections.json"


# ---------------------------
# STEP 1: Download PDF
# ---------------------------
def download_pdf(url, filename):
    print("Downloading PDF...")
    response = requests.get(url)

    if response.status_code == 200:
        with open(filename, "wb") as f:
            f.write(response.content)
        print("Download complete.")
    else:
        print("Failed to download PDF.")
        print("Status Code:", response.status_code)


# ---------------------------
# STEP 2: Extract Text
# ---------------------------
def extract_text_from_pdf(filename):
    print("Extracting text...")
    full_text = ""

    with pdfplumber.open(filename) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text += text + "\n"

    print("Extraction complete.")
    return full_text

def generate_section_hash(content):
    normalized = re.sub(r'\s+', ' ', content).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

SECTION_HASH_FILE = "section_hashes.json"

def show_text_diff(old_text, new_text):
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()

    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        lineterm='',
        fromfile='OLD',
        tofile='NEW'
    )

    return "\n".join(diff)

def detect_section_changes(sections):

    new_hash_map = {}

    for sec in sections:
        section_id = f"{sec['chapter']}|{sec['section_number']}"
        content_hash = generate_section_hash(sec["content"])
        new_hash_map[section_id] = {
            "chapter": sec["chapter"],
            "title": sec["title"],
            "hash": content_hash,
            "content": sec["content"]
        }

    # First run case
    if not os.path.exists(SECTION_HASH_FILE):
        print("No previous section snapshot found. Saving current snapshot.")
        with open(SECTION_HASH_FILE, "w", encoding="utf-8") as f:
            json.dump(new_hash_map, f, indent=4)
        return

    # Load old snapshot
    with open(SECTION_HASH_FILE, "r", encoding="utf-8") as f:
        old_hash_map = json.load(f)

    added = []
    modified = []
    removed = []

    # Detect added & modified
    for section_id, data in new_hash_map.items():
        if section_id not in old_hash_map:
            added.append(section_id)
        elif old_hash_map[section_id]["hash"] != data["hash"]:
            modified.append(section_id)

            print(f"\n🔎 Changes in Section {section_id}")
            print(f"Title: {data['title']}")
            print("-" * 50)

            old_content = old_hash_map[section_id]["content"]
            new_content = data["content"]

            # 1️⃣ Show text diff
            diff_output = show_text_diff(old_content, new_content)
            print(diff_output)

            # 2️⃣ Generate AI summary
            summary = generate_ai_summary(old_content, new_content)

            print("\n" + "=" * 80)
            print(f"📘 SECTION: {section_id}")
            print(f"📌 TITLE: {data['title']}")
            print("=" * 80)

            print("\n🧠 AI CHANGE SUMMARY:\n")
            print(summary)

            print("\n🔍 RAW TEXT DIFF:\n")
            print(diff_output)
            print("=" * 80)

    # Detect removed
    for section_id in old_hash_map:
        if section_id not in new_hash_map:
            removed.append(section_id)

    # Print results
    if not added and not modified and not removed:
        print("No section-level changes detected.")
    else:
        print("\n🚨 SECTION LEVEL CHANGES DETECTED\n")

        if added:
            print("New Sections Added:", added)

        if modified:
            print("Modified Sections:", modified)

        if removed:
            print("Removed Sections:", removed)

    # Save new snapshot
    with open(SECTION_HASH_FILE, "w", encoding="utf-8") as f:
        json.dump(new_hash_map, f, indent=4)
# ---------------------------
# STEP 3: Structure Text
# ---------------------------
def structure_document(text):

    text = re.sub(r'\r', '', text)

    # Match PART headings like:
    # PART I
    part_pattern = r'PART\s+[IVXLC\d]+'

    part_matches = list(re.finditer(part_pattern, text, re.IGNORECASE))

    # Section pattern: 1.0 1.1 2.3.4 etc.
    section_pattern = r'\n(\d+(\.\d+)*\.?)\s'

    section_matches = list(re.finditer(section_pattern, text))

    structured_sections = []
    current_part = "PRELIMINARY"
    part_index = 0

    for i in range(len(section_matches)):

        section_start = section_matches[i].start()
        section_number = section_matches[i].group(1).rstrip('.')

        # Update PART if needed
        while (
            part_index < len(part_matches)
            and part_matches[part_index].start() < section_start
        ):
            part_line = part_matches[part_index].group(0)

            # Get next line after PART I
            part_end_pos = part_matches[part_index].end()
            remaining_text = text[part_end_pos:].strip().split('\n')

            if remaining_text:
                part_title = remaining_text[0].strip()
                current_part = f"{part_line} - {part_title}"
            else:
                current_part = part_line

            part_index += 1

        if i + 1 < len(section_matches):
            section_end = section_matches[i + 1].start()
        else:
            section_end = len(text)

        section_text = text[section_start:section_end].strip()

        # Extract title (first line)
        first_line = section_text.split('\n')[0]
        title = re.sub(r'^(\d+(\.\d+)*\.?)\s*', '', first_line)

        structured_sections.append({
            "chapter": current_part,
            "section_number": section_number,
            "title": title.strip(),
            "content": section_text.strip()
        })

    return structured_sections

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def generate_ai_summary(old_text, new_text):

    prompt = f"""
You are a regulatory analyst helping architects.

Below is the OLD and NEW version of a building bylaw section.

1. Summarize what changed.
2. Explain practical impact.
3. Classify impact as: LOW, MEDIUM, or HIGH.
4. Keep it under 4 sentences.

OLD VERSION:
{old_text}

NEW VERSION:
{new_text}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",  # cheaper + good enough
        messages=[
            {"role": "system", "content": "You are a precise regulatory change summarizer."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2
    )

    return response.choices[0].message.content.strip()
# ---------------------------
# MAIN
# ---------------------------
if __name__ == "__main__":

    # Download if needed
    if not os.path.exists(PDF_FILE):
        download_pdf(PDF_URL, PDF_FILE)
    else:
        print("PDF already exists. Skipping download.")
    # Extract text
    extracted_text = extract_text_from_pdf(PDF_FILE)
    # Save raw text (optional but useful)
    with open(TEXT_FILE, "w", encoding="utf-8") as f:
        f.write(extracted_text)

    # Structure document
    sections = structure_document(extracted_text)

    print(f"\nTotal Structured Sections Found: {len(sections)}\n")

    # Print first 3 structured sections
    for sec in sections[:3]:
        print("Chapter:", sec["chapter"])
        print("Section:", sec["section_number"])
        print("Title:", sec["title"])
        print("Content Preview:", sec["content"][:300])
        print("=" * 60)

    # Save structured JSON
    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(sections, f, indent=4, ensure_ascii=False)

    print("\nStructured sections saved to structured_sections.json")

    detect_section_changes(sections)