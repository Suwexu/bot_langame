import os
import asyncio
import logging

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

        headers = {
            "X-Request-Token": self.api_key,
            "Content-Type": "application/json"
        }

        url = f"{API_BASE_URL}{endpoint}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=120
                ) as response:

                    logger.info("=" * 120)
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


api = LangameAPI(API_KEY)


@dp.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "Тестовый бот Langame\n\n"
        "/products - продажи товаров\n"
        "/goods - список товаров"
    )


@dp.message(Command("products"))
async def products(message: Message):

    await message.answer("Получаю продажи товаров...")

    result = await api.request(
        "/products/expense"
    )

    logger.info("=" * 120)
    logger.info("PRODUCTS RESPONSE:")
    logger.info(result)
    logger.info("=" * 120)

    data = result.get("data", [])

    logger.info(f"ITEMS COUNT: {len(data)}")

    for i, item in enumerate(data[:20]):
        logger.info(f"PRODUCT #{i + 1}")
        logger.info(item)
        logger.info("-" * 80)

    await message.answer("Готово. Смотри Railway Logs.")


@dp.message(Command("goods"))
async def goods(message: Message):

    await message.answer("Получаю справочник товаров...")

    result = await api.request(
        "/products/list"
    )

    logger.info("=" * 120)
    logger.info("GOODS RESPONSE:")
    logger.info(result)
    logger.info("=" * 120)

    data = result.get("data", [])

    logger.info(f"GOODS COUNT: {len(data)}")

    for i, item in enumerate(data[:50]):
        logger.info(f"GOOD #{i + 1}")
        logger.info(item)
        logger.info("-" * 80)

    await message.answer("Готово. Смотри Railway Logs.")


async def main():

    logger.info("BOT STARTED")

    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN not found")

    if not API_KEY:
        raise ValueError("LANGAME_API_KEY not found")

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())