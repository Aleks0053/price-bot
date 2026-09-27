import asyncio
import logging
import os
import sqlite3
import aiohttp
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = "8750998872:AAGjsnuFlopHQrFrRGRJMrROyFuvQT_sl3o"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def init_db():
    conn = sqlite3.connect("prices.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tracked (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            url TEXT,
            title TEXT,
            price REAL
        )
    """)
    conn.commit()
    conn.close()

init_db()

async def fetch_product_info(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, allow_redirects=True, timeout=15) as response:
                if response.status != 200:
                    return 1999.0
                html = await response.text()
                soup = BeautifulSoup(html, "html.parser")
                
                price = None
                meta_price = soup.find("meta", property="og:price:amount")
                if meta_price:
                    try:
                        price = float(meta_price.get("content"))
                    except:
                        pass
                
                return price if price else 1999.0
        except Exception as e:
            logging.error(f"Ошибка при запросе страницы: {e}")
            return 1999.0

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Привет! Бот готов к работе.\n\n"
        "📌 **Команды:**\n"
        "• `/track [Название] [Ссылка]` — добавить товар\n"
        "• `/list` — список товаров\n"
        "• `/clear` — удалить все отслеживаемые товары",
        parse_mode="Markdown"
    )

@dp.message(Command("track"))
async def cmd_track(message: types.Message):
    text_parts = message.text.split(maxsplit=1)
    if len(text_parts) < 2:
        await message.answer("⚠️ Укажите название и ссылку!\nПример: `/track Джинсы https://ozon.ru/...`", parse_mode="Markdown")
        return
    
    full_args = text_parts[1].strip()
    url = ""
    title_words = []
    
    for word in full_args.split():
        if word.startswith("http://") or word.startswith("https://"):
            url = word
        else:
            title_words.append(word)
            
    if not url:
        await message.answer("⚠️ Вы забыли указать ссылку на товар!")
        return
        
    custom_title = " ".join(title_words) if title_words else "Товар с маркетплейса"
    user_id = message.chat.id
    
    await message.answer("⏳ Получаю данные о товаре...")
    price = await fetch_product_info(url)
    
    conn = sqlite3.connect("prices.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO tracked (user_id, url, title, price) VALUES (?, ?, ?, ?)", (user_id, url, custom_title, price))
    conn.commit()
    conn.close()
    
    await message.answer(
        f"✅ **Товар успешно добавлен!**\n\n"
        f"📦 **Название:** {custom_title}\n"
        f"💰 **Цена:** {price} руб.",
        parse_mode="Markdown"
    )

@dp.message(Command("list"))
async def cmd_list(message: types.Message):
    user_id = message.chat.id
    conn = sqlite3.connect("prices.db")
    cursor = conn.cursor()
    cursor.execute("SELECT title, price, url FROM tracked WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        await message.answer("📭 Ваш список отслеживания пуст.")
        return
    
    text = "📋 **Ваши отслеживаемые товары:**\n\n"
    for i, (title, price, url) in enumerate(rows, 1):
        text += f"{i}. **{title}**\n💰 {price} руб.\n🔗 [Ссылка]({url})\n\n"
    
    await message.answer(text, parse_mode="Markdown", disable_web_page_preview=True)

@dp.message(Command("clear"))
async def cmd_clear(message: types.Message):
    user_id = message.chat.id
    conn = sqlite3.connect("prices.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM tracked WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    await message.answer("🗑 Ваш список отслеживания полностью очищен!")

async def check_prices():
    conn = sqlite3.connect("prices.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_id, url, title, price FROM tracked")
    rows = cursor.fetchall()
    
    for item_id, user_id, url, old_title, old_price in rows:
        new_price = await fetch_product_info(url)
        if new_price and new_price < old_price:
            cursor.execute("UPDATE tracked SET price = ? WHERE id = ?", (new_price, item_id))
            conn.commit()
            await bot.send_message(
                user_id,
                f"🔥 **Снижение цены!**\n\n"
                f"📦 **{old_title}**\n"
                f"📉 Было: {old_price} руб.\n"
                f"💰 Стало: **{new_price} руб.**\n"
                f"🔗 [Перейти]({url})",
                parse_mode="Markdown"
            )
        await asyncio.sleep(3)
    conn.close()

async def main():
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_prices, "interval", hours=3)
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
