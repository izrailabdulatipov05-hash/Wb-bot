import asyncio
import logging
import os
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from wb_api import WBClient
from openai_helper import generate_reply
from database import Database

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
RAILWAY_TOKEN = os.getenv("RAILWAY_TOKEN", "")
RAILWAY_PROJECT_ID = "e0a82bf1-41e5-4856-96da-30364133c4a4"
RAILWAY_SERVICE_ID = "a6a9061e-4bd6-42f6-b81f-0deaad117e69"
RAILWAY_ENV_ID = "fd7b05c8-87db-45ff-9a9d-b2e1c0248bb1"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
db = Database()

# Токены в памяти
wb_tokens = {}

# Загружаем WB_TOKEN из env при старте если есть
_startup_wb_token = os.getenv("WB_TOKEN", "")


class SetupStates(StatesGroup):
    waiting_wb_token = State()


def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Статистика"),  KeyboardButton(text="🔑 Подключить API")],
            [KeyboardButton(text="💰 Баланс"),       KeyboardButton(text="💳 Тарифы")],
            [KeyboardButton(text="📋 История"),      KeyboardButton(text="🎁 Реферальная программа")],
            [KeyboardButton(text="⚙️ Профиль")],
        ],
        resize_keyboard=True
    )


async def save_token_to_railway(token: str):
    """Сохраняет WB токен в Railway Variables чтобы не терялся при перезапуске"""
    if not RAILWAY_TOKEN:
        logger.warning("RAILWAY_TOKEN not set, skipping Railway save")
        return
    url = "https://backboard.railway.app/graphql/v2"
    query = """
    mutation upsertVariables($input: VariableCollectionUpsertInput!) {
        variableCollectionUpsert(input: $input)
    }
    """
    variables = {
        "input": {
            "projectId": RAILWAY_PROJECT_ID,
            "serviceId": RAILWAY_SERVICE_ID,
            "environmentId": RAILWAY_ENV_ID,
            "variables": {"WB_TOKEN": token}
        }
    }
    headers = {
        "Authorization": f"Bearer {RAILWAY_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json={"query": query, "variables": variables},
                                   headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
                if "errors" in data:
                    logger.error(f"Railway API error: {data['errors']}")
                else:
                    logger.info("✅ WB token saved to Railway Variables")
    except Exception as e:
        logger.error(f"Railway API exception: {e}")


@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 *Привет!* Я автоматически отвечаю на отзывы покупателей на Wildberries.\n\n"
        "🤖 Использую GPT-4 — отвечаю как живой менеджер:\n"
        "• Хорошая оценка → благодарю покупателя\n"
        "• Плохая оценка → сглаживаю ситуацию\n\n"
        "Для начала подключи свой WB API ключ кнопкой ниже 👇",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )


@dp.message(lambda m: m.text == "🔑 Подключить API")
async def ask_wb_token(message: types.Message, state: FSMContext):
    await state.set_state(SetupStates.waiting_wb_token)
    await message.answer(
        "🔑 Введи свой *WB API токен* (раздел Вопросы и отзывы):",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )


@dp.message(SetupStates.waiting_wb_token)
async def save_wb_token(message: types.Message, state: FSMContext):
    token = message.text.strip()
    if len(token) < 50:
        await message.answer("❌ Токен слишком короткий. Попробуй ещё раз:")
        return
    await message.answer("⏳ Проверяю токен...")
    wb = WBClient(token)
    ok, info = await wb.test_connection()
    if not ok:
        await message.answer(
            f"❌ Не удалось подключиться к WB.\nОшибка: `{info}`",
            parse_mode="Markdown", reply_markup=main_menu()
        )
        await state.clear()
        return

    # Сохраняем в памяти
    wb_tokens[message.from_user.id] = token

    # Сохраняем в Railway Variables — не потеряется при перезапуске
    await save_token_to_railway(token)

    await state.clear()
    await message.answer(
        "✅ *WB подключён успешно!*\n\nБот проверяет отзывы каждые *5 минут* и отвечает автоматически 🚀\n\nМожешь закрыть бота — работает в фоне 24/7",
        parse_mode="Markdown", reply_markup=main_menu()
    )
    logger.info(f"User {message.from_user.id} connected WB token")


@dp.message(lambda m: m.text == "📊 Статистика")
async def cmd_stats(message: types.Message):
    count = db.get_count(message.from_user.id)
    await message.answer(
        f"📊 *Статистика:*\n\n✅ Всего отвечено: *{count}*",
        parse_mode="Markdown"
    )


@dp.message(lambda m: m.text == "💰 Баланс")
async def cmd_balance(message: types.Message):
    await message.answer(
        "💰 *Баланс:*\n\n📋 Тариф: *Тестовый*\n🔢 Лимит: *безлимит*\n\nОплата подключается позже.",
        parse_mode="Markdown"
    )


@dp.message(lambda m: m.text == "💳 Тарифы")
async def cmd_tariffs(message: types.Message):
    await message.answer(
        "💳 *Тарифы:*\n\n"
        "🟢 *Старт* — 1 000 ₽/мес — до 300 отзывов\n"
        "🟡 *Бизнес* — 2 000 ₽/мес — до 700 отзывов\n"
        "🔴 *Про* — 3 000 ₽/мес — до 1 500 отзывов\n\n"
        "Сейчас бот работает в *тестовом режиме* без лимитов.",
        parse_mode="Markdown"
    )


@dp.message(lambda m: m.text == "📋 История")
async def cmd_history(message: types.Message):
    history = db.get_history(message.from_user.id)
    if not history:
        await message.answer("📋 История пуста.")
        return
    text = "📋 *Последние ответы:*\n\n"
    for i, h in enumerate(history, 1):
        stars = "⭐" * h.get("rating", 0)
        text += f"{i}. {stars}\n_{h['reply'][:80]}..._\n\n"
    await message.answer(text, parse_mode="Markdown")


@dp.message(lambda m: m.text == "🎁 Реферальная программа")
async def cmd_referral(message: types.Message):
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref{message.from_user.id}"
    await message.answer(
        f"🎁 *Реферальная программа:*\n\nПриглашай продавцов и получай *10%*.\n\nТвоя ссылка:\n`{ref_link}`",
        parse_mode="Markdown"
    )


@dp.message(lambda m: m.text == "⚙️ Профиль")
async def cmd_profile(message: types.Message):
    has_wb = message.from_user.id in wb_tokens or bool(_startup_wb_token)
    await message.answer(
        f"⚙️ *Профиль:*\n\n"
        f"👤 ID: `{message.from_user.id}`\n"
        f"🟢 WB: *{'Подключён ✅' if has_wb else 'Не подключён ❌'}*\n\n"
        f"Для сброса: /reset",
        parse_mode="Markdown"
    )


@dp.message(Command("reset"))
async def cmd_reset(message: types.Message):
    wb_tokens.pop(message.from_user.id, None)
    await message.answer("🔄 Токен сброшен. Введи новый через *🔑 Подключить API*", parse_mode="Markdown")


async def review_worker():
    logger.info("🔄 Review worker started")
    await asyncio.sleep(10)

    while True:
        try:
            active_tokens = dict(wb_tokens)
            if _startup_wb_token and 0 not in active_tokens:
                active_tokens[0] = _startup_wb_token

            if active_tokens:
                logger.info(f"Checking reviews for {len(active_tokens)} users")

            for uid, token in active_tokens.items():
                wb = WBClient(token)
                reviews = await wb.get_unanswered_reviews()
                if not reviews:
                    logger.info(f"No unanswered reviews for user {uid}")
                    continue
                logger.info(f"User {uid}: found {len(reviews)} unanswered reviews")
                for review in reviews:
                    try:
                        fid = review.get("id", "")
                        if db.is_replied(fid):
                            continue
                        reply_text = await generate_reply(review)
                        success = await wb.post_reply(fid, reply_text)
                        if success:
                            db.log_reply(uid, fid, review.get("productValuation", 0), reply_text)
                            logger.info(f"✅ Replied to {fid}")
                        else:
                            logger.warning(f"❌ Failed to post reply for {fid}")
                    except Exception as e:
                        logger.error(f"Error on review {review.get('id')}: {e}")
                await asyncio.sleep(2)

        except Exception as e:
            logger.error(f"Review worker error: {e}")

        await asyncio.sleep(300)


async def main():
    db.init()
    asyncio.create_task(review_worker())
    logger.info("🚀 Bot started")
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
