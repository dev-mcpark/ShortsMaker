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

## 2026-10-01 — Compare with shared narration and private outcome data

The paired renderer passes the same recorded narration into image and hybrid production, fixes editor settings, and permits one Veo attempt to limit surprise retries. Caller-owned audio is validated but not deleted by the editor. The offline scorecard joins local sidecars to a private review CSV; it reports only complete pairs and waits for matched seven-day YouTube observations. This avoids requesting broader YouTube OAuth scopes or declaring a winning mode before real bills and audience data exist.

## 2026-10-01 — Stop scheduled work on disabled billing

A live image request returned `BILLING_DISABLED` after narration had already been paid for. Scheduled production now disables that schedule when this permanent provider error is returned, rather than repeating planning and TTS on every run. The user can re-enable it after connecting billing and confirming a pilot render. Other failures retain the existing schedule state.

## 2026-10-02 — Keep manual editorial cuts out of mode comparisons

A local re-cut of the first NASA pilot replaced misleading generated visuals with a credited NASA field photo and factual diagrams. It retained the narration and script key, so counting it as another image-mode sample would make the original image/hybrid pair ambiguous. Production sidecars now mark runs using manual scene clips as ineligible for the paired mode scorecard, while preserving those files for editorial review. An eligible pair still requires one render per mode for a script key; add explicit run identifiers if repeated paired experiments become necessary.

## 2026-10-02 — Ground visual briefs before paid generation

The first NASA pilot showed that an accurate narration can still be paired with misleading AI visuals. Use source-matched place, counts, roles, and time in each visual brief, one focused Veo shot, and simple still compositions. Avoid generic 4K/photorealism directives, invented exact labels, and unrelated examples in the planner prompt. The existing editorial validation call now checks visual claims as well as narration; it adds no API call but remains a model judgment, so human review stays required. Version the Veo prompt wrapper in the cache key so earlier paid clips are not silently treated as results of the revised prompt. See [VISUAL_PROMPTING.md](VISUAL_PROMPTING.md) for public guidance and deferred techniques.

## 2026-10-02 — Normalize final audio in the shared editor

The corrected NASA review cut measured -27.4 LUFS, while the original paired renders measured -24.4 LUFS. Normalize the final mixed track once in `VideoEditor` to a chosen -16 LUFS target with a -1.5 dB true-peak ceiling; copy the video stream so local processing does not regenerate visuals or incur API charges. Keep the original render if audio processing fails. The target is an editorial starting point, not proof that pronunciation or pacing is good; those still require playback review.

## 2026-10-02 — Storyboard the explanation before another paid visual

The owner rejected the first technically valid pilot for a static slideshow, absent music, and a flat story. For the next cut, use a source-supported question, observed decision, and limit; animate only the diagram elements that explain a change. Reuse the existing manual scene and prepared-audio route in `ProductionService` for a zero-API review render. Keep any track with unknown rights in local auditions only. One approved cut and actual bills should inform whether another generated visual is worth its cost. See [CREATIVE_FORMAT.md](CREATIVE_FORMAT.md).

## 2026-10-02 — Require documented music before paid media work

The editor previously chose a random local MP3 when the requested mood was missing and suppressed music errors, allowing a silent or unreviewed track in a finished video. Select deterministically among mood-matching tracks only when an adjacent record states title, artist, source, no-attribution license, and the exact file's SHA-256. Fail before TTS or visual generation when BGM is requested but no such track exists; if the mood is already selected, also fail before paid script planning. A deliberate `bgm_volume=0` remains available for silent drafts and paired comparisons. This records evidence for human rights review, not a legal verification of the claim. Remove the unused Pixabay API setting, which never supplied BGM.

Scheduled runs do not know their script's mood until after planning. When there is no documented music at all, pause the schedule before planning; if the resulting mood has no matching track, pause after that failure so the next run cannot repeat the paid planning call. Re-enable only after matching music is available.
