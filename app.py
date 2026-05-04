import asyncio
import random
import string
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiohttp import web

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = os.environ["BOT_TOKEN"]

CHANNEL_1_ID = -1003993803454  # Necrocide
CHANNEL_2_ID = -1003859905398  # KultovHesitey

ADMIN_IDS = [8377328708, 995258854]

REQUIRED_INVITES = 7
RANDOM_CHANCE = 5  # Шанс 5%

PHOTO_URL = "https://i.postimg.cc/90Ryk33F/file-000000005fd87243ba6d7497f8878878.png"

# Словари для хранения данных
invites_count = {}
pending_referrals = {}
promocodes = {}
used_promocodes = {}
used_gifts = {}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ========== СОСТОЯНИЯ FSM ==========
class AdminStates(StatesGroup):
    waiting_for_promocode_name = State()
    waiting_for_activations_count = State()
    waiting_for_expiry_days = State()

class UserStates(StatesGroup):
    waiting_for_promocode_input = State()

# ========== КЛАВИАТУРЫ ==========
def main_menu_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 30 звёзд", callback_data="gift_30")],
        [InlineKeyboardButton(text="🧸 3 мишки", callback_data="gift_mice")],
        [InlineKeyboardButton(text="🎟 Промокод", callback_data="gift_promo")],
        [InlineKeyboardButton(text="👥 Рефералы", callback_data="referrals")]
    ])
    return keyboard

def admin_panel_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🆕 Создать промокод", callback_data="admin_create_promo")],
        [InlineKeyboardButton(text="📋 Список промокодов", callback_data="admin_list_promo")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_to_menu")]
    ])
    return keyboard

def subscribe_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Necrocide", url="https://t.me/+_W1Hit0AXMExMzVi")],
        [InlineKeyboardButton(text="📢 Переходник Hesitey", url="https://t.me/KultovHesitey")],
        [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscribe")]
    ])
    return keyboard

def invites_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Получить реферальную ссылку", callback_data="get_invite_link")],
        [InlineKeyboardButton(text="🔄 Проверить статус", callback_data="check_invites")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])
    return keyboard

# ========== ФУНКЦИИ ==========
async def check_subscription(user_id: int, channel_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        return member.status in ["creator", "administrator", "member"]
    except Exception:
        return False

def generate_invite_link(user_id: int) -> str:
    bot_username = "NecrocideBot"
    return f"https://t.me/{bot_username}?start={user_id}"

def generate_promocode() -> str:
    letters = string.ascii_uppercase + string.digits
    return ''.join(random.choice(letters) for _ in range(10))

async def send_main_menu(message_or_callback):
    if isinstance(message_or_callback, types.CallbackQuery):
        msg = message_or_callback.message
        await msg.delete()
        await msg.answer_photo(
            photo=PHOTO_URL,
            caption="🔮 *Добро пожаловать в бота!*\n\nВыбери действие:",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )
    else:
        await message_or_callback.answer_photo(
            photo=PHOTO_URL,
            caption="🔮 *Добро пожаловать в бота!*\n\nВыбери действие:",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )

# ========== КОМАНДА /START ==========
@dp.message(Command("start"))
async def start_command(message: types.Message):
    args = message.text.split()
    user_id = message.from_user.id
    
    if len(args) > 1 and args[1].isdigit():
        referrer_id = int(args[1])
        if referrer_id != user_id:
            if user_id not in pending_referrals:
                pending_referrals[user_id] = referrer_id
                await message.answer(
                    f"🔗 *Вы были приглашены!*\n\n"
                    f"📌 *Чтобы реферал засчитался:*\n"
                    f"1️⃣ Подпишись на каналы\n"
                    f"2️⃣ Нажми «Я подписался»\n\n"
                    f"После этого ваш друг получит +1 к приглашениям!",
                    parse_mode="Markdown"
                )
            else:
                await message.answer("ℹ️ Вы уже были приглашены ранее.")
    
    await send_main_menu(message)

# ========== КОМАНДА /ADMIN ==========
@dp.message(Command("admin"))
async def admin_command(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к админ-панели!")
        return
    
    await message.answer(
        "🛡 *Админ-панель*\n\nВыбери действие:",
        parse_mode="Markdown",
        reply_markup=admin_panel_keyboard()
    )

# ========== ОБРАБОТКА ГЛАВНОГО МЕНЮ ==========
@dp.callback_query(lambda c: c.data in ["gift_30", "gift_mice", "gift_promo", "referrals", "back_to_menu", "admin_stats"])
async def handle_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    
    if callback.data == "back_to_menu":
        await send_main_menu(callback)
        await callback.answer()
        return
    
    if callback.data == "referrals":
        user_id = callback.from_user.id
        invited = invites_count.get(user_id, 0)
        remaining = REQUIRED_INVITES - invited
        link = generate_invite_link(user_id)
        
        text = (f"👥 *Ваша реферальная система*\n\n"
                f"📎 *Ваша ссылка:* `{link}`\n"
                f"👤 *Приглашено друзей:* {invited}/{REQUIRED_INVITES}\n"
                f"📌 *Осталось пригласить:* {remaining}\n\n"
                f"🎁 *Бонус:* за каждые {REQUIRED_INVITES} приглашенных - подарок!\n\n"
                f"📌 *Как получить подарок:*\n"
                f"1. Отправь ссылку друзьям\n"
                f"2. Друг должен перейти и НАЖАТЬ «Я ПОДПИСАЛСЯ»\n"
                f"3. Только после этого ему засчитается приглашение!")
        
        await callback.message.delete()
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=invites_keyboard())
        await callback.answer()
        return
    
    if callback.data == "admin_stats":
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("Нет доступа!", show_alert=True)
            return
        
        total_invites = sum(invites_count.values())
        active_promos = len(promocodes)
        pending = len(pending_referrals)
        
        text = (f"📊 *Статистика бота*\n\n"
                f"👥 Всего приглашений: {total_invites}\n"
                f"⏳ Ожидают подтверждения: {pending}\n"
                f"🎟 Активных промокодов: {active_promos}\n"
                f"👤 Пользователей: {len(invites_count)}\n"
                f"🎯 Нужно пригласить: {REQUIRED_INVITES}")
        
        await callback.message.delete()
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=admin_panel_keyboard())
        await callback.answer()
        return
    
    # Любой подарок - проверка подписки
    await state.update_data(selected_gift=callback.data)
    await callback.message.delete()
    await callback.message.answer(
        "📢 *Чтобы получить подарок, подпишись на каналы и нажми кнопку:*",
        parse_mode="Markdown",
        reply_markup=subscribe_keyboard()
    )
    await callback.answer()

# ========== ПРОВЕРКА ПОДПИСКИ ==========
@dp.callback_query(lambda c: c.data == "check_subscribe")
async def handle_check_subscribe(callback: CallbackQuery, state: FSMContext):
    global used_gifts
    await callback.answer("🔍 Проверяю...", show_alert=False)
    
    user_id = callback.from_user.id
    is_subscribed_1 = await check_subscription(user_id, CHANNEL_1_ID)
    is_subscribed_2 = await check_subscription(user_id, CHANNEL_2_ID)
    
    if is_subscribed_1 and is_subscribed_2:
        # ЗАЧИСЛЕНИЕ РЕФЕРАЛКИ
        if user_id in pending_referrals:
            referrer_id = pending_referrals[user_id]
            
            if referrer_id not in invites_count:
                invites_count[referrer_id] = 0
            invites_count[referrer_id] += 1
            
            del pending_referrals[user_id]
            
            try:
                await bot.send_message(
                    referrer_id,
                    f"✅ *У вас новое приглашение!*\n\n"
                    f"👤 *Друг:* {callback.from_user.full_name}\n"
                    f"📊 *Теперь у вас:* {invites_count[referrer_id]}/{REQUIRED_INVITES}\n\n"
                    f"🎁 *Продолжайте приглашать друзей!*",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            
            await callback.message.delete()
            await callback.message.answer(
                f"✅ *Спасибо за подписку!*\n\n"
                f"🎁 *Реферал засчитан вашему другу!*\n\n"
                f"📌 *Теперь выбери подарок в главном меню!*",
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard()
            )
            await callback.answer()
            return
        
        # ПРОВЕРКА - НЕ ПОЛУЧИЛ ЛИ УЖЕ ПОДАРОК
        if user_id in used_gifts:
            await callback.message.delete()
            await callback.message.answer(
                f"❌ *Вы уже получили подарок:* {used_gifts[user_id]}\n\n"
                f"📌 *Один пользователь - один подарок!*",
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard()
            )
            await callback.answer()
            return
        
        user_data = await state.get_data()
        selected_gift = user_data.get("selected_gift", "подарок")
        gift_name = "30 звёзд" if selected_gift == "gift_30" else "3 мишки" if selected_gift == "gift_mice" else "подарок"
        
        chance = random.randint(1, 100)
        
        if chance <= RANDOM_CHANCE:
            used_gifts[user_id] = gift_name
            await callback.message.delete()
            await callback.message.answer(
                f"🎁 *ХОЧЕШЬ И ВПРАВДУ ПОДАРОК?*\n\n"
                f"ОТПРАВЬ 5 ЛЮДЯМ ДАННОГО БОТА СО СЛОВАМИ:\n"
                f"*«ПЕРЕЙДИТЕ В БОТА И ПОДПИШИТЕСЬ НА КАНАЛЫ»* - @NecrocideBot\n\n"
                f"⚡ *КАК ТОЛЬКО СДЕЛАЕШЬ ЭТО УСЛОВИЕ -*\n"
                f"ТЫ МОЖЕШЬ НАПИСАТЬ МНЕ В ЛС @FuckHesitey\n\n"
                f"🎁 *И ПОЛУЧИТЬ ПОДАРОК БЕЗ ШУТОК!*\n\n"
                f"🎁 *Твой подарок:* {gift_name}",
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard()
            )
        else:
            invited = invites_count.get(user_id, 0)
            
            if invited >= REQUIRED_INVITES:
                used_gifts[user_id] = gift_name
                await callback.message.delete()
                await callback.message.answer(
                    f"✅ *Ты подписался на каналы!*\n\n"
                    f"🎁 *За подарком обращаться:* @FuckHesitey",
                    parse_mode="Markdown",
                    reply_markup=main_menu_keyboard()
                )
            else:
                remaining = REQUIRED_INVITES - invited
                await callback.message.delete()
                await callback.message.answer(
                    f"✅ *Ты подписался на каналы!*\n\n"
                    f"🎁 *За подарком обращаться:* @FuckHesitey\n\n"
                    f"👥 *Пригласи ещё {remaining} друзей, чтобы получить гарантированный подарок!*",
                    parse_mode="Markdown",
                    reply_markup=main_menu_keyboard()
                )
    else:
        not_subscribed = []
        if not is_subscribed_1:
            not_subscribed.append("📢 Necrocide")
        if not is_subscribed_2:
            not_subscribed.append("📢 Переходник Hesitey")
        
        text = ("❌ *Ты не подписан на следующие каналы:*\n\n"
                + "\n".join(not_subscribed)
                + "\n\n📌 *Подпишись и нажми кнопку снова!*")
        
        await callback.message.delete()
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=subscribe_keyboard())

# ========== РЕФЕРАЛЬНАЯ СИСТЕМА ==========
@dp.callback_query(lambda c: c.data in ["get_invite_link", "check_invites"])
async def handle_referrals(callback: CallbackQuery):
    user_id = callback.from_user.id
    invited = invites_count.get(user_id, 0)
    
    if callback.data == "get_invite_link":
        link = generate_invite_link(user_id)
        remaining = REQUIRED_INVITES - invited
        await callback.message.answer(
            f"🔗 *Твоя реферальная ссылка:*\n`{link}`\n\n"
            f"📌 *Отправь ссылку друзьям!*\n"
            f"👥 *Приглашено:* {invited}/{REQUIRED_INVITES}\n"
            f"📌 *Важно:* Реферал засчитается ТОЛЬКО после того, как друг подпишется на каналы и нажмет «Я подписался»!",
            parse_mode="Markdown"
        )
        await callback.answer()
    
    elif callback.data == "check_invites":
        if invited >= REQUIRED_INVITES:
            text = (f"✅ *Отлично! Ты пригласил {invited} друзей!*\n\n"
                    f"🎁 *Теперь вернись к выбору подарка и нажми «Я подписался» снова!*")
            await callback.message.delete()
            await callback.message.answer(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())
        else:
            remaining = REQUIRED_INVITES - invited
            text = (f"👥 *У тебя {invited}/{REQUIRED_INVITES} приглашенных*\n\n"
                    f"📌 *Осталось пригласить:* {remaining}\n\n"
                    f"🔗 *Отправь ссылку друзьям!*\n"
                    f"💡 *Напомни другу подписаться на каналы и нажать «Я подписался»!*")
            await callback.message.answer(text, parse_mode="Markdown")
        await callback.answer()

# ========== АДМИН: СОЗДАНИЕ ПРОМОКОДА ==========
@dp.callback_query(lambda c: c.data == "admin_create_promo")
async def admin_create_promo(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа!", show_alert=True)
        return
    
    await callback.message.answer("✏️ *Введи название промокода* (или нажми /cancel для отмены):", parse_mode="Markdown")
    await state.set_state(AdminStates.waiting_for_promocode_name)
    await callback.answer()

@dp.message(AdminStates.waiting_for_promocode_name)
async def get_promo_name(message: types.Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Создание промокода отменено.")
        return
    
    await state.update_data(promo_name=message.text)
    await message.answer("🔢 *Введи количество активаций* (например: 10):", parse_mode="Markdown")
    await state.set_state(AdminStates.waiting_for_activations_count)

@dp.message(AdminStates.waiting_for_activations_count)
async def get_activations_count(message: types.Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Создание промокода отменено.")
        return
    
    try:
        count = int(message.text)
        await state.update_data(activations_count=count)
        await message.answer("📅 *Введи срок действия в днях* (например: 7):", parse_mode="Markdown")
        await state.set_state(AdminStates.waiting_for_expiry_days)
    except ValueError:
        await message.answer("❌ Введи число!")

@dp.message(AdminStates.waiting_for_expiry_days)
async def get_expiry_days(message: types.Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Создание промокода отменено.")
        return
    
    try:
        days = int(message.text)
        data = await state.get_data()
        promo_name = data["promo_name"]
        activations = data["activations_count"]
        
        code = generate_promocode()
        expires = datetime.now() + timedelta(days=days)
        
        promocodes[code] = {
            "name": promo_name,
            "activations": activations,
            "remaining": activations,
            "expires": expires,
            "created_by": message.from_user.id,
            "created_at": datetime.now()
        }
        
        text = (f"✅ *Промокод создан!*\n\n"
                f"📌 *Код:* `{code}`\n"
                f"🏷 *Название:* {promo_name}\n"
                f"🔢 *Активаций:* {activations}\n"
                f"📅 *Действует до:* {expires.strftime('%d.%m.%Y %H:%M')}")
        
        await message.answer(text, parse_mode="Markdown", reply_markup=admin_panel_keyboard())
        await state.clear()
    except ValueError:
        await message.answer("❌ Введи число!")

# ========== АДМИН: СПИСОК ПРОМОКОДОВ ==========
@dp.callback_query(lambda c: c.data == "admin_list_promo")
async def admin_list_promo(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа!", show_alert=True)
        return
    
    if not promocodes:
        await callback.message.delete()
        await callback.message.answer("📭 *Нет активных промокодов*", parse_mode="Markdown", reply_markup=admin_panel_keyboard())
        await callback.answer()
        return
    
    text = "*📋 Список промокодов:*\n\n"
    for code, data in promocodes.items():
        text += (f"🔹 `{code}`\n"
                 f"   Название: {data['name']}\n"
                 f"   Осталось: {data['remaining']}/{data['activations']}\n"
                 f"   До: {data['expires'].strftime('%d.%m.%Y')}\n\n")
    
    await callback.message.delete()
    await callback.message.answer(text, parse_mode="Markdown", reply_markup=admin_panel_keyboard())
    await callback.answer()

# ========== ПРОМОКОД ДЛЯ ПОЛЬЗОВАТЕЛЯ ==========
@dp.callback_query(lambda c: c.data == "gift_promo")
async def promo_input_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("🎟 *Введи промокод:*", parse_mode="Markdown")
    await state.set_state(UserStates.waiting_for_promocode_input)
    await callback.answer()

@dp.message(UserStates.waiting_for_promocode_input)
async def check_promocode(message: types.Message, state: FSMContext):
    code = message.text.strip().upper()
    user_id = message.from_user.id
    
    if code not in promocodes:
        await message.answer("❌ *Неверный промокод!*", parse_mode="Markdown")
        await state.clear()
        return
    
    promo = promocodes[code]
    
    if datetime.now() > promo["expires"]:
        await message.answer("❌ *Промокод просрочен!*", parse_mode="Markdown")
        await state.clear()
        return
    
    if promo["remaining"] <= 0:
        await message.answer("❌ *Промокод уже использован!*", parse_mode="Markdown")
        await state.clear()
        return
    
    if user_id in used_promocodes and code in used_promocodes[user_id]:
        await message.answer("❌ *Ты уже использовал этот промокод!*", parse_mode="Markdown")
        await state.clear()
        return
    
    promocodes[code]["remaining"] -= 1
    if user_id not in used_promocodes:
        used_promocodes[user_id] = []
    used_promocodes[user_id].append(code)
    
    await message.answer(
        f"✅ *Промокод активирован!*\n\n"
        f"🏷 *{promo['name']}*\n\n"
        f"🎁 *За подарком обращаться:* @FuckHesitey",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )
    await state.clear()

# ========== ВЕБ-СЕРВЕР ДЛЯ RENDER ==========
async def health_check(request):
    return web.Response(text="Bot is running!")

async def start_web():
    app_web = web.Application()
    app_web.router.add_get('/', health_check)
    runner = web.AppRunner(app_web)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 10000)
    await site.start()
    print("🌐 Веб-сервер для Render запущен на порту 10000")
    while True:
        await asyncio.sleep(3600)

# ========== ЗАПУСК ==========
async def main():
    print("=" * 50)
    print("🚀 БОТ ЗАПУЩЕН")
    print("=" * 50)
    print(f"👑 Админы: {ADMIN_IDS}")
    print(f"📢 Каналы: {CHANNEL_1_ID}, {CHANNEL_2_ID}")
    print(f"🎲 Шанс выпадения подарка: {RANDOM_CHANCE}%")
    print(f"👥 Нужно пригласить друзей: {REQUIRED_INVITES}")
    print(f"🖼 Фото загружено: {PHOTO_URL}")
    print("=" * 50)
    await dp.start_polling(bot)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(start_web())
    loop.run_until_complete(main())
