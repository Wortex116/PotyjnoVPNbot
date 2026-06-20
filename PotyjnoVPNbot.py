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
from datetime import datetime
from threading import Thread

import telebot
from telebot import types
import psycopg2
import requests
from bs4 import BeautifulSoup
from flask import Flask

try:
    import socks  # noqa: F401  (PySocks) — нужен requests для socks5-прокси
    SOCKS_AVAILABLE = True
except ImportError:
    SOCKS_AVAILABLE = False

# ==================== CONFIG ====================
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', '8176196456'))
DATABASE_URL = os.getenv('DATABASE_URL')
CHANNEL_ID = -1003668283208
CHANNEL_LINK = 'https://t.me/ciorsa'
SUPPORT = '@mel1ste'

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)

check_results = {}
search_cache = {}
decrypt_results = {}
proxy_check_results = {}

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

# Приложения, чьи URI-схемы оборачивают ссылки/конфиги подписок
APP_SCHEMES = (
    r'incy|happ|v2ray|v2rayng|v2box|clash|sing-box|quantumult|surge|loon|'
    r'shadowrocket|stash|nekoray|nekobox|hiddify|streisand|karing|mihomo|flclash'
)

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
            added_by BIGINT,
            added_at BIGINT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            referrer_id BIGINT,
            referred_id BIGINT,
            reward_date BIGINT,
            rewarded INTEGER DEFAULT 0,
            PRIMARY KEY (referrer_id, referred_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

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
    """
    Атомарно увеличивает числовой счётчик в settings на `by` и возвращает
    новое значение. Использует один SQL-запрос с RETURNING — безопасно
    при параллельных вызовах из разных потоков/пользователей.
    """
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
    """
    Атомарно увеличивает и возвращает счётчик файлов расшифровки
    (хранится в таблице settings, ключ 'decrypt_file_counter').
    Используется один SQL-запрос с RETURNING, поэтому он безопасен
    при параллельных запросах от разных пользователей.
    """
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
    """
    Гарантирует, что в settings есть метка времени первого запуска бота
    (ключ bot_start_time). Если её нет — создаёт текущим временем.
    Используется для подсчёта "стажа бота".
    """
    existing = get_setting('bot_start_time', '')
    if not existing:
        set_setting('bot_start_time', str(int(time.time())))

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
    """
    Пытается декодировать строку как Base64 (стандартный и urlsafe вариант,
    с разным паддингом). Возвращает декодированный текст или None.
    """
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
            except Exception:
                continue
    return None

def _try_multilevel_b64(data, max_depth=4):
    """
    Многоуровневый Base64: некоторые подписки кодируют Base64 внутри
    Base64 (иногда дважды-трижды). Рекурсивно раскрываем до max_depth
    уровней. На каждом уровне сразу проверяем — не появились ли уже
    читаемые VPN-ключи, и собираем их по пути (а не только с последнего
    слоя), потому что промежуточный текст иногда уже содержит ключи
    вперемешку с ещё закодированными фрагментами.
    """
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
    """
    Разворачивает обёртки и схемы приложений до реального URL или payload:
      - happ://crypt5/<payload>, happ://crypt/<payload>, happ://add/<payload>
      - incy://add/<payload>, incy://sub/<payload>
      - <scheme>://install-config?url=<encoded>
      - https://proxy.domain/https://real.url            (прокси-обёртка)
      - https://proxy.domain/path?url=https://real.url   (прокси-обёртка, query)
      - https://proxy.domain/path?u=...|target=...|link=... (вариации query)
    Возвращает либо http(s) URL для скачивания, либо payload (возможный
    Base64 или сырые ключи) для дальнейшего разбора.
    """
    raw_url = raw_url.strip()

    # 1. Схемы приложений: scheme://action/payload (crypt, crypt5, crypt2...)
    app_scheme = re.match(
        r'^(?:' + APP_SCHEMES + r')://(?:add|sub|crypt\d*|import|install|update)/+(.+)$',
        raw_url, re.IGNORECASE
    )
    if app_scheme:
        payload = urllib.parse.unquote(app_scheme.group(1).strip())
        payload = payload.split('#')[0]
        return payload  # либо http(s) URL, либо Base64/прямые ключи

    # 2. Схемы вида scheme://install-config?url=ENCODED_URL
    qs_scheme = re.match(
        r'^(?:' + APP_SCHEMES + r')://[^?]*\?(?:.*&)?url=([^&]+)',
        raw_url, re.IGNORECASE
    )
    if qs_scheme:
        return urllib.parse.unquote(qs_scheme.group(1).strip())

    # 3. Прокси-обёртка по пути: https://proxy.domain/https://real.url
    proxy_wrap = re.match(r'^https?://[^/]+/+(https?://.+)$', raw_url, re.IGNORECASE)
    if proxy_wrap:
        return proxy_wrap.group(1)

    # 4. Прокси-обёртка через query ?url=
    proxy_qs = re.match(r'^https?://[^?]+\?(?:.*&)?url=(https?[^&]+)', raw_url, re.IGNORECASE)
    if proxy_qs:
        return urllib.parse.unquote(proxy_qs.group(1))

    # 5. Прокси-обёртка через альтернативные query-параметры (?u=, ?target=, ?link=, ?dest=)
    proxy_qs_alt = re.match(r'^https?://[^?]+\?(?:.*&)?(?:u|target|link|dest)=([^&]+)', raw_url, re.IGNORECASE)
    if proxy_qs_alt:
        candidate = urllib.parse.unquote(proxy_qs_alt.group(1))
        if re.match(r'https?://', candidate, re.IGNORECASE):
            return candidate
        decoded = _try_b64(candidate)
        if decoded and re.match(r'https?://', decoded.strip(), re.IGNORECASE):
            return decoded.strip()

    return raw_url

def _parse_keys_from_content(content):
    """
    Извлекает VPN-ключи из произвольного содержимого подписки.
    Поддерживает: прямые ключи, одно- и многоуровневый Base64,
    HTML (текстовые узлы + атрибуты href/data-*), JSON (строковые
    поля с конфигами), построчный разбор смешанных форматов.
    """
    all_keys = []
    if not content:
        return []

    # 1. Прямые ключи в исходном тексте
    all_keys.extend(_extract_vpn_keys(content))

    # 2. Многоуровневый Base64 для всего блока контента
    all_keys.extend(_try_multilevel_b64(content.strip()))

    # 3. Построчный разбор
    for line in content.splitlines():
        line = line.strip()
        if not line or len(line) < 8:
            continue
        all_keys.extend(_extract_vpn_keys(line))
        if len(line) >= 16:
            all_keys.extend(_try_multilevel_b64(line, max_depth=3))

    # 4. HTML — текстовые узлы и атрибуты (href, src, data-*)
    if '<' in content and '>' in content:
        parsed_ok = False
        for parser_name in ('html5lib', 'html.parser'):
            try:
                soup = BeautifulSoup(content, parser_name)
                parsed_ok = True
                break
            except Exception:
                continue
        if parsed_ok:
            try:
                for elem in soup.find_all(string=True):
                    txt = str(elem)
                    all_keys.extend(_extract_vpn_keys(txt))
                    if len(txt.strip()) >= 16:
                        all_keys.extend(_try_multilevel_b64(txt.strip(), max_depth=2))
                for tag in soup.find_all(True):
                    for attr_name, attr_val in tag.attrs.items():
                        if isinstance(attr_val, str):
                            all_keys.extend(_extract_vpn_keys(urllib.parse.unquote(attr_val)))
            except Exception:
                pass

    # 5. JSON — значения строковых полей (config/link/uri/value и т.п.)
    try:
        json_str_matches = re.findall(r'"((?:[^"\\]|\\.)*)"', content)
        for m in json_str_matches:
            try:
                unescaped = m.encode().decode('unicode_escape')
            except Exception:
                unescaped = m
            if re.search(r'(?:vless|vmess|trojan|ss|ssr|hysteria)://', unescaped, re.IGNORECASE):
                all_keys.extend(_extract_vpn_keys(unescaped))
            elif len(unescaped) >= 24:
                all_keys.extend(_try_multilevel_b64(unescaped, max_depth=2))
    except Exception:
        pass

    return _dedup(all_keys)

def load_keys_from_url(raw_url):
    url = _resolve_url(raw_url)
    if not re.match(r'https?://', url, re.IGNORECASE):
        decoded = _try_b64(url)
        if decoded:
            keys = _extract_vpn_keys(decoded)
            if keys:
                return _dedup(keys)
        return _dedup(_extract_vpn_keys(url))

    headers = {'User-Agent': 'v2rayNG/1.8.7', 'Accept': '*/*'}
    content = None
    for verify in [True, False]:
        try:
            resp = requests.get(url, headers=headers, timeout=30, verify=verify)
            content = resp.text
            break
        except:
            continue
    if not content:
        return []
    return _parse_keys_from_content(content)

def load_keys_from_text(text):
    return _parse_keys_from_content(text)

def _finish_update_keys(message, keys, source_label):
    if not keys:
        bot.reply_to(
            message,
            "❌ Не найдено ни одного VPN ключа.\n\n"
            "Поддерживается:\n"
            "• vless:// vmess:// trojan:// ss:// и др.\n"
            "• Base64 подписка (в т.ч. многоуровневая)\n"
            "• URL подписки (включая happ.dska.su и подобные)\n"
            "• HTML страница с ключами"
        )
        return
    save_keys_to_db(keys)
    proto_stats = {}
    for k in keys:
        m = re.match(r'([a-z0-9+]+)://', k, re.IGNORECASE)
        if m:
            p = m.group(1).lower()
            proto_stats[p] = proto_stats.get(p, 0) + 1
    stats = '\n'.join(f"  • {p}:// — {c}" for p, c in sorted(proto_stats.items(), key=lambda x: -x[1]))
    bot.reply_to(
        message,
        f"✅ Ключи обновлены!\n\n"
        f"📊 Загружено ключей: {len(keys)}\n"
        f"📋 По протоколам:\n{stats}\n"
        f"🔗 Источник: {source_label}"
    )

# ==================== CHECKS ====================

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

# ==================== KEYBOARDS ====================

def main_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(
        types.KeyboardButton("👤 Личный кабинет"),
        types.KeyboardButton("📡 Моя подписка")
    )
    kb.add(
        types.KeyboardButton("👥 Рефералы"),
        types.KeyboardButton("🏆 Топ рефералов")
    )
    kb.add(
        types.KeyboardButton("🔓 Декскриптор")
    )
    kb.add(
        types.KeyboardButton("❓ Поддержка")
    )
    return kb

def decryptor_menu():
    """
    Клавиатура раздела "Декскриптор": статистика бота + доступ
    к проверке ключей, проверке прокси, расшифровке подписки,
    а также возврат в главное меню.
    """
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(
        types.KeyboardButton("📊 Стаж бота"),
        types.KeyboardButton("🔑 Проверено ключей")
    )
    kb.add(
        types.KeyboardButton("🔓 Расшифровано подписок"),
        types.KeyboardButton("🌐 Проверено прокси")
    )
    kb.add(
        types.KeyboardButton("🔍 Проверка ключей"),
        types.KeyboardButton("🛡️ Проверка прокси")
    )
    kb.add(
        types.KeyboardButton("🔓 Расшифровать подписку")
    )
    kb.add(
        types.KeyboardButton("🏠 Главное меню")
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
    """
    Возвращает словарь с актуальной статистикой бота:
      - uptime_seconds / uptime_text — стаж бота с первого запуска
      - total_keys_checked          — кол-во проверенных VPN-ключей
      - total_decryptions           — кол-во расшифрованных подписок
      - total_proxies_checked       — кол-во проверенных прокси
    Все значения читаются из таблицы settings.
    """
    ensure_bot_start_time()
    start_time = int(get_setting('bot_start_time', str(int(time.time()))))
    uptime_seconds = int(time.time()) - start_time

    total_keys_checked = int(get_setting('total_keys_checked', '0'))
    total_decryptions = int(get_setting('total_decryptions', '0'))
    total_proxies_checked = int(get_setting('total_proxies_checked', '0'))

    return {
        'start_time': start_time,
        'uptime_seconds': uptime_seconds,
        'uptime_text': _format_duration(uptime_seconds),
        'total_keys_checked': total_keys_checked,
        'total_decryptions': total_decryptions,
        'total_proxies_checked': total_proxies_checked,
    }

# ==================== /start ====================

@bot.message_handler(commands=['start'])
def cmd_start(message):
    if message.chat.type != 'private':
        bot.reply_to(message, "⚠️ Бот работает только в личных сообщениях.")
        return

    user_id = message.from_user.id
    current_time = int(time.time())

    if is_blocked(user_id):
        bot.reply_to(message, blocked_message())
        return

    referrer_id = None
    if message.text and 'start=ref_' in message.text:
        parts = message.text.split('start=ref_')
        if len(parts) > 1:
            try:
                referrer_id = int(parts[1].strip())
            except:
                referrer_id = None

    if referrer_id and referrer_id != user_id:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM referrals WHERE referrer_id = %s AND referred_id = %s",
            (referrer_id, user_id)
        )
        already_ref = cur.fetchone()
        cur.close()
        conn.close()

        if not already_ref:
            if can_add_referral(referrer_id):
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO referrals (referrer_id, referred_id, reward_date, rewarded) VALUES (%s, %s, %s, 0)",
                    (referrer_id, user_id, current_time)
                )
                conn.commit()
                cur.close()
                conn.close()
                name = message.from_user.first_name or str(user_id)
                try:
                    bot.send_message(referrer_id, f"🔔 Новый реферал! Пользователь {name} присоединился по вашей реферальной ссылке.")
                except:
                    pass
                if get_setting('referral_enabled') == '1' and is_subscribed(referrer_id):
                    conn = get_db_connection()
                    cur = conn.cursor()
                    cur.execute("SELECT subscription_end FROM users WHERE user_id = %s", (referrer_id,))
                    ref_result = cur.fetchone()
                    if ref_result:
                        new_end = ref_result[0] + 3 * 24 * 60 * 60
                        cur.execute("UPDATE users SET subscription_end = %s WHERE user_id = %s", (new_end, referrer_id))
                        cur.execute(
                            "UPDATE referrals SET rewarded = 1 WHERE referrer_id = %s AND referred_id = %s",
                            (referrer_id, user_id)
                        )
                        conn.commit()
                        try:
                            bot.send_message(referrer_id, "🎉 Вам начислено +3 дня!")
                        except:
                            pass
                    cur.close()
                    conn.close()
            else:
                try:
                    bot.send_message(referrer_id, "⚠️ Вы достигли лимита рефералов (10 в день). Попробуйте завтра.")
                except:
                    pass

    if not is_subscribed(user_id):
        bot.reply_to(message, "⚠️ Подпишитесь на канал, чтобы пользоваться ботом.", reply_markup=subscribe_button())
        return

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id, last_activity FROM users WHERE user_id = %s", (user_id,))
    user = cur.fetchone()

    if not user:
        token = generate_subscription_token()
        sub_end = current_time + 7 * 24 * 60 * 60
        cur.execute(
            "INSERT INTO users (user_id, subscription_end, last_activity, is_blocked, token) VALUES (%s, %s, %s, 0, %s)",
            (user_id, sub_end, current_time, token)
        )
        conn.commit()
        cur.close()
        conn.close()
        bot.reply_to(message, "🎉 Добро пожаловать! Вам выдана подписка на 7 дней.")
    else:
        last_activity = user[1] or 0
        days_since_last = (current_time - last_activity) // (24 * 60 * 60)
        welcome_text = "👋 С возвращением!" if days_since_last >= 3 else "👋 Добро пожаловать!"
        cur.execute("UPDATE users SET last_activity = %s WHERE user_id = %s", (current_time, user_id))
        conn.commit()
        cur.close()
        conn.close()
        bot.reply_to(message, welcome_text)

    bot.send_message(user_id, "Выберите действие:", reply_markup=main_menu())

# ==================== ЛИЧНЫЙ КАБИНЕТ ====================

@bot.message_handler(func=lambda m: m.text == "👤 Личный кабинет")
def cabinet(message):
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
        bot.reply_to(message, "❌ Вы не зарегистрированы. Используйте /start")
        return
    subscription_end = result[0]
    if subscription_end and subscription_end > current_time:
        status = "✅ Активна"
        days_left = (subscription_end - current_time) // (24 * 60 * 60)
        hours_left = ((subscription_end - current_time) // 3600) % 24
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

# ==================== МОЯ ПОДПИСКА ====================

@bot.message_handler(func=lambda m: m.text == "📡 Моя подписка")
def my_subscription(message):
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
        bot.reply_to(
            message,
            f"🔗 Ваша ссылка для импорта в VPN-клиент:\n\n{link}\n\nСкопируйте её и вставьте в приложение (V2Ray, Hiddify, Nekobox и др.)"
        )
    else:
        bot.reply_to(
            message,
            f"❌ Ваша подписка неактивна или истекла.\n\nДля продления обратитесь к администратору:\n{SUPPORT}"
        )

# ==================== РЕФЕРАЛЫ ====================

@bot.message_handler(func=lambda m: m.text == "👥 Рефералы")
def referrals(message):
    if message.chat.type != 'private':
        return
    user_id = message.from_user.id
    if is_blocked(user_id):
        bot.reply_to(message, blocked_message())
        return
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
    if not cur.fetchone():
        cur.close()
        conn.close()
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
    cur.close()
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
        f"💬 *Вопросы?* Пишите в поддержку: {SUPPORT}"
    )
    bot.reply_to(message, text, parse_mode="Markdown")

# ==================== ТОП РЕФЕРАЛОВ ====================

@bot.message_handler(func=lambda m: m.text == "🏆 Топ рефералов")
def top_referrals(message):
    if message.chat.type != 'private':
        return
    user_id = message.from_user.id
    if is_blocked(user_id):
        bot.reply_to(message, blocked_message())
        return
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT referrer_id, COUNT(*) as count FROM referrals GROUP BY referrer_id ORDER BY count DESC LIMIT 10"
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if not rows:
        bot.reply_to(message, "📭 Пока нет рефералов.")
        return
    text = "🏆 *Топ рефералов:*\n\n"
    medals = ['🥇', '🥈', '🥉']
    for i, (ref_id, count) in enumerate(rows):
        name = get_user_display_name(ref_id)
        icon = medals[i] if i < 3 else f"{i+1}."
        text += f"{icon} {name} — {count} реф.\n"
    bot.reply_to(message, text, parse_mode="Markdown")

# ==================== ДЕКСКРИПТОР (вход в раздел статистики) ====================

@bot.message_handler(func=lambda m: m.text == "🔓 Декскриптор")
def decryptor_section(message):
    if message.chat.type != 'private':
        return
    user_id = message.from_user.id
    if is_blocked(user_id):
        bot.reply_to(message, blocked_message())
        return
    stats = get_bot_stats()
    text = (
        "🔓 *Декскриптор*\n\n"
        f"📊 Стаж бота: {stats['uptime_text']}\n"
        f"🔑 Проверено ключей: {stats['total_keys_checked']}\n"
        f"🔓 Расшифровано подписок: {stats['total_decryptions']}\n"
        f"🌐 Проверено прокси: {stats['total_proxies_checked']}\n\n"
        "Выберите действие ниже 👇"
    )
    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=decryptor_menu())

# ---- Кнопки статистики внутри раздела "Декскриптор" ----

@bot.message_handler(func=lambda m: m.text == "📊 Стаж бота")
def stat_uptime(message):
    if message.chat.type != 'private':
        return
    if is_blocked(message.from_user.id):
        bot.reply_to(message, blocked_message())
        return
    stats = get_bot_stats()
    start_date = datetime.fromtimestamp(stats['start_time']).strftime("%d.%m.%Y в %H:%M")
    bot.reply_to(
        message,
        f"📊 *Стаж бота*\n\n"
        f"🚀 Первый запуск: {start_date}\n"
        f"⏳ Работает: {stats['uptime_text']}",
        parse_mode="Markdown"
    )

@bot.message_handler(func=lambda m: m.text == "🔑 Проверено ключей")
def stat_keys_checked(message):
    if message.chat.type != 'private':
        return
    if is_blocked(message.from_user.id):
        bot.reply_to(message, blocked_message())
        return
    stats = get_bot_stats()
    bot.reply_to(
        message,
        f"🔑 *Проверено ключей*\n\n"
        f"📡 Всего за всё время: {stats['total_keys_checked']}",
        parse_mode="Markdown"
    )

@bot.message_handler(func=lambda m: m.text == "🔓 Расшифровано подписок")
def stat_decryptions(message):
    if message.chat.type != 'private':
        return
    if is_blocked(message.from_user.id):
        bot.reply_to(message, blocked_message())
        return
    stats = get_bot_stats()
    bot.reply_to(
        message,
        f"🔓 *Расшифровано подписок*\n\n"
        f"📁 Всего за всё время: {stats['total_decryptions']}",
        parse_mode="Markdown"
    )

@bot.message_handler(func=lambda m: m.text == "🌐 Проверено прокси")
def stat_proxies_checked(message):
    if message.chat.type != 'private':
        return
    if is_blocked(message.from_user.id):
        bot.reply_to(message, blocked_message())
        return
    stats = get_bot_stats()
    bot.reply_to(
        message,
        f"🌐 *Проверено прокси*\n\n"
        f"🛡️ Всего за всё время: {stats['total_proxies_checked']}",
        parse_mode="Markdown"
    )

@bot.message_handler(func=lambda m: m.text == "🏠 Главное меню")
def back_to_main_menu(message):
    if message.chat.type != 'private':
        return
    if is_blocked(message.from_user.id):
        bot.reply_to(message, blocked_message())
        return
    bot.reply_to(message, "🏠 Главное меню", reply_markup=main_menu())

# ==================== ПРОВЕРКА КЛЮЧЕЙ ====================

@bot.message_handler(func=lambda m: m.text == "🔍 Проверка ключей")
def check_keys_start(message):
    if message.chat.type != 'private':
        return
    user_id = message.from_user.id
    if is_blocked(user_id):
        bot.reply_to(message, blocked_message())
        return
    check_results[user_id] = {'waiting': True}
    bot.reply_to(
        message,
        "📡 Отправьте файл или текст с ключами (в формате vless://...)\n\n"
        "Я проверю их на доступность (пинг).\n"
        "Ключи должны быть в формате:\nvless://...\nvless://...\n\n"
        "⏳ Проверка может занять до 30 секунд."
    )

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

    # Сохраняем счётчик проверенных ключей в settings
    try:
        increment_setting('total_keys_checked', len(keys))
    except Exception as e:
        print(f"[stats] не удалось обновить total_keys_checked: {e}")

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

# ==================== ПРОВЕРКА ПРОКСИ ====================

PROXY_LINE_PATTERN = re.compile(
    r'^(?:(?P<scheme>https?|socks5h?|socks4)://)?'
    r'(?:(?P<user>[^:@\s]+):(?P<pass>[^:@\s]*)@)?'
    r'(?P<host>[A-Za-z0-9\.\-]+):(?P<port>\d{1,5})'
    r'(?::(?P<user2>[^:@\s]+):(?P<pass2>[^:@\s]*))?'
    r'$',
    re.IGNORECASE
)

def _parse_proxy_line(line):
    """
    Разбирает строку прокси в одном из форматов:
      ip:port
      ip:port:user:pass
      user:pass@ip:port
      scheme://ip:port
      scheme://user:pass@ip:port
    Возвращает dict {host, port, user, password, scheme_hint} или None.
    scheme_hint — если схема указана явно (http/socks5/socks4), иначе None
    (тогда при проверке автоопределяем перебором).
    """
    line = line.strip().strip(',;')
    if not line:
        return None
    m = PROXY_LINE_PATTERN.match(line)
    if not m:
        return None
    gd = m.groupdict()
    host = gd.get('host')
    port = gd.get('port')
    if not host or not port:
        return None
    user = gd.get('user') or gd.get('user2')
    password = gd.get('pass') or gd.get('pass2')
    scheme_hint = gd.get('scheme')
    if scheme_hint:
        scheme_hint = scheme_hint.lower()
        if scheme_hint in ('socks5h',):
            scheme_hint = 'socks5'
    return {
        'host': host,
        'port': int(port),
        'user': user,
        'password': password,
        'scheme_hint': scheme_hint,
        'raw': line,
    }

def _build_proxy_url(proxy_info, scheme):
    host = proxy_info['host']
    port = proxy_info['port']
    user = proxy_info.get('user')
    password = proxy_info.get('password')
    auth = ''
    if user:
        auth = urllib.parse.quote(user, safe='')
        if password:
            auth += ':' + urllib.parse.quote(password, safe='')
        auth += '@'
    return f"{scheme}://{auth}{host}:{port}"

TEST_URL = "http://httpbin.org/ip"
TEST_URL_FALLBACK = "https://api.ipify.org?format=json"

def _test_proxy(proxy_info, timeout=8):
    """
    Делает реальный HTTP-запрос через прокси, проверяя оба возможных
    протокола — http и socks5 (если явно не указана схема), и возвращает
    первый сработавший вариант.
    Возвращает dict {ok, scheme, latency_ms, error}.
    """
    schemes_to_try = []
    if proxy_info.get('scheme_hint'):
        hint = proxy_info['scheme_hint']
        if hint == 'socks4':
            schemes_to_try = ['socks4']
        elif hint == 'socks5':
            schemes_to_try = ['socks5']
        else:
            schemes_to_try = ['http']
    else:
        # Без явной схемы — пробуем http, затем socks5 (самые частые случаи)
        schemes_to_try = ['http', 'socks5']

    last_error = None
    for scheme in schemes_to_try:
        if scheme in ('socks5', 'socks4') and not SOCKS_AVAILABLE:
            last_error = "PySocks не установлен на сервере (pip install pysocks)"
            continue
        proxy_url = _build_proxy_url(proxy_info, scheme)
        proxies = {'http': proxy_url, 'https': proxy_url}
        start = time.time()
        try:
            resp = requests.get(TEST_URL, proxies=proxies, timeout=timeout)
            if resp.status_code == 200:
                latency_ms = int((time.time() - start) * 1000)
                return {'ok': True, 'scheme': scheme, 'latency_ms': latency_ms, 'error': None}
            last_error = f"HTTP {resp.status_code}"
        except Exception as e1:
            last_error = str(e1)
            # Пробуем запасной тест-URL на случай если httpbin недоступен
            try:
                start2 = time.time()
                resp2 = requests.get(TEST_URL_FALLBACK, proxies=proxies, timeout=timeout)
                if resp2.status_code == 200:
                    latency_ms = int((time.time() - start2) * 1000)
                    return {'ok': True, 'scheme': scheme, 'latency_ms': latency_ms, 'error': None}
                last_error = f"HTTP {resp2.status_code}"
            except Exception as e2:
                last_error = str(e2)
                continue
    return {'ok': False, 'scheme': None, 'latency_ms': None, 'error': last_error}

@bot.message_handler(func=lambda m: m.text == "🛡️ Проверка прокси")
def proxy_check_start(message):
    if message.chat.type != 'private':
        return
    user_id = message.from_user.id
    if is_blocked(user_id):
        bot.reply_to(message, blocked_message())
        return
    proxy_check_results[user_id] = {'waiting': True}
    socks_note = "" if SOCKS_AVAILABLE else "\n⚠️ На сервере не установлен PySocks — проверка socks5 временно недоступна."
    bot.reply_to(
        message,
        "🛡️ *Проверка прокси*\n\n"
        "Отправьте список прокси (каждая на новой строке). Поддерживаемые форматы:\n\n"
        "• `ip:port`\n"
        "• `ip:port:user:pass`\n"
        "• `user:pass@ip:port`\n"
        "• `http://ip:port` или `socks5://ip:port`\n"
        "• `http://user:pass@ip:port` или `socks5://user:pass@ip:port`\n\n"
        "Тип прокси (http / socks5) бот определит автоматически, если он не указан явно.\n"
        f"⏳ Проверка может занять время в зависимости от количества прокси.{socks_note}",
        parse_mode="Markdown"
    )

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
        proxy_info = _parse_proxy_line(line)
        if not proxy_info:
            results.append((line, {'ok': False, 'scheme': None, 'latency_ms': None, 'error': 'Не удалось распознать формат'}))
            not_working += 1
            continue
        test_result = _test_proxy(proxy_info)
        results.append((line, test_result))
        if test_result['ok']:
            working += 1
        else:
            not_working += 1

    try:
        increment_setting('total_proxies_checked', total)
    except Exception as e:
        print(f"[stats] не удалось обновить total_proxies_checked: {e}")

    report = (
        f"📊 *Результаты проверки прокси*\n\n"
        f"✅ Работает: {working}\n"
        f"❌ Не работает: {not_working}\n"
        f"🌐 Всего проверено: {total}\n\n"
    )
    if working > 0:
        report += "*✅ Работающие прокси:*\n"
        for line, res in results:
            if res['ok']:
                short_line = line[:50] + '...' if len(line) > 50 else line
                report += f"└ `{short_line}` — {res['scheme']}, {res['latency_ms']} мс\n"
        report += "\n"
    if not_working > 0:
        report += "*❌ Не работающие прокси:*\n"
        for line, res in results:
            if not res['ok']:
                short_line = line[:50] + '...' if len(line) > 50 else line
                report += f"└ `{short_line}`\n"

    # Telegram ограничивает длину сообщения — режем при необходимости
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

def _process_proxies(message, raw_text, user_id):
    lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
    if not lines:
        bot.reply_to(message, "❌ Не найдено ни одной строки с прокси.")
        return
    lines = list(dict.fromkeys(lines))
    msg = bot.reply_to(
        message,
        f"🔍 Найдено прокси: {len(lines)}\n⏳ Начинаю проверку...\nЭто может занять некоторое время."
    )
    t = threading.Thread(target=proxy_check_async, args=(message.chat.id, lines, user_id, msg.message_id))
    t.daemon = True
    t.start()

# ==================== РАСШИФРОВКА ПОДПИСКИ ====================

@bot.message_handler(func=lambda m: m.text == "🔓 Расшифровать подписку")
def decrypt_subscription_start(message):
    if message.chat.type != 'private':
        return
    user_id = message.from_user.id
    if is_blocked(user_id):
        bot.reply_to(message, blocked_message())
        return
    decrypt_results[user_id] = {'waiting': True}
    bot.reply_to(
        message,
        "🔓 *Расшифровка VPN подписки*\n\n"
        "Отправьте ссылку, текст или файл подписки.\n\n"
        "Поддерживаю:\n"
        "• `https://example.com/sub` — URL подписки\n"
        "• `https://happ.dska.su/https://...` — прокси-обёртка\n"
        "• `happ://crypt5/...` `happ://crypt/...` — схема Happ\n"
        "• `incy://add/...` — схема Hiddify\n"
        "• `incy://add/BASE64==` — Hiddify с Base64\n"
        "• `happ://add/...` `shadowrocket://...` и др.\n"
        "• `vless://` `vmess://` `trojan://` `ss://` `ssr://`\n"
        "• `hysteria2://` `tuic://` `wg://` и др.\n"
        "• Многоуровневый Base64 текст подписки\n"
        "• HTML страница и JSON с конфигами\n"
        "• .txt файл с ключами\n\n"
        "📄 Получите `.txt` файл со всеми ключами.",
        parse_mode="Markdown"
    )

def _do_decrypt(message, user_id, text=None, file_bytes=None, file_name=None):
    if user_id in decrypt_results:
        del decrypt_results[user_id]

    try:
        wait_msg = bot.reply_to(message, "⏳ Обрабатываю подписку...")
    except Exception:
        wait_msg = None

    def process():
        try:
            # ---- Шаг 1: парсинг ключей ----
            try:
                if file_bytes is not None:
                    raw = file_bytes.decode('utf-8', errors='ignore')
                    keys, steps = _parse_subscription_any(raw, source_label=file_name or 'файл')
                else:
                    keys, steps = _parse_subscription_any(text)
            except Exception as e:
                keys, steps = [], [f"Ошибка парсинга: {e}"]

            if wait_msg:
                try:
                    bot.delete_message(message.chat.id, wait_msg.message_id)
                except Exception:
                    pass

            # ---- Если ключи не найдены ----
            if not keys:
                info = '\n'.join(steps) if steps else '—'
                err_text = (
                    "❌ Не удалось найти VPN ключи\n\n"
                    f"Шаги:\n{info}\n\n"
                    "Убедитесь что ссылка рабочая и содержит VPN ключи."
                )
                # ВАЖНО: без parse_mode="Markdown" — в URL/тексте могут быть
                # символы _ * ` [ ], которые ломали парсинг и "роняли" поток
                # без какого-либо сообщения пользователю.
                try:
                    bot.reply_to(message, err_text)
                except Exception:
                    try:
                        bot.send_message(message.chat.id, err_text)
                    except Exception as e3:
                        print(f"[decrypt] не удалось отправить сообщение об ошибке: {e3}")
                return

            # ---- Счётчик расшифрованных подписок (для статистики) ----
            try:
                increment_setting('total_decryptions', 1)
            except Exception as e:
                print(f"[stats] не удалось обновить total_decryptions: {e}")

            # ---- Порядковый номер файла + дата ----
            try:
                file_number = get_next_file_number()
            except Exception as e:
                print(f"[decrypt] не удалось получить номер файла: {e}")
                file_number = 0
            date_str = datetime.now().strftime("%d.%m.%Y")
            filename = f"{file_number:06d}_{date_str}.txt"

            # ---- Сборка содержимого файла ----
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
            # Telegram режет caption на отправке документа лимитом 1024 символа
            if len(caption) > 1024:
                caption = caption[:1000].rstrip() + "\n…"

            buf = io.BytesIO(file_content.encode('utf-8'))
            buf.name = filename
            try:
                bot.send_document(
                    message.chat.id, buf,
                    caption=caption,
                    visible_file_name=filename
                )
            except Exception as e1:
                print(f"[decrypt] первая попытка send_document не удалась: {e1}")
                try:
                    buf.seek(0)
                    bot.send_document(
                        message.chat.id, buf,
                        caption=f"✅ Найдено ключей: {len(keys)}\n📁 Файл №{file_number:06d}",
                        visible_file_name=filename
                    )
                except Exception as e2:
                    print(f"[decrypt] вторая попытка send_document не удалась: {e2}")
                    try:
                        bot.send_message(message.chat.id, f"❌ Не удалось отправить файл: {e2}")
                    except Exception:
                        pass
        except Exception as outer_e:
            # Сетевая ошибка вызывающая истечение времени или иной непредвиденный сбой —
            # ранее тут поток просто тихо умирал и пользователь не получал НИЧЕГО.
            print(f"[decrypt] непредвиденная ошибка: {outer_e}")
            print(traceback.format_exc())
            try:
                bot.send_message(
                    message.chat.id,
                    "❌ Произошла ошибка при обработке подписки. Попробуйте снова или напишите в поддержку: " + SUPPORT
                )
            except Exception:
                pass

    t = threading.Thread(target=process)
    t.daemon = True
    t.start()

def _parse_subscription_any(raw, source_label=None):
    steps = []
    text = raw.strip()
    label = source_label or text[:60]

    # Шаг 1: Схема приложения (happ://crypt5/, incy://add/ и т.п.) или прокси-обёртка
    app_m = re.match(
        r'^(?:' + APP_SCHEMES + r')://(?:add|sub|crypt\d*|import|install|update)/+(.+)$',
        text, re.IGNORECASE
    )
    if app_m:
        payload = urllib.parse.unquote(app_m.group(1).strip()).split('#')[0]
        steps.append(f"📱 Схема приложения → {payload[:50]}")
        text = payload

    qs_scheme_m = re.match(
        r'^(?:' + APP_SCHEMES + r')://[^?]*\?(?:.*&)?url=([^&]+)',
        text, re.IGNORECASE
    )
    if qs_scheme_m:
        payload = urllib.parse.unquote(qs_scheme_m.group(1).strip())
        steps.append(f"📱 Схема приложения (query) → {payload[:50]}")
        text = payload

    proxy_m = re.match(r'^https?://[^/]+/+(https?://.+)$', text, re.IGNORECASE)
    if proxy_m:
        real_url = proxy_m.group(1)
        steps.append(f"🔄 Прокси-обёртка → {real_url[:50]}")
        text = real_url

    proxy_qs_m = re.match(r'^https?://[^?]+\?(?:.*&)?url=(https?[^&]+)', text, re.IGNORECASE)
    if proxy_qs_m:
        real_url = urllib.parse.unquote(proxy_qs_m.group(1))
        steps.append(f"🔄 Прокси-обёртка (query) → {real_url[:50]}")
        text = real_url

    # Шаг 2: URL — скачать
    if re.match(r'https?://', text, re.IGNORECASE):
        steps.append(f"🌐 Загружаю: {text[:60]}")
        headers = {'User-Agent': 'v2rayNG/1.8.7', 'Accept': '*/*'}
        content = None
        for verify in [True, False]:
            try:
                resp = requests.get(text, headers=headers, timeout=20, verify=verify)
                content = resp.text
                steps.append(f"✅ Получено {len(content)} байт")
                break
            except Exception as e:
                steps.append(f"⚠️ Попытка: {e}")
        if not content:
            return [], steps + ["❌ Не удалось загрузить URL"]
        text = content

    # Шаг 3: Парсинг ключей (прямые, Base64 многоуровневый, HTML, JSON)
    keys = _parse_keys_from_content(text)
    if keys:
        steps.append(f"🔑 Извлечено ключей: {len(keys)}")
    else:
        steps.append("❌ Ключи не найдены")

    return keys, steps

# ==================== ПОДДЕРЖКА ====================

@bot.message_handler(func=lambda m: m.text == "❓ Поддержка")
def support(message):
    if message.chat.type != 'private':
        return
    user_id = message.from_user.id
    if is_blocked(user_id):
        bot.reply_to(message, blocked_message())
        return
    bot.reply_to(message, f"📞 По всем вопросам пишите:\n{SUPPORT}")

# ==================== CHECK SUB CALLBACK ====================

@bot.callback_query_handler(func=lambda call: call.data == "check_sub")
def callback_check_sub(call):
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
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT referrer_id FROM referrals WHERE referred_id = %s AND rewarded = 0",
            (user_id,)
        )
        pending = cur.fetchone()
        if pending and get_setting('referral_enabled') == '1':
            referrer_id = pending[0]
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
        cur.execute("SELECT user_id, token FROM users WHERE user_id = %s", (user_id,))
        user = cur.fetchone()
        if not user:
            token = generate_subscription_token()
            sub_end = current_time + 7 * 24 * 60 * 60
            cur.execute(
                "INSERT INTO users (user_id, subscription_end, last_activity, is_blocked, token) VALUES (%s, %s, %s, 0, %s)",
                (user_id, sub_end, current_time, token)
            )
            conn.commit()
            bot.send_message(user_id, "🎉 Добро пожаловать! Вам выдана подписка на 7 дней.")
        else:
            bot.send_message(user_id, "👋 Добро пожаловать!")
        cur.close()
        conn.close()
        bot.send_message(user_id, "Выберите действие:", reply_markup=main_menu())
    else:
        bot.answer_callback_query(call.id, "❌ Вы ещё не подписались на канал!")

# ==================== ADMIN COMMANDS ====================

@bot.message_handler(commands=['stats'])
def cmd_stats(message):
    if not is_admin(message.from_user.id):
        return
    current_time = int(time.time())
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    total = cur.fetchone()[0]
    cur.execute(f"SELECT COUNT(*) FROM users WHERE subscription_end > {current_time}")
    active = cur.fetchone()[0]
    cur.execute(f"SELECT COUNT(*) FROM users WHERE subscription_end < {current_time}")
    expired = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM users WHERE is_blocked = 1")
    blocked_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM referrals")
    refs = cur.fetchone()[0]
    cur.close()
    conn.close()
    bot_stats = get_bot_stats()
    bot.reply_to(message,
        f"📊 Статистика:\n\n"
        f"👥 Всего пользователей: {total}\n"
        f"✅ Активных: {active}\n"
        f"❌ Истекших: {expired}\n"
        f"🚫 Заблокированных: {blocked_count}\n"
        f"🔗 Всего рефералов: {refs}\n\n"
        f"📊 Стаж бота: {bot_stats['uptime_text']}\n"
        f"🔑 Проверено ключей: {bot_stats['total_keys_checked']}\n"
        f"🔓 Расшифровано подписок: {bot_stats['total_decryptions']}\n"
        f"🌐 Проверено прокси: {bot_stats['total_proxies_checked']}"
    )

@bot.message_handler(commands=['check'])
def cmd_check(message):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "❌ Использование: /check [ID]")
        return
    try:
        target_id = int(args[1])
    except:
        bot.reply_to(message, "❌ Неверный ID.")
        return
    current_time = int(time.time())
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT subscription_end, is_blocked, token FROM users WHERE user_id = %s", (target_id,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    if not result:
        bot.reply_to(message, f"❌ Пользователь {target_id} не найден.")
        return
    subscription_end, blk, token = result
    if blk:
        status = "🚫 Заблокирован"
    elif subscription_end and subscription_end > current_time:
        days_left = (subscription_end - current_time) // (24 * 60 * 60)
        status = f"✅ Активна (осталось {days_left} дн)"
    else:
        status = "❌ Истекла"
    bot.reply_to(message, f"👤 Пользователь {target_id}\n📊 Статус: {status}\n🔗 Токен: {token}")

@bot.message_handler(commands=['prolong'])
def cmd_prolong(message):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) < 3:
        bot.reply_to(message, "❌ Использование: /prolong [ID] [дни]")
        return
    try:
        target_id = int(args[1])
        days = int(args[2])
    except:
        bot.reply_to(message, "❌ Неверные аргументы.")
        return
    current_time = int(time.time())
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT subscription_end FROM users WHERE user_id = %s", (target_id,))
    result = cur.fetchone()
    if not result:
        cur.close()
        conn.close()
        bot.reply_to(message, f"❌ Пользователь {target_id} не найден.")
        return
    current_end = result[0] if (result[0] and result[0] > current_time) else current_time
    new_end = current_end + days * 24 * 60 * 60
    cur.execute("UPDATE users SET subscription_end = %s, notified_3days = 0 WHERE user_id = %s", (new_end, target_id))
    conn.commit()
    cur.close()
    conn.close()
    bot.reply_to(message, f"✅ Пользователю {target_id} продлена подписка на {days} дней.")
    try:
        expire_date = datetime.fromtimestamp(new_end).strftime("%d.%m.%Y в %H:%M")
        bot.send_message(target_id, f"🎉 Ваша подписка продлена на {days} дней!\n📅 Действует до: {expire_date}")
    except:
        pass

@bot.message_handler(commands=['remove'])
def cmd_remove(message):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "❌ Использование: /remove [ID]")
        return
    try:
        target_id = int(args[1])
    except:
        bot.reply_to(message, "❌ Неверный ID.")
        return
    current_time = int(time.time())
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET subscription_end = %s WHERE user_id = %s", (current_time - 1, target_id))
    conn.commit()
    cur.close()
    conn.close()
    bot.reply_to(message, f"✅ Подписка пользователя {target_id} удалена.")
    try:
        bot.send_message(target_id, "❌ Ваша подписка была удалена администратором.")
    except:
        pass

@bot.message_handler(commands=['add_admin'])
def cmd_add_admin(message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "❌ Использование: /add_admin [ID]")
        return
    try:
        target_id = int(args[1])
    except:
        bot.reply_to(message, "❌ Неверный ID.")
        return
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id = %s", (target_id,))
    if not cur.fetchone():
        cur.close()
        conn.close()
        bot.reply_to(message, f"❌ Пользователь {target_id} не найден в базе.")
        return
    cur.execute(
        "INSERT INTO admins (user_id, added_by, added_at) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
        (target_id, ADMIN_ID, int(time.time()))
    )
    conn.commit()
    cur.close()
    conn.close()
    bot.reply_to(message, f"✅ Пользователю {target_id} выдан админ-доступ.")
    try:
        bot.send_message(target_id, "👑 Вам выдан доступ администратора!")
    except:
        pass

@bot.message_handler(commands=['remove_admin'])
def cmd_remove_admin(message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "❌ Использование: /remove_admin [ID]")
        return
    try:
        target_id = int(args[1])
    except:
        bot.reply_to(message, "❌ Неверный ID.")
        return
    if target_id == ADMIN_ID:
        bot.reply_to(message, "❌ Нельзя удалить создателя.")
        return
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM admins WHERE user_id = %s", (target_id,))
    conn.commit()
    cur.close()
    conn.close()
    bot.reply_to(message, f"✅ Админ-доступ у пользователя {target_id} отозван.")
    try:
        bot.send_message(target_id, "❌ Ваш доступ администратора был отозван.")
    except:
        pass

@bot.message_handler(commands=['admins_list'])
def cmd_admins_list(message):
    if message.from_user.id != ADMIN_ID:
        return
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id, added_at FROM admins")
    admins = cur.fetchall()
    cur.close()
    conn.close()
    text = f"👑 Список администраторов:\n\n👤 Создатель: {ADMIN_ID}\n\n"
    if not admins:
        text += "📋 Дополнительных администраторов нет."
    else:
        for admin_id, added_at in admins:
            name = get_user_display_name(admin_id)
            text += f"└ {name} (ID: {admin_id})\n"
    bot.reply_to(message, text)

@bot.message_handler(commands=['block'])
def cmd_block(message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "❌ Использование: /block [ID]")
        return
    try:
        target_id = int(args[1])
    except:
        bot.reply_to(message, "❌ Неверный ID.")
        return
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET is_blocked = 1 WHERE user_id = %s", (target_id,))
    conn.commit()
    cur.close()
    conn.close()
    bot.reply_to(message, f"✅ Пользователь {target_id} заблокирован.")
    try:
        bot.send_message(target_id, f"🚫 Вы заблокированы администратором.\n\nДля выяснения причин обратитесь в поддержку: {SUPPORT}")
    except:
        pass

@bot.message_handler(commands=['unblock'])
def cmd_unblock(message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "❌ Использование: /unblock [ID]")
        return
    try:
        target_id = int(args[1])
    except:
        bot.reply_to(message, "❌ Неверный ID.")
        return
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET is_blocked = 0 WHERE user_id = %s", (target_id,))
    conn.commit()
    cur.close()
    conn.close()
    bot.reply_to(message, f"✅ Пользователь {target_id} разблокирован.")
    try:
        bot.send_message(target_id, "✅ Вы разблокированы! Теперь вы можете пользоваться ботом.")
    except:
        pass

@bot.message_handler(commands=['broadcast'])
def cmd_broadcast(message):
    if message.from_user.id != ADMIN_ID:
        return
    text = message.text.replace('/broadcast', '').strip()
    if not text and not message.reply_to_message:
        bot.reply_to(message,
            "📢 Использование:\n"
            "1. /broadcast Текст сообщения\n"
            "2. Ответьте на фото командой /broadcast Подпись"
        )
        return
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE is_blocked = 0")
    users = cur.fetchall()
    cur.close()
    conn.close()
    success = 0
    fail = 0
    for user in users:
        try:
            if message.reply_to_message and message.reply_to_message.photo:
                photo = message.reply_to_message.photo[-1].file_id
                bot.send_photo(user[0], photo, caption=text)
            else:
                bot.send_message(user[0], text)
            success += 1
            time.sleep(0.05)
        except:
            fail += 1
    bot.reply_to(message, f"✅ Рассылка завершена.\n\n📤 Отправлено: {success}\n❌ Не доставлено: {fail}")

# ==================== UPDATE KEYS ====================

@bot.message_handler(commands=['update_keys'])
def cmd_update_keys(message):
    if not is_admin(message.from_user.id):
        return

    # Режим 1: ответ на документ или текст
    if message.reply_to_message:
        reply = message.reply_to_message
        if reply.document:
            try:
                file_info = bot.get_file(reply.document.file_id)
                downloaded = bot.download_file(file_info.file_path)
                text = downloaded.decode('utf-8', errors='ignore')
                bot.reply_to(message, "⏳ Читаю файл...")
                keys = load_keys_from_text(text)
                _finish_update_keys(message, keys, f"файл: {reply.document.file_name}")
            except Exception as e:
                bot.reply_to(message, f"❌ Ошибка чтения файла: {e}")
            return
        if reply.text:
            t = reply.text.strip()
            if re.match(r'https?://', t) or re.match(
                r'(?:incy|happ|v2rayng|shadowrocket|clash|sing-box)://', t, re.IGNORECASE
            ):
                bot.reply_to(message, "⏳ Загружаю ключи...")
                keys = load_keys_from_url(t)
                _finish_update_keys(message, keys, t[:60])
            else:
                bot.reply_to(message, "⏳ Читаю ключи из текста...")
                keys = load_keys_from_text(t)
                _finish_update_keys(message, keys, "текстовое сообщение")
            return

    # Режим 2: URL в аргументе
    args = message.text.split(maxsplit=1)
    if len(args) >= 2:
        url = args[1].strip()
        bot.reply_to(message, "⏳ Загружаю ключи...")
        keys = load_keys_from_url(url)
        _finish_update_keys(message, keys, url[:60])
        return

    # Режим 3: ждём следующего сообщения
    search_cache[message.from_user.id] = 'waiting_for_keys'
    bot.reply_to(
        message,
        "📥 Отправьте ключи одним из способов:\n\n"
        "• Ссылка: `https://...` или `https://happ.dska.su/https://...`\n"
        "• Схема: `incy://add/...` `happ://add/...` `happ://crypt5/...`\n"
        "• .txt файл с ключами\n"
        "• Текст с ключами vless:// vmess:// и др.",
        parse_mode="Markdown"
    )

# ==================== REF COMMANDS ====================

@bot.message_handler(commands=['ref_on'])
def cmd_ref_on(message):
    if message.from_user.id != ADMIN_ID:
        return
    set_setting('referral_enabled', '1')
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT referrer_id FROM referrals WHERE rewarded = 0")
    referrers = cur.fetchall()
    total_rewarded = 0
    for (referrer_id,) in referrers:
        cur.execute("SELECT subscription_end FROM users WHERE user_id = %s", (referrer_id,))
        ref_result = cur.fetchone()
        if not ref_result:
            continue
        cur.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = %s AND rewarded = 0", (referrer_id,))
        count = cur.fetchone()[0]
        new_end = ref_result[0] + count * 3 * 24 * 60 * 60
        cur.execute("UPDATE users SET subscription_end = %s WHERE user_id = %s", (new_end, referrer_id))
        cur.execute("UPDATE referrals SET rewarded = 1 WHERE referrer_id = %s AND rewarded = 0", (referrer_id,))
        total_rewarded += count
        try:
            bot.send_message(referrer_id,
                f"🎉 Реферальная система включена!\n\n"
                f"За {count} приглашённых вами рефералов начислено {count*3} дней.\n"
                f"Спасибо, что приглашаете друзей! 🌟"
            )
        except:
            pass
    conn.commit()
    cur.close()
    conn.close()
    bot.reply_to(message,
        f"✅ Реферальная система ВКЛЮЧЕНА.\n"
        f"Начислено {total_rewarded*3} дней {total_rewarded} рефералам."
    )

@bot.message_handler(commands=['ref_off'])
def cmd_ref_off(message):
    if message.from_user.id != ADMIN_ID:
        return
    set_setting('referral_enabled', '0')
    bot.reply_to(message, "❌ Реферальная система ВЫКЛЮЧЕНА. Новые рефералы сохраняются, но дни не начисляются.")

@bot.message_handler(commands=['ref_status'])
def cmd_ref_status(message):
    if not is_admin(message.from_user.id):
        return
    status = "ВКЛЮЧЕНА ✅" if get_setting('referral_enabled') == '1' else "ВЫКЛЮЧЕНА ❌"
    bot.reply_to(message, f"📊 Реферальная система: {status}")

# ==================== /manage ====================

manage_cache = {}

def build_user_list_keyboard(users, page, filter_type='all'):
    kb = types.InlineKeyboardMarkup(row_width=2)
    per_page = 5
    start = page * per_page
    end = start + per_page
    page_users = users[start:end]
    current_time = int(time.time())
    for uid in page_users:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT subscription_end, is_blocked FROM users WHERE user_id = %s", (uid,))
        udata = cur.fetchone()
        cur.close()
        conn.close()
        if udata:
            sub_end, blk = udata
            if blk:
                status_icon = "🚫"
            elif sub_end and sub_end > current_time:
                status_icon = "🟢"
            else:
                status_icon = "🔴"
        else:
            status_icon = "❓"
        admin_icon = "👑 " if is_admin(uid) else ""
        name = get_user_display_name(uid)
        display = f"{status_icon} {admin_icon}{name}"[:40]
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
        types.InlineKeyboardButton("📋 Все приглашавшие", callback_data="filter_referrers")
    )
    kb.row(
        types.InlineKeyboardButton("🏆 Топ рефералов", callback_data="top_refs_admin"),
        types.InlineKeyboardButton("🔄 Обновить", callback_data="filter_all")
    )
    kb.row(types.InlineKeyboardButton("❌ Закрыть", callback_data="close_manage"))
    return kb

@bot.message_handler(commands=['manage'])
def cmd_manage(message):
    if not is_admin(message.from_user.id):
        return
    admin_id = message.from_user.id
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE is_blocked = 0 ORDER BY user_id")
    users = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    if not users:
        bot.reply_to(message, "📭 Нет активных пользователей.")
        return
    manage_cache[admin_id] = {'users': users, 'filter': 'all'}
    kb = build_user_list_keyboard(users, 0, 'all')
    bot.reply_to(message, f"👥 Пользователи ({len(users)}):", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data.startswith('filter_') or call.data.startswith('page_') or call.data in ['close_manage', 'back_to_list', 'top_refs_admin'])
def callback_manage_filters(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Нет доступа.")
        return
    admin_id = call.from_user.id
    current_time = int(time.time())
    data = call.data
    if data == 'close_manage':
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
        return
    if data == 'top_refs_admin':
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT referrer_id, COUNT(*) FROM referrals GROUP BY referrer_id ORDER BY COUNT(*) DESC LIMIT 10")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        text = "🏆 *Топ рефералов:*\n\n"
        for i, (ref_id, count) in enumerate(rows):
            name = get_user_display_name(ref_id)
            text += f"{i+1}. {name} (ID: {ref_id}) — {count} реф.\n"
        bot.answer_callback_query(call.id)
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown")
        except:
            bot.send_message(call.message.chat.id, text, parse_mode="Markdown")
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
            bot.edit_message_text(f"👥 Пользователи ({len(users)}):", call.message.chat.id, call.message.message_id, reply_markup=kb)
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
            bot.edit_message_text(f"👥 Пользователи ({len(users)}):", call.message.chat.id, call.message.message_id, reply_markup=kb)
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
    elif data == 'filter_referrers':
        cur.execute("SELECT DISTINCT referrer_id FROM referrals ORDER BY referrer_id")
        filter_type = 'referrers'
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
        bot.edit_message_text(f"👥 Пользователи ({len(users)}):", call.message.chat.id, call.message.message_id, reply_markup=kb)
    except:
        pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('user_') and len(call.data.split('_')) == 2)
def callback_user_detail(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Нет доступа.")
        return
    try:
        target_id = int(call.data.split('_')[1])
    except:
        return
    current_time = int(time.time())
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
    if blk:
        status = "🚫 Заблокирован"
    elif subscription_end and subscription_end > current_time:
        days_left = (subscription_end - current_time) // (24 * 60 * 60)
        status = f"🟢 Активна (осталось {days_left} дн)"
    else:
        status = "🔴 Неактивна"
    is_admin_user = is_admin(target_id)
    admin_text = "✅ Да" if is_admin_user else "❌ Нет"
    name = get_user_display_name(target_id)
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📅 Продлить (+30 дн)", callback_data=f"prolong_{target_id}_30"),
        types.InlineKeyboardButton("🗑️ Удалить подписку", callback_data=f"remove_sub_{target_id}")
    )
    if blk:
        kb.add(types.InlineKeyboardButton("🔓 Разблокировать", callback_data=f"unblock_{target_id}"))
    else:
        kb.add(types.InlineKeyboardButton("🔒 Заблокировать", callback_data=f"block_{target_id}"))
    if is_admin_user:
        kb.add(types.InlineKeyboardButton("👑 Забрать админку", callback_data=f"remove_admin_{target_id}"))
    else:
        kb.add(types.InlineKeyboardButton("👑 Выдать админку", callback_data=f"add_admin_{target_id}"))
    kb.row(
        types.InlineKeyboardButton("🔙 Назад к списку", callback_data="back_to_list"),
        types.InlineKeyboardButton("❌ Закрыть", callback_data="close_manage")
    )
    text = (
        f"👤 *{name}*\n"
        f"🆔 ID: `{target_id}`\n"
        f"📊 Статус: {status}\n"
        f"👑 Админ: {admin_text}"
    )
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=kb)
    except:
        pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('prolong_'))
def callback_prolong(call):
    if not is_admin(call.from_user.id):
        return
    parts = call.data.split('_')
    target_id = int(parts[1])
    days = int(parts[2])
    current_time = int(time.time())
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT subscription_end FROM users WHERE user_id = %s", (target_id,))
    result = cur.fetchone()
    if not result:
        bot.answer_callback_query(call.id, "❌ Пользователь не найден.")
        cur.close()
        conn.close()
        return
    current_end = result[0] if (result[0] and result[0] > current_time) else current_time
    new_end = current_end + days * 24 * 60 * 60
    cur.execute("UPDATE users SET subscription_end = %s, notified_3days = 0 WHERE user_id = %s", (new_end, target_id))
    conn.commit()
    cur.close()
    conn.close()
    bot.answer_callback_query(call.id, "✅ Подписка продлена!")
    try:
        bot.send_message(target_id, f"🎉 Ваша подписка продлена на {days} дней!")
    except:
        pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('remove_sub_'))
def callback_remove_sub(call):
    if not is_admin(call.from_user.id):
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

@bot.callback_query_handler(func=lambda call: re.match(r'^block_\d+$', call.data) is not None)
def callback_block(call):
    if not is_admin(call.from_user.id):
        return
    target_id = int(call.data.split('_')[1])
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

@bot.callback_query_handler(func=lambda call: call.data.startswith('add_admin_'))
def callback_add_admin(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Только создатель может выдавать админку.")
        return
    target_id = int(call.data.split('_')[2])
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO admins (user_id, added_by, added_at) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
        (target_id, ADMIN_ID, int(time.time()))
    )
    conn.commit()
    cur.close()
    conn.close()
    bot.answer_callback_query(call.id, "✅ Админ-доступ выдан!")
    try:
        bot.send_message(target_id, "👑 Вам выдан доступ администратора!")
    except:
        pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('remove_admin_'))
def callback_remove_admin_cb(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Только создатель может отзывать админку.")
        return
    target_id = int(call.data.split('_')[2])
    if target_id == ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нельзя удалить создателя.")
        return
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM admins WHERE user_id = %s", (target_id,))
    conn.commit()
    cur.close()
    conn.close()
    bot.answer_callback_query(call.id, "✅ Админ-доступ отозван!")
    try:
        bot.send_message(target_id, "❌ Ваш доступ администратора был отозван.")
    except:
        pass

# ==================== DOCUMENT HANDLER ====================

@bot.message_handler(content_types=['document'])
def handle_document(message):
    if message.chat.type != 'private':
        return
    user_id = message.from_user.id

    # Режим расшифровки
    if user_id in decrypt_results and decrypt_results[user_id].get('waiting'):
        if is_blocked(user_id):
            bot.reply_to(message, "🚫 Вы заблокированы.")
            del decrypt_results[user_id]
            return
        try:
            file_info = bot.get_file(message.document.file_id)
            downloaded = bot.download_file(file_info.file_path)
            _do_decrypt(message, user_id, file_bytes=downloaded, file_name=message.document.file_name)
        except Exception as e:
            # Раньше при ошибке скачивания файла флаг 'waiting' оставался
            # висеть навсегда — пользователь не мог повторно запустить расшифровку.
            if user_id in decrypt_results:
                del decrypt_results[user_id]
            bot.reply_to(message, f"❌ Не удалось прочитать файл: {e}")
        return

    # Режим ожидания ключей от админа
    if search_cache.get(user_id) == 'waiting_for_keys' and is_admin(user_id):
        del search_cache[user_id]
        try:
            file_info = bot.get_file(message.document.file_id)
            downloaded = bot.download_file(file_info.file_path)
            text = downloaded.decode('utf-8', errors='ignore')
            bot.reply_to(message, "⏳ Читаю файл...")
            keys = load_keys_from_text(text)
            _finish_update_keys(message, keys, f"файл: {message.document.file_name}")
        except Exception as e:
            bot.reply_to(message, f"❌ Ошибка: {e}")
        return

    # Режим проверки прокси (файл со списком прокси)
    if user_id in proxy_check_results and proxy_check_results[user_id].get('waiting'):
        if is_blocked(user_id):
            bot.reply_to(message, "🚫 Вы заблокированы.")
            del proxy_check_results[user_id]
            return
        try:
            file_info = bot.get_file(message.document.file_id)
            downloaded = bot.download_file(file_info.file_path)
            text = downloaded.decode('utf-8', errors='ignore')
        except Exception as e:
            bot.reply_to(message, f"❌ Не удалось прочитать файл: {e}")
            if user_id in proxy_check_results:
                del proxy_check_results[user_id]
            return
        if user_id in proxy_check_results:
            del proxy_check_results[user_id]
        _process_proxies(message, text, user_id)
        return

    # Режим проверки ключей
    if user_id in check_results and check_results[user_id].get('waiting'):
        if is_blocked(user_id):
            bot.reply_to(message, "🚫 Вы заблокированы.")
            return
        try:
            file_info = bot.get_file(message.document.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            text = downloaded_file.decode('utf-8')
            keys = re.findall(r'vless://[^\s<>"\']+', text)
        except:
            bot.reply_to(message, "❌ Не удалось прочитать файл.")
            return
        _process_keys(message, keys, user_id)

# ==================== TEXT HANDLER ====================

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    if message.chat.type != 'private':
        return
    user_id = message.from_user.id

    if message.text and message.text.startswith('/'):
        return

    # Режим расшифровки подписки
    if user_id in decrypt_results and decrypt_results[user_id].get('waiting'):
        if is_blocked(user_id):
            bot.reply_to(message, "🚫 Вы заблокированы.")
            del decrypt_results[user_id]
            return
        _do_decrypt(message, user_id, text=message.text or '')
        return

    # Режим проверки прокси
    if user_id in proxy_check_results and proxy_check_results[user_id].get('waiting'):
        if is_blocked(user_id):
            bot.reply_to(message, "🚫 Вы заблокированы.")
            del proxy_check_results[user_id]
            return
        del proxy_check_results[user_id]
        _process_proxies(message, message.text or '', user_id)
        return

    # Режим ожидания ключей от админа (waiting_for_keys)
    if search_cache.get(user_id) == 'waiting_for_keys' and is_admin(user_id):
        del search_cache[user_id]
        t = (message.text or '').strip()
        if re.match(r'https?://', t) or re.match(
            r'(?:incy|happ|v2rayng|shadowrocket|clash|sing-box)://', t, re.IGNORECASE
        ):
            bot.reply_to(message, "⏳ Загружаю ключи...")
            keys = load_keys_from_url(t)
            _finish_update_keys(message, keys, t[:60])
        else:
            bot.reply_to(message, "⏳ Читаю ключи из текста...")
            keys = load_keys_from_text(t)
            _finish_update_keys(message, keys, "текстовое сообщение")
        return

    # Режим проверки ключей
    if user_id in check_results and check_results[user_id].get('waiting'):
        if is_blocked(user_id):
            bot.reply_to(message, "🚫 Вы заблокированы.")
            return
        keys = re.findall(r'vless://[^\s<>"\']+', message.text or '')
        _process_keys(message, keys, user_id)
        return

    # Режим поиска (manage)
    if search_cache.get(user_id) == 'waiting_for_search':
        del search_cache[user_id]
        query = (message.text or '').strip()
        if query.startswith('@'):
            try:
                chat = bot.get_chat(query)
                target_id = chat.id
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("SELECT subscription_end, is_blocked FROM users WHERE user_id = %s", (target_id,))
                result = cur.fetchone()
                cur.close()
                conn.close()
                if result:
                    bot.reply_to(message, f"✅ Найден: {query} (ID: {target_id})\nПодписка до: {result[0]}, Блок: {result[1]}")
                else:
                    bot.reply_to(message, "❌ Пользователь не найден в базе.")
            except:
                bot.reply_to(message, "❌ Пользователь не найден.")
        else:
            try:
                target_id = int(query)
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("SELECT subscription_end, is_blocked FROM users WHERE user_id = %s", (target_id,))
                result = cur.fetchone()
                cur.close()
                conn.close()
                if result:
                    name = get_user_display_name(target_id)
                    bot.reply_to(message, f"✅ Найден: {name} (ID: {target_id})\nПодписка до: {result[0]}, Блок: {result[1]}")
                else:
                    bot.reply_to(message, "❌ Пользователь не найден.")
            except:
                bot.reply_to(message, "❌ Неверный запрос.")
        return

    if is_blocked(user_id):
        bot.reply_to(message, blocked_message())
        return

def _process_keys(message, keys, user_id):
    if not keys:
        bot.reply_to(message, "❌ Не найдено ключей в формате vless://")
        return
    keys = list(dict.fromkeys(keys))
    msg = bot.reply_to(
        message,
        f"🔍 Найдено ключей: {len(keys)}\n⏳ Начинаю проверку...\nЭто может занять до 30 секунд."
    )
    t = threading.Thread(target=check_keys_async, args=(message.chat.id, keys, user_id, msg.message_id))
    t.daemon = True
    t.start()

# ==================== FLASK ROUTES ====================

@app.route('/ping')
def ping():
    return "ok", 200

@app.route('/')
def index():
    return "PotyjnoVPN Bot is running", 200

@app.route('/sub/<token>')
def sub(token):
    current_time = int(time.time())
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id, subscription_end, is_blocked FROM users WHERE token = %s", (token,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    if not result:
        return "Подписка не найдена", 404
    user_id, subscription_end, blk = result
    if (not subscription_end or subscription_end < current_time) or blk == 1:
        return "Подписка истекла или пользователь заблокирован", 403
    keys = get_keys_from_db()
    if not keys:
        keys = DEFAULT_KEYS
    content = KEY_TEMPLATE.format(expire=subscription_end, keys='\n'.join(keys))
    return content, 200, {'Content-Type': 'text/plain; charset=utf-8'}

# ==================== MAIN ====================

def run_bot():
    bot.infinity_polling(skip_pending=True)

if __name__ == '__main__':
    init_db()
    ensure_bot_start_time()
    if not get_keys_from_db():
        save_keys_to_db(DEFAULT_KEYS)
    thread = Thread(target=run_bot)
    thread.daemon = True
    thread.start()
    from waitress import serve
    serve(app, host='0.0.0.0', port=10000)

