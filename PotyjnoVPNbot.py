import telebot
from telebot import types
import psycopg2
import time
from datetime import datetime
import os
from flask import Flask
from threading import Thread
import requests
import re
from bs4 import BeautifulSoup
import random
import string
import socket
import threading

# ========== ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ==========
BOT_TOKEN = os.getenv('BOT_TOKEN', '8621740437:AAHXYevornlIKyNN204hrZ307slYZiYIqTE')
ADMIN_ID = int(os.getenv('ADMIN_ID', 8176196456))
DATABASE_URL = os.getenv('DATABASE_URL')

# ========== НАСТРОЙКИ КАНАЛА ==========
CHANNEL_ID = -1003668283208
CHANNEL_LINK = "https://t.me/ciorsa"

# ========== ПОДДЕРЖКА ==========
SUPPORT_USERNAME = "@mel1ste"

# ========== ИНИЦИАЛИЗАЦИЯ ==========
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# ========== ГЕНЕРАЦИЯ ТОКЕНА ==========
def generate_subscription_token(length=12):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

# ========== БАЗА ДАННЫХ (POSTGRESQL) ==========
def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            subscription_end BIGINT,
            notified_3days INTEGER DEFAULT 0,
            last_activity BIGINT DEFAULT 0,
            is_blocked INTEGER DEFAULT 0,
            token TEXT UNIQUE
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            user_id BIGINT PRIMARY KEY,
            added_by BIGINT,
            added_at BIGINT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS referrals (
            referrer_id BIGINT,
            referred_id BIGINT,
            reward_date BIGINT,
            rewarded INTEGER DEFAULT 0,
            PRIMARY KEY (referrer_id, referred_id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

# ========== РАБОТА С НАСТРОЙКАМИ ==========
def get_setting(key, default='0'):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = %s", (key,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else default

def set_setting(key, value):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
        (key, value)
    )
    conn.commit()
    conn.close()

# ========== ФУНКЦИИ ПРОВЕРКИ ==========
def is_admin(user_id):
    if user_id == ADMIN_ID:
        return True
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM admins WHERE user_id = %s", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def is_subscribed(user_id):
    try:
        member = bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except:
        return False

def get_subscription_link(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT token FROM users WHERE user_id = %s", (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        token = result[0]
    else:
        token = generate_subscription_token()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET token = %s WHERE user_id = %s", (token, user_id))
        conn.commit()
        conn.close()
    
    return f"https://potyjnovpnbot.onrender.com/sub/{token}"

def is_blocked(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT is_blocked FROM users WHERE user_id = %s", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result and result[0] == 1

def can_add_referral(referrer_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    today_start = int(time.time()) - 24 * 60 * 60
    cursor.execute(
        "SELECT COUNT(*) FROM referrals WHERE referrer_id = %s AND reward_date > %s",
        (referrer_id, today_start)
    )
    count = cursor.fetchone()[0]
    conn.close()
    
    return count < 10

# ========== ПРОВЕРКА КЛЮЧЕЙ (ПИНГ) ==========
check_results = {}

def ping_key(key):
    try:
        match = re.search(r'@([\d\.]+):(\d+)', key)
        if not match:
            match = re.search(r'vless://[^@]+@([\d\.]+):(\d+)', key)
        if not match:
            return False
        
        ip = match.group(1)
        port = int(match.group(2))
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex((ip, port))
        sock.close()
        return result == 0
    except:
        return False

def check_keys_async(chat_id, keys, user_id, message_id):
    results = []
    working = 0
    not_working = 0
    
    for i, key in enumerate(keys):
        if i % 3 == 0:
            try:
                bot.edit_message_text(
                    f"🔍 Проверка ключей...\n\n"
                    f"📊 Проверено: {i}/{len(keys)}\n"
                    f"✅ Работает: {working}\n"
                    f"❌ Не работает: {not_working}",
                    chat_id,
                    message_id
                )
            except:
                pass
        
        status = ping_key(key)
        results.append((key, status))
        if status:
            working += 1
        else:
            not_working += 1
    
    report = f"📊 *Результаты проверки*\n\n"
    report += f"✅ Работает: {working}\n"
    report += f"❌ Не работает: {not_working}\n"
    report += f"📡 Всего проверено: {len(keys)}\n\n"
    
    if not_working > 0:
        report += "*❌ Не работающие ключи:*\n"
        for key, status in results:
            if not status:
                short_key = key[:60] + "..." if len(key) > 60 else key
                report += f"└ {short_key}\n"
    else:
        report += "🎉 *Все ключи работают!*"
    
    try:
        bot.send_message(chat_id, report, parse_mode="Markdown")
    except:
        bot.send_message(chat_id, report)
    
    if user_id in check_results:
        del check_results[user_id]

# ========== КЛАВИАТУРЫ ==========
def main_menu():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn1 = types.KeyboardButton("👤 Личный кабинет")
    btn2 = types.KeyboardButton("📡 Моя подписка")
    btn3 = types.KeyboardButton("👥 Рефералы")
    btn4 = types.KeyboardButton("🏆 Топ рефералов")
    btn5 = types.KeyboardButton("🔍 Проверка ключей")
    btn6 = types.KeyboardButton("❓ Поддержка")
    keyboard.add(btn1, btn2)
    keyboard.add(btn3, btn4)
    keyboard.add(btn5, btn6)
    return keyboard

def subscribe_button():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("📢 ПОДПИСАТЬСЯ", url=CHANNEL_LINK))
    keyboard.add(types.InlineKeyboardButton("✅ Я подписался", callback_data="check_sub"))
    return keyboard

# ========== КОМАНДА /START ==========
@bot.message_handler(commands=['start'])
def start_command(message):
    if message.chat.type != "private":
        bot.reply_to(message, "⚠️ Бот работает только в личных сообщениях.")
        return
    
    user_id = message.from_user.id
    
    if is_blocked(user_id):
        bot.reply_to(message, "🚫 Вы заблокированы администратором. Обратитесь в поддержку: @mel1ste")
        return
    
    referrer_id = None
    if len(message.text.split()) > 1:
        ref_param = message.text.split()[1]
        if ref_param.startswith('ref_'):
            try:
                referrer_id = int(ref_param.split('_')[1])
            except:
                pass
    
    if referrer_id and referrer_id != user_id:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT * FROM referrals WHERE referrer_id = %s AND referred_id = %s",
            (referrer_id, user_id)
        )
        already_ref = cursor.fetchone()
        
        if not already_ref:
            if can_add_referral(referrer_id):
                cursor.execute(
                    "INSERT INTO referrals (referrer_id, referred_id, reward_date, rewarded) VALUES (%s, %s, %s, %s)",
                    (referrer_id, user_id, int(time.time()), 0)
                )
                conn.commit()
                
                try:
                    new_user = bot.get_chat(user_id)
                    new_user_name = f"@{new_user.username}" if new_user.username else new_user.first_name
                    bot.send_message(
                        referrer_id,
                        f"🔔 Новый реферал!\n\n"
                        f"Пользователь {new_user_name} присоединился по вашей реферальной ссылке."
                    )
                except:
                    pass
                
                if is_subscribed(referrer_id) and int(get_setting('referral_enabled')) == 1:
                    cursor.execute("SELECT subscription_end FROM users WHERE user_id = %s", (referrer_id,))
                    ref_result = cursor.fetchone()
                    if ref_result:
                        new_end = ref_result[0] + 3 * 24 * 60 * 60
                        cursor.execute(
                            "UPDATE users SET subscription_end = %s WHERE user_id = %s",
                            (new_end, referrer_id)
                        )
                        cursor.execute(
                            "UPDATE referrals SET rewarded = 1 WHERE referrer_id = %s AND referred_id = %s",
                            (referrer_id, user_id)
                        )
                        conn.commit()
                        
                        try:
                            bot.send_message(
                                referrer_id,
                                f"🎉 Вам начислено +3 дня за реферала {new_user_name}!"
                            )
                        except:
                            pass
            else:
                try:
                    bot.send_message(
                        referrer_id,
                        "⚠️ Вы достигли лимита рефералов (10 в день). Попробуйте завтра."
                    )
                except:
                    pass
        conn.close()
    
    if not is_subscribed(user_id):
        bot.reply_to(
            message,
            "⚠️ Подпишитесь на канал, чтобы пользоваться ботом.",
            reply_markup=subscribe_button()
        )
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, last_activity, token FROM users WHERE user_id = %s", (user_id,))
    user = cursor.fetchone()
    
    current_time = int(time.time())
    
    if not user:
        token = generate_subscription_token()
        cursor.execute(
            "INSERT INTO users (user_id, subscription_end, last_activity, is_blocked, token) VALUES (%s, %s, %s, %s, %s)",
            (user_id, current_time + 7*24*60*60, current_time, 0, token)
        )
        conn.commit()
        bot.reply_to(message, "🎉 Добро пожаловать! Вам выдана подписка на 7 дней.")
    else:
        last_activity = user[1] if user[1] else 0
        days_since_last = (current_time - last_activity) // (24*60*60)
        
        if days_since_last >= 3:
            bot.reply_to(message, "👋 С возвращением!")
        else:
            bot.reply_to(message, "👋 Добро пожаловать!")
        
        cursor.execute(
            "UPDATE users SET last_activity = %s WHERE user_id = %s",
            (current_time, user_id)
        )
        conn.commit()
    
    conn.close()
    bot.reply_to(message, "Выберите действие:", reply_markup=main_menu())

# ========== КНОПКА "ЛИЧНЫЙ КАБИНЕТ" ==========
@bot.message_handler(func=lambda message: message.text == "👤 Личный кабинет")
def profile_command(message):
    if message.chat.type != "private":
        return
    
    user_id = message.from_user.id
    
    if is_blocked(user_id):
        bot.reply_to(message, "🚫 Вы заблокированы администратором. Обратитесь в поддержку: @mel1ste")
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT subscription_end, token FROM users WHERE user_id = %s", (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        bot.reply_to(message, "❌ Вы не зарегистрированы. Используйте /start")
        return
    
    subscription_end, token = result
    current_time = int(time.time())
    
    if subscription_end > current_time:
        status = "✅ Активна"
        days_left = (subscription_end - current_time) // (24*60*60)
        hours_left = (subscription_end - current_time) // (60*60) % 24
        time_left = f"{days_left} дн {hours_left} ч"
        expire_date = datetime.fromtimestamp(subscription_end).strftime("%d.%m.%Y в %H:%M")
        link = get_subscription_link(user_id)
    else:
        status = "❌ Не активна"
        time_left = "Закончилась"
        expire_date = "Закончилась"
        link = "❌ Нет активной подписки"
    
    text = (
        f"👤 Личный кабинет\n\n"
        f"🆔 ID: {user_id}\n"
        f"📅 Подписка до: {expire_date}\n"
        f"⏳ Осталось: {time_left}\n"
        f"📊 Статус: {status}\n"
        f"🔗 Ссылка: {link}"
    )
    bot.reply_to(message, text)

# ========== КНОПКА "МОЯ ПОДПИСКА" ==========
@bot.message_handler(func=lambda message: message.text == "📡 Моя подписка")
def my_subscription(message):
    if message.chat.type != "private":
        return
    
    user_id = message.from_user.id
    
    if is_blocked(user_id):
        bot.reply_to(message, "🚫 Вы заблокированы администратором. Обратитесь в поддержку: @mel1ste")
        return
    
    if not is_subscribed(user_id):
        bot.reply_to(
            message,
            "⚠️ Подпишитесь на канал, чтобы получить доступ.",
            reply_markup=subscribe_button()
        )
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT subscription_end FROM users WHERE user_id = %s", (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        bot.reply_to(message, "❌ Вы не зарегистрированы. Используйте /start")
        return
    
    subscription_end = result[0]
    current_time = int(time.time())
    
    if subscription_end > current_time:
        link = get_subscription_link(user_id)
        bot.reply_to(
            message,
            f"🔗 Ваша ссылка для импорта в VPN-клиент:\n\n{link}\n\n"
            f"Скопируйте её и вставьте в приложение (V2Ray, Hiddify, Nekobox и др.)"
        )
    else:
        bot.reply_to(
            message,
            "❌ Ваша подписка неактивна или истекла.\n\n"
            "Для продления обратитесь к администратору:\n"
            "@mel1ste"
        )

# ========== КНОПКА "РЕФЕРАЛЫ" ==========
@bot.message_handler(func=lambda message: message.text == "👥 Рефералы")
def referrals_command(message):
    if message.chat.type != "private":
        return
    
    user_id = message.from_user.id
    
    if is_blocked(user_id):
        bot.reply_to(message, "🚫 Вы заблокированы администратором. Обратитесь в поддержку: @mel1ste")
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
    if not cursor.fetchone():
        conn.close()
        bot.reply_to(message, "❌ Вы не зарегистрированы. Используйте /start")
        return
    
    cursor.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = %s", (user_id,))
    total = cursor.fetchone()[0]
    
    today_start = int(time.time()) - 24 * 60 * 60
    cursor.execute(
        "SELECT COUNT(*) FROM referrals WHERE referrer_id = %s AND reward_date > %s",
        (user_id, today_start)
    )
    today = cursor.fetchone()[0]
    
    conn.close()
    
    bot_username = bot.get_me().username
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    
    text = (
        f"👥 *Ваши рефералы*\n\n"
        f"📊 Всего: {total}\n"
        f"📅 Сегодня: {today} / 10\n\n"
        f"🔗 *Ваша реферальная ссылка:*\n"
        f"`{ref_link}`\n\n"
        f"📌 *Как это работает:*\n"
        f"• Приглашенные друзья засчитываются вам на баланс\n"
        f"• За каждого друга вы получаете +3 дня подписки\n"
        f"• Лимит: 10 рефералов в день\n\n"
        f"💬 *Вопросы?* Пишите в поддержку: @mel1ste"
    )
    bot.reply_to(message, text, parse_mode="Markdown")

# ========== КНОПКА "ТОП РЕФЕРАЛОВ" ==========
@bot.message_handler(func=lambda message: message.text == "🏆 Топ рефералов")
def top_referrals_command(message):
    if message.chat.type != "private":
        return
    
    user_id = message.from_user.id
    
    if is_blocked(user_id):
        bot.reply_to(message, "🚫 Вы заблокированы администратором. Обратитесь в поддержку: @mel1ste")
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT referrer_id, COUNT(*) as count 
        FROM referrals 
        GROUP BY referrer_id 
        ORDER BY count DESC 
        LIMIT 10
    ''')
    top = cursor.fetchall()
    
    if not top:
        conn.close()
        bot.reply_to(message, "📭 Пока нет рефералов.")
        return
    
    text = "🏆 *Топ рефералов:*\n\n"
    place = 1
    for referrer_id, count in top:
        try:
            user = bot.get_chat(referrer_id)
            name = user.first_name or str(referrer_id)
            if user.username:
                name += f" (@{user.username})"
        except:
            name = str(referrer_id)
        text += f"{place}. {name} — {count} рефералов\n"
        place += 1
    
    conn.close()
    bot.reply_to(message, text, parse_mode="Markdown")

# ========== КНОПКА "ПРОВЕРКА КЛЮЧЕЙ" ==========
@bot.message_handler(func=lambda message: message.text == "🔍 Проверка ключей")
def check_keys_command(message):
    if message.chat.type != "private":
        return
    
    user_id = message.from_user.id
    
    if is_blocked(user_id):
        bot.reply_to(message, "🚫 Вы заблокированы администратором. Обратитесь в поддержку: @mel1ste")
        return
    
    check_results[user_id] = {'waiting': True}
    
    bot.reply_to(
        message,
        "📡 Отправьте файл или текст с ключами (в формате vless://...)\n\n"
        "Я проверю их на доступность (пинг).\n"
        "Ключи должны быть в формате:\n"
        "vless://...\nvless://...\n\n"
        "⏳ Проверка может занять до 30 секунд."
    )

@bot.message_handler(content_types=['document', 'text'])
def handle_keys_input(message):
    user_id = message.from_user.id
    
    if user_id not in check_results or not check_results[user_id].get('waiting', False):
        return
    
    if is_blocked(user_id):
        bot.reply_to(message, "🚫 Вы заблокированы.")
        return
    
    keys = []
    
    if message.document:
        try:
            file_info = bot.get_file(message.document.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            text = downloaded_file.decode('utf-8')
            keys = re.findall(r'vless://[^\s<>"\']+', text)
        except Exception as e:
            bot.reply_to(message, f"❌ Не удалось прочитать файл: {e}")
            return
    
    elif message.text:
        keys = re.findall(r'vless://[^\s<>"\']+', message.text)
    
    if not keys:
        bot.reply_to(
            message,
            "❌ Не найдено ключей в формате vless://\n"
            "Убедитесь, что ключи начинаются с vless://"
        )
        return
    
    keys = list(dict.fromkeys(keys))
    
    msg = bot.reply_to(
        message,
        f"🔍 Найдено ключей: {len(keys)}\n"
        f"⏳ Начинаю проверку...\n"
        f"Это может занять до 30 секунд."
    )
    
    threading.Thread(
        target=check_keys_async,
        args=(message.chat.id, keys, user_id, msg.message_id)
    ).start()

# ========== КНОПКА "ПОДДЕРЖКА" ==========
@bot.message_handler(func=lambda message: message.text == "❓ Поддержка")
def support_command(message):
    if message.chat.type != "private":
        return
    
    user_id = message.from_user.id
    
    if is_blocked(user_id):
        bot.reply_to(message, "🚫 Вы заблокированы администратором. Обратитесь в поддержку: @mel1ste")
        return
    
    bot.reply_to(
        message,
        "📞 По всем вопросам пишите:\n"
        "@mel1ste"
    )

# ========== ОБРАБОТЧИК КНОПКИ "ПОДПИСАЛСЯ" ==========
@bot.callback_query_handler(func=lambda call: call.data == "check_sub")
def check_subscription(call):
    if call.message.chat.type != "private":
        bot.answer_callback_query(call.id, "⚠️ Используйте бота в личных сообщениях.", show_alert=True)
        return
    
    user_id = call.from_user.id
    
    if is_blocked(user_id):
        bot.answer_callback_query(call.id, "🚫 Вы заблокированы.", show_alert=True)
        return
    
    if is_subscribed(user_id):
        bot.answer_callback_query(call.id, "✅ Подписка подтверждена!")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT referrer_id FROM referrals WHERE referred_id = %s AND rewarded = 0",
            (user_id,)
        )
        ref_entry = cursor.fetchone()
        
        if ref_entry and int(get_setting('referral_enabled')) == 1:
            referrer_id = ref_entry[0]
            cursor.execute("SELECT subscription_end FROM users WHERE user_id = %s", (referrer_id,))
            ref_result = cursor.fetchone()
            if ref_result:
                new_end = ref_result[0] + 3 * 24 * 60 * 60
                cursor.execute(
                    "UPDATE users SET subscription_end = %s WHERE user_id = %s",
                    (new_end, referrer_id)
                )
                cursor.execute(
                    "UPDATE referrals SET rewarded = 1 WHERE referred_id = %s",
                    (user_id,)
                )
                conn.commit()
                try:
                    bot.send_message(
                        referrer_id,
                        f"🎉 Ваш реферал подтвердил подписку! Вам начислено +3 дня."
                    )
                except:
                    pass
        
        cursor.execute("SELECT user_id, token FROM users WHERE user_id = %s", (user_id,))
        user = cursor.fetchone()
        
        if not user:
            token = generate_subscription_token()
            cursor.execute(
                "INSERT INTO users (user_id, subscription_end, last_activity, is_blocked, token) VALUES (%s, %s, %s, %s, %s)",
                (user_id, int(time.time()) + 7*24*60*60, int(time.time()), 0, token)
            )
            conn.commit()
            bot.send_message(user_id, "🎉 Добро пожаловать! Вам выдана подписка на 7 дней.")
        else:
            bot.send_message(user_id, "👋 Добро пожаловать!")
        
        conn.close()
        bot.send_message(user_id, "Выберите действие:", reply_markup=main_menu())
    else:
        bot.answer_callback_query(
            call.id,
            "❌ Вы всё ещё не подписаны. Нажмите кнопку и подпишитесь!",
            show_alert=True
        )

# ========== ОБНОВЛЕНИЕ КЛЮЧЕЙ ==========
KEY_TEMPLATE = """#profile-title: 🌐 Потужно VPN Free
#profile-update-interval: 1
#support-url: https://t.me/mel1ste
#announce: 📡 Сервера LTE использовать только при белых списках. Без торрентов. 🕐 Поддержка с 10 до 22, ответят в ближайшее время.
#channel: 📢 https://t.me/ciorsa
#subscription-userinfo: upload=0; download=0; total=10995116277760000; expire={expire}
{keys}"""

def load_keys_from_url(url):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(url, timeout=30, headers=headers)
        response.raise_for_status()
        
        text = response.text
        
        keys = re.findall(r'vless://[^\s<>"\']+', text)
        
        if not keys:
            soup = BeautifulSoup(text, 'html5lib')
            for element in soup.find_all(string=True):
                found = re.findall(r'vless://[^\s<>"\']+', element)
                if found:
                    keys.extend(found)
        
        if not keys:
            json_match = re.search(r'\[{.*}\]', text, re.DOTALL)
            if json_match:
                json_text = json_match.group(0)
                keys = re.findall(r'vless://[^\s<>"\']+', json_text)
        
        seen = set()
        unique_keys = []
        for key in keys:
            if key not in seen:
                seen.add(key)
                unique_keys.append(key)
        
        return unique_keys
    except Exception as e:
        print(f"Ошибка загрузки ключей: {e}")
        return None

def save_keys_to_db(keys):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
        ('vless_keys', '|||'.join(keys))
    )
    conn.commit()
    conn.close()

def get_keys_from_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = %s", ('vless_keys',))
    result = cursor.fetchone()
    conn.close()
    if result:
        return result[0].split('|||')
    return []

@bot.message_handler(commands=['update_keys'])
def update_keys_command(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ У вас нет прав.")
        return
    
    args = message.text.split()
    if len(args) != 2:
        bot.reply_to(
            message,
            "❌ Использование: /update_keys [URL]"
        )
        return
    
    url = args[1]
    
    msg = bot.reply_to(message, "⏳ Загрузка ключей...")
    
    keys = load_keys_from_url(url)
    
    if keys is None:
        bot.edit_message_text(
            "❌ Не удалось загрузить ключи. Проверьте URL.",
            msg.chat.id,
            msg.message_id
        )
        return
    
    if not keys:
        bot.edit_message_text(
            "❌ В файле не найдено ключей (строк с vless://).\n"
            "Проверьте, что ссылка ведёт на файл с ключами.",
            msg.chat.id,
            msg.message_id
        )
        return
    
    save_keys_to_db(keys)
    
    bot.edit_message_text(
        f"✅ Ключи обновлены!\n\n"
        f"📊 Загружено ключей: {len(keys)}\n"
        f"🔗 Источник: {url}",
        msg.chat.id,
        msg.message_id
    )

# ========== РЕФЕРАЛЬНЫЕ КОМАНДЫ ==========
@bot.message_handler(commands=['ref_on'])
def referral_on(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ У вас нет прав.")
        return
    
    set_setting('referral_enabled', '1')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT DISTINCT referrer_id FROM referrals WHERE rewarded = 0')
    referrers = cursor.fetchall()
    
    total_rewarded = 0
    rewarded_users = {}
    
    for (referrer_id,) in referrers:
        cursor.execute("SELECT subscription_end FROM users WHERE user_id = %s", (referrer_id,))
        ref_result = cursor.fetchone()
        
        if ref_result:
            cursor.execute(
                "SELECT COUNT(*) FROM referrals WHERE referrer_id = %s AND rewarded = 0",
                (referrer_id,)
            )
            count = cursor.fetchone()[0]
            
            if count > 0:
                new_end = ref_result[0] + count * 3 * 24 * 60 * 60
                cursor.execute(
                    "UPDATE users SET subscription_end = %s WHERE user_id = %s",
                    (new_end, referrer_id)
                )
                cursor.execute(
                    "UPDATE referrals SET rewarded = 1 WHERE referrer_id = %s AND rewarded = 0",
                    (referrer_id,)
                )
                total_rewarded += count
                rewarded_users[referrer_id] = count
    
    conn.commit()
    conn.close()
    
    for referrer_id, count in rewarded_users.items():
        try:
            bot.send_message(
                referrer_id,
                f"🎉 Реферальная система включена!\n\n"
                f"За {count} приглашённых вами рефералов было начислено {count * 3} дней.\n"
                f"Спасибо, что приглашаете друзей! 🌟"
            )
        except:
            pass
    
    bot.reply_to(
        message,
        f"✅ Реферальная система ВКЛЮЧЕНА.\n"
        f"Начислено {total_rewarded * 3} дней {total_rewarded} рефералам."
    )

@bot.message_handler(commands=['ref_off'])
def referral_off(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ У вас нет прав.")
        return
    
    set_setting('referral_enabled', '0')
    bot.reply_to(message, "❌ Реферальная система ВЫКЛЮЧЕНА. Новые рефералы сохраняются, но дни не начисляются.")

@bot.message_handler(commands=['ref_status'])
def referral_status(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ У вас нет прав.")
        return
    
    status = "ВКЛЮЧЕНА ✅" if int(get_setting('referral_enabled')) == 1 else "ВЫКЛЮЧЕНА ❌"
    bot.reply_to(message, f"📊 Реферальная система: {status}")

# ========== БЛОКИРОВКА ПОЛЬЗОВАТЕЛЕЙ ==========
@bot.message_handler(commands=['block'])
def block_user(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Только создатель может блокировать пользователей.")
        return
    
    args = message.text.split()
    if len(args) != 2:
        bot.reply_to(message, "❌ Использование: /block [ID]")
        return
    
    try:
        user_id = int(args[1])
    except:
        bot.reply_to(message, "❌ ID должен быть числом.")
        return
    
    if user_id == ADMIN_ID:
        bot.reply_to(message, "❌ Нельзя заблокировать создателя.")
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
    if not cursor.fetchone():
        conn.close()
        bot.reply_to(message, f"❌ Пользователь {user_id} не найден.")
        return
    
    cursor.execute("UPDATE users SET is_blocked = 1 WHERE user_id = %s", (user_id,))
    conn.commit()
    conn.close()
    
    bot.reply_to(message, f"✅ Пользователь {user_id} заблокирован.")
    
    try:
        bot.send_message(
            user_id,
            "🚫 Вы заблокированы администратором.\n\n"
            "Для выяснения причин обратитесь в поддержку: @mel1ste"
        )
    except:
        pass

@bot.message_handler(commands=['unblock'])
def unblock_user(message):
    if message.chat.type != "private":
        return
    
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Только создатель может разблокировать пользователей.")
        return
    
    args = message.text.split()
    if len(args) != 2:
        bot.reply_to(message, "❌ Использование: /unblock [ID]")
        return
    
    try:
        user_id = int(args[1])
    except:
        bot.reply_to(message, "❌ ID должен быть числом.")
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
    if not cursor.fetchone():
        conn.close()
        bot.reply_to(message, f"❌ Пользователь {user_id} не найден.")
        return
    
    cursor.execute("UPDATE users SET is_blocked = 0 WHERE user_id = %s", (user_id,))
    conn.commit()
    conn.close()
    
    bot.reply_to(message, f"✅ Пользователь {user_id} разблокирован.")
    
    try:
        bot.send_message(
            user_id,
            "✅ Вы разблокированы! Теперь вы можете пользоваться ботом."
        )
    except:
        pass

# ========== РАССЫЛКА ==========
@bot.message_handler(commands=['broadcast'])
def broadcast_command(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ У вас нет прав.")
        return
    
    text = message.text.replace('/broadcast', '').strip()
    
    if not text and not message.reply_to_message:
        bot.reply_to(
            message,
            "❌ Использование:\n"
            "1. /broadcast [текст] — отправить текст всем\n"
            "2. Ответить на фото с подписью /broadcast — отправить фото + текст"
        )
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE is_blocked = 0")
    users = cursor.fetchall()
    conn.close()
    
    if not users:
        bot.reply_to(message, "❌ Нет активных пользователей для рассылки.")
        return
    
    success = 0
    fail = 0
    
    if message.reply_to_message and message.reply_to_message.photo:
        photo = message.reply_to_message.photo[-1].file_id
        caption = text if text else None
        
        for user in users:
            try:
                bot.send_photo(user[0], photo, caption=caption)
                success += 1
            except:
                fail += 1
    else:
        for user in users:
            try:
                bot.send_message(user[0], text)
                success += 1
            except:
                fail += 1
    
    bot.reply_to(
        message,
        f"✅ Рассылка завершена.\n\n"
        f"📤 Отправлено: {success}\n"
        f"❌ Не доставлено: {fail}"
    )

# ========== АДМИН-КОМАНДЫ ==========
@bot.message_handler(commands=['stats'])
def stats_command(message):
    if message.chat.type != "private":
        return
    
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ У вас нет прав.")
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE subscription_end > %s", (int(time.time()),))
    active_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE subscription_end < %s", (int(time.time()),))
    expired_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM referrals")
    total_refs = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_blocked = 1")
    blocked_users = cursor.fetchone()[0]
    
    conn.close()
    
    text = (
        f"📊 Статистика:\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"✅ Активных: {active_users}\n"
        f"❌ Истекших: {expired_users}\n"
        f"🚫 Заблокированных: {blocked_users}\n"
        f"🔗 Всего рефералов: {total_refs}"
    )
    bot.reply_to(message, text)

@bot.message_handler(commands=['check'])
def check_user(message):
    if message.chat.type != "private":
        return
    
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ У вас нет прав.")
        return
    
    args = message.text.split()
    if len(args) != 2:
        bot.reply_to(message, "❌ Использование: /check [ID]")
        return
    
    try:
        user_id = int(args[1])
    except:
        bot.reply_to(message, "❌ ID должен быть числом.")
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT subscription_end, is_blocked, token FROM users WHERE user_id = %s", (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        bot.reply_to(message, f"❌ Пользователь {user_id} не найден.")
        return
    
    subscription_end, is_blocked, token = result
    current_time = int(time.time())
    
    if is_blocked:
        status = "🚫 Заблокирован"
    elif subscription_end > current_time:
        days_left = (subscription_end - current_time) // (24*60*60)
        status = f"✅ Активна (осталось {days_left} дн)"
    else:
        status = "❌ Истекла"
    
    bot.reply_to(message, f"👤 Пользователь {user_id}\n📊 Статус: {status}\n🔗 Токен: {token}")

@bot.message_handler(commands=['prolong'])
def prolong_user(message):
    if message.chat.type != "private":
        return
    
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ У вас нет прав.")
        return
    
    args = message.text.split()
    if len(args) != 3:
        bot.reply_to(message, "❌ Использование: /prolong [ID] [дни]")
        return
    
    try:
        user_id = int(args[1])
        days = int(args[2])
    except:
        bot.reply_to(message, "❌ ID и дни должны быть числами.")
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT subscription_end FROM users WHERE user_id = %s", (user_id,))
    result = cursor.fetchone()
    
    if not result:
        conn.close()
        bot.reply_to(message, f"❌ Пользователь {user_id} не найден.")
        return
    
    current_end = result[0] if result[0] > int(time.time()) else int(time.time())
    new_end = current_end + days * 24 * 60 * 60
    
    cursor.execute(
        "UPDATE users SET subscription_end = %s, notified_3days = 0 WHERE user_id = %s",
        (new_end, user_id)
    )
    conn.commit()
    conn.close()
    
    bot.reply_to(message, f"✅ Пользователю {user_id} продлена подписка на {days} дней.")
    
    try:
        bot.send_message(
            user_id,
            f"✅ Ваша подписка продлена на {days} дней!\n"
            f"Новая дата окончания: {datetime.fromtimestamp(new_end).strftime('%d.%m.%Y в %H:%M')}"
        )
    except:
        pass

@bot.message_handler(commands=['remove'])
def remove_user(message):
    if message.chat.type != "private":
        return
    
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ У вас нет прав.")
        return
    
    args = message.text.split()
    if len(args) != 2:
        bot.reply_to(message, "❌ Использование: /remove [ID]")
        return
    
    try:
        user_id = int(args[1])
    except:
        bot.reply_to(message, "❌ ID должен быть числом.")
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
    if not cursor.fetchone():
        conn.close()
        bot.reply_to(message, f"❌ Пользователь {user_id} не найден.")
        return
    
    cursor.execute(
        "UPDATE users SET subscription_end = %s, notified_3days = 0 WHERE user_id = %s",
        (int(time.time()) - 1, user_id)
    )
    conn.commit()
    conn.close()
    
    bot.reply_to(message, f"✅ Подписка пользователя {user_id} удалена.")
    
    try:
        bot.send_message(
            user_id,
            "❌ Ваша подписка была отключена администратором.\n"
            "Для восстановления обратитесь в поддержку: @mel1ste"
        )
    except:
        pass

@bot.message_handler(commands=['add_admin'])
def add_admin(message):
    if message.chat.type != "private":
        return
    
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Только создатель может выдавать админ-доступ.")
        return
    
    args = message.text.split()
    if len(args) != 2:
        bot.reply_to(message, "❌ Использование: /add_admin [ID]")
        return
    
    try:
        user_id = int(args[1])
    except:
        bot.reply_to(message, "❌ ID должен быть числом.")
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
    if not cursor.fetchone():
        conn.close()
        bot.reply_to(message, f"❌ Пользователь {user_id} не найден.")
        return
    
    cursor.execute(
        "INSERT INTO admins (user_id, added_by, added_at) VALUES (%s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET added_by = EXCLUDED.added_by, added_at = EXCLUDED.added_at",
        (user_id, message.from_user.id, int(time.time()))
    )
    conn.commit()
    conn.close()
    
    bot.reply_to(message, f"✅ Пользователю {user_id} выдан админ-доступ.")
    
    try:
        bot.send_message(
            user_id,
            "👑 Вам выдан админ-доступ к боту!\n"
            "Теперь вы можете продлевать подписки: /prolong [ID] [дни]"
        )
    except:
        pass

@bot.message_handler(commands=['remove_admin'])
def remove_admin(message):
    if message.chat.type != "private":
        return
    
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Только создатель может забирать админ-доступ.")
        return
    
    args = message.text.split()
    if len(args) != 2:
        bot.reply_to(message, "❌ Использование: /remove_admin [ID]")
        return
    
    try:
        user_id = int(args[1])
    except:
        bot.reply_to(message, "❌ ID должен быть числом.")
        return
    
    if user_id == ADMIN_ID:
        bot.reply_to(message, "❌ Нельзя удалить создателя.")
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM admins WHERE user_id = %s", (user_id,))
    conn.commit()
    conn.close()
    
    bot.reply_to(message, f"✅ Админ-доступ у пользователя {user_id} отозван.")
    
    try:
        bot.send_message(user_id, "❌ Ваш админ-доступ отозван.")
    except:
        pass

# ========== КОМАНДА ADMINS_LIST ==========
@bot.message_handler(commands=['admins_list'])
def admins_list(message):
    if message.chat.type != "private":
        return
    
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Только создатель может смотреть список админов.")
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, added_at FROM admins")
    admins = cursor.fetchall()
    conn.close()
    
    if not admins:
        bot.reply_to(message, "📋 Список администраторов пуст.")
        return
    
    text = "👑 Список администраторов:\n\n"
    text += f"👤 Создатель: {ADMIN_ID}\n\n"
    
    for admin_id, added_at in admins:
        try:
            user = bot.get_chat(admin_id)
            name = user.first_name or str(admin_id)
        except:
            name = str(admin_id)
        text += f"└ {name} (ID: {admin_id})\n"
    
    bot.reply_to(message, text)

# ========== УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ (/manage) ==========
user_cache = {}
search_cache = {}

def get_user_display_name(user_id):
    try:
        user = bot.get_chat(user_id)
        return user.first_name or str(user_id)
    except:
        return str(user_id)

def build_user_list_keyboard(users, page=0, filter_type='all', search_query=None):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    
    per_page = 5
    total_pages = (len(users) + per_page - 1) // per_page if users else 1
    start = page * per_page
    end = min(start + per_page, len(users))
    
    if not users:
        keyboard.add(types.InlineKeyboardButton("📭 Нет пользователей", callback_data="noop"))
    else:
        for user_id in users[start:end]:
            display_name = get_user_display_name(user_id)
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT subscription_end, is_blocked FROM users WHERE user_id = %s", (user_id,))
            result = cursor.fetchone()
            conn.close()
            
            if result and result[0] > int(time.time()):
                status_icon = "🟢"
            else:
                status_icon = "🔴"
            
            if result and result[1] == 1:
                status_icon = "🚫"
            
            is_admin_user = is_admin(user_id)
            admin_icon = "👑 " if is_admin_user else ""
            
            keyboard.add(
                types.InlineKeyboardButton(
                    f"{status_icon} {admin_icon}{display_name}",
                    callback_data=f"user_{user_id}"
                )
            )
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton("◀️ Назад", callback_data=f"page_{page-1}_{filter_type}_{search_query or ''}"))
    if page < total_pages - 1:
        nav_buttons.append(types.InlineKeyboardButton("Вперед ▶️", callback_data=f"page_{page+1}_{filter_type}_{search_query or ''}"))
    if nav_buttons:
        keyboard.add(*nav_buttons)
    
    keyboard.row(
        types.InlineKeyboardButton("🟢 Активные", callback_data=f"filter_active_{page}"),
        types.InlineKeyboardButton("🔴 Неактивные", callback_data=f"filter_inactive_{page}")
    )
    keyboard.row(
        types.InlineKeyboardButton("👑 Админы", callback_data=f"filter_admins_{page}"),
        types.InlineKeyboardButton("📋 Все приглашавшие", callback_data=f"filter_referrers_{page}")
    )
    keyboard.row(
        types.InlineKeyboardButton("🏆 Топ рефералов", callback_data="top_refs"),
        types.InlineKeyboardButton("🔄 Обновить", callback_data="refresh_list")
    )
    keyboard.row(
        types.InlineKeyboardButton("❌ Закрыть", callback_data="close_manage")
    )
    
    return keyboard

@bot.message_handler(commands=['manage'])
def manage_users(message):
    if message.chat.type != "private":
        return
    
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ У вас нет прав.")
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE is_blocked = 0 ORDER BY user_id")
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    if not users:
        bot.reply_to(message, "📭 Нет активных пользователей в базе.")
        return
    
    user_cache[message.from_user.id] = users
    search_cache[message.from_user.id] = None
    
    keyboard = build_user_list_keyboard(users, 0, 'all')
    bot.reply_to(
        message,
        f"👥 Управление пользователями\n\nВсего: {len(users)}",
        reply_markup=keyboard
    )

# ========== ОБРАБОТЧИКИ INLINE-КНОПОК (/manage) ==========
@bot.callback_query_handler(func=lambda call: call.data.startswith('user_'))
def user_action_menu(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ У вас нет прав.", show_alert=True)
        return
    
    user_id = int(call.data.split('_')[1])
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT subscription_end, is_blocked FROM users WHERE user_id = %s", (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        bot.answer_callback_query(call.id, "❌ Пользователь не найден.", show_alert=True)
        return
    
    subscription_end, is_blocked = result
    current_time = int(time.time())
    
    if is_blocked:
        status = "🚫 Заблокирован"
    elif subscription_end > current_time:
        days_left = (subscription_end - current_time) // (24*60*60)
        status = f"🟢 Активна (осталось {days_left} дн)"
    else:
        status = "🔴 Неактивна"
    
    is_admin_user = is_admin(user_id)
    admin_text = "✅ Да" if is_admin_user else "❌ Нет"
    
    display_name = get_user_display_name(user_id)
    
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("📅 Продлить (+30 дн)", callback_data=f"prolong_{user_id}_30"),
        types.InlineKeyboardButton("🗑️ Удалить подписку", callback_data=f"remove_sub_{user_id}")
    )
    if is_blocked:
        keyboard.add(
            types.InlineKeyboardButton("🔓 Разблокировать", callback_data=f"unblock_{user_id}")
        )
    else:
        keyboard.add(
            types.InlineKeyboardButton("🔒 Заблокировать", callback_data=f"block_{user_id}")
        )
    if is_admin_user:
        keyboard.add(
            types.InlineKeyboardButton("👑 Забрать админку", callback_data=f"remove_admin_{user_id}")
        )
    else:
        keyboard.add(
            types.InlineKeyboardButton("👑 Выдать админку", callback_data=f"add_admin_{user_id}")
        )
    keyboard.row(
        types.InlineKeyboardButton("🔙 Назад к списку", callback_data="back_to_list"),
        types.InlineKeyboardButton("❌ Закрыть", callback_data="close_manage")
    )
    
    text = (
        f"👤 *{display_name}*\n"
        f"🆔 ID: `{user_id}`\n"
        f"📊 Статус: {status}\n"
        f"👑 Админ: {admin_text}"
    )
    
    bot.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id,
        parse_mode="Markdown",
        reply_markup=keyboard
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('block_'))
def inline_block_user(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Только создатель может блокировать.", show_alert=True)
        return
    
    user_id = int(call.data.split('_')[1])
    
    if user_id == ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нельзя заблокировать создателя.", show_alert=True)
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_blocked = 1 WHERE user_id = %s", (user_id,))
    conn.commit()
    conn.close()
    
    bot.answer_callback_query(call.id, "✅ Пользователь заблокирован!", show_alert=True)
    
    try:
        bot.send_message(
            user_id,
            "🚫 Вы заблокированы администратором.\n\n"
            "Для выяснения причин обратитесь в поддержку: @mel1ste"
        )
    except:
        pass
    
    user_action_menu(call)

@bot.callback_query_handler(func=lambda call: call.data.startswith('unblock_'))
def inline_unblock_user(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Только создатель может разблокировать.", show_alert=True)
        return
    
    user_id = int(call.data.split('_')[1])
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_blocked = 0 WHERE user_id = %s", (user_id,))
    conn.commit()
    conn.close()
    
    bot.answer_callback_query(call.id, "✅ Пользователь разблокирован!", show_alert=True)
    
    try:
        bot.send_message(
            user_id,
            "✅ Вы разблокированы! Теперь вы можете пользоваться ботом."
        )
    except:
        pass
    
    user_action_menu(call)

@bot.callback_query_handler(func=lambda call: call.data.startswith('prolong_'))
def inline_prolong(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ У вас нет прав.", show_alert=True)
        return
    
    _, user_id, days = call.data.split('_')
    user_id = int(user_id)
    days = int(days)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT subscription_end FROM users WHERE user_id = %s", (user_id,))
    result = cursor.fetchone()
    
    if not result:
        conn.close()
        bot.answer_callback_query(call.id, "❌ Пользователь не найден.", show_alert=True)
        return
    
    current_end = result[0] if result[0] > int(time.time()) else int(time.time())
    new_end = current_end + days * 24 * 60 * 60
    
    cursor.execute(
        "UPDATE users SET subscription_end = %s, notified_3days = 0 WHERE user_id = %s",
        (new_end, user_id)
    )
    conn.commit()
    conn.close()
    
    bot.answer_callback_query(call.id, f"✅ Подписка продлена на {days} дней!", show_alert=True)
    user_action_menu(call)

@bot.callback_query_handler(func=lambda call: call.data.startswith('remove_sub_'))
def inline_remove_sub(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ У вас нет прав.", show_alert=True)
        return
    
    user_id = int(call.data.split('_')[2])
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
    if not cursor.fetchone():
        conn.close()
        bot.answer_callback_query(call.id, "❌ Пользователь не найден.", show_alert=True)
        return
    
    cursor.execute(
        "UPDATE users SET subscription_end = %s, notified_3days = 0 WHERE user_id = %s",
        (int(time.time()) - 1, user_id)
    )
    conn.commit()
    conn.close()
    
    bot.answer_callback_query(call.id, "✅ Подписка удалена!", show_alert=True)
    
    try:
        bot.send_message(
            user_id,
            "❌ Ваша подписка была отключена администратором.\nДля восстановления обратитесь в поддержку: @mel1ste"
        )
    except:
        pass
    
    user_action_menu(call)

@bot.callback_query_handler(func=lambda call: call.data.startswith('add_admin_'))
def inline_add_admin(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Только создатель может выдавать админку.", show_alert=True)
        return
    
    user_id = int(call.data.split('_')[2])
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
    if not cursor.fetchone():
        conn.close()
        bot.answer_callback_query(call.id, "❌ Пользователь не найден.", show_alert=True)
        return
    
    cursor.execute(
        "INSERT INTO admins (user_id, added_by, added_at) VALUES (%s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET added_by = EXCLUDED.added_by, added_at = EXCLUDED.added_at",
        (user_id, call.from_user.id, int(time.time()))
    )
    conn.commit()
    conn.close()
    
    bot.answer_callback_query(call.id, "✅ Админ-доступ выдан!", show_alert=True)
    
    try:
        bot.send_message(
            user_id,
            "👑 Вам выдан админ-доступ к боту!"
        )
    except:
        pass
    
    user_action_menu(call)

@bot.callback_query_handler(func=lambda call: call.data.startswith('remove_admin_'))
def inline_remove_admin(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Только создатель может забирать админку.", show_alert=True)
        return
    
    user_id = int(call.data.split('_')[2])
    
    if user_id == ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нельзя удалить создателя.", show_alert=True)
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM admins WHERE user_id = %s", (user_id,))
    conn.commit()
    conn.close()
    
    bot.answer_callback_query(call.id, "✅ Админ-доступ отозван!", show_alert=True)
    
    try:
        bot.send_message(
            user_id,
            "❌ Ваш админ-доступ отозван."
        )
    except:
        pass
    
    user_action_menu(call)

@bot.callback_query_handler(func=lambda call: call.data == "back_to_list")
def back_to_list(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ У вас нет прав.", show_alert=True)
        return
    
    users = user_cache.get(call.from_user.id, [])
    if not users:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE is_blocked = 0 ORDER BY user_id")
        users = [row[0] for row in cursor.fetchall()]
        conn.close()
        user_cache[call.from_user.id] = users
    
    keyboard = build_user_list_keyboard(users, 0, 'all')
    bot.edit_message_text(
        f"👥 Управление пользователями\n\nВсего: {len(users)}",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "close_manage")
def close_manage(call):
    bot.delete_message(call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "refresh_list")
def refresh_list(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ У вас нет прав.", show_alert=True)
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE is_blocked = 0 ORDER BY user_id")
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    user_cache[call.from_user.id] = users
    search_cache[call.from_user.id] = None
    
    keyboard = build_user_list_keyboard(users, 0, 'all')
    bot.edit_message_text(
        f"👥 Управление пользователями\n\nВсего: {len(users)}",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard
    )
    bot.answer_callback_query(call.id, "🔄 Список обновлен!")

@bot.callback_query_handler(func=lambda call: call.data.startswith('filter_'))
def filter_users(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ У вас нет прав.", show_alert=True)
        return
    
    filter_type = call.data.split('_')[1]
    page = int(call.data.split('_')[2]) if len(call.data.split('_')) > 2 else 0
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, subscription_end, is_blocked FROM users ORDER BY user_id")
    all_users_data = cursor.fetchall()
    conn.close()
    
    current_time = int(time.time())
    filtered_users = []
    
    if filter_type == 'active':
        for user_id, end, blocked in all_users_data:
            if not blocked and end > current_time:
                filtered_users.append(user_id)
    elif filter_type == 'inactive':
        for user_id, end, blocked in all_users_data:
            if not blocked and end <= current_time:
                filtered_users.append(user_id)
    elif filter_type == 'admins':
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM admins")
        filtered_users = [row[0] for row in cursor.fetchall()]
        conn.close()
    elif filter_type == 'referrers':
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT referrer_id FROM referrals')
        filtered_users = [row[0] for row in cursor.fetchall()]
        conn.close()
    else:
        filtered_users = [row[0] for row in all_users_data if not row[2]]
    
    user_cache[call.from_user.id] = filtered_users
    
    keyboard = build_user_list_keyboard(filtered_users, page, filter_type)
    label = {
        'active': '🟢 Активные',
        'inactive': '🔴 Неактивные',
        'admins': '👑 Админы',
        'referrers': '📋 Все приглашавшие',
        'all': '📋 Все'
    }.get(filter_type, 'Все')
    
    bot.edit_message_text(
        f"👥 Управление пользователями\n\n{label}: {len(filtered_users)}",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('page_'))
def paginate_users(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ У вас нет прав.", show_alert=True)
        return
    
    parts = call.data.split('_')
    page = int(parts[1])
    filter_type = parts[2]
    search_query = parts[3] if len(parts) > 3 and parts[3] != '' else None
    
    users = user_cache.get(call.from_user.id, [])
    if not users:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE is_blocked = 0 ORDER BY user_id")
        users = [row[0] for row in cursor.fetchall()]
        conn.close()
        user_cache[call.from_user.id] = users
    
    keyboard = build_user_list_keyboard(users, page, filter_type, search_query)
    bot.edit_message_reply_markup(
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "top_refs")
def top_refs_admin(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ У вас нет прав.", show_alert=True)
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT referrer_id, COUNT(*) as count 
        FROM referrals 
        GROUP BY referrer_id 
        ORDER BY count DESC 
        LIMIT 10
    ''')
    top = cursor.fetchall()
    
    if not top:
        conn.close()
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_list"))
        bot.edit_message_text(
            "📭 Пока нет рефералов.",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboard
        )
        bot.answer_callback_query(call.id)
        return
    
    text = "🏆 *Топ рефералов (админ-панель):*\n\n"
    place = 1
    for referrer_id, count in top:
        try:
            user = bot.get_chat(referrer_id)
            name = user.first_name or str(referrer_id)
            if user.username:
                name += f" (@{user.username})"
        except:
            name = str(referrer_id)
        
        conn2 = get_db_connection()
        cursor2 = conn2.cursor()
        cursor2.execute("SELECT last_activity FROM users WHERE user_id = %s", (referrer_id,))
        reg_result = cursor2.fetchone()
        conn2.close()
        reg_date = datetime.fromtimestamp(reg_result[0]).strftime("%d.%m.%Y") if reg_result else "Неизвестно"
        
        text += f"{place}. {name} — {count} рефералов\n"
        text += f"   📅 Регистрация: {reg_date}\n\n"
        place += 1
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_list"))
    
    bot.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id,
        parse_mode="Markdown",
        reply_markup=keyboard
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "search_user")
def search_user_prompt(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ У вас нет прав.", show_alert=True)
        return
    
    bot.send_message(
        call.message.chat.id,
        "🔍 Введите username (с @) или ID пользователя для поиска:"
    )
    bot.answer_callback_query(call.id)
    search_cache[call.from_user.id] = 'waiting_for_search'

@bot.message_handler(func=lambda message: search_cache.get(message.from_user.id) == 'waiting_for_search')
def handle_search_input(message):
    if not is_admin(message.from_user.id):
        return
    
    query = message.text.strip()
    search_cache[message.from_user.id] = None
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if query.startswith('@'):
        username = query[1:]
        cursor.execute("SELECT user_id FROM users ORDER BY user_id")
        all_users = [row[0] for row in cursor.fetchall()]
        found_users = []
        for user_id in all_users:
            try:
                user = bot.get_chat(user_id)
                if user.username and user.username.lower() == username.lower():
                    found_users.append(user_id)
            except:
                pass
    else:
        try:
            user_id = int(query)
            cursor.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
            result = cursor.fetchone()
            found_users = [result[0]] if result else []
        except:
            found_users = []
    
    conn.close()
    
    if not found_users:
        bot.reply_to(message, "❌ Пользователь не найден. Попробуйте другой запрос.")
        return
    
    user_cache[message.from_user.id] = found_users
    keyboard = build_user_list_keyboard(found_users, 0, 'all', query)
    bot.reply_to(
        message,
        f"🔍 Результаты поиска: {len(found_users)}",
        reply_markup=keyboard
    )

@bot.callback_query_handler(func=lambda call: call.data == "noop")
def noop(call):
    bot.answer_callback_query(call.id)

# ========== ЭНДПОИНТ ДЛЯ ПИНГА ==========
@app.route('/ping')
def ping():
    return "ok", 200

# ========== ЭНДПОИНТ ДЛЯ ПОДПИСКИ ==========
@app.route('/sub/<token>')
def get_subscription(token):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, subscription_end, is_blocked FROM users WHERE token = %s", (token,))
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        return "Подписка не найдена", 404
    
    user_id, subscription_end, is_blocked = result
    
    if subscription_end < int(time.time()) or is_blocked == 1:
        return "Подписка истекла или пользователь заблокирован", 403
    
    keys = get_keys_from_db()
    
    if not keys:
        keys = [
            "vless://b9708941-a851-40d1-bcfd-43f189b17e8f@81.94.159.32:443?encryption=none&flow=xtls-rprx-vision&security=reality&sni=yandex.ru&fp=firefox&pbk=5L6iTGyjR5bzxyYEWEX21CGt1O8_oxWrXlVrh2MCEWM&sid=ef30f4fe17e4d890&spx=%2Fmaps%2F&type=tcp#%D0%9D%D0%BE%D0%B2%D1%8B%D0%B9+%D1%81%D0%B5%D1%80%D0%B2%D0%B5%D1%80"
        ]
    
    return KEY_TEMPLATE.format(
        expire=subscription_end,
        keys='\n'.join(keys)
    )

# ========== ЗАПУСК БОТА ==========
def run_bot():
    bot.infinity_polling(skip_pending=True)

if __name__ == '__main__':
    if not get_keys_from_db():
        default_keys = [
            "vless://b9708941-a851-40d1-bcfd-43f189b17e8f@81.94.159.32:443?encryption=none&flow=xtls-rprx-vision&security=reality&sni=yandex.ru&fp=firefox&pbk=5L6iTGyjR5bzxyYEWEX21CGt1O8_oxWrXlVrh2MCEWM&sid=ef30f4fe17e4d890&spx=%2Fmaps%2F&type=tcp#%D0%9D%D0%BE%D0%B2%D1%8B%D0%B9+%D1%81%D0%B5%D1%80%D0%B2%D0%B5%D1%80"
        ]
        save_keys_to_db(default_keys)
    
    thread = Thread(target=run_bot)
    thread.start()
    app.run(host='0.0.0.0', port=10000)
    
