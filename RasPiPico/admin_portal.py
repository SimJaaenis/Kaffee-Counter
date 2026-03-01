import hashlib
import os
import socket
import time
import binascii
from machine import I2C, Pin

try:
    import ujson as json
except Exception:
    import json

import network
import rp2

import ledger
import config_pins as pins
from drivers.pn532_i2c import PN532I2C
from drivers.rtc_ds1307 import DS1307Clock


SESSION_TTL_S = 1800


def _fmt_eur(cents):
    neg = int(cents) < 0
    v = -int(cents) if neg else int(cents)
    euros = v // 100
    cents_part = v % 100
    out = "{}{:d},{:02d}".format("-" if neg else "", euros, cents_part)
    return out


def _parse_eur_to_cents(text):
    raw = (text or "").strip()
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    if not raw:
        raise ValueError("empty")
    return int(round(float(raw) * 100))


def _month_key_now():
    lt = time.localtime()
    return "{:04d}-{:02d}".format(lt[0], lt[1])


def _parse_jingle_sequence(text):
    # Format: "freq:dur,freq:dur,..." e.g. "988:120,1109:120,0:40,1319:200"
    raw = (text or "").strip()
    if not raw:
        return None
    seq = []
    for part in raw.split(","):
        p = part.strip()
        if not p:
            continue
        if ":" not in p:
            return None
        f, d = p.split(":", 1)
        try:
            freq = int(f.strip())
            dur = int(d.strip())
        except Exception:
            return None
        if dur <= 0:
            return None
        seq.append([freq, dur])
    return seq if seq else None


def _html_page(title, body):
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>{}</title>"
        "<style>body{{font-family:Arial,sans-serif;background:#f2f2f2;margin:0;padding:16px}}"
        ".card{{background:#fff;border-radius:10px;padding:12px;margin-bottom:12px}}"
        "input,textarea,button,select{{font-size:14px;padding:6px;margin:4px 0;width:100%}}"
        "a{{text-decoration:none;color:#1e5bb8}}"
        "table{{width:100%;border-collapse:collapse}}th,td{{border:1px solid #ddd;padding:6px;text-align:left}}"
        "</style></head><body><div class='card'><h2>{}</h2>{}</div></body></html>"
    ).format(title, title, body)


def _url_decode(s):
    s = s.replace("+", " ")
    out = ""
    i = 0
    while i < len(s):
        if s[i] == "%" and i + 2 < len(s):
            try:
                out += chr(int(s[i + 1:i + 3], 16))
                i += 3
                continue
            except Exception:
                pass
        out += s[i]
        i += 1
    return out


def _parse_form(body_bytes):
    raw = (body_bytes or b"").decode("utf-8", "ignore")
    result = {}
    if not raw:
        return result
    for pair in raw.split("&"):
        if "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        result[_url_decode(k)] = _url_decode(v)
    return result


def _parse_query(path):
    if "?" not in path:
        return path, {}
    base, q = path.split("?", 1)
    params = {}
    for pair in q.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            params[_url_decode(k)] = _url_decode(v)
    return base, params


def _get_cookie(headers, key):
    cookies = headers.get("cookie", "")
    for item in cookies.split(";"):
        item = item.strip()
        if not item or "=" not in item:
            continue
        k, v = item.split("=", 1)
        if k.strip() == key:
            return v.strip()
    return None


def _sha256_hex(text):
    h = hashlib.sha256((text or "").encode())
    try:
        return h.hexdigest()
    except Exception:
        # MicroPython builds may only provide digest()
        return binascii.hexlify(h.digest()).decode()


class AdminPortal:
    def __init__(self, store, logger, rgb=None, lcd=None, buzzer=None, printer=None):
        self.store = store
        self.logger = logger
        self.rgb = rgb
        self.lcd = lcd
        self.buzzer = buzzer
        self.printer = printer
        self.sessions = {}
        self.ap = None
        self.dns_sock = None
        self.http_sock = None
        self._blink_on = True
        self._last_blink_ms = time.ticks_ms()
        self._last_station_dump_ms = time.ticks_ms()

        self.ap_ip = self.store.ap_config().get("ip", "192.168.4.1")
        self.i2c = None
        self.pn532 = None
        self.rtc = None
        self._logs_cache_key = None
        self._logs_cache_sig = None
        self._logs_cache_html = None

    def _dbg(self, *args):
        print("[admin]", *args)

    def _confirm_beep(self):
        if not self.buzzer:
            return
        try:
            self.buzzer.success_async()
        except Exception:
            try:
                self.buzzer.play([(1568, 25), (0, 8), (1760, 35)])
            except Exception:
                pass

    def _admin_action_paths(self, month_key):
        paths = []
        paths.append("{}/logs/admin_actions_{}.csv".format(self.store.root, month_key))
        return paths

    def _append_admin_action(self, actor, action, target="", detail=""):
        ts = "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(*time.localtime()[:6])
        month_key = _month_key_now()
        row = "{ts};{actor};{action};{target};{detail}\n".format(
            ts=ts,
            actor=(actor or "").replace(";", ","),
            action=(action or "").replace(";", ","),
            target=(target or "").replace(";", ","),
            detail=(detail or "").replace("\n", " ").replace(";", ","),
        )
        for path in self._admin_action_paths(month_key):
            try:
                parent = path.rsplit("/", 1)[0]
                try:
                    os.mkdir(parent)
                except OSError:
                    pass
                try:
                    with open(path, "r"):
                        pass
                except OSError:
                    with open(path, "w") as f:
                        f.write("ts;admin;action;target;detail\n")
                with open(path, "a") as f:
                    f.write(row)
            except Exception:
                pass

    def _init_nfc_reader(self):
        if self.pn532 is not None:
            return True
        try:
            self._ensure_i2c()
            devices = self.i2c.scan()
            if pins.PN532_ADDR not in devices:
                self._dbg("PN532 nicht gefunden auf 0x{:02X}".format(pins.PN532_ADDR))
                return False
            self.pn532 = PN532I2C(self.i2c, address=pins.PN532_ADDR)
            _ = self.pn532.firmware_version
            self.pn532.SAM_configuration()
            return True
        except Exception as exc:
            self._dbg("PN532 init failed:", exc)
            self.pn532 = None
            return False

    def _ensure_i2c(self):
        if self.i2c is not None:
            return True
        try:
            self.i2c = I2C(
                pins.I2C_ID,
                sda=Pin(pins.I2C_SDA_PIN),
                scl=Pin(pins.I2C_SCL_PIN),
                freq=pins.I2C_FREQ,
            )
            return True
        except Exception:
            self.i2c = None
            return False

    def _init_rtc_reader(self):
        if self.rtc is not None:
            return True
        if not self._ensure_i2c():
            return False
        try:
            self.rtc = DS1307Clock(self.i2c, address=pins.RTC_ADDR)
            return True
        except Exception:
            self.rtc = None
            return False

    @staticmethod
    def _weekday_ymd(year, month, day):
        # 0=Mon ... 6=Sun
        t = [0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4]
        y = int(year)
        m = int(month)
        d = int(day)
        if m < 3:
            y -= 1
        # Sakamoto gives 0=Sun..6=Sat
        sun0 = (y + y // 4 - y // 100 + y // 400 + t[m - 1] + d) % 7
        return (sun0 + 6) % 7

    def _parse_datetime_local(self, value):
        raw = (value or "").strip()
        if not raw:
            return None
        raw = raw.replace("T", " ")
        try:
            date_part, time_part = raw.split(" ", 1)
            y, mo, d = date_part.split("-", 2)
            hh, mm = time_part.split(":", 1)
            ss = 0
            if ":" in mm:
                mm, ss = mm.split(":", 1)
            year = int(y)
            month = int(mo)
            day = int(d)
            hour = int(hh)
            minute = int(mm)
            second = int(ss)
            if year < 2000 or year > 2099:
                return None
            if month < 1 or month > 12:
                return None
            if day < 1 or day > 31:
                return None
            if hour < 0 or hour > 23:
                return None
            if minute < 0 or minute > 59:
                return None
            if second < 0 or second > 59:
                return None
            weekday = self._weekday_ymd(year, month, day)
            return (year, month, day, weekday, hour, minute, second)
        except Exception:
            return None

    def _rtc_time_page(self, message=""):
        rtc_text = "RTC nicht verfuegbar"
        local = "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(*time.localtime()[:6])
        if self._init_rtc_reader() and self.rtc and self.rtc.available():
            ts, src = self.rtc.timestamp_with_source()
            rtc_text = "{} ({})".format(ts, src)
        body = self._admin_menu()
        if message:
            body += "<p><b>{}</b></p>".format(message)
        body += "<p>RTC Zeit: {}</p>".format(rtc_text)
        body += "<p>Systemzeit: {}</p>".format(local)
        body += (
            "<h3>Zeit manuell setzen</h3>"
            "<form method='post' action='/time/set'>"
            "<input type='datetime-local' name='dt_local'>"
            "<button type='submit'>RTC setzen</button></form>"
            "<h3>Mit Browserzeit synchronisieren</h3>"
            "<form id='syncForm' method='post' action='/time/sync-browser'>"
            "<input type='hidden' name='browser_dt' id='browser_dt'>"
            "<button type='submit'>Browserzeit uebernehmen</button></form>"
            "<script>"
            "var d=new Date();"
            "var p=function(n){return (n<10?'0':'')+n};"
            "var s=d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate())+'T'+p(d.getHours())+':'+p(d.getMinutes())+':'+p(d.getSeconds());"
            "document.getElementById('browser_dt').value=s;"
            "</script>"
        )
        return _html_page("Zeit", body)

    def _scan_uid(self, timeout_ms=8000):
        if not self._init_nfc_reader():
            return None
        started = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), started) < timeout_ms:
            try:
                uid = self.pn532.read_passive_target(timeout=0.12)
                if uid is not None:
                    return "".join("{:02X}".format(b) for b in uid)
            except Exception:
                self.pn532 = None
                return None
            time.sleep_ms(50)
        return None

    def _lcd_write_lines(self, l1, l2="", l3="", l4=""):
        if self.lcd is None:
            return
        lines = [l1, l2, l3, l4]
        try:
            self.lcd.clear()
            for row, text in enumerate(lines):
                self.lcd.move_to(0, row)
                t = (text or "")
                if len(t) < 20:
                    t += " " * (20 - len(t))
                self.lcd.putstr(t[:20])
        except Exception:
            pass

    def _new_token(self):
        token = os.urandom(16)
        return "".join("{:02x}".format(b) for b in token)

    def _session_user(self, headers):
        token = _get_cookie(headers, "session")
        if not token:
            return None
        item = self.sessions.get(token)
        if not item:
            return None
        if time.time() > item["exp"]:
            self.sessions.pop(token, None)
            return None
        item["exp"] = time.time() + SESSION_TTL_S
        return item["username"]

    def _create_session(self, username):
        token = self._new_token()
        self.sessions[token] = {"username": username, "exp": time.time() + SESSION_TTL_S}
        return token

    def _configure_ap(self):
        ap_cfg = self.store.ap_config()
        ssid = ap_cfg.get("ssid", "KaffeeCounter-Admin")
        mode = (ap_cfg.get("mode", "open") or "open").lower()
        password = ap_cfg.get("wpa2_password", "KaffeeAdmin42")
        hidden = 1 if ap_cfg.get("hidden", True) else 0

        rp2.country("DE")
        ap = network.WLAN(network.AP_IF)
        ap.active(False)
        time.sleep_ms(100)
        ap.active(True)

        open_attempts = [
            {"ssid": ssid, "security": 0, "hidden": hidden},
            {"essid": ssid, "security": 0, "hidden": hidden},
            {"ssid": ssid, "hidden": hidden},
            {"essid": ssid, "hidden": hidden},
            {"ssid": ssid, "security": 0},
            {"essid": ssid, "security": 0},
            {"ssid": ssid},
            {"essid": ssid},
        ]
        secure_attempts = [
            {"ssid": ssid, "key": password, "security": 3, "hidden": hidden},
            {"essid": ssid, "password": password, "security": 3, "hidden": hidden},
            {"essid": ssid, "password": password, "authmode": 3, "hidden": hidden},
            {"ssid": ssid, "key": password, "security": 4, "hidden": hidden},
            {"essid": ssid, "password": password, "security": 4, "hidden": hidden},
            {"ssid": ssid, "key": password, "security": 3},
            {"essid": ssid, "password": password, "security": 3},
            {"essid": ssid, "password": password, "authmode": 3},
            {"ssid": ssid, "key": password},
            {"essid": ssid, "password": password},
        ]
        attempts = open_attempts + secure_attempts if mode != "secure" else secure_attempts + open_attempts

        configured = False
        for cfg in attempts:
            try:
                ap.config(**cfg)
                # Verify SSID really applied; some firmware accepts config call but ignores values.
                essid_now = None
                try:
                    essid_now = ap.config("essid")
                except Exception:
                    try:
                        essid_now = ap.config("ssid")
                    except Exception:
                        essid_now = None

                if essid_now == ssid:
                    configured = True
                    self._dbg("AP config", cfg, "mode_pref=", mode)
                    break
                else:
                    self._dbg("AP config ignored", cfg, "current_essid=", essid_now)
            except Exception:
                pass

        if not configured:
            # Last-ditch minimal config path for highly restricted builds.
            try:
                ap.config(essid=ssid)
                essid_now = ap.config("essid")
                if essid_now == ssid:
                    configured = True
                    self._dbg("AP minimal essid fallback active")
            except Exception:
                pass

        if not configured:
            raise RuntimeError("AP config failed on this firmware (SSID not applied)")

        ap.ifconfig((self.ap_ip, "255.255.255.0", self.ap_ip, self.ap_ip))
        self.ap = ap
        self._dbg("AP started", ap.ifconfig())

    def _start_dns(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.ap_ip, 53))
        sock.setblocking(False)
        self.dns_sock = sock

    def _build_dns_resp(self, req):
        tid = req[0:2]
        header = tid + b"\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00"

        idx = 12
        qlen = len(req)
        while idx < qlen and req[idx] != 0:
            idx += 1 + req[idx]
        idx += 1
        question = req[12:idx + 4]

        ip_bytes = bytes(map(int, self.ap_ip.split(".")))
        answer = b"\xC0\x0C\x00\x01\x00\x01\x00\x00\x00\x3C\x00\x04" + ip_bytes
        return header + question + answer

    def _start_http(self):
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.ap_ip, 80))
        sock.listen(4)
        sock.setblocking(False)
        self.http_sock = sock

    def _read_http_req(self, conn):
        data = b""
        while b"\r\n\r\n" not in data and len(data) < 8192:
            chunk = conn.recv(512)
            if not chunk:
                break
            data += chunk

        if not data:
            return None

        if b"\r\n\r\n" in data:
            head, body = data.split(b"\r\n\r\n", 1)
        else:
            head, body = data, b""

        lines = head.decode("utf-8", "ignore").split("\r\n")
        first = lines[0].split(" ")
        method = first[0] if len(first) > 0 else "GET"
        path = first[1] if len(first) > 1 else "/"

        headers = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()

        content_len = int(headers.get("content-length", "0") or "0")
        while len(body) < content_len and len(body) < 65536:
            chunk = conn.recv(512)
            if not chunk:
                break
            body += chunk

        return method, path, headers, body

    def _send(self, conn, status, body, headers=None, cookie=None):
        if headers is None:
            headers = {}
        if isinstance(body, str):
            body = body.encode()

        response = "HTTP/1.1 {}\r\n".format(status)
        response += "Content-Length: {}\r\n".format(len(body))
        if "Content-Type" not in headers:
            response += "Content-Type: text/html; charset=utf-8\r\n"
        for k, v in headers.items():
            response += "{}: {}\r\n".format(k, v)
        if cookie:
            response += "Set-Cookie: {}\r\n".format(cookie)
        response += "Connection: close\r\n\r\n"
        self._send_all(conn, response.encode())
        self._send_all(conn, body)

    @staticmethod
    def _send_all(conn, data):
        if not data:
            return
        view = memoryview(data)
        sent_total = 0
        length = len(view)
        while sent_total < length:
            try:
                sent = conn.send(view[sent_total:])
            except Exception:
                break
            if sent is None:
                # Some ports may return None for "sent all".
                break
            if sent <= 0:
                break
            sent_total += sent

    def _bookings_files_signature(self):
        logs_dir = "{}/logs".format(self.store.root)
        try:
            names = os.listdir(logs_dir)
        except OSError:
            return "no-logs"
        pairs = []
        for name in names:
            if not name.startswith("bookings_") or not name.endswith(".csv"):
                continue
            if "mirror" in name:
                continue
            path = "{}/{}".format(logs_dir, name)
            try:
                st = os.stat(path)
                size = int(st[6]) if len(st) > 6 else 0
            except Exception:
                size = -1
            pairs.append((name, size))
        if not pairs:
            return "empty"
        pairs.sort(reverse=True)
        # Keep signature short: newest up to 4 files.
        parts = []
        for name, size in pairs[:4]:
            parts.append("{}:{}".format(name, size))
        return "|".join(parts)

    def _redirect(self, conn, location):
        self._send(conn, "302 Found", b"", headers={"Location": location})

    def _admin_menu(self):
        return (
            "<p><a href='/'>Dashboard</a> | <a href='/users'>Nutzer</a> | "
            "<a href='/enroll'>Nutzer anlegen</a> | <a href='/deposit'>Einzahlung</a> | <a href='/logs'>Logs</a> | "
            "<a href='/products'>Products</a> | <a href='/admins'>Admins</a> | "
            "<a href='/password'>Passwort</a> | <a href='/time'>Zeit</a> | <a href='/jingles'>Jingles</a> | "
            "<a href='/printer'>Druck</a> | <a href='/admin-actions'>Aenderungslog</a> | <a href='/logout'>Logout</a></p>"
        )

    def _dashboard(self):
        users = self.store.list_users()
        body = self._admin_menu()
        body += "<p>Nutzer: {} | Queue: {} | RAM-Logs: {}</p>".format(
            len(users), self.logger.pending(), len(self.logger.ram_ledger)
        )
        body += (
            "<h3>SD Sync</h3>"
            "<p>Interne Konfiguration + Logs auf SD sichern (manuell).</p>"
            "<form method='post' action='/sync/sd'>"
            "<button type='submit'>Jetzt auf SD sichern</button>"
            "</form>"
        )
        body += (
            "<h3>Balances</h3>"
            "<p>Kontostaende aus internen Buchungslogs komplett neu berechnen.</p>"
            "<form method='post' action='/balances/rebuild'>"
            "<button type='submit'>Balances neu berechnen</button>"
            "</form>"
        )
        return _html_page("Admin Dashboard", body)

    def _printer_page(self, message=""):
        cfg = self.store.printer_config()
        status = "aktiv" if cfg.get("enabled", False) else "deaktiviert"
        body = self._admin_menu()
        if message:
            body += "<p><b>{}</b></p>".format(message)
        body += "<p>Druckerstatus: {}</p>".format(status)
        body += (
            "<form method='post' action='/printer/test'><button type='submit'>Testseite drucken</button></form>"
            "<form method='post' action='/printer/ranking-week'><button type='submit'>Wochenranking drucken</button></form>"
            "<form method='post' action='/printer/ranking-month'><button type='submit'>Monatsranking drucken</button></form>"
        )
        return _html_page("Druck", body)

    @staticmethod
    def _normalize_day(text):
        raw = (text or "").strip()
        if not raw:
            return ""
        if len(raw) >= 10:
            return raw[:10]
        return ""

    @staticmethod
    def _collapse_canceled_entries(entries):
        # Hide purchase+undo pairs so only effective (valued) transactions remain.
        if not entries:
            return entries

        # Work on ascending timeline for stable matching.
        indexed = list(enumerate(entries))
        indexed.sort(key=lambda it: it[1].get("ts", ""))

        open_purchases = {}
        canceled_idx = set()

        def _k(item):
            return (
                item.get("user_id", ""),
                item.get("product_id", ""),
                int(item.get("qty", 0) or 0),
                abs(int(item.get("amount_cents", 0) or 0)),
            )

        for original_idx, item in indexed:
            typ = item.get("type", "")
            if typ == "purchase":
                key = _k(item)
                bucket = open_purchases.get(key)
                if bucket is None:
                    bucket = []
                    open_purchases[key] = bucket
                bucket.append(original_idx)
            elif typ == "undo":
                key = _k(item)
                bucket = open_purchases.get(key)
                if bucket:
                    # Cancel latest open purchase (LIFO).
                    purchase_idx = bucket.pop()
                    canceled_idx.add(purchase_idx)
                    canceled_idx.add(original_idx)

        out = []
        for i, item in enumerate(entries):
            if i in canceled_idx:
                continue
            out.append(item)
        return out

    def _load_booking_entries(self, params):
        user_filter = (params.get("user_id", "") or "").strip()
        type_filter = (params.get("type", "") or "").strip()
        valued_only = (params.get("valued_only", "0") or "0").strip() == "1"
        date_from = self._normalize_day(params.get("from", ""))
        date_to = self._normalize_day(params.get("to", ""))
        try:
            months = int(params.get("months", "3") or "3")
        except Exception:
            months = 3
        if months < 1:
            months = 1
        if months > 24:
            months = 24

        try:
            page_hint = int(params.get("page", "1") or "1")
        except Exception:
            page_hint = 1
        try:
            per_page_hint = int(params.get("per_page", "30") or "30")
        except Exception:
            per_page_hint = 30
        if page_hint < 1:
            page_hint = 1
        if per_page_hint < 10:
            per_page_hint = 10
        if per_page_hint > 100:
            per_page_hint = 100
        # Keep memory bounded on microcontroller.
        max_scan = min(350, max(120, (page_hint * per_page_hint) + 120))

        no_filters = (not user_filter) and (not type_filter) and (not date_from) and (not date_to)
        if no_filters:
            # Fast path for captive portal: tail from newest files only.
            all_entries = ledger.tail_recent_entries(
                self.store.root,
                limit=min(max_scan, 250),
                max_files=min(2, months),
                max_bytes_per_file=16384,
            )
        else:
            all_entries = ledger.scan_recent_entries(self.store.root, months=months, max_entries=max_scan)
            all_entries.sort(key=lambda item: item.get("ts", ""), reverse=True)

        filtered = []
        for e in all_entries:
            ts = e.get("ts", "")
            day = ts[:10] if len(ts) >= 10 else ""
            if date_from and day < date_from:
                continue
            if date_to and day > date_to:
                continue
            if user_filter and e.get("user_id", "") != user_filter:
                continue
            if type_filter and e.get("type", "") != type_filter:
                continue
            filtered.append(e)
        if valued_only:
            filtered = self._collapse_canceled_entries(filtered)
        return filtered

    def _load_booking_page(self, params):
        user_filter = (params.get("user_id", "") or "").strip()
        type_filter = (params.get("type", "") or "").strip()
        valued_only = (params.get("valued_only", "0") or "0").strip() == "1"
        date_from = self._normalize_day(params.get("from", ""))
        date_to = self._normalize_day(params.get("to", ""))
        try:
            months = int(params.get("months", "3") or "3")
        except Exception:
            months = 3
        if months < 1:
            months = 1
        if months > 24:
            months = 24

        try:
            page = int(params.get("page", "1") or "1")
        except Exception:
            page = 1
        try:
            per_page = int(params.get("per_page", "20") or "20")
        except Exception:
            per_page = 20
        if page < 1:
            page = 1
        if per_page < 10:
            per_page = 10
        if per_page > 30:
            per_page = 30

        start = (page - 1) * per_page
        need = per_page + 1  # +1 for has_next detection
        fetch_target = start + need + 40
        if fetch_target < 120:
            fetch_target = 120
        if fetch_target > 1200:
            fetch_target = 1200

        no_filters = (not user_filter) and (not type_filter) and (not date_from) and (not date_to)
        if no_filters:
            all_entries = ledger.tail_recent_entries(
                self.store.root,
                limit=fetch_target,
                max_files=min(3, months),
                max_bytes_per_file=24576,
            )
        else:
            all_entries = ledger.scan_recent_entries(
                self.store.root,
                months=months,
                max_entries=fetch_target,
            )
            all_entries.sort(key=lambda item: item.get("ts", ""), reverse=True)

        filtered = []
        for e in all_entries:
            ts = e.get("ts", "")
            day = ts[:10] if len(ts) >= 10 else ""
            if date_from and day < date_from:
                continue
            if date_to and day > date_to:
                continue
            if user_filter and e.get("user_id", "") != user_filter:
                continue
            if type_filter and e.get("type", "") != type_filter:
                continue
            filtered.append(e)

        if valued_only:
            filtered = self._collapse_canceled_entries(filtered)

        page_items = filtered[start:start + need]
        has_next = len(page_items) > per_page
        if has_next:
            page_items = page_items[:per_page]
        return page_items, has_next, page, per_page

    def _users_page(self):
        users = self.store.list_users()
        rows = []
        for u in users:
            uid = u.get("user_id")
            name = u.get("name", "")
            cards = ", ".join(u.get("cards", []))
            bal = self.store.get_balance(uid)
            rows.append(
                "<tr><td>{}</td><td>{}</td><td>{}</td><td>{} EUR</td></tr>".format(
                    uid, name, cards, _fmt_eur(bal)
                )
            )

        table = "<table><tr><th>ID</th><th>Name</th><th>Karten</th><th>Saldo</th></tr>{}</table>".format(
            "".join(rows)
        )

        options = []
        for u in users:
            uid = u.get("user_id", "")
            uname = u.get("name", uid)
            options.append("<option value='{}'>{} ({})</option>".format(uid, uname, uid))
        opts_html = "".join(options)

        forms = (
            "<h3>Umbenennen</h3>"
            "<form method='post' action='/user/rename'>"
            "<select name='user_id'>{}</select>"
            "<input name='name' placeholder='Neuer Name'>"
            "<button type='submit'>Speichern</button></form>"
            "<h3>Karte hinzufuegen</h3>"
            "<form method='post' action='/card/add'>"
            "<select name='user_id'>{}</select>"
            "<input name='uid' placeholder='UID HEX'>"
            "<button type='submit'>Hinzufuegen</button></form>"
            "<form method='post' action='/card/add/scan'>"
            "<select name='user_id'>{}</select>"
            "<button type='submit'>Karte scannen + hinzufuegen</button></form>"
            "<h3>Karte entfernen (global per UID)</h3>"
            "<form method='post' action='/card/remove-global'>"
            "<input name='uid' placeholder='UID HEX'>"
            "<button type='submit'>Entfernen</button></form>"
            "<form method='post' action='/card/remove-global/scan'>"
            "<button type='submit'>Karte scannen + entfernen</button></form>"
            "<h3>Nutzer loeschen</h3>"
            "<form method='post' action='/user/delete'>"
            "<select name='user_id'>{}</select>"
            "<input name='confirm_user_id' placeholder='user_id bestaetigen'>"
            "<button type='submit'>Nutzer loeschen</button></form>"
        ).format(opts_html, opts_html, opts_html, opts_html)

        return _html_page("Nutzer", self._admin_menu() + table + forms)

    def _deposit_page(self):
        options = []
        for u in self.store.list_users():
            options.append("<option value='{}'>{} ({})</option>".format(u.get("user_id"), u.get("name"), u.get("user_id")))

        form = (
            self._admin_menu()
            + "<form method='post' action='/deposit'>"
            + "<label>Nutzer</label><select name='user_id'>{}</select>".format("".join(options))
            + "<label>Betrag in EUR (z.B. 10,50)</label><input name='amount_eur' placeholder='10,50'>"
            + "<button type='submit'>Einzahlung buchen</button></form>"
        )
        return _html_page("Einzahlung", form)

    def _enroll_page(self, message=""):
        body = self._admin_menu()
        if message:
            body += "<p><b>{}</b></p>".format(message)
        body += (
            "<p>Optionaler Name. Danach Karte an den Leser halten.</p>"
            "<form method='post' action='/enroll/scan'>"
            "<label>Name (optional)</label><input name='name' placeholder='Max Mustermann'>"
            "<button type='submit'>Karte scannen und Nutzer anlegen</button></form>"
        )
        return _html_page("Nutzer anlegen", body)

    def _logs_page(self, params):
        cache_key = (
            (params.get("page", "1") or "1").strip(),
            (params.get("per_page", "20") or "20").strip(),
            (params.get("months", "3") or "3").strip(),
            (params.get("user_id", "") or "").strip(),
            (params.get("type", "") or "").strip(),
            (params.get("valued_only", "0") or "0").strip(),
            (params.get("from", "") or "").strip(),
            (params.get("to", "") or "").strip(),
        )
        cache_sig = self._bookings_files_signature()
        if self._logs_cache_html is not None and cache_key == self._logs_cache_key and cache_sig == self._logs_cache_sig:
            return self._logs_cache_html

        entries, has_next, page, per_page = self._load_booking_page(params)

        products_by_id = {}
        for p in self.store.get_products():
            products_by_id[p.get("id")] = p

        def map_type(t):
            if t == "purchase":
                return "Kauf"
            if t == "deposit":
                return "Einzahlung"
            if t == "undo":
                return "Storno"
            return t or "?"

        users_by_id = {}
        for u in self.store.list_users():
            users_by_id[u.get("user_id", "")] = u
        rows = []
        for e in entries:
            user_id = e.get("user_id", "")
            user = users_by_id.get(user_id)
            user_name = user.get("name", user_id) if user else user_id
            product_id = e.get("product_id", "")
            prod = products_by_id.get(product_id)
            product_name = prod.get("name", product_id) if prod else (product_id or "-")

            qty = int(e.get("qty", 0) or 0)
            amount = int(e.get("amount_cents", 0) or 0)
            price_cents = 0
            if qty > 0 and product_id:
                price_cents = abs(amount) // qty
            elif prod:
                price_cents = int(prod.get("price_cents", 0))

            bal_before = e.get("balance_before_cents")
            bal_after = e.get("balance_after_cents")
            bal_before_txt = _fmt_eur(bal_before) if bal_before is not None else "?"
            bal_after_txt = _fmt_eur(bal_after) if bal_after is not None else "?"

            rows.append(
                "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{} EUR</td><td>{} EUR</td><td>{} EUR</td><td>{}</td></tr>".format(
                    e.get("ts", ""),
                    map_type(e.get("type", "")),
                    user_name,
                    product_name,
                    _fmt_eur(price_cents),
                    bal_before_txt,
                    bal_after_txt,
                    (e.get("note", "") or "")[:40],
                )
            )

        users = self.store.list_users()
        user_options = ["<option value=''>alle</option>"]
        selected_user = (params.get("user_id", "") or "").strip()
        for u in users:
            uid = u.get("user_id", "")
            name = u.get("name", uid)
            sel = " selected" if uid == selected_user else ""
            user_options.append("<option value='{}'{}>{} ({})</option>".format(uid, sel, name, uid))
        selected_type = (params.get("type", "") or "").strip()
        valued_only = (params.get("valued_only", "0") or "0").strip() == "1"
        type_options = []
        for val, label in (("", "alle"), ("purchase", "Kauf"), ("deposit", "Einzahlung"), ("undo", "Storno")):
            sel = " selected" if val == selected_type else ""
            type_options.append("<option value='{}'{}>{}</option>".format(val, sel, label))

        months_val = (params.get("months", "3") or "3").strip()
        from_val = (params.get("from", "") or "").strip()
        to_val = (params.get("to", "") or "").strip()
        per_page_val = str(per_page)
        valued_checked = " checked" if valued_only else ""

        def q(base_page):
            return "/logs?page={}&per_page={}&months={}&user_id={}&type={}&valued_only={}&from={}&to={}".format(
                base_page, per_page, months_val, selected_user, selected_type, "1" if valued_only else "0", from_val, to_val
            )

        body = self._admin_menu()
        body += (
            "<form method='get' action='/logs'>"
            "<label>Nutzer</label><select name='user_id'>{}</select>"
            "<label>Typ</label><select name='type'>{}</select>"
            "<label><input type='checkbox' name='valued_only' value='1'{}> Nur gewertete Buchungen (stornierte Paare ausblenden)</label>"
            "<label>Monate rueckwirkend (1-24)</label><input name='months' value='{}'>"
            "<label>Von (YYYY-MM-DD)</label><input name='from' value='{}'>"
            "<label>Bis (YYYY-MM-DD)</label><input name='to' value='{}'>"
            "<label>Eintraege pro Seite</label><input name='per_page' value='{}'>"
            "<input type='hidden' name='page' value='1'>"
            "<button type='submit'>Filter anwenden</button></form>"
        ).format("".join(user_options), "".join(type_options), valued_checked, months_val, from_val, to_val, per_page_val)
        body += "<p><a href='/download/current.csv'>CSV Download aktuell</a></p>"
        body += "<p><a href='/download/readable.csv?months={}&user_id={}&type={}&valued_only={}&from={}&to={}'>CSV Download lesbar (Filter)</a></p>".format(
            months_val, selected_user, selected_type, "1" if valued_only else "0", from_val, to_val
        )
        body += "<p>Seite {} | Eintraege {}</p>".format(page, len(entries))
        if rows:
            body += "<table><tr><th>Uhrzeit</th><th>Buchungsart</th><th>Nutzer</th><th>Produkt</th><th>Produktpreis</th><th>Stand vorher</th><th>Stand nachher</th><th>Note</th></tr>{}</table>".format(
                "".join(rows)
            )
        else:
            body += "<p>(keine Log-Eintraege)</p>"
        nav = []
        if page > 1:
            nav.append("<a href='{}'>Zurueck</a>".format(q(page - 1)))
        if has_next:
            nav.append("<a href='{}'>Weiter</a>".format(q(page + 1)))
        if nav:
            body += "<p>{}</p>".format(" | ".join(nav))
        page_html = _html_page("Logs", body)
        self._logs_cache_key = cache_key
        self._logs_cache_sig = cache_sig
        self._logs_cache_html = page_html
        return page_html

    def _products_page(self):
        rows = []
        product_options = []
        default_id = self.store.default_product_id()
        for p in self.store.get_products():
            pid = p.get("id", "")
            pname = p.get("name", "")
            price = _fmt_eur(int(p.get("price_cents", 0)))
            bg = (p.get("bg_color", "") or "").strip()
            swatch = ""
            if bg:
                swatch = "<span style='display:inline-block;width:22px;height:14px;border:1px solid #999;background:{}'></span> {}".format(bg, bg)
            product_options.append("<option value='{}'>{} ({})</option>".format(pid, pname, pid))
            rows.append(
                "<tr><td>{}</td><td>{}</td><td>{} EUR</td><td>{}</td><td>{}</td></tr>".format(
                    pid,
                    pname,
                    price,
                    swatch,
                    "Ja" if pid == default_id else "",
                )
            )
        table = "<table><tr><th>ID</th><th>Name</th><th>Preis</th><th>Hintergrund</th><th>Default</th></tr>{}</table>".format("".join(rows))
        options_html = "".join(product_options)

        body = self._admin_menu()
        body += table
        body += (
            "<h3>Produkt anlegen</h3>"
            "<form method='post' action='/product/add'>"
            "<input name='product_id' placeholder='p004'>"
            "<input name='name' placeholder='Cappuccino'>"
            "<input name='price_eur' placeholder='1,80'>"
            "<label>Hintergrundfarbe</label><input type='color' name='bg_color' value='#5A5A5A'>"
            "<button type='submit'>Anlegen</button></form>"
            "<h3>Produkt aendern</h3>"
            "<form method='post' action='/product/update'>"
            "<select name='product_id'>{}</select>"
            "<input name='name' placeholder='Neuer Name'>"
            "<input name='price_eur' placeholder='1,20'>"
            "<label>Hintergrundfarbe</label><input type='color' name='bg_color' value='#5A5A5A'>"
            "<label><input type='checkbox' name='bg_color_clear' value='1'> Farbe entfernen</label>"
            "<button type='submit'>Aendern</button></form>"
            "<h3>Default-Produkt setzen</h3>"
            "<form method='post' action='/product/default'>"
            "<select name='product_id'>{}</select>"
            "<button type='submit'>Als Default setzen</button></form>"
            "<h3>Produkt loeschen</h3>"
            "<form method='post' action='/product/delete'>"
            "<select name='product_id'>{}</select>"
            "<button type='submit'>Loeschen</button></form>"
            "<h3>Expertenmodus: products.json ersetzen</h3>"
            "<form method='post' action='/products'>"
            "<textarea name='products_json' rows='10'>{}</textarea>"
            "<button type='submit'>JSON ersetzen</button></form>"
        ).format(options_html, options_html, options_html, json.dumps(self.store.products_cfg))
        return _html_page("Products", body)

    def _admins_page(self):
        rows = []
        for item in self.store.list_admins():
            cards = ", ".join(item.get("cards", []) or [])
            rows.append("<tr><td>{}</td><td>{}</td></tr>".format(item.get("username", ""), cards))
        body = self._admin_menu()
        body += "<table><tr><th>Admin Benutzer</th><th>RFID Karten</th></tr>{}</table>".format("".join(rows))
        options = []
        for item in self.store.list_admins():
            u = item.get("username", "")
            options.append("<option value='{}'>{}</option>".format(u, u))
        opts_html = "".join(options)
        body += (
            "<h3>Admin anlegen</h3>"
            "<form method='post' action='/admin/add'>"
            "<input name='username' placeholder='admin2'>"
            "<input name='password' type='password' placeholder='Neues Passwort'>"
            "<button type='submit'>Admin anlegen</button></form>"
            "<h3>Admin loeschen (mit Bestaetigung)</h3>"
            "<form method='post' action='/admin/delete'>"
            "<input name='username' placeholder='admin2'>"
            "<input name='confirm_username' placeholder='username wiederholen'>"
            "<button type='submit'>Admin loeschen</button></form>"
            "<h3>RFID Karte einem Admin zuordnen</h3>"
            "<form method='post' action='/admin/card/add'>"
            "<select name='username'>{}</select>"
            "<input name='uid' placeholder='UID HEX'>"
            "<button type='submit'>Karte zuordnen</button></form>"
            "<form method='post' action='/admin/card/add/scan'>"
            "<select name='username'>{}</select>"
            "<button type='submit'>Karte scannen + zuordnen</button></form>"
            "<h3>RFID Karte von Admin entfernen</h3>"
            "<form method='post' action='/admin/card/remove'>"
            "<input name='uid' placeholder='UID HEX'>"
            "<button type='submit'>Karte entfernen</button></form>"
            "<form method='post' action='/admin/card/remove/scan'>"
            "<button type='submit'>Karte scannen + entfernen</button></form>"
        ).format(opts_html, opts_html)
        return _html_page("Admins", body)

    def _password_page(self):
        body = self._admin_menu()
        body += (
            "<h3>Passwort aendern</h3>"
            "<form method='post' action='/password/change'>"
            "<input name='old_password' type='password' placeholder='Altes Passwort'>"
            "<input name='new_password' type='password' placeholder='Neues Passwort'>"
            "<input name='new_password2' type='password' placeholder='Neues Passwort wiederholen'>"
            "<button type='submit'>Passwort aktualisieren</button></form>"
        )
        return _html_page("Passwort", body)

    def _admin_actions_page(self):
        month_key = _month_key_now()
        path = "{}/logs/admin_actions_{}.csv".format(self.store.root, month_key)
        rows = []
        try:
            with open(path, "r") as f:
                for line in f:
                    raw = (line or "").strip()
                    if not raw or raw.startswith("ts;"):
                        continue
                    parts = raw.split(";")
                    if len(parts) < 5:
                        continue
                    rows.append("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                        parts[0], parts[1], parts[2], parts[3], ";".join(parts[4:])
                    ))
            rows = rows[-80:]
        except OSError:
            rows = []
        body = self._admin_menu()
        if rows:
            body += "<table><tr><th>Zeit</th><th>Admin</th><th>Aktion</th><th>Ziel</th><th>Detail</th></tr>{}</table>".format("".join(rows))
        else:
            body += "<p>(keine Eintraege)</p>"
        return _html_page("Aenderungslog", body)

    def _jingles_page(self, message=""):
        cfg = self.store.boot_jingle_config()
        lib = self.store.jingle_library()
        selected = cfg.get("selected", "te_deum")
        enabled = bool(cfg.get("enabled", True))
        options = []
        rows = []
        for name in sorted(lib.keys()):
            seq = lib.get(name, [])
            options.append("<option value='{}'{}>{}</option>".format(name, " selected" if name == selected else "", name))
            rows.append("<tr><td>{}</td><td>{}</td></tr>".format(name, len(seq)))
        body = self._admin_menu()
        if message:
            body += "<p><b>{}</b></p>".format(message)
        body += "<table><tr><th>Name</th><th>Noten</th></tr>{}</table>".format("".join(rows))
        body += (
            "<h3>Boot-Jingle</h3>"
            "<form method='post' action='/jingle/select'>"
            "<select name='name'>{}</select>"
            "<button type='submit'>Als Boot-Jingle waehlen</button></form>"
            "<form method='post' action='/jingle/toggle'>"
            "<input type='hidden' name='enabled' value='{}'>"
            "<button type='submit'>{}</button></form>"
            "<h3>Jingle anlegen/ersetzen</h3>"
            "<form method='post' action='/jingle/save'>"
            "<input name='name' placeholder='mein_jingle'>"
            "<textarea name='sequence' rows='4' placeholder='988:120,1109:120,0:40,1319:200'></textarea>"
            "<button type='submit'>Speichern</button></form>"
            "<h3>Jingle loeschen</h3>"
            "<form method='post' action='/jingle/delete'>"
            "<select name='name'>{}</select>"
            "<button type='submit'>Loeschen</button></form>"
        ).format(
            "".join(options),
            "0" if enabled else "1",
            "Boot-Jingle deaktivieren" if enabled else "Boot-Jingle aktivieren",
            "".join(options),
        )
        return _html_page("Jingles", body)

    def _handle_authed_post(self, actor, path, body):
        form = _parse_form(body)

        if path == "/user/rename":
            ok, msg = self.store.rename_user(form.get("user_id", ""), form.get("name", ""))
            if ok:
                self._append_admin_action(actor, "user_rename", form.get("user_id", ""), form.get("name", ""))
            return ok, msg, "/users"

        if path == "/user/delete":
            user_id = (form.get("user_id", "") or "").strip()
            confirm = (form.get("confirm_user_id", "") or "").strip()
            if not user_id or user_id != confirm:
                return False, "bestaetigung fehlt (user_id wiederholen)", "/users"
            ok, msg = self.store.delete_user(user_id)
            if ok:
                self._append_admin_action(actor, "user_delete", user_id, "confirmed")
            return ok, msg, "/users"

        if path == "/card/add":
            ok, msg = self.store.add_card_to_user(form.get("user_id", ""), form.get("uid", ""))
            if ok:
                self._append_admin_action(actor, "card_add", form.get("user_id", ""), form.get("uid", ""))
            return ok, msg, "/users"

        if path == "/card/add/scan":
            user_id = (form.get("user_id", "") or "").strip()
            if not self.store.user_by_id(user_id):
                return False, "user not found", "/users"
            uid_hex = self._scan_uid(timeout_ms=9000)
            if not uid_hex:
                return False, "keine Karte erkannt", "/users"
            ok, msg = self.store.add_card_to_user(user_id, uid_hex)
            if ok:
                self._append_admin_action(actor, "card_add_scan", user_id, uid_hex)
            return ok, msg, "/users"

        if path == "/card/remove":
            ok, msg = self.store.remove_card_from_user(form.get("user_id", ""), form.get("uid", ""))
            if ok:
                self._append_admin_action(actor, "card_remove", form.get("user_id", ""), form.get("uid", ""))
            return ok, msg, "/users"

        if path == "/card/remove-global":
            ok, msg, removed_from_user = self.store.remove_card_globally(form.get("uid", ""))
            if ok:
                self._append_admin_action(actor, "card_remove_global", removed_from_user or "", form.get("uid", ""))
            return ok, msg, "/users"

        if path == "/card/remove-global/scan":
            uid_hex = self._scan_uid(timeout_ms=9000)
            if not uid_hex:
                return False, "keine Karte erkannt", "/users"
            ok, msg, removed_from_user = self.store.remove_card_globally(uid_hex)
            if ok:
                self._append_admin_action(actor, "card_remove_global_scan", removed_from_user or "", uid_hex)
            return ok, msg, "/users"

        if path == "/deposit":
            user_id = form.get("user_id", "")
            if not self.store.user_by_id(user_id):
                return False, "user not found", "/deposit"
            try:
                amount_cents = _parse_eur_to_cents(form.get("amount_eur", "0"))
            except Exception:
                return False, "ungueltiger Betrag", "/deposit"

            if amount_cents <= 0:
                return False, "Betrag > 0", "/deposit"

            ts = "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(*time.localtime()[:6])
            balance_before = int(self.store.get_balance(user_id))
            balance_after = balance_before + int(amount_cents)
            entry = {
                "ts": ts,
                "type": "deposit",
                "user_id": user_id,
                "product_id": "",
                "qty": 1,
                "amount_cents": amount_cents,
                "balance_before_cents": balance_before,
                "balance_after_cents": balance_after,
                "note": "admin deposit by={}".format(actor),
            }

            self.store.apply_balance_delta(user_id, amount_cents)
            steps = self.store.build_ledger_steps(entry)
            if steps:
                self.logger.enqueue_steps(
                    steps + [self.store.save_balances],
                    description="admin_deposit",
                    fallback_ledger_entry=entry,
                )
            else:
                self.logger.enqueue_ledger(lambda: None, entry, self.store.sd_ready)
            self._append_admin_action(actor, "deposit", user_id, "amount_cents={}".format(amount_cents))
            return True, "ok", "/deposit"

        if path == "/product/add":
            try:
                cents = _parse_eur_to_cents(form.get("price_eur", "0"))
            except Exception:
                return False, "ungueltiger Preis", "/products"
            ok, msg = self.store.add_product(
                form.get("product_id", ""),
                form.get("name", ""),
                cents,
                form.get("bg_color", ""),
            )
            if ok:
                self._append_admin_action(
                    actor,
                    "product_add",
                    form.get("product_id", ""),
                    "{}|{}|{}".format(form.get("name", ""), cents, form.get("bg_color", "")),
                )
                self._confirm_beep()
            return ok, msg, "/products"

        if path == "/product/update":
            try:
                cents = _parse_eur_to_cents(form.get("price_eur", "0"))
            except Exception:
                return False, "ungueltiger Preis", "/products"
            bg_color = form.get("bg_color", "")
            if form.get("bg_color_clear", "") == "1":
                bg_color = ""
            ok, msg = self.store.update_product(
                form.get("product_id", ""),
                form.get("name", ""),
                cents,
                bg_color,
            )
            if ok:
                self._append_admin_action(
                    actor,
                    "product_update",
                    form.get("product_id", ""),
                    "{}|{}|{}".format(form.get("name", ""), cents, form.get("bg_color", "")),
                )
                self._confirm_beep()
            return ok, msg, "/products"

        if path == "/product/delete":
            ok, msg = self.store.delete_product(form.get("product_id", ""))
            if ok:
                self._append_admin_action(actor, "product_delete", form.get("product_id", ""), "")
                self._confirm_beep()
            return ok, msg, "/products"

        if path == "/product/default":
            pid = (form.get("product_id", "") or "").strip()
            if not self.store.get_product_by_id(pid):
                return False, "product not found", "/products"
            self.store.set_default_product(pid)
            self.store.save_products()
            self._append_admin_action(actor, "product_default", pid, "")
            self._confirm_beep()
            return True, "ok", "/products"

        if path == "/products":
            raw = form.get("products_json", "")
            try:
                parsed = json.loads(raw)
            except Exception:
                return False, "json parse error", "/products"

            ok, msg = self.store.replace_products_json(parsed)
            if ok:
                self._append_admin_action(actor, "products_replace_json", "", "len={}".format(len(raw)))
                self._confirm_beep()
            return ok, msg, "/products"

        if path == "/admin/add":
            username = (form.get("username", "") or "").strip()
            password = form.get("password", "") or ""
            if len(password) < 6:
                return False, "passwort zu kurz (>=6)", "/admins"
            ok, msg = self.store.add_admin(username, _sha256_hex(password))
            if ok:
                self._append_admin_action(actor, "admin_add", username, "")
            return ok, msg, "/admins"

        if path == "/admin/delete":
            username = (form.get("username", "") or "").strip()
            confirm = (form.get("confirm_username", "") or "").strip()
            if not username or username != confirm:
                return False, "bestaetigung fehlt (username wiederholen)", "/admins"
            ok, msg = self.store.delete_admin(username)
            if ok:
                self._append_admin_action(actor, "admin_delete", username, "")
            return ok, msg, "/admins"

        if path == "/admin/card/add":
            username = (form.get("username", "") or "").strip()
            uid_hex = (form.get("uid", "") or "").strip().upper()
            ok, msg = self.store.add_admin_card(username, uid_hex)
            if ok:
                self._append_admin_action(actor, "admin_card_add", username, uid_hex)
            return ok, msg, "/admins"

        if path == "/admin/card/add/scan":
            username = (form.get("username", "") or "").strip()
            if not username:
                return False, "username required", "/admins"
            uid_hex = self._scan_uid(timeout_ms=9000)
            if not uid_hex:
                return False, "keine Karte erkannt", "/admins"
            ok, msg = self.store.add_admin_card(username, uid_hex)
            if ok:
                self._append_admin_action(actor, "admin_card_add_scan", username, uid_hex)
            return ok, msg, "/admins"

        if path == "/admin/card/remove":
            uid_hex = (form.get("uid", "") or "").strip().upper()
            ok, msg, removed_from = self.store.remove_admin_card(uid_hex)
            if ok:
                self._append_admin_action(actor, "admin_card_remove", removed_from or "", uid_hex)
            return ok, msg, "/admins"

        if path == "/admin/card/remove/scan":
            uid_hex = self._scan_uid(timeout_ms=9000)
            if not uid_hex:
                return False, "keine Karte erkannt", "/admins"
            ok, msg, removed_from = self.store.remove_admin_card(uid_hex)
            if ok:
                self._append_admin_action(actor, "admin_card_remove_scan", removed_from or "", uid_hex)
            return ok, msg, "/admins"

        if path == "/password/change":
            old_password = form.get("old_password", "") or ""
            new_password = form.get("new_password", "") or ""
            new_password2 = form.get("new_password2", "") or ""
            if new_password != new_password2:
                return False, "neues passwort stimmt nicht ueberein", "/password"
            if len(new_password) < 6:
                return False, "neues passwort zu kurz (>=6)", "/password"
            if not self.store.verify_admin_hash(actor, _sha256_hex(old_password)):
                return False, "altes passwort falsch", "/password"
            ok, msg = self.store.set_admin_password(actor, _sha256_hex(new_password))
            if ok:
                self._append_admin_action(actor, "password_change", actor, "")
            return ok, msg, "/password"

        if path == "/time/set":
            dt = self._parse_datetime_local(form.get("dt_local", ""))
            if dt is None:
                return False, "ungueltiges Datum/Uhrzeit", "/time"
            if not self._init_rtc_reader() or not self.rtc or not self.rtc.available():
                return False, "rtc nicht verfuegbar", "/time"
            ok = self.rtc.set_datetime(dt[0], dt[1], dt[2], dt[3], dt[4], dt[5], dt[6])
            if not ok:
                return False, "rtc set fehlgeschlagen", "/time"
            self._append_admin_action(actor, "time_set_manual", "", "{}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(
                dt[0], dt[1], dt[2], dt[4], dt[5], dt[6]
            ))
            return True, "ok", "/time"

        if path == "/time/sync-browser":
            dt = self._parse_datetime_local(form.get("browser_dt", ""))
            if dt is None:
                return False, "browserzeit fehlt/ungueltig", "/time"
            if not self._init_rtc_reader() or not self.rtc or not self.rtc.available():
                return False, "rtc nicht verfuegbar", "/time"
            ok = self.rtc.set_datetime(dt[0], dt[1], dt[2], dt[3], dt[4], dt[5], dt[6])
            if not ok:
                return False, "rtc sync fehlgeschlagen", "/time"
            self._append_admin_action(actor, "time_sync_browser", "", "{}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(
                dt[0], dt[1], dt[2], dt[4], dt[5], dt[6]
            ))
            return True, "ok", "/time"

        if path == "/jingle/select":
            name = (form.get("name", "") or "").strip()
            ok, msg = self.store.set_boot_jingle_selected(name)
            if ok:
                self._append_admin_action(actor, "jingle_select", "", name)
            return ok, msg, "/jingles"

        if path == "/jingle/toggle":
            enabled = (form.get("enabled", "1") or "1").strip() == "1"
            ok, msg = self.store.set_boot_jingle_enabled(enabled)
            if ok:
                self._append_admin_action(actor, "jingle_toggle", "", "enabled={}".format(1 if enabled else 0))
            return ok, msg, "/jingles"

        if path == "/jingle/save":
            name = (form.get("name", "") or "").strip()
            seq = _parse_jingle_sequence(form.get("sequence", ""))
            if not seq:
                return False, "ungueltige Sequenz", "/jingles"
            ok, msg = self.store.upsert_jingle(name, seq)
            if ok:
                self._append_admin_action(actor, "jingle_save", "", name)
            return ok, msg, "/jingles"

        if path == "/jingle/delete":
            name = (form.get("name", "") or "").strip()
            ok, msg = self.store.delete_jingle(name)
            if ok:
                self._append_admin_action(actor, "jingle_delete", "", name)
            return ok, msg, "/jingles"

        if path == "/enroll/scan":
            requested_name = (form.get("name", "") or "").strip()
            uid_hex = self._scan_uid(timeout_ms=9000)
            if not uid_hex:
                return False, "keine Karte erkannt", "/enroll"

            existing = self.store.user_by_uid(uid_hex)
            if existing:
                return False, "Karte bereits zugeordnet: {}".format(existing.get("name", existing.get("user_id", "?"))), "/enroll"

            user, _created = self.store.ensure_user_for_uid(uid_hex)
            if requested_name:
                self.store.rename_user(user.get("user_id"), requested_name)
                user = self.store.user_by_id(user.get("user_id"))
            self._append_admin_action(actor, "user_enroll_card", user.get("user_id", ""), uid_hex)
            return True, "angelegt: {} / UID {}".format(user.get("name"), uid_hex), "/enroll"

        if path == "/sync/sd":
            ok, copied, failed = self.store.sync_internal_to_sd()
            if ok:
                self._append_admin_action(
                    actor,
                    "sync_internal_to_sd",
                    "",
                    "copied={} failed={}".format(copied, failed),
                )
                self._confirm_beep()
                return True, "sync ok copied={} failed={}".format(copied, failed), "/"
            return False, "SD sync fehlgeschlagen", "/"

        if path == "/balances/rebuild":
            ok, user_count = self.store.rebuild_balances_from_ledger(months=None)
            if ok:
                self._append_admin_action(
                    actor,
                    "balances_rebuild",
                    "",
                    "users={}".format(user_count),
                )
                self._confirm_beep()
                return True, "balances neu berechnet ({} Nutzer)".format(user_count), "/"
            return False, "balances konnten nicht gespeichert werden", "/"

        if path == "/printer/test":
            if not self.printer:
                return False, "printer service nicht verfuegbar", "/printer"
            self.printer.enqueue_test_page()
            self._append_admin_action(actor, "printer_test", "", "")
            return True, "Druckjob angelegt", "/printer"

        if path == "/printer/ranking-week":
            if not self.printer:
                return False, "printer service nicht verfuegbar", "/printer"
            self.printer.enqueue_ranking("week")
            self._append_admin_action(actor, "printer_ranking_week", "", "")
            return True, "Wochenranking Druckjob angelegt", "/printer"

        if path == "/printer/ranking-month":
            if not self.printer:
                return False, "printer service nicht verfuegbar", "/printer"
            self.printer.enqueue_ranking("month")
            self._append_admin_action(actor, "printer_ranking_month", "", "")
            return True, "Monatsranking Druckjob angelegt", "/printer"

        return False, "unknown action", "/"

    def _handle_http(self, conn, addr):
        req = self._read_http_req(conn)
        if req is None:
            return
        method, path_raw, headers, body = req

        path, _query = _parse_query(path_raw)
        user = self._session_user(headers)

        captive_paths = (
            "/generate_204",
            "/hotspot-detect.html",
            "/ncsi.txt",
            "/connecttest.txt",
            "/redirect",
            "/fwlink",
            "/canonical.html",
        )

        if path in captive_paths:
            self._redirect(conn, "http://{}/".format(self.ap_ip))
            return

        if path == "/login" and method == "POST":
            form = _parse_form(body)
            username = form.get("username", "")
            password = form.get("password", "")
            if self.store.verify_admin_hash(username, _sha256_hex(password)):
                token = self._create_session(username)
                self._append_admin_action(username, "login", "", "")
                self._send(conn, "302 Found", b"", headers={"Location": "/"}, cookie="session={}; Path=/; HttpOnly".format(token))
            else:
                page = _html_page("Login", "<p>Login fehlgeschlagen</p>" + self._login_form())
                self._send(conn, "200 OK", page)
            return

        if path == "/login/rfid" and method == "POST":
            uid_hex = self._scan_uid(timeout_ms=9000)
            if not uid_hex:
                page = _html_page("Login", "<p>Keine Karte erkannt</p>" + self._login_form())
                self._send(conn, "200 OK", page)
                return
            username = self.store.admin_by_card(uid_hex)
            if username:
                token = self._create_session(username)
                self._append_admin_action(username, "login_rfid", "", uid_hex)
                self._send(conn, "302 Found", b"", headers={"Location": "/"}, cookie="session={}; Path=/; HttpOnly".format(token))
            else:
                page = _html_page("Login", "<p>Karte ist keinem Admin zugeordnet</p>" + self._login_form())
                self._send(conn, "200 OK", page)
            return

        if path == "/logout":
            token = _get_cookie(headers, "session")
            user_for_log = self.sessions.get(token, {}).get("username", "") if token else ""
            if token:
                self.sessions.pop(token, None)
            if user_for_log:
                self._append_admin_action(user_for_log, "logout", "", "")
            self._send(conn, "302 Found", b"", headers={"Location": "/"}, cookie="session=deleted; Path=/; Max-Age=0")
            return

        if not user:
            page = _html_page("Login", self._login_form())
            self._send(conn, "200 OK", page)
            return

        if path == "/" and method == "GET":
            self._send(conn, "200 OK", self._dashboard())
            return

        if path == "/users" and method == "GET":
            self._send(conn, "200 OK", self._users_page())
            return

        if path == "/deposit" and method == "GET":
            self._send(conn, "200 OK", self._deposit_page())
            return

        if path == "/enroll" and method == "GET":
            self._send(conn, "200 OK", self._enroll_page())
            return

        if path == "/logs" and method == "GET":
            try:
                self._send(conn, "200 OK", self._logs_page(_query))
            except Exception as exc:
                page = _html_page("Logs Fehler", self._admin_menu() + "<p>Logs konnten nicht geladen werden: {}</p>".format(exc))
                self._send(conn, "200 OK", page)
            return

        if path == "/products" and method == "GET":
            self._send(conn, "200 OK", self._products_page())
            return

        if path == "/admins" and method == "GET":
            self._send(conn, "200 OK", self._admins_page())
            return

        if path == "/password" and method == "GET":
            self._send(conn, "200 OK", self._password_page())
            return

        if path == "/time" and method == "GET":
            self._send(conn, "200 OK", self._rtc_time_page())
            return

        if path == "/jingles" and method == "GET":
            self._send(conn, "200 OK", self._jingles_page())
            return

        if path == "/printer" and method == "GET":
            self._send(conn, "200 OK", self._printer_page())
            return

        if path == "/admin-actions" and method == "GET":
            self._send(conn, "200 OK", self._admin_actions_page())
            return

        if path == "/download/current.csv" and method == "GET":
            month_key = _month_key_now()
            file_path = "{}/logs/bookings_{}.csv".format(self.store.root, month_key)
            try:
                with open(file_path, "rb") as f:
                    data = f.read()
                self._send(
                    conn,
                    "200 OK",
                    data,
                    headers={
                        "Content-Type": "text/csv",
                        "Content-Disposition": "attachment; filename='bookings_{}.csv'".format(month_key),
                    },
                )
            except OSError:
                self._send(conn, "404 Not Found", "CSV nicht gefunden")
            return

        if path == "/download/readable.csv" and method == "GET":
            try:
                entries = self._load_booking_entries(_query)
            except Exception:
                entries = []
            products_by_id = {}
            for p in self.store.get_products():
                products_by_id[p.get("id")] = p
            lines = ["ts;type;username;product_name;product_price_eur;balance_before_eur;balance_after_eur;note"]
            for e in entries:
                user_id = e.get("user_id", "")
                user = self.store.user_by_id(user_id)
                user_name = user.get("name", user_id) if user else user_id
                product_id = e.get("product_id", "")
                prod = products_by_id.get(product_id)
                product_name = prod.get("name", product_id) if prod else (product_id or "-")
                qty = int(e.get("qty", 0) or 0)
                amount = int(e.get("amount_cents", 0) or 0)
                if qty > 0 and product_id:
                    product_price = abs(amount) // qty
                elif prod:
                    product_price = int(prod.get("price_cents", 0))
                else:
                    product_price = 0
                bal_before = e.get("balance_before_cents")
                bal_after = e.get("balance_after_cents")
                lines.append(
                    "{};{};{};{};{};{};{};{}".format(
                        e.get("ts", ""),
                        e.get("type", ""),
                        user_name.replace(";", ","),
                        product_name.replace(";", ","),
                        _fmt_eur(product_price),
                        _fmt_eur(bal_before) if bal_before is not None else "?",
                        _fmt_eur(bal_after) if bal_after is not None else "?",
                        (e.get("note", "") or "").replace(";", ","),
                    )
                )
            data = ("\n".join(lines) + "\n").encode()
            self._send(
                conn,
                "200 OK",
                data,
                headers={
                    "Content-Type": "text/csv",
                    "Content-Disposition": "attachment; filename='bookings_readable.csv'",
                },
            )
            return

        if method == "POST":
            ok, msg, redirect_to = self._handle_authed_post(user, path, body)
            if ok:
                if redirect_to == "/enroll":
                    self._send(conn, "200 OK", self._enroll_page(message=msg))
                elif redirect_to == "/time":
                    self._send(conn, "200 OK", self._rtc_time_page(message="Zeit aktualisiert"))
                elif redirect_to == "/jingles":
                    self._send(conn, "200 OK", self._jingles_page(message="Gespeichert"))
                elif redirect_to == "/printer":
                    self._send(conn, "200 OK", self._printer_page(message=msg))
                else:
                    self._send(conn, "302 Found", b"", headers={"Location": redirect_to})
            else:
                if redirect_to == "/enroll":
                    page = self._enroll_page(message=msg)
                elif redirect_to == "/time":
                    page = self._rtc_time_page(message=msg)
                elif redirect_to == "/jingles":
                    page = self._jingles_page(message=msg)
                elif redirect_to == "/printer":
                    page = self._printer_page(message=msg)
                else:
                    page = _html_page("Fehler", self._admin_menu() + "<p>{}</p>".format(msg))
                self._send(conn, "200 OK", page)
            return

        self._redirect(conn, "/")

    def _login_form(self):
        return (
            "<form method='post' action='/login'>"
            "<label>Benutzer</label><input name='username'>"
            "<label>Passwort</label><input name='password' type='password'>"
            "<button type='submit'>Login</button></form>"
            "<form method='post' action='/login/rfid'>"
            "<button type='submit'>Alternativ: Login per RFID Karte</button></form>"
        )

    def run_forever(self):
        self._configure_ap()
        self._start_dns()
        self._start_http()

        if self.rgb:
            try:
                self.rgb.set_named("admin")
            except Exception:
                pass
        if self.buzzer:
            try:
                self.buzzer.play([(1760, 40), (0, 30), (2093, 60)])
            except Exception:
                pass
        self._lcd_write_lines(
            "Admin AP aktiv",
            "SSID: {}".format(self.store.ap_config().get("ssid", ""))[:20],
            "IP: {} {}".format(self.ap_ip, (self.store.ap_config().get("mode", "open") or "open")[:5])[:20],
            "Portal: / Login",
        )

        self._dbg("Admin portal running on", self.ap_ip)
        while True:
            self.logger.tick()
            if self.printer:
                self.printer.tick()
            if self.rgb and pins.ADMIN_AP_BLUE_BLINK:
                now = time.ticks_ms()
                if time.ticks_diff(now, self._last_blink_ms) >= pins.ADMIN_AP_BLUE_BLINK_MS:
                    self._blink_on = not self._blink_on
                    self.rgb.set_named("admin" if self._blink_on else "off")
                    self._last_blink_ms = now
            # DNS handling (non-blocking)
            try:
                data, addr = self.dns_sock.recvfrom(512)
                if data:
                    self.dns_sock.sendto(self._build_dns_resp(data), addr)
            except Exception:
                pass

            # HTTP handling (non-blocking)
            conn = None
            try:
                conn, addr = self.http_sock.accept()
                conn.settimeout(2)
                self._handle_http(conn, addr)
            except Exception:
                pass
            finally:
                try:
                    if conn is not None:
                        conn.close()
                except Exception:
                    pass

            # Debug station status every 2s
            try:
                now = time.ticks_ms()
                if time.ticks_diff(now, self._last_station_dump_ms) >= 2000:
                    try:
                        st = self.ap.status("stations")
                    except Exception:
                        st = None
                    self._dbg("stations:", st)
                    self._last_station_dump_ms = now
            except Exception:
                pass

            time.sleep_ms(20)
