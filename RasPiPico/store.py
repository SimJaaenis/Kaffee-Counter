import os

try:
    import ujson as json
except Exception:
    import json

import ledger
import config_pins as pins
from drivers.sd_spi import SDSpi


DEFAULT_PRODUCTS = {
    "default_product_id": "p001",
    "products": [
        {"id": "p001", "name": "Kaffee", "price_cents": 120, "bg_color": "#5A5A5A"},
        {"id": "p002", "name": "Espresso", "price_cents": 100, "bg_color": "#8C5A2B"},
        {"id": "p003", "name": "Milch", "price_cents": 40, "bg_color": "#2F6A9A"},
    ],
}

DEFAULT_USERS = {
    "next_user_num": 1,
    "unknown_name_template": "Nutzer {n}",
    "users": [],
}

DEFAULT_DEVICE = {
    "ap": {
        "ssid": "KaffeeCounter-Admin",
        "mode": "open",
        "hidden": True,
        "wpa2_password": "KaffeeAdmin42",
        "ip": "192.168.4.1",
    },
    "display": {
        "outside_schedule_off": True,
        "active_windows": [
            {"days": [0, 1, 2, 3, 4], "start": "06:00", "end": "20:00"}
        ],
        "outside_wake_s": 120,
        "idle_dim_after_s": 90,
        "normal_brightness": 255,
        "dim_brightness": 50,
        "sleep_brightness": 10,
    },
    "admin": {
        "username": "admin",
        "password_sha256_hex": "240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9",
    },
    "admins": [
        {
            "username": "admin",
            "password_sha256_hex": "240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9",
            "cards": [],
        }
    ],
    "rgb": {
        "invert": False,
    },
    "boot_jingle": {
        "enabled": True,
        "selected": "te_deum",
    },
    "jingles": {
        "te_deum": [
            [988, 110],
            [1109, 110],
            [1175, 140],
            [1319, 220],
            [0, 60],
            [1319, 120],
            [1175, 120],
            [1109, 120],
            [988, 200]
        ]
    },
    "printer": {
        "enabled": True,
        "uart_id": 1,
        "tx_pin": 8,
        "rx_pin": 9,
        "baudrate": 9600,
        "timeout_ms": 100,
        "receipt_per_booking": False,
    },
}

DEFAULT_BALANCES = {}


def _clone(obj):
    try:
        return json.loads(json.dumps(obj))
    except Exception:
        return obj


class Store:
    def __init__(self, root="/data", sd_ready=False, sd_root="/sd"):
        self.root = root
        self.sd_root = sd_root
        self.sd_ready = bool(sd_ready)

        self.config_dir = "{}/config".format(root)
        self.logs_dir = "{}/logs".format(root)
        self.backup_dir = "{}/backup".format(root)

        self.products_path = "{}/products.json".format(self.config_dir)
        self.users_path = "{}/users.json".format(self.config_dir)
        self.device_path = "{}/device.json".format(self.config_dir)
        self.balances_path = "{}/balances.json".format(self.config_dir)

        self.products_cfg = None
        self.users_cfg = None
        self.device_cfg = None
        self.balances = None

    def ensure_layout(self):
        for p in (self.config_dir, self.logs_dir, self.backup_dir):
            try:
                os.mkdir(p)
            except OSError:
                pass

    def ensure_sd_layout(self):
        if not self.sd_ready:
            return
        for p in (
            "{}/config".format(self.sd_root),
            "{}/logs".format(self.sd_root),
            "{}/backup".format(self.sd_root),
        ):
            try:
                os.mkdir(p)
            except OSError:
                pass

    def _read_json(self, path, default_value):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return default_value

    def _copy_file(self, src, dst):
        with open(src, "rb") as rf:
            with open(dst, "wb") as wf:
                while True:
                    chunk = rf.read(1024)
                    if not chunk:
                        break
                    wf.write(chunk)

    def atomic_write_json(self, path, data):
        tmp = path + ".tmp"
        backup = "{}/{}.bak".format(self.backup_dir, path.rsplit("/", 1)[-1])

        try:
            with open(tmp, "w") as f:
                json.dump(data, f)
                f.flush()

            try:
                self._copy_file(path, backup)
            except Exception:
                pass

            try:
                os.remove(path)
            except OSError:
                pass
            os.rename(tmp, path)
            return True
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False

    @staticmethod
    def _ensure_dir(path):
        try:
            os.mkdir(path)
        except OSError:
            pass

    @staticmethod
    def _iter_file_paths(root):
        stack = [root]
        out = []
        while stack:
            cur = stack.pop()
            try:
                names = os.listdir(cur)
            except OSError:
                continue
            for name in names:
                p = "{}/{}".format(cur, name)
                try:
                    st = os.stat(p)
                    mode = st[0]
                except Exception:
                    continue
                # dir bit for MicroPython/Unix-style mode
                if mode & 0x4000:
                    stack.append(p)
                else:
                    out.append(p)
        return out

    @staticmethod
    def _copy_file_safe(src, dst):
        try:
            parent = dst.rsplit("/", 1)[0]
            Store._ensure_dir(parent)
            with open(src, "rb") as rf:
                with open(dst, "wb") as wf:
                    while True:
                        chunk = rf.read(1024)
                        if not chunk:
                            break
                        wf.write(chunk)
            return True
        except Exception:
            return False

    def _sync_root(self, src_root, dst_root):
        copied = 0
        failed = 0
        for rel in ("config", "logs", "backup"):
            src_dir = "{}/{}".format(src_root, rel)
            dst_dir = "{}/{}".format(dst_root, rel)
            self._ensure_dir(dst_root)
            self._ensure_dir(dst_dir)
            paths = self._iter_file_paths(src_dir)
            for src in paths:
                suffix = src[len(src_dir):]
                dst = "{}{}".format(dst_dir, suffix)
                if self._copy_file_safe(src, dst):
                    copied += 1
                else:
                    failed += 1
        return copied, failed

    def ensure_sd_available(self):
        # Fast path: already mounted.
        try:
            os.listdir(self.sd_root)
            self.sd_ready = True
            return True
        except Exception:
            pass

        # Try runtime mount (supports hot-plug after boot).
        try:
            sd = SDSpi(
                pins.SD_SPI_ID,
                pins.SD_SCK_PIN,
                pins.SD_MOSI_PIN,
                pins.SD_MISO_PIN,
                pins.SD_CS_PIN,
                init_baud=pins.SD_INIT_BAUD,
                max_baud=pins.SD_MAX_BAUD,
            )
            sd.mount(self.sd_root)
            sd.ensure_dirs(
                [
                    "{}/config".format(self.sd_root),
                    "{}/logs".format(self.sd_root),
                    "{}/backup".format(self.sd_root),
                ]
            )
            self.sd_ready = True
            return True
        except Exception:
            self.sd_ready = False
            return False

    def _sync_root_sections(self, src_root, dst_root, sections):
        copied = 0
        failed = 0
        for rel in sections:
            src_dir = "{}/{}".format(src_root, rel)
            dst_dir = "{}/{}".format(dst_root, rel)
            self._ensure_dir(dst_root)
            self._ensure_dir(dst_dir)
            paths = self._iter_file_paths(src_dir)
            for src in paths:
                suffix = src[len(src_dir):]
                dst = "{}{}".format(dst_dir, suffix)
                if self._copy_file_safe(src, dst):
                    copied += 1
                else:
                    failed += 1
        return copied, failed

    def sync_sd_to_internal(self):
        if not self.ensure_sd_available():
            return False, 0, 0
        self.ensure_sd_layout()
        self.ensure_layout()
        # At boot, only config should override internal state.
        copied, failed = self._sync_root_sections(self.sd_root, self.root, ("config",))
        return True, copied, failed

    def sync_internal_to_sd(self):
        if not self.ensure_sd_available():
            return False, 0, 0
        self.ensure_sd_layout()
        self.ensure_layout()
        copied, failed = self._sync_root(self.root, self.sd_root)
        return True, copied, failed

    def load_all(self):
        self.ensure_layout()

        self.products_cfg = self._read_json(self.products_path, None)
        if not isinstance(self.products_cfg, dict) or "products" not in self.products_cfg:
            self.products_cfg = _clone(DEFAULT_PRODUCTS)
            self.atomic_write_json(self.products_path, self.products_cfg)

        self.users_cfg = self._read_json(self.users_path, None)
        if not isinstance(self.users_cfg, dict) or "users" not in self.users_cfg:
            self.users_cfg = _clone(DEFAULT_USERS)
            self.atomic_write_json(self.users_path, self.users_cfg)

        self.device_cfg = self._read_json(self.device_path, None)
        if not isinstance(self.device_cfg, dict):
            self.device_cfg = _clone(DEFAULT_DEVICE)
            self.atomic_write_json(self.device_path, self.device_cfg)

        balances_loaded = self._read_json(self.balances_path, None)
        if isinstance(balances_loaded, dict):
            self.balances = balances_loaded
        else:
            self.balances = dict(DEFAULT_BALANCES)
            rebuilt = ledger.rebuild_balances_recent(self.root, months=3)
            self.balances = rebuilt
            self.atomic_write_json(self.balances_path, self.balances)

    def save_products(self):
        return self.atomic_write_json(self.products_path, self.products_cfg)

    def save_users(self):
        return self.atomic_write_json(self.users_path, self.users_cfg)

    def save_device(self):
        return self.atomic_write_json(self.device_path, self.device_cfg)

    def save_balances(self):
        return self.atomic_write_json(self.balances_path, self.balances)

    def rebuild_balances_from_ledger(self, months=None):
        # months=None => all available booking files.
        rebuilt = ledger.rebuild_balances_recent(self.root, months=months)
        self.balances = rebuilt if isinstance(rebuilt, dict) else {}
        ok = self.save_balances()
        if not ok:
            return False, 0
        return True, len(self.balances)

    def get_products(self):
        return self.products_cfg.get("products", [])

    def get_product_by_id(self, product_id):
        for p in self.get_products():
            if p.get("id") == product_id:
                return p
        return None

    def default_product_id(self):
        return self.products_cfg.get("default_product_id")

    def set_default_product(self, product_id):
        self.products_cfg["default_product_id"] = product_id

    def product_index_by_id(self, product_id):
        products = self.get_products()
        for idx, p in enumerate(products):
            if p.get("id") == product_id:
                return idx
        return 0

    def user_by_id(self, user_id):
        for user in self.users_cfg.get("users", []):
            if user.get("user_id") == user_id:
                return user
        return None

    def user_by_uid(self, uid_hex):
        uid_hex = (uid_hex or "").upper()
        for user in self.users_cfg.get("users", []):
            for c in user.get("cards", []):
                if (c or "").upper() == uid_hex:
                    return user
        return None

    def _is_uid_taken(self, uid_hex, except_user_id=None):
        uid_hex = (uid_hex or "").upper()
        for user in self.users_cfg.get("users", []):
            if except_user_id and user.get("user_id") == except_user_id:
                continue
            for c in user.get("cards", []):
                if (c or "").upper() == uid_hex:
                    return True
        return False

    def ensure_user_for_uid(self, uid_hex, persist=True):
        uid_hex = (uid_hex or "").upper()
        found = self.user_by_uid(uid_hex)
        if found:
            return found, False

        n = int(self.users_cfg.get("next_user_num", 1))
        template = self.users_cfg.get("unknown_name_template", "Nutzer {n}")
        user = {
            "user_id": "u{:03d}".format(n),
            "name": template.replace("{n}", str(n)),
            "cards": [uid_hex],
        }
        self.users_cfg.setdefault("users", []).append(user)
        self.users_cfg["next_user_num"] = n + 1
        self.balances.setdefault(user["user_id"], 0)

        # Immediate persistence for auto provisioning.
        if persist:
            self.save_users()
            self.save_balances()

        return user, True

    def rename_user(self, user_id, new_name):
        user = self.user_by_id(user_id)
        if not user:
            return False, "user not found"
        user["name"] = (new_name or "").strip()[:48] or user["name"]
        self.save_users()
        return True, "ok"

    def delete_user(self, user_id):
        users = self.users_cfg.get("users", [])
        idx = -1
        for i, user in enumerate(users):
            if user.get("user_id") == user_id:
                idx = i
                break
        if idx < 0:
            return False, "user not found"
        users.pop(idx)
        if user_id in self.balances:
            try:
                del self.balances[user_id]
            except Exception:
                pass
        self.save_users()
        self.save_balances()
        return True, "ok"

    def add_card_to_user(self, user_id, uid_hex):
        uid_hex = (uid_hex or "").upper()
        user = self.user_by_id(user_id)
        if not user:
            return False, "user not found"
        if self._is_uid_taken(uid_hex, except_user_id=user_id):
            return False, "uid already assigned"

        cards = user.setdefault("cards", [])
        if uid_hex not in [c.upper() for c in cards]:
            cards.append(uid_hex)
            self.save_users()
        return True, "ok"

    def remove_card_from_user(self, user_id, uid_hex):
        uid_hex = (uid_hex or "").upper()
        user = self.user_by_id(user_id)
        if not user:
            return False, "user not found"

        cards = user.setdefault("cards", [])
        new_cards = [c for c in cards if (c or "").upper() != uid_hex]
        user["cards"] = new_cards
        self.save_users()
        return True, "ok"

    def remove_card_globally(self, uid_hex):
        uid_hex = (uid_hex or "").upper()
        if not uid_hex:
            return False, "uid required", None
        for user in self.users_cfg.get("users", []):
            cards = user.setdefault("cards", [])
            new_cards = [c for c in cards if (c or "").upper() != uid_hex]
            if len(new_cards) != len(cards):
                user["cards"] = new_cards
                self.save_users()
                return True, "ok", user.get("user_id")
        return False, "uid not found", None

    def get_balance(self, user_id):
        return int(self.balances.get(user_id, 0))

    def apply_balance_delta(self, user_id, delta_cents):
        self.balances[user_id] = int(self.balances.get(user_id, 0)) + int(delta_cents)

    def list_users(self):
        return list(self.users_cfg.get("users", []))

    def replace_products_json(self, parsed_json):
        if not isinstance(parsed_json, dict):
            return False, "invalid root"
        if "default_product_id" not in parsed_json or "products" not in parsed_json:
            return False, "missing keys"
        if not isinstance(parsed_json.get("products"), list) or not parsed_json.get("products"):
            return False, "products invalid"

        ids = set()
        for p in parsed_json.get("products", []):
            if not isinstance(p, dict):
                return False, "product entry invalid"
            pid = p.get("id")
            if not pid or pid in ids:
                return False, "duplicate product id"
            color = p.get("bg_color", "")
            if color and not self._normalize_hex_color(color):
                return False, "invalid bg_color for {}".format(pid)
            if color:
                p["bg_color"] = self._normalize_hex_color(color)
            ids.add(pid)

        if parsed_json.get("default_product_id") not in ids:
            return False, "default product missing"

        self.products_cfg = parsed_json
        self.save_products()
        return True, "ok"

    @staticmethod
    def _normalize_hex_color(value):
        v = (value or "").strip()
        if len(v) != 7 or not v.startswith("#"):
            return None
        hx = v[1:]
        for ch in hx:
            ok = ("0" <= ch <= "9") or ("a" <= ch.lower() <= "f")
            if not ok:
                return None
        return "#" + hx.upper()

    def add_product(self, product_id, name, price_cents, bg_color=""):
        pid = (product_id or "").strip()
        pname = (name or "").strip()
        if not pid:
            return False, "product id required"
        if not pname:
            return False, "name required"
        try:
            price_cents = int(price_cents)
        except Exception:
            return False, "invalid price"
        if price_cents < 0:
            return False, "price must be >= 0"
        color = self._normalize_hex_color(bg_color) if bg_color else None
        if bg_color and not color:
            return False, "invalid bg_color"
        if self.get_product_by_id(pid):
            return False, "product id exists"
        entry = {"id": pid, "name": pname[:24], "price_cents": price_cents}
        if color:
            entry["bg_color"] = color
        self.products_cfg.setdefault("products", []).append(entry)
        if not self.products_cfg.get("default_product_id"):
            self.products_cfg["default_product_id"] = pid
        self.save_products()
        return True, "ok"

    def update_product(self, product_id, name, price_cents, bg_color=""):
        p = self.get_product_by_id(product_id)
        if not p:
            return False, "product not found"
        pname = (name or "").strip()
        if not pname:
            return False, "name required"
        try:
            price_cents = int(price_cents)
        except Exception:
            return False, "invalid price"
        if price_cents < 0:
            return False, "price must be >= 0"
        color = self._normalize_hex_color(bg_color) if bg_color else None
        if bg_color and not color:
            return False, "invalid bg_color"
        p["name"] = pname[:24]
        p["price_cents"] = price_cents
        if color:
            p["bg_color"] = color
        else:
            try:
                del p["bg_color"]
            except Exception:
                pass
        self.save_products()
        return True, "ok"

    def delete_product(self, product_id):
        products = self.products_cfg.get("products", [])
        idx = -1
        for i, p in enumerate(products):
            if p.get("id") == product_id:
                idx = i
                break
        if idx < 0:
            return False, "product not found"
        if len(products) <= 1:
            return False, "at least one product required"
        products.pop(idx)
        default_id = self.products_cfg.get("default_product_id")
        if default_id == product_id:
            self.products_cfg["default_product_id"] = products[0].get("id")
        self.save_products()
        return True, "ok"

    def build_ledger_steps(self, entry):
        steps = []
        root = self.root
        steps.append(lambda root=root, entry=entry: ledger.append_entry(root, entry, mirror=False))
        return steps

    def admin_credentials(self):
        admins = self.list_admins()
        if admins:
            first = admins[0]
            return first.get("username", "admin"), first.get("password_sha256_hex", "")
        return "admin", ""

    def list_admins(self):
        admins = self.device_cfg.get("admins", [])
        if isinstance(admins, list) and admins:
            out = []
            for item in admins:
                if not isinstance(item, dict):
                    continue
                username = (item.get("username", "") or "").strip()
                pwd = (item.get("password_sha256_hex", "") or "").strip().lower()
                if username and pwd:
                    cards = []
                    for c in item.get("cards", []) or []:
                        cv = (c or "").strip().upper()
                        if cv and cv not in cards:
                            cards.append(cv)
                    out.append({"username": username, "password_sha256_hex": pwd, "cards": cards})
            if out:
                return out

        legacy = self.device_cfg.get("admin", {})
        username = (legacy.get("username", "admin") or "").strip()
        pwd = (legacy.get("password_sha256_hex", "") or "").strip().lower()
        if username and pwd:
            return [{"username": username, "password_sha256_hex": pwd, "cards": []}]
        return []

    def _save_admins(self, admins):
        cleaned = []
        seen = set()
        for item in admins or []:
            if not isinstance(item, dict):
                continue
            username = (item.get("username", "") or "").strip()
            pwd = (item.get("password_sha256_hex", "") or "").strip().lower()
            if not username or not pwd:
                continue
            if username in seen:
                continue
            seen.add(username)
            cards = []
            for c in item.get("cards", []) or []:
                cv = (c or "").strip().upper()
                if cv and cv not in cards:
                    cards.append(cv)
            cleaned.append({"username": username, "password_sha256_hex": pwd, "cards": cards})

        if not cleaned:
            return False, "at least one admin required"

        self.device_cfg["admins"] = cleaned
        self.device_cfg["admin"] = {
            "username": cleaned[0]["username"],
            "password_sha256_hex": cleaned[0]["password_sha256_hex"],
        }
        self.save_device()
        return True, "ok"

    def verify_admin_hash(self, username, password_sha256_hex):
        u = (username or "").strip()
        p = (password_sha256_hex or "").strip().lower()
        for item in self.list_admins():
            if item.get("username") == u and item.get("password_sha256_hex", "").lower() == p:
                return True
        return False

    def admin_by_card(self, uid_hex):
        uid = (uid_hex or "").strip().upper()
        if not uid:
            return None
        for item in self.list_admins():
            cards = item.get("cards", []) or []
            for c in cards:
                if (c or "").upper() == uid:
                    return item.get("username")
        return None

    def add_admin(self, username, password_sha256_hex):
        u = (username or "").strip()
        p = (password_sha256_hex or "").strip().lower()
        if not u:
            return False, "username required"
        if len(u) > 32:
            return False, "username too long"
        if not p or len(p) != 64:
            return False, "invalid password hash"
        admins = self.list_admins()
        for item in admins:
            if item.get("username") == u:
                return False, "admin exists"
        admins.append({"username": u, "password_sha256_hex": p, "cards": []})
        return self._save_admins(admins)

    def delete_admin(self, username):
        u = (username or "").strip()
        admins = self.list_admins()
        new_admins = [a for a in admins if a.get("username") != u]
        if len(new_admins) == len(admins):
            return False, "admin not found"
        if not new_admins:
            return False, "at least one admin required"
        return self._save_admins(new_admins)

    def set_admin_password(self, username, password_sha256_hex):
        u = (username or "").strip()
        p = (password_sha256_hex or "").strip().lower()
        if not p or len(p) != 64:
            return False, "invalid password hash"
        admins = self.list_admins()
        changed = False
        for item in admins:
            if item.get("username") == u:
                item["password_sha256_hex"] = p
                changed = True
                break
        if not changed:
            return False, "admin not found"
        return self._save_admins(admins)

    def add_admin_card(self, username, uid_hex):
        u = (username or "").strip()
        uid = (uid_hex or "").strip().upper()
        if not u:
            return False, "username required"
        if not uid:
            return False, "uid required"
        # Ensure card is unique among admins.
        owner = self.admin_by_card(uid)
        if owner and owner != u:
            return False, "uid already assigned to {}".format(owner)

        admins = self.list_admins()
        found = False
        for item in admins:
            if item.get("username") == u:
                cards = item.setdefault("cards", [])
                if uid not in cards:
                    cards.append(uid)
                found = True
                break
        if not found:
            return False, "admin not found"
        return self._save_admins(admins)

    def remove_admin_card(self, uid_hex):
        uid = (uid_hex or "").strip().upper()
        if not uid:
            return False, "uid required", None
        admins = self.list_admins()
        removed_from = None
        for item in admins:
            cards = item.setdefault("cards", [])
            new_cards = [c for c in cards if (c or "").upper() != uid]
            if len(new_cards) != len(cards):
                item["cards"] = new_cards
                removed_from = item.get("username")
                break
        if removed_from is None:
            return False, "uid not found", None
        ok, msg = self._save_admins(admins)
        if not ok:
            return False, msg, None
        return True, "ok", removed_from

    def ap_config(self):
        ap = self.device_cfg.get("ap", {})
        return {
            "ssid": ap.get("ssid", "KaffeeCounter-Admin"),
            "mode": ap.get("mode", "open"),
            "hidden": bool(ap.get("hidden", True)),
            "wpa2_password": ap.get("wpa2_password", "KaffeeAdmin42"),
            "ip": ap.get("ip", "192.168.4.1"),
        }

    def rgb_invert(self):
        rgb = self.device_cfg.get("rgb", {})
        return bool(rgb.get("invert", False))

    def display_config(self):
        disp = self.device_cfg.get("display", {})
        return {
            "outside_schedule_off": bool(disp.get("outside_schedule_off", True)),
            "active_windows": disp.get("active_windows", [{"days": [0, 1, 2, 3, 4], "start": "06:00", "end": "20:00"}]),
            "outside_wake_s": int(disp.get("outside_wake_s", 120)),
            "idle_dim_after_s": int(disp.get("idle_dim_after_s", 90)),
            "normal_brightness": int(disp.get("normal_brightness", 255)),
            "dim_brightness": int(disp.get("dim_brightness", 50)),
            "sleep_brightness": int(disp.get("sleep_brightness", 10)),
        }

    def boot_jingle_config(self):
        section = self.device_cfg.get("boot_jingle", {})
        return {
            "enabled": bool(section.get("enabled", True)),
            "selected": section.get("selected", "te_deum"),
        }

    def printer_config(self):
        section = self.device_cfg.get("printer", {})
        return {
            "enabled": bool(section.get("enabled", True)),
            "uart_id": int(section.get("uart_id", 1)),
            "tx_pin": int(section.get("tx_pin", 8)),
            "rx_pin": int(section.get("rx_pin", 9)),
            "baudrate": int(section.get("baudrate", 9600)),
            "timeout_ms": int(section.get("timeout_ms", 100)),
            "receipt_per_booking": bool(section.get("receipt_per_booking", False)),
        }

    def set_receipt_per_booking(self, enabled):
        section = self.device_cfg.setdefault("printer", {})
        section["receipt_per_booking"] = bool(enabled)
        return self.save_device()

    def jingle_library(self):
        lib = self.device_cfg.get("jingles", {})
        if not isinstance(lib, dict):
            lib = {}
        out = {}
        for name, seq in lib.items():
            if not isinstance(name, str):
                continue
            if not isinstance(seq, list):
                continue
            cleaned = []
            for pair in seq:
                if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                    continue
                try:
                    f = int(pair[0])
                    d = int(pair[1])
                except Exception:
                    continue
                if d <= 0:
                    continue
                cleaned.append([f, d])
            if cleaned:
                out[name] = cleaned
        # Always keep a default tune available.
        if "te_deum" not in out:
            out["te_deum"] = [
                [988, 110],
                [1109, 110],
                [1175, 140],
                [1319, 220],
                [0, 60],
                [1319, 120],
                [1175, 120],
                [1109, 120],
                [988, 200],
            ]
        return out

    def set_boot_jingle_enabled(self, enabled):
        section = self.device_cfg.setdefault("boot_jingle", {})
        section["enabled"] = bool(enabled)
        self.save_device()
        return True, "ok"

    def set_boot_jingle_selected(self, name):
        lib = self.jingle_library()
        if name not in lib:
            return False, "jingle not found"
        section = self.device_cfg.setdefault("boot_jingle", {})
        section["selected"] = name
        self.save_device()
        return True, "ok"

    def upsert_jingle(self, name, sequence):
        jname = (name or "").strip()
        if not jname:
            return False, "name required"
        cleaned = []
        for pair in sequence or []:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                continue
            try:
                f = int(pair[0])
                d = int(pair[1])
            except Exception:
                continue
            if d <= 0:
                continue
            cleaned.append([f, d])
        if not cleaned:
            return False, "sequence invalid"
        lib = self.jingle_library()
        lib[jname] = cleaned
        self.device_cfg["jingles"] = lib
        self.save_device()
        return True, "ok"

    def delete_jingle(self, name):
        jname = (name or "").strip()
        if jname == "te_deum":
            return False, "te_deum is protected"
        lib = self.jingle_library()
        if jname not in lib:
            return False, "jingle not found"
        del lib[jname]
        self.device_cfg["jingles"] = lib
        cfg = self.boot_jingle_config()
        if cfg.get("selected") == jname:
            self.device_cfg.setdefault("boot_jingle", {})["selected"] = "te_deum"
        self.save_device()
        return True, "ok"
