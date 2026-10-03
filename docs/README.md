# Project map

This is the code map for Codex, Claude Code, and contributors. For what is currently working or next, read [STATUS.md](STATUS.md). For why durable choices were made, read [DECISIONS.md](DECISIONS.md). Root [README.md](../README.md) owns setup and user-facing behavior.

The current evaluation method for finished videos is [QUALITY_EVALUATION.md](QUALITY_EVALUATION.md). `scripts/local_review.py` renders a zero-provider-call edit from complete local scene clips and narration; `scripts/creative_review.py` builds a private music/caption comparison page after checking exact stream identity; `scripts/paired_review.py` runs the budgeted image/hybrid comparison. The private outcome summary is `src/shorts_maker/services/scorecard.py`.
The curated visual prompt rules and official source links are in [VISUAL_PROMPTING.md](VISUAL_PROMPTING.md).
The source-grounded story, motion, music, and spending recipe is [CREATIVE_FORMAT.md](CREATIVE_FORMAT.md).
The current NASA review's exact six-scene, source-checked narration and visual brief is [nasa_field_test_review.json](nasa_field_test_review.json). It is a shareable script for editorial handoff; its video clips, scratch voice, music MP3, sidecar, and review metrics stay local and ignored.

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
| Source-grounded visual briefs and Veo prompt wrapper | `src/shorts_maker/planner/script_planner.py`, `script_validator.py`, `generator/video_generator.py` | `tests/test_review_regressions.py`, `tests/test_production_gates.py` |
| Visual model, duration, or output cost | `src/shorts_maker/services/visual_cost.py`, `generator/video_generator.py`, `utils/config.py` | `tests/test_production_gates.py`, `tests/test_review_regressions.py` |
| Paid request switch and retry exposure | `src/shorts_maker/utils/paid_gate.py`, `utils/character_video_generator.py`, `planner/script_planner.py`, `planner/script_validator.py`, `planner/content_analyzer.py`, `planner/content_enricher.py` | `tests/test_production_gates.py`, `tests/test_review_regressions.py` |
| Scene reuse, narration preflight, and upload sequence | `src/shorts_maker/services/production_service.py` | `tests/test_production_gates.py`, `tests/test_workflows.py` |
| Rendered video and quality gate | `src/shorts_maker/editor/video_editor.py`, `quality_check.py` | `tests/test_production_gates.py` |
| Music brief, provenance, and selection | `src/shorts_maker/planner/models.py`, `planner/script_planner.py`, `utils/bgm_manager.py`, `editor/video_editor.py`, `gui/state/app_state.py`, `gui/pages/main_page.py` | `tests/test_review_regressions.py`, `tests/test_production_gates.py`, `tests/test_workflows.py` |
| Local edit review, creative comparison, paired production, and outcome scorecard | `scripts/local_review.py`, `scripts/creative_review.py`, `scripts/paired_review.py`, `src/shorts_maker/services/scorecard.py` | `tests/test_local_review.py`, `tests/test_creative_review.py`, `tests/test_production_gates.py`, `tests/test_scorecard.py` |
| Browser state and controls | `src/shorts_maker/gui/state/app_state.py`, `gui/pages/`, `gui/components/` | `tests/test_workflows.py` |
| Scheduled runs | `src/shorts_maker/utils/scheduler.py` | `tests/test_review_regressions.py` |
| Upload | `src/shorts_maker/uploader/youtube_uploader.py` | `tests/test_production_gates.py` |

## Runtime boundaries

- Settings load from `config/.env` or root `.env`; use `config/.env.example` as the template. Secrets are not tracked.
- `outputs/`, `temp/`, `logs/`, and local histories are runtime data, not project docs.
- `ProductionService` writes a neighboring `*.production.json` record for each new rendered MP4 when the output directory is writable; keep these local with the video.
- `AppState` is in-memory browser-session state. API settings are process-wide.
- External calls are OpenAI for planning/narration, Brave when configured for enrichment, Google for visuals, and YouTube for upload. Unit tests mock those calls.
- `PAID_PRODUCTION_ENABLED` defaults to false. The shared production service, paired-review script, and direct OpenAI/Google/Brave request helpers check it before new provider calls; it does not cap actual bills. Complete local clip and narration reviews still run.
- The test suite uses `unittest`; a local `.venv` may exist. Run the command in `AGENTS.md` after changes.
