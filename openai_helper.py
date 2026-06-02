import os
import logging
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


async def generate_reply(review: dict) -> str:
    rating = review.get("productValuation", 3)
    text = review.get("text", "").strip()
    pros = review.get("pros", "").strip()
    cons = review.get("cons", "").strip()

    # Собираем текст отзыва
    review_parts = []
    if text:
        review_parts.append(f"Отзыв: {text}")
    if pros:
        review_parts.append(f"Достоинства: {pros}")
    if cons:
        review_parts.append(f"Недостатки: {cons}")
    review_full = "\n".join(review_parts) if review_parts else "Без текста"

    # Инструкция в зависимости от оценки
    if rating >= 4:
        tone_instruction = (
            "Это ХОРОШИЙ отзыв (оценка 4-5 звёзд). "
            "Напиши искреннюю благодарность покупателю. "
            "Порадуйся что товар понравился. "
            "Пригласи вернуться снова. "
            "Тон: тёплый, благодарный, живой."
        )
    elif rating == 3:
        tone_instruction = (
            "Это НЕЙТРАЛЬНЫЙ отзыв (оценка 3 звезды). "
            "Поблагодари за честный отзыв. "
            "Извинись за то что не всё понравилось. "
            "Скажи что учтёшь замечания. "
            "Тон: вежливый, конструктивный."
        )
    else:
        tone_instruction = (
            "Это НЕГАТИВНЫЙ отзыв (оценка 1-2 звезды). "
            "Не оправдывайся и не спорь. "
            "Принеси искренние извинения. "
            "Скажи что хочешь разобраться в ситуации. "
            "Предложи написать в личные сообщения для решения проблемы. "
            "Тон: сочувствующий, профессиональный, готовый помочь."
        )

    system_prompt = (
        "Ты — вежливый и профессиональный менеджер по работе с клиентами интернет-магазина на Wildberries. "
        "Пишешь ответы на отзывы покупателей от имени продавца. "
        "Правила:\n"
        "- Пиши по-русски, грамотно\n"
        "- Ответ 2-4 предложения, не длиннее\n"
        "- Звучи как живой человек, не как робот\n"
        "- Не используй шаблонные фразы типа 'Уважаемый покупатель'\n"
        "- Не упоминай конкурентов\n"
        "- Не обещай того что не можешь выполнить\n"
        "- Никаких emoji в ответе\n"
    )

    user_prompt = (
        f"Оценка покупателя: {rating} из 5\n"
        f"{review_full}\n\n"
        f"Задача: {tone_instruction}\n\n"
        f"Напиши ответ продавца:"
    )

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=300,
            temperature=0.7,
        )
        reply = response.choices[0].message.content.strip()
        logger.info(f"GPT reply generated ({len(reply)} chars) for rating={rating}")
        return reply
    except Exception as e:
        logger.error(f"OpenAI error: {e}")
        # Запасной ответ если OpenAI недоступен
        if rating >= 4:
            return "Благодарим за ваш отзыв! Рады, что товар вам понравился. Ждём вас снова!"
        else:
            return "Приносим извинения за доставленные неудобства. Напишите нам в личные сообщения — обязательно разберёмся в ситуации."
