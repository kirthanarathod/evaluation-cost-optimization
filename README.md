# Cheaper first-pass evaluation for an extraction agent

A cheap screen sits in front of an expensive evaluator. It **accepts** an agent output
only when every extracted value can be found in the source document under the right
kind of label. Everything else is **deferred** to the evaluator. The screen never sees
the expected answer.

## Run

```bash
python3 eval_screen.py              # generate -> tune on dev -> freeze -> test -> cost sensitivity
python3 eval_screen.py --stage tune # re-tune only (writes results/frozen_config.json)
python3 eval_screen.py --stage test # score the frozen config on test only
python3 robustness.py               # repeat the whole procedure for 10 seeds
python3 eval_screen.py --stage costs --fail-costs 1 10 50 100
python3 -m unittest -v              # 18 unit tests
```

Costs are **hypothetical**: evaluator = 1 unit, screen = 0.01 unit
(`--eval-cost`, `--screen-cost`). Missed failures are not priced; see `WRITEUP.md`.

Python 3.9+, standard library only, about 2 seconds. Useful flags: `--n`, `--seed`,
`--fa-budget` (default 0.01), `--eval-cost`, `--screen-cost`.

## Files

| File | What it is |
|---|---|
| `eval_screen.py` | Dataset generator, baseline evaluator, screen, tuning, reporting |
| `test_eval_screen.py` | Unit tests: baseline, each screen decision type, the known blind spot, leakage guard |
| `robustness.py` | Seed sweep: each seed regenerates data and tunes on its own dev split |
| `WRITEUP.md` | One-page approach, results, limitations, next tests |
| `results/dev.jsonl`, `results/test.jsonl` | The generated splits (400 / 400) |
| `results/frozen_config.json` | Config chosen on dev, plus dev metrics |
| `results/dev_grid.md` | Every config tried on dev |
| `results/test_report.md` / `.json` | Test metrics, per-error-type and per-layout tables, every false accept |
| `results/robustness.txt` | Seed-sweep output |
| `results/cost_sensitivity.md` | Total cost vs. assumed cost of a missed failure (config re-selected on dev per cost) |

## Leakage controls

- `screen(document, output, cfg)` takes no expected-answer argument. The expected
  answer is only used by `baseline_evaluate`, for scoring.
- Splits are fixed by document ID before any tuning.
- Tuning reads only `dev.jsonl` and writes `frozen_config.json`. The test stage reads
  that file and never re-tunes.
- `check_labels()` asserts that injected error types agree with the baseline verdict.
  This catches generator or normaliser bugs, such as a correctly formatted date
  variant being marked wrong.

## How I used AI tools

I worked collaboratively with Claude throughout the development process, using it as a coding assistant to brainstorm approaches, refine implementation ideas, and accelerate development. Together, we worked on the synthetic data generator, screening logic, and evaluation framework. I reviewed the implementation, ran experiments, examined false accepts and deferral reasons, and analyzed the results to understand the trade-offs between cost and reliability. I documented the design decisions, findings, and limitations in WRITEUP.md, including the handling of distractor-style errors, ambiguous document layouts, and the decision to keep the test set independent of development tuning.
