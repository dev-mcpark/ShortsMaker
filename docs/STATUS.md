# Current status

Updated: 2026-10-01. This file owns the active milestone and known limits. Code and tests remain the final evidence.

## Goal and milestones

| Stage | State | Exit evidence |
| --- | --- | --- |
| 1. Cost-aware generation | Complete | Commit `3f537b2`; offline tests passed. Hybrid default, scene-level reuse, estimated visual cap, current image model. |
| 2. Source-grounded quality gate | Complete offline | Primary article text is passed to the script validator; missing source and contradictory `unsupported_claim` responses fail closed. 63 offline tests passed on 2026-10-01. |
| 3. Production scorecard | Blocked on Cloud Billing for live output | Paired renderer, shared narration, sidecars, and review method are ready. A verified NASA pilot reached Gemini, then received `BILLING_DISABLED`; no new video was rendered. Resume one pair, then three topics, after billing is enabled. |
| 4. Outcome feedback | Offline path ready; live data pending | Private CSV scorecard computes paired acceptance, billed cost per accepted video, and matched seven-day views, watch time, and revenue. No new published videos or analytics read scope/data exist yet. |

## Current evidence and limits

- Stages 2–4: 69 offline `unittest` checks passed on 2026-10-01; see `tests/test_review_regressions.py`, `tests/test_production_gates.py`, and `tests/test_scorecard.py`.
- Live pilot on 2026-10-01: OpenAI and Google credentials authenticated. Automatic planning of a NASA robot-fleet article was correctly rejected for an unsupported claim. A manually corrected six-scene script passed the source-grounded validator (score 95), and narration was generated once. The first Gemini image request returned `BILLING_DISABLED` for the configured project. No new visual, MP4, sidecar, Veo request, or YouTube upload was produced. OpenAI charges and any provider bill have not been reconciled.
- The app's visual cost cap estimates new output only. It is not a provider billing cap and excludes prompt tokens, OpenAI, retries, and taxes. See `config/.env.example`.
- Automated video checks cover duration, aspect ratio, audible track, and sampled black frames. Human editorial review and channel performance data are still needed before scaling publication.
- Source grounding uses at most the first 5,000 characters of supplied article text and an LLM judgment. It reduces unsupported claims but does not independently verify that the article is true or that the model will always catch an error.
- Older PDCA Markdown in `docs/01-plan/` through `docs/04-report/` and `docs/archive/` is retained for history; its plans and line numbers may no longer match current code.
- Stage 3 local technical baseline: 9 existing `outputs/final_shorts_*.mp4` files were inspected on 2026-10-01. Eight pass the tightened output check; one legacy file (`final_shorts_1773481242.mp4`) is 1062×1920 and now fails the 9:16 check. This audit says nothing about factual accuracy, audience retention, or new renderer output.
- A new render writes `*.production.json` next to its MP4, including failed quality checks after rendering. The record holds a preflight visual output estimate, not actual spend; runs that stop before rendering and old outputs have no sidecar. The scorecard reports zero complete pairs until actual reviews and bills are entered.
- The local ignored root `.env` was changed from `GENERATION_MODE=video` to `hybrid` on 2026-10-01 to match the cost-aware default. New app processes use it; an already running app needs a restart. No credentials or project IDs were changed.
- One enabled local `video` schedule was paused and set to `hybrid` on 2026-10-01 to avoid repeated paid planning/narration while Google billing is disabled. No ShortsMaker process was running at the time. Future scheduled runs pause themselves on `BILLING_DISABLED`; re-enable the saved schedule after billing and a successful pilot.

## Next handoff: production scorecard

Enable billing on the configured Google Cloud project and set a separate account budget; `config/README.md` explains the `BILLING_DISABLED` check. Then use the source-checked local pilot script at `outputs/evaluation/nasa_robot_fleet.json` with `scripts/paired_review.py`. Finish two more distinct source-checked topics as described in [QUALITY_EVALUATION.md](QUALITY_EVALUATION.md), review factual and production quality, and enter real provider charges in the private scorecard. Publish only accepted videos and collect matched seven-day metrics before changing the default mode. The existing YouTube token has upload scope only, so Analytics API automation requires new read scopes and consent; private CSV entry works meanwhile. Keep raw articles, account bills, sidecars, and private channel analytics outside Git; commit only anonymized findings and resulting code decisions. Re-render the flagged legacy file only if needed for publication.

## Intentionally retired

| Path or approach | Replacement | Revisit only if |
| --- | --- | --- |
| Imagen 3 image generation | Gemini 3.1 Flash-Lite Image through the `global` endpoint | A supported model offers measured better quality per dollar. |
| Whole-script visual cache keys | Per-scene visual identity in `outputs/clips/scenes/` | A migration proves old artifacts are worth recovering. |

## Handoff rule

When completing a stage or finding drift, update this file's date, stage state, evidence, and limits in the same commit. Keep historical rationale in `DECISIONS.md`, not here.
