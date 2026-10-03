# Production quality evaluation

This is the repeatable review method for stage 3. [STATUS.md](STATUS.md) owns current findings and stage state. This file defines how to collect the next evidence; it does not claim that an unreviewed video is good.

## Review unit

Keep the source article, final script, rendered video, visual mode, generation settings, and provider charges together in a private local record. Each newly rendered video gets a local `*.production.json` file beside its MP4. The file records the source URL, script key, scene modes/models, generated versus reused/manual scenes, preflight visual output estimate, quality gate result, YouTube ID, and AI disclosure choice if uploaded. A failed quality check after rendering also gets a record. Runs that stop before rendering do not. For an image-versus-hybrid comparison, use the same script, narration, subtitles, and editing settings; change only the visual mode. Match runs by `script_key` and start with three different topics before drawing a directional conclusion.

Manual editorial re-cuts remain in the local evidence but have `paired_comparison_eligible=false` in their sidecar, so a corrected cut with the same script key does not invalidate the original mode pair. Only compare runs where visual mode is the intended difference. If multiple eligible renders of one script and mode exist, the scorecard skips that ambiguous pair; resolve the run grouping before drawing a conclusion.

After verifying a script against its source, run `python scripts/paired_review.py path/to/script.json --budget-usd 1.25`. The command checks a conservative visual upper estimate before TTS, creates one narration set, renders image then hybrid with that same audio, and allows one Veo request attempt. It produces local videos only. Its estimate can double-count images later reused from the scene cache; actual provider charges may also include retries and other calls outside this command.

## Record for each video

| Check | What to record |
| --- | --- |
| Technical gate | `check_video_quality` result, duration, width × height, audible narration, final audio loudness, visible scene defects |
| Source accuracy | Each concrete number, quote, named entity, causal claim, and past-tense event checked against the primary source; distinguish an assigned role or capability from an observed result and count unsupported claims |
| First five seconds | Whether the opening states a specific reason to keep watching without a generic intro |
| Story turn and payoff | A source-supported dilemma, the actual decision or result revealed early, and a clear conclusion; reject a chronological list of facts without a turn |
| Narration and pacing | Intelligibility, awkward speed changes, pauses, phrase caption timing, one-word orphan captions, whether text reveals a later fact early, and dark frames at scene cuts |
| Visual relevance | Before spending, whether each prompt specifies one source-grounded moment with correct setting, counts, and roles; after rendering, whether visuals explain the claim, avoid invented labels, and clearly distinguish AI reconstruction from actual footage |
| Visual rights | Original source and credit for each photo or clip, publisher usage terms and any third-party exception, recognizable people or protected logos, and whether the video implies an agency's endorsement |
| AI disclosure | Check whether any AI-generated or altered scene appears photorealistic or changes a real event/place. Record the YouTube AI-use choice and verify it before publication; obvious diagrams and script assistance alone do not require disclosure under [YouTube's guidance](https://support.google.com/youtube/answer/14328491?hl=en). |
| Visual rhythm | Distinct composition or meaningful motion across scenes; note repeated photos and static stretches even when every individual frame is accurate |
| Music | Compare the script's `music_direction` with the selected track and the full rendered scene arc by ear; record whether the bed is audible under speech, avoids masking narration, and has documented rights for publication. Intentional silence needs an editorial reason. |
| Cost | Sidecar's preflight visual output estimate, actual provider charge attributable to the run, rejected generations, and production time |
| Outcome, if published | Video ID, publish date, retention and revenue after a consistent observation window |

Do not publish a video with a failed technical gate or an unsupported factual claim. Resolve the defect, regenerate only affected scenes when possible, and repeat the check. Human reviewers decide whether hook, narration, and visuals are good enough; the current code does not score these reliably.

## Comparison and sharing

Compare image and hybrid by accepted-video rate, actual cost per accepted video, and reviewer notes first. The sidecar estimate is not the provider bill: it excludes prompt tokens, narration, retries, taxes, and any charges from a failed run without a rendered video. Reconcile bills separately in the private record. Use retention and revenue only after the same observation window and enough published samples. Do not infer audience preference from the nine legacy files in the technical baseline: they were not paired experiments and have no sidecars. Keep raw articles, bills, channel metrics, sidecars, and video files outside Git. Share only anonymized counts, aggregate costs, findings, and resulting code decisions in `STATUS.md` or `DECISIONS.md`.

Run `python -m shorts_maker.services.scorecard init` after each new render to add missing rows to the ignored `outputs/evaluation/reviews.csv`. Fill `accepted` with `yes` or `no` after the checks above. Enter `billed_cost_usd` from the private provider records, including failed attempts and a consistent allocation of shared narration/planning cost. The optional `views_7d`, `average_view_duration_seconds_7d`, and `revenue_usd_7d` refer to the same first seven days after each public upload; leave them blank until observed. Run `python -m shorts_maker.services.scorecard summary` for paired acceptance, billed cost per accepted video, and complete seven-day outcomes. It skips incomplete pairs instead of treating missing values as zero. The current YouTube token only grants upload access, so these metrics must be entered from a private export until analytics read scopes are authorized.
