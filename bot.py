"""
Telegram-бот мониторинга цен.
Каждые 3 часа проверяет ссылки и присылает уведомление, если цена упала.

Команды:
  /add <ссылка> [css-селектор]  - добавить товар (селектор нужен, только если цена не нашлась сама)
  /list                          - список отслеживаемых товаров
  /remove <id>                   - удалить товар
  /check                         - проверить всё прямо сейчас
"""
import asyncio
import json
import logging
import os
import re
import sqlite3
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = os.environ["8750998872:AAGjsnuFlopHQrFrRGRJMrROyFuvQT_sl3o"]
CHECK_INTERVAL = 3 * 60 * 60  # 3 часа, в секундах
DB_PATH = os.environ.get("DB_PATH", "prices.db")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("price-bot")


# ---------- БД ----------
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                selector TEXT,
                title TEXT,
                last_price REAL,
                min_price REAL
            )"""
        )


# ---------- Парсинг цены ----------
def parse_price(text: str):
    text = text.replace("\xa0", " ").replace("\u202f", " ")
    m = re.search(r"\d[\d\s.,]*", text)
    if not m:
        return None
    num = m.group(0).strip().replace(" ", "").rstrip(".,")
    if "," in num and "." in num:
        if num.rfind(",") > num.rfind("."):
            num = num.replace(".", "").replace(",", ".")
        else:
            num = num.replace(",", "")
    elif "," in num:
        head, _, tail = num.rpartition(",")
        num = head.replace(",", "") + "." + tail if len(tail) <= 2 else num.replace(",", "")
    elif "." in num:
        head, _, tail = num.rpartition(".")
        if len(tail) == 3 and head:
            num = num.replace(".", "")
    try:
        return float(num)
    except ValueError:
        return None


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _price_from_jsonld(soup):
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for node in _walk(data):
            offers = node.get("offers")
            if not offers:
                continue
            for offer in offers if isinstance(offers, list) else [offers]:
                if not isinstance(offer, dict):
                    continue
                for key in ("price", "lowPrice"):
                    if key in offer:
                        p = parse_price(str(offer[key]))
                        if p:
                            return p
    return None


def _price_from_meta(soup):
    for attrs in (
        {"property": "product:price:amount"},
        {"property": "og:price:amount"},
        {"itemprop": "price"},
    ):
        tag = soup.find(attrs=attrs)
        if tag:
            p = parse_price(tag.get("content") or tag.get_text())
            if p:
                return p
    return None


def fetch_price(url: str, selector: str | None):
    """Возвращает (цена, название). Блокирующая функция - вызывать через to_thread."""
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    og = soup.find("meta", property="og:title")
    title = (og.get("content") if og else None) or (soup.title.string.strip() if soup.title and soup.title.string else None)
    title = (title or urlparse(url).netloc)[:120]

    price = None
    if selector:
        el = soup.select_one(selector)
        if el:
            price = parse_price(el.get("content") or el.get_text())
    else:
        price = _price_from_jsonld(soup) or _price_from_meta(soup)
    return price, title


def fmt(p: float) -> str:
    return f"{p:,.2f}".replace(",", " ").rstrip("0").rstrip(".")


# ---------- Команды ----------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я слежу за ценами и пишу, когда они падают (проверка каждые 3 часа).\n\n"
        "/add <ссылка> [css-селектор] - добавить товар\n"
        "/list - мои товары\n"
        "/remove <id> - удалить\n"
        "/check - проверить сейчас"
    )


async def add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Использование: /add <ссылка> [css-селектор]")
        return
    url = ctx.args[0]
    selector = " ".join(ctx.args[1:]) or None
    if not urlparse(url).scheme.startswith("http"):
        await update.message.reply_text("Нужна полная ссылка, начинающаяся с http:// или https://")
        return

    await update.message.reply_text("Проверяю страницу...")
    try:
        price, title = await asyncio.to_thread(fetch_price, url, selector)
    except Exception as e:
        await update.message.reply_text(f"Не удалось открыть страницу: {e}")
        return
    if price is None:
        await update.message.reply_text(
            "Цену найти не удалось. Пришли CSS-селектор элемента с ценой:\n"
            "/add <ссылка> .price\n"
            "(в браузере: ПКМ на цене → «Просмотреть код» → Copy → Copy selector)"
        )
        return

    with db() as c:
        cur = c.execute(
            "INSERT INTO items (chat_id, url, selector, title, last_price, min_price) VALUES (?,?,?,?,?,?)",
            (update.effective_chat.id, url, selector, title, price, price),
        )
    await update.message.reply_text(f"✅ Добавлено #{cur.lastrowid}\n{title}\nТекущая цена: {fmt(price)}")


async def list_items(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    with db() as c:
        rows = c.execute("SELECT * FROM items WHERE chat_id=?", (update.effective_chat.id,)).fetchall()
    if not rows:
        await update.message.reply_text("Список пуст. Добавь товар через /add")
        return
    text = "\n\n".join(
        f"#{r['id']} {r['title']}\nСейчас: {fmt(r['last_price'])} | минимум: {fmt(r['min_price'])}\n{r['url']}"
        for r in rows
    )
    await update.message.reply_text(text, disable_web_page_preview=True)


async def remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args or not ctx.args[0].isdigit():
        await update.message.reply_text("Использование: /remove <id>")
        return
    with db() as c:
        cur = c.execute("DELETE FROM items WHERE id=? AND chat_id=?", (int(ctx.args[0]), update.effective_chat.id))
    await update.message.reply_text("Удалено 🗑" if cur.rowcount else "Товар с таким id не найден")


# ---------- Проверка цен ----------
async def check_prices(context: ContextTypes.DEFAULT_TYPE, only_chat: int | None = None):
    with db() as c:
        if only_chat:
            rows = c.execute("SELECT * FROM items WHERE chat_id=?", (only_chat,)).fetchall()
        else:
            rows = c.execute("SELECT * FROM items").fetchall()

    for r in rows:
        try:
            price, _ = await asyncio.to_thread(fetch_price, r["url"], r["selector"])
        except Exception as e:
            log.warning("Ошибка для #%s: %s", r["id"], e)
            continue
        if price is None:
            log.warning("Цена не найдена для #%s", r["id"])
            continue

        old = r["last_price"]
        new_min = min(r["min_price"], price)
        with db() as c:
            c.execute("UPDATE items SET last_price=?, min_price=? WHERE id=?", (price, new_min, r["id"]))

        if price < old:
            pct = (old - price) / old * 100
            record = "\n🔥 Это новый минимум!" if price < r["min_price"] else ""
            await context.bot.send_message(
                r["chat_id"],
                f"📉 Цена упала!\n{r['title']}\n{fmt(old)} → {fmt(price)} (−{pct:.1f}%){record}\n{r['url']}",
            )
        await asyncio.sleep(2)  # пауза между запросами, чтобы не банили


async def scheduled_check(context: ContextTypes.DEFAULT_TYPE):
    log.info("Плановая проверка цен")
    await check_prices(context)


async def manual_check(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Проверяю все товары...")
    await check_prices(ctx, only_chat=update.effective_chat.id)
    await update.message.reply_text("Готово. Если что-то подешевело, я уже написал выше.")


def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("list", list_items))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("check", manual_check))
    app.job_queue.run_repeating(scheduled_check, interval=CHECK_INTERVAL, first=60)
    log.info("Бот запущен")
    app.run_polling()


if __name__ == "__main__":
    main()
