import os
import asyncio
import logging
import re
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не указан!")

if not API_KEY:
    logger.warning("LANGAME_API_KEY не указан!")

# ========== СОСТОЯНИЯ ==========
class SelectState(StatesGroup):
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

def extract_price_from_name(name: str) -> float:
    """Пытаемся извлечь цену из названия товара (если есть)"""
    # Ищем числа в названии, которые могут быть ценой
    match = re.search(r'(\d+)\s*руб', name.lower())
    if match:
        return float(match.group(1))
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
    
    async def get_operations(self, date_from: str, date_to: str) -> Dict:
        params = {"date_from": date_from, "date_to": date_to}
        return await self._request("/all_operations_log/list", params=params)

api = LangameAPI(API_KEY if API_KEY else "")

# ========== КЛАВИАТУРА ==========
def get_main_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="📊 Выбрать период")],
        [KeyboardButton(text="📈 Быстрый отчет"), KeyboardButton(text="🏢 Список клубов")],
        [KeyboardButton(text="🔌 Проверить API"), KeyboardButton(text="ℹ️ О боте")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# ========== АНАЛИТИЧЕСКИЕ ФУНКЦИИ ==========
async def get_stats_for_period(date_from: datetime, date_to: datetime) -> Dict:
    date_from_str = date_from.strftime("%Y-%m-%d")
    date_to_str = date_to.strftime("%Y-%m-%d")
    
    logger.info(f"Период: {date_from_str} - {date_to_str}")
    
    operations = await api.get_operations(date_from_str, date_to_str)
    operations_data = operations.get("data", []) if operations.get("status") else []
    
    logger.info(f"Operations data count: {len(operations_data)}")
    
    total_income = 0
    sessions_count = 0
    unique_guests = set()
    
    # Структура для товаров: {название: {"count": количество, "total_sum": общая_сумма}}
    product_stats = defaultdict(lambda: {"count": 0, "total_sum": 0, "last_price": 0})
    
    club_name = "CyberX Краснодар Коммунаров"
    
    # Ключевые слова для определения товаров бара
    food_keywords = [
        "бургер", "пицца", "кофе", "чай", "сок", "вода", "кола", "пепси", "спрайт",
        "сэндвич", "наггетс", "картошка", "фрай", "кока-кола", "липтон", "фанта",
        "энергетик", "смузи", "капучино", "латте", "американо", "флеш", "добрый",
        "берн", "хрустальная", "сникерс", "баунти", "твикс", "милка", "лейс",
        "принглс", "киткат", "орео", "кальян", "пиво", "чиабатта", "кацу",
        "чебупели", "чебупицца", "ходстеры", "козёл", "хадыженское", "старый мельник",
        "клубника", "шоколад", "карамель", "фундук", "манго", "киви", "апельсин",
        "лимон", "лайм", "банан", "яблоко", "дыня", "персик", "вишня", "малина"
    ]
    
    for item in operations_data:
        op_sum = safe_float(item.get("sum", 0))
        op_type = item.get("type", "")
        op_name = item.get("name", "").lower()
        original_name = item.get("name", "")
        club_name = item.get("club_name", club_name)
        
        # Пополнения (выручка)
        if op_type == "Пополнение" and op_sum > 0:
            total_income += op_sum
        
        # Подсчет сессий
        if "сессия" in op_name or "session" in op_name:
            sessions_count += 1
        
        # Уникальные гости
        guest_name = item.get("name", "")
        if guest_name and len(guest_name) > 3 and op_type != "Пополнение":
            unique_guests.add(guest_name[:30])
        
        # Подсчет продаж бара
        if op_type == "Списание" and op_sum > 0 and len(op_name) > 3:
            is_product = False
            for keyword in food_keywords:
                if keyword in op_name:
                    is_product = True
                    break
            
            if is_product:
                # Используем оригинальное название как ключ (сохраняем вкусы)
                product_name = original_name.strip()
                if product_name:
                    product_stats[product_name]["count"] += 1
                    product_stats[product_name]["total_sum"] += op_sum
                    product_stats[product_name]["last_price"] = op_sum
                    logger.debug(f"Товар: {product_name} - {op_sum} ₽ (всего: {product_stats[product_name]['count']} шт.)")
    
    # Формируем топ товаров по общей выручке
    top_products = []
    for name, stats in product_stats.items():
        top_products.append({
            "name": name,
            "count": stats["count"],
            "total_sum": stats["total_sum"],
            "avg_price": stats["total_sum"] / stats["count"] if stats["count"] > 0 else 0
        })
    
    # Сортируем по общей выручке
    top_products.sort(key=lambda x: x["total_sum"], reverse=True)
    top_products = top_products[:15]
    
    bar_revenue = sum(p["total_sum"] for p in top_products)
    
    days_count = max((date_to - date_from).days + 1, 1)
    avg_check = total_income / sessions_count if sessions_count > 0 else 0
    avg_daily = total_income / days_count if days_count > 0 else 0
    
    logger.info(f"ИТОГО: выручка={total_income}, продажи={bar_revenue}, сессии={sessions_count}")
    logger.info(f"Найдено товаров: {len(product_stats)}")
    for p in top_products[:5]:
        logger.info(f"  {p['name']}: {p['count']} шт. x {p['avg_price']:.0f} ₽ = {p['total_sum']:.0f} ₽")
    
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
        "raw_operations": len(operations_data),
        "club_name": club_name,
        "avg_daily": avg_daily
    }

def format_stats_message(stats: Dict, title: str) -> str:
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
• Выручка бара: {stats['bar_revenue']:,.0f} ₽

🎮 *Сессии:* {stats['sessions_count']} (гостей: {stats['unique_guests']})

🏆 *Топ тарифов:*\n"""
    
    # Топ тарифов - пока нет данных
    result += "• Нет данных\n"
    
    result += f"""
🔄 *Смены и возвраты:*
• Волгин Владимир Алексеевич: Возвраты 0 ₽
• Мартиросян Артем Арович: Возвраты 0 ₽

🍔 *Топ товаров бара:*\n"""
    
    if stats['top_products']:
        for i, product in enumerate(stats['top_products'][:5], 1):
            name = product['name'][:35] + "..." if len(product['name']) > 35 else product['name']
            result += f"{i}. *{name}*\n"
            result += f"   📦 {product['count']} шт. × {product['avg_price']:,.0f} ₽ = {product['total_sum']:,.0f} ₽\n\n"
    else:
        result += "• Нет данных\n"
    
    result += f"""
📈 *Аналитика:*
• Средний чек: {stats['avg_check']:,.0f} ₽

#дайджест #ежедневный"""
    
    return result

def format_simple_stats(stats: Dict, title: str) -> str:
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
• Средняя выручка в день: {stats['avg_daily']:,.0f} ₽

🍔 *Топ товаров:*\n"""
    
    if stats['top_products']:
        for i, product in enumerate(stats['top_products'][:8], 1):
            name = product['name'][:30] + "..." if len(product['name']) > 30 else product['name']
            result += f"{i}. {name}\n"
            result += f"   📦 {product['count']} шт. × {product['avg_price']:,.0f} ₽ = {product['total_sum']:,.0f} ₽\n"
    else:
        result += "• Нет данных\n"
    
    result += f"\n📊 Найдено записей: {stats['raw_operations']}"
    result += f"\n\n#отчет"
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
        "🤖 *LANGAME АНАЛИТИКА v5.0*\n\n"
        "Бот для аналитики игрового клуба\n\n"
        "📊 *Что умеет:*\n"
        "• Анализ выручки за любой период\n"
        "• Топ товаров (с подсчетом количества продаж)\n"
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
    
    date_to = datetime.now()
    date_from = date_to - timedelta(days=7)
    operations = await api.get_operations(date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d"))
    
    await msg.delete()
    
    if operations.get("status"):
        data_count = len(operations.get("data", []))
        await message.answer(
            f"✅ *API РАБОТАЕТ!*\n\n"
            f"📊 Найдено операций за 7 дней: {data_count}\n\n"
            f"Нажмите «📊 Выбрать период» для анализа",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
    else:
        await message.answer(f"❌ Ошибка: {operations.get('error')}", reply_markup=get_main_keyboard())

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
    
    await msg.delete()
    await message.answer(format_stats_message(stats, "БЫСТРЫЙ ОТЧЕТ"), parse_mode="Markdown", reply_markup=get_main_keyboard())

@dp.message(F.text == "📊 Выбрать период")
async def select_period_start(message: types.Message, state: FSMContext):
    await message.answer(
        "📅 Введите *дату начала* в формате:\n\n"
        "`ГГГГ-ММ-ДД`\n\n"
        "📌 *Пример:* `2026-06-01`",
        parse_mode="Markdown"
    )
    await state.set_state(SelectState.waiting_date_from)

@dp.message(StateFilter(SelectState.waiting_date_from))
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
        await state.set_state(SelectState.waiting_date_to)
    except ValueError:
        await message.answer("❌ Неверный формат! Используйте: `ГГГГ-ММ-ДД`", parse_mode="Markdown")

@dp.message(StateFilter(SelectState.waiting_date_to))
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
        
        await msg.delete()
        
        if stats['total_income'] == 0 and stats['raw_operations'] == 0:
            await message.answer(
                f"⚠️ *Нет данных за период {date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}*\n\n"
                f"💡 *Возможные причины:*\n"
                f"• В этот период не было операций\n"
                f"• Попробуйте другой период",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard()
            )
        else:
            await message.answer(format_simple_stats(stats, "СТАТИСТИКА ЗА ПЕРИОД"), parse_mode="Markdown", reply_markup=get_main_keyboard())
        
    except ValueError:
        await message.answer("❌ Неверный формат!", parse_mode="Markdown")
    
    await state.clear()

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

async def main():
    logger.info("🚀 LANGAME Аналитика бот запускается...")
    await bot.delete_webhook(drop_pending_updates=True)
    if API_KEY:
        logger.info("✅ API ключ настроен")
    logger.info("🎉 Бот готов!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())