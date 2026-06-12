import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

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
API_BASE_URL = "https://cyberx302.langame.ru/public_api"

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не указан в переменных окружения!")

if not API_KEY:
    logger.warning("LANGAME_API_KEY не указан! Функции API не будут работать.")

# ========== СОСТОЯНИЯ ДЛЯ FSM ==========
class DateFilterState(StatesGroup):
    waiting_for_date_from = State()
    waiting_for_date_to = State()

# ========== ИНИЦИАЛИЗАЦИЯ БОТА ==========
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
        logger.info(f"API Client initialized with base URL: {base_url}")
    
    async def request(self, endpoint: str, params: Dict = None, timeout: int = 90) -> Dict:
        """Универсальный метод для GET запросов с таймаутом"""
        url = f"{self.base_url}{endpoint}"
        logger.info(f"API Request: GET {url}")
        if params:
            logger.debug(f"Request params: {params}")
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=self.headers, params=params, timeout=timeout) as resp:
                    logger.info(f"Response status: {resp.status}")
                    if resp.status == 200:
                        result = await resp.json()
                        logger.debug(f"Response data: {str(result)[:200]}...")
                        return result
                    elif resp.status == 403:
                        return {"status": False, "error": "Доступ запрещен (403). Проверьте API ключ."}
                    elif resp.status == 404:
                        return {"status": False, "error": f"Эндпоинт {endpoint} не найден (404)"}
                    else:
                        return {"status": False, "error": f"HTTP {resp.status}"}
            except asyncio.TimeoutError:
                logger.error(f"Timeout {timeout}s on {endpoint}")
                return {"status": False, "error": f"Сервер не ответил за {timeout} секунд. Попробуйте позже."}
            except aiohttp.ClientError as e:
                logger.error(f"Client error: {e}")
                return {"status": False, "error": f"Ошибка подключения: {str(e)}"}
            except Exception as e:
                logger.error(f"API error: {e}")
                return {"status": False, "error": str(e)}
    
    async def test_connection(self) -> Dict:
        """Быстрая проверка подключения (5 секунд)"""
        if not self.api_key or self.api_key == "MISSING_API_KEY":
            return {"success": False, "error": "API ключ не настроен"}
        
        result = await self.request("/all_operations_log/list", timeout=10)
        if result.get("status"):
            return {"success": True, "working_endpoint": "/all_operations_log/list"}
        else:
            return {"success": False, "error": result.get("error", "Неизвестная ошибка")}
    
    async def get_operations_log(self, date_from: str = None, date_to: str = None,
                                  operation_type: str = None, operation_source: str = None,
                                  sum_from: float = None, sum_to: float = None,
                                  club_id: int = None) -> Dict:
        """Получить лог операций - /all_operations_log/list"""
        params = {}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        if operation_type:
            params["operation_type"] = operation_type
        if operation_source:
            params["operation_source"] = operation_source
        if sum_from:
            params["sum_from"] = sum_from
        if sum_to:
            params["sum_to"] = sum_to
        if club_id:
            params["club_id"] = club_id
        
        return await self.request("/all_operations_log/list", params=params, timeout=90)
    
    async def get_transactions(self, date_from: str = None, date_to: str = None,
                                page: int = 1, limit: int = 20,
                                tx_type: int = None, pay_system: int = None) -> Dict:
        """Получить транзакции - /transactions/list"""
        params = {"page": page, "page_limit": limit}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        if tx_type:
            params["type"] = tx_type
        if pay_system:
            params["pay_system"] = pay_system
        
        return await self.request("/transactions/list", params=params, timeout=90)
    
    async def get_balances_list(self, date_from: str, date_to: str,
                                 page: int = 1, limit: int = 20) -> Dict:
        """Получить список пополнений баланса - /balances/list"""
        params = {
            "page": page,
            "page_limit": limit,
            "date_from": date_from,
            "date_to": date_to
        }
        return await self.request("/balances/list", params=params, timeout=90)
    
    async def get_guests_balance(self, page: int = 1, limit: int = 20) -> Dict:
        """Получить балансы гостей - /guests/balance"""
        return await self.request("/guests/balance", params={"page": page, "page_limit": limit}, timeout=90)
    
    async def get_bonus_balance(self, page: int = 1, limit: int = 20) -> Dict:
        """Получить бонусные балансы - /guests/bonus_balance"""
        return await self.request("/guests/bonus_balance", params={"page": page, "page_limit": limit}, timeout=90)
    
    async def get_clubs(self) -> Dict:
        """Получить список клубов - /clubs/list"""
        return await self.request("/clubs/list", timeout=30)
    
    async def get_working_shifts(self, page: int = 1, limit: int = 20) -> Dict:
        """Получить список смен - /working_shifts/list"""
        return await self.request("/working_shifts/list", params={"page": page, "page_limit": limit}, timeout=60)

# Создаем экземпляр API клиента
api = LangameAPI(API_KEY if API_KEY else "MISSING_API_KEY", API_BASE_URL)

# ========== КЛАВИАТУРЫ ==========
def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Главная клавиатура"""
    buttons = [
        [KeyboardButton(text="🔌 Проверить API")],
        [KeyboardButton(text="📋 Лог операций"), KeyboardButton(text="💸 Транзакции")],
        [KeyboardButton(text="💰 Балансы гостей"), KeyboardButton(text="🎁 Бонусы гостей")],
        [KeyboardButton(text="🏢 Клубы"), KeyboardButton(text="📊 Смены")],
        [KeyboardButton(text="📈 Статистика"), KeyboardButton(text="ℹ️ О боте")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_back_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура с кнопкой назад"""
    buttons = [[KeyboardButton(text="◀️ Назад")]]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# ========== ФОРМАТТЕРЫ ==========
def format_test_result(result: Dict) -> str:
    """Форматирование результата проверки API"""
    if result.get("success"):
        return f"""✅ API ПОДКЛЮЧЕНИЕ УСПЕШНО!

📊 Статус: Работает
🔑 API Key: Настроен
✅ Работает эндпоинт: {result.get('working_endpoint')}
🌐 API URL: {API_BASE_URL}

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

def format_operations_log(data: Dict, filter_desc: str = "") -> str:
    """Форматирование лога операций"""
    if not data.get("status"):
        return f"❌ Ошибка: {data.get('error', 'Неизвестная ошибка')}"
    
    operations = data.get("data", [])
    if not operations:
        return f"📭 Операции не найдены{f' ({filter_desc})' if filter_desc else ''}"
    
    result = f"📋 ЛОГ ОПЕРАЦИЙ{f' - {filter_desc}' if filter_desc else ''}\n\n"
    
    total_income = 0
    total_expense = 0
    income_count = 0
    expense_count = 0
    
    for op in operations[:20]:
        date_normal = op.get('date_normal', 'N/A')
        if date_normal and date_normal != 'N/A':
            date_normal = date_normal[:16]
        
        op_type = op.get('type', 'Unknown')
        op_name = op.get('name', '')
        op_sum = op.get('sum', 0)
        op_source = op.get('source', '')
        op_form = op.get('form', '')
        club_name = op.get('club_name', '')
        
        if op_sum and op_sum > 0:
            if op_type == "Пополнение":
                total_income += op_sum
                income_count += 1
            elif op_type == "Списание":
                total_expense += abs(op_sum)
                expense_count += 1
        
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
            result += f"   🔹 Источник: {op_source}\n"
        if op_form:
            result += f"   🔸 Форма: {op_form}\n"
        result += "─" * 25 + "\n"
    
    result += f"\n📊 ИТОГИ:\n"
    result += f"💰 Пополнения: {total_income:,.2f} ₽ ({income_count} оп.)\n"
    result += f"💸 Списания: {total_expense:,.2f} ₽ ({expense_count} оп.)\n"
    result += f"📈 Сальдо: {total_income - total_expense:,.2f} ₽"
    
    if len(operations) > 20:
        result += f"\n\n📊 Показано 20 из {len(operations)} записей"
    
    return result

def format_transactions(data: Dict, filter_desc: str = "") -> str:
    """Форматирование транзакций"""
    if not data.get("status"):
        return f"❌ Ошибка: {data.get('error', 'Неизвестная ошибка')}"
    
    transactions = data.get("data", [])
    if not transactions:
        return f"📭 Транзакции не найдены{f' ({filter_desc})' if filter_desc else ''}"
    
    result = f"💸 ТРАНЗАКЦИИ{f' - {filter_desc}' if filter_desc else ''}\n\n"
    total = 0
    
    for tx in transactions[:15]:
        date = tx.get('date_update', 'N/A')[:16]
        amount = float(tx.get('balance', 0))
        if amount > 0:
            total += amount
        sign = "+" if amount > 0 else ""
        result += f"📅 {date}\n"
        result += f"💰 {sign}{amount:,.2f} ₽\n"
        if tx.get('comment'):
            result += f"📝 {tx.get('comment')[:50]}\n"
        result += "─" * 25 + "\n"
    
    result += f"\n💰 Общая сумма пополнений: {total:,.2f} ₽"
    
    if len(transactions) > 15:
        result += f"\n📊 Показано 15 из {len(transactions)} записей"
    
    return result

def format_balances(data: Dict, title: str = "БАЛАНСЫ ГОСТЕЙ", currency: str = "₽") -> str:
    """Форматирование балансов"""
    if not data.get("status"):
        return f"❌ Ошибка: {data.get('error', 'Неизвестная ошибка')}"
    
    balances = data.get("data", [])
    if not balances:
        return f"📭 {title} не найдены"
    
    result = f"💰 {title}\n\n"
    total = 0
    for item in balances[:20]:
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
    
    if len(balances) > 20:
        result += f"\n📊 Показано 20 из {len(balances)} записей"
    else:
        result += f"\n📊 Всего записей: {len(balances)}"
    
    result += f"\n💰 Общая сумма: {total:,.2f} {currency}"
    return result

def format_clubs(data: Dict) -> str:
    """Форматирование списка клубов"""
    if not data.get("status"):
        return f"❌ Ошибка: {data.get('error', 'Неизвестная ошибка')}"
    
    clubs = data.get("data", [])
    if not clubs:
        return "🏢 Клубы не найдены"
    
    result = "🏢 СПИСОК КЛУБОВ\n\n"
    for club in clubs:
        status_icon = "🟢" if club.get("active") else "🔴"
        name = club.get('name', 'Без названия')
        club_id = club.get('id')
        address = club.get('address', '')
        result += f"{status_icon} {name} (ID: {club_id})\n"
        if address:
            result += f"   📍 {address}\n"
        result += "\n"
    
    result += f"\n📊 Всего клубов: {len(clubs)}"
    return result

def format_working_shifts(data: Dict) -> str:
    """Форматирование списка смен"""
    if not data.get("status"):
        return f"❌ Ошибка: {data.get('error', 'Неизвестная ошибка')}"
    
    shifts = data.get("data", [])
    if not shifts:
        return "📭 Смены не найдены"
    
    result = "📊 СПИСОК СМЕН\n\n"
    for shift in shifts[:10]:
        result += f"🆔 Смена #{shift.get('id')}\n"
        result += f"📅 Открыта: {shift.get('date_start', 'N/A')[:16] if shift.get('date_start') else 'N/A'}\n"
        if shift.get('date_stop'):
            result += f"📅 Закрыта: {shift.get('date_stop')[:16]}\n"
        else:
            result += f"🟢 Статус: Активна\n"
        result += f"💰 Наличные: {shift.get('nal', 0):,.2f} ₽\n"
        result += f"💳 Безналичные: {shift.get('beznal', 0):,.2f} ₽\n"
        result += f"📱 МП оплата: {shift.get('mobile_pay', 0):,.2f} ₽\n"
        result += f"💰 Инкассация: {shift.get('incass', 0):,.2f} ₽\n"
        result += f"📈 Средний чек: {shift.get('middle_check', 0)} ₽\n"
        result += "─" * 25 + "\n"
    
    if len(shifts) > 10:
        result += f"\n📊 Показано 10 из {len(shifts)} смен"
    else:
        result += f"\n📊 Всего смен: {len(shifts)}"
    
    return result

# ========== ОБРАБОТЧИКИ КОМАНД ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    welcome_text = """🎮 ДОБРО ПОЖАЛОВАТЬ В LANGAME БОТ!

Я помогаю управлять игровым клубом через API LANGAME.

📋 Доступные функции:
• 🔌 Проверить API - диагностика подключения
• 📋 Лог операций - все финансовые операции
• 💸 Транзакции - история операций с деньгами
• 💰 Балансы гостей - денежные балансы
• 🎁 Бонусы гостей - бонусные баллы
• 🏢 Клубы - список всех клубов
• 📊 Смены - история кассовых смен
• 📈 Статистика - финансовая аналитика

Используйте кнопки ниже 👇"""
    
    await message.answer(welcome_text, reply_markup=get_main_keyboard())
    logger.info(f"User {message.from_user.id} started the bot")

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    help_text = """❓ ПОМОЩЬ

🔌 Проверить API - Тест подключения к API
📋 Лог операций - Все операции (пополнения/списания) за 30 дней
💸 Транзакции - История операций с деньгами за 30 дней
💰 Балансы гостей - Текущие денежные балансы
🎁 Бонусы гостей - Текущие бонусные баллы
🏢 Клубы - Список всех клубов
📊 Смены - История кассовых смен
📈 Статистика - Финансовая аналитика

⏱️ Некоторые запросы могут выполняться до 90 секунд.
Пожалуйста, подождите после нажатия кнопки."""
    
    await message.answer(help_text)

@dp.message(F.text == "◀️ Назад")
async def back_to_main(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("🏠 Главное меню", reply_markup=get_main_keyboard())

@dp.message(F.text == "🔌 Проверить API")
async def test_api_connection(message: types.Message):
    msg = await message.answer("🔄 Проверка подключения к API...")
    
    result = await api.test_connection()
    response_text = format_test_result(result)
    
    await msg.edit_text(response_text)
    logger.info(f"API test result for user {message.from_user.id}: {result['success']}")

@dp.message(F.text == "ℹ️ О боте")
async def about_bot(message: types.Message):
    api_status = "✅ Настроен" if API_KEY else "❌ Не настроен"
    
    about_text = f"""🤖 О БОТЕ LANGAME

Версия: 2.0.0
Платформа: Railway

📌 СТАТУС API:
• Ключ: {api_status}
• URL: {API_BASE_URL}

⏱️ Таймаут запросов: 90 секунд

💡 ПЕРВЫЙ ЗАПУСК:
Нажмите кнопку "🔌 Проверить API"

⚠️ Если данные не загружаются:
• Проверьте интернет-соединение
• Попробуйте позже, когда сервер LANGAME менее загружен"""
    
    await message.answer(about_text)

@dp.message(F.text == "📋 Лог операций")
async def show_operations_log(message: types.Message):
    msg = await message.answer("🔄 Загрузка лога операций за 30 дней...\n⏱️ Это может занять до 90 секунд...", reply_markup=get_back_keyboard())
    
    if not API_KEY:
        await msg.edit_text("❌ API ключ не настроен!\n\nНажмите '🔌 Проверить API' для получения инструкций.")
        return
    
    date_to = datetime.now().strftime("%Y-%m-%d")
    date_from = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    
    response = await api.get_operations_log(date_from, date_to)
    result = format_operations_log(response, "30 дней")
    
    await msg.edit_text(result)

@dp.message(F.text == "💸 Транзакции")
async def show_transactions(message: types.Message):
    msg = await message.answer("🔄 Загрузка транзакций за 30 дней...\n⏱️ Это может занять до 90 секунд...", reply_markup=get_back_keyboard())
    
    if not API_KEY:
        await msg.edit_text("❌ API ключ не настроен!")
        return
    
    date_to = datetime.now().strftime("%Y-%m-%d")
    date_from = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    
    response = await api.get_transactions(date_from, date_to)
    result = format_transactions(response, "30 дней")
    
    await msg.edit_text(result)

@dp.message(F.text == "💰 Балансы гостей")
async def show_balances(message: types.Message):
    msg = await message.answer("🔄 Загрузка балансов гостей...\n⏱️ Это может занять до 90 секунд...", reply_markup=get_back_keyboard())
    
    if not API_KEY:
        await msg.edit_text("❌ API ключ не настроен!")
        return
    
    response = await api.get_guests_balance()
    result = format_balances(response, "БАЛАНСЫ ГОСТЕЙ", "₽")
    
    await msg.edit_text(result)

@dp.message(F.text == "🎁 Бонусы гостей")
async def show_bonus_balances(message: types.Message):
    msg = await message.answer("🔄 Загрузка бонусных балансов...\n⏱️ Это может занять до 90 секунд...", reply_markup=get_back_keyboard())
    
    if not API_KEY:
        await msg.edit_text("❌ API ключ не настроен!")
        return
    
    response = await api.get_bonus_balance()
    result = format_balances(response, "БОНУСНЫЕ БАЛАНСЫ", "бонусов")
    
    await msg.edit_text(result)

@dp.message(F.text == "🏢 Клубы")
async def show_clubs(message: types.Message):
    msg = await message.answer("🔄 Загрузка списка клубов...", reply_markup=get_back_keyboard())
    
    if not API_KEY:
        await msg.edit_text("❌ API ключ не настроен!")
        return
    
    response = await api.get_clubs()
    result = format_clubs(response)
    
    await msg.edit_text(result)

@dp.message(F.text == "📊 Смены")
async def show_working_shifts(message: types.Message):
    msg = await message.answer("🔄 Загрузка списка смен...\n⏱️ Это может занять до 60 секунд...", reply_markup=get_back_keyboard())
    
    if not API_KEY:
        await msg.edit_text("❌ API ключ не настроен!")
        return
    
    response = await api.get_working_shifts()
    result = format_working_shifts(response)
    
    await msg.edit_text(result)

@dp.message(F.text == "📈 Статистика")
async def show_statistics(message: types.Message):
    msg = await message.answer("📊 Сбор статистики за 30 дней...\n⏱️ Это может занять до 90 секунд...")
    
    if not API_KEY:
        await msg.edit_text("❌ API ключ не настроен!")
        return
    
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
        
        await msg.edit_text(result)
    else:
        await msg.edit_text(f"❌ Ошибка получения статистики: {response.get('error', 'Неизвестная ошибка')}")

@dp.message()
async def handle_unknown(message: types.Message):
    if not message.text.startswith("/") and message.text not in ["🔌 Проверить API", "📋 Лог операций", "💸 Транзакции", "💰 Балансы гостей", "🎁 Бонусы гостей", "🏢 Клубы", "📊 Смены", "📈 Статистика", "ℹ️ О боте", "◀️ Назад"]:
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
    
    # Быстрая проверка API при старте
    if API_KEY and API_KEY != "MISSING_API_KEY":
        logger.info("Testing API connection...")
        test_result = await api.test_connection()
        if test_result.get("success"):
            logger.info("✅ API connection successful")
        else:
            logger.warning(f"⚠️ API connection failed: {test_result.get('error')}")
    else:
        logger.warning("⚠️ API Key not configured!")
    
    logger.info("🎉 Bot is ready!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())