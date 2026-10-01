# Production quality evaluation

This is the repeatable review method for stage 3. [STATUS.md](STATUS.md) owns current findings and stage state. This file defines how to collect the next evidence; it does not claim that an unreviewed video is good.

## Review unit

Keep the source article, final script, rendered video, visual mode, generation settings, and provider charges together in a private local record. Each newly rendered video gets a local `*.production.json` file beside its MP4. The file records the source URL, script key, scene modes/models, generated versus reused/manual scenes, preflight visual output estimate, quality gate result, and YouTube ID if uploaded. A failed quality check after rendering also gets a record. Runs that stop before rendering do not. For an image-versus-hybrid comparison, use the same script, narration, subtitles, and editing settings; change only the visual mode. Match runs by `script_key` and start with three different topics before drawing a directional conclusion.

## Record for each video

| Check | What to record |
| --- | --- |
| Technical gate | `check_video_quality` result, duration, width × height, audible narration, visible scene defects |
| Source accuracy | Each concrete number, quote, named entity, and causal claim checked against the primary source; count unsupported claims |
| First five seconds | Whether the opening states a specific reason to keep watching without a generic intro |
| Narration and pacing | Intelligibility, awkward speed changes, pauses, subtitle timing |
| Visual relevance | Whether visuals explain the claim and whether repeated imagery makes the video feel generic |
| Cost | Sidecar's preflight visual output estimate, actual provider charge attributable to the run, rejected generations, and production time |
| Outcome, if published | Video ID, publish date, retention and revenue after a consistent observation window |

Do not publish a video with a failed technical gate or an unsupported factual claim. Resolve the defect, regenerate only affected scenes when possible, and repeat the check. Human reviewers decide whether hook, narration, and visuals are good enough; the current code does not score these reliably.

## Comparison and sharing

Compare image and hybrid by accepted-video rate, actual cost per accepted video, and reviewer notes first. The sidecar estimate is not the provider bill: it excludes prompt tokens, narration, retries, taxes, and any charges from a failed run without a rendered video. Reconcile bills separately in the private record. Use retention and revenue only after the same observation window and enough published samples. Do not infer audience preference from the nine legacy files in the technical baseline: they were not paired experiments and have no sidecars. Keep raw articles, bills, channel metrics, sidecars, and video files outside Git. Share only anonymized counts, aggregate costs, findings, and resulting code decisions in `STATUS.md` or `DECISIONS.md`.
