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
        """Лог операций (для выручки и сессий)"""
        return await self._request("/all_operations_log/list", params={"date_from": date_from, "date_to": date_to})
    
    async def get_products_list(self) -> Dict:
        """Список товаров (для получения названий по ID)"""
        return await self._request("/products/list")
    
    async def get_products_expense(self, date_from: str, date_to: str, page: int = 1) -> Dict:
        """Продажи товаров (основной источник для топа)"""
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
    """Возвращает топ товаров на основе данных из products/expense"""
    date_from_str = date_from.strftime("%Y-%m-%d")
    date_to_str = date_to.strftime("%Y-%m-%d")
    
    # 1. Получаем список товаров (ID -> название)
    products_list = await api.get_products_list()
    goods = {}
    for item in products_list.get("data", []):
        goods[item.get("id")] = item.get("name", f"Товар #{item.get('id')}")
    
    logger.info(f"Загружено товаров: {len(goods)}")
    
    # 2. Получаем продажи за период
    first_page = await api.get_products_expense(date_from_str, date_to_str, 1)
    total_pages = first_page.get("total_pages", 1)
    
    logger.info(f"Страниц продаж: {total_pages}")
    
    # Словарь для сбора выручки по товарам
    revenue = defaultdict(float)
    
    for page in range(1, total_pages + 1):
        data = await api.get_products_expense(date_from_str, date_to_str, page)
        
        for sale in data.get("data", []):
            # Пропускаем отмененные продажи
            if sale.get("cancel") == 1:
                continue
            
            goods_id = sale.get("list_goods_id")
            name = goods.get(goods_id, f"Товар #{goods_id}")
            
            count = safe_float(sale.get("count", 1))
            price = safe_float(sale.get("price_sale", 0))
            
            revenue[name] += count * price
    
    # Сортируем по убыванию и берем топ-15
    top = sorted(revenue.items(), key=lambda x: x[1], reverse=True)[:15]
    
    logger.info(f"Топ товаров: {len(top)} позиций")
    for name, amount in top[:5]:
        logger.info(f"  {name[:30]}: {amount:.0f} ₽")
    
    return top

# ========== АНАЛИТИЧЕСКИЕ ФУНКЦИИ (ВЫРУЧКА, СЕССИИ) ==========
async def get_stats_for_period(date_from: datetime, date_to: datetime) -> Dict:
    """Получение статистики из all_operations_log (выручка, сессии, гости)"""
    date_from_str = date_from.strftime("%Y-%m-%d")
    date_to_str = date_to.strftime("%Y-%m-%d")
    
    operations = await api.get_operations(date_from_str, date_to_str)
    operations_data = operations.get("data", []) if operations.get("status") else []
    
    logger.info(f"Найдено операций: {len(operations_data)}")
    
    total_income = 0
    total_refund = 0
    sessions_count = 0
    unique_guests = set()
    club_name = "CyberX Краснодар Коммунаров"
    
    # Детализация по типам операций
    income_by_type = defaultdict(float)
    refund_by_type = defaultdict(float)
    
    # Для отладки - список всех пополнений
    all_income_operations = []
    
    for item in operations_data:
        op_sum = safe_float(item.get("sum", 0))
        op_type = item.get("type", "")
        op_name = item.get("name", "").lower()
        original_name = item.get("name", "")
        op_source = item.get("source", "")
        op_cancel = item.get("cancel", 0)
        club_name = item.get("club_name", club_name)
        
        # Пропускаем отмененные операции
        if op_cancel == 1:
            logger.debug(f"Пропущена отмененная операция: {original_name[:50]}")
            continue
        
        # ПОПОЛНЕНИЯ (ВЫРУЧКА) - поддерживаем все форматы
        is_income = False
        
        if op_type == "Пополнение" and op_sum > 0:
            is_income = True
            income_by_type["Пополнение"] += op_sum
        elif op_type == "plus" and op_sum > 0:
            is_income = True
            income_by_type["plus"] += op_sum
        elif "пополнение" in op_name and op_sum > 0:
            is_income = True
            income_by_type["название_содержит_пополнение"] += op_sum
        
        if is_income:
            total_income += op_sum
            all_income_operations.append({
                "sum": op_sum,
                "type": op_type,
                "source": op_source,
                "name": original_name[:50]
            })
        
        # ВОЗВРАТЫ
        if "возврат" in op_name or "refund" in op_name:
            refund_amount = abs(op_sum)
            total_refund += refund_amount
            refund_by_type[op_type] += refund_amount
        
        # ПОДСЧЕТ СЕССИЙ
        if "сессия" in op_name or "session" in op_name or "запуск" in op_name:
            sessions_count += 1
        
        # УНИКАЛЬНЫЕ ГОСТИ
        guest_name = item.get("name", "")
        if guest_name and len(guest_name) > 3 and not is_income and "возврат" not in op_name:
            unique_guests.add(guest_name[:30])
    
    # Итоговая выручка (с учетом возвратов)
    net_income = total_income - total_refund
    
    days_count = max((date_to - date_from).days + 1, 1)
    avg_check = total_income / sessions_count if sessions_count > 0 else 0
    avg_daily = net_income / days_count if days_count > 0 else 0
    
    # ВЫВОДИМ ДЕТАЛЬНЫЙ ОТЧЕТ В ЛОГ
    logger.info("=" * 60)
    logger.info("📊 ДЕТАЛИЗАЦИЯ ВЫРУЧКИ:")
    logger.info(f"  Пополнения (тип 'Пополнение'): {income_by_type.get('Пополнение', 0):,.0f} ₽")
    logger.info(f"  Пополнения (тип 'plus'): {income_by_type.get('plus', 0):,.0f} ₽")
    logger.info(f"  Пополнения (по названию): {income_by_type.get('название_содержит_пополнение', 0):,.0f} ₽")
    logger.info(f"  ➕ Общая сумма пополнений: {total_income:,.0f} ₽")
    logger.info(f"")
    logger.info(f"  Возвраты (тип 'minus'): {refund_by_type.get('minus', 0):,.0f} ₽")
    logger.info(f"  Возвраты (тип 'Списание'): {refund_by_type.get('Списание', 0):,.0f} ₽")
    logger.info(f"  ➖ Общая сумма возвратов: {total_refund:,.0f} ₽")
    logger.info(f"")
    logger.info(f"  ✅ ИТОГОВАЯ ВЫРУЧКА: {net_income:,.0f} ₽")
    logger.info(f"")
    logger.info(f"  Сессии: {sessions_count}")
    logger.info(f"  Гости: {len(unique_guests)}")
    logger.info("=" * 60)
    
    # ВЫВОДИМ ВСЕ ПОПОЛНЕНИЯ ДЛЯ ОТЛАДКИ
    if all_income_operations:
        logger.info("📋 СПИСОК ВСЕХ ПОПОЛНЕНИЙ:")
        for inc in all_income_operations:
            logger.info(f"  +{inc['sum']:,.0f} ₽ | тип={inc['type']} | источник={inc['source']} | {inc['name']}")
    else:
        logger.info("📋 Нет пополнений за этот период")
    
    return {
        "total_income": net_income,
        "total_income_gross": total_income,
        "total_refund": total_refund,
        "income_by_type": dict(income_by_type),
        "refund_by_type": dict(refund_by_type),
        "avg_check": avg_check,
        "sessions_count": sessions_count,
        "unique_guests": len(unique_guests),
        "avg_daily": avg_daily,
        "club_name": club_name,
        "raw_operations": len(operations_data),
        "all_income_operations": all_income_operations
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
        "🤖 *LANGAME АНАЛИТИКА v6.0*\n\n"
        "Бот для аналитики игрового клуба\n\n"
        "📊 *Что умеет:*\n"
        "• Анализ выручки за любой период\n"
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
        total_pages = result.get("total_pages", 0)
        await message.answer(
            f"✅ *API РАБОТАЕТ!*\n\n"
            f"📊 Найдено продаж за 7 дней: {data_count}\n"
            f"📄 Всего страниц: {total_pages}\n\n"
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
    
    # Получаем статистику
    stats = await get_stats_for_period(date_from, date_to)
    stats["period_from"] = date_from
    stats["period_to"] = date_to
    
    # Получаем топ товаров
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
        
        # Получаем статистику
        stats = await get_stats_for_period(date_from, date_to)
        stats["period_from"] = date_from
        stats["period_to"] = date_to
        
        # Получаем топ товаров
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