"""Level 2: answer customer questions about one bill (all questions of a bill in one call)."""
import json

from src.ai import call_llm

FALLBACK = "The bill does not show enough information to answer this question reliably."

PROMPT = """You are a helpful assistant explaining a Pakistani electricity bill (image attached) in plain English.
Below are the extracted bill details (JSON, may contain small errors - the image is the source of truth)
and a list of customer questions.

EXTRACTED DETAILS:
{details}

COMPUTED FACTS (the history values were read from the bill and all arithmetic was done by code):
{facts}

QUESTIONS:
{questions}

RULES:
- For averages, counts, highest/lowest, differences and percentages, USE the computed facts above instead of doing your own arithmetic.
  Mention the underlying values. If a computed fact clearly disagrees with what you see in the image, trust the image and say so.
- Answer ONLY from the bill. Do not use outside tariff/rate knowledge. If the bill does not show a needed value, say so clearly instead of guessing.
- Numbers must be right. Do calculations step by step (averages, differences, counts, percentages) and double check them.
  Quote the actual values from the bill that you used (e.g. units per month from the usage history chart, amounts in PKR).
- If you estimate or assume something, say "estimate" and explain how you calculated it.
- If a question has more than one reasonable meaning, state the meaning you used (or answer both).
- Be specific and concise (2-4 sentences). Write in English even if parts of the bill are in Urdu.
- Start the answer with the direct result. The answer must never contradict itself or your working.
- For "how much / what share" questions give the amount AND its percentage of the relevant total (e.g. taxes vs current bill),
  and mention the percentage split printed on the bill if there is one.
- For questions about history or past months, list the months/values you counted. If including or excluding the current month
  changes the result, say so (or state that the result is the same either way).
- Net-metered or standard? Say net-metered (solar) only if the bill shows evidence (e.g. "Net Metering", export/import registers,
  "Net Metering Benefit", negative units or credits); otherwise say standard. Always say what you saw on the bill.
- Fuel adjustment (FPA/FCA): give the amount and the month it relates to (e.g. the "FCA :Jul-26" label on K-Electric bills, or the
  month named in the FPA note on IESCO/LESCO bills; the "Total FPA" line is the FPA amount on IESCO/LESCO).
- Late payment surcharge: give every printed surcharge amount with its date window (e.g. 5% and 10% rows, or the two L.P. Surcharge
  figures) and the resulting payable amounts after the due date.
- If two time windows are plausible (e.g. "last 12 months" with or without the current month), say which one you used and, if the
  result differs, give the other too. If the bill does not show last year's value or enough months, say so.
- Forecasts and "roughly" questions: label them as estimates, give the number from the computed estimates, and say how it was made.
- Payments questions: use only the months shown; mention months with no payment recorded or partial payments, and that the newest
  month may simply not be due yet.
- NEVER include names, addresses, CNIC, account/reference/consumer/contract/meter numbers.

For each question first write your working in "work" (read the values, do the arithmetic, double check), and only THEN write the final "answer".
Return ONE JSON object like {{"Q1": {{"work": "...", "answer": "..."}}, "Q2": {{"work": "...", "answer": "..."}}}}."""


def answer_bill(image_path, details, questions, facts=None):
    """questions: list of (question_id, question_text). Returns {question_id: answer}."""
    qtext = "\n".join(f"{qid}: {q}" for qid, q in questions)
    prompt = PROMPT.format(details=json.dumps(details, ensure_ascii=False), questions=qtext,
                           facts=facts or "(none available)")
    raw = json.loads(call_llm(prompt, image_path=image_path, as_json=True))
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        raw = raw[0]
    out = {}
    for qid, _ in questions:
        a = raw.get(qid)
        if isinstance(a, dict):
            a = a.get("answer")
        out[qid] = " ".join(str(a).split()) if a else None
    return out