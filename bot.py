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
class CustomPeriodState(StatesGroup):
    waiting_date_from = State()
    waiting_date_to = State()

# ========== ИНИЦИАЛИЗАЦИЯ ==========
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
    
    async def get_balances_list(self, date_from: str, date_to: str, page: int = 1, limit: int = 500) -> Dict:
        return await self._request("/balances/list", params={
            "date_from": date_from, "date_to": date_to, "page": page, "page_limit": limit
        })
    
    async def get_transactions(self, date_from: str = None, date_to: str = None, page: int = 1, limit: int = 500) -> Dict:
        params = {"page": page, "page_limit": limit}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        return await self._request("/transactions/list", params=params)
    
    async def get_operations_log(self, date_from: str = None, date_to: str = None) -> Dict:
        params = {}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        return await self._request("/all_operations_log/list", params=params)
    
    async def get_working_shifts(self, page: int = 1, limit: int = 50) -> Dict:
        return await self._request("/working_shifts/list", params={"page": page, "page_limit": limit})
    
    async def get_products_expense(self, date_from: str = None, date_to: str = None, page: int = 1, limit: int = 500) -> Dict:
        params = {"page": page, "page_limit": limit}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        return await self._request("/products/expense", params=params)
    
    async def get_clubs(self) -> Dict:
        return await self._request("/clubs/list")
    
    async def get_guests_sessions(self, date_from: str = None, date_to: str = None, page: int = 1, limit: int = 500) -> Dict:
        """Сессии гостей"""
        params = {"page": page, "page_limit": limit}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        return await self._request("/guests/sessions", params=params)

api = LangameAPI(API_KEY if API_KEY else "")

# ========== КЛАВИАТУРЫ ==========
def get_main_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="📊 Статистика за сегодня")],
        [KeyboardButton(text="📈 Статистика за вчера")],
        [KeyboardButton(text="📅 Статистика за неделю")],
        [KeyboardButton(text="📆 Статистика за месяц")],
        [KeyboardButton(text="🎯 Свой период")],
        [KeyboardButton(text="💰 Финансы"), KeyboardButton(text="🍔 Продажи")],
        [KeyboardButton(text="🔄 Смены"), KeyboardButton(text="🏢 Клубы")],
        [KeyboardButton(text="📋 Лог операций"), KeyboardButton(text="🔌 Проверить API")],
        [KeyboardButton(text="ℹ️ О боте")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_period_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Сегодня", callback_data="period_today")],
        [InlineKeyboardButton(text="📈 Вчера", callback_data="period_yesterday")],
        [InlineKeyboardButton(text="📅 Неделя", callback_data="period_week")],
        [InlineKeyboardButton(text="📆 Месяц", callback_data="period_month")],
        [InlineKeyboardButton(text="🎯 Свой период", callback_data="period_custom")]
    ])

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
async def get_stats_for_period(date_from: datetime, date_to: datetime, period_name: str = "") -> Dict:
    """Получение статистики за период"""
    date_from_str = date_from.strftime("%Y-%m-%d")
    date_to_str = date_to.strftime("%Y-%m-%d")
    
    logger.info(f"Сбор статистики за период: {date_from_str} - {date_to_str}")
    
    # Получаем данные из разных эндпоинтов
    balances = await api.get_balances_list(date_from_str, date_to_str, limit=1000)
    operations = await api.get_operations_log(date_from_str, date_to_str)
    products = await api.get_products_expense(date_from_str, date_to_str, limit=1000)
    sessions_data = await api.get_guests_sessions(date_from_str, date_to_str, limit=1000)
    transactions = await api.get_transactions(date_from_str, date_to_str, limit=1000)
    
    # Сбор статистики
    total_income = 0
    sessions_count = 0
    unique_guests = set()
    product_sales = defaultdict(float)
    bar_revenue = 0
    refunds_total = 0
    
    # 1. ИЗ BALANCES (пополнения) - основной источник выручки
    if balances.get("status") and balances.get("data"):
        for item in balances["data"]:
            amount = safe_float(item.get("amount", 0))
            total_income += amount
            guest_name = item.get("guest_name", "")
            if guest_name:
                unique_guests.add(guest_name)
        logger.info(f"Balances: найдено {len(balances['data'])} записей, выручка {total_income}")
    
    # 2. ИЗ SESSIONS (сессии гостей) - прямой подсчет сессий
    if sessions_data.get("status") and sessions_data.get("data"):
        sessions_count = len(sessions_data["data"])
        logger.info(f"Sessions: найдено {sessions_count} сессий")
    
    # 3. ИЗ OPERATIONS (лог операций) - дополнительная информация
    if operations.get("status") and operations.get("data"):
        for item in operations["data"]:
            op_sum = safe_float(item.get("sum", 0))
            op_type = item.get("type", "")
            # Возвраты
            if "возврат" in op_type.lower() or "refund" in op_type.lower():
                refunds_total += abs(op_sum)
        logger.info(f"Operations: найдено {len(operations['data'])} записей")
    
    # 4. ИЗ PRODUCTS (продажи товаров) - выручка бара и топ товаров
    if products.get("status") and products.get("data"):
        for item in products["data"]:
            price = safe_float(item.get("price_sale", 0))
            count = safe_int(item.get("count", 0))
            name = item.get("name", "")
            sale_sum = price * count
            bar_revenue += sale_sum
            if name and len(name) > 2:
                product_sales[name] += sale_sum
        logger.info(f"Products: найдено {len(products['data'])} записей, выручка бара {bar_revenue}")
    
    # 5. Средний чек из транзакций
    avg_check = 0
    if transactions.get("status") and transactions.get("data"):
        positive_tx = [t for t in transactions["data"] if safe_float(t.get("balance", 0)) > 0]
        if positive_tx:
            total_sum = sum(safe_float(t.get("balance", 0)) for t in positive_tx)
            avg_check = total_sum / len(positive_tx)
    
    # Если нет данных о сессиях из API, пробуем оценить по операциям
    if sessions_count == 0 and operations.get("data"):
        for item in operations["data"]:
            op_name = item.get("name", "").lower()
            if any(word in op_name for word in ["сессия", "session", "игровая", "запуск"]):
                sessions_count += 1
        logger.info(f"Сессии определены через операции: {sessions_count}")
    
    # Топ товаров
    product_sales = {k: v for k, v in product_sales.items() if k and len(k) > 2 and v > 0}
    top_products = sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:5]
    
    # Количество дней в периоде
    days_count = (date_to - date_from).days + 1
    
    return {
        "period": f"{date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}",
        "days_count": days_count,
        "total_income": total_income,
        "avg_check": avg_check,
        "bar_revenue": bar_revenue,
        "sessions_count": sessions_count,
        "unique_guests": len(unique_guests),
        "top_products": top_products,
        "refunds_total": refunds_total,
        "date_from": date_from,
        "date_to": date_to
    }

def format_stats_message(stats: Dict, title: str) -> str:
    """Форматирование статистики"""
    result = f"""📊 *{title}*

📅 Период: {stats['period']}

💰 *Финансы:*
• Выручка: {stats['total_income']:,.0f} ₽
• Средний чек: {stats['avg_check']:,.0f} ₽
• Выручка бара: {stats['bar_revenue']:,.0f} ₽
• Возвраты: {stats['refunds_total']:,.0f} ₽

🎮 *Активность:*
• Сессии: {stats['sessions_count']}
• Уникальных гостей: {stats['unique_guests']}
• Средняя выручка в день: {stats['total_income']/stats['days_count']:,.0f} ₽
• Среднее сессий в день: {stats['sessions_count']/stats['days_count']:.1f}

🍔 *Топ товаров:*\n"""
    
    if stats['top_products']:
        for name, amount in stats['top_products'][:5]:
            short_name = name[:30] + "..." if len(name) > 30 else name
            result += f"• {short_name} — {amount:,.0f} ₽\n"
    else:
        result += "• Нет данных\n"
    
    result += f"\n#отчет #{title.lower().replace(' ', '_')}"
    
    return result

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
        "• 🎯 Свой период (любые даты)\n"
        "• 💰 Финансовый отчет\n"
        "• 🍔 Продажи\n"
        "• 🔄 Отчет по сменам\n\n"
        "Используйте кнопки ниже 👇",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

@dp.message(F.text == "ℹ️ О боте")
async def about(message: types.Message):
    await message.answer(
        "🤖 *LANGAME АНАЛИТИКА v3.0*\n\n"
        "Бот для аналитики игрового клуба\n\n"
        "📊 *Источники данных:*\n"
        "• Пополнения баланса (выручка)\n"
        "• Сессии гостей\n"
        "• Продажи товаров\n"
        "• Кассовые смены\n\n"
        "📅 *Периоды:*\n"
        "• День, неделя, месяц\n"
        "• Любой произвольный период\n\n"
        "🆘 При проблемах обратитесь к администратору",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

@dp.message(F.text == "🔌 Проверить API")
async def test_api(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    msg = await message.answer("🔄 Проверка подключения...")
    
    # Проверяем несколько эндпоинтов
    clubs = await api.get_clubs()
    balances = await api.get_balances_list("2025-01-01", "2025-01-02")
    
    await msg.delete()
    
    result_text = "✅ *API ПРОВЕРКА*\n\n"
    result_text += f"🏢 Клубы: {'✅' if clubs.get('status') else '❌'}\n"
    result_text += f"💰 Балансы: {'✅' if balances.get('status') else '❌'}\n"
    result_text += f"🔑 API Key: {'✅ Настроен' if API_KEY else '❌'}\n\n"
    
    if clubs.get("data"):
        result_text += f"📊 Доступно клубов: {len(clubs['data'])}\n"
    
    await message.answer(result_text, parse_mode="Markdown", reply_markup=get_main_keyboard())

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
        
        stats = await get_stats_for_period(date_from, date_to, "сегодня")
        
        await msg.delete()
        await message.answer(format_stats_message(stats, "СТАТИСТИКА ЗА СЕГОДНЯ"), parse_mode="Markdown", reply_markup=get_main_keyboard())
        
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
        
        stats = await get_stats_for_period(date_from, date_to, "вчера")
        
        await msg.delete()
        await message.answer(format_stats_message(stats, "СТАТИСТИКА ЗА ВЧЕРА"), parse_mode="Markdown", reply_markup=get_main_keyboard())
        
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
        date_from = date_to - timedelta(days=6)
        
        stats = await get_stats_for_period(date_from, date_to, "неделя")
        
        await msg.delete()
        await message.answer(format_stats_message(stats, "СТАТИСТИКА ЗА НЕДЕЛЮ"), parse_mode="Markdown", reply_markup=get_main_keyboard())
        
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
        date_from = date_to - timedelta(days=29)
        
        stats = await get_stats_for_period(date_from, date_to, "месяц")
        
        await msg.delete()
        await message.answer(format_stats_message(stats, "СТАТИСТИКА ЗА МЕСЯЦ"), parse_mode="Markdown", reply_markup=get_main_keyboard())
        
    except Exception as e:
        await msg.delete()
        await message.answer(f"❌ Ошибка: {str(e)}", reply_markup=get_main_keyboard())

# ========== СВОЙ ПЕРИОД ==========
@dp.message(F.text == "🎯 Свой период")
async def custom_period_start(message: types.Message, state: FSMContext):
    await message.answer(
        "📅 Введите начальную дату в формате **ГГГГ-ММ-ДД**\n\n"
        "Пример: `2026-06-01`",
        parse_mode="Markdown"
    )
    await state.set_state(CustomPeriodState.waiting_date_from)

@dp.message(StateFilter(CustomPeriodState.waiting_date_from))
async def custom_period_date_from(message: types.Message, state: FSMContext):
    date_str = message.text.strip()
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        await state.update_data(date_from=date_str)
        await message.answer("📅 Введите конечную дату в формате **ГГГГ-ММ-ДД**\n\nПример: `2026-06-30`", parse_mode="Markdown")
        await state.set_state(CustomPeriodState.waiting_date_to)
    except ValueError:
        await message.answer("❌ Неверный формат даты! Используйте ГГГГ-ММ-ДД")

@dp.message(StateFilter(CustomPeriodState.waiting_date_to))
async def custom_period_execute(message: types.Message, state: FSMContext):
    data = await state.get_data()
    date_from_str = data.get("date_from")
    date_to_str = message.text.strip()
    
    try:
        date_from = datetime.strptime(date_from_str, "%Y-%m-%d")
        date_to = datetime.strptime(date_to_str, "%Y-%m-%d")
        
        if date_from > date_to:
            await message.answer("❌ Дата начала не может быть позже даты окончания!")
            await state.clear()
            return
        
        msg = await message.answer(f"📊 Сбор статистики за период {date_from_str} - {date_to_str}...\n⏱️ Подождите...")
        
        stats = await get_stats_for_period(date_from, date_to, "свой период")
        
        await msg.delete()
        await message.answer(format_stats_message(stats, f"СТАТИСТИКА ЗА ПЕРИОД"), parse_mode="Markdown", reply_markup=get_main_keyboard())
        
    except ValueError:
        await message.answer("❌ Неверный формат даты! Используйте ГГГГ-ММ-ДД")
    
    await state.clear()

# ========== ФИНАНСОВЫЙ ОТЧЕТ ==========
@dp.message(F.text == "💰 Финансы")
async def finance_report(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    
    msg = await message.answer("💰 Сбор финансовых данных за 30 дней...")
    
    try:
        date_to = datetime.now()
        date_from = date_to - timedelta(days=29)
        
        balances = await api.get_balances_list(date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d"), limit=1000)
        
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
    
    msg = await message.answer("🍔 Загрузка данных о продажах за 7 дней...")
    
    try:
        date_to = datetime.now()
        date_from = date_to - timedelta(days=6)
        
        products = await api.get_products_expense(date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d"), limit=1000)
        
        product_sales = defaultdict(float)
        total_revenue = 0
        
        if products.get("status") and products.get("data"):
            for prod in products["data"]:
                price = safe_float(prod.get("price_sale", 0))
                count = safe_int(prod.get("count", 0))
                name = prod.get("name", "")
                if name and len(name) > 2:
                    sale_sum = price * count
                    product_sales[name] += sale_sum
                    total_revenue += sale_sum
        
        top_products = sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:15]
        
        result = f"""🍔 *ТОП ПРОДАЖ*

📅 Период: {date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}

💰 *Общая выручка:* {total_revenue:,.0f} ₽

🏆 *Топ-15 товаров:*\n"""
        
        if top_products:
            for i, (name, amount) in enumerate(top_products, 1):
                short_name = name[:35] + "..." if len(name) > 35 else name
                result += f"{i}. {short_name} — {amount:,.0f} ₽\n"
        else:
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
        shifts = await api.get_working_shifts(limit=30)
        
        result = f"""🔄 *ОТЧЕТ ПО СМЕНАМ*

📊 *Последние смены:*\n\n"""
        
        if shifts.get("status") and shifts.get("data"):
            for shift in shifts["data"][:15]:
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
    
    msg = await message.answer("🔄 Загрузка лога операций за 7 дней...")
    
    date_to = datetime.now()
    date_from = date_to - timedelta(days=6)
    r = await api.get_operations_log(date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d"))
    await msg.delete()
    
    if r.get("status") and r.get("data"):
        result = "📋 *ЛОГ ОПЕРАЦИЙ (последние 15)*\n\n"
        for op in r["data"][:15]:
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
            "• Свой период (любые даты)\n"
            "• Финансовый отчет\n"
            "• Продажи\n"
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