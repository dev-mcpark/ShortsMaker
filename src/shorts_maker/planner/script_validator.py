import json
from openai import AsyncOpenAI
from pydantic import BaseModel
from typing import Optional, Dict, Any
from shorts_maker.utils.logger import get_logger
from shorts_maker.utils.config import settings

class ValidationResult(BaseModel):
    is_valid: bool
    reason: str = ""
    feedback: str = ""
    score: int = 0
    is_advertising: bool = False  # 광고성 콘텐츠 여부

class ScriptValidator:
    def __init__(self):
        self.logger = get_logger(__name__)

        # API 키 검증
        if not settings.openai_api_key:
            raise ValueError(
                "OPENAI_API_KEY is not configured. "
                "Please set it in .env file or config/.env"
            )

        self.client = AsyncOpenAI(api_key=settings.openai_api_key)

    async def validate_script(self, script: Any) -> ValidationResult:
        """
        Validates a ShortsScript object.
        Uses Any for script type to avoid circular imports with script_planner.
        """
        self.logger.info(f"🧐 Validating script: {script.title}")
        
        # Serialize script to text for the LLM
        script_content = script.model_dump_json(indent=2)

        prompt = f"""
        You are a **Strict YouTube Shorts Chief Editor**.
        Review the following Shorts Script Plan for production readiness.

        **Review Criteria:**
        1. **Policy Safety:** No hate speech, explicit violence, sexual content, or copyright infringement.
        2. **Engagement (Hook):** The first 5 seconds (Scene 1) MUST be gripping/surprising. No "Did you know?" or slow intros.
        3. **Visual Feasibility:** Visual descriptions must be concrete (objects, lighting, style) for AI Video Generators. Avoid abstract concepts.
        4. **Length:** Total duration must be under 60 seconds (ideally 40-50s).
        5. **Language:** Must be Natural Korean suitable for narration.
        6. **NO ADVERTISING/PROMOTIONAL CONTENT:** This is CRITICAL. Reject any script that:
           - Promotes or recommends specific products, brands, or services (e.g., "Buy X", "Try Y", "Use Z service")
           - Contains affiliate marketing language or call-to-action for purchases
           - Mentions specific company names, brand names, or product names in a promotional context
           - Reads like a product review, sponsored content, or advertisement
           - Includes pricing information, discount codes, or purchase links
           - Uses phrases like "지금 바로 구매", "할인", "무료 체험", "링크 클릭", "구독하고", "특가", "한정 판매"
           - Focuses on a single product/service's benefits without balanced information

           **EXCEPTION:** Educational content that objectively discusses technology, trends, or phenomena is OK,
           even if it mentions company/product names in an informational (non-promotional) context.

        **Script Data:**
        {script_content}

        Output JSON format:
        {{
            "is_valid": boolean,  // true if it passes ALL criteria
            "score": number,      // 0-100
            "reason": "string",   // Short reason key (e.g., "weak_hook", "policy_violation", "too_long", "advertising_content", "promotional_tone")
            "feedback": "string"  // Specific instructions on how to fix it. If valid, leave empty.
        }}

        **Strict Rules for Failure:**
        - Score < 70 -> Fail
        - Weak Hook -> Fail
        - Abstract Visuals -> Fail
        - Advertising/Promotional Content -> Fail (reason: "advertising_content")
        """

        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            result_data = json.loads(response.choices[0].message.content)

            # 광고성 콘텐츠 여부 플래그 설정
            is_ad = result_data.get("reason", "").lower() in ["advertising_content", "promotional_tone", "promotional_content"]
            result_data["is_advertising"] = is_ad

            result = ValidationResult(**result_data)

            if result.is_valid:
                self.logger.info(f"✅ Script Validated! Score: {result.score}")
            else:
                if result.is_advertising:
                    self.logger.warning(f"🚫 Script Rejected (ADVERTISING). Score: {result.score}. Reason: {result.reason}")
                    self.logger.info(f"⚠️ 광고성 콘텐츠가 감지되었습니다: {result.feedback}")
                else:
                    self.logger.warning(f"❌ Script Rejected. Score: {result.score}. Reason: {result.reason}")
                    self.logger.info(f"Feedback: {result.feedback}")

            return result
            
        except Exception as e:
            self.logger.error(f"Validation failed due to error: {e}")
            # 보안: 검증 오류 시 Fail-Close (통과시키지 않음)
            return ValidationResult(
                is_valid=False,
                score=0,
                reason="validation_error",
                feedback="검증 중 오류가 발생했습니다. 수동 검토가 필요합니다."
            )
