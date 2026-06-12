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
class SelectClubState(StatesGroup):
    waiting_club_id = State()
    waiting_period_type = State()
    waiting_custom_date_from = State()
    waiting_custom_date_to = State()

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
        logger.info(f"Запрос: {url}, параметры: {params}")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, params=params, timeout=90) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        logger.info(f"Ответ: статус={result.get('status')}, data_len={len(result.get('data', []))}")
                        return result
                    else:
                        logger.error(f"HTTP ошибка: {resp.status}")
                        return {"status": False, "error": f"HTTP {resp.status}"}
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            return {"status": False, "error": str(e)}
    
    async def get_clubs(self) -> Dict:
        return await self._request("/clubs/list")
    
    async def get_balances_list(self, date_from: str, date_to: str, club_id: int = None, page: int = 1, limit: int = 2000) -> Dict:
        params = {"date_from": date_from, "date_to": date_to, "page": page, "page_limit": limit}
        if club_id:
            params["club_id"] = club_id
        logger.info(f"Запрос balances: club_id={club_id}, date_from={date_from}, date_to={date_to}")
        result = await self._request("/balances/list", params=params)
        if result.get("status"):
            logger.info(f"Balances: получено {len(result.get('data', []))} записей")
        else:
            logger.warning(f"Balances ошибка: {result.get('error')}")
        return result
    
    async def get_products_expense(self, date_from: str = None, date_to: str = None, club_id: int = None, page: int = 1, limit: int = 2000) -> Dict:
        params = {"page": page, "page_limit": limit}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        if club_id:
            params["club_id"] = club_id
        result = await self._request("/products/expense", params=params)
        if result.get("status"):
            logger.info(f"Products: получено {len(result.get('data', []))} записей")
        else:
            logger.warning(f"Products ошибка: {result.get('error')}")
        return result

api = LangameAPI(API_KEY if API_KEY else "")

# ========== КЛАВИАТУРЫ ==========
def get_main_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="🏢 Выбрать клуб и период")],
        [KeyboardButton(text="🍔 Топ товаров")],
        [KeyboardButton(text="🏢 Список клубов"), KeyboardButton(text="🔌 Проверить API")],
        [KeyboardButton(text="ℹ️ О боте")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_period_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Сегодня", callback_data="period_today")],
        [InlineKeyboardButton(text="📈 Вчера", callback_data="period_yesterday")],
        [InlineKeyboardButton(text="📅 Неделя (7 дней)", callback_data="period_week")],
        [InlineKeyboardButton(text="📆 Месяц (30 дней)", callback_data="period_month")],
        [InlineKeyboardButton(text="🎯 Свой период", callback_data="period_custom")]
    ])

# ========== ФОРМАТИРОВАНИЕ ==========
def format_stats_message(stats: Dict, title: str) -> str:
    """Форматирование статистики"""
    date_from = stats['period_from']
    date_to = stats['period_to']
    
    if date_from.date() == date_to.date():
        period_str = date_from.strftime('%d.%m.%Y')
    else:
        period_str = f"{date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}"
    
    club_info = f"Клуб ID: {stats['club_id']}" if stats['club_id'] else "Все клубы"
    
    result = f"""📊 *{title}*

🏢 {club_info}
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
    
    # Отладочная информация
    result += f"\n📊 *Найдено записей:*\n• Пополнений: {stats['raw_balances']}\n• Продаж: {stats['raw_products']}"
    
    result += f"\n\n#отчет"
    return result

# ========== АНАЛИТИЧЕСКИЕ ФУНКЦИИ ==========
async def get_stats_for_period(date_from: datetime, date_to: datetime, club_id: int = None) -> Dict:
    """Получение статистики за период для конкретного клуба"""
    date_from_str = date_from.strftime("%Y-%m-%d")
    date_to_str = date_to.strftime("%Y-%m-%d")
    
    logger.info(f"=== НАЧАЛО СБОРА СТАТИСТИКИ ===")
    logger.info(f"Клуб ID: {club_id}, период: {date_from_str} - {date_to_str}")
    
    # Получаем данные
    balances = await api.get_balances_list(date_from_str, date_to_str, club_id=club_id, limit=2000)
    products = await api.get_products_expense(date_from_str, date_to_str, club_id=club_id, limit=2000)
    
    balances_data = balances.get("data", []) if balances.get("status") else []
    products_data = products.get("data", []) if products.get("status") else []
    
    logger.info(f"Balances data count: {len(balances_data)}")
    logger.info(f"Products data count: {len(products_data)}")
    
    # Если есть данные, выводим первые 2 для примера
    if balances_data:
        logger.info(f"Пример данных balances: {balances_data[0] if balances_data else 'нет'}")
    if products_data:
        logger.info(f"Пример данных products: {products_data[0] if products_data else 'нет'}")
    
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
    
    # Подсчет сессий (упрощенно)
    sessions_count = len(balances_data) // 2 if balances_data else 0
    
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
        "product_details": product_details,
        "club_id": club_id,
        "raw_balances": len(balances_data),
        "raw_products": len(products_data)
    }

# ========== ОБРАБОТЧИКИ ==========
@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "📊 *LANGAME АНАЛИТИКА*\n\n"
        "Бот для анализа финансовых показателей игрового клуба.\n\n"
        "📋 *Как использовать:*\n"
        "1. Нажмите «🏢 Список клубов» — узнайте ID\n"
        "2. Нажмите «🏢 Выбрать клуб и период»\n"
        "3. Введите ID клуба (или 0 для всех)\n"
        "4. Выберите период\n\n"
        "📊 *Данные берутся из:*\n"
        "• /balances/list — пополнения баланса\n"
        "• /products/expense — продажи товаров",
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
        "• Топ товаров с количеством\n\n"
        "📅 *Формат даты:* ГГГГ-ММ-ДД\n"
        "Пример: `2026-06-01`\n\n"
        "🔍 *Если данные не показываются:*\n"
        "• Проверьте ID клуба\n"
        "• Убедитесь, что в выбранный период были пополнения",
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
    
    if clubs.get("status"):
        clubs_data = clubs.get("data", [])
        result = "✅ *API РАБОТАЕТ!*\n\n"
        result += f"🏢 Доступно клубов: {len(clubs_data)}\n\n"
        result += "📋 *Для теста данных:*\n"
        result += "Нажмите «🏢 Выбрать клуб и период»\n"
        result += "Введите ID клуба и выберите «Свой период»\n"
        result += "Укажите даты, когда точно были пополнения"
        await message.answer(result, parse_mode="Markdown", reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ Ошибка: {clubs.get('error')}", reply_markup=get_main_keyboard())

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
        result += "\n💡 *Используйте ID клуба для анализа*"
        await message.answer(result, parse_mode="Markdown", reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {r.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

# ========== ВЫБОР КЛУБА И ПЕРИОДА ==========
@dp.message(F.text == "🏢 Выбрать клуб и период")
async def select_club(message: types.Message, state: FSMContext):
    await message.answer(
        "🏢 Введите *ID клуба* для анализа\n\n"
        "• Нажмите «🏢 Список клубов» чтобы узнать ID\n"
        "• Введите `0` для анализа по ВСЕМ клубам\n\n"
        "📌 *Пример:* `1`",
        parse_mode="Markdown"
    )
    await state.set_state(SelectClubState.waiting_club_id)

@dp.message(StateFilter(SelectClubState.waiting_club_id))
async def get_club_id(message: types.Message, state: FSMContext):
    try:
        club_id = int(message.text.strip())
        await state.update_data(club_id=club_id if club_id != 0 else None)
        
        await message.answer(
            "📅 *Выберите период анализа:*",
            parse_mode="Markdown",
            reply_markup=get_period_keyboard()
        )
        await state.set_state(SelectClubState.waiting_period_type)
    except ValueError:
        await message.answer("❌ Введите число (ID клуба)!")

# ========== ОБРАБОТКА ВЫБОРА ПЕРИОДА ==========
@dp.callback_query(StateFilter(SelectClubState.waiting_period_type))
async def handle_period_selection(callback: types.CallbackQuery, state: FSMContext):
    period_type = callback.data.replace("period_", "")
    data = await state.get_data()
    club_id = data.get("club_id")
    
    date_to = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    if period_type == "today":
        date_from = date_to
        title = "СТАТИСТИКА ЗА СЕГОДНЯ"
        await process_stats(callback.message, club_id, date_from, date_to, title, state)
    
    elif period_type == "yesterday":
        date_from = date_to - timedelta(days=1)
        date_to = date_from
        title = "СТАТИСТИКА ЗА ВЧЕРА"
        await process_stats(callback.message, club_id, date_from, date_to, title, state)
    
    elif period_type == "week":
        date_from = date_to - timedelta(days=6)
        title = "СТАТИСТИКА ЗА НЕДЕЛЮ"
        await process_stats(callback.message, club_id, date_from, date_to, title, state)
    
    elif period_type == "month":
        date_from = date_to - timedelta(days=29)
        title = "СТАТИСТИКА ЗА МЕСЯЦ"
        await process_stats(callback.message, club_id, date_from, date_to, title, state)
    
    elif period_type == "custom":
        await callback.message.answer(
            "📅 Введите *дату начала* в формате:\n\n"
            "`ГГГГ-ММ-ДД`\n\n"
            "📌 *Пример:* `2026-06-01`",
            parse_mode="Markdown"
        )
        await state.set_state(SelectClubState.waiting_custom_date_from)
        await callback.answer()
        return
    
    await callback.answer()

async def process_stats(message: types.Message, club_id: int, date_from: datetime, date_to: datetime, title: str, state: FSMContext):
    club_str = f"для клуба ID: {club_id}" if club_id else "для всех клубов"
    msg = await message.answer(f"📊 Сбор статистики {club_str} за {date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}...\n⏱️ Подождите...")
    
    stats = await get_stats_for_period(date_from, date_to, club_id)
    
    await msg.delete()
    await message.answer(format_stats_message(stats, title), parse_mode="Markdown", reply_markup=get_main_keyboard())
    
    await state.update_data(last_stats=stats)

# ========== СВОЙ ПЕРИОД ==========
@dp.message(StateFilter(SelectClubState.waiting_custom_date_from))
async def custom_date_from(message: types.Message, state: FSMContext):
    try:
        date_from = datetime.strptime(message.text.strip(), "%Y-%m-%d")
        await state.update_data(custom_date_from=date_from)
        await message.answer(
            "📅 Введите *дату окончания* в формате:\n\n"
            "`ГГГГ-ММ-ДД`\n\n"
            "📌 *Пример:* `2026-06-30`",
            parse_mode="Markdown"
        )
        await state.set_state(SelectClubState.waiting_custom_date_to)
    except ValueError:
        await message.answer("❌ Неверный формат! Используйте: `ГГГГ-ММ-ДД`", parse_mode="Markdown")

@dp.message(StateFilter(SelectClubState.waiting_custom_date_to))
async def custom_date_to(message: types.Message, state: FSMContext):
    try:
        date_to = datetime.strptime(message.text.strip(), "%Y-%m-%d")
        data = await state.get_data()
        date_from = data.get("custom_date_from")
        club_id = data.get("club_id")
        
        if date_from > date_to:
            await message.answer("❌ Дата начала не может быть позже даты окончания!")
            return
        
        # Добавляем время для корректного диапазона
        date_from = date_from.replace(hour=0, minute=0)
        date_to = date_to.replace(hour=23, minute=59)
        
        club_str = f"для клуба ID: {club_id}" if club_id else "для всех клубов"
        msg = await message.answer(f"📊 Сбор статистики {club_str} за {date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}...\n⏱️ Подождите...")
        
        stats = await get_stats_for_period(date_from, date_to, club_id)
        
        await msg.delete()
        await message.answer(format_stats_message(stats, "СТАТИСТИКА ЗА ПЕРИОД"), parse_mode="Markdown", reply_markup=get_main_keyboard())
        
        await state.update_data(last_stats=stats)
        
    except ValueError:
        await message.answer("❌ Неверный формат! Используйте: `ГГГГ-ММ-ДД`", parse_mode="Markdown")
    
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
    await state.set_state(SelectClubState.waiting_club_id)
    await state.update_data(mode="products")

# ========== ОСТАЛЬНЫЕ ОБРАБОТЧИКИ ==========
@dp.message()
async def unknown(message: types.Message):
    if not message.text.startswith("/"):
        await message.answer(
            "❓ Используйте кнопки меню\n\n"
            "📊 *Как получить отчет:*\n"
            "1. Нажмите «🏢 Список клубов» — узнайте ID\n"
            "2. Нажмите «🏢 Выбрать клуб и период»\n"
            "3. Введите ID клуба (или 0 для всех)\n"
            "4. Выберите период\n\n"
            "🍔 *Топ товаров* — отдельный отчет",
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