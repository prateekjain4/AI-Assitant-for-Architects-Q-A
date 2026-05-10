"""
fetch_ranchi_bylaws.py
──────────────────────
Downloads all JBBL PDFs from UDHD Jharkhand, extracts text, and uses
Claude Opus 4.7 to structure the rules into JSON files for RMC and RRDA.

Usage:
    python city_rules/fetch_ranchi_bylaws.py

Outputs:
    city_rules/ranchi_rmc.json   (updated — enriched from JBBL 2016 + 2024)
    city_rules/ranchi_rrda.json  (new — RRDA peri-urban jurisdiction)
"""

import io
import json
import re
import sys
import time
from pathlib import Path

import pdfplumber
import requests
import anthropic

OUT_DIR = Path(__file__).parent
RMC_OUT  = OUT_DIR / "ranchi_rmc.json"
RRDA_OUT = OUT_DIR / "ranchi_rrda.json"

# All 7 JBBL PDFs from https://udhd.jharkhand.gov.in/Other/byLaws.aspx
PDFS = [
    ("JBBL_2016_base",           "https://udhd.jharkhand.gov.in/Handlers/Acts.ashx?id=BL06042016060406PM.pdf"),
    ("JBBL_1st_amendment_2017",  "https://udhd.jharkhand.gov.in/Handlers/Acts.ashx?id=BL03102017031020PM.pdf"),
    ("JBBL_2nd_amendment_2017",  "https://udhd.jharkhand.gov.in/Handlers/Acts.ashx?id=BL03102017041042PM.pdf"),
    ("JBBL_low_risk_2019",       "https://udhd.jharkhand.gov.in/Handlers/Acts.ashx?id=BL21052019020510PM.pdf"),
    ("JBBL_5th_amendment_2019",  "https://udhd.jharkhand.gov.in/Handlers/Acts.ashx?id=BL07062019100639AM.pdf"),
    ("JBBL_para14_5_order_2019", "https://udhd.jharkhand.gov.in/Handlers/Acts.ashx?id=BL14062019120656PM.pdf"),
    ("JBBL_10th_amendment_2024", "https://udhd.jharkhand.gov.in/Handlers/Acts.ashx?id=BL18042024030409PM.pdf"),
]

_EXTRACT_SYSTEM = """You are a building regulations data engineer. You extract structured building bylaw data from Indian government PDF text and return it as valid JSON only."""

_RMC_PROMPT = """From the Jharkhand Building Bye-Laws (JBBL) text below, extract all quantitative rules for the RMC (Ranchi Municipal Corporation) urban zone and return a single JSON object with this exact schema. Fill every field with real values from the text. If a value isn't explicitly stated, use null.

Return ONLY valid JSON — no markdown fences, no commentary outside JSON.

Schema:
{
  "_meta": {
    "city": "ranchi",
    "authority": "RMC",
    "document": "Jharkhand Building Bye-Laws 2016 (10th Amendment 2024)",
    "schema_version": "2.0"
  },
  "far": {
    "zones": {
      "district_and_commercial_centre": { "far": <number>, "note": "<string>" },
      "core_inner_zone":                { "far": <number>, "note": "<string>" },
      "general_zone":                   { "far": <number>, "note": "<string>" }
    },
    "road_width_adjustment": "<string — note if FAR varies by road width>"
  },
  "ground_coverage": {
    "plot_upto_1000sqm_ht_upto_16m":  { "max_coverage_pct": <number> },
    "plot_above_1000sqm_ht_above_16m":{ "max_coverage_pct": <number> }
  },
  "height": {
    "height_tiers_m": [<number>, <number>],
    "max_height_by_road_width": {
      "above_12m_requires_min_road_m": <number>,
      "above_16m_requires_min_road_m": <number>
    },
    "plot_width_upto_10m_max_ht_residential_m": <number>,
    "plot_width_upto_10m_max_ht_commercial_m":  <number>,
    "tandem_site_access_below_4.5m_max_ht_m":   <number>
  },
  "setbacks": {
    "residential": {
      "front_rear_by_plot_depth": {
        "upto_10m":  { "ht_upto_12m": {"front":<n>,"rear":<n>}, "ht_12_to_16m": null, "ht_above_16m": null },
        "10_to_15m": { "ht_upto_12m": {"front":<n>,"rear":<n>}, "ht_12_to_16m": {"front":<n>,"rear":<n>}, "ht_above_16m": {"front":<n>,"rear":<n>} },
        "15_to_21m": { "ht_upto_12m": {"front":<n>,"rear":<n>}, "ht_12_to_16m": {"front":<n>,"rear":<n>}, "ht_above_16m": {"front":<n>,"rear":<n>} },
        "21_to_27m": { "ht_upto_12m": {"front":<n>,"rear":<n>}, "ht_12_to_16m": {"front":<n>,"rear":<n>}, "ht_above_16m": {"front":<n>,"rear":<n>} },
        "27_to_33m": { "ht_upto_12m": {"front":<n>,"rear":<n>}, "ht_12_to_16m": {"front":<n>,"rear":<n>}, "ht_above_16m": {"front":<n>,"rear":<n>} },
        "33_to_39m": { "ht_upto_12m": {"front":<n>,"rear":<n>}, "ht_12_to_16m": {"front":<n>,"rear":<n>}, "ht_above_16m": {"front":<n>,"rear":<n>} },
        "39_to_45m": { "ht_upto_12m": {"front":<n>,"rear":<n>}, "ht_12_to_16m": {"front":<n>,"rear":<n>}, "ht_above_16m": {"front":<n>,"rear":<n>} },
        "above_45m": { "ht_upto_12m": {"front":<n>,"rear":<n>}, "ht_12_to_16m": {"front":<n>,"rear":<n>}, "ht_above_16m": {"front":<n>,"rear":<n>} }
      },
      "sides_by_plot_width": {
        "upto_10m":  { "ht_upto_12m":<n>, "ht_12_to_16m": null, "ht_above_16m": null },
        "10_to_15m": { "ht_upto_12m":<n>, "ht_12_to_16m":<n>,  "ht_above_16m":<n>  },
        "15_to_21m": { "ht_upto_12m":<n>, "ht_12_to_16m":<n>,  "ht_above_16m":<n>  },
        "21_to_27m": { "ht_upto_12m":<n>, "ht_12_to_16m":<n>,  "ht_above_16m":<n>  },
        "27_to_33m": { "ht_upto_12m":<n>, "ht_12_to_16m":<n>,  "ht_above_16m":<n>  },
        "33_to_39m": { "ht_upto_12m":<n>, "ht_12_to_16m":<n>,  "ht_above_16m":<n>  },
        "39_to_45m": { "ht_upto_12m":<n>, "ht_12_to_16m":<n>,  "ht_above_16m":<n>  },
        "above_45m": { "ht_upto_12m":<n>, "ht_12_to_16m":<n>,  "ht_above_16m":<n>  }
      },
      "additional_above_22m": {
        "22_to_28m": { "extra_front":<n>, "extra_rear":<n>, "extra_side":<n> },
        "28_to_34m": { "extra_front":<n>, "extra_rear":<n>, "extra_side":<n> },
        "above_34m": { "extra_front":<n>, "extra_rear":<n>, "extra_side":<n> }
      }
    },
    "commercial": {
      "front_rear_by_plot_depth": { <same structure as residential> },
      "sides_by_plot_width":       { <same structure as residential> }
    }
  },
  "fire_safety": {
    "special_building_height_threshold_m": <number>,
    "special_building_coverage_threshold_sqm": <number>,
    "fire_noc_required_above_height": true,
    "fire_noc_required_above_coverage": true,
    "fire_lift_above_height_m": <number or null>,
    "sprinkler_above_height_m": <number or null>
  },
  "lifts_and_stairs": {
    "lift_mandatory_above_floors": <number>,
    "stair_min_width_up_to_4_floors_m": <number>,
    "stair_min_width_above_4_floors_m": <number>
  },
  "parking": {
    "residential_per_unit": { "cars": <number>, "two_wheelers": <number> },
    "commercial_per_100sqm": { "cars": <number>, "two_wheelers": <number> },
    "visitor_pct": <number or null>
  },
  "landscape": {
    "trees_upto_250sqm": "<string>",
    "trees_250_to_1000sqm": "<string>",
    "trees_above_1000sqm": "<string or number>"
  },
  "accessibility": {
    "mandatory_above_sqm": <number or null>,
    "ramp_gradient": "<string or null>",
    "notes": "<string or null>"
  },
  "basement": {
    "counted_in_far": false,
    "same_setbacks_as_superstructure": true,
    "permitted_uses": ["<string>"],
    "notes": "<string>"
  }
}

JBBL TEXT:
"""

_RRDA_PROMPT = """From the Jharkhand Building Bye-Laws (JBBL) text below, extract rules specifically for RRDA (Ranchi Regional Development Authority) peri-urban areas — the 268 villages in Angara, Kanke, Ratu, Nagri, Namkum, and Ormanjhi circles around Ranchi.

RRDA areas are peri-urban/transitional zones with typically lower density than RMC urban areas. Extract whatever RRDA-specific rules exist, and where the text is ambiguous, apply conservative (lower-density) interpretation.

Return a JSON object with the SAME schema structure as the RMC rules but with RRDA-appropriate values. Set "_meta.authority" to "RRDA".

Return ONLY valid JSON — no markdown fences, no commentary.

JBBL TEXT:
"""


def download_pdf(name: str, url: str) -> bytes | None:
    print(f"  Downloading {name}...")
    try:
        r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        return r.content
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        return None


def extract_text_from_bytes(pdf_bytes: bytes) -> str:
    pages = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            text = page.extract_text()
            if text:
                pages.append(f"--- PAGE {i} ---\n{text}")
    return "\n\n".join(pages)


def ask_claude(client: anthropic.Anthropic, system: str, prompt: str) -> dict:
    with client.messages.stream(
        model="claude-opus-4-7",
        max_tokens=8000,
        thinking={"type": "adaptive"},
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        response = stream.get_final_message()

    raw = next(b.text for b in response.content if b.type == "text").strip()
    raw = re.sub(r"^```json\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"^```\s*",     "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```$",     "", raw, flags=re.MULTILINE)
    return json.loads(raw)


def main():
    import os
    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set in .env")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key, max_retries=3)

    # ── Download all PDFs ─────────────────────────────────────────────────────
    print("\n📥 Downloading JBBL PDFs from UDHD Jharkhand...")
    all_text_parts = []
    for name, url in PDFS:
        pdf_bytes = download_pdf(name, url)
        if pdf_bytes:
            text = extract_text_from_bytes(pdf_bytes)
            all_text_parts.append(f"=== {name} ===\n{text}")
            print(f"  ✓ {name}: {len(text):,} chars extracted")
        time.sleep(1)  # polite crawl delay

    if not all_text_parts:
        print("ERROR: Could not download any PDFs. Check network/URLs.")
        sys.exit(1)

    # Combine all text (keep under 80k chars for Claude context)
    combined_text = "\n\n".join(all_text_parts)
    if len(combined_text) > 80_000:
        combined_text = combined_text[:80_000]
        print(f"  ℹ Text truncated to 80k chars for Claude context")

    print(f"\n📄 Total extracted text: {len(combined_text):,} chars from {len(all_text_parts)} PDFs")

    # ── Extract RMC rules ─────────────────────────────────────────────────────
    print("\n🤖 Extracting RMC rules with Claude Opus 4.7...")
    try:
        rmc_data = ask_claude(client, _EXTRACT_SYSTEM, _RMC_PROMPT + combined_text)
        # Ensure meta is correct
        rmc_data["_meta"] = {
            "city": "ranchi",
            "authority": "RMC",
            "document": "Jharkhand Building Bye-Laws 2016 (10th Amendment 2024)",
            "schema_version": "2.0",
            "source": "https://udhd.jharkhand.gov.in/Other/byLaws.aspx"
        }
        with open(RMC_OUT, "w", encoding="utf-8") as f:
            json.dump(rmc_data, f, indent=2, ensure_ascii=False)
        print(f"  ✓ Saved {RMC_OUT} ({len(json.dumps(rmc_data))} chars)")
    except Exception as e:
        print(f"  ✗ RMC extraction failed: {e}")

    # ── Extract RRDA rules ────────────────────────────────────────────────────
    print("\n🤖 Extracting RRDA rules with Claude Opus 4.7...")
    try:
        rrda_data = ask_claude(client, _EXTRACT_SYSTEM, _RRDA_PROMPT + combined_text)
        rrda_data["_meta"] = {
            "city": "ranchi",
            "authority": "RRDA",
            "document": "Jharkhand Building Bye-Laws 2016 (10th Amendment 2024) — RRDA Jurisdiction",
            "schema_version": "2.0",
            "jurisdiction": "268 peri-urban villages: Angara, Kanke, Ratu, Nagri, Namkum, Ormanjhi circles",
            "source": "https://udhd.jharkhand.gov.in/Other/byLaws.aspx"
        }
        with open(RRDA_OUT, "w", encoding="utf-8") as f:
            json.dump(rrda_data, f, indent=2, ensure_ascii=False)
        print(f"  ✓ Saved {RRDA_OUT} ({len(json.dumps(rrda_data))} chars)")
    except Exception as e:
        print(f"  ✗ RRDA extraction failed: {e}")

    print("\n✅ Done. Review the generated JSON files before deploying.")
    print(f"   {RMC_OUT}")
    print(f"   {RRDA_OUT}")


if __name__ == "__main__":
    main()