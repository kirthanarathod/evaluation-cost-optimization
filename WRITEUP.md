# Making extraction evaluation cheaper without hiding failures

## Problem

Every output from an invoice-extraction agent goes to an expensive evaluator. I built
a cheap first pass that accepts easy cases and defers the rest to the evaluator. The
first pass sees only the document and the agent output, never the expected answer.
**Costs are hypothetical:** evaluator = 1 unit, screen = 0.01 unit.

## Approach

- **Data.** 800 seeded synthetic invoices in three layouts (form, email, compact),
  split 400 dev / 400 test.
- **Fields.** Four are required. `po_number` is optional and legitimately empty on
  about half the invoices.
- **Agent outputs.** About half are correct. The rest contain one injected error:
  - a missing required field
  - a missing optional field
  - a spurious optional field
  - a value not in the document
  - a value copied from another field (due date, subtotal, account number, pre-credit
    total)
- **Baseline evaluator.** Compares each field to the expected answer after
  normalising dates and money.
- **Screen ("grounded labels").** It accepts only if all four checks pass:
  1. Required fields are filled.
  2. Every value appears in the document.
  3. Each value sits just after a label for *its own* field, not after "Due",
     "Subtotal" or "Account".
  4. An empty optional field has no matching label in the document.
- **Tuning.** On dev only: label rule, window size and empty-field policy, tuned to
  maximise calls avoided with false accepts ≤ 1%. The chosen config was frozen to a
  file, and test was scored once.

## Results (test: 400 cases, 179 failures)

| Strategy | Calls avoided | Failures accepted | Failures missed (95% CI) |
|---|---|---|---|
| Accept if required fields present | 90.5% | 141 | 78.8% |
| **Grounded-label screen (frozen)** | **49.0%** | **5** | **2.8% [1.2–6.4%]** |

**By error type.** The screen deferred all of these:

- missing required: 38/38
- missing or spurious optional: 24/24
- not-in-document: 63/63

It deferred 49 of 54 copied-from-another-field errors, and **all 5 false accepts are
of that type**. Example: under `Invoice Number: D194-44 / Account: ACCT-42565`, the
agent returned `ACCT-42565`. The value is in the document and close to an
"Invoice Number" label, so the screen accepted it. Across 10 seeds (procedure re-run
end to end), the screen avoided 21–49% of calls and missed 0.5–3.7% of failures.

**Cost sensitivity.** Total cost = N·C_screen + N_deferred·C_eval + N_missed·C_fail.
For each assumed cost of a missed failure (C_fail), I re-selected the config on dev by
minimising total cost, with "evaluate everything" as an allowed choice. I then scored
it once on test.

| C_fail (× eval call) | Picked on dev | Test cost | Frozen config | Evaluate all |
|---|---|---|---|---|
| 1 | loose (nearest/40) | 183 | 213 | 400 |
| 10 | tight (any/10) | 231 | 258 | 400 |
| 50 | tight (any/10) | 311 | 458 | 400 |
| 100+ | **evaluate everything** | 400 | 708 | 400 |

My original frozen config loses money past about 38× (it missed 5 failures). A
cost-aware config breaks even at about 95× (it missed 2). If a wrong invoice total
costs more than ~100 evaluator calls, the cheapest correct choice is no shortcut.

## Limitations

- The screen cannot separate two plausible values that are both in the document, and
  these are the costliest extraction errors.
- My original objective capped misses rather than pricing them. I did not re-tune it
  after seeing test results. The table above uses a fresh, dev-only selection.
- Test false accepts (1.25% of cases across seeds) exceeded the 1% dev budget.
- Synthetic, in-distribution data: the label vocabulary is hand-built, and these
  numbers are a ceiling.
- Ground-truth baseline: a real evaluator (e.g. an LLM judge) makes errors too.
- Not counted: dev labelling, maintenance as templates change, and the monitoring lost
  on accepted cases.

**Verdict:** the screen is not safe as a replacement for the evaluator. It is
worthwhile only where a missed failure costs less than about 100 evaluator calls,
and then only with a random audit of accepted cases.

## Next steps

1. Add a competing-candidate check: defer when the document has two well-labelled
   values of the right type. Validate it on a fresh split, not this test set.
2. Test on unseen layouts (tables, OCR noise), kept separate from these results.
3. Price failures per field (a wrong total costs more than a wrong PO number).
4. Audit 5–10% of accepted cases and alarm on the accepted-slice failure rate.

Future Work: The above improvements are proposed as future enhancements and were kept outside the scope of this time-constrained assignment.
