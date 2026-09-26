"""Единая сборка chat template для SFT и генерации."""

from typing import Any


def _template_kwargs(params: dict) -> dict:
    """Параметры самого токенизатора — никаких вручную выписанных спецтокенов."""
    value = params["model"].get("enable_thinking")
    return {} if value is None else {"enable_thinking": value}


def split_messages(messages: list[dict]) -> tuple[list[dict], dict]:
    """Последняя реплика — единственный ответ, который обучаем предсказывать."""
    if not messages or messages[-1]["role"] != "assistant":
        raise ValueError("последняя реплика диалога обязана быть ответом ассистента")
    return messages[:-1], messages[-1]


def build_chat_text(
    tokenizer: Any,
    messages: list[dict],
    params: dict,
    add_generation_prompt: bool,
) -> str:
    """Один шаблон Qwen3 и для train, и для inference.

    При inference ассистент ещё не написал ответ, но заголовок ассистента,
    включая шаблон non-thinking режима, должен войти в промпт и маску.
    """
    if add_generation_prompt:
        messages, _answer = split_messages(messages)
    return tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=add_generation_prompt,
        **_template_kwargs(params),
    )


def prompt_token_len(
    tokenizer: Any,
    prompt_text: str,
    full_ids: list[int],
    full_offsets: list[tuple[int, int]],
) -> tuple[int, bool]:
    """Граница маски: совпадающий префикс токенов, иначе символьные офсеты.

    Если BPE склеил границу, токен, который начинается внутри промпта,
    маскируем: нельзя обучать модель на части инструкции пользователя.
    """
    prompt_ids = tokenizer(prompt_text, add_special_tokens=False)["input_ids"]
    n = len(prompt_ids)
    if full_ids[:n] == prompt_ids:
        return n, False

    boundary = len(prompt_text)
    for i, (start, _end) in enumerate(full_offsets):
        if start >= boundary:
            return i, True
    raise ValueError(
        "не нашли начало ответа ассистента: за границей промпта не осталось "
        "ни одного токена"
    )
