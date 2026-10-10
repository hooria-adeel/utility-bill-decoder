"""Build a small fake 'test' folder from the 5 training bills, to rehearse run.py before the real test files arrive.

    python make_mock.py
    python run.py --input ../data/mock --output ../data/mock_out
"""
import csv
import os
import shutil

train = os.path.join("..", "data", "train", "bills")
mock = os.path.join("..", "data", "mock")
os.makedirs(os.path.join(mock, "bills"), exist_ok=True)
os.makedirs(os.path.join(mock, "csv"), exist_ok=True)

ids = []
for fn in sorted(os.listdir(train)):
    if fn.lower().endswith((".png", ".jpg", ".jpeg")):
        shutil.copy(os.path.join(train, fn), os.path.join(mock, "bills", fn))
        ids.append(os.path.splitext(fn)[0])

with open(os.path.join(mock, "csv", "level1.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["bill_id", "json"])
    for b in ids:
        w.writerow([b, ""])

qs = ["How much of my bill is taxes?", "What was my consumption this month in units?"]
with open(os.path.join(mock, "csv", "level2.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["bill_id", "question_id", "question", "answer"])
    for b in ids:
        for i, q in enumerate(qs, 1):
            w.writerow([b, f"Q{i}", q, ""])

print(f"mock folder ready with {len(ids)} bills: {ids}")
