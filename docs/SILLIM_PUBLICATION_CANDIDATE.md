# Sillim publication candidate

Updated: 2026-10-29. This is the editorial handoff for the current private review cut. It is **not** approval to change YouTube visibility. [STATUS.md](STATUS.md) owns the current decision state; [SILLIM_VISUAL_ALIGNMENT_REVIEW.md](SILLIM_VISUAL_ALIGNMENT_REVIEW.md) owns the source and scene evidence.

## Current evidence

- The owner watched the complete 37.5-second retimed cut and judged it a posting candidate. No specific scene objection was named.
- The saved MP4 still passes the technical gate and matches its production-record SHA-256. The record has the primary source URL, the selected Arulo “RnB 2” music, and a private YouTube ID. The music file matches its local license/hash record.
- YouTube Studio showed the current title and description, **private** visibility, completed SD/HD processing, “not made for kids,” and AI-use disclosure set to **yes**. The description names the [Seoul City release](https://www.seoul.go.kr/news/news_report.do?nttNo=457013&srchCtgry=465), identifies the footage as AI explanation, and attributes the approximately 10 cm stream effect to the city rather than a measured reduction in flood damage.
- The city page marks its own images and document as Korea Open Government License Type 4, including noncommercial and no-derivative conditions. The cut uses generated scenes and local editor graphics, not those source images. [Mixkit's music license](https://mixkit.co/license/modal/musicFree/) permits its music in commercial YouTube videos; a platform claim remains possible.
- On 2026-10-29, the saved MP4 again passed `check_video_quality`, matched the sidecar's SHA-256, and `BGMManager.get_track_path("candidate_rnb_2.mp3")` accepted the local music file against its tracked hash. The [Seoul release](https://www.seoul.go.kr/news/news_report.do?nttNo=457013&srchCtgry=465) still states the ground/B1 bus space, B2 35,000-ton reservoir, and approximately 10 cm stream-level effect. [Mixkit's listing](https://mixkit.co/free-stock-music/tag/soft/) still identifies “RnB 2” by Arulo, and its [free music license](https://mixkit.co/license/modal/musicFree/) still allows commercial YouTube use. This local/source check did not revisit the video's current Studio visibility or claim status; the last Studio check above was on 2026-10-26.

## Proposed public metadata — not applied

**Title:** 버스 차고지 아래에 빗물 3만 5천 톤을 담는 이유 | 신림 공영차고지

**Description:**

> 신림 공영차고지는 지상과 지하 1층을 버스 공간으로, 지하 2층을 빗물저류조로 씁니다. 저류조는 폭우 때 빗물을 일시적으로 저장합니다. 서울시는 이 시설이 도림천 수위를 약 10cm 낮추는 효과가 있다고 설명합니다. 이는 시의 발표 수치이며, 이 영상은 실제 침수 피해 감소를 측정한 결과라고 주장하지 않습니다.
>
> 화면은 구조와 기능을 설명하기 위한 AI 생성·편집 영상입니다. 실제 시설의 정밀 도면이나 현장 홍수 영상이 아닙니다.
>
> 출처: https://www.seoul.go.kr/news/news_report.do?nttNo=457013&srchCtgry=465
>
> 음악: RnB 2 — Arulo (Mixkit)

The proposal removes “비공개 검토본” from the current title and description. Keep the YouTube AI-use answer at **yes**, set Korean as the title/description and video language in Studio, and verify the final visible metadata before any public release. Studio currently says external description links require one-time channel verification to become clickable; the URL remains readable as text without it. Future API uploads now set the supported title/description `defaultLanguage` to `ko`; this does not change the existing private video or set its spoken-audio language through the upload API.

## Remaining decision

The owner must approve the exact final metadata and the visibility change separately. Per-video billed cost is still unallocated because provider billing is aggregate and delayed; keep the private scorecard's acceptance, public-release, and audience fields blank until their respective decisions or observations. Do not resume repeating paid production solely because this cut is a candidate.
