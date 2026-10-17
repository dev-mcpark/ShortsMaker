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
