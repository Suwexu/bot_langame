import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict

import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from dotenv import load_dotenv

load_dotenv()

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_KEY = os.getenv("LANGAME_API_KEY")
API_BASE_URL = "https://cyberx302.langame.ru"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

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
class DateFilterState(StatesGroup):
    waiting_for_date_from = State()
    waiting_for_date_to = State()

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
        logger.info(f"API Client initialized")
    
    async def request(self, endpoint: str, params: Dict = None, timeout: int = 90) -> Dict:
        url = f"{self.base_url}/public_api{endpoint}"
        logger.info(f"API Request: GET {url}")
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=self.headers, params=params, timeout=timeout) as resp:
                    logger.info(f"Response status: {resp.status}")
                    if resp.status == 200:
                        return await resp.json()
                    elif resp.status == 401:
                        return {"status": False, "error": "Ошибка авторизации (401). Проверьте API ключ."}
                    elif resp.status == 403:
                        return {"status": False, "error": "Доступ запрещен (403)"}
                    elif resp.status == 404:
                        return {"status": False, "error": f"Эндпоинт {endpoint} не найден (404)"}
                    else:
                        return {"status": False, "error": f"HTTP {resp.status}"}
            except asyncio.TimeoutError:
                return {"status": False, "error": f"Сервер не ответил за {timeout} секунд"}
            except Exception as e:
                return {"status": False, "error": str(e)}
    
    async def test_connection(self) -> Dict:
        if not self.api_key:
            return {"success": False, "error": "API ключ не настроен"}
        
        result = await self.request("/all_operations_log/list", timeout=15)
        if result.get("status"):
            return {"success": True, "working_endpoint": "/all_operations_log/list"}
        else:
            return {"success": False, "error": result.get("error", "Неизвестная ошибка")}
    
    async def get_operations_log(self, date_from: str = None, date_to: str = None) -> Dict:
        params = {}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        return await self.request("/all_operations_log/list", params=params)
    
    async def get_transactions(self, date_from: str = None, date_to: str = None,
                                page: int = 1, limit: int = 20) -> Dict:
        params = {"page": page, "page_limit": limit}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        return await self.request("/transactions/list", params=params)
    
    async def get_guests_balance(self, page: int = 1, limit: int = 20) -> Dict:
        return await self.request("/guests/balance", params={"page": page, "page_limit": limit})
    
    async def get_bonus_balance(self, page: int = 1, limit: int = 20) -> Dict:
        return await self.request("/guests/bonus_balance", params={"page": page, "page_limit": limit})
    
    async def get_clubs(self) -> Dict:
        return await self.request("/clubs/list")
    
    async def get_working_shifts(self, page: int = 1, limit: int = 20) -> Dict:
        return await self.request("/working_shifts/list", params={"page": page, "page_limit": limit})

api = LangameAPI(API_KEY if API_KEY else "MISSING_API_KEY", API_BASE_URL)

# ========== КЛАВИАТУРЫ ==========
def get_main_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="🔌 Проверить API")],
        [KeyboardButton(text="📋 Лог операций"), KeyboardButton(text="💸 Транзакции")],
        [KeyboardButton(text="💰 Балансы гостей"), KeyboardButton(text="🎁 Бонусы гостей")],
        [KeyboardButton(text="🏢 Клубы"), KeyboardButton(text="📊 Смены")],
        [KeyboardButton(text="📈 Статистика"), KeyboardButton(text="ℹ️ О боте")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# ========== ФОРМАТТЕРЫ ==========
def format_test_result(result: Dict) -> str:
    if result.get("success"):
        return f"""✅ API ПОДКЛЮЧЕНИЕ УСПЕШНО!

📊 Статус: Работает
🔑 API Key: Настроен
✅ Работает эндпоинт: {result.get('working_endpoint')}
🌐 API URL: https://cyberx302.langame.ru/public_api

🎉 Бот готов к работе!"""
    else:
        return f"""❌ ОШИБКА ПОДКЛЮЧЕНИЯ К API

🔴 Статус: Не работает
🔑 API Key: {'Настроен' if API_KEY else 'Не настроен'}
❌ Ошибка: {result.get('error')}

💡 Решение:
1. Проверьте API ключ в настройках Railway
2. Убедитесь, что ключ действителен
3. Обратитесь к администратору LANGAME"""

def format_operations_log(data: Dict) -> str:
    if not data.get("status"):
        return f"❌ Ошибка: {data.get('error', 'Неизвестная ошибка')}"
    
    items = data.get("data", [])
    if not items:
        return "📭 Операции не найдены"
    
    result = "📋 ЛОГ ОПЕРАЦИЙ\n\n"
    total_income = 0
    total_expense = 0
    
    for item in items[:20]:
        date_normal = item.get('date_normal', 'N/A')
        if date_normal and date_normal != 'N/A':
            date_normal = date_normal[:16]
        
        op_type = item.get('type', 'Unknown')
        op_name = item.get('name', '')
        op_sum = item.get('sum', 0)
        op_source = item.get('source', '')
        club_name = item.get('club_name', '')
        
        if op_sum and op_sum > 0:
            if op_type == "Пополнение":
                total_income += op_sum
            elif op_type == "Списание":
                total_expense += abs(op_sum)
        
        type_icon = "💰" if op_type == "Пополнение" else "💸"
        result += f"{type_icon} {date_normal}\n"
        if club_name:
            result += f"   📍 {club_name}\n"
        result += f"   📋 {op_type}\n"
        if op_name:
            result += f"   📝 {op_name[:50]}\n"
        if op_sum:
            result += f"   💵 {op_sum:,.2f} ₽\n"
        if op_source:
            result += f"   🔹 {op_source}\n"
        result += "─" * 25 + "\n"
    
    result += f"\n📊 ИТОГИ:\n"
    result += f"💰 Пополнения: {total_income:,.2f} ₽\n"
    result += f"💸 Списания: {total_expense:,.2f} ₽\n"
    result += f"📈 Сальдо: {total_income - total_expense:,.2f} ₽"
    
    if len(items) > 20:
        result += f"\n\n📊 Показано 20 из {len(items)} записей"
    
    return result

def format_transactions(data: Dict) -> str:
    if not data.get("status"):
        return f"❌ Ошибка: {data.get('error', 'Неизвестная ошибка')}"
    
    items = data.get("data", [])
    if not items:
        return "📭 Транзакции не найдены"
    
    result = "💸 ТРАНЗАКЦИИ\n\n"
    total = 0
    
    for item in items[:15]:
        date = item.get('date_update', 'N/A')
        if date and date != 'N/A':
            date = date[:16]
        amount = float(item.get('balance', 0))
        if amount > 0:
            total += amount
        sign = "+" if amount > 0 else ""
        result += f"📅 {date}\n"
        result += f"💰 {sign}{amount:,.2f} ₽\n"
        if item.get('comment'):
            result += f"📝 {item.get('comment')[:50]}\n"
        result += "─" * 25 + "\n"
    
    result += f"\n💰 Общая сумма: {total:,.2f} ₽"
    
    if len(items) > 15:
        result += f"\n📊 Показано 15 из {len(items)} записей"
    
    return result

def format_balances(data: Dict, title: str = "БАЛАНСЫ ГОСТЕЙ", currency: str = "₽") -> str:
    if not data.get("status"):
        return f"❌ Ошибка: {data.get('error', 'Неизвестная ошибка')}"
    
    items = data.get("data", [])
    if not items:
        return f"📭 {title} не найдены"
    
    result = f"💰 {title}\n\n"
    total = 0
    
    for item in items[:20]:
        if "bonus_balance" in item:
            balance = float(item.get('bonus_balance', 0))
            guest_id = item.get('guest_id')
            result += f"• Гость #{guest_id}: {balance:,.0f} {currency}\n"
            total += balance
        else:
            balance = float(item.get('balance', 0))
            guest_id = item.get('guest_id')
            result += f"• Гость #{guest_id}: {balance:,.2f} {currency}\n"
            total += balance
    
    if len(items) > 20:
        result += f"\n📊 Показано 20 из {len(items)} записей"
    else:
        result += f"\n📊 Всего записей: {len(items)}"
    
    result += f"\n💰 Общая сумма: {total:,.2f} {currency}"
    return result

def format_clubs(data: Dict) -> str:
    if not data.get("status"):
        return f"❌ Ошибка: {data.get('error', 'Неизвестная ошибка')}"
    
    items = data.get("data", [])
    if not items:
        return "🏢 Клубы не найдены"
    
    result = "🏢 СПИСОК КЛУБОВ\n\n"
    for club in items:
        status_icon = "🟢" if club.get("active") else "🔴"
        name = club.get('name', 'Без названия')
        club_id = club.get('id')
        address = club.get('address', '')
        result += f"{status_icon} {name} (ID: {club_id})\n"
        if address:
            result += f"   📍 {address}\n"
        result += "\n"
    
    result += f"\n📊 Всего клубов: {len(items)}"
    return result

def format_working_shifts(data: Dict) -> str:
    if not data.get("status"):
        return f"❌ Ошибка: {data.get('error', 'Неизвестная ошибка')}"
    
    items = data.get("data", [])
    if not items:
        return "📭 Смены не найдены"
    
    result = "📊 СПИСОК СМЕН\n\n"
    for shift in items[:10]:
        result += f"🆔 Смена #{shift.get('id')}\n"
        date_start = shift.get('date_start', 'N/A')
        if date_start and date_start != 'N/A':
            date_start = date_start[:16]
        result += f"📅 Открыта: {date_start}\n"
        
        date_stop = shift.get('date_stop')
        if date_stop:
            result += f"📅 Закрыта: {date_stop[:16]}\n"
        else:
            result += f"🟢 Статус: Активна\n"
        
        result += f"💰 Наличные: {shift.get('nal', 0):,.2f} ₽\n"
        result += f"💳 Безналичные: {shift.get('beznal', 0):,.2f} ₽\n"
        result += f"📱 МП оплата: {shift.get('mobile_pay', 0):,.2f} ₽\n"
        result += f"💰 Инкассация: {shift.get('incass', 0):,.2f} ₽\n"
        result += f"📈 Средний чек: {shift.get('middle_check', 0)} ₽\n"
        result += "─" * 25 + "\n"
    
    if len(items) > 10:
        result += f"\n📊 Показано 10 из {len(items)} смен"
    else:
        result += f"\n📊 Всего смен: {len(items)}"
    
    return result

# ========== ОБРАБОТЧИКИ ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    welcome_text = """🎮 ДОБРО ПОЖАЛОВАТЬ В LANGAME БОТ!

Я помогаю управлять игровым клубом через API LANGAME.

📋 Доступные функции:
• 🔌 Проверить API - диагностика
• 📋 Лог операций - все финансовые операции
• 💸 Транзакции - история операций с деньгами
• 💰 Балансы гостей - денежные балансы
• 🎁 Бонусы гостей - бонусные баллы
• 🏢 Клубы - список всех клубов
• 📊 Смены - история кассовых смен
• 📈 Статистика - финансовая аналитика

Используйте кнопки ниже 👇"""
    
    await message.answer(welcome_text, reply_markup=get_main_keyboard())
    logger.info(f"User {message.from_user.id} started")

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    help_text = """❓ ПОМОЩЬ

🔌 Проверить API - Тест подключения
📋 Лог операций - Все операции за 30 дней
💸 Транзакции - История операций с деньгами
💰 Балансы гостей - Текущие балансы
🎁 Бонусы гостей - Текущие бонусы
🏢 Клубы - Список клубов
📊 Смены - История смен
📈 Статистика - Финансовая аналитика

⏱️ Запросы могут выполняться до 90 секунд"""
    
    await message.answer(help_text)

@dp.message(F.text == "🔌 Проверить API")
async def test_api_connection(message: types.Message):
    loading_msg = await message.answer("🔄 Проверка подключения к API...")
    
    result = await api.test_connection()
    response_text = format_test_result(result)
    
    await loading_msg.delete()
    await message.answer(response_text)

@dp.message(F.text == "ℹ️ О боте")
async def about_bot(message: types.Message):
    api_status = "✅ Настроен" if API_KEY else "❌ Не настроен"
    
    about_text = f"""🤖 О БОТЕ LANGAME

Версия: 2.2.0
Платформа: Railway

📌 СТАТУС API:
• Ключ: {api_status}
• URL: https://cyberx302.langame.ru/public_api

⏱️ Таймаут: 90 секунд

💡 Нажмите '🔌 Проверить API' для диагностики"""
    
    await message.answer(about_text)

@dp.message(F.text == "📋 Лог операций")
async def show_operations_log(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    
    loading_msg = await message.answer("🔄 Загрузка лога операций за 30 дней...\n⏱️ До 90 секунд...")
    
    date_to = datetime.now().strftime("%Y-%m-%d")
    date_from = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    
    response = await api.get_operations_log(date_from, date_to)
    result = format_operations_log(response)
    
    await loading_msg.delete()
    await message.answer(result, reply_markup=get_main_keyboard())

@dp.message(F.text == "💸 Транзакции")
async def show_transactions(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    
    loading_msg = await message.answer("🔄 Загрузка транзакций за 30 дней...\n⏱️ До 90 секунд...")
    
    date_to = datetime.now().strftime("%Y-%m-%d")
    date_from = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    
    response = await api.get_transactions(date_from, date_to)
    result = format_transactions(response)
    
    await loading_msg.delete()
    await message.answer(result, reply_markup=get_main_keyboard())

@dp.message(F.text == "💰 Балансы гостей")
async def show_balances(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    
    loading_msg = await message.answer("🔄 Загрузка балансов гостей...\n⏱️ До 90 секунд...")
    
    response = await api.get_guests_balance()
    result = format_balances(response, "БАЛАНСЫ ГОСТЕЙ", "₽")
    
    await loading_msg.delete()
    await message.answer(result, reply_markup=get_main_keyboard())

@dp.message(F.text == "🎁 Бонусы гостей")
async def show_bonus_balances(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    
    loading_msg = await message.answer("🔄 Загрузка бонусных балансов...\n⏱️ До 90 секунд...")
    
    response = await api.get_bonus_balance()
    result = format_balances(response, "БОНУСНЫЕ БАЛАНСЫ", "бонусов")
    
    await loading_msg.delete()
    await message.answer(result, reply_markup=get_main_keyboard())

@dp.message(F.text == "🏢 Клубы")
async def show_clubs(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    
    loading_msg = await message.answer("🔄 Загрузка списка клубов...")
    
    response = await api.get_clubs()
    result = format_clubs(response)
    
    await loading_msg.delete()
    await message.answer(result, reply_markup=get_main_keyboard())

@dp.message(F.text == "📊 Смены")
async def show_working_shifts(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    
    loading_msg = await message.answer("🔄 Загрузка списка смен...\n⏱️ До 60 секунд...")
    
    response = await api.get_working_shifts()
    result = format_working_shifts(response)
    
    await loading_msg.delete()
    await message.answer(result, reply_markup=get_main_keyboard())

@dp.message(F.text == "📈 Статистика")
async def show_statistics(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    
    loading_msg = await message.answer("📊 Сбор статистики за 30 дней...\n⏱️ До 90 секунд...")
    
    date_to = datetime.now().strftime("%Y-%m-%d")
    date_from = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    
    response = await api.get_transactions(date_from, date_to)
    
    if response.get("status") and response.get("data"):
        transactions = response["data"]
        total_income = sum(float(tx.get("balance", 0)) for tx in transactions if float(tx.get("balance", 0)) > 0)
        income_count = len([tx for tx in transactions if float(tx.get("balance", 0)) > 0])
        total_expense = sum(abs(float(tx.get("balance", 0))) for tx in transactions if float(tx.get("balance", 0)) < 0)
        expense_count = len([tx for tx in transactions if float(tx.get("balance", 0)) < 0])
        
        result = f"""📊 ФИНАНСОВАЯ СТАТИСТИКА

📅 Период: {date_from} - {date_to}

💰 ПОПОЛНЕНИЯ:
• Сумма: {total_income:,.2f} ₽
• Кол-во: {income_count} шт.
• Средний чек: {total_income / income_count if income_count > 0 else 0:.2f} ₽

💸 СПИСАНИЯ:
• Сумма: {total_expense:,.2f} ₽
• Кол-во: {expense_count} шт.

📈 ИТОГО:
• Сальдо: {total_income - total_expense:,.2f} ₽
• Всего операций: {len(transactions)} шт."""
        
        await loading_msg.delete()
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await loading_msg.delete()
        await message.answer(f"❌ Ошибка: {response.get('error', 'Неизвестная ошибка')}", reply_markup=get_main_keyboard())

@dp.message()
async def handle_unknown(message: types.Message):
    if message.text not in ["🔌 Проверить API", "📋 Лог операций", "💸 Транзакции", "💰 Балансы гостей", "🎁 Бонусы гостей", "🏢 Клубы", "📊 Смены", "📈 Статистика", "ℹ️ О боте"] and not message.text.startswith("/"):
        await message.answer(
            "❓ Используйте кнопки меню или /help\n\n🔧 Нажмите '🔌 Проверить API'",
            reply_markup=get_main_keyboard()
        )

async def main():
    logger.info("🚀 LANGAME Telegram Bot starting...")
    logger.info(f"API URL: https://cyberx302.langame.ru/public_api")
    logger.info(f"API Key: {'✅ Configured' if API_KEY else '❌ Missing'}")
    
    await bot.delete_webhook(drop_pending_updates=True)
    
    if API_KEY:
        test_result = await api.test_connection()
        if test_result.get("success"):
            logger.info("✅ API connection successful")
        else:
            logger.warning(f"⚠️ API connection failed: {test_result.get('error')}")
    
    logger.info("🎉 Bot is ready!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())