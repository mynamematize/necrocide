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
REQUIRED_COUNT = 20
TARGET = "@OppcountGIFTS"

REWARDS = {
    "stars": {
        "title": "75 ⭐ Stars",
        "comment": "Кому бесплатно звезды @OppcountGIFTS",
    },
    "cups": {
        "title": "2 подарка 🏆",
        "comment": "Кому мишка @OppcountGIFTS",
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
            left = pixels[y * 9 + x]
            right = pixels[y * 9 + x + 1]
            bits.append("1" if left > right else "0")
    return f"{int(''.join(bits), 2):016x}"


def hamming_distance(a: str, b: str) -> int:
    return (int(a, 16) ^ int(b, 16)).bit_count()


async def recognize_text(data: bytes) -> str:
    """OCR.Space is optional. Without an API key, every image goes to manual review."""
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
        async with session.post(
            "https://api.ocr.space/parse/image", data=form
        ) as response:
            payload = await response.json(content_type=None)
    if payload.get("IsErroredOnProcessing"):
        return ""
    results = payload.get("ParsedResults") or []
    return "\n".join(item.get("ParsedText", "") for item in results)


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ 75 Stars", callback_data="reward:stars")],
        [InlineKeyboardButton(text="🏆 2 подарка (кубка)", callback_data="reward:cups")],
    ])


def admin_keyboard(app_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Принять", callback_data=f"admin:accept:{app_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"admin:reject:{app_id}"),
        ]
    ])


def get_application(app_id: int):
    return db.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()


async def send_application_to_admin(app_id: int):
    app = get_application(app_id)
    if not app:
        return
    shots = db.execute(
        "SELECT * FROM screenshots WHERE application_id=? ORDER BY id",
        (app_id,)
    ).fetchall()

    username = f"@{app['username']}" if app["username"] else "не указан"
    await bot.send_message(
        ADMIN_ID,
        f"📥 <b>Новая заявка #{app_id}</b>\n"
        f"Пользователь: {username}\n"
        f"Telegram ID: <code>{app['user_id']}</code>\n"
        f"Награда: <b>{REWARDS[app['reward']]['title']}</b>\n"
        f"Скриншотов: {len(shots)}/{REQUIRED_COUNT}\n"
        f"Проверь все скриншоты и выбери решение.",
        parse_mode="HTML",
    )

    # Telegram media groups support up to 10 photos per group.
    for start in range(0, len(shots), 10):
        chunk = shots[start:start + 10]
        media = [
            InputMediaPhoto(
                media=shot["file_id"],
                caption=(
                    f"Заявка #{app_id} · скриншот {start + index + 1}/20"
                    + (f"\n⚠️ Подозрение: {shot['reason']}" if shot["suspicious"] else "")
                ) if index == 0 else None
            )
            for index, shot in enumerate(chunk)
        ]
        await bot.send_media_group(ADMIN_ID, media)

    suspicious_count = sum(1 for shot in shots if shot["suspicious"])
    await bot.send_message(
        ADMIN_ID,
        f"Итог по заявке #{app_id}: подозрительных скриншотов — "
        f"{suspicious_count}. Решение за тобой.",
        reply_markup=admin_keyboard(app_id),
    )


@dp.message(CommandStart())
async def start(message: Message):
    db.execute(
        "UPDATE applications SET status='cancelled' "
        "WHERE user_id=? AND status='collecting'",
        (message.from_user.id,)
    )
    db.commit()
    await message.answer(
        "⭐ <b>FREE STARS</b>\n\n"
        "Привет! Выбери награду:\n"
        "• 75 Telegram Stars\n"
        "• 2 подарка (кубка)",
        reply_markup=main_menu(),
        parse_mode="HTML",
    )


@dp.callback_query(F.data.startswith("reward:"))
async def choose_reward(callback: CallbackQuery):
    reward = callback.data.split(":", 1)[1]
    if reward not in REWARDS:
        await callback.answer("Неизвестная награда", show_alert=True)
        return

    db.execute(
        "UPDATE applications SET status='cancelled' "
        "WHERE user_id=? AND status='collecting'",
        (callback.from_user.id,)
    )
    cursor = db.execute(
        "INSERT INTO applications(user_id, username, reward, created_at) "
        "VALUES (?, ?, ?, ?)",
        (
            callback.from_user.id,
            callback.from_user.username,
            reward,
            datetime.now(timezone.utc).isoformat(),
        )
    )
    db.commit()
    app_id = cursor.lastrowid
    comment = REWARDS[reward]["comment"]
    await callback.message.answer(
        f"Вы выбрали: <b>{REWARDS[reward]['title']}</b>\n\n"
        f"Теперь отправьте <b>20 скриншотов</b> комментариев.\n"
        f"В каждом комментарии должен быть текст:\n"
        f"<code>{comment}</code>\n\n"
        f"Отправляйте скриншоты по одному как фото. "
        f"Прогресс: 0/20.\n\n"
        f"Если передумали, нажмите /start.",
        parse_mode="HTML",
    )
    await callback.answer()


@dp.message(F.photo)
async def receive_photo(message: Message):
    row = db.execute(
        "SELECT * FROM applications WHERE user_id=? AND status='collecting' "
        "ORDER BY id DESC LIMIT 1",
        (message.from_user.id,)
    ).fetchone()
    if not row:
        await message.answer("Сначала выбери награду командой /start.")
        return

    count = db.execute(
        "SELECT COUNT(*) FROM screenshots WHERE application_id=?",
        (row["id"],)
    ).fetchone()[0]
    if count >= REQUIRED_COUNT:
        await message.answer("Уже получено 20 скриншотов. Дождись проверки администрации.")
        return

    file = await bot.get_file(message.photo[-1].file_id)
    buffer = io.BytesIO()
    await bot.download_file(file.file_path, destination=buffer)
    data = buffer.getvalue()

    sha = hashlib.sha256(data).hexdigest()
    try:
        dhash = difference_hash(data)
    except Exception:
        await message.answer("Не удалось прочитать изображение. Отправь скриншот ещё раз.")
        return

    previous = db.execute(
        "SELECT sha256, dhash FROM screenshots WHERE application_id=?",
        (row["id"],)
    ).fetchall()

    reason = None
    if any(item["sha256"] == sha for item in previous):
        reason = "точный дубликат изображения"
    elif any(hamming_distance(item["dhash"], dhash) <= 4 for item in previous):
        reason = "изображение очень похоже на ранее отправленный скриншот"

    ocr_text = ""
    if not reason:
        try:
            ocr_text = await recognize_text(data)
        except Exception:
            ocr_text = ""

        expected = normalize(REWARDS[row["reward"]]["comment"])
        found = normalize(ocr_text)
        if not OCR_API_KEY:
            reason = "OCR не настроен — нужна ручная проверка"
        elif not found:
            reason = "не удалось распознать текст на скриншоте"
        elif expected not in found:
            reason = "не найден требуемый текст комментария"

    suspicious = int(reason is not None)
    db.execute(
        "INSERT INTO screenshots(application_id, file_id, sha256, dhash, "
        "ocr_text, suspicious, reason) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            row["id"], message.photo[-1].file_id, sha, dhash,
            ocr_text[:4000], suspicious, reason
        )
    )
    db.commit()

    new_count = count + 1
    await message.answer(
        f"Получено: <b>{new_count}/{REQUIRED_COUNT}</b>"
        + ("\n⚠️ Этот скриншот отправлен администрации на ручную проверку."
           if suspicious else "\n✅ Текст распознан."),
        parse_mode="HTML",
    )

    if suspicious:
        await bot.send_photo(
            ADMIN_ID,
            message.photo[-1].file_id,
            caption=(
                f"⚠️ <b>Подозрительный скриншот</b>\n"
                f"Заявка #{row['id']}\n"
                f"Пользователь ID: <code>{message.from_user.id}</code>\n"
                f"Причина: {reason}\n"
                f"Распознанный текст: {ocr_text[:700] or 'нет'}"
            ),
            parse_mode="HTML",
        )

    if new_count == REQUIRED_COUNT:
        db.execute(
            "UPDATE applications SET status='pending' WHERE id=?",
            (row["id"],)
        )
        db.commit()
        await message.answer(
            "🎉 Все 20 скриншотов получены!\n"
            "Заявка отправлена администрации. Ожидай решения."
        )
        await send_application_to_admin(row["id"])


@dp.message()
async def other_message(message: Message):
    row = db.execute(
        "SELECT id FROM applications WHERE user_id=? AND status='collecting' "
        "ORDER BY id DESC LIMIT 1",
        (message.from_user.id,)
    ).fetchone()
    if row:
        await message.answer("Пожалуйста, отправляй именно скриншоты как фото.")
    else:
        await message.answer("Нажми /start, чтобы начать.")


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
        status = "approved"
        user_text = "✅ Твоя заявка одобрена администрацией."
        admin_text = f"Заявка #{app_id} принята."
    elif action == "reject":
        status = "rejected"
        user_text = "❌ Твоя заявка отклонена администрацией."
        admin_text = f"Заявка #{app_id} отклонена."
    else:
        await callback.answer("Неизвестное действие.", show_alert=True)
        return

    db.execute("UPDATE applications SET status=? WHERE id=?", (status, app_id))
    db.commit()
    await bot.send_message(app["user_id"], user_text)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(admin_text)
    await callback.answer("Готово")


async def main():
    print("FREE STARS bot started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
