import aiohttp
import logging

logger = logging.getLogger(__name__)

WB_BASE = "https://feedbacks-api.wildberries.ru"
WB_CONTENT = "https://common-api.wildberries.ru"


class WBClient:
    def __init__(self, token: str):
        self.token = token
        self.headers = {
            "Authorization": token,
            "Content-Type": "application/json",
        }

    async def test_connection(self):
        # Используем ping эндпоинт — не блокируется
        url = f"{WB_CONTENT}/ping"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers=self.headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status in (200, 401, 403):
                        return True, "OK"
                    text = await resp.text()
                    return False, f"HTTP {resp.status}: {text[:200]}"
        except Exception as e:
            return False, str(e)

    async def get_unanswered_reviews(self):
        url = f"{WB_BASE}/api/v1/feedbacks"
        params = {"isAnswered": "false", "take": 20, "skip": 0}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers=self.headers, params=params,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status == 429:
                        logger.warning("WB rate limit, skip this round")
                        return []
                    if resp.status != 200:
                        text = await resp.text()
                        logger.error(f"WB error {resp.status}: {text[:300]}")
                        return []
                    data = await resp.json()
                    feedbacks = data.get("data", {}).get("feedbacks", [])
                    logger.info(f"WB returned {len(feedbacks)} feedbacks")
                    return feedbacks
        except Exception as e:
            logger.error(f"WB exception: {e}")
            return []

    async def post_reply(self, feedback_id: str, text: str) -> bool:
        url = f"{WB_BASE}/api/v1/feedbacks"
        payload = {"id": feedback_id, "text": text}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.patch(
                    url, headers=self.headers, json=payload,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    body = await resp.text()
                    logger.info(f"WB reply {feedback_id}: {resp.status} {body[:100]}")
                    return resp.status in (200, 201, 204)
        except Exception as e:
            logger.error(f"WB post_reply: {e}")
            return False
