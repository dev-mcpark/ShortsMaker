# Story and shot-planning model comparison

Updated: 2026-11-07. This is a preparation plan, not an activated model migration or spending approval. [STATUS.md](STATUS.md) owns the current episode and account evidence.

## Why compare again

The owner found the Cheonggye finished video's story development and visual composition unsatisfactory and requested reconsidering GPT models. Record that cut as needing improvement, not as an accepted scheduled cycle. The owner retains publication control. Technical checks and an agent's intermediate approvals did not establish editorial quality.

The retained script moves through missing driver seat, circular seating, passenger/crew counts, night route and fare/card rules. A useful comparison must test a connected question, development and payoff, rather than merely polish that list. Model choice is a hypothesis; prompts, topic fit and editing also affect the finished result.

## Candidate and compatibility

Proposed quality/cost candidate: **`gpt-6.1-sol`** for story and shot planning. The [official model page](https://developers.openai.com/api/docs/models/gpt-6.1-sol) lists Standard text input/output at **$2/$10 per million tokens**, Chat Completions and structured outputs. This is a candidate, not a claim that it improves this project's videos or is available to this account.

The [official migration guide](https://developers.openai.com/api/docs/guides/latest-model) requires a supported reasoning effort (`low` is the initial comparison setting for Sol), omitting sampling parameters during reasoning. Keep the existing text-only Chat Completions/JSON-object contract, Standard service tier, no tools, `max_retries=0`, and a 4,000-token completion ceiling including reasoning. Do not change voice, Google models, upload permissions or automatic fallback as part of this comparison.

On November 7, a single read-only Sol metadata query returned **404**. The project's returned newer-model list contains only **`gpt-6.1-terra` and `gpt-6-luna`**. Listing or retrieving a model does not prove inference access: the separately approved November 5 Terra request returned **403** after successful metadata retrieval. Its reservation and identity-verification history remain intact. No new inference was sent. Resolve actual access before activating a candidate; do not repeat the failed request or organization-verification loop, create another organization, or assume a model name change fixes access.

## Smallest useful comparison

1. Retain the exact primary-source excerpt, original GPT-4o script and owner feedback. The ignored [comparison plan](../outputs/evaluation/model_upgrade_feedback_20261107/comparison_plan.json) binds the proposed request and source hashes. Do not repurchase RSS scoring, article analysis or a GPT-4o baseline.
2. After access is resolved and a separate comparison scope is authorized, submit **one text rewrite**, without automatic retry. The prepared request's conservative reservation is **$0.059124**: 9,562 UTF-8 input-bound units at $2/million plus 4,000 completion tokens at $10/million. Recompute against the exact bytes, current rates and monthly room before execution. The uploaded episode's **$0.004777** remaining allowance is insufficient and cannot be reopened for this experiment. Preparing this plan changes no ledger rows or production defaults.
3. Compare against the retained baseline on one source-backed question, whether later scenes advance or answer it, spoken Korean, payoff, source accuracy and each shot's visible explanatory role. Do not invent a human's position, controls, safety procedure or autonomy level to explain the missing driver seat. Keep dated service facts in their article context. A passing model score alone cannot decide story interest.
4. Validate the returned JSON with existing script models, duration/scene limits and source checks. Empty, truncated, unsupported or failed responses stop; they do not authorize another call. Build a zero-provider-cost spoken/storyboard audition before buying any new voice, image or Veo output. Owner feedback on that comparison is the editorial evidence.
5. Only adopt a new production model after actual request compatibility, budget accounting and editorial comparison pass. Update shared role constants, reservation prices and all affected call sites/tests together. Keep fast scoring and speech as separate roles. Existing source/frame/raw gates, exclusions and attached-video identity stay in force.

## Evidence boundary

The installed SDK serialized the proposed request and parsed a fixture response through an in-memory HTTPX transport with exactly one POST. This establishes local request construction only, not provider acceptance, model access, source judgment or improved storytelling. No project generation, new reservation, upload or visibility change occurred during preparation. Private source excerpts, request payloads, exports and feedback records remain outside Git.
