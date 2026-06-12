import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Any

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

# ========== СОСТОЯНИЯ ДЛЯ FSM ==========
class SearchState(StatesGroup):
    waiting_for_search_input = State()

class SessionsState(StatesGroup):
    waiting_for_guest_id = State()

class LogsState(StatesGroup):
    waiting_for_guest_id = State()

class BalanceHistoryState(StatesGroup):
    waiting_for_date_from = State()
    waiting_for_date_to = State()

class CashTransactionState(StatesGroup):
    waiting_for_club_id = State()
    waiting_for_date_from = State()
    waiting_for_date_to = State()

class GoodsState(StatesGroup):
    waiting_for_club_id = State()

class ProductsExpenseState(StatesGroup):
    waiting_for_date_from = State()
    waiting_for_date_to = State()

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def safe_float(value: Any, default: float = 0) -> float:
    """Безопасное преобразование в float"""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default

def safe_int(value: Any, default: int = 0) -> int:
    """Безопасное преобразование в int"""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

def format_currency(amount: Any) -> str:
    """Форматирование валюты"""
    try:
        return f"{safe_float(amount):,.2f} ₽"
    except:
        return f"{amount} ₽"

def format_bonus(amount: Any) -> str:
    """Форматирование бонусов"""
    try:
        return f"{safe_float(amount):,.0f}"
    except:
        return f"{amount}"

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
    
    async def request(self, endpoint: str, method: str = "GET", data: Dict = None, params: Dict = None, timeout: int = 90) -> Dict:
        url = f"{self.base_url}/public_api{endpoint}"
        logger.info(f"API Request: {method} {url}")
        
        async with aiohttp.ClientSession() as session:
            try:
                if method.upper() == "GET":
                    async with session.get(url, headers=self.headers, params=params, timeout=timeout) as resp:
                        return await self._handle_response(resp)
                else:
                    async with session.post(url, headers=self.headers, json=data, timeout=timeout) as resp:
                        return await self._handle_response(resp)
            except asyncio.TimeoutError:
                return {"status": False, "error": f"Сервер не ответил за {timeout} секунд"}
            except Exception as e:
                return {"status": False, "error": str(e)}
    
    async def _handle_response(self, resp):
        if resp.status == 200:
            return await resp.json()
        elif resp.status == 401:
            return {"status": False, "error": "Ошибка авторизации (401). Проверьте API ключ."}
        elif resp.status == 403:
            return {"status": False, "error": "Доступ запрещен (403)"}
        elif resp.status == 404:
            return {"status": False, "error": "Эндпоинт не найден (404)"}
        else:
            return {"status": False, "error": f"HTTP {resp.status}"}
    
    async def test_connection(self) -> Dict:
        if not self.api_key:
            return {"success": False, "error": "API ключ не настроен"}
        result = await self.request("/all_operations_log/list", timeout=15)
        if result.get("status"):
            return {"success": True, "working_endpoint": "/all_operations_log/list"}
        return {"success": False, "error": result.get("error", "Неизвестная ошибка")}
    
    async def get_clubs(self) -> Dict:
        return await self.request("/clubs/list")
    
    async def get_guests_list(self, page: int = 1, limit: int = 20, guest_id: int = None) -> Dict:
        params = {"page": page, "page_limit": limit}
        if guest_id:
            params["guest_id"] = guest_id
        return await self.request("/guests/list", params=params)
    
    async def search_guest(self, search_data: Dict) -> Dict:
        return await self.request("/guests/search", method="POST", data=search_data)
    
    async def get_guest_by_id(self, guest_id: int) -> Dict:
        return await self.request(f"/guests/{guest_id}")
    
    async def get_guest_groups(self) -> Dict:
        return await self.request("/guests/groups")
    
    async def get_guest_logs(self, guest_id: int, page: int = 1, limit: int = 20) -> Dict:
        return await self.request("/guests/logs", params={"guest_id": guest_id, "page": page, "page_limit": limit})
    
    async def get_guest_sessions(self, guest_id: int = None, date_from: str = None, date_to: str = None, page: int = 1, limit: int = 20) -> Dict:
        params = {"page": page, "page_limit": limit}
        if guest_id:
            params["guest_id"] = guest_id
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        return await self.request("/guests/sessions", params=params)
    
    async def get_guests_balance(self, page: int = 1, limit: int = 20) -> Dict:
        return await self.request("/guests/balance", params={"page": page, "page_limit": limit})
    
    async def get_bonus_balance(self, page: int = 1, limit: int = 20) -> Dict:
        return await self.request("/guests/bonus_balance", params={"page": page, "page_limit": limit})
    
    async def get_transactions(self, date_from: str = None, date_to: str = None, page: int = 1, limit: int = 20) -> Dict:
        params = {"page": page, "page_limit": limit}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        return await self.request("/transactions/list", params=params)
    
    async def get_operations_log(self, date_from: str = None, date_to: str = None, **kwargs) -> Dict:
        params = {}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        for key, value in kwargs.items():
            if value:
                params[key] = value
        return await self.request("/all_operations_log/list", params=params)
    
    async def get_cash_transactions(self, club_id: int, date_from: str, date_to: str) -> Dict:
        return await self.request("/log_cash_transaction/list", params={"club_id": club_id, "date_from": date_from, "date_to": date_to})
    
    async def get_working_shifts(self, page: int = 1, limit: int = 20) -> Dict:
        return await self.request("/working_shifts/list", params={"page": page, "page_limit": limit})
    
    async def get_balances_list(self, date_from: str, date_to: str, page: int = 1, limit: int = 20) -> Dict:
        return await self.request("/balances/list", params={"page": page, "page_limit": limit, "date_from": date_from, "date_to": date_to})
    
    async def get_pc_list(self) -> Dict:
        return await self.request("/global/linking_pc_by_type/list")
    
    async def get_pc_types(self) -> Dict:
        return await self.request("/global/types_of_pc_in_clubs/list")
    
    async def get_products_list(self) -> Dict:
        return await self.request("/products/list")
    
    async def get_goods_list(self, club_id: int) -> Dict:
        return await self.request("/goods/list", params={"club_id": club_id})
    
    async def get_products_arrival(self, page: int = 1, limit: int = 20) -> Dict:
        return await self.request("/products/arrival", params={"page": page, "page_limit": limit})
    
    async def get_products_expense(self, date_from: str = None, date_to: str = None, type_filter: int = None, page: int = 1, limit: int = 20) -> Dict:
        params = {"page": page, "page_limit": limit}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        if type_filter:
            params["type"] = type_filter
        return await self.request("/products/expense", params=params)
    
    async def get_tariffs(self) -> Dict:
        return await self.request("/tariffs/time_period/list")
    
    async def get_tariff_groups(self) -> Dict:
        return await self.request("/tariffs/groups/list")
    
    async def get_tariff_types(self) -> Dict:
        return await self.request("/tariffs/types_groups/list")
    
    async def get_tariff_by_days(self) -> Dict:
        return await self.request("/tariffs/by_days/list")
    
    async def get_users_list(self) -> Dict:
        return await self.request("/users/list")
    
    async def get_config(self) -> Dict:
        return await self.request("/config/list")
    
    async def get_puf_profiles(self) -> Dict:
        return await self.request("/puf/profiles/list")
    
    async def get_routes(self) -> Dict:
        return await self.request("/routes")
    
    async def get_admin_console_config(self) -> Dict:
        return await self.request("/ver/get_adminconsole")
    
    async def get_terminal_config(self) -> Dict:
        return await self.request("/ver/get_terminal")

api = LangameAPI(API_KEY if API_KEY else "MISSING_API_KEY", API_BASE_URL)

# ========== КЛАВИАТУРЫ ==========
def get_main_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="🔌 Проверить API"), KeyboardButton(text="ℹ️ О боте")],
        [KeyboardButton(text="🏢 Клубы"), KeyboardButton(text="👥 Группы гостей")],
        [KeyboardButton(text="👤 Список гостей"), KeyboardButton(text="👤 Поиск гостя")],
        [KeyboardButton(text="💰 Балансы"), KeyboardButton(text="🎁 Бонусы")],
        [KeyboardButton(text="💸 Транзакции"), KeyboardButton(text="📋 Лог операций")],
        [KeyboardButton(text="💳 Кассовые операции"), KeyboardButton(text="📊 Смены")],
        [KeyboardButton(text="💰 Пополнения"), KeyboardButton(text="🖥️ Компьютеры")],
        [KeyboardButton(text="🎮 Типы ПК"), KeyboardButton(text="🍔 Товары")],
        [KeyboardButton(text="📦 Остатки"), KeyboardButton(text="📥 Поступления")],
        [KeyboardButton(text="📤 Продажи"), KeyboardButton(text="💲 Тарифы")],
        [KeyboardButton(text="📅 Группы тарифов"), KeyboardButton(text="🏷️ Типы тарифов")],
        [KeyboardButton(text="👨‍💼 Администраторы"), KeyboardButton(text="⚙️ Конфигурация")],
        [KeyboardButton(text="📁 Профили PUF"), KeyboardButton(text="🔌 Маршруты")],
        [KeyboardButton(text="📱 Админ ПО"), KeyboardButton(text="💻 Терминал")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_search_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 По телефону", callback_data="search_phone")],
        [InlineKeyboardButton(text="🆔 По ID", callback_data="search_id")],
        [InlineKeyboardButton(text="📝 По ФИО", callback_data="search_name")]
    ])

# ========== ФОРМАТТЕРЫ (с защитой от ошибок) ==========
def format_clubs(data: Dict) -> str:
    if not data.get("status"):
        return f"❌ Ошибка: {data.get('error', 'Неизвестная ошибка')}"
    items = data.get("data", [])
    if not items:
        return "🏢 Клубы не найдены"
    result = "🏢 СПИСОК КЛУБОВ\n\n"
    for club in items:
        status_icon = "🟢" if club.get("active") else "🔴"
        result += f"{status_icon} {club.get('name', 'Без названия')} (ID: {club.get('id')})\n"
        if club.get('address'):
            result += f"   📍 {club.get('address')}\n"
        result += "\n"
    result += f"\n📊 Всего клубов: {len(items)}"
    return result

def format_guests_list(data: Dict) -> str:
    if not data.get("status"):
        return f"❌ Ошибка: {data.get('error', 'Неизвестная ошибка')}"
    items = data.get("data", [])
    if not items:
        return "👤 Гости не найдены"
    result = "👤 СПИСОК ГОСТЕЙ\n\n"
    for guest in items[:15]:
        result += f"🆔 ID: {guest.get('guest_id')}\n"
        result += f"📝 ФИО: {guest.get('fio', 'Не указано')}\n"
        result += f"📱 Телефон: {guest.get('phone', 'Не указан')}\n"
        date_insert = guest.get('date_insert', 'N/A')
        if date_insert and date_insert != 'N/A':
            date_insert = date_insert[:16]
        result += f"📅 Регистрация: {date_insert}\n"
        result += "─" * 25 + "\n"
    if len(items) > 15:
        result += f"\n📊 Показано 15 из {len(items)} записей"
    else:
        result += f"\n📊 Всего гостей: {len(items)}"
    return result

def format_guest_groups(data: Dict) -> str:
    if not data.get("status"):
        return f"❌ Ошибка: {data.get('error', 'Неизвестная ошибка')}"
    items = data.get("data", [])
    if not items:
        return "👥 Группы не найдены"
    result = "👥 ГРУППЫ ГОСТЕЙ\n\n"
    for group in items:
        result += f"🆔 ID: {group.get('id')}\n"
        result += f"📝 Название: {group.get('name')}\n"
        if group.get('percent'):
            result += f"💰 Скидка: {group.get('percent')}%\n"
        if group.get('bonus_birthday'):
            result += f"🎁 Бонус на ДР: {group.get('bonus_birthday')}\n"
        result += "─" * 25 + "\n"
    return result

def format_guest_sessions(data: Dict, guest_id: int = None) -> str:
    if not data.get("status"):
        return f"❌ Ошибка: {data.get('error', 'Неизвестная ошибка')}"
    items = data.get("data", [])
    if not items:
        return f"🎮 Сессии для гостя #{guest_id} не найдены" if guest_id else "🎮 Сессии не найдены"
    result = f"🎮 СЕССИИ ГОСТЯ #{guest_id}\n\n" if guest_id else "🎮 СЕССИИ\n\n"
    for session in items[:10]:
        result += f"🆔 ID сессии: {session.get('id')}\n"
        date_start = session.get('date_start', 'N/A')
        if date_start and date_start != 'N/A':
            date_start = date_start[:16]
        result += f"📅 Начало: {date_start}\n"
        date_stop = session.get('date_stop', 'Активна')
        if date_stop and date_stop != 'Активна':
            date_stop = date_stop[:16]
        result += f"⏱️ Окончание: {date_stop}\n"
        result += f"📊 Статус: {'✅ Завершена' if session.get('normal_stop') else '🟢 Активна'}\n"
        result += "─" * 25 + "\n"
    return result

def format_balances(data: Dict, title: str = "БАЛАНСЫ", currency: str = "₽") -> str:
    if not data.get("status"):
        return f"❌ Ошибка: {data.get('error', 'Неизвестная ошибка')}"
    items = data.get("data", [])
    if not items:
        return f"📭 {title} не найдены"
    result = f"💰 {title}\n\n"
    total = 0.0
    for item in items[:20]:
        if "bonus_balance" in item:
            balance = safe_float(item.get('bonus_balance', 0))
            total += balance
            result += f"• Гость #{item.get('guest_id')}: {balance:,.0f} {currency}\n"
        else:
            balance = safe_float(item.get('balance', 0))
            total += balance
            result += f"• Гость #{item.get('guest_id')}: {balance:,.2f} {currency}\n"
    result += f"\n💰 Общая сумма: {total:,.2f} {currency}"
    return result

def format_transactions(data: Dict) -> str:
    if not data.get("status"):
        return f"❌ Ошибка: {data.get('error', 'Неизвестная ошибка')}"
    items = data.get("data", [])
    if not items:
        return "📭 Транзакции не найдены"
    result = "💸 ТРАНЗАКЦИИ\n\n"
    total = 0.0
    for item in items[:15]:
        date = item.get('date_update', 'N/A')
        if date and date != 'N/A':
            date = date[:16]
        amount = safe_float(item.get('balance', 0))
        if amount > 0:
            total += amount
        result += f"📅 {date}\n💰 {'+' if amount > 0 else ''}{amount:,.2f} ₽\n"
        if item.get('comment'):
            result += f"📝 {item.get('comment')[:50]}\n"
        result += "─" * 25 + "\n"
    result += f"\n💰 Общая сумма пополнений: {total:,.2f} ₽"
    return result

def format_operations_log(data: Dict) -> str:
    if not data.get("status"):
        return f"❌ Ошибка: {data.get('error', 'Неизвестная ошибка')}"
    items = data.get("data", [])
    if not items:
        return "📭 Операции не найдены"
    result = "📋 ЛОГ ОПЕРАЦИЙ\n\n"
    total_income, total_expense = 0.0, 0.0
    for item in items[:20]:
        date = item.get('date_normal', 'N/A')
        if date and date != 'N/A':
            date = date[:16]
        op_type = item.get('type', 'Unknown')
        op_sum = safe_float(item.get('sum', 0))
        if op_sum > 0:
            if op_type == "Пополнение":
                total_income += op_sum
            else:
                total_expense += abs(op_sum)
        result += f"{'💰' if op_type == 'Пополнение' else '💸'} {date}\n"
        result += f"   📋 {op_type}\n"
        if op_sum:
            result += f"   💵 {op_sum:,.2f} ₽\n"
        if item.get('club_name'):
            result += f"   📍 {item.get('club_name')}\n"
        result += "─" * 25 + "\n"
    result += f"\n📊 ИТОГИ:\n💰 Пополнения: {total_income:,.2f} ₽\n💸 Списания: {total_expense:,.2f} ₽\n📈 Сальдо: {total_income - total_expense:,.2f} ₽"
    return result

def format_pc_list(data: Dict) -> str:
    if not data.get("status"):
        return f"❌ Ошибка: {data.get('error', 'Неизвестная ошибка')}"
    items = data.get("data", [])
    if not items:
        return "🖥️ Компьютеры не найдены"
    result = "🖥️ СПИСОК КОМПЬЮТЕРОВ\n\n"
    for pc in items[:20]:
        result += f"{'🎮' if pc.get('isPS') else '🖥️'} {pc.get('name', 'Без имени')}\n"
        if pc.get('fiscal_name'):
            result += f"   📍 {pc.get('fiscal_name')}\n"
        uuid_val = pc.get('UUID', 'N/A')
        result += f"   🆔 UUID: {uuid_val[:16] if len(uuid_val) > 16 else uuid_val}...\n"
        result += "─" * 25 + "\n"
    return result

def format_products_list(data: Dict) -> str:
    if not data.get("status"):
        return f"❌ Ошибка: {data.get('error', 'Неизвестная ошибка')}"
    items = data.get("data", [])
    if not items:
        return "🍔 Товары не найдены"
    result = "🍔 СПИСОК ТОВАРОВ\n\n"
    for product in items[:20]:
        result += f"🆔 ID: {product.get('id')}\n"
        result += f"📝 {product.get('name', 'Без названия')}\n"
        result += f"{'🟢 Активен' if product.get('active') else '🔴 Неактивен'}\n"
        result += "─" * 25 + "\n"
    return result

def format_tariffs(data: Dict) -> str:
    if not data.get("status"):
        return f"❌ Ошибка: {data.get('error', 'Неизвестная ошибка')}"
    items = data.get("data", [])
    if not items:
        return "💲 Тарифы не найдены"
    result = "💲 ТАРИФЫ\n\n"
    for tariff in items[:15]:
        result += f"🆔 ID: {tariff.get('id')}\n"
        result += f"💰 Цена: {safe_float(tariff.get('price', 0)):,.2f} ₽\n"
        time_from = tariff.get('time_from', '')
        time_to = tariff.get('time_to', '')
        if time_from and time_to:
            result += f"⏰ Время: {time_from[:5]} - {time_to[:5]}\n"
        result += "─" * 25 + "\n"
    return result

def format_working_shifts(data: Dict) -> str:
    if not data.get("status"):
        return f"❌ Ошибка: {data.get('error', 'Неизвестная ошибка')}"
    items = data.get("data", [])
    if not items:
        return "📊 Смены не найдены"
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
        result += f"💰 Наличные: {safe_float(shift.get('nal', 0)):,.2f} ₽\n"
        result += f"💳 Безналичные: {safe_float(shift.get('beznal', 0)):,.2f} ₽\n"
        result += f"📈 Средний чек: {shift.get('middle_check', 0)}\n"
        result += "─" * 25 + "\n"
    return result

def format_users_list(data: Dict) -> str:
    if not data.get("status"):
        return f"❌ Ошибка: {data.get('error', 'Неизвестная ошибка')}"
    items = data.get("data", [])
    if not items:
        return "👨‍💼 Администраторы не найдены"
    result = "👨‍💼 АДМИНИСТРАТОРЫ\n\n"
    for user in items:
        result += f"🆔 ID: {user.get('id')}\n"
        result += f"📧 Логин: {user.get('email')}\n"
        if user.get('username'):
            result += f"📝 ФИО: {user.get('username')}\n"
        result += f"{'🟢 Активен' if user.get('verified') else '🔴 Неактивен'}\n"
        result += "─" * 25 + "\n"
    return result

# ========== ОБРАБОТЧИКИ ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("🎮 ДОБРО ПОЖАЛОВАТЬ В LANGAME БОТ!\n\nПолный набор команд для управления игровым клубом.\nИспользуйте кнопки ниже 👇", reply_markup=get_main_keyboard())

@dp.message(F.text == "🔌 Проверить API")
async def test_api(message: types.Message):
    msg = await message.answer("🔄 Проверка...")
    result = await api.test_connection()
    await msg.delete()
    if result.get("success"):
        await message.answer("✅ API ПОДКЛЮЧЕНИЕ УСПЕШНО!\n\n📊 Статус: Работает\n🔑 API Key: Настроен\n🌐 URL: https://cyberx302.langame.ru/public_api", reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ Ошибка: {result.get('error')}", reply_markup=get_main_keyboard())

@dp.message(F.text == "ℹ️ О боте")
async def about_bot(message: types.Message):
    await message.answer("🤖 LANGAME БОТ v3.0\n📍 Все команды из API LANGAME\n⏱️ Таймаут: 90 секунд", reply_markup=get_main_keyboard())

@dp.message(F.text == "🏢 Клубы")
async def show_clubs(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка...")
    response = await api.get_clubs()
    await msg.delete()
    await message.answer(format_clubs(response), reply_markup=get_main_keyboard())

@dp.message(F.text == "👤 Список гостей")
async def show_guests_list(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка списка гостей...")
    response = await api.get_guests_list()
    await msg.delete()
    await message.answer(format_guests_list(response), reply_markup=get_main_keyboard())

@dp.message(F.text == "👥 Группы гостей")
async def show_guest_groups(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка групп...")
    response = await api.get_guest_groups()
    await msg.delete()
    await message.answer(format_guest_groups(response), reply_markup=get_main_keyboard())

@dp.message(F.text == "👤 Поиск гостя")
async def search_guest_prompt(message: types.Message):
    await message.answer("🔍 ВЫБЕРИТЕ СПОСОБ ПОИСКА:", reply_markup=get_search_keyboard())

@dp.callback_query(lambda c: c.data.startswith("search_"))
async def process_search_type(callback: types.CallbackQuery, state: FSMContext):
    search_type = callback.data.replace("search_", "")
    prompts = {"phone": "📱 Введите номер телефона:", "id": "🆔 Введите ID гостя:", "name": "📝 Введите ФИО:"}
    await state.update_data(search_type=search_type)
    await state.set_state(SearchState.waiting_for_search_input)
    await callback.message.edit_text(prompts.get(search_type, "Введите данные:"))
    await callback.answer()

@dp.message(StateFilter(SearchState.waiting_for_search_input))
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
        await msg.delete()
        await message.answer("❌ Неверный формат!")
        await state.clear()
        return
    
    response = await api.search_guest(search_payload)
    await msg.delete()
    
    if response.get("items"):
        result = "👤 РЕЗУЛЬТАТЫ ПОИСКА\n\n"
        for guest in response["items"][:5]:
            result += f"🆔 ID: {guest.get('guest_id')}\n"
            result += f"📝 ФИО: {guest.get('fio', 'Не указано')}\n"
            result += f"📱 Телефон: {guest.get('phone', 'Не указан')}\n"
            
            if guest.get("balance"):
                balance_amount = guest['balance'].get('amount', 0)
                result += f"💰 Баланс: {format_currency(balance_amount)}\n"
            
            if guest.get("bonus_balance"):
                bonus_amount = guest['bonus_balance'].get('amount', 0)
                result += f"🎁 Бонусы: {format_bonus(bonus_amount)}\n"
            
            result += "─" * 25 + "\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer("❌ Гость не найден", reply_markup=get_main_keyboard())
    await state.clear()

@dp.message(F.text == "🎮 Сессии")
async def sessions_prompt(message: types.Message):
    await message.answer("🎮 Введите ID гостя для просмотра сессий:")
    await SessionsState.waiting_for_guest_id.set()

@dp.message(StateFilter(SessionsState.waiting_for_guest_id))
async def show_sessions(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введите число!")
        return
    msg = await message.answer(f"🔄 Загрузка сессий для гостя #{message.text}...")
    response = await api.get_guest_sessions(guest_id=int(message.text))
    await msg.delete()
    await message.answer(format_guest_sessions(response, int(message.text)), reply_markup=get_main_keyboard())
    await state.clear()

@dp.message(F.text == "💰 Балансы")
async def show_balances(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка балансов...")
    response = await api.get_guests_balance()
    await msg.delete()
    await message.answer(format_balances(response, "БАЛАНСЫ ГОСТЕЙ", "₽"), reply_markup=get_main_keyboard())

@dp.message(F.text == "🎁 Бонусы")
async def show_bonus(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка бонусов...")
    response = await api.get_bonus_balance()
    await msg.delete()
    await message.answer(format_balances(response, "БОНУСНЫЕ БАЛАНСЫ", "бонусов"), reply_markup=get_main_keyboard())

@dp.message(F.text == "💸 Транзакции")
async def show_transactions(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка транзакций за 30 дней...")
    date_to = datetime.now().strftime("%Y-%m-%d")
    date_from = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    response = await api.get_transactions(date_from, date_to)
    await msg.delete()
    await message.answer(format_transactions(response), reply_markup=get_main_keyboard())

@dp.message(F.text == "📋 Лог операций")
async def show_operations(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка лога операций за 30 дней...")
    date_to = datetime.now().strftime("%Y-%m-%d")
    date_from = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    response = await api.get_operations_log(date_from, date_to)
    await msg.delete()
    await message.answer(format_operations_log(response), reply_markup=get_main_keyboard())

@dp.message(F.text == "💳 Кассовые операции")
async def cash_transactions_prompt(message: types.Message):
    await message.answer("💳 Введите ID клуба:")
    await CashTransactionState.waiting_for_club_id.set()

@dp.message(StateFilter(CashTransactionState.waiting_for_club_id))
async def cash_transactions_date_from(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введите число!")
        return
    await state.update_data(club_id=int(message.text))
    await message.answer("📅 Введите дату ОТ (ГГГГ-ММ-ДД):")
    await state.set_state(CashTransactionState.waiting_for_date_from)

@dp.message(StateFilter(CashTransactionState.waiting_for_date_from))
async def cash_transactions_date_to(message: types.Message, state: FSMContext):
    await state.update_data(date_from=message.text.strip())
    await message.answer("📅 Введите дату ДО (ГГГГ-ММ-ДД):")
    await state.set_state(CashTransactionState.waiting_for_date_to)

@dp.message(StateFilter(CashTransactionState.waiting_for_date_to))
async def cash_transactions_result(message: types.Message, state: FSMContext):
    data = await state.get_data()
    msg = await message.answer("🔄 Загрузка кассовых операций...")
    response = await api.get_cash_transactions(data['club_id'], data['date_from'], message.text.strip())
    await msg.delete()
    if response.get("status") and response.get("data"):
        result = "💳 КАССОВЫЕ ОПЕРАЦИИ\n\n"
        for item in response["data"][:15]:
            result += f"📅 {item.get('date', 'N/A')}\n"
            result += f"💰 Сумма: {safe_float(item.get('sum', 0)):,.2f} ₽\n"
            if item.get('comment'):
                result += f"📝 {item.get('comment')}\n"
            result += "─" * 25 + "\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {response.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())
    await state.clear()

@dp.message(F.text == "📊 Смены")
async def show_shifts(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка смен...")
    response = await api.get_working_shifts()
    await msg.delete()
    await message.answer(format_working_shifts(response), reply_markup=get_main_keyboard())

@dp.message(F.text == "💰 Пополнения")
async def balances_history_prompt(message: types.Message):
    await message.answer("📅 Введите дату ОТ (ГГГГ-ММ-ДД):")
    await BalanceHistoryState.waiting_for_date_from.set()

@dp.message(StateFilter(BalanceHistoryState.waiting_for_date_from))
async def balances_history_date_to(message: types.Message, state: FSMContext):
    await state.update_data(date_from=message.text.strip())
    await message.answer("📅 Введите дату ДО (ГГГГ-ММ-ДД):")
    await state.set_state(BalanceHistoryState.waiting_for_date_to)

@dp.message(StateFilter(BalanceHistoryState.waiting_for_date_to))
async def balances_history_result(message: types.Message, state: FSMContext):
    data = await state.get_data()
    msg = await message.answer("🔄 Загрузка истории пополнений...")
    response = await api.get_balances_list(data['date_from'], message.text.strip())
    await msg.delete()
    if response.get("status") and response.get("data"):
        result = "💰 ИСТОРИЯ ПОПОЛНЕНИЙ\n\n"
        for item in response["data"][:15]:
            result += f"📅 {item.get('date', 'N/A')}\n"
            result += f"👤 Гость: {item.get('guest_name', 'N/A')}\n"
            result += f"💰 Сумма: {format_currency(item.get('amount', 0))}\n"
            result += "─" * 25 + "\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {response.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())
    await state.clear()

@dp.message(F.text == "🖥️ Компьютеры")
async def show_pc(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка списка ПК...")
    response = await api.get_pc_list()
    await msg.delete()
    await message.answer(format_pc_list(response), reply_markup=get_main_keyboard())

@dp.message(F.text == "🎮 Типы ПК")
async def show_pc_types(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка типов ПК...")
    response = await api.get_pc_types()
    await msg.delete()
    if response.get("status") and response.get("data"):
        result = "🎮 ТИПЫ ПК (ЗОНЫ)\n\n"
        for item in response["data"]:
            result += f"🆔 ID: {item.get('id')}\n📝 {item.get('name', 'Без названия')}\n"
            if item.get('color'):
                result += f"🎨 Цвет: {item.get('color')}\n"
            result += "─" * 25 + "\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {response.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

@dp.message(F.text == "🍔 Товары")
async def show_products(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка товаров...")
    response = await api.get_products_list()
    await msg.delete()
    await message.answer(format_products_list(response), reply_markup=get_main_keyboard())

@dp.message(F.text == "📦 Остатки")
async def goods_prompt(message: types.Message):
    await message.answer("📦 Введите ID клуба:")
    await GoodsState.waiting_for_club_id.set()

@dp.message(StateFilter(GoodsState.waiting_for_club_id))
async def goods_result(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введите число!")
        return
    msg = await message.answer(f"🔄 Загрузка остатков для клуба #{message.text}...")
    response = await api.get_goods_list(int(message.text))
    await msg.delete()
    if response.get("status") and response.get("data"):
        result = f"📦 ОСТАТКИ (клуб #{message.text})\n\n"
        for item in response["data"][:20]:
            result += f"🆔 ID: {item.get('id')}\n📝 {item.get('name', 'Без названия')}\n📦 Кол-во: {safe_int(item.get('count', 0))} шт.\n"
            result += "─" * 25 + "\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {response.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())
    await state.clear()

@dp.message(F.text == "📥 Поступления")
async def show_arrival(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка поступлений...")
    response = await api.get_products_arrival()
    await msg.delete()
    if response.get("status") and response.get("data"):
        result = "📥 ПОСТУПЛЕНИЯ ТОВАРОВ\n\n"
        for item in response["data"][:15]:
            date_fact = item.get('date_fact', 'N/A')
            if date_fact and date_fact != 'N/A':
                date_fact = date_fact[:16]
            result += f"📅 {date_fact}\n"
            result += f"🆔 Товар ID: {item.get('list_goods_id')}\n"
            result += f"📦 Кол-во: {safe_int(item.get('count', 0))} шт.\n"
            if item.get('price_fact'):
                result += f"💰 Цена: {format_currency(item.get('price_fact'))}\n"
            result += "─" * 25 + "\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {response.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

@dp.message(F.text == "📤 Продажи")
async def products_expense_prompt(message: types.Message):
    await message.answer("📅 Введите дату ОТ (ГГГГ-ММ-ДД) или 'все' для всех:")
    await ProductsExpenseState.waiting_for_date_from.set()

@dp.message(StateFilter(ProductsExpenseState.waiting_for_date_from))
async def products_expense_date_to(message: types.Message, state: FSMContext):
    date_from = None if message.text.lower() == "все" else message.text.strip()
    await state.update_data(date_from=date_from)
    await message.answer("📅 Введите дату ДО (ГГГГ-ММ-ДД) или 'все' для всех:")
    await state.set_state(ProductsExpenseState.waiting_for_date_to)

@dp.message(StateFilter(ProductsExpenseState.waiting_for_date_to))
async def products_expense_result(message: types.Message, state: FSMContext):
    data = await state.get_data()
    date_from = data.get('date_from')
    date_to = None if message.text.lower() == "все" else message.text.strip()
    msg = await message.answer("🔄 Загрузка продаж...")
    response = await api.get_products_expense(date_from=date_from, date_to=date_to)
    await msg.delete()
    if response.get("status") and response.get("data"):
        result = "📤 ПРОДАЖИ ТОВАРОВ\n\n"
        total = 0.0
        for item in response["data"][:15]:
            date_val = item.get('date', 'N/A')
            if date_val and date_val != 'N/A':
                date_val = date_val[:16]
            result += f"📅 {date_val}\n"
            result += f"🆔 Товар ID: {item.get('list_goods_id')}\n"
            result += f"📦 Кол-во: {safe_int(item.get('count', 0))} шт.\n"
            price_sale = safe_float(item.get('price_sale', 0))
            count = safe_int(item.get('count', 0))
            sale_sum = price_sale * count
            total += sale_sum
            result += f"💰 Сумма: {sale_sum:,.2f} ₽\n"
            result += "─" * 25 + "\n"
        result += f"\n💰 Общая выручка: {total:,.2f} ₽"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {response.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())
    await state.clear()

@dp.message(F.text == "💲 Тарифы")
async def show_tariffs(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка тарифов...")
    response = await api.get_tariffs()
    await msg.delete()
    await message.answer(format_tariffs(response), reply_markup=get_main_keyboard())

@dp.message(F.text == "📅 Группы тарифов")
async def show_tariff_groups(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка групп тарифов...")
    response = await api.get_tariff_groups()
    await msg.delete()
    if response.get("status") and response.get("data"):
        result = "📅 ГРУППЫ ТАРИФОВ (ТИПЫ ДНЕЙ)\n\n"
        for item in response["data"]:
            result += f"🆔 ID: {item.get('id')}\n📝 {item.get('name')}\n"
            result += f"📆 Дни: {item.get('days', 'N/A')}\n"
            if item.get('color'):
                result += f"🎨 Цвет: {item.get('color')}\n"
            result += "─" * 25 + "\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {response.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

@dp.message(F.text == "🏷️ Типы тарифов")
async def show_tariff_types(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка типов тарифов...")
    response = await api.get_tariff_types()
    await msg.delete()
    if response.get("status") and response.get("data"):
        result = "🏷️ ТИПЫ ТАРИФОВ\n\n"
        type_icons = {"basic": "⭐", "packet": "📦", "subscription": "📅"}
        for item in response["data"]:
            ttype = item.get('type', 'basic')
            result += f"{type_icons.get(ttype, '📌')} {item.get('name')}\n"
            result += f"🆔 ID: {item.get('id')}\n"
            result += f"📋 Тип: {ttype}\n"
            if item.get('duration'):
                result += f"⏱️ Длительность: {item.get('duration')} мин\n"
            result += "─" * 25 + "\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {response.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

@dp.message(F.text == "👨‍💼 Администраторы")
async def show_users(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка списка администраторов...")
    response = await api.get_users_list()
    await msg.delete()
    await message.answer(format_users_list(response), reply_markup=get_main_keyboard())

@dp.message(F.text == "⚙️ Конфигурация")
async def show_config(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка конфигурации...")
    response = await api.get_config()
    await msg.delete()
    if response.get("status") and response.get("data"):
        result = "⚙️ ГЛОБАЛЬНАЯ КОНФИГУРАЦИЯ\n\n"
        for item in response["data"][:20]:
            if item.get('param_name_rus'):
                result += f"📌 {item.get('param_name_rus')}\n"
            result += f"🔧 {item.get('param_name')}: {item.get('value', 'N/A')}\n"
            result += "─" * 25 + "\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {response.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

@dp.message(F.text == "📁 Профили PUF")
async def show_puf_profiles(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка профилей PUF...")
    response = await api.get_puf_profiles()
    await msg.delete()
    if response.get("status") and response.get("data"):
        result = "📁 ПРОФИЛИ ЛИЧНЫХ ФАЙЛОВ (PUF)\n\n"
        for item in response["data"]:
            result += f"🆔 ID: {item.get('id')}\n📝 {item.get('name')}\n"
            if item.get('paths'):
                result += f"📂 Пути: {', '.join(item.get('paths', []))}\n"
            result += "─" * 25 + "\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {response.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

@dp.message(F.text == "🔌 Маршруты")
async def show_routes(message: types.Message):
    msg = await message.answer("🔄 Загрузка доступных маршрутов...")
    response = await api.get_routes()
    await msg.delete()
    if response.get("status") and response.get("data"):
        result = "🔌 ДОСТУПНЫЕ МАРШРУТЫ\n\n"
        for item in response["data"][:25]:
            result += f"🔹 {item.get('method')} {item.get('path')}\n"
            result += f"   📋 {item.get('summary', 'Без описания')}\n"
            result += "─" * 25 + "\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {response.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

@dp.message(F.text == "📱 Админ ПО")
async def show_admin_config(message: types.Message):
    msg = await message.answer("🔄 Загрузка конфигурации админ ПО...")
    response = await api.get_admin_console_config()
    await msg.delete()
    if response.get("status") and response.get("data"):
        result = "📱 КОНФИГУРАЦИЯ АДМИН ПО\n\n"
        for item in response["data"]:
            for key, value in item.items():
                if value:
                    result += f"🔧 {key}: {value}\n"
            result += "─" * 25 + "\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {response.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

@dp.message(F.text == "💻 Терминал")
async def show_terminal_config(message: types.Message):
    msg = await message.answer("🔄 Загрузка конфигурации терминала...")
    response = await api.get_terminal_config()
    await msg.delete()
    if response.get("status") and response.get("data"):
        result = "💻 КОНФИГУРАЦИЯ ТЕРМИНАЛА\n\n"
        for item in response["data"]:
            for key, value in item.items():
                if value:
                    result += f"🔧 {key}: {value}\n"
            result += "─" * 25 + "\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {response.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

@dp.message()
async def handle_unknown(message: types.Message):
    if not message.text.startswith("/") and not any(message.text == btn for row in get_main_keyboard().keyboard for btn in row):
        await message.answer("❓ Используйте кнопки меню или /help", reply_markup=get_main_keyboard())

async def main():
    logger.info("🚀 LANGAME Telegram Bot starting...")
    await bot.delete_webhook(drop_pending_updates=True)
    if API_KEY:
        test_result = await api.test_connection()
        logger.info(f"API connection: {'✅ OK' if test_result.get('success') else '❌ Failed'}")
    logger.info("🎉 Bot is ready!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())