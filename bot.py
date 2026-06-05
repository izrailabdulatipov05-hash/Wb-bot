import asyncio
import logging
import os
import aiohttp
from datetime import datetime
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

# Тарифы: название -> (токены, дней, цена)
PLANS = {
    "trial":    ("Пробный 🆓",     10,    30,  0),
    "start":    ("Старт 🟢",     1000,    30,  1000),
    "business": ("Бизнес 🟡",    2000,    30,  2000),
    "pro":      ("Про 🔴",       3000,    30,  3000),
    "premium":  ("Премиум 💎",   4000,    30,  4000),
    "ultra":    ("Ультра 🚀",    5000,    30,  5000),
    "yearly":   ("Годовой 👑",  12000,   365, 10000),
}


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
    if not RAILWAY_TOKEN:
        return
    url = "https://backboard.railway.app/graphql/v2"
    query = """mutation upsertVariables($input: VariableCollectionUpsertInput!) {
        variableCollectionUpsert(input: $input) }"""
    variables = {"input": {
        "projectId": RAILWAY_PROJECT_ID,
        "serviceId": RAILWAY_SERVICE_ID,
        "environmentId": RAILWAY_ENV_ID,
        "variables": {"WB_TOKEN": token}
    }}
    headers = {"Authorization": f"Bearer {RAILWAY_TOKEN}", "Content-Type": "application/json"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json={"query": query, "variables": variables},
                                   headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
                if "errors" not in data:
                    logger.info("✅ WB token saved to Railway")
    except Exception as e:
        logger.error(f"Railway API error: {e}")


@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await db.create_user(message.from_user.id, message.from_user.username or "")
    user = await db.get_user(message.from_user.id)
    tokens = user.get("tokens_left", 10) if user else 10
    await message.answer(
        "👋 *Привет!* Я автоматически отвечаю на отзывы покупателей на Wildberries.\n\n"
        "🤖 GPT-4 отвечает как живой менеджер:\n"
        "• ⭐⭐⭐⭐⭐ → благодарю покупателя\n"
        "• ⭐⭐ → сглаживаю негатив\n\n"
        f"🎁 У тебя *{tokens} пробных отзывов* бесплатно!\n\n"
        "Подключи WB API токен кнопкой ниже 👇",
        parse_mode="Markdown", reply_markup=main_menu()
    )


@dp.message(lambda m: m.text == "🔑 Подключить API")
async def ask_wb_token(message: types.Message, state: FSMContext):
    await state.set_state(SetupStates.waiting_wb_token)
    await message.answer(
        "🔑 Введи свой *WB API токен*\n\n"
        "Где взять: WB Seller → Настройки → Доступ к API → создай токен с доступом *Вопросы и отзывы*",
        parse_mode="Markdown", reply_markup=ReplyKeyboardRemove()
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
        await message.answer(f"❌ Ошибка подключения: `{info}`",
                           parse_mode="Markdown", reply_markup=main_menu())
        await state.clear()
        return
    await db.save_wb_token(message.from_user.id, token)
    await save_token_to_railway(token)
    await state.clear()
    await message.answer(
        "✅ *WB подключён!*\n\nБот проверяет отзывы каждые 5 минут и отвечает автоматически 🚀",
        parse_mode="Markdown", reply_markup=main_menu()
    )


@dp.message(lambda m: m.text == "📊 Статистика")
async def cmd_stats(message: types.Message):
    count = await db._get_count(message.from_user.id)
    user = await db.get_user(message.from_user.id)
    tokens = user.get("tokens_left", 0) if user else 0
    await message.answer(
        f"📊 *Статистика:*\n\n"
        f"✅ Всего отвечено: *{count}*\n"
        f"🎟 Токенов осталось: *{tokens}*",
        parse_mode="Markdown"
    )


@dp.message(lambda m: m.text == "💰 Баланс")
async def cmd_balance(message: types.Message):
    user = await db.get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала нажми /start")
        return
    plan_key = user.get("plan", "trial")
    plan_name = PLANS.get(plan_key, ("Неизвестный", 0, 0, 0))[0]
    tokens_left = user.get("tokens_left", 0)
    tokens_total = user.get("tokens_total", 10)
    expires = user.get("sub_expires")
    expires_str = expires.strftime("%d.%m.%Y") if expires else "—"
    await message.answer(
        f"💰 *Баланс:*\n\n"
        f"📋 Тариф: *{plan_name}*\n"
        f"🎟 Токенов: *{tokens_left}* из *{tokens_total}*\n"
        f"📅 Действует до: *{expires_str}*\n\n"
        f"Для оплаты напиши /pay",
        parse_mode="Markdown"
    )


@dp.message(lambda m: m.text == "💳 Тарифы")
async def cmd_tariffs(message: types.Message):
    await message.answer(
        "💳 *Тарифы:*\n\n"
        "🆓 *Пробный* — бесплатно — 10 отзывов\n\n"
        "🟢 *Старт* — 1 000 ₽/мес — 1 000 отзывов\n"
        "🟡 *Бизнес* — 2 000 ₽/мес — 2 000 отзывов\n"
        "🔴 *Про* — 3 000 ₽/мес — 3 000 отзывов\n"
        "💎 *Премиум* — 4 000 ₽/мес — 4 000 отзывов\n"
        "🚀 *Ультра* — 5 000 ₽/мес — 5 000 отзывов\n"
        "👑 *Годовой* — 10 000 ₽/год — 12 000 отзывов\n\n"
        "⚠️ Неиспользованные токены сгорают по истечении срока.\n"
        "⚠️ Если токены закончатся раньше — нужно пополнить.\n\n"
        "Для оплаты: /pay",
        parse_mode="Markdown"
    )


@dp.message(Command("pay"))
async def cmd_pay(message: types.Message):
    await message.answer(
        "💳 *Оплата подписки*\n\n"
        "Оплата будет подключена в ближайшее время.\n\n"
        "Пока бот работает в *тестовом режиме* — 10 отзывов бесплатно 🎁",
        parse_mode="Markdown"
    )


@dp.message(lambda m: m.text == "📋 История")
async def cmd_history(message: types.Message):
    history = await db._get_history(message.from_user.id, 5)
    if not history:
        await message.answer("📋 История пуста.")
        return
    text = "📋 *Последние ответы:*\n\n"
    for i, h in enumerate(history, 1):
        stars = "⭐" * (h.get("rating") or 0)
        created = h.get("created_at")
        date_str = created.strftime("%d.%m %H:%M") if created else ""
        text += f"{i}. {stars} {date_str}\n_{str(h.get('reply',''))[:80]}..._\n\n"
    await message.answer(text, parse_mode="Markdown")


@dp.message(lambda m: m.text == "🎁 Реферальная программа")
async def cmd_referral(message: types.Message):
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref{message.from_user.id}"
    await message.answer(
        f"🎁 *Реферальная программа:*\n\n"
        f"Приглашай продавцов и получай *10%* от их оплаты.\n\n"
        f"Твоя ссылка:\n`{ref_link}`\n\n"
        f"_(скоро будет активирована)_",
        parse_mode="Markdown"
    )


@dp.message(lambda m: m.text == "⚙️ Профиль")
async def cmd_profile(message: types.Message):
    user = await db.get_user(message.from_user.id)
    has_wb = bool(user and user.get("wb_token"))
    plan_key = user.get("plan", "trial") if user else "trial"
    plan_name = PLANS.get(plan_key, ("Неизвестный",))[0]
    await message.answer(
        f"⚙️ *Профиль:*\n\n"
        f"👤 ID: `{message.from_user.id}`\n"
        f"📋 Тариф: *{plan_name}*\n"
        f"🔗 WB API: *{'✅ Подключён' if has_wb else '❌ Не подключён'}*\n\n"
        f"/reset — сбросить WB токен",
        parse_mode="Markdown"
    )


@dp.message(Command("reset"))
async def cmd_reset(message: types.Message):
    await db.save_wb_token(message.from_user.id, "")
    await message.answer("🔄 Токен сброшен. Введи новый через *🔑 Подключить API*", parse_mode="Markdown")


async def notify_expiring():
    """Уведомляет пользователей за день до истечения подписки"""
    while True:
        try:
            expiring = await db.get_users_expiring_soon()
            for uid in expiring:
                try:
                    await bot.send_message(uid,
                        "⚠️ *Внимание!*\n\n"
                        "Завтра истекает ваша подписка.\n"
                        "После истечения бот перестанет отвечать на отзывы.\n\n"
                        "Продлите подписку: /pay",
                        parse_mode="Markdown"
                    )
                    await db.mark_expiry_notified(uid)
                    logger.info(f"Sent expiry notification to {uid}")
                except Exception as e:
                    logger.error(f"Error notifying {uid}: {e}")
        except Exception as e:
            logger.error(f"Notify worker error: {e}")
        await asyncio.sleep(3600)  # проверяем каждый час


async def review_worker():
    logger.info("🔄 Review worker started")
    await asyncio.sleep(15)
    while True:
        try:
            users = await db.get_users_with_token()
            for user in users:
                uid = user["telegram_id"]
                token = user["wb_token"]
                wb = WBClient(token)
                reviews = await wb.get_unanswered_reviews()
                if not reviews:
                    continue

                logger.info(f"User {uid}: {len(reviews)} unanswered reviews")
                replied_count = 0

                for review in reviews:
                    fid = review.get("id", "")
                    if await db._is_replied(fid):
                        continue

                    # Проверяем и списываем токен
                    has_token = await db.use_token(uid)
                    if not has_token:
                        try:
                            await bot.send_message(uid,
                                "⚠️ *Токены закончились!*\n\n"
                                "Бот приостановил ответы на отзывы.\n"
                                "Пополните подписку: /pay",
                                parse_mode="Markdown"
                            )
                        except Exception:
                            pass
                        break

                    reply_text = await generate_reply(review)
                    success = await wb.post_reply(fid, reply_text)
                    if success:
                        await db._log_reply(uid, fid, review.get("productValuation", 0), reply_text)
                        replied_count += 1
                        logger.info(f"✅ Replied to {fid}")
                    await asyncio.sleep(2)

                # Уведомляем пользователя если ответили на отзывы
                if replied_count > 0:
                    try:
                        user_data = await db.get_user(uid)
                        tokens_left = user_data.get("tokens_left", 0) if user_data else 0
                        await bot.send_message(uid,
                            f"✅ *Ответил на {replied_count} отзыв(а)*\n\n"
                            f"🎟 Токенов осталось: *{tokens_left}*",
                            parse_mode="Markdown"
                        )
                    except Exception as e:
                        logger.error(f"Error sending notification to {uid}: {e}")

        except Exception as e:
            logger.error(f"Review worker error: {e}")
        await asyncio.sleep(300)


async def main():
    await db._init()
    asyncio.create_task(review_worker())
    asyncio.create_task(notify_expiring())
    logger.info("🚀 Bot started")
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
