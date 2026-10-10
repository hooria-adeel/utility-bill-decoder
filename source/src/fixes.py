"""Post-processing for the IESCO / LESCO 'BILL CHARGES BREAKDOWN' layout.

These bills print ONE combined 'Taxes' amount (so `taxes` must be [] with the amount in total_taxes), a 'Net Electricity
Charges' subtotal (= total_charges), a 'Current Bill' and a separate 'Total FPA' line. A second, focused read of that box is
used to repair systematic slips (grand total mistaken for current bill, FPA added into the subtotal, misread digits).
Values are only replaced when the second read is self-consistent: net charges + taxes = current bill.
"""
import copy
import json

from src.ai import call_llm
from src.extract import to_num

PROMPT = """This is an IESCO or LESCO electricity bill. Find the box titled BILL CHARGES BREAKDOWN and read these values
exactly as printed, reading every digit carefully. Ignore any handwriting.
{
 "total_electricity_charges": number or null,
 "subsidies": number or null,
 "net_electricity_charges": number or null,
 "taxes": number or null,
 "current_bill": number or null,
 "total_fpa": number or null,
 "grand_total": number or null
}
Notes: "Taxes" is one combined amount in this box (about 15-23% of the current bill). "Current Bill" is NOT the Grand Total:
Grand Total = Current Bill + arrears + Total FPA etc. "Total FPA" is printed below Current Bill. Use null when the label
is absent or the value is blank (for example if the bill has no such box). Return JSON only."""

KEYS = ["total_electricity_charges", "subsidies", "net_electricity_charges", "taxes", "current_bill", "total_fpa", "grand_total"]


def read_breakdown(image_path):
    raw = json.loads(call_llm(PROMPT, image_path=image_path, as_json=True))
    if isinstance(raw, list) and raw:
        raw = raw[0]
    return {k: to_num(raw.get(k)) for k in KEYS}


def _close(a, b, tol=1.0):
    return a is not None and b is not None and abs(a - b) <= tol


def apply_breakdown(details, r):
    """Return a repaired copy of `details` using the focused re-read `r` (dict from read_breakdown)."""
    d = copy.deepcopy(details)
    if d.get("provider") not in ("IESCO", "LESCO") or not r:
        return d
    net, tax, cur, fpa = r.get("net_electricity_charges"), r.get("taxes"), r.get("current_bill"), r.get("total_fpa")
    if net is None or tax is None:
        return d  # different layout (e.g. itemised old LESCO bill): leave untouched

    if cur is not None and _close(net + tax, cur):
        # second read is self-consistent: adopt it
        d["total_charges"], d["total_taxes"], d["current_bill"] = net, tax, cur
    elif _close(net, d.get("total_charges")) and _close(cur, d.get("current_bill")):
        # both reads agree on net charges and current bill, only the tax digits disagree: implied taxes
        d["total_taxes"] = round(cur - net, 2)
    # combined tax amount only -> taxes must be []
    d["taxes"] = []

    # FPA is printed as its own line: make sure it is listed once
    if fpa and not any(c.get("type") == "fpa" for c in d.get("charges") or []):
        d.setdefault("charges", []).append({"type": "fpa", "amount": fpa})
    return d


def fix_bill(details, image_path, cache_fn):
    """cache_fn(fn) runs fn once and caches its result. Never raises: on any problem the original details are returned."""
    try:
        if details.get("provider") not in ("IESCO", "LESCO"):
            return details
        r = cache_fn(lambda: read_breakdown(image_path))
        return apply_breakdown(details, r)
    except Exception as e:
        print(f"  (breakdown check skipped: {e})")
        return details