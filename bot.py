import asyncio
import logging
import os
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Получаем токен из переменных окружения Render или вставляем сюда
BOT_TOKEN = os.getenv("BOT_TOKEN", "ВАШ_ТОКЕН_БОТА")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Список товаров для автоматического мониторинга (можно добавлять свои ссылки и желаемую цену)
TRACKED_ITEMS = [
    {
        "url": "https://www.ozon.ru/product/primer-tovara-1",
        "title": "Пример товара на Ozon",
        "last_price": 1500  # Последняя известная цена для сравнения
    },
    # Сюда можно добавлять другие товары:
    # {"url": "https://www.wildberries.ru/catalog/...", "title": "Товар WB", "last_price": 3000}
]

# ID вашего чата, куда бот будет присылать уведомления о скидках
# (Бот сохранит его автоматически при отправке команды /start)
ADMIN_CHAT_ID = None


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    global ADMIN_CHAT_ID
    ADMIN_CHAT_ID = message.chat.id
    await message.answer(
        "👋 Привет! Я бот-трекер цен.\n\n"
        "🤖 Сейчас я настроен на **автоматический мониторинг** популярных товаров 24/7.\n"
        "📉 Как только цена на какой-то из отслеживаемых товаров упадет, я сразу пришлю вам ссылку!"
    )


@dp.message(Command("list"))
async def cmd_list(message: types.Message):
    if not TRACKED_ITEMS:
        await message.answer("📭 Список автоматического мониторинга пока пуст.")
        return
    
    text = "📋 **Список отслеживаемых товаров:**\n\n"
    for idx, item in enumerate(TRACKED_ITEMS, 1):
        text += f"{idx}. {item['title']}\n🔗 {item['url']}\n💰 Последняя цена: {item['last_price']} руб.\n\n"
    
    await message.answer(text, parse_mode="Markdown")


# Функция имитации проверки цен (здесь можно подключить реальный парсер)
async def check_prices():
    global ADMIN_CHAT_ID
    if not ADMIN_CHAT_ID:
        return  # Если пользователь еще не написал /start, бот не знает, куда отправлять
    
    logging.info("🔄 Запуск плановой проверки цен...")
    
    for item in TRACKED_ITEMS:
        # --- ЗДЕСЬ БУДЕТ ВАШ ПАРСЕР ЦЕН ---
        # Для примера сымитируем, что цена случайно упала:
        current_price = item["last_price"] - 100  # Симуляция падения цены
        
        # Если текущая цена стала ниже предыдущей
        if current_price < item["last_price"]:
            old_price = item["last_price"]
            item["last_price"] = current_price  # Обновляем цену в памяти
            
            # Отправляем уведомление в Telegram
            alert_text = (
                f"🔥 **ВНИМАНИЕ! Упала цена!** 🔥\n\n"
                f"📦 **Товар:** {item['title']}\n"
                f"📉 **Было:** {old_price} руб.\n"
                f"✨ **Стало:** {current_price} руб. (-{old_price - current_price} руб.)!\n\n"
                f"🔗 **Ссылка:** {item['url']}"
            )
            try:
                await bot.send_message(ADMIN_CHAT_ID, alert_text, parse_mode="Markdown")
            except Exception as e:
                logging.error(f"Не удалось отправить уведомление: {e}")


async def main():
    # Настраиваем планировщик: проверка будет запускаться каждые 2 часа (можно изменить interval)
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_prices, "interval", hours=2)  # Проверка каждые 2 часа
    scheduler.start()
    
    logging.info("🤖 Бот запущен и планировщик активирован!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
