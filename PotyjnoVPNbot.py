import os
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
from datetime import datetime, timedelta
from threading import Thread

import telebot
from telebot import types
import psycopg2
import requests
from bs4 import BeautifulSoup
from flask import Flask

try:
    import socks
    SOCKS_AVAILABLE = True
except ImportError:
    SOCKS_AVAILABLE = False

# ==================== KEEP ALIVE ====================

def keep_alive_ping():
    url = os.getenv('RENDER_EXTERNAL_URL', 'https://potyjnovpnbot.onrender.com')
    if not url or url == 'https://potyjnovpnbot.onrender.com':
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

def update_activity():
    global last_activity_time
    last_activity_time = time.time()

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

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)

check_results = {}
search_cache = {}
decrypt_results = {}
proxy_check_results = {}
loading_sessions = {}
announce_data = {}
channel_selection = {}
manage_cache = {}
captcha_sessions = {}
autopost_history = {}
autopost_active = {}
admin_keys_loading = {}
autopost_loading = {}

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

VPN_KEY_PATTERN = r'(?:vless|vmess|trojan|ss|ssr|hysteria2?|hy2|tuic|naive\+https?|wg|wireguard|juicity|brook|shadowtls)://[^\s\r\n<>"\'`]+'

APP_SCHEMES = (
    r'incy|happ|v2ray|v2rayng|v2box|clash|sing-box|quantumult|surge|loon|'
    r'shadowrocket|stash|nekoray|nekobox|hiddify|streisand|karing|mihomo|flclash'
)

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
            'admin_panel': True,
        }
    },
    'junior': {
        'name': '🔹 Младший админ',
        'permissions': {
            'check_user': True, 'user_info': True, 'add_days': True, 'remove_days': True,
            'block_user': True, 'unblock_user': True, 'announce': False, 'manage_keys': False,
            'autopost': False, 'manage_admins': False, 'manage_users': False, 'admin_stats': False,
            'admin_panel': True,
        }
    },
    'support': {
        'name': '🟢 Поддержка',
        'permissions': {
            'check_user': True, 'user_info': True, 'add_days': False, 'remove_days': False,
            'block_user': False, 'unblock_user': False, 'announce': False, 'manage_keys': False,
            'autopost': False, 'manage_admins': False, 'manage_users': False, 'admin_stats': False,
            'admin_panel': False,
        }
    }
}

def get_admin_permissions(user_id):
    if user_id == ADMIN_ID:
        return ROLE_PRESETS['owner']['permissions'].copy()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT permissions FROM admins WHERE user_id = %s", (user_id,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    if result and result[0]:
        try:
            return json.loads(result[0])
        except:
            pass
    return {p: False for p in PERMISSIONS}

def has_permission(user_id, permission):
    if user_id == ADMIN_ID:
        return True
    perms = get_admin_permissions(user_id)
    return perms.get(permission, False)

def update_admin_permissions(user_id, permissions_dict):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE admins SET permissions = %s WHERE user_id = %s", (json.dumps(permissions_dict), user_id))
    conn.commit()
    cur.close()
    conn.close()

def get_admin_role(user_id):
    if user_id == ADMIN_ID:
        return 'owner'
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT role FROM admins WHERE user_id = %s", (user_id,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    return result[0] if result else None

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
        cur.execute("SELECT user_id FROM admins WHERE user_id = %s", (user_id,))
        result = cur.fetchone()
        cur.close()
        conn.close()
        return result is not None
    except:
        return False

# ==================== DATABASE ====================

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
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
    cur.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            user_id BIGINT PRIMARY KEY,
            role TEXT DEFAULT 'junior',
            permissions TEXT,
            added_by BIGINT,
            added_at BIGINT
        )
    """)
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

    conn.commit()
    cur.close()
    conn.close()
    init_autopost_tables()

def get_setting(key, default='0'):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key = %s", (key,))
        result = cur.fetchone()
        cur.close()
        conn.close()
        return result[0] if result else default
    except:
        return default

def set_setting(key, value):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = %s",
        (key, value, value)
    )
    conn.commit()
    cur.close()
    conn.close()

def increment_setting(key, by=1):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO settings (key, value) VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE
        SET value = (COALESCE(settings.value, '0')::bigint + %s)::text
        RETURNING value
    """, (key, str(by), by))
    new_value = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return int(new_value)

def get_keys_from_db():
    val = get_setting('vless_keys', '')
    if not val:
        return []
    return [k for k in val.split('|||') if k]

def save_keys_to_db(keys):
    set_setting('vless_keys', '|||'.join(keys))

def generate_subscription_token():
    chars = string.ascii_letters + string.digits
    while True:
        token = ''.join(random.choices(chars, k=12))
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE token = %s", (token,))
        exists = cur.fetchone()
        cur.close()
        conn.close()
        if not exists:
            return token

def get_next_file_number():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO settings (key, value) VALUES ('decrypt_file_counter', '1')
        ON CONFLICT (key) DO UPDATE
        SET value = (COALESCE(settings.value, '0')::integer + 1)::text
        RETURNING value
    """)
    new_value = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return int(new_value)

def ensure_bot_start_time():
    existing = get_setting('bot_start_time', '')
    if not existing:
        set_setting('bot_start_time', str(int(time.time())))

# ==================== AUTO POSTING TABLES ====================

def init_autopost_tables():
    conn = get_db_connection()
    cur = conn.cursor()
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
    cur.close()
    conn.close()
    add_default_channel()

def add_default_channel():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM autopost_channels WHERE is_default = TRUE")
    if not cur.fetchone():
        cur.execute("""
            INSERT INTO autopost_channels 
            (channel_id, channel_name, topic_id, created_by, created_at, is_default, enabled)
            VALUES (%s, %s, %s, %s, %s, TRUE, TRUE)
        """, (AUTO_POST_CHANNEL, "Ciorsa VPN", AUTO_POST_TOPIC_ID, ADMIN_ID, int(time.time())))
        conn.commit()
    cur.close()
    conn.close()

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
    return [k.strip().rstrip('.,;"\')>]}') for k in keys]

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
    return _parse_keys_from_content(content)

def load_keys_from_text(text):
    return _parse_keys_from_content(text)

def _parse_keys_from_content(content):
    all_keys = []
    if not content:
        return []
    all_keys.extend(_extract_vpn_keys(content))
    cleaned = re.sub(r'\s+', '', content.strip())
    if len(cleaned) >= 20 and re.match(r'^[A-Za-z0-9+/_\-=]+$', cleaned):
        decoded = _try_multilevel_b64(cleaned, max_depth=5)
        if decoded:
            for item in decoded:
                all_keys.extend(_extract_vpn_keys(item))
                all_keys.extend(_try_multilevel_b64(item, max_depth=3))
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        all_keys.extend(_extract_vpn_keys(line))
        if len(line) >= 16 and re.match(r'^[A-Za-z0-9+/_\-=]+$', line):
            all_keys.extend(_try_multilevel_b64(line, max_depth=4))
        urls = re.findall(r'https?://[^\s<>"\']+', line)
        for url in urls:
            try:
                resp = requests.get(url, timeout=10, headers={'User-Agent': 'v2rayNG/1.8.7'})
                if resp.status_code == 200:
                    all_keys.extend(_parse_keys_from_content(resp.text))
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
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT token FROM users WHERE user_id = %s", (user_id,))
    result = cur.fetchone()
    if result and result[0]:
        token = result[0]
        cur.close()
        conn.close()
        return f"https://potyjnovpnbot.onrender.com/sub/{token}"
    token = generate_subscription_token()
    cur.execute("UPDATE users SET token = %s WHERE user_id = %s", (token, user_id))
    conn.commit()
    cur.close()
    conn.close()
    return f"https://potyjnovpnbot.onrender.com/sub/{token}"

def is_blocked(user_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT is_blocked FROM users WHERE user_id = %s", (user_id,))
        result = cur.fetchone()
        cur.close()
        conn.close()
        return result[0] == 1 if result else False
    except:
        return False

def can_add_referral(referrer_id):
    today_start = int(time.time()) - 24 * 60 * 60
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM referrals WHERE referrer_id = %s AND reward_date > %s",
        (referrer_id, today_start)
    )
    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return count < 10

def get_user_display_name(user_id):
    try:
        chat = bot.get_chat(user_id)
        name = chat.first_name or ''
        if chat.last_name:
            name += ' ' + chat.last_name
        return name.strip() or str(user_id)
    except:
        return str(user_id)

def get_user_id_from_input(user_input):
    user_input = user_input.strip()
    if user_input.startswith('@'):
        username = user_input.lstrip('@')
        try:
            chat = bot.get_chat(f"@{username}")
            return chat.id
        except Exception as e:
            print(f"[get_user_id] Ошибка получения юзернейма {username}: {e}")
            return None
    try:
        return int(user_input)
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
    if not is_subscribed(referred_id):
        return False, "Реферал не подписан на канал"
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id = %s", (referrer_id,))
    if not cur.fetchone():
        cur.close()
        conn.close()
        return False, "Реферер не найден"
    cur.execute(
        "SELECT * FROM referrals WHERE referrer_id = %s AND referred_id = %s",
        (referrer_id, referred_id)
    )
    if cur.fetchone():
        cur.close()
        conn.close()
        return False, "Этот пользователь уже был приглашен"
    if not can_add_referral(referrer_id):
        cur.close()
        conn.close()
        return False, "Лимит рефералов (10 в день) превышен"
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
            cur.execute("UPDATE users SET subscription_end = %s WHERE user_id = %s", (new_end, referrer_id))
            cur.execute(
                "UPDATE referrals SET rewarded = 1 WHERE referrer_id = %s AND referred_id = %s",
                (referrer_id, referred_id)
            )
            conn.commit()
            cur.close()
            conn.close()
            try:
                bot.send_message(referrer_id, "🎉 Вам начислено +3 дня за нового реферала!")
            except:
                pass
            return True, "Реферал добавлен, начислено +3 дня"
    cur.close()
    conn.close()
    return True, "Реферал сохранен"

# ==================== /start ====================

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
    cur.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
    existing_user = cur.fetchone()
    cur.close()
    conn.close()

    if existing_user:
        if not is_subscribed(user_id):
            bot.reply_to(message, "⚠️ Подпишитесь на канал, чтобы пользоваться ботом.", reply_markup=subscribe_button())
            return
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT last_activity FROM users WHERE user_id = %s", (user_id,))
        result = cur.fetchone()
        if result:
            last_activity = result[0] or 0
            days_since_last = (current_time - last_activity) // (24 * 60 * 60)
            welcome_text = "👋 С возвращением!" if days_since_last >= 3 else "👋 Добро пожаловать!"
            cur.execute("UPDATE users SET last_activity = %s WHERE user_id = %s", (current_time, user_id))
            conn.commit()
            bot.reply_to(message, welcome_text)
        cur.close()
        conn.close()
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
    if message.text and 'start=ref_' in message.text:
        parts = message.text.split('start=ref_')
        if len(parts) > 1:
            try:
                ref = int(parts[1].strip())
                if ref != user_id:
                    referrer_id = ref
            except:
                pass

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

# ==================== ОБРАБОТЧИК КАПЧИ ====================

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
    cur.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
    already_registered = cur.fetchone()
    cur.close()
    conn.close()

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

# ==================== РЕГИСТРАЦИЯ ПОЛЬЗОВАТЕЛЯ ====================

def _register_user(user_id, referrer_id=None):
    current_time = int(time.time())
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
    if cur.fetchone():
        cur.close()
        conn.close()
        return
    token = generate_subscription_token()
    sub_end = current_time + 7 * 24 * 60 * 60
    cur.execute(
        "INSERT INTO users (user_id, subscription_end, last_activity, is_blocked, token) VALUES (%s, %s, %s, 0, %s)",
        (user_id, sub_end, current_time, token)
    )
    conn.commit()
    cur.close()
    conn.close()
    if referrer_id:
        success, message = process_referral(referrer_id, user_id)
        if success:
            try:
                bot.send_message(referrer_id, f"🔔 Новый реферал! Пользователь {get_user_display_name(user_id)} зарегистрировался по вашей ссылке.")
            except:
                pass
    bot.send_message(user_id, "🎉 Добро пожаловать! Вам выдана подписка на 7 дней.")
    bot.send_message(user_id, "Выберите действие:", reply_markup=main_menu())

# ==================== ОБРАБОТЧИК "Я ПОДПИСАЛСЯ" ====================

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
        cur.execute(
            "SELECT referrer_id FROM referrals WHERE referred_id = %s AND rewarded = 0",
            (user_id,)
        )
        pending = cur.fetchone()
        cur.close()
        conn.close()
        if pending:
            referrer_id = pending[0]
            if is_subscribed(referrer_id):
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("SELECT subscription_end FROM users WHERE user_id = %s", (referrer_id,))
                ref_result = cur.fetchone()
                if ref_result:
                    new_end = ref_result[0] + 3 * 24 * 60 * 60
                    cur.execute("UPDATE users SET subscription_end = %s WHERE user_id = %s", (new_end, referrer_id))
                    cur.execute("UPDATE referrals SET rewarded = 1 WHERE referred_id = %s", (user_id,))
                    conn.commit()
                    try:
                        bot.send_message(referrer_id, "🎉 Ваш реферал подтвердил подписку! Вам начислено +3 дня.")
                    except:
                        pass
                cur.close()
                conn.close()
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
        user_exists = cur.fetchone()
        cur.close()
        conn.close()
        if not user_exists:
            _register_user(user_id, None)
        else:
            bot.send_message(user_id, "👋 Добро пожаловать!")
            bot.send_message(user_id, "Выберите действие:", reply_markup=main_menu())
    else:
        bot.answer_callback_query(call.id, "❌ Вы ещё не подписались на канал!")

# ==================== ОСНОВНЫЕ КНОПКИ ====================

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
    cur.execute("SELECT subscription_end, token FROM users WHERE user_id = %s", (user_id,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    if not result:
        bot.reply_to(message, "❌ Используйте /start")
        return
    subscription_end = result[0]
    token = result[1]

    if subscription_end and subscription_end > current_time:
        status = "✅ Активна"
        days_left = (subscription_end - current_time) // (24 * 60 * 60)
        hours_left = ((subscription_end - current_time) // 3600) % 24
        time_left = f"{days_left} дн {hours_left} ч"
        expire_date = datetime.fromtimestamp(subscription_end).strftime("%d.%m.%Y в %H:%M")
        link = get_subscription_link(user_id)
        yandex_link = f"https://translate.yandex.ru/translate?url={link}"
    else:
        status = "❌ Не активна"
        time_left = "Закончилась"
        expire_date = "Закончилась"
        link = "❌ Нет активной подписки"
        yandex_link = "❌ Нет активной подписки"

    text = f"""👤 *Личный кабинет*

🆔 ID: `{user_id}`

📅 Подписка до: `{expire_date}`
⏳ Осталось: `{time_left}`
📊 Статус: {status}

┌ 🔗 *Ссылка для импорта:*
│ `{link}`
│
├ 🔄 *Для белых списков:*
│ `{yandex_link}`
│
└ ℹ️ *Ссылка автообновляется при белых списках*

💬 Поддержка: {SUPPORT}"""

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📋 Обычная", callback_data=f"copy_link_{user_id}"),
        types.InlineKeyboardButton("🔄 Белые списки", callback_data=f"copy_yandex_{user_id}")
    )

    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=kb)

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
        bot.reply_to(message, "⚠️ Подпишитесь на канал, чтобы пользоваться ботом.", reply_markup=subscribe_button())
        return
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT subscription_end FROM users WHERE user_id = %s", (user_id,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    if not result:
        bot.reply_to(message, "❌ Вы не зарегистрированы. Используйте /start")
        return
    subscription_end = result[0]
    if subscription_end and subscription_end > current_time:
        link = get_subscription_link(user_id)
        yandex_link = f"https://translate.yandex.ru/translate?url={link}"

        text = f"""📡 *Моя подписка*

┌ 🔗 *Обычная ссылка:*
│ `{link}`
│
├ 🔄 *Для белых списков:*
│ `{yandex_link}`
│
└ ℹ️ *Ссылка автообновляется при белых списках*
   *Используйте её для импорта в клиент*

📱 *Поддерживаемые клиенты:*
• V2Ray / V2RayNG
• Hiddify / Nekobox
• FlClash / Mihomo
• Clash Meta / Sing-Box

💬 Поддержка: {SUPPORT}"""

        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("📋 Обычная", callback_data=f"copy_link_{user_id}"),
            types.InlineKeyboardButton("🔄 Белые списки", callback_data=f"copy_yandex_{user_id}")
        )

        bot.reply_to(message, text, parse_mode="Markdown", reply_markup=kb)
    else:
        bot.reply_to(
            message,
            f"❌ Ваша подписка неактивна или истекла.\n\nДля продления обратитесь к администратору:\n{SUPPORT}"
        )

# ==================== КОЛБЭКИ ДЛЯ КОПИРОВАНИЯ ====================

@bot.callback_query_handler(func=lambda call: call.data.startswith('copy_link_'))
def callback_copy_link(call):
    user_id = call.from_user.id
    target_id = int(call.data.split('_')[2])

    if user_id != target_id:
        bot.answer_callback_query(call.id, "❌ Это не ваша ссылка.")
        return

    link = get_subscription_link(user_id)

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
    yandex_link = f"https://translate.yandex.ru/translate?url={link}"

    bot.send_message(
        user_id,
        f"🔄 *Ссылка для белых списков:*\n\n`{yandex_link}`\n\nНажмите на сообщение и скопируйте текст.\n\nℹ️ Ссылка автообновляется при белых списках.",
        parse_mode="Markdown"
    )
    bot.answer_callback_query(call.id, "✅ Ссылка для белых списков отправлена!")

@bot.message_handler(func=lambda m: m.text == "👥 Рефералы")
def referrals(message):
    update_activity()
    user_id = message.from_user.id
    if is_blocked(user_id):
        bot.reply_to(message, blocked_message())
        return
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = %s", (user_id,))
    total = cur.fetchone()[0]
    cur.close()
    conn.close()
    bot_username = bot.get_me().username
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    text = f"👥 *Рефералы*\n\n📊 Всего: {total}\n🔗 Ссылка: `{ref_link}`\n\n📌 За каждого друга +3 дня."
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "🏆 Топ рефералов")
def top_referrals(message):
    update_activity()
    user_id = message.from_user.id
    if is_blocked(user_id):
        bot.reply_to(message, blocked_message())
        return
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT referrer_id, COUNT(*) FROM referrals GROUP BY referrer_id ORDER BY COUNT(*) DESC LIMIT 10")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if not rows:
        bot.reply_to(message, "📭 Нет рефералов.")
        return
    text = "🏆 *Топ рефералов:*\n\n"
    medals = ['🥇', '🥈', '🥉']
    for i, (ref_id, count) in enumerate(rows):
        name = get_user_display_name(ref_id)
        icon = medals[i] if i < 3 else f"{i+1}."
        text += f"{icon} {name} — {count} реф.\n"
    bot.reply_to(message, text, parse_mode="Markdown")

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
    cur.execute("SELECT COUNT(*) FROM users")
    total_users = cur.fetchone()[0]
    cur.close()
    conn.close()
    text = f"📊 *Статистика*\n\n⏳ Стаж: {stats['uptime_text']}\n👥 Пользователей: {total_users}\n📦 Ключей: {stats['current_keys']}\n🔑 Проверено: {stats['total_keys_checked']}\n🔓 Расшифровано: {stats['total_decryptions']}"
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "❓ Поддержка")
def support(message):
    bot.reply_to(message, f"💬 Поддержка: {SUPPORT}")

# ==================== РАСШИФРОВКА ПОДПИСКИ ====================

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
    decrypt_results[user_id] = {'waiting': True}
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

def _parse_subscription_any(raw, steps=None):
    if steps is None:
        steps = []
    text = raw.strip()

    # BELKA.NETWORK
    if 'belka.network' in text:
        steps.append(f"🔗 Обнаружена ссылка Belka VPN")
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            resp = requests.get(text, timeout=30, headers=headers)
            if resp.status_code == 200:
                content = resp.text
                steps.append(f"✅ Загружено {len(content)} символов")
                soup = BeautifulSoup(content, 'html.parser')
                sub_links = []
                for a in soup.find_all('a'):
                    href = a.get('href', '')
                    if href and ('sub' in href or 'config' in href or 'profile' in href or 'clash' in href or 'vless' in href or 'vmess' in href):
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
                            sub_resp = requests.get(link, timeout=30, headers=headers)
                            if sub_resp.status_code == 200:
                                keys = _parse_keys_from_content(sub_resp.text)
                                if keys:
                                    steps.append(f"✅ Найдено {len(keys)} ключей")
                                    return _dedup(keys), steps
                        except:
                            pass
                    steps.append(f"📋 Найдены ссылки, но ключи не извлечены")
                    return sub_links, steps
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
                            resp = requests.get(item.strip(), timeout=30)
                            if resp.status_code == 200:
                                return _parse_subscription_any(resp.text, steps)
                        except:
                            pass
                    keys = _extract_vpn_keys(item)
                    if keys:
                        return _dedup(keys), steps
        if re.match(r'https?://', payload, re.IGNORECASE):
            try:
                resp = requests.get(payload, timeout=30)
                if resp.status_code == 200:
                    return _parse_subscription_any(resp.text, steps)
            except:
                pass
        keys = _extract_vpn_keys(payload)
        if keys:
            return _dedup(keys), steps
        return [], steps

    # HTTP URL
    if re.match(r'^https?://', text, re.IGNORECASE):
        steps.append(f"⬇️ Загружаю URL...")
        try:
            session = requests.Session()
            session.max_redirects = 10
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            resp = session.get(text, timeout=30, headers=headers, allow_redirects=True)
            if resp.status_code == 200:
                content = resp.text.strip()
                steps.append(f"✅ Загружено {len(content)} символов")
                if re.match(r'^[A-Za-z0-9+/_\-=]+$', content) and len(content) > 50:
                    decoded = _try_multilevel_b64(content, max_depth=5)
                    if decoded:
                        all_keys = []
                        for item in decoded:
                            all_keys.extend(_extract_vpn_keys(item))
                        if all_keys:
                            return _dedup(all_keys), steps
                keys = _extract_vpn_keys(content)
                if keys:
                    return _dedup(keys), steps
                if '<' in content and '>' in content:
                    soup = BeautifulSoup(content, 'html.parser')
                    for a in soup.find_all('a'):
                        href = a.get('href', '')
                        if href and ('sub' in href or 'config' in href or 'profile' in href or 'clash' in href):
                            if href.startswith('http'):
                                try:
                                    sub_resp = requests.get(href, timeout=30, headers=headers)
                                    if sub_resp.status_code == 200:
                                        sub_keys = _parse_keys_from_content(sub_resp.text)
                                        if sub_keys:
                                            steps.append(f"✅ Найдено {len(sub_keys)} ключей")
                                            return _dedup(sub_keys), steps
                                except:
                                    pass
                steps.append(f"❌ Ключи не найдены")
                return [], steps
            else:
                steps.append(f"❌ Ошибка: HTTP {resp.status_code}")
                return [], steps
        except Exception as e:
            steps.append(f"❌ Ошибка: {e}")
            return [], steps

    # ОБЫЧНЫЙ ТЕКСТ
    keys = load_keys_from_text(text)
    if not keys:
        keys = _extract_vpn_keys(text)
    if keys:
        steps.append(f"🔍 Найдено {len(keys)} ключей")
        return _dedup(keys), steps
    steps.append("❌ Ключи не найдены")
    return [], steps

def _do_decrypt(message, user_id, text=None, file_bytes=None, file_name=None):
    if user_id in decrypt_results:
        del decrypt_results[user_id]
    try:
        wait_msg = bot.reply_to(message, "⏳ Обрабатываю подписку...")
    except:
        wait_msg = None

    def process():
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
    t = threading.Thread(target=process)
    t.daemon = True
    t.start()

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
        types.InlineKeyboardButton("🏠 Главное меню", callback_data="admin_back")
    )
    return kb

# ==================== ADMIN CALLBACKS ====================

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def admin_callback(call):
    user_id = call.from_user.id
    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    data = call.data

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
        bot.send_message(user_id, f"🏛️ Админ панель\n\n👤 Ваша роль: {role_name}", reply_markup=admin_menu())
        bot.answer_callback_query(call.id)
        return

    if data == "admin_manage_admins":
        if not has_permission(user_id, 'manage_admins'):
            bot.answer_callback_query(call.id, "⛔️ У вас нет прав на управление админами.")
            return
        bot.answer_callback_query(call.id)
        show_admin_list(call.message, user_id)
        return

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
        bot.edit_message_text("📢 *Рассылка*\n\nВыберите куда:", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=kb)
        return

    if data == "admin_manage_users":
        if not has_permission(user_id, 'manage_users'):
            bot.answer_callback_query(call.id, "⛔️ Нет прав")
            return
        bot.answer_callback_query(call.id)
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users ORDER BY user_id")
        users = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        if not users:
            bot.edit_message_text("📭 Нет пользователей.", call.message.chat.id, call.message.message_id)
            return
        manage_cache[user_id] = {'users': users, 'filter': 'all'}
        kb = build_user_list_keyboard(users, 0, 'all')
        bot.edit_message_text(f"👥 Пользователи ({len(users)}):", call.message.chat.id, call.message.message_id, reply_markup=kb)
        return

    if data == "admin_keys":
        callback_admin_keys(call)
        return

    if data == "admin_autopost":
        if not has_permission(user_id, 'autopost'):
            bot.answer_callback_query(call.id, "⛔️ Нет прав")
            return
        bot.answer_callback_query(call.id)
        config = get_autopost_config()
        status = "✅ ВКЛ" if config['enabled'] else "❌ ВЫКЛ"
        text = f"📡 *АВТОПОСТИНГ*\n\nСтатус: {status}\nИнтервал: {config['interval'] // 60} мин\nКанал: {config['channel_id']}"
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("📥 Загрузить ключи", callback_data="autopost_load_keys"),
            types.InlineKeyboardButton("🚀 Начать", callback_data="autopost_start"),
            types.InlineKeyboardButton("⚙️ Канал", callback_data="autopost_channel_settings"),
            types.InlineKeyboardButton("⏱ Интервал", callback_data="autopost_interval_settings"),
            types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back_panel")
        )
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=kb)
        return

# ==================== УПРАВЛЕНИЕ КЛЮЧАМИ ====================

@bot.callback_query_handler(func=lambda call: call.data == "admin_keys")
def callback_admin_keys(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'manage_keys'):
        bot.answer_callback_query(call.id, "⛔️ У вас нет прав на управление ключами.")
        return
    
    bot.answer_callback_query(call.id)
    
    keys = get_keys_from_db()
    total_issued = int(get_setting('total_keys_issued', '0'))
    total_checked = int(get_setting('total_keys_checked', '0'))
    
    text = f"""🔑 *Управление ключами*

📦 Ключей в базе: {len(keys)}
🗑️ Выдано ключей: {total_issued}
📊 Всего проверено: {total_checked}

Выберите действие:"""
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📥 Загрузить ключи", callback_data="admin_keys_load"),
        types.InlineKeyboardButton("🧹 Очистить нерабочие", callback_data="admin_keys_clean_dead")
    )
    kb.add(
        types.InlineKeyboardButton("🗑️ Очистить все", callback_data="admin_keys_clear_all"),
        types.InlineKeyboardButton("🔄 Сбросить выдачу", callback_data="admin_keys_reset_issued")
    )
    kb.add(
        types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back_panel")
    )
    
    try:
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown",
            reply_markup=kb
        )
    except:
        bot.send_message(
            user_id,
            text,
            parse_mode="Markdown",
            reply_markup=kb
        )

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
    
    admin_keys_loading[user_id] = {
        'keys': [],
        'message_id': msg.message_id
    }

@bot.callback_query_handler(func=lambda call: call.data == "admin_keys_load_finish")
def callback_admin_keys_load_finish(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'manage_keys'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    
    if user_id not in admin_keys_loading:
        bot.answer_callback_query(call.id, "❌ Нет активной загрузки")
        return
    
    keys = admin_keys_loading[user_id]['keys']
    
    if not keys:
        bot.answer_callback_query(call.id, "❌ Нет загруженных ключей")
        return
    
    save_keys_to_db(keys)
    
    proto_stats = {}
    for k in keys:
        m = re.match(r'([a-z0-9+]+)://', k, re.IGNORECASE)
        if m:
            p = m.group(1).lower()
            proto_stats[p] = proto_stats.get(p, 0) + 1
    stats = '\n'.join(f"  • {p}:// — {c}" for p, c in sorted(proto_stats.items(), key=lambda x: -x[1]))
    
    del admin_keys_loading[user_id]
    bot.answer_callback_query(call.id, f"✅ Загружено {len(keys)} ключей!")
    
    try:
        bot.edit_message_text(
            f"✅ *Ключи загружены!*\n\n"
            f"📊 Загружено ключей: {len(keys)}\n"
            f"📋 По протоколам:\n{stats}\n"
            f"📦 Всего в базе: {len(get_keys_from_db())}",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown"
        )
    except:
        bot.send_message(
            user_id,
            f"✅ *Ключи загружены!*\n\n"
            f"📊 Загружено ключей: {len(keys)}\n"
            f"📋 По протоколам:\n{stats}\n"
            f"📦 Всего в базе: {len(get_keys_from_db())}",
            parse_mode="Markdown"
        )
    
    fake_call = types.CallbackQuery(
        id="dummy",
        from_user=call.from_user,
        message=call.message,
        data="admin_keys"
    )
    callback_admin_keys(fake_call)

@bot.callback_query_handler(func=lambda call: call.data == "admin_keys_load_cancel")
def callback_admin_keys_load_cancel(call):
    user_id = call.from_user.id
    if user_id in admin_keys_loading:
        del admin_keys_loading[user_id]
    bot.answer_callback_query(call.id, "❌ Отменено")
    
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass
    
    fake_call = types.CallbackQuery(
        id="dummy",
        from_user=call.from_user,
        message=call.message,
        data="admin_keys"
    )
    callback_admin_keys(fake_call)

@bot.callback_query_handler(func=lambda call: call.data == "admin_keys_clean_dead")
def callback_admin_keys_clean_dead(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'manage_keys'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    
    bot.answer_callback_query(call.id, "⏳ Проверяю ключи...")
    
    keys = get_keys_from_db()
    if not keys:
        bot.answer_callback_query(call.id, "❌ Нет ключей для проверки")
        return
    
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
    
    total_issued = int(get_setting('total_keys_issued', '0'))
    if total_issued > len(alive_keys):
        set_setting('total_keys_issued', str(len(alive_keys)))
    
    text = f"🧹 *Очистка нерабочих ключей завершена!*\n\n"
    text += f"✅ Оставлено живых: {len(alive_keys)}\n"
    text += f"🗑️ Удалено нерабочих: {len(dead_keys)}\n"
    text += f"📦 Всего в базе: {len(alive_keys)}"
    
    bot.answer_callback_query(call.id, "✅ Готово!")
    
    try:
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown"
        )
    except:
        bot.send_message(user_id, text, parse_mode="Markdown")
    
    time.sleep(3)
    fake_call = types.CallbackQuery(
        id="dummy",
        from_user=call.from_user,
        message=call.message,
        data="admin_keys"
    )
    callback_admin_keys(fake_call)

@bot.callback_query_handler(func=lambda call: call.data == "admin_keys_clear_all")
def callback_admin_keys_clear_all(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'manage_keys'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ Да, удалить все", callback_data="admin_keys_clear_all_confirm"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="admin_keys")
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
        bot.send_message(
            user_id,
            "⚠️ *ВНИМАНИЕ!*\n\n"
            "Вы уверены, что хотите удалить ВСЕ ключи из базы?\n"
            "Это действие НЕЛЬЗЯ будет отменить!",
            parse_mode="Markdown",
            reply_markup=kb
        )

@bot.callback_query_handler(func=lambda call: call.data == "admin_keys_clear_all_confirm")
def callback_admin_keys_clear_all_confirm(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'manage_keys'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    
    save_keys_to_db([])
    set_setting('total_keys_issued', '0')
    
    bot.answer_callback_query(call.id, "🗑️ Все ключи удалены!")
    
    fake_call = types.CallbackQuery(
        id="dummy",
        from_user=call.from_user,
        message=call.message,
        data="admin_keys"
    )
    callback_admin_keys(fake_call)

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
    bot.answer_callback_query(call.id, f"🔄 Сброшено {current_issued} выданных ключей!")
    
    fake_call = types.CallbackQuery(
        id="dummy",
        from_user=call.from_user,
        message=call.message,
        data="admin_keys"
    )
    callback_admin_keys(fake_call)

# ==================== ADMIN USERS LIST ====================

def build_user_list_keyboard(users, page, filter_type='all'):
    kb = types.InlineKeyboardMarkup(row_width=2)
    per_page = 5
    start = page * per_page
    end = start + per_page
    current_time = int(time.time())
    
    for uid in users[start:end]:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT subscription_end, is_blocked FROM users WHERE user_id = %s", (uid,))
        udata = cur.fetchone()
        cur.close()
        conn.close()
        
        if udata:
            sub_end, blk = udata
            if blk:
                icon = "🚫"
            elif sub_end and sub_end > current_time:
                icon = "🟢"
            else:
                icon = "🔴"
        else:
            icon = "❓"
        
        admin_icon = "👑 " if is_admin(uid) else ""
        name = get_user_display_name(uid)
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

@bot.callback_query_handler(func=lambda call: call.data.startswith('filter_') or call.data.startswith('page_') or call.data in ['close_manage', 'back_to_list'])
def callback_manage_filters(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Нет доступа.")
        return
    
    user_id = call.from_user.id
    if not has_permission(user_id, 'manage_users'):
        bot.answer_callback_query(call.id, "⛔️ У вас нет прав на управление пользователями.")
        return
    
    admin_id = call.from_user.id
    current_time = int(time.time())
    data = call.data

    if data == 'close_manage':
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
        bot.answer_callback_query(call.id)
        return

    if data == 'back_to_list':
        cached = manage_cache.get(admin_id, {})
        users = cached.get('users', [])
        filter_type = cached.get('filter', 'all')
        
        if not users:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT user_id FROM users ORDER BY user_id")
            users = [row[0] for row in cur.fetchall()]
            cur.close()
            conn.close()
        
        kb = build_user_list_keyboard(users, 0, filter_type)
        bot.answer_callback_query(call.id)
        try:
            bot.edit_message_text(
                f"👥 Пользователи ({len(users)}):",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=kb
            )
        except:
            pass
        return

    if data.startswith('page_'):
        parts = data.split('_')
        page = int(parts[1])
        filter_type = parts[2] if len(parts) > 2 else 'all'
        cached = manage_cache.get(admin_id, {})
        users = cached.get('users', [])
        kb = build_user_list_keyboard(users, page, filter_type)
        bot.answer_callback_query(call.id)
        try:
            bot.edit_message_text(
                f"👥 Пользователи ({len(users)}):",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=kb
            )
        except:
            pass
        return

    conn = get_db_connection()
    cur = conn.cursor()
    
    if data == 'filter_active':
        cur.execute(f"SELECT user_id FROM users WHERE is_blocked = 0 AND subscription_end > {current_time} ORDER BY user_id")
        filter_type = 'active'
    elif data == 'filter_inactive':
        cur.execute(f"SELECT user_id FROM users WHERE is_blocked = 0 AND subscription_end < {current_time} ORDER BY user_id")
        filter_type = 'inactive'
    elif data == 'filter_admins':
        cur.execute("SELECT user_id FROM admins ORDER BY user_id")
        filter_type = 'admins'
    else:
        cur.execute("SELECT user_id FROM users ORDER BY user_id")
        filter_type = 'all'
    
    users = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    
    manage_cache[admin_id] = {'users': users, 'filter': filter_type}
    kb = build_user_list_keyboard(users, 0, filter_type)
    
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_text(
            f"👥 Пользователи ({len(users)}):",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=kb
        )
    except:
        pass

# ==================== КАРТОЧКА ПОЛЬЗОВАТЕЛЯ ====================

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
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT subscription_end, is_blocked FROM users WHERE user_id = %s", (target_id,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    
    if not result:
        bot.answer_callback_query(call.id, "❌ Пользователь не найден.")
        return
    
    subscription_end, blk = result
    current_time = int(time.time())
    
    if blk:
        status = "🚫 Заблокирован"
    elif subscription_end and subscription_end > current_time:
        days_left = (subscription_end - current_time) // (24 * 60 * 60)
        hours_left = ((subscription_end - current_time) // 3600) % 24
        status = f"🟢 Активен ({days_left} дн {hours_left} ч)"
    else:
        status = "🔴 Неактивен"
    
    is_admin_user = is_admin(target_id)
    admin_text = "✅ Да" if is_admin_user else "❌ Нет"
    name = get_user_display_name(target_id)
    
    username = ""
    try:
        chat = bot.get_chat(target_id)
        if chat.username:
            username = f"@{chat.username}"
        else:
            username = "❌ Нет юзернейма"
    except:
        username = "❌ Не найден"
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    
    if has_permission(user_id, 'add_days'):
        kb.add(types.InlineKeyboardButton("✅ Выдать подписку", callback_data=f"give_sub_{target_id}"))
    
    if has_permission(user_id, 'add_days'):
        kb.add(types.InlineKeyboardButton("📅 +30 дн", callback_data=f"prolong_{target_id}_30"))
    if has_permission(user_id, 'remove_days'):
        kb.add(types.InlineKeyboardButton("📅 -30 дн", callback_data=f"remove_days_{target_id}_30"))
    
    if has_permission(user_id, 'add_days') or has_permission(user_id, 'remove_days'):
        kb.add(types.InlineKeyboardButton("🗑️ Удалить подписку", callback_data=f"remove_sub_{target_id}"))
    
    if has_permission(user_id, 'block_user'):
        if blk:
            kb.add(types.InlineKeyboardButton("🔓 Разблокировать", callback_data=f"unblock_{target_id}"))
        else:
            kb.add(types.InlineKeyboardButton("🔒 Заблокировать", callback_data=f"block_{target_id}"))
    
    if has_permission(user_id, 'manage_admins'):
        if is_admin_user and target_id != ADMIN_ID:
            kb.add(types.InlineKeyboardButton("👑 Забрать админку", callback_data=f"remove_admin_{target_id}"))
        elif not is_admin_user:
            kb.add(types.InlineKeyboardButton("👑 Выдать админку", callback_data=f"add_admin_{target_id}"))
    
    kb.row(
        types.InlineKeyboardButton("🔙 Назад к списку", callback_data="back_to_list"),
        types.InlineKeyboardButton("❌ Закрыть", callback_data="close_manage")
    )
    
    text = f"""👤 *{name}*

🆔 ID: `{target_id}`
👤 Юзернейм: {username}
📊 Статус: {status}
👑 Админ: {admin_text}"""
    
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown",
            reply_markup=kb
        )
    except Exception as e:
        bot.send_message(
            call.message.chat.id,
            text,
            parse_mode="Markdown",
            reply_markup=kb
        )

# ==================== УПРАВЛЕНИЕ ПОДПИСКОЙ ====================

@bot.callback_query_handler(func=lambda call: call.data.startswith('give_sub_'))
def callback_give_sub(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    
    if not has_permission(call.from_user.id, 'add_days'):
        bot.answer_callback_query(call.id, "⛔️ У вас нет прав на выдачу подписки.")
        return
    
    target_id = int(call.data.split('_')[2])
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id = %s", (target_id,))
    result = cur.fetchone()
    
    if not result:
        bot.answer_callback_query(call.id, "❌ Пользователь не найден.")
        cur.close()
        conn.close()
        return
    
    current_time = int(time.time())
    new_end = current_time + 30 * 24 * 60 * 60
    
    cur.execute("UPDATE users SET subscription_end = %s, notified_3days = 0 WHERE user_id = %s", (new_end, target_id))
    conn.commit()
    cur.close()
    conn.close()
    
    bot.answer_callback_query(call.id, "✅ Выдана подписка на 30 дней!")
    
    try:
        bot.send_message(target_id, f"🎉 Администратор выдал вам подписку на 30 дней!")
    except:
        pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('prolong_'))
def callback_prolong(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    
    if not has_permission(call.from_user.id, 'add_days'):
        bot.answer_callback_query(call.id, "⛔️ У вас нет прав на выдачу дней.")
        return
    
    parts = call.data.split('_')
    target_id = int(parts[1])
    days = int(parts[2])
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT subscription_end FROM users WHERE user_id = %s", (target_id,))
    result = cur.fetchone()
    
    if not result:
        bot.answer_callback_query(call.id, "❌ Пользователь не найден.")
        cur.close()
        conn.close()
        return
    
    current_time = int(time.time())
    current_end = result[0] if (result[0] and result[0] > current_time) else current_time
    new_end = current_end + days * 24 * 60 * 60
    
    cur.execute("UPDATE users SET subscription_end = %s, notified_3days = 0 WHERE user_id = %s", (new_end, target_id))
    conn.commit()
    cur.close()
    conn.close()
    
    bot.answer_callback_query(call.id, f"✅ Продлено на {days} дней!")
    
    try:
        bot.send_message(target_id, f"🎉 Ваша подписка продлена на {days} дней администратором!")
    except:
        pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('remove_days_'))
def callback_remove_days(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    
    if not has_permission(call.from_user.id, 'remove_days'):
        bot.answer_callback_query(call.id, "⛔️ У вас нет прав на забирание дней.")
        return
    
    parts = call.data.split('_')
    target_id = int(parts[2])
    days = int(parts[3])
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT subscription_end FROM users WHERE user_id = %s", (target_id,))
    result = cur.fetchone()
    
    if not result:
        bot.answer_callback_query(call.id, "❌ Пользователь не найден.")
        cur.close()
        conn.close()
        return
    
    current_time = int(time.time())
    current_end = result[0] if (result[0] and result[0] > current_time) else current_time
    new_end = current_end - days * 24 * 60 * 60
    
    if new_end < current_time:
        new_end = current_time - 1
    
    cur.execute("UPDATE users SET subscription_end = %s, notified_3days = 0 WHERE user_id = %s", (new_end, target_id))
    conn.commit()
    cur.close()
    conn.close()
    
    bot.answer_callback_query(call.id, f"✅ Убавлено {days} дней!")
    
    try:
        bot.send_message(target_id, f"⚠️ Администратор забрал {days} дней подписки!")
    except:
        pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('remove_sub_'))
def callback_remove_sub(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    
    if not has_permission(call.from_user.id, 'add_days') and not has_permission(call.from_user.id, 'remove_days'):
        bot.answer_callback_query(call.id, "⛔️ У вас нет прав на удаление подписки.")
        return
    
    target_id = int(call.data.split('_')[2])
    current_time = int(time.time())
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET subscription_end = %s WHERE user_id = %s", (current_time - 1, target_id))
    conn.commit()
    cur.close()
    conn.close()
    
    bot.answer_callback_query(call.id, "✅ Подписка удалена!")
    
    try:
        bot.send_message(target_id, "❌ Ваша подписка была удалена администратором.")
    except:
        pass

# ==================== БЛОКИРОВКА ====================

@bot.callback_query_handler(func=lambda call: call.data.startswith('block_'))
def callback_block(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    
    if not has_permission(call.from_user.id, 'block_user'):
        bot.answer_callback_query(call.id, "⛔️ У вас нет прав на блокировку.")
        return
    
    target_id = int(call.data.split('_')[1])
    
    if target_id == ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нельзя заблокировать создателя.")
        return
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET is_blocked = 1 WHERE user_id = %s", (target_id,))
    conn.commit()
    cur.close()
    conn.close()
    
    bot.answer_callback_query(call.id, "✅ Пользователь заблокирован!")
    
    try:
        bot.send_message(target_id, f"🚫 Вы заблокированы администратором.\n\nОбратитесь в поддержку: {SUPPORT}")
    except:
        pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('unblock_'))
def callback_unblock(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    
    if not has_permission(call.from_user.id, 'unblock_user'):
        bot.answer_callback_query(call.id, "⛔️ У вас нет прав на разблокировку.")
        return
    
    target_id = int(call.data.split('_')[1])
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET is_blocked = 0 WHERE user_id = %s", (target_id,))
    conn.commit()
    cur.close()
    conn.close()
    
    bot.answer_callback_query(call.id, "✅ Пользователь разблокирован!")
    
    try:
        bot.send_message(target_id, "✅ Вы разблокированы! Теперь вы можете пользоваться ботом.")
    except:
        pass

# ==================== УПРАВЛЕНИЕ АДМИНАМИ ====================

def show_admin_list(message, user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id, role FROM admins ORDER BY user_id")
    admins = cur.fetchall()
    cur.close()
    conn.close()

    text = "👑 *Управление админами*\n\n"
    for admin_id, role in admins:
        name = get_user_display_name(admin_id)
        role_name = ROLE_PRESETS.get(role, {}).get('name', role)
        text += f"• {role_name} {name} (`{admin_id}`)\n"
    text += f"\n👑 Владелец: {get_user_display_name(ADMIN_ID)} (`{ADMIN_ID}`)"

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("➕ Добавить админа", callback_data="add_admin_start"),
        types.InlineKeyboardButton("⚙️ Настроить права", callback_data="edit_admin_perms")
    )
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back_panel"))

    try:
        bot.edit_message_text(text, message.chat.id, message.message_id, parse_mode="Markdown", reply_markup=kb)
    except:
        bot.send_message(user_id, text, parse_mode="Markdown", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data == "add_admin_start")
def callback_add_admin_start(call):
    user_id = call.from_user.id
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
    
    bot.send_message(user_id, "👑 *Добавление админа*\n\nВыберите роль для нового админа, затем отправьте ID или @username пользователя.", parse_mode="Markdown", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data.startswith('add_admin_role_'))
def callback_add_admin_role(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'manage_admins'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    
    role = call.data.split('_')[3]
    search_cache[user_id] = {'action': 'add_admin', 'role': role}
    bot.answer_callback_query(call.id, f"✅ Выбрана роль: {ROLE_PRESETS[role]['name']}")
    bot.send_message(user_id, f"👑 Выбрана роль: {ROLE_PRESETS[role]['name']}\n\nОтправьте ID или @username пользователя.", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "edit_admin_perms")
def callback_edit_admin_perms(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'manage_admins'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    
    bot.answer_callback_query(call.id)
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id, role FROM admins WHERE user_id != %s", (ADMIN_ID,))
    admins = cur.fetchall()
    cur.close()
    conn.close()
    
    if not admins:
        bot.send_message(user_id, "❌ Нет других админов для настройки.")
        return
    
    kb = types.InlineKeyboardMarkup(row_width=1)
    for admin_id, role in admins:
        name = get_user_display_name(admin_id)
        kb.add(types.InlineKeyboardButton(f"{name} ({role})", callback_data=f"edit_admin_{admin_id}"))
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_manage_admins"))
    
    bot.send_message(user_id, "⚙️ *Выберите админа для настройки прав:*", parse_mode="Markdown", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_admin_'))
def callback_edit_admin(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'manage_admins'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    
    target_id = int(call.data.split('_')[2])
    if target_id == ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нельзя редактировать владельца.")
        return
    
    current_perms = get_admin_permissions(target_id)
    role = get_admin_role(target_id) or 'junior'
    role_name = ROLE_PRESETS.get(role, {}).get('name', role)
    name = get_user_display_name(target_id)
    text = f"⚙️ *Настройка прав*\n\n👤 {name} (`{target_id}`)\n👑 Роль: {role_name}\n\nВключите/отключите нужные разрешения:\n\n"
    kb = types.InlineKeyboardMarkup(row_width=2)
    for perm_key, perm_name in PERMISSIONS.items():
        status = "✅" if current_perms.get(perm_key, False) else "❌"
        kb.add(types.InlineKeyboardButton(f"{status} {perm_name}", callback_data=f"toggle_perm_{target_id}_{perm_key}"))
    kb.add(types.InlineKeyboardButton("🔄 Сбросить к роли", callback_data=f"reset_perm_{target_id}"))
    kb.add(types.InlineKeyboardButton("🗑️ Удалить админа", callback_data=f"remove_admin_{target_id}"))
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="edit_admin_perms"))
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=kb)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('toggle_perm_'))
def callback_toggle_perm(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'manage_admins'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    
    parts = call.data.split('_')
    target_id = int(parts[2])
    perm_key = parts[3]
    
    if target_id == ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нельзя менять права владельца.")
        return
    
    current_perms = get_admin_permissions(target_id)
    current_perms[perm_key] = not current_perms.get(perm_key, False)
    update_admin_permissions(target_id, current_perms)
    
    bot.answer_callback_query(call.id, f"✅ {'Включено' if current_perms[perm_key] else 'Отключено'}")
    callback_edit_admin(call)

@bot.callback_query_handler(func=lambda call: call.data.startswith('reset_perm_'))
def callback_reset_perm(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'manage_admins'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    
    target_id = int(call.data.split('_')[2])
    if target_id == ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нельзя сбросить права владельца.")
        return
    
    role = get_admin_role(target_id) or 'junior'
    new_perms = ROLE_PRESETS[role]['permissions'].copy()
    update_admin_permissions(target_id, new_perms)
    
    bot.answer_callback_query(call.id, "✅ Права сброшены к настройкам роли!")
    callback_edit_admin(call)

@bot.callback_query_handler(func=lambda call: call.data.startswith('remove_admin_'))
def callback_remove_admin_cb(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'manage_admins'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    
    target_id = int(call.data.split('_')[2])
    if target_id == ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нельзя удалить владельца.")
        return
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM admins WHERE user_id = %s", (target_id,))
    conn.commit()
    cur.close()
    conn.close()
    
    bot.answer_callback_query(call.id, "✅ Админские права отозваны!")
    
    try:
        bot.send_message(target_id, "❌ Ваши права администратора были отозваны.")
    except:
        pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('add_admin_'))
def callback_add_admin(call):
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
    cur.execute("SELECT user_id FROM users WHERE user_id = %s", (target_id,))
    user_exists = cur.fetchone()
    cur.close()
    conn.close()
    
    if not user_exists:
        bot.answer_callback_query(call.id, "❌ Пользователь не зарегистрирован в боте.")
        return
    
    role = 'junior'
    perms = ROLE_PRESETS[role]['permissions'].copy()
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO admins (user_id, role, permissions, added_by, added_at) VALUES (%s, %s, %s, %s, %s)",
        (target_id, role, json.dumps(perms), user_id, int(time.time()))
    )
    conn.commit()
    cur.close()
    conn.close()
    
    bot.answer_callback_query(call.id, f"✅ {get_user_display_name(target_id)} назначен админом!")
    
    try:
        bot.send_message(target_id, "👑 Вам назначена роль администратора!\n\nТеперь вы имеете доступ к админ-панели (/admin)")
    except:
        pass

@bot.message_handler(func=lambda m: m.chat.type == 'private' and m.from_user.id in search_cache and search_cache.get(m.from_user.id, {}).get('action') == 'add_admin')
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
    cur.execute("SELECT user_id FROM users WHERE user_id = %s", (target_id,))
    user_exists = cur.fetchone()
    cur.close()
    conn.close()
    
    if not user_exists:
        bot.reply_to(message, "❌ Пользователь не зарегистрирован в боте.")
        return
    
    role = search_cache[user_id].get('role', 'junior')
    perms = ROLE_PRESETS[role]['permissions'].copy()
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO admins (user_id, role, permissions, added_by, added_at) VALUES (%s, %s, %s, %s, %s)",
        (target_id, role, json.dumps(perms), user_id, int(time.time()))
    )
    conn.commit()
    cur.close()
    conn.close()
    
    del search_cache[user_id]
    name = get_user_display_name(target_id)
    bot.reply_to(message, f"✅ {name} (`{target_id}`) назначен {ROLE_PRESETS[role]['name']}!")
    
    try:
        bot.send_message(target_id, f"👑 Вам назначена роль {ROLE_PRESETS[role]['name']}!\n\nТеперь вы имеете доступ к админ-панели (/admin)")
    except:
        pass

# ==================== КОМАНДЫ ДЛЯ ВЫДАЧИ/ЗАБРАНИЯ АДМИНКИ ====================

@bot.message_handler(commands=['add_admin'])
def cmd_add_admin(message):
    if message.chat.type != 'private':
        return
    user_id = message.from_user.id
    
    if not has_permission(user_id, 'manage_admins'):
        bot.reply_to(message, "⛔️ У вас нет прав на управление админами.")
        return
    
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "❌ Использование: `/add_admin [ID или @username]`\n\nПример: `/add_admin 123456789` или `/add_admin @mel1ste`", parse_mode="Markdown")
        return
    
    target_input = args[1]
    target_id = get_user_id_from_input(target_input)
    
    if not target_id:
        bot.reply_to(message, f"❌ Не удалось найти пользователя: `{target_input}`\n\nПроверьте правильность ID или @username.", parse_mode="Markdown")
        return
    
    if target_id == ADMIN_ID:
        bot.reply_to(message, "❌ Это владелец бота.")
        return
    
    if is_admin(target_id):
        bot.reply_to(message, "❌ Пользователь уже является админом.")
        return
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id = %s", (target_id,))
    user_exists = cur.fetchone()
    cur.close()
    conn.close()
    
    if not user_exists:
        bot.reply_to(message, f"❌ Пользователь `{target_id}` не зарегистрирован в боте.", parse_mode="Markdown")
        return
    
    role = 'junior'
    perms = ROLE_PRESETS[role]['permissions'].copy()
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO admins (user_id, role, permissions, added_by, added_at) VALUES (%s, %s, %s, %s, %s)",
        (target_id, role, json.dumps(perms), user_id, int(time.time()))
    )
    conn.commit()
    cur.close()
    conn.close()
    
    name = get_user_display_name(target_id)
    bot.reply_to(message, f"✅ {name} (`{target_id}`) назначен админом!")
    
    try:
        bot.send_message(target_id, f"👑 Вам назначена роль администратора!\n\nТеперь вы имеете доступ к админ-панели (/admin)")
    except:
        pass

@bot.message_handler(commands=['remove_admin'])
def cmd_remove_admin(message):
    if message.chat.type != 'private':
        return
    user_id = message.from_user.id
    
    if not has_permission(user_id, 'manage_admins'):
        bot.reply_to(message, "⛔️ У вас нет прав на управление админами.")
        return
    
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "❌ Использование: `/remove_admin [ID или @username]`\n\nПример: `/remove_admin 123456789` или `/remove_admin @mel1ste`", parse_mode="Markdown")
        return
    
    target_input = args[1]
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
    cur.execute("DELETE FROM admins WHERE user_id = %s", (target_id,))
    conn.commit()
    cur.close()
    conn.close()
    
    name = get_user_display_name(target_id)
    bot.reply_to(message, f"✅ У {name} (`{target_id}`) отозваны права администратора!")
    
    try:
        bot.send_message(target_id, "❌ Ваши права администратора были отозваны.")
    except:
        pass

# ==================== AUTOPOST ====================

@bot.callback_query_handler(func=lambda call: call.data.startswith('autopost_'))
def callback_autopost(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'autopost'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    data = call.data

    if data == "autopost_load_keys":
        bot.answer_callback_query(call.id, "📥 Отправьте ключи")
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(types.InlineKeyboardButton("✅ Завершить", callback_data="autopost_load_finish"), types.InlineKeyboardButton("🔙 Назад", callback_data="autopost_back"))
        msg = bot.send_message(user_id, "📥 Отправляйте ключи.\nКогда закончите - нажмите Завершить.", reply_markup=kb)
        autopost_loading[user_id] = {'keys': [], 'message_id': msg.message_id}
        return

    if data == "autopost_load_finish":
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
        callback_autopost(call)
        return

    if data == "autopost_start":
        keys = get_keys_from_db()
        if not keys:
            bot.answer_callback_query(call.id, "❌ Нет ключей")
            return
        config = get_autopost_config()
        config['enabled'] = True
        save_autopost_config(config)
        bot.answer_callback_query(call.id, "🚀 Запущен!")
        auto_post_keys_to_channel()
        callback_autopost(call)
        return

    if data == "autopost_channel_settings":
        config = get_autopost_config()
        text = f"⚙️ *Канал*\n\n📢 Текущий: {config['channel_id']}\n📝 Ветка: {config['topic_id'] if config['topic_id'] else 'Нет'}"
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(types.InlineKeyboardButton("📢 Сменить", callback_data="autopost_change_channel"), types.InlineKeyboardButton("🔙 Назад", callback_data="autopost_back"))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=kb)
        return

    if data == "autopost_change_channel":
        bot.answer_callback_query(call.id, "🔄 Отправьте новый канал")
        bot.send_message(user_id, "📢 Отправьте ссылку или ID канала.\nПример: `-1001234567890` или `@channel`", parse_mode="Markdown")
        search_cache[user_id] = {'action': 'autopost_set_channel'}
        return

    if data == "autopost_interval_settings":
        config = get_autopost_config()
        text = f"⏱ *Интервал*\n\n⏱ Текущий: {config['interval'] // 60} мин"
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(types.InlineKeyboardButton("⏱ Изменить", callback_data="autopost_set_interval"), types.InlineKeyboardButton("🔙 Назад", callback_data="autopost_back"))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=kb)
        return

    if data == "autopost_set_interval":
        bot.answer_callback_query(call.id, "⏱ Введите минуты")
        bot.send_message(user_id, "⏱ Введите интервал в минутах (5-1440):", parse_mode="Markdown")
        search_cache[user_id] = {'action': 'autopost_set_interval'}
        return

    if data == "autopost_back":
        config = get_autopost_config()
        status = "✅ ВКЛ" if config['enabled'] else "❌ ВЫКЛ"
        text = f"📡 *АВТОПОСТИНГ*\n\nСтатус: {status}\nИнтервал: {config['interval'] // 60} мин\nКанал: {config['channel_id']}"
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("📥 Загрузить ключи", callback_data="autopost_load_keys"),
            types.InlineKeyboardButton("🚀 Начать", callback_data="autopost_start"),
            types.InlineKeyboardButton("⚙️ Канал", callback_data="autopost_channel_settings"),
            types.InlineKeyboardButton("⏱ Интервал", callback_data="autopost_interval_settings"),
            types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back_panel")
        )
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=kb)
        return

@bot.message_handler(func=lambda m: m.chat.type == 'private' and m.from_user.id in autopost_loading)
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
        bot.reply_to(message, f"✅ Загружено {len(keys)}. Всего: {len(autopost_loading[user_id]['keys'])}")
    else:
        bot.reply_to(message, "❌ Не найдено ключей")

@bot.message_handler(func=lambda m: m.chat.type == 'private' and m.from_user.id in search_cache and search_cache.get(m.from_user.id, {}).get('action') == 'autopost_set_channel')
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
    bot.reply_to(message, f"✅ Канал установлен: {channel_id}")

@bot.message_handler(func=lambda m: m.chat.type == 'private' and m.from_user.id in search_cache and search_cache.get(m.from_user.id, {}).get('action') == 'autopost_set_interval')
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
        bot.reply_to(message, f"✅ Интервал: {minutes} мин")
    except:
        bot.reply_to(message, "❌ Введите число")

def auto_post_keys_to_channel():
    config = get_autopost_config()
    if not config['enabled']:
        return
    keys = get_keys_from_db()
    if not keys:
        return
    channel_id = config['channel_id']
    topic_id = config['topic_id']
    
    working = []
    for key in keys[:10]:
        match = re.search(r'@([\d\.]+):(\d+)', key)
        if match:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                result = sock.connect_ex((match.group(1), int(match.group(2))))
                sock.close()
                if result == 0:
                    working.append(key)
            except:
                pass
    if not working:
        working = keys[:1]
    
    key = working[0]
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
                
                flag_match = re.search(r'[🇦🇨🇧🇨🇨🇨🇩🇨🇪🇨🇫🇨🇬🇨🇭🇨🇮🇨🇯🇨🇰🇨🇱🇨🇲🇨🇳🇨🇴🇨🇵🇨🇶🇨🇷🇨🇸🇨🇹🇨🇺🇨🇻🇨🇼🇨🇽🇨🇾🇨🇿🇩🇪🇩🇬🇩🇯🇩🇰🇩🇲🇩🇴🇩🇿🇪🇦🇪🇨🇪🇪🇪🇬🇪🇭🇪🇷🇪🇸🇪🇹🇪🇺🇪🇮🇪🇰🇪🇱🇪🇲🇪🇳🇪🇴🇪🇵🇪🇶🇪🇷🇪🇸🇪🇹🇪🇺🇪🇮🇪🇰🇪🇱🇪🇲🇪🇳🇪🇴🇪🇵🇪🇶🇪🇷🇪🇸🇪🇹🇪🇺🇪🇮🇪🇰🇪🇱🇪🇲🇪🇳🇪🇴🇪🇵🇪🇶🇪🇷🇪🇸🇪🇹🇪🇺🇪🇮🇪🇰🇪🇱🇪🇲🇪🇳🇪🇴🇪🇵🇪🇶🇪🇷🇪🇸🇪🇹🇪🇺🇪🇮🇪🇰🇪🇱🇪🇲🇪🇳🇪🇴🇪🇵🇪🇶🇪🇷🇪🇸🇪🇹🇪🇺🇪🇮🇪🇰🇪🇱🇪🇲🇪🇳🇪🇴🇪🇵🇪🇶🇪🇷]', name)
                if flag_match:
                    country_emoji = flag_match.group(0)
                    flag_to_country = {
                        '🇺🇸': 'USA', '🇬🇧': 'UK', '🇩🇪': 'Germany', '🇫🇷': 'France',
                        '🇷🇺': 'Russia', '🇨🇳': 'China', '🇯🇵': 'Japan', '🇸🇬': 'Singapore',
                        '🇳🇱': 'Netherlands', '🇨🇦': 'Canada', '🇦🇺': 'Australia',
                        '🇮🇳': 'India', '🇧🇷': 'Brazil', '🇹🇷': 'Turkey', '🇮🇹': 'Italy',
                        '🇪🇸': 'Spain', '🇵🇱': 'Poland', '🇺🇦': 'Ukraine', '🇮🇱': 'Israel',
                        '🇦🇪': 'UAE', '🇸🇦': 'Saudi Arabia',
                    }
                    country_name = flag_to_country.get(country_emoji, country_emoji)
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
    
    if latency and latency < 50:
        speed = "100+ Mbps"
    elif latency and latency < 100:
        speed = "50-100 Mbps"
    elif latency and latency < 200:
        speed = "20-50 Mbps"
    elif latency and latency < 500:
        speed = "5-20 Mbps"
    else:
        speed = "1-5 Mbps"
    
    moscow_time = datetime.now() + timedelta(hours=3)
    
    formatted = f"""🚀 #1 | {country_emoji} {country_name}

┌ 🏷 Название: {name}
├ 🔗 Протокол: {proto_icon} {protocol}
├ 📡 Пинг: {latency} ms
├ ⚡ Скорость: {speed}
├ 🌍 Город: {country_name}
└ 🏢 Провайдер: {ip}

🔑 Ключ для подключения:
`{key}`

⏱ Проверено: {moscow_time.strftime('%H:%M:%S')} | 🤖 @Potyjno_vpn_bot
🔗 @ciorsa"""
    
    try:
        if topic_id:
            bot.send_message(channel_id, formatted, parse_mode="Markdown", message_thread_id=topic_id)
        else:
            bot.send_message(channel_id, formatted, parse_mode="Markdown")
        remove_used_keys([key])
        increment_setting('total_keys_issued', 1)
    except Exception as e:
        print(f"[autopost] Ошибка: {e}")

# ==================== ANNOUNCE ====================

@bot.callback_query_handler(func=lambda call: call.data == "announce_dm")
def callback_announce_dm(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'announce'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    bot.answer_callback_query(call.id, "📝 Отправьте текст/медиа")
    bot.send_message(user_id, "📨 *Рассылка в ЛС*\n\nОтправьте текст или медиа.", parse_mode="Markdown")
    announce_data[user_id] = {'type': 'dm', 'waiting': True}

@bot.callback_query_handler(func=lambda call: call.data == "announce_channels")
def callback_announce_channels(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'announce'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    bot.answer_callback_query(call.id)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT channel_id, channel_name FROM autopost_channels WHERE enabled = TRUE")
    channels = cur.fetchall()
    cur.close()
    conn.close()
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
    announce_data[user_id] = {'type': 'channel', 'channel_id': channel_id, 'waiting': True}

@bot.callback_query_handler(func=lambda call: call.data == "announce_all_channels")
def callback_announce_all_channels(call):
    user_id = call.from_user.id
    if not has_permission(user_id, 'announce'):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    bot.answer_callback_query(call.id, "📝 Отправьте текст/медиа")
    bot.send_message(user_id, "📢 *Объявление во все каналы*\n\nОтправьте текст или медиа.", parse_mode="Markdown")
    announce_data[user_id] = {'type': 'all_channels', 'waiting': True}

@bot.message_handler(func=lambda m: m.chat.type == 'private' and m.from_user.id in announce_data)
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
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users")
        users = cur.fetchall()
        cur.close()
        conn.close()
        sent = 0
        for (uid,) in users:
            try:
                if message.photo:
                    bot.send_photo(uid, message.photo[-1].file_id, caption=caption)
                elif message.video:
                    bot.send_video(uid, message.video.file_id, caption=caption)
                elif message.document:
                    bot.send_document(uid, message.document.file_id, caption=caption)
                else:
                    bot.send_message(uid, text)
                sent += 1
            except:
                pass
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
            bot.reply_to(message, "✅ Отправлено")
        except Exception as e:
            bot.reply_to(message, f"❌ Ошибка: {e}")
    elif announce_type == 'all_channels':
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT channel_id FROM autopost_channels WHERE enabled = TRUE")
        channels = cur.fetchall()
        cur.close()
        conn.close()
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
        bot.reply_to(message, f"✅ Отправлено в {sent} каналов")

# ==================== PRIORITY COMMAND HANDLER ====================

@bot.message_handler(commands=['admin', 'check', 'user', 'add_days', 'remove_days', 'block', 'unblock', 'cancel', 'ref', 'ref_debug', 'add_admin', 'remove_admin'])
def cmd_priority_handler(message):
    user_id = message.from_user.id
    command = message.text.split()[0].lower() if message.text else ''
    
    if user_id in decrypt_results:
        del decrypt_results[user_id]
    if user_id in check_results:
        del check_results[user_id]
    if user_id in proxy_check_results:
        del proxy_check_results[user_id]
    if user_id in admin_keys_loading:
        del admin_keys_loading[user_id]
    if user_id in autopost_loading:
        del autopost_loading[user_id]
    if user_id in announce_data:
        del announce_data[user_id]

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

@bot.message_handler(commands=['cancel'])
def cmd_cancel(message):
    if message.chat.type != 'private':
        return
    user_id = message.from_user.id
    cleared = False
    if user_id in decrypt_results:
        del decrypt_results[user_id]
        cleared = True
    if user_id in check_results:
        del check_results[user_id]
        cleared = True
    if user_id in proxy_check_results:
        del proxy_check_results[user_id]
        cleared = True
    if user_id in admin_keys_loading:
        del admin_keys_loading[user_id]
        cleared = True
    if user_id in autopost_loading:
        del autopost_loading[user_id]
        cleared = True
    if user_id in announce_data:
        del announce_data[user_id]
        cleared = True
    if cleared:
        bot.reply_to(message, "✅ Все режимы отменены.")
    else:
        bot.reply_to(message, "❌ Нет активных режимов для отмены.")

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
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "❌ /check [ID или @username]")
        return
    target_id = get_user_id_from_input(args[1])
    if not target_id:
        bot.reply_to(message, "❌ Неверный ID")
        return
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT subscription_end, is_blocked, token FROM users WHERE user_id = %s", (target_id,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    if not result:
        bot.reply_to(message, "❌ Не найден")
        return
    sub_end, blocked, token = result
    current_time = int(time.time())
    status = "🚫 Заблокирован" if blocked else ("✅ Активен" if sub_end > current_time else "❌ Неактивен")
    text = f"📋 *Проверка*\n🆔 ID: `{target_id}`\n📊 Статус: {status}\n🔗 Токен: `{token}`"
    bot.reply_to(message, text, parse_mode="Markdown")

def cmd_user_info(message):
    if message.chat.type != 'private':
        return
    user_id = message.from_user.id
    if not is_admin(user_id) or not has_permission(user_id, 'user_info'):
        return
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "❌ /user [ID или @username]")
        return
    target_id = get_user_id_from_input(args[1])
    if not target_id:
        bot.reply_to(message, "❌ Неверный ID")
        return
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT subscription_end, is_blocked, token, last_activity FROM users WHERE user_id = %s", (target_id,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    if not result:
        bot.reply_to(message, "❌ Не найден")
        return
    sub_end, blocked, token, last_act = result
    current_time = int(time.time())
    status = "🚫 Заблокирован" if blocked else ("✅ Активен" if sub_end > current_time else "❌ Неактивен")
    name = get_user_display_name(target_id)
    last_act_str = datetime.fromtimestamp(last_act).strftime("%d.%m.%Y %H:%M") if last_act else "Нет"
    text = f"👤 *{name}*\n🆔 ID: `{target_id}`\n📊 Статус: {status}\n📅 Подписка до: {datetime.fromtimestamp(sub_end).strftime('%d.%m.%Y') if sub_end else 'Нет'}\n🕐 Активность: {last_act_str}"
    bot.reply_to(message, text, parse_mode="Markdown")

def cmd_add_days(message):
    user_id = message.from_user.id
    if not is_admin(user_id) or not has_permission(user_id, 'add_days'):
        return
    args = message.text.split()
    if len(args) < 3:
        bot.reply_to(message, "❌ /add_days [ID или @username] [дни]")
        return
    target_id = get_user_id_from_input(args[1])
    if not target_id:
        bot.reply_to(message, "❌ Неверный ID")
        return
    try:
        days = int(args[2])
    except:
        bot.reply_to(message, "❌ Дни должны быть числом")
        return
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT subscription_end FROM users WHERE user_id = %s", (target_id,))
    result = cur.fetchone()
    if not result:
        cur.close()
        conn.close()
        bot.reply_to(message, "❌ Не найден")
        return
    current_time = int(time.time())
    current_end = result[0] if (result[0] and result[0] > current_time) else current_time
    new_end = current_end + days * 24 * 60 * 60
    cur.execute("UPDATE users SET subscription_end = %s WHERE user_id = %s", (new_end, target_id))
    conn.commit()
    cur.close()
    conn.close()
    bot.reply_to(message, f"✅ +{days} дней")

def cmd_remove_days(message):
    user_id = message.from_user.id
    if not is_admin(user_id) or not has_permission(user_id, 'remove_days'):
        return
    args = message.text.split()
    if len(args) < 3:
        bot.reply_to(message, "❌ /remove_days [ID или @username] [дни]")
        return
    target_id = get_user_id_from_input(args[1])
    if not target_id:
        bot.reply_to(message, "❌ Неверный ID")
        return
    try:
        days = int(args[2])
    except:
        bot.reply_to(message, "❌ Дни должны быть числом")
        return
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT subscription_end FROM users WHERE user_id = %s", (target_id,))
    result = cur.fetchone()
    if not result:
        cur.close()
        conn.close()
        bot.reply_to(message, "❌ Не найден")
        return
    current_time = int(time.time())
    current_end = result[0] if (result[0] and result[0] > current_time) else current_time
    new_end = current_end - days * 24 * 60 * 60
    if new_end < current_time:
        new_end = current_time - 1
    cur.execute("UPDATE users SET subscription_end = %s WHERE user_id = %s", (new_end, target_id))
    conn.commit()
    cur.close()
    conn.close()
    bot.reply_to(message, f"✅ -{days} дней")

def cmd_block_user(message):
    user_id = message.from_user.id
    if not is_admin(user_id) or not has_permission(user_id, 'block_user'):
        return
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "❌ /block [ID или @username]")
        return
    target_id = get_user_id_from_input(args[1])
    if not target_id:
        bot.reply_to(message, "❌ Неверный ID")
        return
    if target_id == ADMIN_ID:
        bot.reply_to(message, "❌ Нельзя")
        return
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET is_blocked = 1 WHERE user_id = %s", (target_id,))
    conn.commit()
    cur.close()
    conn.close()
    bot.reply_to(message, f"🚫 Заблокирован {target_id}")

def cmd_unblock_user(message):
    user_id = message.from_user.id
    if not is_admin(user_id) or not has_permission(user_id, 'unblock_user'):
        return
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "❌ /unblock [ID или @username]")
        return
    target_id = get_user_id_from_input(args[1])
    if not target_id:
        bot.reply_to(message, "❌ Неверный ID")
        return
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET is_blocked = 0 WHERE user_id = %s", (target_id,))
    conn.commit()
    cur.close()
    conn.close()
    bot.reply_to(message, f"✅ Разблокирован {target_id}")

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
    cur.execute("SELECT id, referrer_id, referred_id, rewarded FROM referrals ORDER BY id DESC LIMIT 10")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if not rows:
        bot.reply_to(message, "📭 Нет рефералов")
        return
    text = "📊 *Рефералы (последние 10):*\n\n"
    for ref_id, refr, refd, rew in rows:
        text += f"{'✅' if rew else '⏳'} {get_user_display_name(refd)} → {get_user_display_name(refr)}\n"
    bot.reply_to(message, text, parse_mode="Markdown")

# ==================== MESSAGE HANDLER ====================

@bot.message_handler(func=lambda m: m.chat.type == 'private')
def handle_private_messages(message):
    user_id = message.from_user.id
    text = message.text or ''

    if text.startswith('/'):
        return

    if user_id in announce_data:
        admin_announce_text(message)
        return

    if user_id in admin_keys_loading:
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
            admin_keys_loading[user_id]['keys'].extend(keys)
            admin_keys_loading[user_id]['keys'] = _dedup(admin_keys_loading[user_id]['keys'])
            bot.reply_to(message, f"✅ Загружено {len(keys)}. Всего: {len(admin_keys_loading[user_id]['keys'])}")
        else:
            bot.reply_to(message, "❌ Не найдено ключей")
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

    if user_id in check_results and check_results[user_id].get('waiting'):
        if message.document:
            try:
                file = bot.get_file(message.document.file_id)
                file_bytes = bot.download_file(file.file_path)
                raw = file_bytes.decode('utf-8', errors='ignore')
                keys = load_keys_from_text(raw)
                if not keys:
                    bot.reply_to(message, "❌ Не найдено ключей.")
                    return
                msg = bot.reply_to(message, f"🔍 Найдено ключей: {len(keys)}\n⏳ Начинаю проверку...")
                t = threading.Thread(target=check_keys_async, args=(message.chat.id, keys, user_id, msg.message_id))
                t.daemon = True
                t.start()
            except Exception as e:
                bot.reply_to(message, f"❌ Ошибка: {e}")
            return
        raw_text = text.strip()
        if raw_text:
            keys = load_keys_from_text(raw_text)
            if not keys:
                bot.reply_to(message, "❌ Не найдено ключей.")
                return
            msg = bot.reply_to(message, f"🔍 Найдено ключей: {len(keys)}\n⏳ Начинаю проверку...")
            t = threading.Thread(target=check_keys_async, args=(message.chat.id, keys, user_id, msg.message_id))
            t.daemon = True
            t.start()
        return

    if user_id in proxy_check_results and proxy_check_results[user_id].get('waiting'):
        if message.document:
            try:
                file = bot.get_file(message.document.file_id)
                file_bytes = bot.download_file(file.file_path)
                raw = file_bytes.decode('utf-8', errors='ignore')
                _process_proxies(message, raw, user_id)
            except Exception as e:
                bot.reply_to(message, f"❌ Ошибка: {e}")
            return
        raw_text = text.strip()
        if raw_text:
            _process_proxies(message, raw_text, user_id)
        return

    if user_id in search_cache:
        action = search_cache.get(user_id, {}).get('action', '')
        if action == 'autopost_set_channel':
            handle_autopost_set_channel(message)
            return
        if action == 'autopost_set_interval':
            handle_autopost_set_interval(message)
            return

    if text == "❓ Поддержка":
        bot.reply_to(message, f"💬 Поддержка: {SUPPORT}")
        return

    if text:
        bot.reply_to(message, "Используйте кнопки меню или /cancel для отмены текущего режима.", reply_markup=main_menu())

# ==================== CHECK KEYS ASYNC ====================

def check_keys_async(chat_id, keys, user_id, message_id):
    results = []
    working = 0
    not_working = 0
    for i, key in enumerate(keys):
        if i % 3 == 0:
            try:
                bot.edit_message_text(
                    f"🔍 Проверяю ключи...\n⏳ Прогресс: {i}/{len(keys)}",
                    chat_id, message_id
                )
            except:
                pass
        status = ping_key(key)
        results.append((key, status))
        if status:
            working += 1
        else:
            not_working += 1
    try:
        increment_setting('total_keys_checked', len(keys))
    except:
        pass
    report = (
        f"📊 *Результаты проверки*\n\n"
        f"✅ Работает: {working}\n"
        f"❌ Не работает: {not_working}\n"
        f"📡 Всего проверено: {len(keys)}\n\n"
    )
    if not_working > 0:
        report += "*❌ Не работающие ключи:*\n"
        for key, status in results:
            if not status:
                short_key = key[:60] + '...' if len(key) > 60 else key
                report += f"└ `{short_key}`\n"
    else:
        report += "🎉 *Все ключи работают!*"
    try:
        bot.send_message(chat_id, report, parse_mode="Markdown")
    except:
        bot.send_message(chat_id, report)
    if user_id in check_results:
        del check_results[user_id]

def ping_key(key):
    match = re.search(r'@([\d\.]+):(\d+)', key)
    if not match:
        return False
    ip = match.group(1)
    port = int(match.group(2))
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex((ip, port))
        sock.close()
        return result == 0
    except:
        return False

# ==================== PROXY CHECK ====================

def _process_proxies(message, raw_text, user_id):
    lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
    if not lines:
        bot.reply_to(message, "❌ Не найдено ни одной строки с прокси.")
        return
    lines = list(dict.fromkeys(lines))
    msg = bot.reply_to(
        message,
        f"🔍 Найдено прокси: {len(lines)}\n⏳ Начинаю проверку..."
    )
    t = threading.Thread(target=proxy_check_async, args=(message.chat.id, lines, user_id, msg.message_id))
    t.daemon = True
    t.start()

def proxy_check_async(chat_id, proxy_lines, user_id, message_id):
    results = []
    working = 0
    not_working = 0
    total = len(proxy_lines)
    for i, line in enumerate(proxy_lines):
        if i % 3 == 0:
            try:
                bot.edit_message_text(
                    f"🛡️ Проверяю прокси...\n⏳ Прогресс: {i}/{total}",
                    chat_id, message_id
                )
            except:
                pass
        test_result = _test_proxy_simple(line)
        results.append((line, test_result))
        if test_result:
            working += 1
        else:
            not_working += 1
    try:
        increment_setting('total_proxies_checked', total)
    except:
        pass
    report = (
        f"📊 *Результаты проверки прокси*\n\n"
        f"✅ Работает: {working}\n"
        f"❌ Не работает: {not_working}\n"
        f"🌐 Всего проверено: {total}\n\n"
    )
    if working > 0:
        report += "*✅ Работающие прокси:*\n"
        for line, res in results:
            if res:
                short_line = line[:50] + '...' if len(line) > 50 else line
                report += f"└ `{short_line}`\n"
        report += "\n"
    if not_working > 0:
        report += "*❌ Не работающие прокси:*\n"
        for line, res in results:
            if not res:
                short_line = line[:50] + '...' if len(line) > 50 else line
                report += f"└ `{short_line}`\n"
    if len(report) > 4000:
        report = report[:3950].rstrip() + "\n…"
    try:
        bot.send_message(chat_id, report, parse_mode="Markdown")
    except:
        try:
            bot.send_message(chat_id, report)
        except:
            pass
    if user_id in proxy_check_results:
        del proxy_check_results[user_id]

def _test_proxy_simple(line):
    try:
        parts = re.split(r'[:@]', line)
        if len(parts) >= 2:
            host = parts[0]
            port = parts[1]
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            result = sock.connect_ex((host, int(port)))
            sock.close()
            return result == 0
    except:
        pass
    return False

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

@app.route('/sub/<token>')
def subscription(token):
    if not token:
        return "Invalid token", 400
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id, subscription_end FROM users WHERE token = %s", (token,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    if not result:
        return "Invalid token", 404
    user_id, sub_end = result
    current_time = int(time.time())
    if sub_end < current_time:
        return "Subscription expired", 403
    keys = get_keys_from_db()
    if not keys:
        keys = DEFAULT_KEYS
    expire_timestamp = sub_end
    content = KEY_TEMPLATE.format(expire=expire_timestamp, keys='\n'.join(keys))
    return content, 200, {'Content-Type': 'text/plain; charset=utf-8'}

# ==================== MAIN ====================

if __name__ == "__main__":
    init_db()
    ensure_bot_start_time()
    print("✅ Бот запущен!")

    Thread(target=keep_alive_ping, daemon=True).start()
    Thread(target=auto_restart_monitor, daemon=True).start()

    from waitress import serve
    Thread(target=lambda: serve(app, host='0.0.0.0', port=int(os.getenv('PORT', 5000))), daemon=True).start()

    try:
        bot.infinity_polling()
    except Exception as e:
        print(f"❌ Ошибка бота: {e}")
        time.sleep(5)
        os.execv(sys.executable, ['python'] + sys.argv)
    
