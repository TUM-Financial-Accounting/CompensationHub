# ROADMAP

**Goal:** a prototype that benchmarks management-board pay against peers and flags unusual pay
structures, on one harmonised 2006–2024 panel. Direction agreed on 11 Sep 2026.

Done and documented where it lives: the panel and dashboard ([`docs/data.md`](docs/data.md)),
the peer benchmark ([`docs/peers.md`](docs/peers.md)), pay prediction
([`docs/prediction.md`](docs/prediction.md)), red flags ([`docs/redflags.md`](docs/redflags.md)),
the assistant and the Add data form ([`docs/assistant.md`](docs/assistant.md)). This file lists
only what is open.

## Plan

| Weeks | Focus | Status |
|---|---|---|
| W9 | Red flags & anomalies | built 18 Nov 2026 ([`docs/redflags.md`](docs/redflags.md)); open items under Next |
| W10–11 | Everything in the dashboard + AI assistant | built; tested on Morpheus 21–22 Oct; open items under Next |
| W12 | Wrap-up, final presentation | open |

## Next

- Red flags: review the thresholds with the chair (`JUMP` 50 %, `PAY_UP` 20 % with negative TSR,
  `SEVERANCE_CAP` 2×, `FLAG_SHARE` 5 %); decide whether
  firm-years without an index listing stay in the detectors (item 3 in
  [`docs/data.md`](docs/data.md#needs-a-decision)); check whether the legacy 2021 figures follow
  §162 (2021 has three times the usual pay jumps). Possible further rule: CEO pay slice
  (Bebchuk, Cremers & Peyer 2011).
- Review the NAICS codes in `data/reference/industries.csv` (none of the 164 rows is reviewed
  yet) and settle the other curation decisions in [`docs/data.md`](docs/data.md#needs-a-decision).
- Assistant: run the 28 demo questions as an automatic test (needs a decision on how strict
  "correct" is); run one full 2025 remuneration report through *Attach* and save it; test with
  `openai:gpt-5-mini` (no OpenAI key yet).
- Hackathon credits: `docs/hackathon/` is now git-ignored, but `docs/peers.md` ("What was taken
  from the six hackathon projects") and the `Method` descriptions in `backend/app/peers.py` still
  name those projects. Decide whether to keep them as credits or reword them.
- Feedback page, before it is opened wider: no login or rate limit on posting, the assistant's
  rate limit trusts a header a client can set, and only the newest 500 posts are listed
  (`ponytail:` notes in `backend/app/main.py`).
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
