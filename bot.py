import os
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from dotenv import load_dotenv

load_dotenv()

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_KEY = os.getenv("LANGAME_API_KEY")  # Ваш X-Request-Token
API_BASE_URL = "https://cyberx302.langame.ru/public_api"

if not BOT_TOKEN or not API_KEY:
    raise ValueError("Укажите BOT_TOKEN и LANGAME_API_KEY в .env файле!")

# ========== СОСТОЯНИЯ ДЛЯ FSM ==========
class BookingState(StatesGroup):
    waiting_for_club_id = State()
    waiting_for_guest_phone = State()
    waiting_for_amount = State()

class DateFilterState(StatesGroup):
    waiting_date_from = State()
    waiting_date_to = State()

# ========== ИНИЦИАЛИЗАЦИЯ БОТА ==========
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
async def api_request(endpoint: str, method: str = "GET", data: Dict = None) -> Dict:
    """Универсальная функция для запросов к API"""
    url = f"{API_BASE_URL}{endpoint}"
    headers = {
        "X-Request-Token": API_KEY,
        "Content-Type": "application/json"
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            if method.upper() == "GET":
                async with session.get(url, headers=headers, params=data) as resp:
                    return await resp.json()
            else:
                async with session.post(url, headers=headers, json=data) as resp:
                    return await resp.json()
        except Exception as e:
            return {"status": False, "error": str(e)}

def format_balance(data: Dict) -> str:
    """Форматирование баланса для вывода"""
    if not data.get("status"):
        return "❌ Ошибка получения данных"
    
    items = data.get("data", [])
    if not items:
        return "📭 Данные не найдены"
    
    result = "💰 *Балансы гостей*\n\n"
    for item in items[:10]:  # Показываем первые 10
        result += f"• Гость #{item['guest_id']}: {item.get('balance', 0)} ₽\n"
    
    if len(items) > 10:
        result += f"\n📊 Всего: {len(items)} записей"
    
    return result

def format_clubs(data: Dict) -> str:
    """Форматирование списка клубов"""
    if not data.get("status"):
        return "❌ Ошибка получения списка клубов"
    
    clubs = data.get("data", [])
    if not clubs:
        return "🏢 Клубы не найдены"
    
    result = "🏢 *Список клубов*\n\n"
    for club in clubs:
        status_icon = "🟢" if club.get("active") else "🔴"
        result += f"{status_icon} *{club['name']}* (ID: {club['id']})\n"
        if club.get("address"):
            result += f"   📍 {club['address']}\n"
        result += "\n"
    
    return result

def format_transactions(data: Dict) -> str:
    """Форматирование транзакций"""
    if not data.get("status"):
        return "❌ Ошибка получения транзакций"
    
    transactions = data.get("data", [])
    if not transactions:
        return "📭 Транзакции не найдены"
    
    result = "💸 *Последние транзакции*\n\n"
    for tx in transactions[:10]:
        result += f"📅 {tx.get('date_update', 'N/A')}\n"
        result += f"💰 Сумма: {tx.get('balance', 0)} ₽\n"
        if tx.get('comment'):
            result += f"📝 {tx['comment']}\n"
        result += "─" * 20 + "\n"
    
    return result

# ========== КЛАВИАТУРЫ ==========
def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Главная клавиатура"""
    buttons = [
        [KeyboardButton(text="🏢 Клубы")],
        [KeyboardButton(text="💰 Балансы"), KeyboardButton(text="💸 Транзакции")],
        [KeyboardButton(text="👤 Поиск гостя"), KeyboardButton(text="🎮 Сессии")],
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="❓ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_back_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура с кнопкой назад"""
    buttons = [[KeyboardButton(text="◀️ Назад")]]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# ========== ОБРАБОТЧИКИ КОМАНД ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Обработчик команды /start"""
    welcome_text = """
🎮 *Добро пожаловать в LANGAME бот!*

Я помогу вам управлять вашим игровым клубом через API LANGAME.

📋 *Доступные функции:*
• 🏢 Просмотр списка клубов
• 💰 Проверка балансов гостей
• 💸 История транзакций
• 👤 Поиск информации о гостях
• 🎮 История игровых сессий
• 📊 Финансовая статистика

🔐 *Важно:* Все данные защищены API-ключом.

Используйте кнопки ниже для навигации 👇
"""
    await message.answer(welcome_text, parse_mode="Markdown", reply_markup=get_main_keyboard())

@dp.message(Command("help"))
@dp.message(F.text == "❓ Помощь")
async def cmd_help(message: types.Message):
    """Помощь"""
    help_text = """
❓ *Справка по командам*

🏢 *Клубы* - Просмотр всех клубов и их статуса
💰 *Балансы* - Текущие балансы гостей
💸 *Транзакции* - История финансовых операций
👤 *Поиск гостя* - Поиск гостя по телефону или ID
🎮 *Сессии* - История игровых сессий
📊 *Статистика* - Финансовая статистика за период

💡 *Совет:* Вы можете указать даты для фильтрации там, где это поддерживается.

🆘 При проблемах обратитесь к администратору.
"""
    await message.answer(help_text, parse_mode="Markdown", reply_markup=get_main_keyboard())

@dp.message(F.text == "🏢 Клубы")
async def show_clubs(message: types.Message):
    """Показать список клубов"""
    await message.answer("🔄 Загружаю список клубов...", reply_markup=get_back_keyboard())
    
    response = await api_request("/v1/clubs/list")
    result = format_clubs(response)
    
    await message.answer(result, parse_mode="Markdown")

@dp.message(F.text == "💰 Балансы")
async def show_balances(message: types.Message):
    """Показать балансы гостей"""
    await message.answer("🔄 Загружаю балансы гостей...", reply_markup=get_back_keyboard())
    
    response = await api_request("/v1/guests/balance", data={"page": 1, "page_limit": 20})
    result = format_balance(response)
    
    await message.answer(result, parse_mode="Markdown")

@dp.message(F.text == "💸 Транзакции")
async def show_transactions(message: types.Message):
    """Показать транзакции"""
    await message.answer("🔄 Загружаю последние транзакции...", reply_markup=get_back_keyboard())
    
    # За последние 7 дней
    date_to = datetime.now().strftime("%Y-%m-%d")
    date_from = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    
    response = await api_request(
        "/v1/transactions/list",
        data={"page": 1, "page_limit": 20, "date_from": date_from, "date_to": date_to}
    )
    result = format_transactions(response)
    
    await message.answer(result, parse_mode="Markdown")

@dp.message(F.text == "👤 Поиск гостя")
async def search_guest_prompt(message: types.Message, state: FSMContext):
    """Запрос данных для поиска гостя"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Поиск по телефону", callback_data="search_by_phone")],
            [InlineKeyboardButton(text="🆔 Поиск по ID", callback_data="search_by_id")],
            [InlineKeyboardButton(text="📝 Поиск по имени", callback_data="search_by_name")]
        ]
    )
    await message.answer(
        "🔍 *Выберите способ поиска гостя:*\n\n"
        "Вы можете найти гостя по:\n"
        "• 📱 Номеру телефона\n"
        "• 🆔 ID гостя\n"
        "• 📝 ФИО (частичное совпадение)",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

@dp.callback_query(lambda c: c.data.startswith("search_by_"))
async def process_search_type(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора типа поиска"""
    search_type = callback.data.replace("search_by_", "")
    
    prompts = {
        "phone": "📱 Введите номер телефона гостя (например: 9001234567)",
        "id": "🆔 Введите ID гостя",
        "name": "📝 Введите ФИО гостя (или часть)"
    }
    
    await state.update_data(search_type=search_type)
    await state.set_state(BookingState.waiting_for_guest_phone)
    await callback.message.edit_text(prompts[search_type])
    await callback.answer()

@dp.message(StateFilter(BookingState.waiting_for_guest_phone))
async def perform_search(message: types.Message, state: FSMContext):
    """Выполнение поиска гостя"""
    data = await state.get_data()
    search_type = data.get("search_type")
    query = message.text.strip()
    
    await message.answer("🔍 Ищу гостя...")
    
    # Формируем запрос в зависимости от типа поиска
    search_data = {
        "pagination": {"page": 1, "size": 10},
        "featues": {"fields": ["guest_id", "fio", "phone"], "balance": True, "bonus_balance": True}
    }
    
    if search_type == "phone":
        search_data["filter"] = {"phone": query}
    elif search_type == "id" and query.isdigit():
        search_data["filter"] = {"ids": [int(query)]}
    elif search_type == "name":
        search_data["filter"] = {"query": query}
    else:
        await message.answer("❌ Неверный формат данных для поиска")
        await state.clear()
        return
    
    response = await api_request("/v1/guests/search", method="POST", data=search_data)
    
    if response.get("status") and response.get("items"):
        guests = response["items"]
        result = "👤 *Результаты поиска*\n\n"
        
        for guest in guests[:5]:
            result += f"🆔 ID: {guest.get('guest_id')}\n"
            result += f"📝 ФИО: {guest.get('fio', 'Не указано')}\n"
            result += f"📱 Телефон: {guest.get('phone', 'Не указан')}\n"
            
            if guest.get("balance"):
                result += f"💰 Баланс: {guest['balance'].get('amount', 0)} ₽\n"
            if guest.get("bonus_balance"):
                result += f"🎁 Бонусы: {guest['bonus_balance'].get('amount', 0)}\n"
            result += "─" * 20 + "\n"
        
        await message.answer(result, parse_mode="Markdown")
    else:
        await message.answer("❌ Гость не найден. Проверьте правильность введенных данных.")
    
    await state.clear()
    await message.answer("Выберите действие:", reply_markup=get_main_keyboard())

@dp.message(F.text == "🎮 Сессии")
async def show_sessions_prompt(message: types.Message):
    """Запрос ID гостя для просмотра сессий"""
    await message.answer(
        "🎮 *История игровых сессий*\n\n"
        "Введите ID гостя, чтобы посмотреть его игровые сессии:",
        parse_mode="Markdown",
        reply_markup=get_back_keyboard()
    )
    await BookingState.waiting_for_club_id.set()

@dp.message(StateFilter(BookingState.waiting_for_club_id))
async def show_sessions(message: types.Message, state: FSMContext):
    """Показать сессии гостя"""
    guest_id = message.text.strip()
    
    if not guest_id.isdigit():
        await message.answer("❌ ID должен быть числом. Попробуйте еще раз:")
        return
    
    await message.answer(f"🔄 Загружаю сессии для гостя #{guest_id}...")
    
    response = await api_request(
        "/v1/guests/sessions",
        data={"guest_id": int(guest_id), "page": 1, "page_limit": 10}
    )
    
    if response.get("status") and response.get("data"):
        sessions = response["data"]
        result = f"🎮 *Сессии гостя #{guest_id}*\n\n"
        
        for session in sessions:
            date_start = session.get("date_start", "N/A")
            date_stop = session.get("date_stop", "Активна")
            status = "✅ Завершена" if session.get("normal_stop") else "🟢 Активна"
            
            result += f"📅 {date_start}\n"
            result += f"⏱️ Окончание: {date_stop}\n"
            result += f"📊 Статус: {status}\n"
            result += "─" * 20 + "\n"
        
        await message.answer(result, parse_mode="Markdown")
    else:
        await message.answer(f"❌ Сессии для гостя #{guest_id} не найдены")
    
    await state.clear()
    await message.answer("Выберите действие:", reply_markup=get_main_keyboard())

@dp.message(F.text == "📊 Статистика")
async def show_stats(message: types.Message):
    """Показать статистику"""
    today = datetime.now()
    week_ago = today - timedelta(days=7)
    
    stats_text = """
📊 *Финансовая статистика*

⌛ *Загрузка данных...*
Это может занять несколько секунд.
"""
    msg = await message.answer(stats_text, parse_mode="Markdown")
    
    # Получаем транзакции за неделю
    transactions = await api_request(
        "/v1/transactions/list",
        data={"date_from": week_ago.strftime("%Y-%m-%d"), "date_to": today.strftime("%Y-%m-%d")}
    )
    
    if transactions.get("status") and transactions.get("data"):
        total_sum = sum(tx.get("balance", 0) for tx in transactions["data"] if tx.get("balance", 0) > 0)
        
        result = f"""
📊 *Финансовая статистика*

📅 *Период:* {week_ago.strftime('%d.%m.%Y')} - {today.strftime('%d.%m.%Y')}

💰 *Общая выручка:* {total_sum:,.2f} ₽
📝 *Количество операций:* {len(transactions['data'])} шт.

📈 *Динамика:*
• Средний чек: {total_sum / len(transactions['data']) if transactions['data'] else 0:.2f} ₽
"""
        await msg.edit_text(result, parse_mode="Markdown")
    else:
        await msg.edit_text("❌ Нет данных для отображения статистики")

@dp.message(F.text == "◀️ Назад")
async def back_to_main(message: types.Message, state: FSMContext):
    """Вернуться в главное меню"""
    await state.clear()
    await message.answer("🏠 Возвращаемся в главное меню", reply_markup=get_main_keyboard())

@dp.message()
async def handle_unknown(message: types.Message):
    """Обработка неизвестных сообщений"""
    await message.answer(
        "❓ Неизвестная команда.\n"
        "Используйте кнопки меню или введите /help",
        reply_markup=get_main_keyboard()
    )

# ========== ЗАПУСК БОТА ==========
async def main():
    """Запуск бота"""
    print("🤖 Бот запускается...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())