import logging
import asyncio
import aiohttp
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command

# Вставьте сюда ВАШ токен прямо в кавычках, чтобы исключить ошибки с .env
TOKEN = "8899799920:AAGH7EXAMPLE_TOKEN_FROM_BOTFATHER" 
API_KEY = "ВАШ_LANGAME_API_KEY"
URL = "https://cyberx302.langame.ru/public_api/all_operations_log/list"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

async def get_total():
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
                # БЕЗ ФИЛЬТРОВ: добавляем всё, что имеет тип 'plus' и сумму > 0
                if op.get("type") == "plus" and val > 0:
                    total += val
                    print(f"✅ УЧТЕНО: {op.get('name')} | {val} ₽")
                else:
                    print(f"➖ ПРОПУЩЕНО: {op.get('name')} | тип: {op.get('type')}")
            
            print(f"ИТОГО: {total}")
            return total

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("Бот готов. Нажми 'Отчет'", reply_markup=types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text="Отчет")]], resize_keyboard=True))

@dp.message(F.text == "Отчет")
async def report(message: types.Message):
    res = await get_total()
    await message.answer(f"Сумма: {res:,.0f} ₽")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())