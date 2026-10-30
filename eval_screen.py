#!/usr/bin/env python3
"""
Cheaper first-pass evaluation for a document-extraction agent.

Pipeline
  1. generate   synthetic invoices + expected fields + agent outputs (seeded)
  2. baseline   compare every output to its expected answer (the "expensive" evaluator)
  3. screen     cheap check using ONLY (document, agent output) -> accept | defer
  4. tune       grid-search screen config on the DEV split, write frozen_config.json
  5. test       load the frozen config, run once on the TEST split, report

Run:  python eval_screen.py            (all stages)
      python eval_screen.py --stage tune
      python eval_screen.py --stage test
Stdlib only. Python 3.9+.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import random
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

OUT = Path(__file__).parent / "results"

# --------------------------------------------------------------------------- schema
REQUIRED = ["vendor", "invoice_number", "invoice_date", "total"]
OPTIONAL = ["po_number"]
FIELDS = REQUIRED + OPTIONAL
KIND = {"vendor": "text", "invoice_number": "id", "invoice_date": "date",
        "total": "money", "po_number": "id"}

FAILURE_TYPES = {"missing_required", "missing_optional", "spurious_optional",
                 "wrong_ungrounded", "wrong_distractor"}

# --------------------------------------------------------------------------- normalisation
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
_LONG = "|".join(MONTHS)
_SHORT = "|".join(m[:3] for m in MONTHS)
DATE_RE = re.compile(
    rf"\d{{4}}-\d{{2}}-\d{{2}}|\d{{2}}/\d{{2}}/\d{{4}}"
    rf"|(?:{_LONG}) \d{{1,2}}, \d{{4}}|\d{{1,2}} (?:{_SHORT}) \d{{4}}")
MONEY_RE = re.compile(r"\$?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}")
DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%d %b %Y"]


def parse_date(s: str):
    s = s.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def parse_money(s: str):
    try:
        return round(float(s.strip().replace("$", "").replace(",", "")) * 100)
    except ValueError:
        return None


def blank(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def norm(field: str, v):
    """Canonical form used by the baseline. Unparseable values fall back to text."""
    if blank(v):
        return None
    v = str(v)
    if KIND[field] == "date":
        return parse_date(v) or v.strip().lower()
    if KIND[field] == "money":
        m = parse_money(v)
        return m if m is not None else v.strip().lower()
    return " ".join(v.split()).lower()


# --------------------------------------------------------------------------- dataset
VENDORS = ["Cedar Ridge Supply", "Harbor Point Logistics", "Bluefin Office Goods",
           "Summit Lab Equipment", "Oakline Printing", "Redwood Cloud Services",
           "Granite Fabrication", "Lumen Electrical", "Pacific Paper Co",
           "Northgate Catering"]
DATE_STYLES = ["long", "iso", "us", "short"]


def fmt_date(d: date, style: str) -> str:
    return {"long": f"{MONTHS[d.month - 1]} {d.day}, {d.year}",
            "iso": d.isoformat(),
            "us": f"{d.month:02d}/{d.day:02d}/{d.year}",
            "short": f"{d.day} {MONTHS[d.month - 1][:3]} {d.year}"}[style]


def fmt_money(x: float) -> str:
    return f"${x:,.2f}"


@dataclass
class Case:
    case_id: str
    layout: str
    document: str
    expected: dict
    output: dict
    error_type: str
    error_field: str | None


def render(rng, layout, f) -> str:
    D = lambda d: fmt_date(d, f["date_style"])
    M = fmt_money
    if layout == "form":
        mid = [f"{rng.choice(['Invoice #', 'Invoice No.', 'Invoice Number'])}: {f['inv_no']}",
               f"{rng.choice(['Invoice Date', 'Date', 'Date of Issue'])}: {D(f['date'])}",
               f"Due Date: {D(f['due'])}",
               f"Account: {f['account']}"]
        if f["po"]:
            mid.append(f"{rng.choice(['PO Number', 'Purchase Order'])}: {f['po']}")
        rng.shuffle(mid)
        money = [f"Subtotal: {M(f['subtotal'])}", f"Tax: {M(f['tax'])}"]
        if f["revised"]:
            money.append(f"Total: {M(f['gross'])} - revised to {M(f['total'])} "
                         f"after credit of {M(f['credit'])}")
        else:
            money.append(f"Total: {M(f['total'])}")
        return "\n".join([f["vendor"], "INVOICE", *mid, *money, "Thank you for your business."])

    if layout == "email":
        body = (f"Hi,\n\nPlease find attached invoice {f['inv_no']} from {f['vendor']}, "
                f"dated {D(f['date'])}. ")
        if f["revised"]:
            body += (f"The original total of {M(f['gross'])} has been revised to "
                     f"{M(f['total'])} after a {M(f['credit'])} credit. ")
        else:
            body += (f"The amount due is {M(f['total'])} (subtotal {M(f['subtotal'])} "
                     f"plus {M(f['tax'])} tax). ")
        body += f"Payment is due by {D(f['due'])}. "
        if f["po"]:
            body += f"This bills against purchase order {f['po']}. "
        body += f"Your account number is {f['account']}.\n\nThanks,\n{f['vendor']} Billing"
        return body

    # compact: one-line summary with an ambiguous shared "Dates:" header
    parts = [f["vendor"], f"Inv {f['inv_no']}",
             f"Dates: {D(f['date'])} (issue), {D(f['due'])} (payment)",
             f"Acct {f['account']}"]
    if f["po"]:
        parts.append(f"Purchase order {f['po']}")
    if f["revised"]:
        parts.append(f"Amount: {M(f['gross'])} less credit {M(f['credit'])} = {M(f['total'])}")
    else:
        parts.append(f"Amount: {M(f['total'])} incl. tax {M(f['tax'])}")
    return " | ".join(parts)


def mutate(rng, field, value: str) -> str:
    """Plausible-looking wrong value that does not appear in the document."""
    if field == "vendor":
        i = rng.randrange(1, len(value) - 1)
        while value[i] == " ":
            i = rng.randrange(1, len(value) - 1)
        return value[:i] + value[i + 1:]
    if field == "invoice_date":
        return (date.fromisoformat(value) + timedelta(days=rng.choice([-1, 1]))).isoformat()
    digits = [i for i, c in enumerate(value) if c.isdigit()]
    for _ in range(20):  # transpose two adjacent digits
        j = rng.randrange(len(digits) - 1)
        a, b = digits[j], digits[j + 1]
        if b == a + 1 and value[a] != value[b]:
            s = list(value)
            s[a], s[b] = s[b], s[a]
            return "".join(s)
    i = rng.choice(digits)  # fallback: replace one digit
    s = list(value)
    s[i] = rng.choice([d for d in "0123456789" if d != s[i]])
    return "".join(s)


def make_case(rng, i: int) -> Case:
    style = rng.choice(["inv", "num", "alnum"])
    n = rng.randint(10000, 99999)
    inv_no = {"inv": f"INV-{n}", "num": str(n),
              "alnum": f"{rng.choice('ABCDEFGH')}{rng.randint(100, 999)}-{rng.randint(10, 99)}"}[style]
    account = str(rng.randint(10000, 99999)) if style == "num" else f"ACCT-{rng.randint(10000, 99999)}"
    d = date(2025, 1, 1) + timedelta(days=rng.randrange(365))
    due = d + timedelta(days=rng.choice([15, 30, 45]))
    subtotal = round(rng.uniform(40, 9500), 2)
    tax = round(subtotal * rng.choice([0.0725, 0.085, 0.0925]), 2)
    gross = round(subtotal + tax, 2)
    revised = rng.random() < 0.15
    credit = round(rng.uniform(5, gross * 0.2), 2) if revised else 0.0
    total = round(gross - credit, 2)
    po = f"PO-{rng.randint(1000, 9999)}" if rng.random() < 0.5 else None
    f = dict(vendor=rng.choice(VENDORS), inv_no=inv_no, account=account, date=d, due=due,
             subtotal=subtotal, tax=tax, gross=gross, credit=credit, total=total, po=po,
             revised=revised, date_style=rng.choice(DATE_STYLES))
    layout = rng.choices(["form", "email", "compact"], weights=[0.5, 0.3, 0.2])[0]
    doc = render(rng, layout, f)

    expected = {"vendor": f["vendor"], "invoice_number": inv_no, "invoice_date": d.isoformat(),
                "total": f"{total:.2f}", "po_number": po}

    # Correct outputs sometimes use the document's surface format (should still pass).
    out = dict(expected)
    if rng.random() < 0.3:
        out["invoice_date"] = fmt_date(d, f["date_style"])
    if rng.random() < 0.3:
        out["total"] = fmt_money(total)

    # Values that ARE in the document but belong to a different field.
    distractors = [("invoice_date", due.isoformat()), ("invoice_number", account)]
    if layout != "compact":
        distractors.append(("total", f"{subtotal:.2f}"))
    if revised:
        distractors.append(("total", f"{gross:.2f}"))

    kind = rng.choices(["correct", "missing_required", "optional_error", "wrong_ungrounded",
                        "wrong_distractor"], weights=[52, 8, 8, 14, 18])[0]
    err_field = None
    if kind == "correct":
        etype = "correct_filled_optional" if po else "correct_empty_optional"
    elif kind == "missing_required":
        etype, err_field = kind, rng.choice(REQUIRED)
        out[err_field] = rng.choice([None, ""])
    elif kind == "optional_error":
        err_field = "po_number"
        if po:
            etype, out["po_number"] = "missing_optional", None
        else:
            etype = "spurious_optional"
            out["po_number"] = rng.choice([f"PO-{rng.randint(1000, 9999)}", account])
    elif kind == "wrong_ungrounded":
        etype, err_field = kind, rng.choice(REQUIRED)
        out[err_field] = mutate(rng, err_field, expected[err_field])
    else:
        etype = kind
        err_field, out[err_field] = rng.choice(distractors)

    return Case(f"doc{i:04d}", layout, doc, expected, out, etype, err_field)


def generate(n: int, seed: int):
    rng = random.Random(seed)
    cases = [make_case(rng, i) for i in range(n)]
    split_rng = random.Random(seed + 1)
    idx = list(range(n))
    split_rng.shuffle(idx)
    dev = [cases[i] for i in sorted(idx[: n // 2])]
    test = [cases[i] for i in sorted(idx[n // 2:])]
    return dev, test


# --------------------------------------------------------------------------- baseline evaluator
def baseline_evaluate(output: dict, expected: dict) -> dict:
    """The expensive, reference-based evaluator: field-by-field normalised comparison."""
    fields = {f: norm(f, output.get(f)) == norm(f, expected.get(f)) for f in FIELDS}
    return {"pass": all(fields.values()), "fields": fields}


# --------------------------------------------------------------------------- cheap screen
# Label vocabulary. Keys starting with "_" are labels of OTHER things in the document
# (due date, subtotal...) that the screen must not confuse with the target field.
KEYWORDS = {
    "invoice_date": ["invoice date", "date of issue", "issued", "dated", "dates", "date"],
    "invoice_number": ["invoice number", "invoice no.", "invoice no", "invoice #", "invoice", "inv"],
    "total": ["amount due", "balance due", "total", "amount"],
    "po_number": ["purchase order", "po number", "po"],
    "_due": ["due date", "due", "deadline"],
    "_subtotal": ["subtotal"],
    "_tax": ["tax"],
    "_account": ["account", "acct"],
}
_KW = sorted(((k, f) for f, ks in KEYWORDS.items() for k in ks), key=lambda x: -len(x[0]))
_KW_FIELD = {k: f for k, f in _KW}
_KW_RE = re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(k) for k, _ in _KW) + r")(?![a-z0-9-])")


def keyword_hits(doc: str):
    return [(m.start(), m.end(), _KW_FIELD[m.group(1)]) for m in _KW_RE.finditer(doc.lower())]


def value_positions(doc: str, field: str, value: str) -> list[int]:
    """Where in the document does this output value appear (format-insensitive)?"""
    if KIND[field] == "date":
        t = parse_date(value)
        return [m.start() for m in DATE_RE.finditer(doc) if t and parse_date(m.group()) == t]
    if KIND[field] == "money":
        t = parse_money(value)
        return [m.start() for m in MONEY_RE.finditer(doc) if t is not None and parse_money(m.group()) == t]
    needle = re.escape(" ".join(value.split()).lower())
    if KIND[field] == "id":
        needle = rf"(?<![a-z0-9]){needle}(?![a-z0-9])"
    return [m.start() for m in re.finditer(needle, doc.lower())]


def anchored(hits, pos: int, field: str, mode: str, window: int) -> bool:
    if mode == "none":
        return True
    prior = [h for h in hits if h[1] <= pos and pos - h[1] <= window]
    if not prior:
        return False
    if mode == "nearest":
        return max(prior, key=lambda h: h[1])[2] == field
    return any(h[2] == field for h in prior)  # mode == "any"


def screen(document: str, output: dict, cfg: dict):
    """Accept or defer using ONLY the document and the agent output. No expected answer."""
    reasons = []
    hits = keyword_hits(document)
    for f in FIELDS:
        v = output.get(f)
        if blank(v):
            if f in REQUIRED:
                reasons.append(f"{f}: required field empty")
            elif cfg["empty_optional"] == "always_defer":
                reasons.append(f"{f}: empty optional (policy defers all)")
            elif any(h[2] == f for h in hits):
                reasons.append(f"{f}: empty but document has a {f} label")
            continue
        pos = value_positions(document, f, str(v))
        if not pos:
            reasons.append(f"{f}: value not found in document")
        elif f != "vendor" and not any(anchored(hits, p, f, cfg["mode"], cfg["window"]) for p in pos):
            reasons.append(f"{f}: value found but not under a {f} label")
    return ("accept" if not reasons else "defer"), reasons


# Naive comparison strategies (also doc+output only).
def screen_accept_all(document, output, cfg=None):
    return "accept", []


def screen_required_present(document, output, cfg=None):
    missing = [f for f in REQUIRED if blank(output.get(f))]
    return ("defer", missing) if missing else ("accept", [])


# --------------------------------------------------------------------------- metrics
def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def run(cases, screen_fn, cfg):
    rows = []
    for c in cases:
        decision, reasons = screen_fn(c.document, c.output, cfg)   # no c.expected here
        verdict = baseline_evaluate(c.output, c.expected)          # reference, for scoring only
        rows.append({"case": c, "decision": decision, "reasons": reasons, "pass": verdict["pass"]})
    return rows


def summarize(rows, eval_cost=1.0, screen_cost=0.01):
    n = len(rows)
    acc = [r for r in rows if r["decision"] == "accept"]
    fails = [r for r in rows if not r["pass"]]
    fa = [r for r in acc if not r["pass"]]
    by_type = {}
    for r in rows:
        t = by_type.setdefault(r["case"].error_type, {"n": 0, "accepted": 0, "deferred": 0})
        t["n"] += 1
        t["accepted" if r["decision"] == "accept" else "deferred"] += 1
    by_layout = {}
    for r in rows:
        t = by_layout.setdefault(r["case"].layout, {"n": 0, "accepted": 0, "false_accepts": 0})
        t["n"] += 1
        t["accepted"] += r["decision"] == "accept"
        t["false_accepts"] += r["decision"] == "accept" and not r["pass"]
    saved = len(acc) * eval_cost - n * screen_cost  # evaluator calls avoided minus screening spend
    return {
        "n": n,
        "failures": len(fails),
        "accepted": len(acc),
        "evaluations_avoided": len(acc) / n,
        "false_accepts": len(fa),
        "false_accept_rate_of_all": len(fa) / n,
        "false_accept_rate_of_all_ci95": wilson(len(fa), n),
        "failures_missed_rate": len(fa) / len(fails) if fails else 0.0,
        "failures_missed_rate_ci95": wilson(len(fa), len(fails)),
        "accept_precision": (len(acc) - len(fa)) / len(acc) if acc else None,
        "net_eval_units_saved": saved,
        "break_even_cost_per_false_accept": (saved / len(fa)) if fa else None,
        "by_error_type": by_type,
        "by_layout": by_layout,
    }


# --------------------------------------------------------------------------- tune / test
GRID = {"mode": ["none", "any", "nearest"],
        "window": [10, 20, 40, 80, 160],
        "empty_optional": ["defer_if_label", "always_defer"]}


def tune(dev, fa_budget: float):
    results = []
    for mode, window, empty in itertools.product(*GRID.values()):
        cfg = {"mode": mode, "window": window, "empty_optional": empty}
        s = summarize(run(dev, screen, cfg))
        results.append((cfg, s))
    feasible = [r for r in results if r[1]["false_accept_rate_of_all"] <= fa_budget]
    pool = feasible or results
    # Max savings within the false-accept budget; ties -> fewer false accepts -> smaller window.
    best_cfg, best = max(pool, key=lambda r: (r[1]["evaluations_avoided"],
                                               -r[1]["false_accepts"], -r[0]["window"]))
    return best_cfg, best, results, bool(feasible)


def total_cost(s, c_fail, eval_cost=1.0, screen_cost=0.01):
    """N*C_screen + N_deferred*C_eval + N_missed*C_fail."""
    return s["n"] * screen_cost + (s["n"] - s["accepted"]) * eval_cost + s["false_accepts"] * c_fail


def stage_costs(args):
    """Cost sensitivity. For each assumed cost of a missed failure, pick the config that
    minimises total cost on DEV (priced objective, no FA cap), then score it once on TEST.
    'Evaluate everything' is the reference: N * C_eval, zero missed failures."""
    dev, test = load_jsonl(OUT / "dev.jsonl"), load_jsonl(OUT / "test.jsonl")
    configs = [dict(zip(GRID, v)) for v in itertools.product(*GRID.values())]
    dev_s = [(c, summarize(run(dev, screen, c))) for c in configs]
    frozen = json.loads((OUT / "frozen_config.json").read_text())["config"]
    rows = []
    for c_fail in args.fail_costs:
        cfg, best = min(dev_s, key=lambda x: (total_cost(x[1], c_fail, args.eval_cost, args.screen_cost),
                                               x[1]["false_accepts"]))
        everything = len(test) * args.eval_cost
        fs = summarize(run(test, screen, frozen))
        if total_cost(best, c_fail, args.eval_cost, args.screen_cost) >= len(dev) * args.eval_cost:
            picked, avoided, missed, cost = "evaluate everything (no screen)", "0.0%", 0, f"{everything:.0f}"
        else:
            ts = summarize(run(test, screen, cfg))
            picked = f"{cfg['mode']}/{cfg['window']}/{cfg['empty_optional']}"
            avoided, missed = f"{ts['evaluations_avoided']:.1%}", ts["false_accepts"]
            cost = f"{total_cost(ts, c_fail, args.eval_cost, args.screen_cost):.0f}"
        rows.append({
            "C_fail (x eval)": c_fail,
            "picked on dev": picked,
            "test avoided": avoided,
            "test missed": missed,
            "test cost": cost,
            "frozen-config cost": f"{total_cost(fs, c_fail, args.eval_cost, args.screen_cost):.0f}",
            "evaluate-all cost": f"{everything:.0f}",
        })
    md = ["# Cost sensitivity (hypothetical units: C_eval = %g, C_screen = %g)" % (args.eval_cost, args.screen_cost),
          "", "Total cost = N*C_screen + N_deferred*C_eval + N_missed*C_fail. "
          "Config chosen on dev for each C_fail; test scored once.", "",
          fmt_table(rows, list(rows[0])), ""]
    (OUT / "cost_sensitivity.md").write_text("\n".join(md))
    print("\n".join(md))


def save_jsonl(path, cases):
    with open(path, "w") as fh:
        for c in cases:
            fh.write(json.dumps(asdict(c)) + "\n")


def load_jsonl(path):
    return [Case(**json.loads(l)) for l in open(path)]


def check_labels(cases):
    """Sanity: injected error types must agree with the baseline verdict."""
    bad = [c.case_id for c in cases
           if baseline_evaluate(c.output, c.expected)["pass"] == (c.error_type in FAILURE_TYPES)]
    assert not bad, f"label/baseline disagreement: {bad[:5]}"


def fmt_table(rows, cols):
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join(str(r[c]) for c in cols) + " |" for r in rows]
    return "\n".join(out)


def stage_generate(args):
    OUT.mkdir(exist_ok=True)
    dev, test = generate(args.n, args.seed)
    check_labels(dev + test)
    save_jsonl(OUT / "dev.jsonl", dev)
    save_jsonl(OUT / "test.jsonl", test)
    print(f"generated {len(dev)} dev / {len(test)} test cases (seed={args.seed})")


def stage_tune(args):
    dev = load_jsonl(OUT / "dev.jsonl")
    cfg, s, results, feasible = tune(dev, args.fa_budget)
    frozen = {"config": cfg, "fa_budget": args.fa_budget, "budget_met_on_dev": feasible,
              "dev_metrics": {k: v for k, v in s.items() if not k.startswith("by_")}}
    (OUT / "frozen_config.json").write_text(json.dumps(frozen, indent=2))
    grid_rows = [{"mode": c["mode"], "window": c["window"], "empty_optional": c["empty_optional"],
                  "avoided": f"{r['evaluations_avoided']:.1%}", "false_acc": r["false_accepts"],
                  "missed": f"{r['failures_missed_rate']:.1%}"}
                 for c, r in sorted(results, key=lambda x: -x[1]["evaluations_avoided"])]
    (OUT / "dev_grid.md").write_text(fmt_table(grid_rows, list(grid_rows[0])) + "\n")
    print(f"DEV  frozen config: {cfg}  (budget met: {feasible})")
    print(f"DEV  avoided {s['evaluations_avoided']:.1%}, false accepts {s['false_accepts']}/{s['n']}, "
          f"missed {s['failures_missed_rate']:.1%} of failures")


def stage_test(args):
    test = load_jsonl(OUT / "test.jsonl")
    cfg = json.loads((OUT / "frozen_config.json").read_text())["config"]  # frozen; never re-tuned
    strategies = {"accept_all": (screen_accept_all, None),
                  "required_present": (screen_required_present, None),
                  "grounded_label_screen": (screen, cfg)}
    report, lines = {}, ["# Test-split report", "", f"Frozen config: `{json.dumps(cfg)}`", ""]
    summary_rows = []
    for name, (fn, c) in strategies.items():
        rows = run(test, fn, c)
        s = summarize(rows, args.eval_cost, args.screen_cost)
        report[name] = s
        lo, hi = s["failures_missed_rate_ci95"]
        summary_rows.append({
            "strategy": name, "avoided": f"{s['evaluations_avoided']:.1%}",
            "false_accepts": f"{s['false_accepts']}/{s['n']}",
            "failures_missed": f"{s['failures_missed_rate']:.1%} [{lo:.1%}, {hi:.1%}]",
            "accept_precision": f"{s['accept_precision']:.1%}" if s["accept_precision"] is not None else "-",
            "break_even_FA_cost": (f"{s['break_even_cost_per_false_accept']:.1f}x eval"
                                   if s["break_even_cost_per_false_accept"] else "n/a (0 FA)")})
        if name == "grounded_label_screen":
            main_rows = rows
    lines += ["## Strategies", "", fmt_table(summary_rows, list(summary_rows[0])), ""]

    s = report["grounded_label_screen"]
    type_rows = []
    for t, v in sorted(s["by_error_type"].items()):
        is_fail = t in FAILURE_TYPES
        type_rows.append({"error_type": t, "is_failure": "yes" if is_fail else "no", "n": v["n"],
                          "accepted": v["accepted"], "deferred": v["deferred"],
                          "meaning_of_accept": "FALSE ACCEPT" if is_fail else "call saved"})
    lines += ["## Grounded-label screen by error type", "", fmt_table(type_rows, list(type_rows[0])), ""]
    lay_rows = [{"layout": k, **v} for k, v in sorted(s["by_layout"].items())]
    lines += ["## By document layout", "", fmt_table(lay_rows, list(lay_rows[0])), ""]

    fas = [r for r in main_rows if r["decision"] == "accept" and not r["pass"]]
    lines += [f"## False accepts ({len(fas)})", ""]
    for r in fas:
        c = r["case"]
        lines += [f"### {c.case_id} ({c.layout}, {c.error_type}, field `{c.error_field}`)",
                  f"- agent output: `{c.output[c.error_field]}`  expected: `{c.expected[c.error_field]}`",
                  "```", c.document, "```", ""]
    (OUT / "test_report.md").write_text("\n".join(lines))
    (OUT / "test_report.json").write_text(json.dumps(report, indent=2))
    print("\n".join(lines[: lines.index(f"## False accepts ({len(fas)})")]))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", choices=["all", "generate", "tune", "test", "costs"], default="all")
    ap.add_argument("--fail-costs", type=float, nargs="+", default=[1, 10, 25, 50, 75, 100, 500])
    ap.add_argument("--n", type=int, default=800)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--fa-budget", type=float, default=0.01,
                    help="max false accepts as a fraction of ALL dev cases when tuning")
    ap.add_argument("--eval-cost", type=float, default=1.0)
    ap.add_argument("--screen-cost", type=float, default=0.01)
    args = ap.parse_args()
    if args.stage in ("all", "generate"):
        stage_generate(args)
    if args.stage in ("all", "tune"):
        stage_tune(args)
    if args.stage in ("all", "test"):
        stage_test(args)
    if args.stage in ("all", "costs"):
        stage_costs(args)


if __name__ == "__main__":
    main()
