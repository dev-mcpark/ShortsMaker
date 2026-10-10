# Sillim Veo opening pilot

Prepared and attempted: 2026-10-10. The owner found the [`nova` review cut](../outputs/evaluation/sillim_depot_nova_review.html) broadly okay and thought Veo footage could make it a stronger Short. The owner then authorized one request within a **$0.15 visual ceiling**. [STATUS.md](STATUS.md) owns the current review state; this page holds the exact attempted shot and acceptance checks.

After comparing the zero-API opening alternative, the owner preferred its motion but said a final cut needs Veo-generated footage. The next staged, five-scene proposal is in [SILLIM_VEO_CUT_PLAN.md](SILLIM_VEO_CUT_PLAN.md); this rejected pilot grants no further API spending authority.

## Result

One 4-second silent 720p Lite clip was generated and saved under ignored `outputs/evaluation/sillim_veo_lite/opening.mp4`. [The private comparison page](../outputs/evaluation/sillim_veo_lite_review.html) shows that raw result beside the existing whole cut. Sampled frames have a large literal `9:16` in the image and invented route-style text, side markings, and plate on the bus. This fails the unlettered, generic explanatory-visual gate. **Reject the clip; do not splice or publish it.** The existing `nova` cut remains the baseline; no retry, re-edit, or upload ran. The prompt wrapper's literal aspect-ratio phrase may have contributed to the large number, but that cause is not proven. The generator now requests one output explicitly and leaves aspect ratio to API configuration instead of repeating `9:16` in prose. That change has not been tested with another paid clip.

## One-shot edit

Replace only the first **3.2 seconds** of scene 1 with a visibly illustrative moving bus-depot shot. At 3.2 seconds, cut to the retained local diagram, which then reveals the 35,000-ton cue and the question at its existing narration beats. Reuse scenes 2–5, the approved five-scene text, retained `nova` files, RnB 2 music, and dark soft captions. Add a visible `AI 설명용 애니메이션` label over the generated portion. The baseline is `outputs/final_shorts_1791593633330339000.mp4`; no YouTube upload is part of this pilot.

The [Seoul City release](https://www.seoul.go.kr/news/news_report.do?nttNo=457013&srchCtgry=465) supports a bus depot with a rainwater reservoir below it, but it is not visual evidence for a particular bus, facade, entrance, or camera view. The page's own reuse notice forbids commercial reuse and alteration of its media. The Veo shot must look like an original explanation, not footage of the actual facility, and must not show the underground answer before the diagram does.

## Exact generation brief

- Model: `veo-3.1-lite-generate-001`, one silent 4-second 9:16 clip at 720p in `us-central1`; one attempt and one output. [Google's model page](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/veo/3-1-generate) lists that duration, resolution, aspect ratio, region, and model ID.
- `visual_description`: `A visibly stylized isometric 3D illustration of a generic Korean municipal bus depot at street level, not a reconstruction of a real site. One unbranded dark teal city bus slowly enters a simple depot bay. Calm daylight, cream background and dark teal accents matching a clean editorial infographic. The ground stays opaque, with no underground structure or flood shown. Plain surfaces without signs, route numbers, logos, labels, or people.`
- `motion_instruction`: `A single gentle left-to-right camera track follows the bus.`
- The existing `VideoGenerator` adds its standard one-shot, caption-space, and silent-footage wrapper. Review the saved clip for unintended text, realistic location claims, bus oddities, extra vehicles, and unusable movement before any edit. If it fails, keep the baseline and make no automatic retry.

## Cost and review gate

At the [Google Cloud Veo list rate](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing) rechecked on 2026-10-10, silent Veo 3.1 Lite 720p is **$0.03 per output second**, so the one 4-second request is **$0.12 estimated visual output** under the owner's $0.15 visual ceiling. This is a request estimate, not a provider billing cap or a final invoice; currency conversion, taxes, and provider accounting still need reconciliation. The prior $0.02 approval covered only Sillim narration. `MAX_VISUAL_COST_USD=0.15` and `PAID_PRODUCTION_ENABLED=true` applied to the single command only; the default remains off. The Cloud Billing page failed to load during preflight, so current account usage could not be verified; the last observed ₩926 was on 2026-10-07 against the ₩10,000 alerts-only monthly budget. The private request record and rejection note live under ignored `outputs/evaluation/sillim_veo_lite/`.

Only after an acceptable future clip, splice its first 3.2 seconds into scene 1 locally and render with `scripts/local_review.py`. Compare the new cut with the baseline using the **same** script, speech, music, captions, and remaining diagrams. Review the opening hook, factual appearance, visible explanatory label, transition, subtitle clearance, and full sound mix. `local_review.py` would report $0 **new output during re-edit** because the generated asset is passed as a manual clip; separately allocate this rejected $0.12 estimated request and reconcile its actual bill before cost-per-accepted-video reporting. Do not mark a cut accepted or upload it from a technical pass alone. Another provider request requires a new visual-round ceiling.
