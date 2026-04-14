"""
extract_rules.py
────────────────
Queries the /ask endpoint for every rule in bengaluru.json,
then compares the extracted values against the current JSON.

Usage:
    python city_rules/extract_rules.py

Output:
    city_rules/extraction_results.json  — raw GPT answers per question
    city_rules/diff_report.txt          — human-readable diff vs bengaluru.json

Run this:
  1. Once now to get a baseline extraction
  2. Every time the BBMP bylaw PDF is updated (via /check-updates)
  3. Review the diff_report.txt and update bengaluru.json manually
"""

import json
import requests
import re
from datetime import datetime
from pathlib import Path

BASE_URL  = "http://localhost:8000"
RULES_DIR = Path(__file__).parent
JSON_PATH = RULES_DIR / "bengaluru.json"
OUT_PATH  = RULES_DIR / "extraction_results.json"
DIFF_PATH = RULES_DIR / "diff_report.txt"


# ── Questions to ask the /ask endpoint ───────────────────────────────
# Each entry: { "key": identifier, "question": what to ask, "parse": how to extract number }

EXTRACTION_QUERIES = [

    # ── FAR ──────────────────────────────────────────────────────────
    {
        "key": "far.R.9",
        "question": "What is the Floor Area Ratio (FAR) for R residential zone on a road width up to 9 metres in Bangalore BBMP bylaws?",
        "expect": 1.50
    },
    {
        "key": "far.R.12",
        "question": "What is the FAR for R residential zone on a 12 metre road in Bangalore BBMP bylaws?",
        "expect": 1.75
    },
    {
        "key": "far.R.24",
        "question": "What is the FAR for R residential zone on a 24 metre road in Bangalore BBMP bylaws?",
        "expect": 2.25
    },
    {
        "key": "far.R.9999",
        "question": "What is the maximum FAR for R residential zone on roads above 30 metres in Bangalore?",
        "expect": 2.50
    },
    {
        "key": "far.C1.24",
        "question": "What is the FAR for C1 commercial zone on a 24 metre road in Bangalore BBMP bylaws?",
        "expect": 2.50
    },
    {
        "key": "far.C1.9999",
        "question": "What is the FAR for C1 commercial zone on roads above 30 metres in Bangalore?",
        "expect": 3.25
    },
    {
        "key": "far.C2.9999",
        "question": "What is the maximum FAR for C2 commercial zone in Bangalore BBMP bylaws?",
        "expect": 3.50
    },
    {
        "key": "far.IT.9999",
        "question": "What is the FAR for IT zone on wide roads in Bangalore BBMP bylaws?",
        "expect": 3.00
    },

    # ── Ground Coverage ───────────────────────────────────────────────
    {
        "key": "ground_coverage.R.12",
        "question": "What is the maximum ground coverage percentage for R zone on roads up to 12 metres in Bangalore BBMP bylaws?",
        "expect": 70
    },
    {
        "key": "ground_coverage.R.24",
        "question": "What is the maximum ground coverage percentage for R zone on a 24 metre road in Bangalore?",
        "expect": 60
    },
    {
        "key": "ground_coverage.C1.24",
        "question": "What is the maximum ground coverage percentage for C1 commercial zone on a 24 metre road in Bangalore?",
        "expect": 55
    },
    {
        "key": "ground_coverage.IT.9999",
        "question": "What is the ground coverage percentage for IT zone on wide roads in Bangalore BBMP bylaws?",
        "expect": 40
    },

    # ── Setbacks ─────────────────────────────────────────────────────
    {
        "key": "setbacks.small_plot.front",
        "question": "What is the front setback required for small residential plots below 1500 sqft in Bangalore BBMP bylaws?",
        "expect": 3.0
    },
    {
        "key": "setbacks.standard_plot.front",
        "question": "What is the front setback required for plots above 1500 sqft in Bangalore BBMP bylaws?",
        "expect": 4.0
    },
    {
        "key": "setbacks.standard_plot.side",
        "question": "What is the side setback for standard plots in Bangalore BBMP bylaws?",
        "expect": 1.5
    },
    {
        "key": "setbacks.standard_plot.rear",
        "question": "What is the rear setback for standard plots in Bangalore BBMP bylaws?",
        "expect": 2.0
    },
    {
        "key": "setbacks.high_rise_threshold_m",
        "question": "At what building height do setbacks increase to 5 metres on all sides in Bangalore BBMP bylaws?",
        "expect": 11.5
    },
    {
        "key": "setbacks.high_rise.all_sides",
        "question": "What is the required setback on all sides for buildings above 11.5 metres in Bangalore?",
        "expect": 5.0
    },

    # ── Fire NOC ─────────────────────────────────────────────────────
    {
        "key": "fire_noc.height_threshold_m",
        "question": "At what building height is a Fire NOC from KSFES mandatory in Bangalore?",
        "expect": 15.0
    },
    {
        "key": "fire_noc.strict_height_m",
        "question": "At what building height are stricter fire requirements like fire command centre and refuge area mandatory in Bangalore?",
        "expect": 24.0
    },
    {
        "key": "fire_noc.commercial_bua_threshold_sqm",
        "question": "What is the minimum built-up area for commercial buildings that triggers mandatory Fire NOC in Bangalore regardless of height?",
        "expect": 500
    },

    # ── Staircase & Lift ─────────────────────────────────────────────
    {
        "key": "staircase.below_high_rise_min_width_m",
        "question": "What is the minimum staircase width for buildings below 11.5 metres in Bangalore BBMP bylaws?",
        "expect": 1.0
    },
    {
        "key": "staircase.above_high_rise_min_width_m",
        "question": "What is the minimum staircase width for buildings above 11.5 metres in Bangalore?",
        "expect": 1.2
    },
    {
        "key": "staircase.lift_mandatory_above_floors",
        "question": "Above how many floors is a lift mandatory in Bangalore BBMP bylaws?",
        "expect": 4
    },
    {
        "key": "staircase.dual_staircase_bua_threshold_sqft",
        "question": "What is the minimum built-up area that requires two staircases in Bangalore BBMP bylaws?",
        "expect": 2000
    },

    # ── Basement ─────────────────────────────────────────────────────
    {
        "key": "basement.max_depth_m",
        "question": "What is the maximum permitted depth for a basement in Bangalore BBMP bylaws?",
        "expect": 3.6
    },
    {
        "key": "basement.max_number",
        "question": "How many basement levels are permitted under BBMP bylaws in Bangalore?",
        "expect": 2
    },

    # ── Projections ───────────────────────────────────────────────────
    {
        "key": "projections.balcony_max_projection_m",
        "question": "What is the maximum allowed balcony projection in Bangalore BBMP bylaws?",
        "expect": 1.5
    },
    {
        "key": "projections.chajja_max_projection_m",
        "question": "What is the maximum projection for a chajja or sun shade in Bangalore BBMP bylaws?",
        "expect": 0.75
    },
    {
        "key": "projections.balcony_far_exclusion_max_pct_of_floor_area",
        "question": "What percentage of floor area can balconies occupy to be excluded from FAR calculation in Bangalore?",
        "expect": 20
    },

    # ── Parking ───────────────────────────────────────────────────────
    {
        "key": "parking.residential.car_per_unit_sqm",
        "question": "How many square metres per car parking space is required for residential buildings per BBMP Table 23?",
        "expect": 50
    },
    {
        "key": "parking.commercial.car_per_100sqm",
        "question": "How many car parking spaces are required per 100 sqm for commercial buildings per BBMP Table 23?",
        "expect": 3
    },
]


def ask_endpoint(question: str) -> dict:
    """Call the /ask endpoint and return the full response."""
    try:
        resp = requests.post(
            f"{BASE_URL}/ask",
            json={"question": question},
            timeout=30
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e), "answer": ""}


def extract_first_number(text: str):
    """Pull the first numeric value (int or float) from a text string."""
    match = re.search(r'\b(\d+\.?\d*)\b', text)
    if match:
        val = match.group(1)
        return float(val) if '.' in val else int(val)
    return None


def run_extraction() -> list:
    """Run all queries against /ask and return results."""
    results = []
    total = len(EXTRACTION_QUERIES)

    print(f"\nRunning {total} extraction queries against {BASE_URL}/ask ...\n")

    for i, q in enumerate(EXTRACTION_QUERIES, 1):
        print(f"  [{i:02d}/{total}] {q['key']} ... ", end="", flush=True)

        response = ask_endpoint(q["question"])
        answer_text = response.get("answer", "")
        extracted = extract_first_number(answer_text)

        match = None
        if extracted is not None and q.get("expect") is not None:
            match = abs(float(extracted) - float(q["expect"])) < 0.01

        status = "✓ MATCH" if match is True else ("✗ MISMATCH" if match is False else "? NO NUMBER")
        print(status)

        results.append({
            "key":       q["key"],
            "question":  q["question"],
            "expected":  q.get("expect"),
            "extracted": extracted,
            "match":     match,
            "raw_answer": answer_text[:300],   # first 300 chars for review
        })

    return results


def build_diff_report(results: list) -> str:
    """Generate a human-readable diff report."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "=" * 70,
        f"BBMP BYLAW EXTRACTION REPORT — {now}",
        f"Source: {BASE_URL}/ask  |  Reference: bengaluru.json",
        "=" * 70,
        "",
    ]

    mismatches = [r for r in results if r["match"] is False]
    no_numbers = [r for r in results if r["match"] is None]
    matches    = [r for r in results if r["match"] is True]

    lines += [
        f"SUMMARY",
        f"  Matched  : {len(matches)} / {len(results)}",
        f"  Mismatch : {len(mismatches)}  ← NEEDS HUMAN REVIEW",
        f"  No number found : {len(no_numbers)}  ← check bylaw PDF manually",
        "",
    ]

    if mismatches:
        lines += ["─" * 70, "MISMATCHES — verify these values in the BBMP PDF", "─" * 70, ""]
        for r in mismatches:
            lines += [
                f"  Rule     : {r['key']}",
                f"  JSON has : {r['expected']}",
                f"  GPT says : {r['extracted']}",
                f"  Answer   : {r['raw_answer'][:200]}",
                "",
            ]

    if no_numbers:
        lines += ["─" * 70, "NO NUMBER EXTRACTED — bylaw text found but value unclear", "─" * 70, ""]
        for r in no_numbers:
            lines += [
                f"  Rule   : {r['key']}",
                f"  Answer : {r['raw_answer'][:200]}",
                "",
            ]

    if matches:
        lines += ["─" * 70, "CONFIRMED MATCHES", "─" * 70, ""]
        for r in matches:
            lines += [f"  ✓  {r['key']} = {r['expected']}"]

    lines += [
        "",
        "=" * 70,
        "ACTION REQUIRED:",
        "  1. Open the BBMP RMP PDF and verify every MISMATCH above.",
        "  2. For NO NUMBER entries, locate the value manually in the PDF.",
        "  3. Update city_rules/bengaluru.json with confirmed values.",
        "  4. Set 'last_verified' and 'verified_by' in the _meta block.",
        "=" * 70,
    ]

    return "\n".join(lines)


def main():
    # ── Run extraction ────────────────────────────────────────────────
    results = run_extraction()

    # ── Save raw results ──────────────────────────────────────────────
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nRaw results saved → {OUT_PATH}")

    # ── Build and save diff report ────────────────────────────────────
    report = build_diff_report(results)
    with open(DIFF_PATH, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"Diff report saved → {DIFF_PATH}")

    # ── Print summary to console ──────────────────────────────────────
    mismatches = sum(1 for r in results if r["match"] is False)
    no_number  = sum(1 for r in results if r["match"] is None)
    matched    = sum(1 for r in results if r["match"] is True)

    print(f"\n{'='*50}")
    print(f"  Matched  : {matched}")
    print(f"  Mismatch : {mismatches}  ← open diff_report.txt")
    print(f"  No value : {no_number}")
    print(f"{'='*50}")
    print(f"\nNext step: open diff_report.txt and verify mismatches against the BBMP PDF.\n")


if __name__ == "__main__":
    main()