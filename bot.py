import logging
import asyncio
import aiohttp
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command

# Берем из Railway, но добавляем страховку
TOKEN = os.getenv("BOT_TOKEN")
API_KEY = os.getenv("LANGAME_API_KEY")
URL = "https://cyberx302.langame.ru/public_api/all_operations_log/list"

logging.basicConfig(level=logging.INFO)

if not TOKEN:
    print("КРИТИЧЕСКАЯ ОШИБКА: BOT_TOKEN не найден в переменных Railway!")
    exit(1)

bot = Bot(token=TOKEN)
dp = Dispatcher()

async def get_stats():
    headers = {"X-Request-Token": API_KEY}
    date_now = datetime.now().strftime("%Y-%m-%d")
    params = {"date_from": date_now, "date_to": date_now}
    
    async with aiohttp.ClientSession() as session:
        async with session.get(URL, headers=headers, params=params) as resp:
            data = await resp.json()
            
            total = 0
            print(f"--- ДИАГНОСТИКА: Данные от Langame ---")
            for op in data.get("data", []):
                val = float(op.get("sum", 0))
                # ВАЖНО: Сейчас считаем АБСОЛЮТНО ВСЕ плюсы
                if op.get("type") == "plus" and val > 0:
                    total += val
                    print(f"✅ УЧТЕНО: {op.get('name')} | {val} ₽")
                else:
                    print(f"➖ ПРОПУЩЕНО: {op.get('name')} | {op.get('type')}")
            
            print(f"ИТОГОВАЯ СУММА: {total}")
            return total

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("Бот онлайн. Нажми 'Отчет'", 
                         reply_markup=types.ReplyKeyboardMarkup(
                             keyboard=[[types.KeyboardButton(text="Отчет")]],
                             resize_keyboard=True))

@dp.message(F.text == "Отчет")
async def report(message: types.Message):
    await message.answer("Считаю...")
    res = await get_stats()
    await message.answer(f"Сумма в Langame: {res:,.0f} ₽")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())