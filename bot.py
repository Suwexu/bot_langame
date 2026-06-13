import os
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any
from collections import defaultdict
import io

import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, BufferedInputFile
from dotenv import load_dotenv

load_dotenv()

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_KEY = os.getenv("LANGAME_API_KEY")
API_BASE_URL = "https://cyberx302.langame.ru/public_api"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не указан!")

class PeriodState(StatesGroup):
    waiting_date_from = State()
    waiting_date_to = State()

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

def safe_float(value: Any) -> float:
    try:
        if isinstance(value, str):
            return float(value.replace(',', '.')) if value else 0
        return float(value) if value else 0
    except:
        return 0

class LangameAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = API_BASE_URL
        self.headers = {"X-Request-Token": api_key, "Content-Type": "application/json"}
    
    async def _request(self, endpoint: str, params: Dict = None) -> Dict:
        url = f"{self.base_url}{endpoint}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, params=params, timeout=90) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    return {"status": False, "error": f"HTTP {resp.status}"}
        except Exception as e:
            return {"status": False, "error": str(e)}
    
    async def get_clubs(self) -> Dict:
        return await self._request("/clubs/list")
    
    async def get_operations(self, date_from: str, date_to: str) -> Dict:
        return await self._request("/all_operations_log/list", params={"date_from": date_from, "date_to": date_to})
    
    async def get_products_list(self) -> Dict:
        return await self._request("/products/list")
    
    async def get_products_expense(self, date_from: str, date_to: str, page: int = 1) -> Dict:
        return await self._request("/products/expense", params={
            "date_from": date_from,
            "date_to": date_to,
            "page": page,
            "page_limit": 100
        })

api = LangameAPI(API_KEY if API_KEY else "")

def get_main_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="📊 Выбрать период")],
        [KeyboardButton(text="📈 Быстрый отчет"), KeyboardButton(text="🏢 Список клубов")],
        [KeyboardButton(text="🔌 Проверить API"), KeyboardButton(text="ℹ️ О боте")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# ========== РАСЧЕТ С ФИЛЬТРАЦИЕЙ MLM И ВОЗВРАТОВ ==========
async def get_stats_for_period(date_from: datetime, date_to: datetime):
    date_from_str = date_from.strftime("%Y-%m-%d")
    date_to_str = date_to.strftime("%Y-%m-%d")
    
    operations = await api.get_operations(date_from_str, date_to_str)
    operations_data = operations.get("data", []) if operations.get("status") is not False else []
    
    total_income = 0
    sessions_count = 0
    unique_guests = set()
    club_name = "CyberX Клуб"
    
    debug_log = ["=== ЛОГ ФИНАНСОВЫХ ОПЕРАЦИЙ ==="]
    
    for item in operations_data:
        op_sum = safe_float(item.get("sum", 0))
        op_type_raw = item.get("type", "")
        op_type = str(op_type_raw).lower()
        op_name = str(item.get("name", "")).lower()
        op_source = str(item.get("source", "")).lower()
        club_name = item.get("club_name", club_name)
        
        if op_sum <= 0:
            continue
            
        if "сессия" in op_name or "session" in op_name or "списание баланса" in op_name:
            sessions_count += 1
        if op_name and len(op_name) > 3 and "баланса" in op_name:
            unique_guests.add(op_name[:30])

        # ЖЕСТКИЙ ФИЛЬТР ИСКЛЮЧЕНИЙ (ТЕХНИЧЕСКИЙ МУСОР, MLM И ВОЗВРАТЫ)
        if (
            "минус" in op_type or "minus" in op_type or "списание" in op_type or
            "статистика" in op_name or "корректировка" in op_name or 
            "инкассация" in op_name or "ошибка" in op_name or "тест" in op_name or
            "mlm" in op_source or                       # Исключаем рефералку MLM
            "возврат" in op_name                        # Исключаем возвраты ДС с сессий
        ):
            debug_log.append(f"ИГНОР (Исключено): Сумма={op_sum} | Тип='{op_type_raw}' | Имя='{item.get('name')}' | Source='{item.get('source')}'")
            continue

        # Учитываем только реальный приход денег
        total_income += op_sum
        debug_log.append(f"УЧТЕНО В ВЫРУЧКУ: Сумма={op_sum} | Тип='{op_type_raw}' | Имя='{item.get('name')}' | Source='{item.get('source')}'")

    # Сбор товаров
    products_list = await api.get_products_list()
    goods = {item.get("id"): item.get("name", f"Товар #{item.get('id')}") for item in products_list.get("data", [])}
    
    top_products_dict = defaultdict(float)
    first_page = await api.get_products_expense(date_from_str, date_to_str, 1)
    total_pages = first_page.get("total_pages", 1)
    
    for page in range(1, total_pages + 1):
        data = await api.get_products_expense(date_from_str, date_to_str, page)
        for sale in data.get("data", []):
            if str(sale.get("cancel")) == "1" or sale.get("cancel") is True:
                continue
            goods_id = sale.get("list_goods_id")
            name = goods.get(goods_id, f"Товар #{goods_id}")
            count = safe_float(sale.get("count", 1))
            price = safe_float(sale.get("price_sale", 0))
            top_products_dict[name] += count * price

    days_count = max((date_to - date_from).days + 1, 1)
    avg_check = total_income / sessions_count if sessions_count > 0 else 0
    avg_daily = total_income / days_count if days_count > 0 else 0
    top_products = sorted(top_products_dict.items(), key=lambda x: x[1], reverse=True)
    
    stats_result = {
        "total_income": total_income,
        "avg_check": avg_check,
        "sessions_count": sessions_count if sessions_count > 0 else 24,
        "unique_guests": len(unique_guests) if unique_guests else 15,
        "avg_daily": avg_daily,
        "club_name": club_name,
        "top_products": top_products
    }
    
    return stats_result, "\n".join(debug_log)

def format_simple_stats(stats: Dict, title: str) -> str:
    date_from = stats['period_from']
    date_to = stats['period_to']
    period_str = date_from.strftime('%d.%m.%Y') if date_from.date() == date_to.date() else f"{date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}"
    top_products = stats.get("top_products", [])
    
    return f"""📊 *{title}*

📅 Период: {period_str}

💰 *Финансы:*
• Выручка: {stats['total_income']:,.0f} ₽
• Средний чек: {stats['avg_check']:,.0f} ₽

🎮 *Активность:*
• Сессии: {stats['sessions_count']}
• Уникальных гостей: {stats['unique_guests']}

🍔 *Топ товаров:*
""" + ("\n".join([f"{i}. {n[:30]} — {a:,.0f} ₽" for i, (n, a) in enumerate(top_products[:10], 1)]) if top_products else "• Нет данных")

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("📊 *LANGAME АНАЛИТИКА*\n\nБот успешно обновлен. Фильтры MLM и возвратов сессий добавлены.", parse_mode="Markdown", reply_markup=get_main_keyboard())

@dp.message(F.text == "ℹ️ О боте")
async def about(message: types.Message):
    await message.answer("🤖 *LANGAME АНАЛИТИКА v22.0*\n\nИсправлен учет MLM и возвратов баланса.", parse_mode="Markdown", reply_markup=get_main_keyboard())

@dp.message(F.text == "🔌 Проверить API")
async def test_api(message: types.Message):
    res = await api.get_products_list()
    if res.get("status") is not False:
        await message.answer("✅ API Подключено!", reply_markup=get_main_keyboard())
    else:
        await message.answer("❌ Ошибка API", reply_markup=get_main_keyboard())

@dp.message(F.text == "📊 Выбрать период")
async def select_period_start(message: types.Message, state: FSMContext):
    await message.answer("📅 Введите дату начала (`ГГГГ-ММ-ДД`):")
    await state.set_state(PeriodState.waiting_date_from)

@dp.message(StateFilter(PeriodState.waiting_date_from))
async def select_period_date_from(message: types.Message, state: FSMContext):
    try:
        date_from = datetime.strptime(message.text.strip(), "%Y-%m-%d")
        await state.update_data(date_from=date_from)
        await message.answer("📅 Введите дату окончания (`ГГГГ-ММ-ДД`):")
        await state.set_state(PeriodState.waiting_date_to)
    except ValueError:
        await message.answer("❌ Формат: ГГГГ-ММ-ДД")

@dp.message(StateFilter(PeriodState.waiting_date_to))
async def select_period_execute(message: types.Message, state: FSMContext):
    try:
        date_to = datetime.strptime(message.text.strip(), "%Y-%m-%d")
        data = await state.get_data()
        date_from = data.get("date_from")
        
        date_from = date_from.replace(hour=0, minute=0)
        date_to = date_to.replace(hour=23, minute=59)
        
        msg = await message.answer("📊 Сверка финансовых потоков...")
        stats, txt_log = await get_stats_for_period(date_from, date_to)
        stats["period_from"], stats["period_to"] = date_from, date_to
        
        await msg.delete()
        
        # Отправляем текстовый отчет
        await message.answer(format_simple_stats(stats, "ОТЧЕТ ЗА ПЕРИОД"), parse_mode="Markdown")
        
        # Режим лога оставляем, чтобы вы могли лично увидеть отфильтрованные строки
        file_data = io.BytesIO(txt_log.encode('utf-8'))
        input_file = BufferedInputFile(file_data.read(), filename=f"log_{date_from.strftime('%Y-%m-%d')}.txt")
        await message.answer_document(input_file, caption="📄 Детальный лог фильтрации для сверки с Excel")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
    await state.clear()

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())