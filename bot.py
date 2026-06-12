import os
import asyncio
import logging
from datetime import datetime, timedelta

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from dotenv import load_dotenv

load_dotenv()

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
        url = f"{API_BASE_URL}{endpoint}"

        headers = {
            "X-Request-Token": self.api_key,
            "Content-Type": "application/json"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=120
                ) as response:

                    logger.info(f"URL: {response.url}")
                    logger.info(f"STATUS: {response.status}")

                    try:
                        data = await response.json()
                    except Exception:
                        data = await response.text()

                    return data

        except Exception as e:
            logger.exception("REQUEST ERROR")
            return {"error": str(e)}

    async def products_expense(self, date_from, date_to):
        return await self.request(
            "/products/expense",
            {
                "date_from": date_from,
                "date_to": date_to
            }
        )


api = LangameAPI(API_KEY)


@dp.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "Тестовый бот запущен.\n\n"
        "/products - проверить products/expense"
    )


@dp.message(Command("products"))
async def products(message: Message):

    await message.answer("Запрашиваю данные...")

    date_to = datetime.now()
    date_from = date_to - timedelta(days=7)

    result = await api.products_expense(
        date_from.strftime("%Y-%m-%d"),
        date_to.strftime("%Y-%m-%d")
    )

    logger.info("=" * 120)
    logger.info("FULL RESPONSE:")
    logger.info(result)
    logger.info("=" * 120)

    if isinstance(result, dict):

        data = result.get("data")

        if isinstance(data, list):

            logger.info(f"ITEMS COUNT: {len(data)}")

            for i, item in enumerate(data[:10]):
                logger.info(f"ITEM #{i + 1}")
                logger.info(item)
                logger.info("-" * 80)

    await message.answer(
        "Готово.\n"
        "Смотри логи Railway."
    )


async def main():
    logger.info("BOT STARTED")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())