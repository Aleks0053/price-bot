import asyncio
import logging
import os
import aiohttp
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiohttp import web

# Настройка логирования, чтобы видеть все ошибки в консоли Render
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

BOT_TOKEN = "8750998872:AAGjsnuFlopHQrFrRGRJMrROyFuvQT_sl3o"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# База данных в оперативной памяти
user_tracked_items = {}

async def check_product_price(url):
    """Надежный парсер цен для Ozon, Wildberries и других сайтов"""
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive"
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, allow_redirects=True, timeout=20) as response:
                if response.status != 200:
                    logging.warning(f"Сайт {url} вернул статус: {response.status}")
                    return None
                
                html = await response.text()
                soup = BeautifulSoup(html, "html.parser")
                
                # 1. Пробуем найти через OpenGraph мета-теги (Ozon часто их использует)
                meta_price = soup.find("meta", property="og:price:amount") or soup.find("meta", {"itemprop": "price"})
                if meta_price and meta_price.get("content"):
                    try:
                        clean = "".join(filter(lambda c: c.isdigit() or c == '.', meta_price.get("content")))
                        val = float(clean)
                        if val > 10:
                            return val
                    except Exception:
                        pass
                
                # 2. Специфичный поиск для Wildberries
                if "wildberries.ru" in url:
                    for tag in ["ins", "span"]:
                        found = soup.find(tag, class_=lambda c: c and ("price" in c.lower() or "cost" in c.lower()))
                        if found:
                            digits = "".join(filter(str.isdigit, found.get_text()))
                            if digits and len(digits) <= 7:
                                val = float(digits)
                                if val > 10:
                                    return val

                # 3. Универсальный поиск по ключевым элементам и тексту с символом рубля
                for tag in soup.find_all(["span", "div", "p", "price"]):
                    text = tag.get_text(strip=True)
                    if ("₽" in text or "руб" in text.lower()) and len(text) < 25:
                        digits = "".join(filter(str.isdigit, text))
                        if digits and len(digits) <= 7:
                            try:
                                val = float(digits)
                                if val > 50: # Отсекаем мелкие копейки/рейтинги
                                    return val
                            except ValueError:
                                continue
                                
        except asyncio.TimeoutError:
            logging.error(f"Таймаут при запросе к сайту: {url}")
        except Exception as e:
            logging.error(f"Ошибка парсинга {url}: {e}")
            
        return None

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "🤖 **Бот-трекер цен полностью перезапущен и готов к работе!**\n\n"
        "📌 **Как добавить товар:**\n"
        "`/track [Название товара] [Цена] [Ссылка]`\n"
        "*Пример:* `/track Детский планшет 3402 https://ozon.ru/t/bTdsVMz`\n\n"
        "📋 **Команды управления:**\n"
        "• `/list` — список товаров с кнопками\n"
        "• `/check` — проверить цены прямо сейчас\n"
        "• `/remove [номер]` — удалить товар\n"
        "• `/clear` — очистить список",
        parse_mode="Markdown"
    )

@dp.message(Command("track"))
async def cmd_track(message: types.Message):
    try:
        text_parts = message.text.split(maxsplit=1)
        if len(text_parts) < 2:
            await message.answer("⚠️ Неверный формат! Используйте: `/track [Название] [Цена] [Ссылка]`", parse_mode="Markdown")
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
            await message.answer("⚠️ Обязательно укажите название, цену и рабочую ссылку в самом конце!")
            return
            
        price_str = words[url_index - 1].replace("руб.", "").replace("₽", "").strip()
        price = float(price_str.replace(",", "."))
        
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
            f"✅ **Товар успешно добавлен в отслеживание!**\n\n"
            f"📦 **Название:** {title}\n"
            f"💰 **Целевая цена:** {price} руб.\n"
            f"🔗 [Ссылка на товар]({url})",
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
    except Exception as e:
        logging.error(f"Ошибка в команде track: {e}")
        await message.answer("⚠️ Ошибка добавления! Убедитесь, что цена — это просто число перед ссылкой.")

@dp.message(Command("list"))
async def cmd_list(message: types.Message):
    user_id = message.chat.id
    items = user_tracked_items.get(user_id, [])
    
    if not items:
        await message.answer("📭 Ваш список отслеживания пуст.")
        return
    
    for i, item in enumerate(items, 1):
        builder = InlineKeyboardBuilder()
        builder.button(text="🔗 Открыть", url=item['url'])
        builder.button(text="❌ Удалить", callback_data=f"del_{i-1}")
        builder.adjust(2)
        
        text = f"📦 **Товар #{i}:** {item['title']}\n💰 **Цель:** {item['price']} руб."
        await message.answer(text, parse_mode="Markdown", reply_markup=builder.as_markup())

@dp.callback_query(lambda c: c.data.startswith("del_"))
async def process_delete_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    index = int(callback.data.split("_")[1])
    
    if user_id in user_tracked_items and 0 <= index < len(user_tracked_items[user_id]):
        removed = user_tracked_items[user_id].pop(index)
        await callback.message.edit_text(f"🗑 Удалено: **{removed['title']}**", parse_mode="Markdown")
    else:
        await callback.answer("Товар уже удален.", show_alert=True)

@dp.message(Command("remove"))
async def cmd_remove(message: types.Message):
    parts = message.text.split()
    user_id = message.chat.id
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("⚠️ Укажите номер. Пример: `/remove 1`", parse_mode="Markdown")
        return
        
    index = int(parts[1]) - 1
    items = user_tracked_items.get(user_id, [])
    if 0 <= index < len(items):
        removed = items.pop(index)
        await message.answer(f"🗑 Удалено: **{removed['title']}**", parse_mode="Markdown")
    else:
        await message.answer("⚠️ Товар не найден. Проверьте `/list`.", parse_mode="Markdown")

@dp.message(Command("check"))
async def cmd_check(message: types.Message):
    user_id = message.chat.id
    items = user_tracked_items.get(user_id, [])
    if not items:
        await message.answer("📭 Список пуст.")
        return
        
    status_msg = await message.answer("🔍 Проверяю актуальные цены на сайтах...")
    
    report = "📊 **Результаты проверки цен:**\n\n"
    for i, item in enumerate(items, 1):
        current_price = await check_product_price(item["url"])
        if current_price:
            if current_price < item["price"]:
                report += f"{i}. **{item['title']}**\n🔥 Упала! Сейчас: **{current_price} руб.** (Цель была: {item['price']})\n\n"
            else:
                report += f"{i}. **{item['title']}**\n💰 Текущая: {current_price} руб. (Цель: {item['price']})\n\n"
        else:
            report += f"{i}. **{item['title']}**\n⚠️ Сайт заблокировал запрос или цена скрыта.\n\n"
        await asyncio.sleep(1.5)
        
    await bot.edit_message_text(report, chat_id=message.chat.id, message_id=status_msg.message_id, parse_mode="Markdown", disable_web_page_preview=True)

@dp.message(Command("clear"))
async def cmd_clear(message: types.Message):
    user_id = message.chat.id
    if user_id in user_tracked_items:
        user_tracked_items[user_id] = []
    await message.answer("🗑 Список очищен!")

async def scheduled_price_check():
    """Фоновая проверка каждые 3 часа"""
    while True:
        await asyncio.sleep(10800) # 3 часа
        for user_id, items in list(user_tracked_items.items()):
            for item in items:
                try:
                    current_price = await check_product_price(item["url"])
                    if current_price and current_price < item["price"]:
                        old_price = item["price"]
                        item["price"] = current_price
                        builder = InlineKeyboardBuilder()
                        builder.button(text="🔗 Купить", url=item['url'])
                        
                        await bot.send_message(
                            user_id,
                            f"🔥 **Цена снизилась!**\n\n"
                            f"📦 **{item['title']}**\n"
                            f"📉 Было: {old_price} руб.\n"
                            f"💰 Стало: **{current_price} руб.**",
                            parse_message="Markdown",
                            reply_markup=builder.as_markup()
                        )
                except Exception as e:
                    logging.error(f"Ошибка в фоновой проверке: {e}")
                await asyncio.sleep(3)

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
    # Запускаем фоновый цикл проверки цен отдельно, чтобы он не падал
    asyncio.create_task(scheduled_price_check())
    
    await asyncio.gather(
        web_server(),
        dp.start_polling(bot)
    )

if __name__ == "__main__":
    asyncio.run(main())
