import aiohttp
import asyncio
import logging

logger = logging.getLogger(__name__)

WB_BASE = "https://feedbacks-api.wildberries.ru"
WB_COMMON = "https://common-api.wildberries.ru"


class WBClient:
    def __init__(self, token: str):
        self.token = token.strip()
        self.headers = {
            "Authorization": self.token,
            "Content-Type": "application/json",
        }

    async def test_connection(self):
        url = f"{WB_COMMON}/ping"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status in (200, 401, 403):
                        return True, "OK"
                    text = await resp.text()
                    return False, f"HTTP {resp.status}: {text[:200]}"
        except Exception as e:
            return False, str(e)

    async def get_unanswered_reviews(self):
        url = f"{WB_BASE}/api/v1/feedbacks"
        params = {"isAnswered": "false", "take": 10, "skip": 0}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 429:
                        logger.warning("WB rate limit on GET, waiting 60s")
                        await asyncio.sleep(60)
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
        # Пауза перед запросом — соблюдаем лимит 1 req/sec
        await asyncio.sleep(2)
        url = f"{WB_BASE}/api/v1/feedbacks/answer"
        payload = {"id": feedback_id, "text": text}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, headers=self.headers, json=payload,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    body = await resp.text()
                    logger.info(f"WB answer {feedback_id}: status={resp.status} body={body[:200]}")
                    if resp.status == 429:
                        logger.warning("WB rate limit on POST, waiting 60s")
                        await asyncio.sleep(60)
                        return False
                    return resp.status in (200, 201, 204)
        except Exception as e:
            logger.error(f"WB post_reply error: {e}")
            return False
