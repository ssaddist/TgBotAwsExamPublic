import asyncio
import logging
import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, Response, status
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from bot.database import init_db, AsyncSessionLocal, User, Product, PriceHistory
from bot.parser import get_product_details
from bot.scheduler import setup_scheduler

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'))

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Critical Error: TELEGRAM_BOT_TOKEN environment variable is missing.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("Database initialized successfully.")

    try:
        price_interval = float(os.getenv("PRICE_CHECK_INTERVAL_HOURS", "4.0"))
        report_interval = float(os.getenv("REPORT_INTERVAL_HOURS", "12.0"))
    except ValueError:
        logger.warning("Invalid interval format in .env. Using default values (4.0 and 12.0).")
        price_interval, report_interval = 4.0, 12.0

    test_mode = os.getenv("TEST", "no").lower() in ("yes", "true", "1")

    scheduler = setup_scheduler(
        bot=bot,
        price_interval=price_interval,
        report_interval=report_interval,
        test_mode=test_mode
    )

    scheduler.start()
    logger.info("APScheduler initialized and started inside lifespan.")

    polling_task = asyncio.create_task(dp.start_polling(bot))
    logger.info("Aiogram Polling task started successfully in background.")

    yield

    scheduler.shutdown()
    logger.info("Scheduler shutdown successfully.")

    polling_task.cancel()
    try:
        await polling_task
    except asyncio.CancelledError:
        logger.info("Aiogram Polling task stopped successfully.")
    await bot.session.close()


app = FastAPI(lifespan=lifespan)


@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    return {"status": "healthy"}


@dp.message(Command("start"))
async def start_cmd(message: Message):
    telegram_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).filter_by(telegram_id=telegram_id))
        user = result.scalars().first()

        if not user:
            user = User(telegram_id=telegram_id, username=username, first_name=first_name)
            session.add(user)
            await session.commit()
            logger.info(f"Registered new user: {telegram_id}")

    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📦 Мої товари"), KeyboardButton(text="➕ Додати товар")]
        ],
        resize_keyboard=True
    )

    await message.answer(
        f"Привіт, {first_name}! 👋\n"
        f"Я бот для трекінгу цін на товари з <b>Rozetka</b> та <b>Prom</b>.\n\n"
        f"Надішли мені посилання на товар, і я повідомлю тебе, коли ціна впаде! 📉",
        parse_mode="HTML",
        reply_markup=keyboard
    )


@dp.message(F.text == "📦 Мої товари")
async def list_products(message: Message):
    telegram_id = message.from_user.id

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).options(selectinload(User.products)).filter_by(telegram_id=telegram_id)
        )
        user = result.scalars().first()

        if not user or not user.products:
            await message.answer("ℹ️ У вас поки немає доданих товарів для відстеження.")
            return

        for product in user.products:
            delete_kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="❌ Видалити", callback_data=f"delete_{product.id}")]
                ]
            )

            await message.answer(
                f"📦 <b><a href='{product.url}'>{product.title}</a></b>\n"
                f"💵 Поточна ціна: <b>{product.current_price:.2f} грн</b>\n"
                f"📉 Початкова ціна: {product.initial_price:.2f} грн",
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=delete_kb
            )


@dp.message(F.text == "➕ Додати товар")
async def add_product_instructions(message: Message):
    await message.answer(
        "📝 Просто відправ мені пряме посилання на товар з сайту <b>Rozetka</b> або <b>Prom</b>.",
        parse_mode="HTML"
    )


@dp.callback_query(F.data.startswith("delete_"))
async def delete_product_callback(callback: types.CallbackQuery):
    product_id = int(callback.data.split("_")[1])

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Product).filter_by(id=product_id))
        product = result.scalars().first()

        if product:
            await session.delete(product)
            await session.commit()
            await callback.answer("Товар видалено з відстеження.")
            await callback.message.edit_text("❌ <i>Товар видалено з відстеження.</i>", parse_mode="HTML")
        else:
            await callback.answer("Товар не знайдено.")


@dp.message(F.text.startswith("http://") | F.text.startswith("https://"))
async def process_product_link(message: Message):
    url = message.text.strip()
    telegram_id = message.from_user.id

    if "rozetka.com.ua" not in url and "prom.ua" not in url:
        await message.answer("❌ На жаль, підтримуються тільки посилання на <b>Rozetka</b> або <b>Prom</b>.",
                             parse_mode="HTML")
        return

    waiting_msg = await message.answer("⏳ Отримую дані про товар, зачекайте будь ласка...")

    try:
        details = get_product_details(url)

        async with AsyncSessionLocal() as session:
            user_result = await session.execute(select(User).filter_by(telegram_id=telegram_id))
            user = user_result.scalars().first()

            if not user:
                user = User(telegram_id=telegram_id, username=message.from_user.username,
                            first_name=message.from_user.first_name)
                session.add(user)
                await session.flush()

            prod_result = await session.execute(select(Product).filter_by(user_id=user.id, url=url))
            existing_product = prod_result.scalars().first()

            if existing_product:
                await waiting_msg.delete()
                await message.answer("ℹ️ Ви вже відстежуєте цей товар.")
                return

            new_product = Product(
                user_id=user.id,
                url=url,
                title=details["title"],
                initial_price=details["price"],
                current_price=details["price"]
            )
            session.add(new_product)
            await session.flush()

            history_entry = PriceHistory(product_id=new_product.id, price=details["price"])
            session.add(history_entry)

            await session.commit()

        await waiting_msg.delete()
        await message.answer(
            f"✅ <b>Товар успішно додано до відстеження!</b>\n\n"
            f"📦 <b>Назва:</b> {details['title']}\n"
            f"💵 <b>Поточна ціна:</b> {details['price']:.2f} грн\n\n"
            f"Я повідомлю вас, як тільки ціна знизиться! 🔔",
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Error parsing or saving product: {e}")
        await waiting_msg.delete()
        await message.answer("❌ Не вдалося отримати дані про товар. Перевірте посилання або спробуйте пізніше.")