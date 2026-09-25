import asyncio
import logging
import re
import sqlite3
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler

TOKEN = "8750998872:AAHfrgpmVWueBaid4iZ9jZERE0BfUnN9v8"

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- НАСТРОЙКА БАЗЫ ДАННЫХ SQLite ---
def init_db():
    conn = sqlite3.connect("tracker.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            url TEXT,
            name TEXT,
            price REAL,
            market TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# --- ПАРСЕР WILDBERRIES ---
async def get_wb_price(url: str):
    try:
        match = re.search(r'/(?:catalog|p|detail)/(\d+)', url)
        if not match:
            match_digits = re.search(r'(\d+)', url)
            if not match_digits: return None
            art = match_digits.group(1)
        else:
            art = match.group(1)
            
        api_url = f"https://card.wb.ru/cards/v2/detail?appType=1&curr=rub&dest=-1257786&spp=30&nm={art}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, headers=headers, timeout=10) as response:
                if response.status != 200: return None
                data = await response.json()
                products = data.get("data", {}).get("products", [])
                if not products: return None
                
                prod = products[0]
                name = prod.get("name", "Товар WB")
                price_u = prod.get("sizes", [{}])[0].get("price", {}).get("total", 0)
                price = price_u / 100.0
                if price <= 0: return None
                return {"name": name, "price": price}
    except Exception as e:
        logging.error(f"Ошибка WB: {e}")
        return None

# --- ПАРСЕР OZON ---
async def get_ozon_price(url: str):
    try:
        match = re.search(r'-([0-9]{5,})/?(\?|$)', url)
        if not match:
            match_alt = re.search(r'/product/.*?([0-9]{5,})', url)
            if not match_alt: return None
            sku = match_alt.group(1)
        else:
            sku = match.group(1)
            
        api_url = f"https://www.ozon.ru/api/composer-api.bx/page/json/v2?url=/product/{sku}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, headers=headers, timeout=10) as response:
                if response.status != 200: return None
                data = await response.json()
                
                widgets = data.get("widgetStates", {})
                name, price = None, None
                
                for key, val in widgets.items():
                    if "web-product-heading" in key or "name-price" in key:
                        import json
                        v_data = json.loads(val) if isinstance(val, str) else val
                        if not name:
                            name = v_data.get("title") or v_data.get("name")
                    if "web-price" in key or "price-bar" in key:
                        import json
                        v_data = json.loads(val) if isinstance(val, str) else val
                        p_str = v_data.get("price") or v_data.get("priceOriginal")
                        if p_str:
                            clean_p = re.sub(r'[^\d]', '', str(p_str))
                            if clean_p:
                                price = float(clean_p)
                                
                if not price: return None
                return {"name": name or "Товар Ozon", "price": price}
    except Exception as e:
        logging.error(f"Ошибка Ozon: {e}")
        return None

# --- ПАРСЕР МЕГАМАРКЕТ ---
async def get_megamarket_price(url: str):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=10) as response:
                if response.status != 200: return None
                html = await response.text()
                
                m_price = re.search(r'"price"\s*:\s*"?([\d.]+)"?', html)
                m_name = re.search(r'<title>(.*?)</title>', html)
                
                if not m_price: return None
                price = float(m_price.group(1))
                name = m_name.group(1).split('|')[0].strip() if m_name else "Товар Мегамаркет"
                
                return {"name": name, "price": price}
    except Exception as e:
        logging.error(f"Ошибка Мегамаркет: {e}")
        return None

async def get_product_info(url: str):
    if "wildberries.ru" in url or "wb.ru" in url:
        res = await get_wb_price(url)
        return res, "wb"
    elif "ozon.ru" in url:
        res = await get_ozon_price(url)
        return res, "ozon"
    elif "megamarket.ru" in url:
        res = await get_megamarket_price(url)
        return res, "megamarket"
    return None, None

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Привет! Я твой надежный бот-трекер цен с базой данных.\n\n"
        "Поддерживаю: **Wildberries, Ozon, Мегамаркет**.\n"
        "Команды:\n"
        "📌 `/track [ссылка]` — добавить товар\n"
        "📋 `/list` — список отслеживаемых товаров",
        parse_mode="Markdown"
    )

@dp.message(Command("track"))
async def add_product(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("⚠️ Укажите ссылку после команды `/track`!", parse_mode="Markdown")
        return
    
    url = args[1].strip()
    chat_id = message.chat.id
    
    await message.answer("⏳ Анализирую ссылку и сохраняю в базу данных...")
    
    product_info, market = await get_product_info(url)
    
    if not product_info:
        await message.answer("❌ Не удалось получить товар. Проверьте ссылку.")
        return
        
    # Сохраняем в SQLite
    conn = sqlite3.connect("tracker.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO products (chat_id, url, name, price, market) VALUES (?, ?, ?, ?, ?)",
        (chat_id, url, product_info["name"], product_info["price"], market)
    )
    conn.commit()
    conn.close()
    
    await message.answer(
        f"✅ *Товар успешно сохранен в базу!*\n\n"
        f"📦 {product_info['name']}\n"
        f"💰 Цена: *{product_info['price']} руб.*",
        parse_mode="Markdown"
    )

@dp.message(Command("list"))
async def list_products(message: types.Message):
    chat_id = message.chat.id
    
    conn = sqlite3.connect("tracker.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, url, price, market FROM products WHERE chat_id = ?", (chat_id,))
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        await message.answer("📭 Ваш список отслеживания пуст.")
        return
    
    text = "📋 *Ваши товары в базе:*\n\n"
    for idx, row in enumerate(rows, 1):
        p_id, name, url, price, market = row
        text += f"{idx}. [{name}]({url}) — *{price} руб.* (`{market.upper()}`)\n"
    await message.answer(text, parse_mode="Markdown", disable_web_page_preview=True)

# Функция фоновой проверки цен 24/7
async def check_prices():
    logging.info("🔄 Плановая проверка цен из базы данных...")
    
    conn = sqlite3.connect("tracker.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, chat_id, url, name, price FROM products")
    rows = cursor.fetchall()
    
    for row in rows:
        p_id, chat_id, url, name, old_price = row
        new_info, _ = await get_product_info(url)
        if not new_info: continue
            
        new_price = new_info["price"]
        
        if new_price < old_price:
            drop = ((old_price - new_price) / old_price) * 100
            if drop >= 3:
                await bot.send_message(
                    chat_id,
                    f"🔥 *ЦЕНА УПАЛА!*\n\n"
                    f"📦 [{name}]({url})\n"
                    f"📉 Было: {old_price} руб.\n"
                    f"🎯 Стало: *{new_price} руб.* (Скидка {drop:.1f}%!)",
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )
                # Обновляем цену в базе данных
                cursor.execute("UPDATE products SET price = ? WHERE id = ?", (new_price, p_id))
                conn.commit()
                
    conn.close()

async def main():
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_prices, "interval", minutes=30)
    scheduler.start()
    
    logging.basicConfig(level=logging.INFO)
    print("🤖 Полноценный бот с базой данных запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())