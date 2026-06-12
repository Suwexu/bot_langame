import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict

import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_KEY = os.getenv("LANGAME_API_KEY")
API_BASE_URL = "https://cyberx302.langame.ru/public_api"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не указан!")

if not API_KEY:
    logger.warning("LANGAME_API_KEY не указан!")

# ========== СОСТОЯНИЯ ==========
class GuestSearchState(StatesGroup):
    waiting_for_search_input = State()

class SessionsState(StatesGroup):
    waiting_for_guest_id = State()

# ========== ИНИЦИАЛИЗАЦИЯ ==========
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ========== API КЛИЕНТ ==========
class LangameAPI:
    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {
            "X-Request-Token": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
    
    async def request(self, endpoint: str, method: str = "GET", data: Dict = None) -> Dict:
        url = f"{self.base_url}{endpoint}"
        
        async with aiohttp.ClientSession() as session:
            try:
                if method.upper() == "GET":
                    async with session.get(url, headers=self.headers, params=data, timeout=30) as resp:
                        return await resp.json()
                else:
                    async with session.post(url, headers=self.headers, json=data, timeout=30) as resp:
                        return await resp.json()
            except Exception as e:
                logger.error(f"API error: {e}")
                return {"status": False, "error": str(e)}
    
    async def get_clubs(self) -> Dict:
        return await self.request("/v1/clubs/list")
    
    async def get_balances(self, page: int = 1, limit: int = 20) -> Dict:
        return await self.request("/v1/guests/balance", data={"page": page, "page_limit": limit})
    
    async def get_transactions(self, date_from: str, date_to: str, page: int = 1, limit: int = 20) -> Dict:
        return await self.request(
            "/v1/transactions/list",
            data={"page": page, "page_limit": limit, "date_from": date_from, "date_to": date_to}
        )
    
    async def search_guest(self, search_data: Dict) -> Dict:
        return await self.request("/v1/guests/search", method="POST", data=search_data)
    
    async def get_guest_sessions(self, guest_id: int, page: int = 1, limit: int = 10) -> Dict:
        return await self.request(
            "/v1/guests/sessions",
            data={"guest_id": guest_id, "page": page, "page_limit": limit}
        )

api = LangameAPI(API_KEY, API_BASE_URL)

# ========== КЛАВИАТУРЫ ==========
def get_main_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="🏢 Клубы")],
        [KeyboardButton(text="💰 Балансы"), KeyboardButton(text="💸 Транзакции")],
        [KeyboardButton(text="👤 Поиск гостя"), KeyboardButton(text="🎮 Сессии")],
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="ℹ️ О боте")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_back_keyboard() -> ReplyKeyboardMarkup:
    buttons = [[KeyboardButton(text="◀️ Назад")]]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_search_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="По телефону", callback_data="search_phone")],
            [InlineKeyboardButton(text="По ID", callback_data="search_id")],
            [InlineKeyboardButton(text="По ФИО", callback_data="search_name")]
        ]
    )

# ========== ФОРМАТТЕРЫ (без Markdown) ==========
def format_clubs(data: Dict) -> str:
    if not data.get("status"):
        return "❌ Ошибка получения списка клубов"
    
    clubs = data.get("data", [])
    if not clubs:
        return "🏢 Клубы не найдены"
    
    result = "🏢 СПИСОК КЛУБОВ\n\n"
    for club in clubs[:15]:
        status_icon = "🟢" if club.get("active") else "🔴"
        result += f"{status_icon} {club.get('name', 'Без названия')} (ID: {club.get('id')})\n"
        if club.get("address"):
            result += f"   📍 {club.get('address')}\n"
        result += "\n"
    
    return result

def format_balances(data: Dict) -> str:
    if not data.get("status"):
        return "❌ Ошибка получения балансов.\n\nВозможные причины:\n• Неверный API ключ\n• Нет доступа к ресурсу"
    
    balances = data.get("data", [])
    if not balances:
        return "📭 Балансы не найдены"
    
    result = "💰 БАЛАНСЫ ГОСТЕЙ\n\n"
    total = 0
    for item in balances[:15]:
        balance = float(item.get('balance', 0))
        total += balance
        result += f"• Гостя #{item.get('guest_id')}: {balance:,.2f} ₽\n"
    
    result += f"\n💰 Общая сумма: {total:,.2f} ₽"
    return result

def format_transactions(data: Dict) -> str:
    if not data.get("status"):
        return "❌ Ошибка получения транзакций"
    
    transactions = data.get("data", [])
    if not transactions:
        return "📭 Транзакции не найдены"
    
    result = "💸 ПОСЛЕДНИЕ ТРАНЗАКЦИИ\n\n"
    total = 0
    for tx in transactions[:10]:
        date = tx.get('date_update', 'N/A')[:16]
        amount = float(tx.get('balance', 0))
        if amount > 0:
            total += amount
        sign = "+" if amount > 0 else ""
        result += f"📅 {date}\n"
        result += f"💰 {sign}{amount:,.2f} ₽\n"
        if tx.get('comment'):
            comment = tx.get('comment')[:50]
            result += f"📝 {comment}\n"
        result += "─" * 25 + "\n"
    
    result += f"\n💰 Общая сумма пополнений: {total:,.2f} ₽"
    return result

# ========== ОБРАБОТЧИКИ ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    welcome_text = """🎮 ДОБРО ПОЖАЛОВАТЬ В LANGAME БОТ!

Я помогаю управлять игровым клубом через API LANGAME.

📋 Доступные функции:
• 🏢 Список клубов
• 💰 Балансы гостей
• 💸 История транзакций
• 👤 Поиск гостей
• 🎮 Игровые сессии
• 📊 Финансовая статистика

Используйте кнопки ниже 👇"""
    
    await message.answer(welcome_text, reply_markup=get_main_keyboard())
    logger.info(f"User {message.from_user.id} started")

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    help_text = """❓ ПОМОЩЬ

🏢 Клубы - Список всех клубов
💰 Балансы - Денежные балансы гостей
💸 Транзакции - История операций за 7 дней
👤 Поиск гостя - Поиск по телефону/ID/ФИО
🎮 Сессии - История игровых сессий
📊 Статистика - Финансовая аналитика

🔧 Настройка API ключа:
1. Зайдите в настройки Railway
2. Добавьте переменную LANGAME_API_KEY
3. Перезапустите бота"""
    
    await message.answer(help_text)

@dp.message(F.text == "◀️ Назад")
async def back_to_main(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("🏠 Главное меню", reply_markup=get_main_keyboard())

@dp.message(F.text == "ℹ️ О боте")
async def about_bot(message: types.Message):
    api_status = "✅ Настроен" if API_KEY else "❌ Не настроен"
    
    about_text = f"""🤖 О БОТЕ LANGAME

Версия: 1.1.0
Платформа: Railway

📌 Статус API: {api_status}

🔧 API настройки:
URL: {API_BASE_URL}
Ключ: {api_status}

💡 Если функции не работают:
1. Проверьте LANGAME_API_KEY в Railway
2. Убедитесь, что ключ имеет доступ к API
3. Перезапустите бота после добавления ключа"""
    
    await message.answer(about_text)
    
    if not API_KEY:
        await message.answer("⚠️ ВНИМАНИЕ! API ключ LANGAME не настроен.\n\nПожалуйста, добавьте переменную LANGAME_API_KEY в настройках Railway для работы всех функций.")

@dp.message(F.text == "🏢 Клубы")
async def show_clubs(message: types.Message):
    msg = await message.answer("🔄 Загрузка списка клубов...", reply_markup=get_back_keyboard())
    
    response = await api.get_clubs()
    result = format_clubs(response)
    
    await msg.edit_text(result)

@dp.message(F.text == "💰 Балансы")
async def show_balances(message: types.Message):
    msg = await message.answer("🔄 Загрузка балансов гостей...", reply_markup=get_back_keyboard())
    
    if not API_KEY:
        await msg.edit_text("❌ API ключ не настроен!\n\nДобавьте переменную LANGAME_API_KEY в настройках Railway и перезапустите бота.")
        return
    
    response = await api.get_balances()
    result = format_balances(response)
    
    await msg.edit_text(result)

@dp.message(F.text == "💸 Транзакции")
async def show_transactions(message: types.Message):
    msg = await message.answer("🔄 Загрузка транзакций за 7 дней...", reply_markup=get_back_keyboard())
    
    if not API_KEY:
        await msg.edit_text("❌ API ключ не настроен!\n\nДобавьте переменную LANGAME_API_KEY в настройках Railway и перезапустите бота.")
        return
    
    date_to = datetime.now().strftime("%Y-%m-%d")
    date_from = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    
    response = await api.get_transactions(date_from, date_to)
    result = format_transactions(response)
    
    await msg.edit_text(result)

@dp.message(F.text == "👤 Поиск гостя")
async def search_guest_prompt(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!\n\nДобавьте переменную LANGAME_API_KEY в настройках Railway и перезапустите бота.")
        return
    
    await message.answer(
        "🔍 ПОИСК ГОСТЯ\n\nВыберите способ поиска:",
        reply_markup=get_search_keyboard()
    )

@dp.callback_query(lambda c: c.data.startswith("search_"))
async def process_search_type(callback: types.CallbackQuery, state: FSMContext):
    search_type = callback.data.replace("search_", "")
    
    prompts = {
        "phone": "📱 Введите номер телефона (например: 9001234567)",
        "id": "🆔 Введите ID гостя (число)",
        "name": "📝 Введите ФИО гостя (можно часть)"
    }
    
    await state.update_data(search_type=search_type)
    await state.set_state(GuestSearchState.waiting_for_search_input)
    await callback.message.edit_text(prompts[search_type])
    await callback.answer()

@dp.message(StateFilter(GuestSearchState.waiting_for_search_input))
async def perform_search(message: types.Message, state: FSMContext):
    data = await state.get_data()
    search_type = data.get("search_type")
    query = message.text.strip()
    
    msg = await message.answer("🔍 Поиск...")
    
    search_payload = {
        "pagination": {"page": 1, "size": 10},
        "featues": {"fields": ["guest_id", "fio", "phone"], "balance": True, "bonus_balance": True}
    }
    
    if search_type == "phone":
        search_payload["filter"] = {"phone": query}
    elif search_type == "id" and query.isdigit():
        search_payload["filter"] = {"ids": [int(query)]}
    elif search_type == "name":
        search_payload["filter"] = {"query": query}
    else:
        await msg.edit_text("❌ Неверный формат. Попробуйте снова /start")
        await state.clear()
        return
    
    response = await api.search_guest(search_payload)
    
    if response.get("items"):
        guests = response["items"]
        result = "👤 РЕЗУЛЬТАТЫ ПОИСКА\n\n"
        
        for guest in guests[:5]:
            result += f"🆔 ID: {guest.get('guest_id')}\n"
            result += f"📝 ФИО: {guest.get('fio', 'Не указано')}\n"
            result += f"📱 Телефон: {guest.get('phone', 'Не указан')}\n"
            
            if guest.get("balance"):
                result += f"💰 Баланс: {guest['balance'].get('amount', 0):,.2f} ₽\n"
            if guest.get("bonus_balance"):
                result += f"🎁 Бонусы: {guest['bonus_balance'].get('amount', 0)}\n"
            result += "─" * 25 + "\n"
        
        await msg.edit_text(result)
    else:
        await msg.edit_text("❌ Гость не найден. Проверьте правильность данных.")
    
    await state.clear()

@dp.message(F.text == "🎮 Сессии")
async def sessions_prompt(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!\n\nДобавьте переменную LANGAME_API_KEY в настройках Railway и перезапустите бота.")
        return
    
    await message.answer(
        "🎮 ИСТОРИЯ СЕССИЙ\n\nВведите ID гостя:",
        reply_markup=get_back_keyboard()
    )
    await SessionsState.waiting_for_guest_id.set()

@dp.message(StateFilter(SessionsState.waiting_for_guest_id))
async def show_sessions(message: types.Message, state: FSMContext):
    guest_id = message.text.strip()
    
    if not guest_id.isdigit():
        await message.answer("❌ ID должен быть числом")
        return
    
    msg = await message.answer(f"🔄 Загрузка сессий для гостя #{guest_id}...")
    
    response = await api.get_guest_sessions(int(guest_id))
    
    if response.get("status") and response.get("data"):
        sessions = response["data"]
        if sessions:
            result = f"🎮 СЕССИИ ГОСТЯ #{guest_id}\n\n"
            
            for session in sessions[:10]:
                date_start = session.get("date_start", "N/A")[:16] if session.get("date_start") else "N/A"
                date_stop = session.get("date_stop", "Активна")[:16] if session.get("date_stop") else "Активна"
                status = "Завершена" if session.get("normal_stop") else "Активна"
                
                result += f"📅 {date_start}\n"
                result += f"⏱️ Окончание: {date_stop}\n"
                result += f"📊 Статус: {status}\n"
                result += "─" * 25 + "\n"
            
            await msg.edit_text(result)
        else:
            await msg.edit_text(f"📭 Сессии для гостя #{guest_id} не найдены")
    else:
        await msg.edit_text(f"❌ Ошибка: {response.get('error', 'Не удалось получить сессии')}")
    
    await state.clear()

@dp.message(F.text == "📊 Статистика")
async def show_stats(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!\n\nДобавьте переменную LANGAME_API_KEY в настройках Railway и перезапустите бота.")
        return
    
    msg = await message.answer("📊 Сбор статистики за 30 дней...")
    
    date_to = datetime.now().strftime("%Y-%m-%d")
    date_from = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    
    response = await api.get_transactions(date_from, date_to)
    
    if response.get("status") and response.get("data"):
        transactions = response["data"]
        total_sum = sum(float(tx.get("balance", 0)) for tx in transactions if float(tx.get("balance", 0)) > 0)
        total_count = len([tx for tx in transactions if float(tx.get("balance", 0)) > 0])
        
        result = f"""📊 ФИНАНСОВАЯ СТАТИСТИКА

📅 Период: {date_from} - {date_to}

💰 Общая выручка: {total_sum:,.2f} ₽
📝 Количество операций: {total_count} шт.

📈 Средний чек: {total_sum / total_count if total_count > 0 else 0:.2f} ₽"""
        
        await msg.edit_text(result)
    else:
        await msg.edit_text(f"❌ Ошибка получения статистики")

@dp.message()
async def handle_unknown(message: types.Message):
    if not message.text.startswith("/"):
        await message.answer(
            "❓ Используйте кнопки меню или команду /help",
            reply_markup=get_main_keyboard()
        )

# ========== ЗАПУСК ==========
async def main():
    logger.info("🚀 Бот запускается...")
    logger.info(f"API Key: {'Есть' if API_KEY else 'Нет'}")
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())