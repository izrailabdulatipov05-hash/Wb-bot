import os
import logging
import aiohttp

logger = logging.getLogger(__name__)


async def generate_reply(review: dict) -> str:
    rating = review.get("productValuation", 3)
    text = review.get("text", "").strip()
    pros = review.get("pros", "").strip()
    cons = review.get("cons", "").strip()

    parts = []
    if text:
        parts.append(f"Отзыв: {text}")
    if pros:
        parts.append(f"Достоинства: {pros}")
    if cons:
        parts.append(f"Недостатки: {cons}")
    review_full = "\n".join(parts) if parts else "Без текста"

    if rating >= 4:
        tone = "Хороший отзыв. Поблагодари искренне, порадуйся что понравилось, пригласи вернуться."
    elif rating == 3:
        tone = "Нейтральный отзыв. Поблагодари за честность, извинись, скажи что учтёшь."
    else:
        tone = "Негативный отзыв. Извинись, не спорь, предложи написать в личку."

    system_prompt = "Ты вежливый менеджер на Wildberries. Отвечаешь на отзывы. По-русски, 2-4 предложения, без emoji."
    user_prompt = f"Оценка: {rating}/5\n{review_full}\n\nЗадача: {tone}\n\nНапиши ответ:"

    api_key = os.getenv("OPENAI_API_KEY")
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 300,
        "temperature": 0.7,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                data = await resp.json()
                return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"OpenAI error: {e}")
        if rating >= 4:
            return "Благодарим за отзыв! Рады что понравилось. Ждём вас снова!"
        return "Извините за неудобства. Напишите нам — обязательно разберёмся."
