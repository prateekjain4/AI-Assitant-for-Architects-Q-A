"""
parse_amendment.py
──────────────────
Uses GPT-4o to compare an amendment PDF's extracted text against the
existing city JSON and produce a structured diff for human review.

Works for any city — pass the target JSON as the second argument.

Usage:
    python city_rules/parse_amendment.py <text_file> <city_json_path>

    Example:
        python city_rules/parse_amendment.py city_rules/amendment_text.txt city_rules/hyderabad_hmda.json
        python city_rules/parse_amendment.py city_rules/amendment_text.txt city_rules/bengaluru_bda.json
        python city_rules/parse_amendment.py city_rules/amendment_text.txt city_rules/ranchi_rmc.json

Output:
    city_rules/amendment_diff.json  — structured diff; open this and set
                                      "approved": true/false on each entry
                                      before running apply_amendment.py
"""

import sys
import json
from datetime import date
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

OUT_PATH = Path(__file__).parent / "amendment_diff.json"

SYSTEM_PROMPT = """You are a building regulations expert helping to merge bylaw amendments into a structured JSON rules file.

You will be given:
1. Amendment text extracted from an official government PDF
2. The current city rules JSON

Your job:
- Identify every numeric or text value in the amendment that differs from (or is absent from) the current JSON
- For each change, produce a JSON entry with the dot-notation path into the current JSON, the old value, the new value, and the exact source text from the amendment
- Classify each change as "value" (safe — JSON edit only) or "structural" (requires code change too, e.g. new zone code, new table row key)
- For structural changes, describe what code file / function also needs updating

Return ONLY valid JSON in this exact schema:
{
  "changes": [
    {
      "path": "zones.R2.far",
      "old": 2.0,
      "new": 2.25,
      "type": "value",
      "source_text": "exact quote from amendment PDF",
      "approved": null
    }
  ],
  "structural_changes": [
    {
      "description": "New zone MU3 added — also update _ZONE_MAP in hyderabad_planning_service.py",
      "type": "structural",
      "details": { "zone_code": "MU3", "far": 3.0, "ground_coverage_pct": 50 },
      "approved": null
    }
  ]
}

If you find no changes, return {"changes": [], "structural_changes": []}.
Do not include any explanation outside the JSON."""


def main():
    if len(sys.argv) < 3:
        print("Usage: python city_rules/parse_amendment.py <text_file> <city_json_path>")
        sys.exit(1)

    text_path = Path(sys.argv[1])
    json_path = Path(sys.argv[2])

    if not text_path.exists():
        print(f"Text file not found: {text_path}")
        sys.exit(1)
    if not json_path.exists():
        print(f"JSON file not found: {json_path}")
        sys.exit(1)

    amendment_text = text_path.read_text(encoding="utf-8")
    current_json   = json_path.read_text(encoding="utf-8")

    print(f"Amendment text : {len(amendment_text):,} chars from {text_path.name}")
    print(f"Target JSON    : {json_path.name}")
    print("Sending to GPT-4o for analysis...")

    client = OpenAI()

    user_prompt = f"""AMENDMENT TEXT (from PDF):
{amendment_text[:12000]}

CURRENT CITY JSON:
{current_json[:12000]}

Identify all changes the amendment makes to the current JSON values. Return only the JSON diff schema."""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content.strip()
    diff = json.loads(raw)

    output = {
        "source_text_file": str(text_path),
        "target_json": str(json_path),
        "generated_at": str(date.today()),
        **diff
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    n_val  = len(diff.get("changes", []))
    n_str  = len(diff.get("structural_changes", []))
    print(f"\nDone. Found {n_val} value change(s) and {n_str} structural change(s).")
    print(f"Review and approve → {OUT_PATH}")
    print("Then run: python city_rules/apply_amendment.py city_rules/amendment_diff.json <city_json_path>")


if __name__ == "__main__":
    main()
