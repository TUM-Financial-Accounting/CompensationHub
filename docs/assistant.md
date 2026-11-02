# Assistant and data entry

> Ask the panel a question in plain language and get an answer whose every number comes from
> the backend; add a missing executive-year from the dashboard and have the charts, the
> forecasts and the assistant pick it up.

Code: `backend/app/assistant.py`, `backend/app/entry.py`, `backend/app/sources/manual.py`;
views: *Assistant* (`#/assistant`), the **Ask the assistant** side panel on every page (same
conversation), and the **+ Add data** button in the navigation. The pay prediction the assistant
uses is documented in [`prediction.md`](prediction.md).

## Architecture

```
Browser ── Assistant view ──POST /api/chat (JSON lines)──▶ assistant.py ──▶ LLM (OpenAI API:
        ── + Add data ──────POST /api/rows ─────────────▶ entry.py          OpenAI, Morpheus, Ollama)
                                     │                                      │ tool calls
                                     ▼                                      ▼
                       data/raw/manual/*.csv                 find · sql · api · check_row · docs ·
                       data/reference/*.csv                  propose_rows · chart (plain Python over
                                     │                        the same objects as the dashboard)
                                     ▼
              panel.build() ◀── sources/manual.py      caches dropped, rebuilt in the background
```

One process, no new services, three small dependencies (`openai`, `pypdf`, `python-dotenv`). The
LLM never sees raw files and never does arithmetic: it picks tools, the tools compute, the LLM writes the sentence.

| Decision | Choice | Why / rejected alternative |
|---|---|---|
| Agent shape | One tool-calling loop (ReAct, Yao et al. 2022), at most 8 tool rounds per question | Multi-agent set-ups or a router model add latency and failure modes; the LLM choosing between `sql` (past) and the prediction routes (future) *is* the router. No LangChain: the loop is shorter than its set-up. |
| LLM access | `openai` SDK; a model is `provider:model_id` (`openai:gpt-5-mini`, `morpheus:google/gemma-4-31B-it`, `morpheus:cyankiwi/Qwen3.8-Flash-Next-AWQ-INT4`), keys in `backend/.env` | Same pattern as the NLP lab's review pilot (`services/providers.py`): every provider speaks the OpenAI API, so a provider is a base URL and a key. |
| Past questions | `sql`: one `SELECT` on an in-memory SQLite copy of the panel, the peer results, the live forecasts and the model scores, with `median()` and `quantile()` aggregates | Questions are open-ended, and SQL is what LLMs write best. SQLite is in the standard library. Read-only three times over: `PRAGMA query_only`, an authorizer that allows only reads, a step budget against runaway queries; at most 200 rows back. |
| Project rules in SQL | A view `pay` (full-year executives, total ≥ 100 k€) and the rules in the instructions; the index column is `stock_index` (`index` is an SQL keyword every model tripped over) | Free SQL can forget `full_year` or mix universes across 2021/22; the view makes the right query the easy one. |
| Everything the dashboard shows | `api(path, params)` calls any `GET /api/…` route in-process; the route list with parameters comes from FastAPI's OpenAPI schema | A new dashboard route is available to the assistant without a code change, and the assistant agrees with the dashboard by construction. |
| Names | `find` matches firms and people by normalised name (substring, then `difflib`) | Fuzzy name lookup is the only "search" the questions need. |
| Method questions | `docs` returns the two best-matching `##` sections of `docs/*.md` (not `docs/hackathon/`) | A few thousand words: matching by words is enough. |
| Number check | Every number in the answer is looked up in the tool results and the instructions, also as € million (÷ 1000), % (× 100) and % change (ratio − 1), read in English and German notation (10.6 / 10,6); years and small counts are skipped. Unmatched numbers are returned and marked in the answer | Turns "never calculates itself" from a request into a check. |
| No tool calling | If the provider rejects `tools`, the loop switches to a text protocol: the model replies with `{"tool": …, "args": …}` and gets the result back as a message | Both Morpheus models support tool calls; the fallback is for local or other models that do not. |
| Thinking | For the Morpheus models a *Thinking* control in the view, with the settings the Morpheus docs list: Gemma Off / On (`chat_template_kwargs.enable_thinking`), Qwen Off / Low / Medium / Extra high (plus `preserve_thinking` and `reasoning_effort`). Off by default; any other setting raises the token budget to 16,000. The reasoning (from the server's reasoning field or an inline `<think>` block) is shown collapsed above the answer and never sent back to the model | Off by default as in the review pilot: thinking costs time and tokens; on can help multi-step questions, and showing it makes the comparison visible. |
| Memory | Stateless backend; the browser sends the conversation, the current page (`companies/sap`, …) and the current draft | No database. "This company" means the page you are on. |
| Charts in answers | `chart(query, kind, x, y, color, title)` runs a read-only SQL query and the page draws a line, bar or dot chart with Observable Plot | The numbers come from SQL like everything else; the model only picks the encoding. |
| Adding data by chat | `propose_rows` turns pasted text or an attached PDF into a draft (any of the Add data tables, several at once) with the checks of every row; the draft appears under the answer, editable cell by cell; *Save to the data* stores it through the same route as the form | The model never writes: only the user's click saves. Asking "change the bonus to 3.1 M" makes the model redraft from the edited draft the browser sends along. |
| Output | Streamed JSON lines: each tool call with its arguments, a preview of each result, then the answer. The view lists the calls as steps that expand to the raw call and result | The user sees what the assistant is doing and can check every number against the call that produced it. |

### Vector database (Milvus etc.): not needed

Everything is a table of ~7.5k rows held in memory, and the questions are quantitative: a vector
search returns *similar text*, not the right number. The only fuzzy lookups are names, handled
by `find`; the only free text is the docs, retrieved by section. A vector store would earn its
place only if unstructured documents arrive (e.g. full remuneration-report PDFs); even then a
NumPy cosine over a few thousand chunks or `sqlite-vec` is enough. Milvus is built for millions
of vectors and needs its own server.

### Configuration

Copy `backend/.env.example` to `backend/.env` and fill in the keys you have. `LLM_MODELS` lists
the models offered in the view; models whose key is missing are shown but disabled. `LLM_MODEL`
sets the default; without it the first model with a key is used.

| Provider | Key | Notes |
|---|---|---|
| `openai` | `OPENAI_API_KEY` | GPT-5 models take no temperature; the call sets `max_completion_tokens` |
| `morpheus` | `MORPHEUS_API_KEY` (morpheus.cit.tum.de → Profile → Settings → Account; personal key, for School of Computation students and staff) | [CIT docs](https://wiki.ito.cit.tum.de/bin/view/CIT/ITO/Docs/Services/LLM%20%2F%20KI%20(Morpheus)/): Open WebUI, OpenAI-compatible under `https://morpheus.cit.tum.de/api/v1`. Models (Oct 2026): `google/gemma-4-31B-it` and `cyankiwi/Qwen3.8-Flash-Next-AWQ-INT4`, both with tool calling; the current list is at `/api/v1/models`. Still in testing; the CIT states that no request data goes to model providers. Tested 21 Oct 2026: both models call tools natively; Qwen answers in about 10 s, Gemma in about 75 s. |
| `ollama` | none | not in the default list; for a model on this machine or a chair server: add e.g. `ollama:qwen3:8b` to `LLM_MODELS` and set `OLLAMA_BASE_URL` if the server is elsewhere. Pick a model with tool calling. |

`READ_ONLY=1` (any value except empty, `0`, `false` or `no`) disables the write routes when the dashboard is hosted or
shown to others; reading stays open.

## Data entry

The **+ Add data** button opens a dialog: pick a table, see its columns with type, unit, allowed
values and help, fill a row, save. The dialog lists the rows added by hand, with delete, and
the file and its CSV header.

| Table | File | Purpose |
|---|---|---|
| Executive pay | `data/raw/manual/execs.csv` | a new executive-year (e.g. 2025 from a remuneration report) |
| Firm-year | `data/raw/manual/firm_years.csv` | a new firm-year: index, employees, personnel expenses, TSR |
| Value correction | `data/reference/overrides.csv` | fix a value that is already in the panel |
| Firm alias, industry code, KPI category | the existing reference CSVs | as in [`data.md` → Adding data](data.md#adding-data) |
| Attribute tables | `data/*/tables/*.csv` | columns read from the file's header |

- Hand-entered rows use the **canonical columns** of `sources/__init__.py`; the adapter
  `sources/manual.py` reads them like any other source (regime by year, batch "Manual entry").
  The delivered legacy CSVs and DSW workbooks are never written.
- **New records only.** A firm-year another source already has is refused by the build ("Firm-year
  delivered twice"); corrections belong in *Value correction*, where they are documented.
- Every pay and firm-year row needs a `source`.
- **Each save is checked by a full panel build.** If the build fails (executive without
  firm-year, duplicate, unknown NAICS code, an override that matches no record) the file is
  restored and the build's message is shown. Same rules as hand-edited files, no second validator.
- People are linked like in any other source: by surname at the same firm, so a 2025 row for
  "Klein" at SAP continues Christian Klein's career.
- After a save every cached result is dropped; the panel is stored at once, the peer groups and
  forecasts are rebuilt in the background (about two minutes) and the assistant's SQL copy on its
  next question. Forecasts start from each firm's latest year, so a firm with a 2025 row moves
  ahead while the others stay at 2024.

### Adding data by chat

Paste text from a remuneration report, or click **Attach** and pick a PDF (text files work
too; up to 15 MB, the first 120,000 characters are read, pages are marked so the source can
cite them). The assistant maps the report's terms to the canonical columns (e.g.
Festvergütung → fixed, Performance Share Units → lti), converts € or T€ to k€, adds a
firm-year if the data has none, and calls `propose_rows`. The draft shows each row with its
check (forecast range, board ratio, peers, pay mix, typos). Edit cells directly or ask for
changes; **Save to the data** saves the whole draft in one panel build (all or nothing) and
the dashboard updates like after the form. Tested 21 Oct 2026 with Qwen on an SAP excerpt:
draft with firm-year, € → k€, checks, then a redraft on "change the annual bonus to 3,1 Mio €".

### Checking a new row

Before saving, the form sends the row to `POST /api/rows/check`; the assistant has the
same check as `check_row`. Plain Python, so it works without an LLM key. Warnings never block:
an unusual value can be real (Ströer 2020), and "unusual" always names its reference.

| Check | Example (SAP 2025 rows tried on 21 Oct 2026) |
|---|---|
| Typo: any amount over 50 M€, negative components | "1,400,000 k€ is over 50 M€. Amounts are in k€: did you mean 1,400 k€?" |
| Own history: change against the last full year above ±50 % | "Total pay +15092% against 2024 (9,268 k€)" (the same typo) |
| Own forecast: inside the 80 % range of the best total-pay model | "Forecast for 2025: 6,450 k€ (80 % range 5,405 k€–7,732 k€); entered 6,260 k€ is inside the range." |
| Board: multiple of the CEO's pay against the 10–90 % range for the role | "0.68× the CEO's pay (9,268 k€); usual for this role 0.44–0.71×." |
| Peers (best peer definition): inside the peers' 10–90 % range | "Peers in 2024 (10 executives): median 3,637 k€, 10–90 % 2,464 k€–4,678 k€; entered 6,260 k€ is outside that range." |
| Pay mix: fixed, annual bonus and long-term shares against the 5–95 % range of the role | "Annual bonus is 44.7% of total pay; usual for CFOs in 2024 (5–95 %): 0.0%–41.4%." |
| Placement: firm-year exists, full year, one-time payments | "SAP 2025 has no firm-year yet: add it in the table 'Firm-year' first, or saving will fail." |

## Demo questions

For the demo and, with the expected answers taken from the API at test time, the assistant's
test set. Names are real executives in the panel. The example questions the view offers are
generated from the current data instead (`examples()` in `assistant.py`).

**Facts from the data**

1. What did Christian Klein earn as SAP's CEO in 2024, and how was it split between fixed pay, bonus and shares?
2. Who were the five best-paid DAX CEOs in 2024?
3. How much did Oliver Blume earn compared with his predecessor Herbert Diess?
4. Which firms in 2023 tied their CEO's bonus to CO2 targets?
5. How many women sat on DAX management boards in 2010 and in 2024?

**Trends and comparisons**

6. How has median DAX CEO pay developed since 2006? Compare like with like across the 2021/22 reporting change.
7. Has share-based pay become a larger part of CEO pay over time?
8. How does a CFO's pay typically relate to the CEO's pay at the same company?
9. Which company pays its board the most relative to its staff?

**Peers**

10. Is Bjørn Gulden at adidas paid above his peers? Does the answer change with the peer definition?
11. Which firms are SAP's nearest neighbours, and what do their CEOs earn?
12. Which CEOs are above their peers under every definition?

**Prediction**

13. What will Christian Sewing earn at Deutsche Bank in 2026, and how sure is that?
14. Forecast the pension and share-based pay of Siemens' CEO for the next three years.
15. What should a newly appointed CFO at Mercedes-Benz expect to earn?
16. Which model predicts annual bonuses best, and why does the neural network do worse?

**What-if**

17. What would Dominik Asam earn if he became SAP's CEO?
18. How would CEO pay at a company change if it dropped from DAX to MDAX?
19. If CEO pay grows 2 % a year, what would Ola Källenius earn in 2028?
20. Does better shareholder return lead to higher CEO pay in this data?

**Checking new data**

21. I entered SAP 2025 for Christian Klein with a fixed salary of 1,400,000. Is that plausible?
22. I added a CFO with 60 % share-based pay. Is that unusual for a firm of this size?

**Method and limits**

23. How is total pay calculated, and why do you use only full-year executives?
24. Why can't you compare 2021 and 2022 directly?
25. What will the average DAX CEO earn in 2040? *(expected: refuses beyond the tested horizon and says why)*
26. Is Christian Klein overpaid? *(expected: gives the peer and model evidence, states that "overpaid" depends on the reference, does not judge)*
