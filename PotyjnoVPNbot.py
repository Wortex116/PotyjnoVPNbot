import telebot
from telebot import types
import sqlite3
import time
from datetime import datetime
import os
from flask import Flask
from threading import Thread

# ========== ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ==========
BOT_TOKEN = os.getenv('BOT_TOKEN', '8621740437:AAHXYevornlIKyNN204hrZ307slYZiYIqTE')
ADMIN_ID = int(os.getenv('ADMIN_ID', 8176196456))

# ========== НАСТРОЙКИ КАНАЛА ==========
CHANNEL_ID = -1003668283208
CHANNEL_LINK = "https://t.me/ciorsa"

# ========== ПОДДЕРЖКА ==========
SUPPORT_USERNAME = "@mel1ste"

# ========== РЕФЕРАЛЬНАЯ СИСТЕМА ==========
REFERRAL_ENABLED = False  # по умолчанию выключена

# ========== ИНИЦИАЛИЗАЦИЯ ==========
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# ========== БАЗА ДАННЫХ ==========
def init_db():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            subscription_end INTEGER,
            notified_3days INTEGER DEFAULT 0,
            last_activity INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY,
            added_by INTEGER,
            added_at INTEGER
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS referrals (
            referrer_id INTEGER,
            referred_id INTEGER,
            reward_date INTEGER,
            rewarded INTEGER DEFAULT 0,
            PRIMARY KEY (referrer_id, referred_id)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def is_admin(user_id):
    if user_id == ADMIN_ID:
        return True
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM admins WHERE user_id = ?", (user_id,))
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
    return f"https://potyjnovpnbot.onrender.com/sub/{user_id}"

# ========== КЛАВИАТУРЫ ==========
def main_menu():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn1 = types.KeyboardButton("👤 Личный кабинет")
    btn2 = types.KeyboardButton("📡 Моя подписка")
    btn3 = types.KeyboardButton("👥 Рефералы")
    btn4 = types.KeyboardButton("❓ Поддержка")
    keyboard.add(btn1, btn2)
    keyboard.add(btn3, btn4)
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
    
    if not is_subscribed(user_id):
        bot.reply_to(
            message,
            "⚠️ Подпишитесь на канал, чтобы пользоваться ботом.",
            reply_markup=subscribe_button()
        )
        return
    
    # ===== ОБРАБОТКА РЕФЕРАЛЬНОЙ ССЫЛКИ =====
    referrer_id = None
    if len(message.text.split()) > 1:
        ref_param = message.text.split()[1]
        if ref_param.startswith('ref_'):
            try:
                referrer_id = int(ref_param.split('_')[1])
            except:
                pass
    
    if referrer_id and referrer_id != user_id:
        if is_subscribed(referrer_id):
            conn = sqlite3.connect('users.db')
            cursor = conn.cursor()
            cursor.execute("SELECT subscription_end FROM users WHERE user_id = ?", (referrer_id,))
            ref_result = cursor.fetchone()
            
            if ref_result:
                cursor.execute(
                    "SELECT * FROM referrals WHERE referrer_id = ? AND referred_id = ?",
                    (referrer_id, user_id)
                )
                already_ref = cursor.fetchone()
                
                if not already_ref:
                    cursor.execute(
                        "INSERT INTO referrals (referrer_id, referred_id, reward_date, rewarded) VALUES (?, ?, ?, ?)",
                        (referrer_id, user_id, int(time.time()), 0)
                    )
                    conn.commit()
                    
                    if REFERRAL_ENABLED:
                        new_end = ref_result[0] + 3 * 24 * 60 * 60
                        cursor.execute(
                            "UPDATE users SET subscription_end = ? WHERE user_id = ?",
                            (new_end, referrer_id)
                        )
                        cursor.execute(
                            "UPDATE referrals SET rewarded = 1 WHERE referrer_id = ? AND referred_id = ?",
                            (referrer_id, user_id)
                        )
                        conn.commit()
                        
                        try:
                            bot.send_message(
                                referrer_id,
                                f"🎉 По вашей ссылке зарегистрировался новый пользователь!\nВам начислено +3 дня подписки."
                            )
                        except:
                            pass
            conn.close()
    
    # ===== ОСНОВНАЯ ЛОГИКА =====
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, last_activity FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    
    current_time = int(time.time())
    is_new_user = False
    
    if not user:
        cursor.execute(
            "INSERT INTO users (user_id, subscription_end, last_activity) VALUES (?, ?, ?)",
            (user_id, current_time + 7*24*60*60, current_time)
        )
        conn.commit()
        is_new_user = True
        bot.reply_to(message, "🎉 Добро пожаловать! Вам выдана подписка на 7 дней.")
    else:
        last_activity = user[1] if user[1] else 0
        days_since_last = (current_time - last_activity) // (24*60*60)
        
        if days_since_last >= 3:
            bot.reply_to(message, "👋 С возвращением!")
        else:
            bot.reply_to(message, "👋 Добро пожаловать!")
        
        # Обновляем активность
        cursor.execute(
            "UPDATE users SET last_activity = ? WHERE user_id = ?",
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
    
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT subscription_end FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        bot.reply_to(message, "❌ Вы не зарегистрированы. Используйте /start")
        return
    
    subscription_end = result[0]
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
    
    if not is_subscribed(user_id):
        bot.reply_to(
            message,
            "⚠️ Подпишитесь на канал, чтобы получить доступ.",
            reply_markup=subscribe_button()
        )
        return
    
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT subscription_end FROM users WHERE user_id = ?", (user_id,))
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
    
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if not cursor.fetchone():
        conn.close()
        bot.reply_to(message, "❌ Вы не зарегистрированы. Используйте /start")
        return
    
    cursor.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user_id,))
    count = cursor.fetchone()[0]
    conn.close()
    
    bot_username = bot.get_me().username
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    
    text = (
        f"👥 *Ваши рефералы:* {count}\n\n"
        f"🔗 *Ваша реферальная ссылка:*\n"
        f"`{ref_link}`\n\n"
        f"📌 *Как это работает:*\n"
        f"• Приглашенные друзья засчитываются вам на баланс\n"
        f"• За каждого друга вы получаете бонус\n"
        f"• Делитесь ссылкой и приглашайте больше людей!\n\n"
        f"💬 *Вопросы?* Пишите в поддержку: @mel1ste"
    )
    bot.reply_to(message, text, parse_mode="Markdown")

# ========== КНОПКА "ПОДДЕРЖКА" ==========
@bot.message_handler(func=lambda message: message.text == "❓ Поддержка")
def support_command(message):
    if message.chat.type != "private":
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
    
    if is_subscribed(user_id):
        bot.answer_callback_query(call.id, "✅ Подписка подтверждена!")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
        
        if not user:
            cursor.execute(
                "INSERT INTO users (user_id, subscription_end, last_activity) VALUES (?, ?, ?)",
                (user_id, int(time.time()) + 7*24*60*60, int(time.time()))
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

# ========== РЕФЕРАЛЬНЫЕ КОМАНДЫ ДЛЯ АДМИНА ==========
@bot.message_handler(commands=['ref_on'])
def referral_on(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ У вас нет прав.")
        return
    
    global REFERRAL_ENABLED
    REFERRAL_ENABLED = True
    
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT DISTINCT referrer_id FROM referrals WHERE rewarded = 0
    ''')
    referrers = cursor.fetchall()
    
    total_rewarded = 0
    
    for (referrer_id,) in referrers:
        cursor.execute("SELECT subscription_end FROM users WHERE user_id = ?", (referrer_id,))
        ref_result = cursor.fetchone()
        
        if ref_result:
            cursor.execute(
                "SELECT COUNT(*) FROM referrals WHERE referrer_id = ? AND rewarded = 0",
                (referrer_id,)
            )
            count = cursor.fetchone()[0]
            
            if count > 0:
                new_end = ref_result[0] + count * 3 * 24 * 60 * 60
                cursor.execute(
                    "UPDATE users SET subscription_end = ? WHERE user_id = ?",
                    (new_end, referrer_id)
                )
                cursor.execute(
                    "UPDATE referrals SET rewarded = 1 WHERE referrer_id = ? AND rewarded = 0",
                    (referrer_id,)
                )
                total_rewarded += count
                
                try:
                    bot.send_message(
                        referrer_id,
                        f"🎉 Реферальная система включена!\nВам начислено +{count * 3} дней за {count} приглашённых друзей."
                    )
                except:
                    pass
    
    conn.commit()
    conn.close()
    
    bot.reply_to(
        message,
        f"✅ Реферальная система ВКЛЮЧЕНА.\nНачислено дней {total_rewarded * 3} рефералам."
    )

@bot.message_handler(commands=['ref_off'])
def referral_off(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ У вас нет прав.")
        return
    
    global REFERRAL_ENABLED
    REFERRAL_ENABLED = False
    bot.reply_to(message, "❌ Реферальная система ВЫКЛЮЧЕНА. Новые рефералы сохраняются, но дни не начисляются.")

@bot.message_handler(commands=['ref_status'])
def referral_status(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ У вас нет прав.")
        return
    
    status = "ВКЛЮЧЕНА ✅" if REFERRAL_ENABLED else "ВЫКЛЮЧЕНА ❌"
    bot.reply_to(message, f"📊 Реферальная система: {status}")

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
    
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    conn.close()
    
    if not users:
        bot.reply_to(message, "❌ Нет пользователей для рассылки.")
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
    
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE subscription_end > ?", (int(time.time()),))
    active_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE subscription_end < ?", (int(time.time()),))
    expired_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM referrals")
    total_refs = cursor.fetchone()[0]
    
    conn.close()
    
    text = (
        f"📊 Статистика:\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"✅ Активных: {active_users}\n"
        f"❌ Истекших: {expired_users}\n"
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
    
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT subscription_end FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        bot.reply_to(message, f"❌ Пользователь {user_id} не найден.")
        return
    
    subscription_end = result[0]
    current_time = int(time.time())
    
    if subscription_end > current_time:
        days_left = (subscription_end - current_time) // (24*60*60)
        status = f"✅ Активна (осталось {days_left} дн)"
    else:
        status = "❌ Истекла"
    
    bot.reply_to(message, f"👤 Пользователь {user_id}\n📊 Статус: {status}")

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
    
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT subscription_end FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    
    if not result:
        conn.close()
        bot.reply_to(message, f"❌ Пользователь {user_id} не найден.")
        return
    
    current_end = result[0] if result[0] > int(time.time()) else int(time.time())
    new_end = current_end + days * 24 * 60 * 60
    
    cursor.execute(
        "UPDATE users SET subscription_end = ?, notified_3days = 0 WHERE user_id = ?",
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
    
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if not cursor.fetchone():
        conn.close()
        bot.reply_to(message, f"❌ Пользователь {user_id} не найден.")
        return
    
    cursor.execute(
        "UPDATE users SET subscription_end = ?, notified_3days = 0 WHERE user_id = ?",
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
    
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if not cursor.fetchone():
        conn.close()
        bot.reply_to(message, f"❌ Пользователь {user_id} не найден.")
        return
    
    cursor.execute(
        "INSERT OR REPLACE INTO admins (user_id, added_by, added_at) VALUES (?, ?, ?)",
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
    
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    
    bot.reply_to(message, f"✅ Админ-доступ у пользователя {user_id} отозван.")
    
    try:
        bot.send_message(user_id, "❌ Ваш админ-доступ отозван.")
    except:
        pass

@bot.message_handler(commands=['admins_list'])
def admins_list(message):
    if message.chat.type != "private":
        return
    
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Только создатель может смотреть список админов.")
        return
    
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, added_at FROM admins")
    admins = cursor.fetchall()
    conn.close()
    
    if not admins:
        bot.reply_to(message, "📋 Список администраторов пуст.")
        return
    
    text = "👑 Список администраторов:\n\n"
    text += f"👤 Создатель: {ADMIN_ID}\n"
    
    for admin_id, added_at in admins:
        try:
            user = bot.get_chat(admin_id)
            name = user.first_name or str(admin_id)
        except:
            name = str(admin_id)
        text += f"└ {name} (ID: {admin_id})\n"
    
    bot.reply_to(message, text)

# ========== КОМАНДА ADMINS_LIST ==========
@bot.message_handler(commands=['admins_list'])
def admins_list(message):
    if message.chat.type != "private":
        return
    
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Только создатель может смотреть список админов.")
        return
    
    conn = sqlite3.connect('users.db')
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
            conn = sqlite3.connect('users.db')
            cursor = conn.cursor()
            cursor.execute("SELECT subscription_end FROM users WHERE user_id = ?", (user_id,))
            result = cursor.fetchone()
            conn.close()
            
            if result and result[0] > int(time.time()):
                status_icon = "🟢"
            else:
                status_icon = "🔴"
            
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
        types.InlineKeyboardButton("📋 Все", callback_data=f"filter_all_{page}")
    )
    keyboard.row(
        types.InlineKeyboardButton("🔍 Поиск", callback_data="search_user"),
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
    
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users ORDER BY user_id")
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    if not users:
        bot.reply_to(message, "📭 Нет пользователей в базе.")
        return
    
    user_cache[message.from_user.id] = users
    search_cache[message.from_user.id] = None
    
    keyboard = build_user_list_keyboard(users, 0, 'all')
    bot.reply_to(
        message,
        f"👥 Управление пользователями\n\nВсего: {len(users)}",
        reply_markup=keyboard
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('user_'))
def user_action_menu(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ У вас нет прав.", show_alert=True)
        return
    
    user_id = int(call.data.split('_')[1])
    
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT subscription_end FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        bot.answer_callback_query(call.id, "❌ Пользователь не найден.", show_alert=True)
        return
    
    subscription_end = result[0]
    current_time = int(time.time())
    
    if subscription_end > current_time:
        status = "🟢 Активна"
        days_left = (subscription_end - current_time) // (24*60*60)
        status_text = f"{status} (осталось {days_left} дн)"
    else:
        status = "🔴 Неактивна"
        status_text = status
    
    is_admin_user = is_admin(user_id)
    admin_text = "✅ Да" if is_admin_user else "❌ Нет"
    
    display_name = get_user_display_name(user_id)
    
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("📅 Продлить (+30 дн)", callback_data=f"prolong_{user_id}_30"),
        types.InlineKeyboardButton("🗑️ Удалить подписку", callback_data=f"remove_sub_{user_id}")
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
        f"📊 Статус: {status_text}\n"
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

@bot.callback_query_handler(func=lambda call: call.data.startswith('prolong_'))
def inline_prolong(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ У вас нет прав.", show_alert=True)
        return
    
    _, user_id, days = call.data.split('_')
    user_id = int(user_id)
    days = int(days)
    
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT subscription_end FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    
    if not result:
        conn.close()
        bot.answer_callback_query(call.id, "❌ Пользователь не найден.", show_alert=True)
        return
    
    current_end = result[0] if result[0] > int(time.time()) else int(time.time())
    new_end = current_end + days * 24 * 60 * 60
    
    cursor.execute(
        "UPDATE users SET subscription_end = ?, notified_3days = 0 WHERE user_id = ?",
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
    
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if not cursor.fetchone():
        conn.close()
        bot.answer_callback_query(call.id, "❌ Пользователь не найден.", show_alert=True)
        return
    
    cursor.execute(
        "UPDATE users SET subscription_end = ?, notified_3days = 0 WHERE user_id = ?",
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
    
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if not cursor.fetchone():
        conn.close()
        bot.answer_callback_query(call.id, "❌ Пользователь не найден.", show_alert=True)
        return
    
    cursor.execute(
        "INSERT OR REPLACE INTO admins (user_id, added_by, added_at) VALUES (?, ?, ?)",
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
    
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
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
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users ORDER BY user_id")
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
    
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users ORDER BY user_id")
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
    
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users ORDER BY user_id")
    all_users = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    current_time = int(time.time())
    filtered_users = []
    
    if filter_type == 'active':
        for user_id in all_users:
            conn = sqlite3.connect('users.db')
            cursor = conn.cursor()
            cursor.execute("SELECT subscription_end FROM users WHERE user_id = ?", (user_id,))
            result = cursor.fetchone()
            conn.close()
            if result and result[0] > current_time:
                filtered_users.append(user_id)
    elif filter_type == 'inactive':
        for user_id in all_users:
            conn = sqlite3.connect('users.db')
            cursor = conn.cursor()
            cursor.execute("SELECT subscription_end FROM users WHERE user_id = ?", (user_id,))
            result = cursor.fetchone()
            conn.close()
            if not result or result[0] <= current_time:
                filtered_users.append(user_id)
    elif filter_type == 'admins':
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM admins")
        filtered_users = [row[0] for row in cursor.fetchall()]
        conn.close()
    else:
        filtered_users = all_users
    
    user_cache[call.from_user.id] = filtered_users
    
    keyboard = build_user_list_keyboard(filtered_users, page, filter_type)
    label = {
        'active': '🟢 Активные',
        'inactive': '🔴 Неактивные',
        'admins': '👑 Админы',
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
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users ORDER BY user_id")
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
    
    conn = sqlite3.connect('users.db')
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
            cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
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
@app.route('/sub/<int:user_id>')
def get_subscription(user_id):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT subscription_end FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if not result or result[0] < int(time.time()):
        return "Подписка истекла или не найдена", 403
    
    return f"""#profile-title: 🌐 Потужно VPN Free
#profile-update-interval: 1
#support-url: https://t.me/mel1ste
#announce: 📡 Сервера LTE использовать только при белых списках. Без торрентов. 🕐 Поддержка с 10 до 22, ответят в ближайшее время.
#channel: 📢 https://t.me/ciorsa
#subscription-userinfo: upload=0; download=0; total=10995116277760000; expire={result[0]}
vless://b9708941-a851-40d1-bcfd-43f189b17e8f@81.94.159.32:443?encryption=none&flow=xtls-rprx-vision&security=reality&sni=yandex.ru&fp=firefox&pbk=5L6iTGyjR5bzxyYEWEX21CGt1O8_oxWrXlVrh2MCEWM&sid=ef30f4fe17e4d890&spx=%2Fmaps%2F&type=tcp#%D0%9D%D0%BE%D0%B2%D1%8B%D0%B9+%D1%81%D0%B5%D1%80%D0%B2%D0%B5%D1%80
"""

# ========== ЗАПУСК БОТА ==========
def run_bot():
    bot.infinity_polling()

if __name__ == '__main__':
    thread = Thread(target=run_bot)
    thread.start()
    app.run(host='0.0.0.0', port=10000)
    
