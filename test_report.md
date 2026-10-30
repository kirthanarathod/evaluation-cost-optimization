# Test-split report

Frozen config: `{"mode": "any", "window": 20, "empty_optional": "defer_if_label"}`

## Strategies

| strategy | avoided | false_accepts | failures_missed | accept_precision | break_even_FA_cost |
|---|---|---|---|---|---|
| accept_all | 100.0% | 179/400 | 100.0% [97.9%, 100.0%] | 55.2% | 2.2x eval |
| required_present | 90.5% | 141/400 | 78.8% [72.2%, 84.1%] | 61.0% | 2.5x eval |
| grounded_label_screen | 49.0% | 5/400 | 2.8% [1.2%, 6.4%] | 97.4% | 38.4x eval |

## Grounded-label screen by error type

| error_type | is_failure | n | accepted | deferred | meaning_of_accept |
|---|---|---|---|---|---|
| correct_empty_optional | no | 100 | 90 | 10 | call saved |
| correct_filled_optional | no | 121 | 101 | 20 | call saved |
| missing_optional | yes | 11 | 0 | 11 | FALSE ACCEPT |
| missing_required | yes | 38 | 0 | 38 | FALSE ACCEPT |
| spurious_optional | yes | 13 | 0 | 13 | FALSE ACCEPT |
| wrong_distractor | yes | 54 | 5 | 49 | FALSE ACCEPT |
| wrong_ungrounded | yes | 63 | 0 | 63 | FALSE ACCEPT |

## By document layout

| layout | n | accepted | false_accepts |
|---|---|---|---|
| compact | 74 | 29 | 0 |
| email | 122 | 60 | 1 |
| form | 204 | 107 | 4 |

## False accepts (5)

### doc0033 (form, wrong_distractor, field `invoice_number`)
- agent output: `ACCT-42565`  expected: `D194-44`
```
Cedar Ridge Supply
INVOICE
Date: 2025-07-16
Due Date: 2025-08-15
Invoice Number: D194-44
Account: ACCT-42565
Subtotal: $6,149.19
Tax: $522.68
Total: $6,671.87
Thank you for your business.
```

### doc0374 (form, wrong_distractor, field `invoice_number`)
- agent output: `ACCT-48784`  expected: `INV-63514`
```
Bluefin Office Goods
INVOICE
Account: ACCT-48784
Invoice Number: INV-63514
Due Date: 08/23/2025
Date of Issue: 08/08/2025
Subtotal: $67.60
Tax: $4.90
Total: $72.50
Thank you for your business.
```

### doc0492 (form, wrong_distractor, field `invoice_number`)
- agent output: `66773`  expected: `63184`
```
Harbor Point Logistics
INVOICE
Due Date: 2025-08-09
Invoice No.: 63184
Account: 66773
PO Number: PO-5653
Date of Issue: 2025-07-25
Subtotal: $825.12
Tax: $76.32
Total: $901.44
Thank you for your business.
```

### doc0519 (form, wrong_distractor, field `invoice_number`)
- agent output: `55317`  expected: `44382`
```
Lumen Electrical
INVOICE
Date: 12/14/2025
Invoice Number: 44382
Account: 55317
Due Date: 01/28/2026
Subtotal: $3,917.60
Tax: $333.00
Total: $4,250.60
Thank you for your business.
```

### doc0676 (email, wrong_distractor, field `total`)
- agent output: `3486.61`  expected: `3368.77`
```
Hi,

Please find attached invoice 33647 from Redwood Cloud Services, dated 21 Dec 2025. The original total of $3,486.61 has been revised to $3,368.77 after a $117.84 credit. Payment is due by 20 Jan 2026. Your account number is 99441.

Thanks,
Redwood Cloud Services Billing
```
