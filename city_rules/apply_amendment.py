"""
apply_amendment.py
──────────────────
Applies approved changes from amendment_diff.json into the target city JSON.
Never overwrites the original — writes to <city_json>_amended.json first.

Works for any city.

Usage:
    python city_rules/apply_amendment.py <diff_file> <city_json_path>

    Example:
        python city_rules/apply_amendment.py city_rules/amendment_diff.json city_rules/hyderabad_hmda.json

Output:
    city_rules/hyderabad_hmda_amended.json  — amended copy (original untouched)

After verifying the output is correct:
    Rename original → hyderabad_hmda_v1_backup.json
    Rename amended  → hyderabad_hmda.json
"""

import sys
import json
from pathlib import Path


def get_nested(data: dict, path: str):
    keys = path.split(".")
    for key in keys:
        if isinstance(data, dict) and key in data:
            data = data[key]
        else:
            return None
    return data


def set_nested(data: dict, path: str, value):
    keys = path.split(".")
    for key in keys[:-1]:
        data = data.setdefault(key, {})
    data[keys[-1]] = value


def main():
    if len(sys.argv) < 3:
        print("Usage: python city_rules/apply_amendment.py <diff_file> <city_json_path>")
        sys.exit(1)

    diff_path = Path(sys.argv[1])
    json_path = Path(sys.argv[2])

    if not diff_path.exists():
        print(f"Diff file not found: {diff_path}")
        sys.exit(1)
    if not json_path.exists():
        print(f"JSON file not found: {json_path}")
        sys.exit(1)

    diff = json.loads(diff_path.read_text(encoding="utf-8"))
    base = json.loads(json_path.read_text(encoding="utf-8"))

    changes     = diff.get("changes", [])
    structural  = diff.get("structural_changes", [])

    approved = [c for c in changes if c.get("approved") is True]
    skipped  = [c for c in changes if c.get("approved") is not True]

    print(f"\nAmendment diff  : {diff_path.name}")
    print(f"Target JSON     : {json_path.name}")
    print(f"Approved changes: {len(approved)}")
    print(f"Skipped (not approved or null): {len(skipped)}")

    applied = []
    errors  = []

    for change in approved:
        path  = change["path"]
        old   = change.get("old")
        new   = change["new"]

        current = get_nested(base, path)

        if current != old:
            print(f"  WARN  {path}: expected old={old!r}, found {current!r} — applying anyway")

        try:
            set_nested(base, path, new)
            applied.append(path)
            print(f"  OK    {path}: {old!r} → {new!r}")
        except Exception as e:
            errors.append({"path": path, "error": str(e)})
            print(f"  ERROR {path}: {e}")

    if structural:
        print(f"\n── STRUCTURAL CHANGES (require manual code update) ──────────")
        for s in structural:
            print(f"  ! {s['description']}")
        print("  These are NOT auto-applied. Update the relevant service file manually.")

    # Write amended JSON (never overwrite original)
    stem    = json_path.stem
    out_path = json_path.parent / f"{stem}_amended.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(base, f, indent=2, ensure_ascii=False)

    print(f"\nAmended JSON written → {out_path}")
    print(f"Applied: {len(applied)}  |  Errors: {len(errors)}")

    if errors:
        print("\nErrors:")
        for e in errors:
            print(f"  {e['path']}: {e['error']}")

    print("\nNext steps:")
    print(f"  1. Verify output in {out_path.name}")
    print(f"  2. Test with POST /planning-<city> to confirm correct values")
    print(f"  3. If correct:")
    print(f"       mv {json_path.name} {stem}_v1_backup.json")
    print(f"       mv {out_path.name} {json_path.name}")


if __name__ == "__main__":
    main()
