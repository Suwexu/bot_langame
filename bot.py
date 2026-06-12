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

load_dotenv()

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_KEY = os.getenv("LANGAME_API_KEY")
API_BASE_URL = "https://cyberx302.langame.ru/public_api"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не указан!")

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
        self.connection_status = None
        self.last_error = None
    
    async def test_connection(self) -> Dict:
        """Тестирование подключения к API"""
        logger.info("Testing API connection...")
        
        # Проверка API ключа
        if not self.api_key or self.api_key == "MISSING_API_KEY":
            self.connection_status = False
            self.last_error = "API key is missing"
            return {"success": False, "error": "API ключ не настроен"}
        
        # Пробуем получить список клубов (этот эндпоинт точно есть в спецификации)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/v1/clubs/list",
                    headers=self.headers,
                    timeout=10
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("status"):
                            self.connection_status = True
                            clubs_count = len(data.get("data", []))
                            return {"success": True, "data": data, "clubs_count": clubs_count}
                        else:
                            self.connection_status = False
                            self.last_error = data.get("detail", "Unknown API error")
                            return {"success": False, "error": self.last_error}
                    elif resp.status == 403:
                        self.connection_status = False
                        self.last_error = "Invalid API key (403 Forbidden)"
                        return {"success": False, "error": "Неверный API ключ или нет доступа"}
                    else:
                        self.connection_status = False
                        self.last_error = f"HTTP {resp.status}"
                        return {"success": False, "error": f"Ошибка HTTP {resp.status}"}
        except Exception as e:
            self.connection_status = False
            self.last_error = str(e)
            return {"success": False, "error": str(e)}
    
    async def request(self, endpoint: str, method: str = "GET", data: Dict = None) -> Dict:
        """Выполнение запроса к API"""
        # Формируем правильный URL
        # Для эндпоинтов, которые уже начинаются с /v1, не добавляем лишний v1
        if endpoint.startswith("/v1/"):
            url = f"{self.base_url}{endpoint}"
        else:
            url = f"{self.base_url}/v1{endpoint}"
        
        logger.info(f"API Request: {method} {url}")
        
        async with aiohttp.ClientSession() as session:
            try:
                if method.upper() == "GET":
                    async with session.get(url, headers=self.headers, params=data, timeout=30) as resp:
                        logger.info(f"Response status: {resp.status}")
                        if resp.status == 200:
                            result = await resp.json()
                            return result
                        else:
                            return {"status": False, "error": f"HTTP {resp.status}", "http_status": resp.status}
                else:
                    async with session.post(url, headers=self.headers, json=data, timeout=30) as resp:
                        logger.info(f"Response status: {resp.status}")
                        if resp.status == 200:
                            return await resp.json()
                        else:
                            return {"status": False, "error": f"HTTP {resp.status}", "http_status": resp.status}
            except asyncio.TimeoutError:
                logger.error(f"Timeout on {endpoint}")
                return {"status": False, "error": "Request timeout"}
            except Exception as e:
                logger.error(f"API error: {e}")
                return {"status": False, "error": str(e)}
    
    async def get_clubs(self) -> Dict:
        """Получить список клубов"""
        return await self.request("/v1/clubs/list")
    
    async def get_balances(self, page: int = 1, limit: int = 20) -> Dict:
        """Получить балансы гостей"""
        return await self.request("/v1/guests/balance", data={"page": page, "page_limit": limit})
    
    async def get_transactions(self, date_from: str, date_to: str, page: int = 1, limit: int = 20) -> Dict:
        """Получить транзакции"""
        return await self.request(
            "/v1/transactions/list",
            data={"page": page, "page_limit": limit, "date_from": date_from, "date_to": date_to}
        )
    
    async def search_guest(self, search_data: Dict) -> Dict:
        """Поиск гостя"""
        return await self.request("/v1/guests/search", method="POST", data=search_data)
    
    async def get_guest_sessions(self, guest_id: int, page: int = 1, limit: int = 10) -> Dict:
        """Получить сессии гостя"""
        return await self.request(
            "/v1/guests/sessions",
            data={"guest_id": guest_id, "page": page, "page_limit": limit}
        )

# Создаем экземпляр API клиента
api = LangameAPI(API_KEY if API_KEY else "MISSING_API_KEY", API_BASE_URL)

# ========== КЛАВИАТУРЫ ==========
def get_main_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="🔌 Проверить API")],
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

# ========== ФОРМАТТЕРЫ ==========
def format_clubs(data: Dict) -> str:
    if not data.get("status"):
        error = data.get("error", "Unknown error")
        http_status = data.get("http_status", "")
        return f"❌ Ошибка API: {error}\n\n{http_status and f'HTTP Status: {http_status}' or ''}"
    
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
    
    if len(clubs) > 15:
        result += f"\n📊 Всего клубов: {len(clubs)} (показано 15)"
    else:
        result += f"\n📊 Всего клубов: {len(clubs)}"
    
    return result

def format_balances(data: Dict) -> str:
    if not data.get("status"):
        error = data.get("error", "Unknown error")
        if "403" in str(data.get("http_status", "")):
            return "❌ ОШИБКА АВТОРИЗАЦИИ\n\nПроверьте API ключ LANGAME_API_KEY в настройках Railway.\n\nВозможно, ключ неверный или у него нет доступа к этому методу."
        return f"❌ Ошибка API: {error}"
    
    balances = data.get("data", [])
    if not balances:
        return "📭 Балансы не найдены"
    
    result = "💰 БАЛАНСЫ ГОСТЕЙ\n\n"
    total = 0
    for item in balances[:15]:
        balance = float(item.get('balance', 0))
        total += balance
        result += f"• Гость #{item.get('guest_id')}: {balance:,.2f} ₽\n"
    
    if len(balances) > 15:
        result += f"\n📊 Показано 15 из {len(balances)} записей"
    else:
        result += f"\n📊 Всего записей: {len(balances)}"
    
    result += f"\n💰 Общая сумма: {total:,.2f} ₽"
    return result

def format_transactions(data: Dict) -> str:
    if not data.get("status"):
        return f"❌ Ошибка API: {data.get('error', 'Unknown error')}"
    
    transactions = data.get("data", [])
    if not transactions:
        return "📭 Транзакции не найдены за указанный период"
    
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
• 🔌 Проверить API - тест подключения
• 🏢 Список клубов
• 💰 Балансы гостей
• 💸 История транзакций
• 👤 Поиск гостей
• 🎮 Игровые сессии
• 📊 Финансовая статистика

🔧 ПЕРВЫЙ ШАГ:
Нажмите кнопку "🔌 Проверить API" для диагностики подключения

Используйте кнопки ниже 👇"""
    
    await message.answer(welcome_text, reply_markup=get_main_keyboard())
    logger.info(f"User {message.from_user.id} started")

@dp.message(F.text == "◀️ Назад")
async def back_to_main(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("🏠 Главное меню", reply_markup=get_main_keyboard())

@dp.message(F.text == "🔌 Проверить API")
async def test_api_connection(message: types.Message):
    """Проверка подключения к API"""
    msg = await message.answer("🔄 Проверка подключения к API LANGAME...\n\nТестирую эндпоинт /v1/clubs/list...")
    
    result = await api.test_connection()
    
    if result["success"]:
        clubs_count = result.get("clubs_count", 0)
        response_text = f"""✅ API ПОДКЛЮЧЕНИЕ УСПЕШНО!

📊 Статус: Работает
🔑 API Key: Настроен
🏢 Доступно клубов: {clubs_count}
🌐 API URL: {API_BASE_URL}

🎉 Бот готов к работе! Используйте остальные кнопки меню."""
    else:
        response_text = f"""❌ ОШИБКА ПОДКЛЮЧЕНИЯ К API

🔴 Статус: Не работает
🔑 API Key: {'Не настроен' if not API_KEY else 'Настроен'}
❌ Ошибка: {result['error']}

💡 РЕШЕНИЕ:
1. Проверьте API ключ у администратора LANGAME
2. Убедитесь, что ключ действителен и активен
3. Проверьте, что у ключа есть доступ к API
4. После исправления нажмите "🔌 Проверить API" снова

📝 Если ключа нет - обратитесь к администратору LANGAME"""
    
    await msg.edit_text(response_text)
    logger.info(f"API test result: {result['success']}")

@dp.message(F.text == "ℹ️ О боте")
async def about_bot(message: types.Message):
    api_status = "✅ Настроен" if API_KEY else "❌ Не настроен"
    
    about_text = f"""🤖 О БОТЕ LANGAME

Версия: 1.3.0
Платформа: Railway

📌 СТАТУС API:
• Ключ: {api_status}
• URL: {API_BASE_URL}

💡 ПЕРВЫЙ ЗАПУСК:
Нажмите кнопку "🔌 Проверить API"

⚠️ Если функции не работают:
1. Нажмите "🔌 Проверить API"
2. Следуйте инструкциям из результата проверки"""
    
    await message.answer(about_text)
    
    if not API_KEY:
        await message.answer("⚠️ ВНИМАНИЕ! API ключ LANGAME не настроен.\n\nНажмите кнопку '🔌 Проверить API' для получения инструкций.")

@dp.message(F.text == "🏢 Клубы")
async def show_clubs(message: types.Message):
    msg = await message.answer("🔄 Загрузка списка клубов...", reply_markup=get_back_keyboard())
    
    if not API_KEY:
        await msg.edit_text("❌ API ключ не настроен!\n\nНажмите кнопку '🔌 Проверить API' для получения инструкций.")
        return
    
    response = await api.get_clubs()
    result = format_clubs(response)
    
    await msg.edit_text(result)

@dp.message(F.text == "💰 Балансы")
async def show_balances(message: types.Message):
    msg = await message.answer("🔄 Загрузка балансов гостей...", reply_markup=get_back_keyboard())
    
    if not API_KEY:
        await msg.edit_text("❌ API ключ не настроен!\n\nНажмите кнопку '🔌 Проверить API' для получения инструкций.")
        return
    
    response = await api.get_balances()
    result = format_balances(response)
    
    await msg.edit_text(result)

@dp.message(F.text == "💸 Транзакции")
async def show_transactions(message: types.Message):
    msg = await message.answer("🔄 Загрузка транзакций за 7 дней...", reply_markup=get_back_keyboard())
    
    if not API_KEY:
        await msg.edit_text("❌ API ключ не настроен!\n\nНажмите кнопку '🔌 Проверить API' для получения инструкций.")
        return
    
    date_to = datetime.now().strftime("%Y-%m-%d")
    date_from = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    
    response = await api.get_transactions(date_from, date_to)
    result = format_transactions(response)
    
    await msg.edit_text(result)

@dp.message(F.text == "👤 Поиск гостя")
async def search_guest_prompt(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!\n\nНажмите кнопку '🔌 Проверить API' для получения инструкций.")
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
        await message.answer("❌ API ключ не настроен!\n\nНажмите кнопку '🔌 Проверить API' для получения инструкций.")
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
        error = response.get('error', 'Не удалось получить сессии')
        await msg.edit_text(f"❌ Ошибка: {error}")
    
    await state.clear()

@dp.message(F.text == "📊 Статистика")
async def show_stats(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!\n\nНажмите кнопку '🔌 Проверить API' для получения инструкций.")
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
            "❓ Используйте кнопки меню или команду /help\n\n🔧 Первым делом нажмите '🔌 Проверить API'",
            reply_markup=get_main_keyboard()
        )

# ========== ЗАПУСК ==========
async def main():
    logger.info("🚀 LANGAME Telegram Bot starting...")
    logger.info(f"API URL: {API_BASE_URL}")
    logger.info(f"API Key configured: {'YES' if API_KEY else 'NO'}")
    
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Автоматическая проверка API при старте
    if API_KEY:
        logger.info("Running automatic API connection test...")
        test_result = await api.test_connection()
        logger.info(f"Auto API test result: {test_result['success']}")
        if not test_result['success']:
            logger.warning(f"API test failed: {test_result['error']}")
    else:
        logger.warning("API Key not configured! Please add LANGAME_API_KEY")
    
    logger.info("Bot is ready!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())