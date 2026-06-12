import os
import asyncio
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Any, Dict

import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_KEY = os.getenv("LANGAME_API_KEY")
API_BASE_URL = "https://cyberx302.langame.ru/public_api"

logging.basicConfig(level=logging.INFO)

def safe_float(v):
    try:
        return float(str(v).replace(",", "."))
    except:
        return 0.0

class LangameAPI:
    def __init__(self, api_key):
        self.headers = {"X-Request-Token": api_key}
    async def _get(self, endpoint, params=None):
        async with aiohttp.ClientSession() as s:
            async with s.get(API_BASE_URL + endpoint, headers=self.headers, params=params) as r:
                return await r.json()

    async def get_products(self):
        return await self._get("/products/list")

    async def get_products_expense(self, date_from, date_to, page=1):
        return await self._get("/products/expense", {
            "date_from": date_from,
            "date_to": date_to,
            "page": page
        })

api = LangameAPI(API_KEY)

bot = Bot(BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

async def build_top():
    now = datetime.now()
    date_from = now.replace(day=1).strftime("%Y-%m-%d")
    date_to = now.strftime("%Y-%m-%d")

    products = await api.get_products()
    goods = {x["id"]: x["name"] for x in products.get("data", [])}

    first = await api.get_products_expense(date_from, date_to, 1)
    pages = first.get("total_pages", 1)

    revenue = defaultdict(float)

    for page in range(1, pages + 1):
        data = await api.get_products_expense(date_from, date_to, page)

        for sale in data.get("data", []):
            if sale.get("cancel") == 1:
                continue

            gid = sale.get("list_goods_id")
            name = goods.get(gid, f"Товар #{gid}")

            count = safe_float(sale.get("count", 1))
            price = safe_float(sale.get("price_sale", 0))

            revenue[name] += count * price

    top = sorted(revenue.items(), key=lambda x: x[1], reverse=True)[:10]

    text = "🏆 ТОП ТОВАРОВ\n\n"
    for i, (name, amount) in enumerate(top, start=1):
        text += f"{i}. {name} — {amount:.0f} ₽\n"

    return text

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("Используй /top")

@dp.message(Command("top"))
async def top(message: types.Message):
    await message.answer("Считаю...")
    await message.answer(await build_top())

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
