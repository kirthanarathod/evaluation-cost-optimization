# Cost sensitivity (hypothetical units: C_eval = 1, C_screen = 0.01)

Total cost = N*C_screen + N_deferred*C_eval + N_missed*C_fail. Config chosen on dev for each C_fail; test scored once.

| C_fail (x eval) | picked on dev | test avoided | test missed | test cost | frozen-config cost | evaluate-all cost |
|---|---|---|---|---|---|---|
| 1 | nearest/40/defer_if_label | 57.2% | 8 | 183 | 213 | 400 |
| 10 | any/10/defer_if_label | 48.2% | 2 | 231 | 258 | 400 |
| 25 | any/10/defer_if_label | 48.2% | 2 | 261 | 333 | 400 |
| 50 | any/10/defer_if_label | 48.2% | 2 | 311 | 458 | 400 |
| 75 | any/10/defer_if_label | 48.2% | 2 | 361 | 583 | 400 |
| 100 | evaluate everything (no screen) | 0.0% | 0 | 400 | 708 | 400 |
| 500 | evaluate everything (no screen) | 0.0% | 0 | 400 | 2708 | 400 |
