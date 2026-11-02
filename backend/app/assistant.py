"""Assistant: an LLM answers questions about the panel by calling the backend's own functions.

The LLM never computes a number. It picks tools, the tools compute, the LLM writes the answer,
and every number in the answer is looked up in the tool results; numbers that are not found are
returned as unverified. Tools:

    find       firms and executives by name (fuzzy)
    sql        read-only SQL over the panel, peer results, forecasts and model scores
    api        any GET route of the dashboard's API, so every chart's numbers are reachable
    check_row  the plausibility check of the Add data form
    docs       sections of docs/*.md for questions about method

Providers speak the OpenAI API, so a model is "provider:model_id": OpenAI, the CIT's Morpheus
service (Open WebUI, OpenAI-compatible under /api/v1, both models with tool calling) or Ollama. Keys and the
model list live in backend/.env (see .env.example).
"""

from __future__ import annotations

import difflib
import inspect
import json
import math
import os
import re
import sqlite3
import threading
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

import openai
import pandas as pd
from dotenv import load_dotenv
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from starlette.routing import Match

from . import entry, forecast, panel, peers

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

PROVIDERS = {  # provider: (base URL, its environment variable and default, key variable)
    "openai": (None, None, "OPENAI_API_KEY"),
    "morpheus": ("MORPHEUS_BASE_URL", "https://morpheus.cit.tum.de/api/v1", "MORPHEUS_API_KEY"),
    "ollama": ("OLLAMA_BASE_URL", "http://localhost:11434/v1", None),
}
MODELS = "openai:gpt-5-mini,morpheus:google/gemma-4-31B-it,morpheus:cyankiwi/Qwen3.8-Flash-Next-AWQ-INT4"
MAX_STEPS = 8            # tool rounds per question
MAX_RESULT = 12_000      # characters of one tool result sent back to the LLM
MAX_ROWS = 200
DOCS = panel.ROOT / "docs"


# --------------------------------------------------------------------------- providers


def models() -> list[dict]:
    names = [m.strip() for m in os.getenv("LLM_MODELS", MODELS).split(",") if m.strip()]
    out = []
    for m in names:
        provider = m.partition(":")[0]
        key = PROVIDERS.get(provider, (None, None, "?"))[2]
        out.append({"id": m, "default": False, "thinking": thinking_levels(provider, m.partition(":")[2]),
                    "available": provider in PROVIDERS and (key is None or bool(os.getenv(key)))})
    default = os.getenv("LLM_MODEL") or next((m["id"] for m in out if m["available"]), names[0])
    for m in out:
        m["default"] = m["id"] == default
    return out


@lru_cache(maxsize=None)
def client(provider: str) -> openai.OpenAI:
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider '{provider}' (use {', '.join(PROVIDERS)})")
    url_var, url_default, key_var = PROVIDERS[provider]
    key = os.getenv(key_var) if key_var else provider
    if not key:
        raise ValueError(f"{key_var} is not set in backend/.env")
    base = os.getenv(url_var, url_default) if url_var else None
    return openai.OpenAI(api_key=key, base_url=base, timeout=180)


def thinking_levels(provider: str, model: str) -> list[str]:
    """Thinking settings a model offers, as in the Morpheus docs: Gemma switches thinking on or
    off; Qwen also takes a reasoning effort. Empty: not switchable."""
    if provider != "morpheus":
        return []
    if re.search(r"qwen", model, re.I):
        return ["off", "low", "medium", "xhigh"]
    return ["off", "on"] if re.search(r"gemma", model, re.I) else []


def options(provider: str, model: str, thinking: str = "off") -> dict:
    """Per-provider request options. GPT-5 models take no temperature. Thinking is off unless
    asked for: it burns the token budget and the gateway's time, so it gets a larger budget."""
    if provider == "openai" and model.startswith("gpt-5"):
        return {"max_completion_tokens": 8000}
    levels = thinking_levels(provider, model)
    on = thinking in levels and thinking != "off"
    opts: dict = {"max_tokens": 16000 if on else 4000, "temperature": 0}
    if levels:
        body: dict = {"chat_template_kwargs": {"enable_thinking": on}}
        if on and thinking != "on":
            body["chat_template_kwargs"]["preserve_thinking"] = True
            body["reasoning_effort"] = thinking
        opts["extra_body"] = body
    return opts


# --------------------------------------------------------------------------- SQL


class Median:
    def __init__(self):
        self.values = []

    def step(self, v):
        if v is not None:
            self.values.append(v)

    def finalize(self):
        return float(pd.Series(self.values).median()) if self.values else None


class Quantile(Median):
    def step(self, v, q):
        self.q = q
        super().step(v)

    def finalize(self):
        return float(pd.Series(self.values).quantile(self.q)) if self.values else None


TABLE_NOTES = {
    "execs": "one row per executive × firm × year; amounts k€; total = fixed+sti+mti+lti+other; "
             "full_year = at least 360 days in office; stock_index is 'DAX', 'MDAX' or empty",
    "pay": "view: execs with full_year = 1 and total >= 100 — use it for pay statistics",
    "firm_years": "one row per firm × year; staff_cost k€, tsr a fraction, avg_staff_cost k€ per employee",
    "firms": "one row per firm",
    "peer_results": "peer benchmark per executive-year and peer definition (method): peer_median k€, "
                    "ratio = total ÷ peer_median, percentile 0–1, verdict",
    "forecasts": "forecasts from the latest year, every model; value, lo, hi (80 % range) in k€; "
                 "target is the pay item",
    "model_scores": "backtest of the prediction models: mae of log values (0.2 ≈ 20 %), skill > 0 "
                    "beats 'last year + drift'",
}


@lru_cache(maxsize=1)
def database() -> tuple[sqlite3.Connection, threading.Lock, str]:
    p, b, f = panel.get_panel(), peers.get_benchmarks(), forecast.get_forecasts()
    con = sqlite3.connect(":memory:", check_same_thread=False)
    firms = p.firms[["firm_id", "name", "isin", "naics", "naics_title", "first_year", "last_year"]]
    names = firms[["firm_id", "name"]].rename(columns={"name": "firm"})
    execs = p.execs[["person_id", "name", "firm_id", "year", "role", "index", "regime", "batch",
                     "female", "german", "birth_year", "days", "full_year", "fixed", "sti", "mti",
                     "lti", "other", "pension", "one_time", "total", "total_incl", "internal",
                     "max_comp"]].merge(names, on="firm_id").rename(columns={"index": "stock_index"})
    fy = p.firm_years[["firm_id", "year", "index", "regime", "opt_out", "n_execs", "board_total",
                       "employees", "staff_cost", "avg_staff_cost", "tsr", "sti_esg_share",
                       "lti_esg_share"]].merge(names, on="firm_id").rename(columns={"index": "stock_index"})
    res = b.results[b.results["method"].isin(peers.METHOD_IDS)].join(
        b.rows[["person_id", "name", "firm_id", "firm", "year", "role", "total"]])
    res = res[["method", "year", "firm_id", "firm", "person_id", "name", "role", "total",
               "peer_median", "p10", "p90", "ratio", "percentile", "verdict", "n_firms"]]
    lo, hi = f"lo{forecast.BAND:g}", f"hi{forecast.BAND:g}"
    fc = f.live[["person_id", "firm_id", "role", "target", "model", "year", "h", "value", lo, hi]]
    for name, df in [("execs", execs), ("firm_years", fy), ("firms", firms), ("peer_results", res),
                     ("forecasts", fc.rename(columns={lo: "lo", hi: "hi"})),
                     ("model_scores", f.scorecard)]:
        df.to_sql(name, con, index=False)
    con.execute("CREATE VIEW pay AS SELECT * FROM execs WHERE full_year = 1 AND total >= 100")
    con.create_aggregate("median", 1, Median)
    con.create_aggregate("quantile", 2, Quantile)
    schema = "\n".join(
        f"- {name}({', '.join(r[1] for r in con.execute(f'PRAGMA table_info({name})'))}): {note}"
        for name, note in TABLE_NOTES.items())
    con.execute("PRAGMA query_only = 1")
    allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
    con.set_authorizer(lambda action, *_: sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY)
    return con, threading.Lock(), schema


def sql(query: str) -> dict:
    con, lock, _ = database()
    with lock:
        steps = [0]

        def budget():
            steps[0] += 1
            return steps[0] > 2000  # × 1000 VM steps: stops runaway queries

        con.set_progress_handler(budget, 1000)
        try:
            cur = con.execute(query)
            rows = cur.fetchmany(MAX_ROWS + 1)
        except sqlite3.Error as e:
            return {"error": f"{e}. Only SELECT queries on the listed tables are allowed."}
        finally:
            con.set_progress_handler(None, 0)
    cols = [d[0] for d in cur.description or []]
    return {"columns": cols, "rows": [list(r) for r in rows[:MAX_ROWS]],
            "truncated": len(rows) > MAX_ROWS}


# --------------------------------------------------------------------------- other tools


def find(query: str) -> dict:
    p = panel.get_panel()
    q = panel.norm(query)
    people = (p.execs.sort_values("year").groupby("person_id")
              .agg(name=("name", "last"), firm_id=("firm_id", "last"), first=("year", "min"),
                   last=("year", "max"), role=("role", "last")).reset_index())

    def score(name: str) -> float:
        n = panel.norm(name)
        return 1.0 if q and q in n else difflib.SequenceMatcher(None, q, n).ratio()

    firms = p.firms.assign(score=p.firms["name"].map(score)).nlargest(5, "score")
    people = people.assign(score=people["name"].map(score)).nlargest(8, "score")
    return {"firms": firms[firms["score"] > 0.5][["firm_id", "name", "first_year", "last_year"]]
            .to_dict("records"),
            "people": people[people["score"] > 0.5].drop(columns="score").to_dict("records")}


def api(path: str, params: dict | None = None) -> object:
    """Call a GET route of the API in-process, as the dashboard would."""
    from .main import app

    path = "/" + path.lstrip("/")
    if not path.startswith("/api/"):
        path = "/api" + path
    for route in app.routes:
        match, child = route.matches({"type": "http", "path": path, "method": "GET"})
        if match != Match.FULL or path.startswith("/api/chat"):
            continue
        sig = inspect.signature(route.endpoint)
        kwargs = dict(child.get("path_params", {}))
        for k, v in (params or {}).items():
            if k in sig.parameters and v is not None:
                ann = sig.parameters[k].annotation
                kwargs[k] = int(v) if "int" in str(ann) and "float" not in str(ann) else (
                    float(v) if "float" in str(ann) else v)
        try:
            return jsonable_encoder(route.endpoint(**kwargs))
        except HTTPException as e:
            return {"error": e.detail}
        except (TypeError, ValueError) as e:
            return {"error": str(e)}
    return {"error": f"No GET route {path}. See the route list in the instructions."}


def routes() -> str:
    from .main import app

    out = []
    for path, ops in app.openapi()["paths"].items():
        op = ops.get("get")
        if not op or path.startswith("/api/chat"):
            continue
        params = [p["name"] for p in op.get("parameters", []) if p["in"] == "query"]
        doc = (op.get("description") or op.get("summary") or "").split("\n")[0]
        out.append(f"- {path}" + (f"?{'&'.join(params)}" if params else "") + (f" — {doc}" if doc else ""))
    return "\n".join(out)


@lru_cache(maxsize=1)
def sections() -> list[tuple[str, str]]:
    out = []
    for path in sorted(DOCS.glob("*.md")):
        for part in re.split(r"\n(?=## )", path.read_text(encoding="utf-8")):
            title = part.strip().splitlines()[0].lstrip("# ")
            out.append((f"{path.name} › {title}", part.strip()))
    return out


def docs(query: str) -> dict:
    words = set(re.findall(r"\w{4,}", query.lower()))
    ranked = sorted(sections(), key=lambda s: -len(words & set(re.findall(r"\w{4,}", s[1].lower()))))
    return {"sections": [{"title": t, "text": text[:4000]} for t, text in ranked[:2]]}


def check_row(row: dict) -> dict:
    return entry.check(row)


def propose_rows(changes: list[dict]) -> dict:
    """A draft for the user: the rows with their checks. Nothing is saved here."""
    parsed = []
    for c in changes:
        t = entry.table(str(c.get("table")))
        if t is None or t.id.startswith("custom:"):
            return {"error": f"Unknown table '{c.get('table')}'. Use one of: "
                             + ", ".join(t.id for t in entry.TABLES)}
        rows = [{k: "" if v is None else str(v) for k, v in r.items()} for r in c.get("rows") or []]
        parsed.append((t, rows))
    return {"changes": [{"table": t.id, "rows": rows} for t, rows in parsed],
            "checks": entry.validate(parsed),
            "note": "Shown to the user as an editable draft. Nothing is saved until they click Save."}


def chart(query: str, kind: str, x: str, y: str, title: str, color: str | None = None) -> dict:
    """Rows of a read-only SQL query and how to draw them; the page draws the chart."""
    if kind not in ("line", "bar", "dot"):
        return {"error": "kind must be line, bar or dot"}
    out = sql(query)
    if "error" in out:
        return out
    missing = {x, y, color} - {None, *out["columns"]}
    if missing:
        return {"error": f"Columns {sorted(missing)} are not in the query result {out['columns']}"}
    rows = [dict(zip(out["columns"], r)) for r in out["rows"]]
    return {"title": title, "kind": kind, "x": x, "y": y, "color": color, "rows": rows}


TABLE_ROWS = {"type": "array", "items": {"type": "object", "properties": {
    "table": {"type": "string"}, "rows": {"type": "array", "items": {"type": "object"}}},
    "required": ["table", "rows"]}}

TOOLS = {  # name: (function, description, parameters, required)
    "find": (find, "Find firms and executives by (part of) their name. Use it first to get ids.",
             {"query": {"type": "string"}}, ["query"]),
    "sql": (sql, "Run one read-only SQLite SELECT on the tables listed in the instructions. "
                 "Aggregates median(x) and quantile(x, q) are available.",
            {"query": {"type": "string"}}, ["query"]),
    "api": (api, "Call a GET route of the dashboard API (list in the instructions) and get its "
                 "JSON, e.g. path '/people/<person_id>/prediction' (ids from `find`) or '/whatif' "
                 "with params.",
            {"path": {"type": "string"}, "params": {"type": "object"}}, ["path"]),
    "check_row": (check_row, "Check a new executive-year before it is saved: typos, the "
                             "executive's forecast, the board, the peers and the pay mix. Fields: "
                             "firm, year, first_name, last_name, role, days, fixed, sti, mti, lti, "
                             "other, pension, one_time (k€).",
                  {"row": {"type": "object"}}, ["row"]),
    "propose_rows": (propose_rows, "Show the user a draft of rows to add (one or more tables, "
                                   "e.g. a firm-year and its executives). Returns the checks of "
                                   "every row. The user edits and saves the draft; call it again "
                                   "with the whole corrected draft when asked to change it.",
                     {"changes": TABLE_ROWS}, ["changes"]),
    "chart": (chart, "Draw a small chart in the answer from a read-only SQL query: kind 'line' "
                     "(trends over years), 'bar' (comparisons) or 'dot'; x and y are column names "
                     "of the result, color an optional column for series.",
              {"query": {"type": "string"}, "kind": {"type": "string", "enum": ["line", "bar", "dot"]},
               "x": {"type": "string"}, "y": {"type": "string"}, "title": {"type": "string"},
               "color": {"type": "string"}}, ["query", "kind", "x", "y", "title"]),
    "docs": (docs, "Search the project documentation (method, definitions, data issues).",
             {"query": {"type": "string"}}, ["query"]),
}
TOOL_SPECS = [{"type": "function", "function": {
    "name": name, "description": desc,
    "parameters": {"type": "object", "properties": props, "required": required}}}
    for name, (_, desc, props, required) in TOOLS.items()]


def run(name: str, args: dict) -> object:
    if name not in TOOLS:
        return {"error": f"Unknown tool '{name}'"}
    try:
        return TOOLS[name][0](**args)
    except Exception as e:  # a tool error goes back to the LLM, which can try again
        return {"error": f"{type(e).__name__}: {e}"}


# --------------------------------------------------------------------------- instructions


def table_lines() -> str:
    def column(c: entry.Column) -> str:
        extra = c.unit or "/".join(c.options)
        return c.name + (f" ({extra})" if extra else "") + ("*" if c.required else "")
    return "\n".join(f"- {t.id}: {', '.join(map(column, t.columns))}" for t in entry.TABLES[:3])


def instructions(page: str | None = None, draft: list[dict] | None = None) -> str:
    f = forecast.get_forecasts()
    p = panel.get_panel()
    best = ", ".join(f"{forecast.TARGETS[t]}: {m}" for t, m in f.best.items())
    methods = ", ".join(f"{m.id} ({m.name})" for m in peers.METHODS)
    return f"""You answer questions about the pay of German management boards (DAX and MDAX,
{int(p.execs['year'].min())}–{f.last_year}) for a research dashboard at TUM.

Rules
- Every number you write must come from a tool result. Never estimate, convert or calculate a
  number yourself: if you need a median, sum, share or change, get it with `sql` or `api`.
- Amounts are in k€ (thousand euro); you may write them as € million with one decimal.
  Shares in the data are fractions 0–1.
- Pay statistics use full-year executives (the view `pay`). Comparisons across 2021/22 use DAX
  firms only: reporting changed to §162 AktG in 2022 and the universe shrank to the DAX.
- Forecasts and what-if answers: use `api` with /people/{{id}}/prediction or /whatif. Give the
  80 % range, say which model, that forecasts assume the person stays in the role, and that
  what-if results are associations, not causes. Forecasts reach {max(forecast.HORIZONS)} years ahead
  (to {f.last_year + max(forecast.HORIZONS)}); for a later year say there is no forecast because it
  could not be tested against the data. Do not mention this limit otherwise.
- Best model per pay item (by backtest): {best}.
- Peer questions: there are six peer definitions: {methods}. If the user does not say which,
  ask, and suggest {f.peer_method} (best fit on the peer scorecard), or show all six.
- "Is X overpaid?": give the evidence (peers, forecast range, board), say that the answer
  depends on the reference, do not judge.
- Find ids with `find` first. Keep answers short: a direct answer, then a few bullet points.
  Answer in the language of the user's question (English if unclear).
- Use `chart` when a trend or a comparison is easier to see than to read; at most two per
  answer, and still state the key numbers in the text.

Adding data from a document or pasted text
- Never save anything. Extract the rows and call `propose_rows`; the user reviews, edits and
  saves the draft. When the user asks for a change, call `propose_rows` again with the whole
  corrected draft. Explain each warning the checks return in one line.
- Tables (* = required; amounts in k€):
{table_lines()}
- An executive-year needs a firm-year: check `firm_years` with `sql` and add a firm_years row
  to the same draft if it is missing. `firm` is the company name as in the data (use `find`).
- From a §162 remuneration report take the granted and owed amounts ("gewährte und geschuldete
  Vergütung"), not target amounts. Festvergütung / Grundgehalt → fixed; Nebenleistungen →
  other; einjährige variable Vergütung / STI / Bonus → sti; mehrjährige variable Vergütung in
  cash → mti; aktienbasierte Vergütung / LTI / Performance Shares → lti; Versorgungsaufwand /
  Dienstzeitaufwand → pension; Abfindung, Sign-on → one_time. Converting the document's unit
  (€, T€, Mio. €) to k€ is the one calculation you may do; say the document's unit.
- days = days on the board in that year (365 for the full year). source = document name and
  page, e.g. "SAP Vergütungsbericht 2025, p. 14". Leave unknown values empty and ask for them;
  never guess.

SQL tables
{database()[2]}

API routes (for `api`)
{routes()}
""" + (f"\nThe user is on the dashboard page '{page}' (companies/<firm_id>, people/<person_id>, "
       "prediction/<model>, peers/<definition>, …): 'this company', 'this person' or 'this "
       "model' refers to it.\n" if page else "") + (
        "\nCurrent draft, as the user has edited it (change this one when asked):\n"
        + json.dumps(draft, ensure_ascii=False) + "\n" if draft else "")


# --------------------------------------------------------------------------- answer check


NUMBER = re.compile(r"(?<![\w.,])[-+−]?\d(?:[\d.,]*\d)?")


def numbers_in(obj: object, out: set[float]) -> set[float]:
    if isinstance(obj, bool) or obj is None:
        return out
    if isinstance(obj, (int, float)):
        if math.isfinite(obj):
            out.add(float(obj))
    elif isinstance(obj, str):
        out.update(v for m in NUMBER.findall(obj) for v in readings(m))
    elif isinstance(obj, dict):
        for v in obj.values():
            numbers_in(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            numbers_in(v, out)
    return out


def readings(text: str) -> set[float]:
    """A number as written in English (1,234.5) and in German (1.234,5)."""
    text = text.replace("−", "-")
    out = set()
    for thousands, decimal in ((",", "."), (".", ",")):
        try:
            out.add(float(text.replace(thousands, "").replace(decimal, ".")))
        except ValueError:
            pass
    return out


def unverified(answer: str, results: list[object]) -> list[str]:
    """Numbers in the answer that no tool result (or the instructions) contains, in any of the
    forms the instructions allow (k€ as € million, fractions as %, ratios as % change), within
    rounding, read as English or German notation."""
    known: set[float] = set()
    for r in results:
        numbers_in(r, known)
    forms = {x for v in known for x in (v, v / 1000, v * 100, (v - 1) * 100, v / 1_000_000)}
    out = []
    for text in NUMBER.findall(answer):
        values = readings(text)
        if any(abs(v) <= 12 and v == int(v) or 1900 <= v <= 2100 and v == int(v) for v in values):
            continue  # counts, horizons, list numbers and years
        if not any(abs(v - k) <= max(0.051, 0.006 * abs(k)) for v in values for k in forms):
            out.append(text)
    return out


# --------------------------------------------------------------------------- the loop


def split_thinking(msg) -> tuple[str, str]:
    """(reasoning, answer): from the server's reasoning field, or from an inline <think> block
    (whose opening tag the chat template may already have put into the prompt)."""
    text = msg.content or ""
    extra = msg.model_extra or {}
    reasoning = extra.get("reasoning_content") or extra.get("reasoning") or ""
    if "</think>" in text:
        before, _, text = text.rpartition("</think>")
        reasoning = reasoning or before.replace("<think>", "")
    return reasoning.strip(), text.strip()


def chat(messages: list[dict], model: str, thinking: str = "off", page: str | None = None,
         draft: list[dict] | None = None) -> Iterator[dict]:
    """Events: {'type': 'thinking', text}, {'type': 'tool', name, args}, {'type': 'result',
    name, preview}, {'type': 'draft', changes, checks}, {'type': 'chart', title, kind, x, y,
    color, rows}, {'type': 'answer', text, unverified}, {'type': 'error', text}."""
    provider, _, name = model.partition(":")
    try:
        llm = client(provider)
        convo = [{"role": "system", "content": instructions(page, draft)}, *messages]
    except Exception as e:
        yield {"type": "error", "text": str(e)}
        return
    # numbers from the instructions and from what the user wrote or attached count as known
    results: list[object] = [convo[0]["content"], *(m["content"] for m in messages if m["role"] == "user")]
    native = True
    for step in range(MAX_STEPS + 1):
        last = step == MAX_STEPS
        if last:
            convo.append({"role": "user", "content": "No more tools: answer now with the results you have."})
        try:
            reply = llm.chat.completions.create(
                model=name, messages=convo, **options(provider, name, thinking),
                **({"tools": TOOL_SPECS} if native and not last else {}))
        except openai.BadRequestError as e:
            if native and "tool" in str(e).lower():
                native = False  # the gateway or model has no tool calling: describe tools in text
                convo[0]["content"] += TEXT_TOOLS
                continue
            yield {"type": "error", "text": f"The model refused the request: {e}"}
            return
        except openai.OpenAIError as e:
            yield {"type": "error", "text": f"{type(e).__name__}: {e}"}
            return
        msg = reply.choices[0].message
        calls = [(c.id, c.function.name, c.function.arguments) for c in msg.tool_calls or []]
        reasoning, text = split_thinking(msg)
        if reasoning:
            yield {"type": "thinking", "text": reasoning}
        if not native and not last and (call := text_call(text)):
            calls, text = [("text", *call)], ""
        if not calls:
            if not text:
                yield {"type": "error", "text": "The model returned no answer. Try again or ask more narrowly."}
                return
            yield {"type": "answer", "text": text, "unverified": unverified(text, results)}
            return
        if native:
            convo.append({k: v for k, v in msg.model_dump(exclude_none=True).items()
                          if k not in ("reasoning_content", "reasoning")})
        for call_id, tool, raw in calls:
            try:
                args = json.loads(raw or "{}")
            except json.JSONDecodeError:
                args = {}
            yield {"type": "tool", "name": tool, "args": args}
            result = run(tool, args)
            results.append(result)
            body = json.dumps(result, default=str, ensure_ascii=False)
            if len(body) > MAX_RESULT:
                body = body[:MAX_RESULT] + " … (cut: ask for fewer rows)"
            yield {"type": "result", "name": tool, "preview": body[:1500]}
            if isinstance(result, dict) and "error" not in result and tool in ("propose_rows", "chart"):
                yield {"type": "draft" if tool == "propose_rows" else "chart",
                       **{k: v for k, v in result.items() if k != "note"}}
            if native:
                convo.append({"role": "tool", "tool_call_id": call_id, "content": body})
            else:
                convo += [{"role": "assistant", "content": json.dumps({"tool": tool, "args": args})},
                          {"role": "user", "content": f"Result of {tool}: {body}"}]
    yield {"type": "error", "text": "No answer after the maximum number of tool calls."}


TEXT_TOOLS = """

Tools (this model has no native tool calling)
To call a tool, reply with only one JSON object: {"tool": "<name>", "args": {...}}. When you have
everything you need, reply with the answer as plain text. Tools:
""" + "\n".join(f"- {n}({', '.join(p)}): {d}" for n, (_, d, p, _) in TOOLS.items())


def text_call(text: str) -> tuple[str, str] | None:
    m = re.search(r"\{.*\}", text, re.S)
    try:
        obj = json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        return None
    if isinstance(obj, dict) and obj.get("tool") in TOOLS:
        return obj["tool"], json.dumps(obj.get("args") or {})
    return None


# --------------------------------------------------------------------------- examples


def examples() -> list[str]:
    """Demo questions built from the current data, so names and years are always valid."""
    f = forecast.get_forecasts()
    now = f.now.sort_values("total", ascending=False)
    ceos, cfos = now[now["role"] == "CEO"], now[now["role"] == "CFO"]
    last = f.last_year
    if len(ceos) < 4 or cfos.empty:
        return []
    a, b, c, cfo = ceos.iloc[0], ceos.iloc[1], ceos.iloc[3], cfos.iloc[0]
    first = int(panel.get_panel().execs["year"].min())
    return [
        f"What did {a['name']} earn as {a['firm']}'s CEO in {last}, and how was it split?",
        f"Who were the five best-paid DAX CEOs in {last}?",
        f"How has median DAX CEO pay developed since {first}? Compare like with like across the "
        "2021/22 reporting change.",
        f"Is {b['name']} at {b['firm']} paid above peers? Does it depend on the peer definition?",
        f"What will {c['name']} earn in {last + 2}, and how sure is that?",
        f"What would {cfo['name']} earn as CEO of {cfo['firm']}?",
        "Which model predicts annual bonuses best, and why does the neural network do worse?",
        f"I want to add {last + 1} for {a['name']} with a fixed salary of 1,400,000. Is that "
        "plausible?",
        f"What will the average DAX CEO earn in {last + 16}?",
    ]
