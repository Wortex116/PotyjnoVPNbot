import os
import sys
import re
import time
import socket
import string
import random
import threading
import traceback
import base64
import urllib.parse
import io
import json
import warnings
import urllib3
from datetime import datetime, timedelta
from threading import Thread, Lock, Event
from waitress import serve
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import wraps
from collections import defaultdict

import telebot
from telebot import types
import psycopg2
from psycopg2 import pool
import requests
from bs4 import BeautifulSoup
from flask import Flask, request

# Отключаем предупреждения SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

try:
    import socks
    SOCKS_AVAILABLE = True
except ImportError:
    SOCKS_AVAILABLE = False

# ==================== MENU BUTTONS ====================
MENU_BUTTONS = {
    "👤 Личный кабинет", "📡 Моя подписка",
    "👥 Рефералы", "🏆 Топ рефералов",
    "ℹ️ Стаж бота", "🔓 Расшифровать подписку",
    "❓ Поддержка"
}

# ==================== KEEP ALIVE ====================

def keep_alive_ping():
    url = os.getenv('RENDER_EXTERNAL_URL', '')
    if not url:
        url = os.getenv('PUBLIC_URL', '')
    if not url:
        url = 'https://potyjnovpnbot.onrender.com'
    url = url.rstrip('/')
    print(f"[keep_alive] Запущен пинг-механизм для {url}")
    ping_count = 0
    while True:
        try:
            response = requests.get(f"{url}/ping", timeout=10)
            ping_count += 1
            print(f"[keep_alive] Пинг #{ping_count} в {datetime.now().strftime('%H:%M:%S')}: {response.status_code}")
            requests.get(f"{url}/health", timeout=10)
        except:
            pass
        time.sleep(240)

def auto_restart_monitor():
    max_idle_time = 600
    print(f"[auto_restart] Запущен монитор перезапуска")
    while True:
        try:
            current_time = time.time()
            with _last_activity_lock:
                idle_time = current_time - last_activity_time
            if idle_time > max_idle_time:
                print(f"[auto_restart] Длительное бездействие, выполняем мягкий перезапуск...")
                try:
                    url = os.getenv('RENDER_EXTERNAL_URL', 'https://potyjnovpnbot.onrender.com')
                    for _ in range(3):
                        requests.get(f"{url}/ping", timeout=5)
                        time.sleep(1)
                except:
                    pass
            time.sleep(30)
        except:
            time.sleep(60)

_last_activity_lock = Lock()
last_activity_time = time.time()

def update_activity():
    global last_activity_time
    with _last_activity_lock:
        last_activity_time = time.time()

# ==================== CONFIG ====================
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', '8176196456'))
DATABASE_URL = os.getenv('DATABASE_URL')
CHANNEL_ID = -1003668283208
CHANNEL_LINK = 'https://t.me/ciorsa'
SUPPORT = '@mel1ste'
AUTO_POST_CHANNEL = -1003668283208
AUTO_POST_TOPIC_ID = 461
AUTO_POST_INTERVAL = 600
PROXY_LOADING_TIMEOUT = 600

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)

# ==================== BASE URL ====================
def get_bot_base_url():
    base_url = os.getenv('RENDER_EXTERNAL_URL', '')
    if not base_url:
        base_url = os.getenv('PUBLIC_URL', 'https://potyjnovpnbot.onrender.com')
    base_url = base_url.rstrip('/')
    if not base_url.startswith(('http://', 'https://')):
        base_url = 'https://' + base_url
    return base_url

BOT_BASE_URL = get_bot_base_url()

# ==================== ПУЛ СОЕДИНЕНИЙ ====================
db_pool = None

def init_db_pool():
    global db_pool
    try:
        db_pool = pool.SimpleConnectionPool(1, 20, DATABASE_URL)
        print("[db_pool] ✅ Пул соединений инициализирован (min=1, max=20)")
    except Exception as e:
        print(f"[db_pool] ❌ Ошибка инициализации пула: {e}")
        db_pool = None

def get_db_connection():
    if db_pool:
        return db_pool.getconn()
    return psycopg2.connect(DATABASE_URL)

def return_db_connection(conn):
    if db_pool and conn:
        db_pool.putconn(conn)
    elif conn:
        conn.close()

# Активные словари
search_cache = {}
exchange_cache = {}
decrypt_results = {}
announce_data = {}
manage_cache = {}
captcha_sessions = {}
autopost_loading = {}
keys_loading = {}
proxy_url_loading = {}
autopost_active = {}
autopost_history = {}

# ==================== ОЧИСТКА СЕССИЙ ====================
SESSION_TIMEOUT = 3600

def cleanup_expired_sessions():
    current_time = int(time.time())
    
    # Очистка captcha_sessions
    to_remove = []
    for user_id, session in captcha_sessions.items():
        if current_time - session.get('timestamp', 0) > SESSION_TIMEOUT:
            to_remove.append(user_id)
    for user_id in to_remove:
        del captcha_sessions[user_id]
    
    # Очистка search_cache
    to_remove = []
    for user_id, cache in search_cache.items():
        if current_time - cache.get('timestamp', 0) > SESSION_TIMEOUT:
            to_remove.append(user_id)
    for user_id in to_remove:
        del search_cache[user_id]
    
    # Очистка exchange_cache
    to_remove = []
    for user_id, cache in exchange_cache.items():
        if current_time - cache.get('timestamp', 0) > SESSION_TIMEOUT:
            to_remove.append(user_id)
    for user_id in to_remove:
        del exchange_cache[user_id]
    
    # Очистка decrypt_results
    to_remove = []
    for user_id, session in decrypt_results.items():
        if current_time - session.get('timestamp', 0) > SESSION_TIMEOUT:
            to_remove.append(user_id)
    for user_id in to_remove:
        del decrypt_results[user_id]
    
    # Очистка announce_data
    to_remove = []
    for user_id, data in announce_data.items():
        if current_time - data.get('timestamp', 0) > SESSION_TIMEOUT:
            to_remove.append(user_id)
    for user_id in to_remove:
        del announce_data[user_id]
    
    # Очистка keys_loading
    to_remove = []
    for user_id, data in keys_loading.items():
        if current_time - data.get('timestamp', 0) > SESSION_TIMEOUT:
            to_remove.append(user_id)
    for user_id in to_remove:
        del keys_loading[user_id]
    
    # Очистка proxy_url_loading
    to_remove = []
    for user_id, data in proxy_url_loading.items():
        if current_time - data.get('timestamp', 0) > SESSION_TIMEOUT:
            to_remove.append(user_id)
    for user_id in to_remove:
        del proxy_url_loading[user_id]
    
    # Очистка autopost_loading
    to_remove = []
    for user_id, data in autopost_loading.items():
        if current_time - data.get('timestamp', 0) > SESSION_TIMEOUT:
            to_remove.append(user_id)
    for user_id in to_remove:
        del autopost_loading[user_id]
    
    # Очистка _user_blocked_cache
    with _user_blocked_cache_lock:
        to_remove = [
            uid for uid, data in _user_blocked_cache.items()
            if current_time - data.get('timestamp', 0) > USER_BLOCKED_CACHE_TTL
        ]
        for uid in to_remove:
            del _user_blocked_cache[uid]

def cleanup_sessions_scheduler():
    print("[cleanup] Запущен планировщик очистки сессий")
    while True:
        try:
            cleanup_expired_sessions()
            _notify_expiring_subscriptions()
            time.sleep(300)
        except Exception as e:
            print(f"[cleanup] Ошибка: {e}")
            time.sleep(60)

def _notify_expiring_subscriptions():
    current_time = int(time.time())
    threshold = current_time + 3 * 24 * 60 * 60
    conn = get_db_connection()
    cur = None
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT user_id, subscription_end FROM users
            WHERE is_blocked = 0
              AND notified_3days = 0
              AND subscription_end > %s
              AND subscription_end <= %s
        """, (current_time, threshold))
        rows = cur.fetchall()
        for user_id, sub_end in rows:
            days_left = (sub_end - current_time) // (24 * 60 * 60)
            try:
                bot.send_message(
                    user_id,
                    f"⚠️ *Подписка заканчивается через {days_left} дн.*\n\n"
                    f"Для продления обратитесь в поддержку: {SUPPORT}",
                    parse_mode="Markdown"
                )
                cur.execute(
                    "UPDATE users SET notified_3days = 1 WHERE user_id = %s",
                    (user_id,)
                )
                conn.commit()
            except Exception as e:
                print(f"[notify] Ошибка отправки {user_id}: {e}")
                conn.rollback()
    except Exception as e:
        print(f"[notify] Ошибка: {e}")
        conn.rollback()
    finally:
        if cur:
            cur.close()
        return_db_connection(conn)

KEY_TEMPLATE = """\
#profile-title: 🌐 Потужно VPN Free
#profile-update-interval: 1
#support-url: https://t.me/mel1ste
#announce: 📡 Сервера LTE использовать только при белых списках. Без торрентов. 🕐 Поддержка с 10 до 22, ответят в ближайшее время.
#channel: 📢 https://t.me/ciorsa
#subscription-userinfo: upload=0; download=0; total=10995116277760000; expire={expire}
{keys}"""

DEFAULT_KEYS = [
    'vless://00000000-0000-0000-0000-000000000001@1.1.1.1:443?type=tcp&security=tls#Demo-Key-1',
]

VPN_KEY_PATTERN = r'(?:vless|vmess|trojan|ss|ssr|hysteria2?|hy2|tuic|naive\+https?|wg|wireguard|juicity|brook|shadowtls|anytls|snell|socks5?|naive|reality)://[^\s\r\n<>"\'`]+'

APP_SCHEMES = (
    r'incy|happ|v2ray|v2rayng|v2box|clash|sing-box|quantumult|surge|loon|'
    r'shadowrocket|stash|nekoray|nekobox|hiddify|streisand|karing|mihomo|flclash'
)

# ==================== СИСТЕМА РАНГОВ ====================

RANKS = [
    {'name': '🥉 Новичок',  'min': 0,     'max': 999,   'cost': 500},
    {'name': '🥈 Участник', 'min': 1000,  'max': 4999,  'cost': 450},
    {'name': '🥇 Активист', 'min': 5000,  'max': 9999,  'cost': 400},
    {'name': '💎 Ветеран',  'min': 10000, 'max': 24999, 'cost': 350},
    {'name': '👑 Легенда',  'min': 25000, 'max': None,  'cost': 250},
]

def get_rank(points):
    for rank in RANKS:
        if rank['max'] is None or points <= rank['max']:
            return rank
    return RANKS[-1]

def get_days_available(points):
    rank = get_rank(points)
    return points // rank['cost']

def get_exchange_cost(points, days):
    rank = get_rank(points)
    return days * rank['cost']

# ==================== СИСТЕМА ПРАВ АДМИНОВ ====================

PERMISSIONS = {
    'check_user': 'Проверка пользователя (/check)',
    'user_info': 'Информация о пользователе (/user)',
    'add_days': 'Выдача дней (/add_days)',
    'remove_days': 'Забирание дней (/remove_days)',
    'block_user': 'Блокировка (/block)',
    'unblock_user': 'Разблокировка (/unblock)',
    'announce': 'Рассылка',
    'manage_keys': 'Управление ключами',
    'autopost': 'Автопостинг',
    'manage_admins': 'Управление админами',
    'manage_users': 'Управление пользователями',
    'admin_stats': 'Статистика бота',
    'admin_panel': 'Доступ к админ-панели',
    'points_system': 'Система баллов',
    'view_logs': 'Просмотр логов',
}

ROLE_PRESETS = {
    'owner': {
        'name': '👑 Владелец',
        'permissions': {p: True for p in PERMISSIONS}
    },
    'senior': {
        'name': '⭐ Старший админ',
        'permissions': {
            'check_user': True, 'user_info': True, 'add_days': True, 'remove_days': True,
            'block_user': True, 'unblock_user': True, 'announce': True, 'manage_keys': True,
            'autopost': True, 'manage_admins': False, 'manage_users': True, 'admin_stats': True,
            'admin_panel': True, 'points_system': True, 'view_logs': True,
        }
    },
    'junior': {
        'name': '🔹 Младший админ',
        'permissions': {
            'check_user': True, 'user_info': True, 'add_days': True, 'remove_days': True,
            'block_user': True, 'unblock_user': True, 'announce': False, 'manage_keys': False,
            'autopost': False, 'manage_admins': False, 'manage_users': False, 'admin_stats': False,
            'admin_panel': True, 'points_system': False, 'view_logs': False,
        }
    },
    'support': {
        'name': '🟢 Поддержка',
        'permissions': {
            'check_user': True, 'user_info': True, 'add_days': False, 'remove_days': False,
            'block_user': False, 'unblock_user': False, 'announce': False, 'manage_keys': False,
            'autopost': False, 'manage_admins': False, 'manage_users': False, 'admin_stats': False,
            'admin_panel': False, 'points_system': False, 'view_logs': False,
        }
    }
}

# ==================== ЛОГИРОВАНИЕ АДМИНОВ ====================

def log_admin_action(admin_id, action, target_id=None, details=None, target_name=None, ip_address=None):
    """Запись действия админа в лог"""
    try:
        admin_name = get_user_display_name(admin_id)
        if target_id:
            target_name = target_name or get_user_display_name(target_id)
        
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO admin_logs 
                (admin_id, admin_name, action, target_id, target_name, details, ip_address, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                admin_id,
                admin_name,
                action,
                target_id,
                target_name,
                details,
                ip_address,
                int(time.time())
            ))
            conn.commit()
        finally:
            cur.close()
            return_db_connection(conn)
    except Exception as e:
        print(f"[log_admin_action] Ошибка: {e}")

# ==================== КЭШ ИМЁН ПОЛЬЗОВАТЕЛЕЙ ====================
_user_name_cache = {}
_user_name_cache_lock = Lock()
USER_NAME_CACHE_TTL = 3600

def get_user_display_name_cached(user_id):
    """Получение имени пользователя с кэшированием"""
    current_time = int(time.time())
    
    with _user_name_cache_lock:
        cached = _user_name_cache.get(user_id, {})
        if cached.get('timestamp', 0) > current_time - USER_NAME_CACHE_TTL:
            return cached.get('name', str(user_id))
    
    try:
        chat = bot.get_chat(user_id)
        if chat.username:
            name = f"@{chat.username}"
        else:
            name = chat.first_name or ''
            if chat.last_name:
                name += ' ' + chat.last_name
            name = name.strip() or str(user_id)
    except:
        name = str(user_id)
    
    with _user_name_cache_lock:
        _user_name_cache[user_id] = {
            'name': name,
            'timestamp': current_time
        }
    
    return name

# ==================== DATABASE ====================

def init_auto_update():
    if not get_setting('auto_update_enabled', ''):
        set_setting('auto_update_enabled', 'false')
        set_setting('auto_update_interval', '3')
        set_setting('auto_update_last', '0')
        set_setting('auto_update_notify', 'true')
        print("[init] ✅ Настройки автообновления инициализированы")

def init_points_system():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS points INTEGER DEFAULT 0")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_frozen INTEGER DEFAULT 0")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS frozen_days_left INTEGER DEFAULT 0")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS frozen_at BIGINT DEFAULT 0")
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS points_chats (
                chat_id BIGINT PRIMARY KEY,
                chat_name TEXT,
                enabled BOOLEAN DEFAULT TRUE,
                points_per_message INTEGER DEFAULT 1,
                added_by BIGINT,
                added_at BIGINT
            )
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_activity (
                user_id BIGINT,
                chat_id BIGINT,
                messages_count BIGINT DEFAULT 0,
                last_message BIGINT DEFAULT 0,
                daily_bonus_claimed BIGINT DEFAULT 0,
                PRIMARY KEY (user_id, chat_id)
            )
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages_log (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                chat_id BIGINT,
                message_text TEXT,
                message_id BIGINT,
                created_at BIGINT
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_log_user_id ON chat_messages_log(user_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_log_chat_id ON chat_messages_log(chat_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_log_created_at ON chat_messages_log(created_at DESC)")
        
        conn.commit()
        print("[init] ✅ Система баллов инициализирована")
    except Exception as e:
        print(f"[init] Ошибка инициализации системы баллов: {e}")
    finally:
        cur.close()
        return_db_connection(conn)

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                subscription_end BIGINT,
                notified_3days INTEGER DEFAULT 0,
                last_activity BIGINT DEFAULT 0,
                is_blocked INTEGER DEFAULT 0,
                token TEXT UNIQUE
            )
        """)
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_users_subscription_end ON users(subscription_end)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_users_notified_3days ON users(notified_3days)")
        conn.commit()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id BIGINT PRIMARY KEY
            )
        """)
        conn.commit()
        
        cur.execute("ALTER TABLE admins ADD COLUMN IF NOT EXISTS role TEXT DEFAULT 'junior'")
        cur.execute("ALTER TABLE admins ADD COLUMN IF NOT EXISTS permissions TEXT")
        cur.execute("ALTER TABLE admins ADD COLUMN IF NOT EXISTS added_by BIGINT")
        cur.execute("ALTER TABLE admins ADD COLUMN IF NOT EXISTS added_at BIGINT")
        conn.commit()
        
        try:
            cur.execute("""
                INSERT INTO admins (user_id, role, permissions, added_by, added_at) 
                VALUES (%s, %s, %s, %s, %s) 
                ON CONFLICT (user_id) DO UPDATE SET role = %s, permissions = %s
            """, (ADMIN_ID, 'owner', json.dumps({p: True for p in PERMISSIONS}), ADMIN_ID, int(time.time()), 'owner', json.dumps({p: True for p in PERMISSIONS})))
            conn.commit()
            print(f"[init] ✅ Создатель {ADMIN_ID} добавлен с ролью Владелец")
        except Exception as e:
            print(f"[init] Ошибка добавления создателя: {e}")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id SERIAL PRIMARY KEY,
                referrer_id BIGINT,
                referred_id BIGINT,
                reward_date BIGINT,
                rewarded INTEGER DEFAULT 0,
                referrer_subscribed INTEGER DEFAULT 0,
                referred_subscribed INTEGER DEFAULT 0,
                UNIQUE(referrer_id, referred_id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        
        # Таблицы для модерации
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_settings (
                chat_id BIGINT PRIMARY KEY,
                welcome_text TEXT,
                welcome_enabled BOOLEAN DEFAULT TRUE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_warns (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                chat_id BIGINT,
                reason TEXT,
                warned_by BIGINT,
                warned_at BIGINT
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_chat_warns_user_chat ON chat_warns(user_id, chat_id)")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_mutes (
                user_id BIGINT,
                chat_id BIGINT,
                until BIGINT,
                reason TEXT,
                PRIMARY KEY (user_id, chat_id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_admins (
                user_id BIGINT,
                chat_id BIGINT,
                role TEXT DEFAULT 'admin',
                added_by BIGINT,
                added_at BIGINT,
                PRIMARY KEY (user_id, chat_id)
            )
        """)
        
        # Таблица для логов админов
        cur.execute("""
            CREATE TABLE IF NOT EXISTS admin_logs (
                id SERIAL PRIMARY KEY,
                admin_id BIGINT NOT NULL,
                admin_name TEXT,
                action TEXT NOT NULL,
                target_id BIGINT,
                target_name TEXT,
                details TEXT,
                ip_address TEXT,
                created_at BIGINT NOT NULL
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_admin_logs_admin_id ON admin_logs(admin_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_admin_logs_created_at ON admin_logs(created_at DESC)")
        
        conn.commit()
    finally:
        cur.close()
        return_db_connection(conn)
    init_autopost_tables()
    init_points_system()
    init_auto_update()

def get_setting(key, default='0'):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT value FROM settings WHERE key = %s", (key,))
        result = cur.fetchone()
        return result[0] if result else default
    finally:
        cur.close()
        return_db_connection(conn)

def set_setting(key, value):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = %s",
            (key, value, value)
        )
        conn.commit()
    finally:
        cur.close()
        return_db_connection(conn)

def increment_setting(key, by=1):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO settings (key, value) VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE
            SET value = (COALESCE(settings.value, '0')::bigint + %s)::text
            RETURNING value
        """, (key, str(by), by))
        new_value = cur.fetchone()[0]
        conn.commit()
        return int(new_value)
    finally:
        cur.close()
        return_db_connection(conn)

def get_keys_from_db():
    val = get_setting('vless_keys', '')
    if not val:
        return []
    return [k for k in val.split('|||') if k]

def save_keys_to_db(keys):
    set_setting('vless_keys', '|||'.join(keys))

def generate_subscription_token():
    chars = string.ascii_letters + string.digits
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        max_attempts = 100
        for _ in range(max_attempts):
            token = ''.join(random.choices(chars, k=12))
            cur.execute("SELECT user_id FROM users WHERE token = %s", (token,))
            if not cur.fetchone():
                return token
        token = ''.join(random.choices(chars, k=16))
        return token
    finally:
        cur.close()
        return_db_connection(conn)

def get_next_file_number():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO settings (key, value) VALUES ('decrypt_file_counter', '1')
            ON CONFLICT (key) DO UPDATE
            SET value = (COALESCE(settings.value, '0')::integer + 1)::text
            RETURNING value
        """)
        new_value = cur.fetchone()[0]
        conn.commit()
        return int(new_value)
    finally:
        cur.close()
        return_db_connection(conn)

def ensure_bot_start_time():
    existing = get_setting('bot_start_time', '')
    if not existing:
        set_setting('bot_start_time', str(int(time.time())))

# ==================== AUTO POSTING TABLES ====================

def init_autopost_tables():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS autopost_channels (
                id SERIAL PRIMARY KEY,
                channel_id BIGINT NOT NULL,
                channel_name TEXT,
                topic_id BIGINT DEFAULT 0,
                enabled BOOLEAN DEFAULT TRUE,
                interval_seconds INTEGER DEFAULT 1800,
                max_working INTEGER DEFAULT 10,
                max_not_working INTEGER DEFAULT 5,
                last_post BIGINT DEFAULT 0,
                created_by BIGINT,
                created_at BIGINT,
                is_default BOOLEAN DEFAULT FALSE,
                UNIQUE(channel_id, topic_id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS autopost_user_access (
                user_id BIGINT,
                channel_id BIGINT,
                can_post BOOLEAN DEFAULT TRUE,
                can_manage BOOLEAN DEFAULT FALSE,
                can_announce BOOLEAN DEFAULT FALSE,
                granted_by BIGINT,
                granted_at BIGINT,
                PRIMARY KEY (user_id, channel_id)
            )
        """)
        conn.commit()
    finally:
        cur.close()
        return_db_connection(conn)
    add_default_channel()

def add_default_channel():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM autopost_channels WHERE is_default = TRUE")
        if not cur.fetchone():
            cur.execute("""
                INSERT INTO autopost_channels 
                (channel_id, channel_name, topic_id, created_by, created_at, is_default, enabled)
                VALUES (%s, %s, %s, %s, %s, TRUE, TRUE)
            """, (AUTO_POST_CHANNEL, "Ciorsa VPN", AUTO_POST_TOPIC_ID, ADMIN_ID, int(time.time())))
            conn.commit()
    finally:
        cur.close()
        return_db_connection(conn)

# ==================== AUTO POSTING FUNCTIONS ====================

def remove_used_keys(keys_to_remove):
    current_keys = get_keys_from_db()
    for key in keys_to_remove:
        if key in current_keys:
            current_keys.remove(key)
    save_keys_to_db(current_keys)

def get_autopost_config():
    return {
        'enabled': get_setting('autopost_enabled', 'true') == 'true',
        'interval': int(get_setting('autopost_interval', str(AUTO_POST_INTERVAL))),
        'channel_id': int(get_setting('autopost_channel', str(AUTO_POST_CHANNEL))),
        'topic_id': int(get_setting('autopost_topic', str(AUTO_POST_TOPIC_ID))),
    }

def save_autopost_config(config):
    set_setting('autopost_enabled', str(config['enabled']).lower())
    set_setting('autopost_interval', str(config['interval']))
    set_setting('autopost_channel', str(config['channel_id']))
    set_setting('autopost_topic', str(config['topic_id']))

# ==================== KEY PARSING UTILS ====================

def _dedup(lst):
    seen = set()
    out = []
    for x in lst:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

def _extract_vpn_keys(text):
    keys = re.findall(VPN_KEY_PATTERN, text, re.IGNORECASE)
    cleaned = []
    for k in keys:
        k = k.strip().rstrip('.,;"\')>]}')
        if 'vless://' in k.lower():
            if 'reality' in k.lower() or 'flow=xtls' in k.lower():
                cleaned.append(k)
                continue
        cleaned.append(k)
    return cleaned

def _try_b64(data, min_len=16):
    if not data:
        return None
    cleaned = re.sub(r'\s+', '', data.strip())
    if len(cleaned) < min_len:
        return None
    if not re.match(r'^[A-Za-z0-9+/_\-=]+$', cleaned):
        return None
    variants = [cleaned, cleaned.replace('-', '+').replace('_', '/')]
    for variant in variants:
        for pad_len in range(0, 4):
            padded = variant + ('=' * pad_len)
            try:
                decoded = base64.b64decode(padded, validate=False).decode('utf-8', errors='ignore')
                if len(decoded) > 8:
                    return decoded
            except:
                continue
    return None

def _try_multilevel_b64(data, max_depth=4):
    found = []
    current = data
    seen_layers = set()
    for _ in range(max_depth):
        if current in seen_layers:
            break
        seen_layers.add(current)
        direct = _extract_vpn_keys(current)
        if direct:
            found.extend(direct)
        decoded = _try_b64(current)
        if not decoded or decoded == current:
            break
        current = decoded
    return found

def _resolve_url(raw_url):
    raw_url = raw_url.strip()
    app_scheme = re.match(
        r'^(?:' + APP_SCHEMES + r')://(?:add|sub|crypt\d*|import|install|update)/+(.+)$',
        raw_url, re.IGNORECASE
    )
    if app_scheme:
        payload = urllib.parse.unquote(app_scheme.group(1).strip())
        payload = payload.split('#')[0]
        decoded = _try_b64(payload)
        if decoded and re.match(r'https?://', decoded.strip(), re.IGNORECASE):
            return decoded.strip()
        return payload
    return raw_url

def _safe_request(url, timeout=30, headers=None):
    session = requests.Session()
    try:
        if headers is None:
            headers = {'User-Agent': 'Mozilla/5.0'}
        resp = session.get(url, timeout=timeout, headers=headers, verify=False, allow_redirects=True)
        return resp
    finally:
        session.close()

def load_keys_from_url(raw_url):
    url = _resolve_url(raw_url)
    if not re.match(r'https?://', url, re.IGNORECASE):
        decoded = _try_b64(url)
        if decoded:
            keys = _extract_vpn_keys(decoded)
            if keys:
                return _dedup(keys)
        return _dedup(_extract_vpn_keys(url))
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive'
    }
    content = None
    for verify in [True, False]:
        try:
            session = requests.Session()
            resp = session.get(
                url,
                headers=headers,
                timeout=30,
                verify=verify,
                allow_redirects=True,
                max_redirects=10
            )
            if resp.status_code == 200:
                content = resp.text
                break
        except:
            continue
    if not content:
        return []
    visited = {url}
    return _parse_keys_from_content(content, depth=0, visited_urls=visited)

def load_keys_from_text(text):
    return _parse_keys_from_content(text, depth=0, visited_urls=set())

def _parse_clash_yaml(content):
    keys = []
    try:
        proxy_section = re.search(
            r'(?:^|\n)proxies:\s*\n(.*?)(?=\n\w|\Z)',
            content,
            re.DOTALL | re.IGNORECASE
        )
        if not proxy_section:
            return keys
        
        proxy_text = proxy_section.group(1)
        proxy_blocks = re.split(r'\n\s*-\s*name:', proxy_text)
        
        for block in proxy_blocks:
            if not block.strip():
                continue
            
            block = 'name:' + block if not block.startswith('name:') else block
            proxy = {}
            
            name_m = re.search(r'name:\s*["\']?([^"\'\n]+)["\']?', block)
            type_m = re.search(r'type:\s*(\w+)', block)
            server_m = re.search(r'server:\s*([^\s\n]+)', block)
            port_m = re.search(r'port:\s*(\d+)', block)
            
            if not all([type_m, server_m, port_m]):
                continue
            
            proxy['name'] = name_m.group(1).strip() if name_m else 'Unknown'
            proxy['type'] = type_m.group(1).strip().lower()
            proxy['server'] = server_m.group(1).strip()
            proxy['port'] = port_m.group(1).strip()
            
            uuid_m = re.search(r'uuid:\s*([^\s\n]+)', block)
            if uuid_m:
                proxy['uuid'] = uuid_m.group(1).strip()
            
            password_m = re.search(r'password:\s*([^\s\n]+)', block)
            if password_m:
                proxy['password'] = password_m.group(1).strip()
            
            cipher_m = re.search(r'cipher:\s*([^\s\n]+)', block)
            if cipher_m:
                proxy['cipher'] = cipher_m.group(1).strip()
            
            tls_m = re.search(r'tls:\s*(true|false)', block)
            if tls_m:
                proxy['tls'] = tls_m.group(1) == 'true'
            
            sni_m = re.search(r'sni:\s*([^\s\n]+)', block)
            if sni_m:
                proxy['sni'] = sni_m.group(1).strip()
            
            network_m = re.search(r'network:\s*(\w+)', block)
            if network_m:
                proxy['network'] = network_m.group(1).strip()
            
            flow_m = re.search(r'flow:\s*([^\s\n]+)', block)
            if flow_m:
                proxy['flow'] = flow_m.group(1).strip()
            
            reality_m = re.search(r'reality-opts:(.*?)(?=\n\s*\w|\Z)', block, re.DOTALL)
            if reality_m:
                reality_block = reality_m.group(1)
                pub_key_m = re.search(r'public-key:\s*([^\s\n]+)', reality_block)
                short_id_m = re.search(r'short-id:\s*([^\s\n]+)', reality_block)
                if pub_key_m:
                    proxy['pbk'] = pub_key_m.group(1).strip()
                if short_id_m:
                    proxy['sid'] = short_id_m.group(1).strip()
            
            ws_m = re.search(r'ws-opts:(.*?)(?=\n\s*\w|\Z)', block, re.DOTALL)
            if ws_m:
                ws_block = ws_m.group(1)
                path_m = re.search(r'path:\s*([^\s\n]+)', ws_block)
                host_m = re.search(r'Host:\s*([^\s\n]+)', ws_block)
                if path_m:
                    proxy['path'] = path_m.group(1).strip()
                if host_m:
                    proxy['host'] = host_m.group(1).strip()
            
            key = _build_key_from_clash(proxy)
            if key:
                keys.append(key)
                
    except Exception as e:
        print(f"[_parse_clash_yaml] Ошибка: {e}")
    
    return keys

def _parse_singbox_json(data):
    keys = []
    try:
        outbounds = data.get('outbounds', [])
        for ob in outbounds:
            if not isinstance(ob, dict):
                continue
            
            ob_type = ob.get('type', '').lower()
            
            if ob_type in ('selector', 'urltest', 'direct', 'block', 'dns'):
                continue
            
            server = ob.get('server', '')
            port = ob.get('server_port', ob.get('port', ''))
            tag = ob.get('tag', server)
            
            if not server or not port:
                continue
            
            if ob_type == 'vless':
                uuid = ob.get('uuid', '')
                if not uuid:
                    continue
                
                tls = ob.get('tls', {})
                transport = ob.get('transport', {})
                
                params = {
                    'type': transport.get('type', 'tcp'),
                    'security': 'reality' if tls.get('reality') else ('tls' if tls.get('enabled') else 'none'),
                }
                
                flow = ob.get('flow', '')
                if flow:
                    params['flow'] = flow
                
                sni = tls.get('server_name', '')
                if sni:
                    params['sni'] = sni
                
                reality = tls.get('reality', {})
                if reality:
                    params['security'] = 'reality'
                    if reality.get('public_key'):
                        params['pbk'] = reality['public_key']
                    if reality.get('short_id'):
                        params['sid'] = reality['short_id']
                
                fp = tls.get('utls', {}).get('fingerprint', '')
                if fp:
                    params['fp'] = fp
                
                if transport.get('type') == 'ws':
                    params['path'] = transport.get('path', '/')
                    headers = transport.get('headers', {})
                    if headers.get('Host'):
                        params['host'] = headers['Host']
                
                name_encoded = urllib.parse.quote(tag)
                query = urllib.parse.urlencode(params)
                keys.append(f"vless://{uuid}@{server}:{port}?{query}#{name_encoded}")
            
            elif ob_type == 'vmess':
                uuid = ob.get('uuid', '')
                if not uuid:
                    continue
                
                transport = ob.get('transport', {})
                tls = ob.get('tls', {})
                
                vmess_obj = {
                    "v": "2", "ps": tag, "add": server, "port": str(port),
                    "id": uuid, "aid": str(ob.get('alter_id', 0)),
                    "scy": ob.get('security', 'auto'),
                    "net": transport.get('type', 'tcp'),
                    "type": "none",
                    "host": transport.get('headers', {}).get('Host', ''),
                    "path": transport.get('path', ''),
                    "tls": "tls" if tls.get('enabled') else "",
                    "sni": tls.get('server_name', ''),
                }
                encoded = base64.b64encode(
                    json.dumps(vmess_obj, ensure_ascii=False).encode()
                ).decode()
                keys.append(f"vmess://{encoded}")
            
            elif ob_type == 'trojan':
                password = ob.get('password', '')
                if not password:
                    continue
                tls = ob.get('tls', {})
                transport = ob.get('transport', {})
                params = {
                    'security': 'tls',
                    'sni': tls.get('server_name', server),
                    'type': transport.get('type', 'tcp'),
                }
                name_encoded = urllib.parse.quote(tag)
                query = urllib.parse.urlencode(params)
                keys.append(f"trojan://{password}@{server}:{port}?{query}#{name_encoded}")
            
            elif ob_type in ('shadowsocks', 'ss'):
                method = ob.get('method', 'aes-256-gcm')
                password = ob.get('password', '')
                if not password:
                    continue
                credentials = base64.b64encode(
                    f"{method}:{password}".encode()
                ).decode()
                name_encoded = urllib.parse.quote(tag)
                keys.append(f"ss://{credentials}@{server}:{port}#{name_encoded}")
            
            elif ob_type == 'hysteria2':
                password = ob.get('password', ob.get('auth', ''))
                if not password:
                    continue
                tls = ob.get('tls', {})
                sni = tls.get('server_name', server)
                name_encoded = urllib.parse.quote(tag)
                keys.append(f"hysteria2://{password}@{server}:{port}?sni={sni}#{name_encoded}")
            
            elif ob_type == 'tuic':
                uuid = ob.get('uuid', '')
                password = ob.get('password', '')
                if not uuid:
                    continue
                tls = ob.get('tls', {})
                sni = tls.get('server_name', server)
                name_encoded = urllib.parse.quote(tag)
                keys.append(f"tuic://{uuid}:{password}@{server}:{port}?sni={sni}#{name_encoded}")
                
    except Exception as e:
        print(f"[_parse_singbox_json] Ошибка: {e}")
    
    return keys

def _extract_keys_from_json(content):
    keys = []
    if not content:
        return keys
    
    content = content.strip()
    
    if 'proxies:' in content or 'Proxies:' in content:
        yaml_keys = _parse_clash_yaml(content)
        if yaml_keys:
            keys.extend(yaml_keys)
    
    try:
        data = json.loads(content)
        
        if 'outbounds' in data:
            sing_keys = _parse_singbox_json(data)
            keys.extend(sing_keys)
        
        keys.extend(_parse_json_recursive(data))
        if keys:
            return _dedup(keys)
    except (json.JSONDecodeError, ValueError):
        pass
    
    try:
        for match in re.finditer(r'(\{.*?\}|\[.*?\])', content, re.DOTALL):
            try:
                data = json.loads(match.group(0))
                keys.extend(_parse_json_recursive(data))
            except:
                pass
    except:
        pass
    
    return _dedup(keys)

def _parse_json_recursive(data, depth=0):
    keys = []
    if depth > 10:
        return keys
    
    if isinstance(data, str):
        found = _extract_vpn_keys(data)
        if found:
            keys.extend(found)
        decoded = _try_b64(data)
        if decoded:
            keys.extend(_extract_vpn_keys(decoded))
            keys.extend(_parse_json_recursive(decoded, depth + 1))
        return keys
    
    if isinstance(data, list):
        for item in data:
            keys.extend(_parse_json_recursive(item, depth + 1))
        return keys
    
    if isinstance(data, dict):
        if 'type' in data and 'server' in data and 'port' in data:
            clash_key = _build_key_from_clash(data)
            if clash_key:
                keys.append(clash_key)
        
        if 'outbounds' in data:
            for ob in data.get('outbounds', []):
                if isinstance(ob, dict):
                    keys.extend(_parse_json_recursive(ob, depth + 1))
        
        for k, v in data.items():
            keys.extend(_parse_json_recursive(v, depth + 1))
        
        if all(f in data for f in ['add', 'port', 'id']):
            vmess_key = _build_vmess_from_json(data)
            if vmess_key:
                keys.append(vmess_key)
        
        return keys
    
    return keys

def _build_vmess_from_json(data):
    try:
        required = ['add', 'port', 'id']
        if not all(k in data for k in required):
            return None
        
        vmess_obj = {
            "v": str(data.get("v", "2")),
            "ps": str(data.get("ps", data.get("name", ""))),
            "add": str(data["add"]),
            "port": str(data["port"]),
            "id": str(data["id"]),
            "aid": str(data.get("aid", data.get("alterId", "0"))),
            "scy": str(data.get("scy", data.get("security", "auto"))),
            "net": str(data.get("net", data.get("network", "tcp"))),
            "type": str(data.get("type", data.get("headerType", "none"))),
            "host": str(data.get("host", data.get("sni", ""))),
            "path": str(data.get("path", "")),
            "tls": str(data.get("tls", "")),
            "sni": str(data.get("sni", "")),
            "alpn": str(data.get("alpn", "")),
            "fp": str(data.get("fp", "")),
        }
        
        encoded = base64.b64encode(
            json.dumps(vmess_obj, ensure_ascii=False).encode()
        ).decode()
        
        return f"vmess://{encoded}"
    except:
        return None

def _build_key_from_clash(data):
    try:
        proxy_type = str(data.get('type', '')).lower()
        server = str(data.get('server', data.get('address', '')))
        port = str(data.get('port', ''))
        name = str(data.get('name', data.get('ps', server)))
        
        if not server or not port:
            return None
        
        if proxy_type == 'ss':
            method = data.get('cipher', data.get('method', 'aes-256-gcm'))
            password = data.get('password', '')
            if not password:
                return None
            credentials = base64.b64encode(
                f"{method}:{password}".encode()
            ).decode()
            name_encoded = urllib.parse.quote(name)
            return f"ss://{credentials}@{server}:{port}#{name_encoded}"
        
        if proxy_type == 'trojan':
            password = data.get('password', '')
            if not password:
                return None
            sni = data.get('sni', data.get('server-name', server))
            params = urllib.parse.urlencode({
                'security': 'tls',
                'sni': sni,
                'type': data.get('network', 'tcp'),
            })
            name_encoded = urllib.parse.quote(name)
            return f"trojan://{password}@{server}:{port}?{params}#{name_encoded}"
        
        if proxy_type == 'vless':
            uuid = data.get('uuid', data.get('id', ''))
            if not uuid:
                return None
            flow = data.get('flow', '')
            network = data.get('network', data.get('type', 'tcp'))
            security = 'reality' if data.get('pbk') else ('tls' if data.get('tls') else 'none')
            sni = data.get('sni', data.get('server-name', ''))
            params = {
                'type': network,
                'security': security,
            }
            if flow:
                params['flow'] = flow
            if sni:
                params['sni'] = sni
            if data.get('pbk'):
                params['pbk'] = data['pbk']
            if data.get('sid'):
                params['sid'] = data['sid']
            path = data.get('ws-opts', {}).get('path', data.get('path', ''))
            if path:
                params['path'] = path
            host = data.get('ws-opts', {}).get('headers', {}).get('Host', '')
            if host:
                params['host'] = host
            fp = data.get('client-fingerprint', '')
            if fp:
                params['fp'] = fp
            name_encoded = urllib.parse.quote(name)
            query = urllib.parse.urlencode(params)
            return f"vless://{uuid}@{server}:{port}?{query}#{name_encoded}"
        
        if proxy_type == 'vmess':
            uuid = data.get('uuid', '')
            if not uuid:
                return None
            vmess_obj = {
                "v": "2",
                "ps": name,
                "add": server,
                "port": port,
                "id": uuid,
                "aid": str(data.get('alterId', data.get('aid', '0'))),
                "scy": data.get('cipher', 'auto'),
                "net": data.get('network', 'tcp'),
                "type": "none",
                "host": data.get('ws-opts', {}).get('headers', {}).get('Host', ''),
                "path": data.get('ws-opts', {}).get('path', ''),
                "tls": "tls" if data.get('tls') else "",
                "sni": data.get('sni', ''),
            }
            encoded = base64.b64encode(
                json.dumps(vmess_obj, ensure_ascii=False).encode()
            ).decode()
            return f"vmess://{encoded}"
        
        if proxy_type in ('hysteria2', 'hy2'):
            password = data.get('password', data.get('auth', ''))
            if not password:
                return None
            sni = data.get('sni', server)
            name_encoded = urllib.parse.quote(name)
            return f"hysteria2://{password}@{server}:{port}?sni={sni}#{name_encoded}"
        
        if proxy_type == 'tuic':
            uuid = data.get('uuid', '')
            password = data.get('password', '')
            if not uuid:
                return None
            sni = data.get('sni', server)
            name_encoded = urllib.parse.quote(name)
            return f"tuic://{uuid}:{password}@{server}:{port}?sni={sni}#{name_encoded}"
        
        return None
    except:
        return None

def _parse_keys_from_content(content, depth=0, visited_urls=None):
    all_keys = []
    if not content or depth > 3:
        return []
    
    if visited_urls is None:
        visited_urls = set()
    
    direct_keys = _extract_vpn_keys(content)
    all_keys.extend(direct_keys)
    
    json_keys = _extract_keys_from_json(content)
    all_keys.extend(json_keys)
    
    cleaned = re.sub(r'\s+', '', content.strip())
    if len(cleaned) >= 20 and re.match(r'^[A-Za-z0-9+/_\-=]+$', cleaned):
        decoded_items = _try_multilevel_b64(cleaned, max_depth=5)
        if decoded_items:
            for item in decoded_items:
                all_keys.extend(_extract_vpn_keys(item))
                all_keys.extend(_extract_keys_from_json(item))
                all_keys.extend(_try_multilevel_b64(item, max_depth=3))
    
    url_counter = 0
    MAX_URLS_PER_PARSE = 5
    
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        all_keys.extend(_extract_vpn_keys(line))
        if len(line) >= 16 and re.match(r'^[A-Za-z0-9+/_\-=]+$', line):
            decoded_line = _try_multilevel_b64(line, max_depth=4)
            for dk in decoded_line:
                all_keys.extend(_extract_vpn_keys(dk))
                all_keys.extend(_extract_keys_from_json(dk))
        if url_counter < MAX_URLS_PER_PARSE:
            urls = re.findall(r'https?://[^\s<>"\']+', line)
            for url in urls:
                if url_counter >= MAX_URLS_PER_PARSE:
                    break
                if url in visited_urls:
                    continue
                visited_urls.add(url)
                try:
                    resp = _safe_request(url, timeout=10, headers={'User-Agent': 'v2rayNG/1.8.7'})
                    if resp.status_code == 200:
                        all_keys.extend(_parse_keys_from_content(resp.text, depth + 1, visited_urls))
                    url_counter += 1
                except:
                    pass
    
    return _dedup(all_keys)

# ==================== CHECKS ====================

def is_subscribed(user_id):
    try:
        member = bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except:
        return False

def get_subscription_link(user_id):
    if is_blocked(user_id):
        return None
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT token, is_frozen FROM users WHERE user_id = %s", (user_id,))
        result = cur.fetchone()
        if not result:
            return None
        
        token, is_frozen = result
        
        if is_frozen:
            return None
        
        if token:
            return f"{BOT_BASE_URL}/sub/{token}"
        
        token = generate_subscription_token()
        cur.execute("UPDATE users SET token = %s WHERE user_id = %s", (token, user_id))
        conn.commit()
        return f"{BOT_BASE_URL}/sub/{token}"
    finally:
        cur.close()
        return_db_connection(conn)

def is_blocked(user_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT is_blocked FROM users WHERE user_id = %s", (user_id,))
            result = cur.fetchone()
            return result[0] == 1 if result else False
        finally:
            cur.close()
            return_db_connection(conn)
    except:
        return False

def get_user_display_name(user_id):
    return get_user_display_name_cached(user_id)

def update_user_username(user_id, username):
    if not username:
        return
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("UPDATE users SET username = %s WHERE user_id = %s", (username, user_id))
            conn.commit()
        finally:
            cur.close()
            return_db_connection(conn)
    except Exception as e:
        print(f"[update_user_username] Ошибка: {e}")

def _find_user_by_username_in_db(username):
    try:
        username_lower = username.lower().lstrip('@')
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT user_id FROM users WHERE LOWER(username) = %s", (username_lower,))
            result = cur.fetchone()
            if result:
                return result[0]
        finally:
            cur.close()
            return_db_connection(conn)
    except Exception as e:
        print(f"[_find_user_by_username_in_db] Ошибка: {e}")
    return None

def get_user_id_from_input(user_input):
    user_input = user_input.strip()
    
    tg_match = re.search(r'tg://user\?id=(\d+)', user_input)
    if tg_match:
        try:
            user_id = int(tg_match.group(1))
            if user_id <= 0:
                return None
            return user_id
        except:
            return None
    
    tme_match = re.search(r't\.me/([a-zA-Z0-9_]+)', user_input)
    if tme_match:
        username = tme_match.group(1)
        uid = _find_user_by_username_in_db(username)
        if uid:
            return uid
        try:
            chat = bot.get_chat(f"@{username}")
            return chat.id
        except:
            return None
    
    if user_input.startswith('@'):
        username = user_input.lstrip('@')
        uid = _find_user_by_username_in_db(username)
        if uid:
            return uid
        try:
            chat = bot.get_chat(user_input)
            return chat.id
        except:
            return None
    
    try:
        user_id = int(user_input)
        if user_id <= 0:
            return None
        return user_id
    except:
        return None

# ==================== KEYBOARDS ====================

def main_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(
        types.KeyboardButton("👤 Личный кабинет"),
        types.KeyboardButton("📡 Моя подписка")
    )
    kb.row(
        types.KeyboardButton("👥 Рефералы"),
        types.KeyboardButton("🏆 Топ рефералов")
    )
    kb.row(
        types.KeyboardButton("ℹ️ Стаж бота"),
        types.KeyboardButton("🔓 Расшифровать подписку")
    )
    kb.row(
        types.KeyboardButton("❓ Поддержка")
    )
    return kb

def subscribe_button():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📢 ПОДПИСАТЬСЯ", url=CHANNEL_LINK))
    kb.add(types.InlineKeyboardButton("✅ Я подписался", callback_data="check_sub"))
    return kb

def blocked_message():
    return f"🚫 Вы заблокированы администратором. Обратитесь в поддержку: {SUPPORT}"

# ==================== СТАТИСТИКА БОТА ====================

def _format_duration(seconds):
    seconds = max(0, int(seconds))
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    parts = []
    if days:
        parts.append(f"{days} дн")
    if hours or days:
        parts.append(f"{hours} ч")
    parts.append(f"{minutes} мин")
    return ' '.join(parts)

def get_bot_stats():
    ensure_bot_start_time()
    start_time = int(get_setting('bot_start_time', str(int(time.time()))))
    uptime_seconds = int(time.time()) - start_time
    return {
        'uptime_text': _format_duration(uptime_seconds),
        'total_keys_checked': int(get_setting('total_keys_checked', '0')),
        'total_decryptions': int(get_setting('total_decryptions_success', '0')),
        'total_proxies_checked': int(get_setting('total_proxies_checked', '0')),
        'total_keys_issued': int(get_setting('total_keys_issued', '0')),
        'current_keys': len(get_keys_from_db()),
    }

# ==================== КАПЧА ====================

CAPTCHA_TIMEOUT = 300
SUBSCRIBE_MONITOR = {'timestamps': [], 'blocked_until': 0}
SUBSCRIBE_LIMIT = 100
SUBSCRIBE_BAN_TIME = 3600

def check_subscribe_rate():
    current_time = int(time.time())
    SUBSCRIBE_MONITOR['timestamps'] = [t for t in SUBSCRIBE_MONITOR['timestamps'] if current_time - t < 60]
    count = len(SUBSCRIBE_MONITOR['timestamps'])
    if current_time < SUBSCRIBE_MONITOR['blocked_until']:
        remaining = SUBSCRIBE_MONITOR['blocked_until'] - current_time
        return False, f"⏳ Подписки заблокированы. Осталось {remaining//60} мин."
    if count > SUBSCRIBE_LIMIT:
        SUBSCRIBE_MONITOR['blocked_until'] = current_time + SUBSCRIBE_BAN_TIME
        return False, "⚠️ Слишком много подписок. Попробуйте через час."
    return True, "OK"

def add_subscribe_record(user_id):
    SUBSCRIBE_MONITOR['timestamps'].append(int(time.time()))

# ==================== РЕФЕРАЛЬНАЯ СИСТЕМА ====================

def process_referral(referrer_id, referred_id):
    if referrer_id == referred_id:
        return False, "Нельзя пригласить самого себя"
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT user_id FROM users WHERE user_id = %s", (referred_id,))
        if not cur.fetchone():
            return False, "Реферал не зарегистрирован в боте"
        
        if not is_subscribed(referred_id):
            return False, "Реферал не подписан на канал"
        
        cur.execute("SELECT user_id FROM users WHERE user_id = %s", (referrer_id,))
        if not cur.fetchone():
            return False, "Реферер не найден"
        
        today_start = int(time.time()) - 24 * 60 * 60
        cur.execute(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id = %s AND reward_date > %s",
            (referrer_id, today_start)
        )
        count = cur.fetchone()[0]
        if count >= 10:
            return False, "Лимит рефералов (10 в день) превышен"
        
        cur.execute(
            "SELECT * FROM referrals WHERE referrer_id = %s AND referred_id = %s",
            (referrer_id, referred_id)
        )
        if cur.fetchone():
            return False, "Этот пользователь уже был приглашен"
        
        current_time = int(time.time())
        cur.execute(
            "INSERT INTO referrals (referrer_id, referred_id, reward_date, rewarded, referrer_subscribed, referred_subscribed) VALUES (%s, %s, %s, 0, %s, %s)",
            (referrer_id, referred_id, current_time, 1 if is_subscribed(referrer_id) else 0, 1)
        )
        conn.commit()
        if is_subscribed(referrer_id):
            cur.execute("SELECT subscription_end FROM users WHERE user_id = %s", (referrer_id,))
            ref_result = cur.fetchone()
            if ref_result:
                new_end = ref_result[0] + 3 * 24 * 60 * 60
                cur.execute("UPDATE users SET subscription_end = %s, notified_3days = 0 WHERE user_id = %s", (new_end, referrer_id))
                cur.execute(
                    "UPDATE referrals SET rewarded = 1 WHERE referrer_id = %s AND referred_id = %s",
                    (referrer_id, referred_id)
                )
                conn.commit()
                try:
                    bot.send_message(referrer_id, "🎉 Вам начислено +3 дня за нового реферала!")
                except:
                    pass
                return True, "Реферал добавлен, начислено +3 дня"
        return True, "Реферал сохранен"
    finally:
        cur.close()
        return_db_connection(conn)

# ==================== ADMIN FUNCTIONS ====================

def get_admin_permissions(user_id):
    if user_id == ADMIN_ID:
        return ROLE_PRESETS['owner']['permissions'].copy()
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT permissions FROM admins WHERE user_id = %s", (user_id,))
        result = cur.fetchone()
        if result and result[0]:
            try:
                return json.loads(result[0])
            except:
                pass
    finally:
        cur.close()
        return_db_connection(conn)
    return {p: False for p in PERMISSIONS}

def has_permission(user_id, permission):
    if user_id == ADMIN_ID:
        return True
    perms = get_admin_permissions(user_id)
    return perms.get(permission, False)

def update_admin_permissions(user_id, permissions_dict):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE admins SET permissions = %s WHERE user_id = %s", (json.dumps(permissions_dict), user_id))
        conn.commit()
    finally:
        cur.close()
        return_db_connection(conn)

def get_admin_role(user_id):
    if user_id == ADMIN_ID:
        return 'owner'
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT role FROM admins WHERE user_id = %s", (user_id,))
        result = cur.fetchone()
        return result[0] if result else None
    finally:
        cur.close()
        return_db_connection(conn)

def get_admin_role_name(user_id):
    role = get_admin_role(user_id)
    if role == 'owner': return "👑 Владелец"
    elif role == 'senior': return "⭐ Старший админ"
    elif role == 'junior': return "🔹 Младший админ"
    elif role == 'support': return "🟢 Поддержка"
    return "❌ Не админ"

def is_admin(user_id):
    if user_id == ADMIN_ID:
        return True
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT user_id FROM admins WHERE user_id = %s", (user_id,))
            result = cur.fetchone()
            return result is not None
        finally:
            cur.close()
            return_db_connection(conn)
    except:
        return False

# ==================== BUILD USER LIST KEYBOARD ====================

def build_user_list_keyboard(users, page, filter_type='all'):
    kb = types.InlineKeyboardMarkup(row_width=2)
    per_page = 5
    start = page * per_page
    end = start + per_page
    current_time = int(time.time())

    page_users = users[start:end]
    user_data = {}
    if page_users:
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            placeholders = ','.join(['%s'] * len(page_users))
            cur.execute(
                f"SELECT user_id, subscription_end, is_blocked FROM users WHERE user_id IN ({placeholders})",
                page_users
            )
            user_data = {row[0]: row for row in cur.fetchall()}
        finally:
            cur.close()
            return_db_connection(conn)

    for uid in page_users:
        row = user_data.get(uid)
        if row:
            _, sub_end, blk = row
            if blk:
                icon = "🚫"
            elif sub_end and sub_end > current_time:
                icon = "🟢"
            else:
                icon = "🔴"
        else:
            icon = "❓"
        admin_icon = "👑 " if is_admin(uid) else ""
        name = get_user_display_name_cached(uid)
        display = f"{icon} {admin_icon}{name}"[:40]
        kb.add(types.InlineKeyboardButton(display, callback_data=f"user_{uid}"))

    nav_row = []
    if page > 0:
        nav_row.append(types.InlineKeyboardButton("◀️ Назад", callback_data=f"page_{page-1}_{filter_type}"))
    if end < len(users):
        nav_row.append(types.InlineKeyboardButton("Вперед ▶️", callback_data=f"page_{page+1}_{filter_type}"))
    if nav_row:
        kb.row(*nav_row)

    kb.row(
        types.InlineKeyboardButton("🟢 Активные", callback_data="filter_active"),
        types.InlineKeyboardButton("🔴 Неактивные", callback_data="filter_inactive")
    )
    kb.row(
        types.InlineKeyboardButton("👑 Админы", callback_data="filter_admins"),
        types.InlineKeyboardButton("📋 Все", callback_data="filter_all")
    )
    kb.row(
        types.InlineKeyboardButton("🔙 Назад в админ-панель", callback_data="admin_back_panel"),
        types.InlineKeyboardButton("❌ Закрыть", callback_data="close_manage")
    )
    return kb

# ==================== ADMIN MENU ====================

def admin_menu():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📢 Рассылка", callback_data="admin_announce"),
        types.InlineKeyboardButton("👥 Управление пользователями", callback_data="admin_manage_users")
    )
    kb.add(
        types.InlineKeyboardButton("🔑 Управление ключами", callback_data="admin_keys"),
        types.InlineKeyboardButton("📡 Автопостинг", callback_data="admin_autopost")
    )
    kb.add(
        types.InlineKeyboardButton("👑 Управление админами", callback_data="admin_manage_admins"),
        types.InlineKeyboardButton("🪙 Система баллов", callback_data="admin_points_system")
    )
    kb.add(
        types.InlineKeyboardButton("📋 Логи админов", callback_data="admin_view_logs"),
        types.InlineKeyboardButton("🏠 Главное меню", callback_data="admin_back")
    )
    return kb

def show_keys_menu(user_id, chat_id, message_id):
    keys = get_keys_from_db()
    total_issued = int(get_setting('total_keys_issued', '0'))
    total_checked = int(get_setting('total_keys_checked', '0'))
    proxy_url = get_setting('proxy_sub_url', '')
    proxy_status = f"🔗 {proxy_url[:40]}..." if proxy_url else "❌ Не задана"
    
    auto_enabled = get_setting('auto_update_enabled', 'false') == 'true'
    auto_interval = get_setting('auto_update_interval', '3')
    auto_last = int(get_setting('auto_update_last', '0'))
    auto_status = "✅ ВКЛ" if auto_enabled else "❌ ВЫКЛ"
    
    if auto_last:
        last_str = datetime.fromtimestamp(auto_last).strftime("%d.%m в %H:%M")
        next_time = datetime.fromtimestamp(
            auto_last + int(auto_interval) * 3600
        ).strftime("%H:%M")
        auto_info = f"Последнее: {last_str}\nСледующее: в {next_time}"
    else:
        auto_info = "Ещё не запускалось"
    
    text = (
        f"🔑 *Управление ключами*\n\n"
        f"📦 Ключей в базе: {len(keys)}\n"
        f"🗑️ Выдано ключей: {total_issued}\n"
        f"📊 Всего проверено: {total_checked}\n"
        f"🌐 Прокси ссылка: {proxy_status}\n\n"
        f"🔄 *Автообновление:* {auto_status}\n"
        f"⏱ Интервал: каждые {auto_interval} ч.\n"
        f"{auto_info}\n\n"
        f"Выберите действие:"
    )
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📥 Загрузить ключи", callback_data="admin_keys_load"),
        types.InlineKeyboardButton("🌐 Загрузить из прокси", callback_data="admin_keys_proxy_menu")
    )
    kb.add(
        types.InlineKeyboardButton("🧹 Очистить нерабочие", callback_data="admin_keys_clean_dead"),
        types.InlineKeyboardButton("🗑️ Очистить все", callback_data="admin_keys_clear_all")
    )
    kb.add(
        types.InlineKeyboardButton("🔄 Автообновление", callback_data="admin_keys_auto_update"),
        types.InlineKeyboardButton("🔄 Сбросить выдачу", callback_data="admin_keys_reset_issued")
    )
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back_panel"))
    
    sent = False
    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, parse_mode="Markdown", reply_markup=kb)
            sent = True
        except Exception as e:
            print(f"[show_keys_menu] edit failed: {e}")
    if not sent:
        bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=kb)

def _show_admin_list_for_call(call):
    user_id = call.from_user.id
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT user_id, role FROM admins ORDER BY user_id")
        admins = cur.fetchall()
    finally:
        cur.close()
        return_db_connection(conn)

    text = "👑 *Управление админами*\n\n"
    for admin_id, role in admins:
        name = get_user_display_name_cached(admin_id)
        role_name = ROLE_PRESETS.get(role, {}).get('name', role)
        text += f"• {role_name} {name} (`{admin_id}`)\n"
    text += f"\n👑 Владелец: {get_user_display_name_cached(ADMIN_ID)} (`{ADMIN_ID}`)"

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("➕ Добавить админа", callback_data="add_admin_start"),
        types.InlineKeyboardButton("⚙️ Настроить права", callback_data="edit_admin_perms")
    )
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back_panel"))

    try:
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown",
            reply_markup=kb
        )
    except:
        bot.send_message(user_id, text, parse_mode="Markdown", reply_markup=kb)

def _redraw_admin_perms(call, target_id):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT role FROM admins WHERE user_id = %s", (target_id,))
        result = cur.fetchone()
    finally:
        cur.close()
        return_db_connection(conn)
    
    if not result:
        return
    
    current_perms = get_admin_permissions(target_id)
    role = result[0] or 'junior'
    role_name = ROLE_PRESETS.get(role, {}).get('name', role)
    name = get_user_display_name_cached(target_id)
    
    text = (
        f"⚙️ *Настройка прав*\n\n"
        f"👤 {name} (`{target_id}`)\n"
        f"👑 Роль: {role_name}\n\n"
        f"Включите/отключите нужные разрешения:\n\n"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    
    for perm_key, perm_name in PERMISSIONS.items():
        status = "✅" if current_perms.get(perm_key, False) else "❌"
        kb.add(types.InlineKeyboardButton(f"{status} {perm_name}", callback_data=f"toggle_perm_{target_id}_{perm_key}"))
    
    kb.add(types.InlineKeyboardButton("🔄 Сбросить к роли", callback_data=f"reset_perm_{target_id}"))
    kb.add(types.InlineKeyboardButton("🗑️ Удалить админа", callback_data=f"remove_admin_{target_id}"))
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="edit_admin_perms"))
    
    try:
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown",
            reply_markup=kb
        )
    except Exception as e:
        print(f"[_redraw_admin_perms] Ошибка: {e}")

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ ПРОКСИ ====================

def _show_proxy_menu(chat_id, message_id, user_id):
    proxy_url = get_setting('proxy_sub_url', '')
    proxy_urls = get_setting('proxy_sub_urls', '')
    
    if proxy_urls:
        url_list = [u for u in proxy_urls.split('|||') if u]
        proxy_text = f"🔗 Загружено ссылок: {len(url_list)}\n"
        for i, u in enumerate(url_list[:3], 1):
            proxy_text += f"  {i}. {u[:50]}...\n" if len(u) > 50 else f"  {i}. {u}\n"
        if len(url_list) > 3:
            proxy_text += f"  ... и ещё {len(url_list) - 3}\n"
    elif proxy_url:
        proxy_text = f"🔗 {proxy_url[:60]}..." if len(proxy_url) > 60 else f"🔗 {proxy_url}"
    else:
        proxy_text = "❌ Прокси ссылка не задана"
    
    text = f"🌐 *Загрузить из прокси ссылки*\n\n{proxy_text}"
    
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("📥 Загрузить прокси ссылку", callback_data="admin_keys_proxy_load"),
        types.InlineKeyboardButton("🗑️ Сбросить прокси ссылку", callback_data="admin_keys_proxy_reset"),
        types.InlineKeyboardButton("🔙 Назад", callback_data="admin_keys_back")
    )
    
    try:
        bot.edit_message_text(text, chat_id, message_id, parse_mode="Markdown", reply_markup=kb)
    except:
        bot.send_message(user_id, text, parse_mode="Markdown", reply_markup=kb)

def handle_proxy_url_input(message):
    user_id = message.from_user.id
    if user_id not in proxy_url_loading:
        return
    
    session = proxy_url_loading[user_id]
    if int(time.time()) - session.get('timestamp', 0) > PROXY_LOADING_TIMEOUT:
        del proxy_url_loading[user_id]
        bot.reply_to(message, "⏰ Время сессии истекло. Начните заново через меню.")
        return
    
    text = (message.text or '').strip()
    if not text:
        bot.reply_to(message, "❌ Отправьте ссылку текстом.")
        return
    
    urls_found = re.findall(r'https?://[^\s<>"\']+', text)
    app_urls = re.findall(
        r'(?:' + APP_SCHEMES + r')://[^\s<>"\']+',
        text, re.IGNORECASE
    )
    
    if not urls_found and not app_urls:
        urls_found = [text]
    
    all_found = list(dict.fromkeys(urls_found + app_urls))
    
    if not all_found:
        bot.reply_to(message, "❌ Не найдено ни одной ссылки.")
        return
    
    proxy_url_loading[user_id]['urls'].extend(all_found)
    proxy_url_loading[user_id]['urls'] = list(dict.fromkeys(proxy_url_loading[user_id]['urls']))
    
    total = len(proxy_url_loading[user_id]['urls'])
    added = len(all_found)
    
    bot.reply_to(
        message,
        f"✅ Добавлено ссылок: {added}\n"
        f"📋 Всего в очереди: {total}\n\n"
        "Отправьте ещё или нажмите *✅ Завершить загрузку*",
        parse_mode="Markdown"
    )

# ==================== ФУНКЦИЯ _do_decrypt ====================

DECRYPT_MAX_THREADS = 10
_decrypt_thread_semaphore = threading.Semaphore(DECRYPT_MAX_THREADS)

def _do_decrypt(message, user_id, text=None, file_bytes=None, file_name=None):
    if user_id in decrypt_results:
        del decrypt_results[user_id]
    try:
        wait_msg = bot.reply_to(message, "⏳ Обрабатываю подписку...")
    except Exception as e:
        print(f"[decrypt] Не удалось создать wait_msg: {e}")
        wait_msg = None

    decrypt_results[user_id] = {'waiting': True, 'timestamp': int(time.time())}

    def process():
        with _decrypt_thread_semaphore:
            try:
                if file_bytes is not None:
                    raw = file_bytes.decode('utf-8', errors='ignore')
                    keys, steps = _parse_subscription_any(raw, [])
                else:
                    keys, steps = _parse_subscription_any(text, [])
                if wait_msg:
                    try:
                        bot.delete_message(message.chat.id, wait_msg.message_id)
                    except:
                        pass
                if not keys:
                    info = '\n'.join(steps) if steps else '—'
                    err_text = (
                        "❌ Не удалось найти VPN ключи\n\n"
                        f"Шаги:\n{info}\n\n"
                        "Убедитесь что источник содержит ключи."
                    )
                    try:
                        bot.reply_to(message, err_text)
                    except:
                        try:
                            bot.send_message(message.chat.id, err_text)
                        except:
                            pass
                    return
                try:
                    increment_setting('total_decryptions_success', 1)
                except:
                    pass
                try:
                    file_number = get_next_file_number()
                except:
                    file_number = 0
                filename = f"{file_number:06d}_{datetime.now().strftime('%d.%m.%Y')}.txt"
                now = datetime.now().strftime("%Y-%m-%d %H:%M")
                src = text[:80] if text else (file_name or 'файл')
                file_content = (
                    f"# VPN подписка расшифрована\n"
                    f"# Номер файла: {file_number:06d}\n"
                    f"# Дата: {now}\n"
                    f"# Ключей: {len(keys)}\n"
                    f"# Источник: {src}\n"
                    f"# {'='*48}\n\n"
                )
                file_content += '\n'.join(keys) + '\n'
                proto_stats = {}
                for k in keys:
                    m = re.match(r'([a-z0-9+]+)://', k, re.IGNORECASE)
                    if m:
                        p = m.group(1).lower()
                        proto_stats[p] = proto_stats.get(p, 0) + 1
                stats_text = '\n'.join(f"  • {p}:// — {c}" for p, c in sorted(proto_stats.items(), key=lambda x: -x[1]))
                steps_text = '\n'.join(steps) if steps else '—'
                caption = (
                    f"✅ Расшифровка завершена!\n\n"
                    f"📊 Найдено ключей: {len(keys)}\n"
                    f"📁 Файл №{file_number:06d}\n\n"
                    f"📋 По протоколам:\n{stats_text}\n\n"
                    f"🔍 Шаги:\n{steps_text}"
                )
                if len(caption) > 1024:
                    caption = caption[:1000].rstrip() + "\n…"
                buf = io.BytesIO(file_content.encode('utf-8'))
                buf.name = filename
                try:
                    bot.send_document(message.chat.id, buf, caption=caption, visible_file_name=filename)
                except:
                    try:
                        buf.seek(0)
                        bot.send_document(message.chat.id, buf, caption=f"✅ Найдено ключей: {len(keys)}\n📁 Файл №{file_number:06d}", visible_file_name=filename)
                    except:
                        pass
            except Exception as outer_e:
                print(f"[decrypt] ошибка: {outer_e}")
                try:
                    bot.send_message(message.chat.id, "❌ Произошла ошибка при обработке подписки.")
                except:
                    pass
            finally:
                if user_id in decrypt_results:
                    del decrypt_results[user_id]
    
    t = threading.Thread(target=process)
    t.daemon = True
    t.start()

# ==================== ФУНКЦИЯ _parse_subscription_any ====================

def _parse_subscription_any(raw, steps=None):
    if steps is None:
        steps = []
    text = raw.strip()

    # GITHUB RAW
    if 'github.com' in text and '/blob/' in text:
        text = text.replace('github.com', 'raw.githubusercontent.com').replace('/blob/', '/')
        steps.append(f"🔄 GitHub → raw: {text[:60]}...")

    # PASTEBIN
    if 'pastebin.com' in text and '/raw/' not in text:
        paste_id = re.search(r'pastebin\.com/([a-zA-Z0-9]+)', text)
        if paste_id:
            text = f"https://pastebin.com/raw/{paste_id.group(1)}"
            steps.append(f"🔄 Pastebin → raw: {text}")

    # TELEGRA.PH
    if 'telegra.ph' in text:
        steps.append(f"🔗 Обнаружена ссылка Telegra.ph")
        try:
            resp = _safe_request(text, timeout=30, headers={'User-Agent': 'Mozilla/5.0'})
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                article = soup.find('article')
                if article:
                    content = article.get_text('\n')
                    steps.append(f"✅ Telegra.ph: {len(content)} символов")
                    keys = _parse_keys_from_content(content, depth=0, visited_urls=set())
                    if keys:
                        steps.append(f"✅ Найдено {len(keys)} ключей")
                        return _dedup(keys), steps
        except Exception as e:
            steps.append(f"❌ Ошибка Telegra.ph: {e}")

    # NOTION
    if 'notion.so' in text or 'notion.site' in text:
        steps.append(f"🔗 Обнаружена ссылка Notion")
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            }
            resp = _safe_request(text, timeout=30, headers=headers)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                content = soup.get_text('\n')
                steps.append(f"✅ Notion: {len(content)} символов")
                keys = _parse_keys_from_content(content, depth=0, visited_urls=set())
                if keys:
                    steps.append(f"✅ Найдено {len(keys)} ключей")
                    return _dedup(keys), steps
        except Exception as e:
            steps.append(f"❌ Ошибка Notion: {e}")

    # BELKA.NETWORK
    if 'belka.network' in text:
        steps.append(f"🔗 Обнаружена ссылка Belka VPN")
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            resp = _safe_request(text, timeout=30, headers=headers)
            if resp.status_code == 200:
                content = resp.text
                steps.append(f"✅ Загружено {len(content)} символов")
                soup = BeautifulSoup(content, 'html.parser')
                sub_links = []
                for a in soup.find_all('a'):
                    href = a.get('href', '')
                    if href and ('sub' in href or 'config' in href or 'profile' in href or 'clash' in href):
                        sub_links.append(href)
                    if a.text and ('Получить ссылку' in a.text or 'Copy' in a.text or 'скопировать' in a.text):
                        onclick = a.get('onclick', '')
                        if onclick:
                            match = re.search(r"['\"](https?://[^'\"]+)['\"]", onclick)
                            if match:
                                sub_links.append(match.group(1))
                scripts = soup.find_all('script')
                for script in scripts:
                    if script.string:
                        found = re.findall(r'https?://[^\s<>"\'`]+', script.string)
                        for link in found:
                            if len(link) > 30 and ('sub' in link or 'config' in link or 'profile' in link):
                                sub_links.append(link)
                text_content = soup.get_text()
                found_links = re.findall(r'https?://[^\s<>"\'`]+', text_content)
                for link in found_links:
                    if len(link) > 30 and ('sub' in link or 'config' in link or 'profile' in link or 'clash' in link):
                        sub_links.append(link)
                sub_links = _dedup([l.strip() for l in sub_links if l and l.startswith('http')])
                if sub_links:
                    steps.append(f"🔍 Найдено {len(sub_links)} ссылок на подписку")
                    for link in sub_links:
                        steps.append(f"⬇️ Пробую загрузить: {link[:50]}...")
                        try:
                            sub_resp = _safe_request(link, timeout=30, headers=headers)
                            if sub_resp.status_code == 200:
                                keys = _parse_keys_from_content(sub_resp.text, depth=0, visited_urls=set())
                                if keys:
                                    steps.append(f"✅ Найдено {len(keys)} ключей")
                                    return _dedup(keys), steps
                        except:
                            pass
                    steps.append(f"📋 Найдены ссылки, но ключи не извлечены")
                    return [], steps
                steps.append(f"❌ Не найдена ссылка на подписку на странице Belka")
                return [], steps
            else:
                steps.append(f"❌ Ошибка загрузки: HTTP {resp.status_code}")
                return [], steps
        except Exception as e:
            steps.append(f"❌ Ошибка: {e}")
            return [], steps

    # СХЕМЫ ПРИЛОЖЕНИЙ
    app_scheme_match = re.match(r'^(?:' + APP_SCHEMES + r')://(?:add|sub|crypt\d*|import|install|update|get|fetch)/+(.+)$', text, re.IGNORECASE)
    if app_scheme_match:
        steps.append("📱 Обнаружена схема приложения")
        payload = app_scheme_match.group(1).strip()
        payload = urllib.parse.unquote(payload)
        if re.match(r'^[A-Za-z0-9+/_\-=]+$', payload) and len(payload) > 10:
            decoded = _try_multilevel_b64(payload, max_depth=3)
            if decoded:
                for item in decoded:
                    if re.match(r'https?://', item.strip(), re.IGNORECASE):
                        try:
                            resp = _safe_request(item.strip(), timeout=30)
                            if resp.status_code == 200:
                                return _parse_subscription_any(resp.text, steps)
                        except:
                            pass
                    keys = _extract_vpn_keys(item)
                    if keys:
                        return _dedup(keys), steps
        if re.match(r'https?://', payload, re.IGNORECASE):
            try:
                resp = _safe_request(payload, timeout=30)
                if resp.status_code == 200:
                    return _parse_subscription_any(resp.text, steps)
            except:
                pass
        keys = _extract_vpn_keys(payload)
        if keys:
            return _dedup(keys), steps
        return [], steps

    # ========== HTTP URL ==========
    if re.match(r'^https?://', text, re.IGNORECASE):
        steps.append(f"⬇️ Загружаю URL: {text[:80]}...")
        
        user_agents = [
            'v2rayNG/1.8.7',
            'clash/1.18.0',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Hiddify/2.0.0',
        ]
        
        last_error = None
        resp = None
        
        for ua in user_agents:
            for attempt in range(2):
                try:
                    steps.append(f"🔄 Попытка {attempt+1}/2 с User-Agent: {ua[:20]}...")
                    
                    resp = _safe_request(
                        text,
                        timeout=15,
                        headers={'User-Agent': ua}
                    )
                    
                    steps.append(f"📊 Статус: {resp.status_code}, размер: {len(resp.text)} байт")
                    
                    if resp.status_code == 200:
                        break
                    last_error = f"HTTP {resp.status_code}"
                    
                except requests.exceptions.SSLError as e:
                    steps.append(f"⚠️ SSL ошибка: {e}")
                    last_error = f"SSL: {e}"
                    continue
                    
                except requests.exceptions.ConnectionError as e:
                    steps.append(f"❌ Ошибка соединения: {e}")
                    last_error = f"Connection: {e}"
                    time.sleep(1)
                    continue
                    
                except requests.exceptions.Timeout:
                    steps.append(f"⏰ Таймаут (15s)")
                    last_error = "Timeout"
                    time.sleep(1)
                    continue
                    
                except Exception as e:
                    steps.append(f"❌ Неизвестная ошибка: {type(e).__name__}: {e}")
                    last_error = f"{type(e).__name__}: {e}"
                    time.sleep(1)
                    continue
            
            if resp and resp.status_code == 200:
                break
        
        if not resp or resp.status_code != 200:
            steps.append(f"❌ Ошибка после всех попыток: {last_error}")
            return [], steps
        
        content = resp.text.strip()
        steps.append(f"✅ Загружено {len(content)} символов")
        
        if re.match(r'^[A-Za-z0-9+/_\-=]+$', content) and len(content) > 50:
            decoded = _try_multilevel_b64(content, max_depth=5)
            if decoded:
                all_keys = []
                for item in decoded:
                    all_keys.extend(_extract_vpn_keys(item))
                    all_keys.extend(_extract_keys_from_json(item))
                if all_keys:
                    steps.append(f"✅ Найдено {len(all_keys)} ключей (Base64 + JSON)")
                    return _dedup(all_keys), steps
        
        json_keys = _extract_keys_from_json(content)
        if json_keys:
            steps.append(f"✅ Найдено {len(json_keys)} ключей (JSON)")
            return _dedup(json_keys), steps
        
        keys = _extract_vpn_keys(content)
        if keys:
            steps.append(f"✅ Найдено {len(keys)} ключей")
            return _dedup(keys), steps
        
        if '<' in content and '>' in content:
            steps.append("🔍 Обнаружен HTML, ищу ссылки на подписки...")
            soup = BeautifulSoup(content, 'html.parser')
            for a in soup.find_all('a'):
                href = a.get('href', '')
                if href and ('sub' in href or 'config' in href or 'profile' in href or 'clash' in href):
                    if href.startswith('http'):
                        steps.append(f"⬇️ Пробую загрузить: {href[:50]}...")
                        try:
                            sub_resp = _safe_request(href, timeout=30, headers={'User-Agent': user_agents[0]})
                            if sub_resp.status_code == 200:
                                sub_keys = _parse_keys_from_content(sub_resp.text, depth=0, visited_urls=set())
                                if sub_keys:
                                    steps.append(f"✅ Найдено {len(sub_keys)} ключей (по ссылке)")
                                    return _dedup(sub_keys), steps
                        except:
                            pass
        
        steps.append(f"❌ Ключи не найдены")
        return [], steps

    keys = load_keys_from_text(text)
    if not keys:
        keys = _extract_vpn_keys(text)
    if keys:
        steps.append(f"🔍 Найдено {len(keys)} ключей")
        return _dedup(keys), steps
    steps.append("❌ Ключи не найдены")
    return [], steps

# ==================== АВТООБНОВЛЕНИЕ КЛЮЧЕЙ ====================

_auto_update_event = Event()

def auto_update_keys_scheduler():
    print("[auto_update] Запущен планировщик автообновления ключей")
    while True:
        try:
            enabled = get_setting('auto_update_enabled', 'false') == 'true'
            if enabled:
                interval_hours = int(get_setting('auto_update_interval', '3'))
                last_update = int(get_setting('auto_update_last', '0'))
                current_time = int(time.time())
                
                if current_time - last_update >= interval_hours * 3600:
                    print("[auto_update] Запуск автообновления ключей...")
                    _do_auto_update_keys()
            time.sleep(300)
        except Exception as e:
            print(f"[auto_update] Ошибка: {e}")
            time.sleep(600)

def _do_auto_update_keys():
    if _auto_update_event.is_set():
        print("[auto_update] Уже запущен, пропускаем")
        return
    _auto_update_event.set()
    try:
        proxy_urls = get_setting('proxy_sub_urls', '')
        if not proxy_urls:
            proxy_url = get_setting('proxy_sub_url', '')
            if not proxy_url:
                print("[auto_update] Нет прокси ссылок для обновления")
                return
            url_list = [proxy_url]
        else:
            url_list = [u for u in proxy_urls.split('|||') if u]
        
        if not url_list:
            return
        
        current_time = int(time.time())
        all_new_keys = []
        results = []
        
        for url in url_list:
            try:
                keys = load_keys_from_url(url)
                results.append((url, len(keys), True))
                all_new_keys.extend(keys)
            except Exception as e:
                results.append((url, 0, False))
                print(f"[auto_update] Ошибка загрузки {url}: {e}")
        
        all_new_keys = _dedup(all_new_keys)
        
        if not all_new_keys:
            print("[auto_update] Новых ключей не найдено")
            set_setting('auto_update_last', str(current_time))
            
            notify = get_setting('auto_update_notify', 'true') == 'true'
            if notify:
                try:
                    bot.send_message(
                        ADMIN_ID,
                        "🔄 *Автообновление ключей*\n\n"
                        "❌ Новых ключей не найдено\n"
                        f"🔗 Проверено ссылок: {len(url_list)}\n"
                        f"⏰ Следующее: через {get_setting('auto_update_interval', '3')} ч.",
                        parse_mode="Markdown"
                    )
                except:
                    pass
            return
        
        current_keys = get_keys_from_db()
        before_count = len(current_keys)
        merged = _dedup(current_keys + all_new_keys)
        after_count = len(merged)
        added_count = after_count - before_count
        
        save_keys_to_db(merged)
        set_setting('auto_update_last', str(current_time))
        
        print(f"[auto_update] Добавлено {added_count} новых ключей. Всего: {after_count}")
        
        notify = get_setting('auto_update_notify', 'true') == 'true'
        if notify:
            results_text = ""
            for url, count, ok in results:
                short_url = url[:45] + "..." if len(url) > 45 else url
                icon = "✅" if ok else "❌"
                results_text += f"{icon} {short_url} — {count} ключей\n"
            
            next_update = datetime.fromtimestamp(
                current_time + int(get_setting('auto_update_interval', '3')) * 3600
            ).strftime("%H:%M")
            
            text = (
                f"🔄 *Автообновление ключей*\n\n"
                f"🔗 Проверено ссылок: {len(url_list)}\n"
                f"🔑 Новых ключей: +{added_count}\n"
                f"📦 Всего в базе: {after_count}\n\n"
                f"📊 По ссылкам:\n{results_text}\n"
                f"⏰ Следующее: в {next_update}"
            )
            try:
                bot.send_message(ADMIN_ID, text, parse_mode="Markdown")
            except:
                pass
    finally:
        _auto_update_event.clear()

# ==================== ОБРАБОТЧИКИ КНОПОК МЕНЮ ====================

@bot.message_handler(func=lambda m: m.text == "👤 Личный кабинет")
def cabinet(message):
    update_activity()
    if message.chat.type != 'private':
        return
    user_id = message.from_user.id
    current_time = int(time.time())
    
    if is_blocked(user_id):
        bot.reply_to(message, blocked_message())
        return
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT subscription_end, points, is_frozen, frozen_days_left 
            FROM users WHERE user_id = %s
        """, (user_id,))
        result = cur.fetchone()
        if not result:
            bot.reply_to(message, "❌ Используйте /start")
            return
        
        subscription_end, points, is_frozen, frozen_days_left = result
        points = points or 0
        
        if is_frozen:
            status = "❄️ Заморожена"
            days_left = frozen_days_left or 0
            time_left = f"{days_left} дн"
            expire_date = "Заморожена"
        elif subscription_end and subscription_end > current_time:
            status = "✅ Активна"
            days_left = (subscription_end - current_time) // (24 * 60 * 60)
            hours_left = ((subscription_end - current_time) // 3600) % 24
            time_left = f"{days_left} дн {hours_left} ч"
            expire_date = datetime.fromtimestamp(subscription_end).strftime("%d.%m.%Y в %H:%M")
        else:
            status = "❌ Не активна"
            time_left = "Закончилась"
            expire_date = "Закончилась"
        
        cur.execute("""
            SELECT SUM(messages_count) FROM chat_activity WHERE user_id = %s
        """, (user_id,))
        total_messages = cur.fetchone()[0] or 0
        
        rank = get_rank(points)
        days_available = get_days_available(points)
        
        text = (
            f"👤 *Личный кабинет*\n\n"
            f"🆔 ID: `{user_id}`\n"
            f"📊 Статус: {status}\n"
            f"📅 Подписка до: `{expire_date}`\n"
            f"⏳ Осталось: `{time_left}`\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"{rank['name']}\n"
            f"🪙 *Баллов:* `{points:,}`\n"
            f"💬 Сообщений: `{total_messages:,}`\n"
            f"💰 Курс: `{rank['cost']}` баллов = 1 день\n"
            f"🎁 Можно обменять: `{days_available}` дн.\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )

        kb = types.InlineKeyboardMarkup(row_width=2)
        if days_available > 0:
            kb.add(types.InlineKeyboardButton(
                f"🎁 Обменять баллы ({days_available} дн.)",
                callback_data="exchange_points"
            ))
        else:
            cost_per_day = get_rank(points)['cost']
            needed = cost_per_day - (points % cost_per_day) if points % cost_per_day != 0 else cost_per_day
            kb.add(types.InlineKeyboardButton(
                f"🪙 Нужно ещё {needed} баллов для обмена",
                callback_data="points_info"
            ))
        kb.add(types.InlineKeyboardButton("🔄 Обновить", callback_data="refresh_cabinet"))
        
        bot.reply_to(message, text, parse_mode="Markdown", reply_markup=kb)
        
    finally:
        cur.close()
        return_db_connection(conn)

@bot.callback_query_handler(func=lambda call: call.data == "refresh_cabinet")
def callback_refresh_cabinet(call):
    user_id = call.from_user.id
    current_time = int(time.time())
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT subscription_end, points, is_frozen, frozen_days_left 
            FROM users WHERE user_id = %s
        """, (user_id,))
        result = cur.fetchone()
        if not result:
            bot.answer_callback_query(call.id, "❌ Ошибка")
            return
        
        subscription_end, points, is_frozen, frozen_days_left = result
        points = points or 0
        
        if is_frozen:
            status = "❄️ Заморожена"
            days_left = frozen_days_left or 0
            time_left = f"{days_left} дн"
            expire_date = "Заморожена"
        elif subscription_end and subscription_end > current_time:
            status = "✅ Активна"
            days_left = (subscription_end - current_time) // (24 * 60 * 60)
            hours_left = ((subscription_end - current_time) // 3600) % 24
            time_left = f"{days_left} дн {hours_left} ч"
            expire_date = datetime.fromtimestamp(subscription_end).strftime("%d.%m.%Y в %H:%M")
        else:
            status = "❌ Не активна"
            time_left = "Закончилась"
            expire_date = "Закончилась"
        
        cur.execute("""
            SELECT SUM(messages_count) FROM chat_activity WHERE user_id = %s
        """, (user_id,))
        total_messages = cur.fetchone()[0] or 0
        
        rank = get_rank(points)
        days_available = get_days_available(points)
        
        text = (
            f"👤 *Личный кабинет*\n\n"
            f"🆔 ID: `{user_id}`\n"
            f"📊 Статус: {status}\n"
            f"📅 Подписка до: `{expire_date}`\n"
            f"⏳ Осталось: `{time_left}`\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"{rank['name']}\n"
            f"🪙 *Баллов:* `{points:,}`\n"
            f"💬 Сообщений: `{total_messages:,}`\n"
            f"💰 Курс: `{rank['cost']}` баллов = 1 день\n"
            f"🎁 Можно обменять: `{days_available}` дн.\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )

        kb = types.InlineKeyboardMarkup(row_width=2)
        if days_available > 0:
            kb.add(types.InlineKeyboardButton(
                f"🎁 Обменять баллы ({days_available} дн.)",
                callback_data="exchange_points"
            ))
        else:
            cost_per_day = get_rank(points)['cost']
            needed = cost_per_day - (points % cost_per_day) if points % cost_per_day != 0 else cost_per_day
            kb.add(types.InlineKeyboardButton(
                f"🪙 Нужно ещё {needed} баллов для обмена",
                callback_data="points_info"
            ))
        kb.add(types.InlineKeyboardButton("🔄 Обновить", callback_data="refresh_cabinet"))
        
        try:
            bot.edit_message_text(
                text,
                call.message.chat.id,
                call.message.message_id,
                parse_mode="Markdown",
                reply_markup=kb
            )
        except:
            bot.send_message(user_id, text, parse_mode="Markdown", reply_markup=kb)
        
        bot.answer_callback_query(call.id, "✅ Обновлено!")
        
    finally:
        cur.close()
        return_db_connection(conn)

@bot.callback_query_handler(func=lambda call: call.data == "points_info")
def callback_points_info(call):
    user_id = call.from_user.id
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT points FROM users WHERE user_id = %s", (user_id,))
        result = cur.fetchone()
        points = result[0] if result else 0
    finally:
        cur.close()
        return_db_connection(conn)

    rank = get_rank(points)
    cost_per_day = rank['cost']
    needed = cost_per_day - (points % cost_per_day) if points % cost_per_day != 0 else cost_per_day
    days_available = points // cost_per_day

    if days_available > 0:
        bot.answer_callback_query(
            call.id,
            f"🪙 У вас {points} баллов\n"
            f"Можно обменять на {days_available} дн.\n"
            f"Используйте кнопку обмена!",
            show_alert=True
        )
    else:
        bot.answer_callback_query(
            call.id,
            f"🪙 У вас {points} баллов\n"
            f"Нужно ещё {needed} баллов для 1 дня\n"
            f"Пишите в чатах чтобы накопить!",
            show_alert=True
        )

# ==================== ОБМЕН БАЛЛОВ ====================

@bot.callback_query_handler(func=lambda call: call.data == "exchange_points")
def callback_exchange_points(call):
    user_id = call.from_user.id
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT points, subscription_end, is_frozen FROM users WHERE user_id = %s",
            (user_id,)
        )
        result = cur.fetchone()
        if not result:
            bot.answer_callback_query(call.id, "❌ Ошибка")
            return
        
        points, sub_end, is_frozen = result
        points = points or 0
        days_available = get_days_available(points)
        
        if is_frozen:
            bot.answer_callback_query(call.id, "❌ Подписка заморожена. Разморозьте её сначала.")
            return
        
        if days_available == 0:
            bot.answer_callback_query(call.id, "❌ Недостаточно баллов")
            return
        
        exchange_cache[user_id] = {
            'exchange_days': 1,
            'max_days': days_available,
            'points': points,
            'timestamp': int(time.time())
        }
        
        _show_exchange_panel(call, user_id, 1, days_available, points)
        bot.answer_callback_query(call.id)
        
    finally:
        cur.close()
        return_db_connection(conn)

def _show_exchange_panel(call, user_id, selected_days, max_days, points):
    rank = get_rank(points)
    cost = get_exchange_cost(points, selected_days)
    
    text = (
        f"🎁 *Обмен баллов*\n\n"
        f"🪙 Ваши баллы: `{points:,}`\n"
        f"{rank['name']}\n"
        f"💰 Курс: `{rank['cost']}` баллов = 1 день\n"
        f"📅 Максимум дней: `{max_days}`\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Выбрано: *{selected_days} дн.* = `{cost:,}` баллов\n"
        f"Останется: `{points - cost:,}` баллов\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )
    
    kb = types.InlineKeyboardMarkup(row_width=3)
    
    row = []
    if selected_days > 1:
        row.append(types.InlineKeyboardButton("➖", callback_data=f"exch_{selected_days-1}"))
    else:
        row.append(types.InlineKeyboardButton("➖", callback_data="exch_min"))
    
    row.append(types.InlineKeyboardButton(f"📅 {selected_days} дн.", callback_data="exch_info"))
    
    if selected_days < max_days:
        row.append(types.InlineKeyboardButton("➕", callback_data=f"exch_{selected_days+1}"))
    else:
        row.append(types.InlineKeyboardButton("➕", callback_data="exch_max"))
    
    kb.row(*row)
    
    quick = []
    for d in [1, 7, 30]:
        if d <= max_days:
            quick.append(types.InlineKeyboardButton(f"{d}д", callback_data=f"exch_{d}"))
    if quick:
        kb.row(*quick)
    
    kb.row(
        types.InlineKeyboardButton(f"✅ Обменять {selected_days} дн.", callback_data=f"exch_confirm_{selected_days}"),
        types.InlineKeyboardButton("🔙 Назад", callback_data="refresh_cabinet")
    )
    
    try:
        bot.edit_message_text(
            text, call.message.chat.id, call.message.message_id,
            parse_mode="Markdown", reply_markup=kb
        )
    except:
        bot.send_message(user_id, text, parse_mode="Markdown", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data.startswith('exch_'))
def callback_exchange_action(call):
    user_id = call.from_user.id
    data = call.data
    
    if data in ('exch_min', 'exch_max', 'exch_info'):
        bot.answer_callback_query(call.id)
        return
    
    if data.startswith('exch_confirm_'):
        days = int(data.split('_')[2])
        
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT points, subscription_end, is_frozen FROM users WHERE user_id = %s",
                (user_id,)
            )
            result = cur.fetchone()
            if not result:
                bot.answer_callback_query(call.id, "❌ Ошибка")
                return
            
            points, sub_end, is_frozen = result
            points = points or 0
            
            if is_frozen:
                bot.answer_callback_query(call.id, "❌ Подписка заморожена. Разморозьте её сначала.")
                return
            
            rank = get_rank(points)
            cost = days * rank['cost']
            
            if points < cost:
                bot.answer_callback_query(call.id, "❌ Недостаточно баллов")
                return
            
            current_time = int(time.time())
            current_end = sub_end if (sub_end and sub_end > current_time) else current_time
            new_end = current_end + days * 24 * 60 * 60
            new_points = points - cost
            
            cur.execute("""
                UPDATE users SET points = %s, subscription_end = %s, notified_3days = 0
                WHERE user_id = %s
            """, (new_points, new_end, user_id))
            conn.commit()
            
            bot.answer_callback_query(call.id, f"✅ +{days} дней!")
            
            text = (
                f"✅ *Обмен выполнен!*\n\n"
                f"🎁 Получено: +{days} дней\n"
                f"💸 Потрачено: {cost:,} баллов\n"
                f"🪙 Осталось: {new_points:,} баллов\n"
                f"📅 Подписка до: {datetime.fromtimestamp(new_end).strftime('%d.%m.%Y')}"
            )
            
            if user_id in exchange_cache:
                exchange_cache[user_id]['points'] = new_points
                exchange_cache[user_id]['max_days'] = new_points // rank['cost']
                exchange_cache[user_id]['timestamp'] = int(time.time())
            
            try:
                bot.edit_message_text(
                    text, call.message.chat.id, call.message.message_id,
                    parse_mode="Markdown"
                )
            except:
                bot.send_message(user_id, text, parse_mode="Markdown")
            
        finally:
            cur.close()
            return_db_connection(conn)
        return
    
    try:
        days = int(data.split('_')[1])
    except:
        bot.answer_callback_query(call.id)
        return
    
    cached = exchange_cache.get(user_id, {})
    cache_age = int(time.time()) - cached.get('timestamp', 0)
    
    if cache_age > 60 or not cached.get('points'):
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT points FROM users WHERE user_id = %s", (user_id,))
            result = cur.fetchone()
            if result:
                points = result[0] or 0
                max_days = get_days_available(points)
                exchange_cache[user_id] = {
                    'exchange_days': days,
                    'max_days': max_days,
                    'points': points,
                    'timestamp': int(time.time())
                }
        finally:
            cur.close()
            return_db_connection(conn)
    
    cached = exchange_cache.get(user_id, {})
    max_days = cached.get('max_days', 1)
    points = cached.get('points', 0)
    
    days = max(1, min(days, max_days))
    exchange_cache[user_id]['exchange_days'] = days
    exchange_cache[user_id]['timestamp'] = int(time.time())
    
    _show_exchange_panel(call, user_id, days, max_days, points)
    bot.answer_callback_query(call.id)

# ==================== КОМАНДА /DECRYPT ДЛЯ ЧАТОВ ====================

@bot.message_handler(commands=['decrypt'])
def cmd_decrypt(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if is_blocked(user_id):
        bot.reply_to(message, blocked_message())
        return
    
    text = message.text.strip()
    
    if ' ' in text:
        parts = text.split(maxsplit=1)
        command_part = parts[0]
        
        if '@' in command_part:
            command_part = command_part.split('@')[0]
            if len(parts) > 1:
                text = command_part + ' ' + parts[1]
            else:
                text = command_part
    
    parts = text.split(maxsplit=1)
    
    if len(parts) < 2:
        bot.reply_to(
            message,
            "❌ Использование: `/decrypt [ссылка]`\n\n"
            "Пример: `/decrypt https://example.com/sub`",
            parse_mode="Markdown"
        )
        return
    
    url = parts[1].strip()
    
    if not url.startswith('http'):
        bot.reply_to(
            message,
            "❌ Это не ссылка! Отправьте ссылку на подписку.\n\n"
            "Пример: `/decrypt https://example.com/sub`",
            parse_mode="Markdown"
        )
        return
    
    wait_msg = bot.reply_to(message, "⏳ Расшифровываю подписку...")
    
    def process_decrypt():
        try:
            keys, steps = _parse_subscription_any(url, [])
            
            if not keys:
                info = '\n'.join(steps) if steps else '—'
                err_text = (
                    "❌ Не удалось найти VPN ключи\n\n"
                    f"Шаги:\n{info}"
                )
                bot.edit_message_text(err_text, chat_id, wait_msg.message_id)
                return
            
            proto_stats = {}
            for k in keys:
                m = re.match(r'([a-z0-9+]+)://', k, re.IGNORECASE)
                if m:
                    p = m.group(1).lower()
                    proto_stats[p] = proto_stats.get(p, 0) + 1
            
            stats_text = '\n'.join(
                f"  • {p}:// — {c}"
                for p, c in sorted(proto_stats.items(), key=lambda x: -x[1])
            )
            
            keys_preview = '\n'.join([f"`{k}`" for k in keys[:5]])
            
            result_text = (
                f"✅ *Расшифровка завершена!*\n\n"
                f"📊 Найдено ключей: {len(keys)}\n"
                f"📋 По протоколам:\n{stats_text}\n\n"
                f"🔑 *Ключи:*\n{keys_preview}"
            )
            
            if len(keys) > 5:
                result_text += f"\n\n_... и ещё {len(keys)-5} ключей_"
            
            kb = None
            if len(keys) > 5:
                kb = types.InlineKeyboardMarkup()
                kb.add(types.InlineKeyboardButton(
                    f"📋 Показать все ({len(keys)} ключей)",
                    callback_data=f"decrypt_show_all_{user_id}_{chat_id}_{wait_msg.message_id}"
                ))
                decrypt_results[user_id] = {
                    'keys': keys,
                    'chat_id': chat_id,
                    'message_id': wait_msg.message_id,
                    'timestamp': int(time.time())
                }
            
            try:
                bot.edit_message_text(
                    result_text,
                    chat_id,
                    wait_msg.message_id,
                    parse_mode="Markdown",
                    reply_markup=kb
                )
            except:
                bot.send_message(chat_id, result_text, parse_mode="Markdown")
                
        except Exception as e:
            try:
                bot.edit_message_text(
                    f"❌ Ошибка: {e}",
                    chat_id,
                    wait_msg.message_id
                )
            except:
                bot.send_message(chat_id, f"❌ Ошибка: {e}")
    
    t = threading.Thread(target=process_decrypt)
    t.daemon = True
    t.start()

# ==================== ОБРАБОТЧИК КНОПКИ "ПОКАЗАТЬ ВСЕ" ====================

@bot.callback_query_handler(func=lambda call: call.data.startswith('decrypt_show_all_'))
def callback_decrypt_show_all(call):
    data_parts = call.data.split('_')
    user_id = int(data_parts[3])
    chat_id = int(data_parts[4])
    message_id = int(data_parts[5])
    
    if call.from_user.id != user_id:
        bot.answer_callback_query(call.id, "❌ Это не ваша расшифровка")
        return
    
    cached = decrypt_results.get(user_id, {})
    keys = cached.get('keys', [])
    
    if not keys:
        bot.answer_callback_query(call.id, "❌ Ключи не найдены или истекли")
        return
    
    keys_text = '\n'.join([f"`{k}`" for k in keys])
    text = (
        f"📋 *Все ключи ({len(keys)}):*\n\n"
        f"{keys_text}"
    )
    
    if len(text) > 4000:
        parts = []
        current = "📋 *Все ключи:*\n\n"
        for k in keys:
            line = f"`{k}`\n"
            if len(current) + len(line) > 3900:
                parts.append(current)
                current = ""
            current += line
        if current:
            parts.append(current)
        
        bot.answer_callback_query(call.id, f"✅ Показано {len(keys)} ключей")
        for i, part in enumerate(parts):
            if i == 0:
                bot.send_message(chat_id, part, parse_mode="Markdown")
            else:
                bot.send_message(chat_id, part, parse_mode="Markdown")
    else:
        try:
            bot.edit_message_text(
                text,
                chat_id,
                message_id,
                parse_mode="Markdown"
            )
        except:
            bot.send_message(chat_id, text, parse_mode="Markdown")
    
    bot.answer_callback_query(call.id, "✅ Показаны все ключи")

# ==================== "МОЯ ПОДПИСКА" С ЗАМОРОЗКОЙ ====================

@bot.message_handler(func=lambda m: m.text == "📡 Моя подписка")
def my_subscription(message):
    update_activity()
    if message.chat.type != 'private':
        return
    user_id = message.from_user.id
    current_time = int(time.time())
    
    if is_blocked(user_id):
        bot.reply_to(message, blocked_message())
        return
    if not is_subscribed(user_id):
        bot.reply_to(message, "⚠️ Подпишитесь на канал.", reply_markup=subscribe_button())
        return
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT subscription_end, is_frozen, frozen_days_left 
            FROM users WHERE user_id = %s
        """, (user_id,))
        result = cur.fetchone()
        if not result:
            bot.reply_to(message, "❌ Не зарегистрированы. /start")
            return
        
        subscription_end, is_frozen, frozen_days_left = result
        
        if is_frozen:
            text = (
                f"📡 *Моя подписка*\n\n"
                f"❄️ *Подписка заморожена*\n\n"
                f"⏳ Сохранено дней: `{frozen_days_left}`\n\n"
                f"Нажмите кнопку ниже чтобы разморозить.\n"
                f"Будет сгенерирован новый токен подписки.\n\n"
                f"💬 Поддержка: {SUPPORT}"
            )
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton(
                "🔥 Разморозить подписку",
                callback_data="unfreeze_sub"
            ))
            bot.reply_to(message, text, parse_mode="Markdown", reply_markup=kb)
            return
        
        link = get_subscription_link(user_id) if subscription_end and subscription_end > current_time else None
        yandex_link = f"https://translate.yandex.ru/translate?url={link}" if link else None
        days_left = (subscription_end - current_time) // (24 * 60 * 60) if subscription_end and subscription_end > current_time else 0

        if subscription_end and subscription_end > current_time:
            status_text = f"✅ Активна\n⏳ Осталось: `{days_left}` дн."
        else:
            status_text = "❌ Не активна\n\nДля продления обратитесь к администратору:"

        text = (
            f"📡 *Моя подписка*\n\n"
            f"📊 Статус: {status_text}\n\n"
        )
        
        if link:
            text += (
                f"┌ 🔗 *Обычная ссылка:*\n"
                f"│ `{link}`\n"
                f"│\n"
                f"├ 🔄 *Для белых списков:*\n"
                f"│ `{yandex_link}`\n"
                f"│\n"
                f"└ ℹ️ *Ссылка автообновляется*\n\n"
            )
        
        text += (
            f"📱 *Поддерживаемые клиенты:*\n"
            f"• V2Ray / V2RayNG\n"
            f"• Hiddify / Nekobox\n"
            f"• FlClash / Mihomo\n"
            f"• Clash Meta / Sing-Box\n\n"
            f"💬 Поддержка: {SUPPORT}"
        )

        kb = types.InlineKeyboardMarkup(row_width=2)
        
        if link:
            kb.add(
                types.InlineKeyboardButton("📋 Обычная", callback_data=f"copy_link_{user_id}"),
                types.InlineKeyboardButton("🔄 Белые списки", callback_data=f"copy_yandex_{user_id}")
            )
            kb.row(
                types.InlineKeyboardButton("🍎 Incy iOS", url="https://apps.apple.com/ru/app/incy/id6756943388"),
                types.InlineKeyboardButton("🤖 Incy Android", url="https://play.google.com/store/apps/details?id=llc.itdev.incy")
            )
            if days_left > 0:
                kb.add(types.InlineKeyboardButton(
                    f"❄️ Заморозить ({days_left} дн.)",
                    callback_data="freeze_sub"
                ))
        else:
            kb.add(types.InlineKeyboardButton(
                "💬 Связаться с поддержкой",
                url=f"https://t.me/{SUPPORT.lstrip('@')}"
            ))
            kb.add(types.InlineKeyboardButton(
                "🔄 Обновить статус",
                callback_data="refresh_cabinet"
            ))
        
        bot.reply_to(message, text, parse_mode="Markdown", reply_markup=kb)
    finally:
        cur.close()
        return_db_connection(conn)

@bot.callback_query_handler(func=lambda call: call.data == "freeze_sub")
def callback_freeze_sub(call):
    user_id = call.from_user.id
    bot.answer_callback_query(call.id)
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT subscription_end FROM users WHERE user_id = %s",
            (user_id,)
        )
        result = cur.fetchone()
        if not result:
            return
        
        current_time = int(time.time())
        sub_end = result[0]
        days_left = max(0, (sub_end - current_time) // (24 * 60 * 60))
        
    finally:
        cur.close()
        return_db_connection(conn)
    
    text = (
        f"❄️ *Заморозка подписки*\n\n"
        f"⚠️ *Внимание!*\n\n"
        f"• Текущий токен подписки будет *удалён*\n"
        f"• Сохранится: `{days_left}` дней\n"
        f"• При разморозке генерируется *новый токен*\n"
        f"• Старая ссылка перестанет работать\n\n"
        f"Вы уверены?"
    )
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ Да, заморозить", callback_data="freeze_confirm"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="freeze_cancel")
    )
    
    try:
        bot.edit_message_text(
            text, call.message.chat.id, call.message.message_id,
            parse_mode="Markdown", reply_markup=kb
        )
    except:
        bot.send_message(user_id, text, parse_mode="Markdown", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data == "freeze_confirm")
def callback_freeze_confirm(call):
    user_id = call.from_user.id
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT subscription_end FROM users WHERE user_id = %s",
            (user_id,)
        )
        result = cur.fetchone()
        if not result:
            bot.answer_callback_query(call.id, "❌ Ошибка")
            return
        
        current_time = int(time.time())
        sub_end = result[0]
        days_left = max(0, (sub_end - current_time) // (24 * 60 * 60))
        
        cur.execute("""
            UPDATE users SET 
                is_frozen = 1,
                frozen_days_left = %s,
                frozen_at = %s,
                token = NULL,
                subscription_end = 0
            WHERE user_id = %s
        """, (days_left, int(time.time()), user_id))
        conn.commit()
    finally:
        cur.close()
        return_db_connection(conn)
    
    bot.answer_callback_query(call.id, "❄️ Подписка заморожена!")
    
    try:
        bot.edit_message_text(
            f"❄️ *Подписка заморожена*\n\n⏳ Сохранено: `{days_left}` дней\n\nДля разморозки нажмите кнопку в разделе 📡 *Моя подписка*",
            call.message.chat.id, call.message.message_id,
            parse_mode="Markdown"
        )
    except:
        pass

@bot.callback_query_handler(func=lambda call: call.data == "freeze_cancel")
def callback_freeze_cancel(call):
    bot.answer_callback_query(call.id, "❌ Отменено")
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass

@bot.callback_query_handler(func=lambda call: call.data == "unfreeze_sub")
def callback_unfreeze_sub(call):
    user_id = call.from_user.id
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT frozen_days_left FROM users WHERE user_id = %s",
            (user_id,)
        )
        result = cur.fetchone()
        if not result:
            bot.answer_callback_query(call.id, "❌ Ошибка")
            return
        
        frozen_days = result[0] or 0
        current_time = int(time.time())
        new_sub_end = current_time + frozen_days * 24 * 60 * 60
        new_token = generate_subscription_token()
        
        cur.execute("""
            UPDATE users SET
                is_frozen = 0,
                frozen_days_left = 0,
                frozen_at = 0,
                subscription_end = %s,
                token = %s,
                notified_3days = 0
            WHERE user_id = %s
        """, (new_sub_end, new_token, user_id))
        conn.commit()
        
        new_link = f"{BOT_BASE_URL}/sub/{new_token}"
        
    finally:
        cur.close()
        return_db_connection(conn)
    
    bot.answer_callback_query(call.id, "🔥 Подписка разморожена!")
    
    text = (
        f"🔥 *Подписка разморожена!*\n\n"
        f"✅ Активна ещё: `{frozen_days}` дней\n"
        f"🔗 Новая ссылка:\n"
        f"`{new_link}`\n\n"
        f"⚠️ Старая ссылка больше не работает!\n"
        f"Обновите подписку в клиенте."
    )
    
    try:
        bot.edit_message_text(
            text, call.message.chat.id, call.message.message_id,
            parse_mode="Markdown"
        )
    except:
        bot.send_message(user_id, text, parse_mode="Markdown")

# ==================== АВТОПОСТИНГ ====================

def autopost_scheduler():
    print("[autopost_scheduler] Запущен планировщик автопостинга")
    while True:
        try:
            config = get_autopost_config()
            if config['enabled']:
                last_post = int(get_setting('autopost_last_post', '0'))
                current_time = int(time.time())
                if current_time - last_post >= config['interval']:
                    print(f"[autopost_scheduler] Запуск автопостинга (интервал: {config['interval']}с)")
                    auto_post_keys_to_channel()
                    set_setting('autopost_last_post', str(current_time))
            time.sleep(30)
        except Exception as e:
            print(f"[autopost_scheduler] Ошибка: {e}")
            time.sleep(60)

def auto_post_keys_to_channel():
    config = get_autopost_config()
    if not config['enabled']:
        return
    keys = get_keys_from_db()
    if not keys:
        return
    channel_id = config['channel_id']
    topic_id = config['topic_id']
    
    def _check_key(key):
        match = re.search(r'@([\d\.]+):(\d+)', key)
        if not match:
            return None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((match.group(1), int(match.group(2))))
            sock.close()
            return key if result == 0 else None
        except:
            return None

    working = []
    keys_to_check = keys[:20]
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(_check_key, k): k for k in keys_to_check}
        for future in as_completed(futures):
            result = future.result()
            if result:
                working.append(result)
            if len(working) >= 5:
                for f in futures:
                    if not f.done():
                        f.cancel()
                break

    if not working:
        key_to_post = keys_to_check[0] if keys_to_check else None
    else:
        key_to_post = working[0]
    
    current_keys = get_keys_from_db()
    if key_to_post not in current_keys:
        key_to_post = current_keys[0] if current_keys else None
    
    if not key_to_post:
        return
    
    key = key_to_post
    
    latency = 0
    match = re.search(r'@([\d\.]+):(\d+)', key)
    if match:
        try:
            start = time.time()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect_ex((match.group(1), int(match.group(2))))
            sock.close()
            latency = int((time.time() - start) * 1000)
        except:
            latency = 0
    
    name = "VPN Server"
    country_emoji = "🌍"
    country_name = "Unknown"
    
    name_match = re.search(r'#([^#\s]+)$', key)
    if name_match:
        raw_name = name_match.group(1)
        try:
            decoded_name = urllib.parse.unquote(raw_name)
            decoded_name = re.sub(r'\|.*$', '', decoded_name)
            decoded_name = re.sub(r'@\w+', '', decoded_name)
            decoded_name = decoded_name.strip()
            if decoded_name:
                name = decoded_name
        except:
            pass
    
    ip_match = re.search(r'@([^:]+):(\d+)', key)
    ip = ip_match.group(1) if ip_match else "Unknown"
    
    protocol_match = re.match(r'([a-z0-9+]+)://', key, re.IGNORECASE)
    protocol = protocol_match.group(1).upper() if protocol_match else "VLESS"
    
    protocol_icons = {
        'VLESS': '🔹', 'VMESS': '🔸', 'TROJAN': '🟣', 'SS': '🟢',
        'SSR': '🟡', 'HYSTERIA': '🟠', 'TUIC': '🔵', 'WIREGUARD': '🟩',
    }
    proto_icon = protocol_icons.get(protocol, '🔹')
    
    speed = "100+ Mbps"
    
    moscow_time = datetime.now() + timedelta(hours=3)
    
    formatted = (
        f"🚀 #1 | {country_emoji} {country_name}\n\n"
        f"┌ 🏷 Название: {name}\n"
        f"├ 🔗 Протокол: {proto_icon} {protocol}\n"
        f"├ 📡 Пинг: {latency} ms\n"
        f"├ ⚡ Скорость: {speed}\n"
        f"├ 🌍 Город: {country_name}\n"
        f"└ 🏢 Провайдер: {ip}\n\n"
        f"🔑 Ключ для подключения:\n"
        f"`{key}`\n\n"
        f"⏱ Проверено: {moscow_time.strftime('%H:%M:%S')} | 🤖 @Potyjno_vpn_bot\n"
        f"🔗 @ciorsa"
    )
    
    try:
        if topic_id:
            bot.send_message(channel_id, formatted, parse_mode="Markdown", message_thread_id=topic_id)
        else:
            bot.send_message(channel_id, formatted, parse_mode="Markdown")
        
        # Атомарное удаление после успешной отправки
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            current_keys = get_keys_from_db()
            if key_to_post in current_keys:
                current_keys.remove(key_to_post)
                save_keys_to_db(current_keys)
                increment_setting('total_keys_issued', 1)
        finally:
            cur.close()
            return_db_connection(conn)
    except Exception as e:
        print(f"[autopost] Ошибка: {e}")

# ==================== ADMIN CALLBACK (ОБЪЕДИНЁННЫЙ) ====================

@bot.callback_query_handler(func=lambda call: (
    call.data.startswith('admin_') or 
    call.data.startswith('add_admin_') or
    call.data == 'edit_admin_perms'
) and not call.data.startswith('admin_keys_'))
def admin_callback(call):
    user_id = call.from_user.id
    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    data = call.data

    # ========== НАВИГАЦИЯ ==========
    if data == "admin_back":
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
        bot.send_message(user_id, "🏠 Главное меню", reply_markup=main_menu())
        bot.answer_callback_query(call.id)
        return

    if data == "admin_back_panel":
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
        role_name = get_admin_role_name(user_id)
        bot.send_message(
            user_id,
            f"🏛️ Админ панель\n\n👤 Ваша роль: {role_name}",
            reply_markup=admin_menu()
        )
        bot.answer_callback_query(call.id)
        return

    # ========== РАССЫЛКА ==========
    if data == "admin_announce":
        if not has_permission(user_id, 'announce'):
            bot.answer_callback_query(call.id, "⛔️ Нет прав")
            return
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton("📨 В ЛС", callback_data="announce_dm"),
            types.InlineKeyboardButton("📢 В каналы", callback_data="announce_channels"),
            types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back_panel")
        )
        try:
            bot.edit_message_text(
                "📢 *Рассылка*\n\nВыберите куда:",
                call.message.chat.id, call.message.message_id,
                parse_mode="Markdown", reply_markup=kb
            )
        except:
            bot.send_message(user_id, "📢 *Рассылка*\n\nВыберите куда:",
                           parse_mode="Markdown", reply_markup=kb)
        return

    # ========== УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ ==========
    if data == "admin_manage_users":
        if not has_permission(user_id, 'manage_users'):
            bot.answer_callback_query(call.id, "⛔️ Нет прав")
            return
        bot.answer_callback_query(call.id)
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT user_id FROM users ORDER BY user_id")
            users = [row[0] for row in cur.fetchall()]
        finally:
            cur.close()
            return_db_connection(conn)
        if not users:
            try:
                bot.edit_message_text("📭 Нет пользователей.",
                                     call.message.chat.id, call.message.message_id)
            except:
                bot.send_message(user_id, "📭 Нет пользователей.")
            return
        manage_cache[user_id] = {'users': users, 'filter': 'all'}
        kb = build_user_list_keyboard(users, 0, 'all')
        try:
            bot.edit_message_text(
                f"👥 Пользователи ({len(users)}):",
                call.message.chat.id, call.message.message_id,
                reply_markup=kb
            )
        except:
            bot.send_message(user_id, f"👥 Пользователи ({len(users)}):", reply_markup=kb)
        return

    # ========== УПРАВЛЕНИЕ КЛЮЧАМИ ==========
    if data == "admin_keys":
        if not has_permission(user_id, 'manage_keys'):
            bot.answer_callback_query(call.id, "⛔️ У вас нет прав на управление ключами.")
            return
        bot.answer_callback_query(call.id)
        show_keys_menu(user_id, call.message.chat.id, call.message.message_id)
        return

    # ========== АВТОПОСТИНГ ==========
    if data == "admin_autopost":
        if not has_permission(user_id, 'autopost'):
            bot.answer_callback_query(call.id, "⛔️ Нет прав")
            return
        bot.answer_callback_query(call.id)
        config = get_autopost_config()
        status = "✅ ВКЛ" if config['enabled'] else "❌ ВЫКЛ"
        text = (
            f"📡 *АВТОПОСТИНГ*\n\n"
            f"Статус: {status}\n"
            f"Интервал: {config['interval'] // 60} мин\n"
            f"Канал: {config['channel_id']}"
        )
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("📥 Загрузить ключи", callback_data="autopost_load_keys"),
            types.InlineKeyboardButton("🚀 Начать", callback_data="autopost_start"),
            types.InlineKeyboardButton("⚙️ Канал", callback_data="autopost_channel_settings"),
            types.InlineKeyboardButton("⏱ Интервал", callback_data="autopost_interval_settings"),
            types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back_panel")
        )
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                                 parse_mode="Markdown", reply_markup=kb)
        except:
            bot.send_message(user_id, text, parse_mode="Markdown", reply_markup=kb)
        return

    # ========== УПРАВЛЕНИЕ АДМИНАМИ ==========
    if data == "admin_manage_admins":
        if not has_permission(user_id, 'manage_admins'):
            bot.answer_callback_query(call.id, "⛔️ У вас нет прав на управление админами.")
            return
        bot.answer_callback_query(call.id)
        _show_admin_list_for_call(call)
        return

    if data == "edit_admin_perms":
        if not has_permission(user_id, 'manage_admins'):
            bot.answer_callback_query(call.id, "⛔️ Нет прав")
            return
        bot.answer_callback_query(call.id)
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT user_id, role FROM admins WHERE user_id != %s", (ADMIN_ID,))
            admins = cur.fetchall()
        finally:
            cur.close()
            return_db_connection(conn)
        if not admins:
            bot.send_message(user_id, "❌ Нет других админов для настройки.")
            return
        kb = types.InlineKeyboardMarkup(row_width=1)
        for admin_id_item, role in admins:
            name = get_user_display_name_cached(admin_id_item)
            kb.add(types.InlineKeyboardButton(
                f"{name} ({role})",
                callback_data=f"edit_admin_{admin_id_item}"
            ))
        kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_manage_admins"))
        try:
            bot.edit_message_text(
                "⚙️ *Выберите админа для настройки прав:*",
                call.message.chat.id, call.message.message_id,
                parse_mode="Markdown", reply_markup=kb
            )
        except:
            bot.send_message(user_id, "⚙️ *Выберите админа для настройки прав:*",
                           parse_mode="Markdown", reply_markup=kb)
        return

    if data.startswith("add_admin_role_"):
        if not has_permission(user_id, 'manage_admins'):
            bot.answer_callback_query(call.id, "⛔️ Нет прав")
            return
        if user_id in search_cache:
            del search_cache[user_id]
        role = data.split('_')[3]
        search_cache[user_id] = {
            'action': 'add_admin',
            'role': role,
            'timestamp': int(time.time())
        }
        bot.answer_callback_query(call.id, f"✅ Выбрана роль: {ROLE_PRESETS[role]['name']}")
        bot.send_message(
            user_id,
            f"👑 Выбрана роль: {ROLE_PRESETS[role]['name']}\n\n"
            "Отправьте ID или @username пользователя.",
            parse_mode="Markdown"
        )
        return

    if data == "add_admin_start":
        if not has_permission(user_id, 'manage_admins'):
            bot.answer_callback_query(call.id, "⛔️ Нет прав")
            return
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("⭐ Старший админ", callback_data="add_admin_role_senior"),
            types.InlineKeyboardButton("🔹 Младший админ", callback_data="add_admin_role_junior"),
            types.InlineKeyboardButton("🟢 Поддержка", callback_data="add_admin_role_support")
        )
        kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_manage_admins"))
        bot.send_message(
            user_id,
            "👑 *Добавление админа*\n\n"
            "Выберите роль для нового админа, затем отправьте ID или @username пользователя.",
            parse_mode="Markdown",
            reply_markup=kb
        )
        return

    # ========== СИСТЕМА БАЛЛОВ ==========
    if data == "admin_points_system":
        if not has_permission(user_id, 'points_system'):
            bot.answer_callback_query(call.id, "⛔️ Нет прав")
            return
        bot.answer_callback_query(call.id)
        _show_admin_points_system(call)
        return

    if data == "admin_points_chats":
        if not has_permission(user_id, 'points_system'):
            bot.answer_callback_query(call.id, "⛔️ Нет прав")
            return
        bot.answer_callback_query(call.id)
        _show_admin_points_chats(call)
        return

    if data == "admin_points_log":
        if not has_permission(user_id, 'points_system'):
            bot.answer_callback_query(call.id, "⛔️ Нет прав")
            return
        bot.answer_callback_query(call.id)
        _show_admin_points_log(call)
        return

    if data == "admin_points_top":
        if not has_permission(user_id, 'points_system'):
            bot.answer_callback_query(call.id, "⛔️ Нет прав")
            return
        bot.answer_callback_query(call.id)
        _show_admin_points_top(call)
        return

    if data == "admin_points_add_chat":
        if not has_permission(user_id, 'points_system'):
            bot.answer_callback_query(call.id, "⛔️ Нет прав")
            return
        bot.answer_callback_query(call.id)
        bot.send_message(
            user_id,
            "💬 Добавьте бота в нужный чат и отправьте сюда ID чата.\n\n"
            "Узнать ID чата: перешлите любое сообщение из чата боту @userinfobot\n\n"
            "Формат: `-1001234567890`"
        )
        search_cache[user_id] = {'action': 'add_points_chat', 'timestamp': int(time.time())}
        return

    if data.startswith("admin_points_toggle_"):
        if not has_permission(user_id, 'points_system'):
            bot.answer_callback_query(call.id, "⛔️ Нет прав")
            return
        try:
            chat_id_pts = int(data.replace("admin_points_toggle_", ""))
        except ValueError:
            bot.answer_callback_query(call.id, "❌ Ошибка формата")
            return
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "UPDATE points_chats SET enabled = NOT enabled WHERE chat_id = %s RETURNING enabled",
                (chat_id_pts,)
            )
            new_state = cur.fetchone()[0]
            conn.commit()
            log_admin_action(
                user_id,
                f"Переключил чат {chat_id_pts} на {'вкл' if new_state else 'выкл'}"
            )
        finally:
            cur.close()
            return_db_connection(conn)
        bot.answer_callback_query(call.id, "✅ ВКЛ" if new_state else "❌ ВЫКЛ")
        _show_admin_points_chats(call)
        return

    if data.startswith("admin_points_del_"):
        if not has_permission(user_id, 'points_system'):
            bot.answer_callback_query(call.id, "⛔️ Нет прав")
            return
        try:
            chat_id_pts = int(data.replace("admin_points_del_", ""))
        except ValueError:
            bot.answer_callback_query(call.id, "❌ Ошибка формата")
            return
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM points_chats WHERE chat_id = %s", (chat_id_pts,))
            conn.commit()
            log_admin_action(user_id, f"Удалил чат {chat_id_pts} из системы баллов")
        finally:
            cur.close()
            return_db_connection(conn)
        bot.answer_callback_query(call.id, "🗑 Удалено")
        _show_admin_points_chats(call)
        return

    # ========== АВТООБНОВЛЕНИЕ КЛЮЧЕЙ ==========
    if data == "admin_keys_auto_update":
        if not has_permission(user_id, 'manage_keys'):
            bot.answer_callback_query(call.id, "⛔️ Нет прав")
            return
        bot.answer_callback_query(call.id)
        _show_auto_update_menu(call.message.chat.id, call.message.message_id, user_id)
        return

    if data == "admin_auto_update_toggle":
        if not has_permission(user_id, 'manage_keys'):
            bot.answer_callback_query(call.id, "⛔️ Нет прав")
            return
        current = get_setting('auto_update_enabled', 'false') == 'true'
        new_val = 'false' if current else 'true'
        set_setting('auto_update_enabled', new_val)
        log_admin_action(
            user_id,
            f"Автообновление {'включено' if new_val == 'true' else 'выключено'}"
        )
        bot.answer_callback_query(call.id, "✅ ВКЛ" if new_val == 'true' else "❌ ВЫКЛ")
        _show_auto_update_menu(call.message.chat.id, call.message.message_id, user_id)
        return

    if data == "admin_auto_update_notify":
        if not has_permission(user_id, 'manage_keys'):
            bot.answer_callback_query(call.id, "⛔️ Нет прав")
            return
        current = get_setting('auto_update_notify', 'true') == 'true'
        new_val = 'false' if current else 'true'
        set_setting('auto_update_notify', new_val)
        log_admin_action(
            user_id,
            f"Уведомления автообновления {'включены' if new_val == 'true' else 'выключены'}"
        )
        bot.answer_callback_query(call.id, "🔔 ВКЛ" if new_val == 'true' else "🔕 ВЫКЛ")
        _show_auto_update_menu(call.message.chat.id, call.message.message_id, user_id)
        return

    if data == "admin_auto_update_now":
        if not has_permission(user_id, 'manage_keys'):
            bot.answer_callback_query(call.id, "⛔️ Нет прав")
            return
        proxy_urls = get_setting('proxy_sub_urls', '')
        proxy_url = get_setting('proxy_sub_url', '')
        if not proxy_urls and not proxy_url:
            bot.answer_callback_query(call.id, "❌ Нет прокси ссылок")
            return
        bot.answer_callback_query(call.id, "⏳ Запускаю обновление...")
        log_admin_action(user_id, "Запущено ручное автообновление ключей")

        def run():
            _do_auto_update_keys()
            try:
                _show_auto_update_menu(call.message.chat.id, call.message.message_id, user_id)
            except:
                pass

        t = threading.Thread(target=run)
        t.daemon = True
        t.start()
        return

    # ========== ЛОГИ ==========
    if data == "admin_view_logs":
        if not has_permission(user_id, 'view_logs'):
            bot.answer_callback_query(call.id, "⛔️ Нет прав на просмотр логов")
            return
        bot.answer_callback_query(call.id)
        _show_admin_logs(call)
        return

    bot.answer_callback_query(call.id)

# ==================== ПРОСМОТР ЛОГОВ АДМИНОВ ====================

def _show_admin_logs(call):
    user_id = call.from_user.id
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT admin_name, action, target_name, details, created_at
            FROM admin_logs
            ORDER BY created_at DESC
            LIMIT 20
        """)
        logs = cur.fetchall()
    finally:
        cur.close()
        return_db_connection(conn)
    
    if not logs:
        text = "📋 *Логи админов*\n\nПусто"
    else:
        text = "📋 *Последние 20 действий:*\n\n"
        for admin_name, action, target_name, details, created_at in logs:
            time_str = datetime.fromtimestamp(created_at).strftime("%d.%m %H:%M")
            target = f" → {target_name}" if target_name else ""
            text += f"🕐 {time_str} | *{admin_name}* {action}{target}\n"
            if details:
                text += f"  📎 {details}\n"
            text += "\n"
    
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("🔄 Обновить", callback_data="admin_view_logs"),
        types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back_panel")
    )
    
    try:
        if len(text) > 4000:
            text = text[:3950] + "\n…"
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=kb)
    except:
        bot.send_message(user_id, text, parse_mode="Markdown", reply_markup=kb)

# ==================== СИСТЕМА БАЛЛОВ - АДМИНКА ====================

def _show_admin_points_system(call):
    user_id = call.from_user.id
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM points_chats WHERE enabled = TRUE")
        active_chats = cur.fetchone()[0]
        
        cur.execute("SELECT SUM(points) FROM users")
        total_points = cur.fetchone()[0] or 0
        
        cur.execute("SELECT COUNT(*) FROM chat_messages_log")
        total_logs = cur.fetchone()[0] or 0
        
    finally:
        cur.close()
        return_db_connection(conn)
    
    text = (
        f"🪙 *Система баллов*\n\n"
        f"📊 Активных чатов: `{active_chats}`\n"
        f"🪙 Всего баллов выдано: `{total_points:,}`\n"
        f"💬 Сообщений в логах: `{total_logs:,}`\n\n"
        f"*Коэффициент:* 1000 баллов = 1 день"
    )
    
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("💬 Управление чатами", callback_data="admin_points_chats"),
        types.InlineKeyboardButton("📋 Лог сообщений", callback_data="admin_points_log"),
        types.InlineKeyboardButton("🏆 Топ по баллам", callback_data="admin_points_top"),
        types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back_panel")
    )
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                             parse_mode="Markdown", reply_markup=kb)
    except:
        bot.send_message(user_id, text, parse_mode="Markdown", reply_markup=kb)

def _show_admin_points_chats(call):
    user_id = call.from_user.id
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT chat_id, chat_name, enabled FROM points_chats")
        chats = cur.fetchall()
    finally:
        cur.close()
        return_db_connection(conn)
    
    text = "💬 *Чаты для баллов*\n\n"
    if chats:
        for chat_id, name, enabled in chats:
            icon = "✅" if enabled else "❌"
            text += f"{icon} {name or chat_id} (`{chat_id}`)\n"
    else:
        text += "Нет добавленных чатов"
    
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("➕ Добавить чат", callback_data="admin_points_add_chat"))
    
    for chat_id, name, enabled in chats:
        toggle = "❌ Выкл" if enabled else "✅ Вкл"
        kb.add(types.InlineKeyboardButton(
            f"{toggle} {name or chat_id}",
            callback_data=f"admin_points_toggle_{chat_id}"
        ))
        kb.add(types.InlineKeyboardButton(
            f"🗑 Удалить {name or chat_id}",
            callback_data=f"admin_points_del_{chat_id}"
        ))
    
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_points_system"))
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                             parse_mode="Markdown", reply_markup=kb)
    except:
        bot.send_message(user_id, text, parse_mode="Markdown", reply_markup=kb)

def _show_admin_points_log(call):
    user_id = call.from_user.id
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT l.user_id, l.message_text, l.created_at, l.chat_id
            FROM chat_messages_log l
            ORDER BY l.created_at DESC
            LIMIT 10
        """)
        logs = cur.fetchall()
    finally:
        cur.close()
        return_db_connection(conn)
    
    text = "📋 *Последние сообщения:*\n\n"
    for uid, msg_text, created_at, chat_id in logs:
        name = get_user_display_name_cached(uid)
        time_str = datetime.fromtimestamp(created_at).strftime("%d.%m %H:%M")
        text += f"👤 {name} | {time_str}\n"
        text += f"💬 {msg_text[:100]}{'...' if len(msg_text) > 100 else ''}\n"
        text += "─────────────\n"
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🔄 Обновить", callback_data="admin_points_log"),
        types.InlineKeyboardButton("🔙 Назад", callback_data="admin_points_system")
    )
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                             parse_mode="Markdown", reply_markup=kb)
    except:
        bot.send_message(user_id, text, parse_mode="Markdown", reply_markup=kb)

def _show_admin_points_top(call):
    user_id = call.from_user.id
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT user_id, points FROM users 
            WHERE points > 0 
            ORDER BY points DESC 
            LIMIT 10
        """)
        top = cur.fetchall()
    finally:
        cur.close()
        return_db_connection(conn)
    
    text = "🏆 *Топ по баллам:*\n\n"
    medals = ['🥇', '🥈', '🥉']
    for i, (uid, pts) in enumerate(top):
        name = get_user_display_name_cached(uid)
        icon = medals[i] if i < 3 else f"{i+1}."
        days = get_days_available(pts)
        text += f"{icon} {name} — `{pts:,}` баллов ({days} дн.)\n"
    
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_points_system"))
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                             parse_mode="Markdown", reply_markup=kb)
    except:
        bot.send_message(user_id, text, parse_mode="Markdown", reply_markup=kb)

# ==================== АВТООБНОВЛЕНИЕ - ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def _show_auto_update_menu(chat_id, message_id, user_id):
    enabled = get_setting('auto_update_enabled', 'false') == 'true'
    interval = get_setting('auto_update_interval', '3')
    notify = get_setting('auto_update_notify', 'true') == 'true'
    last = int(get_setting('auto_update_last', '0'))
    
    proxy_urls = get_setting('proxy_sub_urls', '')
    url_count = len([u for u in proxy_urls.split('|||') if u]) if proxy_urls else 0
    if url_count == 0 and get_setting('proxy_sub_url', ''):
        url_count = 1
    
    status = "✅ ВКЛ" if enabled else "❌ ВЫКЛ"
    notify_status = "✅ ВКЛ" if notify else "❌ ВЫКЛ"
    last_str = datetime.fromtimestamp(last).strftime("%d.%m в %H:%M") if last else "Никогда"
    
    text = (
        f"🔄 *Автообновление ключей*\n\n"
        f"📊 Статус: {status}\n"
        f"⏱ Интервал: каждые {interval} ч.\n"
        f"🔗 Прокси ссылок: {url_count}\n"
        f"🔔 Уведомления: {notify_status}\n"
        f"🕐 Последнее: {last_str}"
    )
    
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton(
            "❌ Выключить" if enabled else "✅ Включить",
            callback_data="admin_auto_update_toggle"
        ),
        types.InlineKeyboardButton(
            f"🔔 Уведомления: {'ВЫКЛ' if notify else 'ВКЛ'}",
            callback_data="admin_auto_update_notify"
        ),
        types.InlineKeyboardButton("▶️ Запустить сейчас", callback_data="admin_auto_update_now"),
        types.InlineKeyboardButton("🔙 Назад", callback_data="admin_keys_back")
    )
    
    try:
        bot.edit_message_text(text, chat_id, message_id, parse_mode="Markdown", reply_markup=kb)
    except:
        bot.send_message(user_id, text, parse_mode="Markdown", reply_markup=kb)

# ==================== ОБРАБОТЧИКИ ГРУППОВЫХ СООБЩЕНИЙ ====================

_user_blocked_cache = {}
_user_blocked_cache_lock = Lock()
USER_BLOCKED_CACHE_TTL = 3600

def is_user_blocked_bot(user_id):
    current_time = int(time.time())
    
    with _user_blocked_cache_lock:
        cached = _user_blocked_cache.get(user_id, {})
        if cached.get('timestamp', 0) > current_time - USER_BLOCKED_CACHE_TTL:
            return cached.get('blocked', False)
    
    try:
        bot.send_chat_action(user_id, 'typing')
        blocked = False
    except Exception as e:
        if 'blocked' in str(e).lower() or 'deactivated' in str(e).lower():
            blocked = True
        else:
            blocked = False
    
    with _user_blocked_cache_lock:
        _user_blocked_cache[user_id] = {
            'blocked': blocked,
            'timestamp': current_time
        }
    
    return blocked

@bot.message_handler(func=lambda m: m.chat.type in ['group', 'supergroup'])
def handle_group_message(message):
    # Игнорируем команды — их обрабатывают отдельные хэндлеры
    if message.text and message.text.startswith('/'):
        return
    
    user_id = message.from_user.id
    chat_id = message.chat.id
    current_time = int(time.time())
    
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute(
            "SELECT enabled, points_per_message FROM points_chats WHERE chat_id = %s",
            (chat_id,)
        )
        chat = cur.fetchone()
        if not chat or not chat[0]:
            return
        
        points_per_msg = chat[1]
        
        cur.execute(
            "SELECT user_id, is_blocked FROM users WHERE user_id = %s",
            (user_id,)
        )
        user = cur.fetchone()
        if not user or user[1] == 1:
            return
        
        if is_user_blocked_bot(user_id):
            return
        
        cur.execute(
            "SELECT last_message FROM chat_activity WHERE user_id = %s AND chat_id = %s",
            (user_id, chat_id)
        )
        activity = cur.fetchone()
        
        if activity and current_time - activity[0] < 3:
            return
        
        conn.autocommit = False
        
        cur.execute("""
            INSERT INTO chat_activity (user_id, chat_id, messages_count, last_message)
            VALUES (%s, %s, 1, %s)
            ON CONFLICT (user_id, chat_id) DO UPDATE SET
                messages_count = chat_activity.messages_count + 1,
                last_message = %s
        """, (user_id, chat_id, current_time, current_time))
        
        cur.execute(
            "UPDATE users SET points = points + %s WHERE user_id = %s",
            (points_per_msg, user_id)
        )
        
        if message.text:
            log_text = message.text[:500]
            cur.execute("""
                INSERT INTO chat_messages_log 
                (user_id, chat_id, message_text, message_id, created_at)
                VALUES (%s, %s, %s, %s, %s)
            """, (user_id, chat_id, log_text, message.message_id, current_time))
            
            cur.execute("""
                DELETE FROM chat_messages_log 
                WHERE chat_id = %s AND id NOT IN (
                    SELECT id FROM chat_messages_log 
                    WHERE chat_id = %s 
                    ORDER BY created_at DESC 
                    LIMIT 1000
                )
            """, (chat_id, chat_id))
        
        conn.commit()
        
    except Exception as e:
        print(f"[group_message] Ошибка: {e}")
        if conn:
            conn.rollback()
    finally:
        if cur:
            cur.close()
        if conn:
            conn.autocommit = True
            return_db_connection(conn)

# ==================== КОМАНДЫ БОНУС, ТОП, РАНГ ====================

DAILY_BONUS_POINTS = 50
DAILY_BONUS_COOLDOWN = 86400

@bot.message_handler(commands=['bonus'])
def cmd_bonus(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    current_time = int(time.time())

    if message.chat.type == 'private':
        bot.reply_to(message, "❌ Команда доступна только в групповых чатах.")
        return

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT enabled FROM points_chats WHERE chat_id = %s",
            (chat_id,)
        )
        chat = cur.fetchone()
        if not chat or not chat[0]:
            bot.reply_to(message, "❌ В этом чате система баллов не активна.")
            return

        cur.execute(
            "SELECT user_id, is_blocked FROM users WHERE user_id = %s",
            (user_id,)
        )
        user = cur.fetchone()
        if not user:
            bot.reply_to(message, "❌ Сначала зарегистрируйся в боте → @potyjno_vpn_bot")
            return
        if user[1] == 1:
            bot.reply_to(message, "🚫 Ты заблокирован.")
            return

        if is_user_blocked_bot(user_id):
            bot.reply_to(
                message,
                f"❌ {message.from_user.first_name}, разблокируй бота → @potyjno_vpn_bot"
            )
            return

        cur.execute("""
            SELECT daily_bonus_claimed
            FROM chat_activity
            WHERE user_id = %s AND chat_id = %s
        """, (user_id, chat_id))
        activity = cur.fetchone()

        if activity and current_time - activity[0] < DAILY_BONUS_COOLDOWN:
            remaining = DAILY_BONUS_COOLDOWN - (current_time - activity[0])
            hours = remaining // 3600
            minutes = (remaining % 3600) // 60
            bot.reply_to(
                message,
                f"⏳ Следующий бонус через {hours} ч. {minutes} мин."
            )
            return

        cur.execute("""
            INSERT INTO chat_activity (user_id, chat_id, daily_bonus_claimed)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, chat_id) DO UPDATE SET daily_bonus_claimed = %s
        """, (user_id, chat_id, current_time, current_time))

        cur.execute(
            "UPDATE users SET points = points + %s WHERE user_id = %s RETURNING points",
            (DAILY_BONUS_POINTS, user_id)
        )
        new_points = cur.fetchone()[0]
        conn.commit()

        rank = get_rank(new_points)
        days_available = get_days_available(new_points)

        bot.reply_to(
            message,
            f"🎁 *+{DAILY_BONUS_POINTS} баллов!*\n\n"
            f"🪙 Всего: `{new_points:,}`\n"
            f"{rank['name']}\n"
            f"🎯 Можно обменять: `{days_available}` дн.\n\n"
            f"💡 Обмен → @potyjno_vpn_bot",
            parse_mode="Markdown"
        )

    finally:
        cur.close()
        return_db_connection(conn)

@bot.message_handler(commands=['top'])
def cmd_top_chat(message):
    chat_id = message.chat.id

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if message.chat.type == 'private':
            cur.execute("""
                SELECT user_id, points FROM users
                WHERE points > 0
                ORDER BY points DESC
                LIMIT 10
            """)
            rows = cur.fetchall()
            medals = ['🥇', '🥈', '🥉']
            text = "🏆 *Топ по баллам (все пользователи)*\n\n"
            
            for i, row in enumerate(rows):
                uid = row[0]
                points = row[1]
                rank = get_rank(points)
                name = get_user_display_name_cached(uid)
                icon = medals[i] if i < 3 else f"{i+1}."
                text += f"{icon} {name}\n{rank['name']} • `{points:,}` баллов\n\n"
            
            bot.reply_to(message, text, parse_mode="Markdown")
            return
        else:
            cur.execute("""
                SELECT ca.user_id, u.points, ca.messages_count
                FROM chat_activity ca
                JOIN users u ON u.user_id = ca.user_id
                WHERE ca.chat_id = %s AND u.is_blocked = 0
                ORDER BY ca.messages_count DESC
                LIMIT 10
            """, (chat_id,))

            rows = cur.fetchall()

            if not rows:
                bot.reply_to(message, "📭 Пока никто не набрал баллов.")
                return

            medals = ['🥇', '🥈', '🥉']
            text = f"🏆 *Топ активных*\n\n"

            for i, row in enumerate(rows):
                uid = row[0]
                points = row[1]
                msg_count = row[2] if len(row) > 2 else 0
                rank = get_rank(points)

                try:
                    member = bot.get_chat_member(chat_id, uid)
                    name = member.user.first_name or str(uid)
                    if member.user.username:
                        name = f"@{member.user.username}"
                except:
                    name = str(uid)

                icon = medals[i] if i < 3 else f"{i+1}."
                text += f"{icon} {name}\n{rank['name']} • 💬 {msg_count:,} сообщ. • 🪙 {points:,}\n\n"

            user_id = message.from_user.id
            cur.execute("""
                SELECT COUNT(*) + 1 FROM chat_activity ca
                JOIN users u ON u.user_id = ca.user_id
                WHERE ca.chat_id = %s 
                AND ca.messages_count > (
                    SELECT COALESCE(messages_count, 0) 
                    FROM chat_activity 
                    WHERE user_id = %s AND chat_id = %s
                )
                AND u.is_blocked = 0
            """, (chat_id, user_id, chat_id))
            my_rank = cur.fetchone()[0]

            cur.execute("""
                SELECT messages_count FROM chat_activity
                WHERE user_id = %s AND chat_id = %s
            """, (user_id, chat_id))
            my_msgs = cur.fetchone()
            my_msgs = my_msgs[0] if my_msgs else 0

            text += f"─────────────\n"
            text += f"👤 Ты: #{my_rank} • 💬 {my_msgs:,} сообщ."

            bot.reply_to(message, text, parse_mode="Markdown")

    finally:
        cur.close()
        return_db_connection(conn)

@bot.message_handler(commands=['rank'])
def cmd_rank(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT points, is_blocked FROM users WHERE user_id = %s",
            (user_id,)
        )
        result = cur.fetchone()
        if not result:
            bot.reply_to(message, "❌ Сначала зарегистрируйся → @potyjno_vpn_bot")
            return

        points, blocked = result
        points = points or 0

        if blocked:
            bot.reply_to(message, "🚫 Ты заблокирован.")
            return

        rank = get_rank(points)
        days_available = get_days_available(points)

        current_rank_idx = RANKS.index(rank)
        next_rank = RANKS[current_rank_idx + 1] if current_rank_idx < len(RANKS) - 1 else None

        if message.chat.type != 'private':
            cur.execute("""
                SELECT messages_count FROM chat_activity
                WHERE user_id = %s AND chat_id = %s
            """, (user_id, chat_id))
            my_msgs = cur.fetchone()
            my_msgs = my_msgs[0] if my_msgs else 0

            cur.execute("""
                SELECT COUNT(*) + 1 FROM chat_activity ca
                JOIN users u ON u.user_id = ca.user_id
                WHERE ca.chat_id = %s
                AND ca.messages_count > %s
                AND u.is_blocked = 0
            """, (chat_id, my_msgs))
            my_position = cur.fetchone()[0]
            position_text = f"📊 Позиция в чате: #{my_position}\n💬 Сообщений: `{my_msgs:,}`\n"
        else:
            position_text = ""

        text = (
            f"👤 *Твой профиль*\n\n"
            f"{rank['name']}\n"
            f"🪙 Баллов: `{points:,}`\n"
            f"{position_text}"
            f"🎁 Можно обменять: `{days_available}` дн.\n"
            f"💰 Курс: `{rank['cost']}` баллов = 1 день\n"
        )

        if next_rank:
            needed = next_rank['min'] - points
            text += f"\n⬆️ До *{next_rank['name']}*: `{needed:,}` баллов"
            text += f"\n💡 Новый курс: `{next_rank['cost']}` баллов = 1 день"

        text += f"\n\n🔄 Обмен баллов → @potyjno_vpn_bot"

        bot.reply_to(message, text, parse_mode="Markdown")

    finally:
        cur.close()
        return_db_connection(conn)

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ МОДЕРАЦИИ ====================

def parse_duration(text):
    if text in ('permanent', 'навсегда', '0'):
        return None
    match = re.match(r'^(\d+)(s|m|h|d)$', text.lower())
    if not match:
        return None
    value, unit = int(match.group(1)), match.group(2)
    multipliers = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}
    return value * multipliers[unit]

def is_chat_admin(user_id, chat_id):
    # Владелец бота и его админы с доступом к панели — имеют доступ везде
    if user_id == ADMIN_ID:
        return True
    if is_admin(user_id) and has_permission(user_id, 'admin_panel'):
        return True
    # Владелец или администратор чата в Telegram
    try:
        member = bot.get_chat_member(chat_id, user_id)
        if member.status in ['administrator', 'creator']:
            return True
    except:
        pass
    # Назначен через /chatadmin
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT user_id FROM chat_admins WHERE user_id = %s AND chat_id = %s",
            (user_id, chat_id)
        )
        return cur.fetchone() is not None
    finally:
        cur.close()
        return_db_connection(conn)


def is_chat_owner(user_id, chat_id):
    # Владелец бота — владелец всего
    if user_id == ADMIN_ID:
        return True
    # Админ бота с доступом к панели
    if is_admin(user_id) and has_permission(user_id, 'admin_panel'):
        return True
    # Реальный владелец чата в Telegram
    try:
        member = bot.get_chat_member(chat_id, user_id)
        return member.status == 'creator'
    except:
        return False

def _get_user_from_message(message):
    if message.reply_to_message:
        return message.reply_to_message.from_user.id, message.reply_to_message.from_user.first_name
    text = message.text or ''
    parts = text.split(None, 2)
    if len(parts) < 2:
        return None, None
    target_id = get_user_id_from_input(parts[1])
    return target_id, str(target_id) if target_id else None

WARN_LIMIT = 3

# ==================== КАСТОМНОЕ ПРИВЕТСТВИЕ ====================

@bot.message_handler(commands=['welcome'], func=lambda m: m.chat.type in ['group', 'supergroup'])
def cmd_welcome_info(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    try:
        member = bot.get_chat_member(chat_id, user_id)
        if member.status not in ['administrator', 'creator']:
            bot.reply_to(message, "⛔️ Только для администраторов чата.")
            return
    except:
        return

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT welcome_text, welcome_enabled FROM chat_settings WHERE chat_id = %s", (chat_id,))
        result = cur.fetchone()
    finally:
        cur.close()
        return_db_connection(conn)

    if not result or not result[0]:
        text = (
            "ℹ️ *Приветствие*\n\n"
            "Сейчас используется стандартное приветствие.\n\n"
            "Команды:\n"
            "`/setwelcome текст` — установить своё\n"
            "`/welcomeoff` — отключить\n"
            "`/welcomeon` — включить\n\n"
            "Переменные: `{name}`, `{chat}`, `{id}`"
        )
    else:
        welcome_text, enabled = result
        status = "✅ Включено" if enabled else "❌ Отключено"
        text = (
            f"ℹ️ *Приветствие* — {status}\n\n"
            f"📝 Текущий текст:\n`{welcome_text}`\n\n"
            "Команды:\n"
            "`/setwelcome текст` — изменить\n"
            "`/welcomeoff` — отключить\n"
            "`/welcomeon` — включить"
        )
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['setwelcome'], func=lambda m: m.chat.type in ['group', 'supergroup'])
def cmd_setwelcome(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    try:
        member = bot.get_chat_member(chat_id, user_id)
        if member.status not in ['administrator', 'creator']:
            bot.reply_to(message, "⛔️ Только для администраторов чата.")
            return
    except:
        return

    text = message.text.strip()
    parts = text.split(None, 1)
    if len(parts) < 2:
        bot.reply_to(message,
            "❌ Использование: `/setwelcome текст`\n\n"
            "Переменные:\n"
            "`{name}` — имя пользователя\n"
            "`{chat}` — название чата\n"
            "`{id}` — ID пользователя\n\n"
            "Пример: `/setwelcome Привет, {name}! Добро пожаловать в {chat}!`",
            parse_mode="Markdown"
        )
        return

    welcome_text = parts[1]
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO chat_settings (chat_id, welcome_text, welcome_enabled)
            VALUES (%s, %s, TRUE)
            ON CONFLICT (chat_id) DO UPDATE SET welcome_text = %s, welcome_enabled = TRUE
        """, (chat_id, welcome_text, welcome_text))
        conn.commit()
    finally:
        cur.close()
        return_db_connection(conn)

    preview = welcome_text.format(
        name=message.from_user.first_name or "Иван",
        chat=message.chat.title or "чат",
        id=message.from_user.id
    )
    bot.reply_to(message,
        f"✅ Приветствие сохранено!\n\n"
        f"👁 *Превью:*\n{preview}",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=['welcomeoff'], func=lambda m: m.chat.type in ['group', 'supergroup'])
def cmd_welcomeoff(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    try:
        member = bot.get_chat_member(chat_id, user_id)
        if member.status not in ['administrator', 'creator']:
            bot.reply_to(message, "⛔️ Только для администраторов чата.")
            return
    except:
        return

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO chat_settings (chat_id, welcome_enabled)
            VALUES (%s, FALSE)
            ON CONFLICT (chat_id) DO UPDATE SET welcome_enabled = FALSE
        """, (chat_id,))
        conn.commit()
    finally:
        cur.close()
        return_db_connection(conn)
    bot.reply_to(message, "✅ Приветствие отключено.")

@bot.message_handler(commands=['welcomeon'], func=lambda m: m.chat.type in ['group', 'supergroup'])
def cmd_welcomeon(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    try:
        member = bot.get_chat_member(chat_id, user_id)
        if member.status not in ['administrator', 'creator']:
            bot.reply_to(message, "⛔️ Только для администраторов чата.")
            return
    except:
        return

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO chat_settings (chat_id, welcome_enabled)
            VALUES (%s, TRUE)
            ON CONFLICT (chat_id) DO UPDATE SET welcome_enabled = TRUE
        """, (chat_id,))
        conn.commit()
    finally:
        cur.close()
        return_db_connection(conn)
    bot.reply_to(message, "✅ Приветствие включено.")

# ==================== МОДЕРАЦИЯ ЧАТОВ ====================

@bot.message_handler(commands=['warn'], func=lambda m: m.chat.type in ['group', 'supergroup'])
def cmd_warn(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    if not is_chat_admin(user_id, chat_id):
        bot.reply_to(message, "⛔️ Только для администраторов.")
        return

    target_id, target_name = _get_user_from_message(message)
    if not target_id:
        bot.reply_to(message, "❌ Укажите пользователя: `/warn @user причина` или ответьте на сообщение", parse_mode="Markdown")
        return

    if target_id == ADMIN_ID or is_chat_owner(target_id, chat_id):
        bot.reply_to(message, "⛔️ Нельзя варнить владельца.")
        return

    text = message.text or ''
    parts = text.split(None, 2 if not message.reply_to_message else 1)
    reason = parts[-1] if len(parts) > (1 if message.reply_to_message else 2) else "Не указана"

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO chat_warns (user_id, chat_id, reason, warned_by, warned_at) VALUES (%s, %s, %s, %s, %s)",
            (target_id, chat_id, reason, user_id, int(time.time()))
        )
        conn.commit()
        cur.execute("SELECT COUNT(*) FROM chat_warns WHERE user_id = %s AND chat_id = %s", (target_id, chat_id))
        warn_count = cur.fetchone()[0]
    finally:
        cur.close()
        return_db_connection(conn)

    name = get_user_display_name_cached(target_id)

    if warn_count >= WARN_LIMIT:
        try:
            bot.ban_chat_member(chat_id, target_id)
            bot.reply_to(message,
                f"🚫 *{name}* получил {warn_count}/{WARN_LIMIT} варнов и *забанен*!\n"
                f"📋 Причина последнего: {reason}",
                parse_mode="Markdown"
            )
        except Exception as e:
            bot.reply_to(message, f"⚠️ Варн выдан, но бан не удался: {e}")
    else:
        bot.reply_to(message,
            f"⚠️ *{name}* получил варн [{warn_count}/{WARN_LIMIT}]\n"
            f"📋 Причина: {reason}",
            parse_mode="Markdown"
        )

@bot.message_handler(commands=['unwarn'], func=lambda m: m.chat.type in ['group', 'supergroup'])
def cmd_unwarn(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    if not is_chat_admin(user_id, chat_id):
        bot.reply_to(message, "⛔️ Только для администраторов.")
        return

    target_id, _ = _get_user_from_message(message)
    if not target_id:
        bot.reply_to(message, "❌ Укажите пользователя.")
        return

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            DELETE FROM chat_warns WHERE id = (
                SELECT id FROM chat_warns
                WHERE user_id = %s AND chat_id = %s
                ORDER BY warned_at DESC LIMIT 1
            )
        """, (target_id, chat_id))
        conn.commit()
        cur.execute("SELECT COUNT(*) FROM chat_warns WHERE user_id = %s AND chat_id = %s", (target_id, chat_id))
        remaining = cur.fetchone()[0]
    finally:
        cur.close()
        return_db_connection(conn)

    name = get_user_display_name_cached(target_id)
    bot.reply_to(message, f"✅ У *{name}* снят 1 варн. Осталось: {remaining}/{WARN_LIMIT}", parse_mode="Markdown")

@bot.message_handler(commands=['warns'], func=lambda m: m.chat.type in ['group', 'supergroup'])
def cmd_warns(message):
    chat_id = message.chat.id
    target_id, _ = _get_user_from_message(message)

    if not target_id:
        target_id = message.from_user.id

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT reason, warned_at FROM chat_warns
            WHERE user_id = %s AND chat_id = %s
            ORDER BY warned_at DESC
        """, (target_id, chat_id))
        warns = cur.fetchall()
    finally:
        cur.close()
        return_db_connection(conn)

    name = get_user_display_name_cached(target_id)
    if not warns:
        bot.reply_to(message, f"✅ У *{name}* нет варнов.", parse_mode="Markdown")
        return

    text = f"⚠️ *Варны {name}* [{len(warns)}/{WARN_LIMIT}]:\n\n"
    for reason, warned_at in warns:
        time_str = datetime.fromtimestamp(warned_at).strftime("%d.%m.%Y %H:%M")
        text += f"• {time_str} — {reason}\n"
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['mute'], func=lambda m: m.chat.type in ['group', 'supergroup'])
def cmd_mute(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    if not is_chat_admin(user_id, chat_id):
        bot.reply_to(message, "⛔️ Только для администраторов.")
        return

    target_id, _ = _get_user_from_message(message)
    if not target_id:
        bot.reply_to(message, "❌ Использование: `/mute @user 1h причина`\nВремя: `10m`, `1h`, `1d`, `permanent`", parse_mode="Markdown")
        return

    if target_id == ADMIN_ID or is_chat_owner(target_id, chat_id):
        bot.reply_to(message, "⛔️ Нельзя замутить владельца.")
        return

    text = message.text or ''
    if message.reply_to_message:
        parts = text.split(None, 2)
        duration_str = parts[1] if len(parts) > 1 else 'permanent'
        reason = parts[2] if len(parts) > 2 else "Не указана"
    else:
        parts = text.split(None, 3)
        duration_str = parts[2] if len(parts) > 2 else 'permanent'
        reason = parts[3] if len(parts) > 3 else "Не указана"

    duration = parse_duration(duration_str)
    until = int(time.time()) + duration if duration else 0

    try:
        until_date = until if until else None
        bot.restrict_chat_member(
            chat_id, target_id,
            until_date=until_date,
            permissions=types.ChatPermissions(
                can_send_messages=False,
                can_send_media_messages=False,
                can_send_other_messages=False
            )
        )
    except Exception as e:
        bot.reply_to(message, f"❌ Не удалось замутить: {e}")
        return

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO chat_mutes (user_id, chat_id, until, reason)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, chat_id) DO UPDATE SET until = %s, reason = %s
        """, (target_id, chat_id, until, reason, until, reason))
        conn.commit()
    finally:
        cur.close()
        return_db_connection(conn)

    name = get_user_display_name_cached(target_id)
    duration_text = f"на {duration_str}" if duration else "навсегда"
    bot.reply_to(message,
        f"🔇 *{name}* замучен {duration_text}\n📋 Причина: {reason}",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=['unmute'], func=lambda m: m.chat.type in ['group', 'supergroup'])
def cmd_unmute(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    if not is_chat_admin(user_id, chat_id):
        bot.reply_to(message, "⛔️ Только для администраторов.")
        return

    target_id, _ = _get_user_from_message(message)
    if not target_id:
        bot.reply_to(message, "❌ Укажите пользователя.")
        return

    try:
        bot.restrict_chat_member(
            chat_id, target_id,
            permissions=types.ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True
            )
        )
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")
        return

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM chat_mutes WHERE user_id = %s AND chat_id = %s", (target_id, chat_id))
        conn.commit()
    finally:
        cur.close()
        return_db_connection(conn)

    name = get_user_display_name_cached(target_id)
    bot.reply_to(message, f"🔊 *{name}* размучен.", parse_mode="Markdown")

@bot.message_handler(commands=['ban'], func=lambda m: m.chat.type in ['group', 'supergroup'])
def cmd_ban(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    if not is_chat_admin(user_id, chat_id):
        bot.reply_to(message, "⛔️ Только для администраторов.")
        return

    target_id, _ = _get_user_from_message(message)
    if not target_id:
        bot.reply_to(message, "❌ Использование: `/ban @user 1d причина`\nВремя: `1h`, `7d`, `permanent`", parse_mode="Markdown")
        return

    if target_id == ADMIN_ID or is_chat_owner(target_id, chat_id):
        bot.reply_to(message, "⛔️ Нельзя забанить владельца.")
        return

    text = message.text or ''
    if message.reply_to_message:
        parts = text.split(None, 2)
        duration_str = parts[1] if len(parts) > 1 else 'permanent'
        reason = parts[2] if len(parts) > 2 else "Не указана"
    else:
        parts = text.split(None, 3)
        duration_str = parts[2] if len(parts) > 2 else 'permanent'
        reason = parts[3] if len(parts) > 3 else "Не указана"

    duration = parse_duration(duration_str)
    until = int(time.time()) + duration if duration else 0

    try:
        until_date = until if until else None
        bot.ban_chat_member(chat_id, target_id, until_date=until_date)
    except Exception as e:
        bot.reply_to(message, f"❌ Не удалось забанить: {e}")
        return

    name = get_user_display_name_cached(target_id)
    duration_text = f"на {duration_str}" if duration else "навсегда"
    bot.reply_to(message,
        f"🚫 *{name}* забанен {duration_text}\n📋 Причина: {reason}",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=['unban'], func=lambda m: m.chat.type in ['group', 'supergroup'])
def cmd_unban(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    if not is_chat_admin(user_id, chat_id):
        bot.reply_to(message, "⛔️ Только для администраторов.")
        return

    target_id, _ = _get_user_from_message(message)
    if not target_id:
        bot.reply_to(message, "❌ Укажите пользователя.")
        return

    try:
        bot.unban_chat_member(chat_id, target_id, only_if_banned=True)
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")
        return

    name = get_user_display_name_cached(target_id)
    bot.reply_to(message, f"✅ *{name}* разбанен.", parse_mode="Markdown")

@bot.message_handler(commands=['modhelp'], func=lambda m: m.chat.type in ['group', 'supergroup'])
def cmd_modhelp(message):
    text = (
        "🛡 *Система модерации*\n\n"
        "*Варны (лимит 3 → автобан):*\n"
        "`/warn @user причина` — выдать варн\n"
        "`/unwarn @user` — снять последний варн\n"
        "`/warns @user` — посмотреть варны\n\n"
        "*Мут:*\n"
        "`/mute @user 10m причина` — замутить\n"
        "`/unmute @user` — размутить\n"
        "_Время: `10m`, `1h`, `1d`, `permanent`_\n\n"
        "*Бан:*\n"
        "`/ban @user 7d причина` — забанить\n"
        "`/unban @user` — разбанить\n"
        "_Время: `1h`, `7d`, `permanent`_\n\n"
        "*Чат-администраторы (только владелец чата):*\n"
        "`/chatadmin @user` — назначить чат-админа\n"
        "`/chatdeadmin @user` — снять чат-админа\n"
        "`/chatadmins` — список чат-админов\n\n"
        "ℹ️ Владелец чата определяется автоматически при добавлении бота.\n"
        "👑 Владелец и админы бота имеют доступ ко всем командам во всех чатах.\n\n"
        "*Приветствие:*\n"
        "`/welcome` — посмотреть текущее\n"
        "`/setwelcome текст` — задать приветствие\n"
        "`/welcomeoff` — отключить\n"
        "`/welcomeon` — включить\n"
        "_Переменные: `{name}`, `{chat}`, `{id}`_\n\n"
        "*Топ и баллы:*\n"
        "`/top` — топ активных участников\n"
        "`/rank` — ваш ранг и баллы\n"
        "`/bonus` — ежедневный бонус\n\n"
        "⚠️ Все команды — ответом на сообщение или `@username`\n"
        "👑 Владелец бота защищён от всех санкций"
    )
    bot.reply_to(message, text, parse_mode="Markdown")

# ==================== НОВЫЕ КОМАНДЫ ДЛЯ ЧАТ-АДМИНОВ ====================

@bot.message_handler(commands=['chatadmin'], func=lambda m: m.chat.type in ['group', 'supergroup'])
def cmd_chatadmin(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    if not is_chat_owner(user_id, chat_id):
        bot.reply_to(message, "⛔️ Только для владельца чата.")
        return

    target_id, _ = _get_user_from_message(message)
    if not target_id:
        bot.reply_to(
            message,
            "❌ Укажите пользователя: `/chatadmin @user` или ответьте на сообщение",
            parse_mode="Markdown"
        )
        return

    if target_id == user_id:
        bot.reply_to(message, "❌ Нельзя назначить самого себя.")
        return

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO chat_admins (user_id, chat_id, role, added_by, added_at)
            VALUES (%s, %s, 'admin', %s, %s)
            ON CONFLICT (user_id, chat_id) DO UPDATE SET role = 'admin', added_by = %s
        """, (target_id, chat_id, user_id, int(time.time()), user_id))
        conn.commit()
    finally:
        cur.close()
        return_db_connection(conn)

    name = get_user_display_name_cached(target_id)
    bot.reply_to(message, f"✅ *{name}* назначен чат-администратором.", parse_mode="Markdown")


@bot.message_handler(commands=['chatdeadmin'], func=lambda m: m.chat.type in ['group', 'supergroup'])
def cmd_chatdeadmin(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    if not is_chat_owner(user_id, chat_id):
        bot.reply_to(message, "⛔️ Только для владельца чата.")
        return

    target_id, _ = _get_user_from_message(message)
    if not target_id:
        bot.reply_to(message, "❌ Укажите пользователя.")
        return

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Не даём снять роль 'owner'
        cur.execute(
            "SELECT role FROM chat_admins WHERE user_id = %s AND chat_id = %s",
            (target_id, chat_id)
        )
        row = cur.fetchone()
        if row and row[0] == 'owner':
            bot.reply_to(message, "⛔️ Нельзя снять владельца чата.")
            return

        cur.execute(
            "DELETE FROM chat_admins WHERE user_id = %s AND chat_id = %s",
            (target_id, chat_id)
        )
        conn.commit()
    finally:
        cur.close()
        return_db_connection(conn)

    name = get_user_display_name_cached(target_id)
    bot.reply_to(message, f"✅ У *{name}* сняты права чат-администратора.", parse_mode="Markdown")


@bot.message_handler(commands=['chatadmins'], func=lambda m: m.chat.type in ['group', 'supergroup'])
def cmd_chatadmins(message):
    chat_id = message.chat.id

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT user_id, role FROM chat_admins WHERE chat_id = %s ORDER BY role DESC",
            (chat_id,)
        )
        rows = cur.fetchall()
    finally:
        cur.close()
        return_db_connection(conn)

    if not rows:
        bot.reply_to(message, "📭 Чат-администраторов нет.")
        return

    text = "👑 *Администраторы чата (в боте):*\n\n"
    for uid, role in rows:
        name = get_user_display_name_cached(uid)
        icon = "👑" if role == 'owner' else "🔹"
        text += f"{icon} {name} (`{uid}`) — {role}\n"

    bot.reply_to(message, text, parse_mode="Markdown")

# ==================== ОБРАБОТЧИК ВХОДА БОТА В ЧАТ ====================

@bot.my_chat_member_handler()
def handle_bot_added_to_chat(update):
    """Срабатывает когда бот добавляется в чат или его статус меняется"""
    chat = update.chat
    new_status = update.new_chat_member.status

    # Бот добавлен в группу
    if new_status in ('member', 'administrator') and chat.type in ('group', 'supergroup'):
        chat_id = chat.id
        _register_chat_owner(chat_id)


def _register_chat_owner(chat_id):
    """Находит владельца чата и регистрирует его в chat_admins"""
    try:
        admins = bot.get_chat_administrators(chat_id)
        for member in admins:
            if member.status == 'creator':
                owner_id = member.user.id
                conn = get_db_connection()
                cur = conn.cursor()
                try:
                    cur.execute("""
                        INSERT INTO chat_admins (user_id, chat_id, role, added_by, added_at)
                        VALUES (%s, %s, 'owner', %s, %s)
                        ON CONFLICT (user_id, chat_id) DO UPDATE SET role = 'owner'
                    """, (owner_id, chat_id, owner_id, int(time.time())))
                    conn.commit()
                    print(f"[chat_owner] Зарегистрирован владелец {owner_id} для чата {chat_id}")
                    
                    try:
                        chat_info = bot.get_chat(chat_id)
                        bot.send_message(
                            owner_id,
                            f"👋 Привет! Я добавлен в чат *{chat_info.title or 'чат'}*.\n\n"
                            f"Ты автоматически назначен владельцем чата в боте.\n"
                            f"Теперь ты можешь назначать чат-админов через `/chatadmin`.\n\n"
                            f"📋 Список команд: `/modhelp`",
                            parse_mode="Markdown"
                        )
                    except:
                        pass
                finally:
                    cur.close()
                    return_db_connection(conn)
                break
    except Exception as e:
        print(f"[chat_owner] Ошибка регистрации владельца чата {chat_id}: {e}")

# ==================== ОБРАБОТЧИК edit_admin_ ====================

@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_admin_') and not call.data == 'edit_admin_perms')
def callback_edit_admin(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'manage_admins'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    target_id = int(call.data.split('_')[2])
    if target_id == ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нельзя редактировать владельца.")
        return
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT role FROM admins WHERE user_id = %s", (target_id,))
        result = cur.fetchone()
    finally:
        cur.close()
        return_db_connection(conn)
    if not result:
        bot.answer_callback_query(call.id, "❌ Админ не найден.")
        return
    _redraw_admin_perms(call, target_id)
    bot.answer_callback_query(call.id)

# ==================== ИСТОРИЯ СООБЩЕНИЙ В КАРТОЧКЕ ПОЛЬЗОВАТЕЛЯ ====================

@bot.callback_query_handler(func=lambda call: call.data.startswith('user_msg_history_'))
def callback_user_msg_history(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    target_id = int(call.data.split('_')[3])
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT l.message_text, l.created_at, l.chat_id
            FROM chat_messages_log l
            WHERE l.user_id = %s
            ORDER BY l.created_at DESC
            LIMIT 20
        """, (target_id,))
        logs = cur.fetchall()
    finally:
        cur.close()
        return_db_connection(conn)

    name = get_user_display_name_cached(target_id)
    text = f"💬 *История сообщений — {name}*\n\n"

    if not logs:
        text += "Нет сообщений в логах."
    else:
        prev_time = None
        for msg_text, created_at, chat_id in logs:
            time_str = datetime.fromtimestamp(created_at).strftime("%d.%m %H:%M:%S")
            if prev_time:
                delta = created_at - prev_time
                if delta < 60:
                    interval = f"{delta}с"
                elif delta < 3600:
                    interval = f"{delta // 60}м"
                else:
                    interval = f"{delta // 3600}ч {(delta % 3600) // 60}м"
                text += f"⏱ +{interval}\n"
            text += f"🕐 {time_str} | чат `{chat_id}`\n"
            text += f"💬 {msg_text[:100]}{'...' if len(msg_text) > 100 else ''}\n\n"
            prev_time = created_at

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data=f"user_{target_id}"))

    if len(text) > 4000:
        text = text[:3950] + "\n…"

    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                              parse_mode="Markdown", reply_markup=kb)
    except:
        bot.send_message(call.from_user.id, text, parse_mode="Markdown", reply_markup=kb)
    bot.answer_callback_query(call.id)

# ==================== ОБРАБОТЧИК callback_user_detail (С КНОПКАМИ БАЛЛОВ) ====================

def _refresh_user_card(call, target_id, admin_id):
    """Обновляет карточку пользователя после изменения"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT subscription_end, is_blocked, points FROM users WHERE user_id = %s", (target_id,))
            row = cur.fetchone()
        finally:
            cur.close()
            return_db_connection(conn)

        if not row:
            return

        subscription_end, blk, pts_val = row
        pts_val = pts_val or 0
        current_time = int(time.time())
        
        if blk:
            status = "🚫 Заблокирован"
        elif subscription_end and subscription_end > current_time:
            days_left = (subscription_end - current_time) // 86400
            status = f"🟢 Активен ({days_left} дн)"
        else:
            status = "🔴 Неактивен"

        is_admin_user = is_admin(target_id)
        admin_text = "✅ Да" if is_admin_user else "❌ Нет"
        name = get_user_display_name_cached(target_id)
        rank_info = get_rank(pts_val)
        
        try:
            chat = bot.get_chat(target_id)
            username = f"@{chat.username}" if chat.username else "❌ Нет юзернейма"
        except:
            username = "❌ Не найден"

        text = f"""👤 *{name}*

🆔 ID: `{target_id}`
👤 Юзернейм: {username}
📊 Статус: {status}
👑 Админ: {admin_text}
🪙 Баллов: `{pts_val:,}` — {rank_info['name']}"""

        kb = types.InlineKeyboardMarkup(row_width=2)
        if has_permission(admin_id, 'add_days'):
            kb.add(types.InlineKeyboardButton("✅ Выдать подписку", callback_data=f"give_sub_{target_id}"))
        if has_permission(admin_id, 'add_days'):
            kb.add(types.InlineKeyboardButton("📅 +30 дн", callback_data=f"prolong_{target_id}_30"))
        if has_permission(admin_id, 'remove_days'):
            kb.add(types.InlineKeyboardButton("📅 -30 дн", callback_data=f"remove_days_{target_id}_30"))
        if has_permission(admin_id, 'add_days') or has_permission(admin_id, 'remove_days'):
            kb.add(types.InlineKeyboardButton("🗑️ Удалить подписку", callback_data=f"remove_sub_{target_id}"))
        if has_permission(admin_id, 'block_user'):
            if blk:
                kb.add(types.InlineKeyboardButton("🔓 Разблокировать", callback_data=f"unblock_{target_id}"))
            else:
                kb.add(types.InlineKeyboardButton("🔒 Заблокировать", callback_data=f"block_{target_id}"))
        if has_permission(admin_id, 'manage_admins'):
            if is_admin_user and target_id != ADMIN_ID:
                kb.add(types.InlineKeyboardButton("👑 Забрать админку", callback_data=f"remove_admin_{target_id}"))
            elif not is_admin_user:
                kb.add(types.InlineKeyboardButton("👑 Выдать админку", callback_data=f"grant_admin_{target_id}"))
        
        # --- БАЛЛЫ ---
        if has_permission(admin_id, 'points_system'):
            kb.row(
                types.InlineKeyboardButton(f"🪙 +100", callback_data=f"pts_add_{target_id}_100"),
                types.InlineKeyboardButton(f"🪙 +500", callback_data=f"pts_add_{target_id}_500"),
                types.InlineKeyboardButton(f"🪙 +1000", callback_data=f"pts_add_{target_id}_1000"),
            )
            kb.row(
                types.InlineKeyboardButton(f"➖ -100", callback_data=f"pts_sub_{target_id}_100"),
                types.InlineKeyboardButton(f"➖ -500", callback_data=f"pts_sub_{target_id}_500"),
                types.InlineKeyboardButton(f"🗑 Обнулить", callback_data=f"pts_zero_{target_id}"),
            )
            kb.add(
                types.InlineKeyboardButton(
                    f"✏️ Установить баллы (сейчас: {pts_val:,})",
                    callback_data=f"pts_set_{target_id}"
                )
            )
        
        kb.add(types.InlineKeyboardButton("💬 История сообщений", callback_data=f"user_msg_history_{target_id}"))
        kb.row(
            types.InlineKeyboardButton("🔙 Назад к списку", callback_data="back_to_list"),
            types.InlineKeyboardButton("❌ Закрыть", callback_data="close_manage")
        )

        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown",
            reply_markup=kb
        )
    except Exception as e:
        print(f"[refresh_card] Ошибка обновления карточки: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('user_') and len(call.data.split('_')) == 2)
def callback_user_detail(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Нет доступа.")
        return
    user_id = call.from_user.id
    target_id = int(call.data.split('_')[1])
    if not has_permission(user_id, 'manage_users'):
        bot.answer_callback_query(call.id, "⛔️ У вас нет прав на управление пользователями.")
        return
    
    _refresh_user_card(call, target_id, user_id)
    bot.answer_callback_query(call.id)

# ==================== КНОПКИ УПРАВЛЕНИЯ БАЛЛАМИ ====================

@bot.callback_query_handler(func=lambda call: call.data.startswith(('pts_add_', 'pts_sub_', 'pts_zero_', 'pts_set_', 'pts_set_confirm_')))
def callback_points_manage(call):
    user_id = call.from_user.id
    if not is_admin(user_id) or not has_permission(user_id, 'points_system'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return

    data = call.data

    # Установить вручную — ждём ввода
    if data.startswith('pts_set_') and not data.startswith('pts_set_confirm_'):
        target_id = int(data.split('_')[2])
        search_cache[user_id] = {
            'action': 'set_points',
            'target_id': target_id,
            'timestamp': int(time.time())
        }
        bot.answer_callback_query(call.id)
        bot.send_message(
            user_id,
            f"✏️ Введите новое количество баллов для пользователя:\n\n"
            f"Например: `1000`\n\n"
            f"Или /cancel для отмены.",
            parse_mode="Markdown"
        )
        return

    parts = data.split('_')

    if data.startswith('pts_zero_'):
        target_id = int(parts[2])
        amount = None
        action = 'zero'
    elif data.startswith('pts_add_'):
        target_id = int(parts[2])
        amount = int(parts[3])
        action = 'add'
    elif data.startswith('pts_sub_'):
        target_id = int(parts[2])
        amount = int(parts[3])
        action = 'sub'
    else:
        bot.answer_callback_query(call.id)
        return

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT points FROM users WHERE user_id = %s", (target_id,))
        result = cur.fetchone()
        if not result:
            bot.answer_callback_query(call.id, "❌ Пользователь не найден")
            return

        old_points = result[0] or 0

        if action == 'zero':
            new_points = 0
            detail = f"Обнулил баллы (было {old_points})"
        elif action == 'add':
            new_points = old_points + amount
            detail = f"+{amount} баллов ({old_points} → {new_points})"
        else:  # sub
            new_points = max(0, old_points - amount)
            detail = f"-{amount} баллов ({old_points} → {new_points})"

        cur.execute("UPDATE users SET points = %s WHERE user_id = %s", (new_points, target_id))
        conn.commit()
    finally:
        cur.close()
        return_db_connection(conn)

    log_admin_action(user_id, f"Изменил баллы {target_id}", target_id=target_id, details=detail)
    bot.answer_callback_query(call.id, f"✅ {detail}")

    # Уведомляем пользователя
    try:
        bot.send_message(
            target_id,
            f"🪙 Администратор изменил ваши баллы.\n\n"
            f"📊 Было: {old_points:,}\n"
            f"📊 Стало: {new_points:,}\n"
            f"{get_rank(new_points)['name']}"
        )
    except:
        pass

    # Обновляем карточку
    _refresh_user_card(call, target_id, user_id)

# ==================== GRANT/REMOVE ADMIN С ОБНОВЛЕНИЕМ КАРТОЧКИ ====================

@bot.callback_query_handler(func=lambda call: call.data.startswith('grant_admin_'))
def callback_grant_admin(call):
    user_id = call.from_user.id
    target_id = int(call.data.split('_')[2])
    if not has_permission(user_id, 'manage_admins'):
        bot.answer_callback_query(call.id, "⛔️ У вас нет прав на управление админами.")
        return
    if target_id == ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Это владелец бота.")
        return
    if is_admin(target_id):
        bot.answer_callback_query(call.id, "❌ Пользователь уже является админом.")
        return
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT user_id FROM users WHERE user_id = %s", (target_id,))
        user_exists = cur.fetchone()
    finally:
        cur.close()
        return_db_connection(conn)
    if not user_exists:
        bot.answer_callback_query(call.id, "❌ Пользователь не зарегистрирован в боте.")
        return
    role = 'junior'
    perms = ROLE_PRESETS[role]['permissions'].copy()
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO admins (user_id, role, permissions, added_by, added_at) VALUES (%s, %s, %s, %s, %s)",
            (target_id, role, json.dumps(perms), user_id, int(time.time()))
        )
        conn.commit()
    finally:
        cur.close()
        return_db_connection(conn)
    log_admin_action(user_id, f"Назначил админом {target_id}", target_id=target_id, details=f"Роль: {role}")
    bot.answer_callback_query(call.id, f"✅ {get_user_display_name_cached(target_id)} назначен админом!")
    try:
        bot.send_message(target_id, "👑 Вам назначена роль администратора!\n\nТеперь вы имеете доступ к админ-панели (/admin)")
    except:
        pass

    # Обновляем карточку
    _refresh_user_card(call, target_id, user_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('remove_admin_'))
def callback_remove_admin(call):
    user_id = call.from_user.id
    target_id = int(call.data.split('_')[2])
    if not has_permission(user_id, 'manage_admins'):
        bot.answer_callback_query(call.id, "⛔️ У вас нет прав на управление админами.")
        return
    if target_id == ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нельзя удалить владельца.")
        return
    if not is_admin(target_id):
        bot.answer_callback_query(call.id, "❌ Пользователь не является админом.")
        return
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM admins WHERE user_id = %s", (target_id,))
        conn.commit()
    finally:
        cur.close()
        return_db_connection(conn)
    log_admin_action(user_id, f"Удалил админа {target_id}", target_id=target_id)
    bot.answer_callback_query(call.id, "✅ Админ удален!")
    try:
        bot.send_message(target_id, "❌ Ваши права администратора были отозваны.")
    except:
        pass
    
    # Обновляем карточку
    _refresh_user_card(call, target_id, user_id)

# ==================== ОСТАЛЬНЫЕ ОБРАБОТЧИКИ ====================

@bot.message_handler(func=lambda m: m.text == "👥 Рефералы")
def referrals(message):
    update_activity()
    user_id = message.from_user.id
    if is_blocked(user_id):
        bot.reply_to(message, blocked_message())
        return
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
        if not cur.fetchone():
            bot.reply_to(message, "❌ Вы не зарегистрированы. Используйте /start")
            return
        cur.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = %s", (user_id,))
        total = cur.fetchone()[0]
        today_start = int(time.time()) - 24 * 60 * 60
        cur.execute(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id = %s AND reward_date > %s",
            (user_id, today_start)
        )
        today = cur.fetchone()[0]
        bot_username = bot.get_me().username
        ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
        text = f"👥 *Рефералы*\n\n📊 Всего: {total}\n📅 Сегодня: {today} / 10\n\n🔗 Ссылка: `{ref_link}`\n\n📌 За каждого друга +3 дня."
        bot.reply_to(message, text, parse_mode="Markdown")
    finally:
        cur.close()
        return_db_connection(conn)

@bot.message_handler(func=lambda m: m.text == "🏆 Топ рефералов")
def top_referrals(message):
    update_activity()
    user_id = message.from_user.id
    if is_blocked(user_id):
        bot.reply_to(message, blocked_message())
        return
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT referrer_id, COUNT(*) FROM referrals GROUP BY referrer_id ORDER BY COUNT(*) DESC LIMIT 10")
        rows = cur.fetchall()
        if not rows:
            bot.reply_to(message, "📭 Нет рефералов.")
            return
        text = "🏆 *Топ рефералов:*\n\n"
        medals = ['🥇', '🥈', '🥉']
        for i, (ref_id, count) in enumerate(rows):
            name = get_user_display_name_cached(ref_id)
            icon = medals[i] if i < 3 else f"{i+1}."
            text += f"{icon} {name} — {count} реф.\n"
        bot.reply_to(message, text, parse_mode="Markdown")
    finally:
        cur.close()
        return_db_connection(conn)

@bot.message_handler(func=lambda m: m.text == "ℹ️ Стаж бота")
def bot_stats_command(message):
    update_activity()
    user_id = message.from_user.id
    if is_blocked(user_id):
        bot.reply_to(message, blocked_message())
        return
    stats = get_bot_stats()
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM users")
        total_users = cur.fetchone()[0]
        text = (
            f"📊 *Статистика*\n\n"
            f"⏳ Стаж: {stats['uptime_text']}\n"
            f"👥 Пользователей: {total_users}\n"
            f"📦 Ключей: {stats['current_keys']}\n"
            f"🔑 Проверено: {stats['total_keys_checked']}\n"
            f"🔓 Расшифровано: {stats['total_decryptions']}"
        )
        bot.reply_to(message, text, parse_mode="Markdown")
    finally:
        cur.close()
        return_db_connection(conn)

@bot.message_handler(func=lambda m: m.text == "🔓 Расшифровать подписку")
def decrypt_subscription_start(message):
    update_activity()
    if message.chat.type != 'private':
        return
    user_id = message.from_user.id
    if is_blocked(user_id):
        bot.reply_to(message, blocked_message())
        return
    if user_id in decrypt_results:
        del decrypt_results[user_id]
    decrypt_results[user_id] = {'waiting': True, 'timestamp': int(time.time())}
    bot.reply_to(
        message,
        "🔓 *Расшифровка VPN подписки*\n\n"
        "Отправьте ссылку, текст или файл подписки.\n\n"
        "Поддерживаю:\n"
        "• URL подписки\n"
        "• Base64 (все уровни)\n"
        "• HTML/JSON\n"
        "• Схемы: happ://, incy:// и др.\n"
        "• Файлы с ключами\n\n"
        "📄 Получите `.txt` файл со всеми ключами.\n\n"
        "❗ Чтобы выйти из режима расшифровки - нажмите /cancel",
        parse_mode="Markdown"
    )

@bot.message_handler(func=lambda m: m.text == "❓ Поддержка")
def support(message):
    bot.reply_to(message, f"💬 Поддержка: {SUPPORT}")

# ==================== ОБРАБОТЧИКИ КОПИРОВАНИЯ ====================

@bot.callback_query_handler(func=lambda call: call.data.startswith('copy_link_'))
def callback_copy_link(call):
    user_id = call.from_user.id
    target_id = int(call.data.split('_')[2])

    if user_id != target_id:
        bot.answer_callback_query(call.id, "❌ Это не ваша ссылка.")
        return

    link = get_subscription_link(user_id)
    if not link:
        bot.answer_callback_query(call.id, "❌ Подписка заморожена или недоступна.")
        return

    bot.send_message(
        user_id,
        f"📋 *Обычная ссылка:*\n\n`{link}`\n\nНажмите на сообщение и скопируйте текст.",
        parse_mode="Markdown"
    )
    bot.answer_callback_query(call.id, "✅ Ссылка отправлена!")

@bot.callback_query_handler(func=lambda call: call.data.startswith('copy_yandex_'))
def callback_copy_yandex(call):
    user_id = call.from_user.id
    target_id = int(call.data.split('_')[2])

    if user_id != target_id:
        bot.answer_callback_query(call.id, "❌ Это не ваша ссылка.")
        return

    link = get_subscription_link(user_id)
    if not link:
        bot.answer_callback_query(call.id, "❌ Подписка заморожена или недоступна.")
        return
    
    yandex_link = f"https://translate.yandex.ru/translate?url={link}"

    bot.send_message(
        user_id,
        f"🔄 *Ссылка для белых списков:*\n\n`{yandex_link}`\n\nНажмите на сообщение и скопируйте текст.\n\nℹ️ Ссылка автообновляется при белых списках.",
        parse_mode="Markdown"
    )
    bot.answer_callback_query(call.id, "✅ Ссылка для белых списков отправлена!")

@bot.callback_query_handler(func=lambda call: call.data == "check_sub")
def callback_check_sub(call):
    update_activity()
    if call.message.chat.type != 'private':
        bot.answer_callback_query(call.id, "⚠️ Работает только в личных сообщениях.")
        return
    user_id = call.from_user.id
    current_time = int(time.time())
    if is_blocked(user_id):
        bot.answer_callback_query(call.id, "🚫 Вы заблокированы.")
        return
    if is_subscribed(user_id):
        bot.answer_callback_query(call.id, "✅ Подписка подтверждена!")
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
        if user_id in captcha_sessions and captcha_sessions[user_id].get('waiting_for_sub'):
            session = captcha_sessions[user_id]
            bot.send_message(user_id, "✅ Подписка подтверждена! Регистрируем вас...")
            _register_user(user_id, session.get('referrer_id'))
            del captcha_sessions[user_id]
            return
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT referrer_id FROM referrals WHERE referred_id = %s AND rewarded = 0",
                (user_id,)
            )
            pending = cur.fetchone()
        finally:
            cur.close()
            return_db_connection(conn)
        if pending:
            referrer_id = pending[0]
            if is_subscribed(referrer_id):
                conn = get_db_connection()
                cur = conn.cursor()
                try:
                    cur.execute("SELECT subscription_end FROM users WHERE user_id = %s", (referrer_id,))
                    ref_result = cur.fetchone()
                    if ref_result:
                        new_end = ref_result[0] + 3 * 24 * 60 * 60
                        cur.execute("UPDATE users SET subscription_end = %s, notified_3days = 0 WHERE user_id = %s", (new_end, referrer_id))
                        cur.execute("UPDATE referrals SET rewarded = 1 WHERE referred_id = %s", (user_id,))
                        conn.commit()
                        try:
                            bot.send_message(referrer_id, "🎉 Ваш реферал подтвердил подписку! Вам начислено +3 дня.")
                        except:
                            pass
                finally:
                    cur.close()
                    return_db_connection(conn)
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
            user_exists = cur.fetchone()
        finally:
            cur.close()
            return_db_connection(conn)
        if not user_exists:
            _register_user(user_id, None)
        else:
            bot.send_message(user_id, "👋 Добро пожаловать!")
            bot.send_message(user_id, "Выберите действие:", reply_markup=main_menu())
    else:
        bot.answer_callback_query(call.id, "❌ Вы ещё не подписались на канал!")

# ==================== РЕГИСТРАЦИЯ ПОЛЬЗОВАТЕЛЯ ====================

def _register_user(user_id, referrer_id=None):
    current_time = int(time.time())
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        token = generate_subscription_token()
        sub_end = current_time + 7 * 24 * 60 * 60
        
        cur.execute("""
            INSERT INTO users (user_id, subscription_end, last_activity, is_blocked, token) 
            VALUES (%s, %s, %s, 0, %s)
            ON CONFLICT (user_id) DO NOTHING
            RETURNING user_id
        """, (user_id, sub_end, current_time, token))
        result = cur.fetchone()
        
        if not result:
            return
        
        conn.commit()
        
        try:
            chat = bot.get_chat(user_id)
            if chat.username:
                update_user_username(user_id, chat.username)
        except:
            pass
    finally:
        cur.close()
        return_db_connection(conn)
    
    if referrer_id:
        success, message = process_referral(referrer_id, user_id)
        if success:
            try:
                bot.send_message(referrer_id, f"🔔 Новый реферал! Пользователь {get_user_display_name_cached(user_id)} зарегистрировался по вашей ссылке.")
            except:
                pass
    
    bot.send_message(user_id, "🎉 Добро пожаловать! Вам выдана подписка на 7 дней.")
    bot.send_message(user_id, "Выберите действие:", reply_markup=main_menu())

# ==================== ОБРАБОТЧИК СТАРТА ====================

@bot.message_handler(commands=['start'])
def cmd_start(message):
    update_activity()
    if message.chat.type != 'private':
        bot.reply_to(message, "⚠️ Бот работает только в личных сообщениях.")
        return

    user_id = message.from_user.id
    current_time = int(time.time())

    if is_blocked(user_id):
        bot.reply_to(message, blocked_message())
        return

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
        existing_user = cur.fetchone()
    finally:
        cur.close()
        return_db_connection(conn)

    if existing_user:
        if not is_subscribed(user_id):
            bot.reply_to(message, "⚠️ Подпишитесь на канал, чтобы пользоваться ботом.", reply_markup=subscribe_button())
            return
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT last_activity FROM users WHERE user_id = %s", (user_id,))
            result = cur.fetchone()
            if result:
                last_activity = result[0] or 0
                days_since_last = (current_time - last_activity) // (24 * 60 * 60)
                welcome_text = "👋 С возвращением!" if days_since_last >= 3 else "👋 Добро пожаловать!"
                cur.execute("UPDATE users SET last_activity = %s WHERE user_id = %s", (current_time, user_id))
                conn.commit()
                bot.reply_to(message, welcome_text)
        finally:
            cur.close()
            return_db_connection(conn)
        bot.send_message(user_id, "Выберите действие:", reply_markup=main_menu())
        return

    if user_id in captcha_sessions:
        session = captcha_sessions[user_id]
        if int(time.time()) - session['timestamp'] < CAPTCHA_TIMEOUT:
            bot.reply_to(
                message,
                "⏳ Вы уже проходите капчу. Нажмите кнопку ниже.",
                reply_markup=types.InlineKeyboardMarkup().add(
                    types.InlineKeyboardButton("✅ Я НЕ РОБОТ", callback_data=f"captcha_verify_{user_id}")
                )
            )
            return
        else:
            del captcha_sessions[user_id]

    ok, msg = check_subscribe_rate()
    if not ok:
        bot.reply_to(message, f"⚠️ {msg}")
        return

    add_subscribe_record(user_id)

    referrer_id = None
    if message.text:
        parts = message.text.strip().split()
        if len(parts) > 1:
            for part in parts:
                if part.startswith('ref_'):
                    try:
                        ref = int(part[4:])
                        if ref != user_id:
                            referrer_id = ref
                        break
                    except ValueError:
                        continue

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("✅ Я НЕ РОБОТ", callback_data=f"captcha_verify_{user_id}"))

    msg = bot.reply_to(
        message,
        "🤖 *Пожалуйста, подтвердите, что вы не робот*\n\n"
        "Нажмите кнопку ниже для проверки.\n"
        f"⏱ У вас {CAPTCHA_TIMEOUT//60} минут.",
        parse_mode="Markdown",
        reply_markup=kb
    )

    captcha_sessions[user_id] = {
        'timestamp': int(time.time()),
        'message_id': msg.message_id,
        'referrer_id': referrer_id,
        'waiting_for_sub': False
    }

@bot.callback_query_handler(func=lambda call: call.data.startswith('captcha_verify_'))
def callback_captcha_verify(call):
    user_id = int(call.data.split('_')[2])
    if call.from_user.id != user_id:
        bot.answer_callback_query(call.id, "❌ Это не ваша капча.")
        return
    if user_id not in captcha_sessions:
        bot.answer_callback_query(call.id, "❌ Сессия истекла. Нажмите /start")
        return
    session = captcha_sessions[user_id]
    current_time = int(time.time())
    if current_time - session['timestamp'] > CAPTCHA_TIMEOUT:
        del captcha_sessions[user_id]
        bot.answer_callback_query(call.id, "⏰ Время вышло. Нажмите /start")
        return
    try:
        bot.delete_message(call.message.chat.id, session['message_id'])
    except:
        pass
    bot.answer_callback_query(call.id, "✅ Капча пройдена!")

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
        already_registered = cur.fetchone()
    finally:
        cur.close()
        return_db_connection(conn)

    if already_registered:
        del captcha_sessions[user_id]
        bot.send_message(user_id, "👋 Вы уже зарегистрированы!")
        bot.send_message(user_id, "Выберите действие:", reply_markup=main_menu())
        return

    if is_subscribed(user_id):
        bot.send_message(user_id, "✅ Подписка подтверждена! Регистрируем вас...")
        _register_user(user_id, session.get('referrer_id'))
        del captcha_sessions[user_id]
    else:
        bot.send_message(
            user_id,
            "⚠️ Подпишитесь на канал, чтобы завершить регистрацию.\n\n"
            "После подписки нажмите кнопку ниже.",
            reply_markup=subscribe_button()
        )
        captcha_sessions[user_id]['waiting_for_sub'] = True

# ==================== АВТОПОСТИНГ CALLBACKS ====================

@bot.callback_query_handler(func=lambda call: call.data == "autopost_back")
def callback_autopost_back(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'autopost'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    
    config = get_autopost_config()
    status = "✅ ВКЛ" if config['enabled'] else "❌ ВЫКЛ"
    text = (
        f"📡 *АВТОПОСТИНГ*\n\n"
        f"Статус: {status}\n"
        f"Интервал: {config['interval'] // 60} мин\n"
        f"Канал: {config['channel_id']}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📥 Загрузить ключи", callback_data="autopost_load_keys"),
        types.InlineKeyboardButton("🚀 Начать", callback_data="autopost_start"),
        types.InlineKeyboardButton("⚙️ Канал", callback_data="autopost_channel_settings"),
        types.InlineKeyboardButton("⏱ Интервал", callback_data="autopost_interval_settings"),
        types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back_panel")
    )
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=kb)
    except:
        bot.send_message(user_id, text, parse_mode="Markdown", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data == "autopost_load_keys")
def callback_autopost_load_keys(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'autopost'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    bot.answer_callback_query(call.id, "📥 Отправьте ключи")
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ Завершить", callback_data="autopost_load_finish"),
        types.InlineKeyboardButton("🔙 Назад", callback_data="autopost_back")
    )
    msg = bot.send_message(user_id, "📥 Отправляйте ключи.\nКогда закончите - нажмите Завершить.", reply_markup=kb)
    autopost_loading[user_id] = {'keys': [], 'message_id': msg.message_id, 'timestamp': int(time.time())}

@bot.callback_query_handler(func=lambda call: call.data == "autopost_load_finish")
def callback_autopost_load_finish(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'autopost'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    if user_id not in autopost_loading:
        bot.answer_callback_query(call.id, "❌ Нет загрузки")
        return
    keys = autopost_loading[user_id]['keys']
    if not keys:
        bot.answer_callback_query(call.id, "❌ Нет ключей")
        return
    save_keys_to_db(keys)
    del autopost_loading[user_id]
    bot.answer_callback_query(call.id, f"✅ Сохранено {len(keys)}")
    callback_autopost_back(call)

@bot.callback_query_handler(func=lambda call: call.data == "autopost_start")
def callback_autopost_start(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'autopost'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    keys = get_keys_from_db()
    if not keys:
        bot.answer_callback_query(call.id, "❌ Нет ключей")
        return
    config = get_autopost_config()
    config['enabled'] = True
    save_autopost_config(config)
    bot.answer_callback_query(call.id, "🚀 Запущен!")
    auto_post_keys_to_channel()
    set_setting('autopost_last_post', str(int(time.time())))
    callback_autopost_back(call)

@bot.callback_query_handler(func=lambda call: call.data == "autopost_channel_settings")
def callback_autopost_channel_settings(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'autopost'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    config = get_autopost_config()
    text = (
        f"⚙️ *Канал*\n\n"
        f"📢 Текущий: {config['channel_id']}\n"
        f"📝 Ветка: {config['topic_id'] if config['topic_id'] else 'Нет'}"
    )
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("📢 Сменить", callback_data="autopost_change_channel"),
        types.InlineKeyboardButton("🔙 Назад", callback_data="autopost_back")
    )
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data == "autopost_change_channel")
def callback_autopost_change_channel(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'autopost'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    bot.answer_callback_query(call.id, "🔄 Отправьте новый канал")
    bot.send_message(user_id, "📢 Отправьте ссылку или ID канала.\nПример: `-1001234567890` или `@channel`", parse_mode="Markdown")
    search_cache[user_id] = {'action': 'autopost_set_channel', 'timestamp': int(time.time())}

@bot.callback_query_handler(func=lambda call: call.data == "autopost_interval_settings")
def callback_autopost_interval_settings(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'autopost'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    config = get_autopost_config()
    text = f"⏱ *Интервал*\n\n⏱ Текущий: {config['interval'] // 60} мин"
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("⏱ Изменить", callback_data="autopost_set_interval"),
        types.InlineKeyboardButton("🔙 Назад", callback_data="autopost_back")
    )
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data == "autopost_set_interval")
def callback_autopost_set_interval(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'autopost'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    bot.answer_callback_query(call.id, "⏱ Введите минуты")
    bot.send_message(user_id, "⏱ Введите интервал в минутах (5-1440):", parse_mode="Markdown")
    search_cache[user_id] = {'action': 'autopost_set_interval', 'timestamp': int(time.time())}

# ==================== УПРАВЛЕНИЕ КЛЮЧАМИ CALLBACKS ====================

@bot.callback_query_handler(func=lambda call: call.data == "admin_keys_load")
def callback_admin_keys_load(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'manage_keys'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    bot.answer_callback_query(call.id, "📥 Отправьте ключи")
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ Завершить", callback_data="admin_keys_load_finish"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="admin_keys_load_cancel")
    )
    msg = bot.send_message(
        user_id,
        "📥 *Загрузка ключей*\n\n"
        "Отправляйте ключи по одному сообщению.\n"
        "Поддерживаются:\n"
        "• Текст с ключами (vless://, vmess:// и др.)\n"
        "• .txt файл с ключами\n"
        "• Ссылка на подписку\n\n"
        "⚠️ *ВНИМАНИЕ:* Новая загрузка ПОЛНОСТЬЮ ЗАМЕНИТ все текущие ключи!\n\n"
        "Когда закончите - нажмите *✅ Завершить*",
        parse_mode="Markdown",
        reply_markup=kb
    )
    keys_loading[user_id] = {
        'keys': [],
        'message_id': msg.message_id,
        'timestamp': int(time.time())
    }

@bot.callback_query_handler(func=lambda call: call.data == "admin_keys_load_finish")
def callback_admin_keys_load_finish(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'manage_keys'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    if user_id not in keys_loading:
        bot.answer_callback_query(call.id, "❌ Нет активной загрузки")
        return
    keys = keys_loading[user_id]['keys']
    if not keys:
        bot.answer_callback_query(call.id, "❌ Нет загруженных ключей")
        return
    save_keys_to_db(keys)
    log_admin_action(user_id, f"Загрузил {len(keys)} ключей", details=f"Ключей: {len(keys)}")
    proto_stats = {}
    for k in keys:
        m = re.match(r'([a-z0-9+]+)://', k, re.IGNORECASE)
        if m:
            p = m.group(1).lower()
            proto_stats[p] = proto_stats.get(p, 0) + 1
    stats = '\n'.join(f"  • {p}:// — {c}" for p, c in sorted(proto_stats.items(), key=lambda x: -x[1]))
    del keys_loading[user_id]
    bot.answer_callback_query(call.id, f"✅ Загружено {len(keys)} ключей!")
    total_in_db = len(get_keys_from_db())
    try:
        bot.edit_message_text(
            f"✅ *Ключи загружены!*\n\n"
            f"📊 Загружено ключей: {len(keys)}\n"
            f"📋 По протоколам:\n{stats}\n"
            f"📦 Всего в базе: {total_in_db}",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown"
        )
    except:
        bot.send_message(user_id, 
            f"✅ *Ключи загружены!*\n\n"
            f"📊 Загружено ключей: {len(keys)}\n"
            f"📋 По протоколам:\n{stats}\n"
            f"📦 Всего в базе: {total_in_db}",
            parse_mode="Markdown"
        )

@bot.callback_query_handler(func=lambda call: call.data == "admin_keys_load_cancel")
def callback_admin_keys_load_cancel(call):
    user_id = call.from_user.id
    if user_id in keys_loading:
        del keys_loading[user_id]
    bot.answer_callback_query(call.id, "❌ Отменено")
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass
    show_keys_menu(user_id, call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_keys_clean_dead")
def callback_admin_keys_clean_dead(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'manage_keys'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    keys = get_keys_from_db()
    if not keys:
        bot.answer_callback_query(call.id, "❌ Нет ключей для проверки")
        return
    bot.answer_callback_query(call.id, "⏳ Проверяю ключи...")
    alive_keys = []
    dead_keys = []
    for key in keys:
        match = re.search(r'@([\d\.]+):(\d+)', key)
        if match:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                result = sock.connect_ex((match.group(1), int(match.group(2))))
                sock.close()
                if result == 0:
                    alive_keys.append(key)
                else:
                    dead_keys.append(key)
            except:
                dead_keys.append(key)
        else:
            dead_keys.append(key)
    save_keys_to_db(alive_keys)
    log_admin_action(user_id, f"Очистил нерабочие ключи", details=f"Удалено: {len(dead_keys)}, осталось: {len(alive_keys)}")
    text = (
        f"🧹 *Очистка нерабочих ключей завершена!*\n\n"
        f"✅ Оставлено живых: {len(alive_keys)}\n"
        f"🗑️ Удалено нерабочих: {len(dead_keys)}\n"
        f"📦 Всего в базе: {len(alive_keys)}"
    )
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown")
    except:
        bot.send_message(user_id, text, parse_mode="Markdown")
    time.sleep(2)
    show_keys_menu(user_id, call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_keys_clear_all")
def callback_admin_keys_clear_all(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'manage_keys'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    bot.answer_callback_query(call.id)
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ Да, удалить все", callback_data="admin_keys_clear_confirm"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="admin_keys_back")
    )
    try:
        bot.edit_message_text(
            "⚠️ *ВНИМАНИЕ!*\n\n"
            "Вы уверены, что хотите удалить ВСЕ ключи из базы?\n"
            "Это действие НЕЛЬЗЯ будет отменить!",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown",
            reply_markup=kb
        )
    except:
        bot.send_message(user_id, "⚠️ Подтвердите удаление всех ключей.", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data == "admin_keys_clear_confirm")
def callback_admin_keys_clear_confirm(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'manage_keys'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    count = len(get_keys_from_db())
    save_keys_to_db([])
    set_setting('total_keys_issued', '0')
    log_admin_action(user_id, f"Удалил все ключи", details=f"Удалено: {count} ключей")
    bot.answer_callback_query(call.id, "🗑️ Все ключи удалены!")
    show_keys_menu(user_id, call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_keys_back")
def callback_admin_keys_back(call):
    user_id = call.from_user.id
    bot.answer_callback_query(call.id)
    show_keys_menu(user_id, call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_keys_reset_issued")
def callback_admin_keys_reset_issued(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'manage_keys'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    current_issued = int(get_setting('total_keys_issued', '0'))
    if current_issued == 0:
        bot.answer_callback_query(call.id, "❌ Выдано 0 ключей, сбрасывать нечего")
        return
    set_setting('total_keys_issued', '0')
    log_admin_action(user_id, f"Сбросил счётчик выданных ключей", details=f"Было: {current_issued}")
    bot.answer_callback_query(call.id, f"🔄 Сброшено {current_issued} выданных ключей!")
    show_keys_menu(user_id, call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_keys_proxy_menu")
def callback_admin_keys_proxy_menu(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'manage_keys'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    bot.answer_callback_query(call.id)
    _show_proxy_menu(call.message.chat.id, call.message.message_id, user_id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_keys_proxy_reset")
def callback_admin_keys_proxy_reset(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'manage_keys'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    set_setting('proxy_sub_url', '')
    set_setting('proxy_sub_urls', '')
    log_admin_action(user_id, "Сбросил прокси ссылки")
    bot.answer_callback_query(call.id, "✅ Прокси ссылки сброшены!")
    _show_proxy_menu(call.message.chat.id, call.message.message_id, user_id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_keys_proxy_load")
def callback_admin_keys_proxy_load(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'manage_keys'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    bot.answer_callback_query(call.id)
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ Завершить загрузку", callback_data="admin_keys_proxy_finish"),
        types.InlineKeyboardButton("🔙 Назад", callback_data="admin_keys_back")
    )
    msg = bot.send_message(
        user_id,
        "🌐 *Загрузка прокси ссылок*\n\n"
        "Отправляйте ссылки на подписки по одной.\n"
        "Можно загрузить несколько ссылок — ключи из всех будут объединены.\n\n"
        "Поддерживаются:\n"
        "• Обычные HTTP/HTTPS ссылки на подписки\n"
        "• Base64-закодированные ссылки\n"
        "• Схемы приложений (happ://, incy:// и др.)\n\n"
        "⚠️ Ключи будут *добавлены* к уже существующим в базе.\n\n"
        "Когда закончите — нажмите *✅ Завершить загрузку*",
        parse_mode="Markdown",
        reply_markup=kb
    )
    proxy_url_loading[user_id] = {
        'urls': [],
        'message_id': msg.message_id,
        'timestamp': int(time.time())
    }

@bot.callback_query_handler(func=lambda call: call.data == "admin_keys_proxy_finish")
def callback_admin_keys_proxy_finish(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'manage_keys'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    if user_id not in proxy_url_loading:
        bot.answer_callback_query(call.id, "❌ Нет активной загрузки")
        return
    urls = proxy_url_loading[user_id].get('urls', [])
    if not urls:
        bot.answer_callback_query(call.id, "❌ Нет добавленных ссылок")
        return
    bot.answer_callback_query(call.id, f"⏳ Загружаю ключи из {len(urls)} ссылок...")
    proxy_url_loading.pop(user_id)
    
    def process_proxy_urls():
        all_keys = []
        results = []
        for url in urls:
            try:
                keys = load_keys_from_url(url)
                results.append((url, len(keys), True))
                all_keys.extend(keys)
            except Exception as e:
                results.append((url, 0, False))
        all_keys = _dedup(all_keys)
        if not all_keys:
            try:
                bot.send_message(
                    user_id,
                    "❌ Не удалось извлечь ключи ни из одной ссылки.\n\n"
                    "Проверьте доступность ссылок и формат подписки."
                )
            except:
                pass
            return
        existing_urls = get_setting('proxy_sub_urls', '')
        all_urls = [u for u in existing_urls.split('|||') if u] if existing_urls else []
        all_urls.extend(urls)
        all_urls = list(dict.fromkeys(all_urls))
        set_setting('proxy_sub_urls', '|||'.join(all_urls))
        if urls:
            set_setting('proxy_sub_url', urls[-1])
        current_keys = get_keys_from_db()
        merged = _dedup(current_keys + all_keys)
        save_keys_to_db(merged)
        log_admin_action(user_id, f"Загрузил ключи из прокси", details=f"Ссылок: {len(urls)}, ключей: {len(all_keys)}")
        proto_stats = {}
        for k in all_keys:
            m = re.match(r'([a-z0-9+]+)://', k, re.IGNORECASE)
            if m:
                p = m.group(1).lower()
                proto_stats[p] = proto_stats.get(p, 0) + 1
        stats_text = '\n'.join(
            f"  • {p}:// — {c}"
            for p, c in sorted(proto_stats.items(), key=lambda x: -x[1])
        )
        results_text = ""
        for url, count, ok in results:
            short_url = url[:45] + "..." if len(url) > 45 else url
            icon = "✅" if ok else "❌"
            results_text += f"{icon} {short_url} — {count} ключей\n"
        report = (
            f"✅ *Загрузка из прокси завершена!*\n\n"
            f"🔗 Обработано ссылок: {len(urls)}\n"
            f"🔑 Новых ключей: {len(all_keys)}\n"
            f"📦 Всего в базе: {len(merged)}\n\n"
            f"📋 По протоколам:\n{stats_text}\n\n"
            f"📊 Результаты по ссылкам:\n{results_text}"
        )
        if len(report) > 4000:
            report = report[:3950].rstrip() + "\n…"
        try:
            bot.send_message(user_id, report, parse_mode="Markdown")
        except:
            bot.send_message(user_id, report)
    t = threading.Thread(target=process_proxy_urls)
    t.daemon = True
    t.start()

# ==================== УПРАВЛЕНИЕ ПОДПИСКОЙ ====================

@bot.callback_query_handler(func=lambda call: call.data.startswith('give_sub_'))
def callback_give_sub(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    user_id = call.from_user.id
    if not has_permission(user_id, 'add_days'):
        bot.answer_callback_query(call.id, "⛔️ У вас нет прав на выдачу подписки.")
        return
    target_id = int(call.data.split('_')[2])
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT user_id FROM users WHERE user_id = %s", (target_id,))
        result = cur.fetchone()
        if not result:
            bot.answer_callback_query(call.id, "❌ Пользователь не найден.")
            return
        current_time = int(time.time())
        new_end = current_time + 30 * 24 * 60 * 60
        cur.execute("UPDATE users SET subscription_end = %s, notified_3days = 0 WHERE user_id = %s", (new_end, target_id))
        conn.commit()
    finally:
        cur.close()
        return_db_connection(conn)
    log_admin_action(user_id, f"Выдал подписку {target_id}", target_id=target_id, details="30 дней")
    bot.answer_callback_query(call.id, "✅ Выдана подписка на 30 дней!")
    try:
        bot.send_message(target_id, f"🎉 Администратор выдал вам подписку на 30 дней!")
    except:
        pass
    
    _refresh_user_card(call, target_id, user_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('prolong_'))
def callback_prolong(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    user_id = call.from_user.id
    if not has_permission(user_id, 'add_days'):
        bot.answer_callback_query(call.id, "⛔️ У вас нет прав на выдачу дней.")
        return
    parts = call.data.split('_')
    target_id = int(parts[1])
    days = int(parts[2])
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT subscription_end FROM users WHERE user_id = %s", (target_id,))
        result = cur.fetchone()
        if not result:
            bot.answer_callback_query(call.id, "❌ Пользователь не найден.")
            return
        current_time = int(time.time())
        current_end = result[0] if (result[0] and result[0] > current_time) else current_time
        new_end = current_end + days * 24 * 60 * 60
        cur.execute("UPDATE users SET subscription_end = %s, notified_3days = 0 WHERE user_id = %s", (new_end, target_id))
        conn.commit()
    finally:
        cur.close()
        return_db_connection(conn)
    log_admin_action(user_id, f"Продлил подписку {target_id}", target_id=target_id, details=f"+{days} дней")
    bot.answer_callback_query(call.id, f"✅ Продлено на {days} дней!")
    try:
        bot.send_message(target_id, f"🎉 Ваша подписка продлена на {days} дней администратором!")
    except:
        pass
    
    _refresh_user_card(call, target_id, user_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('remove_days_'))
def callback_remove_days(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    user_id = call.from_user.id
    if not has_permission(user_id, 'remove_days'):
        bot.answer_callback_query(call.id, "⛔️ У вас нет прав на забирание дней.")
        return
    parts = call.data.split('_')
    target_id = int(parts[2])
    days = int(parts[3])
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT subscription_end FROM users WHERE user_id = %s", (target_id,))
        result = cur.fetchone()
        if not result:
            bot.answer_callback_query(call.id, "❌ Пользователь не найден.")
            return
        current_time = int(time.time())
        current_end = result[0] if (result[0] and result[0] > current_time) else current_time
        new_end = current_end - days * 24 * 60 * 60
        if new_end < current_time:
            new_end = current_time - 1
        cur.execute("UPDATE users SET subscription_end = %s, notified_3days = 0 WHERE user_id = %s", (new_end, target_id))
        conn.commit()
    finally:
        cur.close()
        return_db_connection(conn)
    log_admin_action(user_id, f"Забрал дни у {target_id}", target_id=target_id, details=f"-{days} дней")
    bot.answer_callback_query(call.id, f"✅ Убавлено {days} дней!")
    try:
        bot.send_message(target_id, f"⚠️ Администратор забрал {days} дней подписки!")
    except:
        pass
    
    _refresh_user_card(call, target_id, user_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('remove_sub_'))
def callback_remove_sub(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    user_id = call.from_user.id
    if not has_permission(user_id, 'add_days') and not has_permission(user_id, 'remove_days'):
        bot.answer_callback_query(call.id, "⛔️ У вас нет прав на удаление подписки.")
        return
    target_id = int(call.data.split('_')[2])
    current_time = int(time.time())
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE users SET subscription_end = %s WHERE user_id = %s", (current_time - 1, target_id))
        conn.commit()
    finally:
        cur.close()
        return_db_connection(conn)
    log_admin_action(user_id, f"Удалил подписку у {target_id}", target_id=target_id)
    bot.answer_callback_query(call.id, "✅ Подписка удалена!")
    try:
        bot.send_message(target_id, "❌ Ваша подписка была удалена администратором.")
    except:
        pass
    
    _refresh_user_card(call, target_id, user_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('block_'))
def callback_block(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    user_id = call.from_user.id
    if not has_permission(user_id, 'block_user'):
        bot.answer_callback_query(call.id, "⛔️ У вас нет прав на блокировку.")
        return
    target_id = int(call.data.split('_')[1])
    if target_id == ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нельзя заблокировать создателя.")
        return
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE users SET is_blocked = 1 WHERE user_id = %s", (target_id,))
        conn.commit()
    finally:
        cur.close()
        return_db_connection(conn)
    log_admin_action(user_id, f"Заблокировал {target_id}", target_id=target_id)
    bot.answer_callback_query(call.id, "✅ Пользователь заблокирован!")
    try:
        bot.send_message(target_id, f"🚫 Вы заблокированы администратором.\n\nОбратитесь в поддержку: {SUPPORT}")
    except:
        pass
    
    _refresh_user_card(call, target_id, user_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('unblock_'))
def callback_unblock(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    user_id = call.from_user.id
    if not has_permission(user_id, 'unblock_user'):
        bot.answer_callback_query(call.id, "⛔️ У вас нет прав на разблокировку.")
        return
    target_id = int(call.data.split('_')[1])
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE users SET is_blocked = 0 WHERE user_id = %s", (target_id,))
        conn.commit()
    finally:
        cur.close()
        return_db_connection(conn)
    log_admin_action(user_id, f"Разблокировал {target_id}", target_id=target_id)
    bot.answer_callback_query(call.id, "✅ Пользователь разблокирован!")
    try:
        bot.send_message(target_id, "✅ Вы разблокированы! Теперь вы можете пользоваться ботом.")
    except:
        pass
    
    _refresh_user_card(call, target_id, user_id)

# ==================== РАССЫЛКА ====================

@bot.callback_query_handler(func=lambda call: call.data == "announce_dm")
def callback_announce_dm(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'announce'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    bot.answer_callback_query(call.id, "📝 Отправьте текст/медиа")
    bot.send_message(user_id, "📨 *Рассылка в ЛС*\n\nОтправьте текст или медиа.", parse_mode="Markdown")
    announce_data[user_id] = {'type': 'dm', 'waiting': True, 'timestamp': int(time.time())}

@bot.callback_query_handler(func=lambda call: call.data == "announce_channels")
def callback_announce_channels(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'announce'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    bot.answer_callback_query(call.id)
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT channel_id, channel_name FROM autopost_channels WHERE enabled = TRUE")
        channels = cur.fetchall()
    finally:
        cur.close()
        return_db_connection(conn)
    if not channels:
        bot.send_message(user_id, "❌ Нет каналов")
        return
    kb = types.InlineKeyboardMarkup(row_width=1)
    for ch_id, ch_name in channels:
        kb.add(types.InlineKeyboardButton(f"📢 {ch_name}", callback_data=f"announce_to_channel_{ch_id}"))
    kb.add(types.InlineKeyboardButton("📢 Во все", callback_data="announce_all_channels"))
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back_panel"))
    bot.send_message(user_id, "📢 *Выберите канал:*", parse_mode="Markdown", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data.startswith('announce_to_channel_'))
def callback_announce_to_channel(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'announce'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    channel_id = int(call.data.split('_')[3])
    bot.answer_callback_query(call.id, "📝 Отправьте текст/медиа")
    bot.send_message(user_id, f"📢 *Объявление в канал*\n\nID: {channel_id}\n\nОтправьте текст или медиа.", parse_mode="Markdown")
    announce_data[user_id] = {'type': 'channel', 'channel_id': channel_id, 'waiting': True, 'timestamp': int(time.time())}

@bot.callback_query_handler(func=lambda call: call.data == "announce_all_channels")
def callback_announce_all_channels(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'announce'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    bot.answer_callback_query(call.id, "📝 Отправьте текст/медиа")
    bot.send_message(user_id, "📢 *Объявление во все каналы*\n\nОтправьте текст или медиа.", parse_mode="Markdown")
    announce_data[user_id] = {'type': 'all_channels', 'waiting': True, 'timestamp': int(time.time())}

# ==================== ОБРАБОТЧИКИ ДЛЯ РЕЖИМОВ ====================

def handle_autopost_load_keys(message):
    user_id = message.from_user.id
    if user_id not in autopost_loading:
        return
    raw = message.text or message.caption or ''
    keys = load_keys_from_text(raw) if raw else []
    if not keys and message.document:
        try:
            file = bot.get_file(message.document.file_id)
            data = bot.download_file(file.file_path)
            keys = load_keys_from_text(data.decode('utf-8', errors='ignore'))
        except:
            pass
    if keys:
        autopost_loading[user_id]['keys'].extend(keys)
        autopost_loading[user_id]['keys'] = _dedup(autopost_loading[user_id]['keys'])
        autopost_loading[user_id]['timestamp'] = int(time.time())
        bot.reply_to(message, f"✅ Загружено {len(keys)}. Всего: {len(autopost_loading[user_id]['keys'])}")
    else:
        bot.reply_to(message, "❌ Не найдено ключей")

def handle_autopost_set_channel(message):
    user_id = message.from_user.id
    text = message.text.strip()
    channel_id = None
    topic_id = 0
    if 't.me/' in text:
        match = re.search(r't\.me/([a-zA-Z0-9_]+)', text)
        if match:
            try:
                chat = bot.get_chat(f"@{match.group(1)}")
                channel_id = chat.id
            except:
                pass
    if not channel_id:
        try:
            channel_id = int(text)
        except:
            pass
    if 'thread_id=' in text:
        match = re.search(r'thread_id=(\d+)', text)
        if match:
            topic_id = int(match.group(1))
    if not channel_id:
        bot.reply_to(message, "❌ Не удалось распознать")
        return
    config = get_autopost_config()
    config['channel_id'] = channel_id
    config['topic_id'] = topic_id
    save_autopost_config(config)
    del search_cache[user_id]
    log_admin_action(user_id, f"Изменил канал автопостинга", details=f"channel_id={channel_id}, topic_id={topic_id}")
    bot.reply_to(message, f"✅ Канал установлен: {channel_id}")

def handle_autopost_set_interval(message):
    user_id = message.from_user.id
    try:
        minutes = int(message.text.strip())
        if minutes < 5 or minutes > 1440:
            bot.reply_to(message, "❌ 5-1440 минут")
            return
        config = get_autopost_config()
        config['interval'] = minutes * 60
        save_autopost_config(config)
        del search_cache[user_id]
        log_admin_action(user_id, f"Изменил интервал автопостинга", details=f"{minutes} мин")
        bot.reply_to(message, f"✅ Интервал: {minutes} мин")
    except:
        bot.reply_to(message, "❌ Введите число")

def handle_add_admin_input(message):
    user_id = message.from_user.id
    if not has_permission(user_id, 'manage_admins'):
        return
    target_id = get_user_id_from_input(message.text.strip())
    if not target_id:
        bot.reply_to(message, "❌ Неверный ID или юзернейм.")
        return
    if target_id == ADMIN_ID:
        bot.reply_to(message, "❌ Это владелец бота.")
        return
    if is_admin(target_id):
        bot.reply_to(message, "❌ Пользователь уже является админом.")
        return
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT user_id FROM users WHERE user_id = %s", (target_id,))
        user_exists = cur.fetchone()
    finally:
        cur.close()
        return_db_connection(conn)
    if not user_exists:
        bot.reply_to(message, "❌ Пользователь не зарегистрирован в боте.")
        return
    role = search_cache[user_id].get('role', 'junior')
    perms = ROLE_PRESETS[role]['permissions'].copy()
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO admins (user_id, role, permissions, added_by, added_at) VALUES (%s, %s, %s, %s, %s)",
            (target_id, role, json.dumps(perms), user_id, int(time.time()))
        )
        conn.commit()
    finally:
        cur.close()
        return_db_connection(conn)
    del search_cache[user_id]
    name = get_user_display_name_cached(target_id)
    log_admin_action(user_id, f"Добавил админа {target_id}", target_id=target_id, details=f"Роль: {role}")
    bot.reply_to(message, f"✅ {name} (`{target_id}`) назначен {ROLE_PRESETS[role]['name']}!")
    try:
        bot.send_message(target_id, f"👑 Вам назначена роль {ROLE_PRESETS[role]['name']}!\n\nТеперь вы имеете доступ к админ-панели (/admin)")
    except:
        pass

def admin_announce_text(message):
    user_id = message.from_user.id
    if user_id not in announce_data:
        return
    data = announce_data[user_id]
    del announce_data[user_id]
    announce_type = data.get('type', 'dm')
    text = message.text
    caption = message.caption or ''
    
    if announce_type == 'dm':
        if not text and not message.photo and not message.video and not message.document:
            bot.reply_to(message, "❌ Отправьте текст или медиа.")
            return
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT user_id FROM users")
            users = cur.fetchall()
        finally:
            cur.close()
            return_db_connection(conn)
        sent = 0
        for (uid,) in users:
            try:
                if is_blocked(uid):
                    continue
                if message.photo:
                    bot.send_photo(uid, message.photo[-1].file_id, caption=caption)
                elif message.video:
                    bot.send_video(uid, message.video.file_id, caption=caption)
                elif message.document:
                    bot.send_document(uid, message.document.file_id, caption=caption)
                else:
                    bot.send_message(uid, text)
                sent += 1
                time.sleep(0.05)
            except:
                pass
        log_admin_action(user_id, f"Сделал рассылку в ЛС", details=f"Отправлено: {sent} пользователей")
        bot.reply_to(message, f"✅ Отправлено {sent} пользователям")
    elif announce_type == 'channel':
        channel_id = data.get('channel_id')
        try:
            if message.photo:
                bot.send_photo(channel_id, message.photo[-1].file_id, caption=caption)
            elif message.video:
                bot.send_video(channel_id, message.video.file_id, caption=caption)
            elif message.document:
                bot.send_document(channel_id, message.document.file_id, caption=caption)
            else:
                bot.send_message(channel_id, text)
            log_admin_action(user_id, f"Отправил объявление в канал {channel_id}")
            bot.reply_to(message, "✅ Отправлено")
        except Exception as e:
            bot.reply_to(message, f"❌ Ошибка: {e}")
    elif announce_type == 'all_channels':
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT channel_id FROM autopost_channels WHERE enabled = TRUE")
            channels = cur.fetchall()
        finally:
            cur.close()
            return_db_connection(conn)
        if not channels:
            bot.reply_to(message, "❌ Нет активных каналов.")
            return
        sent = 0
        for (ch_id,) in channels:
            try:
                if message.photo:
                    bot.send_photo(ch_id, message.photo[-1].file_id, caption=caption)
                elif message.video:
                    bot.send_video(ch_id, message.video.file_id, caption=caption)
                elif message.document:
                    bot.send_document(ch_id, message.document.file_id, caption=caption)
                else:
                    bot.send_message(ch_id, text)
                sent += 1
                time.sleep(0.3)
            except:
                pass
        log_admin_action(user_id, f"Сделал рассылку во все каналы", details=f"Отправлено: {sent} каналов")
        bot.reply_to(message, f"✅ Отправлено в {sent} каналов")

# ==================== ОБРАБОТЧИК ПРИВАТНЫХ СООБЩЕНИЙ ====================

@bot.message_handler(func=lambda m: m.chat.type == 'private' and not (m.text or '').startswith('/'))
def handle_private_messages(message):
    user_id = message.from_user.id
    text = message.text or ''

    if message.from_user.username:
        update_user_username(user_id, message.from_user.username)

    if text in MENU_BUTTONS:
        return

    if user_id in proxy_url_loading:
        handle_proxy_url_input(message)
        return

    if user_id in announce_data:
        admin_announce_text(message)
        return

    if user_id in autopost_loading:
        handle_autopost_load_keys(message)
        return

    if user_id in decrypt_results and decrypt_results[user_id].get('waiting'):
        if message.document:
            try:
                file = bot.get_file(message.document.file_id)
                data = bot.download_file(file.file_path)
                _do_decrypt(message, user_id, file_bytes=data, file_name=message.document.file_name)
            except Exception as e:
                bot.reply_to(message, f"❌ Ошибка: {e}")
            return
        if text:
            _do_decrypt(message, user_id, text=text)
        return

    if user_id in search_cache:
        action = search_cache.get(user_id, {}).get('action', '')
        if action == 'autopost_set_channel':
            handle_autopost_set_channel(message)
            return
        if action == 'autopost_set_interval':
            handle_autopost_set_interval(message)
            return
        if action == 'add_admin':
            handle_add_admin_input(message)
            return
        if action == 'add_points_chat':
            try:
                new_chat_id = int(message.text.strip())
                try:
                    chat_info = bot.get_chat(new_chat_id)
                    chat_name = chat_info.title or str(new_chat_id)
                except:
                    chat_name = str(new_chat_id)
                
                conn = get_db_connection()
                cur = conn.cursor()
                try:
                    cur.execute("""
                        INSERT INTO points_chats (chat_id, chat_name, enabled, points_per_message, added_by, added_at)
                        VALUES (%s, %s, TRUE, 1, %s, %s)
                        ON CONFLICT (chat_id) DO UPDATE SET chat_name = %s
                    """, (new_chat_id, chat_name, user_id, int(time.time()), chat_name))
                    conn.commit()
                finally:
                    cur.close()
                    return_db_connection(conn)
                
                del search_cache[user_id]
                log_admin_action(user_id, f"Добавил чат {new_chat_id} в систему баллов", details=f"Название: {chat_name}")
                bot.reply_to(message, f"✅ Чат *{chat_name}* добавлен!\n\nТеперь сообщения в нём будут приносить баллы.", parse_mode="Markdown")
            except:
                bot.reply_to(message, "❌ Неверный ID чата")
            return
        elif action == 'set_points':
            target_id = search_cache[user_id].get('target_id')
            if not target_id:
                del search_cache[user_id]
                return
            try:
                new_points = int(message.text.strip())
                if new_points < 0:
                    raise ValueError
            except ValueError:
                bot.reply_to(message, "❌ Введите целое неотрицательное число.")
                return

            conn = get_db_connection()
            cur = conn.cursor()
            try:
                cur.execute("SELECT points FROM users WHERE user_id = %s", (target_id,))
                result = cur.fetchone()
                if not result:
                    bot.reply_to(message, "❌ Пользователь не найден.")
                    del search_cache[user_id]
                    return
                old_points = result[0] or 0
                cur.execute("UPDATE users SET points = %s WHERE user_id = %s", (new_points, target_id))
                conn.commit()
            finally:
                cur.close()
                return_db_connection(conn)

            del search_cache[user_id]
            name = get_user_display_name_cached(target_id)
            rank_info = get_rank(new_points)
            log_admin_action(
                user_id, f"Установил баллы {target_id}",
                target_id=target_id,
                details=f"{old_points} → {new_points}"
            )
            bot.reply_to(
                message,
                f"✅ *{name}*\n\n"
                f"🪙 Было: `{old_points:,}`\n"
                f"🪙 Установлено: `{new_points:,}`\n"
                f"{rank_info['name']}",
                parse_mode="Markdown"
            )
            try:
                bot.send_message(
                    target_id,
                    f"🪙 Администратор установил ваши баллы.\n\n"
                    f"💰 Новый баланс: {new_points:,}\n"
                    f"{rank_info['name']}"
                )
            except:
                pass
            return

    if text:
        bot.reply_to(message, "Используйте кнопки меню или /cancel для отмены текущего режима.", reply_markup=main_menu())

# ==================== PRIORITY COMMAND HANDLER ====================

@bot.message_handler(commands=['admin', 'check', 'user', 'add_days', 'remove_days', 
                                'block', 'unblock', 'cancel', 'ref', 'ref_debug', 
                                'add_admin', 'remove_admin', 'logs', 'points', 'set_points'])
def cmd_priority_handler(message):
    user_id = message.from_user.id
    command = message.text.split()[0].lower() if message.text else ''
    
    if user_id in decrypt_results:
        del decrypt_results[user_id]
    if user_id in autopost_loading:
        del autopost_loading[user_id]
    if user_id in announce_data:
        del announce_data[user_id]
    if user_id in proxy_url_loading:
        del proxy_url_loading[user_id]

    if command == '/admin':
        admin_panel(message)
    elif command == '/check':
        cmd_check_user(message)
    elif command == '/user':
        cmd_user_info(message)
    elif command == '/add_days':
        cmd_add_days(message)
    elif command == '/remove_days':
        cmd_remove_days(message)
    elif command == '/block':
        cmd_block_user(message)
    elif command == '/unblock':
        cmd_unblock_user(message)
    elif command == '/cancel':
        cmd_cancel(message)
    elif command == '/ref':
        cmd_ref_link(message)
    elif command == '/ref_debug':
        cmd_ref_debug(message)
    elif command == '/add_admin':
        cmd_add_admin(message)
    elif command == '/remove_admin':
        cmd_remove_admin(message)
    elif command == '/logs':
        cmd_view_logs(message)
    elif command == '/points':
        cmd_points(message)
    elif command == '/set_points':
        cmd_set_points(message)

# ==================== ADMINS COMMANDS ====================

def admin_panel(message):
    if message.chat.type != 'private':
        return
    user_id = message.from_user.id
    if not is_admin(user_id):
        bot.reply_to(message, "⛔️ У вас нет прав администратора.")
        return
    if not has_permission(user_id, 'admin_panel'):
        bot.reply_to(message, "⛔️ У вас нет доступа к админ-панели.")
        return
    role_name = get_admin_role_name(user_id)
    bot.send_message(user_id, f"🏛️ Админ панель\n\n👤 Ваша роль: {role_name}", reply_markup=admin_menu())

def cmd_check_user(message):
    if message.chat.type != 'private':
        return
    user_id = message.from_user.id
    if not is_admin(user_id) or not has_permission(user_id, 'check_user'):
        return
    text = message.text.strip()
    parts = text.split(None, 1)
    if len(parts) < 2:
        bot.reply_to(message, "❌ /check [ID или @username]\n\nПример: `/check 123456789` или `/check @mel1ste` или `/check tg://user?id=123456789`", parse_mode="Markdown")
        return
    target_input = parts[1].strip()
    target_id = get_user_id_from_input(target_input)
    if not target_id:
        bot.reply_to(message, f"❌ Неверный ID или юзернейм: `{target_input}`")
        return
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT subscription_end, is_blocked, token FROM users WHERE user_id = %s", (target_id,))
        result = cur.fetchone()
        if not result:
            bot.reply_to(message, "❌ Не найден")
            return
        sub_end, blocked, token = result
        current_time = int(time.time())
        status = "🚫 Заблокирован" if blocked else ("✅ Активен" if sub_end > current_time else "❌ Неактивен")
        text = f"📋 *Проверка*\n🆔 ID: `{target_id}`\n📊 Статус: {status}\n🔗 Токен: `{token}`"
        log_admin_action(user_id, f"Проверил пользователя {target_id}", target_id=target_id)
        bot.reply_to(message, text, parse_mode="Markdown")
    finally:
        cur.close()
        return_db_connection(conn)

def cmd_user_info(message):
    if message.chat.type != 'private':
        return
    user_id = message.from_user.id
    if not is_admin(user_id) or not has_permission(user_id, 'user_info'):
        return
    text = message.text.strip()
    parts = text.split(None, 1)
    if len(parts) < 2:
        bot.reply_to(message, "❌ /user [ID или @username]\n\nПример: `/user 123456789` или `/user @mel1ste` или `/user tg://user?id=123456789`", parse_mode="Markdown")
        return
    target_input = parts[1].strip()
    target_id = get_user_id_from_input(target_input)
    if not target_id:
        bot.reply_to(message, f"❌ Неверный ID или юзернейм: `{target_input}`")
        return
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT subscription_end, is_blocked, token, last_activity, points FROM users WHERE user_id = %s", (target_id,))
        result = cur.fetchone()
        if not result:
            bot.reply_to(message, "❌ Не найден")
            return
        sub_end, blocked, token, last_act, points = result
        current_time = int(time.time())
        status = "🚫 Заблокирован" if blocked else ("✅ Активен" if sub_end > current_time else "❌ Неактивен")
        name = get_user_display_name_cached(target_id)
        last_act_str = datetime.fromtimestamp(last_act).strftime("%d.%m.%Y %H:%M") if last_act else "Нет"
        points = points or 0
        rank = get_rank(points)
        text = f"""👤 *{name}*
🆔 ID: `{target_id}`
📊 Статус: {status}
📅 Подписка до: {datetime.fromtimestamp(sub_end).strftime('%d.%m.%Y') if sub_end else 'Нет'}
🕐 Активность: {last_act_str}
🪙 Баллов: {points}
{rank['name']}"""
        log_admin_action(user_id, f"Посмотрел инфо о {target_id}", target_id=target_id)
        bot.reply_to(message, text, parse_mode="Markdown")
    finally:
        cur.close()
        return_db_connection(conn)

def cmd_add_days(message):
    user_id = message.from_user.id
    if not is_admin(user_id) or not has_permission(user_id, 'add_days'):
        return
    text = message.text.strip()
    parts = text.split(None, 1)
    if len(parts) < 2:
        bot.reply_to(message, "❌ /add_days [ID или @username] [дни]\n\nПример: `/add_days 123456789 30` или `/add_days @mel1ste 30` или `/add_days tg://user?id=123456789 30`", parse_mode="Markdown")
        return
    args = parts[1].strip().split()
    if len(args) < 2:
        bot.reply_to(message, "❌ /add_days [ID или @username] [дни]", parse_mode="Markdown")
        return
    target_id = get_user_id_from_input(args[0])
    if not target_id:
        bot.reply_to(message, f"❌ Неверный ID или юзернейм: `{args[0]}`")
        return
    try:
        days = int(args[1])
    except:
        bot.reply_to(message, "❌ Дни должны быть числом")
        return
    if days < 1:
        bot.reply_to(message, "❌ Количество дней должно быть больше 0.")
        return
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT subscription_end FROM users WHERE user_id = %s", (target_id,))
        result = cur.fetchone()
        if not result:
            bot.reply_to(message, "❌ Не найден")
            return
        current_time = int(time.time())
        current_end = result[0] if (result[0] and result[0] > current_time) else current_time
        new_end = current_end + days * 24 * 60 * 60
        cur.execute("UPDATE users SET subscription_end = %s, notified_3days = 0 WHERE user_id = %s", (new_end, target_id))
        conn.commit()
        log_admin_action(user_id, f"Выдал {days} дней {target_id}", target_id=target_id)
        bot.reply_to(message, f"✅ +{days} дней")
    finally:
        cur.close()
        return_db_connection(conn)

def cmd_remove_days(message):
    user_id = message.from_user.id
    if not is_admin(user_id) or not has_permission(user_id, 'remove_days'):
        return
    text = message.text.strip()
    parts = text.split(None, 1)
    if len(parts) < 2:
        bot.reply_to(message, "❌ /remove_days [ID или @username] [дни]\n\nПример: `/remove_days 123456789 30` или `/remove_days @mel1ste 30` или `/remove_days tg://user?id=123456789 30`", parse_mode="Markdown")
        return
    args = parts[1].strip().split()
    if len(args) < 2:
        bot.reply_to(message, "❌ /remove_days [ID или @username] [дни]", parse_mode="Markdown")
        return
    target_id = get_user_id_from_input(args[0])
    if not target_id:
        bot.reply_to(message, f"❌ Неверный ID или юзернейм: `{args[0]}`")
        return
    try:
        days = int(args[1])
    except:
        bot.reply_to(message, "❌ Дни должны быть числом")
        return
    if days < 1:
        bot.reply_to(message, "❌ Количество дней должно быть больше 0.")
        return
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT subscription_end FROM users WHERE user_id = %s", (target_id,))
        result = cur.fetchone()
        if not result:
            bot.reply_to(message, "❌ Не найден")
            return
        current_time = int(time.time())
        current_end = result[0] if (result[0] and result[0] > current_time) else current_time
        new_end = current_end - days * 24 * 60 * 60
        if new_end < current_time:
            new_end = current_time - 1
        cur.execute("UPDATE users SET subscription_end = %s, notified_3days = 0 WHERE user_id = %s", (new_end, target_id))
        conn.commit()
        log_admin_action(user_id, f"Забрал {days} дней у {target_id}", target_id=target_id)
        bot.reply_to(message, f"✅ -{days} дней")
    finally:
        cur.close()
        return_db_connection(conn)

def cmd_block_user(message):
    user_id = message.from_user.id
    if not is_admin(user_id) or not has_permission(user_id, 'block_user'):
        return
    text = message.text.strip()
    parts = text.split(None, 1)
    if len(parts) < 2:
        bot.reply_to(message, "❌ /block [ID или @username]\n\nПример: `/block 123456789` или `/block @mel1ste` или `/block tg://user?id=123456789`", parse_mode="Markdown")
        return
    target_input = parts[1].strip()
    target_id = get_user_id_from_input(target_input)
    if not target_id:
        bot.reply_to(message, f"❌ Неверный ID или юзернейм: `{target_input}`")
        return
    if target_id == ADMIN_ID:
        bot.reply_to(message, "❌ Нельзя заблокировать создателя.")
        return
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE users SET is_blocked = 1 WHERE user_id = %s", (target_id,))
        conn.commit()
        log_admin_action(user_id, f"Заблокировал {target_id}", target_id=target_id)
        bot.reply_to(message, f"🚫 Заблокирован {target_id}")
    finally:
        cur.close()
        return_db_connection(conn)

def cmd_unblock_user(message):
    user_id = message.from_user.id
    if not is_admin(user_id) or not has_permission(user_id, 'unblock_user'):
        return
    text = message.text.strip()
    parts = text.split(None, 1)
    if len(parts) < 2:
        bot.reply_to(message, "❌ /unblock [ID или @username]\n\nПример: `/unblock 123456789` или `/unblock @mel1ste` или `/unblock tg://user?id=123456789`", parse_mode="Markdown")
        return
    target_input = parts[1].strip()
    target_id = get_user_id_from_input(target_input)
    if not target_id:
        bot.reply_to(message, f"❌ Неверный ID или юзернейм: `{target_input}`")
        return
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE users SET is_blocked = 0 WHERE user_id = %s", (target_id,))
        conn.commit()
        log_admin_action(user_id, f"Разблокировал {target_id}", target_id=target_id)
        bot.reply_to(message, f"✅ Разблокирован {target_id}")
    finally:
        cur.close()
        return_db_connection(conn)

def cmd_cancel(message):
    if message.chat.type != 'private':
        return
    user_id = message.from_user.id
    cleared = False
    if user_id in decrypt_results:
        del decrypt_results[user_id]
        cleared = True
    if user_id in autopost_loading:
        del autopost_loading[user_id]
        cleared = True
    if user_id in announce_data:
        del announce_data[user_id]
        cleared = True
    if user_id in proxy_url_loading:
        del proxy_url_loading[user_id]
        cleared = True
    if cleared:
        bot.reply_to(message, "✅ Все режимы отменены.")
    else:
        bot.reply_to(message, "❌ Нет активных режимов для отмены.")

def cmd_ref_link(message):
    user_id = message.from_user.id
    if is_blocked(user_id):
        bot.reply_to(message, blocked_message())
        return
    bot_username = bot.get_me().username
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    bot.reply_to(message, f"🔗 *Реферальная ссылка:*\n`{ref_link}`", parse_mode="Markdown")

def cmd_ref_debug(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, referrer_id, referred_id, rewarded FROM referrals ORDER BY id DESC LIMIT 10")
        rows = cur.fetchall()
        if not rows:
            bot.reply_to(message, "📭 Нет рефералов")
            return
        text = "📊 *Рефералы (последние 10):*\n\n"
        for ref_id, refr, refd, rew in rows:
            text += f"{'✅' if rew else '⏳'} {get_user_display_name_cached(refd)} → {get_user_display_name_cached(refr)}\n"
        bot.reply_to(message, text, parse_mode="Markdown")
    finally:
        cur.close()
        return_db_connection(conn)

def cmd_add_admin(message):
    if message.chat.type != 'private':
        return
    user_id = message.from_user.id
    if not has_permission(user_id, 'manage_admins'):
        bot.reply_to(message, "⛔️ У вас нет прав на управление админами.")
        return
    text = message.text.strip()
    parts = text.split(None, 1)
    if len(parts) < 2:
        bot.reply_to(message, "❌ Использование: `/add_admin [ID или @username]`\n\nПример: `/add_admin 123456789` или `/add_admin @mel1ste` или `/add_admin tg://user?id=123456789`", parse_mode="Markdown")
        return
    target_input = parts[1].strip()
    target_id = get_user_id_from_input(target_input)
    if not target_id:
        bot.reply_to(message, f"❌ Не удалось найти пользователя: `{target_input}`\n\nПроверьте правильность ID, @username или ссылки.", parse_mode="Markdown")
        return
    if target_id == ADMIN_ID:
        bot.reply_to(message, "❌ Это владелец бота.")
        return
    if is_admin(target_id):
        bot.reply_to(message, "❌ Пользователь уже является админом.")
        return
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT user_id FROM users WHERE user_id = %s", (target_id,))
        user_exists = cur.fetchone()
    finally:
        cur.close()
        return_db_connection(conn)
    if not user_exists:
        bot.reply_to(message, f"❌ Пользователь `{target_id}` не зарегистрирован в боте.", parse_mode="Markdown")
        return
    role = 'junior'
    perms = ROLE_PRESETS[role]['permissions'].copy()
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO admins (user_id, role, permissions, added_by, added_at) VALUES (%s, %s, %s, %s, %s)",
            (target_id, role, json.dumps(perms), user_id, int(time.time()))
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        bot.reply_to(message, f"❌ Ошибка БД: {e}")
        return
    finally:
        cur.close()
        return_db_connection(conn)
    name = get_user_display_name_cached(target_id)
    log_admin_action(user_id, f"Добавил админа {target_id}", target_id=target_id, details=f"Роль: {role}")
    bot.reply_to(message, f"✅ {name} (`{target_id}`) назначен админом!", parse_mode="Markdown")
    try:
        bot.send_message(target_id, "👑 Вам назначена роль администратора!\n\nТеперь вы имеете доступ к админ-панели (/admin)")
    except:
        pass

def cmd_remove_admin(message):
    if message.chat.type != 'private':
        return
    user_id = message.from_user.id
    if not has_permission(user_id, 'manage_admins'):
        bot.reply_to(message, "⛔️ У вас нет прав на управление админами.")
        return
    text = message.text.strip()
    parts = text.split(None, 1)
    if len(parts) < 2:
        bot.reply_to(message, "❌ Использование: `/remove_admin [ID или @username]`\n\nПример: `/remove_admin 123456789` или `/remove_admin @mel1ste` или `/remove_admin tg://user?id=123456789`", parse_mode="Markdown")
        return
    target_input = parts[1].strip()
    target_id = get_user_id_from_input(target_input)
    if not target_id:
        bot.reply_to(message, f"❌ Не удалось найти пользователя: `{target_input}`", parse_mode="Markdown")
        return
    if target_id == ADMIN_ID:
        bot.reply_to(message, "❌ Нельзя удалить владельца.")
        return
    if not is_admin(target_id):
        bot.reply_to(message, "❌ Пользователь не является админом.")
        return
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM admins WHERE user_id = %s", (target_id,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        bot.reply_to(message, f"❌ Ошибка БД: {e}")
        return
    finally:
        cur.close()
        return_db_connection(conn)
    name = get_user_display_name_cached(target_id)
    log_admin_action(user_id, f"Удалил админа {target_id}", target_id=target_id)
    bot.reply_to(message, f"✅ У {name} (`{target_id}`) отозваны права администратора!", parse_mode="Markdown")
    try:
        bot.send_message(target_id, "❌ Ваши права администратора были отозваны.")
    except:
        pass

def cmd_view_logs(message):
    if message.chat.type != 'private':
        return
    user_id = message.from_user.id
    if not is_admin(user_id) or not has_permission(user_id, 'view_logs'):
        bot.reply_to(message, "⛔️ У вас нет прав на просмотр логов.")
        return
    
    text = message.text.strip()
    parts = text.split(None, 1)
    limit = 20
    if len(parts) > 1:
        try:
            limit = int(parts[1])
            if limit > 100:
                limit = 100
        except:
            pass
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT admin_name, action, target_name, details, created_at
            FROM admin_logs
            ORDER BY created_at DESC
            LIMIT %s
        """, (limit,))
        logs = cur.fetchall()
    finally:
        cur.close()
        return_db_connection(conn)
    
    if not logs:
        bot.reply_to(message, "📋 *Логи админов*\n\nПусто", parse_mode="Markdown")
        return
    
    text = f"📋 *Последние {len(logs)} действий:*\n\n"
    for admin_name, action, target_name, details, created_at in logs:
        time_str = datetime.fromtimestamp(created_at).strftime("%d.%m %H:%M")
        target = f" → {target_name}" if target_name else ""
        text += f"🕐 {time_str} | *{admin_name}* {action}{target}\n"
        if details:
            text += f"  📎 {details}\n"
        text += "\n"
    
    if len(text) > 4000:
        text = text[:3950] + "\n…"
    
    bot.reply_to(message, text, parse_mode="Markdown")

# ==================== НОВЫЕ КОМАНДЫ ДЛЯ УПРАВЛЕНИЯ БАЛЛАМИ ====================

def cmd_points(message):
    """/points [ID или @username] [+/-число] — добавить/убрать баллы"""
    if message.chat.type != 'private':
        return
    user_id = message.from_user.id
    if not is_admin(user_id) or not has_permission(user_id, 'points_system'):
        bot.reply_to(message, "⛔️ Нет прав.")
        return

    text = message.text.strip()
    parts = text.split(None, 1)
    if len(parts) < 2:
        bot.reply_to(
            message,
            "❌ Использование:\n"
            "`/points @user +500` — добавить 500\n"
            "`/points @user -200` — убрать 200\n"
            "`/points @user 0` — обнулить",
            parse_mode="Markdown"
        )
        return

    args = parts[1].strip().split()
    if len(args) < 2:
        bot.reply_to(message, "❌ Укажите пользователя и количество баллов.")
        return

    target_id = get_user_id_from_input(args[0])
    if not target_id:
        bot.reply_to(message, f"❌ Неверный ID или юзернейм: `{args[0]}`", parse_mode="Markdown")
        return

    raw = args[1].strip()
    try:
        amount = int(raw)
    except ValueError:
        bot.reply_to(message, "❌ Количество баллов должно быть числом. Пример: `+500`, `-200`, `0`", parse_mode="Markdown")
        return

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT points FROM users WHERE user_id = %s", (target_id,))
        result = cur.fetchone()
        if not result:
            bot.reply_to(message, "❌ Пользователь не найден.")
            return

        old_points = result[0] or 0

        # Если передано просто число без знака — это абсолютное значение (обнуление = 0)
        if raw.startswith('+') or raw.startswith('-'):
            new_points = max(0, old_points + amount)
            action_text = f"{'добавлено' if amount > 0 else 'убрано'} {abs(amount)}"
        else:
            # Абсолютное значение
            new_points = max(0, amount)
            action_text = f"установлено {new_points}"

        cur.execute("UPDATE users SET points = %s WHERE user_id = %s", (new_points, target_id))
        conn.commit()
    finally:
        cur.close()
        return_db_connection(conn)

    name = get_user_display_name_cached(target_id)
    rank = get_rank(new_points)
    log_admin_action(
        user_id,
        f"Изменил баллы {target_id}",
        target_id=target_id,
        details=f"Было: {old_points} → Стало: {new_points} ({action_text})"
    )

    bot.reply_to(
        message,
        f"✅ *{name}*\n\n"
        f"🪙 Было: `{old_points:,}`\n"
        f"🪙 Стало: `{new_points:,}`\n"
        f"{rank['name']}\n"
        f"📝 Действие: {action_text}",
        parse_mode="Markdown"
    )

    # Уведомляем пользователя
    try:
        if amount > 0 or (not raw.startswith('-') and new_points > old_points):
            bot.send_message(
                target_id,
                f"🎁 Администратор начислил вам баллы!\n\n"
                f"🪙 +{new_points - old_points} баллов\n"
                f"💰 Итого: {new_points:,} баллов"
            )
        elif new_points < old_points:
            bot.send_message(
                target_id,
                f"⚠️ Администратор изменил ваши баллы.\n\n"
                f"🪙 Было: {old_points:,}\n"
                f"🪙 Стало: {new_points:,} баллов"
            )
    except:
        pass


def cmd_set_points(message):
    """Алиас: /set_points @user 1000 — устанавливает точное значение"""
    if message.chat.type != 'private':
        return
    user_id = message.from_user.id
    if not is_admin(user_id) or not has_permission(user_id, 'points_system'):
        bot.reply_to(message, "⛔️ Нет прав.")
        return

    text = message.text.strip()
    parts = text.split(None, 1)
    if len(parts) < 2:
        bot.reply_to(
            message,
            "❌ Использование: `/set_points @user 1000`\n\nУстанавливает точное количество баллов.",
            parse_mode="Markdown"
        )
        return

    args = parts[1].strip().split()
    if len(args) < 2:
        bot.reply_to(message, "❌ Укажите пользователя и количество.")
        return

    target_id = get_user_id_from_input(args[0])
    if not target_id:
        bot.reply_to(message, f"❌ Неверный ID: `{args[0]}`", parse_mode="Markdown")
        return

    try:
        new_points = int(args[1])
        if new_points < 0:
            raise ValueError
    except ValueError:
        bot.reply_to(message, "❌ Введите целое неотрицательное число.")
        return

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT points FROM users WHERE user_id = %s", (target_id,))
        result = cur.fetchone()
        if not result:
            bot.reply_to(message, "❌ Пользователь не найден.")
            return
        old_points = result[0] or 0
        cur.execute("UPDATE users SET points = %s WHERE user_id = %s", (new_points, target_id))
        conn.commit()
    finally:
        cur.close()
        return_db_connection(conn)

    name = get_user_display_name_cached(target_id)
    rank = get_rank(new_points)
    log_admin_action(
        user_id,
        f"Установил баллы {target_id}",
        target_id=target_id,
        details=f"{old_points} → {new_points}"
    )

    bot.reply_to(
        message,
        f"✅ *{name}*\n\n"
        f"🪙 Было: `{old_points:,}`\n"
        f"🪙 Установлено: `{new_points:,}`\n"
        f"{rank['name']}",
        parse_mode="Markdown"
    )
    try:
        bot.send_message(
            target_id,
            f"🪙 Ваш баланс баллов обновлён администратором.\n\n"
            f"💰 Новый баланс: {new_points:,} баллов\n"
            f"{rank['name']}"
        )
    except:
        pass

# ==================== FLASK APP ====================

@app.route('/')
def index():
    return "VPN Bot is running!"

@app.route('/ping')
def ping():
    return "OK", 200

@app.route('/health')
def health():
    return "OK", 200

# Rate limiting для /sub
_rate_limit = defaultdict(list)

def rate_limit(limit=10, window=60):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            ip = request.remote_addr
            now = time.time()
            _rate_limit[ip] = [t for t in _rate_limit[ip] if now - t < window]
            if len(_rate_limit[ip]) >= limit:
                return "Too many requests", 429
            _rate_limit[ip].append(now)
            return f(*args, **kwargs)
        return decorated
    return decorator

@app.route('/sub/<token>')
@rate_limit(limit=10, window=60)
def subscription(token):
    if not token:
        return "Invalid token", 400
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT user_id, subscription_end, is_frozen, is_blocked FROM users WHERE token = %s", (token,))
        result = cur.fetchone()
        if not result:
            return "Invalid token", 404
        user_id, sub_end, is_frozen, is_blocked = result
        
        if is_blocked:
            return "User blocked", 403
        
        cur.execute("UPDATE users SET last_activity = %s WHERE user_id = %s", (int(time.time()), user_id))
        conn.commit()
        
        current_time = int(time.time())
        
        if is_frozen:
            content = KEY_TEMPLATE.format(
                expire=int(time.time()),
                keys='# Подписка заморожена'
            )
            return content, 200, {'Content-Type': 'text/plain; charset=utf-8'}
        
        if sub_end < current_time:
            return "Subscription expired", 403
        keys = get_keys_from_db()
        if not keys:
            keys = DEFAULT_KEYS
        expire_timestamp = sub_end
        content = KEY_TEMPLATE.format(expire=expire_timestamp, keys='\n'.join(keys))
        return content, 200, {'Content-Type': 'text/plain; charset=utf-8'}
    finally:
        cur.close()
        return_db_connection(conn)

# ==================== ЗАПУСК ====================

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN не задан в переменных окружения!")
        sys.exit(1)
    if not DATABASE_URL:
        print("❌ DATABASE_URL не задан в переменных окружения!")
        sys.exit(1)
    
    print("🚀 Запуск бота...")
    
    init_db_pool()
    
    try:
        init_db()
        print("✅ База данных инициализирована")
    except Exception as e:
        print(f"❌ Ошибка инициализации базы данных: {e}")
        sys.exit(1)
    
    ensure_bot_start_time()
    print("✅ Время запуска сохранено")
    
    # Устанавливаем команды бота
    try:
        bot.set_my_commands([
            types.BotCommand("start", "Запустить бота"),
            types.BotCommand("bonus", "Получить ежедневный бонус"),
            types.BotCommand("top", "Топ активных участников"),
            types.BotCommand("rank", "Ваш ранг и баллы"),
            types.BotCommand("decrypt", "Расшифровать подписку"),
            types.BotCommand("modhelp", "Помощь по модерации"),
        ])
        print("✅ Команды бота установлены")
    except Exception as e:
        print(f"[set_commands] Ошибка: {e}")
    
    Thread(target=autopost_scheduler, daemon=True).start()
    Thread(target=auto_update_keys_scheduler, daemon=True).start()
    Thread(target=cleanup_sessions_scheduler, daemon=True).start()
    
    if os.getenv('RENDER'):
        print("📡 Запущен на Render, активируем keep-alive")
        Thread(target=keep_alive_ping, daemon=True).start()
        Thread(target=auto_restart_monitor, daemon=True).start()
    
    print("📡 Запускаем Flask сервер...")
    Thread(target=lambda: serve(app, host='0.0.0.0', port=int(os.getenv('PORT', 5000))), daemon=True).start()
    
    print("🤖 Бот запущен и готов к работе!")
    
    # Основной цикл polling с защитой от 409
    while True:
        try:
            # Сбрасываем webhook перед запуском polling
            bot.delete_webhook(drop_pending_updates=True)
            time.sleep(1)
            
            bot.infinity_polling(
                timeout=30,
                long_polling_timeout=30,
                allowed_updates=['message', 'callback_query', 'my_chat_member']
            )
        except Exception as e:
            err = str(e)
            if '409' in err:
                print(f"⚠️ Конфликт: другой экземпляр бота уже запущен. Ждём 30 сек...")
                time.sleep(30)
            else:
                print(f"❌ Ошибка в polling: {e}")
                print("🔄 Переподключение через 10 секунд...")
                time.sleep(10)
                try:
                    bot.delete_webhook(drop_pending_updates=True)
                except:
                    pass
