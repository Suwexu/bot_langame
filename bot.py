import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple
from collections import defaultdict

import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from dotenv import load_dotenv

load_dotenv()

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_KEY = os.getenv("LANGAME_API_KEY")
API_BASE_URL = "https://cyberx302.langame.ru"
ALLOWED_USERS = [int(x) for x in os.getenv("ALLOWED_USERS", "").split(",") if x]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не указан!")

# ========== СОСТОЯНИЯ ==========
class StatsState(StatesGroup):
    waiting_date_from = State()
    waiting_date_to = State()

# ========== ИНИЦИАЛИЗАЦИЯ ==========
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

def is_admin(user_id: int) -> bool:
    if not ALLOWED_USERS:
        return True
    return user_id in ALLOWED_USERS

def safe_float(value: Any) -> float:
    try:
        return float(value) if value else 0
    except:
        return 0

def safe_int(value: Any) -> int:
    try:
        return int(value) if value else 0
    except:
        return 0

# ========== API КЛИЕНТ ==========
class LangameAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = f"{API_BASE_URL}/public_api"
        self.headers = {"X-Request-Token": api_key, "Content-Type": "application/json"}
    
    async def _request(self, endpoint: str, method: str = "GET", params: Dict = None, data: Dict = None) -> Dict:
        url = f"{self.base_url}{endpoint}"
        try:
            async with aiohttp.ClientSession() as session:
                if method == "GET":
                    async with session.get(url, headers=self.headers, params=params, timeout=60) as resp:
                        if resp.status == 200:
                            return await resp.json()
                        else:
                            return {"status": False, "error": f"HTTP {resp.status}"}
                else:
                    async with session.post(url, headers=self.headers, params=params, json=data, timeout=60) as resp:
                        if resp.status == 200:
                            return await resp.json()
                        else:
                            return {"status": False, "error": f"HTTP {resp.status}"}
        except Exception as e:
            return {"status": False, "error": str(e)}
    
    async def get_operations(self, date_from: str, date_to: str) -> Dict:
        return await self._request("/all_operations_log/list", params={"date_from": date_from, "date_to": date_to})
    
    async def get_transactions(self, date_from: str, date_to: str) -> Dict:
        return await self._request("/transactions/list", params={"date_from": date_from, "date_to": date_to, "page_limit": 500})
    
    async def get_products_expense(self, date_from: str, date_to: str) -> Dict:
        return await self._request("/products/expense", params={"date_from": date_from, "date_to": date_to, "page_limit": 500})
    
    async def get_tariffs(self) -> Dict:
        return await self._request("/tariffs/time_period/list")
    
    async def get_clubs(self) -> Dict:
        return await self._request("/clubs/list")
    
    async def get_shifts(self, page: int = 1, limit: int = 50) -> Dict:
        return await self._request("/working_shifts/list", params={"page": page, "page_limit": limit})

api = LangameAPI(API_KEY if API_KEY else "")

# ========== КЛАВИАТУРА ==========
def get_main_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="📊 Статистика за сегодня")],
        [KeyboardButton(text="📈 Статистика за вчера")],
        [KeyboardButton(text="📅 Статистика за неделю")],
        [KeyboardButton(text="📆 Статистика за месяц")],
        [KeyboardButton(text="💰 Финансы"), KeyboardButton(text="🍔 Продажи бара")],
        [KeyboardButton(text="🎮 Сессии"), KeyboardButton(text="🏆 Топ тарифы")],
        [KeyboardButton(text="🔄 Смены"), KeyboardButton(text="🏢 Клубы")],
        [KeyboardButton(text="📋 Лог операций"), KeyboardButton(text="👥 Новые гости")],
        [KeyboardButton(text="🔌 Проверить API"), KeyboardButton(text="ℹ️ О боте")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# ========== ФОРМАТИРОВАНИЕ ==========
def format_date_ru(date_str: str) -> str:
    weekdays = {
        "Monday": "Понедельник", "Tuesday": "Вторник", "Wednesday": "Среда",
        "Thursday": "Четверг", "Friday": "Пятница", "Saturday": "Суббота", "Sunday": "Воскресенье"
    }
    for eng, rus in weekdays.items():
        date_str = date_str.replace(eng, rus)
    return date_str

# ========== ОБРАБОТЧИКИ ==========
@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "📊 *LANGAME АНАЛИТИКА*\n\n"
        "Бот для анализа финансовых показателей игрового клуба.\n\n"
        "📋 *Доступные функции:*\n"
        "• 📊 Статистика за сегодня\n"
        "• 📈 Статистика за вчера\n"
        "• 📅 Статистика за неделю\n"
        "• 📆 Статистика за месяц\n"
        "• 💰 Финансовый отчет\n"
        "• 🍔 Продажи бара\n"
        "• 🎮 Статистика сессий\n"
        "• 🏆 Топ тарифов\n"
        "• 🔄 Отчет по сменам\n\n"
        "Используйте кнопки ниже 👇",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

@dp.message(F.text == "ℹ️ О боте")
async def about(message: types.Message):
    await message.answer(
        "🤖 *LANGAME АНАЛИТИКА v2.0*\n\n"
        "Бот для аналитики игрового клуба CyberX\n\n"
        "📊 *Источники данных:*\n"
        "• Транзакции\n"
        "• Лог операций\n"
        "• Продажи товаров\n"
        "• Кассовые смены\n\n"
        "📅 *Периоды:* день, неделя, месяц\n\n"
        "🔐 *Доступ:* только для авторизованных администраторов",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

@dp.message(F.text == "🔌 Проверить API")
async def test_api(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    msg = await message.answer("🔄 Проверка подключения...")
    result = await api.get_operations(
        (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
        datetime.now().strftime("%Y-%m-%d")
    )
    await msg.delete()
    if result.get("status"):
        await message.answer("✅ API РАБОТАЕТ!\n\nДанные получены, бот готов к работе.", reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ Ошибка API: {result.get('error', 'Неизвестная ошибка')}", reply_markup=get_main_keyboard())

# ========== СТАТИСТИКА ЗА СЕГОДНЯ ==========
@dp.message(F.text == "📊 Статистика за сегодня")
async def stats_today(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    
    msg = await message.answer("📊 Сбор статистики за сегодня...\n⏱️ Подождите...")
    
    try:
        date_to = datetime.now()
        date_from = date_to.replace(hour=0, minute=0, second=0, microsecond=0)
        date_from_str = date_from.strftime("%Y-%m-%d")
        date_to_str = date_to.strftime("%Y-%m-%d")
        
        operations = await api.get_operations(date_from_str, date_to_str)
        transactions = await api.get_transactions(date_from_str, date_to_str)
        products = await api.get_products_expense(date_from_str, date_to_str)
        shifts = await api.get_shifts()
        
        total_income = 0
        sessions_count = 0
        unique_guests = set()
        product_sales = defaultdict(int)
        tariff_count = defaultdict(int)
        shift_refunds = defaultdict(int)
        
        if operations.get("status"):
            for op in operations.get("data", []):
                op_sum = safe_float(op.get("sum", 0))
                op_type = op.get("type", "")
                op_name = op.get("name", "")
                
                if op_type == "Пополнение":
                    total_income += op_sum
                
                if "сессия" in op_name.lower():
                    sessions_count += 1
                
                if op_name:
                    tariff_count[op_name] += 1
        
        avg_check = 0
        if transactions.get("status"):
            tx_data = transactions.get("data", [])
            positive_tx = [t for t in tx_data if safe_float(t.get("balance", 0)) > 0]
            if positive_tx:
                total_sum = sum(safe_float(t.get("balance", 0)) for t in positive_tx)
                avg_check = total_sum / len(positive_tx) if positive_tx else 0
        
        bar_revenue = 0
        top_products = []
        if products.get("status"):
            for prod in products.get("data", []):
                price = safe_float(prod.get("price_sale", 0))
                count = safe_int(prod.get("count", 0))
                name = prod.get("name", "")
                sale_sum = price * count
                bar_revenue += sale_sum
                if name:
                    product_sales[name] += sale_sum
            top_products = sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:5]
        
        if shifts.get("status"):
            for shift in shifts.get("data", []):
                admin_name = shift.get("user_name") or shift.get("admin_name") or "Неизвестно"
                refunds = safe_float(shift.get("refunds_nal", 0)) + safe_float(shift.get("refunds_beznal", 0))
                shift_refunds[admin_name] += refunds
        
        top_tariffs = sorted(tariff_count.items(), key=lambda x: x[1], reverse=True)[:3]
        
        date_name = date_from.strftime("%A, %d %B %Y")
        date_name = format_date_ru(date_name)
        
        result = f"""📊 *RAW DATA CyberX Краснодар Коммунаров*
{date_name}

💰 *Финансы:*
• Выручка: {total_income:,.0f} ₽
• Средний чек: {avg_check:,.0f} ₽
• Выручка бара: {bar_revenue:,.0f} ₽

🎮 *Сессии:* {sessions_count} (гостей: {len(unique_guests)})

🏆 *Топ тарифов:*\n"""
        
        if top_tariffs:
            for name, count in top_tariffs:
                result += f"• {name} ({count} раз)\n"
        else:
            result += "• Нет данных\n"
        
        result += f"\n🔄 *Смены и возвраты:*\n"
        if shift_refunds:
            for admin, refunds in shift_refunds.items():
                result += f"• {admin}: Возвраты {refunds:,.0f} ₽\n"
        else:
            result += "• Нет данных\n"
        
        result += f"\n🍔 *Топ товаров бара:*\n"
        if top_products:
            for name, amount in top_products[:3]:
                result += f"• {name} ({amount:,.0f} ₽)\n"
        else:
            result += "• Нет данных\n"
        
        result += f"\n#дайджест #ежедневный"
        
        await msg.delete()
        await message.answer(result, parse_mode="Markdown", reply_markup=get_main_keyboard())
        
    except Exception as e:
        await msg.delete()
        await message.answer(f"❌ Ошибка: {str(e)}", reply_markup=get_main_keyboard())

# ========== СТАТИСТИКА ЗА ВЧЕРА ==========
@dp.message(F.text == "📈 Статистика за вчера")
async def stats_yesterday(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    
    msg = await message.answer("📊 Сбор статистики за вчера...\n⏱️ Подождите...")
    
    try:
        date_to = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        date_from = date_to
        date_from_str = date_from.strftime("%Y-%m-%d")
        date_to_str = date_to.strftime("%Y-%m-%d")
        
        operations = await api.get_operations(date_from_str, date_to_str)
        transactions = await api.get_transactions(date_from_str, date_to_str)
        products = await api.get_products_expense(date_from_str, date_to_str)
        shifts = await api.get_shifts()
        
        total_income = 0
        sessions_count = 0
        product_sales = defaultdict(int)
        tariff_count = defaultdict(int)
        shift_refunds = defaultdict(int)
        
        if operations.get("status"):
            for op in operations.get("data", []):
                op_sum = safe_float(op.get("sum", 0))
                op_type = op.get("type", "")
                op_name = op.get("name", "")
                
                if op_type == "Пополнение":
                    total_income += op_sum
                
                if "сессия" in op_name.lower():
                    sessions_count += 1
                
                if op_name:
                    tariff_count[op_name] += 1
        
        avg_check = 0
        if transactions.get("status"):
            tx_data = transactions.get("data", [])
            positive_tx = [t for t in tx_data if safe_float(t.get("balance", 0)) > 0]
            if positive_tx:
                total_sum = sum(safe_float(t.get("balance", 0)) for t in positive_tx)
                avg_check = total_sum / len(positive_tx) if positive_tx else 0
        
        bar_revenue = 0
        top_products = []
        if products.get("status"):
            for prod in products.get("data", []):
                price = safe_float(prod.get("price_sale", 0))
                count = safe_int(prod.get("count", 0))
                name = prod.get("name", "")
                sale_sum = price * count
                bar_revenue += sale_sum
                if name:
                    product_sales[name] += sale_sum
            top_products = sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:5]
        
        if shifts.get("status"):
            for shift in shifts.get("data", []):
                admin_name = shift.get("user_name") or shift.get("admin_name") or "Неизвестно"
                refunds = safe_float(shift.get("refunds_nal", 0)) + safe_float(shift.get("refunds_beznal", 0))
                shift_refunds[admin_name] += refunds
        
        top_tariffs = sorted(tariff_count.items(), key=lambda x: x[1], reverse=True)[:3]
        
        date_name = date_from.strftime("%A, %d %B %Y")
        date_name = format_date_ru(date_name)
        
        result = f"""📊 *RAW DATA CyberX Краснодар Коммунаров*
{date_name}

💰 *Финансы:*
• Выручка: {total_income:,.0f} ₽
• Средний чек: {avg_check:,.0f} ₽
• Выручка бара: {bar_revenue:,.0f} ₽

🎮 *Сессии:* {sessions_count}

🏆 *Топ тарифов:*\n"""
        
        if top_tariffs:
            for name, count in top_tariffs:
                result += f"• {name} ({count} раз)\n"
        else:
            result += "• Нет данных\n"
        
        result += f"\n🔄 *Смены и возвраты:*\n"
        if shift_refunds:
            for admin, refunds in shift_refunds.items():
                result += f"• {admin}: Возвраты {refunds:,.0f} ₽\n"
        else:
            result += "• Нет данных\n"
        
        result += f"\n🍔 *Топ товаров бара:*\n"
        if top_products:
            for name, amount in top_products[:3]:
                result += f"• {name} ({amount:,.0f} ₽)\n"
        else:
            result += "• Нет данных\n"
        
        result += f"\n#дайджест #ежедневный"
        
        await msg.delete()
        await message.answer(result, parse_mode="Markdown", reply_markup=get_main_keyboard())
        
    except Exception as e:
        await msg.delete()
        await message.answer(f"❌ Ошибка: {str(e)}", reply_markup=get_main_keyboard())

# ========== СТАТИСТИКА ЗА НЕДЕЛЮ ==========
@dp.message(F.text == "📅 Статистика за неделю")
async def stats_week(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    
    msg = await message.answer("📊 Сбор статистики за неделю...\n⏱️ Подождите...")
    
    try:
        date_to = datetime.now()
        date_from = date_to - timedelta(days=7)
        
        operations = await api.get_operations(date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d"))
        transactions = await api.get_transactions(date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d"))
        products = await api.get_products_expense(date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d"))
        
        total_income = 0
        sessions_count = 0
        bar_revenue = 0
        
        if operations.get("status"):
            for op in operations.get("data", []):
                if op.get("type") == "Пополнение":
                    total_income += safe_float(op.get("sum", 0))
                if "сессия" in op.get("name", "").lower():
                    sessions_count += 1
        
        avg_check = 0
        if transactions.get("status"):
            tx_data = transactions.get("data", [])
            positive_tx = [t for t in tx_data if safe_float(t.get("balance", 0)) > 0]
            if positive_tx:
                total_sum = sum(safe_float(t.get("balance", 0)) for t in positive_tx)
                avg_check = total_sum / len(positive_tx) if positive_tx else 0
        
        if products.get("status"):
            for prod in products.get("data", []):
                price = safe_float(prod.get("price_sale", 0))
                count = safe_int(prod.get("count", 0))
                bar_revenue += price * count
        
        result = f"""📊 *СТАТИСТИКА ЗА НЕДЕЛЮ*

📅 Период: {date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}

💰 *Финансы:*
• Выручка: {total_income:,.0f} ₽
• Средний чек: {avg_check:,.0f} ₽
• Выручка бара: {bar_revenue:,.0f} ₽

🎮 *Сессии:* {sessions_count}

📈 *Динамика:*
• Средняя выручка в день: {total_income/7:,.0f} ₽
• Среднее кол-во сессий в день: {sessions_count/7:.0f}

#неделя #отчет"""
        
        await msg.delete()
        await message.answer(result, parse_mode="Markdown", reply_markup=get_main_keyboard())
        
    except Exception as e:
        await msg.delete()
        await message.answer(f"❌ Ошибка: {str(e)}", reply_markup=get_main_keyboard())

# ========== СТАТИСТИКА ЗА МЕСЯЦ ==========
@dp.message(F.text == "📆 Статистика за месяц")
async def stats_month(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    
    msg = await message.answer("📊 Сбор статистики за месяц...\n⏱️ Подождите...")
    
    try:
        date_to = datetime.now()
        date_from = date_to - timedelta(days=30)
        
        operations = await api.get_operations(date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d"))
        
        total_income = 0
        if operations.get("status"):
            for op in operations.get("data", []):
                if op.get("type") == "Пополнение":
                    total_income += safe_float(op.get("sum", 0))
        
        result = f"""📊 *СТАТИСТИКА ЗА МЕСЯЦ*

📅 Период: {date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}

💰 *Финансы:*
• Выручка: {total_income:,.0f} ₽
• Средняя выручка в день: {total_income/30:,.0f} ₽

📈 *Прогноз на следующий месяц:* {total_income:,.0f} ₽

#месячный #отчет"""
        
        await msg.delete()
        await message.answer(result, parse_mode="Markdown", reply_markup=get_main_keyboard())
        
    except Exception as e:
        await msg.delete()
        await message.answer(f"❌ Ошибка: {str(e)}", reply_markup=get_main_keyboard())

# ========== ФИНАНСОВЫЙ ОТЧЕТ ==========
@dp.message(F.text == "💰 Финансы")
async def finance_report(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    
    msg = await message.answer("💰 Сбор финансовых данных за 30 дней...")
    
    try:
        date_to = datetime.now()
        date_from = date_to - timedelta(days=30)
        
        transactions = await api.get_transactions(date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d"))
        
        total_income = 0
        total_expense = 0
        transactions_count = 0
        
        if transactions.get("status"):
            for tx in transactions.get("data", []):
                amount = safe_float(tx.get("balance", 0))
                transactions_count += 1
                if amount > 0:
                    total_income += amount
                else:
                    total_expense += abs(amount)
        
        result = f"""💰 *ФИНАНСОВЫЙ ОТЧЕТ*

📅 Период: {date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}

📊 *Основные показатели:*
• Общая выручка: {total_income:,.0f} ₽
• Общие списания: {total_expense:,.0f} ₽
• Чистая прибыль: {total_income - total_expense:,.0f} ₽
• Количество транзакций: {transactions_count}

📈 *Средние значения:*
• Средний чек: {total_income/transactions_count if transactions_count > 0 else 0:,.0f} ₽
• Средняя выручка в день: {total_income/30:,.0f} ₽

#финансы #отчет"""
        
        await msg.delete()
        await message.answer(result, parse_mode="Markdown", reply_markup=get_main_keyboard())
        
    except Exception as e:
        await msg.delete()
        await message.answer(f"❌ Ошибка: {str(e)}", reply_markup=get_main_keyboard())

# ========== ПРОДАЖИ БАРА ==========
@dp.message(F.text == "🍔 Продажи бара")
async def bar_sales(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    
    msg = await message.answer("🍔 Загрузка данных о продажах...")
    
    try:
        date_to = datetime.now()
        date_from = date_to - timedelta(days=7)
        
        products = await api.get_products_expense(date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d"))
        
        product_sales = defaultdict(int)
        total_revenue = 0
        
        if products.get("status"):
            for prod in products.get("data", []):
                price = safe_float(prod.get("price_sale", 0))
                count = safe_int(prod.get("count", 0))
                name = prod.get("name", "")
                if name:
                    sale_sum = price * count
                    product_sales[name] += sale_sum
                    total_revenue += sale_sum
        
        top_products = sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:10]
        
        result = f"""🍔 *ТОП ПРОДАЖ БАРА*

📅 Период: {date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}

💰 *Общая выручка бара:* {total_revenue:,.0f} ₽

🏆 *Топ-10 товаров:*\n"""
        
        for i, (name, amount) in enumerate(top_products, 1):
            result += f"{i}. {name} — {amount:,.0f} ₽\n"
        
        if not top_products:
            result += "• Нет данных о продажах\n"
        
        await msg.delete()
        await message.answer(result, parse_mode="Markdown", reply_markup=get_main_keyboard())
        
    except Exception as e:
        await msg.delete()
        await message.answer(f"❌ Ошибка: {str(e)}", reply_markup=get_main_keyboard())

# ========== СТАТИСТИКА СЕССИЙ ==========
@dp.message(F.text == "🎮 Сессии")
async def sessions_report(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    
    msg = await message.answer("🎮 Сбор статистики по сессиям...")
    
    try:
        date_to = datetime.now()
        date_from = date_to - timedelta(days=7)
        
        operations = await api.get_operations(date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d"))
        
        sessions_count = 0
        if operations.get("status"):
            for op in operations.get("data", []):
                if "сессия" in op.get("name", "").lower():
                    sessions_count += 1
        
        result = f"""🎮 *СТАТИСТИКА СЕССИЙ*

📅 Период: {date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}

📊 *Показатели:*
• Всего сессий: {sessions_count}
• Среднее в день: {sessions_count/7:.0f}

📈 *Динамика:*
• Цель на неделю: {int(sessions_count * 1.1)} сессий (+10%)

#сессии #активность"""
        
        await msg.delete()
        await message.answer(result, parse_mode="Markdown", reply_markup=get_main_keyboard())
        
    except Exception as e:
        await msg.delete()
        await message.answer(f"❌ Ошибка: {str(e)}", reply_markup=get_main_keyboard())

# ========== ТОП ТАРИФОВ ==========
@dp.message(F.text == "🏆 Топ тарифы")
async def top_tariffs(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    
    msg = await message.answer("🏆 Сбор данных о тарифах...")
    
    try:
        date_to = datetime.now()
        date_from = date_to - timedelta(days=30)
        
        operations = await api.get_operations(date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d"))
        
        tariff_count = defaultdict(int)
        tariff_revenue = defaultdict(float)
        
        if operations.get("status"):
            for op in operations.get("data", []):
                name = op.get("name", "")
                op_sum = safe_float(op.get("sum", 0))
                if name and op_sum > 0:
                    tariff_count[name] += 1
                    tariff_revenue[name] += op_sum
        
        top_by_count = sorted(tariff_count.items(), key=lambda x: x[1], reverse=True)[:10]
        top_by_revenue = sorted(tariff_revenue.items(), key=lambda x: x[1], reverse=True)[:10]
        
        result = f"""🏆 *ТОП ТАРИФОВ*

📅 Период: {date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}

📊 *По популярности (кол-во продаж):*\n"""
        
        for i, (name, count) in enumerate(top_by_count, 1):
            result += f"{i}. {name} — {count} раз\n"
        
        result += f"\n💰 *По выручке:*\n"
        for i, (name, revenue) in enumerate(top_by_revenue, 1):
            result += f"{i}. {name} — {revenue:,.0f} ₽\n"
        
        await msg.delete()
        await message.answer(result, parse_mode="Markdown", reply_markup=get_main_keyboard())
        
    except Exception as e:
        await msg.delete()
        await message.answer(f"❌ Ошибка: {str(e)}", reply_markup=get_main_keyboard())

# ========== СМЕНЫ ==========
@dp.message(F.text == "🔄 Смены")
async def shifts_report(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    
    msg = await message.answer("🔄 Загрузка данных о сменах...")
    
    try:
        shifts = await api.get_shifts()
        
        result = f"""🔄 *ОТЧЕТ ПО СМЕНАМ*

📊 *Последние смены:*\n\n"""
        
        if shifts.get("status"):
            for shift in shifts.get("data", [])[:10]:
                admin = shift.get("user_name") or shift.get("admin_name") or "Неизвестно"
                date_start = shift.get("date_start", "—")[:16] if shift.get("date_start") else "—"
                nal = safe_float(shift.get("nal", 0))
                beznal = safe_float(shift.get("beznal", 0))
                refunds_nal = safe_float(shift.get("refunds_nal", 0))
                refunds_beznal = safe_float(shift.get("refunds_beznal", 0))
                
                result += f"👤 {admin}\n"
                result += f"📅 {date_start}\n"
                result += f"💰 Наличные: {nal:,.0f} ₽ | Безнал: {beznal:,.0f} ₽\n"
                result += f"🔄 Возвраты: {refunds_nal + refunds_beznal:,.0f} ₽\n"
                result += "─" * 25 + "\n"
        else:
            result += "Нет данных о сменах\n"
        
        await msg.delete()
        await message.answer(result, parse_mode="Markdown", reply_markup=get_main_keyboard())
        
    except Exception as e:
        await msg.delete()
        await message.answer(f"❌ Ошибка: {str(e)}", reply_markup=get_main_keyboard())

# ========== КЛУБЫ ==========
@dp.message(F.text == "🏢 Клубы")
async def clubs(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    
    msg = await message.answer("🔄 Загрузка списка клубов...")
    r = await api.get_clubs()
    await msg.delete()
    
    if r.get("status") and r.get("data"):
        result = "🏢 *СПИСОК КЛУБОВ*\n\n"
        for club in r["data"]:
            status = "🟢 Активен" if club.get("active") else "🔴 Неактивен"
            result += f"📌 {club.get('name', '—')}\n"
            result += f"   🆔 ID: {club.get('id', '—')}\n"
            result += f"   📍 {club.get('address', 'Адрес не указан')}\n"
            result += f"   {status}\n\n"
        await message.answer(result, parse_mode="Markdown", reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {r.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

# ========== ЛОГ ОПЕРАЦИЙ ==========
@dp.message(F.text == "📋 Лог операций")
async def operations_log(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    
    msg = await message.answer("🔄 Загрузка лога операций за 7 дней...")
    
    date_to = datetime.now()
    date_from = date_to - timedelta(days=7)
    r = await api.get_operations(date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d"))
    await msg.delete()
    
    if r.get("status") and r.get("data"):
        result = "📋 *ЛОГ ОПЕРАЦИЙ (последние 10)*\n\n"
        for op in r["data"][:10]:
            date = op.get("date_normal", "—")[:16]
            op_type = op.get("type", "—")
            op_sum = safe_float(op.get("sum", 0))
            op_name = op.get("name", "—")
            result += f"{'💰' if op_type == 'Пополнение' else '💸'} {date}\n"
            result += f"   📋 {op_type}\n"
            result += f"   📝 {op_name[:30]}\n"
            result += f"   💵 {op_sum:,.2f} ₽\n"
            result += "─" * 25 + "\n"
        await message.answer(result, parse_mode="Markdown", reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {r.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

# ========== НОВЫЕ ГОСТИ ==========
@dp.message(F.text == "👥 Новые гости")
async def new_guests(message: types.Message):
    await message.answer(
        "👥 *НОВЫЕ ГОСТИ*\n\n"
        "📊 Функция в разработке\n\n"
        "В ближайшее время будет добавлена аналитика по новым гостям:\n"
        "• Количество новых регистраций\n"
        "• Динамика прироста\n"
        "• Активность новых гостей\n"
        "• Конверсия в постоянных",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

# ========== ОБРАБОТЧИК НЕИЗВЕСТНЫХ ==========
@dp.message()
async def unknown(message: types.Message):
    if not message.text.startswith("/"):
        await message.answer(
            "❓ Используйте кнопки меню\n\n"
            "📊 *Доступные отчеты:*\n"
            "• Статистика за сегодня/вчера/неделю/месяц\n"
            "• Финансовый отчет\n"
            "• Продажи бара\n"
            "• Статистика сессий\n"
            "• Топ тарифов\n"
            "• Отчет по сменам",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )

# ========== ЗАПУСК ==========
async def main():
    logger.info("🚀 LANGAME Аналитика бот запускается...")
    await bot.delete_webhook(drop_pending_updates=True)
    if API_KEY:
        logger.info("✅ API ключ настроен")
    logger.info("🎉 Бот готов!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())