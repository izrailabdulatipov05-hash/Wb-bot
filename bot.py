import asyncio
import logging
import os
import aiohttp
import hashlib
import time
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web as aio_web
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

ROBOKASSA_LOGIN = "Wildberrieshelp"
ROBOKASSA_PASS1 = "XNd9upBb1m7z27EcuVjW"
ROBOKASSA_PASS2 = "dn46qte5kCp0ZNz8IVGi"


def generate_payment_url(amount: int, order_id: str, plan_key: str, description: str) -> str:
    # Робокасса требует, чтобы доп. параметры (shp_) шли в алфавитном порядке в конце строки хэша
    signature = hashlib.md5(
        f"{ROBOKASSA_LOGIN}:{amount}:{order_id}:{ROBOKASSA_PASS1}:shp_plan={plan_key}".encode()
    ).hexdigest()
    desc_encoded = description.replace(" ", "+")
    return (
        f"https://auth.robokassa.ru/Merchant/Index.aspx"
        f"?MerchantLogin={ROBOKASSA_LOGIN}"
        f"&OutSum={amount}"
        f"&InvId={order_id}"
        f"&Description={desc_encoded}"
        f"&SignatureValue={signature}"
        f"&shp_plan={plan_key}"
        f"&IsTest=0"
    )


async def robokassa_webhook(request, bot_instance, db_instance):
    try:
        data = await request.post()
        out_sum = data.get("OutSum", "")
        inv_id = data.get("InvId", "")
        signature = data.get("SignatureValue", "")
        plan_key = data.get("shp_plan", "")
        
        # Проверяем подпись Паролем #2
        expected = hashlib.md5(
            f"{out_sum}:{inv_id}:{ROBOKASSA_PASS2}:shp_plan={plan_key}".encode()
        ).hexdigest()
        
        if expected.lower() != signature.lower():
            return aio_web.Response(text="bad sign")
            
        # Отсекаем временную метку (последние 10 цифр), чтобы получить чистый Telegram ID пользователя
        inv_id_str = str(inv_id)
        if len(inv_id_str) > 10:
            telegram_id = int(inv_id_str[:-10])
        else:
            telegram_id = int(inv_id_str)
        
        PLAN_DATA = {
            "m1": (1000, 30), "m2": (2000, 60), "m3": (3000, 90),
            "m4": (4000, 120), "m5": (5000, 150), "m6": (6000, 180),
            "m12": (12000, 365),
        }
        if plan_key not in PLAN_DATA:
            return aio_web.Response(text="bad plan")
            
        tokens, days = PLAN_DATA[plan_key]
        await db_instance.activate_plan(telegram_id, plan_key, tokens, days)
        months = days // 30
        try:
            await bot_instance.send_message(
                telegram_id,
                f"✅ *Оплата прошла успешно!*\n\n"
                f"📋 Подписка: *{months} мес.*\n"
                f"🎟 Токенов: *{tokens:,}*\n\n"
                f"Бот уже работает и отвечает на ваши отзывы 🚀",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return aio_web.Response(text=f"OK{inv_id}")
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return aio_web.Response(text="error", status=500)



PLANS = {
    "m1":  ("1 месяц",   1000,   1,   1000),
    "m2":  ("2 месяца",  2000,   2,   2000),
    "m3":  ("3 месяца",  3000,   3,   3000),
    "m4":  ("4 месяца",  4000,   4,   4000),
    "m5":  ("5 месяцев", 5000,   5,   5000),
    "m6":  ("6 месяцев", 6000,   6,   6000),
    "m12": ("12 месяцев",12000, 12,  10000),
}


class SetupStates(StatesGroup):
    waiting_wb_token = State()


def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Статистика"),  KeyboardButton(text="🔑 Подключить API")],
            [KeyboardButton(text="💰 Баланс"),       KeyboardButton(text="💳 Тарифы")],
            [KeyboardButton(text="📋 История"),      KeyboardButton(text="🎁 Реферальная программа")],
            [KeyboardButton(text="⚙️ Профиль"),      KeyboardButton(text="🆘 Поддержка")],
            [KeyboardButton(text="📄 Оферта")],
        ],
        resize_keyboard=True
    )


def tariffs_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1️⃣  1 месяц — 1 000 ₽ (1 000 ответов)",  callback_data="plan_m1")],
        [InlineKeyboardButton(text="2️⃣  2 месяца — 2 000 ₽ (2 000 ответов)", callback_data="plan_m2")],
        [InlineKeyboardButton(text="3️⃣  3 месяца — 3 000 ₽ (3 000 ответов)", callback_data="plan_m3")],
        [InlineKeyboardButton(text="4️⃣  4 месяца — 4 000 ₽ (4 000 ответов)", callback_data="plan_m4")],
        [InlineKeyboardButton(text="5️⃣  5 месяцев — 5 000 ₽ (5 000 ответов)",callback_data="plan_m5")],
        [InlineKeyboardButton(text="6️⃣  6 месяцев — 6 000 ₽ (6 000 ответов)",callback_data="plan_m6")],
        [InlineKeyboardButton(text="👑  12 месяцев — 10 000 ₽ (12 000 ответов)", callback_data="plan_m12")],
    ])


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
    plan = user.get("plan", "trial") if user else "trial"

    if plan == "trial" and tokens <= 0:
        await message.answer(
            "👋 Добро пожаловать!\n\n"
            "⚠️ *Пробный период закончился.*\n\n"
            "Оформите подписку чтобы продолжить получать автоматические ответы на отзывы.",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )
        await message.answer("Выберите тариф:", reply_markup=tariffs_keyboard())
        return

    await message.answer(
        "👋 Добро пожаловать!\n\n"
        "Этот бот автоматически отвечает на отзывы покупателей в вашем магазине на Wildberries.\n\n"
        "Просто подключите API ключ — и бот сам будет отвечать на все новые отзывы.\n\n"
        f"🎁 Вам доступно *{tokens} бесплатных* ответов для знакомства с сервисом.\n\n"
        "Нажмите *🔑 Подключить API* чтобы начать 👇",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )


@dp.message(lambda m: m.text == "🔑 Подключить API")
async def ask_wb_token(message: types.Message, state: FSMContext):
    user = await db.get_user(message.from_user.id)
    if user and user.get("plan") == "trial" and user.get("tokens_left", 0) <= 0:
        await message.answer(
            "⚠️ *Пробный период закончился*\n\nОформите подписку чтобы продолжить:",
            parse_mode="Markdown"
        )
        await message.answer("Выберите тариф:", reply_markup=tariffs_keyboard())
        return
    await state.set_state(SetupStates.waiting_wb_token)
    await message.answer(
        "🔑 *Как получить WB API токен:*\n\n"
        "1️⃣ Зайдите в *WB Seller* (seller.wildberries.ru)\n"
        "2️⃣ Настройки → Доступ к API\n"
        "3️⃣ Нажмите *«Создать токен»*\n"
        "4️⃣ Выберите вкладку *«Вручную»*\n"
        "5️⃣ Тип токена: *«Персональный токен»*\n"
        "6️⃣ Поставьте галочку ✅ *«Вопросы и отзывы»*\n"
        "7️⃣ Уровень доступа: *«Чтение и запись»*\n"
        "8️⃣ Придумайте название, нажмите *«Создать токен»*\n"
        "9️⃣ Скопируйте токен и отправьте сюда 👇",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )


@dp.message(SetupStates.waiting_wb_token)
async def save_wb_token(message: types.Message, state: FSMContext):
    token = message.text.strip()
    if len(token) < 50:
        await message.answer("❌ Токен слишком короткий. Попробуйте ещё раз:")
        return
    await message.answer("⏳ Проверяю подключение...")
    wb = WBClient(token)
    ok, info = await wb.test_connection()
    if not ok:
        await message.answer(
            f"❌ Не удалось подключиться.\nОшибка: `{info}`",
            parse_mode="Markdown", reply_markup=main_menu()
        )
        await state.clear()
        return
    await db.save_wb_token(message.from_user.id, token)
    await save_token_to_railway(token)
    await state.clear()
    await message.answer(
        "✅ *Магазин подключён!*\n\n"
        "Бот проверяет новые отзывы каждые 5 минут и отвечает автоматически.\n\n"
        "Можете закрыть приложение — всё работает в фоне 24/7 🚀",
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
        await message.answer("Сначала нажмите /start")
        return
    plan_key = user.get("plan", "trial")
    months = PLANS.get(plan_key, (None,))[2] if plan_key in PLANS else None
    plan_name = f"{months} мес." if months else "Пробный 🆓"
    tokens_left = user.get("tokens_left", 0)
    tokens_total = user.get("tokens_total", 10)
    expires = user.get("sub_expires")
    expires_str = str(expires)[:10] if expires else "—"
    await message.answer(
        f"💰 *Баланс:*\n\n"
        f"📋 Подписка: *{plan_name}*\n"
        f"🎟 Токенов: *{tokens_left}* из *{tokens_total}*\n"
        f"📅 До: *{expires_str}*",
        parse_mode="Markdown"
    )


@dp.message(lambda m: m.text == "💳 Тарифы")
async def cmd_tariffs(message: types.Message):
    await message.answer(
        "💳 *Выберите тариф:*\n\n"
        "Каждый ответ на отзыв = 1 токен.\n"
        "Токены сгорают по окончании срока подписки.\n"
        "🎁 Новым пользователям — 10 ответов бесплатно.",
        parse_mode="Markdown",
        reply_markup=tariffs_keyboard()
    )


@dp.callback_query(F.data.startswith("plan_"))
async def handle_plan_select(callback: types.CallbackQuery):
    plan_key = callback.data.replace("plan_", "")
    if plan_key not in PLANS:
        await callback.answer("Неизвестный тариф")
        return
    name, tokens, months, price = PLANS[plan_key]
    
    # Склеиваем Telegram ID и текущее время в секундах (например, 87784930981718123456)
    # Это гарантирует 100% уникальность инвойса для Робокассы при каждом нажатии
    order_id = f"{callback.from_user.id}{int(time.time())}"
    
    pay_url = generate_payment_url(price, order_id, plan_key, f"Подписка WB HELP {name}")
    
    await callback.message.answer(
        f"📦 *{name}*\n\n"
        f"🎟 Токенов: *{tokens:,}*\n"
        f"💰 Стоимость: *{price:,} ₽*\n\n"
        f"После оплаты подписка активируется автоматически.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"💳 Оплатить {price:,} ₽", url=pay_url)],
            [InlineKeyboardButton(text="◀️ Назад к тарифам", callback_data="back_to_plans")]
        ])
    )
    await callback.answer()


@dp.callback_query(F.data == "back_to_plans")
async def back_to_plans(callback: types.CallbackQuery):
    await callback.message.answer("💳 Выберите тариф:", reply_markup=tariffs_keyboard())
    await callback.answer()


@dp.message(Command("pay"))
async def cmd_pay(message: types.Message):
    await message.answer(
        "💳 *Оплата подписки*\n\nВыберите тариф:",
        parse_mode="Markdown",
        reply_markup=tariffs_keyboard()
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
        created = str(h.get("created_at", ""))[:16]
        text += f"{i}. {stars} {created}\n_{str(h.get('reply',''))[:80]}..._\n\n"
    await message.answer(text, parse_mode="Markdown")


@dp.message(lambda m: m.text == "🎁 Реферальная программа")
async def cmd_referral(message: types.Message):
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref{message.from_user.id}"
    await message.answer(
        f"🎁 *Реферальная программа*\n\n"
        f"Приглашайте других продавцов и получайте *10%* от их оплаты.\n\n"
        f"Ваша ссылка:\n`{ref_link}`\n\n_(будет активирована в ближайшее время)_",
        parse_mode="Markdown"
    )


@dp.message(lambda m: m.text == "⚙️ Профиль")
async def cmd_profile(message: types.Message):
    user = await db.get_user(message.from_user.id)
    has_wb = bool(user and user.get("wb_token"))
    plan_key = user.get("plan", "trial") if user else "trial"
    if plan_key in PLANS:
        plan_name = f"{PLANS[plan_key][2]} мес."
    else:
        plan_name = "Пробный 🆓"
    await message.answer(
        f"⚙️ *Профиль:*\n\n"
        f"🆔 ID: `{message.from_user.id}`\n"
        f"📋 Подписка: *{plan_name}*\n"
        f"🔗 WB: *{'Подключён ✅' if has_wb else 'Не подключён ❌'}*\n\n"
        f"/reset — сбросить токен WB",
        parse_mode="Markdown"
    )


@dp.message(Command("reset"))
async def cmd_reset(message: types.Message):
    await db.save_wb_token(message.from_user.id, "")
    await message.answer("🔄 Токен сброшен. Введите новый через *🔑 Подключить API*", parse_mode="Markdown")


async def notify_expiring():
    while True:
        try:
            expiring = await db.get_users_expiring_soon()
            for uid in expiring:
                try:
                    await bot.send_message(uid,
                        "⚠️ *Подписка истекает завтра*\n\n"
                        "После окончания бот перестанет отвечать на отзывы.\n\n"
                        "Продлить подписку: /pay",
                        parse_mode="Markdown"
                    )
                    await db.mark_expiry_notified(uid)
                except Exception as e:
                    logger.error(f"Error notifying {uid}: {e}")
        except Exception as e:
            logger.error(f"Notify worker error: {e}")
        await asyncio.sleep(3600)


async def process_user(user: dict):
    uid = user["telegram_id"]
    token = user["wb_token"]
    try:
        wb = WBClient(token)
        reviews = await wb.get_unanswered_reviews()
        if not reviews:
            return
        logger.info(f"User {uid}: {len(reviews)} unanswered reviews")
        replied_count = 0
        for review in reviews:
            fid = review.get("id", "")
            if await db._is_replied(fid):
                continue
            has_token = await db.use_token(uid)
            if not has_token:
                try:
                    await bot.send_message(uid,
                        "⚠️ *Пробный период закончился*\n\n"
                        "Бот приостановил ответы на отзывы.\n"
                        "Оформите подписку: /pay",
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

        if replied_count > 0:
            try:
                user_data = await db.get_user(uid)
                tokens_left = user_data.get("tokens_left", 0) if user_data else 0
                word = "отзыв" if replied_count == 1 else "отзыва" if replied_count < 5 else "отзывов"
                await bot.send_message(uid,
                    f"✅ Ответил на *{replied_count} {word}*\n"
                    f"🎟 Осталось токенов: *{tokens_left}*",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Notification error {uid}: {e}")
    except Exception as e:
        logger.error(f"Error processing user {uid}: {e}")


async def review_worker():
    logger.info("🔄 Review worker started")
    await asyncio.sleep(15)
    while True:
        try:
            users = await db.get_users_with_token()
            if users:
                logger.info(f"Processing {len(users)} users in parallel")
                await asyncio.gather(*[process_user(u) for u in users])
        except Exception as e:
            logger.error(f"Review worker error: {e}")
        await asyncio.sleep(300)



@dp.message(lambda m: m.text == "🆘 Поддержка")
async def cmd_support(message: types.Message):
    await message.answer(
        "🆘 *Поддержка*\n\n"
        "По всем вопросам обращайтесь к администратору:\n\n"
        "👤 @CID202020\n\n"
        "Время ответа: в течение 24 часов.",
        parse_mode="Markdown"
    )


@dp.message(lambda m: m.text == "📄 Оферта")
async def cmd_oferta(message: types.Message):
    await message.answer(
        "📄 *Публичная оферта*\n\n"
        "Используя бот, вы соглашаетесь с условиями оферты.\n\n"
        "Нажмите кнопку ниже чтобы прочитать полный текст:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📄 Читать оферту", callback_data="show_oferta_1")]
        ])
    )


@dp.callback_query(F.data == "show_oferta_1")
async def show_oferta_part1(callback: types.CallbackQuery):
    await callback.message.answer(
        "📄 *ПУБЛИЧНАЯ ОФЕРТА*\n"
        "_о заключении договора об оказании услуг_\n\n"
        "*1. Общие положения*\n"
        "Настоящая Оферта содержит условия заключения Договора об оказании услуг. "
        "Совершение действий (запуск бота, оплата подписки) означает безоговорочное принятие всех условий.\n\n"
        "*Сервис (Бот)* — Telegram-бот @Wildberriess_help_bot для автоматической генерации ответов на отзывы WB с использованием ИИ.\n\n"
        "*Токен* — единица тарификации, расходуемая при генерации каждого ответа.\n\n"
        "*2. Предмет Договора*\n"
        "Исполнитель оказывает услуги автоответов на отзывы WB. Заказчик оплачивает выбранный тариф.\n\n"
        "*3. Цена и расчёты*\n"
        "Тарифы опубликованы в боте. Оплата в рублях, авансом. "
        "Неиспользованные токены не возвращаются и не переносятся.\n\n"
        "*4. Ответственность*\n"
        "Исполнитель не несёт ответственности за результаты использования ответов, "
        "сбои Telegram и OpenAI. Ответственность ограничена суммой оплаченной подписки.\n\n"
        "*5. Конфиденциальность*\n"
        "Обрабатываются: Telegram ID, имя пользователя, история запросов. "
        "Данные не передаются третьим лицам, кроме обезличенных запросов к OpenAI.\n\n"
        "*10. Реквизиты Исполнителя*\n"
        "Абдулатипов Зайнудин Зайнодинович\n"
        "ИНН: 052402592602\n"
        "Telegram: @CID202020\n"
        "Email: ivanov3322111@mail.ru",
        parse_mode="Markdown"
    )
    await callback.answer()


@dp.message(Command("oferta"))
async def cmd_oferta_command(message: types.Message):
    await cmd_oferta(message)

async def main():
    await db._init()
    asyncio.create_task(review_worker())
    asyncio.create_task(notify_expiring())
    
    app = aio_web.Application()
    app.router.add_post("/robokassa", lambda r: robokassa_webhook(r, bot, db))
    app.router.add_get("/health", lambda r: aio_web.Response(text="OK"))
    
    runner = aio_web.AppRunner(app)
    await runner.setup()
    site = aio_web.TCPSite(runner, "0.0.0.0", 3000)
    await site.start()
    logger.info("🌐 Web server started on port 3000")
    
    logger.info("🚀 Bot started")
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
