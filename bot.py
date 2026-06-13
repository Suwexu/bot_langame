import os
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any
from collections import defaultdict

import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_KEY = os.getenv("LANGAME_API_KEY")
API_BASE_URL = "https://cyberx302.langame.ru/public_api"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

class LangameAPI:
    def __init__(self, api_key: str):
        self.headers = {"X-Request-Token": api_key, "Content-Type": "application/json"}
    
    async def _request(self, endpoint: str, params: Dict = None) -> Dict:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_BASE_URL}{endpoint}", headers=self.headers, params=params) as resp:
                return await resp.json() if resp.status == 200 else {"status": False}

    async def get_operations(self, date_from: str, date_to: str):
        return await self._request("/all_operations_log/list", {"date_from": date_from, "date_to": date_to})

    async def get_products_list(self):
        return await self._request("/products/list")

    async def get_products_expense(self, date_from: str, date_to: str, page: int = 1):
        return await self._request("/products/expense", {"date_from": date_from, "date_to": date_to, "page": page})

api = LangameAPI(API_KEY)

async def get_stats_for_period(date_from: datetime, date_to: datetime) -> Dict:
    date_from_str, date_to_str = date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d")
    operations = await api.get_operations(date_from_str, date_to_str)
    
    total_income = 0
    sessions_count = 0
    
    print("\n--- ПОЛНЫЙ СПИСОК ОПЕРАЦИЙ (БЕЗ ФИЛЬТРОВ) ---")
    
    for item in operations.get("data", []):
        op_sum = float(item.get("sum", 0))
        op_type = str(item.get("type", "")).lower()
        op_name = str(item.get("name", "")).lower()
        
        # Единственное ограничение - явная инкассация (обычно это минус или нулевая операция)
        if op_sum <= 0 or "инкассация" in op_name:
            continue
            
        if "сессия" in op_name or "session" in op_name:
            sessions_count += 1
            
        if op_type == "plus":
            total_income += op_sum
            print(f"➕ УЧТЕНО: {item.get('name')} | {op_sum} ₽")
        else:
            print(f"➖ ПРОПУЩЕНО (не plus): {item.get('name')} | {op_sum} ₽")
            
    print(f"ИТОГО ВЫШЛО: {total_income} ₽")
    
    return {"total_income": total_income, "sessions_count": sessions_count}

@dp.message(F.text == "📈 Быстрый отчет")
async def quick_report(message: types.Message):
    date_to = datetime.now()
    date_from = date_to.replace(hour=0, minute=0, second=0, microsecond=0)
    stats = await get_stats_for_period(date_from, date_to)
    await message.answer(f"📊 Выручка: {stats['total_income']:,.0f} ₽\nСессии: {stats['sessions_count']}")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())