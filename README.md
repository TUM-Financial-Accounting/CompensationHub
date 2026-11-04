# DAX Executive Pay

Interdisciplinary project (IDP), Chair of Financial Accounting, TUM. One harmonised panel of
management-board compensation — DAX and MDAX 2006–2021, DAX 40 2022–2024 — with an analytical
dashboard on top: pay trends, company and executive pages, a peer benchmark, pay prediction, an
LLM assistant and a form for adding data. What is still open: [`ROADMAP.md`](ROADMAP.md). Data and
its issues: [`docs/data.md`](docs/data.md).

## Run

Needs Python ≥ 3.10 with [uv](https://docs.astral.sh/uv/), and Node 20.19+ or 22.12+. The raw
files must be in `data/raw/` (git-ignored; copy them from `../Compensation Data/`).

```bash
cd backend && uv sync && uv run uvicorn app.main:app --reload   # API on :8000
cd frontend && npm install && npm run dev                        # dashboard on :5173
```

The first start builds the panel from the Excel/CSV files (~10 s) and caches it in `data/cache/`;
the peer benchmark (~20 s) and the pay prediction (~2 min) are then computed in the background
and cached next to it. All rebuild whenever a file in `data/` or the backend code changes, and
after every row saved with **+ Add data**.

The assistant needs an LLM: copy `backend/.env.example` to `backend/.env` and add an OpenAI or
Morpheus key, or run a local Ollama model ([`docs/assistant.md`](docs/assistant.md#configuration)).

**On a phone on the same Wi-Fi:** start the dashboard with `npm run dev -- --host` and open the
Network URL it prints in Safari or Chrome. The Vite dev server forwards `/api` to the backend, so
the backend can stay on `127.0.0.1`. The panel is confidential, so use a network you trust; when
others can reach the dashboard, start the backend with `READ_ONLY=1` (or set it in `backend/.env`)
to switch off the write routes of **+ Add data**.

**Hosted (Railway):** one service built from the `Dockerfile` (settings in `railway.json`) plus a
Postgres with `DATABASE_URL=${{Postgres.DATABASE_URL}}`. Pushes to `main` deploy; a deploy goes
live only once `/api/summary` answers, so a broken build leaves the previous one running.
`data/raw/` is not in git, so the app restores it from Postgres at startup; after changing it,
store it again with `DATABASE_URL=<DATABASE_PUBLIC_URL> uv run python -m app.rawdata`.

Commands:

- Data report: `cd backend && uv run python -m app.panel` lists every source found and every open issue
- Peer scorecard: `cd backend && uv run python -m app.peers`
- Prediction scorecard: `cd backend && uv run python -m app.forecast`
- Checks: `cd backend && uv run pytest` · `cd frontend && npx tsc -b && npx oxlint src`

New years, firms and datasets are added as files, not code, or row by row with the **+ Add data**
button. See [`docs/data.md` → Adding data](docs/data.md#adding-data).

## Layout

```
backend/app/sources/     one adapter per file format (legacy CSVs, DSW workbooks, rows added by hand)
backend/app/reference.py curated tables: aliases, KPI categories, overrides, attribute tables
backend/app/panel.py     builds the panel: identity, joins, overrides, totals, validation
backend/app/peers.py     peer benchmark: six peer definitions, statistics, scorecard
backend/app/forecast.py  pay prediction: fourteen models, seven pay items, backtest, what-if
backend/app/entry.py     Add data form: tables, save with rebuild check, plausibility check
backend/app/assistant.py LLM assistant: providers, tools, loop, number check
backend/app/main.py      JSON API, one route per dashboard view
backend/app/schemas.py   response models (mirrored in frontend/src/api.ts)
backend/tests/           pytest: panel, peers, forecast, entry, assistant
frontend/src/views/      one file per dashboard view, the Add data dialog and the assistant
frontend/src/api.ts      response types and data hooks, mirror of schemas.py
frontend/src/charts.ts   shared chart settings (axes, colours, regime-break marker)
data/reference/          curated CSVs (in git), incl. NAICS codes per firm; data/raw/ holds the confidential files
docs/data.md             data study, how the panel is built, how to add data
docs/peers.md            peer benchmark: definitions, tests, results, references
docs/prediction.md       pay prediction: models, evaluation, results
docs/assistant.md        assistant and data entry: architecture, tools, configuration, demo questions
docs/charts.md           how each dashboard chart is computed
docs/hackathon/          historical, git-ignored: review of the six hackathon projects this builds on
```

## API

| Route | Serves |
|---|---|
| `GET /api/summary` | headline numbers, DAX CEO pay quantiles per year |
| `GET /api/trends?scope=dax\|all` | pay level by role, pay mix, CEO premium, opt-out rate |
| `GET /api/firms`, `/api/firms/{id}` | company list; one company's years, executives, plan design |
| `GET /api/executives?year=` | every executive in a year |
| `GET /api/people/{id}` | one executive's career |
| `GET /api/peers` | peer definitions with their scorecard, agreement, convergence |
| `GET /api/peers/verdicts?year=&role=` | every executive of a year and role under each definition |
| `GET /api/peers/{definition}?year=&role=` | one definition: results, chosen peers, groups, model details |
| `GET /api/firms/{id}/peers` | the firm's CEOs against peers, every year and definition |
| `GET /api/design` | KPI categories, caps, ESG weights, maximum pay (2022–2024) |
| `GET /api/board` | gender and nationality mix, CEO-to-staff pay ratio, pay vs. TSR |
| `GET /api/quality` | coverage per field and year, universe, data issues |
| `GET /api/prediction` | prediction models with their scorecard per pay item, by horizon, paid-or-not |
| `GET /api/prediction/{model}?target=` | one model: predicted vs. paid, calibration, by role, misses, what it learned |
| `GET /api/people/{id}/prediction?peer_method=` | forecasts of every pay item, board, staff and peer comparison |
| `GET /api/firms/{id}/prediction` | next year's total pay for each board member |
| `GET /api/whatif?person_id=&years=&role=&index=&board=&employees=&growth=` | what-if for an executive |
| `GET /api/tables`, `DELETE /api/tables/{id}/rows/{i}` | tables of the Add data form; delete a hand-entered row |
| `POST /api/rows`, `POST /api/rows/check` | save rows to one or more tables in one build (all or nothing); check them first (writes are off with `READ_ONLY=1`) |
| `POST /api/extract` | text of an uploaded PDF or text file, for the assistant |
| `GET /api/feedback`, `POST /api/feedback` | feedback posts, newest first; post one (open to all, also with `READ_ONLY=1`; needs `DATABASE_URL`) |
| `GET /api/chat/models`, `POST /api/chat` | assistant: models and demo questions; streamed answer |

Interactive docs at `http://localhost:8000/docs`.

## Stack

- **FastAPI + pandas**, no database for the panel: it is ~7.5k rows and fits in memory. Only the
  Feedback page's posts live in Postgres (`DATABASE_URL`; the table is created on first use).
  scikit-learn for the peer definitions and the prediction models; the `openai` SDK for the
  assistant (OpenAI, TUM's Morpheus and Ollama all speak its API); SQLite (standard library) as
  the assistant's read-only query copy; `pypdf` to read attached reports.
- **React + Vite + [Observable Plot](https://observablehq.com/plot/)**. Plot is a grammar for
  statistical graphics (bands, facets, beeswarms, heatmaps) that renders plain SVG, so charts
  take the page's fonts and colour tokens and follow light/dark mode. No UI kit, no router:
  hash URLs such as `#/companies/sap` keep every view linkable. Navigation is a sidebar on
  desktop and a drawer on phones.
