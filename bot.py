import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any

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

ALLOWED_USERS = [int(x) for x in os.getenv("ALLOWED_USERS", "").split(",") if x] if os.getenv("ALLOWED_USERS") else []

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

class BalanceTopupState(StatesGroup):
    waiting_for_phone = State()
    waiting_for_amount = State()
    waiting_for_comment = State()

class PcManageState(StatesGroup):
    waiting_for_uuids = State()

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def safe_float(value: Any, default: float = 0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default

def safe_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

def format_currency(amount: Any) -> str:
    try:
        return f"{safe_float(amount):,.2f} ₽"
    except:
        return f"{amount} ₽"

def is_admin(user_id: int) -> bool:
    if not ALLOWED_USERS:
        return True
    return user_id in ALLOWED_USERS

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
                    async with session.post(url, headers=self.headers, json=data, params=params, timeout=timeout) as resp:
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
    
    async def get_guests_list(self, page: int = 1, limit: int = 20) -> Dict:
        return await self.request("/guests/list", params={"page": page, "page_limit": limit})
    
    async def search_guest(self, search_data: Dict) -> Dict:
        return await self.request("/guests/search", method="POST", data=search_data)
    
    async def get_guest_by_phone(self, phone: str) -> Dict:
        search_data = {
            "filter": {"phone": phone},
            "pagination": {"page": 1, "size": 1},
            "featues": {"fields": ["guest_id", "fio", "phone", "balance"]}
        }
        return await self.request("/guests/search", method="POST", data=search_data)
    
    async def get_guest_groups(self) -> Dict:
        return await self.request("/guests/groups")
    
    async def get_guest_sessions(self, guest_id: int = None, page: int = 1, limit: int = 20) -> Dict:
        params = {"page": page, "page_limit": limit}
        if guest_id:
            params["guest_id"] = guest_id
        return await self.request("/guests/sessions", params=params)
    
    async def get_guests_balance(self, page: int = 1, limit: int = 20) -> Dict:
        return await self.request("/guests/balance", params={"page": page, "page_limit": limit})
    
    async def get_bonus_balance(self, page: int = 1, limit: int = 20) -> Dict:
        return await self.request("/guests/bonus_balance", params={"page": page, "page_limit": limit})
    
    async def update_guest_balance_by_phone(self, phone: str, amount: float, comment: str = None) -> Dict:
        """Пополнение/списание баланса гостя по номеру телефона"""
        data = {
            "phone": phone,
            "type": "balance",
            "sum": float(amount)
        }
        if comment:
            data["comment"] = comment
        return await self.request("/guest/balance", method="POST", data=data)
    
    async def manage_pc(self, command: str, club_id: int = None, uuids: list = None, pc_type: str = "free") -> Dict:
        data = {"command": command, "type": pc_type}
        if club_id:
            data["club_id"] = club_id
        if uuids:
            data["uuids"] = uuids
        return await self.request("/pc/manage", method="POST", data=data)
    
    async def get_transactions(self, date_from: str = None, date_to: str = None, page: int = 1, limit: int = 20) -> Dict:
        params = {"page": page, "page_limit": limit}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        return await self.request("/transactions/list", params=params)
    
    async def get_operations_log(self, date_from: str = None, date_to: str = None) -> Dict:
        params = {}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
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
    
    async def get_products_expense(self, date_from: str = None, date_to: str = None, page: int = 1, limit: int = 20) -> Dict:
        params = {"page": page, "page_limit": limit}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        return await self.request("/products/expense", params=params)
    
    async def get_tariffs(self) -> Dict:
        return await self.request("/tariffs/time_period/list")
    
    async def get_tariff_groups(self) -> Dict:
        return await self.request("/tariffs/groups/list")
    
    async def get_tariff_types(self) -> Dict:
        return await self.request("/tariffs/types_groups/list")
    
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

# ========== КЛАВИАТУРА ==========
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
        [KeyboardButton(text="📱 Админ ПО"), KeyboardButton(text="💻 Терминал")],
        [KeyboardButton(text="💰 Пополнить баланс"), KeyboardButton(text="💸 Списать баланс")],
        [KeyboardButton(text="🖥️ Технический старт"), KeyboardButton(text="🔓 Ручная разблокировка")],
        [KeyboardButton(text="🔒 Блокировка ПК"), KeyboardButton(text="🔄 Перезагрузка ПК")],
        [KeyboardButton(text="🛑 Тех. остановка"), KeyboardButton(text="🔌 Включить ПК")],
        [KeyboardButton(text="⛔ Выключить ПК")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_search_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 По телефону", callback_data="search_phone")],
        [InlineKeyboardButton(text="🆔 По ID", callback_data="search_id")],
        [InlineKeyboardButton(text="📝 По ФИО", callback_data="search_name")]
    ])

# ========== ФОРМАТТЕРЫ (сокращенные для читаемости) ==========
def format_clubs(data: Dict) -> str:
    if not data.get("status"):
        return f"❌ Ошибка: {data.get('error', 'Неизвестная ошибка')}"
    items = data.get("data", [])
    if not items:
        return "🏢 Клубы не найдены"
    result = "🏢 СПИСОК КЛУБОВ\n\n"
    for club in items:
        result += f"{'🟢' if club.get('active') else '🔴'} {club.get('name', 'Без названия')} (ID: {club.get('id')})\n"
        if club.get('address'):
            result += f"   📍 {club.get('address')}\n"
        result += "\n"
    return result

def format_guests_list(data: Dict) -> str:
    if not data.get("status"):
        return f"❌ Ошибка: {data.get('error', 'Неизвестная ошибка')}"
    items = data.get("data", [])
    if not items:
        return "👤 Гости не найдены"
    result = "👤 СПИСОК ГОСТЕЙ\n\n"
    for guest in items[:15]:
        result += f"🆔 ID: {guest.get('guest_id')}\n📝 {guest.get('fio', 'Не указано')}\n📱 {guest.get('phone', 'Не указан')}\n"
        result += "─" * 25 + "\n"
    return result

def format_balances(data: Dict, title: str = "БАЛАНСЫ") -> str:
    if not data.get("status"):
        return f"❌ Ошибка: {data.get('error', 'Неизвестная ошибка')}"
    items = data.get("data", [])
    if not items:
        return f"📭 {title} не найдены"
    result = f"💰 {title}\n\n"
    total = 0
    for item in items[:20]:
        balance = safe_float(item.get('balance', 0)) if "balance" in item else safe_float(item.get('bonus_balance', 0))
        total += balance
        result += f"• Гость #{item.get('guest_id')}: {balance:,.2f} {'₽' if 'balance' in item else 'бонусов'}\n"
    result += f"\n💰 Общая сумма: {total:,.2f} {'₽' if 'balance' in items[0] else 'бонусов'}"
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
        amount = safe_float(item.get('balance', 0))
        if amount > 0:
            total += amount
        result += f"📅 {item.get('date_update', 'N/A')[:16]}\n💰 {'+' if amount > 0 else ''}{amount:,.2f} ₽\n" + "─" * 25 + "\n"
    result += f"\n💰 Общая сумма: {total:,.2f} ₽"
    return result

def format_operations_log(data: Dict) -> str:
    if not data.get("status"):
        return f"❌ Ошибка: {data.get('error', 'Неизвестная ошибка')}"
    items = data.get("data", [])
    if not items:
        return "📭 Операции не найдены"
    result = "📋 ЛОГ ОПЕРАЦИЙ\n\n"
    income, expense = 0, 0
    for item in items[:20]:
        op_sum = safe_float(item.get('sum', 0))
        if item.get('type') == "Пополнение":
            income += op_sum
        else:
            expense += abs(op_sum)
        result += f"{'💰' if item.get('type') == 'Пополнение' else '💸'} {item.get('date_normal', 'N/A')[:16]}\n   💵 {op_sum:,.2f} ₽\n" + "─" * 25 + "\n"
    result += f"\n📊 ИТОГИ:\n💰 Пополнения: {income:,.2f} ₽\n💸 Списания: {expense:,.2f} ₽\n📈 Сальдо: {income - expense:,.2f} ₽"
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
async def show_guests(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка...")
    response = await api.get_guests_list()
    await msg.delete()
    await message.answer(format_guests_list(response), reply_markup=get_main_keyboard())

@dp.message(F.text == "👥 Группы гостей")
async def show_groups(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка...")
    response = await api.get_guest_groups()
    await msg.delete()
    if response.get("status") and response.get("data"):
        result = "👥 ГРУППЫ ГОСТЕЙ\n\n"
        for group in response["data"]:
            result += f"🆔 ID: {group.get('id')}\n📝 {group.get('name')}\n"
            if group.get('percent'):
                result += f"💰 Скидка: {group.get('percent')}%\n"
            result += "─" * 25 + "\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {response.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

@dp.message(F.text == "👤 Поиск гостя")
async def search_prompt(message: types.Message):
    await message.answer("🔍 ВЫБЕРИТЕ СПОСОБ ПОИСКА:", reply_markup=get_search_keyboard())

@dp.callback_query(lambda c: c.data.startswith("search_"))
async def process_search(callback: types.CallbackQuery, state: FSMContext):
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
        "featues": {"fields": ["guest_id", "fio", "phone"], "balance": True}
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
            result += f"🆔 ID: {guest.get('guest_id')}\n📝 ФИО: {guest.get('fio', 'Не указано')}\n📱 Телефон: {guest.get('phone', 'Не указан')}\n"
            if guest.get("balance"):
                result += f"💰 Баланс: {format_currency(guest['balance'].get('amount', 0))}\n"
            result += "─" * 25 + "\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer("❌ Гость не найден", reply_markup=get_main_keyboard())
    await state.clear()

@dp.message(F.text == "🎮 Сессии")
async def sessions_prompt(message: types.Message):
    await message.answer("🎮 Введите ID гостя:")
    await SessionsState.waiting_for_guest_id.set()

@dp.message(StateFilter(SessionsState.waiting_for_guest_id))
async def show_sessions(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введите число!")
        return
    msg = await message.answer(f"🔄 Загрузка...")
    response = await api.get_guest_sessions(guest_id=int(message.text))
    await msg.delete()
    if response.get("status") and response.get("data"):
        result = f"🎮 СЕССИИ ГОСТЯ #{message.text}\n\n"
        for session in response["data"][:10]:
            result += f"📅 Начало: {session.get('date_start', 'N/A')[:16]}\n"
            result += f"⏱️ Окончание: {session.get('date_stop', 'Активна')[:16]}\n"
            result += f"📊 {'✅ Завершена' if session.get('normal_stop') else '🟢 Активна'}\n"
            result += "─" * 25 + "\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {response.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())
    await state.clear()

@dp.message(F.text == "💰 Балансы")
async def show_balances(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка...")
    response = await api.get_guests_balance()
    await msg.delete()
    await message.answer(format_balances(response, "БАЛАНСЫ ГОСТЕЙ"), reply_markup=get_main_keyboard())

@dp.message(F.text == "🎁 Бонусы")
async def show_bonus(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка...")
    response = await api.get_bonus_balance()
    await msg.delete()
    await message.answer(format_balances(response, "БОНУСНЫЕ БАЛАНСЫ"), reply_markup=get_main_keyboard())

@dp.message(F.text == "💸 Транзакции")
async def show_transactions(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка за 30 дней...")
    date_to = datetime.now().strftime("%Y-%m-%d")
    date_from = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    response = await api.get_transactions(date_from, date_to)
    await msg.delete()
    await message.answer(format_transactions(response), reply_markup=get_main_keyboard())

@dp.message(F.text == "📋 Лог операций")
async def show_operations(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка за 30 дней...")
    date_to = datetime.now().strftime("%Y-%m-%d")
    date_from = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    response = await api.get_operations_log(date_from, date_to)
    await msg.delete()
    await message.answer(format_operations_log(response), reply_markup=get_main_keyboard())

@dp.message(F.text == "📊 Смены")
async def show_shifts(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка...")
    response = await api.get_working_shifts()
    await msg.delete()
    if response.get("status") and response.get("data"):
        result = "📊 СПИСОК СМЕН\n\n"
        for shift in response["data"][:10]:
            result += f"🆔 Смена #{shift.get('id')}\n"
            result += f"📅 Открыта: {shift.get('date_start', 'N/A')[:16]}\n"
            result += f"💰 Наличные: {safe_float(shift.get('nal', 0)):,.2f} ₽\n"
            result += f"💳 Безналичные: {safe_float(shift.get('beznal', 0)):,.2f} ₽\n"
            result += "─" * 25 + "\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {response.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

@dp.message(F.text == "🖥️ Компьютеры")
async def show_pc(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка...")
    response = await api.get_pc_list()
    await msg.delete()
    await message.answer(format_pc_list(response), reply_markup=get_main_keyboard())

@dp.message(F.text == "🍔 Товары")
async def show_products(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка...")
    response = await api.get_products_list()
    await msg.delete()
    if response.get("status") and response.get("data"):
        result = "🍔 СПИСОК ТОВАРОВ\n\n"
        for product in response["data"][:20]:
            result += f"🆔 ID: {product.get('id')}\n📝 {product.get('name', 'Без названия')}\n"
            result += f"{'🟢 Активен' if product.get('active') else '🔴 Неактивен'}\n"
            result += "─" * 25 + "\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {response.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

@dp.message(F.text == "💲 Тарифы")
async def show_tariffs(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка...")
    response = await api.get_tariffs()
    await msg.delete()
    if response.get("status") and response.get("data"):
        result = "💲 ТАРИФЫ\n\n"
        for tariff in response["data"][:15]:
            result += f"🆔 ID: {tariff.get('id')}\n💰 Цена: {safe_float(tariff.get('price', 0)):,.2f} ₽\n"
            result += "─" * 25 + "\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {response.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

# ========== УПРАВЛЕНИЕ БАЛАНСОМ ==========
@dp.message(F.text == "💰 Пополнить баланс")
async def topup_balance(message: types.Message, state: FSMContext):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав для выполнения этой операции!")
        return
    await state.update_data(operation="topup")
    await state.set_state(BalanceTopupState.waiting_for_phone)
    await message.answer("📱 Введите номер телефона гостя (например: 9001234567):")

@dp.message(F.text == "💸 Списать баланс")
async def withdraw_balance(message: types.Message, state: FSMContext):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав для выполнения этой операции!")
        return
    await state.update_data(operation="withdraw")
    await state.set_state(BalanceTopupState.waiting_for_phone)
    await message.answer("📱 Введите номер телефона гостя (например: 9001234567):")

@dp.message(StateFilter(BalanceTopupState.waiting_for_phone))
async def balance_phone_handler(message: types.Message, state: FSMContext):
    phone = message.text.strip()
    phone = ''.join(filter(str.isdigit, phone))
    if len(phone) < 10:
        await message.answer("❌ Введите корректный номер телефона (10-11 цифр)!")
        return
    
    msg = await message.answer(f"🔍 Проверка гостя с номером {phone}...")
    search_result = await api.get_guest_by_phone(phone)
    await msg.delete()
    
    if not search_result.get("items"):
        await message.answer(f"❌ Гость с номером {phone} не найден!")
        await state.clear()
        return
    
    guest = search_result["items"][0]
    guest_name = guest.get('fio', 'Не указано')
    guest_id = guest.get('guest_id')
    
    await state.update_data(phone=phone, guest_id=guest_id, guest_name=guest_name)
    await state.set_state(BalanceTopupState.waiting_for_amount)
    await message.answer(f"👤 Найден гость: {guest_name} (ID: {guest_id})\n\n💰 Введите сумму (положительное число):")

@dp.message(StateFilter(BalanceTopupState.waiting_for_amount))
async def balance_amount_handler(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0:
            await message.answer("❌ Сумма должна быть положительной!")
            return
    except ValueError:
        await message.answer("❌ Введите корректную сумму (число)!")
        return
    
    data = await state.get_data()
    operation = data.get("operation", "topup")
    final_amount = amount if operation == "topup" else -amount
    
    await state.update_data(amount=final_amount)
    await state.set_state(BalanceTopupState.waiting_for_comment)
    await message.answer(f"💰 Сумма: {final_amount:+,.2f} ₽\n\n📝 Введите комментарий к операции (или 'нет' для пропуска):")

@dp.message(StateFilter(BalanceTopupState.waiting_for_comment))
async def balance_comment_handler(message: types.Message, state: FSMContext):
    data = await state.get_data()
    comment = None if message.text.lower() == "нет" else message.text
    
    msg = await message.answer(f"🔄 Выполняется операция для гостя {data['guest_name']} на сумму {data['amount']} ₽...")
    
    response = await api.update_guest_balance_by_phone(
        phone=data['phone'],
        amount=data['amount'],
        comment=comment
    )
    
    await msg.delete()
    
    if response.get("status"):
        operation_text = "ПОПОЛНЕНИЕ" if data['amount'] > 0 else "СПИСАНИЕ"
        await message.answer(
            f"✅ ОПЕРАЦИЯ УСПЕШНО ВЫПОЛНЕНА!\n\n"
            f"{operation_text}\n"
            f"👤 Гость: {data['guest_name']} (ID: {data['guest_id']})\n"
            f"📱 Телефон: {data['phone']}\n"
            f"💰 Сумма: {data['amount']:+,.2f} ₽\n"
            f"📝 Комментарий: {comment or 'Нет'}",
            reply_markup=get_main_keyboard()
        )
    else:
        error_msg = response.get('error', 'Неизвестная ошибка')
        await message.answer(
            f"❌ Ошибка: {error_msg}\n\n"
            f"💡 Возможные причины:\n"
            f"• У API ключа нет прав на эту операцию\n"
            f"• Неправильный формат запроса\n"
            f"• Гость заблокирован",
            reply_markup=get_main_keyboard()
        )
    
    await state.clear()

# ========== УПРАВЛЕНИЕ ПК ==========
PC_COMMANDS = {
    "🖥️ Технический старт": "tech_start",
    "🛑 Тех. остановка": "tech_stop",
    "🔓 Ручная разблокировка": "unlock",
    "🔒 Блокировка ПК": "lock",
    "🔄 Перезагрузка ПК": "reboot",
    "🔌 Включить ПК": "power_on",
    "⛔ Выключить ПК": "power_off"
}

@dp.message(F.text.in_(PC_COMMANDS.keys()))
async def pc_manage(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав для выполнения этой операции!")
        return
    
    command = PC_COMMANDS[message.text]
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖥️ Все свободные ПК", callback_data=f"pc_{command}_free")],
        [InlineKeyboardButton(text="🎮 Все ПК (включая занятые)", callback_data=f"pc_{command}_all")],
        [InlineKeyboardButton(text="📋 Выбрать по UUID", callback_data=f"pc_{command}_uuids")],
        [InlineKeyboardButton(text="◀️ Отмена", callback_data="pc_cancel")]
    ])
    await message.answer(f"🖥️ {message.text}\n\nВыберите режим выполнения:", reply_markup=keyboard)

@dp.callback_query(lambda c: c.data.startswith("pc_"))
async def pc_callback(callback: types.CallbackQuery, state: FSMContext):
    if callback.data == "pc_cancel":
        await callback.message.edit_text("❌ Операция отменена")
        await callback.answer()
        return
    
    parts = callback.data.split("_")
    command = parts[1]
    mode = parts[2]
    
    if mode == "free":
        msg = await callback.message.answer(f"🔄 Выполняется {command} для всех свободных ПК...")
        response = await api.manage_pc(command=command, pc_type="free")
        await msg.delete()
        if response.get("status"):
            await callback.message.answer(f"✅ Команда '{command}' успешно отправлена!", reply_markup=get_main_keyboard())
        else:
            await callback.message.answer(f"❌ Ошибка: {response.get('error', 'Неизвестная ошибка')}", reply_markup=get_main_keyboard())
    
    elif mode == "all":
        msg = await callback.message.answer(f"🔄 Выполняется {command} для ВСЕХ ПК...")
        response = await api.manage_pc(command=command, pc_type="all")
        await msg.delete()
        if response.get("status"):
            await callback.message.answer(f"✅ Команда '{command}' успешно отправлена!", reply_markup=get_main_keyboard())
        else:
            await callback.message.answer(f"❌ Ошибка: {response.get('error', 'Неизвестная ошибка')}", reply_markup=get_main_keyboard())
    
    elif mode == "uuids":
        await state.update_data(pc_command=command)
        await callback.message.answer("📋 Введите UUID ПК (можно несколько через запятую или пробел):\n\n💡 Список UUID можно получить через '🖥️ Компьютеры'")
        await state.set_state(PcManageState.waiting_for_uuids)
    
    await callback.message.delete()
    await callback.answer()

@dp.message(StateFilter(PcManageState.waiting_for_uuids))
async def pc_uuids_handler(message: types.Message, state: FSMContext):
    data = await state.get_data()
    command = data.get("pc_command")
    
    uuids = [uuid.strip() for uuid in message.text.replace(",", " ").split() if uuid.strip()]
    
    if not uuids:
        await message.answer("❌ Не указаны UUID! Попробуйте снова.")
        return
    
    msg = await message.answer(f"🔄 Выполняется {command} для {len(uuids)} ПК...")
    response = await api.manage_pc(command=command, uuids=uuids)
    await msg.delete()
    
    if response.get("status"):
        await message.answer(f"✅ Команда '{command}' успешно отправлена для {len(uuids)} ПК!", reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ Ошибка: {response.get('error', 'Неизвестная ошибка')}", reply_markup=get_main_keyboard())
    
    await state.clear()

# ========== КОРОТКИЕ ОБРАБОТЧИКИ ДЛЯ ОСТАЛЬНЫХ КНОПОК ==========
@dp.message(F.text == "💳 Кассовые операции")
async def cash_prompt(message: types.Message):
    await message.answer("💳 Введите ID клуба:")
    await CashTransactionState.waiting_for_club_id.set()

@dp.message(StateFilter(CashTransactionState.waiting_for_club_id))
async def cash_date_from(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введите число!")
        return
    await state.update_data(club_id=int(message.text))
    await message.answer("📅 Введите дату ОТ (ГГГГ-ММ-ДД):")
    await state.set_state(CashTransactionState.waiting_for_date_from)

@dp.message(StateFilter(CashTransactionState.waiting_for_date_from))
async def cash_date_to(message: types.Message, state: FSMContext):
    await state.update_data(date_from=message.text.strip())
    await message.answer("📅 Введите дату ДО (ГГГГ-ММ-ДД):")
    await state.set_state(CashTransactionState.waiting_for_date_to)

@dp.message(StateFilter(CashTransactionState.waiting_for_date_to))
async def cash_result(message: types.Message, state: FSMContext):
    data = await state.get_data()
    msg = await message.answer("🔄 Загрузка...")
    response = await api.get_cash_transactions(data['club_id'], data['date_from'], message.text.strip())
    await msg.delete()
    if response.get("status") and response.get("data"):
        result = "💳 КАССОВЫЕ ОПЕРАЦИИ\n\n"
        for item in response["data"][:15]:
            result += f"📅 {item.get('date', 'N/A')}\n💰 {safe_float(item.get('sum', 0)):,.2f} ₽\n" + "─" * 25 + "\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {response.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())
    await state.clear()

@dp.message(F.text == "💰 Пополнения")
async def balances_history(message: types.Message):
    await message.answer("📅 Введите дату ОТ (ГГГГ-ММ-ДД):")
    await BalanceHistoryState.waiting_for_date_from.set()

@dp.message(StateFilter(BalanceHistoryState.waiting_for_date_from))
async def history_date_to(message: types.Message, state: FSMContext):
    await state.update_data(date_from=message.text.strip())
    await message.answer("📅 Введите дату ДО (ГГГГ-ММ-ДД):")
    await state.set_state(BalanceHistoryState.waiting_for_date_to)

@dp.message(StateFilter(BalanceHistoryState.waiting_for_date_to))
async def history_result(message: types.Message, state: FSMContext):
    data = await state.get_data()
    msg = await message.answer("🔄 Загрузка...")
    response = await api.get_balances_list(data['date_from'], message.text.strip())
    await msg.delete()
    if response.get("status") and response.get("data"):
        result = "💰 ИСТОРИЯ ПОПОЛНЕНИЙ\n\n"
        for item in response["data"][:15]:
            result += f"📅 {item.get('date', 'N/A')}\n👤 {item.get('guest_name', 'N/A')}\n💰 {format_currency(item.get('amount', 0))}\n" + "─" * 25 + "\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {response.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())
    await state.clear()

@dp.message(F.text == "📦 Остатки")
async def goods_prompt(message: types.Message):
    await message.answer("📦 Введите ID клуба:")
    await GoodsState.waiting_for_club_id.set()

@dp.message(StateFilter(GoodsState.waiting_for_club_id))
async def goods_result(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введите число!")
        return
    msg = await message.answer(f"🔄 Загрузка...")
    response = await api.get_goods_list(int(message.text))
    await msg.delete()
    if response.get("status") and response.get("data"):
        result = f"📦 ОСТАТКИ (клуб #{message.text})\n\n"
        for item in response["data"][:20]:
            result += f"🆔 ID: {item.get('id')}\n📝 {item.get('name', 'Без названия')}\n📦 {safe_int(item.get('count', 0))} шт.\n" + "─" * 25 + "\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {response.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())
    await state.clear()

@dp.message(F.text == "📥 Поступления")
async def show_arrival(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка...")
    response = await api.get_products_arrival()
    await msg.delete()
    if response.get("status") and response.get("data"):
        result = "📥 ПОСТУПЛЕНИЯ\n\n"
        for item in response["data"][:15]:
            result += f"📅 {item.get('date_fact', 'N/A')[:16]}\n🆔 Товар ID: {item.get('list_goods_id')}\n📦 {safe_int(item.get('count', 0))} шт.\n" + "─" * 25 + "\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {response.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

@dp.message(F.text == "📤 Продажи")
async def expense_prompt(message: types.Message):
    await message.answer("📅 Введите дату ОТ (ГГГГ-ММ-ДД) или 'все':")
    await ProductsExpenseState.waiting_for_date_from.set()

@dp.message(StateFilter(ProductsExpenseState.waiting_for_date_from))
async def expense_date_to(message: types.Message, state: FSMContext):
    date_from = None if message.text.lower() == "все" else message.text.strip()
    await state.update_data(date_from=date_from)
    await message.answer("📅 Введите дату ДО (ГГГГ-ММ-ДД) или 'все':")
    await state.set_state(ProductsExpenseState.waiting_for_date_to)

@dp.message(StateFilter(ProductsExpenseState.waiting_for_date_to))
async def expense_result(message: types.Message, state: FSMContext):
    data = await state.get_data()
    date_to = None if message.text.lower() == "все" else message.text.strip()
    msg = await message.answer("🔄 Загрузка...")
    response = await api.get_products_expense(date_from=data.get('date_from'), date_to=date_to)
    await msg.delete()
    if response.get("status") and response.get("data"):
        result = "📤 ПРОДАЖИ\n\n"
        total = 0
        for item in response["data"][:15]:
            sale_sum = safe_float(item.get('price_sale', 0)) * safe_int(item.get('count', 0))
            total += sale_sum
            result += f"📅 {item.get('date', 'N/A')[:16]}\n🆔 Товар ID: {item.get('list_goods_id')}\n📦 {safe_int(item.get('count', 0))} шт.\n💰 {sale_sum:,.2f} ₽\n" + "─" * 25 + "\n"
        result += f"\n💰 Общая выручка: {total:,.2f} ₽"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {response.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())
    await state.clear()

@dp.message(F.text == "📅 Группы тарифов")
async def show_tariff_groups(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка...")
    response = await api.get_tariff_groups()
    await msg.delete()
    if response.get("status") and response.get("data"):
        result = "📅 ГРУППЫ ТАРИФОВ\n\n"
        for item in response["data"]:
            result += f"🆔 ID: {item.get('id')}\n📝 {item.get('name')}\n📆 Дни: {item.get('days', 'N/A')}\n" + "─" * 25 + "\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {response.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

@dp.message(F.text == "🏷️ Типы тарифов")
async def show_tariff_types(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка...")
    response = await api.get_tariff_types()
    await msg.delete()
    if response.get("status") and response.get("data"):
        result = "🏷️ ТИПЫ ТАРИФОВ\n\n"
        for item in response["data"]:
            result += f"{'⭐' if item.get('type') == 'basic' else '📦' if item.get('type') == 'packet' else '📅'} {item.get('name')}\n"
            result += f"🆔 ID: {item.get('id')}\n📋 Тип: {item.get('type')}\n" + "─" * 25 + "\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {response.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

@dp.message(F.text == "👨‍💼 Администраторы")
async def show_users(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка...")
    response = await api.get_users_list()
    await msg.delete()
    if response.get("status") and response.get("data"):
        result = "👨‍💼 АДМИНИСТРАТОРЫ\n\n"
        for user in response["data"]:
            result += f"🆔 ID: {user.get('id')}\n📧 {user.get('email')}\n📝 {user.get('username', 'Не указано')}\n" + "─" * 25 + "\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {response.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

@dp.message(F.text == "⚙️ Конфигурация")
async def show_config(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка...")
    response = await api.get_config()
    await msg.delete()
    if response.get("status") and response.get("data"):
        result = "⚙️ КОНФИГУРАЦИЯ\n\n"
        for item in response["data"][:20]:
            result += f"🔧 {item.get('param_name')}: {item.get('value', 'N/A')}\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {response.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

@dp.message(F.text == "📁 Профили PUF")
async def show_puf(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка...")
    response = await api.get_puf_profiles()
    await msg.delete()
    if response.get("status") and response.get("data"):
        result = "📁 ПРОФИЛИ PUF\n\n"
        for item in response["data"]:
            result += f"🆔 ID: {item.get('id')}\n📝 {item.get('name')}\n" + "─" * 25 + "\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {response.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

@dp.message(F.text == "🔌 Маршруты")
async def show_routes(message: types.Message):
    msg = await message.answer("🔄 Загрузка...")
    response = await api.get_routes()
    await msg.delete()
    if response.get("status") and response.get("data"):
        result = "🔌 ДОСТУПНЫЕ МАРШРУТЫ\n\n"
        for item in response["data"][:25]:
            result += f"🔹 {item.get('method')} {item.get('path')}\n   📋 {item.get('summary', 'Без описания')}\n" + "─" * 25 + "\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {response.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

@dp.message(F.text == "📱 Админ ПО")
async def show_admin(message: types.Message):
    msg = await message.answer("🔄 Загрузка...")
    response = await api.get_admin_console_config()
    await msg.delete()
    if response.get("status") and response.get("data"):
        result = "📱 АДМИН ПО\n\n"
        for item in response["data"]:
            for key, value in item.items():
                if value:
                    result += f"🔧 {key}: {value}\n"
            result += "─" * 25 + "\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {response.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

@dp.message(F.text == "💻 Терминал")
async def show_terminal(message: types.Message):
    msg = await message.answer("🔄 Загрузка...")
    response = await api.get_terminal_config()
    await msg.delete()
    if response.get("status") and response.get("data"):
        result = "💻 ТЕРМИНАЛ\n\n"
        for item in response["data"]:
            for key, value in item.items():
                if value:
                    result += f"🔧 {key}: {value}\n"
            result += "─" * 25 + "\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {response.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

@dp.message(F.text == "🎮 Типы ПК")
async def show_pc_types(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка...")
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

# ========== ОБРАБОТЧИК НЕИЗВЕСТНЫХ СООБЩЕНИЙ ==========
@dp.message()
async def handle_unknown(message: types.Message):
    if not message.text.startswith("/"):
        await message.answer("❓ Используйте кнопки меню или /help", reply_markup=get_main_keyboard())

# ========== ЗАПУСК ==========
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