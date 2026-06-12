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
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
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
    waiting_time_from = State()
    waiting_date_to = State()
    waiting_time_to = State()

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
                async with session.get(url, headers=self.headers, params=params, timeout=120) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        return {"status": False, "error": f"HTTP {resp.status}"}
        except Exception as e:
            return {"status": False, "error": str(e)}
    
    async def get_clubs(self) -> Dict:
        """Список клубов"""
        return await self._request("/clubs/list")
    
    async def get_balances_list(self, date_from: str, date_to: str, club_id: int = None, page: int = 1, limit: int = 2000) -> Dict:
        """Пополнения баланса"""
        params = {"date_from": date_from, "date_to": date_to, "page": page, "page_limit": limit}
        if club_id:
            params["club_id"] = club_id
        return await self._request("/balances/list", params=params)
    
    async def get_products_expense(self, date_from: str = None, date_to: str = None, club_id: int = None, page: int = 1, limit: int = 2000) -> Dict:
        """Продажи товаров"""
        params = {"page": page, "page_limit": limit}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        if club_id:
            params["club_id"] = club_id
        return await self._request("/products/expense", params=params)
    
    async def get_guests_sessions(self, date_from: str = None, date_to: str = None, club_id: int = None, page: int = 1, limit: int = 2000) -> Dict:
        """Сессии гостей"""
        params = {"page": page, "page_limit": limit}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        if club_id:
            params["club_id"] = club_id
        return await self._request("/guests/sessions", params=params)
    
    async def get_operations_log(self, date_from: str = None, date_to: str = None, club_id: int = None) -> Dict:
        """Лог операций"""
        params = {}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        if club_id:
            params["club_id"] = club_id
        return await self._request("/all_operations_log/list", params=params)

api = LangameAPI(API_KEY if API_KEY else "")

# ========== КЛАВИАТУРА ==========
def get_main_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="📊 Выбрать период")],
        [KeyboardButton(text="🍔 Топ товаров")],
        [KeyboardButton(text="🏢 Список клубов")],
        [KeyboardButton(text="🔌 Проверить API"), KeyboardButton(text="ℹ️ О боте")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# ========== ФОРМАТИРОВАНИЕ ==========
def format_datetime_ru(dt: datetime) -> str:
    months = {
        1: "января", 2: "февраля", 3: "марта", 4: "апреля",
        5: "мая", 6: "июня", 7: "июля", 8: "августа",
        9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"
    }
    weekdays = {
        0: "Понедельник", 1: "Вторник", 2: "Среда",
        3: "Четверг", 4: "Пятница", 5: "Суббота", 6: "Воскресенье"
    }
    weekday = weekdays.get(dt.weekday(), "")
    return f"{weekday}, {dt.day} {months.get(dt.month, '')} {dt.year}"

# ========== АНАЛИТИЧЕСКИЕ ФУНКЦИИ ==========
async def get_stats_for_period(date_from: datetime, date_to: datetime, club_id: int = None) -> Dict:
    """Получение статистики за период"""
    date_from_str = date_from.strftime("%Y-%m-%d")
    date_to_str = date_to.strftime("%Y-%m-%d")
    
    logger.info(f"Сбор статистики: клуб={club_id}, период={date_from_str} {date_from.strftime('%H:%M')} - {date_to_str} {date_to.strftime('%H:%M')}")
    
    # Получаем данные
    balances = await api.get_balances_list(date_from_str, date_to_str, club_id=club_id, limit=2000)
    products = await api.get_products_expense(date_from_str, date_to_str, club_id=club_id, limit=2000)
    sessions_data = await api.get_guests_sessions(date_from_str, date_to_str, club_id=club_id, limit=2000)
    operations = await api.get_operations_log(date_from_str, date_to_str, club_id=club_id)
    
    # Логируем для отладки
    logger.info(f"Balances status: {balances.get('status')}, data count: {len(balances.get('data', []))}")
    logger.info(f"Products status: {products.get('status')}, data count: {len(products.get('data', []))}")
    logger.info(f"Sessions status: {sessions_data.get('status')}, data count: {len(sessions_data.get('data', []))}")
    logger.info(f"Operations status: {operations.get('status')}, data count: {len(operations.get('data', []))}")
    
    # Сбор статистики
    total_income = 0
    sessions_count = 0
    unique_guests = set()
    product_sales = defaultdict(float)
    bar_revenue = 0
    product_details = []
    
    # 1. ИЗ BALANCES (пополнения) - выручка
    if balances.get("status") and balances.get("data"):
        for item in balances["data"]:
            amount = safe_float(item.get("amount", 0))
            total_income += amount
            guest_name = item.get("guest_name", "")
            if guest_name:
                unique_guests.add(guest_name)
        logger.info(f"Balances: найдено {len(balances['data'])} записей, выручка {total_income:,.0f} ₽")
    else:
        logger.warning(f"Balances error: {balances.get('error')}")
    
    # 2. ИЗ SESSIONS - количество сессий
    if sessions_data.get("status") and sessions_data.get("data"):
        sessions_count = len(sessions_data["data"])
        logger.info(f"Sessions: найдено {sessions_count} сессий")
    else:
        logger.warning(f"Sessions error: {sessions_data.get('error')}")
    
    # 3. ИЗ PRODUCTS - продажи товаров
    if products.get("status") and products.get("data"):
        for item in products["data"]:
            price = safe_float(item.get("price_sale", 0))
            count = safe_int(item.get("count", 0))
            name = item.get("name", "")
            sale_sum = price * count
            if sale_sum > 0:
                bar_revenue += sale_sum
                if name and len(name) > 2 and price > 0:
                    product_sales[name] += sale_sum
                    product_details.append({
                        "name": name,
                        "price": price,
                        "count": count,
                        "sum": sale_sum,
                        "date": item.get("date", "")
                    })
        logger.info(f"Products: найдено {len(products['data'])} записей, выручка бара {bar_revenue:,.0f} ₽")
    else:
        logger.warning(f"Products error: {products.get('error')}")
    
    # 4. Если нет данных из balances, пробуем получить из operations
    if total_income == 0 and operations.get("status") and operations.get("data"):
        for item in operations["data"]:
            if item.get("type") == "Пополнение":
                total_income += safe_float(item.get("sum", 0))
        logger.info(f"Operations: выручка из операций {total_income:,.0f} ₽")
    
    # Топ товаров
    top_products = sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:15]
    
    # Средний чек
    avg_check = 0
    if balances.get("data"):
        positive_items = [b for b in balances["data"] if safe_float(b.get("amount", 0)) > 0]
        if positive_items:
            total_sum = sum(safe_float(b.get("amount", 0)) for b in positive_items)
            avg_check = total_sum / len(positive_items)
    
    # Количество дней в периоде
    hours_diff = (date_to - date_from).total_seconds() / 3600
    days_count = max(hours_diff / 24, 0.1)
    
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
        "club_id": club_id,
        "raw_balances_count": len(balances.get("data", [])),
        "raw_products_count": len(products.get("data", [])),
        "raw_sessions_count": len(sessions_data.get("data", []))
    }

def format_stats_message(stats: Dict) -> str:
    """Форматирование статистики"""
    date_from = stats['period_from']
    date_to = stats['period_to']
    
    if date_from.date() == date_to.date():
        period_str = f"{date_from.strftime('%d.%m.%Y')} {date_from.strftime('%H:%M')} - {date_to.strftime('%H:%M')}"
    else:
        period_str = f"{date_from.strftime('%d.%m.%Y %H:%M')} - {date_to.strftime('%d.%m.%Y %H:%M')}"
    
    club_info = f" (клуб ID: {stats['club_id']})" if stats.get('club_id') else ""
    
    result = f"""📊 *СТАТИСТИКА ЗА ПЕРИОД*{club_info}

📅 Период: {period_str}

💰 *Финансы:*
• Выручка: {stats['total_income']:,.0f} ₽
• Средний чек: {stats['avg_check']:,.0f} ₽
• Выручка бара: {stats['bar_revenue']:,.0f} ₽

🎮 *Активность:*
• Сессии: {stats['sessions_count']}
• Уникальных гостей: {stats['unique_guests']}
• Средняя выручка в день: {stats['total_income']/stats['days_count'] if stats['days_count'] > 0 else 0:,.0f} ₽
• Среднее сессий в день: {stats['sessions_count']/stats['days_count'] if stats['days_count'] > 0 else 0:.1f}

🍔 *Топ товаров:*\n"""
    
    if stats['top_products']:
        for name, amount in stats['top_products'][:10]:
            short_name = name[:35] + "..." if len(name) > 35 else name
            result += f"• {short_name} — {amount:,.0f} ₽\n"
    else:
        result += "• Нет данных\n"
    
    # Добавляем отладочную информацию
    result += f"\n📊 *Данные:*\n"
    result += f"• Пополнений: {stats['raw_balances_count']}\n"
    result += f"• Продаж: {stats['raw_products_count']}\n"
    result += f"• Сессий в API: {stats['raw_sessions_count']}\n"
    
    result += f"\n#отчет #статистика"
    
    return result

def format_products_message(stats: Dict) -> str:
    """Форматирование списка товаров"""
    if not stats['product_details']:
        return "🍔 *Нет данных о продажах за указанный период*\n\n💡 Попробуйте:\n• Проверить ID клуба\n• Расширить период\n• Убедиться, что в выбранные даты были продажи"
    
    products_grouped = defaultdict(lambda: {"count": 0, "sum": 0, "price": 0})
    for p in stats['product_details']:
        products_grouped[p['name']]["count"] += p['count']
        products_grouped[p['name']]["sum"] += p['sum']
        products_grouped[p['name']]["price"] = p['price']
    
    sorted_products = sorted(products_grouped.items(), key=lambda x: x[1]["sum"], reverse=True)[:20]
    
    club_info = f" (клуб ID: {stats['club_id']})" if stats.get('club_id') else ""
    
    result = f"""🍔 *ТОП ТОВАРОВ ЗА ПЕРИОД*{club_info}

📅 {stats['period_from'].strftime('%d.%m.%Y %H:%M')} - {stats['period_to'].strftime('%d.%m.%Y %H:%M')}

💰 *Общая выручка бара:* {stats['bar_revenue']:,.0f} ₽

🏆 *Топ товаров:*\n\n"""
    
    for i, (name, data) in enumerate(sorted_products, 1):
        short_name = name[:30] + "..." if len(name) > 30 else name
        result += f"{i}. *{short_name}*\n"
        result += f"   📦 {data['count']} шт. × {data['price']:,.0f} ₽ = {data['sum']:,.0f} ₽\n\n"
    
    return result

# ========== ОБРАБОТЧИКИ ==========
@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "📊 *LANGAME АНАЛИТИКА*\n\n"
        "Бот для анализа финансовых показателей игрового клуба.\n\n"
        "📋 *Как использовать:*\n"
        "1. Нажмите «🏢 Список клубов» чтобы узнать ID клуба\n"
        "2. Нажмите «📊 Выбрать период» для анализа\n"
        "3. Введите ID клуба (или 0 для всех клубов)\n"
        "4. Введите дату и время начала и окончания\n\n"
        "📅 *Формат даты:* `ГГГГ-ММ-ДД ЧЧ:ММ`\n"
        "Пример: `2026-06-01 10:00`\n\n"
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
        "• Анализ за любой период с точным временем\n"
        "• Фильтрация по конкретному клубу\n"
        "• Выручка, средний чек\n"
        "• Количество сессий и уникальных гостей\n"
        "• Топ товаров с количеством и ценой\n\n"
        "📅 *Формат даты:* ГГГГ-ММ-ДД ЧЧ:ММ\n"
        "Пример: `2026-06-01 10:00`\n\n"
        "💡 *Если нет данных:*\n"
        "• Проверьте ID клуба\n"
        "• Убедитесь, что в выбранный период были операции\n"
        "• Расширьте период",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

@dp.message(F.text == "🔌 Проверить API")
async def test_api(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    msg = await message.answer("🔄 Проверка подключения...")
    
    clubs = await api.get_clubs()
    
    await msg.delete()
    
    result_text = "✅ *API ПРОВЕРКА*\n\n"
    result_text += f"🔑 API Key: {'✅ Настроен' if API_KEY else '❌'}\n"
    
    if clubs.get("status") and clubs.get("data"):
        result_text += f"🏢 Доступно клубов: {len(clubs['data'])}\n\n"
        for club in clubs["data"][:5]:
            result_text += f"• {club.get('name')} (ID: {club.get('id')})\n"
    else:
        result_text += f"❌ Ошибка получения клубов: {clubs.get('error')}"
    
    await message.answer(result_text, parse_mode="Markdown", reply_markup=get_main_keyboard())

@dp.message(F.text == "🏢 Список клубов")
async def clubs_list(message: types.Message):
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
            result += f"📌 *{club.get('name', '—')}*\n"
            result += f"   🆔 ID: `{club.get('id', '—')}`\n"
            if club.get('address'):
                result += f"   📍 {club.get('address')}\n"
            result += f"   {status}\n\n"
        result += "\n💡 *Для анализа введите ID клуба из списка*"
        await message.answer(result, parse_mode="Markdown", reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {r.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

# ========== ВЫБОР ПЕРИОДА ==========
@dp.message(F.text == "📊 Выбрать период")
async def select_club(message: types.Message, state: FSMContext):
    await message.answer(
        "🏢 Введите *ID клуба* для анализа\n\n"
        "• Нажмите «🏢 Список клубов» чтобы узнать ID\n"
        "• Введите `0` для анализа по всем клубам\n\n"
        "📌 *Пример:* `1`",
        parse_mode="Markdown"
    )
    await state.set_state(CustomPeriodState.waiting_club_id)

@dp.message(StateFilter(CustomPeriodState.waiting_club_id))
async def get_club_id(message: types.Message, state: FSMContext):
    try:
        club_id = int(message.text.strip())
        await state.update_data(club_id=club_id if club_id != 0 else None)
        
        await message.answer(
            "📅 Введите *дату и время начала* в формате:\n\n"
            "`ГГГГ-ММ-ДД ЧЧ:ММ`\n\n"
            "📌 *Примеры:*\n"
            "• `2026-06-01 10:00` — 1 июня 2026, 10:00\n"
            "• `2026-06-01 00:00` — начало суток\n\n"
            "ℹ️ Время можно указывать с точностью до минуты",
            parse_mode="Markdown"
        )
        await state.set_state(CustomPeriodState.waiting_date_from)
    except ValueError:
        await message.answer("❌ Введите число (ID клуба)!")

@dp.message(StateFilter(CustomPeriodState.waiting_date_from))
async def custom_period_date_from(message: types.Message, state: FSMContext):
    try:
        if " " in message.text:
            dt = datetime.strptime(message.text.strip(), "%Y-%m-%d %H:%M")
        else:
            dt = datetime.strptime(message.text.strip(), "%Y-%m-%d")
            dt = dt.replace(hour=0, minute=0)
        
        await state.update_data(date_from=dt)
        await message.answer(
            "📅 Введите *дату и время окончания* в формате:\n\n"
            "`ГГГГ-ММ-ДД ЧЧ:ММ`\n\n"
            "📌 *Пример:* `2026-06-30 23:59`",
            parse_mode="Markdown"
        )
        await state.set_state(CustomPeriodState.waiting_date_to)
    except ValueError:
        await message.answer("❌ Неверный формат! Используйте: `ГГГГ-ММ-ДД ЧЧ:ММ`\n\nПример: `2026-06-01 10:00`", parse_mode="Markdown")

@dp.message(StateFilter(CustomPeriodState.waiting_date_to))
async def custom_period_execute(message: types.Message, state: FSMContext):
    try:
        if " " in message.text:
            dt_to = datetime.strptime(message.text.strip(), "%Y-%m-%d %H:%M")
        else:
            dt_to = datetime.strptime(message.text.strip(), "%Y-%m-%d")
            dt_to = dt_to.replace(hour=23, minute=59)
        
        data = await state.get_data()
        dt_from = data.get("date_from")
        club_id = data.get("club_id")
        
        if dt_from > dt_to:
            await message.answer("❌ Дата начала не может быть позже даты окончания!")
            await state.clear()
            return
        
        period_str = f"{dt_from.strftime('%d.%m.%Y %H:%M')} - {dt_to.strftime('%d.%m.%Y %H:%M')}"
        club_str = f" для клуба ID: {club_id}" if club_id else " для всех клубов"
        
        msg = await message.answer(f"📊 Сбор статистики за период\n{period_str}{club_str}\n\n⏱️ Подождите, это может занять до 2 минут...")
        
        stats = await get_stats_for_period(dt_from, dt_to, club_id)
        
        await msg.delete()
        await message.answer(format_stats_message(stats), parse_mode="Markdown", reply_markup=get_main_keyboard())
        
        # Сохраняем статистику для команды "Топ товаров"
        await state.update_data(last_stats=stats)
        
    except ValueError:
        await message.answer("❌ Неверный формат! Используйте: `ГГГГ-ММ-ДД ЧЧ:ММ`\n\nПример: `2026-06-30 23:59`", parse_mode="Markdown")
    
    await state.clear()

# ========== ТОП ТОВАРОВ ==========
@dp.message(F.text == "🍔 Топ товаров")
async def top_products_select_club(message: types.Message, state: FSMContext):
    await message.answer(
        "🏢 Введите *ID клуба* для анализа товаров\n\n"
        "• Нажмите «🏢 Список клубов» чтобы узнать ID\n"
        "• Введите `0` для всех клубов\n\n"
        "📌 *Пример:* `1`",
        parse_mode="Markdown"
    )
    await state.set_state(CustomPeriodState.waiting_club_id)
    await state.update_data(mode="products")

# ========== ОБРАБОТЧИК НЕИЗВЕСТНЫХ ==========
@dp.message()
async def unknown(message: types.Message):
    if not message.text.startswith("/"):
        await message.answer(
            "❓ Используйте кнопки меню\n\n"
            "📊 *Доступные функции:*\n"
            "• 📊 Выбрать период — анализ за любой период\n"
            "• 🍔 Топ товаров — детальный отчет по товарам\n"
            "• 🏢 Список клубов — узнать ID клубов\n"
            "• 🔌 Проверить API — диагностика\n"
            "• ℹ️ О боте — информация",
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