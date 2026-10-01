# Durable decisions

This file records reasons that Git history alone does not explain. Append a dated entry when a design choice changes; routine fixes belong in commits. Verify each claim against current code before changing behavior.

## 2026-10-01 — Keep one production service

The NiceGUI and scheduler paths use `ProductionService` for the same planning, generation, render, quality, and upload sequence. This keeps paid-call ordering and upload readiness in one place. Avoid parallel pipelines in UI components.

## 2026-10-01 — Use hybrid generation by default

One short, silent Veo hook supplies motion; later scenes use Gemini stills. Per-scene `visual_mode` and manual clips allow exceptions. A preflight estimate blocks visual generation above `MAX_VISUAL_COST_USD`; provider-side spend controls remain separate. The decision is based on published model rates, not proven audience retention. Revisit after a production scorecard exists.

## 2026-10-01 — Cache visual work by scene

Narration or metadata edits should not regenerate unchanged paid visuals. The cache key includes visual prompt, model, duration, format, and character overlay asset versions. Corrupt files are ignored. This replaced whole-script cache keys.

## 2026-10-01 — Replace retired Imagen integration

Use Gemini 3.1 Flash-Lite Image through the `global` endpoint for 9:16 1K stills. Keep its output-price estimate and model lifecycle under review using Google Cloud's official documentation. Do not restore retired Imagen 3 calls merely because old prompts or docs mention them.

## 2026-10-01 — Ground planned scripts in the primary article

Pass up to 5,000 characters of the selected article or RSS summary to the existing GPT-4o editorial validator. Require it to reject unsupported concrete claims; a missing source stops planning before that call. Supplementary search snippets are leads only unless the primary article supports them. This reuses the existing review call and avoids a second paid fact-check request. It cannot independently prove the article true, so publication still needs editorial review and a measured scorecard.

## 2026-10-01 — Fix the render canvas and tighten aspect validation

A local audit found a legacy 1062×1920 output that passed the former loose ratio tolerance. Set every composed scene's canvas to the configured 1080×1920 and reduce the quality-check ratio tolerance to 0.002. The stricter check rejects the legacy file; it does not alter files already rendered. Keep the tolerance small enough for encoder rounding while rejecting visibly incorrect framing.

## 2026-10-01 — Keep production evidence beside each video

Write an atomic local `*.production.json` sidecar after rendering, including failed technical checks, and add the YouTube ID after a successful upload. A stable key from source, title, and narration lets image and hybrid runs of the same script be paired without copying the script into the sidecar. This is runtime data outside Git. The visual output estimate is planning evidence, not a bill; reconcile actual provider charges and human review privately before changing the default mode.
