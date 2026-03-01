import time

import config_pins as pins
import ledger
from drivers.tm_t88_rs232 import TmT88Rs232


def _fmt_eur(cents):
    v = int(cents)
    neg = v < 0
    if neg:
        v = -v
    return "{}{}.{:02d}".format("-" if neg else "", v // 100, v % 100)


def _fmt_eur_accounting(cents):
    v = int(cents)
    sign = "-" if v < 0 else "+"
    if v < 0:
        v = -v
    euros = v // 100
    cents_part = v % 100
    # Fixed width so commas/decimals line up in columns.
    return "{:>10}".format("{}{:d},{:02d}".format(sign, euros, cents_part))


def _parse_ts_epoch(ts):
    try:
        y = int(ts[0:4])
        m = int(ts[5:7])
        d = int(ts[8:10])
        hh = int(ts[11:13])
        mm = int(ts[14:16])
        ss = int(ts[17:19])
        return time.mktime((y, m, d, hh, mm, ss, 0, 0))
    except Exception:
        return None


def _iso_weeks_in_year(year):
    # ISO week for Dec 28 determines number of ISO weeks in year.
    try:
        ep = time.mktime((int(year), 12, 28, 0, 0, 0, 0, 0))
        lt = time.localtime(ep)
        wday = int(lt[6])  # 0=Mon..6=Sun
        yday = int(lt[7])
        week = (yday - wday + 10) // 7
        if week < 52:
            return 52
        if week > 53:
            return 53
        return week
    except Exception:
        return 52


def _iso_year_week(y, m, d):
    ep = time.mktime((int(y), int(m), int(d), 0, 0, 0, 0, 0))
    lt = time.localtime(ep)
    year = int(lt[0])
    wday = int(lt[6])  # 0=Mon..6=Sun
    yday = int(lt[7])
    week = (yday - wday + 10) // 7
    if week < 1:
        iso_year = year - 1
        week = _iso_weeks_in_year(iso_year)
    else:
        maxw = _iso_weeks_in_year(year)
        if week > maxw:
            iso_year = year + 1
            week = 1
        else:
            iso_year = year
    return iso_year, week


def _parse_ts_ymd(ts):
    try:
        return int(ts[0:4]), int(ts[5:7]), int(ts[8:10])
    except Exception:
        return None


def _build_ranking(store, period):
    now = time.localtime()
    now_epoch = None
    try:
        now_epoch = time.mktime((now[0], now[1], now[2], now[3], now[4], now[5], 0, 0))
    except Exception:
        now_epoch = None
    entries = ledger.scan_recent_entries(store.root, months=3, max_entries=6000)
    users = {}
    for u in store.list_users():
        users[u.get("user_id")] = u.get("name", u.get("user_id", "?"))

    agg = {}
    for e in entries:
        ts = e.get("ts", "")
        if period == "month":
            if ts[:7] != "{:04d}-{:02d}".format(now[0], now[1]):
                continue
        elif period == "week":
            if now_epoch is not None:
                ep = _parse_ts_epoch(ts)
                if ep is None:
                    continue
                if ep < (now_epoch - 7 * 24 * 3600) or ep > now_epoch:
                    continue
            else:
                if ts[:7] != "{:04d}-{:02d}".format(now[0], now[1]):
                    continue
        typ = e.get("type", "")
        uid = e.get("user_id", "")
        if not uid:
            continue
        row = agg.get(uid)
        if row is None:
            row = {"qty": 0, "spent_cents": 0}
            agg[uid] = row
        qty = int(e.get("qty", 0) or 0)
        amount = int(e.get("amount_cents", 0) or 0)
        if typ == "purchase":
            row["qty"] += qty
            row["spent_cents"] += -amount
        elif typ == "undo":
            row["qty"] -= qty
            row["spent_cents"] -= amount

    items = []
    for uid, row in agg.items():
        qty = int(row.get("qty", 0))
        spent = int(row.get("spent_cents", 0))
        if qty <= 0 and spent <= 0:
            continue
        items.append((uid, qty, spent))
    items.sort(key=lambda x: (x[1], x[2]), reverse=True)
    return users, items[:10]


def _period_match(ts, period_kind, value, year_ref):
    ymd = _parse_ts_ymd(ts)
    if ymd is None:
        return False
    y, m, d = ymd
    if period_kind == "week":
        iso_y, iso_w = _iso_year_week(y, m, d)
        return iso_y == int(year_ref) and iso_w == int(value)
    if period_kind == "month":
        return y == int(year_ref) and m == int(value)
    if period_kind == "year":
        return y == int(value)
    return False


def _entry_to_user_line(entry, product_name):
    ts = entry.get("ts", "")
    typ = entry.get("type", "")
    amount = int(entry.get("amount_cents", 0) or 0)
    if typ == "purchase":
        action = "Kauf"
    elif typ == "undo":
        action = "Storno"
    elif typ == "deposit":
        action = "Einzahlung"
    else:
        action = typ[:10]
    stamp = ts
    if len(ts) >= 16:
        # dd.mm hh:mm for compact human-readable output.
        stamp = "{}.{} {}".format(ts[8:10], ts[5:7], ts[11:16])
    return {
        "stamp": stamp,
        "action": action,
        "product": (product_name or "-")[:12],
        "amount_cents": int(amount),
        "invert": (typ == "undo"),
    }


class PrinterService:
    def __init__(self, store):
        self.store = store
        self.printer = None
        self.enabled = False
        self._queue = []
        self.last_error = None
        self._receipt_per_booking = False
        self._init_from_config()

    def _init_from_config(self):
        cfg = self.store.printer_config()
        self.enabled = bool(cfg.get("enabled", False))
        self._receipt_per_booking = bool(cfg.get("receipt_per_booking", False))
        if not self.enabled:
            return
        try:
            self.printer = TmT88Rs232(
                uart_id=cfg.get("uart_id", pins.PRINTER_UART_ID),
                tx_pin=cfg.get("tx_pin", pins.PRINTER_UART_TX_PIN),
                rx_pin=cfg.get("rx_pin", pins.PRINTER_UART_RX_PIN),
                baudrate=cfg.get("baudrate", pins.PRINTER_UART_BAUD),
                timeout_ms=cfg.get("timeout_ms", 100),
            )
        except Exception as exc:
            self.last_error = "init: {}".format(exc)
            self.printer = None

    def receipt_per_booking_enabled(self):
        return bool(self._receipt_per_booking)

    def toggle_receipt_per_booking(self):
        self._receipt_per_booking = not bool(self._receipt_per_booking)
        self.store.set_receipt_per_booking(self._receipt_per_booking)
        return self._receipt_per_booking

    def _enqueue(self, fn):
        if not self.enabled:
            return
        if len(self._queue) >= 240:
            self._queue.pop(0)
        self._queue.append(fn)

    def _enqueue_receipt(self, title, lines, footer=None):
        # Build receipt as many tiny jobs so web loop stays responsive.
        self._enqueue(lambda: self.printer.reset())
        self._enqueue(lambda: self.printer.align("center"))
        self._enqueue(lambda: self.printer.bold(True))
        self._enqueue(lambda t=(title or "Kaffee-Counter"): self.printer.line(str(t)[:42]))
        self._enqueue(lambda: self.printer.bold(False))
        self._enqueue(lambda: self.printer.align("left"))
        self._enqueue(lambda: self.printer.hr())
        for raw in lines or []:
            line = str(raw or "").replace("\n", " ").replace("\r", " ")
            self._enqueue(lambda line=line: self.printer.line(line[:42]))
        self._enqueue(lambda: self.printer.hr())
        if footer:
            self._enqueue(lambda: self.printer.align("center"))
            self._enqueue(lambda f=str(footer): self.printer.line(f[:42]))
            self._enqueue(lambda: self.printer.align("left"))
        self._enqueue(lambda: self.printer.feed(3))
        self._enqueue(lambda: self.printer.cut())

    def tick(self):
        if not self.enabled or self.printer is None or not self._queue:
            return
        fn = self._queue.pop(0)
        try:
            fn()
        except Exception as exc:
            self.last_error = "print: {}".format(exc)

    def enqueue_test_page(self):
        self._enqueue_receipt(
            "Kaffee-Counter",
            [
                "Drucker-Test",
                "Epson TM-T88III RS232",
                "Verbindung OK",
            ],
            footer="Testseite",
        )

    def enqueue_purchase_receipt(self, ts, user_name, product_name, amount_cents, balance_before, balance_after):
        def _job():
            lines = [
                "Zeit: {}".format(ts),
                "Nutzer: {}".format(user_name),
                "Produkt: {}".format(product_name),
                "Betrag: -{} EUR".format(_fmt_eur(abs(int(amount_cents)))),
                "Saldo vorher: {} EUR".format(_fmt_eur(balance_before)),
                "Saldo nachher: {} EUR".format(_fmt_eur(balance_after)),
            ]
            self._enqueue_receipt("Kaffee Buchung", lines, footer="Danke")
        self._enqueue(_job)

    def enqueue_undo_receipt(self, ts, user_name, product_name, amount_cents, balance_before, balance_after):
        def _job():
            lines = [
                "Zeit: {}".format(ts),
                "Nutzer: {}".format(user_name),
                "Storno: {}".format(product_name),
                "Betrag: +{} EUR".format(_fmt_eur(abs(int(amount_cents)))),
                "Saldo vorher: {} EUR".format(_fmt_eur(balance_before)),
                "Saldo nachher: {} EUR".format(_fmt_eur(balance_after)),
            ]
            self._enqueue_receipt("Kaffee Storno", lines, footer="Korrektur gebucht")
        self._enqueue(_job)

    def enqueue_ranking(self, period):
        period_name = "Wochenranking" if period == "week" else "Monatsranking"
        users, rows = _build_ranking(self.store, period)

        def _job():
            lines = []
            if not rows:
                lines.append("Keine Buchungen im Zeitraum")
            else:
                pos = 1
                for uid, qty, spent in rows:
                    name = users.get(uid, uid)
                    lines.append("{}. {} ({}x, {} EUR)".format(pos, name[:18], qty, _fmt_eur(spent)))
                    pos += 1
            self._enqueue_receipt(period_name, lines, footer="Kaffee-Counter")
        self._enqueue(_job)

    def user_period_summary(self, user_id, period_kind="week", offset=0):
        now = time.localtime()
        cur_year = int(now[0])
        cur_month = int(now[1])
        cur_week = _iso_year_week(now[0], now[1], now[2])[1]

        if period_kind == "week":
            week = cur_week - int(offset)
            year_ref = cur_year
            while week < 1:
                year_ref -= 1
                week += _iso_weeks_in_year(year_ref)
            label = "KW {:02d}/{}".format(week, year_ref)
            value = week
        else:
            month = cur_month - int(offset)
            year_ref = cur_year
            while month < 1:
                year_ref -= 1
                month += 12
            label = "Monat {:02d}/{}".format(month, year_ref)
            value = month

        if period_kind == "week":
            # Roughly 4-5 weeks per month.
            months_window = max(2, (int(offset) // 4) + 2)
        else:
            months_window = max(2, int(offset) + 2)
        if months_window > 24:
            months_window = 24
        entries = ledger.scan_recent_entries_filtered(
            self.store.root,
            months=months_window,
            max_entries=5000,
            user_id=user_id,
            types=("purchase", "undo"),
        )
        count = 0
        spent = 0
        filtered = []
        products = {}
        for p in self.store.get_products():
            products[p.get("id")] = p.get("name", p.get("id", ""))
        for e in entries:
            if not _period_match(e.get("ts", ""), period_kind, value, year_ref):
                continue
            typ = e.get("type", "")
            amt = int(e.get("amount_cents", 0) or 0)
            if typ == "purchase":
                count += int(e.get("qty", 0) or 0)
                spent += -amt
            elif typ == "undo":
                count -= int(e.get("qty", 0) or 0)
                spent -= amt
            filtered.append((e, products.get(e.get("product_id", ""), e.get("product_id", ""))))
        filtered.sort(key=lambda x: x[0].get("ts", ""))
        return {
            "label": label,
            "count": count if count > 0 else 0,
            "spent_cents": spent if spent > 0 else 0,
            "entries": filtered,
            "period_kind": period_kind,
            "value": value,
            "year_ref": year_ref,
        }

    def enqueue_user_period_log(self, user_name, summary):
        def _line42(col1, col2, col3, col4):
            # Exact 42 chars: 11 +1+ 7 +1+ 11 +1+ 10
            return "{:<11} {:<7} {:<11} {:>10}".format(col1, col2, col3, col4)[:42]

        header_lines = [
            "Nutzer: {}".format((user_name or "?")[:24]),
            "Zeitraum: {}".format(summary.get("label", "")),
            "Buchungen: {}".format(summary.get("count", 0)),
            "Summe: {} EUR".format(_fmt_eur(summary.get("spent_cents", 0))),
            _line42("Zeit", "Typ", "Produkt", "Betrag"),
            "------------------------------------------",
        ]
        entry_lines = []
        for e, product_name in summary.get("entries", [])[-24:]:
            row = _entry_to_user_line(e, product_name)
            txt = _line42(
                row["stamp"][:11],
                row["action"][:7],
                row["product"][:11],
                _fmt_eur_accounting(row["amount_cents"]),
            )
            entry_lines.append((txt, bool(row.get("invert", False))))

        self._enqueue(lambda: self.printer.reset())
        self._enqueue(lambda: self.printer.align("center"))
        self._enqueue(lambda: self.printer.bold(True))
        self._enqueue(lambda: self.printer.line("Buchungslog Nutzer"))
        self._enqueue(lambda: self.printer.bold(False))
        self._enqueue(lambda: self.printer.align("left"))
        self._enqueue(lambda: self.printer.hr())
        for line in header_lines:
            self._enqueue(lambda line=line: self.printer.line(line[:42]))
        for txt, inv in entry_lines:
            if inv:
                self._enqueue(lambda: self.printer.invert(True))
            self._enqueue(lambda txt=txt: self.printer.line(txt))
            if inv:
                self._enqueue(lambda: self.printer.invert(False))
        self._enqueue(lambda: self.printer.hr())
        self._enqueue(lambda: self.printer.align("center"))
        self._enqueue(lambda: self.printer.line("Kaffee-Counter"))
        self._enqueue(lambda: self.printer.align("left"))
        self._enqueue(lambda: self.printer.feed(3))
        self._enqueue(lambda: self.printer.cut())

    def ranking_summary(self, period_kind, value, year_ref=None):
        if year_ref is None:
            year_ref = int(time.localtime()[0])
        entries = ledger.scan_recent_entries(self.store.root, months=12, max_entries=20000)
        users = {}
        for u in self.store.list_users():
            users[u.get("user_id")] = u.get("name", u.get("user_id", "?"))
        agg = {}
        booking_count = 0
        for e in entries:
            if not _period_match(e.get("ts", ""), period_kind, value, year_ref):
                continue
            typ = e.get("type", "")
            if typ not in ("purchase", "undo"):
                continue
            uid = e.get("user_id", "")
            if not uid:
                continue
            row = agg.get(uid)
            if row is None:
                row = {"qty": 0, "spent": 0}
                agg[uid] = row
            qty = int(e.get("qty", 0) or 0)
            amt = int(e.get("amount_cents", 0) or 0)
            if typ == "purchase":
                row["qty"] += qty
                row["spent"] += -amt
                booking_count += qty
            else:
                row["qty"] -= qty
                row["spent"] -= amt
                booking_count -= qty
        rows = []
        for uid, row in agg.items():
            qty = int(row.get("qty", 0))
            spent = int(row.get("spent", 0))
            if qty <= 0 and spent <= 0:
                continue
            rows.append((uid, qty, spent))
        rows.sort(key=lambda x: (x[1], x[2]), reverse=True)
        rows = rows[:20]
        label = ""
        if period_kind == "week":
            label = "KW {:02d}/{}".format(int(value), int(year_ref))
        elif period_kind == "month":
            label = "Monat {:02d}/{}".format(int(value), int(year_ref))
        else:
            label = "Jahr {}".format(int(value))
        return {"label": label, "rows": rows, "users": users, "booking_count": max(0, int(booking_count))}

    def enqueue_ranking_period(self, period_kind, value, year_ref=None):
        s = self.ranking_summary(period_kind, value, year_ref)
        title = "Ranking {}".format(s.get("label", ""))

        def _job():
            lines = ["Buchungen gesamt: {}".format(s.get("booking_count", 0))]
            rows = s.get("rows", [])
            users = s.get("users", {})
            if not rows:
                lines.append("Keine Buchungen")
            else:
                pos = 1
                for uid, qty, spent in rows[:10]:
                    name = users.get(uid, uid)
                    lines.append("{}. {} {}x {}EUR".format(pos, name[:16], qty, _fmt_eur(spent)))
                    pos += 1
            self._enqueue_receipt(title, lines, footer="Kaffee-Counter")

        self._enqueue(_job)
