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

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)

check_results = {}
search_cache = {}
decrypt_results = {}
proxy_check_results = {}
loading_sessions = {}
announce_data = {}
channel_selection = {}

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

# ==================== AUTO POSTING CONFIG ====================
AUTO_POST_CHANNEL = -1003668283208
AUTO_POST_TOPIC_ID = 461
AUTO_POST_INTERVAL = 1800
AUTO_POST_ENABLED = True
AUTO_POST_EXTRA_USERS = set()

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
    if is_admin(user_id):
        cur.execute("""
            SELECT id, channel_id, channel_name, topic_id, enabled, interval_seconds, last_post, is_default 
            FROM autopost_channels 
            ORDER BY is_default DESC, id
        """)
    else:
        cur.execute("""
            SELECT c.id, c.channel_id, c.channel_name, c.topic_id, c.enabled, c.interval_seconds, c.last_post, c.is_default
            FROM autopost_channels c
            JOIN autopost_user_access a ON c.channel_id = a.channel_id
            WHERE a.user_id = %s AND a.can_post = TRUE
            ORDER BY c.is_default DESC, c.id
        """, (user_id,))
    channels = cur.fetchall()
    cur.close()
    conn.close()
    return channels

def get_channel_access(user_id, channel_id):
    if is_admin(user_id):
        return True, True
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
    if is_admin(user_id):
        return True
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
    if is_admin(user_id):
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

@bot.message_handler(func=lambda m: m.text == "🔍 Проверка ключей" or m.text == "🔍 Проверка ключей" and m.chat.type == 'private')
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
    if re.match(r'https?://', text, re.IGNORECASE):
        steps.append(f"🌐 Загружаю: {text[:60]}")
        headers = {'User-Agent': 'v2rayNG/1.8.7', 'Accept': '*/*'}
        content = None
        for timeout in [10, 20, 30]:
            try:
                resp = requests.get(text, headers=headers, timeout=timeout, verify=False)
                if resp.status_code == 200:
                    content = resp.text
                    steps.append(f"✅ Получено {len(content)} байт за {timeout}с")
                    break
            except requests.exceptions.Timeout:
                steps.append(f"⏰ Таймаут {timeout}с, пробую ещё...")
                continue
            except Exception as e:
                steps.append(f"⚠️ Ошибка: {str(e)[:50]}")
                continue
        if not content:
            steps.append("❌ Не удалось загрузить URL после всех попыток")
            return [], steps
        text = content
    keys = _parse_keys_from_content(text)
    if keys:
        steps.append(f"🔑 Извлечено ключей: {len(keys)}")
    else:
        steps.append("❌ Ключи не найдены")
    return keys, steps

# ==================== ПОДДЕРЖКА ====================

@bot.message_handler(func=lambda m: m.text == "❓ Поддержка")
def support(message):
    update_activity()
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

# ==================== МЕНЮ ДЛЯ АДМИНА (/admin) ====================

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    """Полное меню для админа"""
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "❌ Нет доступа.")
        return
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📢 Каналы", callback_data="admin_channels"),
        types.InlineKeyboardButton("👥 Доступ", callback_data="admin_access")
    )
    kb.add(
        types.InlineKeyboardButton("📥 Загрузить ключи", callback_data="admin_loadkeys"),
        types.InlineKeyboardButton("🚀 Автопостинг", callback_data="admin_autopost")
    )
    kb.add(
        types.InlineKeyboardButton("📢 Объявление", callback_data="admin_announce"),
        types.InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")
    )
    kb.add(
        types.InlineKeyboardButton("❌ Закрыть", callback_data="admin_close")
    )
    
    text = "👑 *АДМИН-ПАНЕЛЬ*\n\nВыберите действие:"
    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def admin_callback(call):
    user_id = call.from_user.id
    
    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "❌ Нет доступа.")
        return
    
    data = call.data.replace('admin_', '')
    
    if data == 'close':
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id)
        return
    
    if data == 'channels':
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT channel_id, channel_name, topic_id, enabled FROM autopost_channels")
        channels = cur.fetchall()
        cur.close()
        conn.close()
        
        if not channels:
            text = "📭 Нет каналов.\n\n/add_channel [ID] [название] [ветка]"
        else:
            text = "📢 *Каналы:*\n\n"
            for ch_id, ch_name, topic_id, enabled in channels:
                status = "✅" if enabled else "❌"
                text += f"{status} {ch_name} (ID: {ch_id})"
                if topic_id:
                    text += f" | ветка {topic_id}"
                text += "\n"
        
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=admin_back_button())
        bot.answer_callback_query(call.id)
        return
    
    if data == 'access':
        text = "👥 *Управление доступом*\n\n"
        text += "/grant [user] [channel] - выдать доступ\n"
        text += "/revoke [user] [channel] - отозвать доступ"
        
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=admin_back_button())
        bot.answer_callback_query(call.id)
        return
    
    if data == 'loadkeys':
        bot.answer_callback_query(call.id)
        cmd_loadkeys(call.message)
        return
    
    if data == 'autopost':
        config = get_autopost_config()
        status = "✅ ВКЛ" if config['enabled'] else "❌ ВЫКЛ"
        text = f"🚀 *Автопостинг*\n\nСтатус: {status}\nИнтервал: {config['interval']//60} мин"
        
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("⏸ Вкл/Выкл", callback_data="admin_autopost_toggle"),
            types.InlineKeyboardButton("⏱ Интервал", callback_data="admin_autopost_interval")
        )
        kb.add(
            types.InlineKeyboardButton("🚀 Запустить", callback_data="admin_autopost_now"),
            types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back")
        )
        
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=kb)
        bot.answer_callback_query(call.id)
        return
    
    if data == 'autopost_toggle':
        config = get_autopost_config()
        config['enabled'] = not config['enabled']
        save_autopost_config(config)
        bot.answer_callback_query(call.id, f"Автопостинг {'включен' if config['enabled'] else 'выключен'}")
        admin_callback(call)
        return
    
    if data == 'autopost_now':
        bot.answer_callback_query(call.id, "⏳ Запускаю...")
        auto_post_keys_to_channel()
        bot.send_message(call.message.chat.id, "✅ Готово!")
        return
    
    if data == 'announce':
        bot.answer_callback_query(call.id, "📝 Отправьте текст объявления")
        search_cache[user_id] = {'action': 'admin_announce'}
        return
    
    if data == 'stats':
        stats = get_bot_stats()
        text = f"📊 *Статистика*\n\n"
        text += f"⏳ Стаж: {stats['uptime_text']}\n"
        text += f"🔑 Проверено ключей: {stats['total_keys_checked']}\n"
        text += f"🔓 Расшифровано: {stats['total_decryptions']}\n"
        text += f"🌐 Проверено прокси: {stats['total_proxies_checked']}\n"
        text += f"🗑 Выдано ключей: {stats['total_keys_issued']}\n"
        text += f"📦 Ключей в базе: {stats['current_keys']}"
        
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=admin_back_button())
        bot.answer_callback_query(call.id)
        return
    
    if data == 'back':
        admin_panel(call.message)
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id)
        return

def admin_back_button():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back"))
    return kb

# ==================== МЕНЮ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ (/user) ====================

@bot.message_handler(commands=['user'])
def user_panel(message):
    """Меню для обычных пользователей"""
    user_id = message.from_user.id
    
    if is_blocked(user_id):
        bot.reply_to(message, blocked_message())
        return
    
    channels = get_user_channels(user_id)
    
    if not channels:
        bot.reply_to(message, "❌ У вас нет доступа ни к одному каналу.")
        return
    
    kb = types.InlineKeyboardMarkup(row_width=1)
    
    for ch in channels:
        ch_id, channel_id, channel_name, topic_id, enabled, interval_sec, last_post, is_default = ch
        status = "✅" if enabled else "❌"
        default = "⭐ " if is_default else ""
        label = f"{status} {default}{channel_name}"
        if topic_id and topic_id != 0:
            label += f" (ветка {topic_id})"
        kb.add(types.InlineKeyboardButton(label, callback_data=f"user_channel_{channel_id}"))
    
    kb.add(
        types.InlineKeyboardButton("📥 Загрузить ключи", callback_data="user_loadkeys")
    )
    kb.add(
        types.InlineKeyboardButton("🔄 Обновить", callback_data="user_refresh"),
        types.InlineKeyboardButton("❌ Закрыть", callback_data="user_close")
    )
    
    text = f"📊 *МОЙ ДАШБОРД*\n\n👤 {message.from_user.first_name}\n📢 Каналов: {len(channels)}\n\nВыберите канал:"
    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data.startswith('user_'))
def user_callback(call):
    user_id = call.from_user.id
    
    if is_blocked(user_id):
        bot.answer_callback_query(call.id, "🚫 Вы заблокированы.")
        return
    
    data = call.data.replace('user_', '')
    
    if data == 'refresh':
        user_panel(call.message)
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id, "🔄 Обновлено")
        return
    
    if data == 'close':
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id, "❌ Закрыто")
        return
    
    if data == 'loadkeys':
        bot.answer_callback_query(call.id)
        cmd_loadkeys(call.message)
        return
    
    if data.startswith('channel_'):
        channel_id = int(data.split('_')[1])
        
        can_post, can_manage = get_channel_access(user_id, channel_id)
        if not can_post:
            bot.answer_callback_query(call.id, "❌ Нет доступа.")
            return
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT channel_name, topic_id, enabled FROM autopost_channels WHERE channel_id = %s", (channel_id,))
        result = cur.fetchone()
        cur.close()
        conn.close()
        
        if not result:
            bot.answer_callback_query(call.id, "❌ Канал не найден.")
            return
        
        ch_name, topic_id, enabled = result
        status = "✅ Включен" if enabled else "❌ Выключен"
        
        text = f"📢 *{ch_name}*\n\n📊 Статус: {status}\n📝 Ветка: {topic_id if topic_id else 'Нет'}"
        
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("🚀 Постить сейчас", callback_data=f"user_postnow_{channel_id}"),
            types.InlineKeyboardButton("📥 Загрузить ключи", callback_data=f"user_loadkeys_to_{channel_id}")
        )
        kb.add(
            types.InlineKeyboardButton("🔙 Назад", callback_data="user_back")
        )
        
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=kb)
        bot.answer_callback_query(call.id)
        return
    
    if data.startswith('postnow_'):
        channel_id = int(data.split('_')[1])
        
        can_post, can_manage = get_channel_access(user_id, channel_id)
        if not can_post:
            bot.answer_callback_query(call.id, "❌ Нет доступа.")
            return
        
        bot.answer_callback_query(call.id, "⏳ Запускаю постинг...")
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT topic_id FROM autopost_channels WHERE channel_id = %s", (channel_id,))
        result = cur.fetchone()
        cur.close()
        conn.close()
        
        topic_id = result[0] if result else 0
        auto_post_keys_to_channel(channel_id, topic_id)
        bot.send_message(call.message.chat.id, "✅ Постинг выполнен!")
        return
    
    if data.startswith('loadkeys_to_'):
        channel_id = int(data.split('_')[2])
        
        can_post, can_manage = get_channel_access(user_id, channel_id)
        if not can_post:
            bot.answer_callback_query(call.id, "❌ Нет доступа.")
            return
        
        channel_selection[user_id] = {
            'keys': [],
            'message_id': None,
            'channel_id': channel_id,
            'topic_id': 0
        }
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT topic_id, channel_name FROM autopost_channels WHERE channel_id = %s", (channel_id,))
        result = cur.fetchone()
        cur.close()
        conn.close()
        
        if result:
            channel_selection[user_id]['topic_id'] = result[0] or 0
            ch_name = result[1]
        else:
            ch_name = str(channel_id)
        
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("📥 Начать проверку", callback_data="load_start_check"),
            types.InlineKeyboardButton("🗑️ Очистить", callback_data="load_clear"),
            types.InlineKeyboardButton("❌ Отмена", callback_data="load_cancel")
        )
        
        bot.edit_message_text(
            f"📥 *Загрузка ключей в канал: {ch_name}*\n\n"
            "Отправляйте ключи по одному или файлом.\n"
            "Поддерживаются:\n"
            "• Текст с ключами (vless://, vmess://, и т.д.)\n"
            "• Файл .txt с ключами\n"
            "• URL подписки\n"
            "• Base64 подписка\n\n"
            "Когда закончите, нажмите *Начать проверку*",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown",
            reply_markup=kb
        )
        bot.answer_callback_query(call.id)
        return
    
    if data == 'back':
        user_panel(call.message)
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id)
        return

# ==================== ЗАГРУЗКА КЛЮЧЕЙ ====================

@bot.message_handler(commands=['loadkeys'])
def cmd_loadkeys(message):
    """Загрузка ключей с выбором канала"""
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "❌ Только для администраторов.")
        return
    
    user_id = message.from_user.id
    channels = get_user_channels(user_id)
    
    if not channels:
        bot.reply_to(message, "❌ У вас нет доступа ни к одному каналу.")
        return
    
    kb = types.InlineKeyboardMarkup(row_width=1)
    for ch in channels:
        ch_id, channel_id, channel_name, topic_id, enabled, interval_sec, last_post, is_default = ch
        label = f"📢 {channel_name}"
        if topic_id and topic_id != 0:
            label += f" (ветка {topic_id})"
        kb.add(types.InlineKeyboardButton(label, callback_data=f"load_channel_{channel_id}_{topic_id}"))
    
    kb.add(types.InlineKeyboardButton("❌ Отмена", callback_data="load_cancel"))
    
    channel_selection[user_id] = {'keys': [], 'message_id': None, 'channel_id': None, 'topic_id': None}
    
    msg = bot.reply_to(message, "📥 *Выберите канал для загрузки ключей*", parse_mode="Markdown", reply_markup=kb)
    channel_selection[user_id]['message_id'] = msg.message_id

@bot.callback_query_handler(func=lambda call: call.data.startswith('load_'))
def load_callback(call):
    user_id = call.from_user.id
    
    if user_id not in channel_selection:
        bot.answer_callback_query(call.id, "❌ Сессия истекла.")
        return
    
    data = call.data.split('_')[1]
    
    if data == 'cancel':
        if user_id in channel_selection:
            del channel_selection[user_id]
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id, "❌ Отменено")
        return
    
    if data == 'clear':
        channel_selection[user_id]['keys'] = []
        bot.answer_callback_query(call.id, "🗑️ Список очищен")
        return
    
    if data == 'start_check':
        keys = channel_selection[user_id]['keys']
        channel_id = channel_selection[user_id]['channel_id']
        
        if not keys:
            bot.answer_callback_query(call.id, "❌ Нет ключей для проверки")
            return
        
        if not channel_id:
            bot.answer_callback_query(call.id, "❌ Канал не выбран")
            return
        
        bot.answer_callback_query(call.id, f"⏳ Проверяю {len(keys)} ключей...")
        
        # Сохраняем ключи в базу
        save_keys_to_db(keys)
        
        # Запускаем проверку
        check_number = get_next_check_number()
        status_msg = bot.send_message(call.message.chat.id, f"🔍 Проверка ключей #{check_number}...")
        
        thread = threading.Thread(
            target=check_keys_parallel,
            args=(keys, call.message.chat.id, status_msg, channel_id)
        )
        thread.daemon = True
        thread.start()
        
        if user_id in channel_selection:
            del channel_selection[user_id]
        return
    
    if data == 'channel':
        parts = call.data.split('_')
        channel_id = int(parts[2])
        topic_id = int(parts[3]) if len(parts) > 3 else 0
        
        channel_selection[user_id]['channel_id'] = channel_id
        channel_selection[user_id]['topic_id'] = topic_id
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT channel_name FROM autopost_channels WHERE channel_id = %s", (channel_id,))
        result = cur.fetchone()
        cur.close()
        conn.close()
        
        ch_name = result[0] if result else str(channel_id)
        
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("📥 Начать проверку", callback_data="load_start_check"),
            types.InlineKeyboardButton("🗑️ Очистить", callback_data="load_clear"),
            types.InlineKeyboardButton("❌ Отмена", callback_data="load_cancel")
        )
        
        bot.edit_message_text(
            f"📥 *Загрузка ключей в канал: {ch_name}*\n\n"
            "Отправляйте ключи по одному или файлом.\n"
            "Поддерживаются:\n"
            "• Текст с ключами (vless://, vmess://, и т.д.)\n"
            "• Файл .txt с ключами\n"
            "• URL подписки\n"
            "• Base64 подписка\n\n"
            "Когда закончите, нажмите *Начать проверку*",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown",
            reply_markup=kb
        )
        bot.answer_callback_query(call.id, f"✅ Выбран канал: {ch_name}")
        return

# ==================== АВТОПОСТИНГ ====================

def auto_post_keys_to_channel(channel_id=None, topic_id=0):
    """Автопостинг в канал"""
    keys = get_keys_from_db()
    if not keys:
        print(f"[autopost] Нет ключей")
        return
    
    if not channel_id:
        config = get_autopost_config()
        channel_id = config['channel_id']
        topic_id = config['topic_id']
    
    # Проверяем ключи
    working = []
    not_working = []
    
    for key in keys:
        status, latency = ping_key_advanced(key)
        if status:
            working.append({'key': key, 'latency': latency})
        else:
            not_working.append({'key': key})
    
    working.sort(key=lambda x: x['latency'] if x['latency'] else 9999)
    
    # Отправляем ключи
    sent_keys = []
    for i, key_data in enumerate(working[:10], 1):
        key = key_data['key']
        latency = key_data['latency']
        
        # Форматируем ключ с меткой @ciorsa
        if '| @ciorsa' not in key:
            if '#' in key:
                key = key.replace('#', '# | @ciorsa ')
            else:
                key = f"{key} # | @ciorsa"
        
        formatted = f"🚀 #{i} | {key}\n⏱ Пинг: {latency}ms"
        
        try:
            if topic_id and topic_id != 0:
                bot.send_message(channel_id, formatted, parse_mode="Markdown", message_thread_id=topic_id)
            else:
                bot.send_message(channel_id, formatted, parse_mode="Markdown")
            sent_keys.append(key_data['key'])
            time.sleep(0.3)
        except Exception as e:
            print(f"[autopost] Ошибка: {e}")
    
    # Удаляем выданные ключи
    if sent_keys:
        remove_used_keys(sent_keys)
        increment_setting('total_keys_issued', len(sent_keys))
    
    # Статистика
    current_time = datetime.now().strftime("%d.%m.%Y %H:%M")
    stats_msg = f"""📊 *Автопостинг*

🕐 {current_time}
✅ Работает: {len(working)}
❌ Не работает: {len(not_working)}
🗑️ Выдано: {len(sent_keys)}
📦 Осталось: {len(get_keys_from_db())}

🔗 @ciorsa"""
    
    try:
        if topic_id and topic_id != 0:
            bot.send_message(channel_id, stats_msg, parse_mode="Markdown", message_thread_id=topic_id)
        else:
            bot.send_message(channel_id, stats_msg, parse_mode="Markdown")
    except:
        pass

def ping_key_advanced(key):
    """Проверяет доступность ключа (пинг)"""
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

def check_keys_parallel(keys, chat_id, status_msg, channel_id=None):
    """Проверка ключей в несколько потоков"""
    results = []
    working = 0
    not_working = 0
    total = len(keys)
    
    for i, key in enumerate(keys):
        if i % 3 == 0:
            try:
                bot.edit_message_text(
                    f"🔍 Проверяю ключи...\n⏳ {i}/{total}",
                    chat_id, status_msg.message_id
                )
            except:
                pass
        
        status, latency = ping_key_advanced(key)
        results.append({'key': key, 'status': status, 'latency': latency})
        
        if status:
            working += 1
        else:
            not_working += 1
    
    # Обновляем статистику
    increment_setting('total_keys_checked', total)
    
    # Сохраняем только живые ключи
    alive_keys = [r['key'] for r in results if r['status']]
    if alive_keys:
        save_keys_to_db(alive_keys)
    
    # Финальное сообщение
    final_text = f"""📊 *ПРОВЕРКА ЗАВЕРШЕНА*

✅ Живые: {working}
❌ Мертвые: {not_working}
📡 Всего: {total}

📁 Файл с результатами:"""
    
    try:
        bot.edit_message_text(final_text, chat_id, status_msg.message_id, parse_mode="Markdown")
    except:
        bot.send_message(chat_id, final_text, parse_mode="Markdown")
    
    # Создаем файл с результатами
    filename = f"check_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    file_content = f"# Проверка ключей\n# {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    file_content += f"✅ Живые ({working}):\n"
    for r in results:
        if r['status']:
            file_content += f"{r['key']} | {r['latency']}ms\n"
    file_content += f"\n❌ Мертвые ({not_working}):\n"
    for r in results:
        if not r['status']:
            file_content += f"{r['key']}\n"
    
    buf = io.BytesIO(file_content.encode('utf-8'))
    buf.name = filename
    bot.send_document(chat_id, buf, caption=f"📊 Результаты проверки")

# ==================== ОБЪЯВЛЕНИЯ ====================

@bot.message_handler(func=lambda m: m.from_user.id in search_cache and search_cache.get(m.from_user.id, {}).get('action') == 'admin_announce')
def handle_admin_announce(message):
    """Обработка текста объявления от админа"""
    user_id = message.from_user.id
    text = message.text.strip()
    
    if not text:
        bot.reply_to(message, "❌ Текст не может быть пустым")
        return
    
    # Получаем все каналы
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT channel_id, topic_id, channel_name FROM autopost_channels WHERE enabled = TRUE")
    channels = cur.fetchall()
    cur.close()
    conn.close()
    
    if not channels:
        bot.reply_to(message, "❌ Нет активных каналов.")
        return
    
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("📢 Во все каналы", callback_data="announce_all"))
    for ch_id, topic_id, ch_name in channels:
        label = f"📢 {ch_name}"
        if topic_id:
            label += f" (ветка {topic_id})"
        kb.add(types.InlineKeyboardButton(label, callback_data=f"announce_to_{ch_id}"))
    
    kb.add(types.InlineKeyboardButton("❌ Отмена", callback_data="announce_cancel"))
    
    search_cache[user_id] = {'action': 'announce', 'text': text}
    
    bot.reply_to(
        message,
        f"📢 *Выберите канал для объявления:*\n\n{text[:200]}",
        parse_mode="Markdown",
        reply_markup=kb
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('announce_'))
def announce_callback(call):
    user_id = call.from_user.id
    
    if user_id not in search_cache or search_cache[user_id].get('action') != 'announce':
        bot.answer_callback_query(call.id, "❌ Сессия истекла.")
        return
    
    data = call.data.split('_')[1]
    
    if data == 'cancel':
        if user_id in search_cache:
            del search_cache[user_id]
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id, "❌ Отменено")
        return
    
    text = search_cache[user_id]['text']
    formatted = f"📢 *ОБЪЯВЛЕНИЕ*\n\n{text}\n\n---\n🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n🤖 @Potyjno_vpn_bot"
    
    if data == 'all':
        # Во все каналы
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT channel_id, topic_id FROM autopost_channels WHERE enabled = TRUE")
        channels = cur.fetchall()
        cur.close()
        conn.close()
        
        success = 0
        for ch_id, topic_id in channels:
            try:
                if topic_id:
                    bot.send_message(ch_id, formatted, parse_mode="Markdown", message_thread_id=topic_id)
                else:
                    bot.send_message(ch_id, formatted, parse_mode="Markdown")
                success += 1
                time.sleep(0.3)
            except:
                pass
        
        bot.answer_callback_query(call.id, f"✅ Отправлено в {success} каналов")
        bot.send_message(call.message.chat.id, f"✅ Объявление отправлено в {success} каналов")
        
    else:
        # В один канал
        channel_id = int(data)
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT topic_id, channel_name FROM autopost_channels WHERE channel_id = %s", (channel_id,))
        result = cur.fetchone()
        cur.close()
        conn.close()
        
        if not result:
            bot.answer_callback_query(call.id, "❌ Канал не найден.")
            return
        
        topic_id, ch_name = result
        
        try:
            if topic_id:
                bot.send_message(channel_id, formatted, parse_mode="Markdown", message_thread_id=topic_id)
            else:
                bot.send_message(channel_id, formatted, parse_mode="Markdown")
            bot.answer_callback_query(call.id, f"✅ Отправлено в {ch_name}")
            bot.send_message(call.message.chat.id, f"✅ Объявление отправлено в {ch_name}")
        except Exception as e:
            bot.answer_callback_query(call.id, f"❌ Ошибка: {e}")
    
    if user_id in search_cache:
        del search_cache[user_id]
    
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass

# ==================== ADMIN COMMANDS ====================

@bot.message_handler(commands=['grant'])
def cmd_grant(message):
    if not is_admin(message.from_user.id):
        return
    
    args = message.text.split()
    if len(args) < 3:
        bot.reply_to(message, "❌ /grant [user_id] [channel_id] [manage?]")
        return
    
    try:
        user_id = int(args[1])
        channel_id = int(args[2])
        can_manage = args[3].lower() == 'true' if len(args) > 3 else False
    except:
        bot.reply_to(message, "❌ Неверные аргументы.")
        return
    
    grant_channel_access(user_id, channel_id, can_manage, False, message.from_user.id)
    bot.reply_to(message, f"✅ Доступ выдан.")

@bot.message_handler(commands=['revoke'])
def cmd_revoke(message):
    if not is_admin(message.from_user.id):
        return
    
    args = message.text.split()
    if len(args) < 3:
        bot.reply_to(message, "❌ /revoke [user_id] [channel_id]")
        return
    
    try:
        user_id = int(args[1])
        channel_id = int(args[2])
    except:
        bot.reply_to(message, "❌ Неверные аргументы.")
        return
    
    remove_channel_access(user_id, channel_id)
    bot.reply_to(message, f"✅ Доступ отозван.")

@bot.message_handler(commands=['add_channel'])
def cmd_add_channel(message):
    if not is_admin(message.from_user.id):
        return
    
    args = message.text.split(maxsplit=3)
    if len(args) < 3:
        bot.reply_to(message, "❌ /add_channel [channel_id] [название] [topic_id]")
        return
    
    try:
        channel_id = int(args[1])
        channel_name = args[2]
        topic_id = int(args[3]) if len(args) > 3 else 0
    except:
        bot.reply_to(message, "❌ Неверные аргументы.")
        return
    
    add_channel(channel_id, channel_name, topic_id, message.from_user.id)
    bot.reply_to(message, f"✅ Канал '{channel_name}' добавлен.")

# ==================== FLASK ROUTES ====================

@app.route('/ping')
def ping():
    update_activity()
    return "ok", 200

@app.route('/health')
def health():
    stats = get_bot_stats()
    return {
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'uptime': stats['uptime_text'],
        'keys_checked': stats['total_keys_checked'],
        'decryptions': stats['total_decryptions'],
        'proxies_checked': stats['total_proxies_checked']
    }, 200

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
    while True:
        try:
            print(f"[bot] Запуск бота в {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            bot.infinity_polling(skip_pending=True, timeout=60)
        except Exception as e:
            print(f"[bot] Ошибка: {e}")
            print(traceback.format_exc())
            time.sleep(10)

if __name__ == '__main__':
    print(f"[main] Инициализация бота в {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    init_db()
    ensure_bot_start_time()
    if not get_keys_from_db():
        save_keys_to_db(DEFAULT_KEYS)
    
    keep_alive_thread = Thread(target=keep_alive_ping)
    keep_alive_thread.daemon = True
    keep_alive_thread.start()
    print("[main] ✅ Запущен пинг-механизм (каждые 4 минуты)")
    
    restart_monitor_thread = Thread(target=auto_restart_monitor)
    restart_monitor_thread.daemon = True
    restart_monitor_thread.start()
    print("[main] ✅ Запущен монитор перезапуска")
    
    bot_thread = Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    print("[main] ✅ Бот запущен")
    
    print(f"[main] 🚀 Запуск веб-сервера на порту 10000")
    from waitress import serve
    serve(app, host='0.0.0.0', port=10000, threads=4, connection_limit=100)
    
