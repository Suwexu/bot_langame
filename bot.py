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
ALLOWED_USERS = [int(x) for x in os.getenv("ALLOWED_USERS", "").split(",") if x]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не указан!")

# ========== СОСТОЯНИЯ ==========
class BalanceState(StatesGroup):
    waiting_phone = State()
    waiting_amount = State()
    waiting_comment = State()

class SearchState(StatesGroup):
    waiting_input = State()

class SessionsState(StatesGroup):
    waiting_guest_id = State()

class CashState(StatesGroup):
    waiting_club_id = State()
    waiting_date_from = State()
    waiting_date_to = State()

class GoodsState(StatesGroup):
    waiting_club_id = State()

class ExpenseState(StatesGroup):
    waiting_date_from = State()
    waiting_date_to = State()

class HistoryState(StatesGroup):
    waiting_date_from = State()
    waiting_date_to = State()

class PcUuidsState(StatesGroup):
    waiting_uuids = State()

# ========== ИНИЦИАЛИЗАЦИЯ ==========
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def is_admin(user_id: int) -> bool:
    if not ALLOWED_USERS:
        return True
    return user_id in ALLOWED_USERS

def safe_str(value: Any) -> str:
    if value is None:
        return "Нет данных"
    return str(value)

# ========== API КЛИЕНТ ==========
class LangameAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = f"{API_BASE_URL}/public_api"
        self.headers = {"X-Request-Token": api_key, "Content-Type": "application/json"}
    
    async def _request(self, endpoint: str, method: str = "GET", params: Dict = None, data: Dict = None) -> Dict:
        url = f"{self.base_url}{endpoint}"
        try:
            async with aiohttp.ClientSession() as session:
                if method == "GET":
                    async with session.get(url, headers=self.headers, params=params, timeout=60) as resp:
                        return await resp.json() if resp.status == 200 else {"status": False, "error": f"HTTP {resp.status}"}
                else:
                    async with session.post(url, headers=self.headers, params=params, json=data, timeout=60) as resp:
                        return await resp.json() if resp.status == 200 else {"status": False, "error": f"HTTP {resp.status}"}
        except Exception as e:
            return {"status": False, "error": str(e)}
    
    async def test_api(self) -> Dict:
        return await self._request("/all_operations_log/list", params={"date_from": "2024-01-01", "date_to": "2024-01-02"})
    
    async def get_clubs(self) -> Dict:
        return await self._request("/clubs/list")
    
    async def get_guests(self, page: int = 1) -> Dict:
        return await self._request("/guests/list", params={"page": page, "page_limit": 20})
    
    async def search_guest(self, query: str, search_type: str) -> Dict:
        payload = {"pagination": {"page": 1, "size": 10}, "featues": {"fields": ["guest_id", "fio", "phone", "balance"]}}
        if search_type == "phone":
            payload["filter"] = {"phone": query}
        elif search_type == "id":
            payload["filter"] = {"ids": [int(query)]}
        else:
            payload["filter"] = {"query": query}
        return await self._request("/guests/search", method="POST", data=payload)
    
    async def get_guest_by_phone(self, phone: str) -> Dict:
        payload = {"filter": {"phone": phone}, "pagination": {"page": 1, "size": 1}}
        return await self._request("/guests/search", method="POST", data=payload)
    
    async def get_groups(self) -> Dict:
        return await self._request("/guests/groups")
    
    async def get_sessions(self, guest_id: int) -> Dict:
        return await self._request("/guests/sessions", params={"guest_id": guest_id, "page_limit": 10})
    
    async def get_balances(self) -> Dict:
        return await self._request("/guests/balance", params={"page_limit": 20})
    
    async def get_bonus(self) -> Dict:
        return await self._request("/guests/bonus_balance", params={"page_limit": 20})
    
    async def get_transactions(self, days: int = 30) -> Dict:
        date_to = datetime.now().strftime("%Y-%m-%d")
        date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        return await self._request("/transactions/list", params={"date_from": date_from, "date_to": date_to, "page_limit": 20})
    
    async def get_operations(self, days: int = 30) -> Dict:
        date_to = datetime.now().strftime("%Y-%m-%d")
        date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        return await self._request("/all_operations_log/list", params={"date_from": date_from, "date_to": date_to})
    
    async def get_cash(self, club_id: int, date_from: str, date_to: str) -> Dict:
        return await self._request("/log_cash_transaction/list", params={"club_id": club_id, "date_from": date_from, "date_to": date_to})
    
    async def get_shifts(self) -> Dict:
        return await self._request("/working_shifts/list", params={"page_limit": 10})
    
    async def get_balance_history(self, date_from: str, date_to: str) -> Dict:
        return await self._request("/balances/list", params={"date_from": date_from, "date_to": date_to, "page_limit": 20})
    
    async def get_pcs(self) -> Dict:
        return await self._request("/global/linking_pc_by_type/list")
    
    async def get_pc_types(self) -> Dict:
        return await self._request("/global/types_of_pc_in_clubs/list")
    
    async def get_products(self) -> Dict:
        return await self._request("/products/list")
    
    async def get_goods(self, club_id: int) -> Dict:
        return await self._request("/goods/list", params={"club_id": club_id})
    
    async def get_arrivals(self) -> Dict:
        return await self._request("/products/arrival", params={"page_limit": 20})
    
    async def get_expenses(self, date_from: str = None, date_to: str = None) -> Dict:
        params = {"page_limit": 20}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        return await self._request("/products/expense", params=params)
    
    async def get_tariffs(self) -> Dict:
        return await self._request("/tariffs/time_period/list")
    
    async def get_tariff_groups(self) -> Dict:
        return await self._request("/tariffs/groups/list")
    
    async def get_tariff_types(self) -> Dict:
        return await self._request("/tariffs/types_groups/list")
    
    async def get_users(self) -> Dict:
        return await self._request("/users/list")
    
    async def get_config(self) -> Dict:
        return await self._request("/config/list")
    
    async def get_puf(self) -> Dict:
        return await self._request("/puf/profiles/list")
    
    async def get_routes(self) -> Dict:
        return await self._request("/routes")
    
    async def get_admin_console(self) -> Dict:
        return await self._request("/ver/get_adminconsole")
    
    async def get_terminal(self) -> Dict:
        return await self._request("/ver/get_terminal")
    
    async def update_balance(self, phone: str, amount: float, comment: str = None) -> Dict:
        data = {"phone": phone, "type": "balance", "sum": amount}
        if comment:
            data["comment"] = comment
        return await self._request("/guest/balance", method="POST", data=data)
    
    async def manage_pc(self, command: str, pc_type: str = "free", uuids: list = None) -> Dict:
        data = {"command": command, "type": pc_type}
        if uuids:
            data["uuids"] = uuids
        return await self._request("/pc/manage", method="POST", data=data)

api = LangameAPI(API_KEY if API_KEY else "")

# ========== КЛАВИАТУРЫ ==========
def get_main_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="🔌 Проверить API"), KeyboardButton(text="ℹ️ О боте")],
        [KeyboardButton(text="🏢 Клубы"), KeyboardButton(text="👥 Группы")],
        [KeyboardButton(text="👤 Гости"), KeyboardButton(text="👤 Поиск гостя")],
        [KeyboardButton(text="💰 Балансы"), KeyboardButton(text="🎁 Бонусы")],
        [KeyboardButton(text="💸 Транзакции"), KeyboardButton(text="📋 Лог операций")],
        [KeyboardButton(text="💳 Касса"), KeyboardButton(text="📊 Смены")],
        [KeyboardButton(text="💰 Пополнения"), KeyboardButton(text="🖥️ ПК")],
        [KeyboardButton(text="🎮 Типы ПК"), KeyboardButton(text="🍔 Товары")],
        [KeyboardButton(text="📦 Остатки"), KeyboardButton(text="📥 Поступления")],
        [KeyboardButton(text="📤 Продажи"), KeyboardButton(text="💲 Тарифы")],
        [KeyboardButton(text="📅 Группы тарифов"), KeyboardButton(text="🏷️ Типы тарифов")],
        [KeyboardButton(text="👨‍💼 Админы"), KeyboardButton(text="⚙️ Конфиг")],
        [KeyboardButton(text="📁 PUF"), KeyboardButton(text="🔌 Маршруты")],
        [KeyboardButton(text="📱 Админ ПО"), KeyboardButton(text="💻 Терминал")],
        [KeyboardButton(text="💰 Пополнить"), KeyboardButton(text="💸 Списать")],
        [KeyboardButton(text="🖥️ Техстарт"), KeyboardButton(text="🔓 Разблокировка")],
        [KeyboardButton(text="🔒 Блокировка"), KeyboardButton(text="🔄 Ребут")],
        [KeyboardButton(text="🛑 Техстоп"), KeyboardButton(text="🔌 Вкл ПК")],
        [KeyboardButton(text="⛔ Выкл ПК")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_search_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 По телефону", callback_data="search_phone")],
        [InlineKeyboardButton(text="🆔 По ID", callback_data="search_id")],
        [InlineKeyboardButton(text="📝 По ФИО", callback_data="search_name")]
    ])

def get_pc_keyboard(command: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖥️ Свободные ПК", callback_data=f"pc_{command}_free")],
        [InlineKeyboardButton(text="🎮 Все ПК", callback_data=f"pc_{command}_all")],
        [InlineKeyboardButton(text="📋 По UUID", callback_data=f"pc_{command}_uuids")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="pc_cancel")]
    ])

# ========== ФОРМАТТЕРЫ ==========
def format_result(data: Dict, title: str, fields: list) -> str:
    if not data.get("status"):
        return f"❌ {data.get('error', 'Ошибка')}"
    items = data.get("data", [])
    if not items:
        return f"📭 {title} не найдены"
    result = f"📋 {title}\n\n"
    for item in items[:15]:
        for field in fields:
            value = item.get(field, "—")
            if field in ["balance", "bonus_balance", "sum", "amount"] and isinstance(value, (int, float)):
                result += f"💰 {field}: {value:,.2f} ₽\n"
            else:
                result += f"📌 {field}: {safe_str(value)}\n"
        result += "─" * 25 + "\n"
    return result

def format_operations(data: Dict) -> str:
    if not data.get("status"):
        return f"❌ {data.get('error', 'Ошибка')}"
    items = data.get("data", [])
    if not items:
        return "📭 Операции не найдены"
    result = "📋 ЛОГ ОПЕРАЦИЙ\n\n"
    income = expense = 0
    for item in items[:20]:
        date = item.get('date_normal', '')[:16]
        op_type = item.get('type', '')
        op_sum = item.get('sum', 0)
        if isinstance(op_sum, str):
            try:
                op_sum = float(op_sum)
            except:
                op_sum = 0
        if op_type == "Пополнение":
            income += op_sum
        else:
            expense += abs(op_sum)
        result += f"{'💰' if op_type == 'Пополнение' else '💸'} {date}\n"
        result += f"   📋 {op_type}\n"
        result += f"   💵 {op_sum:,.2f} ₽\n"
        if item.get('club_name'):
            result += f"   📍 {item.get('club_name')}\n"
        result += "─" * 25 + "\n"
    result += f"\n📊 ИТОГИ:\n💰 Пополнения: {income:,.2f} ₽\n💸 Списания: {expense:,.2f} ₽\n📈 Сальдо: {income - expense:,.2f} ₽"
    return result

def format_guests(data: Dict) -> str:
    if not data.get("status"):
        return f"❌ {data.get('error', 'Ошибка')}"
    items = data.get("data", [])
    if not items:
        return "👤 Гости не найдены"
    result = "👤 ГОСТИ\n\n"
    for guest in items[:15]:
        result += f"🆔 ID: {guest.get('guest_id')}\n"
        result += f"📝 ФИО: {guest.get('fio', '—')}\n"
        result += f"📱 Телефон: {guest.get('phone', '—')}\n"
        bal = guest.get('balance', 0)
        if isinstance(bal, (int, float)):
            result += f"💰 Баланс: {bal:,.2f} ₽\n"
        result += "─" * 25 + "\n"
    return result

def format_pcs(data: Dict) -> str:
    if not data.get("status"):
        return f"❌ {data.get('error', 'Ошибка')}"
    items = data.get("data", [])
    if not items:
        return "🖥️ ПК не найдены"
    result = "🖥️ КОМПЬЮТЕРЫ\n\n"
    for pc in items[:20]:
        result += f"{'🎮' if pc.get('isPS') else '🖥️'} {pc.get('name', 'Без имени')}\n"
        if pc.get('fiscal_name'):
            result += f"   📍 {pc.get('fiscal_name')}\n"
        uuid_val = pc.get('UUID', '')
        result += f"   🆔 UUID: {uuid_val[:16]}...\n" if uuid_val else ""
        result += "─" * 25 + "\n"
    return result

# ========== ОБРАБОТЧИКИ ==========
@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("🎮 LANGAME БОТ\n\nИспользуйте кнопки ниже 👇", reply_markup=get_main_keyboard())

@dp.message(F.text == "🔌 Проверить API")
async def test_api(message: types.Message):
    if not API_KEY:
        await message.answer("❌ API ключ не настроен!")
        return
    msg = await message.answer("🔄 Проверка...")
    result = await api.test_api()
    await msg.delete()
    if result.get("status"):
        await message.answer("✅ API РАБОТАЕТ!\n\n📊 Статус: Ok\n🔑 API Key: Настроен\n🌐 URL: https://cyberx302.langame.ru/public_api", reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ Ошибка: {result.get('error', 'Неизвестная ошибка')}", reply_markup=get_main_keyboard())

@dp.message(F.text == "ℹ️ О боте")
async def about(message: types.Message):
    await message.answer("🤖 LANGAME БОТ v3.0\n📍 Все команды API\n🔐 Для операций с балансом и ПК нужны права", reply_markup=get_main_keyboard())

# ========== ПРОСТЫЕ КОМАНДЫ ==========
@dp.message(F.text == "🏢 Клубы")
async def clubs(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка...")
    r = await api.get_clubs()
    await msg.delete()
    await message.answer(format_result(r, "КЛУБЫ", ["id", "name", "address", "active"]), reply_markup=get_main_keyboard())

@dp.message(F.text == "👥 Группы")
async def groups(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка...")
    r = await api.get_groups()
    await msg.delete()
    await message.answer(format_result(r, "ГРУППЫ ГОСТЕЙ", ["id", "name", "percent", "bonus_birthday"]), reply_markup=get_main_keyboard())

@dp.message(F.text == "👤 Гости")
async def guests(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка...")
    r = await api.get_guests()
    await msg.delete()
    await message.answer(format_guests(r), reply_markup=get_main_keyboard())

@dp.message(F.text == "💰 Балансы")
async def balances(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка...")
    r = await api.get_balances()
    await msg.delete()
    await message.answer(format_result(r, "БАЛАНСЫ", ["guest_id", "balance"]), reply_markup=get_main_keyboard())

@dp.message(F.text == "🎁 Бонусы")
async def bonuses(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка...")
    r = await api.get_bonus()
    await msg.delete()
    await message.answer(format_result(r, "БОНУСЫ", ["guest_id", "bonus_balance"]), reply_markup=get_main_keyboard())

@dp.message(F.text == "💸 Транзакции")
async def transactions(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка за 30 дней...")
    r = await api.get_transactions()
    await msg.delete()
    await message.answer(format_result(r, "ТРАНЗАКЦИИ", ["date_update", "balance", "comment"]), reply_markup=get_main_keyboard())

@dp.message(F.text == "📋 Лог операций")
async def operations(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка за 30 дней...")
    r = await api.get_operations()
    await msg.delete()
    await message.answer(format_operations(r), reply_markup=get_main_keyboard())

@dp.message(F.text == "📊 Смены")
async def shifts(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка...")
    r = await api.get_shifts()
    await msg.delete()
    await message.answer(format_result(r, "СМЕНЫ", ["id", "date_start", "nal", "beznal", "middle_check"]), reply_markup=get_main_keyboard())

@dp.message(F.text == "🖥️ ПК")
async def pcs(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка...")
    r = await api.get_pcs()
    await msg.delete()
    await message.answer(format_pcs(r), reply_markup=get_main_keyboard())

@dp.message(F.text == "🎮 Типы ПК")
async def pc_types(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка...")
    r = await api.get_pc_types()
    await msg.delete()
    await message.answer(format_result(r, "ТИПЫ ПК", ["id", "name", "color"]), reply_markup=get_main_keyboard())

@dp.message(F.text == "🍔 Товары")
async def products(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка...")
    r = await api.get_products()
    await msg.delete()
    await message.answer(format_result(r, "ТОВАРЫ", ["id", "name", "active"]), reply_markup=get_main_keyboard())

@dp.message(F.text == "💲 Тарифы")
async def tariffs(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка...")
    r = await api.get_tariffs()
    await msg.delete()
    await message.answer(format_result(r, "ТАРИФЫ", ["id", "price", "time_from", "time_to"]), reply_markup=get_main_keyboard())

@dp.message(F.text == "📅 Группы тарифов")
async def tariff_groups(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка...")
    r = await api.get_tariff_groups()
    await msg.delete()
    await message.answer(format_result(r, "ГРУППЫ ТАРИФОВ", ["id", "name", "days"]), reply_markup=get_main_keyboard())

@dp.message(F.text == "🏷️ Типы тарифов")
async def tariff_types(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка...")
    r = await api.get_tariff_types()
    await msg.delete()
    await message.answer(format_result(r, "ТИПЫ ТАРИФОВ", ["id", "name", "type", "duration"]), reply_markup=get_main_keyboard())

@dp.message(F.text == "👨‍💼 Админы")
async def users(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка...")
    r = await api.get_users()
    await msg.delete()
    await message.answer(format_result(r, "АДМИНИСТРАТОРЫ", ["id", "email", "username", "verified"]), reply_markup=get_main_keyboard())

@dp.message(F.text == "⚙️ Конфиг")
async def config(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка...")
    r = await api.get_config()
    await msg.delete()
    await message.answer(format_result(r, "КОНФИГУРАЦИЯ", ["param_name", "value"]), reply_markup=get_main_keyboard())

@dp.message(F.text == "📁 PUF")
async def puf(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка...")
    r = await api.get_puf()
    await msg.delete()
    await message.answer(format_result(r, "ПРОФИЛИ PUF", ["id", "name"]), reply_markup=get_main_keyboard())

@dp.message(F.text == "🔌 Маршруты")
async def routes(message: types.Message):
    msg = await message.answer("🔄 Загрузка...")
    r = await api.get_routes()
    await msg.delete()
    await message.answer(format_result(r, "МАРШРУТЫ", ["method", "path", "summary"]), reply_markup=get_main_keyboard())

@dp.message(F.text == "📱 Админ ПО")
async def admin_console(message: types.Message):
    msg = await message.answer("🔄 Загрузка...")
    r = await api.get_admin_console()
    await msg.delete()
    if r.get("status") and r.get("data"):
        result = "📱 АДМИН ПО\n\n"
        for item in r["data"]:
            for k, v in item.items():
                result += f"🔧 {k}: {v}\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {r.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

@dp.message(F.text == "💻 Терминал")
async def terminal(message: types.Message):
    msg = await message.answer("🔄 Загрузка...")
    r = await api.get_terminal()
    await msg.delete()
    if r.get("status") and r.get("data"):
        result = "💻 ТЕРМИНАЛ\n\n"
        for item in r["data"]:
            for k, v in item.items():
                result += f"🔧 {k}: {v}\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {r.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())

# ========== КОМАНДЫ С ПАРАМЕТРАМИ ==========
@dp.message(F.text == "👤 Поиск гостя")
async def search_prompt(message: types.Message):
    await message.answer("🔍 Выберите способ поиска:", reply_markup=get_search_keyboard())

@dp.callback_query(lambda c: c.data.startswith("search_"))
async def search_callback(callback: types.CallbackQuery, state: FSMContext):
    search_type = callback.data.replace("search_", "")
    await state.update_data(search_type=search_type)
    await state.set_state(SearchState.waiting_input)
    prompts = {"phone": "📱 Введите номер телефона:", "id": "🆔 Введите ID гостя:", "name": "📝 Введите ФИО:"}
    await callback.message.edit_text(prompts.get(search_type, "Введите данные:"))
    await callback.answer()

@dp.message(StateFilter(SearchState.waiting_input))
async def search_execute(message: types.Message, state: FSMContext):
    data = await state.get_data()
    search_type = data.get("search_type")
    query = message.text.strip()
    msg = await message.answer("🔍 Поиск...")
    r = await api.search_guest(query, search_type)
    await msg.delete()
    if r.get("items"):
        result = "👤 РЕЗУЛЬТАТЫ ПОИСКА\n\n"
        for guest in r["items"][:5]:
            result += f"🆔 ID: {guest.get('guest_id')}\n📝 ФИО: {guest.get('fio', '—')}\n📱 Телефон: {guest.get('phone', '—')}\n"
            bal = guest.get('balance', {}).get('amount', 0) if isinstance(guest.get('balance'), dict) else 0
            try:
                result += f"💰 Баланс: {float(bal):,.2f} ₽\n"
            except:
                result += f"💰 Баланс: {bal} ₽\n"
            result += "─" * 25 + "\n"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer("❌ Гость не найден", reply_markup=get_main_keyboard())
    await state.clear()

@dp.message(F.text == "🎮 Сессии")
async def sessions_prompt(message: types.Message):
    await message.answer("🎮 Введите ID гостя:")
    await SessionsState.waiting_guest_id.set()

@dp.message(StateFilter(SessionsState.waiting_guest_id))
async def sessions_execute(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введите число!")
        return
    msg = await message.answer(f"🔄 Загрузка...")
    r = await api.get_sessions(int(message.text))
    await msg.delete()
    await message.answer(format_result(r, f"СЕССИИ ГОСТЯ #{message.text}", ["id", "date_start", "date_stop", "UUID"]), reply_markup=get_main_keyboard())
    await state.clear()

@dp.message(F.text == "💳 Касса")
async def cash_prompt(message: types.Message):
    await message.answer("💳 Введите ID клуба:")
    await CashState.waiting_club_id.set()

@dp.message(StateFilter(CashState.waiting_club_id))
async def cash_date_from(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введите число!")
        return
    await state.update_data(club_id=int(message.text))
    await message.answer("📅 Введите дату ОТ (ГГГГ-ММ-ДД):")
    await state.set_state(CashState.waiting_date_from)

@dp.message(StateFilter(CashState.waiting_date_from))
async def cash_date_to(message: types.Message, state: FSMContext):
    await state.update_data(date_from=message.text.strip())
    await message.answer("📅 Введите дату ДО (ГГГГ-ММ-ДД):")
    await state.set_state(CashState.waiting_date_to)

@dp.message(StateFilter(CashState.waiting_date_to))
async def cash_execute(message: types.Message, state: FSMContext):
    data = await state.get_data()
    msg = await message.answer("🔄 Загрузка...")
    r = await api.get_cash(data['club_id'], data['date_from'], message.text.strip())
    await msg.delete()
    await message.answer(format_result(r, "КАССОВЫЕ ОПЕРАЦИИ", ["date", "sum", "comment", "admin"]), reply_markup=get_main_keyboard())
    await state.clear()

@dp.message(F.text == "💰 Пополнения")
async def history_prompt(message: types.Message):
    await message.answer("📅 Введите дату ОТ (ГГГГ-ММ-ДД):")
    await HistoryState.waiting_date_from.set()

@dp.message(StateFilter(HistoryState.waiting_date_from))
async def history_date_to(message: types.Message, state: FSMContext):
    await state.update_data(date_from=message.text.strip())
    await message.answer("📅 Введите дату ДО (ГГГГ-ММ-ДД):")
    await state.set_state(HistoryState.waiting_date_to)

@dp.message(StateFilter(HistoryState.waiting_date_to))
async def history_execute(message: types.Message, state: FSMContext):
    data = await state.get_data()
    msg = await message.answer("🔄 Загрузка...")
    r = await api.get_balance_history(data['date_from'], message.text.strip())
    await msg.delete()
    await message.answer(format_result(r, "ИСТОРИЯ ПОПОЛНЕНИЙ", ["date", "guest_name", "phone", "amount"]), reply_markup=get_main_keyboard())
    await state.clear()

@dp.message(F.text == "📦 Остатки")
async def goods_prompt(message: types.Message):
    await message.answer("📦 Введите ID клуба:")
    await GoodsState.waiting_club_id.set()

@dp.message(StateFilter(GoodsState.waiting_club_id))
async def goods_execute(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введите число!")
        return
    msg = await message.answer(f"🔄 Загрузка...")
    r = await api.get_goods(int(message.text))
    await msg.delete()
    await message.answer(format_result(r, f"ОСТАТКИ (клуб {message.text})", ["id", "name", "count"]), reply_markup=get_main_keyboard())
    await state.clear()

@dp.message(F.text == "📥 Поступления")
async def arrivals(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    msg = await message.answer("🔄 Загрузка...")
    r = await api.get_arrivals()
    await msg.delete()
    await message.answer(format_result(r, "ПОСТУПЛЕНИЯ", ["date_fact", "list_goods_id", "count", "price_fact"]), reply_markup=get_main_keyboard())

@dp.message(F.text == "📤 Продажи")
async def expense_prompt(message: types.Message):
    await message.answer("📅 Введите дату ОТ (ГГГГ-ММ-ДД) или 'все':")
    await ExpenseState.waiting_date_from.set()

@dp.message(StateFilter(ExpenseState.waiting_date_from))
async def expense_date_to(message: types.Message, state: FSMContext):
    date_from = None if message.text.lower() == "все" else message.text.strip()
    await state.update_data(date_from=date_from)
    await message.answer("📅 Введите дату ДО (ГГГГ-ММ-ДД) или 'все':")
    await state.set_state(ExpenseState.waiting_date_to)

@dp.message(StateFilter(ExpenseState.waiting_date_to))
async def expense_execute(message: types.Message, state: FSMContext):
    data = await state.get_data()
    date_to = None if message.text.lower() == "все" else message.text.strip()
    msg = await message.answer("🔄 Загрузка...")
    r = await api.get_expenses(date_from=data.get('date_from'), date_to=date_to)
    await msg.delete()
    
    if r.get("status") and r.get("data"):
        items = r["data"][:15]
        result = "📤 ПРОДАЖИ ТОВАРОВ\n\n"
        total = 0
        for item in items:
            price = item.get('price_sale', 0)
            count = item.get('count', 0)
            if isinstance(price, str):
                try:
                    price = float(price)
                except:
                    price = 0
            if isinstance(count, str):
                try:
                    count = int(count)
                except:
                    count = 0
            sale_sum = price * count
            total += sale_sum
            result += f"📅 {item.get('date', '—')[:16]}\n"
            result += f"🆔 Товар ID: {item.get('list_goods_id')}\n"
            result += f"📦 Кол-во: {count} шт.\n"
            result += f"💰 Сумма: {sale_sum:,.2f} ₽\n"
            result += "─" * 25 + "\n"
        result += f"\n💰 Общая выручка: {total:,.2f} ₽"
        await message.answer(result, reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {r.get('error', 'Нет данных')}", reply_markup=get_main_keyboard())
    await state.clear()

# ========== УПРАВЛЕНИЕ БАЛАНСОМ ==========
@dp.message(F.text == "💰 Пополнить")
async def topup(message: types.Message, state: FSMContext):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    if not is_admin(message.from_user.id):
        return await message.answer("⛔ Нет прав!")
    await state.update_data(operation="topup")
    await state.set_state(BalanceState.waiting_phone)
    await message.answer("📱 Введите номер телефона гостя:")

@dp.message(F.text == "💸 Списать")
async def withdraw(message: types.Message, state: FSMContext):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    if not is_admin(message.from_user.id):
        return await message.answer("⛔ Нет прав!")
    await state.update_data(operation="withdraw")
    await state.set_state(BalanceState.waiting_phone)
    await message.answer("📱 Введите номер телефона гостя:")

@dp.message(StateFilter(BalanceState.waiting_phone))
async def balance_phone(message: types.Message, state: FSMContext):
    phone = ''.join(filter(str.isdigit, message.text.strip()))
    if len(phone) < 10:
        await message.answer("❌ Неверный номер!")
        return
    msg = await message.answer("🔍 Поиск гостя...")
    r = await api.get_guest_by_phone(phone)
    await msg.delete()
    if not r.get("items"):
        await message.answer("❌ Гость не найден!")
        await state.clear()
        return
    guest = r["items"][0]
    await state.update_data(phone=phone, guest_name=guest.get('fio', '—'), guest_id=guest.get('guest_id'))
    await state.set_state(BalanceState.waiting_amount)
    await message.answer(f"👤 Гость: {guest.get('fio', '—')}\n💰 Введите сумму:")

@dp.message(StateFilter(BalanceState.waiting_amount))
async def balance_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0:
            raise ValueError
    except:
        await message.answer("❌ Введите положительное число!")
        return
    data = await state.get_data()
    final = amount if data.get("operation") == "topup" else -amount
    await state.update_data(amount=final)
    await state.set_state(BalanceState.waiting_comment)
    await message.answer(f"💰 Сумма: {final:+,.2f} ₽\n📝 Введите комментарий (или 'нет'):")

@dp.message(StateFilter(BalanceState.waiting_comment))
async def balance_comment(message: types.Message, state: FSMContext):
    data = await state.get_data()
    comment = None if message.text.lower() == "нет" else message.text
    msg = await message.answer(f"🔄 Выполнение операции...")
    r = await api.update_balance(data['phone'], data['amount'], comment)
    await msg.delete()
    if r.get("status"):
        await message.answer(f"✅ {data.get('operation').upper()}\n👤 {data['guest_name']}\n💰 {data['amount']:+,.2f} ₽\n📝 {comment or '—'}", reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {r.get('error', 'Ошибка')}", reply_markup=get_main_keyboard())
    await state.clear()

# ========== УПРАВЛЕНИЕ ПК ==========
PC_COMMANDS = {
    "🖥️ Техстарт": "tech_start",
    "🛑 Техстоп": "tech_stop",
    "🔓 Разблокировка": "unlock",
    "🔒 Блокировка": "lock",
    "🔄 Ребут": "reboot",
    "🔌 Вкл ПК": "power_on",
    "⛔ Выкл ПК": "power_off"
}

@dp.message(F.text.in_(PC_COMMANDS.keys()))
async def pc_command(message: types.Message):
    if not API_KEY: return await message.answer("❌ API ключ не настроен!")
    if not is_admin(message.from_user.id):
        return await message.answer("⛔ Нет прав!")
    command = PC_COMMANDS[message.text]
    await message.answer(f"🖥️ {message.text}\n\nВыберите режим:", reply_markup=get_pc_keyboard(command))

@dp.callback_query(lambda c: c.data.startswith("pc_"))
async def pc_callback(callback: types.CallbackQuery, state: FSMContext):
    if callback.data == "pc_cancel":
        await callback.message.edit_text("❌ Отменено")
        await callback.answer()
        return
    parts = callback.data.split("_")
    command = parts[1]
    mode = parts[2]
    if mode == "uuids":
        await state.update_data(pc_command=command)
        await callback.message.edit_text("📋 Введите UUID ПК (через запятую или пробел):\n\n💡 Список UUID можно получить через '🖥️ ПК'")
        await state.set_state(PcUuidsState.waiting_uuids)
        await callback.answer()
        return
    pc_type = "free" if mode == "free" else "all"
    msg = await callback.message.answer(f"🔄 Выполняется {command}...")
    r = await api.manage_pc(command=command, pc_type=pc_type)
    await msg.delete()
    if r.get("status"):
        await callback.message.answer(f"✅ {command} отправлен!", reply_markup=get_main_keyboard())
    else:
        await callback.message.answer(f"❌ {r.get('error', 'Ошибка')}", reply_markup=get_main_keyboard())
    await callback.message.delete()
    await callback.answer()

@dp.message(StateFilter(PcUuidsState.waiting_uuids))
async def pc_uuids(message: types.Message, state: FSMContext):
    data = await state.get_data()
    command = data.get("pc_command")
    uuids = [u.strip() for u in message.text.replace(",", " ").split() if u.strip()]
    if not uuids:
        await message.answer("❌ Введите UUID!")
        return
    msg = await message.answer(f"🔄 Выполняется {command} для {len(uuids)} ПК...")
    r = await api.manage_pc(command=command, uuids=uuids)
    await msg.delete()
    if r.get("status"):
        await message.answer(f"✅ {command} отправлен для {len(uuids)} ПК!", reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {r.get('error', 'Ошибка')}", reply_markup=get_main_keyboard())
    await state.clear()

# ========== ОБРАБОТЧИК НЕИЗВЕСТНЫХ ==========
@dp.message()
async def unknown(message: types.Message):
    if not message.text.startswith("/"):
        await message.answer("❓ Используйте кнопки меню", reply_markup=get_main_keyboard())

# ========== ЗАПУСК ==========
async def main():
    logger.info("🚀 Бот запускается...")
    await bot.delete_webhook(drop_pending_updates=True)
    if API_KEY:
        r = await api.test_api()
        logger.info(f"API: {'✅ OK' if r.get('status') else '❌ Failed'}")
    logger.info("🎉 Бот готов!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())