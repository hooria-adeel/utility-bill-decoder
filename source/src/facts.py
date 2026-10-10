"""Level 2 helper: the model only READS the history tables; all arithmetic is done here in Python."""
import json
import statistics

from src.ai import call_llm
from src.extract import to_num

THRESHOLDS = [100, 150, 200, 250, 300, 400, 500]

PROMPT = """Read the HISTORY sections of this electricity bill image (usage / consumption history chart or table,
billing & payment history, bill history). Return ONE JSON object:
{
 "usage_history": [{"month": "YYYY-MM", "units": number}],
 "billing_history": [{"month": "YYYY-MM", "billed": number or null, "paid": number or null, "units": number or null}]
}
Rules:
- usage_history: every month of the usage / units history, oldest first, INCLUDING the current bill month if it is shown.
  If there is no separate chart, take units from the bill history table.
- billing_history: one entry per row of the billing / payment / bill history table (billed amount, payment amount, units if shown). Use null for blanks.
- Read values exactly as printed. Months run oldest to newest and the newest is the bill month (BILL_MONTH); use that to work out the year of each month.
- Use [] if the bill has no such history. Do not include names or identifiers."""


def extract_history(image_path, details):
    prompt = PROMPT.replace("BILL_MONTH", str(details.get("bill_month")))
    raw = json.loads(call_llm(prompt, image_path=image_path, as_json=True))
    if isinstance(raw, list) and raw:
        raw = raw[0]
    usage, billing = [], []
    for it in raw.get("usage_history") or []:
        u = to_num(it.get("units"))
        m = str(it.get("month") or "").strip()
        if u is not None and m:
            usage.append({"month": m, "units": u})
    for it in raw.get("billing_history") or []:
        m = str(it.get("month") or "").strip()
        if m:
            billing.append({"month": m, "billed": to_num(it.get("billed")),
                            "paid": to_num(it.get("paid")), "units": to_num(it.get("units"))})
    usage.sort(key=lambda r: _ym(r["month"]) or (0, 0))
    billing.sort(key=lambda r: _ym(r["month"]) or (0, 0))
    return {"usage_history": usage, "billing_history": billing}


def _summary(rows):
    if not rows:
        return None
    vals = [r["units"] for r in rows]
    hi = max(rows, key=lambda r: r["units"])
    lo = min(rows, key=lambda r: r["units"])
    return {
        "months_counted": len(rows),
        "total_units": round(sum(vals), 2),
        "average_units": round(statistics.mean(vals), 2),
        "median_units": round(statistics.median(vals), 2),
        "highest": f"{hi['month']} ({hi['units']})",
        "lowest": f"{lo['month']} ({lo['units']})",
        "number_of_months_above": {str(t): sum(1 for v in vals if v > t) for t in THRESHOLDS},
    }


def usage_stats(usage, bill_month):
    out = {}
    current = None
    previous = list(usage)
    if usage and usage[-1]["month"] == bill_month:
        current = usage[-1]
        previous = usage[:-1]
    out["all_months_in_history_including_current"] = _summary(usage)
    out["previous_months_only_excluding_current"] = _summary(previous)
    if current and previous:
        avg = statistics.mean(r["units"] for r in previous)
        diff = current["units"] - avg
        out["current_month_units"] = current["units"]
        out["current_vs_previous_average"] = {
            "difference_units": round(diff, 2),
            "difference_percent": round(diff / avg * 100, 2) if avg else None}
    return out


def derived(d):
    out = {}
    cb, u = d.get("current_bill"), d.get("units_consumed")
    tt, tc = d.get("total_taxes"), d.get("total_charges")
    if cb and tt is not None:
        out["taxes_percent_of_current_bill"] = round(tt / cb * 100, 2)
    if cb and tc is not None:
        out["charges_percent_of_current_bill"] = round(tc / cb * 100, 2)
    if cb and u:
        out["current_bill_per_unit"] = round(cb / u, 2)
    by = {}
    for c in d.get("charges") or []:
        by[c["type"]] = round(by.get(c["type"], 0) + c["amount"], 2)
    if by:
        out["charges_by_type"] = by
    byt = {}
    for t in d.get("taxes") or []:
        byt[t["type"]] = round(byt.get(t["type"], 0) + t["amount"], 2)
    if byt:
        out["taxes_by_type"] = byt
    if by.get("energy") and u:
        out["energy_charge_per_unit"] = round(by["energy"] / u, 2)
    if d.get("payable_after_due_date") is not None and d.get("payable_within_due_date") is not None:
        out["extra_if_paid_after_due_date"] = round(d["payable_after_due_date"] - d["payable_within_due_date"], 2)
    if d.get("previous_reading") is not None and d.get("current_reading") is not None:
        out["reading_difference"] = round(d["current_reading"] - d["previous_reading"], 2)
    if cb is not None and d.get("arrears") is not None:
        out["current_bill_plus_arrears"] = round(cb + d["arrears"], 2)
    return out


SUMMER = {6, 7, 8}
WINTER = {12, 1, 2}


def _ym(m):
    try:
        y, mo = str(m).strip().split("-")[:2]
        return int(y), int(mo)
    except Exception:
        return None


def _r(x):
    return None if x is None else round(x, 2)


def _series(details, usage):
    """Previous months (without the bill month) + the current bill month, oldest first."""
    bm, cu = details.get("bill_month"), details.get("units_consumed")
    prev = [r for r in usage if r["month"] != bm]
    series = list(prev)
    if bm and cu is not None:
        series = prev + [{"month": bm, "units": cu}]
    return prev, series


def trend_facts(details, usage):
    if not usage:
        return None
    bm, cu = details.get("bill_month"), details.get("units_consumed")
    prev, series = _series(details, usage)
    last12 = series[-12:]
    out = {"history_months_listed_on_bill": [r["month"] for r in prev], "current_month": bm,
           "current_month_units": cu}

    def hi_lo(rows):
        if not rows:
            return None
        hi = max(rows, key=lambda r: r["units"])
        lo = min(rows, key=lambda r: r["units"])
        return {"highest": f"{hi['month']} ({hi['units']})", "lowest": f"{lo['month']} ({lo['units']})"}

    out["highest_lowest_in_listed_history_months"] = hi_lo(prev)
    out["highest_lowest_in_last_12_months_including_current"] = hi_lo(last12)
    if last12:
        avg12 = statistics.mean(r["units"] for r in last12)
        out["average_units_last_12_months_including_current"] = _r(avg12)
    if prev:
        avgp = statistics.mean(r["units"] for r in prev)
        out["average_units_listed_history_months"] = _r(avgp)
        if cu is not None and avgp:
            out["current_vs_listed_history_average"] = {
                "difference_units": _r(cu - avgp), "difference_percent": _r((cu - avgp) / avgp * 100)}

    # summer vs winter (inside the last 12 months so no month is counted twice)
    summer = [r for r in last12 if (_ym(r["month"]) or (0, 0))[1] in SUMMER]
    winter = [r for r in last12 if (_ym(r["month"]) or (0, 0))[1] in WINTER]
    if summer and winter:
        st, wt = sum(r["units"] for r in summer), sum(r["units"] for r in winter)
        sa, wa = st / len(summer), wt / len(winter)
        out["summer_vs_winter"] = {
            "summer_months_used": [f"{r['month']} ({r['units']})" for r in summer],
            "winter_months_used": [f"{r['month']} ({r['units']})" for r in winter],
            "summer_total": _r(st), "winter_total": _r(wt), "summer_average_per_month": _r(sa),
            "winter_average_per_month": _r(wa), "difference_of_totals": _r(st - wt),
            "difference_of_monthly_averages": _r(sa - wa)}
    else:
        out["summer_vs_winter"] = "summer and/or winter months are not both present in the history shown"

    # same month last year
    ym = _ym(bm) if bm else None
    if ym and cu is not None:
        ly = next((r for r in prev if _ym(r["month"]) == (ym[0] - 1, ym[1])), None)
        if ly:
            out["same_month_last_year"] = {"month": ly["month"], "units": ly["units"], "this_month_units": cu,
                                           "difference_units": _r(cu - ly["units"]),
                                           "difference_percent": _r((cu - ly["units"]) / ly["units"] * 100) if ly["units"] else None}
        else:
            out["same_month_last_year"] = "not shown on the bill"

    # last 3 months trend
    if len(series) >= 3:
        l3 = series[-3:]
        v = [r["units"] for r in l3]
        label = "rising" if v[0] < v[1] < v[2] else "falling" if v[0] > v[1] > v[2] else "mixed (not steadily up or down)"
        out["last_3_months"] = {"months": [f"{r['month']} ({r['units']})" for r in l3], "direction": label,
                                "change_first_to_last": _r(v[2] - v[0])}
        if len(series) >= 6:
            p3 = statistics.mean(r["units"] for r in series[-6:-3])
            out["last_3_months"]["average_vs_previous_3_months"] = {
                "last_3_average": _r(statistics.mean(v)), "previous_3_average": _r(p3)}

    # next month estimate
    if len(last12) >= 3:
        vals = [r["units"] for r in last12]
        n = len(vals)
        xm, ym_ = (n - 1) / 2, statistics.mean(vals)
        den = sum((i - xm) ** 2 for i in range(n))
        slope = sum((i - xm) * (vals[i] - ym_) for i in range(n)) / den if den else 0
        est = {"average_of_last_3_months": _r(statistics.mean(vals[-3:])),
               "average_of_last_12_months": _r(ym_),
               "linear_trend_projection": _r(ym_ + slope * (n - xm)),
               "trend_slope_units_per_month": _r(slope)}
        if ym:
            ny, nm = (ym[0], ym[1] + 1) if ym[1] < 12 else (ym[0] + 1, 1)
            ly = next((r for r in series if _ym(r["month"]) == (ny - 1, nm)), None)
            if ly:
                est["same_calendar_month_last_year"] = f"{ly['month']} ({ly['units']})"
        out["next_month_units_ESTIMATES"] = est

    # bill if the same units repeat
    cb = details.get("current_bill")
    if cb and cu and cu > 0:
        e = {"bill_if_same_units_as_this_bill_month": cb}
        if len(series) >= 2 and series[-2]["units"] > 0:
            pu = series[-2]["units"]
            e["previous_month_units"] = pu
            e["rough_bill_if_same_units_as_previous_month"] = _r(pu * cb / cu)
            e["note"] = "rough estimate: previous-month units x this bill's average cost per unit (includes fixed charges and taxes)"
        out["bill_if_same_units_ESTIMATES"] = e
    return out


def billing_facts(details, billing):
    if not billing:
        return None
    rows = billing
    billed = [r["billed"] for r in rows if r["billed"] is not None]
    out = {"months_listed": [r["month"] for r in rows], "number_of_months": len(rows)}
    if billed:
        out["total_billed_listed_months"] = _r(sum(billed))
        out["average_billed_listed_months"] = _r(statistics.mean(billed))
        hi = max((r for r in rows if r["billed"] is not None), key=lambda r: r["billed"])
        out["highest_bill"] = f"{hi['month']} ({hi['billed']})"
        cb = details.get("current_bill")
        if cb is not None:
            allb = billed[-11:] + [cb]
            out["average_monthly_cost_last_up_to_12_bills_including_current"] = _r(statistics.mean(allb))
            out["number_of_bills_in_that_average"] = len(allb)
    out["months_with_no_payment_recorded"] = [r["month"] for r in rows if r["billed"] and not r["paid"]]
    out["paid_less_than_billed"] = [f"{r['month']} (billed {r['billed']}, paid {r['paid']})" for r in rows
                                    if r["billed"] and r["paid"] and r["paid"] < r["billed"] - 1]
    out["paid_more_than_billed"] = [f"{r['month']} (billed {r['billed']}, paid {r['paid']})" for r in rows
                                    if r["billed"] and r["paid"] and r["paid"] > r["billed"] + 1]
    out["note"] = "the newest listed month may show no payment simply because it was not yet due"
    return out


def facts_text(details, hist):
    """Text block given to the Level 2 prompt."""
    parts = ["Derived from the bill figures: " + json.dumps(derived(details), ensure_ascii=False)]
    if hist and hist.get("usage_history"):
        parts.append("Usage history read from the bill (month, units): " +
                     json.dumps(hist["usage_history"], ensure_ascii=False))
        parts.append("Usage statistics computed by code: " +
                     json.dumps(usage_stats(hist["usage_history"], details.get("bill_month")), ensure_ascii=False))
    if hist and hist.get("billing_history"):
        parts.append("Billing/payment history read from the bill: " +
                     json.dumps(hist["billing_history"], ensure_ascii=False))
    for label, fn, data in (("Trend, seasonal and estimate analysis computed by code", trend_facts, (hist or {}).get("usage_history")),
                            ("Billing and payment analysis computed by code", billing_facts, (hist or {}).get("billing_history"))):
        try:
            res = fn(details, data or [])
            if res:
                parts.append(label + ": " + json.dumps(res, ensure_ascii=False))
        except Exception as e:  # never let an analysis bug break the run
            parts.append(f"({label} unavailable: {e})")
    return "\n".join(parts)