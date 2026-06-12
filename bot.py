import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple
from collections import defaultdict

import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
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
        if isinstance(value, str):
            return float(value.replace(',', '.')) if value else 0
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
    
    async def _request(self, endpoint: str, method: str = "GET", params: Dict = None) -> Dict:
        url = f"{self.base_url}{endpoint}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, params=params, timeout=90) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        return {"status": False, "error": f"HTTP {resp.status}"}
        except Exception as e:
            return {"status": False, "error": str(e)}
    
    # ========== ОСНОВНЫЕ ЭНДПОИНТЫ ==========
    async def get_balances_list(self, date_from: str, date_to: str, page: int = 1, limit: int = 100) -> Dict:
        """Пополнения баланса - /balances/list"""
        return await self._request("/balances/list", params={
            "date_from": date_from, "date_to": date_to, "page": page, "page_limit": limit
        })
    
    async def get_guests_balance(self, page: int = 1, limit: int = 100) -> Dict:
        """Балансы гостей - /guests/balance"""
        return await self._request("/guests/balance", params={"page": page, "page_limit": limit})
    
    async def get_transactions(self, date_from: str = None, date_to: str = None, page: int = 1, limit: int = 100) -> Dict:
        """Транзакции - /transactions/list"""
        params = {"page": page, "page_limit": limit}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        return await self._request("/transactions/list", params=params)
    
    async def get_operations_log(self, date_from: str = None, date_to: str = None) -> Dict:
        """Лог операций - /all_operations_log/list"""
        params = {}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        return await self._request("/all_operations_log/list", params=params)
    
    async def get_working_shifts(self, page: int = 1, limit: int = 50) -> Dict:
        """Смены - /working_shifts/list"""
        return await self._request("/working_shifts/list", params={"page": page, "page_limit": limit})
    
    async def get_products_expense(self, date_from: str = None, date_to: str = None, page: int = 1, limit: int = 100) -> Dict:
        """Продажи товаров - /products/expense"""
        params = {"page": page, "page_limit": limit}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        return await self._request("/products/expense", params=params)
    
    async def get_clubs(self) -> Dict:
        """Клубы - /clubs/list"""
        return await self._request("/clubs/list")

api = LangameAPI(API_KEY if API_KEY else "")

# ========== КЛАВИАТУРА ==========
def get_main_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="📊 Статистика за сегодня")],
        [KeyboardButton(text="📈 Статистика за вчера")],
        [KeyboardButton(text="📅 Статистика за неделю")],
        [KeyboardButton(text="📆 Статистика за месяц")],
        [KeyboardButton(text="💰 Финансы"), KeyboardButton(text="🍔 Продажи")],
        [KeyboardButton(text="🔄 Смены"), KeyboardButton(text="🏢 Клубы")],
        [KeyboardButton(text="📋 Лог операций"), KeyboardButton(text="🔌 Проверить API")],
        [KeyboardButton(text="ℹ️ О боте")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# ========== ФОРМАТИРОВАНИЕ ==========
def format_date_ru(date_str: str) -> str:
    weekdays = {
        "Monday": "Понедельник", "Tuesday": "Вторник", "Wednesday": "Среда",
        "Thursday": "Четверг", "Friday": "Пятница", "Saturday": "Суббота", "Sunday": "Воскресенье"
    }
    months = {
        "January": "января", "February": "февраля", "March": "марта",
        "April": "апреля", "May": "мая", "June": "июня",
        "July": "июля", "August": "августа", "September": "сентября",
        "October": "октября", "November": "ноября", "December": "декабря"
    }
    for eng, rus in weekdays.items():
        date_str = date_str.replace(eng, rus)
    for eng, rus in months.items():
        date_str = date_str.replace(eng, rus)
    return date_str

# ========== АНАЛИТИЧЕСКИЕ ФУНКЦИИ ==========
async def get_daily_stats(date_from: datetime, date_to: datetime) -> Dict:
    """Получение статистики за день"""
    date_from_str = date_from.strftime("%Y-%m-%d")
    date_to_str = date_to.strftime("%Y-%m-%d")
    
    # Получаем данные из разных эндпоинтов
    balances = await api.get_balances_list(date_from_str, date_to_str, limit=200)
    transactions = await api.get_transactions(date_from_str, date_to_str, limit=200)
    operations = await api.get_operations_log(date_from_str, date_to_str)
    products = await api.get_products_expense(date_from_str, date_to_str, limit=200)
    
    # Сбор статистики
    total_income = 0
    sessions_count = 0
    unique_guests = set()
    product_sales = defaultdict(int)
    tariff_count = defaultdict(int)
    bar_revenue = 0
    
    # Из balances (пополнения)
    if balances.get("status") and balances.get("data"):
        for item in balances["data"]:
            amount = safe_float(item.get("amount", 0))
            total_income += amount
            guest_name = item.get("guest_name", "")
            if guest_name:
                unique_guests.add(guest_name)
    
    # Из transactions (транзакции)
    if transactions.get("status") and transactions.get("data"):
        for item in transactions["data"]:
            amount = safe_float(item.get("balance", 0))
            if amount > 0:
                total_income = max(total_income, amount)  # используем balances для точности
    
    # Из operations (лог операций)
    if operations.get("status") and operations.get("data"):
        for item in operations["data"]:
            op_sum = safe_float(item.get("sum", 0))
            op_type = item.get("type", "")
            op_name = item.get("name", "")
            op_source = item.get("source", "")
            
            # Пополнения
            if op_type == "Пополнение" and op_sum > 0:
                total_income = max(total_income, op_sum)
            
            # Сессии
            if "сессия" in op_name.lower() or "session" in op_name.lower():
                sessions_count += 1
            
            # Тарифы
            if op_name and "тариф" in op_name.lower():
                tariff_count[op_name] += 1
    
    # Из products (продажи)
    if products.get("status") and products.get("data"):
        for item in products["data"]:
            price = safe_float(item.get("price_sale", 0))
            count = safe_int(item.get("count", 0))
            name = item.get("name", "")
            sale_sum = price * count
            bar_revenue += sale_sum
            if name:
                product_sales[name] += sale_sum
    
    # Средний чек
    avg_check = 0
    if transactions.get("status") and transactions.get("data"):
        positive_tx = [t for t in transactions["data"] if safe_float(t.get("balance", 0)) > 0]
        if positive_tx:
            total_sum = sum(safe_float(t.get("balance", 0)) for t in positive_tx)
            avg_check = total_sum / len(positive_tx) if positive_tx else 0
    
    # Топ товаров
    top_products = sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:5]
    
    # Топ тарифов
    top_tariffs = sorted(tariff_count.items(), key=lambda x: x[1], reverse=True)[:3]
    
    return {
        "total_income": total_income,
        "avg_check": avg_check,
        "bar_revenue": bar_revenue,
        "sessions_count": sessions_count,
        "unique_guests": len(unique_guests),
        "top_products": top_products,
        "top_tariffs": top_tariffs
    }

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
        "• 🍔 Продажи\n"
        "• 🔄 Отчет по сменам\n"
        "• 📋 Лог операций\n\n"
        "Используйте кнопки ниже 👇",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

@dp.message(F.text == "ℹ️ О боте")
async def about(message: types.Message):
    await message.answer(
        "🤖 *LANGAME АНАЛИТИКА v2.0*\n\n"
        "Бот для аналитики игрового клуба\n\n"
        "📊 *Источники данных:*\n"
        "• Пополнения баланса\n"
        "• Транзакции\n"
        "• Лог операций\n"
        "• Продажи товаров\n"
        "• Кассовые смены\n\n"
        "📅 *Периоды:* день, неделя, месяц",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

@dp.message(F.text == "🔌 Проверить API")
async def test_api(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    msg = await message.answer("🔄 Проверка подключения...")
    result = await api.get_clubs()
    await msg.delete()
    if result.get("status"):
        clubs_count = len(result.get("data", []))
        await message.answer(f"✅ API РАБОТАЕТ!\n\n📊 Доступно клубов: {clubs_count}\n🔑 API Key: Настроен", reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ Ошибка API: {result.get('error', 'Неизвестная ошибка')}", reply_markup=get_main_keyboard())

# ========== СТАТИСТИКА ЗА СЕГОДНЯ ==========
@dp.message(F.text == "📊 Статистика за сегодня")
async def stats_today(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    
    msg = await message.answer("📊 Сбор статистики за сегодня...\n⏱️ Подождите до 30 секунд...")
    
    try:
        date_to = datetime.now()
        date_from = date_to.replace(hour=0, minute=0, second=0, microsecond=0)
        
        stats = await get_daily_stats(date_from, date_to)
        
        date_name = date_from.strftime("%A, %d %B %Y")
        date_name = format_date_ru(date_name)
        
        result = f"""📊 *RAW DATA CyberX Краснодар Коммунаров*
{date_name}

💰 *Финансы:*
• Выручка: {stats['total_income']:,.0f} ₽
• Средний чек: {stats['avg_check']:,.0f} ₽
• Выручка бара: {stats['bar_revenue']:,.0f} ₽

🎮 *Сессии:* {stats['sessions_count']} (гостей: {stats['unique_guests']})

🏆 *Топ тарифов:*\n"""
        
        if stats['top_tariffs']:
            for name, count in stats['top_tariffs']:
                result += f"• {name[:30]} ({count} раз)\n"
        else:
            result += "• Нет данных\n"
        
        result += f"\n🍔 *Топ товаров бара:*\n"
        if stats['top_products']:
            for name, amount in stats['top_products'][:3]:
                short_name = name[:25] + "..." if len(name) > 25 else name
                result += f"• {short_name} ({amount:,.0f} ₽)\n"
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
    
    msg = await message.answer("📊 Сбор статистики за вчера...\n⏱️ Подождите до 30 секунд...")
    
    try:
        date_to = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        date_from = date_to
        
        stats = await get_daily_stats(date_from, date_to)
        
        date_name = date_from.strftime("%A, %d %B %Y")
        date_name = format_date_ru(date_name)
        
        result = f"""📊 *RAW DATA CyberX Краснодар Коммунаров*
{date_name}

💰 *Финансы:*
• Выручка: {stats['total_income']:,.0f} ₽
• Средний чек: {stats['avg_check']:,.0f} ₽
• Выручка бара: {stats['bar_revenue']:,.0f} ₽

🎮 *Сессии:* {stats['sessions_count']}

🏆 *Топ тарифов:*\n"""
        
        if stats['top_tariffs']:
            for name, count in stats['top_tariffs']:
                result += f"• {name[:30]} ({count} раз)\n"
        else:
            result += "• Нет данных\n"
        
        result += f"\n🍔 *Топ товаров бара:*\n"
        if stats['top_products']:
            for name, amount in stats['top_products'][:3]:
                short_name = name[:25] + "..." if len(name) > 25 else name
                result += f"• {short_name} ({amount:,.0f} ₽)\n"
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
    
    msg = await message.answer("📊 Сбор статистики за неделю...\n⏱️ Подождите до 60 секунд...")
    
    try:
        date_to = datetime.now()
        date_from = date_to - timedelta(days=7)
        date_from_str = date_from.strftime("%Y-%m-%d")
        date_to_str = date_to.strftime("%Y-%m-%d")
        
        # Получаем данные за неделю
        balances = await api.get_balances_list(date_from_str, date_to_str, limit=500)
        operations = await api.get_operations_log(date_from_str, date_to_str)
        products = await api.get_products_expense(date_from_str, date_to_str, limit=500)
        
        total_income = 0
        sessions_count = 0
        bar_revenue = 0
        tariff_count = defaultdict(int)
        
        if balances.get("status") and balances.get("data"):
            for item in balances["data"]:
                total_income += safe_float(item.get("amount", 0))
        
        if operations.get("status") and operations.get("data"):
            for item in operations["data"]:
                op_name = item.get("name", "")
                if "сессия" in op_name.lower():
                    sessions_count += 1
                if op_name and "тариф" in op_name.lower():
                    tariff_count[op_name] += 1
        
        if products.get("status") and products.get("data"):
            for item in products["data"]:
                price = safe_float(item.get("price_sale", 0))
                count = safe_int(item.get("count", 0))
                bar_revenue += price * count
        
        # Средний чек
        transactions = await api.get_transactions(date_from_str, date_to_str, limit=500)
        avg_check = 0
        if transactions.get("status") and transactions.get("data"):
            positive_tx = [t for t in transactions["data"] if safe_float(t.get("balance", 0)) > 0]
            if positive_tx:
                total_sum = sum(safe_float(t.get("balance", 0)) for t in positive_tx)
                avg_check = total_sum / len(positive_tx) if positive_tx else 0
        
        top_tariffs = sorted(tariff_count.items(), key=lambda x: x[1], reverse=True)[:3]
        
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

🏆 *Топ тарифов:*\n"""
        
        if top_tariffs:
            for name, count in top_tariffs:
                result += f"• {name[:30]} ({count} раз)\n"
        else:
            result += "• Нет данных\n"
        
        result += f"\n#неделя #отчет"
        
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
    
    msg = await message.answer("📊 Сбор статистики за месяц...\n⏱️ Подождите до 90 секунд...")
    
    try:
        date_to = datetime.now()
        date_from = date_to - timedelta(days=30)
        date_from_str = date_from.strftime("%Y-%m-%d")
        date_to_str = date_to.strftime("%Y-%m-%d")
        
        balances = await api.get_balances_list(date_from_str, date_to_str, limit=500)
        
        total_income = 0
        if balances.get("status") and balances.get("data"):
            for item in balances["data"]:
                total_income += safe_float(item.get("amount", 0))
        
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
    
    msg = await message.answer("💰 Сбор финансовых данных...")
    
    try:
        date_to = datetime.now()
        date_from = date_to - timedelta(days=30)
        date_from_str = date_from.strftime("%Y-%m-%d")
        date_to_str = date_to.strftime("%Y-%m-%d")
        
        balances = await api.get_balances_list(date_from_str, date_to_str, limit=500)
        
        total_income = 0
        transactions_count = 0
        
        if balances.get("status") and balances.get("data"):
            for item in balances["data"]:
                total_income += safe_float(item.get("amount", 0))
                transactions_count += 1
        
        result = f"""💰 *ФИНАНСОВЫЙ ОТЧЕТ*

📅 Период: {date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}

📊 *Основные показатели:*
• Общая выручка: {total_income:,.0f} ₽
• Количество операций: {transactions_count}
• Средняя сумма: {total_income/transactions_count if transactions_count > 0 else 0:,.0f} ₽

📈 *Средние значения:*
• Средняя выручка в день: {total_income/30:,.0f} ₽

#финансы #отчет"""
        
        await msg.delete()
        await message.answer(result, parse_mode="Markdown", reply_markup=get_main_keyboard())
        
    except Exception as e:
        await msg.delete()
        await message.answer(f"❌ Ошибка: {str(e)}", reply_markup=get_main_keyboard())

# ========== ПРОДАЖИ ==========
@dp.message(F.text == "🍔 Продажи")
async def sales_report(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    
    msg = await message.answer("🍔 Загрузка данных о продажах...")
    
    try:
        date_to = datetime.now()
        date_from = date_to - timedelta(days=7)
        
        products = await api.get_products_expense(date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d"), limit=500)
        
        product_sales = defaultdict(int)
        total_revenue = 0
        
        if products.get("status") and products.get("data"):
            for prod in products["data"]:
                price = safe_float(prod.get("price_sale", 0))
                count = safe_int(prod.get("count", 0))
                name = prod.get("name", "")
                if name:
                    sale_sum = price * count
                    product_sales[name] += sale_sum
                    total_revenue += sale_sum
        
        top_products = sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:10]
        
        result = f"""🍔 *ТОП ПРОДАЖ*

📅 Период: {date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}

💰 *Общая выручка:* {total_revenue:,.0f} ₽

🏆 *Топ-10 товаров:*\n"""
        
        for i, (name, amount) in enumerate(top_products, 1):
            short_name = name[:35] + "..." if len(name) > 35 else name
            result += f"{i}. {short_name} — {amount:,.0f} ₽\n"
        
        if not top_products:
            result += "• Нет данных о продажах\n"
        
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
        shifts = await api.get_working_shifts(limit=20)
        
        result = f"""🔄 *ОТЧЕТ ПО СМЕНАМ*

📊 *Последние смены:*\n\n"""
        
        if shifts.get("status") and shifts.get("data"):
            for shift in shifts["data"][:10]:
                admin = shift.get("user_name") or "Неизвестно"
                date_start = shift.get("date_start", "—")
                if date_start and date_start != "—":
                    date_start = date_start[:16]
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
            if club.get('address'):
                result += f"   📍 {club.get('address')}\n"
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
    
    msg = await message.answer("🔄 Загрузка лога операций...")
    
    date_to = datetime.now()
    date_from = date_to - timedelta(days=7)
    r = await api.get_operations_log(date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d"))
    await msg.delete()
    
    if r.get("status") and r.get("data"):
        result = "📋 *ЛОГ ОПЕРАЦИЙ (последние 10)*\n\n"
        for op in r["data"][:10]:
            date = op.get("date_normal", "—")[:16] if op.get("date_normal") else "—"
            op_type = op.get("type", "—")
            op_sum = safe_float(op.get("sum", 0))
            op_name = op.get("name", "—")
            result += f"{'💰' if op_type == 'Пополнение' else '💸'} {date}\n"
            result += f"   📋 {op_type}\n"
            if op_name and op_name != "—":
                short_name = op_name[:35] + "..." if len(op_name) > 35 else op_name
                result += f"   📝 {short_name}\n"
            result += f"   💵 {op_sum:,.2f} ₽\n"
            result += "─" * 25 + "\n"
        await message.answer(result, parse_mode="Markdown", reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {r.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

# ========== ОБРАБОТЧИК НЕИЗВЕСТНЫХ ==========
@dp.message()
async def unknown(message: types.Message):
    if not message.text.startswith("/"):
        await message.answer(
            "❓ Используйте кнопки меню\n\n"
            "📊 *Доступные отчеты:*\n"
            "• Статистика за сегодня/вчера/неделю/месяц\n"
            "• Финансовый отчет\n"
            "• Продажи\n"
            "• Отчет по сменам\n"
            "• Лог операций",
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