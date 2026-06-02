import aiohttp
import logging

logger = logging.getLogger(__name__)

WB_BASE = "https://feedbacks-api.wildberries.ru"


class WBClient:
    def __init__(self, token: str):
        self.token = token
        self.headers = {
            "Authorization": token,
            "Content-Type": "application/json",
        }

    # ── Проверка подключения ──
    async def test_connection(self):
        url = f"{WB_BASE}/api/v1/feedbacks"
        params = {"isAnswered": False, "take": 1, "skip": 0}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        return True, "OK"
                    text = await resp.text()
                    return False, f"HTTP {resp.status}: {text[:200]}"
        except Exception as e:
            return False, str(e)

    # ── Получить НЕотвеченные отзывы ──
    async def get_unanswered_reviews(self):
        url = f"{WB_BASE}/api/v1/feedbacks"
        params = {
            "isAnswered": False,
            "take": 20,
            "skip": 0,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        logger.error(f"WB get_reviews error {resp.status}: {text[:300]}")
                        return []
                    data = await resp.json()
                    feedbacks = data.get("data", {}).get("feedbacks", [])
                    logger.info(f"WB returned {len(feedbacks)} unanswered feedbacks")
                    return feedbacks
        except Exception as e:
            logger.error(f"WB get_unanswered_reviews exception: {e}")
            return []

    # ── Опубликовать ответ на отзыв ──
    # КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ: правильный эндпоинт PATCH /api/v1/feedbacks
    async def post_reply(self, feedback_id: str, text: str) -> bool:
        url = f"{WB_BASE}/api/v1/feedbacks"
        payload = {
            "id": feedback_id,
            "text": text,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.patch(url, headers=self.headers, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    body = await resp.text()
                    logger.info(f"WB post_reply {feedback_id}: status={resp.status} body={body[:200]}")
                    if resp.status in (200, 201, 204):
                        return True
                    logger.error(f"WB post_reply failed {resp.status}: {body[:300]}")
                    return False
        except Exception as e:
            logger.error(f"WB post_reply exception: {e}")
            return False
