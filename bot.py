import asyncio
import re
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from aiogram.utils.media_group import MediaGroupBuilder

from config import *
from database import *

# ---------------- ЛОГИРОВАНИЕ ----------------

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()


# ---------------- АНТИ-СПАМ ----------------

class AntiSpam:
    def __init__(self):
        self.user_messages = defaultdict(list)
        self.user_posts = defaultdict(list)
        self.blocked_users = {}
    
    def is_blocked(self, user_id: int) -> bool:
        if user_id in self.blocked_users:
            if datetime.now() < self.blocked_users[user_id]:
                return True
            else:
                del self.blocked_users[user_id]
        return False
    
    def get_block_time(self, user_id: int) -> str:
        if user_id in self.blocked_users:
            delta = self.blocked_users[user_id] - datetime.now()
            hours = delta.seconds // 3600
            minutes = (delta.seconds % 3600) // 60
            seconds = delta.seconds % 60
            
            parts = []
            if hours > 0:
                parts.append(f"{hours} ч")
            if minutes > 0:
                parts.append(f"{minutes} мин")
            parts.append(f"{seconds} сек")
            return " ".join(parts)
        return "0 сек"
    
    def check_flood(self, user_id: int, limit: int = 3, period: int = 60) -> bool:
        now = datetime.now()
        self.user_messages[user_id] = [
            t for t in self.user_messages[user_id] 
            if now - t < timedelta(seconds=period)
        ]
        self.user_messages[user_id].append(now)
        
        if len(self.user_messages[user_id]) > limit:
            self.blocked_users[user_id] = now + timedelta(hours=1)
            logger.warning(f"Пользователь {user_id} заблокирован за флуд на 1 час")
            return True
        
        return False
    
    def check_post_limit(self, user_id: int, limit: int = 3, hours: int = 2) -> bool:
        now = datetime.now()
        self.user_posts[user_id] = [
            t for t in self.user_posts[user_id] 
            if now - t < timedelta(hours=24)
        ]
        
        if len(self.user_posts[user_id]) >= limit:
            return True
        
        if self.user_posts[user_id]:
            last_post_time = self.user_posts[user_id][-1]
            if now - last_post_time < timedelta(hours=hours):
                return True
        
        return False
    
    def get_remaining_posts(self, user_id: int) -> int:
        now = datetime.now()
        self.user_posts[user_id] = [
            t for t in self.user_posts[user_id] 
            if now - t < timedelta(hours=24)
        ]
        return 3 - len(self.user_posts[user_id])
    
    def get_next_post_time(self, user_id: int) -> str:
        if not self.user_posts[user_id]:
            return "сейчас"
        
        now = datetime.now()
        last_post = self.user_posts[user_id][-1]
        next_time = last_post + timedelta(hours=2)
        
        if next_time <= now:
            return "сейчас"
        
        delta = next_time - now
        hours = delta.seconds // 3600
        minutes = (delta.seconds % 3600) // 60
        
        if hours > 0:
            return f"через {hours} ч {minutes} мин"
        return f"через {minutes} мин"
    
    def add_post(self, user_id: int):
        self.user_posts[user_id].append(datetime.now())

anti_spam = AntiSpam()


# ---------------- ВЕРИФИКАЦИЯ ----------------

class Verification:
    def __init__(self):
        self.verified_users = set()
    
    def is_verified(self, user_id: int) -> bool:
        return user_id in self.verified_users
    
    def verify_user(self, user_id: int):
        self.verified_users.add(user_id)

verification = Verification()

def get_verify_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, мне есть 21 год", callback_data="verify_age")],
        [InlineKeyboardButton(text="❌ Нет, мне нет 21 года", callback_data="verify_reject")]
    ])


# ---------------- КНОПКИ ----------------

def mod_kb(post_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve:{post_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{post_id}")
        ]
    ])


def post_kb(username: str = None, user_id: int = None):
    """Кнопки под постом в канале"""
    if username:
        contact_url = f"https://t.me/{username}"
    else:
        contact_url = f"tg://user?id={user_id}"
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📩 Написать продавцу", url=contact_url)],
        [InlineKeyboardButton(text="📝 Подать объявление", url="https://t.me/krd_vapebot")],
        [InlineKeyboardButton(text="📢 Реклама", url="https://t.me/a_operay")]
    ])


# ---------------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ----------------

def format_remaining_text(remaining: int) -> str:
    """Красивое отображение остатка постов"""
    if remaining == 0:
        return "лимит исчерпан"
    elif remaining == 1:
        return "ещё 1 объявление"
    elif remaining == 2:
        return "ещё 2 объявления"
    else:
        return f"ещё {remaining} объявления"

# ---------------- START ----------------

@dp.message(F.text == "/start")
async def start(message: Message):
    if not verification.is_verified(message.from_user.id):
        await message.answer(
            "👋 <b>Добро пожаловать!</b>\n\n"
            "Для подачи объявлений необходимо подтвердить возраст.\n"
            "Материалы канала предназначены для лиц старше 21 года.",
            reply_markup=get_verify_kb(),
            parse_mode="HTML"
        )
        return
    
    await message.answer(
        "👋 <b>Добро пожаловать!</b>\n\n"
        "Вы можете подать объявление прямо в этого бота.\n\n"
        "📝 <b>Как подать объявление:</b>\n"
        "• Прикрепите фото (до 3 штук)\n"
        "• Напишите текст в формате:\n"
        "  <i>Название / Описание / Цена / Место встречи</i>\n\n"
        "⏰ <b>Ограничения:</b>\n"
        "• Не более 3 объявлений в сутки\n"
        "• Перерыв между публикациями — 2 часа\n"
        "• За флуд — бан на 1 час\n\n"
        "📢 По вопросам рекламы: @a_operay\n\n"
        "📋 <b>Команды:</b>\n"
        "/start — главное меню\n"
        "/rules — правила\n"
        "/id — мой Telegram ID",
        parse_mode="HTML"
    )


# ---------------- /rules ----------------

@dp.message(F.text == "/rules")
async def rules(message: Message):
    await message.answer(
        "📋 <b>Правила подачи объявлений</b>\n\n"
        "<b>Как оформить объявление:</b>\n"
        "• Прикрепите фото (до 3 штук)\n"
        "• Напишите текст в формате:\n"
        "  <i>Название / Описание / Цена / Место встречи</i>\n\n"
        "<b>Ограничения:</b>\n"
        "• Не более 3 объявлений в сутки\n"
        "• Перерыв между публикациями — 2 часа\n"
        "• За флуд — бан на 1 час\n\n"
        "⚠️ Запрещено:\n"
        "• Оскорбления и спам\n"
        "• Объявления не по теме\n"
        "• Предоплата без гарантий\n\n"
        "По спорным вопросам: @callumom",
        parse_mode="HTML"
    )


# ---------------- /id ----------------

@dp.message(F.text == "/id")
async def get_id(message: Message):
    await message.answer(
        "🆔 <b>Ваши данные:</b>\n\n"
        f"ID: <code>{message.from_user.id}</code>\n"
        f"Username: @{message.from_user.username if message.from_user.username else 'не указан'}\n"
        f"Имя: {message.from_user.full_name}",
        parse_mode="HTML"
    )


# ---------------- ВЕРИФИКАЦИЯ CALLBACKS ----------------

@dp.callback_query(F.data == "verify_age")
async def verify_age(callback: CallbackQuery):
    user = callback.from_user
    
    if hasattr(user, 'created_at'):
        account_age = (datetime.now() - user.created_at).days
        if account_age < 3:
            await callback.answer("❌ Аккаунт должен быть старше 3 дней", show_alert=True)
            return
    
    verification.verify_user(user.id)
    logger.info(f"Пользователь {user.id} верифицирован")
    
    await callback.message.delete()
    await callback.message.answer(
        "✅ <b>Возраст подтверждён!</b>\n\n"
        "Теперь вы можете подавать объявления.\n\n"
        "📝 <b>Как подать объявление:</b>\n"
        "• Прикрепите фото (до 3 штук)\n"
        "• Напишите текст в формате:\n"
        "  <i>Название / Описание / Цена / Место встречи</i>\n\n"
        "Просто отправьте объявление в чат!",
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "verify_reject")
async def verify_reject(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(
        "😔 К сожалению, доступ к боту разрешён только с 21 года.\n\n"
        "Если вы считаете, что произошла ошибка — @callumom"
    )
    await callback.answer()


# ---------------- TEXT (без медиа) ----------------

@dp.message(F.text)
async def text_post(message: Message):
    if message.text.startswith("/"):
        return
    
    user_id = message.from_user.id
    
    if not verification.is_verified(user_id):
        await message.answer(
            "❌ Сначала подтвердите возраст.\n"
            "Отправьте /start"
        )
        return
    
    if anti_spam.is_blocked(user_id):
        block_time = anti_spam.get_block_time(user_id)
        await message.answer(
            "🚫 <b>Вы временно заблокированы</b>\n\n"
            f"Причина: флуд\n"
            f"Разблокировка через: {block_time}\n\n"
            "Пожалуйста, не отправляйте много сообщений подряд.",
            parse_mode="HTML"
        )
        return
    
    if anti_spam.check_flood(user_id):
        block_time = anti_spam.get_block_time(user_id)
        await message.answer(
            "🚫 <b>Блокировка на 1 час!</b>\n\n"
            "Вы отправляете слишком много сообщений.\n"
            f"Разблокировка через: {block_time}",
            parse_mode="HTML"
        )
        return
    
    if anti_spam.check_post_limit(user_id):
        remaining = anti_spam.get_remaining_posts(user_id)
        next_time = anti_spam.get_next_post_time(user_id)
        
        if remaining > 0:
            await message.answer(
                f"⏰ <b>Подождите немного</b>\n\n"
                f"Следующее объявление можно отправить {next_time}.\n"
                f"Сегодня доступно: {format_remaining_text(remaining)}",
                parse_mode="HTML"
            )
        else:
            await message.answer(
                "📊 <b>Лимит исчерпан</b>\n\n"
                "Вы использовали все 3 объявления на сегодня.\n"
                "Приходите завтра!",
                parse_mode="HTML"
            )
        return
    
    if not message.text or not message.text.strip():
        await message.answer("❌ Добавьте текст к объявлению.")
        return
    
    post_id = await add_post(
        message.from_user.id,
        message.from_user.username,
        message.text,
        None,
        "text"
    )
    
    anti_spam.add_post(user_id)
    remaining = anti_spam.get_remaining_posts(user_id)
    
    logger.info(f"Новый пост #{post_id} от @{message.from_user.username}")

    await bot.send_message(
        MODERATION_CHAT_ID,
        "📋 <b>Новое объявление</b>\n"
        f"ID: <code>#{post_id}</code>\n\n"
        f"{message.text}\n\n"
        f"👤 @{message.from_user.username}",
        reply_markup=mod_kb(post_id),
        parse_mode="HTML"
    )

    await message.answer(
        "✅ <b>Объявление отправлено!</b>\n\n"
        "Оно появится в канале после проверки модератором.\n\n"
        f"📊 Сегодня доступно: {format_remaining_text(remaining)}",
        parse_mode="HTML"
    )


# ---------------- ОДИНОЧНОЕ ФОТО ----------------

@dp.message(F.photo, ~F.media_group_id)
async def single_photo_post(message: Message):
    user_id = message.from_user.id
    
    if not verification.is_verified(user_id):
        await message.answer("❌ Сначала подтвердите возраст. Отправьте /start")
        return
    
    if anti_spam.is_blocked(user_id):
        block_time = anti_spam.get_block_time(user_id)
        await message.answer(
            f"🚫 Вы временно заблокированы.\nРазблокировка через: {block_time}"
        )
        return
    
    if anti_spam.check_flood(user_id):
        block_time = anti_spam.get_block_time(user_id)
        await message.answer(
            f"🚫 Блокировка на 1 час за флуд!\nРазблокировка через: {block_time}"
        )
        return
    
    if anti_spam.check_post_limit(user_id):
        remaining = anti_spam.get_remaining_posts(user_id)
        next_time = anti_spam.get_next_post_time(user_id)
        
        if remaining > 0:
            await message.answer(
                f"⏰ Следующее объявление можно отправить {next_time}.\n"
                f"Сегодня доступно: {format_remaining_text(remaining)}"
            )
        else:
            await message.answer("📊 Лимит на сегодня исчерпан (3 из 3).")
        return
    
    text = message.caption or ""
    
    if not text or not text.strip():
        await message.answer("❌ Добавьте текст к объявлению.")
        return
    
    file_id = message.photo[-1].file_id

    post_id = await add_post(
        message.from_user.id,
        message.from_user.username,
        text,
        file_id,
        "photo"
    )
    
    anti_spam.add_post(user_id)
    remaining = anti_spam.get_remaining_posts(user_id)
    
    logger.info(f"Новый пост #{post_id} (фото) от @{message.from_user.username}")

    await bot.send_photo(
        MODERATION_CHAT_ID,
        file_id,
        caption=(
            "📋 <b>Новое объявление</b>\n"
            f"ID: <code>#{post_id}</code>\n\n"
            f"{text}\n\n"
            f"👤 @{message.from_user.username}"
        ),
        reply_markup=mod_kb(post_id),
        parse_mode="HTML"
    )

    await message.answer(
        "✅ <b>Объявление отправлено!</b>\n\n"
        "Оно появится в канале после проверки.\n\n"
        f"📊 Сегодня доступно: {format_remaining_text(remaining)}",
        parse_mode="HTML"
    )


# ---------------- АЛЬБОМ (2-3 фото) ----------------

album_cache = defaultdict(list)
album_timers = {}


async def process_album(user_id: int, chat_id: int):
    if user_id not in album_cache:
        return
    
    messages = album_cache[user_id]
    
    if not messages:
        return
    
    text = ""
    for msg in messages:
        if msg.caption:
            text = msg.caption
            break
    
    file_ids = []
    for msg in messages[:3]:
        if msg.photo:
            file_ids.append(msg.photo[-1].file_id)
    
    if not file_ids:
        return
    
    if not verification.is_verified(user_id):
        await bot.send_message(chat_id, "❌ Сначала подтвердите возраст. Отправьте /start")
        del album_cache[user_id]
        return
    
    if anti_spam.is_blocked(user_id):
        block_time = anti_spam.get_block_time(user_id)
        await bot.send_message(chat_id, f"🚫 Вы заблокированы. Разблокировка через: {block_time}")
        del album_cache[user_id]
        return
    
    if anti_spam.check_post_limit(user_id):
        remaining = anti_spam.get_remaining_posts(user_id)
        next_time = anti_spam.get_next_post_time(user_id)
        
        if remaining > 0:
            await bot.send_message(
                chat_id,
                f"⏰ Следующее объявление можно отправить {next_time}.\n"
                f"Сегодня доступно: {format_remaining_text(remaining)}"
            )
        else:
            await bot.send_message(chat_id, "📊 Лимит на сегодня исчерпан.")
        del album_cache[user_id]
        return
    
    if not text or not text.strip():
        await bot.send_message(chat_id, "❌ Добавьте текст к объявлению.")
        del album_cache[user_id]
        return
    
    post_id = await add_post(
        user_id,
        messages[0].from_user.username,
        text,
        file_ids[0],
        "photo"
    )
    
    anti_spam.add_post(user_id)
    remaining = anti_spam.get_remaining_posts(user_id)
    
    logger.info(f"Новый пост #{post_id} (альбом) от @{messages[0].from_user.username}")
    
    await bot.send_photo(
        MODERATION_CHAT_ID,
        file_ids[0],
        caption=(
            "📋 <b>Новое объявление</b>\n"
            f"ID: <code>#{post_id}</code>\n"
            f"📸 Фото: {len(file_ids)} шт.\n\n"
            f"{text}\n\n"
            f"👤 @{messages[0].from_user.username}"
        ),
        reply_markup=mod_kb(post_id),
        parse_mode="HTML"
    )
    
    if len(file_ids) > 1:
        media_group = []
        for fid in file_ids[1:]:
            media_group.append(InputMediaPhoto(media=fid))
        
        await bot.send_media_group(MODERATION_CHAT_ID, media_group)
    
    await bot.send_message(
        chat_id,
        "✅ <b>Объявление отправлено!</b>\n\n"
        "Оно появится в канале после проверки.\n\n"
        f"📊 Сегодня доступно: {format_remaining_text(remaining)}",
        parse_mode="HTML"
    )
    
    del album_cache[user_id]


@dp.message(F.photo, F.media_group_id)
async def collect_album(message: Message):
    user_id = message.from_user.id
    
    album_cache[user_id].append(message)
    
    if user_id in album_timers:
        album_timers[user_id].cancel()
    
    album_timers[user_id] = asyncio.create_task(asyncio.sleep(1))
    
    try:
        await album_timers[user_id]
        await process_album(user_id, message.chat.id)
    except asyncio.CancelledError:
        pass


# ---------------- VIDEO ----------------

@dp.message(F.video)
async def video_post(message: Message):
    user_id = message.from_user.id
    
    if not verification.is_verified(user_id):
        await message.answer("❌ Сначала подтвердите возраст. Отправьте /start")
        return
    
    if anti_spam.is_blocked(user_id):
        block_time = anti_spam.get_block_time(user_id)
        await message.answer(f"🚫 Вы заблокированы. Разблокировка через: {block_time}")
        return
    
    if anti_spam.check_flood(user_id):
        block_time = anti_spam.get_block_time(user_id)
        await message.answer(f"🚫 Блокировка на 1 час за флуд!\nРазблокировка через: {block_time}")
        return
    
    if anti_spam.check_post_limit(user_id):
        remaining = anti_spam.get_remaining_posts(user_id)
        next_time = anti_spam.get_next_post_time(user_id)
        
        if remaining > 0:
            await message.answer(
                f"⏰ Следующее объявление можно отправить {next_time}.\n"
                f"Сегодня доступно: {format_remaining_text(remaining)}"
            )
        else:
            await message.answer("📊 Лимит на сегодня исчерпан.")
        return
    
    text = message.caption or ""
    
    if not text or not text.strip():
        await message.answer("❌ Добавьте текст к объявлению.")
        return
    
    file_id = message.video.file_id

    post_id = await add_post(
        message.from_user.id,
        message.from_user.username,
        text,
        file_id,
        "video"
    )
    
    anti_spam.add_post(user_id)
    remaining = anti_spam.get_remaining_posts(user_id)
    
    logger.info(f"Новый пост #{post_id} (видео) от @{message.from_user.username}")

    await bot.send_video(
        MODERATION_CHAT_ID,
        file_id,
        caption=(
            "📋 <b>Новое объявление</b>\n"
            f"ID: <code>#{post_id}</code>\n\n"
            f"{text}\n\n"
            f"👤 @{message.from_user.username}"
        ),
        reply_markup=mod_kb(post_id),
        parse_mode="HTML"
    )

    await message.answer(
        "✅ <b>Объявление отправлено!</b>\n\n"
        "Оно появится в канале после проверки.\n\n"
        f"📊 Сегодня доступно: {format_remaining_text(remaining)}",
        parse_mode="HTML"
    )


# ---------------- CALLBACKS ----------------

@dp.callback_query(F.data.startswith("approve:"))
async def approve(callback: CallbackQuery):
    post_id = int(callback.data.split(":")[1])

    post = await get_post(post_id)
    if not post:
        return

    _, user_id, username, text, file_id, file_type, _ = post

    disclaimer = (
        "\n\n"
        "───────────────\n\n"
        "⚠️ Не переводите предоплату незнакомым людям.\n"
        "Будьте внимательны при совершении сделок.\n"
        "Канал носит информационный характер. 21+"
    )

    final_text = f"{text}{disclaimer}"

    kb = post_kb(username=username, user_id=user_id)

    if file_type == "photo":
        await bot.send_photo(MARKET_CHANNEL_ID, file_id, caption=final_text, reply_markup=kb)
    elif file_type == "video":
        await bot.send_video(MARKET_CHANNEL_ID, file_id, caption=final_text, reply_markup=kb)
    else:
        await bot.send_message(MARKET_CHANNEL_ID, final_text, reply_markup=kb)

    await update_status(post_id, "approved")
    logger.info(f"Пост #{post_id} одобрен")

    await bot.send_message(
        user_id,
        "🎉 <b>Объявление опубликовано!</b>\n\n"
        "Оно уже в канале.\n\n"
        "Хотите ещё? Отправляйте следующее.\n"
        "Не более 3 объявлений в день с интервалом 2 часа.",
        parse_mode="HTML"
    )

    await callback.message.edit_reply_markup()
    await callback.answer("✅ Одобрено!")


@dp.callback_query(F.data.startswith("reject:"))
async def reject(callback: CallbackQuery):
    post_id = int(callback.data.split(":")[1])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Нарушение правил", callback_data=f"reject_reason:rules:{post_id}")],
        [InlineKeyboardButton(text="📝 Неверный формат", callback_data=f"reject_reason:format:{post_id}")],
        [InlineKeyboardButton(text="🚫 Спам", callback_data=f"reject_reason:spam:{post_id}")],
        [InlineKeyboardButton(text="🎯 Не по теме", callback_data=f"reject_reason:offtopic:{post_id}")],
        [InlineKeyboardButton(text="💬 Другое", callback_data=f"reject_reason:other:{post_id}")],
        [InlineKeyboardButton(text="↩️ Отмена", callback_data=f"back_to_mod:{post_id}")]
    ])
    
    await callback.message.edit_reply_markup(reply_markup=keyboard)
    await callback.answer("Выберите причину отклонения:")


@dp.callback_query(F.data.startswith("reject_reason:"))
async def reject_with_reason(callback: CallbackQuery):
    _, reason, post_id = callback.data.split(":")
    post_id = int(post_id)
    
    reasons = {
        "rules": "Нарушение правил",
        "format": "Неверный формат объявления",
        "spam": "Спам",
        "offtopic": "Не по теме канала",
        "other": "Другая причина"
    }
    
    reason_text = reasons.get(reason, "Не указана")
    
    post = await get_post(post_id)
    if not post:
        return
    
    user_id = post[1]
    
    await update_status(post_id, "rejected")
    logger.info(f"Пост #{post_id} отклонен. Причина: {reason_text}")
    
    try:
        await bot.send_message(
            user_id,
            "❌ <b>Объявление отклонено</b>\n\n"
            f"Причина: {reason_text}\n\n"
            "Вы можете отправить новое объявление, исправив ошибки.\n"
            "Если не согласны с решением — @callumom",
            parse_mode="HTML"
        )
    except:
        pass
    
    status_text = f"❌ Отклонено: {reason_text}"
    
    if callback.message.text:
        new_text = callback.message.text + f"\n\n{status_text}"
    else:
        current_caption = callback.message.caption or ""
        new_text = current_caption + f"\n\n{status_text}"
    
    try:
        if callback.message.text:
            await callback.message.edit_text(new_text)
        else:
            await callback.message.edit_caption(caption=new_text)
    except:
        pass
    
    await callback.answer(f"Отклонено: {reason_text}")


@dp.callback_query(F.data.startswith("back_to_mod:"))
async def back_to_mod(callback: CallbackQuery):
    post_id = int(callback.data.split(":")[1])
    
    await callback.message.edit_reply_markup(reply_markup=mod_kb(post_id))
    await callback.answer("↩️ Отмена")


# ---------------- НЕИЗВЕСТНЫЕ КОМАНДЫ ----------------

@dp.message(F.text.startswith("/"))
async def unknown_command(message: Message):
    await message.answer(
        "❓ <b>Неизвестная команда</b>\n\n"
        "Доступные команды:\n"
        "/start — главное меню\n"
        "/rules — правила\n"
        "/id — мой Telegram ID",
        parse_mode="HTML"
    )


# ---------------- START BOT ----------------

async def main():
    await init_db()
    logger.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
