# Shipping-capacity story audition

Prepared: 2026-10-29. This is an unapproved **next-topic** audition, separate from the current Jamsu Bridge visual pilot. The current milestone and spending state live in [STATUS.md](STATUS.md); the exact draft is [shipping_capacity_review_draft.json](shipping_capacity_review_draft.json). No model request or upload is authorized by this page.

## Source and story boundary

The single primary source is the [Federal Reserve Bank of St. Louis analysis published 2026-10-27](https://www.stlouisfed.org/on-the-economy/2026/oct/measuring-shipping-disruptions-satellite-data). The free RSS preview collected 13 candidates across the selected city, economy, and design categories. The project's `ContentExtractor` recovered this article's 1,730-word body and 2026-10-27 date without a paid model call. The extracted headings still include navigation, so the article body and figures were checked against the original page, not trusted solely because the word threshold passed.

| Narration or source background | Original article support | Visual proof and limit |
| --- | --- | --- |
| By early 2022, deployed capacity on U.S.-bound routes was more than 60% above its prepandemic level. | “The 2021 West Coast Port Crisis,” paragraph beginning “The COVID-19 pandemic supply chain crisis…” | Show **deployed capacity**, not a claim that 60% more cargo arrived. |
| Satellite AIS positions underlie the analysis; the article reconstructs nearly 59,000 U.S.-bound trips. The current narration mentions the satellite method, not the trip count. | “Tracking Container Ships from Space” | Original route model only; do not copy the article's map. |
| Overall shipping utilization fell from about 89% before the pandemic to below 70% during 2021–22. | “The 2021 West Coast Port Crisis” | Display a ratio of effective to potential shipping capacity; do not label it total volume or a price increase. |
| The Asia-to-U.S.-West-Coast route fell from about 92% before 2020 to 53% by late 2021; port waiting and slower sailing both mattered. | Same section's route-specific paragraphs | Keep this route's dates and denominator separate from the overall U.S.-bound figures. Show waiting and reduced movement in the shot itself. |
| More deployed vessels alone do not reveal usable shipping service. | Inference from the article's potential/effective-capacity definition and crisis comparison | End as an explanation of the measure, not a claim that total cargo delivered fell. |

The first free Yuna read took 50.2 seconds and felt numerically dense in the script review. Trimming the method and shortening the reveal brought the current read to 38.4 seconds: [audio and scene text](../outputs/evaluation/shipping_capacity_20261029/scratch_audio_v4/story_review.html). Its `narration.json` binds all five complete local audio files to the draft's SHA-256. Earlier audio versions remain ignored under `outputs/` for comparison.

## Next gate

Judge whether the paradox is interesting through the complete audio before making any visual asset. If it is, build an original, small-scale route proof where added ships, queueing, and slower motion are readable without a large chart over the footage. Recheck each narrated number on the source page, and review a first frame and raw silent motion before any separately approved Veo request. Do not treat the current `image` draft mode, provisional durations, or music direction as an approved final production recipe.
