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

## 2026-10-03 — Carry a music brief with the story

A broad `mood` value did not explain why a track should fit the NASA A cut. Add an optional `music_direction` sentence to the script, request it in the existing planning call, show it in Studio, and copy it beside the selected track in the private production record. Older scripts default to an empty brief. For the NASA pilot, describe curious restraint, a small lift at the branch decision, and a calm Earth-test ending; avoid horror, triumphant scoring, and a beat that masks speech. The brief guides human listening and adds no API request, but it cannot certify suitability.

## 2026-10-03 — Disable hidden OpenAI planning retries

The installed OpenAI Python SDK defaults to two retries, while the planner, analyzer, enricher, and validator constructed clients without an override. Use `max_retries=0` for those four clients, matching the narration client's explicit retry accounting. A failed request may still have provider-side cost, and the planner can deliberately inspect another topic or be rerun, so this change bounds each SDK call rather than a whole production round. It improves cost predictability without changing prompts or source checks.

## 2026-10-03 — Verify controlled music and caption comparisons

A music choice and a caption treatment need separate listening and viewing judgments. Generate a local three-cut review page only after comparing encoded streams: the music alternate must keep the baseline video exactly, while the caption alternate must keep its audio exactly. `scripts/creative_review.py` makes this check reproducible and keeps the page with ignored video files. It is not a perceptual score or owner acceptance; neither an exact shared stream nor a license record can prove the song fits the story.

## 2026-10-04 — Carry the owner's NASA music and caption choice into the next cut

The owner heard the controlled options and found Digital Clouds the best fit, then preferred soft captions over the card treatment. Use that exact documented MP3 at the reviewed 20% level and the soft style for the NASA A pilot's next edit. Record this in private review notes without marking the scratch-voice cut fully accepted. The choice is specific to this story; other scripts still require music selected against their own `music_direction` and playback review. Do not buy final narration until the exact script and a round spending ceiling are confirmed.

## 2026-10-04 — Retain a budgeted final narration set for free revisions

The owner approved the NASA script, chose OpenAI `nova`, and set a $0.02 ceiling for new narration API work only. The standard service removes generated temporary speech after rendering, which would force a new paid request for each edit. Use `scripts/prepare_narration.py` to keep each validated scene MP3 under ignored `outputs/`, bind it to the exact script and voice, and write a cumulative request reserve before any new request. The reserve includes the editor's one explicit transient retry and is a planning guard, not a billing record. Complete scenes can be reused in `scripts/local_review.py` with the paid switch off. Keep video generation and upload outside this authorization; the final voice still needs playback review.

## 2026-10-05 — Balance speech before adding the music bed

The selected Yuna scratch speech was about 11 dB louder than the new `nova` file for the first NASA scene. Mixing both at the same 20% BGM setting made the new voice vulnerable to masking; normalizing the entire finished mix cannot change the speech/music ratio. Normalize each narration scene near -18 LUFS in the shared editor before BGM mixing, using temporary local WAVs and keeping the original audio files for reuse. Keep the final mix normalization as a separate output step. This is a measured level correction, not a substitute for listening to pronunciation, musical fit, and phrase timing.

## 2026-10-05 — Slow short scenes instead of restarting them

The final `nova` voice made five of the six NASA scene durations longer than their existing manual animations. The shared editor looped short clips, visibly resetting both a diagram and its progress bar before the scene ended. Stretch silent scene playback to the narration duration instead, preserving each clip's visual arc without new generation cost. This is a modest slowdown for the current pilot; more extreme mismatches still need human review and a better storyboard.

## 2026-10-05 — Hold the final frame without retiming reveals

The slowed NASA cut fixed the restart but delayed the scene 5 highlight until after the narration had named the other rover. Supersede the slowdown choice above: play short silent clips at their original speed, then freeze the last frame to match narration length. This keeps authored reveals aligned with speech and avoids another visual generation call. Long holds still need editorial review and, if distracting, a revised storyboard.

## 2026-10-05 — Rebuild the manual storyboard for the final voice

The final-frame policy is a safe fallback for arbitrary short clips, but the NASA pilot has local storyboard source and five 0.88–1.72-second holds after switching from scratch Yuna to `nova`. Track a small NASA-specific renderer that times the six diagrams to the retained narration lengths, keeping the right-rover cue at the second phrase rather than scaling its time with the scene duration. Render locally and reuse the same speech, music, and captions. This removes avoidable static tails without another provider call; it does not certify that the full cut is engaging by ear or in motion.

## 2026-10-05 — Bind retained narration to its scene text before editing

The retained narration manifest records both the approved scene text and each completed audio file's hash, but local re-renders previously checked only the number and playable length of prepared files. Check the existing manifest in the shared production path when it is present, before visual work, so a renamed or replaced file cannot silently voice a different claim under the approved captions. Keep manifest-free scratch audio usable for local comparisons; reviewers must check its alignment themselves. This verifies text/file identity, not pronunciation or the truth of the source article.

## 2026-10-07 — Count editorial cuts without contaminating paired experiments

The NASA pilot now uses source-grounded manual storyboard clips, but the scorecard summarized only image/hybrid pairs. Report manual-clip re-cuts separately, using the existing private review CSV and sidecar flag. Count cost and acceptance only for rows with both a human verdict and an allocated bill; include rejected drafts in cost per accepted editorial cut. Keep paired image/hybrid results and their matched seven-day outcomes unchanged. Draft count is not a count of independent topics, and missing bills remain missing rather than zero.

## 2026-10-07 — Apply the visual cap to direct generator calls

The standalone generation test invokes `VideoGenerator` without `ProductionService`, so enabling paid production previously allowed it to bypass the service's visual-output cap. Check the full direct batch before launching any scene and check single-scene calls as well, reserving configured Veo attempts. Direct generation has no service cache, so count every requested scene. Keep the service's cache-aware preflight and the default-off paid switch; neither estimate includes provider input charges or guarantees the final bill.

## 2026-10-07 — Test story interest with a second topic at zero API cost

The owner found the NASA final voice, music, captions, and visual pacing suitable but could not isolate the story's appeal from its subject. Build a private CW-Net draft from the primary paper's cyclist case with original concept diagrams and local scratch voice, reusing the documented music only provisionally. Keep its script and music unapproved, label the different voices in the comparison, and avoid treating this as a controlled A/B result. Delay final paid voice, generated visuals, and publication until editorial review and a separate spending ceiling are agreed.

## 2026-10-07 — Compare story topics with the existing shared scratch voice

The first topic page paired NASA `nova` with CW-Net Yuna, so voice quality could influence a story judgment. Add the already-rendered NASA Yuna cut as the main comparator and keep `nova` as the owner's final-voice reference. This costs no new media work and reduces one confound, while different scripts, lengths, and visuals still prevent a controlled A/B claim.

## 2026-10-07 — Normalize documented music before the volume setting

The three documented tracks differ by 12.7 LU over their first 37.5 seconds, so applying the same 20% volume directly makes a track swap unexpectedly loud or quiet. Normalize a temporary copy toward -14 LUFS with a -2 dB true-peak ceiling, then apply the existing mix volume; preserve the licensed MP3 and its hash. Keep the already-reviewed NASA cut unchanged and compare its new local mix by ear before choosing a replacement. Level matching makes options comparable but cannot judge whether a track fits the story or masks an individual word.

## 2026-10-07 — Describe the cyclist signal without inventing the driver's thought

The CW-Net paper reports a BIKE concept below 1% in the first cyclist tests and later more cautious self-driving engagement, but its case narrative does not quote the safety driver's precise initial belief. Replace the draft's attributed thought with the observed stop and low explanation signal. Keep the separate perception/planner and backup-braking reveal, align the numeric graphic with its spoken phrase, and retain the earlier shared scratch cut only for old links. This is a source-accuracy correction, not owner approval of the new story.

## 2026-10-07 — Lead the wind-tunnel draft with the measured turn

The paper's laboratory result is that the power-maximizing tip-speed ratio changes with yaw angle; the wind-farm benefit comes from a separate uncertain model case study. Put the measured turn immediately after the opening question, then show how the tunnel test produced it. Describe combined yaw and rotor control as an opportunity, and reserve farm gains for a clearly labeled modeled prospect. Keep this as a text-only candidate until the owner chooses the story direction.

## 2026-10-07 — Preserve measured versus modeled evidence in automatic scripts

The automated story prompt already requires a source-backed question, early result, causal steps, and limit, but it did not name the distinction exposed by the wind-tunnel paper: a measured laboratory result versus a modeled wind-farm gain. State that distinction in the existing generation and source-validation prompts, and repeat it in the editorial recipe. Keep the same planning and validation calls; prompt tests verify the instructions are sent, not that a live model always follows them.
