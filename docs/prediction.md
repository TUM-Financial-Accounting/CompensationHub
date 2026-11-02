# Pay prediction

> What will an executive be paid in one to five years, how sure can we be, and which kind of
> model should answer that — a simple rule, a regression, or machine learning?

Fourteen models forecast seven pay items side by side, on the same executive-years, with the
same test. Several are on the page because they are expected to lose: "why not a neural
network?" gets a measured answer instead of an opinion. Code: `backend/app/forecast.py`; views:
*Pay prediction* (`#/prediction`, one page per model), a forecast panel on every executive page
and a board forecast on every company page. Numbers below are from the panel as of
21 October 2026 (data up to 2024); the dashboard always shows the current ones, and
`uv run python -m app.forecast` prints them.

## The question every model answers

For a full-year executive (pay ≥ 100 k€, as in the peer benchmark) seen in year *t*: what is the
pay item in year *t + h*, h = 1…5, **for the same person, firm and role**, within one disclosure
regime. A forecast therefore assumes the executive stays in the role; role changes are what-if
questions (below). Pairs that cross the 2021/22 break are never used: §162 AktG changed what
"share-based pay" and "multi-year bonus" mean.

## Pay items

| Item | Model shape | Why |
|---|---|---|
| Total pay | change models and the rest | the headline number |
| Fixed salary | same | moves in contract steps: last year's value is hard to beat |
| Annual bonus, multi-year bonus, share-based pay, pension, other benefits | **two parts**: paid at all? (logistic regression), then how much if paid | zero for some executives in some years (multi-year bonus: most of them after 2022) |
| One-time payments | **no model** | sign-on and severance payments are events, not a series; the Add data check flags them instead |

Amounts are modelled as logarithms: pay is skewed, effects are proportional, and an error of
0.2 in log pay reads as "about 20 % off". The dashboard shows `exp(error) − 1`.

## Models

| Family | Model | What it does |
|---|---|---|
| Own past | Same as last year | ŷ(t+h) = y(t): the random walk |
| | Last year + market drift | log ŷ = log y(t) + h·μ, μ = median yearly change of continuing executives |
| | Own trend | a straight line through the executive's own past years, extended (stands in for ARIMA, which needs longer series than any executive has) |
| Comparable executives | Median of year, role and index | what "typical pay" means without a model |
| | Peer median | the peers of the peer benchmark's best definition ([`peers.md`](peers.md)) |
| | Same board | the median of the board colleagues × the usual ratio of the role to the rest of the board |
| Expected pay (level) | Linear | log pay relative to the group median on role, index, board size, tenure, age, employees, horizon (Core, Holthausen & Larcker 1999) |
| | + gender and nationality | the same with *woman* and *German nationality*; shown for its coefficients, **never used for predictions** |
| | + firm effect | the firm's own average deviation from the linear model, shrunk toward zero the fewer observations it rests on (empirical Bayes: weight n / (n + σ²/τ²)) |
| Change models | Change model | **median** regression (Koenker & Bassett 1978) of log y(t+h) − log y(t) on the gap to the group median, role, index, board size, tenure, age, employees, horizon |
| | Change model, §162 only | the same, fitted on 2022+ pairs only: does the old history help? |
| | Gradient boosting | scikit-learn's histogram boosting (LightGBM's algorithm) on the same inputs plus the last value |
| | Random forest | 100 trees on the same inputs |
| | Neural network | a perceptron with 32 and 16 units; run with three seeds |

LightGBM and SHAP, planned at the start, are replaced by this comparison (decided 21 Oct 2026):
scikit-learn's boosting is the same algorithm and loses to simpler models on this data, and the
linear and median-regression models explain themselves through their coefficients.

Every model gets the same inputs where it can use them. Employees exist only from 2022; they
enter as log employees plus an "employees known" flag, so one model covers both regimes.
Personnel expenses are left out (almost collinear with employees), TSR too (120 firm-years).

## Evaluation

- **Rolling origin.** For every origin year *o* with at least 1,000 earlier pairs, each model is
  fitted on the pairs whose *target* year is ≤ o — exactly what was known in *o* — and predicts
  every pair that starts in *o*. Origins: every year from 2009 to 2020 and 2022–2023.
  A firm's own past is allowed: it is known when the forecast is made. (The peer benchmark
  cross-fits by firm because there a firm must not be its own peer; here the honest
  constraint is time.)
- **Error:** mean absolute error of the log value; **skill** = 1 − error / error of "last year +
  market drift" *on the same pairs*, so a model that predicts only easy pairs gets no credit for
  it. **Coverage:** the share of pairs a model can predict at all (the own trend needs two past
  years, the peer median five peer firms).
- **Ranges** are *online conformal*: a prediction made in year *o* gets the 10 % and 90 %
  quantiles of the same model's errors (same item and horizon) at origins before *o*. The
  scorecard checks whether 80 % ranges hold 80 % of the actual values, and the model pages
  check 50 % and 90 % too. Live forecasts for horizons that §162 data cannot test yet borrow the
  errors of all test years and are marked.
- **The model shown on executive pages** is, per pay item, the one with the lowest error on the
  §162 test pairs among those that predict at least half of them. The demographic variant is
  never chosen.

## Results

§162 test years (forecasts from 2022 and 2023, 496 executive-year pairs for total pay); error
is the mean absolute log error, 0.16 ≈ 17 % off.
The table leaves out three models: the own trend, the change model fitted on §162 data only and
the demographic variant. The dashboard shows all fourteen.

| Model | Total pay | Fixed | Annual bonus | Share-based | Pension | Other |
|---|---|---|---|---|---|---|
| Last year + market drift | **0.158** | 0.073 | **0.315** | **0.226** | 0.247 | **0.396** |
| Same as last year | 0.170 | 0.079 | 0.319 | 0.238 | **0.230** | **0.396** |
| Random forest | 0.184 | **0.072** | 0.354 | 0.249 | 0.240 | 0.520 |
| Change model (median regression) | 0.188 | 0.074 | 0.334 | 0.261 | 0.247 | 0.433 |
| Same board | 0.194 | 0.126 | 0.332 | 0.265 | 0.328 | 0.932 |
| Neural network | 0.203 | 0.093 | 0.360 | 0.306 | 0.328 | 0.553 |
| Gradient boosting | 0.211 | 0.079 | 0.378 | 0.277 | 0.264 | 0.533 |
| Expected pay + firm effect | 0.272 | 0.190 | 0.479 | 0.414 | 0.379 | 0.985 |
| Expected pay (linear) | 0.314 | 0.241 | 0.483 | 0.423 | 0.482 | 1.170 |
| Median of year, role and index | 0.324 | 0.272 | 0.493 | 0.402 | 0.497 | 1.184 |
| Peer median | 0.338 | 0.255 | 0.489 | 0.459 | 0.563 | 1.193 |

1. **The simple models win.** For six of seven pay items the best forecast is "same as last
   year", with or without the market drift; for fixed salary a random forest wins by 1 %
   (0.072 vs. 0.073). In the 2006–2021 years the median-regression change model ties the drift
   baseline (0.264 vs. 0.261 for total pay). Pay is sticky: last year's value carries almost
   everything a model could know.
2. **Machine learning does not help, and the neural network is fragile.** Boosting, the forest
   and the network all trail the drift baseline on total pay (−16 % to −33 % skill). Three
   network runs that differ only in their random start miss by 35 %, 37 % and 41 % on the full
   test set: the answer depends on chance.
3. **Characteristics alone are far off.** Models that ignore the executive's own pay (group
   median, peer median, expected pay) have errors of 0.27–0.34, twice the baseline: role, index
   and board size explain the level of pay, not who earns what within it. The firm effect helps
   most of them (0.314 → 0.272), and the board (0.194) beats the peers (0.338): colleagues on the
   same board are the better reference.
4. **The 2006–2021 history helps.** The change model fitted on §162 pairs alone is 4 % worse
   than the drift baseline on the pairs it can predict (2023 forecasts only).
5. **The ranges are honest, mostly on the safe side.** For total pay, 80 % ranges hold 85–92 %
   of §162 values: pay moved less after 2022 than in the earlier years the errors come from.
   The exception is *other benefits*, where most models' ranges hold only 52–79 %: benefits
   moved more after 2022 than the earlier errors suggest; the data does not say why.
6. **Paid or not** is as predictable from "paid now" as from a logistic regression (e.g.
   share-based pay 93 % vs. 96 %); only for the annual bonus does the model do better
   (92 % vs. 90 %).
7. **The parts add up:** the best component forecasts sum to 0.99× the best total-pay forecast
   (median over executives).
8. **Demographic variant:** after role, firm size, tenure and age, women earn 2 % less and German
   executives 12 % less than others. These coefficients are shown on the model's page and used
   nowhere else.

## What-if

`GET /api/whatif` (and the panel on every executive page) changes role, index, board size,
employees or yearly growth and keeps what is specific to the executive:

    y' = y · exp( Σ βₖ · (x'ₖ − xₖ) ) · (1 + g)^years

β comes from a regression of log pay on role, index, board size, tenure, age and employees
**within each year** (year fixed effects), one per pay item; g is the market drift unless given.
For role changes the panel also shows what was observed: the median pay change of executives
who moved between the same roles at the same firm (e.g. CFO → CEO). These are associations,
not causal effects: a firm that promotes its CFO is not a random firm.

## References

- Core, Holthausen & Larcker (1999), *Corporate governance, CEO compensation, and firm
  performance*, Journal of Financial Economics 51(3) — expected pay and its residual.
- Koenker & Bassett (1978), *Regression quantiles*, Econometrica 46(1).
- Romano, Patterson & Candès (2019), *Conformalized quantile regression*, NeurIPS; online
  conformal ranges as in Gibbs & Candès (2021), *Adaptive conformal inference under
  distribution shift*, NeurIPS.
- Efron & Morris (1975), *Data analysis using Stein's estimator and its generalizations*, JASA
  70 — shrinkage of firm effects.
- Hyndman & Athanasopoulos, *Forecasting: Principles and Practice* — rolling-origin evaluation
  and why the random walk is the benchmark.
- Gabaix & Landier (2008), *Why has CEO pay increased so much?*, QJE 123(1) — pay scales with
  firm size, the reason the size proxies carry the level models.
