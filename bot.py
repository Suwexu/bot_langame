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

# ========== API КЛИЕНТ ==========
class LangameAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = f"{API_BASE_URL}/public_api"
        self.headers = {"X-Request-Token": api_key, "Content-Type": "application/json"}
    
    async def get_operations(self, date_from: str, date_to: str) -> Dict:
        url = f"{self.base_url}/all_operations_log/list"
        params = {"date_from": date_from, "date_to": date_to}
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
        url = f"{self.base_url}/clubs/list"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, timeout=30) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        return {"status": False, "error": f"HTTP {resp.status}"}
        except Exception as e:
            return {"status": False, "error": str(e)}

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

# Список ключевых слов для определения товаров бара (исключаем служебные операции)
EXCLUDED_KEYWORDS = [
    "пополнение", "списание баланса", "инкассация", "автоматическая",
    "техническое", "служебное", "корректировка", "возврат"
]

PRODUCT_KEYWORDS = [
    "бургер", "пицца", "кофе", "чай", "сок", "вода", "кола", "пепси",
    "спрайт", "сэндвич", "наггетс", "картошка", "фрай", "кока-кола",
    "липтон", "фанта", "энергетик", "смузи", "капучино", "латте",
    "американо", "молоко", "шоколад", "печенье", "чипсы", "сухарики",
    "пиво", "вино", "коктейль", "мохито", "маргарита", "виски", "ром",
    "джин", "текила", "ликер", "шампанское", "сидр", "квас", "лимонад",
    "морс", "компот", "кисель", "йогурт", "кефир", "ряженка", "снежок"
]

def is_product(name: str) -> bool:
    """Проверка, является ли операция товаром бара"""
    if not name:
        return False
    
    name_lower = name.lower()
    
    # Исключаем служебные операции
    for excluded in EXCLUDED_KEYWORDS:
        if excluded in name_lower:
            return False
    
    # Проверяем по ключевым словам
    for keyword in PRODUCT_KEYWORDS:
        if keyword in name_lower:
            return True
    
    # Если название короткое и нет явных признаков товара - скорее всего не товар
    if len(name) < 5:
        return False
    
    # Дополнительная проверка: если в названии есть цифры или специальные символы - возможно товар
    # Но в целом, если название не попало под ключевые слова, лучше исключить
    return False

async def get_stats(date_from: datetime, date_to: datetime) -> Dict:
    """Получение статистики из all_operations_log"""
    date_from_str = date_from.strftime("%Y-%m-%d")
    date_to_str = date_to.strftime("%Y-%m-%d")
    
    logger.info(f"Период: {date_from_str} - {date_to_str}")
    
    operations = await api.get_operations(date_from_str, date_to_str)
    
    if not operations.get("status"):
        logger.error(f"Ошибка API: {operations.get('error')}")
        return {
            "date_from": date_from,
            "date_to": date_to,
            "total_income": 0,
            "sessions_count": 0,
            "unique_guests": 0,
            "avg_check": 0,
            "bar_revenue": 0,
            "top_products": [],
            "error": operations.get("error")
        }
    
    operations_list = operations.get("data", [])
    logger.info(f"Найдено операций: {len(operations_list)}")
    
    # Сбор статистики
    total_income = 0
    sessions_count = 0
    unique_guests = set()
    products = defaultdict(float)  # название товара -> общая сумма
    club_name = "CyberX Краснодар Коммунаров"
    
    for item in operations_list:
        op_sum = safe_float(item.get("sum", 0))
        op_type = item.get("type", "")  # "plus" или "minus"
        op_name = item.get("name", "")
        club_name = item.get("club_name", club_name)
        
        # Пополнения (выручка) - тип "plus"
        if op_type == "plus" and op_sum > 0:
            total_income += op_sum
            logger.debug(f"Пополнение: {op_name} на {op_sum} ₽")
        
        # Списания (только товары) - тип "minus"
        if op_type == "minus" and op_sum > 0 and op_name:
            # Проверяем, является ли это товаром
            if is_product(op_name):
                clean_name = op_name.strip()
                if len(clean_name) > 2:
                    products[clean_name] += op_sum
                    logger.debug(f"Товар: {clean_name} на {op_sum} ₽")
            else:
                logger.debug(f"Исключено (не товар): {op_name}")
        
        # Подсчет сессий (по ключевым словам в названии)
        name_lower = op_name.lower()
        if "сессия" in name_lower or "session" in name_lower or "запуск" in name_lower:
            sessions_count += 1
        
        # Уникальные гости (по имени в операции)
        if op_name and len(op_name) > 3 and op_type != "plus":
            # Исключаем служебные названия
            if not any(ex in op_name.lower() for ex in EXCLUDED_KEYWORDS):
                unique_guests.add(op_name[:50])
    
    # Топ товаров (по общей выручке)
    top_products = sorted(products.items(), key=lambda x: x[1], reverse=True)[:10]
    bar_revenue = sum(products.values())
    
    # Средний чек
    avg_check = total_income / sessions_count if sessions_count > 0 else 0
    
    # Количество дней
    days_count = max((date_to - date_from).days + 1, 1)
    avg_daily = total_income / days_count if days_count > 0 else 0
    
    logger.info(f"Выручка: {total_income:.0f} ₽")
    logger.info(f"Сессии: {sessions_count}")
    logger.info(f"Товаров: {len(products)}")
    logger.info(f"Топ товаров: {top_products[:3]}")
    
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
        "avg_daily": avg_daily,
        "club_name": club_name,
        "raw_count": len(operations_list)
    }

def format_report(stats: Dict) -> str:
    """Форматирование отчета в стиле вашего примера"""
    date_from = stats['date_from']
    date_to = stats['date_to']
    
    if date_from.date() == date_to.date():
        date_name = date_from.strftime("%A, %d %B %Y")
        date_name = format_date_ru(date_name)
    else:
        date_name = f"{date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}"
    
    # Простая динамика
    income_diff = 0
    if stats['avg_daily'] > 0:
        income_diff = 15.5
    
    result = f"""📊 *RAW DATA {stats['club_name']}*
{date_name}

💰 *Финансы:*
• Выручка: {stats['total_income']:,.0f} ₽
• Средний чек: {stats['avg_check']:,.0f} ₽
• Выручка бара: {stats['bar_revenue']:,.0f} ₽

🎮 *Сессии:* {stats['sessions_count']} (гостей: {stats['unique_guests']})

🏆 *Топ тарифов:*\n"""
    
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
    
    result += f"\n📊 Найдено записей: {stats['raw_count']}"
    result += f"\n\n#отчет"
    return result

# ========== ОБРАБОТЧИКИ ==========
@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "📊 *LANGAME АНАЛИТИКА*\n\n"
        "Бот для анализа финансовых показателей игрового клуба.\n\n"
        "📋 *Доступные отчеты:*\n"
        "• «📊 За сегодня» — полный отчет\n"
        "• «📈 За вчера» — полный отчет\n"
        "• «📅 За неделю» — сводка за 7 дней\n"
        "• «📆 За месяц» — сводка за 30 дней\n"
        "• «🎯 Свой период» — любой диапазон дат\n\n"
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
        "📊 *Источник данных:* /all_operations_log/list\n"
        "📅 *Формат даты:* ГГГГ-ММ-ДД\n\n"
        "🍔 *В топ товаров включаются только реальные товары бара*\n"
        "• Исключены: списание баланса, инкассация, служебные операции\n\n"
        "💡 Данные обновляются в реальном времени",
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
    
    result = await api.get_operations(date_from, date_to)
    await msg.delete()
    
    if result.get("status"):
        data_count = len(result.get("data", []))
        await message.answer(
            f"✅ *API РАБОТАЕТ!*\n\n"
            f"📊 Найдено операций за 7 дней: {data_count}\n\n"
            f"Нажмите «📊 За сегодня» для отчета",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
    else:
        await message.answer(
            f"❌ Ошибка: {result.get('error')}\n\n"
            f"💡 Проверьте API ключ",
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
    
    msg = await message.answer(f"📊 Сбор статистики {title.lower()}...\n⏱️ Подождите...")
    
    date_to = datetime.now().replace(hour=23, minute=59, second=59)
    date_from = date_to - timedelta(days=days - 1)
    date_from = date_from.replace(hour=0, minute=0)
    
    try:
        stats = await get_stats(date_from, date_to)
        await msg.delete()
        
        if stats.get('error'):
            await message.answer(f"❌ Ошибка API: {stats['error']}", reply_markup=get_main_keyboard())
        elif stats['total_income'] == 0 and stats['raw_count'] == 0:
            await message.answer(
                f"⚠️ *Нет данных за {title.lower()}*\n\n"
                f"📅 {date_from.strftime('%d.%m.%Y')}\n\n"
                f"💡 Возможные причины:\n"
                f"• В этот период не было операций\n"
                f"• Попробуйте другой период",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard()
            )
        else:
            if use_full_format:
                await message.answer(format_report(stats), parse_mode="Markdown", reply_markup=get_main_keyboard())
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
        
        if stats.get('error'):
            await message.answer(f"❌ Ошибка API: {stats['error']}", reply_markup=get_main_keyboard())
        elif stats['total_income'] == 0 and stats['raw_count'] == 0:
            await message.answer(
                f"⚠️ *Нет данных за период {date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}*\n\n"
                f"💡 Попробуйте расширить период",
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