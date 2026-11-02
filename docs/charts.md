# How each chart is made

Every number is computed in the backend (`backend/app/main.py`) from the harmonised panel; the
frontend only draws it. Unless a chart says otherwise:

- **Total pay** = fixed salary + annual bonus + multi-year bonus + share-based pay + other
  benefits, in k€. Pension cost and one-time payments are not included.
- **Full-year** = at least 360 days on the board that year. Pay statistics use full-year
  executives only, so joiners and leavers do not pull medians down.
- **DAX** = firms listed in the DAX that year. This is the only group covered both before and
  after the 2022 change in reporting rules (§162 AktG), so comparisons over time use it.
- The dotted vertical line marks that 2022 change.

## Overview

- **Headline numbers.** Median DAX CEO pay in the first and last year; share of women among
  DAX board members; the median CEO-to-employee pay ratio (see *Board & workforce*); and counts
  of firms, people and person-years in the whole dataset.
- **DAX CEO pay, 2006–2024.** For each year, the pay of all full-year DAX CEOs is sorted and the
  median (line), middle 50 % (dark band) and middle 80 % (light band) are drawn. Co-CEOs count
  individually.

## Pay trends

The DAX / All firms switch changes which firms are included in every chart on the page.

- **Pay level by role.** Same method as the Overview chart, done separately for CEOs, CFOs and
  other board members: median line plus a band for the middle 50 %.
- **What the package is made of.** For each year, the five pay components are added up over all
  full-year executives who report all five, and each component is shown as a share of that sum.
  Executives with a missing component are left out, so a gap is not read as zero.
- **CEO premium.** For each firm and year, CEO pay is divided by the median pay of the other
  board members; the chart shows the median of that ratio across firms.
- **Opt-outs from individual disclosure.** Share of firms per year that reported only a board
  total instead of pay per person (allowed under §286(5) HGB until 2021).

## Companies

- **Company list.** One row per firm with its latest year in the data, index, board total and
  the CEO's pay.
- **Headline numbers (company page).** Board total and number of members, the CEO's pay, the
  CEO-to-employee ratio and the shareholder return in the latest year.
- **Board pay by component.** For each year, the pay of all board members of the firm is added
  up per component and stacked. Grey bars are years in which the firm reported only a board
  total.
- **CEO pay against the DAX.** The firm's CEO pay per year (highest-paid full-year CEO) against
  the median full-year DAX CEO from the Overview chart.
- **Board members table.** Every member in the chosen year with each pay component; part-year
  members show their days in office.
- **Plan design.** The CEO's named bonus and long-term criteria with their KPI categories, the
  bonus cap (2022 onwards), and how ESG enters the plans (2023 onwards).
- **More data.** Columns from extra firm and firm-year tables, if any were added
  ([`data.md` → Adding data](data.md#adding-data)).

## Executives

- **Distribution of executive pay.** One dot per person and firm in the chosen year, placed by
  total pay and coloured by role; dots are stacked so they do not overlap. Hollow dots were on
  the board for only part of the year. Clicking a dot opens that person's page.
- **Pay by year (person page).** The person's pay per year, stacked by component, across all
  firms they sat on.

## Peer benchmark

How the six peer definitions work and how they are tested: [`peers.md`](peers.md). Every chart
uses full-year executives paid at least 100 k€, compares them only with executives in the same
role and year at other firms, and gives no result with fewer than five peer firms.
**Pay ÷ peer median** is drawn on a log scale (2× and 0.5× are equally far from 1×); the shaded
zones mark the verdicts *above* (from 1.5×) and *below* (up to 1 / 1.5). Colour marks the
family of a definition (fixed groups, industry first, nearest neighbours), the symbol the
definition within it.

- **Headline numbers.** Typical gap (median distance between pay and the peer median) of the
  best and the weakest definition and of no selection; share of CEO-years *above* under some
  definitions but not under all; share of the gap closed within a year under the definition
  with the strongest pull.
- **Which definition explains pay best.** Four dot charts on the executive-years every
  definition covers: typical gap, gap closed within a year (slope of next year's pay change on
  today's gap, net of year means; bars ±2 standard errors clustered by firm), year-to-year
  overlap of a firm's peer firms (Jaccard), and coverage. The grey row and line: every other
  firm as peers.
- **Do the definitions agree?** For each pair: rank correlation of pay ÷ peer median, or the
  share of equal verdicts.
- **Same executive, different verdicts.** One row per CEO (or CFO) of the chosen year, one
  symbol per definition, a grey line from the lowest to the highest ratio; the right column
  counts the definitions with verdict *above*. Rows are sorted by that count, then by pay.
  Clicking opens the company.
- **Robust and fragile verdicts, year by year.** Share of benchmarked CEOs whose pay is at least
  1.5× the peer median under every definition that benchmarks them (dark) or under some only
  (light); then the share of flagged CEO-years whose flag depends on the definition for verdict
  lines from 1.25× to 3×; below, the list of the robust CEO-years with their lowest and highest
  ratio.
- **Pay drifts toward the peer median.** For each definition, executive-years in ten
  equal-sized groups by their gap this year, against the mean change in log pay to the next
  year (same person, firm and role, same disclosure regime), net of that year's mean change.
  Grey: the same with every other firm as peers.
- **Definition pages** (`#/peers/<id>`): the definition's peer groups with their median pay
  (group definitions) or how many chosen peers share the executive's NAICS sector
  (nearest-neighbour definitions); the cluster profiles and the silhouette / coverage curves
  for K = 4–12 (K-means); the forest's out-of-firm accuracy and permutation importance (random
  forest); a beeswarm of pay ÷ peer median; the peers of the selected executive against their
  pay quartiles; and a table of all executives.
- **CEO pay against peers (company page).** Per year, pay ÷ peer median of the highest-paid
  full-year CEO under each definition.

## Pay prediction

How the fourteen models work and are tested: [`prediction.md`](prediction.md). **Typical miss** is
the mean absolute error of log pay, shown as a percentage; **skill** compares a model with "last
year + market drift" on the same executive-years. Everything is scored per disclosure regime.

- **Headline numbers.** The most accurate model for total pay and its typical miss; in how many
  pay items a model that looks only at the executive's own past is the most accurate; the range
  of the neural network's typical miss over three random starts; the pay gap of women and of
  German executives after role, firm size, tenure and age (shown, never used for predictions).
- **Who beats "last year + market drift"?** One cell per model and pay item: how much smaller
  its error is than the baseline's. A ring marks the model shown on executive pages.
- **How far off, and how honest the range.** Per pay item: typical miss of each model, and the
  share of actual values inside its stated 80 % range.
- **Error grows with the horizon.** Typical miss by years ahead; horizons with fewer than 30
  test pairs are left out.
- **Is the item paid at all?** Accuracy of the logistic regression for bonuses, share plans and
  pensions against "paid then if paid now".
- **Model pages** (`#/prediction/<id>`): predicted against paid one year ahead; error by years
  ahead; stated against achieved range coverage (50, 80, 90 %); typical miss by role; what is
  specific to the model (coefficients of the linear and change models, permutation importance of
  boosting and the forest, firm effects with their shrinkage weight, the three runs of the neural
  network); the largest misses.
- **Forecast and comparison (executive page).** The person's history, the forecast median and
  its 80 % range per pay item and model, assuming they stay in the role; chance that the item is
  paid at all; rank among peers; total pay against average staff cost; the same board; a
  what-if panel (role, index, board size, yearly growth; an association, not a cause).
- **Board pay forecast (company page).** Next year's total pay of each current full-year board
  member: forecast median and 80 % range, with last year's pay as a tick.

## Pay design (2022–2024, DAX)

- **Capped bonus / capped LTI.** Share of DAX CEOs whose plan has a cap, from the yes/no cap
  columns in the DSW study. **Median bonus cap**: median of the stated cap, as a percentage of
  the target bonus.
- **What variable pay is tied to.** Each firm's free-text bonus criteria (the first three per
  plan) are mapped to 11 categories with `data/reference/kpi_categories.csv`. For each category
  the bar shows the share of DAX firms whose CEO plan uses at least one criterion of it, for
  the annual bonus and the long-term plans separately. Every name in the mapping was checked by
  hand ([`data.md`](data.md#kpi-categories)).
- **Criteria by firm.** The same mapping as a grid: a filled cell means the firm's CEO plan uses
  that category. Hovering shows the criteria in the firm's own words.
- **Bonus caps.** One dot per firm at its CEO's bonus cap (% of target bonus).
- **ESG weight in variable pay.** One line per firm: the weight of ESG targets in the annual
  bonus (yellow) and the LTI (green), from the DSW ESG file (2023 onwards). Only plans where
  ESG is a weighted target are drawn. Plans where ESG is a multiplier on the payout have no
  weight and are listed below the chart. When a plan has both, the target's weight is used.
- **CEO pay against the maximum.** The CEO's total pay plus pension cost, divided by the
  maximum remuneration set in the firm's pay policy (§87a AktG). Recorded for 2024 only.

## Board & workforce

- **Board composition.** Per year, the share of women and of members without German
  nationality among all board members, part-year members included. Dual nationals with German
  citizenship count as German.
- **Median board age, external hires.** Median of (year − birth year) across board members;
  share of CEOs and of all members hired from outside the firm, shown only for years where the
  hiring origin is known for at least 80 % of members.
- **CEO pay against average staff cost.** For each firm, full-year CEO pay divided by personnel
  expenses per employee (personnel expenses ÷ employees, from the DSW study). Personnel
  expenses include social security and pension cost, so the ratio is on the low side. The
  dashed line is the median across firms.
- **Pay change against shareholder return.** One dot per firm: the change in CEO pay against
  the previous year (same CEO, full year in both years) on one axis, the firm's total
  shareholder return (share price change plus dividend) on the other; Pearson r in the corner.

## Data quality

- **Sources loaded.** Every file set found in `data/raw/`, with its reporting regime and the number
  of person-years and firm-years it contributes.
- **Firms per year.** Number of firms per year, split by index listing; "Other" means the index
  field is empty in the source. Hovering shows executives and opt-outs.
- **Field coverage.** For each field and year, the share of rows that have a value: pay fields
  per person-year, firm fields per firm-year.
- **Issues.** Every problem found while merging the sources, grouped into *needs a decision*,
  *handled in code* and *worth knowing*, with counts.
