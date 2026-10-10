"""Build ../submission.zip (output/ + source/ + demo/) and run the final checklist.

    python make_submission.py
"""
import os
import sys
import zipfile

from dotenv import load_dotenv

load_dotenv()
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SKIP_DIRS = {".cache", "__pycache__", "venv", ".venv", ".git"}
SKIP_FILES = {".env"}
KEY = os.getenv("API_KEY", "")
problems = []

for need in ("output/level1.csv", "output/level2.csv", "source/README.md", "source/.env.example"):
    if not os.path.exists(os.path.join(ROOT, need)):
        problems.append(f"missing {need}")

zip_path = os.path.join(ROOT, "submission.zip")
files = []
for top in ("output", "source", "demo"):
    base = os.path.join(ROOT, top)
    for dp, dns, fns in os.walk(base):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for fn in fns:
            if fn in SKIP_FILES:
                continue
            files.append(os.path.join(dp, fn))

for p in files:  # make sure the real key is not inside any file
    try:
        if KEY and len(KEY) > 8 and KEY in open(p, encoding="utf-8", errors="ignore").read():
            problems.append(f"API KEY found inside {os.path.relpath(p, ROOT)}")
    except OSError:
        pass

if problems:
    sys.exit("NOT BUILT:\n- " + "\n- ".join(problems))

with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
    for p in files:
        z.write(p, os.path.relpath(p, ROOT))

size = os.path.getsize(zip_path) / 1024 / 1024
print(f"submission.zip built: {size:.1f} MB (limit 15 MB)")
for p in files:
    print("  ", os.path.relpath(p, ROOT))
if size > 15:
    print("WARNING: ZIP is over 15 MB - shrink the demo video.")
