# Visual prompt practice

Reviewed: 2026-10-02. This guide records public techniques selected for ShortsMaker's source-grounded, low-cost workflow. [STATUS.md](STATUS.md) owns current production evidence; [DECISIONS.md](DECISIONS.md) owns durable choices. A well-written prompt improves direction but cannot prove that a generated frame is accurate.

## Evidence and application

| Public guidance | Use here | Reason |
| --- | --- | --- |
| [Google's Veo 3.1 guide](https://cloud.google.com/blog/products/ai-machine-learning/ultimate-prompting-guide-for-veo-3-1/) structures a prompt around camera, subject, action, context, and style. | Ask for those concrete parts, with one motion instruction for a short hook. | Gives the model a clear shot without boilerplate cinematic effects. |
| [Google's video best practices](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/video/best-practice) recommend a single focused moment in short clips and clear, direct language. | One scene per paid clip; one camera or subject movement. Keep audio off because narration is added by the editor. | Reduces conflicting requests and expensive unusable output. |
| [Gemini image prompting guidance](https://ai.google.dev/gemini-api/docs/image-generation#best-practices) recommends specific context, composition, and positive descriptions of the intended scene. | Use a static subject, setting, and layout. Reserve the lower third for editor captions; avoid asking the image model to render exact labels. | The first pilot produced invented robot labels despite a `no text` instruction. |
| [YouTube's AI disclosure guidance](https://support.google.com/youtube/answer/14328491) requires disclosure for realistic AI-generated scenes that did not occur. [Its monetization rules](https://support.google.com/youtube/answer/1311392) emphasize original, varied value over generic mass production. | Keep source photos, stylized explanation, and realistic reconstruction distinct in review. Check upload disclosure and the video's original explanation before publishing. | Prompt quality alone does not satisfy publication or monetization review. |

## Prompt brief before a paid request

1. Read the primary source for actual place, time, subject count, equipment, roles, and what is a future goal rather than a completed event.
2. Choose one point the viewer should understand in this scene. For Veo, specify one shot and one movement. For Gemini stills, specify one static composition.
3. If the source cannot support a realistic depiction, request a visibly stylized explanatory image. Use a separately cleared source photo or a local diagram when accuracy depends on exact equipment or labels.
4. Leave exact words, numbers, credits, and subtitles to the editor. Review the resulting frame for extra objects, readable invented labels, setting mismatch, and any appearance of real footage.

Example for the NASA pilot: `A clearly stylized top-down diagram of one scouting drone and two distinct ground rovers on a grassy research field; one point of interest; simple shapes; calm open lower third.` The location and robot count come from the [NASA article](https://science.nasa.gov/blogs/planetary-expeditions/2026/09/15/nasa-field-tests-ai-fleet-capability-for-science-exploration/). If a real device appearance is needed, choose the credited source photo in editorial review instead of inventing one.

## Deferred techniques

- Reference-image and image-to-video generation can improve continuity, but rights and factual identity of the input need review, and each extra visual request costs money. Try only against a measured quality gain.
- Automatic prompt enhancement or paid multi-variant retries add calls before there is evidence that they raise acceptance rate. Keep one planned prompt and repair only rejected scenes.
- Timed multi-shot prompts may be useful for longer video, but the current six-second hook benefits from the provider's single-moment guidance.

Any prompt wording or model wrapper change that alters generated visuals must change the scene cache identity. Existing saved outputs remain on disk but must not silently stand in for a new prompt's result.
