import asyncio
import logging
import os
import aiohttp
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiohttp import web

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = "8750998872:AAGjsnuFlopHQrFrRGRJMrROyFuvQT_sl3o"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Хранилище в оперативной памяти
user_tracked_items = {}

async def check_product_price(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, allow_redirects=True, timeout=15) as response:
                if response.status != 200:
                    return None
                html = await response.text()
                soup = BeautifulSoup(html, "html.parser")
                
                meta_price = soup.find("meta", property="og:price:amount")
                if meta_price:
                    try:
                        return float(meta_price.get("content"))
                    except:
                        pass
                
                for span in soup.find_all(["span", "div"]):
                    text = span.get_text(strip=True)
                    if "₽" in text and len(text) < 15:
                        clean_price = "".join(filter(str.isdigit, text))
                        if clean_price and len(clean_price) <= 7:
                            val = float(clean_price)
                            if val > 50:
                                return val
        except Exception as e:
            logging.error(f"Ошибка проверки цены: {e}")
        return None

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 **Привет! Бот трекер цен запущен.**\n\n"
        "📌 **Как добавлять товар:**\n"
        "`/track [Название товара] [Цена] [Ссылка]`\n"
        "*Пример:* `/track Детский планшет 3402 https://ozon.ru/t/bTdsVMz`\n\n"
        "📋 **Команды:**\n"
        "• `/list` — посмотреть список товаров\n"
        "• `/clear` — очистить список",
        parse_mode="Markdown"
    )

@dp.message(Command("track"))
async def cmd_track(message: types.Message):
    text_parts = message.text.split(maxsplit=1)
    if len(text_parts) < 2:
        await message.answer(
            "⚠️ Неверный формат!\n"
            "Используйте: `/track [Название товара] [Цена] [Ссылка]`",
            parse_mode="Markdown"
        )
        return
    
    args_text = text_parts[1].strip()
    words = args_text.split()
    
    url = ""
    url_index = -1
    for i, word in enumerate(words):
        if word.startswith("http://") or word.startswith("https://"):
            url = word
            url_index = i
            break
            
    if not url or url_index < 2:
        await message.answer("⚠️ Обязательно укажите название, цену и ссылку в конце!")
        return
        
    price_str = words[url_index - 1].replace("руб.", "").replace("₽", "").strip()
    try:
        price = float(price_str.replace(",", "."))
    except ValueError:
        await message.answer(f"⚠️ Не удалось распознать цену (`{price_str}`). Убедитесь, что перед ссылкой идет число, например: `3402`", parse_mode="Markdown")
        return
        
    title = " ".join(words[:url_index - 1])
    user_id = message.chat.id
    
    if user_id not in user_tracked_items:
        user_tracked_items[user_id] = []
        
    user_tracked_items[user_id].append({
        "title": title,
        "price": price,
        "url": url
    })
    
    await message.answer(
        f"✅ **Товар успешно добавлен!**\n\n"
        f"📦 **Название:** {title}\n"
        f"💰 **Цена:** {price} руб.\n"
        f"🔗 [Ссылка на товар]({url})",
        parse_mode="Markdown",
        disable_web_page_preview=True
    )

@dp.message(Command("list"))
async def cmd_list(message: types.Message):
    user_id = message.chat.id
    items = user_tracked_items.get(user_id, [])
    
    if not items:
        await message.answer("📭 Ваш список отслеживания пуст.")
        return
    
    text = "📋 **Ваши отслеживаемые товары:**\n\n"
    for i, item in enumerate(items, 1):
        text += f"{i}. **{item['title']}**\n💰 {item['price']} руб.\n🔗 [Ссылка]({item['url']})\n\n"
        
    await message.answer(text, parse_mode="Markdown", disable_web_page_preview=True)

@dp.message(Command("clear"))
async def cmd_clear(message: types.Message):
    user_id = message.chat.id
    if user_id in user_tracked_items:
        user_tracked_items[user_id] = []
    await message.answer("🗑 Ваш список отслеживания полностью очищен!")

async def scheduled_price_check():
    for user_id, items in user_tracked_items.items():
        for item in items:
            current_price = await check_product_price(item["url"])
            if current_price and current_price < item["price"]:
                old_price = item["price"]
                item["price"] = current_price
                try:
                    await bot.send_message(
                        user_id,
                        f"🔥 **Цена снизилась!**\n\n"
                        f"📦 **{item['title']}**\n"
                        f"📉 Было: {old_price} руб.\n"
                        f"💰 Стало: **{current_price} руб.**\n"
                        f"🔗 [Перейти к товару]({item['url']})",
                        parse_mode="Markdown",
                        disable_web_page_preview=True
                    )
                except Exception as e:
                    logging.error(f"Ошибка уведомления: {e}")
            await asyncio.sleep(2)

# Заглушка веб-сервера для Render, чтобы он не отключал бота
async def handle(request):
    return web.Response(text="Bot is running!")

async def web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    scheduler = AsyncIOScheduler()
    scheduler.add_job(scheduled_price_check, "interval", hours=3)
    scheduler.start()
    
    # Запускаем и веб-сервер для Render, и самого бота параллельно
    await asyncio.gather(
        web_server(),
        dp.start_polling(bot)
    )

if __name__ == "__main__":
    asyncio.run(main())
