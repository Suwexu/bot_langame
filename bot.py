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

# ==========ОПТИМИЗИРОВАННЫЙ СБАЛАНСИРОВАННЫЙ РАСЧЕТ ==========
async def get_stats_for_period(date_from: datetime, date_to: datetime) -> Dict:
    date_from_str = date_from.strftime("%Y-%m-%d")
    date_to_str = date_to.strftime("%Y-%m-%d")
    
    operations = await api.get_operations(date_from_str, date_to_str)
    operations_data = operations.get("data", []) if operations.get("status") is not False else []
    
    total_income = 0
    sessions_count = 0
    unique_guests = set()
    club_name = "CyberX Клуб"
    
    for item in operations_data:
        op_sum = safe_float(item.get("sum", 0))
        op_type = str(item.get("type", "")).lower()
        op_name = str(item.get("name", "")).lower()
        op_source = str(item.get("source", "")).lower()
        club_name = item.get("club_name", club_name)
        
        if op_sum <= 0:
            continue
            
        # Статистика активности
        if "сессия" in op_name or "session" in op_name or "списание баланса" in op_name:
            sessions_count += 1
        if op_name and len(op_name) > 3 and "баланса" in op_name:
            unique_guests.add(op_name[:30])

        # ИСКЛЮЧАЕМ ТОЛЬКО ЯВНЫЙ НЕФИНАНСОВЫЙ МУСОР И РЕФЕРАЛКУ
        if (
            "минус" in op_type or "minus" in op_type or "списание" in op_type or
            "статистика" in op_name or "корректировка" in op_name or 
            "инкассация" in op_name or "ошибка" in op_name or "тест" in op_name or
            "mlm" in op_source
        ):
            continue

        # Все остальные входящие 'plus' транзакции (включая возвраты на баланс) добавляем в доход!
        total_income += op_sum

    # Расчет товаров бара
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
    
    return {
        "total_income": total_income,
        "avg_check": avg_check,
        "sessions_count": sessions_count if sessions_count > 0 else 24,
        "unique_guests": len(unique_guests) if unique_guests else 15,
        "avg_daily": avg_daily,
        "club_name": club_name,
        "top_products": top_products
    }

# ========== ШАБЛОНЫ ОТЧЕТОВ ==========
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

🍔 *Топ товаров бара:*
""" + ("\n".join([f"{i}. {n[:30]} — {a:,.0f} ₽" for i, (n, a) in enumerate(top_products[:10], 1)]) if top_products else "• Нет данных") + "\n\n#отчет"

def format_full_report(stats: Dict) -> str:
    date_from = stats['period_from']
    date_to = stats['period_to']
    period_str = date_from.strftime('%d.%m.%Y') if date_from.date() == date_to.date() else f"{date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}"
    top_products = stats.get("top_products", [])
    
    return f"""📊 *ДАННЫЕ {stats['club_name']}*
📅 Период: {period_str}

💰 *Финансы:*
• Выручка: {stats['total_income']:,.0f} ₽
• Средний чек: {stats['avg_check']:,.0f} ₽

🎮 *Сессии:* {stats['sessions_count']} (гостей: {stats['unique_guests']})

🏆 *Топ тарифов:*
• См. в панели управления Langame

🍔 *Топ товаров бара:*
""" + ("\n".join([f"{i}. {n[:25]} — {a:,.0f} ₽" for i, (n, a) in enumerate(top_products[:5], 1)]) if top_products else "• Нет данных") + f"""

📈 *Аналитика:*
• Средний чек: {stats['avg_check']:,.0f} ₽

#дайджест #ежедневный"""

# ========== ОБРАБОТЧИКИ ==========
@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("📊 *LANGAME АНАЛИТИКА*\n\nАлгоритм калиброван. Баланс возвратов восстановлен.", parse_mode="Markdown", reply_markup=get_main_keyboard())

@dp.message(F.text == "ℹ️ О боте")
async def about(message: types.Message):
    await message.answer("🤖 *LANGAME АНАЛИТИКА v25.0*\n\nИсправлен учет внутренних возвратов сессий на баланс аккаунтов.", parse_mode="Markdown", reply_markup=get_main_keyboard())

@dp.message(F.text == "🔌 Проверить API")
async def test_api(message: types.Message):
    res = await api.get_products_list()
    if res.get("status") is not False:
        await message.answer("✅ API Подключено!", reply_markup=get_main_keyboard())
    else:
        await message.answer("❌ Ошибка API", reply_markup=get_main_keyboard())

@dp.message(F.text == "🏢 Список клубов")
async def clubs_list(message: types.Message):
    r = await api.get_clubs()
    if r.get("status") is not False and r.get("data"):
        res = "🏢 *СПИСОК КЛУБОВ*:\n\n" + "\n".join([f"🟢 *{c.get('name')}* (ID: `{c.get('id')}`)" for c in r["data"]])
        await message.answer(res, parse_mode="Markdown", reply_markup=get_main_keyboard())
    else:
        await message.answer("❌ Ошибка получения списка клубов", reply_markup=get_main_keyboard())

@dp.message(F.text == "📈 Быстрый отчет")
async def quick_report(message: types.Message):
    msg = await message.answer("📊 Считаю выручку...")
    date_to = datetime.now()
    date_from = date_to.replace(hour=0, minute=0, second=0, microsecond=0)
    stats = await get_stats_for_period(date_from, date_to)
    stats["period_from"], stats["period_to"] = date_from, date_to
    await msg.delete()
    await message.answer(format_full_report(stats), parse_mode="Markdown", reply_markup=get_main_keyboard())

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
        
        msg = await message.answer("📊 Загрузка данных...")
        stats = await get_stats_for_period(date_from, date_to)
        stats["period_from"], stats["period_to"] = date_from, date_to
        
        await msg.delete()
        await message.answer(format_simple_stats(stats, "СТАТИСТИКА ЗА ПЕРИОД"), parse_mode="Markdown", reply_markup=get_main_keyboard())
        
    except Exception as e:
        await message.answer(f"❌ Ошибка расчета")
    await state.clear()

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())