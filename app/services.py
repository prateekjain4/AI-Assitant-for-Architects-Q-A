import requests
import pdfplumber
import hashlib
import os
import re
import json
import datetime
import difflib
from openai import OpenAI
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer

VECTOR_INDEX_FILE = "data/bylaw_index.faiss"
METADATA_FILE = "data/section_metadata.json"
TEXT_FILE = "Bangalore-Building-Byelaws.txt"
JSON_FILE = "data/structured_sections.json"
SECTION_HASH_FILE = "data/section_hashes.json"

PDF_SOURCES = [
    {
        "name": "bbmp_bylaws",
        "category": "bylaws",
        "url": "https://www.naredco.in/notification/pdfs/Bangalore-Building-Byelaws.pdf",
        "file": "Bangalore-Building-Byelaws.pdf"
    },
    {
        "name": "zoning_regulations",
        "category": "zoning",
        "url": "https://data-opencity.sgp1.cdn.digitaloceanspaces.com/Documents/Recent/Bengaluru-BDA-RMP-2031-Volume_6_Zoning_Regulations.pdf",
        "file": "BDA_Zoning_Regulations.pdf"
    },
    {
        "name": "fire_safety",
        "category": "fire",
        "url": "https://fireandsafetyequipments.com/wp-content/uploads/2018/09/NBC2016-Part-IV.pdf",
        "file": "NBC2016_Fire_Safety.pdf"
    }
]

model = SentenceTransformer("all-MiniLM-L6-v2")
# Initialize change_report at module level
change_report = {}

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
    global change_report
    new_hash_map = {}
    change_report = {
        "added": [],
        "modified": [],
        "removed": []
    }
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

    # Detect added & modified
    for section_id, data in new_hash_map.items():
        if section_id not in old_hash_map:
            change_report["added"].append(section_id)
        elif old_hash_map[section_id]["hash"] != data["hash"]:

            old_content = old_hash_map[section_id]["content"]
            new_content = data["content"]

            # Generate AI summary first
            summary = generate_ai_summary(old_content, new_content)

            change_report["modified"].append({
                "section_id": section_id,
                "title": data["title"],
                "summary": summary
            })

    # Detect removed
    for section_id in old_hash_map:
        if section_id not in new_hash_map:
            change_report["removed"].append(section_id)

    # Print results
    # if not added and not modified and not removed:
    #     print("No section-level changes detected.")
    # else:
    #     print("\n🚨 SECTION LEVEL CHANGES DETECTED\n")

    #     if added:
    #         print("New Sections Added:", added)

    #     if modified:
    #         print("Modified Sections:", modified)

    #     if removed:
    #         print("Removed Sections:", removed)

    # Save new snapshot
    with open(SECTION_HASH_FILE, "w", encoding="utf-8") as f:
        json.dump(new_hash_map, f, indent=4)
    return change_report
# ---------------------------
# STEP 3: Structure Text
# ---------------------------
def structure_document(text, source, category):

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
            "source": source,
            "category": category,
            "chapter": current_part,
            "section_number": section_number,
            "title": title.strip(),
            "content": section_text.strip()
        })
    return structured_sections

def build_vector_index(sections):

    print("Building vector index...")

    embeddings = []
    metadata = []

    for sec in sections:
        text = sec["content"]

        embedding = model.encode(text)

        embeddings.append(embedding)

        metadata.append({
            "source": sec["source"],
            "category": sec["category"],
            "chapter": sec["chapter"],
            "section_number": sec["section_number"],
            "title": sec["title"],
            "content": sec["content"]
        })

    embeddings = np.array(embeddings).astype("float32")

    dimension = embeddings.shape[1]

    index = faiss.IndexFlatL2(dimension)

    index.add(embeddings)

    os.makedirs("data", exist_ok=True)

    faiss.write_index(index, VECTOR_INDEX_FILE)

    with open(METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump(metadata, f)

    print("Vector index saved.")

def classify_question(question):

    q = question.lower()

    if any(word in q for word in [
        "fire", "exit", "sprinkler", "evacuation",
        "fire lift", "fire safety", "smoke detector"
    ]):
        return "fire"

    if any(word in q for word in [
        "zone", "zoning", "far", "fsi", "floor area ratio",
        "land use", "residential zone", "commercial zone"
    ]):
        return "zoning"

    return "bylaws"

def get_openai_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set.")
    return OpenAI(api_key=api_key)


def generate_ai_summary(old_text, new_text):

    client = get_openai_client()   # ✅ create client here

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
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a precise regulatory change summarizer."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2
    )

    return response.choices[0].message.content.strip()

def extract_plot_info(question):

    zone = None
    road_width = None

    zone_match = re.search(r'\bR\d\b', question.upper())
    if zone_match:
        zone = zone_match.group(0)

    road_match = re.search(r'(\d+)\s*m', question.lower())
    if road_match:
        road_width = int(road_match.group(1))

    return zone, road_width

def get_far_from_rules(zone, road_width):

    if not os.path.exists("data/zoning_rules.json"):
        return None

    with open("data/zoning_rules.json") as f:
        rules = json.load(f)

    for rule in rules:

        if rule["zone"] == zone:

            if rule["road_min"] <= road_width < rule["road_max"]:
                return rule["far"]

    return None


def answer_question_from_bylaws(question):

    if not os.path.exists(METADATA_FILE):
        return {"error": "Metadata not found. Run /check-updates first."}

    # Load sections first
    with open(METADATA_FILE, "r", encoding="utf-8") as f:
        sections = json.load(f)

    # Classify question
    category = classify_question(question)

    # Filter sections by category
    candidate_sections = [
        sec for sec in sections
        if sec.get("category") == category
    ]

    if not candidate_sections:
        return {"error": f"No sections found for category {category}"}

    # Prepare texts
    candidate_texts = [sec["content"] for sec in candidate_sections]

    # Encode embeddings
    candidate_embeddings = model.encode(candidate_texts)

    candidate_embeddings = np.array(candidate_embeddings).astype("float32")

    dimension = candidate_embeddings.shape[1]

    temp_index = faiss.IndexFlatL2(dimension)

    temp_index.add(candidate_embeddings)

    # Query embedding
    query_embedding = model.encode(question)

    query_embedding = np.array([query_embedding]).astype("float32")

    zone, road_width = extract_plot_info(question)

    if zone and road_width:

        far = get_far_from_rules(zone, road_width)

        if far:
            return {
                "question": question,
                "answer": f"For zone {zone} with road width {road_width}m, the permissible FAR is {far} according to BDA RMP 2031 zoning regulations.",
                "sources": ["BDA RMP 2031 Zoning Regulations"]
            }
    

    # Search
    k = 10
    distances, indices = temp_index.search(query_embedding, k)

    relevant_sections = []

    for idx in indices[0]:
        relevant_sections.append(candidate_sections[idx])

    context_text = "\n\n".join([
        f"Source: {sec.get('source','unknown')} | {sec['chapter']} - Section {sec['section_number']}:\n{sec['content']}"
        for sec in relevant_sections
    ])

    client = get_openai_client()

    prompt = f"""
You are a regulatory assistant helping architects understand building bylaws.

The question belongs to category: {category}

Answer ONLY using the provided sections.

If relevant information exists, explain it clearly.
Only say "Not specified" if no relevant rule exists.

Relevant Sections:
{context_text}

Question:
{question}

Provide the answer clearly and cite the section number.
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a precise regulatory assistant."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2
    )

    return {
        "question": question,
        "answer": response.choices[0].message.content.strip(),
        "sources": relevant_sections
    }

def run_full_pipeline():

    all_sections = []

    for pdf in PDF_SOURCES:

        if not os.path.exists(pdf["file"]):
            download_pdf(pdf["url"], pdf["file"])

        extracted_text = extract_text_from_pdf(pdf["file"])

        sections = structure_document(extracted_text, pdf["name"], pdf["category"])

        all_sections.extend(sections)

    changes = detect_section_changes(all_sections)

    os.makedirs("data", exist_ok=True)

    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(all_sections, f, indent=4, ensure_ascii=False)

    build_vector_index(all_sections)

    return {
        "status": "completed",
        "total_sections": len(all_sections),
        "changes": changes
    }