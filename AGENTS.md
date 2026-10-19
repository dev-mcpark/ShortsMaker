# Shared project instructions

ShortsMaker's goal is to sustain repeatable production and upload of source-grounded Korean Shorts within a controlled budget, with measurable quality and eventual YouTube revenue. Optimize for videos worth publishing, not upload volume alone. Automatic uploads are private review copies; public release remains an editorial decision.

Before editing, read [docs/README.md](docs/README.md) for the code map and [docs/STATUS.md](docs/STATUS.md) for the active milestone. Read task-relevant entries in [docs/DECISIONS.md](docs/DECISIONS.md). Verify these documents against current code and tests; record any drift you find.

Keep one owner for each fact:

- Structure and code ownership: `docs/README.md`.
- Current milestone, evidence, blockers, and intentionally retired paths: `docs/STATUS.md`.
- Durable design choices and reversals: `docs/DECISIONS.md`.
- Setup and user-facing behavior: root `README.md` and `config/.env.example`.

Update the relevant document with the code change. Date status and decision entries. Do not use docs as proof that code works; run the applicable tests. Standard offline check: `python -m unittest discover -s tests -q` in the project environment (or `.venv/bin/python -m unittest discover -s tests -q` when available).

Avoid live paid API calls and YouTube uploads during routine verification. Keep secrets, tokens, downloaded articles, and private channel metrics out of Git. Prefer small changes within the existing modular monolith; preserve resumable scene work, cost preflight, and output quality gates.
