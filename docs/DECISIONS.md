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

## 2026-10-02 — Reveal captions by phrase and cut between scenes

The first moving NASA draft displayed each entire scene sentence from its first frame, including facts the voice had not reached. Its five later scene starts also faded from black for 0.5 seconds while narration had already begun; sampled frame brightness was near zero just after each cut. Show short caption phrases in sequence and use immediate scene cuts. With no word timestamps, phrase duration is estimated from character counts and remains a review draft: the editor must check speech synchronization before publication. Reuse the same narration and visuals for local comparison; this change does not request another API asset.

## 2026-10-02 — Pilot a documented stock music bed

The editor had no publishable BGM candidate, and the Studio's fixed `calm` selection overrode a science script's `sci-fi` mood. Use a Mixkit track whose [listing](https://mixkit.co/free-stock-music/atmospheres/) identifies title and artist and whose [Stock Music Free License](https://mixkit.co/license/modal/musicFree/) permits commercial YouTube videos without attribution. Keep the MP3 local and ignored; commit only its exact-hash license record and retrieval instructions. Let Studio follow the script mood by default, retain an explicit override, and expose the mix level. Auto mood requires at least one documented track before paid planning and a matching track after the script is known. Set the initial level to 40% for this measured -23.26 LUFS track against the -16 LUFS draft voice; check audibility and masking by ear. License metadata records evidence, not Content ID clearance or editorial acceptance.

## 2026-10-02 — Carry AI disclosure into private uploads

[YouTube's policy](https://support.google.com/youtube/answer/14328491?hl=en) requires disclosure for realistic AI-generated or meaningfully altered content, while obvious animation and script assistance alone do not require it. The API accepts [the disclosure in `status.containsSyntheticMedia`](https://developers.google.com/youtube/v3/docs/videos). The automatic pipeline creates AI visuals and cannot reliably judge their realism, so default its private API uploads to disclosure. A manual uploader must choose yes or no after reviewing the actual cut. Keep the result private until the source, visual rights, metadata, and label are checked; allow a deliberate false value for a non-realistic manual cut.

## 2026-10-02 — Distinguish source photos from explanation graphics

The NASA A/B review cuts used a `NASA ASTRA` banner that could suggest official production even though they are independent explanations. Keep the source credit, but label the local storyboard as a field-test explanation and distinguish actual source photos from conceptual diagrams in each scene. Preserve the older renders privately for audit; compare the corrected cuts before commissioning final narration or visuals.

## 2026-10-03 — Require complete local inputs for a free edit review

The NASA review files were rendered by ignored, topic-specific scripts, while the Studio's manual-clip route can still request fresh narration and a partially supplied clip set can fall through to visual generation. Add a small `scripts/local_review.py` entry that requires a clip and one prepared narration file for every scene before calling the existing `ProductionService`. Keep the media and script local; let the service apply the same music, caption, technical, and sidecar gates. The command does not upload. This makes the zero-provider-call review step reusable without changing the partial-manual behavior of the Studio.

## 2026-10-03 — Keep narration retries bounded and voice consistent

The editor previously retried every OpenAI TTS failure three times on top of the SDK's own retries, then silently switched to gTTS. This could repeat permanent failures and change the voice in a finished cut. Create the OpenAI client only when narration generation is requested so a complete local edit works without an API key. Disable SDK retries and retry only a transient connection or server error once; propagate authentication, quota, validation, and exhausted transient errors. Remove the unused gTTS fallback. Prepared narration remains the no-API review path.

## 2026-10-03 — Reserve Veo retry exposure before narration

The regular pipeline allowed four Veo attempts while its visual preflight priced one output. Use one attempt by default, as the paired comparison already does. If a caller explicitly requests more attempts, multiply each uncached Veo scene's output estimate by that limit before narration or generation. Cached and manual scenes reserve nothing. This is a conservative request reserve, not an actual bill or protection from provider-side retries and other unpriced inputs.

## 2026-10-03 — Keep the question-first tone for the NASA pilot

The owner preferred A's question-first storytelling voice over B's result-first voice. Continue the NASA pilot with A's specific dilemma, early observed choice, and causal explanation. Correct factual phrasing against the primary article even when the preferred cut needs revision: the drone briefly paused but did not abandon its original task. This preference applies to the current pilot; test other topics before making question-first delivery a universal rule. Full editorial and publication acceptance remain separate decisions.

## 2026-10-03 — Change the NASA music bed and soften captions

The owner found the documented “Feedback Dreams” music wholly mismatched to the NASA A story, while the visual rhythm was acceptable and caption styling felt rigid. Keep the visual timing. Route `sci-fi` to a documented [Mixkit “Digital Clouds” technology track](https://mixkit.co/free-stock-music/tag/technology/) and retain “Feedback Dreams” under `mysterious`. Use the existing [free stock music license](https://mixkit.co/license/modal/musicFree/) and local hash check instead of adding a paid music API. Start this louder track at 20% under speech, subject to playback review. Use softer white Korean captions with a slimmer dark outline and rebalance short final lines. This is one pilot treatment, not proof of musical fit, final voice clarity, or a universal style.

## 2026-10-03 — Keep a capability distinct from an observed result

In the NASA review script, “the rover collected a sample” converted the [source's description of its robotic-arm sampling role](https://science.nasa.gov/blogs/planetary-expeditions/2026/09/15/nasa-field-tests-ai-fleet-capability-for-science-exploration/) into a specific past event the article did not establish. Change the local narration to describe the role, and ask both the planner and existing validator to preserve this distinction. This adds no model call. The prompt rule reduces the risk but cannot verify generated scripts without a source check and human review.

## 2026-10-03 — Let the local music review name one track

A script mood is too broad to guarantee that a stock song fits an individual story. Keep mood selection for automatic drafts, but allow `scripts/local_review.py --bgm-track` to name one documented MP3 exactly. Resolve it before paid planning when used in production, and fail if it is missing or its hash differs instead of falling back to a mood match. This keeps stock music comparison local and free; the owner still decides musical fit by listening.

## 2026-10-03 — Compare caption presentation without changing the edit

The owner accepted the NASA cut's visual rhythm but found the captions rigid. Keep `soft` as the shared default while offering a local `card` review style with left-aligned text and a subtle translucent panel. Use the same script, scene clips, narration, and music to compare caption feel at zero provider cost. Record the selected style in the private production sidecar. Do not adopt a style globally until the owner reviews it in motion.

## 2026-10-03 — Default the current review round to zero new paid calls

The working plan says $0 in new provider calls until a per-round budget is agreed, but the regular service previously enforced only a visual-output estimate. Add `PAID_PRODUCTION_ENABLED=false` by default: block service planning and regeneration before OpenAI use, block production before new TTS or visual work, and block the paired script before its shared narration request. Pause a scheduled run when this condition is disabled. Prepared narration plus manual or cached visuals remain available for no-API review. This is an explicit start/stop control for the normal workflow, not a provider spending limit or a reliable estimate of total cost; standalone provider utilities remain outside it. Do not turn it on merely because Cloud Billing is active.

## 2026-10-03 — Check the spending switch at direct provider requests

The service-level switch left direct generator, narration, planner, character-video, and Brave search helpers able to issue provider calls. Add a small check immediately before each OpenAI, Google generation, and Brave request, so a direct CLI/helper call also respects `PAID_PRODUCTION_ENABLED=false`. The standalone character-video helper also drops its three automatic Veo attempts in favor of one explicit attempt. This closes a documented bypass without changing local editing or the service's preflight. The switch still has no monetary accounting; direct utilities need their own estimate before enabling it, and a request already in flight is not cancelled by turning it off.

## 2026-10-03 — Let Studio name the reviewed music file

The NASA critique showed that `sci-fi` can select a documented but mismatched song. Keep mood selection for automatic drafts, but list only hash-verified tracks with title and artist in Studio and allow an exact filename override. Preserve a missing prior choice visibly, so the existing preflight fails before paid planning instead of silently falling back to another track. When a session's editor choice changes, create a new production service rather than reusing its cached editor with the old music. This exposes an editorial decision; no metadata can prove musical fit without listening.
