"""Generate output/level1.csv and output/level2.csv from a folder of bill images.

Usage (run from the source/ folder):
    python run.py --input ../data/test --output ../output

--input folder must contain: bills/ (images) and csv/level1.csv, csv/level2.csv (templates).
Results are cached in .cache/ so a re-run does not repeat API calls (use --fresh to ignore the cache).
"""
import argparse
import csv
import json
import os

from src.extract import empty_bill, extract_bill
from src.facts import extract_history, facts_text
from src.fixes import fix_bill
from src.qa import FALLBACK, answer_bill

CACHE = ".cache"


def find_image(bills_dir, bill_id):
    for ext in (".png", ".jpg", ".jpeg", ".PNG", ".JPG", ".JPEG"):
        p = os.path.join(bills_dir, bill_id + ext)
        if os.path.exists(p):
            return p
    return None


def cached(name, fresh, fn):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name + ".json")
    if not fresh and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    result = fn()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    return result


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        return r.fieldnames, list(r)


def write_csv(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="folder with bills/ and csv/")
    ap.add_argument("--output", default="../output")
    ap.add_argument("--fresh", action="store_true", help="ignore cache")
    a = ap.parse_args()

    bills_dir = os.path.join(a.input, "bills")
    os.makedirs(a.output, exist_ok=True)
    failed = []

    # ---------- Level 1 ----------
    f1, rows1 = read_csv(os.path.join(a.input, "csv", "level1.csv"))
    details = {}
    for row in rows1:
        bid = row["bill_id"]
        img = find_image(bills_dir, bid)
        print(f"[L1] {bid}")
        try:
            if not img:
                raise FileNotFoundError(f"image for {bid} not found")
            base = cached(f"{bid}_l1", a.fresh, lambda: extract_bill(img))
            details[bid] = fix_bill(base, img, lambda fn: cached(f"{bid}_bd", a.fresh, fn))
        except Exception as e:
            print(f"  ! failed: {e}")
            failed.append(f"L1 {bid}")
            details[bid] = empty_bill()
        row["json"] = json.dumps(details[bid], ensure_ascii=False, separators=(",", ":"))
    write_csv(os.path.join(a.output, "level1.csv"), f1, rows1)

    # ---------- Level 2 ----------
    f2, rows2 = read_csv(os.path.join(a.input, "csv", "level2.csv"))
    by_bill = {}
    for row in rows2:
        by_bill.setdefault(row["bill_id"], []).append((row["question_id"], row["question"]))
    answers = {}
    for bid, qs in by_bill.items():
        img = find_image(bills_dir, bid)
        print(f"[L2] {bid} ({len(qs)} questions)")
        try:
            if not img:
                raise FileNotFoundError(f"image for {bid} not found")
            d = details.get(bid, empty_bill())

            def work():
                try:  # step 1: read history tables, step 2: arithmetic in Python
                    hist = cached(f"{bid}_hist", a.fresh, lambda: extract_history(img, d))
                except Exception as e:
                    print(f"  (history step skipped: {e})")
                    hist = None
                return answer_bill(img, d, qs, facts_text(d, hist))

            answers[bid] = cached(f"{bid}_l2", a.fresh, work)
        except Exception as e:
            print(f"  ! failed: {e}")
            failed.append(f"L2 {bid}")
            answers[bid] = {}
    fallbacks = 0
    for row in rows2:
        ans = answers.get(row["bill_id"], {}).get(row["question_id"])
        if not ans:
            fallbacks += 1
            failed.append(f"L2 {row['bill_id']} {row['question_id']} (no answer)")
        row["answer"] = ans or FALLBACK
    write_csv(os.path.join(a.output, "level2.csv"), f2, rows2)

    empty1 = sum(1 for r in rows1 if not r["json"])
    empty2 = sum(1 for r in rows2 if not r["answer"])
    print(f"Done. level1: {len(rows1)} rows, level2: {len(rows2)} rows, empty cells: {empty1 + empty2}")
    if failed:
        print("\nSOME ITEMS FAILED, run the same command again (finished bills are cached and skipped):")
        for item in failed:
            print("  -", item)
    else:
        print("All bills and questions answered by the model.")


if __name__ == "__main__":
    main()