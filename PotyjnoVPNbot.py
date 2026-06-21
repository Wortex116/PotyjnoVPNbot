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

    try:
        cur.execute("""
            INSERT INTO admins (user_id, added_by, added_at) 
            VALUES (%s, %s, %s) 
            ON CONFLICT (user_id) DO NOTHING
        """, (ADMIN_ID, ADMIN_ID, int(time.time())))
        conn.commit()
        print(f"[init] ✅ Создатель {ADMIN_ID} добавлен в админы")
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

def get_next_check_number():
    check_number = int(get_setting('last_check_number', '0')) + 1
    set_setting('last_check_number', str(check_number))
    return check_number

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

def get_user_channels(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    if user_id == ADMIN_ID:
        cur.execute("""
            SELECT id, channel_id, channel_name, topic_id, enabled, interval_seconds, last_post, is_default 
            FROM autopost_channels 
            ORDER BY is_default DESC, id
        """)
    else:
        cur.execute("""
            SELECT c.id, c.channel_id, c.channel_name, c.topic_id, c.enabled, c.interval_seconds, c.last_post, c.is_default
            FROM autopost_channels c
            INNER JOIN autopost_user_access a ON c.channel_id = a.channel_id
            WHERE a.user_id = %s AND a.can_post = TRUE AND c.enabled = TRUE
            ORDER BY c.is_default DESC, c.id
        """, (user_id,))
    channels = cur.fetchall()
    cur.close()
    conn.close()
    return channels

def get_channel_access(user_id, channel_id):
    if user_id == ADMIN_ID:
        return True, True
    if channel_id == AUTO_POST_CHANNEL and user_id != ADMIN_ID:
        return False, False
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT can_post, can_manage FROM autopost_user_access WHERE user_id = %s AND channel_id = %s",
        (user_id, channel_id)
    )
    result = cur.fetchone()
    cur.close()
    conn.close()
    if result:
        return result[0], result[1]
    return False, False

def can_announce_in_channel(user_id, channel_id):
    if user_id == ADMIN_ID:
        return True
    if channel_id == AUTO_POST_CHANNEL and user_id != ADMIN_ID:
        return False
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT can_announce FROM autopost_user_access WHERE user_id = %s AND channel_id = %s",
        (user_id, channel_id)
    )
    result = cur.fetchone()
    cur.close()
    conn.close()
    return result[0] if result else False

def get_user_announce_channels(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    if user_id == ADMIN_ID:
        cur.execute("SELECT channel_id, channel_name, topic_id FROM autopost_channels WHERE enabled = TRUE")
    else:
        cur.execute("""
            SELECT c.channel_id, c.channel_name, c.topic_id
            FROM autopost_channels c
            JOIN autopost_user_access a ON c.channel_id = a.channel_id
            WHERE a.user_id = %s AND a.can_announce = TRUE AND c.enabled = TRUE
        """, (user_id,))
    channels = cur.fetchall()
    cur.close()
    conn.close()
    return channels

def add_channel(channel_id, channel_name, topic_id=0, created_by=None):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO autopost_channels 
        (channel_id, channel_name, topic_id, created_by, created_at)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (channel_id, topic_id) DO UPDATE SET 
        channel_name = EXCLUDED.channel_name,
        enabled = TRUE
        RETURNING id
    """, (channel_id, channel_name, topic_id, created_by, int(time.time())))
    channel_db_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return channel_db_id

def grant_channel_access(user_id, channel_id, can_manage=False, can_announce=False, granted_by=None):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO autopost_user_access 
        (user_id, channel_id, can_post, can_manage, can_announce, granted_by, granted_at)
        VALUES (%s, %s, TRUE, %s, %s, %s, %s)
        ON CONFLICT (user_id, channel_id) DO UPDATE SET
        can_post = TRUE,
        can_manage = EXCLUDED.can_manage,
        can_announce = EXCLUDED.can_announce,
        granted_by = EXCLUDED.granted_by,
        granted_at = EXCLUDED.granted_at
    """, (user_id, channel_id, can_manage, can_announce, granted_by, int(time.time())))
    conn.commit()
    cur.close()
    conn.close()

def remove_channel_access(user_id, channel_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM autopost_user_access WHERE user_id = %s AND channel_id = %s",
        (user_id, channel_id)
    )
    conn.commit()
    cur.close()
    conn.close()

def remove_used_keys(keys_to_remove):
    current_keys = get_keys_from_db()
    for key in keys_to_remove:
        if key in current_keys:
            current_keys.remove(key)
    save_keys_to_db(current_keys)
    print(f"[keys] Удалено {len(keys_to_remove)} выданных ключей")

def get_autopost_config():
    config = {
        'enabled': get_setting('autopost_enabled', 'true') == 'true',
        'interval': int(get_setting('autopost_interval', '1800')),
        'channel_id': int(get_setting('autopost_channel', str(AUTO_POST_CHANNEL))),
        'topic_id': int(get_setting('autopost_topic', str(AUTO_POST_TOPIC_ID))),
        'max_working': int(get_setting('autopost_max_working', '10')),
        'max_not_working': int(get_setting('autopost_max_not_working', '5')),
        'last_post': get_setting('autopost_last_post', '0'),
    }
    return config

def save_autopost_config(config):
    set_setting('autopost_enabled', str(config['enabled']).lower())
    set_setting('autopost_interval', str(config['interval']))
    set_setting('autopost_channel', str(config['channel_id']))
    set_setting('autopost_topic', str(config['topic_id']))
    set_setting('autopost_max_working', str(config['max_working']))
    set_setting('autopost_max_not_working', str(config['max_not_working']))

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
    qs_scheme = re.match(
        r'^(?:' + APP_SCHEMES + r')://[^?]*\?(?:.*&)?url=([^&]+)',
        raw_url, re.IGNORECASE
    )
    if qs_scheme:
        payload = urllib.parse.unquote(qs_scheme.group(1).strip())
        decoded = _try_b64(payload)
        if decoded and re.match(r'https?://', decoded.strip(), re.IGNORECASE):
            return decoded.strip()
        return payload
    proxy_wrap = re.match(r'^https?://[^/]+/+(https?://.+)$', raw_url, re.IGNORECASE)
    if proxy_wrap:
        inner = proxy_wrap.group(1)
        decoded = _try_b64(inner)
        if decoded and re.match(r'https?://', decoded.strip(), re.IGNORECASE):
            return decoded.strip()
        return inner
    proxy_qs = re.match(r'^https?://[^?]+\?(?:.*&)?url=(https?[^&]+)', raw_url, re.IGNORECASE)
    if proxy_qs:
        return urllib.parse.unquote(proxy_qs.group(1))
    proxy_qs_alt = re.match(r'^https?://[^?]+\?(?:.*&)?(?:u|target|link|dest)=([^&]+)', raw_url, re.IGNORECASE)
    if proxy_qs_alt:
        candidate = urllib.parse.unquote(proxy_qs_alt.group(1))
        if re.match(r'https?://', candidate, re.IGNORECASE):
            return candidate
        decoded = _try_b64(candidate)
        if decoded and re.match(r'https?://', decoded.strip(), re.IGNORECASE):
            return decoded.strip()
        return candidate
    if re.match(r'https?://[^/]+/[A-Za-z0-9_\-]+$', raw_url):
        path = raw_url.split('/')[-1]
        if len(path) >= 20 and re.match(r'^[A-Za-z0-9+/_\-=]+$', path):
            decoded = _try_multilevel_b64(path, max_depth=5)
            if decoded:
                for item in decoded:
                    if re.match(r'https?://', item.strip(), re.IGNORECASE):
                        return item.strip()
                    keys = _extract_vpn_keys(item)
                    if keys:
                        return item
    if raw_url.endswith('=') or '=' in raw_url.split('/')[-1]:
        path = raw_url.split('/')[-1]
        decoded = _try_multilevel_b64(path, max_depth=5)
        if decoded:
            for item in decoded:
                if re.match(r'https?://', item.strip(), re.IGNORECASE):
                    return item.strip()
                keys = _extract_vpn_keys(item)
                if keys:
                    return item
    return raw_url

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
            encoded = urllib.parse.unquote(url)
            if len(encoded) >= 16 and re.match(r'^[A-Za-z0-9+/_\-=]+$', encoded):
                all_keys.extend(_try_multilevel_b64(encoded, max_depth=3))
    if '<' in content and '>' in content:
        try:
            soup = BeautifulSoup(content, 'html.parser')
            for elem in soup.find_all(string=True):
                txt = str(elem).strip()
                if not txt:
                    continue
                all_keys.extend(_extract_vpn_keys(txt))
                if len(txt) >= 16 and re.match(r'^[A-Za-z0-9+/_\-=]+$', txt):
                    all_keys.extend(_try_multilevel_b64(txt, max_depth=4))
            for tag in soup.find_all(True):
                for attr_name, attr_val in tag.attrs.items():
                    if isinstance(attr_val, str):
                        decoded = urllib.parse.unquote(attr_val)
                        if not decoded:
                            continue
                        all_keys.extend(_extract_vpn_keys(decoded))
                        if len(decoded) >= 16 and re.match(r'^[A-Za-z0-9+/_\-=]+$', decoded):
                            all_keys.extend(_try_multilevel_b64(decoded, max_depth=4))
        except:
            pass
    try:
        json_str_matches = re.findall(r'"((?:[^"\\]|\\.)*)"', content)
        for m in json_str_matches:
            try:
                unescaped = m.encode().decode('unicode_escape')
            except:
                unescaped = m
            if not unescaped:
                continue
            all_keys.extend(_extract_vpn_keys(unescaped))
            if len(unescaped) >= 16 and re.match(r'^[A-Za-z0-9+/_\-=]+$', unescaped):
                all_keys.extend(_try_multilevel_b64(unescaped, max_depth=4))
    except:
        pass
    app_schemes = re.findall(
        r'(?:incy|happ|v2ray|v2rayng|shadowrocket|clash|sing-box|quantumult|surge|nekoray|hiddify|streisand|karing|mihomo|flclash)://[^\s<>"\']+',
        content, re.IGNORECASE
    )
    for scheme_url in app_schemes:
        resolved = _resolve_url(scheme_url)
        if resolved and re.match(r'https?://', resolved, re.IGNORECASE):
            try:
                resp = requests.get(resolved, timeout=10, headers={'User-Agent': 'v2rayNG/1.8.7'})
                if resp.status_code == 200:
                    all_keys.extend(_parse_keys_from_content(resp.text))
            except:
                pass
        elif resolved and len(resolved) >= 16:
            all_keys.extend(_extract_vpn_keys(resolved))
            if re.match(r'^[A-Za-z0-9+/_\-=]+$', resolved):
                all_keys.extend(_try_multilevel_b64(resolved, max_depth=4))
    proxy_wraps = re.findall(
        r'https?://[^/]+/+(https?://[^\s<>"\']+)',
        content, re.IGNORECASE
    )
    for wrapped_url in proxy_wraps:
        try:
            resp = requests.get(wrapped_url, timeout=10, headers={'User-Agent': 'v2rayNG/1.8.7'})
            if resp.status_code == 200:
                all_keys.extend(_parse_keys_from_content(resp.text))
        except:
            pass
    key_value_pairs = re.findall(r'([a-zA-Z0-9_\-]+)=([^&\s]+)', content)
    for key, value in key_value_pairs:
        if len(value) >= 16:
            decoded = urllib.parse.unquote(value)
            if re.match(r'^[A-Za-z0-9+/_\-=]+$', decoded):
                all_keys.extend(_try_multilevel_b64(decoded, max_depth=3))
    sub_patterns = re.findall(
        r'(?:sub|subscription|config|link|url|uri)=([^&\s]+)',
        content, re.IGNORECASE
    )
    for sub_data in sub_patterns:
        decoded = urllib.parse.unquote(sub_data)
        if re.match(r'https?://', decoded, re.IGNORECASE):
            try:
                resp = requests.get(decoded, timeout=10, headers={'User-Agent': 'v2rayNG/1.8.7'})
                if resp.status_code == 200:
                    all_keys.extend(_parse_keys_from_content(resp.text))
            except:
                pass
        elif len(decoded) >= 16 and re.match(r'^[A-Za-z0-9+/_\-=]+$', decoded):
            all_keys.extend(_try_multilevel_b64(decoded, max_depth=4))
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
            "• URL подписки\n"
            "• HTML страница с ключами\n"
            "• JSON с конфигами"
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
    except Exception as e:
        print(f"[is_admin] Ошибка: {e}")
        if user_id == ADMIN_ID:
            return True
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
    kb.row(
        types.KeyboardButton("👤 Личный кабинет"),
        types.KeyboardButton("📡 Моя подписка")
    )
    kb.row(
        types.KeyboardButton("👥 Рефералы"),
        types.KeyboardButton("🏆 Топ рефералов")
    )
    kb.row(
        types.KeyboardButton("🔓 Decrypt"),
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
    total_keys_checked = int(get_setting('total_keys_checked', '0'))
    total_decryptions = int(get_setting('total_decryptions_success', '0'))
    total_proxies_checked = int(get_setting('total_proxies_checked', '0'))
    total_keys_issued = int(get_setting('total_keys_issued', '0'))
    current_keys = len(get_keys_from_db())
    return {
        'start_time': start_time,
        'uptime_seconds': uptime_seconds,
        'uptime_text': _format_duration(uptime_seconds),
        'total_keys_checked': total_keys_checked,
        'total_decryptions': total_decryptions,
        'total_proxies_checked': total_proxies_checked,
        'total_keys_issued': total_keys_issued,
        'current_keys': current_keys,
    }

# ==================== КАПЧА ====================

CAPTCHA_TIMEOUT = 300

SUBSCRIBE_MONITOR = {
    'timestamps': [],
    'blocked_until': 0,
}

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
    current_time = int(time.time())
    SUBSCRIBE_MONITOR['timestamps'].append(current_time)

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

    is_new_user = existing_user is None

    if is_new_user:
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

        return

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
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE user_id = %s", (referrer_id,))
        referrer_exists = cur.fetchone()
        cur.close()
        conn.close()

        if referrer_exists and referrer_id != user_id:
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

                    name = get_user_display_name(user_id)
                    try:
                        bot.send_message(referrer_id, f"🔔 Новый реферал! Пользователь {name} зарегистрировался по вашей ссылке.")
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
                                bot.send_message(referrer_id, "🎉 Вам начислено +3 дня за нового реферала!")
                            except:
                                pass
                        cur.close()
                        conn.close()
                else:
                    try:
                        bot.send_message(referrer_id, "⚠️ Лимит рефералов (10 в день). Попробуйте завтра.")
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

        if pending and get_setting('referral_enabled') == '1':
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

# ==================== ЛИЧНЫЙ КАБИНЕТ ====================

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
    update_activity()
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
    update_activity()
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

# ==================== DECRYPT ====================

@bot.message_handler(func=lambda m: m.text == "🔓 Decrypt")
def decryptor_section(message):
    update_activity()
    if message.chat.type != 'private':
        return
    user_id = message.from_user.id
    if is_blocked(user_id):
        bot.reply_to(message, blocked_message())
        return

    text = "🔓 *Decrypt*\n\nВыберите действие:"
    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=decryptor_menu())

def decryptor_menu():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📊 Стаж бота", callback_data="decrypt_stats"),
        types.InlineKeyboardButton("🔍 Проверка ключей", callback_data="decrypt_check_keys")
    )
    kb.add(
        types.InlineKeyboardButton("🛡️ Проверка прокси", callback_data="decrypt_check_proxy"),
        types.InlineKeyboardButton("🔓 Расшифровать подписку", callback_data="decrypt_decrypt_sub")
    )
    kb.add(
        types.InlineKeyboardButton("🏠 Главное меню", callback_data="decrypt_back")
    )
    return kb

@bot.callback_query_handler(func=lambda call: call.data.startswith('decrypt_'))
def decryptor_callback(call):
    user_id = call.from_user.id

    if call.data == "decrypt_back":
        bot.edit_message_text(
            "🏠 Главное меню",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=None
        )
        bot.send_message(user_id, "Выберите действие:", reply_markup=main_menu())
        bot.answer_callback_query(call.id)
        return

    if call.data == "decrypt_stats":
        stats = get_bot_stats()
        total_keys = int(get_setting('total_keys_checked', '0'))
        total_proxies = int(get_setting('total_proxies_checked', '0'))
        total_decryptions = int(get_setting('total_decryptions_success', '0'))
        total_keys_issued = int(get_setting('total_keys_issued', '0'))
        current_keys = len(get_keys_from_db())

        text = f"📊 *Статистика бота*\n\n"
        text += f"⏳ Стаж: {stats['uptime_text']}\n"
        text += f"🔑 Проверено ключей: {total_keys}\n"
        text += f"🌐 Проверено прокси: {total_proxies}\n"
        text += f"🔓 Расшифровано подписок: {total_decryptions}\n"
        text += f"🗑️ Выдано ключей: {total_keys_issued}\n"
        text += f"📦 Ключей в базе: {current_keys}"

        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=decryptor_menu())
        bot.answer_callback_query(call.id)
        return

    if call.data == "decrypt_check_keys":
        bot.answer_callback_query(call.id)
        check_keys_start(call.message)
        return

    if call.data == "decrypt_check_proxy":
        bot.answer_callback_query(call.id)
        proxy_check_start(call.message)
        return

    if call.data == "decrypt_decrypt_sub":
        bot.answer_callback_query(call.id)
        decrypt_subscription_start(call.message)
        return

# ==================== ПРОВЕРКА КЛЮЧЕЙ ====================

@bot.message_handler(func=lambda m: m.text == "🔍 Проверка ключей" and m.chat.type == 'private')
def check_keys_start(message):
    update_activity()
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
        schemes_to_try = ['http', 'socks5']
    last_error = None
    for scheme in schemes_to_try:
        if scheme in ('socks5', 'socks4') and not SOCKS_AVAILABLE:
            last_error = "PySocks не установлен"
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
        except:
            try:
                start2 = time.time()
                resp2 = requests.get(TEST_URL_FALLBACK, proxies=proxies, timeout=timeout)
                if resp2.status_code == 200:
                    latency_ms = int((time.time() - start2) * 1000)
                    return {'ok': True, 'scheme': scheme, 'latency_ms': latency_ms, 'error': None}
                last_error = f"HTTP {resp2.status_code}"
            except:
                continue
    return {'ok': False, 'scheme': None, 'latency_ms': None, 'error': last_error}

@bot.message_handler(func=lambda m: m.text == "🛡️ Проверка прокси" and m.chat.type == 'private')
def proxy_check_start(message):
    update_activity()
    if message.chat.type != 'private':
        return
    user_id = message.from_user.id
    if is_blocked(user_id):
        bot.reply_to(message, blocked_message())
        return
    proxy_check_results[user_id] = {'waiting': True}
    socks_note = "" if SOCKS_AVAILABLE else "\n⚠️ PySocks не установлен"
    bot.reply_to(
        message,
        "🛡️ *Проверка прокси*\n\n"
        "Отправьте список прокси (каждая на новой строке).\n\n"
        "Форматы:\n"
        "• `ip:port`\n"
        "• `ip:port:user:pass`\n"
        "• `user:pass@ip:port`\n"
        "• `http://ip:port` или `socks5://ip:port`\n\n"
        f"⏳ Проверка может занять время.{socks_note}",
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
            results.append((line, {'ok': False, 'scheme': None, 'latency_ms': None, 'error': 'Не удалось распознать'}))
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
        f"🔍 Найдено прокси: {len(lines)}\n⏳ Начинаю проверку..."
    )
    t = threading.Thread(target=proxy_check_async, args=(message.chat.id, lines, user_id, msg.message_id))
    t.daemon = True
    t.start()

# ==================== РАСШИФРОВКА ПОДПИСКИ ====================

@bot.message_handler(func=lambda m: m.text == "🔓 Расшифровать подписку" and m.chat.type == 'private')
def decrypt_subscription_start(message):
    update_activity()
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
        "• URL подписки\n"
        "• Base64 (все уровни)\n"
        "• HTML/JSON\n"
        "• Схемы: happ://, incy:// и др.\n"
        "• Файлы с ключами\n\n"
        "📄 Получите `.txt` файл со всеми ключами.",
        parse_mode="Markdown"
    )

def _do_decrypt(message, user_id, text=None, file_bytes=None, file_name=None):
    if user_id in decrypt_results:
        del decrypt_results[user_id]
    try:
        wait_msg = bot.reply_to(message, "⏳ Обрабатываю подписку...")
    except:
        wait_msg = None

    def process():
        try:
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

def _parse_subscription_any(raw, source_label=None):
    steps = []
    text = raw.strip()
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
        steps.append(f"🔗 URL в схеме → {payload[:50]}")
        text = payload
    proxy_wrap_m = re.match(r'^https?://[^/]+/+(https?://.+)$', text, re.IGNORECASE)
    if proxy_wrap_m:
        inner = proxy_wrap_m.group(1)
        steps.append(f"🌐 Обертка прокси → {inner[:50]}")
        text = inner
    if re.match(r'^[A-Za-z0-9+/_\-=]+$', text[:200].strip()):
        decoded_any = _try_multilevel_b64(text.strip(), max_depth=5)
        if decoded_any:
            steps.append(f"🧩 Расшифровано {len(decoded_any)} уровней Base64")
            text = '\n'.join(decoded_any)
    if re.match(r'https?://', text, re.IGNORECASE):
        steps.append(f"⬇️ Загружаю подписку по URL...")
        try:
            headers = {'User-Agent': 'v2rayNG/1.8.7'}
            resp = requests.get(text, timeout=30, headers=headers)
            if resp.status_code == 200:
                text = resp.text
                steps.append(f"✅ Загружено {len(text)} символов")
            else:
                steps.append(f"❌ Ошибка загрузки: HTTP {resp.status_code}")
        except Exception as e:
            steps.append(f"❌ Ошибка загрузки: {e}")
            return [], steps
    keys = load_keys_from_text(text)
    if not keys:
        keys = _extract_vpn_keys(text)
        steps.append(f"🔍 Извлечено {len(keys)} ключей через regex")
    else:
        steps.append(f"🔍 Извлечено {len(keys)} ключей через парсер")
    return keys, steps

# ==================== ФУНКЦИИ ФОРМАТИРОВАНИЯ КЛЮЧЕЙ ====================

def get_country_flag(country):
    flags = {
        'united states': '🇺🇸', 'usa': '🇺🇸', 'us': '🇺🇸',
        'united kingdom': '🇬🇧', 'uk': '🇬🇧',
        'germany': '🇩🇪', 'deutschland': '🇩🇪', 'de': '🇩🇪',
        'france': '🇫🇷', 'fr': '🇫🇷',
        'russia': '🇷🇺', 'ru': '🇷🇺',
        'china': '🇨🇳', 'cn': '🇨🇳',
        'japan': '🇯🇵', 'jp': '🇯🇵',
        'singapore': '🇸🇬', 'sg': '🇸🇬',
        'netherlands': '🇳🇱', 'nl': '🇳🇱',
        'canada': '🇨🇦', 'ca': '🇨🇦',
        'australia': '🇦🇺', 'au': '🇦🇺',
        'india': '🇮🇳', 'in': '🇮🇳',
        'brazil': '🇧🇷', 'br': '🇧🇷',
        'turkey': '🇹🇷', 'tr': '🇹🇷',
        'italy': '🇮🇹', 'it': '🇮🇹',
        'spain': '🇪🇸', 'es': '🇪🇸',
        'poland': '🇵🇱', 'pl': '🇵🇱',
        'ukraine': '🇺🇦', 'ua': '🇺🇦',
        'israel': '🇮🇱', 'il': '🇮🇱',
        'uae': '🇦🇪', 'ae': '🇦🇪',
        'las vegas': '🇺🇸',
        'saudi arabia': '🇸🇦', 'sa': '🇸🇦',
    }
    country_lower = country.lower().strip()
    for key, flag in flags.items():
        if key in country_lower:
            return flag
    return '🌍'

def format_key_for_post(key, latency, index):
    protocol_match = re.match(r'([a-z0-9+]+)://', key, re.IGNORECASE)
    protocol = protocol_match.group(1).upper() if protocol_match else "UNKNOWN"
    
    name_match = re.search(r'#([^#\s]+)', key)
    if name_match:
        name = urllib.parse.unquote(name_match.group(1))
        name = re.sub(r'\|.*$', '', name)
        name = re.sub(r'@\w+', '', name)
        name = name.strip()
    else:
        name = "VPN Server"
    
    ip_match = re.search(r'@([^:]+):(\d+)', key)
    ip = ip_match.group(1) if ip_match else "Unknown"
    
    country = "Unknown"
    city = "Unknown"
    
    countries = {
        'united states': '🇺🇸', 'usa': '🇺🇸', 'us': '🇺🇸',
        'united kingdom': '🇬🇧', 'uk': '🇬🇧',
        'germany': '🇩🇪', 'deutschland': '🇩🇪', 'de': '🇩🇪',
        'france': '🇫🇷', 'fr': '🇫🇷',
        'russia': '🇷🇺', 'ru': '🇷🇺',
        'china': '🇨🇳', 'cn': '🇨🇳',
        'japan': '🇯🇵', 'jp': '🇯🇵',
        'singapore': '🇸🇬', 'sg': '🇸🇬',
        'netherlands': '🇳🇱', 'nl': '🇳🇱',
        'canada': '🇨🇦', 'ca': '🇨🇦',
        'australia': '🇦🇺', 'au': '🇦🇺',
        'india': '🇮🇳', 'in': '🇮🇳',
        'brazil': '🇧🇷', 'br': '🇧🇷',
        'turkey': '🇹🇷', 'tr': '🇹🇷',
        'italy': '🇮🇹', 'it': '🇮🇹',
        'spain': '🇪🇸', 'es': '🇪🇸',
        'poland': '🇵🇱', 'pl': '🇵🇱',
        'ukraine': '🇺🇦', 'ua': '🇺🇦',
        'israel': '🇮🇱', 'il': '🇮🇱',
        'uae': '🇦🇪', 'ae': '🇦🇪',
        'las vegas': '🇺🇸',
    }
    
    name_lower = name.lower()
    for country_name, flag in countries.items():
        if country_name in name_lower:
            country = country_name.title()
            city_match = re.search(r'([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)', name)
            if city_match and city_match.group(1).lower() != country_name:
                city = city_match.group(1)
            break
    
    flag = get_country_flag(country)
    
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
    
    protocol_icons = {
        'VLESS': '🔹',
        'VMESS': '🔸',
        'TROJAN': '🟣',
        'SS': '🟢',
        'SSR': '🟡',
        'HYSTERIA': '🟠',
        'TUIC': '🔵',
        'WIREGUARD': '🟩',
    }
    proto_icon = protocol_icons.get(protocol.upper(), '🔹')
    
    formatted = f"""🚀 #{index} | {flag} {country}

┌ 🏷 Название: {flag} {country} | @ciorsa
├ 🔗 Протокол: {proto_icon} {protocol.upper()}
├ 📡 Пинг: {latency} ms
├ ⚡ Скорость: {speed}
├ 🌍 Город: {city}
└ 🏢 Провайдер: {ip}

🔑 Ключ для подключения:
`{key}`

⏱ Проверено: {datetime.now().strftime('%H:%M:%S')} | 🤖 @Potyjno_vpn_bot
🔗 @ciorsa"""
    
    return formatted

# ==================== ADMIN MENU ====================

def admin_menu():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📢 Рассылка", callback_data="admin_announce"),
        types.InlineKeyboardButton("👥 Управление админами", callback_data="admin_manage_admins")
    )
    kb.add(
        types.InlineKeyboardButton("👥 Управление пользователями", callback_data="admin_manage_users"),
        types.InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")
    )
    kb.add(
        types.InlineKeyboardButton("🔑 Управление ключами", callback_data="admin_keys"),
        types.InlineKeyboardButton("🚫 Блокировка", callback_data="admin_block")
    )
    kb.add(
        types.InlineKeyboardButton("📡 Автопостинг", callback_data="admin_autopost"),
        types.InlineKeyboardButton("🏠 Главное меню", callback_data="admin_back")
    )
    return kb

# ==================== ADMINS COMMANDS ====================

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.chat.type != 'private':
        return
    user_id = message.from_user.id
    if not is_admin(user_id):
        bot.reply_to(message, "⛔️ У вас нет прав администратора.")
        return
    bot.send_message(user_id, "🏛️ Админ панель:", reply_markup=admin_menu())

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def admin_callback(call):
    user_id = call.from_user.id
    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return

    data = call.data

    # ====== ГЛАВНОЕ МЕНЮ ======
    if data == "admin_back":
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
        bot.send_message(user_id, "🏠 Главное меню", reply_markup=main_menu())
        bot.answer_callback_query(call.id)
        return

    # ====== НАЗАД В АДМИН-ПАНЕЛЬ ======
    if data == "admin_back_panel":
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
        bot.send_message(user_id, "🏛️ Админ панель:", reply_markup=admin_menu())
        bot.answer_callback_query(call.id)
        return

    # ====== УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ ======
    if data == "admin_manage_users":
        bot.answer_callback_query(call.id)
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
        fake_msg = types.Message(
            message_id=call.message.message_id + 1,
            date=int(time.time()),
            chat=call.message.chat,
            from_user=call.from_user,
            text="/manage"
        )
        cmd_manage(fake_msg)
        return

    # ====== РАССЫЛКА ======
    if data == "admin_announce":
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton("📨 В ЛС бота", callback_data="announce_dm"),
            types.InlineKeyboardButton("📢 В каналы/чаты", callback_data="announce_channels"),
            types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back_panel")
        )
        bot.edit_message_text(
            "📢 *Рассылка*\n\nВыберите куда отправить объявление:",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown",
            reply_markup=kb
        )
        return

    # ====== УПРАВЛЕНИЕ АДМИНАМИ ======
    if data == "admin_manage_admins":
        bot.answer_callback_query(call.id)
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id, added_by, added_at FROM admins ORDER BY added_at")
        admins = cur.fetchall()
        cur.close()
        conn.close()
        
        kb = types.InlineKeyboardMarkup(row_width=1)
        
        for uid, added_by, added_at in admins:
            name = get_user_display_name(uid)
            date = datetime.fromtimestamp(added_at).strftime("%d.%m.%Y")
            kb.add(types.InlineKeyboardButton(
                f"👑 {name} (ID: {uid}) — {date}",
                callback_data=f"admin_detail_{uid}"
            ))
        
        kb.add(types.InlineKeyboardButton("➕ Добавить админа", callback_data="admin_add_user"))
        kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back_panel"))
        
        text = (
            "👥 *Управление админами*\n\n"
            f"👑 Всего админов: {len(admins)}\n"
            f"👤 Создатель: {ADMIN_ID}\n\n"
            "Нажмите на админа для управления:"
        )
        
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown",
            reply_markup=kb
        )
        return

    # ====== СТАТИСТИКА ======
    if data == "admin_stats":
        stats = get_bot_stats()
        total_users = 0
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users")
        total_users = cur.fetchone()[0]
        cur.close()
        conn.close()
        text = (
            f"📊 *Статистика бота*\n\n"
            f"👥 Всего пользователей: {total_users}\n"
            f"⏳ Стаж: {stats['uptime_text']}\n"
            f"🔑 Ключей в базе: {stats['current_keys']}\n"
            f"📊 Проверено ключей: {stats['total_keys_checked']}\n"
            f"🌐 Проверено прокси: {stats['total_proxies_checked']}\n"
            f"🔓 Расшифровано подписок: {stats['total_decryptions']}\n"
            f"🗑️ Выдано ключей: {stats['total_keys_issued']}"
        )
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown",
            reply_markup=admin_menu()
        )
        bot.answer_callback_query(call.id)
        return

    # ====== УПРАВЛЕНИЕ КЛЮЧАМИ ======
    if data == "admin_keys":
        bot.answer_callback_query(call.id)
        bot.send_message(
            user_id,
            "🔑 *Управление ключами*\n\n"
            "Отправьте файл или текст с ключами (vless://, vmess:// и др.)\n"
            "Или просто отправьте ссылку на подписку для загрузки.",
            parse_mode="Markdown"
        )
        loading_sessions[user_id] = {'waiting': True, 'source': 'admin_keys'}
        return

    # ====== БЛОКИРОВКА ======
    if data == "admin_block":
        bot.answer_callback_query(call.id)
        bot.send_message(
            user_id,
            "🚫 *Блокировка пользователя*\n\n"
            "Отправьте ID пользователя для блокировки.\n\n"
            "Пример: `123456789`",
            parse_mode="Markdown"
        )
        return

    # ====== АВТОПОСТИНГ ======
    if data == "admin_autopost":
        bot.answer_callback_query(call.id)
        
        config = get_autopost_config()
        status = "✅ ВКЛ" if config['enabled'] else "❌ ВЫКЛ"
        
        text = (
            "📡 *АВТОПОСТИНГ*\n\n"
            f"📊 Статус: {status}\n"
            f"⏱ Интервал: {config['interval'] // 60} мин\n"
            f"📢 Канал: {config['channel_id']}\n"
            f"📝 Ветка: {config['topic_id'] if config['topic_id'] else 'Нет'}\n\n"
            "Выберите действие:"
        )
        
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("📥 Загрузить ключи", callback_data="autopost_load_keys"),
            types.InlineKeyboardButton("🚀 Начать автопостинг", callback_data="autopost_start")
        )
        kb.add(
            types.InlineKeyboardButton("⚙️ Настройки канала", callback_data="autopost_channel_settings"),
            types.InlineKeyboardButton("⏱ Настройки интервала", callback_data="autopost_interval_settings")
        )
        kb.add(
            types.InlineKeyboardButton("📊 История", callback_data="autopost_history_menu")
        )
        kb.add(
            types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back_panel")
        )
        
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown",
            reply_markup=kb
        )
        return

# ==================== УПРАВЛЕНИЕ АДМИНАМИ (ДЕТАЛИ) ====================

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_detail_'))
def callback_admin_detail(call):
    user_id = call.from_user.id
    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    
    target_id = int(call.data.split('_')[2])
    
    if target_id == ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Это создатель, его нельзя удалить.")
        return
    
    name = get_user_display_name(target_id)
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🗑️ Снять админку", callback_data=f"admin_remove_{target_id}"),
        types.InlineKeyboardButton("🚫 Заблокировать", callback_data=f"admin_block_{target_id}")
    )
    kb.add(
        types.InlineKeyboardButton("🔙 Назад", callback_data="admin_manage_admins")
    )
    
    text = f"👤 *{name}*\n🆔 ID: `{target_id}`\n\nВыберите действие:"
    
    bot.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id,
        parse_mode="Markdown",
        reply_markup=kb
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_remove_'))
def callback_admin_remove(call):
    user_id = call.from_user.id
    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
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
    
    bot.answer_callback_query(call.id, f"✅ Админ {target_id} снят")
    callback_admin_manage_admins(call)

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_block_'))
def callback_admin_block_from_manage(call):
    user_id = call.from_user.id
    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    
    target_id = int(call.data.split('_')[2])
    
    if target_id == ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нельзя заблокировать создателя.")
        return
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT is_blocked FROM users WHERE user_id = %s", (target_id,))
    result = cur.fetchone()
    if result:
        current = result[0]
        new_status = 0 if current == 1 else 1
        cur.execute("UPDATE users SET is_blocked = %s WHERE user_id = %s", (new_status, target_id))
        conn.commit()
        status_text = "заблокирован" if new_status == 1 else "разблокирован"
        bot.answer_callback_query(call.id, f"✅ Пользователь {status_text}")
    else:
        cur.execute("INSERT INTO users (user_id, is_blocked, subscription_end, last_activity, token) VALUES (%s, 1, 0, 0, '')", (target_id,))
        conn.commit()
        bot.answer_callback_query(call.id, f"✅ Пользователь {target_id} заблокирован")
    
    cur.close()
    conn.close()
    callback_admin_manage_admins(call)

@bot.callback_query_handler(func=lambda call: call.data == "admin_add_user")
def callback_admin_add_user(call):
    user_id = call.from_user.id
    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return
    
    bot.answer_callback_query(call.id, "📝 Введите ID пользователя")
    bot.send_message(
        user_id,
        "➕ *Добавление админа*\n\n"
        "Введите ID пользователя, которому хотите выдать права администратора.\n\n"
        "Пример: `123456789`",
        parse_mode="Markdown"
    )
    search_cache[user_id] = {'action': 'add_admin_waiting'}

@bot.message_handler(func=lambda m: m.from_user.id in search_cache and search_cache.get(m.from_user.id, {}).get('action') == 'add_admin_waiting')
def handle_add_admin_input(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return
    
    try:
        target_id = int(message.text.strip())
    except:
        bot.reply_to(message, "❌ Неверный ID. Введите число.")
        return
    
    if target_id == ADMIN_ID:
        bot.reply_to(message, "❌ Это создатель.")
        return
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id = %s", (target_id,))
    if not cur.fetchone():
        token = generate_subscription_token()
        sub_end = int(time.time()) + 7 * 24 * 60 * 60
        cur.execute(
            "INSERT INTO users (user_id, subscription_end, last_activity, is_blocked, token) VALUES (%s, %s, 0, 0, %s)",
            (target_id, sub_end, token)
        )
        conn.commit()
    
    cur.execute(
        "INSERT INTO admins (user_id, added_by, added_at) VALUES (%s, %s, %s) ON CONFLICT (user_id) DO NOTHING",
        (target_id, user_id, int(time.time()))
    )
    conn.commit()
    cur.close()
    conn.close()
    
    del search_cache[user_id]
    
    name = get_user_display_name(target_id)
    bot.reply_to(message, f"✅ Админ {name} (ID: {target_id}) добавлен!")
    
    fake_msg = types.Message(
        message_id=message.message_id,
        date=int(time.time()),
        chat=message.chat,
        from_user=message.from_user,
        text="/admin"
    )
    admin_panel(fake_msg)

# ==================== АВТОПОСТИНГ (ОБРАБОТЧИКИ) ====================

@bot.callback_query_handler(func=lambda call: call.data.startswith('autopost_'))
def callback_autopost_handlers(call):
    user_id = call.from_user.id
    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return

    data = call.data

    # ====== НАЗАД В АДМИН-ПАНЕЛЬ ======
    if data == "autopost_back":
        bot.answer_callback_query(call.id)
        callback_admin_autopost(call)
        return

    # ====== ЗАГРУЗКА КЛЮЧЕЙ ======
    if data == "autopost_load_keys":
        bot.answer_callback_query(call.id, "📥 Отправьте ключи")
        bot.send_message(
            user_id,
            "📥 *Загрузка ключей*\n\n"
            "Отправьте ключи одним из способов:\n"
            "• Текст с ключами (vless://, vmess:// и др.)\n"
            "• .txt файл с ключами\n"
            "• URL подписки\n"
            "• Ссылку на GitHub репозиторий (view raw)\n\n"
            "После загрузки бот проверит ключи и покажет результат.",
            parse_mode="Markdown"
        )
        loading_sessions[user_id] = {'waiting': True, 'source': 'autopost'}
        return

    # ====== НАСТРОЙКИ КАНАЛА ======
    if data == "autopost_channel_settings":
        bot.answer_callback_query(call.id)
        config = get_autopost_config()
        
        text = (
            "⚙️ *Настройки канала*\n\n"
            f"📢 Текущий канал: {config['channel_id']}\n"
            f"📝 Текущая ветка: {config['topic_id'] if config['topic_id'] else 'Нет'}\n\n"
            "Выберите действие:"
        )
        
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton("📢 Сменить канал", callback_data="autopost_change_channel"),
            types.InlineKeyboardButton("🔙 Назад", callback_data="autopost_back")
        )
        
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown",
            reply_markup=kb
        )
        return

    # ====== СМЕНА КАНАЛА ======
    if data == "autopost_change_channel":
        bot.answer_callback_query(call.id)
        
        text = (
            "📢 *Смена канала*\n\n"
            "Текущий канал можно сбросить и выбрать новый.\n\n"
            "После сброса отправьте мне ссылку на канал или чат.\n"
            "Пример: `https://t.me/ciorsa` или `-1001234567890`"
        )
        
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton("🔄 Сбросить канал", callback_data="autopost_reset_channel"),
            types.InlineKeyboardButton("🔙 Назад", callback_data="autopost_channel_settings")
        )
        
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown",
            reply_markup=kb
        )
        return

    # ====== СБРОС КАНАЛА ======
    if data == "autopost_reset_channel":
        bot.answer_callback_query(call.id, "🔄 Канал сброшен. Отправьте новый канал.")
        bot.send_message(
            user_id,
            "📢 *Сброс канала*\n\n"
            "Канал сброшен.\n"
            "Отправьте ссылку на канал или ID чата.\n\n"
            "Пример: `https://t.me/ciorsa` или `-1001234567890`"
        )
        search_cache[user_id] = {'action': 'autopost_set_channel'}
        return

    # ====== НАСТРОЙКИ ИНТЕРВАЛА ======
    if data == "autopost_interval_settings":
        bot.answer_callback_query(call.id)
        config = get_autopost_config()
        
        text = (
            "⏱ *Настройки интервала*\n\n"
            f"⏱ Текущий интервал: {config['interval'] // 60} минут\n\n"
            "Выберите действие:"
        )
        
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton("⏱ Изменить интервал", callback_data="autopost_set_interval"),
            types.InlineKeyboardButton("🔄 Сбросить интервал", callback_data="autopost_reset_interval"),
            types.InlineKeyboardButton("🔙 Назад", callback_data="autopost_back")
        )
        
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown",
            reply_markup=kb
        )
        return

    # ====== УСТАНОВКА ИНТЕРВАЛА ======
    if data == "autopost_set_interval":
        bot.answer_callback_query(call.id, "⏱ Введите интервал в минутах")
        bot.send_message(
            user_id,
            "⏱ *Установка интервала*\n\n"
            "Введите интервал автопостинга в минутах.\n"
            "Минимальное значение: 5 минут\n"
            "Максимальное значение: 1440 минут (24 часа)\n\n"
            "Пример: `30`",
            parse_mode="Markdown"
        )
        search_cache[user_id] = {'action': 'autopost_set_interval'}
        return

    # ====== СБРОС ИНТЕРВАЛА ======
    if data == "autopost_reset_interval":
        bot.answer_callback_query(call.id, "🔄 Интервал сброшен на 30 минут")
        config = get_autopost_config()
        config['interval'] = 1800
        save_autopost_config(config)
        callback_autopost_handlers(call)
        return

    # ====== ИСТОРИЯ ======
    if data == "autopost_history_menu":
        bot.answer_callback_query(call.id)
        
        text = "📊 *История автопостинга*\n\nВыберите раздел:"
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("📊 Активные постинги", callback_data="autopost_active_history"),
            types.InlineKeyboardButton("📁 Завершенные", callback_data="autopost_completed_history")
        )
        kb.add(
            types.InlineKeyboardButton("🔙 Назад", callback_data="autopost_back")
        )
        
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown",
            reply_markup=kb
        )
        return

    # ====== АКТИВНЫЕ ПОСТИНГИ ======
    if data == "autopost_active_history":
        bot.answer_callback_query(call.id)
        
        config = get_autopost_config()
        keys = get_keys_from_db()
        
        text = (
            "📊 *Активные постинги*\n\n"
            f"📢 Канал: {config['channel_id']}\n"
            f"⏱ Интервал: {config['interval'] // 60} мин\n"
            f"📦 Всего ключей: {len(keys)}\n"
            f"🗑️ Выдано: {int(get_setting('total_keys_issued', '0'))}\n"
            f"📦 Осталось: {len(keys) - int(get_setting('total_keys_issued', '0'))}\n"
            f"📊 Статус: {'✅ Активен' if config['enabled'] else '❌ Остановлен'}\n\n"
            "Выберите действие:"
        )
        
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton("🔄 Сбросить автопостинг", callback_data="autopost_reset_active"),
            types.InlineKeyboardButton("🔙 Назад", callback_data="autopost_history_menu")
        )
        
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown",
            reply_markup=kb
        )
        return

    # ====== СБРОС АКТИВНОГО ======
    if data == "autopost_reset_active":
        bot.answer_callback_query(call.id, "🔄 Автопостинг сброшен")
        config = get_autopost_config()
        config['enabled'] = False
        save_autopost_config(config)
        callback_autopost_handlers(call)
        return

    # ====== ЗАВЕРШЕННЫЕ ПОСТИНГИ ======
    if data == "autopost_completed_history":
        bot.answer_callback_query(call.id)
        
        history = autopost_history.get('completed', [])
        
        if not history:
            text = "📁 *Завершенные постинги*\n\nНет завершенных постингов."
        else:
            text = "📁 *Завершенные постинги*\n\n"
            for i, item in enumerate(history[-10:], 1):
                text += f"{i}. Канал: {item.get('channel_id', 'Unknown')}\n"
                text += f"   📦 Выдано: {item.get('issued', 0)}\n"
                text += f"   📅 {item.get('date', 'Unknown')}\n\n"
        
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="autopost_history_menu"))
        
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown",
            reply_markup=kb
        )
        return

    # ====== ОЧИСТКА ВСЕХ ======
    if data == "autopost_clear_all":
        bot.answer_callback_query(call.id)
        save_keys_to_db([])
        set_setting('total_keys_issued', '0')
        bot.send_message(user_id, "🗑️ Все ключи удалены")
        return

    # ====== ОЧИСТКА НЕРАБОЧИХ ======
    if data == "autopost_clear_dead":
        bot.answer_callback_query(call.id, "⏳ Проверяю ключи...")
        
        keys = get_keys_from_db()
        if not keys:
            bot.send_message(user_id, "❌ Нет ключей для проверки")
            return
        
        alive_keys = []
        dead_keys = []
        
        for key in keys:
            status, _ = ping_key_advanced(key)
            if status:
                alive_keys.append(key)
            else:
                dead_keys.append(key)
        
        save_keys_to_db(alive_keys)
        
        current_issued = int(get_setting('total_keys_issued', '0'))
        set_setting('total_keys_issued', str(current_issued - len(dead_keys) if current_issued >= len(dead_keys) else 0))
        
        text = f"🧹 *Очистка нерабочих ключей завершена!*\n\n"
        text += f"✅ Оставлено живых: {len(alive_keys)}\n"
        text += f"🗑️ Удалено нерабочих: {len(dead_keys)}\n"
        text += f"📦 Всего в базе: {len(alive_keys)}"
        
        bot.send_message(user_id, text, parse_mode="Markdown")
        return

    # ====== ЗАПУСК АВТОПОСТИНГА ======
    if data == "autopost_start":
        keys = get_keys_from_db()
        if not keys:
            bot.answer_callback_query(call.id, "❌ Нет ключей для постинга")
            return
        
        config = get_autopost_config()
        config['enabled'] = True
        save_autopost_config(config)
        
        bot.answer_callback_query(call.id, "🚀 Автопостинг запущен!")
        bot.send_message(
            user_id,
            f"🚀 *Автопостинг запущен!*\n\n"
            f"📢 Канал: {config['channel_id']}\n"
            f"⏱ Интервал: {config['interval'] // 60} мин\n"
            f"📦 Ключей: {len(keys)}\n\n"
            "Автопостинг будет выполняться автоматически.",
            parse_mode="Markdown"
        )
        
        auto_post_keys_to_channel()
        return

# ==================== АВТОПОСТИНГ (ОСНОВНАЯ ФУНКЦИЯ) ====================

def ping_key_advanced(key):
    match = re.search(r'@([\d\.]+):(\d+)', key)
    if not match:
        return False, None
    ip = match.group(1)
    port = int(match.group(2))
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        start = time.time()
        result = sock.connect_ex((ip, port))
        latency = int((time.time() - start) * 1000)
        sock.close()
        if result == 0:
            return True, latency
        return False, latency
    except:
        return False, None

def auto_post_keys_to_channel():
    config = get_autopost_config()
    if not config['enabled']:
        return
    
    keys = get_keys_from_db()
    if not keys:
        bot.send_message(ADMIN_ID, "❌ Нет ключей для автопостинга")
        return
    
    channel_id = config['channel_id']
    topic_id = config['topic_id']
    
    working = []
    not_working = []
    
    for key in keys:
        status, latency = ping_key_advanced(key)
        if status:
            working.append({'key': key, 'latency': latency})
        else:
            not_working.append({'key': key})
    
    working.sort(key=lambda x: x['latency'] if x['latency'] else 9999)
    
    sent_keys = []
    for i, key_data in enumerate(working[:10], 1):
        formatted = format_key_for_post(key_data['key'], key_data['latency'], i)
        
        try:
            if topic_id and topic_id != 0:
                bot.send_message(channel_id, formatted, parse_mode="Markdown", message_thread_id=topic_id)
            else:
                bot.send_message(channel_id, formatted, parse_mode="Markdown")
            sent_keys.append(key_data['key'])
            time.sleep(0.5)
        except Exception as e:
            print(f"[autopost] Ошибка: {e}")
    
    if sent_keys:
        remove_used_keys(sent_keys)
        increment_setting('total_keys_issued', len(sent_keys))
    
    current_time = datetime.now().strftime("%d.%m.%Y %H:%M")
    stats_msg = f"""📊 *АВТОПОСТИНГ*

🕐 {current_time}
✅ Работает: {len(working)}
❌ Не работает: {len(not_working)}
🗑️ Выдано: {len(sent_keys)}
📦 Осталось: {len(get_keys_from_db())}

📢 Канал: {channel_id}
📝 Ветка: {topic_id if topic_id else 'Нет'}

🔗 @ciorsa"""
    
    try:
        bot.send_message(ADMIN_ID, stats_msg, parse_mode="Markdown")
    except Exception as e:
        print(f"[autopost] Ошибка отправки статистики: {e}")

# ==================== ЗАГРУЗКА КЛЮЧЕЙ ====================

@bot.message_handler(func=lambda m: m.chat.type == 'private' and m.from_user.id in loading_sessions)
def admin_load_keys_autopost(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return
    if user_id not in loading_sessions:
        return
    
    source = loading_sessions[user_id].get('source', 'admin_keys')
    del loading_sessions[user_id]
    
    raw_text = message.text or message.caption or ''
    
    if message.document:
        try:
            file = bot.get_file(message.document.file_id)
            file_bytes = bot.download_file(file.file_path)
            text = file_bytes.decode('utf-8', errors='ignore')
            keys = load_keys_from_text(text)
            _finish_autopost_load(message, keys, "файл")
        except Exception as e:
            bot.reply_to(message, f"❌ Ошибка загрузки файла: {e}")
        return
    
    if raw_text.strip().startswith('http'):
        keys = load_keys_from_url(raw_text.strip())
        _finish_autopost_load(message, keys, f"URL: {raw_text[:50]}...")
        return
    
    if raw_text.strip():
        keys = load_keys_from_text(raw_text)
        _finish_autopost_load(message, keys, "текст")
        return
    
    bot.reply_to(message, "❌ Отправьте текст, ссылку или файл с ключами.")

def _finish_autopost_load(message, keys, source_label):
    if not keys:
        bot.reply_to(message, "❌ Не найдено ни одного VPN ключа.")
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
        f"✅ *Ключи загружены!*\n\n"
        f"📊 Загружено ключей: {len(keys)}\n"
        f"📋 По протоколам:\n{stats}\n"
        f"📦 Всего в базе: {len(get_keys_from_db())}\n"
        f"🔗 Источник: {source_label}\n\n"
        "Теперь вы можете запустить автопостинг через меню.",
        parse_mode="Markdown"
    )

# ==================== ОБРАБОТЧИКИ РАССЫЛКИ ====================

@bot.callback_query_handler(func=lambda call: call.data == "announce_dm")
def callback_announce_dm(call):
    user_id = call.from_user.id
    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return

    bot.answer_callback_query(call.id, "📝 Отправьте текст или медиа")
    bot.send_message(
        user_id,
        "📨 *Рассылка в ЛС*\n\n"
        "Отправьте текст, фото или видео для рассылки всем пользователям.",
        parse_mode="Markdown"
    )
    announce_data[user_id] = {'type': 'dm', 'waiting': True}

@bot.callback_query_handler(func=lambda call: call.data == "announce_channels")
def callback_announce_channels(call):
    user_id = call.from_user.id
    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return

    bot.answer_callback_query(call.id)

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT channel_id, channel_name, topic_id FROM autopost_channels WHERE enabled = TRUE")
    channels = cur.fetchall()
    cur.close()
    conn.close()

    if not channels:
        bot.send_message(user_id, "❌ Нет активных каналов.")
        return

    kb = types.InlineKeyboardMarkup(row_width=1)
    for ch_id, ch_name, topic_id in channels:
        label = f"📢 {ch_name}"
        if topic_id and topic_id != 0:
            label += f" (ветка {topic_id})"
        kb.add(types.InlineKeyboardButton(label, callback_data=f"announce_to_channel_{ch_id}"))

    kb.add(types.InlineKeyboardButton("📢 Во все каналы", callback_data="announce_all_channels"))
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back_panel"))

    bot.edit_message_text(
        "📢 *Выберите канал для объявления*",
        call.message.chat.id,
        call.message.message_id,
        parse_mode="Markdown",
        reply_markup=kb
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('announce_to_channel_'))
def callback_announce_to_channel(call):
    user_id = call.from_user.id
    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return

    channel_id = int(call.data.split('_')[3])

    bot.answer_callback_query(call.id, "📝 Отправьте текст или медиа")
    bot.send_message(
        user_id,
        f"📢 *Объявление в канал*\n\n"
        f"Отправьте текст, фото или видео для публикации.\n"
        f"ID канала: `{channel_id}`",
        parse_mode="Markdown"
    )
    announce_data[user_id] = {'type': 'channel', 'channel_id': channel_id, 'waiting': True}

@bot.callback_query_handler(func=lambda call: call.data == "announce_all_channels")
def callback_announce_all_channels(call):
    user_id = call.from_user.id
    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "⛔️ Нет прав")
        return

    bot.answer_callback_query(call.id, "📝 Отправьте текст или медиа")
    bot.send_message(
        user_id,
        "📢 *Объявление во все каналы*\n\n"
        "Отправьте текст, фото или видео для публикации во все активные каналы.",
        parse_mode="Markdown"
    )
    announce_data[user_id] = {'type': 'all_channels', 'waiting': True}

# ==================== ОБРАБОТЧИК СООБЩЕНИЙ ДЛЯ РАССЫЛКИ ====================

@bot.message_handler(func=lambda m: m.chat.type == 'private' and m.from_user.id in announce_data)
def admin_announce_text(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return
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
        cur.execute("SELECT user_id FROM users")
        users = cur.fetchall()
        cur.close()
        conn.close()

        sent = 0
        failed = 0
        for (uid,) in users:
            try:
                if message.photo:
                    bot.send_photo(uid, message.photo[-1].file_id, caption=caption)
                elif message.video:
                    bot.send_video(uid, message.video.file_id, caption=caption)
                elif message.document:
                    bot.send_document(uid, message.document.file_id, caption=caption)
                elif text:
                    bot.send_message(uid, text)
                sent += 1
            except:
                failed += 1

        bot.reply_to(message, f"📢 Рассылка в ЛС завершена!\n✅ Отправлено: {sent}\n❌ Не доставлено: {failed}")
        return

    elif announce_type == 'channel':
        channel_id = data.get('channel_id')
        if not channel_id:
            bot.reply_to(message, "❌ Канал не выбран.")
            return

        try:
            if message.photo:
                bot.send_photo(channel_id, message.photo[-1].file_id, caption=caption)
            elif message.video:
                bot.send_video(channel_id, message.video.file_id, caption=caption)
            elif message.document:
                bot.send_document(channel_id, message.document.file_id, caption=caption)
            elif text:
                bot.send_message(channel_id, text)
            bot.reply_to(message, f"✅ Объявление отправлено в канал.")
        except Exception as e:
            bot.reply_to(message, f"❌ Ошибка: {e}")
        return

    elif announce_type == 'all_channels':
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT channel_id, topic_id FROM autopost_channels WHERE enabled = TRUE")
        channels = cur.fetchall()
        cur.close()
        conn.close()

        if not channels:
            bot.reply_to(message, "❌ Нет активных каналов.")
            return

        sent = 0
        failed = 0
        for ch_id, topic_id in channels:
            try:
                if topic_id and topic_id != 0:
                    if message.photo:
                        bot.send_photo(ch_id, message.photo[-1].file_id, caption=caption, message_thread_id=topic_id)
                    elif message.video:
                        bot.send_video(ch_id, message.video.file_id, caption=caption, message_thread_id=topic_id)
                    elif message.document:
                        bot.send_document(ch_id, message.document.file_id, caption=caption, message_thread_id=topic_id)
                    elif text:
                        bot.send_message(ch_id, text, message_thread_id=topic_id)
                else:
                    if message.photo:
                        bot.send_photo(ch_id, message.photo[-1].file_id, caption=caption)
                    elif message.video:
                        bot.send_video(ch_id, message.video.file_id, caption=caption)
                    elif message.document:
                        bot.send_document(ch_id, message.document.file_id, caption=caption)
                    elif text:
                        bot.send_message(ch_id, text)
                sent += 1
                time.sleep(0.3)
            except Exception as e:
                print(f"[announce] Ошибка в канал {ch_id}: {e}")
                failed += 1

        bot.reply_to(message, f"📢 Рассылка в каналы завершена!\n✅ Отправлено в {sent} каналов\n❌ Ошибок: {failed}")
        return

# ==================== MANAGE ====================

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
    kb.row(
        types.InlineKeyboardButton("🔙 Назад в админ-панель", callback_data="admin_back_panel"),
        types.InlineKeyboardButton("❌ Закрыть", callback_data="close_manage")
    )
    return kb

@bot.message_handler(commands=['manage'])
def cmd_manage(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "❌ Только для администраторов.")
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

@bot.callback_query_handler(func=lambda call: call.data.startswith('filter_') or call.data.startswith('page_') or call.data in ['close_manage', 'back_to_list', 'top_refs_admin', 'admin_back_panel'])
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
        bot.answer_callback_query(call.id)
        return

    if data == 'admin_back_panel':
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
        admin_panel(call.message)
        bot.answer_callback_query(call.id)
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
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=build_user_list_keyboard(manage_cache.get(admin_id, {}).get('users', []), 0, manage_cache.get(admin_id, {}).get('filter', 'all')))
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
        bot.answer_callback_query(call.id, "❌ Только создатель.")
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
        bot.answer_callback_query(call.id, "❌ Только создатель.")
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

# ==================== ОБРАБОТЧИК ОСТАЛЬНЫХ СООБЩЕНИЙ ====================

@bot.message_handler(func=lambda m: m.chat.type == 'private')
def handle_private_messages(message):
    user_id = message.from_user.id
    text = message.text or ''

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

    if user_id in decrypt_results and decrypt_results[user_id].get('waiting'):
        if message.document:
            try:
                file = bot.get_file(message.document.file_id)
                file_bytes = bot.download_file(file.file_path)
                raw = file_bytes.decode('utf-8', errors='ignore')
                _do_decrypt(message, user_id, text=raw, file_bytes=file_bytes, file_name=message.document.file_name)
            except Exception as e:
                bot.reply_to(message, f"❌ Ошибка: {e}")
            return
        raw_text = text.strip()
        if raw_text:
            _do_decrypt(message, user_id, text=raw_text)
        return

    if user_id in loading_sessions:
        admin_load_keys_autopost(message)
        return

    if user_id in announce_data:
        admin_announce_text(message)
        return

    if user_id in search_cache and search_cache.get(user_id, {}).get('action') == 'autopost_set_channel':
        handle_autopost_set_channel(message)
        return

    if user_id in search_cache and search_cache.get(user_id, {}).get('action') == 'autopost_set_interval':
        handle_autopost_set_interval(message)
        return

    if user_id in search_cache and search_cache.get(user_id, {}).get('action') == 'add_admin_waiting':
        handle_add_admin_input(message)
        return

    if text == "❓ Поддержка":
        bot.reply_to(message, f"💬 Поддержка: {SUPPORT}")
        return

    bot.reply_to(message, "Используйте кнопки меню.", reply_markup=main_menu())

# ==================== ОБРАБОТЧИКИ НАСТРОЕК АВТОПОСТИНГА ====================

@bot.message_handler(func=lambda m: m.from_user.id in search_cache and search_cache.get(m.from_user.id, {}).get('action') == 'autopost_set_channel')
def handle_autopost_set_channel(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return
    
    text = message.text.strip()
    del search_cache[user_id]
    
    channel_id = None
    topic_id = 0
    
    if 't.me/' in text:
        match = re.search(r't\.me/([a-zA-Z0-9_]+)', text)
        if match:
            username = match.group(1)
            try:
                chat = bot.get_chat(f"@{username}")
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
        bot.reply_to(message, "❌ Не удалось распознать канал. Отправьте ссылку или ID.")
        return
    
    config = get_autopost_config()
    config['channel_id'] = channel_id
    config['topic_id'] = topic_id
    save_autopost_config(config)
    
    bot.reply_to(message, f"✅ Канал установлен!\n📢 ID: {channel_id}\n📝 Ветка: {topic_id if topic_id else 'Нет'}")

@bot.message_handler(func=lambda m: m.from_user.id in search_cache and search_cache.get(m.from_user.id, {}).get('action') == 'autopost_set_interval')
def handle_autopost_set_interval(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return
    
    try:
        minutes = int(message.text.strip())
        if minutes < 5:
            bot.reply_to(message, "❌ Минимальное значение: 5 минут")
            return
        if minutes > 1440:
            bot.reply_to(message, "❌ Максимальное значение: 1440 минут (24 часа)")
            return
    except:
        bot.reply_to(message, "❌ Введите число (минуты).")
        return
    
    del search_cache[user_id]
    
    config = get_autopost_config()
    config['interval'] = minutes * 60
    save_autopost_config(config)
    
    bot.reply_to(message, f"✅ Интервал установлен: {minutes} минут")

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
