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

## 2026-10-07 — Treat model analysis as story ideas, not primary evidence

The script writer called a previous LLM analysis `PRIORITY` even though the validator checks factual claims against the source article or RSS excerpt, and the web-search snippets were already leads only. Relabel that analysis as unverified story ideas and explicitly require the article text to support its claims. Keep the analysis for useful hook and structure suggestions without making another call. The offline prompt test exercises both analysis and search-snippet branches; this reduces a conflicting instruction, but does not prove a future model will ignore every unsupported suggestion.

## 2026-10-08 — Match generation evidence to the validator's excerpt

For long articles, `_write_script` could see 8,000 characters while `ScriptValidator` only checked the first 5,000 after trimming whitespace. Use the same 5,000-character excerpt in the shared writer for both direct-URL and RSS paths; retain the longer source in planning context for later editorial use. This avoids writing claims the validator cannot inspect and shortens the generation prompt without adding an API call. A prompt test verifies the boundary; it does not measure provider savings or replace factual review.

## 2026-10-08 — Reject empty evidence at model request boundaries

The normal planner rejected an empty source before approving a script, but its writer could still request a paid draft and the validator's public entry point could skip source grounding entirely when called directly. Reject a blank excerpt in both entry points before their completion requests. Let the planner continue to the next RSS candidate and let direct regeneration return no script. This saves avoidable calls and keeps source checking fail-closed; it does not prove that a nonempty source supports every generated claim.

## 2026-10-08 — Audition a third story without buying media

The NASA voice, music, captions, and visual pacing received positive feedback, while story interest remained topic-dependent. A CW-Net audition alone gives only one contrasting subject. Advance the source-checked wind-tunnel draft from text-only to a local scratch cut with original diagrams, the same Yuna voice and temporary normalized music mix as the NASA/CW-Net story cuts. Reveal the measured yaw-dependent result with its spoken caption and keep the wind-farm gain visibly labeled as a model forecast. This reverses the earlier text-only hold for a zero-provider-cost audition, not approval of the draft, music fit, or any paid production. The three subjects and visual treatments still differ, so their review is exploratory rather than a controlled A/B experiment.

## 2026-10-08 — Pause scheduled spending after a provider limit

A provider `429` or `RESOURCE_EXHAUSTED` error can mean quota pressure or temporary shared-capacity exhaustion, so the response alone does not justify another unattended paid attempt. Disable only the failing repeating schedule and mark it `provider_limit` whether the pipeline returns or raises that error. Preserve a sanitized limit marker when script planning fails, because its former generic error hid the cause from the scheduler; clear that marker before the next planning run. Let the owner inspect provider usage and the failed run before re-enabling it. Keep other transient failures on their existing schedule policy; this limits repeated cross-run spend, not in-flight retries or actual provider charges.

## 2026-10-08 — Stop a planning round on OpenAI rate limits

Topic-scoring fallback, optional article analysis, enrichment summarization, and source validation previously swallowed OpenAI `RateLimitError` and let the same run continue to another paid call or candidate. Propagate that SDK exception through all four stages so the production service can stop the round and the scheduler can pause a repeating run. Recognize its HTTP 429 status even when the message lacks the number, and expose only a generic limit marker. Preserve the existing fallback for malformed responses and other local failures; this change does not classify every provider error or replace bill reconciliation.

## 2026-10-09 — Bound standalone character-video cost

The standalone character-video helper omitted `generate_audio` and skipped the shared visual-output cap, although the character compositor discards clip audio. Request a silent 720p Veo clip explicitly and use the existing model/duration estimate before its one generation request. Reject unsupported durations and unknown-price models before the call. This protects one helper invocation, not cumulative spending or provider-side charges.

## 2026-10-09 — Do not retry Veo after a provider limit

The Veo helper allowed explicit extra attempts for transient server errors but also retried `429` and `RESOURCE_EXHAUSTED` after 30 seconds. Stop immediately on either limit, including an exception whose HTTP status is 429 but whose message omits the number, and return a sanitized marker that lets the existing scheduler pause. Keep explicitly budgeted retries for other server failures and safety-prompt fallback. A submitted operation may still finish or be billed after a polling error; this only prevents another request from this helper.

## 2026-10-09 — Require concrete stakes before another story audition

The owner found none of the NASA, CW-Net, and wind-tunnel topics compelling in the shared-voice comparison. This overturns the desk hypothesis that CW-Net's causal reversal was enough to carry the episode; it does not retract the favorable NASA voice, music, caption, or pacing feedback. Stop comparing those three as potential winners. The automatic title scorer formerly favored niche mechanisms and surprise without an ordinary viewer's stake; ask it to score concrete consequences, a source-supported turn, and a payoff conservatively when the title gives too little evidence. Treat that prompt as a filter, not a measured engagement model. Start one story draft about the 2024 Alaska Airlines door-plug investigation, whose NTSB news release and case page link missing bolts, undocumented factory work, missed inspection, the in-flight separation, and safe return. The current automatic validator checks only one extracted article, so manually verify claims from both pages before any media work. Keep it unapproved and spend nothing on voice, visuals, or upload until its story is assessed; do not imply that a more dramatic subject guarantees audience interest.

## 2026-10-09 — Let topic discovery abstain instead of forcing a cut

The owner described the source themes as personally uninteresting and said they also watch architecture, economics, and everyday topics. That is useful editorial feedback, not audience-performance evidence or a request to lock the channel to those three categories. The recent four auditions were manually chosen from research, technology, and safety stories, so they do not establish that every configured RSS feed is unsuitable. In RSS mode, let the title scorer select no candidate when the pool has no clear story; stop before extraction and script drafting if it does. Empty or malformed scoring output also stops rather than picking a random article. A direct URL still works. This saves downstream paid work when the current pool is weak, but the scoring request itself may have a cost when paid production is enabled. Keep a lightweight cross-topic source preview before making another full local cut; use future audience retention and viewed-versus-swiped observations to test appeal rather than assuming the owner's taste predicts it.

## 2026-10-09 — Match soft caption color to a light storyboard

The shared white `soft` caption reads as hollow dark outlines on the Sillim depot's cream diagrams. Expose the editor's existing `subtitle_color` through `scripts/local_review.py`, leave the NASA/default white treatment intact, and use dark ink for this light storyboard. Record the color in the local production sidecar. Re-render every Sillim music comparator with the same dark captions so the music-only comparison still has identical video streams; judge final legibility in playback rather than assuming a sampled frame proves it.

## 2026-10-09 — Remove unused narration settings before model migration

`Settings.tts_model` and `Settings.default_voice` were never read by the editor or retained-narration preflight. Changing them could falsely appear to switch providers or voices while calls still used `VideoEditor.TTS_MODEL` and the editor's `tts_voice` option. Remove the dead fields and keep the current model identity in one place until a replacement has a verified voice, token-based spending guard, and local review result. This does not migrate the deprecated model or authorize another paid narration set.

## 2026-10-10 — Reveal the Sillim question and second role with narration

The local story held some central diagrams for several seconds, but motion for its own sake would add no explanation. Two premature reveals were concrete: the opening diagram wrote its question before the question caption, and the concluding diagram showed the flood-response role before the transport-first phrase. Delay only those elements to the matching Yuna scratch narration beats; retain the remaining concept diagrams, music mixes, and dark soft captions. Re-render every music candidate from the same updated scene clips so the comparison stays music-only. A final voice will need its own timing pass because its duration and phrasing can differ.

## 2026-10-10 — Carry RnB 2 forward for the Sillim edit

The owner preferred Arulo's “RnB 2” if choosing among the Sillim music comparisons. Carry its documented local MP3 and provisional normalized 20% mix into the next Sillim review. This is a choice among the heard tracks, not approval of the complete video or proof that it fits a final voice. Recheck speech masking after final narration, and do not turn this story-specific preference into an automatic mapping for every `curious` script.

## 2026-10-10 — Reuse the Sillim storyboard under one approved final voice

The owner approved the exact five-scene script and a $0.02 ceiling for one `nova` narration set. Retain the five generated MP3s with the script-bound manifest. Their request reserve, including the configured possible retry, is $0.00771; leave the actual bill unknown until provider reconciliation. The final voice changes scene lengths by at most about 0.2 seconds from the Yuna audition, so reuse four existing diagrams. The opening question was visibly early against the final caption; redraw only that scene with the cue at 5.7 seconds. Keep the RnB 2 level provisional until listening to the final mix, and require a whole-video editorial verdict before publication.

## 2026-10-10 — Count Veo outputs explicitly and keep aspect ratio out of prompt prose

The approved $0.15 Sillim visual pilot reserved one $0.12 four-second silent Veo 3.1 Lite output. Its single generated clip had a large literal `9:16` and invented text on the bus, so it failed the generic unlettered visual gate and was not spliced into the final-voice cut. The generation wrapper had spelled out `9:16` even though the API configuration already set the aspect ratio. Remove that literal from future prompt prose and set `number_of_videos=1` explicitly so the request matches the one-output cost reserve. The literal phrase may have contributed to the artifact, but this is unproven; no second paid request was made to test the revised prompt. Keep the rejected request in later production-cost accounting, with actual billing still pending.

## 2026-10-10 — Compare explanatory opening motion without another paid generation

The rejected Veo result left the approved Sillim script and existing `nova` cut unchanged. Animate only the original diagram's bus entrance over its first 1.6 seconds, before the 2.3-second reservoir text and 5.7-second question cues; this depicts a generic bus, not a claimed observation at the real depot. Render a private alternative with the retained speech, RnB 2 music, soft captions, and byte-identical scenes 2–5. The two final MP4s have the same encoded audio stream, so playback can isolate the opening motion. The owner later preferred the animated opening, so carry that cut as the next review candidate. This component preference did not establish whole-video quality; the later full-cut verdict below supersedes it as a publication candidate. Keep the rejected Veo request in eventual cost accounting.

## 2026-10-10 — Stage a Veo-led Sillim cut after the whole-video verdict

The owner preferred the local bus motion but found the full diagram cut insufficient for a final Short; the final target is an edit built from Veo footage. Mark the local animated cut rejected for publication while retaining it as the timing and sound reference. Plan one source-safe moving shot per scene, with exact floors, numbers, arrows, and attribution added locally so generated text or fabricated architecture cannot become evidence. Try one 8-second opening first and inspect it before committing to four further shots; keep every rejected attempt in cost accounting. The previous $0.15 visual round was consumed, so neither this plan nor the opening preference authorizes another paid request. See [SILLIM_VEO_CUT_PLAN.md](SILLIM_VEO_CUT_PLAN.md) for shot briefs and current list-price estimates.

## 2026-10-10 — Record each Veo request before sending it

The second Sillim visual test ended in a provider code 13 error before any MP4 was rendered, so its cost cannot appear in a rendered-video sidecar or review CSV. At the shared `VideoGenerator` request boundary, write one ignored local record per app attempt before calling Google, then update it on success, error, or timeout. Keep model, requested seconds, one-output estimate, status, and provider operation/error identifier when supplied, but omit prompt text and leave actual billed cost null. If the initial record cannot be written, do not submit the paid request. This also records each explicitly budgeted retry separately. It does not determine Google billing, cover older direct requests or standalone character-video calls, or replace cost allocation to accepted videos.

## 2026-10-10 — Pause a recurring run after an unverified Veo operation

The Sillim code 13 operation completed without a video, and the prior scheduler policy would treat that as an ordinary failure and repeat the paid pipeline at its next time. After all explicitly reserved attempts, mark a submitted Veo operation that yields no verified file or times out as `VEO_RESULT_UNVERIFIED`. Pause only the affected repeating schedule and require the owner to inspect its request record and provider bill before re-enabling it. This narrows the earlier choice to leave transient failures scheduled: a pre-submission `503` still follows that policy. It cannot establish the actual charge or stop provider work already in flight.

## 2026-10-10 — Prepare a source-safe first frame before another Sillim Veo attempt

The four-second text-to-video clip invented prominent writing and the later eight-second request returned no file, so neither established a usable visual style. Google supports an image first frame for Veo 3.1 Lite and advises motion-only prompting for that mode. Retain one unlettered, visibly fictional depot miniature as a reviewable candidate for the next single-shot pilot. Exact factual labels remain local overlays. This is an experiment, not a generic image-to-video pipeline or another paid request: only a reviewed output can show whether the first frame reduces artifacts and improves the Short. Keep the earlier attempts in cost accounting and require a new ceiling after billing reconciliation.

## 2026-10-10 — Typeset source facts during local review

Veo's rejected opening put unwanted writing inside generated footage, while the Sillim cut still needs an explanatory label and attributed numbers. Let the local review command pass explicitly timed, positioned text cues to the existing editor layer stack, below subtitles, and record those cues in the private production sidecar. Keep the cues out of generation prompts and require the editor to inspect their factual wording and placement against each accepted raw shot. The first static opening test verifies only that this path renders without new provider spend; it cannot settle moving-footage clearance or the complete five-scene design.

## 2026-10-10 — Reuse the Veo request gate for a first-frame pilot

The tracked Sillim opening image could not pass through the existing text-only Veo request, and calling that low-level method directly could bypass the visual cost preflight. Add an optional local first-frame image at the shared request boundary and reserve every explicitly requested attempt against the current visual cap before submission. Validate file format, portrait shape, input size, and supported duration; send the image bytes only in the provider request, while recording its SHA-256 and input type in the private attempt log. Keep the normal automatic scene path text-only until a paid image-to-video pilot produces an acceptable raw shot. Offline SDK-shape and mock tests establish the request form, not Google acceptance, actual billing, or style quality.

## 2026-10-10 — Require a ceiling on every low-level Veo request

The first-frame helper can be called directly while the paid switch is temporarily enabled; the configured per-video cap alone does not encode the owner's smaller authorization for a single pilot. Require a finite, nonnegative `request_budget_usd` at the shared Veo boundary and reject any output reserve for all requested attempts above it before submission. The regular scene path passes its existing configured cap, while direct pilots must pass their separately approved ceiling. Store the ceiling in each private attempt record without presenting it as an actual bill or cumulative account limit. This does not reuse an earlier authorization or constrain provider-side charges outside the listed output estimate.

## 2026-10-11 — Keep the selected Sillim miniature style and stage factual overlays

The owner chose the fictional depot miniature after reviewing its static first-scene placement. Carry that image as the candidate for one later image-to-video test; the preference does not establish moving-shot quality or authorize another paid call. Complete the source-grounded local cue sheet for all five scenes over blank proxy backgrounds, which exposes timing and caption collisions without duplicating the existing diagram text. Treat the positions as provisional until the cards are checked over each accepted Veo shot. Keep the approved speech and RnB 2 mix unchanged for this isolated layout check.

## 2026-10-12 — Reserve Google visual spend against an optional local monthly limit

The owner wants the program to control spending from the models it uses, starting with Google Cloud and a manually chosen won-per-USD conversion factor. Keep the existing per-video and per-request USD checks, then optionally add a monthly KRW check at each Google image or silent Veo request boundary. Price known models from the existing visual cost table and write one SQLite reservation before submission so parallel calls cannot both spend the same remaining balance. Use Cloud Billing's Pacific calendar month and a manually entered opening amount for usage before the ledger; require a new month and opening amount at rollover. Retain failed or interrupted requests in the reserve until billed cost can be reconciled, since a missing output does not prove a free request. Check the visual batch before new narration and pause a repeating schedule when its Google budget is exhausted. Do not silently downgrade an editorially required Veo shot to an image. This local estimate cannot enforce the account-wide Google budget, see other workloads or late charges, or price OpenAI work; keep it opt-in and initialize it only with a checked conservative opening amount and current model rates.

## 2026-10-12 — Fail closed when the local budget ledger is missing

Review found that automatically creating the SQLite ledger during a preflight or reservation could silently reset this month's local spend after `outputs/` cleanup. Create the ledger only with an explicit `--init` command after its opening amount is checked; normal budget checks and provider requests require the existing file and schema. If the file is lost, recover its reservations or include them in a new opening amount before reinitializing. Batch preflight reserves up to one extra won per additional request for independent ceiling rounding, and offline tests isolate mocked paid requests from any configured private ledger. This tightens the optional app-local gate but still cannot observe or enforce the actual Cloud Billing balance.

## 2026-10-12 — Stop on a completed Veo operation with resource-exhausted code 8

The approved Sillim image-to-video pilot reached a completed Google operation whose error code was 8 and whose message said the service was under high load. It returned no video. The Veo helper previously recognized 429 text or HTTP status, but a completed operation's canonical code 8 became a generic unverified-result error; with explicit extra attempts it could have retried. Treat code 8 as a provider limit, retain its budget reservation and private operation record, and stop without another generation call. A high-load message does not prove that the attempt was free or establish when capacity will return.

## 2026-10-13 — Reuse approved production assets in the full upload flow

The approved Sillim narration and local scene clips allow a bounded private test of editing, quality checks, and YouTube delivery without another planning, TTS, or Veo request. Let `ProductionService.full_pipeline` accept a reviewed script and prepared scene assets while preserving the existing topic/URL route. Reject conflicting new-topic input, keep the paid production switch off for this local run, and supply reviewed metadata because the historical script description still calls itself a draft. A private upload proves the delivery path only; it does not reverse the owner's rejection of the diagram cut as a public release candidate or establish Veo footage quality.

## 2026-10-13 — Keep Veo scene attempts single-use and adapt soft caption contrast by scene

The owner approved one five-scene Sillim Veo Lite review round with a $1.50 total output-estimate ceiling and no automatic retries. Run one scene at a time from the tracked shot brief, save a private request record before submission, and require an inspected clip hash before moving on. Keep raw clips even when a local crop or mask removes invented marks; those edits do not erase the cost or establish factual footage. The standard Fast/global-duration route does not represent this scene-specific Lite round. Mixed bright miniature and dark water shots also make a single subtitle color illegible, so let local review specify a validated color per scene while preserving the selected `soft` treatment. Record the chosen mapping in the production sidecar; do not change the default caption color for unrelated stories.

## 2026-10-13 — Require visible proof for each narrated relationship

The five Veo shots made the Sillim cut attractive, but owner playback found that their images did not explain the narration in enough detail. The main error was treating a prompt for decorative motion plus local noun labels as sufficient to depict a spatial or causal claim: scene 3 explicitly omitted a floor diagram, and the final edit never supplied one. Before another visual request, write one source-backed relationship that the viewer must see, specify the Veo component and the editor-owned graphic, and test the scene silently with captions hidden. Reuse the retained footage and voice for a local explanatory composite first; buy a replacement only for a scene that still fails. Exact text, numeric effects, and factual structure remain editor-controlled and source-attributed. See [the five-scene assessment](SILLIM_VISUAL_ALIGNMENT_REVIEW.md). This changes the editorial gate, not the closed Veo round or its cost record.

## 2026-10-13 — Carry visual proof into automatic script validation

The manual Sillim brief now demands a visible relationship, but the automatic writer still asked only for one narrated idea and a concrete shot, while its validator checked factual plausibility without asking whether the image explained a spatial or causal claim. Add that conditional requirement to the existing writer and validator prompts. Treat `missing_visual_proof` as a failed validation even if the model contradictorily returns `is_valid=true`, before buying visual output. Do not add a provider call or a new script field; the existing visual description must contain the proof, or the topic needs manual editorial planning. A stricter rejection can trigger the existing bounded RSS topic retry, so this is a cheaper-visual-spend gate rather than a guarantee of lower total planning cost. Offline prompt tests verify the request and fail-closed reason, not a live model's judgment or the generated image's explanatory quality.

## 2026-10-13 — Reject an unaffordable automatic visual round before paid script planning

The automatic writer requests at least six scenes, but the full pipeline previously bought OpenAI planning before discovering that even six configured visual outputs exceeded the visual cap or local Google monthly room. Check that minimum only for a new automatic full run, using the configured image or silent Veo model and explicit Veo attempt count. Pause a repeating schedule when either that minimum or the eventual exact script exceeds its visual cap. Keep the exact post-script visual preflight and per-request ledger reservation: a passing minimum is not a spending guarantee, and future cache hits cannot be predicted before the script exists. Standalone script planning and a supplied approved script with retained clips keep their existing paths.

## 2026-10-13 — Reject unsupported music moods instead of changing the story's tone

The automatic writer previously replaced every out-of-list mood with `energetic`. This could turn a quiet or curious explanation into an unrelated voice and stock-music choice, while the output looked valid to later stages. Treat an unsupported model mood as a planning error and stop before source validation, TTS, or visual generation. Propagate the specific failure through the full pipeline and pause a repeating schedule instead of repurchasing planning on its next run. A valid broad mood still does not prove that its first documented track fits the script; retain the exact-track listening gate for editorial acceptance.

## 2026-10-13 — Keep explanatory overlays small after full-cut playback

The owner found the source-checked Sillim diagram cards too large over otherwise attractive Veo footage. Preserve each narrated relationship with a compact editor-drawn inset only in scenes that need it, rather than leaving a full storyboard crop over most of the shot. The three replacement insets occupy under 12% of their scene frames; scene 5 needs only the existing small, attributed editor labels. Retain the original moving shots, narration, music, and subtitle treatment for a visual-only comparison. This is a local editorial choice, not a universal overlay-size rule; the full compact cut still needs owner review before acceptance or publication.

## 2026-10-14 — Make explanatory motion part of the generated shot

The owner reviewed the smaller Sillim diagram approach and directed future work toward footage that explains the narration by itself. Retire editor-drawn relationship diagrams as the planned repair for generated scenes. For an explanatory Veo shot, the brief and returned raw clip must show the narrated spatial or causal relationship without voice, captions, or graphics. Editor text may still supply exact words, numbers, and source attribution. This reverses the earlier Sillim plan to accept abstract scene 3 and supply its floor arrangement only in the edit; the compact cut remains a local comparison, not an accepted production format. Keep the existing source and cost gates, and request a new ceiling before any replacement generation.

## 2026-10-15 — Keep Studio estimates and manual mode aligned with production

The script preview's visual estimate uses the same scene-mode and model-price functions as the production preflight, assuming one new output per scene before cache or manual reuse. The label names that scope so it cannot be mistaken for a total bill. Mode and source selections update the active view immediately. After a manual edit, keep manual mode selected while showing its finished preview; silently returning to automatic generation would misstate what the next action can spend. This UI contract does not change provider pricing, local budget reservations, or the owner's editorial gate.

## 2026-10-18 — Bind reviewed factual labels to their exact scene clips

The first local cut with replacement Sillim scene 3 applied floor labels at positions reviewed for the older Veo shot, so those labels pointed above the new levels. An optional `_clip_sha256` map in a local cue sheet binds each labeled scene to its reviewed MP4. `scripts/local_review.py` checks all bindings before rendering and passes only cues to the editor and sidecar. Existing unbound sheets still load, while the tracked five-scene Sillim sheet and the ignored replacement override use bindings. A new shot requires a new placement review and hash, not just a changed filename; matching hashes cannot replace human playback or source checking.

## 2026-10-18 — Do not require an unsupported outlet in Sillim scene 4

The Seoul City release supports temporary storage in the B2 reservoir and attributes an approximately 10 cm river-level effect to the facility. It does not specify outlet geometry, discharge timing, or rate. The earlier visual brief required a smaller later outlet, which could add a false engineering claim and prompt an unnecessary paid replacement. Retire that requirement. Acceptable raw visual proof for scene 4 is water visibly accumulating within a bounded basin; leave the river-level result attributed in narration and editor text. Keep the existing Veo shot as a provisional candidate until owner playback confirms that the storage is readable. Revisit outlet depiction only with a primary engineering source.

## 2026-10-18 — Separate Sillim's two problems before revealing the shared-site answer

The Seoul City release identifies insufficient bus-depot space and Dorimcheon-area flood risk as two motivations for the project, but it does not establish that a cramped yard and the stream adjoin at the new site. The earlier scene-2 native-shot gate demanded both pressures on the same parcel, which could invent a geographic relationship and reveal the scene-3 solution before the narration. Depict two clearly separate fictional miniature problems in scene 2; use scene 3's stacked uses to explain how one facility addresses them. Require muted raw playback to show a full yard and rain risk without labels, flooding, or implied real-site geography. This is a source-boundary correction and candidate visual brief, not approval for a new Veo request.

## 2026-10-18 — Cut between separate Sillim problems instead of placing them together

The owner could distinguish the bus-space and stream-risk problems in the first scene-2 miniature, but the shared tabletop still looked like two adjacent real places. A disclaimer cannot repair that visual claim. Retire the combined first frame as a Veo input: show one fictional depot, then cut to one independent generic rain-and-stream shot when the narration changes subject. Keep both shots free of location markings and measured outcomes. Scene 3 alone reveals the shared-site solution. The owner also found a cut at the old 2.7-second overlay cue awkward; place the transition at the actual speech pause, not a guessed graphic cue. Review the two-shot order with retained narration before paying for motion, then judge each generated shot without labels. This changes the scene-2 visual brief, not the approved narration or previous request record.

## 2026-10-18 — Preserve a scene's motion proof in Veo safety retries

The automatic fallback prompt previously omitted `motion_instruction` after a safety rejection. That could buy a second visually polished clip without the narrated action, despite cost preflight. Keep the same visual description and motion clause in both prompts, simplifying only the surrounding language. A retry may still fail if the motion itself is rejected; do not silently replace the action with generic camera movement. The default remains one attempt, and any higher attempt count still needs its full budget reserve.

## 2026-10-18 — Reject unsourced geography in automatic visual plans

The Sillim scene-2 tabletop showed two independent problems clearly but implied that the bus yard and stream physically adjoin, which the cited source does not establish. The automatic writer must keep separate places visually separate or split the narration beat into scenes; the validator must judge spatial claims created by composition even when narration does not state them. Reuse `unsupported_visual` rather than adding a new result type. These prompt checks reduce an identified failure mode but cannot verify generated pixels, so the raw-shot and owner playback gates still apply.

## 2026-10-18 — Bind free scratch narration to its script

The unit-price paper audition used macOS Yuna without a provider call, but a sandboxed `say` run returned success while leaving unusable 4 KB files. A local scratch helper now decodes each temporary result before saving it and records scene text and file hashes in the same manifest shape the editor already verifies. A pending scene can resume; a changed script, altered completed audio, or untracked file stops the reuse path. This keeps zero-cost story auditions reproducible between agents without treating the Yuna voice as final narration or relaxing the paid TTS budget gate.

## 2026-10-19 — Require reviewed metadata for approved-script uploads

The October 13 approved-script path relied on its caller to supply reviewed upload metadata because the retained Sillim draft's description still says it is unapproved. `full_pipeline` previously fell back to that stale script description when the caller omitted `upload_metadata`. For `approved_script` with `auto_upload=True`, require an explicit nonblank title and description plus a boolean AI disclosure choice before rendering; a missing field now fails before any potential paid work. Ordinary automatic script uploads keep their existing metadata defaults and private visibility. This checks that a choice was made, not whether the words, credits, or disclosure are editorially correct; review the final video and metadata before publication.

## 2026-10-20 — Make sustainable publishing an explicit product goal

The no-code-repair prerequisite in this historical entry is superseded by the 2026-10-31 operating-and-improvement decision below.

The owner wants ShortsMaker to support ongoing video uploads, in addition to improving the quality of a single pilot. Treat success as a repeatable, affordable sequence of source selection, reviewed production, private delivery, separately approved public release, and measured results. Demonstrate it across multiple accepted episodes without code repair between runs before claiming the workflow is sustainable. Keep spending and source/rights/editorial gates in place; a scheduled job or technically successful upload is not evidence that viewers will value the result. This goal does not authorize a new paid request, activate a schedule, or change any video's visibility.

## 2026-10-20 — Summarize accepted editorial outcomes before bills arrive

The original scorecard tracked seven-day audience outcomes only for matched image/hybrid experiments. The production path now being reviewed uses manual Veo clips and is deliberately excluded from those pairs, so its published results would disappear from the summary. Add a separate editorial outcome aggregate for accepted, quality-passed cuts with an upload ID and complete views/duration observations. Keep cost review independent so a delayed provider bill does not hide observed retention; leave revenue blank when any included video lacks it. An upload ID does not establish public release, so the private CSV operator must enter metrics only after verifying visibility and the common seven-day window. This does not grant analytics scopes or publish a video.

## 2026-10-20 — Fail visibly when a repeating job cannot be registered

An enabled schedule whose APScheduler job never registered could look like a working upload cadence. Surface backend and registration failures at scheduler startup, stop startup if a saved job cannot be registered, and disable a newly created or edited live schedule when its registration fails. Preserve the saved schedule for operator repair instead of silently claiming it will run. A deliberately disabled schedule must not register. This does not enable paid production or create a publishing schedule.

## 2026-10-20 — Pause a repeating run that left a rendered video after failure

A scheduled private upload or final quality check can fail after planning, narration, visuals, and editing have already produced a file. Repeating the entire pipeline at the next trigger would spend again and leave the recoverable video unreviewed. When a failed result includes a rendered video path, disable that schedule, remove its live job, and expose the path in the local log. The operator can inspect the retained file and decide whether to retry its upload or repair the video before re-enabling production. A failure before any video exists retains the existing provider-specific pause behavior; this rule does not infer actual billable cost from the file path.

## 2026-10-20 — Require confirmed public release for outcome summaries

The upload API always creates private review copies. An upload ID plus manually entered seven-day metrics could therefore be misread as public audience evidence. Add an explicit `public_release_confirmed` field to the ignored review CSV and require `yes` for paired and editorial outcome summaries. Preserve existing review and cost entries when adding the field to an older CSV. The operator sets it only after the separate publication decision and a visibility check in YouTube; the current upload-only OAuth scope cannot verify visibility automatically. This gate does not infer seven-day completeness from a timestamp or approve publication.

## 2026-10-20 — Treat a scheduled direct URL as one episode

A fixed article URL is not a recurring topic feed. The direct planner writes URL history after a valid script but deliberately lets a user request the same URL again; an enabled daily schedule could therefore buy the same script, narration, and visuals repeatedly. Keep manual direct-URL planning available, but pause its schedule after a rendered result and retain the URL. A later trigger or manual re-enable with that same URL must stop before any paid work, including for older schedules whose last result was already successful. A newly entered URL can be used for a new episode; RSS discovery remains the repeating source path. Reject empty and disallowed direct URLs at schedule save time so an empty URL cannot silently become RSS discovery. This does not activate or authorize a schedule.

## 2026-10-20 — Require extracted article text for automatic RSS scripts

The earlier source gate accepted an RSS summary when full-article extraction failed. Feed collection admits summaries as short as 200 characters, so an automatic run could pay to write and validate a six-scene story against only a teaser. Align RSS with the existing direct-URL minimum of 100 extracted article words. Remove a missing or short article from the current candidate pool before paid analysis or script writing, then try another selected candidate within the existing retry limit. The feed summary remains useful for topic scoring, not factual grounding of a completed script. This favors sourced quality and avoids some wasted writing calls but can reduce output from inaccessible publishers; it does not certify that a sufficiently long article is accurate or interesting.

## 2026-10-20 — Add verified official city feeds to the recurring source pool

The owner's interests include architecture, economics, and everyday life, while the prior default pool had no city-life category. A bounded live check of two feeds in each old category found mixed availability; some feeds worked, but others failed to provide an eligible article in this environment. Seoul City's [official RSS directory](https://mediahub.seoul.go.kr/staticpage/rss.do) supplies housing, transport, and economy feeds. On this date each returned 20 entries and three sampled article bodies per feed exceeded the planner's 100-word threshold; the live 14-day filter found 1, 4, and 18 eligible entries respectively. Add housing and transport under `City_Life` and economy under `Finance_Economy`, including this workspace's saved ignored source file. Keep other saved sources rather than deleting them from a small diagnostic sample. Enforce the existing five-candidate category cap before fetching an additional feed so an expanded pool does not silently raise the title-scoring batch. Source availability is not story appeal, and these articles still need claim, visual-rights, and editorial review before publication.

## 2026-10-20 — Evaluate topic leads with bounded context and one valid selection

The automatic RSS scorer only saw headlines even though the collector retained summaries, so a vague headline could hide a concrete consequence or a visual relationship. Send a short, HTML-stripped feed excerpt alongside each title, cap both fields, and ask whether source-checkable footage could explain the key relationship. Treat feed text as unverified leads and never as instructions or final evidence; the existing 100-word extracted-body gate still decides whether writing may proceed. Remove duplicate and disallowed article URLs before paid scoring. Require exactly one score record per candidate with unique indices, valid scores and booleans, and at most one selected topic; malformed or ambiguous responses stop the round rather than silently selecting the first entry. This can increase scorer input tokens and make malformed responses abort more often. It does not measure audience appeal or verify that generated footage conveys the relationship; those still need editorial review and later audience outcomes.

## 2026-10-20 — Treat the RSS score as a shortlist, not a production verdict

Two bounded live GPT-4o mini calls on the same ten official Seoul RSS leads exposed a calibration problem. The first selected a night-market visit report at 9/10 and copied the prompt's high-score example into its reason. Remove filled high-score examples and tell the scorer to rate promotional visits, event guides, discounts, and openings conservatively without a separate observed outcome. The second call lowered that article to 5/10, but selected an autonomous night-bus launch notice at 8/10 with a speculative impact reason; its night service was still scheduled for October 22. Both full articles cleared the 100-word extraction gate. Therefore neither scoring nor article length establishes a completed explanatory story. Keep the score as a shortlist for source review and do not use this test as approval for a script, visual call, or unattended publishing. A source-body story-fit gate remains needed before higher-cost production.

## 2026-10-20 — Check RSS story fit in the existing article analysis call

The live shortlist test showed that a long article can still be a future service announcement with no established result. Reuse the existing full-article analysis call to request a strict story-fit verdict and one exact, substantive source sentence. In automatic RSS mode, reject a negative verdict or a short/mismatched quote before enrichment or script writing, remove that candidate, and use the bounded topic retry. A missing or malformed analysis stops the round rather than spending on another selection after a provider failure; propagate that distinct failure through the service so a repeating schedule pauses as `analysis_failed` before its next paid trigger. Keep direct-URL planning as a manual topic choice with its existing source and script-validation gates. This adds no API stage and can save later calls, but lengthens the analysis prompt and can reject good articles when the model miscopies evidence. Offline contract tests cannot prove the model will classify future announcements reliably; calibrate on live articles before unattended production.

## 2026-10-20 — Cap article-analysis output before paid calibration

The existing GPT-4o article analysis had no output-token limit, so a malformed or verbose answer could spend beyond a small calibration round. Set `max_completion_tokens=1500` on its single Chat Completions request; a length-truncated or invalid JSON result still fails closed in RSS mode. This bounds output tokens, not input tokens or the provider's dollar bill. For each live calibration, inspect the exact extracted article and prompt size, verify current model pricing, and reserve a conservative per-request amount before submission. Keep source bodies and any provider response in ignored `outputs/`, not Git.

## 2026-10-20 — Pause recurring work after invalid topic scoring

The RSS scorer already validates one result per candidate but returned an empty list when the paid request failed or its JSON was malformed. That was indistinguishable from a legitimate decision to select no article, so a repeating schedule remained enabled and could pay to retry at its next trigger. Raise a distinct `TOPIC_SCORING_UNVERIFIED` error, preserve it through `ProductionService`, and pause the schedule as `scoring_failed`. Keep a valid all-unselected response as an ordinary no-story run. Cap scorer output at 2,000 tokens and reject a length-truncated response even if its JSON happens to parse; this is not a dollar cap and does not limit input tokens or actual provider billing.

## 2026-10-20 — Separate rejected stories from planning errors in schedules

A script validator that cannot complete returns `validation_error` for fail-closed safety. The RSS planner previously treated that operational error as a rejected article and could spend on another candidate, while script-writing exceptions became a generic script failure that left the repeating job enabled. Stop candidate retries when validation is unavailable, mark uncategorized planning exceptions as `PLANNING_UNVERIFIED`, and pause repeating schedules as `planning_failed`. Keep actual invalid-script verdicts and valid no-story selections as content outcomes, so later source discoveries remain possible. This protects the local cost path but requires an operator to inspect and re-enable a failed schedule.

## 2026-10-21 — Keep the article-fit gate, but require later claim review

The first bounded live GPT-4o check classified an October 22 service announcement as unsuitable before its start date and a completed bus depot as suitable with a sentence copied from the source. The current RSS planner rejected the first before writing and passed the second to a mocked writer. This supports the gate's direction on these two articles only. The positive analysis also described intended flood and transport benefits in outcome language, although the source establishes the finished facility and states some benefits as city estimates or expectations. Keep the analysis as a story lead, not evidence; the writer and validator must ground each narrated effect in the source and preserve attribution and tense. Do not enable unattended production or approve visuals from this two-case result. The two approved one-shot calls are exhausted, and actual OpenAI billing remains unverified.

## 2026-10-21 — Bound writing and review responses; omit speculative payoff text

The Sillim article-fit analysis correctly selected a completed facility but described expected flood and transport benefits as achieved in its suggested impact. Do not pass its `future_impact` or story-structure impact fields to the writer. Keep the earlier analysis as hook and mechanism ideas while the primary excerpt supplies payoff facts; prompt the writer and validator to distinguish completed construction from measured benefits and city estimates. Cap the existing GPT-4o writer response at 4,000 output tokens and validator response at 1,500, reject length-truncated outputs, and require a real JSON boolean for the validator's `is_valid`. When Brave enrichment is configured, cap its GPT-4o mini search query at 128 output tokens and snippet summary at 1,000, and bound the five snippets sent to the summarizer. A truncated query stops planning; a truncated optional summary contributes no source facts or extra request. These are per-call token bounds and fail-closed checks, not a dollar budget or proof that the next model-written script will be accurate. The existing no-retry clients and paused-schedule behavior handle operational failures without an automatic paid repeat.

## 2026-10-21 — Pause repeating work after an unclassified failure

The scheduler already paused for named provider, budget, planning, and rendered-video failures, but a returned generic error such as a 503 or an unexpected exception left the job enabled. A later trigger could repeat paid planning or visual work without knowing which requests completed. Pause every failed result except the explicit ordinary no-story result, and pause every unexpected exception while recording its run count. Keep the detailed exception in local logs and store only a generic status in the schedule file. The next source window may still retry a no-story outcome; that remains a separate potential OpenAI planning cost, not a proof of new article availability. This favors review and cost containment after uncertain work over automatic recovery from a transient error.

## 2026-10-21 — Remember decided RSS leads across runs

The URL history previously recorded only accepted scripts, so a valid no-selection verdict or a rejected article could incur the same topic-scoring or article-analysis cost on the next daily run. Record URLs after a definite scoring rejection, insufficient extracted body, negative story-fit verdict, or invalid-script verdict; keep the existing accepted-script record. Never record a lead after an uncertain provider or validation error. Retain the latest 500 distinct URLs to span normal feed recency, write the ignored history atomically, and stop before paid scoring if that history is corrupt rather than silently resetting it. This reduces repeated evaluation, but a mistaken editorial rejection can hide a good RSS lead until it ages out of the history; the direct-URL route remains available for deliberate review.

## 2026-10-21 — Preview the actual RSS pool before buying topic scores

The current city and economy feeds yielded mostly event, discount, and upcoming-service leads on two free checks. Expose exactly the planner's five-per-category discovery pool in an ignored HTML page so an editor can inspect original links before paying for scoring or choosing a direct URL. Reuse the existing collector; do not add another ranking heuristic or claim that a title is a source-verified story. A zero-candidate page must mention possible feed failure because the collector currently logs and skips broken feeds. Keep the automatic scheduler disabled while the scorer and source pool remain uncalibrated for unattended quality. This is an editorial cost gate, not proof of an accepted episode or a replacement for the full-article validator.

## 2026-10-21 — Treat total RSS failure as a planning error

The preview exposed that the collector silently returned no candidates when every feed failed, which let a recurring job record an ordinary no-story result. Require at least one successfully read RSS feed and reject HTTP 200 bodies with no feed format. With zero configured sources or all failed/invalid feeds, raise `RSS_SOURCE_UNVERIFIED`; the existing production error boundary wraps this as `PLANNING_UNVERIFIED`, so the scheduler pauses instead of waiting for the next run. A valid empty feed still permits an ordinary no-story result, and partial feed failures still produce a candidate pool with warnings. Do not mark article URLs reviewed after a total source failure. The preview command now exits without writing a fresh page in that case; a previously saved page may remain and must be read with its timestamp.

## 2026-10-21 — Replace a dead life-tips feed with an official civic source

The configured `Life_Tips` pair yielded no candidates: one URL returned HTTP 404 and the other feed's recent deal snippets missed the 200-character lead threshold. The [Interior Ministry's official RSS directory](https://mois.go.kr/frt/sub/a08/rss/screen.do) lists a press-release feed that returned recent full summaries; two linked original articles cleared the existing 100-word body gate. Replace the dead default and local URL with that feed, keeping the existing five-candidate category cap and all later paid/source gates. This does not make a press release unbiased or interesting: a free five-item sample still contained mostly meetings and planned events. The linked HTML pages have specific document titles, but trafilatura extracted `보도자료`; use the page title's first segment only for this observed generic-title case so both RSS and direct-URL analysis get the actual subject while the article body remains factual evidence. Other generic-title patterns are not inferred without evidence. Do not treat the extra source as permission to start a paid run or recurring schedule.

## 2026-10-21 — Let editorial review see beyond the paid RSS sample

The new official feed contained 21 recent eligible leads, but the existing randomized five-item `Life_Tips` preview was mostly meetings and promotional items and hid a completed administrative change. Keep the five-per-category cap for the paid scorer and scheduled pipeline. Add an explicit free inventory view that reuses the collector with only that cap removed; preserve URL, recency, history, and summary-length filters, and show feed dates so the editor can open a promising original article. The first live inventory exposed both a completed document-simplification story and a flood-damage release whose own rainfall caveat prevents a simple causal claim. More visible leads do not establish story appeal, source accuracy, rights, or a publishable video; direct-URL planning and later review gates still decide that.

## 2026-10-21 — Match automatic scene count to the accepted short story

The approved Sillim pilot tells its complete question, pressure, layout, mechanism, and attributed limit in five scenes, while the automatic writer demanded six to eight and the preflight reserved at least six visuals. Allow five to seven generated scenes, discourage a scene that merely repeats a fact, and ask for calm direct spoken Korean rather than a press-release list. Enforce the generated count after parsing so the minimum visual preflight matches a real output constraint; manual approved scripts keep their existing flexible scene count. This may save a visual output when five scenes suffice and avoid padded beats, but it does not prove a model-written five-scene story is engaging. Exact post-script visual and narration gates still apply, and no new provider call is justified by the prompt change.

## 2026-10-21 — Treat contradictory script validation as unverified

The editorial validator accepted `is_valid=true` with an unrecognized negative reason, and `is_valid=false` with no reason was treated as a definite script rejection. Either response can misclassify an unsupported claim or permanently mark a good RSS lead as reviewed. Keep known failure reasons as rejection, but treat unknown success reasons and reasonless rejection as `validation_error`; the existing planner and scheduler then stop instead of saving a decision about the article. Explicitly ask for an empty reason on a valid response. A strict result contract can pause a run after an otherwise usable script, so the operator must inspect it before re-enabling production. No extra validation request or retry is added.

## 2026-10-21 — Require a dated RSS lead before automatic scoring

The RSS recency check previously treated missing and invalid dates as recent, admitted future dates, and converted feedparser's UTC tuple through the local timezone. Require a valid publication date no more than 14 days old in UTC before either preview or paid scoring. This can hide useful articles from feeds that omit `pubDate`; the manual direct-URL path remains available after source review. A live feed refresh should measure the candidate-count change when network access returns. Do not spend on an undated lead merely because its feed presents it near the top.

## 2026-10-21 — Keep free RSS previews reproducible within a day

The bounded free preview and paid discovery used independent random shuffles, so looking at the preview did not identify the later scorer's actual five leads per category, even when feeds had not changed. Order sources and feed entries by a stable digest of local date and URLs; preserve the five-lead cap, cross-category mix, and daily rotation without a new model call or configuration. Sort a copy of cached entries so one preview cannot alter the next selection. New feed content, changed URL history, source failures, or the next day can still change the shortlist. This fixes preview parity, not ranking quality or feed-source coverage in a single run.

## 2026-10-21 — Make the free story-listening gate reproducible

The Jamsu Bridge story audition needed an ad hoc command to join five verified scratch scenes and write a review page. Extend the existing macOS Yuna CLI to produce a local combined audio file and escaped HTML page after its script-bound scene checks, without touching the production voice path or making a provider call. Rebuild the derived review on rerun while retaining verified scene files, and replace completed outputs only after FFmpeg succeeds. This gives later agents a one-command way to test an unapproved story's spoken arc before buying music, visuals, or final narration. A listen can reject a weak topic; it cannot establish source truth, visual clarity, or audience retention.

## 2026-10-21 — Keep free RSS discovery independent of paid planner setup

The RSS preview reused the production planner constructor, which required `OPENAI_API_KEY` and created paid planning helpers even though the preview never called them. A discovery-only factory now initializes exactly the state used by the existing RSS collector, leaving the production constructor and source filters unchanged. This lets an editor inspect candidates without a paid-provider key. The discovery-only instance cannot write or validate scripts; keep paid planning on the normal constructor. An offline no-key test verifies construction and zero OpenAI client creation, but live feed reachability remains a separate check.

## 2026-10-22 — Alternate RSS feeds within the paid candidate cap

The earlier five-per-category collector stopped reading sources after the first feed filled all slots. The October 21 design inventory showed 30 eligible articles but the bounded batch contained only Hypebeast items, concealing designboom architecture leads. Read each configured public feed, retain the same recency, URL-history, readable-summary, and global duplicate filters, then interleave eligible items by source until the existing five-per-category cap is reached. The free unbounded inventory keeps its source order. This reverses the earlier decision to skip later feed requests once a category is full: public RSS traffic and latency can rise, while the paid scorer's candidate count remains bounded. A live three-category preview included both design sources without an OpenAI key, but finance still depended on one promotional feed because two others returned 403. Source diversity is not a quality score or permission for unattended paid production.

## 2026-10-22 — Count article body, not navigation, before paid analysis

The 100-word article gate assumed the extractor returned substantive body text. A current Bank of Korea HTML release exposed the failure: recall mode returned 161 mostly navigation words, while precision mode returned 53 page words and the supporting facts lived in an attachment. Favor precision in the shared extractor so both RSS and direct-URL planning reject that short body before analysis or writing. Keep the existing 100-word gate and no-PDF behavior; do not add an official feed merely because its RSS summaries are long when its linked HTML cannot supply usable source evidence. Precision mode can omit some legitimate short articles, which an editor can inspect manually, but it does not justify treating menus as evidence. Keep the tracked RSS example aligned with source defaults so future setups reproduce the current candidate categories.

## 2026-10-22 — Admit shorter substantive economics leads before full-body review

The previous 200-character visible RSS excerpt gate excluded the St. Louis Fed's official On the Economy feed even though its current 153–193-character teasers link to substantial, extractable articles. Lower that shared free-discovery threshold to 150 characters and add this single official feed under `Finance_Economy`; leave the five-per-category paid scorer cap and 100-word extracted-body requirement unchanged. A no-paid-call preview now interleaves two Fed leads with three Seoul leads instead of taking all five from Seoul's event-heavy feed. Shorter teasers may give the topic scorer less context and the extra feed adds public network work, so the scorer must still abstain on unclear stories and the full article-fit gate must establish source evidence before writing. Keep U.S. claims geographically explicit in Korean narration and use original visuals unless publisher media rights are independently cleared. This is source diversity, not evidence that the new leads will interest the owner or viewers.

## 2026-10-22 — Preserve the publisher name through RSS cache hits

The first fetch read the feed title but stored only article fields; a cache hit labeled the same source `Cached Source`, and that label could be injected into an automatic script as its source name. Store the title with each cached entry and reuse it on later discovery calls. For older in-memory entries without a title, use the feed URL as an accurate fallback. A first-fetch/cache-hit regression checks equal titles without a second HTTP request. The cache remains in memory and its existing TTL is unchanged.

## 2026-10-22 — Retire failed and misattributed default RSS feeds

A live read of all default public feeds found five that returned HTTP 403/404 in this environment and a URL labeled TechCrunch that served an unrelated Blogspot feed. A subsequent actual discovery run found a hostname-mismatched TLS certificate on the KED Global feed; its `www` address returned an empty RSS feed. Remove these seven from new defaults, the tracked example, and this workspace's ignored source file. Switch the working Verge and MarketWatch URLs from HTTP to verified HTTPS. Do not silently delete URLs from other users' customized source files or bypass certificate checks. This reduces failed public requests and prevents the known wrong publisher from entering topic selection, but does not prove the remaining leads are interesting, extractable, or safe to publish.

## 2026-10-22 — Classify Seoul's event-heavy economy feed as city life

An uncapped free inventory found 17 eligible items from Seoul's economy-labelled feed and four from the St. Louis Fed. Most Seoul items covered local events, discounts, or visits, so the prior finance category spent three of its five paid-scoring slots on those leads. Move the official Seoul feed to `City_Life` in the defaults, tracked example, and this workspace's matching ignored source selection. Keep the feed because some local business stories may still be useful, and keep the five-per-category paid cap unchanged. This reverses the October 17 classification of that feed as `Finance_Economy`; other users' customized source files are not rewritten. The new finance preview contains four U.S. Fed leads and no Korean economic analysis, so finding a reliable Korean economics source remains open. The move changes lead grouping, not the article truth or audience-interest gate.

## 2026-10-23 — Make RSS category controls select actual feeds

The Studio's planning, full-pipeline, and scheduling screens passed an optional free-text "topic keyword" that the RSS planner ignored. Replace those controls with the categories already registered in `SourceManager`, plus an all-category choice. Pass the exact category to the shared collector and reject unknown values before network collection or paid scoring. Preserve the direct-URL route's optional title override, but do not pass a hidden RSS choice into that route. This makes the displayed choice match the sources used; it does not provide semantic keyword search or guarantee story quality. Legacy schedules containing an arbitrary keyword need to be recreated with a registered category before they can run.

## 2026-10-23 — Score an RSS pool once before article-fit retries

The existing five-topic retry loop bought a new GPT-4o mini score after each selected article was missing, too short, or rejected by article/script checks. Current official RSS probes show that readable excerpts can link to pages below the 100-word body gate. Ask one scoring request to mark up to `max_topic_retries` genuinely promising leads, then try those in descending score order without buying another score in the same run. Keep the all-unselected abstention, article-body and evidence gates, and fail-closed operational errors. This bounds topic-scoring calls to one per automatic RSS run while retaining up to five article attempts by default. A lead outside the marked shortlist can be reconsidered on a later run or through manual direct-URL review; the change does not prove the model chooses good stories or cap other OpenAI costs.

## 2026-10-23 — Show only licensed, available manual music moods

The Studio mood picker offered options such as calm and energetic even when the local catalogue had no documented track for them. Choosing one failed the existing preflight and could look like a broken control. Build the manual option list from the same hash- and license-checked `BGMManager.get_bgm_path` used for production; retain an already selected missing choice with an unavailable label rather than silently replacing it. Keep Auto visible with its explicit post-script matching warning, since the script mood is unknown before paid planning. Do not infer musical fit from a filename or silently substitute another song. This improves the control's truthfulness but does not solve the sparse catalogue or permit unattended broad-topic production.

## 2026-10-23 — Reserve each OpenAI request against a separate optional monthly budget

The Google ledger protects visual requests but cannot see GPT planning or `tts-1` narration. Add a separate UTC-month dollar ledger with an explicitly reconciled opening amount, atomic SQLite reservations, and the current standard-tier prices for only the models actually used (`gpt-4o`, `gpt-4o-mini`, `tts-1`). Reserve the full text output-token ceiling plus a conservative UTF-8 input estimate, or one speech attempt's character charge, immediately before each provider submission. Failed or interrupted attempts remain reserved until billing reconciliation; a missing ledger, old month, insufficient room, or unpriced model fails closed. The setting is optional and off until the operator sets an opening amount and initializes the ledger; the existing paid-call switch and individual round approvals still apply. This is a local estimate, not a provider-side spending cap, and does not include Brave or external OpenAI use. Official deprecation notices now put `tts-1` on 2027-01-06 and GPT-4o/4o-mini on 2027-01-14; do not substitute a new model or voice in production without budgeted contract and listening checks.

## 2026-10-24 — Prefer one scored lead per real-world event

The current RSS collector deduplicates exact article URLs, but two publishers can cover the same action with distinct URLs and angles; the October 22 preview showed two Airbnb housekeeping-policy leads. A title-overlap rule would risk hiding a useful source, so keep both for the single paid scorer call and ask it to select at most one lead for any underlying event, preferring the clearer source-checkable account. Shorten per-lead reasons and raise the response ceiling from 2,000 to 4,000 tokens for the existing possible 30-lead pool, reserving that entire ceiling before submission. The extra worst-case output reserve is $0.0012 at the current `gpt-4o-mini` list price. A prompt cannot enforce semantic uniqueness; measure a budgeted live result before treating this as a solved topic-quality gate. Keep the scheduler and paid switch disabled in the meantime.

## 2026-10-24 — Audition new licensed music before mood mapping

Keep newly sourced, hash-checked Mixkit tracks under `candidate_` filenames so they can be selected exactly for local comparisons without appearing in automatic mood lookup. The existing manager validates their license records and file hashes; the filename prefix deliberately prevents an unreviewed song from filling a broad mood. Promote a track to a mood prefix only after listening to it against a specific narration and checking speech masking, then revisit whether that pairing generalizes. A license record establishes provenance, not musical fit or immunity from future platform claims.

## 2026-10-24 — Reuse a recorded private upload ID for the same cut

The manual Publishing action and a recovered automatic run can call upload again for a finished file. Before contacting YouTube, require that file's matching, quality-passed production record. If it already contains a YouTube ID, return that ID and show the existing-upload state instead of creating another private copy; a missing or invalid record stops the request. Keep the uploader itself private-only. The local record cannot resolve a provider response lost before its ID was saved, and a path match alone does not prove that an existing file was never altered. Such uncertain uploads require a Studio check before a manual retry.

## 2026-10-24 — Carry the primary source link into upload metadata

The writer was asked to mention the source in the description, but its `source_url` lived in a separate script field and the default auto-upload path sent the description verbatim. Append the exact selected primary URL when it is absent from automatic upload metadata, and prefill the same credited description when Studio loads script metadata for manual review. Do not alter an explicitly supplied approved-script upload description: that text is an editorial choice. A link helps viewers and reviewers find the source; it does not validate the claims or make publication automatic.

## 2026-10-24 — Require both monthly ledgers for unattended production

Per-request Google and OpenAI reservations are optional for supervised manual work. That leaves a repeating schedule able to spend on planning and media each trigger if an operator enables the paid switch without one of the monthly guards. Before any scheduled pipeline call, require both local ledgers to be enabled for the current month, readable, and above zero remaining room; otherwise disable that schedule with the existing provider budget status. Keep per-request reservations and the exact visual preflight because positive monthly room does not guarantee that one episode fits. Do not initialize a ledger or guess opening usage automatically; the operator must reconcile the account first. This does not change manual, separately approved production.

## 2026-10-24 — Distinguish explanatory prices from sales offers

The validator's blanket rejection of pricing information contradicted the source-grounded unit-price candidate and would exclude useful economics stories. Reject prices used as a sales offer, discount codes, purchase links, and calls to buy; allow neutral, source-backed price figures and arithmetic when the script clearly separates hypothetical examples from observed figures. Keep the existing source-claim and unsupported-visual gates. This changes the model's review instructions, not a deterministic classification rule: check a future budgeted result and the finished cut before treating the topic as accepted.

## 2026-10-24 — Offer only available music moods to automatic writing

Auto music previously checked only whether *some* licensed track existed before spending on a script; five of the writer's seven allowed moods currently have no matching track. Restrict the writer's mood list to locally documented matches for auto music, and stop before planning if the list is empty. Ask the writer to abstain when none of the offered moods fits instead of forcing an unrelated bed. Keep the full mood list when an exact reviewed track is chosen or music is intentionally silent. This avoids a predictable post-planning failure without pretending that a filename proves story fit or that a model will reliably abstain. The chosen track still needs full-cut listening before publication.

## 2026-10-24 — Bind private upload reuse to finished video bytes

A quality-passed sidecar and matching path did not prove that the MP4 still held the rendered or already uploaded cut. Record a SHA-256 after a successful render check and compare it before YouTube submission or reuse of an existing upload ID. Reject a changed file; for an older unuploaded sidecar, bind the current file only after another technical check. An older already-uploaded sidecar without a hash cannot prove identity, so require Studio verification instead of claiming it is the current file. This improves local identity, not the unresolved case where YouTube accepted an upload but its response or sidecar update was lost; that still needs a Studio check.

## 2026-10-24 — Leave an upload claim until its result is recorded

An upload can reach YouTube even when the app receives no ID or cannot persist it. Claim the video path with an exclusive, local `*.upload-pending.json` file before submission; a concurrent or later attempt without a recorded ID stops instead of creating another private copy. Remove the claim only after the returned ID is saved in the production sidecar. A failed call may also leave a claim when YouTube received nothing, so an operator checks Studio before clearing or reconciling it. This favors duplicate prevention over automatic retry and does not retroactively resolve earlier ambiguous uploads.

## 2026-10-24 — Include routine automatic cuts in standalone review

The scorecard previously treated only manual-clip runs as editorial cuts, so a recurring automatic video's review row could never contribute to the accepted-video cost or seven-day outcome summaries unless it formed a unique image/hybrid experiment pair. Keep unique eligible pairs separate for mode comparison; aggregate every other finished cut as a standalone editorial review regardless of visual mode or scene source. Rejected drafts still contribute cost when their bill is allocated, and repeated cuts do not become independent topics. This changes summary grouping only, not acceptance, billing, or publication status.

## 2026-10-24 — Require RSS story evidence within the shared source excerpt

Automatic RSS analysis could return a valid quote from anywhere in a long article, but writing and validation each inspect only the first 5,000 source characters. Require the story-fit evidence sentence within that same excerpt before enrichment or script writing. This does not add a provider call and prevents paying for a draft whose decisive source proof the validator cannot inspect. A long article with its meaningful turn only later may now be skipped; revisit excerpt selection if that pattern appears in viable sources, and use deliberate direct-URL review meanwhile.

## 2026-10-24 — Select the shared RSS excerpt around verified later evidence

The fixed-prefix guard above protected validation but discarded a source-backed long article when its decisive sentence appeared later. Keep its invariant that the writer and validator inspect the same 5,000-character source excerpt, but choose a contiguous window containing the exact analyzer evidence after confirming it occurs in the full extracted article. Keep the article beginning when the evidence fits there. This avoids another provider call and preserves late-source candidates; one window may omit distant introductory facts, which remain an editorial review limit. The earlier fixed-prefix rejection is superseded.

## 2026-10-24 — Preflight the normal hybrid video hook before paid planning

The full-run preflight used five image outputs for `hybrid`, even though its normal minimum five-scene composition has one Veo hook and four images. Check that normal composition, including explicit Veo attempts and Google monthly request slots, before buying an automatic script. This prevents a predictable post-planning visual-cap failure without changing exact post-script cost checks or forcing a still hook. A tight cap can now block a script that would have chosen an all-image hybrid; the operator can select `image` mode for that cheaper intent. The reserve is an output-list estimate, not a provider-enforced spending limit.

## 2026-10-24 — Treat generated music as an audition, not an automatic fallback

The currently documented local catalogue supports only two automatic story moods, so new topics may need more music than stock selection can supply. Google documents instrumental generation and commercial use under the Lyria 3 preview terms; its 30-second clip is shorter than the current Sillim cut, while Pro can cover it in one request at a higher listed price. Do not wire a new model into the automatic fallback or replace the owner's reviewed Arulo track on price and capability alone. First require a distinct request ceiling, a Google monthly ledger reservation that includes music, an instrumental output checked against the exact narration for arc and speech masking, and an editorial rights/platform check before any publication use. The existing visual-only ledger cannot guard a direct Lyria request. This leaves the current fail-closed music selection intact until a measured audition justifies integration.

## 2026-10-24 — Count source-linked story cost separately from edit cuts

The scorecard's editorial-cut denominator counts every local revision, so it cannot show whether repeated spending produced distinct source-grounded stories. Keep that cut view and the unique image/hybrid experiment view, and add a rollup keyed by the recorded primary source URL across all rendered cuts, including pairs and script revisions. Count an accepted source once if any cut was approved, but report its cost only after every cut has a verdict and allocated bill; reject incomplete groups rather than treating missing charges as zero. Do not infer event uniqueness from URL identity or claim that unrendered failed calls appear automatically. This makes the repeat-production cost question visible without changing existing review rows or acceptance decisions.

## 2026-10-24 — Serialize scheduled production within one app process

Two schedules due together could read the same pre-production RSS history and start paid runs for the same lead. Run one scheduled pipeline at a time within `ScheduleManager`, then reload each waiting schedule so changed budget and enabled state are checked before it spends. If another schedule has already rendered a fixed article URL, stop the second as `duplicate_url`, even if it has its own schedule ID. Keep paired mode experiments as separately reviewed manual work instead of overlapping recurring jobs for one article. This does not lock across multiple app processes or identify duplicate events at different URLs; the local monthly ledgers still guard concurrent visual and OpenAI requests separately.

## 2026-10-24 — Reject silent scene narration before buying visuals

The final MP4's non-silent audio check can pass on BGM alone, while the earlier narration preflight checked only file duration and optional script-bound hashes. Sample each retained or newly generated narration file for a minimal signal before visual requests. Reject a silent or nearly silent scene rather than letting music mask a missing voice. Keep the final human listen: a peak threshold cannot identify wrong words, pronunciation, or masking after the mix. Do not treat this as a second TTS request or a reason to regenerate visuals.

## 2026-10-24 — Add a verified Korean monetary-policy lead without relaxing source gates

The default finance pool supplied only U.S. Fed blog leads. Add the Bank of Korea's official monetary-policy RSS after its current release passed the existing parser, 150-character teaser filter, and 100-word precision-extraction gate. Keep the category cap, scorer, article analysis, and source-grounded script checks unchanged: a policy decision can be a lead while its forecasts and claimed downstream effects remain unverified for narration. The feed publishes infrequently, so it does not by itself establish a sustainable domestic-economics pipeline. Existing customized source files are not overwritten; this workspace's ignored file receives the feed explicitly.

## 2026-10-24 — Pause a successful scheduled episode for editorial review

An RSS schedule previously continued after successful rendering or private upload, allowing its next trigger to buy another episode before the first had a story and visual verdict. Disable the job after any successful finished video and show the review-pending state in Studio; retain the last rendered path so the operator can play the cut before resuming. Only offer the player for an existing MP4 within the configured output folder, because schedule JSON is local mutable input and must not expose arbitrary files. Keep no-story RSS discovery eligible for the next source window and preserve the existing failure pauses. This adds a human cadence gate to unattended production without treating technical success or private upload as publication approval.

## 2026-10-24 — Serialize scheduled spending across local app instances

The earlier per-instance lock cannot stop two Studio processes from reading the same enabled schedule before either records a result. Use a standard-library SQLite exclusive transaction beside the local schedule file around each scheduled pipeline, then re-read the schedule after obtaining it. SQLite keeps this path portable across the project's supported operating systems and releases the lock when the connection closes or a process exits. Preserve the per-instance async lock to avoid needless local contenders. This prevents simultaneous scheduled runs sharing one local file; it does not coordinate different machines or prevent a later retry after an abruptly interrupted paid call with no saved final result.

## 2026-10-24 — Persist a schedule pause before starting paid production

An app exit or coroutine cancellation can release the SQLite process lock without reaching the final schedule update. Save `run_in_progress`, increment the attempt count, and disable the schedule before entering `ProductionService.full_pipeline`. A completed ordinary no-story result explicitly re-enables RSS discovery; a finished video or failure replaces the marker with its existing outcome. If the process stops before that replacement, the disabled marker survives restart and requires output, request-record, and billing reconciliation before manual resume. This uses the existing atomic schedule file instead of another recovery store. It does not prevent manual resumption without reconciliation or coordinate separate machines.

## 2026-10-25 — Retry unreadable RSS feeds at the next scheduled window

The October 21 source-failure gate correctly separated unreadable feeds from a valid empty feed, but its generic planning-failure pause left a recurring schedule disabled after a transient DNS outage. RSS collection fails before model scoring or other paid production requests. Keep `RSS_SOURCE_UNVERIFIED` as a visible failure and do not reuse stale leads or mark URLs reviewed; for an RSS schedule with no rendered video, record `source_unavailable` and leave the next scheduled check enabled. Direct-URL and later planning failures still pause. Repeated bad configuration can produce repeated free failures, so show the state in Studio and inspect the feed logs if it persists. This reverses only the automatic pause for total RSS source failure, not the source accuracy gate.

## 2026-10-25 — Attribute future Google visual reservations to the script source

The monthly Google ledger held estimated image and Veo reservations, including failed requests, but only rendered videos had a primary source URL. A failed attempt could not be grouped with its story even for manual cost review. Pass the script's URL through automatic scene generation into each Google reservation and Veo attempt record; direct calls without a script keep a null source. Add a nullable URL column to existing SQLite ledgers inside the next atomic reservation so old rows and their conservative holds stay intact. Report source-linked and unattributed reserves separately without treating either as actual billed cost. This does not backfill older requests, attribute OpenAI planning or narration, or prove that Google billed a particular operation.

## 2026-10-25 — Attribute article-bound OpenAI reserves without assigning shared scoring

The OpenAI ledger also lacked a story key. Record the primary article URL for analysis, optional enrichment, script writing and validation, and every TTS attempt; propagate it from the selected article or approved script rather than parsing prompts. Keep the one RSS scoring call across several candidate URLs unattributed instead of charging whichever lead eventually wins. Extend an existing SQLite ledger only within the next atomic reservation, preserving older rows and the conservative opening amount. Report these as estimated source-linked and unattributed reserves, never as actual provider charges or a complete per-video cost; Brave, Google, rejected leads, and account-level billing still need separate reconciliation.

## 2026-10-25 — Check whole-set narration room before the first scene

Per-request speech reservations stop overspending, but a low monthly balance could buy one scene and then fail the next. Before automatic narration or a standalone retained set, compare the remaining scene texts at the current `tts-1` character rate, rounded per request, including the editor's one possible transient retry. Do not reserve the whole set at preflight because each actual attempt is still recorded immediately before submission; concurrent work can change the balance, so the per-request reservation remains authoritative. A local plan-only narration quote does not require the monthly ledger.

## 2026-10-26 — Verify saved YouTube authorization before auto-upload production

A read-only refresh of the current saved YouTube token returned `invalid_grant` even though the local file contains a refresh token. An auto-upload run would otherwise spend on planning, narration, and visuals before discovering that it cannot deliver the private review copy. Check the saved upload scope noninteractively before any full-pipeline paid work and stop with a visible authentication marker if refresh fails. Keep manual sign-in as an explicit `--auth-only` operation with no video request; do not open an unattended browser from the schedule. For a manual upload, distinguish authentication failure before any media request from an uncertain request result: clear the former's pending claim for a safe retry, retain the latter until Studio reconciliation. This verifies OAuth readiness, not channel ownership, quota, upload completion, or public release.

## 2026-10-26 — Preserve free RSS review snapshots

The RSS preview command wrote each run to one fixed filename, so a later source check silently replaced the page cited for an earlier editorial judgment. Name each CLI output with the run date and a unique suffix, for both bounded and expanded previews, while keeping the explicit `preview(..., output)` helper available to callers that intentionally choose a path. The pages remain ignored local review data and do not become validated sources. Older fixed-path pages that were already overwritten cannot be reconstructed from this change; historical documentation should not link them as if they were preserved.

## 2026-10-26 — Retain the submitted private-upload description

The approved Sillim narration draft still contains an older description of a diagram audition, while its latest private review upload used a corrected description of AI footage and the city-attributed effect. A production sidecar that records only the YouTube ID cannot establish which wording was submitted. Prepare the uploader's exact private request body before claiming an upload, reject malformed metadata before a media request, and retain the prepared body in the ignored pending claim and successful sidecar. Preserve older sidecars without backfilling unverified metadata. This records what the app submitted, not what YouTube finally displays; Studio remains the visibility and processing check. No new OAuth scope, public release, or provider request is implied.

## 2026-10-26 — Require primary source credit for new private uploads

The earlier source-link prefill could be erased in Studio or omitted from a caller-supplied approved-script description. At the shared `ProductionService.upload_to_youtube` boundary, require the exact primary `source_url` from a production record in the prepared description before claiming or sending a new upload. Leave the editor's wording intact and return a clear error so it can be corrected. Reusing an existing recorded YouTube ID remains idempotent without rechecking proposed metadata. Legacy records with no source URL remain uploadable; this gate proves a link was submitted, not that the claims or rights are valid.

## 2026-10-26 — Preflight automatic upload metadata before paid work

The final upload gate alone can discover a missing source URL or malformed caller metadata after planning or rendering. Validate supplied request fields before automatic planning, then check the selected script's source URL against the chosen description before narration or visuals. Keep the final sidecar-based upload gate because a manually changed description or record can still arrive through Studio. A generated script's source cannot be checked before the planning that discovers it; this preflight only prevents avoidable downstream work.

## 2026-10-26 — Link a scheduled private upload from its review card

A successful scheduled private upload paused for editorial review but its Studio card showed only the local MP4. Retain the returned YouTube ID with that run's video path and show a fixed-host Shorts link only for a successful automatic upload with a safe ID. Clear the saved ID when a later render has no confirmed upload so it cannot be paired with the wrong cut. The schedule remains paused; the link is a review aid, not proof of public release or editorial acceptance.

## 2026-10-26 — Label Korean upload text in future API requests

The Sillim Studio details show Korean title and description with the default metadata language unset. [YouTube's `videos.insert` documentation](https://developers.google.com/youtube/data/reference/rest/v3/videos/insert) permits `snippet.defaultLanguage` in the upload request. Set it to `ko` for future ShortsMaker API uploads, whose title and description are Korean. Do not assume this edits earlier uploads or sets the spoken-audio language; the insert method's settable-field list does not include `defaultAudioLanguage`. The current private Sillim candidate needs its language fields reviewed in Studio before a separate public-release decision.

## 2026-10-27 — Bind supporting-source credit to a new private upload

The Jamsu story needs Seoul's 2024 proposal and 2026 revision, but the script and upload gate previously tracked only the latter. Let a reviewed script list optional supporting source URLs while retaining one primary URL for discovery, budget attribution, and distinct-source scorecard grouping. Preserve that list in each new production sidecar, prefill all missing links in default and Studio metadata, and require every recorded link before a new private upload. Treat a longer URL containing a source URL as a different link. Reject malformed supporting URLs in the script and malformed source lists in a sidecar. Older sidecars lack this field and cannot prove complete credit for a multi-source cut; rebuild from the reviewed script before uploading. This is citation coverage, not automated verification that every spoken claim is supported by the cited pages.

## 2026-10-27 — Keep source-precise story auditions independently reviewable

The Jamsu revision needed dated and walking-space-specific narration after a local cut already existed. Keep the earlier script and script-bound Yuna audio for comparison, and create a separate candidate rather than silently changing the approved input of that audition. The scratch review page links the primary and every supporting source as distinct, escaped anchors so an editor can inspect both claims before buying final voice or visuals. Links expose evidence for review; they do not certify that each spoken sentence follows from the articles. Any accepted wording change requires a new narration set and a timing check against the visual cut.

## 2026-10-28 — Release only failed Google requests verified as unbilled

The October Google ledger conservatively kept three failed Veo Lite reservations after submission failure or provider overload. Cloud Billing's daily Lite output counts through October 27 match all 52 seconds of locally saved post-ledger video and contain no additional count for those failures. Let a deliberate reconciliation release only current-month `not_submitted_dns_failure` or `provider_limited` rows after recording external evidence; retain their original amounts, prior statuses, and verification time in the ignored ledger. Reject saved, ambiguous, repeated, and cross-month releases. Keep the paid-production switch and per-request ceiling separate: freeing an estimate does not authorize another API call, prove a final invoice, or make the draft worth publishing.

## 2026-10-28 — Judge first frames by the narrated claim before buying motion

The first Jamsu scene-3 image was produced by a manual image-generation edit of flat geometry, outside the source-to-scene planning path. Its stacked slabs preserved two levels but did not read as a proposed pedestrian route or explain the design change, so the owner rejected it. Retain that image for audit, block the single-shot paid runner, and review a new image alongside the exact narration, the 2024 proposal, the 2026 revision, and the next scene's job. An input frame for this scene must visibly establish a separate elevated walking path and an intact lower bridge; the moving clip must remove only the proposal layer. The revised plan's widened walking space, viewing areas, and transparent sections belong to the next scene, not an invented transformation in this one. A polished illustration or a passed size/price check is insufficient approval for a provider request.

Bind each manually reviewed first-frame verdict to the exact scene text, cited sources, frame bytes, motion prompt, and visible pass/fail criteria. For the current Jamsu pilot, the record remained pending until the owner confirmed v3's two-level walking-path meaning; reject a changed input at the paid boundary instead of relying on a mutable boolean in code. The verdict is separate from a spend authorization and from the later muted raw-clip and full-cut reviews. This closes the manual-first-frame escape observed here without claiming that a manifest or test can judge artistic quality.

## 2026-10-29 — Stop automatic production at a reviewable script

The unattended route previously bought narration and visuals immediately after script validation, so a source-grounded but visually weak story could spend the Google budget before an editor saw its scene plan. A new `full_pipeline` call without an `approved_script` now returns a successful `review_pending` script and stops. Scheduled runs persist that script in their ignored schedule record and pause; Studio loads it for the existing Planning review and binds confirmation to the current script content before the Generation button can run. A changed script needs another confirmation. Existing explicitly reviewed `approved_script` calls retain rendering and private upload with reviewed metadata. New Studio schedules no longer offer an automatic-upload switch because their first run ends at script review; older saved upload preferences cannot cause an upload from that planning-only run. This is an intermediate gate, not approval of Veo first frames or a completed episode. Finish the scene-level visual and raw-clip gates and connect accepted manual production back to recurring schedules before claiming sustainable uploads.

## 2026-10-29 — Require an editorial disposition before another scheduled topic

The saved script-review pause could be bypassed by clicking Resume on an RSS schedule, starting another paid topic round while its first script was still pending. Reject that resume in Studio and stop even a directly re-enabled saved job before paid work. The editor can explicitly exclude the pending script; only then does an RSS schedule return to its next discovery window. A direct-URL schedule stays stopped and retains its planned URL, so rejecting it cannot repurchase the same article. Keep each script's actual source URL and the rejected script in ignored local history for audit. This is a discard path; accepting a manually produced private video still needs a separate schedule handoff.

## 2026-10-29 — Bind a completed private review to its source schedule

A manually finished and privately uploaded video previously left its source schedule in `script_review_pending` forever. Let the editor explicitly accept that whole cut from the schedule card after viewing it. Require the MP4 inside the configured output folder, an unchanged SHA-256 matching its passing production record, the pending script's primary source URL, and a saved private YouTube upload request and ID. Persist the accepted video path, ID, and review time beside the schedule; reopen only RSS discovery. A direct article URL remains one episode. Keep the video and schedule local and private; this acceptance does not make it public or prove its artistic or factual quality automatically. The UI warns that an active paid-work switch and monthly ledgers can permit a paid planning call at the next RSS window.

## 2026-10-29 — Match the whole pending script at private-review handoff

The primary URL alone does not identify a particular narration or visual brief. Put a deterministic hash of the complete serialized script in each new production record and require equality with the saved scheduled script before accepting its private upload. Keep the existing video-byte and private-upload checks. A legacy production record without this hash cannot complete a pending schedule automatically; the editor must produce a record from the intended script rather than bind a different cut by URL.

## 2026-10-29 — Require a reviewed first frame for ordinary Veo scenes

The Jamsu pilot required a source-bound input review, but ordinary Studio production could still buy text-only Veo footage after script confirmation. Require each new automatic video scene to have a locally previewed portrait PNG/JPEG and a written pass/fail review bound to the exact source URLs, scene text, visual and motion brief, prompt version, and image bytes. Reject a missing or stale approval before narration or visual work; recheck the image hash at the Veo request boundary and include it in the video cache identity. Keep the records local and ignored, while the one-shot Jamsu pilot retains its tracked bespoke record. This is a human input decision and a spending gate, not proof of factual imagery or acceptable motion. Manual clips and still-only scenes retain their existing paths. A separate muted raw-clip checkpoint is still needed before normal production can claim the full visual review sequence.

## 2026-10-29 — Request and approve one Veo raw scene before whole-cut production

Ordinary production prepared paid narration and could then submit several Veo requests without pausing for a muted meaning verdict. Separate the one-scene Veo request from final `produce_video`: the editor clicks a cost-labelled Studio button after first-frame approval, watches the cached silent portrait MP4, and saves an approve/reject note bound to the script, input frame, and raw clip hash. The whole-cut path accepts only approved cached Veo clips and checks this before TTS or remaining image calls. A rejected clip remains in the local cache; changed first-frame or scene brief creates a different cache identity for a newly budgeted attempt. Preserve the monthly and per-video visual cap by pricing all still-missing scenes before the first staged request, then reserving each actual provider attempt at its request boundary. This also avoids repeated TTS payments during visual review. A raw verdict is still a human judgment of motion and meaning; final voice, music, captions, source accuracy, private upload, and public release retain their separate reviews.

Use an exclusive per-cache request marker before the one-attempt call and retain it on an uncertain failure. A valid saved clip makes a repeat button click a cache read; a missing clip plus marker blocks another paid request until the provider attempt and bill are reconciled. The image/hybrid paired comparison also refuses missing raw approval before it buys shared narration and counts only remaining image output in its new-spend estimate. Keep prior Veo costs in source-level accounting rather than charging the already saved raw clip again.

## 2026-10-29 — Preserve every validated script revision for recovery

The planner saved approved scripts under a second-resolution timestamp and title, so two revisions with the same title inside one second overwrote the earlier file. Give each saved script a unique filename and write it through a temporary file before exposing the JSON. Keep these local files as recovery evidence if a scheduled run stops after paid planning but before its pending-script record is saved. Do not resume a `run_in_progress` schedule automatically from a file: its source, provider attempts, and billing still need reconciliation.

## 2026-10-30 — Show design alternatives without physical removal

The owner watched the Jamsu scene-3 Veo shot and read the pink upper path lifting away as real demolition, even though the first frame and underlying bridge were clear. Reject that exact raw clip and retire the 2026-10-28 physical-removal motion hypothesis for this story. Show the 2024 proposal and 2026 revision as separate unbuilt design states; guide attention between them without making a bridge component move, disappear, flood, or break. A still first-frame verdict does not imply an acceptable moving shot. The owner also found scene 4's planned features readable but its single-image hold too long, so audition timed camera reframing locally before considering new paid motion. Keep the source counts and proposal status in editorial text and require muted raw and whole-cut meaning checks for any later Veo result. A free moving crop proves edit timing only, not native generated action or final quality.

## 2026-10-31 — Start a new planning cycle every four weeks

The owner's provisional cadence under the ₩10,000 monthly Google budget is one accepted private review cut per four weeks, with later public release decided separately. Add a true 28-day scheduler interval anchored to the first selected local clock time after the schedule is initially enabled; retain the anchor across later pauses and Studio restarts rather than approximating it with a calendar-month cron day. Make this the new Studio schedule form default without changing saved daily or weekly jobs. Each trigger starts source-grounded planning and pauses at the existing script review gate. A missed trigger while Studio is closed is not replayed, and a failed quality or budget gate cannot be counted as an uploaded episode. Do not activate paid production or promise automatic upload merely by saving an interval. Measure three accepted consecutive cycles and their actual costs before considering a shorter cadence.

## 2026-10-31 — Improve the pipeline during real production cycles

Replace the broad “plan, implement, and verify a continuous Shorts process” objective with the operating objective and initial acceptance in [STATUS.md](STATUS.md#goal-and-milestones). Run toward one accepted private review upload per four-week slot, inspect real outputs and costs, implement the highest-impact supported improvement, and verify it in the next episode. Remove the former requirement to finish three episodes without intervening code repair: repairs are part of the requested development process and must be tracked with their recurrence and evidence. Preserve source, quality, spending, retry, and private-upload controls while changing code; tests or altered thresholds cannot substitute for owner acceptance or real provider/upload evidence. Three consecutive accepted slots validate the initial operating base; subsequent maintenance remains recurring work. A failed slot is retained as a failure, and quality does not pass merely to meet a date. Revenue remains a longer-term outcome to measure, not a guaranteed initial exit condition. Goal editing alone neither activates the disabled production schedule nor configures an agent to wake and develop later.

## 2026-10-31 — Carry the displayed scene ceiling through ordinary Veo requests

The one-shot pilots supplied a narrow per-request ceiling, while ordinary staged production passed the broader per-video cap at the final Veo boundary. Pass Studio's displayed scene estimate through the existing service and generator arguments, keeping a separate total-remaining-visual check and monthly ledger. Reject an invalid ceiling or an estimate above it before creating the single-use attempt marker, then record the ceiling with that marker and the existing provider audit. An omitted service ceiling uses the current single-scene estimate; it does not infer user spending authorization. Public generator video calls also default to their scene reserve. Keep low-level validation and duplicate protection intact. A changed higher estimate requires refreshed review; exact scene/source/frame approval, model configuration, actual billing, and raw meaning remain separate checks. This lets a future authorized Jamsu shot use the ordinary staged path without creating another topic-specific runner solely to enforce a small request amount.

## 2026-10-31 — Recover audio choices per exact script across production pauses

A four-week episode can outlive the Studio process. Persist an explicitly saved voice, exact BGM filename, mood and level separately from browser sessions, keyed to the full script hash. Reuse those values when the same saved or scheduled script is loaded; new scripts without a record start from audio defaults so one topic's music does not carry into another. Validate values and documented music before changing current state, and publish records atomically. Keep credentials, paid switches, input/raw/editorial approvals and upload paths out of these records. Loading a saved script clears its in-memory script confirmation and final-video path. A planned voice choice is not permission to buy speech or proof of a reviewed mix. Keep remaining UI state process-local until another observed recovery need justifies more persistence.

## 2026-10-31 — Retain each scheduled attempt before starting another episode

The scheduler previously stored only the latest result per schedule, so another attempt overwrote the preceding review/failure and could leave its old script, video, upload ID and acceptance time on the new episode. Archive the previous attempt inside the existing ignored schedule JSON when the attempt counter advances, then clear its episode fields before applying the new result. Updates within one attempt, including script exclusion or private-upload acceptance, update that current attempt instead of duplicating history. Save the verified video hash with acceptance and retain complete prior scripts for source/revision recovery. Use the same atomic schedule write; reject malformed history without rewriting the file. Studio displays the latest ten attempts, preserving all saved attempts locally.

Do not reconstruct overwritten legacy history or label these attempts as three successful scheduled cycles. They record actual starts and their latest disposition; missed time slots, editorial quality, costs and bill reconciliation still need their own evidence. Keep the current production schedule and paid switch off during offline verification.

## 2026-10-31 — Recover staged raw requests independently of changed model defaults

The approved Jamsu v2 request used Lite/eight seconds in a subprocess, while restarted Studio used Fast/six seconds. Its exact raw file and rejection survived, but the model-specific cache lookup showed generation pending. Retain a per-script, scene, first-frame and prompt-version request record before any new staged call, independently of current model defaults. Use exclusive creation for its pending state and atomic completion with the saved clip hash. Keep the original model-specific cache and marker for compatibility. Recompute its original cache identity using the recorded model/seconds so changed overlay settings still require reconciliation. A staged button also carries its displayed first-frame hash; a changed input must refresh the displayed cost before another request. A recorded missing, altered, corrupt or pending result blocks another paid call, even after defaults change; another approved frame or changed script has a separate identity. Do not auto-adopt an arbitrary file or scan for a visually similar replacement.

Raw review, remaining-cost checks and final production recover that exact saved clip; final production still requires its hash-bound raw approval and reports its recorded model. A saved request is not raw acceptance, spend permission, or an invoice. Keep new-spend estimates separate from the preview's full visual estimate before reuse. Legacy results lack this new request record: explicitly reconcile their script/frame/clip hashes and actual request metadata before adding one, without resubmitting or rewriting an old editorial verdict.

## 2026-10-31 — Pin Google SDK retries to the application's budgeted attempts

The installed `google-genai` 1.55.0 uses a single attempt when no retry options are supplied; this audit found no current hidden SDK retry defect. Its [versioned retry implementation](https://github.com/googleapis/python-genai/blob/v1.55.0/google/genai/_api_client.py) uses a different retry policy when options exist, so do not depend on an unspecified SDK default for the project's one-shot spending contract. Explicitly pass `HttpRetryOptions(attempts=1)` to the regional Veo, global Gemini image and character-video clients. Existing permitted application-level retries still need their own reservation and attempt records; this does not grant them automatically.

Exercise the actual installed SDK with static dummy credentials and an in-memory HTTPX transport, returning 429 and 503 for each client. Assert exactly one POST per SDK call rather than merely mocking the model method. These offline checks establish transport retry behavior, not provider availability, past billing or a live production result.

## 2026-11-01 — Delegate intermediate editorial review within standing episode limits

The owner approved the concrete [operating scope](OPERATING_AUTHORIZATION_PROPOSAL.md) with “이 한도로 자율 운영 (권장)”. Let the agent inspect sources, scripts, first frames, silent originals and the full edit, record its own decisions, and continue bounded production through one private upload. Keep final acceptance and public release with the owner. Preserve existing raw exclusions, per-request identities, no SDK retry, episode revision limits and monthly guards. Bind each episode’s cumulative new-spend scope before calls, including any month crossing; a new calendar month does not replenish that episode’s allowance. Verify each provider’s current-period opening independently instead of clearing historical reservations. This authority removes per-asset owner pauses within scope; it does not establish an active schedule, a working unattended handoff or three accepted recurring cycles.

## 2026-11-01 — Preserve raw verdicts across exact visual reuse and price local edits correctly

Actual Jamsu production reused the owner-approved scene-4 file after other visual briefs and publication metadata changed. A single clip-level verdict file overwrote the prior full-script binding. Save new verdicts per full script and scene alongside the cache; read an existing legacy verdict only when no current scoped file exists. A rejection or corrupted current file must never fall back to an older approval. Changing a script still requires explicit source/frame/context review before saving a separate verdict; this does not transfer acceptance automatically.

The staged remaining-cost check also priced an already composed local comparison as a fresh Veo scene, blocking a valid mixed-source round before provider submission. Accept the existing manual-clip mapping in staged preflight, validate scene numbers and playable local videos before discounting them, and reject a staged request for a scene already supplied locally. Preserve the monthly ceiling, per-request reserve and rounding buffer; fix the estimate instead of raising the approved budget. These changes do not waive raw/content review or imply a scheduled upload.

## 2026-11-01 — Separate the 28-day clock from bounded editorial production

An agent-operated schedule queues one persisted `operator_pending` attempt at its due slot, with no paid call from the clock process. Continue that exact attempt through isolated operator subprocesses using the ordinary service and review gates; do not turn on Studio's global paid switch. Capture immutable request-ID baselines for both existing ledgers once per episode. Count all new local reservations conservatively, including unallocated concurrent work and prior-month requests, and lower each subprocess's monthly ceiling to current used plus remaining episode scope, bounded by the monthly authorization. A rollover does not reset an episode and a missing baseline row blocks continuation. Normal clients still perform atomic reservation checks; arbitrary child code is trusted operator code, not a sandbox or substitute for review/retry authority.

Keep a queue-only macOS user host independent of NiceGUI. Synchronize external accept/pause edits without replacing an unchanged trigger. An explicit initial date can place the first true scheduled slot 28 days after a manual pilot. On recovery, enqueue only the latest due slot, retaining skipped dates and lateness rather than silently claiming old cycles ran or paying for a backlog. This recovery changes only delegated agent schedules; legacy Studio jobs retain their previous behavior. A private upload can be attached before owner acceptance; its exact saved script and MP4 hashes must match, and attachment alone cannot enable the next slot. Three real scheduled, owner-accepted, cost-reconciled cycles remain required.
