"""Bill Decoder: Streamlit demo UI.

Run from the source/ folder:
    streamlit run app.py

Reuses the same pipeline as run.py (src/): extract -> breakdown check -> history facts -> plain-English answers.
The API key is read from .env (never typed into the UI, never stored).
"""
import hashlib
import html
import json
import os
import tempfile
from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st

from src.extract import extract_bill
from src.facts import extract_history, facts_text
from src.fixes import fix_bill
from src.qa import answer_bill

st.set_page_config(page_title="Bill Decoder", page_icon="⚡", layout="wide", initial_sidebar_state="collapsed")

MODEL_NAME = os.getenv("MODEL_NAME", "gemini-3.1-flash-lite")

# palette: meter-face greys, ink blue, hazard-sign yellow, meter-red last digit
INK, INK2, MUTED = "#14213D", "#22345C", "#5E6B80"
SLATE, SIGNAL, RED, TEAL = "#C5CEDA", "#FFC61A", "#D62839", "#0E8C84"
FONT = "Instrument Sans"

CHARGE_COL = {"energy": "#14213D", "fixed": "#2F4B7C", "fpa": "#4F6FA1", "quarterly_adjustment": "#7F98BE",
              "surcharge": "#A9BAD4", "meter_rent": "#C3D0E3", "other": "#D6DFEC"}
TAX_COL = {"gst": "#FFC61A", "electricity_duty": "#FFD861", "municipal_tax": "#FFE493",
           "income_tax": "#F0A800", "other_tax": "#FFEFB8"}

QUICK = {
    "Solar or standard?": "Is this a net-metered (solar) connection or a standard connection? How did you tell?",
    "Fuel adjustment": "How much fuel adjustment am I being charged (shown as FPA or FCA on the bill), and for which month?",
    "Late payment": "If I don't pay on time, what late payment surcharges will be added?",
    "Usage trend": "Have my units consumed gone up or down over the last 3 months?",
    "Compared with last year": "Am I consuming more units than in the same month last year?",
    "Next month": "Based on the 12 months trend, how many units should I expect to consume next month?",
}
MORE_QUESTIONS = [
    "Which month in the last 12 months had the highest units consumed?",
    "What are my average monthly units consumed, and how does this month compare?",
    "How many more units do I consume in summer (June-August) than in winter (December-February)?",
    "Looking at the payments for the 12 months shown on the bill, have I been paying every bill?",
    "If I wanted to spread my electricity cost evenly across the year, how much should I set aside each month?",
    "If I consume the same units as last month, what would my bill be roughly?",
]
VIEWS = ["Overview", "Ask about this bill", "Raw JSON"]

TERMS = [
    ("FPA / FCA", "Fuel price adjustment. Charged or credited when fuel costs differ from what the tariff assumed."),
    ("QTA", "Quarterly tariff adjustment, a periodic correction added on top of the tariff."),
    ("GST", "Sales tax added to the bill."),
    ("ED", "Electricity duty, a government levy."),
    ("Arrears", "Dues carried over from earlier bills. A minus sign means you have a credit."),
    ("L.P. surcharge", "Late payment surcharge, added if you pay after the due date."),
]

# ---------------------------------------------------------------- styling
# digit wheels: each wheel is a strip of 0-9; the class w<N> slides the strip to digit N, and the keyframe
# (which only defines "from") makes it roll up from 0 once when the bill is first rendered.
WHEEL_CSS = "".join(f".reg .w{d} .strip{{transform:translateY({-d * 1.15:.2f}em)}}" for d in range(10))
DELAY_CSS = "".join(f".reg b:nth-of-type({i}) .strip{{animation-delay:{(i - 1) * 0.09:.2f}s}}" for i in range(1, 11))

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700;12..96,800&family=Chivo+Mono:wght@500;700&family=Instrument+Sans:wght@400;500;600&display=swap');
:root{--ink:#14213D;--ink2:#22345C;--paper:#F2F4F7;--line:#DDE3EB;--muted:#5E6B80;--signal:#FFC61A;--red:#D62839;--teal:#0E8C84;}
.stApp{background:var(--paper);color:var(--ink);font-family:'Instrument Sans',system-ui,sans-serif;}
header[data-testid="stHeader"]{background:transparent;}
#MainMenu,footer{visibility:hidden;}
.block-container{max-width:1160px;padding-top:1.2rem;padding-bottom:4rem;}
:focus-visible{outline:3px solid var(--ink);outline-offset:2px;}

.topbar{display:flex;align-items:center;gap:.7rem;padding:.2rem 0 1.5rem;flex-wrap:wrap;}
.mark{width:34px;height:34px;border-radius:9px;background:var(--ink);display:grid;place-items:center;}
.wordmark{font-family:'Bricolage Grotesque',sans-serif;font-weight:800;font-size:1.3rem;letter-spacing:-.01em;}
.topbar .sp{flex:1;}
.tag{font-size:.78rem;color:var(--muted);border:1px solid var(--line);background:#fff;border-radius:999px;padding:.2rem .65rem;}

.hero-h{font-family:'Bricolage Grotesque',sans-serif;font-weight:800;font-size:clamp(2.3rem,5vw,3.7rem);line-height:1.02;
  letter-spacing:-.03em;margin:.4rem 0 1.1rem;max-width:12ch;}
.hero-p{font-size:1.08rem;line-height:1.55;color:var(--muted);max-width:46ch;margin:0 0 1.4rem;}

.receipt,.ledger{position:relative;background:#fff;filter:drop-shadow(0 10px 22px rgba(20,33,61,.09));}
.receipt::after,.ledger::after{content:"";position:absolute;left:0;right:0;bottom:-7px;height:7px;
  background:conic-gradient(from -45deg at 50% 100%,#fff 90deg,transparent 0) 0 0/14px 7px repeat-x;}
.receipt{padding:1.3rem 1.5rem 1.4rem;margin-bottom:10px;}
.rc-title{font-weight:600;font-size:.92rem;color:var(--muted);display:flex;justify-content:space-between;gap:1rem;
  border-bottom:2px dashed var(--line);padding-bottom:.75rem;margin-bottom:.3rem;}
.rc-row{display:grid;grid-template-columns:6.4rem 1fr;gap:.9rem;padding:.7rem 0;border-bottom:1px dotted #C9D1DC;align-items:baseline;}
.rc-row:last-child{border-bottom:0;}
.rc-term{font-family:'Chivo Mono',monospace;font-weight:700;font-size:.92rem;}
.rc-def{font-size:.93rem;line-height:1.45;color:#2B3957;}

.bill-head{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(0,1fr);background:var(--ink);color:#fff;border-radius:18px;overflow:hidden;
  box-shadow:0 18px 40px rgba(20,33,61,.22);}
.bh-main{padding:1.6rem 1.9rem 1.7rem;}
.bh-label{font-size:.98rem;color:#B9C4D8;margin-bottom:.8rem;}
.bh-late{margin-top:1.1rem;font-size:.97rem;color:#B9C4D8;}
.bh-late b{color:#fff;font-weight:600;}
.delta{margin-left:.5rem;background:var(--red);color:#fff;border-radius:6px;padding:.1rem .5rem;font-size:.82rem;font-weight:600;}
.bh-side{background:var(--ink2);padding:1.3rem 1.7rem;display:flex;flex-direction:column;justify-content:center;gap:.85rem;}
.stat{display:flex;justify-content:space-between;align-items:baseline;gap:1rem;border-bottom:1px solid rgba(255,255,255,.13);padding-bottom:.8rem;}
.stat:last-child{border-bottom:0;padding-bottom:0;}
.stat span{color:#B9C4D8;font-size:.92rem;}
.stat b{font-family:'Chivo Mono',monospace;font-weight:700;font-size:1.08rem;text-align:right;}
.plain{font-size:1.12rem;line-height:1.6;max-width:72ch;margin:1.3rem 0 .6rem;color:#22304F;}

.reg{display:flex;align-items:center;gap:5px;font-family:'Chivo Mono',monospace;font-weight:700;
  font-size:clamp(2.3rem,6vw,3.8rem);line-height:1;}
.reg .cur{font-size:.3em;color:#B9C4D8;font-weight:500;margin-right:.4rem;align-self:flex-end;padding-bottom:.5em;}
.reg .sep{color:#B9C4D8;align-self:flex-end;font-size:.8em;margin:0 -1px;}
.reg .na{font-size:.6em;color:#B9C4D8;}
.reg .cr{font-size:.3em;font-weight:600;margin-left:.5rem;background:var(--teal);border-radius:5px;padding:.15em .5em;align-self:center;}
.wheel{display:block;position:relative;overflow:hidden;width:.72em;height:1.15em;background:#0B1530;border-radius:6px;
  box-shadow:inset 0 .2em .28em rgba(0,0,0,.55),inset 0 -.2em .28em rgba(0,0,0,.45),0 0 0 1px rgba(255,255,255,.08);}
.wheel.last{background:var(--red);}
.strip{display:flex;flex-direction:column;animation:spin 1.3s cubic-bezier(.16,.84,.24,1) both;}
.strip i{font-style:normal;display:block;height:1.15em;line-height:1.15em;text-align:center;color:#fff;}
@keyframes spin{from{transform:translateY(0);}}
@media (prefers-reduced-motion:reduce){.strip{animation:none;}}
__WHEELS__

.sec{font-family:'Bricolage Grotesque',sans-serif;font-weight:700;font-size:1.4rem;letter-spacing:-.01em;margin:1.9rem 0 .15rem;}
.sec-sub{color:var(--muted);font-size:.94rem;margin:0 0 .9rem;max-width:64ch;}
.split{display:flex;gap:8px;margin:.5rem 0 .2rem;}
.segs{display:flex;height:36px;border-radius:8px;overflow:hidden;gap:2px;}
.seg{min-width:3px;}
.legend{display:flex;flex-wrap:wrap;gap:.4rem 1.4rem;font-size:.92rem;color:#2B3957;margin:.6rem 0 1rem;}
.legend i{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:.45rem;vertical-align:-1px;}

.ledger{padding:1.1rem 1.3rem 1.2rem;margin-bottom:14px;}
.lg-title{font-weight:700;font-size:1.02rem;margin-bottom:.45rem;}
.lg-row{display:flex;align-items:baseline;padding:.27rem 0;}
.lg-name{color:#2B3957;}
.lg-dots{flex:1;border-bottom:2px dotted #C3CBD8;margin:0 .5rem .25rem;}
.lg-amt{font-family:'Chivo Mono',monospace;font-weight:500;font-size:.95rem;}
.lg-amt.neg{color:var(--teal);}
.lg-total{display:flex;justify-content:space-between;border-top:2px solid var(--ink);margin-top:.6rem;padding-top:.6rem;font-weight:700;}
.lg-note{font-size:.86rem;color:var(--muted);margin-top:.5rem;line-height:1.4;}

.plate{background:#fff;border:1px solid var(--line);border-radius:14px;padding:.35rem 1rem;margin-top:.8rem;}
.pl-row{display:flex;justify-content:space-between;gap:1rem;padding:.55rem 0;border-bottom:1px solid var(--line);font-size:.9rem;}
.pl-row:last-child{border-bottom:0;}
.pl-row span{color:var(--muted);}
.pl-row b{font-weight:600;text-align:right;}

.trust{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1.5rem;margin:2.4rem 0 0;}
.trust div{border-left:3px solid var(--signal);padding-left:.9rem;font-size:.95rem;line-height:1.5;color:#2B3957;}
.trust b{display:block;font-family:'Bricolage Grotesque',sans-serif;font-size:1.08rem;margin-bottom:.15rem;color:var(--ink);}
.note{padding:.7rem .9rem;border-radius:10px;background:#FFF6D6;border:1px solid #F2DC8A;color:#5C4600;font-size:.88rem;}

[data-testid="stFileUploaderDropzone"]{background:#fff;border:2px dashed #AAB6C8;border-radius:16px;padding:1.5rem;}
[data-testid="stFileUploaderDropzone"]:hover{border-color:var(--ink);}
section[data-testid="stSidebar"]{background:#fff;}
[data-testid="stChatMessage"]{background:#fff;border:1px solid var(--line);border-radius:14px;}
.stButton>button{border-radius:10px;border:1px solid #B8C2D1;background:#fff;color:var(--ink);font-weight:500;}
.stButton>button:hover{border-color:var(--ink);background:var(--signal);color:var(--ink);}

@media (max-width:760px){
  .bill-head{grid-template-columns:1fr;}
  .trust{grid-template-columns:1fr;}
  .rc-row{grid-template-columns:1fr;gap:.2rem;}
}
</style>
""".replace("__WHEELS__", WHEEL_CSS + DELAY_CSS)

BOLT = ('<svg width="18" height="18" viewBox="0 0 24 24" fill="#FFC61A" aria-hidden="true">'
        '<path d="M13.5 2 5 13.5h6L10 22l9-12h-6.2z"/></svg>')


# ---------------------------------------------------------------- formatting helpers
def h(*parts):
    """Join HTML pieces with no whitespace (blank lines would end a markdown HTML block)."""
    return "".join(parts)


def esc(v):
    return html.escape(str(v))


def num(v):
    if v is None:
        return "n/a"
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"


def money(v):
    if v is None:
        return "n/a"
    return f"{'-' if v < 0 else ''}PKR {num(abs(v))}"


def fmt_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").strftime("%d %b %Y").lstrip("0")
    except (TypeError, ValueError):
        return s or "n/a"


def month_label(m, long=False):
    try:
        return datetime.strptime(str(m), "%Y-%m").strftime("%B %Y" if long else "%b '%y")
    except ValueError:
        return str(m) if m else "n/a"


def type_label(t):
    t = t.replace("_", " ")
    return t.upper() if t.lower() in ("fpa", "gst") else t.title()


# ---------------------------------------------------------------- html components
def register(value):
    """Meter-style odometer for a PKR amount. The last digit is red, like the decimal wheel on a real meter."""
    if value is None:
        return '<div class="reg"><span class="na">n/a</span></div>'
    digits = f"{int(round(abs(value))):,}"
    last = max(i for i, ch in enumerate(digits) if ch != ",")
    cells = []
    for i, ch in enumerate(digits):
        if ch == ",":
            cells.append('<span class="sep">,</span>')
            continue
        strip = h("".join(f"<i>{d}</i>" for d in range(10)))
        cells.append(f'<b class="wheel w{ch}{" last" if i == last else ""}"><span class="strip">{strip}</span></b>')
    credit = '<span class="cr">CREDIT</span>' if value < 0 else ""
    return h('<div class="reg"><span class="cur">PKR</span>', *cells, credit, "</div>")


def plain_summary(d):
    cb, tc, tt, ar = (d.get(k) for k in ("current_bill", "total_charges", "total_taxes", "arrears"))
    u, due = d.get("units_consumed"), d.get("due_date")
    within, after = d.get("payable_within_due_date"), d.get("payable_after_due_date")
    out = []
    if u is not None:
        out.append(f"You used <b>{num(u)} units</b> in this billing period.")
    if tc is not None and tt is not None:
        share = f", which is {tt / cb * 100:.1f}% of this month's bill" if cb else ""
        out.append(f"Electricity charges came to {money(tc)} and taxes to {money(tt)}{share}.")
    if ar:
        out.append(f"A credit of {money(abs(ar))} was carried over from earlier bills." if ar < 0
                   else f"{money(ar)} of earlier dues is carried over.")
    if within is not None and after is not None and after > within and due:
        out.append(f"Pay by <b>{esc(fmt_date(due))}</b>; after that, {money(after - within)} extra is added.")
    return f'<p class="plain">{" ".join(out)}</p>' if out else ""


def bill_head(d):
    within, after, due = d.get("payable_within_due_date"), d.get("payable_after_due_date"), d.get("due_date")
    amount = within if within is not None else d.get("current_bill")
    label = f"Pay by {fmt_date(due)}" if due else "Amount payable"
    late = ""
    if after is not None:
        delta = f'<span class="delta">+{esc(money(after - within))}</span>' if within is not None and after > within else ""
        late = f'<div class="bh-late">After the due date: <b>{esc(money(after))}</b>{delta}</div>'
    arrears = d.get("arrears")
    ar_txt = "n/a" if arrears is None else money(arrears) + (" (credit)" if arrears < 0 else "")
    side = h(
        f'<div class="stat"><span>Units used</span><b>{esc(num(d.get("units_consumed")))}</b></div>',
        f'<div class="stat"><span>This month\'s bill</span><b>{esc(money(d.get("current_bill")))}</b></div>',
        f'<div class="stat"><span>Arrears</span><b>{esc(ar_txt)}</b></div>',
    )
    return h('<section class="bill-head"><div class="bh-main">',
             f'<div class="bh-label">{esc(label)}</div>', register(amount), late,
             f'</div><div class="bh-side">{side}</div></section>')


def ledger(title, items, total, note=""):
    counts = {}
    for it in items:
        counts[it["type"]] = counts.get(it["type"], 0) + 1
    seen, rows = {}, []
    for it in items:
        t = it["type"]
        seen[t] = seen.get(t, 0) + 1
        name = type_label(t) + (f" ({seen[t]} of {counts[t]})" if counts[t] > 1 else "")
        neg = " neg" if it["amount"] < 0 else ""
        rows.append(f'<div class="lg-row"><span class="lg-name">{esc(name)}</span><span class="lg-dots"></span>'
                    f'<span class="lg-amt{neg}">{esc(num(it["amount"]))}</span></div>')
    note_html = f'<div class="lg-note">{esc(note)}</div>' if note else ""
    return h(f'<div class="ledger"><div class="lg-title">{esc(title)}</div>', *rows,
             f'<div class="lg-total"><span>Total</span><span>{esc(num(total))}</span></div>', note_html, "</div>")


def split_bar(d):
    """One bar for the whole bill: every charge and tax line sized by its amount, taxes in yellow."""
    tc, tt = d.get("total_charges"), d.get("total_taxes")
    ch = [(type_label(c["type"]), c["amount"], CHARGE_COL.get(c["type"], "#D6DFEC"))
          for c in d.get("charges") or [] if c["amount"] > 0]
    tx = [(type_label(t["type"]), t["amount"], TAX_COL.get(t["type"], "#FFEFB8"))
          for t in d.get("taxes") or [] if t["amount"] > 0]
    if not ch and tc and tc > 0:
        ch = [("Charges", tc, CHARGE_COL["energy"])]
    if not tx and tt and tt > 0:
        tx = [("Taxes (combined)", tt, TAX_COL["gst"])]
    ch_sum, tx_sum = sum(a for _, a, _ in ch), sum(a for _, a, _ in tx)
    if not ch_sum or not tx_sum:
        return ""

    def group(items, total):
        segs = "".join(f'<div class="seg" title="{esc(n)}: {esc(money(a))}" style="flex:{a};background:{c}"></div>'
                       for n, a, c in items)
        return f'<div style="flex:{total};min-width:0"><div class="segs">{segs}</div></div>'

    pct = tx_sum / (ch_sum + tx_sum) * 100
    legend = (f'<div class="legend"><span><i style="background:{CHARGE_COL["energy"]}"></i>'
              f'Electricity charges {esc(money(ch_sum))} ({100 - pct:.1f}%)</span>'
              f'<span><i style="background:{TAX_COL["gst"]}"></i>Taxes {esc(money(tx_sum))} ({pct:.1f}%)</span></div>')
    return h('<div class="split">', group(ch, ch_sum), group(tx, tx_sum), "</div>", legend)


def plate(d):
    load = d.get("sanctioned_load_kw")
    rows = [("Provider", d.get("provider") or "n/a"), ("Tariff", d.get("tariff") or "n/a"),
            ("Sanctioned load", "n/a" if load is None else f"{load:g} kW"),
            ("Billing month", month_label(d.get("bill_month"), long=True)),
            ("Reading date", fmt_date(d.get("reading_date"))), ("Issue date", fmt_date(d.get("issue_date"))),
            ("Previous reading", num(d.get("previous_reading"))), ("Current reading", num(d.get("current_reading")))]
    return h('<div class="plate">', *(f'<div class="pl-row"><span>{esc(k)}</span><b>{esc(v)}</b></div>' for k, v in rows), "</div>")


def section(title, sub=""):
    st.markdown(f'<div class="sec">{esc(title)}</div>' + (f'<p class="sec-sub">{esc(sub)}</p>' if sub else ""),
                unsafe_allow_html=True)


# ---------------------------------------------------------------- charts
def style_chart(chart):
    return (chart.configure_view(stroke=None)
            .configure_axis(labelFont=FONT, titleFont=FONT, labelColor=MUTED, titleColor=MUTED,
                            gridColor="#E3E8EF", domainColor="#C3CBD8", tickColor="#C3CBD8")
            .configure_legend(labelFont=FONT, labelColor=INK, symbolType="square"))


def usage_chart(usage):
    df = pd.DataFrame(usage)
    df["label"] = df["month"].map(month_label)
    df["current"] = False
    df.loc[df.index[-1], "current"] = True
    order = list(dict.fromkeys(df["label"]))
    angle = 0 if len(df) <= 8 else -45
    bars = (alt.Chart(df).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
            .encode(x=alt.X("label:N", sort=order, title=None, axis=alt.Axis(labelAngle=angle)),
                    y=alt.Y("units:Q", title="Units"),
                    color=alt.condition("datum.current", alt.value(INK), alt.value(SLATE)),
                    tooltip=[alt.Tooltip("month:N", title="Month"), alt.Tooltip("units:Q", title="Units")])
            .properties(height=270))
    previous = df[~df["current"]]
    if previous.empty:
        return style_chart(bars), None
    avg = float(previous["units"].mean())
    rule = (alt.Chart(pd.DataFrame({"avg": [avg]})).mark_rule(color=RED, strokeDash=[5, 4], strokeWidth=1.6)
            .encode(y="avg:Q"))
    return style_chart(bars + rule), avg


def billing_chart(billing):
    bdf = pd.DataFrame(billing)
    bdf["label"] = bdf["month"].map(month_label)
    order = list(dict.fromkeys(bdf["label"]))
    long = bdf.melt(id_vars=["month", "label"], value_vars=["billed", "paid"], var_name="Type", value_name="PKR").dropna()
    chart = (alt.Chart(long).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
             .encode(x=alt.X("label:N", sort=order, title=None, axis=alt.Axis(labelAngle=0 if len(bdf) <= 8 else -45)),
                     xOffset="Type:N", y=alt.Y("PKR:Q", title="PKR"),
                     color=alt.Color("Type:N", scale=alt.Scale(domain=["billed", "paid"], range=[SLATE, TEAL]),
                                     legend=alt.Legend(orient="top", title=None)),
                     tooltip=[alt.Tooltip("month:N", title="Month"), "Type", alt.Tooltip("PKR:Q", format=",.0f")])
             .properties(height=250))
    return style_chart(chart)


# ---------------------------------------------------------------- pipeline
def run_pipeline(data, suffix):
    """Image bytes -> (details, history). Writes a temp file because the model client reads from a path."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
        f.write(data)
        path = f.name
    try:
        with st.status("Decoding your bill...", expanded=True) as status:
            st.write("Reading the bill image")
            base = extract_bill(path)
            st.write("Checking that the totals add up")
            details = fix_bill(base, path, lambda fn: fn())
            st.write("Reading the usage and payment history")
            try:
                hist = extract_history(path, details)
            except Exception:
                hist = None
            status.update(label="Bill decoded", state="complete", expanded=False)
        return details, hist
    finally:
        os.unlink(path)


def ask(data, suffix, details, hist, question):
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
        f.write(data)
        path = f.name
    try:
        res = answer_bill(path, details, [("Q1", question)], facts_text(details, hist))
        return res.get("Q1")
    finally:
        os.unlink(path)


# ---------------------------------------------------------------- page
st.markdown(CSS, unsafe_allow_html=True)
st.markdown(
    h('<div class="topbar"><div class="mark">', BOLT, '</div><span class="wordmark">Bill Decoder</span>',
      '<span class="sp"></span><span class="tag">K-Electric</span><span class="tag">LESCO</span>',
      f'<span class="tag">IESCO</span><span class="tag">{esc(MODEL_NAME)}</span></div>'),
    unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### How it works")
    st.markdown(
        "**1. Read.** A vision model turns the image into a strict JSON schema.\n\n"
        "**2. Verify.** Code checks that totals add up and repairs known IESCO/LESCO layout slips.\n\n"
        "**3. Compute.** The model only *reads* the history tables. Averages, trends and comparisons are calculated in Python.\n\n"
        "**4. Explain.** Answers are written in plain English, from the bill only."
    )
    st.divider()
    st.caption("The image is processed in memory for this session only and is not saved. "
               "Blur personal details before sharing screenshots.")
    st.caption("Built for Women Tech Quest 2026, Build Track.")

intro = st.container()
up = st.file_uploader("Upload a bill image (PNG or JPG)", type=["png", "jpg", "jpeg"])

if not up:
    with intro:
        left, right = st.columns([1.05, 1], gap="large")
        with left:
            st.markdown('<div class="hero-h">Your electricity bill, in plain words.</div>'
                        '<p class="hero-p">Upload a photo or screenshot of a K-Electric, LESCO or IESCO bill. '
                        'You get every figure pulled out and clear answers about what you are paying for.</p>',
                        unsafe_allow_html=True)
        with right:
            rows = "".join(f'<div class="rc-row"><span class="rc-term">{esc(t)}</span><span class="rc-def">{esc(x)}</span></div>'
                           for t, x in TERMS)
            st.markdown(f'<div class="receipt"><div class="rc-title"><span>On your bill</span><span>In plain words</span></div>{rows}</div>',
                        unsafe_allow_html=True)
    st.caption("Decoding takes roughly 20-30 seconds on the free API tier. Tilted photos and Urdu bills work too.")
    st.markdown(
        '<div class="trust">'
        '<div><b>The model reads. Python calculates.</b>Averages, comparisons and forecasts are computed in code, so arithmetic is never guessed.</div>'
        '<div><b>Totals are cross-checked.</b>Net charges plus taxes must equal the current bill before results are shown.</div>'
        '<div><b>Only what the bill shows.</b>When a value is missing or estimated, the answer says so.</div>'
        '</div>', unsafe_allow_html=True)
    st.stop()

data = up.getvalue()
suffix = os.path.splitext(up.name)[1].lower() or ".png"
key = hashlib.sha256(data).hexdigest()

if st.session_state.get("key") != key:
    try:
        details, hist = run_pipeline(data, suffix)
    except Exception as e:
        st.error(f"Could not decode this bill: {e}. Check that the image is a clear photo of an electricity bill "
                 "and that API_KEY is set in .env, then upload it again.")
        st.stop()
    st.session_state.update(key=key, details=details, hist=hist, chat=[])
details, hist = st.session_state["details"], st.session_state["hist"]

st.markdown(bill_head(details) + plain_summary(details), unsafe_allow_html=True)

left, right = st.columns([1, 2.2], gap="large")
with left:
    st.image(data, caption="Uploaded bill", width="stretch")
    st.markdown(plate(details), unsafe_allow_html=True)

with right:
    # a segmented control (not st.tabs) keeps the selected view after reruns
    view = st.segmented_control("View", VIEWS, default="Overview", key="view", label_visibility="collapsed") or "Overview"

    if view == "Overview":
        section("Where the money goes", "Every charge and tax line on the bill, sized by its amount.")
        st.markdown(split_bar(details), unsafe_allow_html=True)
        tc, tt, cb = details.get("total_charges"), details.get("total_taxes"), details.get("current_bill")
        a, b = st.columns(2, gap="medium")
        with a:
            charges = details.get("charges") or []
            if charges:
                st.markdown(ledger("Charges", charges, tc), unsafe_allow_html=True)
            else:
                st.caption("No itemised charges were read from this bill.")
        with b:
            taxes = details.get("taxes") or []
            share = f"{tt / cb * 100:.1f}% of this month's bill" if tt and cb else ""
            if taxes:
                st.markdown(ledger("Taxes", taxes, tt, share), unsafe_allow_html=True)
            else:
                st.markdown(
                    f'<div class="ledger"><div class="lg-title">Taxes</div>'
                    f'<div class="lg-total" style="border-top:0;margin-top:0"><span>Combined</span><span>{esc(num(tt))}</span></div>'
                    f'<div class="lg-note">This bill prints one combined tax amount, so there is no itemised list. {esc(share)}</div></div>',
                    unsafe_allow_html=True)

        usage = (hist or {}).get("usage_history") or []
        if usage:
            section("Units per month", "The dark bar is this bill's month.")
            chart, avg = usage_chart(usage)
            st.altair_chart(chart, width="stretch")
            if avg is not None:
                st.caption(f"Dashed line: average of the earlier months shown ({avg:,.1f} units).")

        billing = [r for r in (hist or {}).get("billing_history") or [] if r.get("billed") is not None]
        if billing:
            section("Billed and paid", "A month with no paid bar had no payment recorded. The newest month may simply not be due yet.")
            st.altair_chart(billing_chart(billing), width="stretch")

    elif view == "Ask about this bill":
        st.markdown("Pick a quick question, choose another one, or type your own. "
                    "Answers use only what the bill shows.")
        pending = None
        cols = st.columns(3)
        for i, (name, q) in enumerate(QUICK.items()):
            if cols[i % 3].button(name, key=f"quick{i}", width="stretch"):
                pending = q
        more = st.selectbox("More questions", ["(choose one)"] + MORE_QUESTIONS, key="more")
        if st.button("Ask selected question", disabled=more == "(choose one)"):
            pending = more
        typed = st.chat_input("Ask your own question about this bill...")
        pending = typed or pending

        if pending:
            with st.spinner("Working it out..."):
                try:
                    ans = ask(data, suffix, details, hist, pending)
                except Exception as e:
                    ans = f"This request failed ({e}). Try asking again."
            st.session_state["chat"].append((pending, ans or "No answer was returned."))

        for q, a in reversed(st.session_state["chat"]):
            with st.chat_message("user"):
                st.write(q)
            with st.chat_message("assistant", avatar="⚡"):
                st.write(a)
        if not st.session_state["chat"]:
            st.markdown('<div class="note">Answers about the future, such as next month\'s units, are labelled as estimates.</div>',
                        unsafe_allow_html=True)

    else:
        st.json(details)
        st.download_button("Download JSON", json.dumps(details, indent=2, ensure_ascii=False),
                           file_name="bill.json", mime="application/json")