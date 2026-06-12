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
API_BASE_URL = "https://cyberx302.langame.ru/public_api"

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

# ========== API КЛИЕНТ ==========
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
                    else:
                        logger.error(f"HTTP {resp.status}: {url}")
                        return {"status": False, "error": f"HTTP {resp.status}"}
        except Exception as e:
            logger.error(f"Ошибка: {e}")
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

# ========== КЛАВИАТУРА ==========
def get_main_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="📊 Выбрать период")],
        [KeyboardButton(text="📈 Быстрый отчет"), KeyboardButton(text="🏢 Список клубов")],
        [KeyboardButton(text="🔌 Проверить API"), KeyboardButton(text="ℹ️ О боте")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# ========== ФУНКЦИЯ ДЛЯ ТОПА ТОВАРОВ ==========
async def get_top_products(date_from: datetime, date_to: datetime) -> list:
    date_from_str = date_from.strftime("%Y-%m-%d")
    date_to_str = date_to.strftime("%Y-%m-%d")
    
    products_list = await api.get_products_list()
    goods = {}
    for item in products_list.get("data", []):
        goods[item.get("id")] = item.get("name", f"Товар #{item.get('id')}")
    
    first_page = await api.get_products_expense(date_from_str, date_to_str, 1)
    total_pages = first_page.get("total_pages", 1)
    
    revenue = defaultdict(float)
    
    for page in range(1, total_pages + 1):
        data = await api.get_products_expense(date_from_str, date_to_str, page)
        for sale in data.get("data", []):
            if sale.get("cancel") == 1:
                continue
            goods_id = sale.get("list_goods_id")
            name = goods.get(goods_id, f"Товар #{goods_id}")
            count = safe_float(sale.get("count", 1))
            price = safe_float(sale.get("price_sale", 0))
            revenue[name] += count * price
    
    return sorted(revenue.items(), key=lambda x: x[1], reverse=True)[:15]

# ========== АНАЛИТИЧЕСКИЕ ФУНКЦИИ ==========
async def get_stats_for_period(date_from: datetime, date_to: datetime) -> Dict:
    date_from_str = date_from.strftime("%Y-%m-%d")
    date_to_str = date_to.strftime("%Y-%m-%d")
    
    operations = await api.get_operations(date_from_str, date_to_str)
    operations_data = operations.get("data", []) if operations.get("status") else []
    
    total_income = 0
    sessions_count = 0
    unique_guests = set()
    club_name = "CyberX Краснодар Коммунаров"
    
    # Список товаров, которые НЕ должны попадать в выручку
    # (они уже учитываются в products/expense для топа, но не для выручки)
    exclude_products = [
        "Монстер", "Берн", "Импор", "Пиво", "Добрый", "Флеш", "Сникерс",
        "Баунти", "Твикс", "Милка", "Лейс", "Принглс", "Кальян", "Липтон",
        "Кола", "Спрайт", "Фанта", "Энергетик", "Чиабатта", "Кацу", "Хот-дог"
    ]
    
    for item in operations_data:
        op_sum = safe_float(item.get("sum", 0))
        op_type = item.get("type", "")
        op_name = item.get("name", "")
        op_name_lower = op_name.lower()
        club_name = item.get("club_name", club_name)
        
        # ТОЛЬКО РЕАЛЬНЫЕ ПОПОЛНЕНИЯ (без возвратов и без товаров)
        is_valid_income = False
        if (op_type == "Пополнение" or op_type == "plus") and op_sum > 0:
            # Исключаем возвраты
            if "возврат" in op_name_lower:
                continue
            # Исключаем продажи товаров (они идут как plus, но это не пополнения)
            is_product = False
            for product in exclude_products:
                if product in op_name:
                    is_product = True
                    break
            if not is_product:
                is_valid_income = True
        
        if is_valid_income:
            total_income += op_sum
            logger.debug(f"Пополнение: +{op_sum} ₽ | {op_name[:50]}")
        
        # Подсчет сессий
        if "сессия" in op_name_lower or "session" in op_name_lower:
            sessions_count += 1
        
        # Уникальные гости
        if op_name and len(op_name) > 3 and "пополнение" not in op_name_lower:
            unique_guests.add(op_name[:30])
    
    days_count = max((date_to - date_from).days + 1, 1)
    avg_check = total_income / sessions_count if sessions_count > 0 else 0
    avg_daily = total_income / days_count if days_count > 0 else 0
    
    logger.info("=" * 60)
    logger.info(f"✅ ВЫРУЧКА: {total_income:,.0f} ₽")
    logger.info(f"🎮 Сессии: {sessions_count}")
    logger.info(f"👥 Гости: {len(unique_guests)}")
    logger.info("=" * 60)
    
    return {
        "total_income": total_income,
        "avg_check": avg_check,
        "sessions_count": sessions_count,
        "unique_guests": len(unique_guests),
        "avg_daily": avg_daily,
        "club_name": club_name,
        "raw_operations": len(operations_data)
    }

# ========== ФОРМАТИРОВАНИЕ ОТЧЕТОВ ==========
def format_simple_stats(stats: Dict, title: str, top_products: list) -> str:
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

🎮 *Активность:*
• Сессии: {stats['sessions_count']}
• Уникальных гостей: {stats['unique_guests']}
• Средняя выручка в день: {stats['avg_daily']:,.0f} ₽

🍔 *Топ товаров:*\n"""
    
    if top_products:
        for i, (name, amount) in enumerate(top_products[:10], 1):
            short_name = name[:30] + "..." if len(name) > 30 else name
            result += f"{i}. {short_name} — {amount:,.0f} ₽\n"
    else:
        result += "• Нет данных\n"
    
    result += f"\n#отчет"
    return result

def format_full_report(stats: Dict, top_products: list) -> str:
    date_from = stats['period_from']
    date_to = stats['period_to']
    
    if date_from.date() == date_to.date():
        period_str = date_from.strftime('%d.%m.%Y')
    else:
        period_str = f"{date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}"
    
    # Форматируем дату
    date_name = date_from.strftime("%A, %d %B %Y")
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
        date_name = date_name.replace(eng, rus)
    for eng, rus in months.items():
        date_name = date_name.replace(eng, rus)
    
    result = f"""📊 *RAW DATA {stats['club_name']}*
{date_name}

💰 *Финансы:*
• Выручка: {stats['total_income']:,.0f} ₽
• Средний чек: {stats['avg_check']:,.0f} ₽

🎮 *Сессии:* {stats['sessions_count']} (гостей: {stats['unique_guests']})

🏆 *Топ тарифов:*\n"""
    
    result += "• Нет данных\n"
    
    result += f"""
🔄 *Смены и возвраты:*
• Нет данных

🍔 *Топ товаров бара:*\n"""
    
    if top_products:
        for i, (name, amount) in enumerate(top_products[:5], 1):
            short_name = name[:25] + "..." if len(name) > 25 else name
            result += f"{i}. {short_name} — {amount:,.0f} ₽\n"
    else:
        result += "• Нет данных\n"
    
    result += f"""
📈 *Аналитика:*
• Средний чек: {stats['avg_check']:,.0f} ₽

#дайджест #ежедневный"""
    
    return result

# ========== ОБРАБОТЧИКИ ==========
@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "📊 *LANGAME АНАЛИТИКА*\n\n"
        "Бот для анализа финансовых показателей игрового клуба.\n\n"
        "📋 *Как использовать:*\n"
        "• «📊 Выбрать период» — анализ за любой период\n"
        "• «📈 Быстрый отчет» — отчет за сегодня\n"
        "• «🏢 Список клубов» — список клубов\n\n"
        "📅 *Формат даты:* `ГГГГ-ММ-ДД`\n"
        "Пример: `2026-06-01`",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

@dp.message(F.text == "ℹ️ О боте")
async def about(message: types.Message):
    await message.answer(
        "🤖 *LANGAME АНАЛИТИКА v7.0*\n\n"
        "Бот для аналитики игрового клуба\n\n"
        "📊 *Что умеет:*\n"
        "• Анализ выручки за любой период (только пополнения, без товаров)\n"
        "• Топ товаров (количество × цена)\n"
        "• Статистика сессий\n\n"
        "📅 *Формат даты:* ГГГГ-ММ-ДД",
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
    date_from = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    
    result = await api.get_products_expense(date_from, date_to)
    await msg.delete()
    
    if result.get("status"):
        data_count = len(result.get("data", []))
        await message.answer(
            f"✅ *API РАБОТАЕТ!*\n\n"
            f"📊 Найдено продаж за 7 дней: {data_count}\n\n"
            f"Нажмите «📊 Выбрать период» для анализа",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
    else:
        await message.answer(f"❌ Ошибка: {result.get('error')}", reply_markup=get_main_keyboard())

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
            status = "🟢" if club.get("active") else "🔴"
            result += f"{status} *{club.get('name', '—')}* — ID: `{club.get('id')}`\n"
        await message.answer(result, parse_mode="Markdown", reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {r.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

@dp.message(F.text == "📈 Быстрый отчет")
async def quick_report(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    
    msg = await message.answer("📊 Сбор статистики за сегодня...\n⏱️ Подождите...")
    
    date_to = datetime.now()
    date_from = date_to.replace(hour=0, minute=0, second=0, microsecond=0)
    
    stats = await get_stats_for_period(date_from, date_to)
    stats["period_from"] = date_from
    stats["period_to"] = date_to
    
    top_products = await get_top_products(date_from, date_to)
    
    await msg.delete()
    await message.answer(format_full_report(stats, top_products), parse_mode="Markdown", reply_markup=get_main_keyboard())

@dp.message(F.text == "📊 Выбрать период")
async def select_period_start(message: types.Message, state: FSMContext):
    await message.answer(
        "📅 Введите *дату начала* в формате:\n\n"
        "`ГГГГ-ММ-ДД`\n\n"
        "📌 *Пример:* `2026-06-01`",
        parse_mode="Markdown"
    )
    await state.set_state(PeriodState.waiting_date_from)

@dp.message(StateFilter(PeriodState.waiting_date_from))
async def select_period_date_from(message: types.Message, state: FSMContext):
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
async def select_period_execute(message: types.Message, state: FSMContext):
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
        
        stats = await get_stats_for_period(date_from, date_to)
        stats["period_from"] = date_from
        stats["period_to"] = date_to
        
        top_products = await get_top_products(date_from, date_to)
        
        await msg.delete()
        
        if stats['total_income'] == 0 and not top_products:
            await message.answer(
                f"⚠️ *Нет данных за период {date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}*\n\n"
                f"💡 *Возможные причины:*\n"
                f"• В этот период не было операций\n"
                f"• Попробуйте другой период",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard()
            )
        else:
            await message.answer(format_simple_stats(stats, "СТАТИСТИКА ЗА ПЕРИОД", top_products), 
                                parse_mode="Markdown", reply_markup=get_main_keyboard())
        
    except ValueError:
        await message.answer("❌ Неверный формат!", parse_mode="Markdown")
    
    await state.clear()

# ========== ОБРАБОТЧИК НЕИЗВЕСТНЫХ ==========
@dp.message()
async def unknown(message: types.Message):
    if not message.text.startswith("/"):
        await message.answer(
            "❓ Используйте кнопки меню\n\n"
            "📊 *Как получить отчет:*\n"
            "• «📈 Быстрый отчет» — за сегодня\n"
            "• «📊 Выбрать период» — за любой период\n\n"
            "📅 *Формат:* ГГГГ-ММ-ДД\n"
            "Пример: `2026-06-01`",
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