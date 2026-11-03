import asyncio
import hashlib
import io
import os
import re
import sqlite3
from datetime import datetime, timezone

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    InputMediaPhoto
)
from PIL import Image

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
OCR_API_KEY = os.getenv("OCR_SPACE_API_KEY", "").strip()
DB_PATH = os.getenv("DB_PATH", "free_stars.sqlite3")

REQUIRED_COUNT = 10
CHANNEL_USERNAME = "@oppcountgift"
CHANNEL_URL = "https://t.me/oppcountgift"

REWARDS = {
    "stars": {
        "title": "75 Telegram Stars ⭐",
        "comment": "Кому бесплатно звезды @OppcountGIFTS",
        "emoji": "⭐",
    },
    "cups": {
        "title": "2 подарка-кубка 🏆",
        "comment": "Кому мишка @OppcountGIFTS",
        "emoji": "🏆",
    },
}

if not BOT_TOKEN:
    raise RuntimeError("Set BOT_TOKEN environment variable")
if not ADMIN_ID:
    raise RuntimeError("Set ADMIN_ID environment variable")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
db = sqlite3.connect(DB_PATH)
db.row_factory = sqlite3.Row
db.execute("""
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    username TEXT,
    reward TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'collecting',
    created_at TEXT NOT NULL
)
""")
db.execute("""
CREATE TABLE IF NOT EXISTS screenshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL,
    file_id TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    dhash TEXT NOT NULL,
    ocr_text TEXT,
    suspicious INTEGER NOT NULL DEFAULT 0,
    reason TEXT,
    FOREIGN KEY(application_id) REFERENCES applications(id)
)
""")
db.commit()


def normalize(text: str) -> str:
    text = (text or "").lower().replace("ё", "е")
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^a-zа-яіїєґ0-9@]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def difference_hash(data: bytes) -> str:
    image = Image.open(io.BytesIO(data)).convert("L").resize((9, 8))
    pixels = list(image.getdata())
    bits = []
    for y in range(8):
        for x in range(8):
            bits.append("1" if pixels[y * 9 + x] > pixels[y * 9 + x + 1] else "0")
    return f"{int(''.join(bits), 2):016x}"


def hamming_distance(a: str, b: str) -> int:
    return (int(a, 16) ^ int(b, 16)).bit_count()


async def recognize_text(data: bytes) -> str:
    if not OCR_API_KEY:
        return ""
    timeout = aiohttp.ClientTimeout(total=45)
    form = aiohttp.FormData()
    form.add_field("apikey", OCR_API_KEY)
    form.add_field("language", "rus")
    form.add_field("OCREngine", "2")
    form.add_field("isOverlayRequired", "false")
    form.add_field("file", data, filename="screenshot.jpg",
                   content_type="application/octet-stream")
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post("https://api.ocr.space/parse/image", data=form) as response:
            payload = await response.json(content_type=None)
    if payload.get("IsErroredOnProcessing"):
        return ""
    return "\n".join(item.get("ParsedText", "") for item in payload.get("ParsedResults") or [])


def subscription_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Открыть канал", url=CHANNEL_URL)],
        [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscription")],
    ])


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Получить 75 Stars", callback_data="reward:stars")],
        [InlineKeyboardButton(text="🏆 Получить 2 подарка", callback_data="reward:cups")],
    ])


def admin_keyboard(app_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Одобрить", callback_data=f"admin:accept:{app_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"admin:reject:{app_id}"),
    ]])


async def is_subscribed(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as error:
        print(f"Subscription check failed for {user_id}: {error}")
        return False


def get_application(app_id: int):
    return db.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()


async def send_application_to_admin(app_id: int):
    app = get_application(app_id)
    shots = db.execute(
        "SELECT * FROM screenshots WHERE application_id=? ORDER BY id", (app_id,)
    ).fetchall()

    username = f"@{app['username']}" if app["username"] else "не указан"
    suspicious_count = sum(1 for shot in shots if shot["suspicious"])

    await bot.send_message(
        ADMIN_ID,
        f"╭━━━ ✦ <b>НОВАЯ ЗАЯВКА</b> ✦ ━━━╮\n"
        f"│ Номер: <code>#{app_id}</code>\n"
        f"│ Пользователь: {username}\n"
        f"│ Telegram ID: <code>{app['user_id']}</code>\n"
        f"│ Награда: <b>{REWARDS[app['reward']]['title']}</b>\n"
        f"│ Скриншотов: <b>{len(shots)}/{REQUIRED_COUNT}</b>\n"
        f"│ Подозрительных: <b>{suspicious_count}</b>\n"
        f"╰━━━━━━━━━━━━━━━━━━━━╯\n\n"
        "Просмотри материалы и выбери решение.",
        parse_mode="HTML",
    )

    for start in range(0, len(shots), 10):
        chunk = shots[start:start + 10]
        media = []
        for index, shot in enumerate(chunk):
            caption = None
            if index == 0:
                caption = f"Заявка #{app_id} · скриншоты {start + 1}–{start + len(chunk)}"
            media.append(InputMediaPhoto(media=shot["file_id"], caption=caption))
        await bot.send_media_group(ADMIN_ID, media)

    for shot in shots:
        if shot["suspicious"]:
            await bot.send_message(
                ADMIN_ID,
                f"⚠️ <b>Подозрительный файл в заявке #{app_id}</b>\n"
                f"Причина: {shot['reason']}\n"
                f"OCR: <code>{(shot['ocr_text'] or 'текст не распознан')[:700]}</code>",
                parse_mode="HTML",
            )

    await bot.send_message(
        ADMIN_ID, f"Решение по заявке #{app_id}:",
        reply_markup=admin_keyboard(app_id),
    )


@dp.message(CommandStart())
async def start(message: Message):
    db.execute(
        "UPDATE applications SET status='cancelled' WHERE user_id=? AND status='collecting'",
        (message.from_user.id,)
    )
    db.commit()

    await message.answer(
        "✦ <b>FREE STARS</b> ✦\n\n"
        "Есть минутка? Возможно, именно она приблизит тебя к приятному подарку. 🎁\n\n"
        "Выбери награду, выполни условия участия и отправь заявку на проверку. "
        "После проверки администрация сообщит результат.\n\n"
        "🔐 <b>Первый шаг — подписка на наш канал:</b>",
        reply_markup=subscription_menu(),
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "check_subscription")
async def check_subscription(callback: CallbackQuery):
    if not await is_subscribed(callback.from_user.id):
        await callback.answer(
            "Подписка пока не найдена. Подпишись на канал и попробуй ещё раз.",
            show_alert=True,
        )
        return
    await callback.message.answer(
        "✦ <b>Отлично, подписка подтверждена!</b>\n\n"
        "Теперь выбери, какую награду хочешь получить:",
        reply_markup=main_menu(),
        parse_mode="HTML",
    )
    await callback.answer("Подписка подтверждена!")


@dp.callback_query(F.data.startswith("reward:"))
async def choose_reward(callback: CallbackQuery):
    reward = callback.data.split(":", 1)[1]
    if reward not in REWARDS:
        await callback.answer("Неизвестная награда.", show_alert=True)
        return

    if not await is_subscribed(callback.from_user.id):
        await callback.answer("Сначала подпишись на канал.", show_alert=True)
        await callback.message.answer(
            "🔐 Для продолжения нужна подписка на канал.",
            reply_markup=subscription_menu(),
        )
        return

    db.execute(
        "UPDATE applications SET status='cancelled' WHERE user_id=? AND status='collecting'",
        (callback.from_user.id,)
    )
    cursor = db.execute(
        "INSERT INTO applications(user_id, username, reward, created_at) VALUES (?, ?, ?, ?)",
        (callback.from_user.id, callback.from_user.username, reward,
         datetime.now(timezone.utc).isoformat())
    )
    db.commit()

    await callback.message.answer(
        f"🎁 <b>Твой выбор: {REWARDS[reward]['title']}</b>\n\n"
        "Следующий шаг — отправить <b>10 скриншотов</b> комментариев.\n\n"
        "📝 <b>Текст комментария:</b>\n"
        f"<code>{REWARDS[reward]['comment']}</code>\n\n"
        "Отправляй скриншоты по одному, именно как фотографии. "
        "После каждого файла покажем прогресс.\n\n"
        "⚠️ Все материалы проходят автоматическую предварительную проверку "
        "и могут быть дополнительно проверены администрацией.\n\n"
        "Прогресс: <b>0/10</b>",
        parse_mode="HTML",
    )
    await callback.answer()


@dp.message(F.photo)
async def receive_photo(message: Message):
    row = db.execute(
        "SELECT * FROM applications WHERE user_id=? AND status='collecting' ORDER BY id DESC LIMIT 1",
        (message.from_user.id,)
    ).fetchone()
    if not row:
        await message.answer("Чтобы начать, нажми /start.")
        return

    count = db.execute(
        "SELECT COUNT(*) FROM screenshots WHERE application_id=?", (row["id"],)
    ).fetchone()[0]
    if count >= REQUIRED_COUNT:
        await message.answer("Все 10 скриншотов уже получены. Дождись решения администрации.")
        return

    file = await bot.get_file(message.photo[-1].file_id)
    buffer = io.BytesIO()
    await bot.download_file(file.file_path, destination=buffer)
    data = buffer.getvalue()

    sha = hashlib.sha256(data).hexdigest()
    try:
        dhash = difference_hash(data)
    except Exception:
        await message.answer("Не удалось обработать изображение. Попробуй отправить его ещё раз.")
        return

    previous = db.execute(
        "SELECT sha256, dhash FROM screenshots WHERE application_id=?", (row["id"],)
    ).fetchall()

    reason = None
    if any(item["sha256"] == sha for item in previous):
        reason = "точный дубликат изображения"
    elif any(hamming_distance(item["dhash"], dhash) <= 4 for item in previous):
        reason = "изображение похоже на ранее отправленный скриншот"

    ocr_text = ""
    if not reason:
        try:
            ocr_text = await recognize_text(data)
        except Exception as error:
            print(f"OCR error: {error}")

        expected = normalize(REWARDS[row["reward"]]["comment"])
        found = normalize(ocr_text)
        if not OCR_API_KEY:
            reason = "OCR не настроен — требуется ручная проверка"
        elif not found:
            reason = "не удалось распознать текст"
        elif expected not in found:
            reason = "не найден точный текст задания"

    suspicious = int(reason is not None)
    db.execute(
        "INSERT INTO screenshots(application_id, file_id, sha256, dhash, ocr_text, suspicious, reason) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (row["id"], message.photo[-1].file_id, sha, dhash, ocr_text[:4000], suspicious, reason)
    )
    db.commit()

    new_count = count + 1
    progress = "🟨" * new_count + "⬜" * (REQUIRED_COUNT - new_count)
    await message.answer(
        f"📸 <b>Скриншот принят</b>\n\n{progress}\n"
        f"<b>{new_count}/{REQUIRED_COUNT}</b>"
        + ("\n\n⚠️ Файл отмечен для дополнительной проверки." if suspicious
           else "\n\n✅ Предварительная проверка пройдена."),
        parse_mode="HTML",
    )

    if suspicious:
        await bot.send_photo(
            ADMIN_ID,
            message.photo[-1].file_id,
            caption=(
                f"⚠️ <b>Требуется проверка</b>\n"
                f"Заявка: #{row['id']}\n"
                f"Пользователь ID: <code>{message.from_user.id}</code>\n"
                f"Причина: {reason}\n"
                f"Распознанный текст: {(ocr_text or 'не распознан')[:700]}"
            ),
            parse_mode="HTML",
        )

    if new_count == REQUIRED_COUNT:
        db.execute("UPDATE applications SET status='pending' WHERE id=?", (row["id"],))
        db.commit()
        await message.answer(
            "🎉 <b>Все 10 скриншотов отправлены!</b>\n\n"
            "Заявка передана администрации на проверку. "
            "Мы сообщим тебе о результате здесь.\n\n"
            "Спасибо за участие! ✨",
            parse_mode="HTML",
        )
        await send_application_to_admin(row["id"])


@dp.message()
async def other_message(message: Message):
    row = db.execute(
        "SELECT id FROM applications WHERE user_id=? AND status='collecting' ORDER BY id DESC LIMIT 1",
        (message.from_user.id,)
    ).fetchone()
    if row:
        await message.answer("Пожалуйста, отправляй скриншоты именно как фотографии.")
    else:
        await message.answer("Нажми /start, чтобы открыть меню FREE STARS.")


@dp.callback_query(F.data.startswith("admin:"))
async def admin_decision(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    try:
        _, action, app_id_raw = callback.data.split(":")
        app_id = int(app_id_raw)
    except (ValueError, TypeError):
        await callback.answer("Некорректная команда.", show_alert=True)
        return

    app = get_application(app_id)
    if not app or app["status"] != "pending":
        await callback.answer("Заявка уже обработана или не найдена.", show_alert=True)
        return

    if action == "accept":
        status, user_text, admin_text = (
            "approved",
            "🎉 <b>Твоя заявка одобрена!</b>\n\nАдминистрация подтвердила выполнение условий. Спасибо за участие! ✨",
            f"✅ Заявка #{app_id} одобрена.",
        )
    elif action == "reject":
        status, user_text, admin_text = (
            "rejected",
            "К сожалению, заявка не прошла проверку. Если считаешь, что произошла ошибка, свяжись с администрацией канала.",
            f"❌ Заявка #{app_id} отклонена.",
        )
    else:
        await callback.answer("Неизвестное действие.", show_alert=True)
        return

    db.execute("UPDATE applications SET status=? WHERE id=?", (status, app_id))
    db.commit()
    await bot.send_message(app["user_id"], user_text, parse_mode="HTML")
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(admin_text)
    await callback.answer("Решение сохранено.")


async def main():
    print("FREE STARS bot started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
