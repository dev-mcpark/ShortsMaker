# Sillim narration-to-visual review

Reviewed: 2026-10-13. This evaluates the approved five-scene narration, exact prompts in `scripts/sillim_veo_round.py`, returned shots, and privately uploaded 37.5-second cut. It is **not** a new generation order or approval to replace the narration. [STATUS.md](STATUS.md) owns the active gate; [SILLIM_VEO_CUT_PLAN.md](SILLIM_VEO_CUT_PLAN.md) owns the completed request and cost record.

## Finding

The owner finds the footage attractive and the invented markings on the final building and bus unobtrusive. The larger defect is **explanatory alignment**: narration describes two site pressures, a three-level arrangement, temporary storage, and a stated water-level effect; the moving images mostly show miniature buildings, rain, water, and buses. Small local labels repeat nouns without showing their relationships. The largest gap was planned: scene 3's prompt explicitly requested `no visible floor diagram or technically exact cross-section`, although its narration needs the viewer to see which level holds each function. The raw-scene review said to add a verified floor diagram locally; the final edit added three text labels instead.

The script's five-step order is coherent and its concrete claims match the [Seoul City release](https://www.seoul.go.kr/news/news_report.do?nttNo=457013&srchCtgry=465): 35,000-tonne capacity; depot on the ground and basement 1; reservoir in basement 2; temporary storage intended to temper the stream's rise; and the city's stated roughly 10 cm effect. The source does not establish observed flood-damage reduction, an exact engineering cross-section, or a measured before/after river-level recording. Attribute the 10 cm to Seoul City. Use original artwork rather than the release's restrictively licensed photographs or diagrams.

| Scene | Visual proof needed | Current result | Assessment and cheapest fix |
| --- | --- | --- | --- |
| 1 — question | Bus depot and a hint of hidden rainwater storage. | Bus enters an attractive fictional depot; 35,000 tonnes is a small editor label. | Retain. Let scene 3 pay off the hidden-space question; enlarge the capacity cue. |
| 2 — two pressures | Both bus-depot space shortage **and** Dorimcheon flood risk lead to one site decision. | Prompt asks for a miniature block and approaching cloud; footage shows one rainy street. | A cloud is atmosphere, not a land-use conflict. Keep the Veo background and add two timed graphic panels converging on **one site**. |
| 3 — arrangement | Buses on ground and basement 1; rainwater reservoir on basement 2. | Prompt forbids a floor diagram; footage shows blank building sides; local text floats over it. | **Primary failure.** First prototype a large original three-band cutaway over the moving footage. Show two bus levels, then reveal the blue basin when named. Label it a conceptual section, not an exact site plan. |
| 4 — mechanism | Rainwater is held temporarily, reducing the immediate rush toward the stream. | Footage resembles a continuous waterfall into an open void; labels state storage and reduced rise. | Add an input → bounded tank-fill → smaller later outflow graphic timed to the voice. Do not portray a measured flow or disaster. |
| 5 — payoff | Daily transport and rain storage share one site; roughly 10 cm is Seoul City's stated effect. | Bus leaves beside a blue block, but opaque ground hides the vertical relation; the effect is small text. | Reuse a compact cutaway, highlight both operating modes, and make `약 10cm · 서울시 설명` readable. Fabricated signage is lower priority after owner feedback. |

## Script judgment

Keep the approved `nova` audio for the next local edit. Its question → two pressures → decision → mechanism → payoff progression is concise and source grounded, and re-recording now would spend money without testing the main visual hypothesis. If the visual revision still leaves confusion, test these **unapproved** wording candidates with scratch audio before buying new narration:

- Scene 3: `그래서 같은 땅을 위아래로 나눴습니다. 지상과 지하 1층은 차고지, 지하 2층은 빗물저류조입니다.` This states the spatial decision before the floor list.
- Scene 4: `도림천으로 한꺼번에 향할 빗물을 이곳에 잠시 모아, 하천 수위가 급히 오르는 걸 줄이려는 설계입니다.` This names the before-and-after flow. Check duration and the source boundary before replacing the approved line.

The last line's roughly 10 cm is a **city-stated effect**, not observed flood-damage reduction. Do not animate an exact before/after gauge as though measured.

## Next visual brief

Write one source-backed relationship the viewer must **see** per scene. Decide which shapes come from Veo and which factual labels or diagrams come from the editor. Camera moves and miniature style are secondary. At the first frame, reveal, and end, hide subtitles and mute audio: if the relationship cannot be inferred from shapes and motion, the image is only decoration.

1. **No-cost first:** composite explanatory graphics over existing Veo scenes 2–5 with the retained narration and music. The scene-3 three-level cutaway and scene-4 hold-and-release relationship are mandatory. Compare with the current private cut at matching timestamps. Keep the raw footage and original upload intact.
2. **Only if scene 3 still fails:** prepare an original, clearly fictional, unlettered first-frame cutaway with three broad bands. Keep exact Korean floor names and numbers in the editor. A single Veo scene-3 trial may then animate the miniature while keeping the bands fixed. The previous five-scene round is closed; any new paid request needs a fresh checked price, cap, and authorization.
3. **Candidate scene-3 prompt:** `Vertical 9:16, one continuous shot of a clearly fictional cream-and-dark-teal miniature depot shown as a simple isometric cutaway. Keep three broad horizontal bands fixed and visually separate: an open ground-level bus bay, one lower bus-parking band, and one deeper empty blue storage basin. One gentle camera push only; the bands do not rearrange or grow. Keep every surface blank and leave space for Korean labels added in editing. This is a conceptual illustration, not the actual Sillim structure. No readable writing, numbers, logos, roads, people, or disaster imagery.` Supply a reviewed first-frame image encoding the three bands; time the basin reveal locally rather than relying on Veo for a factual beat.
4. **If scenes 2 or 4 later need replacement:** scene 2 should show a fixed fictional site with constrained bus parking and a distinct rain-to-stream risk cue. Scene 4 should show water **collecting inside a bounded basin** and a separate smaller outlet. Test still storyboards before either paid call; adding more camera movement or negative terms to the old prompts will not supply the missing relationship.

The current [Google price list](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing) gives silent 720p Veo 3.1 Lite at USD 0.03 per output second, so one six-second scene-3 replacement has a **USD 0.18 list-price output estimate** before possible failed attempts or other charges. This is planning, not a bill or call authorization. This review made no paid API call or upload.

## No-provider-call comparison — 2026-10-13

`scripts/sillim_explanatory_composite.py` placed timed crops of the already source-checked local storyboard over the retained Veo footage in scenes 2–5. `scripts/local_review.py` then reused the same approved `nova` MP3s, RnB 2 mix, and soft captions. The resulting ignored `outputs/final_shorts_1791865576500296000.mp4` is 37.5 seconds at 1080×1920, passed `check_video_quality`, records five manual scenes and $0 **new** visual output estimate, and has no YouTube ID. The encoded audio stream hash matches the uploaded baseline exactly (`88590cae…efd58d47`), isolating the comparison to video. The [private side-by-side page](../outputs/evaluation/sillim_veo_round_20261013/explanatory_review.html) shows both cuts. Sampled final frames show the two-problem card, delayed third-floor reveal, and filling basin above the soft subtitles, with moving Veo footage still visible. This is an inexpensive visual-proof experiment, not yet an accepted design; the cards may feel too large or schematic on full playback, and scene 4's smaller later outflow remains a diagrammatic goal rather than a measured result. The owner must compare the full cuts before a further edit or paid request.

## Acceptance for the next private cut

- Silent, caption-hidden playback of scenes 2–4 conveys **two problems → three levels → temporary hold** through shapes and motion.
- Graphics appear with the corresponding narration, avoid the moving subject and soft subtitles, and identify the section as explanatory.
- The 35,000-tonne and roughly 10 cm claims are readable, attributed, and never shown as observed flood outcomes.
- The owner prefers the full explanatory revision over the attractive baseline. Editorial acceptance stays blank until then.
