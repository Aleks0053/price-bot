import asyncio
import logging
import os
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO)

# Ваш токен бота
BOT_TOKEN = "8750998872:AAHfrgptmWueBaid4i2Z9jZEREObfU"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Ключевые слова для автоматического поиска скидок
SEARCH_QUERIES = ["наушники беспроводные", "смартфон", "электросамокат"]

# ID чата для уведомлений
ADMIN_CHAT_ID = None

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    global ADMIN_CHAT_ID
    ADMIN_CHAT_ID = message.chat.id
    await message.answer(
        "👋 Привет! Бот успешно запущен и переведен на режим **автоматического поиска скидок**.\n\n"
        "🔍 Я сканирую каталог по ключевым словам и буду присылать выгодные предложения 24/7!"
    )

@dp.message(Command("keywords"))
async def cmd_keywords(message: types.Message):
    text = "🔑 **Текущие поисковые запросы для мониторинга:**\n\n"
    for q in SEARCH_QUERIES:
        text += f"• {q}\n"
    await message.answer(text, parse_mode="Markdown")

# Функция автоматического поиска товаров по каталогу
async def search_and_notify():
    global ADMIN_CHAT_ID
    if not ADMIN_CHAT_ID:
        return
    
    logging.info("🔎 Запуск автоматического поиска скидок в каталоге...")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    async with aiohttp.ClientSession() as session:
        for query in SEARCH_QUERIES:
            try:
                search_url = f"https://sapi.ozon.ru/searchgw/v2/search?text={query}&page=1"
                
                async with session.get(search_url, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        items = data.get("result", {}).get("items", [])
                        
                        if items:
                            top_item = items[0]
                            title = top_item.get("title", "Товар")
                            price = top_item.get("price", {}).get("price", 0)
                            link = top_item.get("link", "https://ozon.ru")
                            
                            alert_text = (
                                f"🔥 **Найдено предложение по запросу:** _{query}_\n\n"
                                f"📦 **{title}**\n"
                                f"💰 **Цена:** {price} руб.\n"
                                f"🔗 [Ссылка на товар]({link})"
                            )
                            await bot.send_message(ADMIN_CHAT_ID, alert_text, parse_mode="Markdown")
                            
            except Exception as e:
                logging.error(f"Ошибка при поиске по запросу '{query}': {e}")
            
            await asyncio.sleep(5)

async def main():
    scheduler = AsyncIOScheduler()
    scheduler.add_job(search_and_notify, "interval", hours=3)
    scheduler.start()
    
    logging.info("🤖 Бот автоматического поиска запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
