# Peer benchmark

> Is an executive paid more than comparable executives — and how much does the answer depend on
> who counts as comparable?

The benchmark puts six peer definitions side by side on the same executive-years, then tests
which one explains pay best and how often their verdicts agree. Code: `backend/app/peers.py`;
views: *Peer benchmark* in the dashboard (`#/peers`, one page per definition) and a panel on
every company page. Numbers below are from the panel as of 4 October 2026 (data up to 2024);
the dashboard always shows the current ones.

## Why peers

German law asks the supervisory board to keep management-board pay "customary" (*üblich*,
§87(1) AktG). The German Corporate Governance Code makes the comparison concrete: the board
should judge customariness against a peer group of other companies whose composition it
discloses (DCGK G.3; horizontal comparison), and against the firm's own workforce (G.4;
vertical comparison, see *Board & workforce*). Commentary and practice name three criteria for
the horizontal comparison: **industry, size and country**. Proxy advisers build their own peer
groups the same way — ISS takes companies of similar size (revenue and market value within
0.4–2.5×) and widens the industry step by step until it has 12–24 peers; Glass Lewis builds a
network from the peer groups that companies disclose.

The panel has no industry classification and no financials ([`data.md`](data.md)). Country is the
same for everyone; size is known through the index (DAX/MDAX), board size and, from 2022,
employees; industry was added for this benchmark (below).

## Rules every definition follows

| Rule | Why |
|---|---|
| Same year | Pay levels drift; and peers never mix the 2006–2021 and §162 disclosure regimes. |
| Same role (CEO, CFO, other members) | A CEO is compared with CEOs. |
| Never the executive's own firm | You cannot be your own peer (Fin1's rule; FairPay and ProxyEngine kept the firm in its own median). |
| Full-year executives with at least 100 k€ | Joiners and leavers distort pay; below 100 k€ is symbolic pay (Zalando's founders, Medion's founder, United Internet's founder) and would drag peer medians down. |
| Peers are firms | A definition picks peer **firms**; every full-year executive in the same role at those firms is a peer. |
| At least five peer firms | Fewer give no result instead of a fragile number (the original plan's "no result below 5 peers"; Fin1's `INSUFFICIENT_PEERS`). |

For each benchmarked executive-year and definition the API gives the number of peers and peer
firms, the peers' pay quantiles (10/25/50/75/90 %), **pay ÷ peer median**, the **percentile
rank** (share of peers paid less, ties count half) and a **verdict**: *above* from 1.5× the
peer median, *below* up to 1 / 1.5, *in line* in between. The 1.5 is a convention, stated in
every chart; ISS's "multiple of median" concern thresholds for CEOs are higher (around 2.3× and
3.3× in the US), with peer groups of 12–24 firms.

## Industry: NAICS 2022 codes

`data/reference/industries.csv` gives each of the 164 firms a six-digit **NAICS 2022** code
for its main activity (largest segment over its years in the panel), with a note wherever the
call is not obvious (conglomerates, holdings, brand owners with outsourced production). The
official code list (US Census Bureau, all 2,125 codes) is `data/reference/naics_2022.csv`, so a
typo stops the build instead of silently moving a firm to another peer group.

- **Hierarchy used:** industry group (4 digits) → subsector (3 digits) → sector. NAICS combines
  some two-digit codes into one sector (31-33 Manufacturing, 44-45 Retail, 48-49 Transport);
  the spans are read from the official list, not hard-coded.
- **Review status:** the codes were suggested with AI assistance from public company
  descriptions and are marked `reviewed` = empty. The *Data quality* view lists them under
  *Needs a decision* until each row is checked and set to `yes` — the same workflow as the KPI
  categories. A new firm without a code is reported there too.
- **Why NAICS:** it was asked for, it is hierarchical (the widening needs that), and its code
  list is public. NACE Rev. 2 (WZ 2008), the EU equivalent, would work the same way; at the
  levels the panel can support (3 digits and above) both put these firms in almost the same
  groups. GICS, which ISS uses, is proprietary.
- Two source fixes came with it: the legacy short name "DEPFA" is Deutsche Pfandbriefbank AG
  (ISIN DE0008019001, alias added), and IKB's ISIN arrived with a space.

## The six definitions

Colour in the dashboard marks the family, the symbol the definition within it.

| | Definition | Peers are | From |
|---|---|---|---|
| Fixed groups | **Index & board size** | firms in the same index (DAX / MDAX / none) and the same board-size tercile of that index and year | FairPay Radar; the original plan's rule-based definition |
| | **Clusters (K-means)** | firms in the same of 8 K-means clusters of firm-years (standardised DAX flag and log board size, one-hot NAICS sector), pooled over all years so a cluster means the same thing every year | ProxyEngine's "shadow peers" |
| Industry first | **Industry (NAICS)** | firms in the same industry group; with fewer than five, the subsector, then the sector; below that no result (no fallback to "all firms") | ECIS, ExComp, with an official classification |
| | **Industry & size (ISS-style)** | ten firms inside a size band (0.4–2.5× the employees where both report them, else same index and board within two members), from the same industry group first, then subsector, sector, any industry; ties by size. If the band holds fewer than ten firms (the largest DAX firms), the closest firms outside it fill the rest, again industry first | ISS peer methodology; §87 AktG / DCGK G.3 |
| Nearest neighbours | **Nearest neighbours (Gower)** | the ten firms with the smallest Gower distance: equal-weight mean of industry difference (1 − shared NAICS levels / 3), index, range-normalised log board size and, from 2022, log employees; a feature missing for either firm is left out of that pair | Fin1; Gower (1971) |
| | **Learned similarity (random forest)** | the ten firms that a random forest of pay most often puts in the same leaf as the executive's firm | Breiman (2001) proximity; Geertsema & Lu (2023) |

Nearest-neighbour definitions take the ten closest firms **plus every firm tied with the
tenth**, so no peer is chosen by alphabetical accident (board sizes repeat a lot).

**The random forest** predicts log pay relative to the median of its year and role from role,
index, log board size, log employees (2022+, gaps handled by the trees) and NAICS sector and
subsector (300 trees, at least 30 executive-years per leaf, a third of the features per split).
It is **cross-fitted by firm**: five folds of firms; the forest that scores a firm, and picks its
peers, never saw that firm's pay. Two firm-years are as similar as the share of trees that put
them in the same leaf. Out of firm it explains 27 % of the variance in relative log pay
(typical error 38 % against 51 % for the year-and-role median). Shuffling a feature among the
firms of the same year shows what it uses: index (+70 % squared error), role (+4 %),
employees (+2 %), board size (+1 %), industry (0 %). Correlated features share credit.

**K = 8 clusters** is the largest K that still leaves nine in ten CEO-years with five peer
firms in their cluster; silhouette rises with K because the sector dummies pull towards one
cluster per sector. The cluster page shows both curves for K = 4–12.

## How the definitions are compared

All tests use the 3,476 executive-years that every definition benchmarks (coverage on all 5,940).

| Test | Measures | Reading |
|---|---|---|
| **Typical gap** | median \|log(pay ÷ peer median)\|, shown as a percentage | how well the peers explain pay; lower is better |
| **Pull** | OLS slope of next year's log pay change (same person, firm and role, same regime) on today's log gap, both net of year means; standard errors clustered by firm | −0.21 = 21 % of the gap closes within a year: pay gravitates to these peers; stronger is better |
| **Stability** | mean Jaccard overlap of a firm's peer firms in consecutive years | a peer group that changes every year is hard to defend |
| **Coverage** | share of executive-years with at least five peer firms | |
| **Agreement** | Spearman correlation of pay ÷ peer median, and share of equal verdicts, per pair | |
| **Fragility** | CEO-years *above* under at least one definition vs. under all that cover them | how much of an "overpaid" verdict is the analyst's choice |

The baseline "all other firms" (no selection) is part of every comparison. The pull test is
the one Bizjak, Lemmon & Naveen (2008) used for US CEOs (pay below the peer median rises
faster); part of it is chance — a lucky year is followed by a less lucky one — which the
baseline shows too, so what counts is the pull *beyond* the baseline.

## Results (4 October 2026)

| Definition | Coverage | Peer firms | Typical gap | Pull | Stability | Above |
|---|---|---|---|---|---|---|
| All other firms (baseline) | 100 % | 67 | 54 % | −0.14 (0.02) | 79 % | 24 % |
| Index & board size | 96 % | 11 | 37 % | −0.21 (0.03) | 33 % | 18 % |
| Clusters (K-means) | 89 % | 9 | 37 % | −0.21 (0.03) | 56 % | 18 % |
| Industry (NAICS) | 70 % | 9 | 59 % | −0.14 (0.02) | 80 % | 25 % |
| Industry & size (ISS-style) | 100 % | 11 | 36 % | −0.21 (0.03) | 44 % | 17 % |
| Nearest neighbours (Gower) | 100 % | 11 | 36 % | −0.21 (0.03) | 48 % | 15 % |
| Learned similarity (forest) | 100 % | 10 | 38 % | −0.21 (0.03) | 50 % | 20 % |

Pull standard errors in brackets. What it says:

1. **Peer selection matters, and size is what matters.** Every definition that controls for
   size cuts the typical gap from 54 % (no selection) to 36–38 % and pulls pay about half as
   strongly again as the baseline (−0.21 vs −0.14).
2. **Industry alone is worse than no peer group at all** (59 % vs 54 %). A NAICS group mixes
   DAX giants with MDAX firms a tenth their size; adding the size band (ISS-style) fixes it, but
   then industry adds nothing over size alone. The forest agrees from the other side: given the
   size proxies, industry does not improve its out-of-firm predictions. This holds for this
   panel and these size proxies; with revenue or market value it may differ.
3. **The size-aware definitions rank executives almost identically** (Spearman 0.92–0.97;
   same verdict 85–94 %), yet **70 % of "overpaid" CEO verdicts depend on the definition**: of
   459 CEO-years at least 1.5× their peer median under some definition, 138 are so under every
   definition that covers them. Year by year, about a third of CEOs are above under at least one
   definition but only about one in ten under all (none in 2022). In 2024 Adidas, Volkswagen and
   Deutsche Bank are above under all six and SAP under all five that cover it; Siemens and Merck
   under three; Henkel under one. The finding does not hinge on the 1.5× line: the share of flags
   that depend on the definition is 63 % at 1.25×, 77 % at 2× and 81 % at 2.5× and 3× — stricter
   lines, closer to proxy-adviser multiples, make verdicts more fragile, not less.
4. **Stable peer groups and accurate ones are different things.** Industry groups barely change
   year to year (Jaccard 80 %) but explain pay worst; board-size terciles explain pay well but
   keep only about half of a firm's peers from one year to the next (Jaccard 33 %), because a
   board that gains one member can jump tercile. Clusters and the nearest-neighbour definitions
   sit in between.
5. **Pay drifts toward the peer median** under every definition. Net of the market, executives
   in the lowest tenth (paid about 0.4× their peer median) get 22–26 % more the next year under
   the size-aware definitions, those in the top tenth (about 2×) 14–16 % less; with all firms
   as peers the same groups move +19 % and −12 %.

## What was taken from the six hackathon projects

| Project | Taken | Not taken, and why |
|---|---|---|
| FairPay Radar | index + board-size terciles; same-year groups; refusal below a minimum | the firm's own pay inside its peer median (`compute_peer_stats` includes it) |
| Fin1 | Gower k-NN; own firm excluded; `INSUFFICIENT_PEERS` | year as a numeric feature (mixes years); gender as a peer feature (would normalise a pay gap); distance weights computed but never used (`compute_peer_stats` returns the plain median) |
| ProxyEngine | K-means "shadow peers"; multiple of median | revenue/employee clusters (no such data before 2022); the firm inside its cluster median; the "Reach" ratio, whose exponent amplifies residuals |
| ECIS | industry peers with a minimum group size; "pay > 3× peer median" flag | the hand-typed `INDUSTRY_MAP` with duplicate spellings; widening to "all DAX", which makes every firm everyone's peer |
| ExComp | — (peer rank within all DAX firms) | ranking against the whole index is the baseline here, not a peer group |
| Executive Compass | — | no peer logic |

New here: an official industry classification with a review workflow, the ISS-style
definition, the random-forest similarity, and the comparison itself (fit, pull, stability,
agreement, fragility) — the question this project set out and none of the six asked.

## Limitations

- **Size is proxied.** Index, board size and (2022+) employees, no revenue or market value
  (decided 19 Sep 2026). Results are about pay relative to index and board peers.
- **Industry codes are unreviewed** AI suggestions until checked; conglomerates (Siemens,
  ThyssenKrupp, Bayer) have no single right code.
- **Granted, not realised pay.** Pay is the source's total (fixed, bonuses, share-based at
  grant value, other); share-based grants make single years noisy, which the pull test partly
  reflects.
- **The 1.5× verdict line is a convention.** The fragility result holds for lines from 1.25× to
  3× (see results), and the strip chart shows the ratios themselves so a reader can apply another.
- **The universe changes in 2022** (DAX + MDAX → DAX only). Peers are always same-year, so
  verdicts stay comparable in kind, but the peer pool for 2022–2024 is the 40 DAX firms.

## Next steps

Open work on this benchmark (review of `industries.csv`, the disclosed DCGK G.3 peer groups as a
test of self-serving peer selection, Faulkender & Yang 2010) is listed in
[`ROADMAP.md`](../ROADMAP.md).

## Code

| Where | What |
|---|---|
| `backend/app/peers.py` | definitions (`size_peers`, `cluster_peers`, `industry_peers`, `industry_size_peers`, `knn_peers`, `forest_peers`), `peer_stats`, `evaluate`, `get_benchmarks` (cached in `data/cache/benchmarks.pkl`, ~20 s to rebuild) |
| `backend/app/main.py` | `/api/peers`, `/api/peers/verdicts`, `/api/peers/{method}`, `/api/firms/{id}/peers` |
| `frontend/src/views/Peers.tsx` | overview, one page per definition, company-page panel |
| `backend/tests/test_peers.py` | invariants (never own firm, ≥ 5 peer firms, ratios, NAICS levels) and toy cases |
| `uv run python -m app.peers` | prints the scorecard, forest accuracy and the K choice |

Parameters are named constants at the top of `peers.py` (`MIN_PEER_FIRMS`, `K_FIRMS`,
`MIN_PAY`, `HIGH`, `N_CLUSTERS`, `EMPLOYEE_BAND`, `BOARD_BAND`, forest settings). A new
definition is a function returning peer firms per firm, year and role, plus a `Method` entry;
statistics, evaluation, API and views pick it up.

## References

- Aktiengesetz §87(1); Deutscher Corporate Governance Kodex (2022), recommendations G.3 and G.4.
- ISS, *Peer Group Selection Methodology* and *U.S. Compensation Policies FAQ* (multiple of median).
- Glass Lewis / Equilar market-based peer groups (2012).
- Bizjak, J., Lemmon, M., Naveen, L. (2008). Does the use of peer groups contribute to higher
  pay and less efficient compensation? *Journal of Financial Economics* 90(2), 152–168.
- Faulkender, M., Yang, J. (2010). Inside the black box: The role and composition of
  compensation peer groups. *Journal of Financial Economics* 96(2), 257–270.
- Gabaix, X., Landier, A. (2008). Why has CEO pay increased so much? *Quarterly Journal of
  Economics* 123(1), 49–100.
- Gower, J. C. (1971). A general coefficient of similarity and some of its properties.
  *Biometrics* 27(4), 857–871.
- Breiman, L. (2001). Random forests. *Machine Learning* 45, 5–32.
- Geertsema, P., Lu, H. (2023). Relative valuation with machine learning. *Journal of
  Accounting Research* 61(1), 329–376.
- US Census Bureau, North American Industry Classification System 2022.
