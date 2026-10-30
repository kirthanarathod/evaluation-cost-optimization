#!/usr/bin/env python3
"""Unit tests for the baseline evaluator and the cheap screen.  Run: python3 -m unittest -v"""
import unittest

import eval_screen as E

CFG = {"mode": "any", "window": 20, "empty_optional": "defer_if_label"}

DOC = """Cedar Ridge Supply
INVOICE
Invoice Number: INV-12345
Invoice Date: March 4, 2025
Due Date: April 3, 2025
Account: ACCT-99999
Subtotal: $1,000.00
Tax: $85.00
Total: $1,085.00"""

DOC_WITH_PO = DOC.replace("Account:", "PO Number: PO-4321\nAccount:")

EXPECTED = {"vendor": "Cedar Ridge Supply", "invoice_number": "INV-12345",
            "invoice_date": "2025-03-04", "total": "1085.00", "po_number": None}


def out(**changes):
    o = dict(EXPECTED)
    o.update(changes)
    return o


class Baseline(unittest.TestCase):
    def test_exact_match_passes(self):
        self.assertTrue(E.baseline_evaluate(out(), EXPECTED)["pass"])

    def test_format_variants_pass(self):
        o = out(invoice_date="March 4, 2025", total="$1,085.00", vendor="  cedar ridge  SUPPLY")
        self.assertTrue(E.baseline_evaluate(o, EXPECTED)["pass"])

    def test_empty_string_equals_none_for_optional(self):
        self.assertTrue(E.baseline_evaluate(out(po_number=""), EXPECTED)["pass"])

    def test_wrong_total_fails_on_that_field_only(self):
        r = E.baseline_evaluate(out(total="1000.00"), EXPECTED)
        self.assertFalse(r["pass"])
        self.assertEqual([f for f, ok in r["fields"].items() if not ok], ["total"])

    def test_missing_required_fails(self):
        self.assertFalse(E.baseline_evaluate(out(invoice_number=None), EXPECTED)["pass"])


class Screen(unittest.TestCase):
    def decide(self, doc, o):
        return E.screen(doc, o, CFG)[0]

    def test_correct_output_accepted(self):
        self.assertEqual(self.decide(DOC, out()), "accept")

    def test_correct_output_in_document_format_accepted(self):
        self.assertEqual(self.decide(DOC, out(invoice_date="March 4, 2025", total="$1,085.00")), "accept")

    def test_legitimately_empty_optional_accepted(self):
        self.assertEqual(self.decide(DOC, out(po_number=None)), "accept")

    def test_empty_optional_with_label_in_doc_deferred(self):
        self.assertEqual(self.decide(DOC_WITH_PO, out(po_number=None)), "defer")

    def test_missing_required_deferred(self):
        for f in E.REQUIRED:
            with self.subTest(field=f):
                self.assertEqual(self.decide(DOC, out(**{f: ""})), "defer")

    def test_hallucinated_value_deferred(self):
        self.assertEqual(self.decide(DOC, out(total="1058.00")), "defer")
        self.assertEqual(self.decide(DOC, out(invoice_number="INV-12354")), "defer")

    def test_distractor_subtotal_as_total_deferred(self):
        self.assertEqual(self.decide(DOC, out(total="1000.00")), "defer")

    def test_distractor_due_date_as_invoice_date_deferred(self):
        self.assertEqual(self.decide(DOC, out(invoice_date="2025-04-03")), "defer")

    def test_spurious_optional_deferred(self):
        self.assertEqual(self.decide(DOC, out(po_number="ACCT-99999")), "defer")

    def test_known_failure_account_under_invoice_label_accepted(self):
        """Documents the shortcut's blind spot: with the loose 'any' rule, an account
        number sitting right after an Invoice Number line is accepted."""
        doc = "Vendor X\nInvoice Number: D194-44\nAccount: ACCT-42565\nTotal: $10.00"
        hits = E.keyword_hits(doc)
        pos = E.value_positions(doc, "invoice_number", "ACCT-42565")
        self.assertTrue(E.anchored(hits, pos[0], "invoice_number", "any", 20))       # blind spot
        self.assertFalse(E.anchored(hits, pos[0], "invoice_number", "nearest", 20))  # stricter rule catches it

    def test_screen_never_receives_expected(self):
        import inspect
        self.assertEqual(list(inspect.signature(E.screen).parameters), ["document", "output", "cfg"])


class Costs(unittest.TestCase):
    def test_total_cost_formula(self):
        s = {"n": 100, "accepted": 40, "false_accepts": 2}
        # 100*0.01 screen + 60 deferred*1 eval + 2 missed*50
        self.assertAlmostEqual(E.total_cost(s, 50, 1.0, 0.01), 1 + 60 + 100)


class Data(unittest.TestCase):
    def test_generator_labels_agree_with_baseline_and_splits_disjoint(self):
        dev, test = E.generate(200, seed=123)
        E.check_labels(dev + test)
        self.assertFalse({c.case_id for c in dev} & {c.case_id for c in test})
        types = {c.error_type for c in dev + test}
        self.assertTrue({"correct_empty_optional", "missing_required",
                         "wrong_ungrounded", "wrong_distractor"} <= types)


if __name__ == "__main__":
    unittest.main()
