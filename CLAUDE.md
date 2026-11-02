# CLAUDE.md

Executive-compensation IDP: a harmonised DAX/MDAX pay panel (2006–2024) behind a FastAPI API and a
React dashboard. Read `README.md` for layout and commands (its Run section lists server, tests,
scorecards and checks), `docs/data.md` before touching data logic, `ROADMAP.md` for what is open.

## Rules

- **Numbers come from the backend.** Statistics are computed in Python (`main.py`); the frontend
  only filters and draws. Never hard-code a data-derived number in UI text.
- **Units:** amounts in k€ everywhere; shares as fractions 0–1 unless a name ends in `_pct`.
- **Pay statistics** use full-year executives (`full_year`); comparisons across 2021/22 use
  `scope=dax`, the only universe on both sides of the disclosure break.
- **Peer benchmark** (`peers.py`, `docs/peers.md`): every definition picks peer firms in the
  same year and role, never the executive's own firm, and gives no result below
  `MIN_PEER_FIRMS`; anything model-based is cross-fitted by firm. A new definition is one
  function plus a `Method` entry; industry comes from `industries.csv` (NAICS 2022).
- **Pay prediction** (`forecast.py`, `docs/prediction.md`): a model is trained only on pairs whose
  target year is ≤ the origin it predicts from, never across the 2021/22 break; a new model is
  one function in `FITS` plus a `Model` entry. Gender and nationality never enter a prediction
  shown to users.
- **Assistant** (`assistant.py`, `docs/assistant.md`): the LLM picks tools, Python computes;
  every new GET route is reachable through the `api` tool, so keep route docstrings meaningful.
  Writes go only through the Add data routes (`entry.py`), which rebuild the panel before keeping a row.
- **Data layers:** format-specific cleaning in its adapter (`backend/app/sources/`), cross-source
  logic in `panel.py`, curated knowledge in `data/reference/*.csv` (aliases, KPI categories,
  value overrides) — never as constants in code. Every fix gets an `issue(...)` entry so it
  shows in the Data quality view. Joins fail loudly or report unmatched rows; never drop silently.
- **Nothing data-dependent is hard-coded** in the frontend: years, firms and index names come
  from the API. The one fixed year is the legal §162 break (`REGIME_BREAK` in `charts.ts`).
- **Keep `schemas.py` and `frontend/src/api.ts` in sync** when a response changes.
- **Charts:** Observable Plot only; colours via the CSS variables in `styles.css`
  (`var(--c-…)`), shared axes and the regime-break marker from `charts.ts`. Each chart needs a
  caption saying what is measured and an `aria-label` stating its takeaway.
- **Raw data stays out of git:** never commit `data/raw/`. There is no NDA; external LLM APIs
  may be used on the data.
- **Docs:** one fact, one place. README: what it is, how to run, layout, API table. `docs/*.md`:
  deep dives (the assistant's `docs` tool searches their `##` sections, so keep headings
  meaningful). ROADMAP: open work only. `reports/` (session and demo reports) is git-ignored.
