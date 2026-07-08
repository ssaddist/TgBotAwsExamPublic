import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from bot.parser import get_product_details
from aiogram import Bot

logger = logging.getLogger(__name__)

async def check_prices_job(bot: Bot):
    from bot.database import AsyncSessionLocal, Product, PriceHistory

    logger.info("Starting background price check job...")
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Product).options(selectinload(Product.user))
        )
        products = result.scalars().all()
        
        if not products:
            logger.info("No products found to track.")
            return

        for product in products:
            try:
                details = get_product_details(product.url)
                new_price = details["price"]
                old_price = product.current_price
                
                product.current_price = new_price
                history_entry = PriceHistory(product_id=product.id, price=new_price)
                session.add(history_entry)
                
                if new_price < old_price:
                    savings = old_price - new_price
                    user_tg_id = product.user.telegram_id
                    
                    message_text = (
                        f"📉 <b>Зниження ціни!</b>\n\n"
                        f"Назва: <a href='{product.url}'>{product.title}</a>\n"
                        f"Стара ціна: <s>{old_price:.2f} грн</s>\n"
                        f"Нова ціна: <b>{new_price:.2f} грн</b>\n"
                        f"Ви економите: <b>{savings:.2f} грн</b>! 🥳"
                    )
                    
                    try:
                        await bot.send_message(
                            chat_id=user_tg_id,
                            text=message_text,
                            parse_mode="HTML",
                            disable_web_page_preview=True
                        )
                    except Exception as send_err:
                        logger.error(f"Failed to send notification to user {user_tg_id}: {send_err}")
            except Exception as e:
                logger.error(f"Error checking price for product ID {product.id}: {e}")
        
        await session.commit()
    logger.info("Background price check job finished.")


async def send_scheduled_reports_job(bot: Bot):
    from bot.database import AsyncSessionLocal, User

    logger.info("Starting scheduled user reports job...")
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).options(selectinload(User.products))
        )
        users = result.scalars().all()

        for user in users:
            if not user.products:
                continue

            report_text = f"📋 <b>Ваш регулярний звіт по товарах:</b>\n"
            report_text += f"━━━━━━━━━━━━━━━━━━━━\n"
            
            for p in user.products:
                report_text += (
                    f"📦 <b><a href='{p.url}'>{p.title}</a></b>\n"
                    f"💵 Поточна ціна: <b>{p.current_price:.2f} грн</b>\n"
                    f"📉 Початкова ціна: {p.initial_price:.2f} грн\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                )
            
            try:
                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=report_text,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
                logger.info(f"Sent scheduled report to user {user.telegram_id}")
            except Exception as e:
                logger.error(f"Failed to send scheduled report to user {user.telegram_id}: {e}")


def setup_scheduler(bot: Bot, price_interval: float, report_interval: float, test_mode: bool = False) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    
    if test_mode:
        scheduler.add_job(
            check_prices_job,
            "interval",
            minutes=1,
            args=[bot],
            id="price_check_job",
            replace_existing=True
        )
        scheduler.add_job(
            send_scheduled_reports_job,
            "interval",
            minutes=1,
            args=[bot],
            id="user_report_job",
            replace_existing=True
        )
        logger.info("TEST mode: price check and user reports scheduled every 1 minute.")
    else:
        scheduler.add_job(
            check_prices_job,
            "interval",
            hours=price_interval,
            args=[bot],
            id="price_check_job",
            replace_existing=True
        )
        scheduler.add_job(
            send_scheduled_reports_job,
            "interval",
            hours=report_interval,
            args=[bot],
            id="user_report_job",
            replace_existing=True
        )
        logger.info(f"Price check scheduled every {price_interval} hour(s).")
        logger.info(f"User reports scheduled every {report_interval} hour(s).")
    
    return scheduler