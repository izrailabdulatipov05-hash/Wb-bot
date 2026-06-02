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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
db = Database()


class SetupStates(StatesGroup):
    waiting_wb_token = State()


# ── Клавиатура главного меню ──
def main_menu():
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Статистика"),  KeyboardButton(text="🔑 Подключить API")],
            [KeyboardButton(text="💰 Баланс"),       KeyboardButton(text="💳 Тарифы")],
            [KeyboardButton(text="📋 История"),      KeyboardButton(text="🎁 Реферальная программа")],
            [KeyboardButton(text="⚙️ Профиль")],
        ],
        resize_keyboard=True
    )
    return kb


# ── /start ──
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user = db.get_user(message.from_user.id)
    if not user:
        db.create_user(message.from_user.id, message.from_user.username or "")
    await message.answer(
        "👋 *Привет!* Я автоматически отвечаю на отзывы покупателей на Wildberries.\n\n"
        "🤖 Использую GPT-4 — отвечаю как живой менеджер:\n"
        "• Хорошая оценка → благодарю покупателя\n"
        "• Плохая оценка → сглаживаю ситуацию\n\n"
        "Для начала подключи свой WB API ключ кнопкой ниже 👇",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )


# ── Подключить API ──
@dp.message(lambda m: m.text == "🔑 Подключить API")
async def ask_wb_token(message: types.Message, state: FSMContext):
    await state.set_state(SetupStates.waiting_wb_token)
    await message.answer(
        "🔑 Введи свой *WB API токен* (токен продавца из личного кабинета WB):\n\n"
        "Найти: *WB Seller* → Настройки → Доступ к API",
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
            parse_mode="Markdown",
            reply_markup=main_menu()
        )
        await state.clear()
        return

    db.save_wb_token(message.from_user.id, token)
    await state.clear()
    await message.answer(
        f"✅ *WB подключён успешно!*\n\n"
        f"Бот будет автоматически проверять новые отзывы каждые *5 минут* и отвечать на них.\n\n"
        f"Можешь закрыть бота — он работает в фоне 24/7 🚀",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )


# ── Статистика ──
@dp.message(lambda m: m.text == "📊 Статистика")
async def cmd_stats(message: types.Message):
    stats = db.get_stats(message.from_user.id)
    await message.answer(
        f"📊 *Твоя статистика:*\n\n"
        f"✅ Отвечено сегодня: *{stats['today']}*\n"
        f"📅 За этот месяц: *{stats['month']}*\n"
        f"📦 Всего за всё время: *{stats['total']}*\n",
        parse_mode="Markdown"
    )


# ── Баланс ──
@dp.message(lambda m: m.text == "💰 Баланс")
async def cmd_balance(message: types.Message):
    user = db.get_user(message.from_user.id)
    plan = user.get("plan", "Нет подписки") if user else "Нет подписки"
    limit = user.get("review_limit", 0) if user else 0
    used = db.get_stats(message.from_user.id)["month"]
    remaining = max(0, limit - used)
    await message.answer(
        f"💰 *Баланс и подписка:*\n\n"
        f"📋 Тариф: *{plan}*\n"
        f"🔢 Лимит отзывов: *{limit}/мес*\n"
        f"✅ Использовано: *{used}*\n"
        f"⏳ Остаток: *{remaining}*\n\n"
        f"Для оплаты напиши: /pay",
        parse_mode="Markdown"
    )


# ── Тарифы ──
@dp.message(lambda m: m.text == "💳 Тарифы")
async def cmd_tariffs(message: types.Message):
    await message.answer(
        "💳 *Тарифы:*\n\n"
        "🟢 *Старт* — 1 000 ₽/мес\n   до 300 отзывов\n\n"
        "🟡 *Бизнес* — 2 000 ₽/мес\n   до 700 отзывов\n\n"
        "🔴 *Про* — 3 000 ₽/мес\n   до 1 500 отзывов\n\n"
        "Оплата подключается позже. Сейчас бот работает в *тестовом режиме* без лимитов.\n\n"
        "Для активации тарифа напиши: /pay",
        parse_mode="Markdown"
    )


# ── История ──
@dp.message(lambda m: m.text == "📋 История")
async def cmd_history(message: types.Message):
    history = db.get_history(message.from_user.id, limit=5)
    if not history:
        await message.answer("📋 История пуста. Бот ещё не отвечал на отзывы.")
        return

    text = "📋 *Последние 5 ответов:*\n\n"
    for i, h in enumerate(history, 1):
        stars = "⭐" * h.get("rating", 0)
        text += f"{i}. {stars} — {h['created_at'][:10]}\n"
        text += f"   _{h['reply'][:80]}..._\n\n"
    await message.answer(text, parse_mode="Markdown")


# ── Реферальная программа ──
@dp.message(lambda m: m.text == "🎁 Реферальная программа")
async def cmd_referral(message: types.Message):
    ref_link = f"https://t.me/{(await bot.get_me()).username}?start=ref{message.from_user.id}"
    await message.answer(
        f"🎁 *Реферальная программа:*\n\n"
        f"Приглашай других продавцов и получай *10%* от их оплаты.\n\n"
        f"Твоя ссылка:\n`{ref_link}`\n\n"
        f"_(скоро будет подключена)_",
        parse_mode="Markdown"
    )


# ── Профиль ──
@dp.message(lambda m: m.text == "⚙️ Профиль")
async def cmd_profile(message: types.Message):
    user = db.get_user(message.from_user.id)
    has_wb = bool(user and user.get("wb_token"))
    await message.answer(
        f"⚙️ *Профиль:*\n\n"
        f"👤 ID: `{message.from_user.id}`\n"
        f"📛 Username: @{message.from_user.username or 'нет'}\n"
        f"🟢 WB подключён: *{'Да ✅' if has_wb else 'Нет ❌'}*\n\n"
        f"Для сброса токена нажми /reset",
        parse_mode="Markdown"
    )


@dp.message(Command("reset"))
async def cmd_reset(message: types.Message):
    db.save_wb_token(message.from_user.id, "")
    await message.answer("🔄 WB токен удалён. Введи новый через кнопку *🔑 Подключить API*", parse_mode="Markdown")


# ── Фоновый процесс: обход отзывов ──
async def review_worker():
    logger.info("🔄 Review worker started")
    while True:
        try:
            users = db.get_users_with_token()
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
                        reply_text = await generate_reply(review)
                        success = await wb.post_reply(review["id"], reply_text)
                        if success:
                            db.log_reply(uid, review["id"], review.get("productValuation", 0), reply_text)
                            logger.info(f"✅ Replied to review {review['id']}")
                        else:
                            logger.warning(f"❌ Failed to post reply for review {review['id']}")
                    except Exception as e:
                        logger.error(f"Error processing review {review.get('id')}: {e}")
        except Exception as e:
            logger.error(f"Review worker error: {e}")
        await asyncio.sleep(300)  # каждые 5 минут


async def main():
    db.init()
    asyncio.create_task(review_worker())
    logger.info("🚀 Bot started")
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
