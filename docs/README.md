# Project map

This is the code map for Codex, Claude Code, and contributors. For what is currently working or next, read [STATUS.md](STATUS.md). For why durable choices were made, read [DECISIONS.md](DECISIONS.md). Root [README.md](../README.md) owns setup and user-facing behavior.

The current evaluation method for finished videos is [QUALITY_EVALUATION.md](QUALITY_EVALUATION.md). `scripts/prepare_narration.py` retains a budgeted, resumable narration set under ignored `outputs/`; `scripts/local_review.py` renders a zero-provider-call edit from complete local scene clips and narration, optionally passing timed text-overlay cues to `VideoEditor`; `scripts/creative_review.py` builds a private music/caption comparison page; `scripts/music_review.py` checks exact video-stream identity for a music-only comparison; `scripts/paired_review.py` runs the budgeted image/hybrid comparison. The private outcome summary is `src/shorts_maker/services/scorecard.py`.
The curated visual prompt rules and official source links are in [VISUAL_PROMPTING.md](VISUAL_PROMPTING.md).
The source-grounded story, motion, music, and spending recipe is [CREATIVE_FORMAT.md](CREATIVE_FORMAT.md).
The current zero-API, cross-topic source feasibility check is [TOPIC_DIRECTION_PREVIEW.md](TOPIC_DIRECTION_PREVIEW.md); it contains question-level hypotheses, not approved scripts or feeds.
Its Sillim depot paper gate produced a [five-scene script](sillim_depot_review_draft.json), now approved for one retained `nova` narration set. `scripts/render_sillim_depot_storyboard.py` draws original diagrams for the local audition; the final-voice cut reuses four of those clips and retimes the opening question. The renderer can also give the opening bus a short illustrative entrance for a zero-API comparison. `scripts/local_review.py` assembles ignored review cuts without new provider calls. [STATUS.md](STATUS.md) owns the current review gate.
The attempted single-shot Veo upgrade, exact prompt, source boundary, cost record, and rejection are in [SILLIM_VEO_PILOT.md](SILLIM_VEO_PILOT.md). The [five-scene Veo cut plan](SILLIM_VEO_CUT_PLAN.md) maps the approved voice to source-safe shots, local factual overlays, staged cost gates, the tracked [opening first-frame candidate](../assets/sillim_veo_opening_seed_v1.png), and [opening overlay pilot cues](sillim_opening_overlay_pilot.json). Private raw clips and review pages stay under ignored `outputs/evaluation/`.
The current NASA review's exact six-scene, source-checked narration and visual brief is [nasa_field_test_review.json](nasa_field_test_review.json). `scripts/render_nasa_storyboard.py` recreates its local six-scene diagrams from the source photo and retained narration lengths, then `scripts/local_review.py` makes the review cut. The photo, video clips, voice, music MP3, sidecar, and review metrics stay local and ignored.
The unapproved six-scene drafts for distinct [CW-Net](cw_net_review_draft.json) and [wind-tunnel](wind_tunnel_review_draft.json) episodes are not automatic visual-generation inputs; their primary-source checks and production gate are in [STATUS.md](STATUS.md). `scripts/render_cw_net_storyboard.py` and `scripts/render_wind_tunnel_storyboard.py` make original diagrams sized to local scratch narration for private, zero-API story auditions.
The [door-plug investigation draft](door_plug_review_draft.json) is an earlier source-checked story proposal after those three topics were rejected for weak interest. Its claims draw on two official NTSB pages; the current single-article automatic validator cannot verify both at once, so claims were manually checked for its local audition. `scripts/render_door_plug_storyboard.py` makes the six original diagrams from local scratch narration. The ignored media is not approved; [STATUS.md](STATUS.md) records its evidence and next gate.

Earlier PDCA plans, designs, analyses, and reports under `01-plan/` through `04-report/` and `archive/` are preserved as historical context. They describe past proposals and completion reports, not the current implementation contract. Verify them against code before reusing a pattern. Local `.pdca-*` snapshots and `.bkit-memory.json` are tool state and remain untracked.

## Production flow

```text
NiceGUI / scheduler
  -> AppState / ProductionService
  -> paid-production gate before new planning, narration, or visuals
  -> ScriptPlanner: RSS or URL -> extraction -> analysis -> script -> source-grounded validation
  -> visual cost preflight -> narration duration check
  -> VideoGenerator: per-scene Veo or Gemini, with visual cache
  -> VideoEditor: narration, subtitles, music, render
  -> rendered-file quality check + local production sidecar -> optional YouTube upload
```

The app is a Python modular monolith. `ProductionService` owns orchestration, progress, cancellation, scene routing, and upload readiness. External API and media details stay in their own modules. The scheduler invokes the same service without browser state.

## Find the owner

| Change | Start here | Verify with |
| --- | --- | --- |
| Topic sourcing and script facts | `src/shorts_maker/planner/script_planner.py`, `content_extractor.py`, `script_validator.py` | `tests/test_content_extraction.py`, `tests/test_review_regressions.py` |
| Source-grounded visual briefs, Veo prompt wrapper, optional first-frame input, and private per-request attempt records | `src/shorts_maker/planner/script_planner.py`, `script_validator.py`, `generator/video_generator.py` | `tests/test_review_regressions.py`, `tests/test_production_gates.py` |
| Visual model, duration, or output cost | `src/shorts_maker/services/visual_cost.py`, `generator/video_generator.py`, `utils/config.py` | `tests/test_production_gates.py`, `tests/test_review_regressions.py` |
| Paid request switch and retry exposure | `src/shorts_maker/utils/paid_gate.py`, `utils/character_video_generator.py`, `planner/script_planner.py`, `planner/script_validator.py`, `planner/content_analyzer.py`, `planner/content_enricher.py` | `tests/test_production_gates.py`, `tests/test_review_regressions.py` |
| Scene reuse, narration preflight, and upload sequence | `src/shorts_maker/services/production_service.py` | `tests/test_production_gates.py`, `tests/test_workflows.py` |
| Rendered video and quality gate | `src/shorts_maker/editor/video_editor.py`, `quality_check.py` | `tests/test_production_gates.py` |
| Music brief, provenance, and selection | `src/shorts_maker/planner/models.py`, `planner/script_planner.py`, `utils/bgm_manager.py`, `editor/video_editor.py`, `gui/state/app_state.py`, `gui/pages/main_page.py` | `tests/test_review_regressions.py`, `tests/test_production_gates.py`, `tests/test_workflows.py` |
| Retained narration, topic storyboards, local edit review, creative comparison, paired production, and outcome scorecard | `scripts/prepare_narration.py`, `scripts/render_nasa_storyboard.py`, `scripts/render_cw_net_storyboard.py`, `scripts/render_wind_tunnel_storyboard.py`, `scripts/render_door_plug_storyboard.py`, `scripts/render_sillim_depot_storyboard.py`, `scripts/local_review.py`, `scripts/creative_review.py`, `scripts/music_review.py`, `scripts/paired_review.py`, `src/shorts_maker/services/scorecard.py` | `tests/test_prepare_narration.py`, `tests/test_nasa_storyboard.py`, `tests/test_cw_net_storyboard.py`, `tests/test_wind_tunnel_storyboard.py`, `tests/test_door_plug_storyboard.py`, `tests/test_sillim_depot_storyboard.py`, `tests/test_local_review.py`, `tests/test_creative_review.py`, `tests/test_music_review.py`, `tests/test_production_gates.py`, `tests/test_scorecard.py` |
| Browser state and controls | `src/shorts_maker/gui/state/app_state.py`, `gui/pages/`, `gui/components/` | `tests/test_workflows.py` |
| Scheduled runs | `src/shorts_maker/utils/scheduler.py` | `tests/test_review_regressions.py` |
| Upload | `src/shorts_maker/uploader/youtube_uploader.py` | `tests/test_production_gates.py` |

## Runtime boundaries

- Settings load from `config/.env` or root `.env`; use `config/.env.example` as the template. Secrets are not tracked.
- `outputs/`, `temp/`, `logs/`, and local histories are runtime data, not project docs.
- `ProductionService` writes a neighboring `*.production.json` record for each new rendered MP4 when the output directory is writable; keep these local with the video.
- Each new `VideoGenerator` Veo request writes a private, prompt-free record under `outputs/evaluation/visual_attempts/` before the provider call and updates it after success, error, or timeout. One file represents one app attempt; a missing or incomplete final state needs billing reconciliation. Older direct pilot requests have separate ignored request records and are not backfilled here.
- `scripts/prepare_narration.py` writes scene MP3s and a cumulative request-reserve manifest to ignored `outputs/`; its ceiling uses a caller-verified model price and bounds requests, not the provider's final bill. `ProductionService` checks this manifest's scene text and file hashes when reusing those files. Legacy scratch audio without a manifest remains possible for local review and needs human script alignment.
- `VideoEditor.TTS_MODEL` owns the currently used narration model; `scripts/prepare_narration.py` reads that same value for its manifest and preflight. The default voice is an editor option. Settings has no independent TTS model or voice switch.
- `AppState` is in-memory browser-session state. API settings are process-wide.
- External calls are OpenAI for planning/narration, Brave when configured for enrichment, Google for visuals, and YouTube for upload. Unit tests mock those calls.
- `PAID_PRODUCTION_ENABLED` defaults to false. The shared production service, paired-review script, and direct OpenAI/Google/Brave request helpers check it before new provider calls; it does not cap actual bills. Complete local clip and narration reviews still run.
- `ProductionService` subtracts manual and cached visuals before its visual estimate. Direct `VideoGenerator.generate_clips()` and `generate_scene_clip()` also check the configured visual-output cap before generating; direct batches conservatively reserve every scene because they do not use the service cache. The standalone character-video helper checks one silent Veo clip against the same cap.
- The test suite uses `unittest`; a local `.venv` may exist. Run the command in `AGENTS.md` after changes.
