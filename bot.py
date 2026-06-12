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
        logger.info(f"Запрос: {url}, параметры: {params}")
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
    
    # Используем эндпоинт /transactions/list вместо /balances/list
    async def get_transactions(self, date_from: str, date_to: str, page: int = 1, limit: int = 2000) -> Dict:
        params = {"date_from": date_from, "date_to": date_to, "page": page, "page_limit": limit}
        return await self._request("/transactions/list", params=params)
    
    # Используем эндпоинт /all_operations_log/list для получения всех операций
    async def get_operations(self, date_from: str, date_to: str) -> Dict:
        params = {"date_from": date_from, "date_to": date_to}
        return await self._request("/all_operations_log/list", params=params)

api = LangameAPI(API_KEY if API_KEY else "")

# ========== КЛАВИАТУРА ==========
def get_main_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="📊 Выбрать период")],
        [KeyboardButton(text="🏢 Список клубов")],
        [KeyboardButton(text="🔌 Проверить API"), KeyboardButton(text="ℹ️ О боте")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# ========== АНАЛИТИЧЕСКИЕ ФУНКЦИИ ==========
async def get_stats_for_period(date_from: datetime, date_to: datetime) -> Dict:
    """Получение статистики за период"""
    date_from_str = date_from.strftime("%Y-%m-%d")
    date_to_str = date_to.strftime("%Y-%m-%d")
    
    logger.info(f"Период: {date_from_str} - {date_to_str}")
    
    # Получаем данные из работающих эндпоинтов
    transactions = await api.get_transactions(date_from_str, date_to_str, limit=2000)
    operations = await api.get_operations(date_from_str, date_to_str)
    
    transactions_data = transactions.get("data", []) if transactions.get("status") else []
    operations_data = operations.get("data", []) if operations.get("status") else []
    
    logger.info(f"Transactions data count: {len(transactions_data)}")
    logger.info(f"Operations data count: {len(operations_data)}")
    
    # Сбор статистики
    total_income = 0
    unique_guests = set()
    sessions_count = 0
    product_sales = defaultdict(float)
    bar_revenue = 0
    
    # Из транзакций - это операции с деньгами
    for item in transactions_data:
        amount = safe_float(item.get("balance", 0))
        if amount > 0:
            total_income += amount
        guest_id = item.get("guest_id")
        if guest_id:
            unique_guests.add(str(guest_id))
    
    # Из лога операций - здесь есть информация о сессиях и товарах
    for item in operations_data:
        op_name = item.get("name", "").lower()
        op_sum = safe_float(item.get("sum", 0))
        
        # Подсчет сессий
        if "сессия" in op_name or "session" in op_name:
            sessions_count += 1
        
        # Подсчет продаж бара (по наличию названия товара)
        if op_sum > 0 and len(op_name) > 3 and "пополнение" not in op_name:
            if any(word in op_name for word in ["бургер", "пицца", "кофе", "чай", "сок", "вода", "кола", "сэндвич", "наггетс", "картошка", "фрай"]):
                product_sales[item.get("name", "Товар")] += op_sum
                bar_revenue += op_sum
    
    # Количество дней
    days_count = max((date_to - date_from).days + 1, 1)
    
    # Средний чек
    avg_check = 0
    if transactions_data:
        positive_items = [t for t in transactions_data if safe_float(t.get("balance", 0)) > 0]
        if positive_items:
            total_sum = sum(safe_float(t.get("balance", 0)) for t in positive_items)
            avg_check = total_sum / len(positive_items)
    
    # Топ товаров
    top_products = sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:10]
    
    logger.info(f"ИТОГО: выручка={total_income}, продажи={bar_revenue}, сессии={sessions_count}")
    
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
        "raw_transactions": len(transactions_data),
        "raw_operations": len(operations_data)
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
    
    result += f"\n📊 *Найдено записей:*\n• Транзакций: {stats['raw_transactions']}\n• Операций: {stats['raw_operations']}"
    
    result += f"\n\n#отчет"
    return result

# ========== ОБРАБОТЧИКИ ==========
@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "📊 *LANGAME АНАЛИТИКА*\n\n"
        "Бот для анализа финансовых показателей игрового клуба.\n\n"
        "📋 *Как использовать:*\n"
        "1. Нажмите «📊 Выбрать период»\n"
        "2. Введите начальную дату\n"
        "3. Введите конечную дату\n\n"
        "📅 *Формат даты:* `ГГГГ-ММ-ДД`\n"
        "Пример: `2026-06-01`\n\n"
        "📊 *Данные берутся из:*\n"
        "• /transactions/list — транзакции\n"
        "• /all_operations_log/list — лог операций",
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
        "• Топ товаров\n\n"
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
    
    # Проверяем транзакции за последние 7 дней
    date_to = datetime.now()
    date_from = date_to - timedelta(days=7)
    transactions = await api.get_transactions(date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d"))
    
    await msg.delete()
    
    if transactions.get("status"):
        data_count = len(transactions.get("data", []))
        await message.answer(
            f"✅ *API РАБОТАЕТ!*\n\n"
            f"📊 Найдено транзакций за 7 дней: {data_count}\n\n"
            f"Нажмите «📊 Выбрать период» для анализа",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
    else:
        await message.answer(f"❌ Ошибка: {transactions.get('error')}", reply_markup=get_main_keyboard())

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

# ========== ВЫБОР ПЕРИОДА ==========
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
        
        # Добавляем время для корректного диапазона
        date_from = date_from.replace(hour=0, minute=0)
        date_to = date_to.replace(hour=23, minute=59)
        
        msg = await message.answer(f"📊 Сбор статистики за {date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}...\n⏱️ Подождите до 30 секунд...")
        
        stats = await get_stats_for_period(date_from, date_to)
        
        await msg.delete()
        
        if stats['total_income'] == 0 and stats['raw_transactions'] == 0:
            await message.answer(
                f"⚠️ *Нет данных за период {date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}*\n\n"
                f"💡 *Возможные причины:*\n"
                f"• В этот период не было операций\n"
                f"• Попробуйте другой период\n"
                f"• Нажмите «🔌 Проверить API» для диагностики",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard()
            )
        else:
            await message.answer(format_stats_message(stats, "СТАТИСТИКА ЗА ПЕРИОД"), parse_mode="Markdown", reply_markup=get_main_keyboard())
        
    except ValueError:
        await message.answer("❌ Неверный формат! Используйте: `ГГГГ-ММ-ДД`", parse_mode="Markdown")
    
    await state.clear()

# ========== ОСТАЛЬНЫЕ ОБРАБОТЧИКИ ==========
@dp.message()
async def unknown(message: types.Message):
    if not message.text.startswith("/"):
        await message.answer(
            "❓ Используйте кнопки меню\n\n"
            "📊 *Как получить отчет:*\n"
            "1. Нажмите «📊 Выбрать период»\n"
            "2. Введите начальную дату\n"
            "3. Введите конечную дату\n\n"
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