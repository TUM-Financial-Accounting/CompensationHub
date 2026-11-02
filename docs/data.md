# Data

```
data/raw/         files as delivered, never edited (git-ignored, confidential)
  2006-2021/      legacy panel CSVs
  2022/ 2023/ …   one folder per DSW study year
  manual/         rows added with the dashboard's Add data form (canonical columns)
  tables/         optional extra datasets: firm or firm-year CSVs
data/reference/   small hand-curated tables, versioned in git
  firm_aliases.csv, kpi_categories.csv, industries.csv (NAICS code per firm),
  naics_2022.csv (official code list), overrides.csv, tables/
data/cache/       rebuilt automatically, git-ignored
```

The dashboard's *Data quality* view shows what was loaded and every issue below, with live counts.
`uv run python -m app.panel` (in `backend/`) prints the same report in the terminal.

## Sources

| Folder | Files | Covers |
|---|---|---|
| `2006-2021/` | `company_year.csv` (1,467 rows), `person_year.csv` (6,726), `company_person.csv` (1,721), pipe-delimited | 163 DAX + MDAX firms, 2006–2021 |
| `2022/`, `2023/`, `2024/` | DSW workbooks `Executive_Compensation_<year>.xlsx` (sheets `Compensation`, `Members`, `Companies`, `DAX (…)`) and `Executive_Compensation_ESG_<year>.xlsx` from 2023 | the 40 DAX firms, 254–262 executives a year |

The folder was named `2008-2020` in the original drop; the CSVs cover 2006–2021.

## How the panel is built

1. **Adapters** (`backend/app/sources/`, one per file format) find their files and translate
   columns into one canonical shape: executives, firm-years, extra facts, a people directory.
   The contract is documented in `sources/__init__.py`.
2. **Firm identity.** Every source spelling goes through `firm_aliases.csv`; the ID is a slug of
   the resulting name (`Daimler` → `Mercedes-Benz` → `mercedes-benz`).
3. **Person identity.** Sources with their own IDs keep them. Others are matched to the people
   directories and to earlier records at the same firm, by surname (+ first initial when
   ambiguous). The legacy `company_person.csv` is such a directory, so moves between firms keep
   one ID (e.g. Hauke Stars, Deutsche Börse → Volkswagen).
4. **Facts and tables.** Extra sheets and every CSV in `data/raw/tables/` or
   `data/reference/tables/` fill empty cells only. Rows for unknown firms are reported, not
   dropped silently.
5. **Overrides** from `overrides.csv`. Each row must match exactly one record, or the build stops.
6. **Derived columns** (totals, flags, board aggregates), then validation: unique keys, one
   firm-year per source, no executive without a firm-year, no ID with two ISINs.

## Harmonised panel

All amounts in **k€**; both sources already use k€, so nothing is rescaled.

- **firms**: `firm_id`, name, ISIN (legacy only), activity text, plus columns from firm tables.
- **firm_years**: index, opt-out flag, board total (also for opt-out firms). From 2022 also
  employees, personnel expenses and TSR; from 2023 the ESG share of STI/LTI and how ESG enters
  each plan (`*_esg_kind`: target, multiplier, or both). Plus firm-year table columns.
- **execs**: one row per executive × firm × year: role (CEO / CFO / member), gender, German
  nationality (dual nationals included), birth year, days in office, pay components, `reported` (all five components
  present). From 2022 also caps, named KPIs, internal/external hire, and maximum remuneration
  (2024 only).

| Component | Legacy column | DSW column |
|---|---|---|
| fixed | `salary` | `fix` |
| sti | `one_year_bonus` | `sti` |
| mti | `multi_year_bonus` | `mtiprov` |
| lti | `total_equity_grants` | `lti` |
| other | `other_annual_comp` | `others` |
| **total** = sum of the five | = `total_comp` exactly | computed |
| pension | `pension` | `pension` |
| one_time | `one_time_payment` | `payoff` |

Pay statistics use full-year executives (≥ 360 days) so joiners, leavers and CEO hand-overs do
not distort medians; pay-mix shares also require all five components to be reported.

## Adding data

| You have | Do | Code change |
|---|---|---|
| A new DSW study year | Put the workbook(s) in `data/raw/<year>/`, restart the backend | none, if the DSW keeps its column names |
| A few executive-years or firm-years (e.g. one 2025 report) | **+ Add data** in the dashboard: rows go to `data/raw/manual/` in the canonical columns, each with its source; every save is checked by a full build ([`assistant.md`](assistant.md#data-entry)) | none |
| A firm under another name | Add `alias,name` to `firm_aliases.csv` | none |
| A firm's industry | A row `firm,naics,reviewed,note` in `industries.csv` with a six-digit NAICS 2022 code (the build stops on a code not in `naics_2022.csv`) | none: used by the industry peer groups |
| Firm-level data (e.g. ratings) | CSV with `firm,<columns…>` in `data/reference/tables/` (public) or `data/raw/tables/` (confidential) | none: shown on company pages and in the API |
| Firm-year data (e.g. financials, votes) | CSV with `firm,year,<columns…>` in the same folders | none: shown on company pages, in the API and in the coverage heatmap |
| A wrong or missing value | A row in `overrides.csv` (`table` = `execs` or `firm_years`, `person` = full name for execs) | none |
| New KPI names appear | Run `uv run python -m app.panel --add-kpis`, then review the new rows in `kpi_categories.csv` (set `reviewed` to `yes`) | none |
| Another file format (other country, other study) | A new adapter in `backend/app/sources/` that returns the canonical shape, listed in `panel.SOURCES` | one module |

`firm` in tables and overrides may be a name, an alias or a firm ID. Using a table's columns in a
chart or model is code, as it should be; getting them into the panel is not.

After adding data as files, run `uv run python -m app.panel`. It lists every source it found and
every issue that needs a decision, including table rows that matched no firm. Then restart the
backend: `--reload` watches code, not data, and the cache rebuilds by itself when files change.
Rows saved with **+ Add data** need no restart.

## KPI categories

Firms name their bonus criteria in free text (255 distinct names in 2022–2024).
`data/reference/kpi_categories.csv` maps each name to one or more categories. It was reviewed
name by name against the firm and plan that use it; the `note` column explains non-obvious
calls. The four groups follow Armeli & Fligge (2026), the Hans-Böckler-Stiftung study of 885
German remuneration reports (2021–2023). That study splits criteria into financial,
non-financial and capital-market metrics plus individual targets, which is also the usual
accounting vs. market split in the literature.

| Group | Category | Counts | Examples |
|---|---|---|---|
| Financial | Profit & EPS | earnings, margins, costs | EBIT, EBITDA, net income, EPS, return on sales, FFO (property firms) |
| Financial | Return on capital | profit relative to capital employed, incl. profit after a capital charge | ROCE, ROIC, RoE, RoTE, EVA, EBIT after asset charge |
| Financial | Cash flow & balance sheet | cash generation and balance-sheet strength | free cash flow, operating cash flow, working capital, leverage, NTA or book value per share |
| Financial | Revenue & growth | top line and its growth | revenue, organic growth, cloud backlog, gross merchandise volume, bank revenues ("Erträge") |
| Financial | Financial, unspecified | financial targets whose metric is not named | "Konzernfinanzziele" |
| Capital market | Share price & TSR | absolute or relative share price or total shareholder return | relative TSR vs. an index or peer group |
| Non-financial | ESG | environment, social (employees, customers, health & safety), governance (compliance, regulatory) | CO2 intensity, NPS, "Einhaltung der US-Vorschriften" |
| Non-financial | Strategic & operational | strategic projects, transformation, innovation, market position, operating model | "Digitale Transformation", "Win with Skin Care" |
| Non-financial | Non-financial, unspecified | non-financial targets whose content is not named | "Nicht-finanzieller Faktor" |
| Individual | Individual & discretionary | individual targets and performance factors, discretionary modifiers, per-portfolio targets | "Individueller Leistungsfaktor", "Ermessens-Multiplikator" |
| — | Unspecified | placeholders that name no criterion | "Kriterien des STI", "Gesamtleistung", "Zielbetrag" |

Decision rules:

- **Composite criteria get every category they combine** ("Jahresüberschuss × CO2-Komponente" →
  Profit & EPS; ESG), so the dashboard counts them in each.
- **Content beats wording.** DHL's "Nachhaltigkeitskriterium EAC" is a capital-return target;
  "Nachhaltigkeit" means durability there. Deutsche Bank's "Erträge Privatkundenbank" is revenue.
- **Measured strategic goals** carry both categories ("Digitale Transformation … E-Commerce-Umsatz"
  → Strategic & operational; Revenue & growth).
- **Uncertain means unspecified.** If the source does not say what a label covers, it is not
  guessed.

New names from new data are guessed by keyword rules (`KPI_RULES` in `backend/app/reference.py`)
and flagged until reviewed: run `uv run python -m app.panel --add-kpis`, check the new rows, set
`reviewed` to `yes`. An unknown category name in the file stops the build.

Sources: [Armeli & Fligge (2026), Mitbestimmungsreport 89](https://www.imu-boeckler.de/fpdf/HBS-009403/p_mbf_report_2026_89.pdf);
[Meridian, performance measurement in executive compensation](https://www.meridiancp.com/insights/understanding-performance-measurement-in-executive-compensation/);
[Bettis et al. (2018), Journal of Accounting and Economics 66(1)](https://ideas.repec.org/a/eee/jaecon/v66y2018i1p194-221.html).

## What was checked

- Legacy components add up to `total_comp` in all 6,726 rows. Board totals match the sum of
  members within 5 % in 1,265 of 1,270 disclosed firm-years.
- Opt-out firm-years (197) are exactly those without person rows.
- All DSW `Compensation` rows join 1:1 to `Members`, and every fact row finds its firm (tested).
- Cross-regime continuity: the DAX-only median member pay moves 2,680 → 3,018 k€ (+13 %) from
  2021 to 2022, while the unfiltered median jumps +45 %. That jump is the DAX + MDAX → DAX
  universe change, not pay.

## Curation status

### Settled

- **Blank legacy components mean "not reported"** (chair). Totals are the source's totals and may
  understate pay where a component is missing; pay-mix shares use fully reported rows only.
- **Firm renames and spellings** are in `firm_aliases.csv` (Daimler, Heidelberg Cement,
  Porsche SE/AG, four ESG-workbook spellings, and "DEPFA": the legacy short name of Deutsche
  Pfandbriefbank AG, whose company name and ISIN DE0008019001 the source also gives).
- **Metro** stays as delivered: pre-2017 rows follow the management team to the new METRO AG,
  and the old Metro AG continues as Ceconomy. Documented, not changed.
- **KPI categories** reviewed for all 255 names (see [KPI categories](#kpi-categories)).
- Handled in code: 4 Rhön-Klinikum 2013 rows without person ID dropped; one Excel serial date;
  2022 activity text in the wrong column; CEO vs. division-CEO titles; line breaks in KPI names;
  a space inside IKB's ISIN and after "Bilfinger".

### Needs a decision

1. **Industry codes.** The data has no classification and the activity text is partly wrong
   (Infineon: "Konsumgüter und Industrieprodukte"). `industries.csv` therefore gives every firm
   a NAICS 2022 code, suggested with AI assistance and unreviewed: check each row and set
   `reviewed` to `yes`; the Data quality view counts the open ones. How the codes are chosen and
   used: [`peers.md`](peers.md#industry-naics-2022-codes).
2. **ESG shares with two values.** Six firms a year give two numbers ("20; 33,33"). The column
   `<plan>_ESG_KPI_as_multiplier_or_KPI` lists 1 (multiplier) or 2 (target) in the same order, so
   plans with one target and one multiplier are resolved in code: the share is the target's
   weight. Still empty: plans with two multipliers (Allianz LTI 2023–24, Mercedes-Benz STI
   2023–24, Heidelberg Materials STI 2023). Settle them with `overrides.csv` rows.
3. **Index listing missing** for 117 legacy firm-years: 56 are a firm's first year in the panel,
   1 its last, 60 a gap in the middle (e.g. Deutz 2009–10 between MDAX years). Likely the firm
   was in neither DAX nor MDAX that year (e.g. dropped to SDAX); not verified.

### Worth knowing

- **Regime break 2021/22.** Legacy follows the DCGK model tables; from 2022, §162 AktG "granted
  and owed". Same unit, different definitions for multi-year and share-based pay.
- **Universe change.** ~90 DAX + MDAX firms a year until 2021, the 40 DAX firms after. Use the
  DAX filter to compare across the break.
- **No firm financials, and none are coming.** Employees and personnel expenses exist from 2022.
  Index (Spearman ρ with CEO pay 0.59 for DAX vs. MDAX) and board size (0.45) are the size
  proxies for all years, comparable to employees (0.47) where both exist.
- **Opt-outs** (§286(5) HGB): 25 % of firms in 2006, 0 % in 2021; board totals only.
- **Extreme grant values** are real: Ströer 2020 (243 M€ board equity grants), Zalando 2018
  (57 M€), Beiersdorf 2018 (CEO 23.5 M€). Winsorise for modelling, not for display.
- **Negative pension cost** in 52 legacy rows: plausible (plan changes), worth a spot check.
- **CEO flags.** Legacy flags only the year-end CEO; the DSW flags both CEOs in a hand-over year.
  DSW "days in office" counts board days, not CEO days, so a board member who became CEO in
  October still counts as a full-year CEO (2024: BASF, Commerzbank, Daimler Truck, Deutsche
  Börse, Symrise, Zalando). `pentryceoposition` gives the CEO start date; there is no CEO end date.
- **ESG shares.** 2022 gives multiplier ranges or prose, so only 2023+ is used. From 2023 the
  ESG file says per plan whether ESG is a **target** (the share is its weight; for most firms it
  equals the sum of the E/S/G target weights in the same file) or a **multiplier** on the payout
  (the number is not a weight: 100 can mean a modifier on the whole plan). The dashboard's ESG
  weight chart shows targets only and lists multiplier plans by name.
- **Maximum remuneration** (§87a AktG) is recorded for 2024 only.
- **HypoVereinsbank 2006–2007** carries UniCredit's ISIN (IT0005239360) in the legacy panel;
  HVB's own was DE0008022005. It only shows on the company page, so it is left as delivered.
