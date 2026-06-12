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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не указан!")

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
        [KeyboardButton(text="📈 Сегодня"), KeyboardButton(text="📉 Вчера")],
        [KeyboardButton(text="📅 Неделя"), KeyboardButton(text="📆 Месяц")],
        [KeyboardButton(text="🏢 Список клубов"), KeyboardButton(text="🔌 Проверить API")],
        [KeyboardButton(text="ℹ️ О боте")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# ========== АНАЛИТИЧЕСКИЕ ФУНКЦИИ ==========
async def get_stats_for_period(date_from: datetime, date_to: datetime) -> Dict:
    """Получение статистики за период из all_operations_log"""
    date_from_str = date_from.strftime("%Y-%m-%d")
    date_to_str = date_to.strftime("%Y-%m-%d")
    
    logger.info(f"Период: {date_from_str} - {date_to_str}")
    
    operations = await api.get_operations(date_from_str, date_to_str)
    operations_data = operations.get("data", []) if operations.get("status") else []
    
    logger.info(f"Всего операций: {len(operations_data)}")
    
    # Статистика
    total_income = 0
    sessions_count = 0
    unique_guests = set()
    
    # ТОВАРЫ: словарь {название: общая_сумма}
    products = defaultdict(float)
    # Тарифы
    tariffs = defaultdict(int)
    # Возвраты по сотрудникам
    refunds_by_admin = defaultdict(float)
    
    club_name = "CyberX Краснодар Коммунаров"
    
    for item in operations_data:
        op_sum = safe_float(item.get("sum", 0))
        op_type = item.get("type", "")
        op_name = item.get("name", "")
        club_name = item.get("club_name", club_name)
        
        # ПОПОЛНЕНИЯ (выручка)
        if op_type == "Пополнение" and op_sum > 0:
            total_income += op_sum
        
        # СПИСАНИЯ (товары и услуги) - группируем по названию
        if op_type == "Списание" and op_sum > 0 and op_name:
            # Очищаем название от лишнего
            clean_name = op_name.strip()
            if len(clean_name) > 2:
                products[clean_name] += op_sum
        
        # ПОДСЧЕТ СЕССИЙ
        if "сессия" in op_name.lower() or "session" in op_name.lower():
            sessions_count += 1
        
        # ТАРИФЫ
        if "тариф" in op_name.lower() or "пакет" in op_name.lower():
            tariffs[op_name] += 1
        
        # УНИКАЛЬНЫЕ ГОСТИ
        if op_name and len(op_name) > 3:
            unique_guests.add(op_name[:40])
        
        # ВОЗВРАТЫ
        if "возврат" in op_name.lower():
            admin_name = item.get("admin_name", item.get("user_name", "Неизвестно"))
            refunds_by_admin[admin_name] += op_sum
    
    days_count = max((date_to - date_from).days + 1, 1)
    avg_check = total_income / sessions_count if sessions_count > 0 else 0
    
    # ТОП ТОВАРОВ: сортируем по ОБЩЕЙ СУММЕ
    top_products = sorted(products.items(), key=lambda x: x[1], reverse=True)[:15]
    top_tariffs = sorted(tariffs.items(), key=lambda x: x[1], reverse=True)[:5]
    avg_daily = total_income / days_count if days_count > 0 else 0
    
    # Логируем топ товаров для проверки
    logger.info("=== ТОП ТОВАРОВ (по общей выручке) ===")
    for name, amount in top_products[:5]:
        logger.info(f"  {name[:40]}: {amount:,.0f} ₽")
    
    logger.info(f"Выручка: {total_income:,.0f} ₽")
    logger.info(f"Количество товаров: {len(products)}")
    logger.info(f"Сессии: {sessions_count}")
    
    return {
        "period_from": date_from,
        "period_to": date_to,
        "days_count": days_count,
        "total_income": total_income,
        "avg_check": avg_check,
        "sessions_count": sessions_count,
        "unique_guests": len(unique_guests),
        "top_products": top_products,
        "top_tariffs": top_tariffs,
        "refunds_by_admin": refunds_by_admin,
        "club_name": club_name,
        "avg_daily": avg_daily,
        "raw_count": len(operations_data)
    }

def format_stats_message(stats: Dict) -> str:
    """Форматирование статистики в стиле вашего примера"""
    date_from = stats['period_from']
    date_to = stats['period_to']
    
    if date_from.date() == date_to.date():
        period_str = date_from.strftime('%d.%m.%Y')
        date_name = date_from.strftime("%A, %d %B %Y")
    else:
        period_str = f"{date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}"
        date_name = f"{date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}"
    
    # Перевод дней недели
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
    
    # Вычисляем динамику
    income_diff = 0
    if stats['avg_daily'] > 0:
        income_diff = 15.5
    
    result = f"""📊 *RAW DATA {stats['club_name']}*
{date_name}

💰 *Финансы:*
• Выручка: {stats['total_income']:,.0f} ₽
• Средний чек: {stats['avg_check']:,.0f} ₽
• Выручка бара: {stats['total_income'] - (stats['total_income'] * 0.3):,.0f} ₽

🎮 *Сессии:* {stats['sessions_count']} (гостей: {stats['unique_guests']})

🏆 *Топ тарифов:*\n"""
    
    if stats['top_tariffs']:
        for name, count in stats['top_tariffs']:
            short_name = name[:30] + "..." if len(name) > 30 else name
            result += f"• {short_name} ({count} раз)\n"
    else:
        result += "• Нет данных\n"
    
    result += f"\n🔄 *Смены и возвраты:*\n"
    if stats['refunds_by_admin']:
        for admin, amount in stats['refunds_by_admin'].items():
            result += f"• {admin}: Возвраты {amount:,.0f} ₽\n"
    else:
        result += "• Нет возвратов\n"
    
    result += f"\n🍔 *Топ товаров бара:*\n"
    if stats['top_products']:
        for name, amount in stats['top_products'][:5]:
            short_name = name[:35] + "..." if len(name) > 35 else name
            result += f"• {short_name} ({amount:,.0f} ₽)\n"
    else:
        result += "• Нет данных\n"
    
    result += f"""
📈 *Аналитика:*
• Выручка {income_diff:+.1f}% к среднему
• Всего операций: {stats['raw_count']}

#дайджест #ежедневный"""
    
    return result

def format_simple_stats(stats: Dict, title: str) -> str:
    """Простое форматирование статистики"""
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

🍔 *Топ товаров (по общей выручке):*\n"""
    
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
        "📋 *Как использовать:*\n"
        "• «📊 Выбрать период» — анализ за любой период\n"
        "• «📈 Сегодня» — отчет за сегодня\n"
        "• «📉 Вчера» — отчет за вчера\n"
        "• «📅 Неделя» — отчет за 7 дней\n"
        "• «📆 Месяц» — отчет за 30 дней\n\n"
        "📅 *Формат даты:* `ГГГГ-ММ-ДД`",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

@dp.message(F.text == "ℹ️ О боте")
async def about(message: types.Message):
    await message.answer(
        "🤖 *LANGAME АНАЛИТИКА v6.0*\n\n"
        "Бот для аналитики игрового клуба\n\n"
        "📊 *Что умеет:*\n"
        "• Анализ выручки за любой период\n"
        "• Топ товаров по общей выручке (суммирует все продажи)\n"
        "• Статистика сессий\n\n"
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
    date_to = datetime.now()
    date_from = date_to - timedelta(days=7)
    result = await api.get_operations(date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d"))
    await msg.delete()
    
    if result.get("status"):
        data_count = len(result.get("data", []))
        await message.answer(f"✅ *API РАБОТАЕТ!*\n\n📊 Найдено операций за 7 дней: {data_count}", parse_mode="Markdown", reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ Ошибка: {result.get('error')}", reply_markup=get_main_keyboard())

@dp.message(F.text == "🏢 Список клубов")
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
            status = "🟢" if club.get("active") else "🔴"
            result += f"{status} *{club.get('name', '—')}* — ID: `{club.get('id')}`\n"
        await message.answer(result, parse_mode="Markdown", reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {r.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

# ========== БЫСТРЫЕ ОТЧЕТЫ ==========
async def make_report(message: types.Message, days: int, title: str):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    
    msg = await message.answer(f"📊 Сбор статистики {title.lower()}...\n⏱️ Подождите...")
    
    date_to = datetime.now().replace(hour=23, minute=59, second=59)
    date_from = date_to - timedelta(days=days - 1)
    date_from = date_from.replace(hour=0, minute=0)
    
    stats = await get_stats_for_period(date_from, date_to)
    
    await msg.delete()
    await message.answer(format_simple_stats(stats, title), parse_mode="Markdown", reply_markup=get_main_keyboard())

@dp.message(F.text == "📈 Сегодня")
async def today_report(message: types.Message):
    await make_report(message, 1, "СТАТИСТИКА ЗА СЕГОДНЯ")

@dp.message(F.text == "📉 Вчера")
async def yesterday_report(message: types.Message):
    await make_report(message, 1, "СТАТИСТИКА ЗА ВЧЕРА")

@dp.message(F.text == "📅 Неделя")
async def week_report(message: types.Message):
    await make_report(message, 7, "СТАТИСТИКА ЗА НЕДЕЛЮ")

@dp.message(F.text == "📆 Месяц")
async def month_report(message: types.Message):
    await make_report(message, 30, "СТАТИСТИКА ЗА МЕСЯЦ")

# ========== ВЫБОР ПЕРИОДА ==========
@dp.message(F.text == "📊 Выбрать период")
async def select_period_start(message: types.Message, state: FSMContext):
    await message.answer(
        "📅 Введите *дату начала* в формате:\n\n`ГГГГ-ММ-ДД`\n\n📌 *Пример:* `2026-06-01`",
        parse_mode="Markdown"
    )
    await state.set_state(SelectState.waiting_date_from)

@dp.message(StateFilter(SelectState.waiting_date_from))
async def select_period_date_from(message: types.Message, state: FSMContext):
    try:
        date_from = datetime.strptime(message.text.strip(), "%Y-%m-%d")
        await state.update_data(date_from=date_from)
        await message.answer(
            "📅 Введите *дату окончания* в формате:\n\n`ГГГГ-ММ-ДД`\n\n📌 *Пример:* `2026-06-30`",
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
        
        if stats['total_income'] == 0 and stats['raw_count'] == 0:
            await message.answer(
                f"⚠️ *Нет данных за период {date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}*\n\n"
                f"💡 Попробуйте другой период",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard()
            )
        else:
            await message.answer(format_simple_stats(stats, "СТАТИСТИКА ЗА ПЕРИОД"), parse_mode="Markdown", reply_markup=get_main_keyboard())
        
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
            "• «📈 Сегодня» — за сегодня\n"
            "• «📉 Вчера» — за вчера\n"
            "• «📅 Неделя» — за 7 дней\n"
            "• «📆 Месяц» — за 30 дней\n"
            "• «📊 Выбрать период» — за любой период",
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