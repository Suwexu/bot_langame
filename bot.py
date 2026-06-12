import os
import asyncio
import logging
from datetime import datetime

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_KEY = os.getenv("LANGAME_API_KEY")

API_BASE_URL = "https://cyberx302.langame.ru/public_api"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()


class LangameAPI:

    def __init__(self, api_key):
        self.api_key = api_key

    async def request(self, endpoint, params=None):

        headers = {
            "X-Request-Token": self.api_key,
            "Content-Type": "application/json"
        }

        url = f"{API_BASE_URL}{endpoint}"

        async with aiohttp.ClientSession() as session:

            async with session.get(
                url,
                headers=headers,
                params=params
            ) as response:

                logger.info(f"URL: {response.url}")
                logger.info(f"STATUS: {response.status}")

                try:
                    return await response.json()
                except:
                    return {"error": await response.text()}

    async def get_products_list(self):
        return await self.request("/products/list")

    async def get_products_expense(self, date_from, date_to, page=1):

        return await self.request(
            "/products/expense",
            {
                "date_from": date_from,
                "date_to": date_to,
                "page": page
            }
        )


api = LangameAPI(API_KEY)


@dp.message(Command("debug"))
async def debug(message: Message):

    await message.answer("Начинаю проверку...")

    date_from = "2026-06-01"
    date_to = "2026-06-30"

    logger.info("=" * 100)
    logger.info("STEP 1 - PRODUCTS LIST")
    logger.info("=" * 100)

    goods = await api.get_products_list()

    logger.info(goods)

    goods_map = {}

    if goods.get("status"):

        for item in goods.get("data", []):

            goods_map[item["id"]] = item["name"]

    logger.info(f"GOODS COUNT: {len(goods_map)}")

    logger.info("=" * 100)
    logger.info("STEP 2 - PRODUCTS EXPENSE PAGE 1")
    logger.info("=" * 100)

    sales = await api.get_products_expense(
        date_from,
        date_to,
        1
    )

    logger.info(sales)

    if not sales.get("status"):

        await message.answer("products/expense вернул ошибку")

        return

    logger.info(
        f"TOTAL PAGES: {sales.get('total_pages')}"
    )

    logger.info(
        f"FIRST PAGE ITEMS: {len(sales.get('data', []))}"
    )

    all_sales = []

    total_pages = sales.get("total_pages", 1)

    for page in range(1, total_pages + 1):

        logger.info(f"LOADING PAGE {page}")

        page_data = await api.get_products_expense(
            date_from,
            date_to,
            page
        )

        if page_data.get("status"):

            all_sales.extend(
                page_data.get("data", [])
            )

    logger.info(
        f"TOTAL SALES RECORDS: {len(all_sales)}"
    )

    product_revenue = {}

    for sale in all_sales:

        if sale.get("cancel") == 1:
            continue

        goods_id = sale.get("list_goods_id")

        name = goods_map.get(
            goods_id,
            f"UNKNOWN_{goods_id}"
        )

        count = float(
            sale.get("count", 0)
        )

        price = float(
            sale.get("price_sale", 0)
        )

        revenue = count * price

        product_revenue[name] = (
            product_revenue.get(name, 0)
            + revenue
        )

    top = sorted(
        product_revenue.items(),
        key=lambda x: x[1],
        reverse=True
    )[:20]

    logger.info("=" * 100)
    logger.info("TOP PRODUCTS")
    logger.info("=" * 100)

    for i, item in enumerate(top, start=1):

        logger.info(
            f"{i}. {item[0]} = {item[1]}"
        )

    logger.info("=" * 100)

    await message.answer(
        f"Готово.\n"
        f"Товаров: {len(goods_map)}\n"
        f"Продаж: {len(all_sales)}\n"
        f"Смотри логи Railway."
    )


async def main():

    logger.info("DEBUG BOT STARTED")

    await bot.delete_webhook(
        drop_pending_updates=True
    )

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())