import os
from functools import lru_cache
from google import genai
from google.genai import types, errors

from context_builder import build_context_for_llm
from persona import umamusume
from quota import _check_quota_or_msg, add_usage, _estimate_output_tokens_from_config


MODEL_NAME = "gemini-2.5-flash"

_config_kwargs = dict(
    temperature=0.8,
    max_output_tokens=150,
    top_p=0.95,
    top_k=40,
    stop_sequences=["트레이너 씨:", "User:"],
    system_instruction=umamusume,
    thinking_config=types.ThinkingConfig(thinking_budget=0),
)

CONFIG = genai.types.GenerateContentConfig(**_config_kwargs)


@lru_cache(maxsize=1)
def _get_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "환경변수 GEMINI_API_KEY가 설정되어 있지 않습니다. .env 파일 또는 시스템 환경변수에 키를 등록해주세요."
        )
    return genai.Client(api_key=api_key)


def generate_genai(chat_id: int, user_name: str, user_msg: str) -> str:
    prompt = build_context_for_llm(
        chat_id=chat_id,
        user_name=user_name,
        user_msg=user_msg,
        budget_chars=3000,
    )

    # === [가드] 호출 전 한도 검사 ==========================================
    limit_msg = _check_quota_or_msg(chat_id, input_chars=len(prompt), config=CONFIG)
    if limit_msg:
        return limit_msg
    # ========================================================================

    client = _get_client()

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=CONFIG,
        )
    except errors.ServerError as exc:
        print(f"[llm] ServerError: {exc}")
        return "잠시 과자 좀 먹고요... 조금 뒤에 다시 부탁해 주실래요?"
    except errors.GoogleAPIError as exc:  # includes ClientError, PermissionDenied 등
        print(f"[llm] GoogleAPIError: {exc}")
        return "어라... 뭔가 멍하네요. 잠시만요..?"
    except Exception as exc:  # defensive catch-all so bot stays alive
        print(f"[llm] Unexpected error: {exc}")
        return "엣, 죄송해요... 방금 뭐라고 하셨죠?"

    # === [기록] 호출 후 사용량 누적 =========================================
    add_usage(chat_id, input_chars=len(prompt), output_tokens=_estimate_output_tokens_from_config(CONFIG))
    # ========================================================================

    if hasattr(response, "text"):
        print(f"LLM response: {response.text}")

    candidates = getattr(response, "candidates", None) or []
    if candidates:
        candidate = candidates[0]
        parts = getattr(candidate, "content", None)
        text = None
        if parts and getattr(parts, "parts", None):
            first_part = parts.parts[0]
            text = getattr(first_part, "text", None)

        if candidate.finish_reason == "MAX_TOKENS" and text:
            return f"{text} ...라는걸로요."
        if text:
            return text

    return "에... 머릿속 통신 상태가 영 좋지 않은 모양인데요." 