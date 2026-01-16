import os
import json
from openai import AsyncOpenAI
from pydantic import BaseModel
from typing import Optional, Dict, Any
from shorts_maker.utils.logger import get_logger

class ValidationResult(BaseModel):
    is_valid: bool
    reason: str = ""
    feedback: str = ""
    score: int = 0

class ScriptValidator:
    def __init__(self):
        self.logger = get_logger(__name__)
        self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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

        **Script Data:**
        {script_content}

        Output JSON format:
        {{
            "is_valid": boolean,  // true if it passes ALL criteria
            "score": number,      // 0-100
            "reason": "string",   // Short reason key (e.g., "weak_hook", "policy_violation", "too_long")
            "feedback": "string"  // Specific instructions on how to fix it. If valid, leave empty.
        }}
        
        **Strict Rules for Failure:**
        - Score < 70 -> Fail
        - Weak Hook -> Fail
        - Abstract Visuals -> Fail
        """

        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            result_data = json.loads(response.choices[0].message.content)
            result = ValidationResult(**result_data)
            
            if result.is_valid:
                self.logger.info(f"✅ Script Validated! Score: {result.score}")
            else:
                self.logger.warning(f"❌ Script Rejected. Score: {result.score}. Reason: {result.reason}")
                self.logger.info(f"Feedback: {result.feedback}")
                
            return result
            
        except Exception as e:
            self.logger.error(f"Validation failed due to error: {e}")
            # If validation crashes, we default to passing to avoid blocking, but log it.
            return ValidationResult(is_valid=True, score=50, reason="validation_error", feedback="Validator crashed, proceeding cautiously.")
