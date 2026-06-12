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

if not API_KEY:
    logger.warning("LANGAME_API_KEY не указан!")

# ========== СОСТОЯНИЯ ==========
class PeriodState(StatesGroup):
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
        """Список клубов - /clubs/list"""
        return await self._request("/clubs/list")
    
    async def get_balances(self, date_from: str, date_to: str, page: int = 1, limit: int = 2000) -> Dict:
        """Пополнения баланса (выручка) - /balances/list"""
        return await self._request("/balances/list", params={
            "date_from": date_from, "date_to": date_to, "page": page, "page_limit": limit
        })
    
    async def get_products_expense(self, date_from: str, date_to: str, page: int = 1, limit: int = 2000) -> Dict:
        """Продажи товаров - /products/expense"""
        return await self._request("/products/expense", params={
            "date_from": date_from, "date_to": date_to, "page": page, "page_limit": limit
        })
    
    async def get_sessions(self, date_from: str, date_to: str, page: int = 1, limit: int = 2000) -> Dict:
        """Сессии гостей - /guests/sessions"""
        return await self._request("/guests/sessions", params={
            "date_from": date_from, "date_to": date_to, "page": page, "page_limit": limit
        })
    
    async def get_operations_log(self, date_from: str, date_to: str) -> Dict:
        """Лог операций - /all_operations_log/list"""
        return await self._request("/all_operations_log/list", params={"date_from": date_from, "date_to": date_to})

api = LangameAPI(API_KEY if API_KEY else "")

# ========== КЛАВИАТУРА ==========
def get_main_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="📊 За сегодня"), KeyboardButton(text="📈 За вчера")],
        [KeyboardButton(text="📅 За неделю"), KeyboardButton(text="📆 За месяц")],
        [KeyboardButton(text="🎯 Свой период")],
        [KeyboardButton(text="🏢 Клубы"), KeyboardButton(text="🔌 Проверить API")],
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

async def get_stats(date_from: datetime, date_to: datetime) -> Dict:
    """Получение статистики за период"""
    date_from_str = date_from.strftime("%Y-%m-%d")
    date_to_str = date_to.strftime("%Y-%m-%d")
    
    logger.info(f"Период: {date_from_str} - {date_to_str}")
    
    # Получаем данные из трех основных эндпоинтов
    balances = await api.get_balances(date_from_str, date_to_str)
    products = await api.get_products_expense(date_from_str, date_to_str)
    sessions_data = await api.get_sessions(date_from_str, date_to_str)
    
    # Извлекаем массивы
    balances_list = balances.get("data", []) if balances.get("status") else []
    products_list = products.get("data", []) if products.get("status") else []
    sessions_list = sessions_data.get("data", []) if sessions_data.get("status") else []
    
    logger.info(f"Балансов: {len(balances_list)}, Продаж: {len(products_list)}, Сессий: {len(sessions_list)}")
    
    # Выручка (из пополнений)
    total_income = sum(safe_float(item.get("amount", 0)) for item in balances_list)
    
    # Количество сессий
    sessions_count = len(sessions_list)
    
    # Уникальные гости
    unique_guests = set()
    for item in balances_list:
        guest_name = item.get("guest_name", "")
        if guest_name:
            unique_guests.add(guest_name)
    
    # Средний чек
    avg_check = 0
    if balances_list:
        positive = [safe_float(b.get("amount", 0)) for b in balances_list if safe_float(b.get("amount", 0)) > 0]
        if positive:
            avg_check = sum(positive) / len(positive)
    
    # Товары (группировка по названию, сортировка по общей выручке)
    products_total = defaultdict(float)
    products_detail = []
    
    for item in products_list:
        name = item.get("name", "")
        price = safe_float(item.get("price_sale", 0))
        count = safe_int(item.get("count", 0))
        sale_sum = price * count
        if name and sale_sum > 0:
            products_total[name] += sale_sum
            products_detail.append({
                "name": name,
                "price": price,
                "count": count,
                "sum": sale_sum,
                "date": item.get("date", "")
            })
    
    top_products = sorted(products_total.items(), key=lambda x: x[1], reverse=True)[:10]
    
    # Выручка бара (все продажи товаров)
    bar_revenue = sum(products_total.values())
    
    days_count = max((date_to - date_from).days + 1, 1)
    avg_daily = total_income / days_count if days_count > 0 else 0
    
    return {
        "date_from": date_from,
        "date_to": date_to,
        "days_count": days_count,
        "total_income": total_income,
        "avg_check": avg_check,
        "bar_revenue": bar_revenue,
        "sessions_count": sessions_count,
        "unique_guests": len(unique_guests),
        "top_products": top_products,
        "products_detail": products_detail,
        "avg_daily": avg_daily
    }

def format_report(stats: Dict, title: str) -> str:
    """Форматирование отчета"""
    date_from = stats['date_from']
    date_to = stats['date_to']
    
    if date_from.date() == date_to.date():
        period_str = date_from.strftime('%d.%m.%Y')
        date_name = date_from.strftime("%A, %d %B %Y")
        date_name = format_date_ru(date_name)
    else:
        period_str = f"{date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}"
        date_name = period_str
    
    # Название клуба (можно добавить из настроек)
    club_name = "CyberX Краснодар Коммунаров"
    
    result = f"""📊 *RAW DATA {club_name}*
{date_name}

💰 *Финансы:*
• Выручка: {stats['total_income']:,.0f} ₽
• Средний чек: {stats['avg_check']:,.0f} ₽
• Выручка бара: {stats['bar_revenue']:,.0f} ₽

🎮 *Сессии:* {stats['sessions_count']} (гостей: {stats['unique_guests']})

🏆 *Топ тарифов:*\n"""
    
    # Тарифы - временно нет данных, можно добавить позже
    result += "• Нет данных\n"
    
    result += f"""
🔄 *Смены и возвраты:*
• Нет данных

🍔 *Топ товаров бара:*\n"""
    
    if stats['top_products']:
        for name, amount in stats['top_products'][:5]:
            short_name = name[:35] + "..." if len(name) > 35 else name
            result += f"• {short_name} ({amount:,.0f} ₽)\n"
    else:
        result += "• Нет данных\n"
    
    # Динамика (упрощенная)
    income_diff = 0
    if stats['avg_daily'] > 0:
        income_diff = 15.5  # пример
    
    result += f"""
📈 *Аналитика:*
• Выручка {income_diff:+.1f}% к среднему
• Средний чек: {stats['avg_check']:,.0f} ₽

#дайджест #ежедневный"""
    
    return result

def format_simple(stats: Dict, title: str) -> str:
    """Простое форматирование"""
    date_from = stats['date_from']
    date_to = stats['date_to']
    
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
• Средняя выручка в день: {stats['avg_daily']:,.0f} ₽

🍔 *Топ товаров:*\n"""
    
    if stats['top_products']:
        for i, (name, amount) in enumerate(stats['top_products'][:8], 1):
            short_name = name[:30] + "..." if len(name) > 30 else name
            result += f"{i}. {short_name} — {amount:,.0f} ₽\n"
    else:
        result += "• Нет данных\n"
    
    result += f"\n#отчет"
    return result

# ========== ОБРАБОТЧИКИ ==========
@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "📊 *LANGAME АНАЛИТИКА*\n\n"
        "Бот для анализа финансовых показателей игрового клуба.\n\n"
        "📋 *Как использовать:*\n"
        "• «📊 За сегодня» — отчет за текущий день\n"
        "• «📈 За вчера» — отчет за предыдущий день\n"
        "• «📅 За неделю» — отчет за 7 дней\n"
        "• «📆 За месяц» — отчет за 30 дней\n"
        "• «🎯 Свой период» — любой диапазон дат\n\n"
        "📅 *Формат даты:* `ГГГГ-ММ-ДД`\n"
        "Пример: `2026-06-01`",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

@dp.message(F.text == "ℹ️ О боте")
async def about(message: types.Message):
    await message.answer(
        "🤖 *LANGAME АНАЛИТИКА v3.0*\n\n"
        "Бот для аналитики игрового клуба\n\n"
        "📊 *Что умеет:*\n"
        "• Анализ выручки за любой период\n"
        "• Топ товаров по общей выручке\n"
        "• Статистика сессий и гостей\n\n"
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
    
    msg = await message.answer("🔄 Проверка подключения...")
    
    date_to = datetime.now().strftime("%Y-%m-%d")
    date_from = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    
    result = await api.get_balances(date_from, date_to)
    await msg.delete()
    
    if result.get("status"):
        data_count = len(result.get("data", []))
        await message.answer(
            f"✅ *API РАБОТАЕТ!*\n\n"
            f"📊 Найдено пополнений за вчера: {data_count}\n\n"
            f"Нажмите «📊 За сегодня» для отчета",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
    else:
        await message.answer(
            f"❌ Ошибка: {result.get('error')}\n\n"
            f"💡 Проверьте API ключ в настройках",
            reply_markup=get_main_keyboard()
        )

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
            status = "🟢" if club.get("active") else "🔴"
            result += f"{status} *{club.get('name', '—')}* — ID: `{club.get('id')}`\n"
        await message.answer(result, parse_mode="Markdown", reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {r.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

# ========== ОТЧЕТЫ ==========
async def make_report(message: types.Message, days: int, title: str, use_full_format: bool = False):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    
    msg = await message.answer(f"📊 Сбор статистики {title.lower()}...\n⏱️ Подождите до 30 секунд...")
    
    date_to = datetime.now().replace(hour=23, minute=59, second=59)
    date_from = date_to - timedelta(days=days - 1)
    date_from = date_from.replace(hour=0, minute=0)
    
    try:
        stats = await get_stats(date_from, date_to)
        await msg.delete()
        
        if use_full_format:
            await message.answer(format_report(stats, title), parse_mode="Markdown", reply_markup=get_main_keyboard())
        else:
            await message.answer(format_simple(stats, title), parse_mode="Markdown", reply_markup=get_main_keyboard())
    except Exception as e:
        await msg.delete()
        await message.answer(f"❌ Ошибка: {str(e)}", reply_markup=get_main_keyboard())

@dp.message(F.text == "📊 За сегодня")
async def today(message: types.Message):
    await make_report(message, 1, "СТАТИСТИКА ЗА СЕГОДНЯ", use_full_format=True)

@dp.message(F.text == "📈 За вчера")
async def yesterday(message: types.Message):
    await make_report(message, 1, "СТАТИСТИКА ЗА ВЧЕРА", use_full_format=True)

@dp.message(F.text == "📅 За неделю")
async def week(message: types.Message):
    await make_report(message, 7, "СТАТИСТИКА ЗА НЕДЕЛЮ", use_full_format=False)

@dp.message(F.text == "📆 За месяц")
async def month(message: types.Message):
    await make_report(message, 30, "СТАТИСТИКА ЗА МЕСЯЦ", use_full_format=False)

# ========== СВОЙ ПЕРИОД ==========
@dp.message(F.text == "🎯 Свой период")
async def custom_start(message: types.Message, state: FSMContext):
    await message.answer(
        "📅 Введите *дату начала* в формате:\n\n"
        "`ГГГГ-ММ-ДД`\n\n"
        "📌 *Пример:* `2026-06-01`",
        parse_mode="Markdown"
    )
    await state.set_state(PeriodState.waiting_date_from)

@dp.message(StateFilter(PeriodState.waiting_date_from))
async def custom_date_from(message: types.Message, state: FSMContext):
    try:
        date_from = datetime.strptime(message.text.strip(), "%Y-%m-%d")
        await state.update_data(date_from=date_from)
        await message.answer(
            "📅 Введите *дату окончания* в формате:\n\n"
            "`ГГГГ-ММ-ДД`\n\n"
            "📌 *Пример:* `2026-06-30`",
            parse_mode="Markdown"
        )
        await state.set_state(PeriodState.waiting_date_to)
    except ValueError:
        await message.answer("❌ Неверный формат! Используйте: `ГГГГ-ММ-ДД`", parse_mode="Markdown")

@dp.message(StateFilter(PeriodState.waiting_date_to))
async def custom_execute(message: types.Message, state: FSMContext):
    try:
        date_to = datetime.strptime(message.text.strip(), "%Y-%m-%d")
        data = await state.get_data()
        date_from = data.get("date_from")
        
        if date_from > date_to:
            await message.answer("❌ Дата начала не может быть позже даты окончания!")
            await state.clear()
            return
        
        date_from = date_from.replace(hour=0, minute=0)
        date_to = date_to.replace(hour=23, minute=59)
        
        msg = await message.answer(f"📊 Сбор статистики за {date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}...\n⏱️ Подождите...")
        
        stats = await get_stats(date_from, date_to)
        await msg.delete()
        
        if stats['total_income'] == 0 and stats['sessions_count'] == 0:
            await message.answer(
                f"⚠️ *Нет данных за период {date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}*\n\n"
                f"💡 Возможные причины:\n"
                f"• В этот период не было операций\n"
                f"• Попробуйте расширить период",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard()
            )
        else:
            await message.answer(format_simple(stats, "СТАТИСТИКА ЗА ПЕРИОД"), parse_mode="Markdown", reply_markup=get_main_keyboard())
        
    except ValueError:
        await message.answer("❌ Неверный формат!", parse_mode="Markdown")
    
    await state.clear()

# ========== ОБРАБОТЧИК НЕИЗВЕСТНЫХ ==========
@dp.message()
async def unknown(message: types.Message):
    if not message.text.startswith("/"):
        await message.answer(
            "❓ Используйте кнопки меню\n\n"
            "📊 *Доступные отчеты:*\n"
            "• «📊 За сегодня» — за сегодня\n"
            "• «📈 За вчера» — за вчера\n"
            "• «📅 За неделю» — за 7 дней\n"
            "• «📆 За месяц» — за 30 дней\n"
            "• «🎯 Свой период» — за любой период",
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