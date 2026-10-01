# Current status

Updated: 2026-10-01. This file owns the active milestone and known limits. Code and tests remain the final evidence.

## Goal and milestones

| Stage | State | Exit evidence |
| --- | --- | --- |
| 1. Cost-aware generation | Complete | Commit `3f537b2`; offline tests passed. Hybrid default, scene-level reuse, estimated visual cap, current image model. |
| 2. Source-grounded quality gate | Complete offline | Primary article text is passed to the script validator; missing source and contradictory `unsupported_claim` responses fail closed. 63 offline tests passed on 2026-10-01. |
| 3. Production scorecard | Next | Review a small set of real finished videos for factual accuracy, hook, pacing, sound, visual variety, and estimated versus billed cost. Record a repeatable decision rule before scaling. |
| 4. Outcome feedback | Later | Connect video-level YouTube retention/revenue and provider bills to choose image versus hybrid versus video by measured return. |

## Current evidence and limits

- Stage 2: 63 offline `unittest` checks passed on 2026-10-01; see `tests/test_review_regressions.py` for source handoff and rejection checks.
- No live Veo, Gemini, OpenAI, or YouTube run was made for this milestone; account access, output quality, and actual billing remain unverified.
- The app's visual cost cap estimates new output only. It is not a provider billing cap and excludes prompt tokens, OpenAI, retries, and taxes. See `config/.env.example`.
- Automated video checks cover duration, aspect ratio, audible track, and sampled black frames. Human editorial review and channel performance data are still needed before scaling publication.
- Source grounding uses at most the first 5,000 characters of supplied article text and an LLM judgment. It reduces unsupported claims but does not independently verify that the article is true or that the model will always catch an error.
- Older PDCA Markdown in `docs/01-plan/` through `docs/04-report/` and `docs/archive/` is retained for history; its plans and line numbers may no longer match current code.

## Next handoff: production scorecard

Use a small, consented set of real preview videos. For each, record the source URL, human checked factual claims, hook clarity in the first five seconds, pacing, sound intelligibility, visual relevance/variety, estimated and billed API cost, and whether it was published. Keep raw articles, account bills, and private channel analytics outside Git; commit only anonymized findings and changes to the decision rule. Compare image and hybrid output before increasing scheduled volume.

## Intentionally retired

| Path or approach | Replacement | Revisit only if |
| --- | --- | --- |
| Imagen 3 image generation | Gemini 3.1 Flash-Lite Image through the `global` endpoint | A supported model offers measured better quality per dollar. |
| Whole-script visual cache keys | Per-scene visual identity in `outputs/clips/scenes/` | A migration proves old artifacts are worth recovering. |

## Handoff rule

When completing a stage or finding drift, update this file's date, stage state, evidence, and limits in the same commit. Keep historical rationale in `DECISIONS.md`, not here.
