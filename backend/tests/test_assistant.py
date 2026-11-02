from app import assistant, entry


def test_sql_is_read_only():
    assert "error" in assistant.sql("DELETE FROM execs")
    assert "error" in assistant.sql("CREATE TABLE x (a)")
    out = assistant.sql("SELECT median(total), quantile(total, 0.9) FROM pay WHERE role = 'CEO'")
    assert out["rows"][0][0] < out["rows"][0][1]


def test_api_reaches_dashboard_routes_in_process():
    assert assistant.api("/firms/sap")["firm"]["name"] == "SAP"
    assert assistant.api("summary")["n_firms"] > 0
    assert "error" in assistant.api("/nope")
    assert "error" in assistant.api("/people/unknown")


def test_find_matches_partial_names():
    assert any(f["firm_id"] == "sap" for f in assistant.find("SAP")["firms"])


def test_numbers_not_in_tool_results_are_flagged():
    results = [{"total": 9268.2, "share": 0.35, "ratio": 1.42}]
    answer = "He earned €9.3 million (9,268 k€), 35% fixed, 42% above peers, in 2024; 5 peers. Bonus 777 k€."
    assert assistant.unverified(answer, results) == ["777"]


def test_text_tool_calls_are_parsed():
    assert assistant.text_call('Sure. {"tool": "sql", "args": {"query": "SELECT 1"}}') == (
        "sql", '{"query": "SELECT 1"}')
    assert assistant.text_call("The answer is 5.") is None


def test_thinking_is_switched_per_request_and_kept_out_of_the_answer():
    from types import SimpleNamespace

    gemma = assistant.options("morpheus", "google/gemma-4-31B-it", "on")["extra_body"]
    assert gemma == {"chat_template_kwargs": {"enable_thinking": True}}
    qwen = assistant.options("morpheus", "cyankiwi/Qwen3.8-Flash-Next-AWQ-INT4", "medium")["extra_body"]
    assert qwen == {"chat_template_kwargs": {"enable_thinking": True, "preserve_thinking": True},
                    "reasoning_effort": "medium"}
    off = assistant.options("morpheus", "cyankiwi/Qwen3.8-Flash-Next-AWQ-INT4", "huge")["extra_body"]
    assert off == {"chat_template_kwargs": {"enable_thinking": False}}  # unknown setting: off
    assert "extra_body" not in assistant.options("openai", "gpt-5-mini", "on")
    inline = SimpleNamespace(content="Let me check.</think>SAP paid 9,268 k€.", model_extra={})
    assert assistant.split_thinking(inline) == ("Let me check.", "SAP paid 9,268 k€.")
    field = SimpleNamespace(content="Answer.", model_extra={"reasoning_content": "Steps."})
    assert assistant.split_thinking(field) == ("Steps.", "Answer.")


def test_german_notation_and_numbers_from_the_instructions_count_as_known():
    results = ["full_year = at least 360 days", {"total": 10599.479}]
    assert assistant.unverified("Blume: 10.599 k€ (≈ €10,6 Mio.), Vollzeit ab 360 Tagen.", results) == []
    assert assistant.unverified("Blume: €12,4 Mio.", results) == ["12,4"]
    assert "stock_index" in assistant.sql("SELECT * FROM pay LIMIT 1")["columns"]


def test_drafts_are_checked_but_never_saved():
    before = {t.id: len(entry.rows(t)) for t in entry.TABLES[:2]}
    out = assistant.propose_rows([
        {"table": "firm_years", "rows": [{"firm": "SAP", "year": 2025, "index": "DAX", "source": "test"}]},
        {"table": "execs", "rows": [{"firm": "SAP", "year": 2025, "first_name": "Christian",
                                     "last_name": "Klein", "role": "CEO", "days": 365,
                                     "fixed": 1400000, "source": "test"}]}])
    execs = next(c for c in out["checks"] if c["table"] == "execs")["findings"]
    assert any("did you mean 1,400 k€" in f["message"] for f in execs)
    assert not any("no firm-year yet" in f["message"] for f in execs)  # it is in the same draft
    assert {t.id: len(entry.rows(t)) for t in entry.TABLES[:2]} == before
    assert "error" in assistant.propose_rows([{"table": "nope", "rows": []}])


def test_charts_take_their_numbers_from_sql():
    c = assistant.chart("SELECT year, median(total) AS pay FROM pay WHERE role = 'CEO' GROUP BY year",
                        "line", "year", "pay", "CEO median")
    assert c["rows"][0].keys() == {"year", "pay"}
    assert "error" in assistant.chart("SELECT year FROM pay", "line", "year", "pay", "x")
