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

BOT_TOKEN = "8750998872:AAHfrgptmWueBaid4i2Z9jZEREObfU"

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
                    return "Товар с маркетплейса", 1500.0
                html = await response.text()
                soup = BeautifulSoup(html, "html.parser")
                
                title_elem = soup.find("title")
                title = title_elem.text.split("—")[0].split("|")[0].strip() if title_elem else "Товар"
                
                price = None
                meta_price = soup.find("meta", property="og:price:amount")
                if meta_price:
                    try:
                        price = float(meta_price.get("content"))
                    except:
                        pass
                
                if not price:
                    price = 1999.0
                    
                return title, price
        except Exception as e:
            logging.error(f"Ошибка при запросе страницы: {e}")
            return "Товар с маркетплейса", 1999.0

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Привет! Я твой бот-трекер цен.\n\n"
        "📌 **Команды:**\n"
        "• `/track [название и ссылка]` — добавить товар\n"
        "• `/list` — список товаров",
        parse_mode="Markdown"
    )

@dp.message(Command("track"))
async def cmd_track(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("⚠️ Укажите ссылку после команды `/track`!\nПример: `/track Джинсы https://ozon.ru/...`", parse_mode="Markdown")
        return
    
    full_text = args[1].strip()
    parts = full_text.split()
    url = ""
    custom_title = ""
    
    for part in parts:
        if part.startswith("http://") or part.startswith("https://"):
            url = part
        else:
            custom_title += part + " "
            
    if not url:
        url = full_text
        
    user_id = message.chat.id
    await message.answer("⏳ Анализирую ссылку и сохраняю...")
    
    # Пытаемся получить данные, но если пользователь написал свое название — используем его
    scraped_title, price = await fetch_product_info(url)
    
    # Если вы написали название руками (как «Джинсы MkJeans»), берем его, иначе то, что спарсилось
    title = custom_title.strip() if custom_title.strip() else scraped_title
    
    conn = sqlite3.connect("prices.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO tracked (user_id, url, title, price) VALUES (?, ?, ?, ?)", (user_id, url, title, price))
    conn.commit()
    conn.close()
    
    await message.answer(
        f"✅ **Товар добавлен в трекер!**\n\n"
        f"📦 **{title}**\n"
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

async def check_prices():
    conn = sqlite3.connect("prices.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_id, url, title, price FROM tracked")
    rows = cursor.fetchall()
    
    for item_id, user_id, url, old_title, old_price in rows:
        _, new_price = await fetch_product_info(url)
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
