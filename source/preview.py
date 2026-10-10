"""Try the solution on ONE bill image (good for the training bills and the demo video).

    python preview.py ../data/train/bills/KESC_0008.png
    python preview.py ../data/train/bills/KESC_0008.png "How much of my bill is taxes?"
"""
import json
import sys

from src.extract import extract_bill
from src.facts import extract_history, facts_text
from src.qa import answer_bill

if len(sys.argv) < 2:
    sys.exit(__doc__)

img = sys.argv[1]
details = extract_bill(img)
print("=== Level 1 ===")
print(json.dumps(details, indent=2, ensure_ascii=False))

if len(sys.argv) > 2:
    try:
        hist = extract_history(img, details)
    except Exception as e:
        print(f"(history step skipped: {e})")
        hist = None
    facts = facts_text(details, hist)
    print("\n=== Computed facts (Python) ===")
    print(facts)
    questions = [(f"Q{i}", q) for i, q in enumerate(sys.argv[2:], 1)]
    print("\n=== Level 2 ===")
    for qid, ans in answer_bill(img, details, questions, facts).items():
        print(f"{qid}: {ans}")