# Utility Bill Decoder (WTQ 2026 Build Track)

An AI-powered assistant that reads an electricity bill image (K-Electric, LESCO or IESCO), extracts the
bill details as JSON (Level 1) and answers customer questions about the bill in plain English (Level 2).

## Runtime
Python 3.14.6 (3.11 or later required)

## Setup
Run these commands inside the `source/` folder.

Windows:
```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```
Mac / Linux:
```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```
Then open `.env` and replace `your-api-key-here` with your Google AI Studio (Gemini) API key.

## Run
Generate both result files for a folder of bills. The input folder must contain `bills/` (images) and
`csv/level1.csv` + `csv/level2.csv` (the templates):
```
python run.py --input ../data/test --output ../output
```
This writes `output/level1.csv` (one JSON object per bill) and `output/level2.csv` (one answer per question).
Results are cached in `.cache/`, so re-running does not repeat API calls (finished bills are skipped).
Use `--fresh` to ignore the cache.

Try a single bill (optionally with questions):
```
python preview.py ../data/train/bills/KESC_0008.png "How much of my bill is taxes?"
```

## How it works
1. **Level 1 (`src/extract.py`)**: the bill image is sent to the model with a schema-driven prompt (field rules,
   charge and tax types, handling of credits, null for unavailable values, one worked example). The reply is parsed
   as JSON and cleaned in code: every field is present, numbers are real numbers, credits are negative, and unknown
   charge/tax types are mapped to `other` / `other_tax`. If the tax lines (or charge lines) do not add up to the
   printed subtotals, the bill is re-read once with that hint, and the more consistent reading is kept.
2. **Breakdown check (`src/fixes.py`)**: for IESCO/LESCO bills, the "BILL CHARGES BREAKDOWN" box is read a second
   time. Its values (net charges, combined taxes, current bill, FPA) replace the first reading only when they are
   consistent (net charges + taxes = current bill). A single combined tax amount is reported as `total_taxes`
   with `taxes: []`.
3. **History facts (`src/facts.py`)**: one extra model call reads only the usage and billing history tables.
   All arithmetic (averages, counts above a threshold, highest/lowest, differences, percentages, cost per unit)
   is then done in Python, so these numbers are computed by code and not by the model.
4. **Level 2 (`src/qa.py`)**: for each bill, the image, the Level 1 JSON, the computed facts and all of its
   questions are sent in one call. The model first writes its working and then the final answer. Answers use only
   the bill, label estimates, state when data is missing and exclude personal identifiers.
5. **Pipeline (`run.py`)**: reads the CSV templates, keeps `bill_id`, `question_id` and `question` untouched, and
   writes the results with Python's `csv` module (UTF-8, correct quoting, JSON on one line). If a bill still fails
   after retries, a safe fallback is written so no cell is empty, and the failed items are listed so the same
   command can be run again.
6. **Rate limits (`src/ai.py`)**: calls are spaced out to stay under the free-tier limit (15 requests per minute),
   use temperature 0 and JSON output mode, a 60 s timeout, and are retried with backoff on errors.

## AI usage
- Model used by the solution: Gemini 3.1 Flash-Lite (`gemini-3.1-flash-lite`), provider `google`, via Google AI Studio
- APIs and services used: Google Gemini API (`google-genai` SDK) only
- OCR libraries or invoice-extraction services: none
- AI tools used to help write the code: Claude (Anthropic chatbot)

## Configuration
Environment variables are listed in `.env.example`: `MODEL_PROVIDER`, `MODEL_NAME`, `API_KEY`.
No API keys and no `.env` file are included in this submission.

## Known limitations
- Bills with several meter registers (net metering) are ambiguous; the first meter row is used for LESCO/IESCO,
  and readings are null for K-Electric bills with several registers.
- Very blurry or heavily tilted photos may produce `null` for some fields rather than a guess.
- Questions about future bills can only be answered as labelled estimates, because the bill does not show future rates.
