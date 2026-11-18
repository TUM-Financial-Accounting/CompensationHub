# Red flags

> Which executive-years should a supervisory board or an investor look at, and how much does the
> answer depend on the method that flags them?

Two kinds of check run side by side on the same executive-years: **rules** taken from the law
and the governance code, and **statistical detectors** that score how unusual pay is. Every flag
carries its evidence as a sentence. A flag is a reason to look, not a verdict: the robustness of
a flag is how many checks raise it. Code: `backend/app/redflags.py`; views: *Red flags*
(`#/flags`) and a *Red flags* panel on every company and executive page. Numbers below are from
the panel as of 18 November 2026 (data up to 2024); the dashboard always shows the current ones,
and `uv run python -m app.redflags` prints them.

## Why red flags

§87(1) AktG asks the supervisory board to keep management-board pay appropriate to the tasks,
the performance and the situation of the company, and not above the usual level without special
reasons; for variable pay it should agree a limit for extraordinary developments. §87a AktG adds
a maximum remuneration to every remuneration system, and the German Corporate Governance Code
(DCGK 2022) turns this into recommendations: a maximum (G.1), a peer comparison that avoids an
upward ratchet (G.3), a severance cap of two years' pay (G.13). Investors and proxy advisers
screen pay quantitatively before they read a report: ISS compares a CEO's pay with the median of
its peers ("multiple of median") and with shareholder return. This page does both: rules where
the law or the code gives a line, statistics where it does not.

## The checks in plain words

One real case per check, from the 2024 panel unless noted (the dashboard shows every case with
its evidence).

| Check | What it means | Example |
|---|---|---|
| Pay up by more than half | pay jumped more than 50 % on the year before, same person, firm and role | Fresenius CFO 2024: 664 k€ → 2,810 k€ (+323 %) |
| Pay up while shareholders lost | pay up more than 20 % in a year with negative total shareholder return | Bayer CFO 2024: +29 % (2,573 → 3,327 k€) while TSR was −42 % |
| One-time payment above two years' pay | a severance or sign-on payment larger than two years of normal pay | SAP board member leaving in 2024: 12,970 k€, 2.2× annual pay |
| No individual disclosure (firm-year) | the firm published only the whole board's pay, not each person's | Puma 2020: 12,894 k€ for 3 members, no split |
| Above the peers | paid more than 90 % of comparable executives at similar firms | Deutsche Bank board member 2024: above the peers under 6 of 6 definitions, 2.5–2.7× the peer median |
| Above the forecast range | paid far more than the executive's own history predicted | Fresenius CEO 2024: forecast 1,803 k€ (80 % range up to 2,575 k€), paid 6,671 k€ |
| Above expected pay | paid more than a regression expects for the role, index, board size, tenure, age and firm size | Deutsche Bank board member 2024: expected 2,893 k€, paid 8,994 k€ (3.1×) |
| Robust distance (MCD), isolation forest | the pay *mix* is rare (level, fixed salary, bonus and long-term shares together), even when the total looks normal | Siemens Energy CFO 2024: no long-term pay and 72 % fixed salary; CFOs usually get 31–53 % long-term and 23–40 % fixed |

## Rules

| Rule | Flags | Basis | Years |
|---|---|---|---|
| **Pay up by more than half** | total pay above 1.5× the previous full year (same person, firm, role and regime) | DCGK G.3 (no upward ratchet); "leapfrogging" (DiPrete, Eirich & Pittinsky 2010) | 2007–2021, 2023–2024 |
| **Pay up while shareholders lost** | total pay up more than 20 % while the year's total shareholder return was negative | §87(1) AktG (performance, situation of the company); ISS pay-for-performance | 2023–2024 (TSR comes with the §162 data, and a change needs two §162 years) |
| **One-time payment above two years' pay** | severance or sign-on above 2× annual pay: the previous full year's total at the firm, or for a newcomer this year's total scaled to a full year | DCGK G.13 severance cap | all |
| **No individual disclosure** (firm-year) | only the board total was published (opt-out, §286(5) HGB old version) | transparency; abolished by ARUG II | 2006–2020 |

The thresholds are named constants at the top of `redflags.py` (`JUMP`, `PAY_UP`,
`SEVERANCE_CAP`). One-time payments are not split into severance and sign-on in the sources,
so the severance cap is applied to both and the evidence says which reference it used. Rules
that were considered and left out are under [What was not used](#what-was-not-used-and-why).

## Statistical detectors

Five detectors in two families. Colour in the dashboard marks the family, the symbol the
detector within it.

| | Detector | Score | Flags | From |
|---|---|---|---|---|
| Pay against a reference | **Above the peers** | median over the six peer definitions of log(pay ÷ peers' 90th percentile) | above 0: above the 90th percentile under the median definition (with six definitions the median is the mean of the middle two, so three of six can be enough) | the peer benchmark ([`peers.md`](peers.md)); §87 AktG, DCGK G.3; ISS "multiple of median" |
| | **Above the forecast range** | log pay − log upper end of the 80 % range of last year's forecast (best model for total pay) | above 0 | the pay prediction ([`prediction.md`](prediction.md)); online conformal ranges |
| | **Above expected pay** | log pay − expected log pay: the other firms' median of the year, role and index plus a linear model of role, index, board size, tenure, age and employees | top 5 % of its regime | "excess compensation", Core, Holthausen & Larcker (1999) |
| Pay package as a whole | **Robust distance (MCD)** | Mahalanobis distance from a robust centre and covariance | top 5 % | Rousseeuw & Van Driessen (1999) |
| | **Isolation forest** | how few random splits isolate the row | top 5 % | Liu, Ting & Zhou (2008) |

**The reference detectors** ask one question, *is pay high?*, against three references: the
executive's peers (a local reference: the most similar firms), the executive's own past (the
forecast), and a regression over all firms (a global reference). This is the split that
contextual outlier detection makes between local and global estimates of expected behaviour
(Liang & Parthasarathy 2016). They only flag pay *above* the reference: low pay is not a red flag.

**The package detectors** look at four numbers per executive-year, each against the other
firms of the same year and role: pay against their median of the year, role and index (log),
and the shares of fixed salary, annual bonus and long-term pay (multi-year bonus plus
share-based) in total pay, each minus the other firms' median. They
need fixed salary, annual bonus and share-based pay to be reported; a blank legacy component
means "not reported", not zero ([`data.md`](data.md#settled)). MCD is the classical statistical
test; the isolation forest is the best detector of "global" anomalies in the largest benchmark of
such methods, where deep models are no better (Bouman, Bukhsh & Heskes 2024). Both come from
scikit-learn. A local detector (LOF) and ECOD were tested next to them and left out (see
[What was not used](#what-was-not-used-and-why)).

The evidence of a package flag names the numbers beyond their 2.5 % or 97.5 % percentile in the
regime, with the 10–90 % range of the same year and role ("annual bonus 83 % of pay; CEOs
2012: 0–45 %"); when no single number is extreme, it says that the combination is rare.

## Rules every detector follows

| Rule | Why |
|---|---|
| Cross-fitted by firm | The model that scores a firm (regression, MCD, isolation forest) is fitted on five folds of the *other* firms, as in the peer benchmark, and the medians the numbers are measured against leave the firm out: a firm's own pay never sets its own norm. An executive-year with no other firm in its group (year, role, index) is not judged. |
| Within one disclosure regime | The regression and the package detectors are fitted, and their flag rate set, separately for 2006–2021 and for 2022+ (§162, granted and owed). The forecast detector uses the pay prediction's ranges, which for §162 years come from the errors of all earlier years: they are wider than §162 pay needs, so it flags about 4 % of §162 executive-years against 7 % before. |
| Same year and role | The package numbers and the expected pay are relative to the year and role (and index for the level). |
| A common flag rate for model-based detectors | Each flags the 5 % (`FLAG_SHARE`) highest out-of-firm scores of its regime: a fixed budget, so their flags are comparable (the same idea as cutting conformal p-values at 0.05, Bates et al. 2023, with the scored executive-years as the reference). The peer and forecast detectors keep the 90th percentile and the 80 % range of their own pages. |
| Gender and nationality never enter | As in the pay prediction: the demographic model variant is left out of the forecast count too. |

## How the detectors are compared

There are no labelled cases of "excessive pay", so the detectors are tested the way outlier
detection benchmarks test them: by **planting known anomalies** in real data (ADBench uses the
same idea for its "local", "global" and "dependency" anomaly types). Each anomaly is planted in
each of the 2,863 executive-years that every detector can judge (the bonus anomaly in those of
them with a bonus), one at a time, and the planted row is scored by models that never saw its
firm. Because the norms leave the firm out, planting changes nothing but the row itself:

| Anomaly | What changes | Who should see it |
|---|---|---|
| **Paid more, every year** | pay × 1.25 … 3 in every year of the executive at the firm | peers, expected pay; not the forecast (no jump against the own past) |
| **Pay jumps in one year** | pay × 1.25 … 3 in one year | everyone, the forecast most of all |
| **Same pay, bonus made fixed** | 25–100 % of the annual bonus paid as fixed salary; total unchanged | only the package detectors |

Measured per detector: the share of planted rows flagged at each size (the first size leaves the
data unchanged, so it is the false-alarm rate on these rows) and the AUC at ×2 and at 100 %:
the chance that the planted version scores above a real executive-year of the same rows and
regime (0.5 = blind). Whether the forecast can see a persistent level follows from the best
model's family: a forecast from the executive's own past moves with last year's pay, exactly for
the "own past" models and approximately for change models. Also shown: flags per year and check, and the Jaccard overlap of the flags of
every pair of checks.

## Results (18 November 2026)

| Detector | Flagged (all years) | Without anomaly | AUC: paid more | AUC: jump | AUC: bonus made fixed |
|---|---|---|---|---|---|
| Above the peers | 13.6 % | 13 % | 0.86 | 0.86 | 0.50 |
| Above the forecast range | 6.4 % | 6 % | 0.50 | **0.95** | 0.50 |
| Above expected pay | 5.0 % | 4 % | **0.88** | 0.88 | 0.50 |
| Robust distance (MCD) | 5.0 % | 4 % | 0.72 | 0.72 | 0.90 |
| Isolation forest | 5.0 % | 4 % | 0.71 | 0.71 | **0.91** |

Share of planted rows flagged at ×2 (paid more / jump) and at 100 % (bonus made fixed):

| Detector | Paid more | Jump | Bonus made fixed |
|---|---|---|---|
| Above the peers | 69 % | 69 % | 13 % |
| Above the forecast range | 6 % | **88 %** | 7 % |
| Above expected pay | 47 % | 47 % | 4 % |
| Robust distance (MCD) | 7 % | 7 % | **23 %** |
| Isolation forest | 5 % | 5 % | 9 % |

Rules over all years: 358 of 4,210 year-on-year pay changes are rises of more than half; of the
349 §162 changes with a known TSR, 52 are rises above 20 % and 12 of those came in a year of
negative shareholder return; 100 of 612 one-time payments exceed two years' pay; 197 legacy
firm-years published only the board total (24 in 2006, none in 2021).

1. **No detector sees every anomaly.** The forecast finds nine in ten pay doublings but is blind
   to an executive who is paid double every year; the peers and expected pay see that one but
   not a bonus turned into fixed salary; only the package detectors see the last. This is the
   case for showing several detectors and counting how many raise a flag, instead of picking one.
2. **For pay level, the simple references win.** Against the peers and against expected pay a
   doubling is found with AUC 0.86–0.88; the two package detectors reach 0.71–0.72, because the
   level is one of four numbers they weigh. Machine learning adds nothing over the regression
   here, as in the pay prediction.
3. **For the pay package, the isolation forest and MCD rank best** (AUC 0.91 and 0.90), but at a
   5 % flag rate they catch a quarter or less of fully fixed bonuses (MCD 23 %, isolation forest
   9 %): years without a bonus are common in the real data (a fifth of executives in 2009 and
   2020), so an all-fixed package is unusual but not rare.
4. **The checks flag different executives.** The median pair of checks shares 7 % of its flags
   (Jaccard), and 24 of 27 pairs stay below 0.15. The close pairs are the expected ones: the
   50 % jump rule and the forecast range (0.76), the isolation forest and MCD (0.35), the peers
   and expected pay (0.32).

## What was not used, and why

| Option | Why not |
|---|---|
| Local outlier factor (Breunig et al. 2000) | tested as the local detector next to the isolation forest; the weakest on every planted anomaly (AUC 0.72 on pay level, 0.68 on a bonus made fixed) and no flags the others miss |
| Tail probabilities, ECOD (Li et al. 2022) | tested; below the isolation forest on the package (AUC 0.80 against 0.91) and shared half of its flags with it (Jaccard 0.50) |
| Rule: above the maximum remuneration (§87a(1) AktG, DCGK G.1) | the maximum is recorded for 2024 only, and all five executives above it were leavers whose one-time payments were counted; whether those count towards the maximum is set by each firm's remuneration system, which the data does not record |
| Rule: bonus without a cap (§87(1) sentence 3 AktG) | flagged 2 firm-years in the whole panel (Porsche AG and Henkel, 2022); blank cap fields are "not recorded", not "no cap" |
| Rule: long-term pay above short-term pay (DCGK G.6) | concerns *target* pay, while the §162 data reports pay *granted and owed*, which pays out older plans |
| PyOD (Zhao et al.; PyOD 2 with LLM-based model selection, 2024) | a new dependency for what scikit-learn does; its model selection would replace a choice this page wants to show |
| Deep detectors (autoencoders, Deep SVDD) | no better than the classical ones on tabular benchmarks (ADBench; Bouman et al. 2024), and they explain nothing |
| Zero-shot foundation models (FoMo-0D, Shen, Wen & Akoglu 2025) | the newest research direction for tabular outliers; a PyTorch model whose scores cannot be traced to a reason, which the evidence sentences require |
| Isolation forest or LOF *inside* each peer group | a peer group holds about ten firms, too few to fit them; the package numbers are measured against the year and role instead, and the peer detector covers the peer comparison |
| A fixed share of CEO pay in board pay (CEO pay slice, Bebchuk, Cremers & Peyer 2011) | a possible further rule; it needs a decision on the threshold and the board's full composition every year |
| Say-on-pay votes, realised pay, financial performance | not in the data (decided 19 Sep 2026); TSR exists from 2022 only |

## Limitations

- **No ground truth.** The planted test shows what each detector *can* see, not how many real
  cases of excessive pay exist. A flag is evidence for a closer look.
- **Granted, not realised pay**, as in the rest of the dashboard; share-based grants make single
  years noisy, which the jump rule and the forecast both react to.
- **One-time payments** are not split into severance and sign-on; legacy years report them only
  partly (blank = not reported).
- **Timing under §162.** "Granted and owed" reports a bonus in the year it is paid out, so a
  first or last year on the board can show an unusual package (all fixed, or a large payout);
  the package detectors flag what they see, and the evidence names the numbers.
- **Market-wide years.** The jump rule and the forecast flag far more in 2010 (rebound after
  the 2009 crisis year) and 2021 (rebound after 2020, and the first remuneration reports under
  §162 AktG, which the legacy panel may mix with the old tables): about 18–26 % against 1–11 %
  in other years. Whether the 2021 legacy figures follow the old or the new definitions is not
  checked.
- **One-time payments without a reference** (no previous full year and no days in office; 15
  legacy rows) are not checked.
- **Pay against performance** can only be checked from 2023, when TSR exists for two consecutive
  years; firm financials are not available.
- **Firm-years without an index listing** (117 legacy firm-years, [`data.md`](data.md#needs-a-decision))
  are judged against an "index: none" group that mixes firms before their listing with SDAX and
  TecDAX firms; flags there deserve extra care.

## Code

| Where | What |
|---|---|
| `backend/app/redflags.py` | rules (`rule_checks`, `one_time_checks`, `firm_rules`), reference detectors (`peer_scores`, `forecast_scores`, `expected_scores`), package detectors (`structure_inputs`, `fit_structure`, `structure_scores`), evidence, planted test, `get_flags` (cached in `data/cache/flags.pkl`; seconds after the forecasts) |
| `backend/app/main.py` | `/api/flags`, `/api/flags/executives?year=&firm=&person=` |
| `frontend/src/views/RedFlags.tsx` | the page and the panel on company and executive pages |
| `backend/tests/test_redflags.py` | thresholds, evidence, flag rate per regime, cross-fitting folds, planted-test invariants, routes |
| `uv run python -m app.redflags` | prints flag counts, the planted test and the AUCs |

A new detector is a score per executive-year passed to `checks_of` plus a `Detector` entry; a
model-based one also gets a line in `variant` so the planted test can score it.

## References

- Aktiengesetz §87(1), §87a(1), §162; Handelsgesetzbuch §286(5) (old version); Deutscher Corporate
  Governance Kodex (2022), recommendations G.1, G.3, G.6, G.13.
- ISS, *Pay-for-Performance Mechanics* (relative degree of alignment, multiple of median,
  pay-TSR alignment).
- Bates, S., Candès, E., Lei, L., Romano, Y., Sesia, M. (2023). Testing for outliers with conformal
  p-values. *Annals of Statistics* 51(1), 149–178.
- Bebchuk, L., Cremers, M., Peyer, U. (2011). The CEO pay slice. *Journal of Financial Economics*
  102(1), 199–221.
- Bouman, R., Bukhsh, Z., Heskes, T. (2024). Unsupervised anomaly detection algorithms on
  real-world data: how many do we need? *Journal of Machine Learning Research* 25(105), 1–34.
- Breunig, M., Kriegel, H.-P., Ng, R., Sander, J. (2000). LOF: identifying density-based local
  outliers. *ACM SIGMOD*, 93–104.
- Core, J., Holthausen, R., Larcker, D. (1999). Corporate governance, chief executive officer
  compensation, and firm performance. *Journal of Financial Economics* 51(3), 371–406.
- DiPrete, T., Eirich, G., Pittinsky, M. (2010). Compensation benchmarking, leapfrogs, and the
  surge in executive pay. *American Journal of Sociology* 115(6), 1671–1712.
- Han, S., Hu, X., Huang, H., Jiang, M., Zhao, Y. (2022). ADBench: Anomaly detection benchmark.
  *NeurIPS Datasets and Benchmarks*.
- Li, Z., Zhao, Y., Hu, X., Botta, N., Ionescu, C., Chen, G. (2022). ECOD: Unsupervised outlier
  detection using empirical cumulative distribution functions. *IEEE Transactions on Knowledge
  and Data Engineering*.
- Liang, J., Parthasarathy, S. (2016). Robust contextual outlier detection: where context meets
  sparsity. *ACM CIKM*.
- Liu, F. T., Ting, K. M., Zhou, Z.-H. (2008). Isolation forest. *IEEE ICDM*, 413–422.
- Rousseeuw, P., Van Driessen, K. (1999). A fast algorithm for the minimum covariance determinant
  estimator. *Technometrics* 41(3), 212–223.
- Shen, Y., Wen, H., Akoglu, L. (2025). FoMo-0D: A foundation model for zero-shot tabular outlier
  detection. *Transactions on Machine Learning Research*.
