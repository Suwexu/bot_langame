import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any
from collections import defaultdict

import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
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
class CustomPeriodState(StatesGroup):
    waiting_club_id = State()
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
    
    async def _request(self, endpoint: str, params: Dict = None) -> Dict:
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
    
    async def get_clubs(self) -> Dict:
        return await self._request("/clubs/list")
    
    async def get_balances_list(self, date_from: str, date_to: str, page: int = 1, limit: int = 2000) -> Dict:
        return await self._request("/balances/list", params={
            "date_from": date_from, "date_to": date_to, "page": page, "page_limit": limit
        })
    
    async def get_products_expense(self, date_from: str = None, date_to: str = None, page: int = 1, limit: int = 2000) -> Dict:
        params = {"page": page, "page_limit": limit}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        return await self._request("/products/expense", params=params)
    
    async def get_operations_log(self, date_from: str = None, date_to: str = None) -> Dict:
        params = {}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        return await self._request("/all_operations_log/list", params=params)

api = LangameAPI(API_KEY if API_KEY else "")

# ========== КЛАВИАТУРА ==========
def get_main_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="📊 За сегодня"), KeyboardButton(text="📈 За вчера")],
        [KeyboardButton(text="📅 За неделю"), KeyboardButton(text="📆 За месяц")],
        [KeyboardButton(text="🎯 Свой период")],
        [KeyboardButton(text="🍔 Топ товаров"), KeyboardButton(text="🏢 Клубы")],
        [KeyboardButton(text="🔌 Проверить API"), KeyboardButton(text="ℹ️ О боте")]
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
async def get_stats_for_period(date_from: datetime, date_to: datetime) -> Dict:
    """Получение статистики за период"""
    date_from_str = date_from.strftime("%Y-%m-%d")
    date_to_str = date_to.strftime("%Y-%m-%d")
    
    # Получаем данные
    balances = await api.get_balances_list(date_from_str, date_to_str, limit=2000)
    products = await api.get_products_expense(date_from_str, date_to_str, limit=2000)
    
    # Извлекаем данные
    balances_data = balances.get("data", []) if balances.get("status") else []
    products_data = products.get("data", []) if products.get("status") else []
    
    # Сбор статистики
    total_income = 0
    unique_guests = set()
    product_sales = defaultdict(float)
    bar_revenue = 0
    product_details = []
    
    # Из пополнений
    for item in balances_data:
        amount = safe_float(item.get("amount", 0))
        total_income += amount
        guest_name = item.get("guest_name", "")
        if guest_name:
            unique_guests.add(guest_name)
    
    # Из продаж
    for item in products_data:
        price = safe_float(item.get("price_sale", 0))
        count = safe_int(item.get("count", 0))
        name = item.get("name", "")
        sale_sum = price * count
        if sale_sum > 0:
            bar_revenue += sale_sum
            if name and len(name) > 2:
                product_sales[name] += sale_sum
                product_details.append({
                    "name": name,
                    "price": price,
                    "count": count,
                    "sum": sale_sum
                })
    
    # Средний чек
    avg_check = 0
    if balances_data:
        positive_items = [b for b in balances_data if safe_float(b.get("amount", 0)) > 0]
        if positive_items:
            total_sum = sum(safe_float(b.get("amount", 0)) for b in positive_items)
            avg_check = total_sum / len(positive_items)
    
    # Количество дней
    days_count = max((date_to - date_from).days + 1, 1)
    
    # Подсчет сессий (примерно)
    sessions_count = 0
    for item in balances_data:
        if "сессия" in item.get("guest_name", "").lower():
            sessions_count += 1
    
    # Топ товаров
    top_products = sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:10]
    
    return {
        "period_from": date_from,
        "period_to": date_to,
        "days_count": days_count,
        "total_income": total_income,
        "avg_check": avg_check,
        "bar_revenue": bar_revenue,
        "sessions_count": sessions_count,
        "unique_guests": len(unique_guests),
        "top_products": top_products,
        "product_details": product_details,
        "raw_balances": len(balances_data),
        "raw_products": len(products_data)
    }

def format_stats_message(stats: Dict, title: str) -> str:
    """Форматирование статистики"""
    date_from = stats['period_from']
    date_to = stats['period_to']
    
    if date_from.date() == date_to.date():
        period_str = date_from.strftime('%d.%m.%Y')
    else:
        period_str = f"{date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}"
    
    result = f"""📊 *{title}*

📅 Период: {period_str}

💰 *Финансы:*
• Выручка: {stats['total_income']:,.0f} ₽
• Средний чек: {stats['avg_check']:,.0f} ₽
• Выручка бара: {stats['bar_revenue']:,.0f} ₽

🎮 *Активность:*
• Сессии: {stats['sessions_count']}
• Уникальных гостей: {stats['unique_guests']}
• Средняя выручка в день: {stats['total_income']/stats['days_count'] if stats['days_count'] > 0 else 0:,.0f} ₽

🍔 *Топ товаров:*\n"""
    
    if stats['top_products']:
        for name, amount in stats['top_products'][:5]:
            short_name = name[:30] + "..." if len(name) > 30 else name
            result += f"• {short_name} — {amount:,.0f} ₽\n"
    else:
        result += "• Нет данных\n"
    
    result += f"\n#отчет"
    return result

def format_products_message(stats: Dict) -> str:
    if not stats['product_details']:
        return "🍔 *Нет данных о продажах за указанный период*"
    
    products_grouped = defaultdict(lambda: {"count": 0, "sum": 0})
    for p in stats['product_details']:
        products_grouped[p['name']]["count"] += p['count']
        products_grouped[p['name']]["sum"] += p['sum']
    
    sorted_products = sorted(products_grouped.items(), key=lambda x: x[1]["sum"], reverse=True)[:15]
    
    result = f"""🍔 *ТОП ТОВАРОВ ЗА ПЕРИОД*

📅 {stats['period_from'].strftime('%d.%m.%Y')} - {stats['period_to'].strftime('%d.%m.%Y')}

💰 *Общая выручка бара:* {stats['bar_revenue']:,.0f} ₽

🏆 *Топ товаров:*\n\n"""
    
    for i, (name, data) in enumerate(sorted_products, 1):
        short_name = name[:30] + "..." if len(name) > 30 else name
        result += f"{i}. *{short_name}*\n"
        result += f"   📦 {data['count']} шт. = {data['sum']:,.0f} ₽\n\n"
    
    return result

# ========== ОБРАБОТЧИКИ ==========
@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "📊 *LANGAME АНАЛИТИКА*\n\n"
        "Бот для анализа финансовых показателей игрового клуба.\n\n"
        "📋 *Доступные функции:*\n"
        "• 📊 За сегодня — статистика за текущий день\n"
        "• 📈 За вчера — статистика за предыдущий день\n"
        "• 📅 За неделю — статистика за 7 дней\n"
        "• 📆 За месяц — статистика за 30 дней\n"
        "• 🎯 Свой период — любой диапазон дат\n"
        "• 🍔 Топ товаров — детальный отчет по товарам\n\n"
        "Используйте кнопки ниже 👇",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

@dp.message(F.text == "ℹ️ О боте")
async def about(message: types.Message):
    await message.answer(
        "🤖 *LANGAME АНАЛИТИКА v4.0*\n\n"
        "Бот для аналитики игрового клуба\n\n"
        "📊 *Что умеет:*\n"
        "• Анализ за любой период\n"
        "• Выручка, средний чек\n"
        "• Топ товаров с количеством\n\n"
        "📅 *Формат даты:* ГГГГ-ММ-ДД\n"
        "Пример: `2026-06-01`",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

@dp.message(F.text == "🔌 Проверить API")
async def test_api(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    msg = await message.answer("🔄 Проверка...")
    clubs = await api.get_clubs()
    await msg.delete()
    
    if clubs.get("status"):
        await message.answer(f"✅ API РАБОТАЕТ!\n\n🏢 Доступно клубов: {len(clubs.get('data', []))}", reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ Ошибка: {clubs.get('error')}", reply_markup=get_main_keyboard())

@dp.message(F.text == "🏢 Клубы")
async def clubs_list(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    
    msg = await message.answer("🔄 Загрузка...")
    r = await api.get_clubs()
    await msg.delete()
    
    if r.get("status") and r.get("data"):
        result = "🏢 *СПИСОК КЛУБОВ*\n\n"
        for club in r["data"]:
            result += f"📌 {club.get('name', '—')} (ID: {club.get('id')})\n"
        await message.answer(result, parse_mode="Markdown", reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {r.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

# ========== СТАТИСТИКА ==========
@dp.message(F.text == "📊 За сегодня")
async def stats_today(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    
    msg = await message.answer("📊 Сбор статистики...")
    
    date_to = datetime.now()
    date_from = date_to.replace(hour=0, minute=0, second=0, microsecond=0)
    
    stats = await get_stats_for_period(date_from, date_to)
    
    await msg.delete()
    await message.answer(format_stats_message(stats, "СТАТИСТИКА ЗА СЕГОДНЯ"), parse_mode="Markdown", reply_markup=get_main_keyboard())

@dp.message(F.text == "📈 За вчера")
async def stats_yesterday(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    
    msg = await message.answer("📊 Сбор статистики...")
    
    date_to = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    date_from = date_to
    
    stats = await get_stats_for_period(date_from, date_to)
    
    await msg.delete()
    await message.answer(format_stats_message(stats, "СТАТИСТИКА ЗА ВЧЕРА"), parse_mode="Markdown", reply_markup=get_main_keyboard())

@dp.message(F.text == "📅 За неделю")
async def stats_week(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    
    msg = await message.answer("📊 Сбор статистики за неделю...")
    
    date_to = datetime.now()
    date_from = date_to - timedelta(days=6)
    
    stats = await get_stats_for_period(date_from, date_to)
    
    await msg.delete()
    await message.answer(format_stats_message(stats, "СТАТИСТИКА ЗА НЕДЕЛЮ"), parse_mode="Markdown", reply_markup=get_main_keyboard())

@dp.message(F.text == "📆 За месяц")
async def stats_month(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    
    msg = await message.answer("📊 Сбор статистики за месяц...")
    
    date_to = datetime.now()
    date_from = date_to - timedelta(days=29)
    
    stats = await get_stats_for_period(date_from, date_to)
    
    await msg.delete()
    await message.answer(format_stats_message(stats, "СТАТИСТИКА ЗА МЕСЯЦ"), parse_mode="Markdown", reply_markup=get_main_keyboard())

# ========== СВОЙ ПЕРИОД ==========
@dp.message(F.text == "🎯 Свой период")
async def custom_period_start(message: types.Message, state: FSMContext):
    await message.answer(
        "📅 Введите *дату начала* в формате:\n\n"
        "`ГГГГ-ММ-ДД`\n\n"
        "📌 *Пример:* `2026-06-01`",
        parse_mode="Markdown"
    )
    await state.set_state(CustomPeriodState.waiting_date_from)

@dp.message(StateFilter(CustomPeriodState.waiting_date_from))
async def custom_period_date_to(message: types.Message, state: FSMContext):
    try:
        date_from = datetime.strptime(message.text.strip(), "%Y-%m-%d")
        await state.update_data(date_from=date_from)
        await message.answer(
            "📅 Введите *дату окончания* в формате:\n\n"
            "`ГГГГ-ММ-ДД`\n\n"
            "📌 *Пример:* `2026-06-30`",
            parse_mode="Markdown"
        )
        await state.set_state(CustomPeriodState.waiting_date_to)
    except ValueError:
        await message.answer("❌ Неверный формат! Используйте: `ГГГГ-ММ-ДД`", parse_mode="Markdown")

@dp.message(StateFilter(CustomPeriodState.waiting_date_to))
async def custom_period_execute(message: types.Message, state: FSMContext):
    try:
        date_to = datetime.strptime(message.text.strip(), "%Y-%m-%d")
        data = await state.get_data()
        date_from = data.get("date_from")
        
        if date_from > date_to:
            await message.answer("❌ Дата начала не может быть позже даты окончания!")
            await state.clear()
            return
        
        # Добавляем время к датам
        date_from = date_from.replace(hour=0, minute=0)
        date_to = date_to.replace(hour=23, minute=59)
        
        msg = await message.answer(f"📊 Сбор статистики за период {date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}...\n⏱️ Подождите...")
        
        stats = await get_stats_for_period(date_from, date_to)
        
        await msg.delete()
        await message.answer(format_stats_message(stats, "СТАТИСТИКА ЗА ПЕРИОД"), parse_mode="Markdown", reply_markup=get_main_keyboard())
        
        await state.update_data(last_stats=stats)
        
    except ValueError:
        await message.answer("❌ Неверный формат! Используйте: `ГГГГ-ММ-ДД`", parse_mode="Markdown")
    
    await state.clear()

# ========== ТОП ТОВАРОВ ==========
@dp.message(F.text == "🍔 Топ товаров")
async def top_products(message: types.Message, state: FSMContext):
    await message.answer(
        "📅 Введите *дату начала* периода в формате:\n\n"
        "`ГГГГ-ММ-ДД`\n\n"
        "📌 *Пример:* `2026-06-01`",
        parse_mode="Markdown"
    )
    await state.set_state(CustomPeriodState.waiting_date_from)
    await state.update_data(mode="products")

# Обработчик для товаров (переопределяем)
@dp.message(StateFilter(CustomPeriodState.waiting_date_from))
async def products_date_from(message: types.Message, state: FSMContext):
    try:
        date_from = datetime.strptime(message.text.strip(), "%Y-%m-%d")
        await state.update_data(date_from=date_from)
        await message.answer(
            "📅 Введите *дату окончания* периода:\n\n"
            "`ГГГГ-ММ-ДД`\n\n"
            "📌 *Пример:* `2026-06-30`",
            parse_mode="Markdown"
        )
        await state.set_state(CustomPeriodState.waiting_date_to)
    except ValueError:
        await message.answer("❌ Неверный формат! Используйте: `ГГГГ-ММ-ДД`", parse_mode="Markdown")

@dp.message(StateFilter(CustomPeriodState.waiting_date_to))
async def products_execute(message: types.Message, state: FSMContext):
    data = await state.get_data()
    mode = data.get("mode", "stats")
    
    try:
        date_to = datetime.strptime(message.text.strip(), "%Y-%m-%d")
        date_from = data.get("date_from")
        
        if date_from > date_to:
            await message.answer("❌ Дата начала не может быть позже даты окончания!")
            await state.clear()
            return
        
        date_from = date_from.replace(hour=0, minute=0)
        date_to = date_to.replace(hour=23, minute=59)
        
        msg = await message.answer(f"🍔 Сбор данных о товарах за период {date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}...")
        
        stats = await get_stats_for_period(date_from, date_to)
        
        await msg.delete()
        
        if mode == "products":
            await message.answer(format_products_message(stats), parse_mode="Markdown", reply_markup=get_main_keyboard())
        else:
            await message.answer(format_stats_message(stats, "СТАТИСТИКА ЗА ПЕРИОД"), parse_mode="Markdown", reply_markup=get_main_keyboard())
        
    except ValueError:
        await message.answer("❌ Неверный формат!", parse_mode="Markdown")
    
    await state.clear()

# ========== ОСТАЛЬНЫЕ ОБРАБОТЧИКИ ==========
@dp.message()
async def unknown(message: types.Message):
    if not message.text.startswith("/"):
        await message.answer(
            "❓ Используйте кнопки меню\n\n"
            "📊 *Доступные отчеты:*\n"
            "• За сегодня/вчера/неделю/месяц\n"
            "• Свой период\n"
            "• Топ товаров",
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