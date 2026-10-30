#!/usr/bin/env python3
"""Re-run the whole procedure (generate -> tune on dev -> freeze -> test) for several seeds.

Each seed tunes only on its own dev split, so this measures variance of the *procedure*,
not of one lucky config. It never feeds test results back into tuning.
"""
import statistics as st

import eval_screen as E

rows = []
print("seed | frozen config | dev avoided / FA | test avoided / FA | test failures missed")
for seed in range(1, 11):
    dev, test = E.generate(800, seed)
    cfg, dv, _, ok = E.tune(dev, 0.01)
    t = E.summarize(E.run(test, E.screen, cfg))
    rows.append(t)
    print(f"{seed:>4} | {cfg['mode']}/{cfg['window']}/{cfg['empty_optional']}"
          f" | {dv['evaluations_avoided']:.1%} / {dv['false_accepts']}"
          f" | {t['evaluations_avoided']:.1%} / {t['false_accepts']}"
          f" | {t['failures_missed_rate']:.1%}")
av = [r["evaluations_avoided"] for r in rows]
ms = [r["failures_missed_rate"] for r in rows]
print(f"\ntest avoided: mean {st.mean(av):.1%}, range {min(av):.1%}-{max(av):.1%}")
print(f"test failures missed: mean {st.mean(ms):.1%}, range {min(ms):.1%}-{max(ms):.1%}")
