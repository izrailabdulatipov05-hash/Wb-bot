import asyncio
    import os
    import unittest
    from contextlib import asynccontextmanager
    from unittest.mock import patch

    os.environ.setdefault("BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk")

    import bot as bot_module


    class FakeDatabase:
      def __init__(self, tokens=1):
          self._lock = asyncio.Lock()
          self.tokens = tokens
          self.reserve_calls = 0
          self.refund_calls = 0
          self.logged_replies = []

      @asynccontextmanager
      async def generation_lock(self, telegram_id):
          if self._lock.locked():
              yield None
              return
          await self._lock.acquire()
          try:
              yield self
          finally:
              self._lock.release()

      async def _is_replied(self, feedback_id, conn=None):
          return False

      async def reserve_token(self, telegram_id, conn=None):
          self.reserve_calls += 1
          if self.tokens <= 0:
              return False
          self.tokens -= 1
          return True

      async def refund_token(self, telegram_id, conn=None):
          self.refund_calls += 1
          self.tokens += 1

      async def _log_reply(self, telegram_id, feedback_id, rating, reply, conn=None):
          self.logged_replies.append(feedback_id)

      async def get_user(self, telegram_id, conn=None):
          return {"tokens_left": self.tokens}


    class FakeWB:
      post_calls = 0

      def __init__(self, token):
          pass

      async def get_unanswered_reviews(self):
          return [{"id": "review-1", "productValuation": 5}]

      async def post_reply(self, feedback_id, text):
          type(self).post_calls += 1
          return True


    class GenerationConcurrencyTests(unittest.TestCase):
      def run_async(self, coroutine):
          return asyncio.run(coroutine)

      def test_same_user_has_only_one_parallel_generation(self):
          database = FakeDatabase(tokens=1)
          FakeWB.post_calls = 0
          generate_calls = 0

          async def generate(_review):
              nonlocal generate_calls
              generate_calls += 1
              await asyncio.sleep(0)
              return "reply"

          async def send_message(*args, **kwargs):
              pass

          async def run():
              with patch.object(bot_module, "db", database), \
                   patch.object(bot_module, "WBClient", FakeWB), \
                   patch.object(bot_module, "generate_reply", generate), \
                   patch.object(bot_module, "bot", type("Bot", (), {"send_message": send_message})()):
                  await asyncio.gather(
                      bot_module.process_user({"telegram_id": 42, "wb_token": "token"}),
                      bot_module.process_user({"telegram_id": 42, "wb_token": "token"}),
                  )

          self.run_async(run())
          self.assertEqual(generate_calls, 1)
          self.assertEqual(FakeWB.post_calls, 1)
          self.assertEqual(database.reserve_calls, 1)
          self.assertEqual(database.refund_calls, 0)
          self.assertEqual(database.logged_replies, ["review-1"])

      def test_failed_generation_refunds_reserved_token(self):
          database = FakeDatabase(tokens=1)

          async def generate(_review):
              raise RuntimeError("generation failed")

          async def run():
              with patch.object(bot_module, "db", database), \
                   patch.object(bot_module, "WBClient", FakeWB), \
                   patch.object(bot_module, "generate_reply", generate):
                  await bot_module.process_user({"telegram_id": 42, "wb_token": "token"})

          self.run_async(run())
          self.assertEqual(database.reserve_calls, 1)
          self.assertEqual(database.refund_calls, 1)
          self.assertEqual(database.tokens, 1)


    if __name__ == "__main__":
      unittest.main()
    