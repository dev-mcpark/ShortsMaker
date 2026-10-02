# Current status

Updated: 2026-10-02. This file owns the active milestone and known limits. Code and tests remain the final evidence.

## Goal and milestones

| Stage | State | Exit evidence |
| --- | --- | --- |
| 1. Cost-aware generation | Complete | Commit `3f537b2`; offline tests passed. Hybrid default, scene-level reuse, estimated visual cap, current image model. |
| 2. Source-grounded quality gate | Complete offline | Primary article text is passed to the script validator; missing source and contradictory `unsupported_claim` responses fail closed. 63 offline tests passed on 2026-10-01. |
| 3. Production scorecard | One paired topic rendered; editorial review pending | Image and hybrid videos from the same source-checked NASA script passed the technical gate. Visual setting and subtitle defects found in sampled frames block publication; actual bills and two more distinct topics are pending. |
| 4. Outcome feedback | Offline path ready; live data pending | Private CSV scorecard computes paired acceptance, billed cost per accepted video, and matched seven-day views, watch time, and revenue. No new published videos or analytics read scope/data exist yet. |

## Current evidence and limits

- Stages 2–4: 70 offline `unittest` checks passed on 2026-10-02; see `tests/test_review_regressions.py`, `tests/test_production_gates.py`, and `tests/test_scorecard.py`.
- Live pilot on 2026-10-01: OpenAI and Google credentials authenticated. Automatic planning of a NASA robot-fleet article was correctly rejected for an unsupported claim. A manually corrected six-scene script passed the source-grounded validator (score 95), and narration was generated once. The first Gemini image request returned `BILLING_DISABLED` for the configured project. No new visual, MP4, sidecar, Veo request, or YouTube upload was produced. OpenAI charges and any provider bill have not been reconciled.
- On 2026-10-02, Cloud Billing account `013235-BB5E57-BC700A` displayed as paid and listed the configured project `gen-lang-client-0536476734` as linked. An alerts-only monthly budget named `ShortsMaker monthly budget` was created for this billing account at ₩10,000, with actual-spend emails at 50%, 90%, and 100% to billing administrators/users. The budget does not stop spending, and it does not cover OpenAI charges.
- One authorized paired pilot was attempted on 2026-10-02. Its visual output upper estimate was $0.854 under the $1.25 comparison ceiling. A sandboxed attempt stopped during TTS because network access was unavailable; the retried run reached the first Gemini still and received `429 RESOURCE_EXHAUSTED`. No visual, MP4, sidecar, Veo request, or YouTube upload resulted. Narration may have incurred OpenAI TTS charges; reconcile provider bills before recording actual cost. Google documents 429 as either quota or shared-capacity exhaustion, so the specific cause remains unverified.
- A budget-conscious image-only test on 2026-10-02 succeeded with one Gemini 3.1 Flash-Lite Image request. The resulting scene 6 still passed the cache file check and was saved under ignored `outputs/clips/scenes/` for reuse. The published 1K output estimate is $0.034 plus input tokens; actual billing is not yet reconciled. No TTS, Veo, render, or upload ran in this test. One success confirms access, not sustained capacity or completion of a paired video.
- On 2026-10-02, one 6-second silent Veo 3.1 Fast hook succeeded and was cached (published output estimate $0.48). With all image and hybrid visuals cached, `scripts/paired_review.py` rendered one image/hybrid pair using shared 260-character narration. Both local MP4s are 1080×1920, 38.33 seconds, have audio, passed `check_video_quality`, and have sidecars with zero new visual output estimated during the render. Two private review rows were added; actual provider charges are still unknown. Nothing was uploaded.
- Editorial sampling found generated desert footage that can be mistaken for the [NASA source's Virginia field test](https://science.nasa.gov/blogs/planetary-expeditions/2026/09/15/nasa-field-tests-ai-fleet-capability-for-science-exploration/), an extra invented robot label in a future-scene still, and Korean subtitles split at awkward positions. Do not publish these pilot renders. Subtitle wrapping was fixed in code after rendering; the existing MP4s still show the old text. Source-matched visual prompts or clearly labeled reconstructions and a fresh review are needed before acceptance.
- The app's visual cost cap estimates new output only. It is not a provider billing cap and excludes prompt tokens, OpenAI, retries, and taxes. See `config/.env.example`.
- Automated video checks cover duration, aspect ratio, audible track, and sampled black frames. Human editorial review and channel performance data are still needed before scaling publication.
- Source grounding uses at most the first 5,000 characters of supplied article text and an LLM judgment. It reduces unsupported claims but does not independently verify that the article is true or that the model will always catch an error.
- Older PDCA Markdown in `docs/01-plan/` through `docs/04-report/` and `docs/archive/` is retained for history; its plans and line numbers may no longer match current code.
- Stage 3 local technical baseline: 9 existing `outputs/final_shorts_*.mp4` files were inspected on 2026-10-01. Eight pass the tightened output check; one legacy file (`final_shorts_1773481242.mp4`) is 1062×1920 and now fails the 9:16 check. This audit says nothing about factual accuracy, audience retention, or new renderer output.
- A new render writes `*.production.json` next to its MP4, including failed quality checks after rendering. The record holds a preflight visual output estimate, not actual spend; runs that stop before rendering and old outputs have no sidecar. The scorecard reports zero complete pairs until actual reviews and bills are entered.
- The local ignored root `.env` was changed from `GENERATION_MODE=video` to `hybrid` on 2026-10-01 to match the cost-aware default. New app processes use it; an already running app needs a restart. No credentials or project IDs were changed.
- One enabled local `video` schedule was paused and set to `hybrid` on 2026-10-01 to avoid repeated paid planning/narration while Google billing is disabled. No ShortsMaker process was running at the time. Future scheduled runs pause themselves on `BILLING_DISABLED`; re-enable the saved schedule after billing and a successful pilot.

## Next handoff: production scorecard

Billing and account budget are in place, and the first paired production path works technically. Review the two private pilot videos and repair the source-mismatched visuals before any publication; avoid paid regeneration until the visual plan is settled. The current paired script regenerates narration on another run. Finish two more distinct source-checked topics as described in [QUALITY_EVALUATION.md](QUALITY_EVALUATION.md), then enter real provider charges and editorial decisions in the private scorecard. Publish only accepted videos and collect matched seven-day metrics before changing the default mode. The existing YouTube token has upload scope only, so Analytics API automation requires new read scopes and consent; private CSV entry works meanwhile. Keep raw articles, account bills, sidecars, and private channel analytics outside Git; commit only anonymized findings and resulting code decisions. Re-render the flagged legacy file only if needed for publication.

## Intentionally retired

| Path or approach | Replacement | Revisit only if |
| --- | --- | --- |
| Imagen 3 image generation | Gemini 3.1 Flash-Lite Image through the `global` endpoint | A supported model offers measured better quality per dollar. |
| Whole-script visual cache keys | Per-scene visual identity in `outputs/clips/scenes/` | A migration proves old artifacts are worth recovering. |

## Handoff rule

When completing a stage or finding drift, update this file's date, stage state, evidence, and limits in the same commit. Keep historical rationale in `DECISIONS.md`, not here.
