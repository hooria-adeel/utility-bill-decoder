"""Level 1: bill image -> one JSON object (schema from the participant guide)."""
import json
import re

from src.ai import call_llm

CHARGE_TYPES = {"energy", "fixed", "fpa", "quarterly_adjustment", "surcharge", "meter_rent", "subsidy", "other"}
TAX_TYPES = {"gst", "electricity_duty", "income_tax", "municipal_tax", "other_tax"}
NUM_FIELDS = ["sanctioned_load_kw", "previous_reading", "current_reading", "units_consumed",
              "total_charges", "total_taxes", "current_bill", "arrears",
              "payable_within_due_date", "payable_after_due_date"]
STR_FIELDS = ["provider", "tariff", "bill_month", "reading_date", "issue_date", "due_date"]
PROVIDERS = {"KE": "KE", "KESC": "KE", "K-ELECTRIC": "KE", "K ELECTRIC": "KE",
             "LESCO": "LESCO", "IESCO": "IESCO"}

PROMPT = """You read Pakistani electricity bills (K-Electric, LESCO, IESCO). The image may be tilted, a photo,
or partly in Urdu. Personal identifiers are covered by grey boxes. Return ONE JSON object only.

SCHEMA (include every key, use null if not printed / blank / covered / unreadable. Never guess):
{
 "provider": "KE" | "LESCO" | "IESCO",
 "tariff": string exactly as printed (e.g. "A1-R", "A-1a(01)"),
 "sanctioned_load_kw": number (labelled Sanc Load / S.Load / San Load),
 "bill_month": "YYYY-MM", "reading_date": "YYYY-MM-DD", "issue_date": "YYYY-MM-DD", "due_date": "YYYY-MM-DD",
 "previous_reading": number, "current_reading": number, "units_consumed": number (units billed this month),
 "charges": [ {"type": "energy|fixed|fpa|quarterly_adjustment|surcharge|meter_rent|subsidy|other", "amount": number} ],
 "total_charges": number or null (printed charges subtotal),
 "taxes": [ {"type": "gst|electricity_duty|income_tax|municipal_tax|other_tax", "amount": number} ],
 "total_taxes": number or null (printed tax subtotal),
 "current_bill": number (printed amount for this month's bill),
 "arrears": number (previous dues carried forward, keep printed sign, null if blank),
 "payable_within_due_date": number,
 "payable_after_due_date": number (if several late amounts are shown, use the HIGHEST)
}

RULES:
- Extract values exactly as printed. Do not recalculate, round or correct.
- Numbers are plain PKR numbers: "Rs. 19,964" -> 19964. Credits/subsidies are NEGATIVE: "38209CR" -> -38209.
  This applies to EVERY amount field, including payable_within_due_date and payable_after_due_date:
  "54770CR" printed as the payable amount -> -54770.
- If a payable amount field has no number but text instead (e.g. "NOT TO BE PAID"), return null for that field.
- arrears: read the number printed beside the "Arrears" label in the charges breakdown. The label and its value can
  sit on different rows, and the value may carry stray marks (e.g. "39411 / 2" -> 39411). Printed 0 -> 0; blank -> null.
  If Current Bill plus arrears equals the printed Grand Total / payable amount, that confirms you read it correctly.
- Several meter rows (registers / net metering): for LESCO and IESCO bills use the FIRST row for previous_reading,
  current_reading and units_consumed, all three from that same row (current - previous = units).
  For K-Electric bills with ONE meter row (e.g. a single "Energy" row) use that row's Previous and Current Reading.
  Only when a K-Electric bill has SEVERAL registers (off-peak, peak, import...) return null for previous_reading and
  current_reading, and use the printed "Current Month ... units" figure for units_consumed.
- Dates: "22nd Sep 2026" -> "2026-09-22"; "MAR 2026" -> "2026-03". due_date = last date to pay without late surcharge.
- "charges": one entry per line in the charges section. Skip blank lines and lines printed as 0.
  Keep separate entries if the same type appears more than once (e.g. two energy lines).
  energy = cost of units (Variable Upto.. Units / Cost of Electricity / Energy Charges); fixed = fixed charges;
  fpa = FPA and FCA; quarterly_adjustment = QTA / Uniform Quarterly Adjustment; surcharge = Additional Surcharge (PHL) / F.C Surcharge;
  meter_rent = meter or service rent; subsidy = government subsidy/relief (negative); other = anything else.
- "taxes": one entry per line in the tax/government section. Classify by SECTION, not by name.
  gst = sales tax/GST (incl. GST on FPA); electricity_duty = ED; income_tax; municipal_tax = e.g. MUCT (KMC); other_tax = extra/further tax, TV fee.
  If only one combined tax amount is printed, use [] and put the amount in total_taxes.
- NEVER output names, addresses, CNIC, account/reference/consumer/contract/meter numbers.

EXAMPLE (K-Electric bill, Apr 2026) of a correct answer:
{"provider":"KE","tariff":"A1-R","sanctioned_load_kw":3,"bill_month":"2026-04","reading_date":"2026-04-03",
"issue_date":"2026-04-07","due_date":"2026-04-21","previous_reading":8819,"current_reading":8970,"units_consumed":151,
"charges":[{"type":"fixed","amount":900},{"type":"energy","amount":1054},{"type":"energy","amount":663.51},
{"type":"quarterly_adjustment","amount":52.91},{"type":"fpa","amount":125.27},{"type":"surcharge","amount":64.93}],
"total_charges":2860.62,"taxes":[{"type":"electricity_duty","amount":29.41},{"type":"gst","amount":520.21},
{"type":"municipal_tax","amount":20}],"total_taxes":569.62,"current_bill":3430.24,"arrears":-0.53,
"payable_within_due_date":3430,"payable_after_due_date":3716}
"""


def to_num(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    neg = s.upper().endswith("CR") or s.startswith("-")
    s = re.sub(r"[^0-9.]", "", s)
    if not s or s == ".":
        return None
    try:
        x = float(s)
    except ValueError:
        return None
    x = -x if neg else x
    return int(x) if x == int(x) else x


def _entries(items, allowed, fallback):
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        amt = to_num(it.get("amount"))
        if amt is None:
            continue
        t = str(it.get("type", "")).strip().lower()
        out.append({"type": t if t in allowed else fallback, "amount": amt})
    return out


def empty_bill():
    d = {k: None for k in STR_FIELDS + NUM_FIELDS}
    d["charges"], d["taxes"] = [], []
    return order(d)


def order(d):
    keys = ["provider", "tariff", "sanctioned_load_kw", "bill_month", "reading_date", "issue_date", "due_date",
            "previous_reading", "current_reading", "units_consumed", "charges", "total_charges",
            "taxes", "total_taxes", "current_bill", "arrears", "payable_within_due_date", "payable_after_due_date"]
    return {k: d.get(k) for k in keys}


def clean(raw):
    d = empty_bill()
    for k in STR_FIELDS:
        v = raw.get(k)
        d[k] = str(v).strip() if v not in (None, "") else None
    if d["provider"]:
        d["provider"] = PROVIDERS.get(d["provider"].upper(), d["provider"].upper())
    for k in NUM_FIELDS:
        d[k] = to_num(raw.get(k))
    d["charges"] = _entries(raw.get("charges"), CHARGE_TYPES, "other")
    d["taxes"] = _entries(raw.get("taxes"), TAX_TYPES, "other_tax")
    return order(d)


def _issues(d):
    bad = []
    s = lambda items: round(sum(i["amount"] for i in items), 2)
    tc, tt, cb = d["total_charges"], d["total_taxes"], d["current_bill"]
    if d["charges"] and tc is not None and not any(c["type"] == "subsidy" for c in d["charges"]) and abs(s(d["charges"]) - tc) > 1:
        bad.append(f"charge lines add up to {s(d['charges'])} but total_charges is {tc}")
    if d["taxes"] and tt is not None and abs(s(d["taxes"]) - tt) > 1:
        bad.append(f"tax lines add up to {s(d['taxes'])} but total_taxes is {tt}")
    if None not in (tc, tt, cb) and abs(tc + tt - cb) > 1:
        bad.append(f"total_charges + total_taxes = {round(tc + tt, 2)} but current_bill is {cb}")
    return bad


def extract_bill(image_path):
    def run(prompt):
        raw = json.loads(call_llm(prompt, image_path=image_path, as_json=True))
        if isinstance(raw, list) and raw:
            raw = raw[0]
        return clean(raw)

    d = run(PROMPT)
    bad = _issues(d)
    if bad:
        print("  (recheck:", "; ".join(bad), ")")
        try:
            d2 = run(PROMPT + "\n\nCHECK: your previous reading had these inconsistencies: " + "; ".join(bad) +
                     ". Re-read those sections of the image carefully. Keep each value exactly as printed; "
                     "if the printed values really are inconsistent, keep them as printed.")
            if len(_issues(d2)) < len(bad):
                return d2
        except Exception:
            pass
    return d