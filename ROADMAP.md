# ROADMAP

**Goal:** a prototype that benchmarks management-board pay against peers and flags unusual pay
structures, on one harmonised 2006–2024 panel. Direction agreed on 11 Sep 2026.

Done and documented where it lives: the panel and dashboard ([`docs/data.md`](docs/data.md)),
the peer benchmark ([`docs/peers.md`](docs/peers.md)), pay prediction
([`docs/prediction.md`](docs/prediction.md)), the assistant and the Add data form
([`docs/assistant.md`](docs/assistant.md)). This file lists only what is open.

## Plan

| Weeks | Focus | Status |
|---|---|---|
| W9 | Red flags & anomalies | open |
| W10–11 | Everything in the dashboard + AI assistant | built; tested on Morpheus 21–22 Oct; open items under Next |
| W12 | Wrap-up, final presentation | open |

## Red flags & anomalies

Rules from the governance code and §87 AktG (no cap, opt-out, pay up while performance falls,
large one-time payments, sudden jumps) plus statistical flags (above the peers' 90th percentile or
the forecast's 80 % range; Isolation Forest / LOF within peer groups). Every flag shows its
evidence; robustness = in how many peer definitions and models it is raised.
Reusable: the peer verdicts ("above under k definitions"), the forecast ranges and the
plausibility check in `entry.py`.

## Next

- Red flags (above), with a page in the dashboard.
- Review the NAICS codes in `data/reference/industries.csv` and settle the other curation
  decisions in [`docs/data.md`](docs/data.md#needs-a-decision).
- Assistant: run the 26 demo questions as an automatic test (needs a decision on how strict
  "correct" is); run one full 2025 remuneration report through *Attach* and save it; test with
  `openai:gpt-5-mini` (no OpenAI key yet).
- Hackathon credits: `docs/hackathon/` is now git-ignored, but `docs/peers.md` ("What was taken
  from the six hackathon projects") and the `Method` descriptions in `backend/app/peers.py` still
  name those projects. Decide whether to keep them as credits or reword them.
- Optional: collect the DCGK G.3 peer groups the DAX 40 disclose and compare them with the
  peer definitions, a direct test of self-serving peer selection (Faulkender & Yang 2010).

## Decided

**No further data is coming** (19 Sep 2026): no ORBIS financials, no sector list (the NAICS codes
were assigned in this project). Firm size is proxied by index and board size
([`docs/data.md`](docs/data.md#worth-knowing)), so results are about pay *relative to board and
index peers*, not size-adjusted in the ORBIS sense. State this in the write-up.

## Open questions for the chair

- [ ] Priorities between the remaining features, meeting rhythm.
- [ ] To mention at the next meeting: LightGBM and SHAP were replaced by the model comparison
  ([`docs/prediction.md`](docs/prediction.md#models)); the demographic model variant exists for
  its coefficients only and never predicts.
