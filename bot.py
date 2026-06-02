import asyncio
import logging
import os
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
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
db = Database()


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


@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user = await db.get_user(message.from_user.id)
    if not user:
        await db.create_user(message.from_user.id, message.from_user.username or "")
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
        "🔑 Введи свой *WB API токен*:",
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
            f"❌ Не удалось подключиться к WB.\nОшибка: `{info}`\n\nПроверь токен и попробуй снова.",
            parse_mode="Markdown", reply_markup=main_menu()
        )
        await state.clear()
        return
    await db.save_wb_token(message.from_user.id, token)
    await state.clear()
    await message.answer(
        "✅ *WB подключён успешно!*\n\nБот будет автоматически проверять новые отзывы каждые *5 минут* и отвечать на них.\n\nМожешь закрыть бота — он работает в фоне 24/7 🚀",
        parse_mode="Markdown", reply_markup=main_menu()
    )


@dp.message(lambda m: m.text == "📊 Статистика")
async def cmd_stats(message: types.Message):
    stats = await db.get_stats(message.from_user.id)
    await message.answer(
        f"📊 *Твоя статистика:*\n\n✅ Сегодня: *{stats['today']}*\n📅 За месяц: *{stats['month']}*\n📦 Всего: *{stats['total']}*",
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
        "💳 *Тарифы:*\n\n🟢 *Старт* — 1 000 ₽/мес — до 300 отзывов\n🟡 *Бизнес* — 2 000 ₽/мес — до 700 отзывов\n🔴 *Про* — 3 000 ₽/мес — до 1 500 отзывов\n\nСейчас бот работает в *тестовом режиме* без лимитов.",
        parse_mode="Markdown"
    )


@dp.message(lambda m: m.text == "📋 История")
async def cmd_history(message: types.Message):
    history = await db.get_history(message.from_user.id, limit=5)
    if not history:
        await message.answer("📋 История пуста. Бот ещё не отвечал на отзывы.")
        return
    text = "📋 *Последние ответы:*\n\n"
    for i, h in enumerate(history, 1):
        stars = "⭐" * h.get("rating", 0)
        reply_preview = h['reply'][:80] if h.get('reply') else ''
        text += f"{i}. {stars}\n_{reply_preview}..._\n\n"
    await message.answer(text, parse_mode="Markdown")


@dp.message(lambda m: m.text == "🎁 Реферальная программа")
async def cmd_referral(message: types.Message):
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref{message.from_user.id}"
    await message.answer(
        f"🎁 *Реферальная программа:*\n\nПриглашай продавцов и получай *10%* от их оплаты.\n\nТвоя ссылка:\n`{ref_link}`",
        parse_mode="Markdown"
    )


@dp.message(lambda m: m.text == "⚙️ Профиль")
async def cmd_profile(message: types.Message):
    user = await db.get_user(message.from_user.id)
    has_wb = bool(user and user.get("wb_token"))
    await message.answer(
        f"⚙️ *Профиль:*\n\n👤 ID: `{message.from_user.id}`\n📛 Username: @{message.from_user.username or 'нет'}\n🟢 WB: *{'Подключён ✅' if has_wb else 'Не подключён ❌'}*\n\nДля сброса токена: /reset",
        parse_mode="Markdown"
    )


@dp.message(Command("reset"))
async def cmd_reset(message: types.Message):
    await db.save_wb_token(message.from_user.id, "")
    await message.answer("🔄 WB токен удалён. Введи новый через *🔑 Подключить API*", parse_mode="Markdown")


async def review_worker():
    logger.info("🔄 Review worker started")
    while True:
        try:
            users = await db.get_users_with_token()
            for user in users:
                uid = user["telegram_id"]
                token = user["wb_token"]
                if not token:
                    continue
                wb = WBClient(token)
                reviews = await wb.get_unanswered_reviews()
                if not reviews:
                    continue
                logger.info(f"User {uid}: found {len(reviews)} unanswered reviews")
                for review in reviews:
                    try:
                        already = await db.is_already_replied(review["id"])
                        if already:
                            continue
                        reply_text = await generate_reply(review)
                        success = await wb.post_reply(review["id"], reply_text)
                        if success:
                            await db.log_reply(uid, review["id"], review.get("productValuation", 0), reply_text)
                            logger.info(f"✅ Replied to review {review['id']}")
                        else:
                            logger.warning(f"❌ Failed to post reply for {review['id']}")
                    except Exception as e:
                        logger.error(f"Error processing review {review.get('id')}: {e}")
        except Exception as e:
            logger.error(f"Review worker error: {e}")
        await asyncio.sleep(300)


async def main():
    await db.init()
    asyncio.create_task(review_worker())
    logger.info("🚀 Bot started")
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
