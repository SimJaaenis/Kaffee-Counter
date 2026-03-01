from machine import I2C, Pin
import time

import config_pins as pins
import ledger

from drivers.i2c_lcd_20x4_pcf8574 import I2cLcd20x4
from drivers.rgb_pwm import RgbPwm
from drivers.buzzer_pwm import BuzzerPwm
from drivers.buttons import ButtonPanel
from drivers.encoder_ky040 import EncoderKY040
from drivers.rtc_ds1307 import DS1307Clock
from drivers.pn532_i2c import PN532I2C

try:
    import _thread
except Exception:
    _thread = None


STATE_IDLE = "IDLE"
STATE_SHOW_BALANCE = "SHOW_BALANCE"
STATE_UNDO_WINDOW = "UNDO_WINDOW"
STATE_ERROR = "ERROR"
STATE_BALANCE_PRINT = "BALANCE_PRINT"
STATE_RANKING_KIND = "RANKING_KIND"
STATE_RANKING_VALUE = "RANKING_VALUE"
STATE_RANKING_PREVIEW = "RANKING_PREVIEW"


def uid_to_hex(uid_bytes):
    return "".join("{:02X}".format(b) for b in uid_bytes)


def fmt_eur(cents):
    neg = cents < 0
    v = -cents if neg else cents
    euros = v // 100
    cents_part = v % 100
    out = "{}, {:02d}".format(euros, cents_part).replace(" ", "")
    return "-{}".format(out) if neg else out


def parse_hex_rgb(value):
    v = (value or "").strip()
    if len(v) != 7 or not v.startswith("#"):
        return None
    hx = v[1:]
    for ch in hx:
        ok = ("0" <= ch <= "9") or ("a" <= ch.lower() <= "f")
        if not ok:
            return None
    try:
        return (int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16))
    except Exception:
        return None


class KioskApp:
    def __init__(self, store, logger, printer=None):
        self.store = store
        self.logger = logger
        self.printer = printer

        self.i2c = None
        self.lcd = None
        self.rgb = None
        self.buzzer = None
        self.buttons = None
        self.encoder = None
        self.rtc = None
        self.pn532 = None

        self.state = STATE_IDLE
        self.selected_idx = 0

        self._events = []
        self._last_nfc_poll = 0
        self._last_uid = None
        self._last_uid_ms = 0

        self._deadline_ms = 0
        self._error_text = ""
        self._render_cache = None

        self._balance_prompt = False
        self._balance_user = None
        self._balance_cents = 0

        self._undo = None
        self._feedback_mode = "idle"
        self._feedback_until_ms = 0
        self._last_activity_ms = time.ticks_ms()
        self._last_screen_eval_ms = time.ticks_ms()
        self._screen_state = "normal"
        self._display_cfg = {}
        self._outside_wake_until_ms = 0
        self._nfc_thread_enabled = bool(getattr(pins, "NFC_THREAD_ENABLED", False))
        self._nfc_thread_running = False
        self._nfc_thread_started = False
        self._nfc_thread_lock = None
        self._nfc_thread_queue = []
        self._nfc_thread_error = None
        self._event_queue_max = int(getattr(pins, "EVENT_QUEUE_MAX", 80))
        self._max_events_per_tick = int(getattr(pins, "MAX_EVENTS_PER_TICK", 24))
        self._selection_mode = False
        self._selection_deadline_ms = 0
        self._balance_print_period = "week"
        self._balance_print_offset = 0
        self._balance_print_cache_key = None
        self._balance_print_cache_summary = None
        self._ranking_kind_idx = 0
        self._ranking_value = 1
        self._ranking_year_ref = 0
        self._ranking_preview = None
        self._ranking_preview_key = None

    class _NoopLock:
        def acquire(self):
            return True

        def release(self):
            return True

    @staticmethod
    def _center20(text):
        t = (text or "")[:20]
        if len(t) >= 20:
            return t
        left = (20 - len(t)) // 2
        right = 20 - len(t) - left
        return (" " * left) + t + (" " * right)

    def boot(self):
        self._init_i2c()
        self._init_ui()
        self._init_inputs()
        self._init_rtc()
        self._init_nfc()
        self._display_cfg = self.store.display_config()

        self._show_welcome_screen()
        self._play_boot_jingle()

        default_id = self.store.default_product_id()
        self.selected_idx = self.store.product_index_by_id(default_id)

        self._set_status_rgb("idle")

        self._render(force=True)
        self._wake_screen()

    def _show_welcome_screen(self):
        if not self.lcd:
            return
        try:
            self.lcd.write_lines(
                [
                    "Kaffee Counter",
                    "System startet...",
                    "Bitte warten",
                    "",
                ]
            )
            time.sleep_ms(1200)
        except Exception:
            pass

    def _play_boot_jingle(self):
        if not self.buzzer:
            return
        try:
            cfg = self.store.boot_jingle_config()
            if not cfg.get("enabled", True):
                return
            lib = self.store.jingle_library()
            name = cfg.get("selected", "te_deum")
            seq = lib.get(name) or lib.get("te_deum") or []
            if seq:
                self.buzzer.play_async(seq, clear=True)
        except Exception:
            pass

    def _init_i2c(self):
        self.i2c = I2C(
            pins.I2C_ID,
            sda=Pin(pins.I2C_SDA_PIN),
            scl=Pin(pins.I2C_SCL_PIN),
            freq=pins.I2C_FREQ,
        )

    def _init_ui(self):
        try:
            self.lcd = I2cLcd20x4(
                self.i2c,
                i2c_addr=pins.LCD_ADDR,
                num_lines=pins.LCD_ROWS,
                num_columns=pins.LCD_COLS,
            )
        except Exception:
            self.lcd = None

        self.rgb = RgbPwm(
            pins.RGB_R_PIN,
            pins.RGB_G_PIN,
            pins.RGB_B_PIN,
            freq_hz=pins.RGB_PWM_FREQ,
            invert=self.store.rgb_invert(),
        )
        self.buzzer = BuzzerPwm(pins.BUZZER_PIN)

    def _init_inputs(self):
        self.buttons = ButtonPanel(
            pins.BTN_GREEN_PIN,
            pins.BTN_WHITE_PIN,
            pins.BTN_RED_PIN,
            long_press_ms=pins.RED_LONG_PRESS_MS,
            backup_press_ms=getattr(pins, "RED_BACKUP_HOLD_MS", None),
            combo_press_ms=getattr(pins, "WHITE_GREEN_COMBO_MS", 5000),
            debounce_ms=30,
        )
        # Backward-compatible init: older encoder driver may not support reversal_guard_ms.
        try:
            self.encoder = EncoderKY040(
                pins.ENC_CLK_PIN,
                pins.ENC_DT_PIN,
                pins.ENC_SW_PIN,
                debounce_ms=pins.ENCODER_DEBOUNCE_MS,
                button_debounce_ms=25,
                button_long_ms=getattr(pins, "ENCODER_LONG_PRESS_MS", 5000),
                steps_per_detent=pins.ENCODER_STEPS_PER_DETENT,
                reversal_guard_ms=pins.ENCODER_REVERSAL_GUARD_MS,
            )
        except TypeError:
            self.encoder = EncoderKY040(
                pins.ENC_CLK_PIN,
                pins.ENC_DT_PIN,
                pins.ENC_SW_PIN,
                debounce_ms=pins.ENCODER_DEBOUNCE_MS,
                button_debounce_ms=25,
                steps_per_detent=pins.ENCODER_STEPS_PER_DETENT,
            )

    def _init_rtc(self):
        self.rtc = DS1307Clock(self.i2c, address=pins.RTC_ADDR)
        try:
            if not self.rtc.available():
                print("RTC (HW-111/DS1307) nicht gefunden auf 0x{:02X}".format(pins.RTC_ADDR))
            else:
                _ = self.rtc.read_datetime()
        except Exception as exc:
            print("RTC init Hinweis:", exc)

    def _init_nfc(self):
        self.pn532 = None
        last_exc = None
        try:
            devices = self.i2c.scan()
        except Exception as exc:
            devices = []
            last_exc = exc

        if pins.PN532_ADDR not in devices:
            self._set_error("NFC Adr fehlt")
            return

        # PN532 braucht nach Bus-/Power-Start manchmal mehrere Anlaeufe.
        for _ in range(4):
            try:
                on_wait_cb = None if self._nfc_thread_enabled else self._service_realtime
                self.pn532 = PN532I2C(self.i2c, address=pins.PN532_ADDR, on_wait=on_wait_cb)
                _ = self.pn532.firmware_version
                self.pn532.SAM_configuration()
                self._start_nfc_thread_if_enabled()
                return
            except Exception as exc:
                last_exc = exc
                time.sleep_ms(150)

        print("PN532 init failed:", last_exc)
        self.pn532 = None
        self._set_error("NFC nicht erreichbar")

    def _start_nfc_thread_if_enabled(self):
        if not self._nfc_thread_enabled:
            return
        if _thread is None:
            self._nfc_thread_enabled = False
            print("NFC thread deaktiviert: _thread nicht verfuegbar")
            return
        if self._nfc_thread_started or self.pn532 is None:
            return
        if self._nfc_thread_lock is None:
            self._nfc_thread_lock = _thread.allocate_lock()
        self._nfc_thread_running = True
        self._nfc_thread_started = True
        _thread.start_new_thread(self._nfc_thread_loop, ())
        print("NFC thread aktiv")

    def _nfc_lock_acquire(self):
        if self._nfc_thread_lock is None:
            if _thread is not None:
                try:
                    self._nfc_thread_lock = _thread.allocate_lock()
                except Exception:
                    self._nfc_thread_lock = self._NoopLock()
            else:
                self._nfc_thread_lock = self._NoopLock()
        self._nfc_thread_lock.acquire()

    def _nfc_lock_release(self):
        if self._nfc_thread_lock is None:
            return
        try:
            self._nfc_thread_lock.release()
        except Exception:
            pass

    def _nfc_thread_push(self, item):
        if self._nfc_thread_lock is None:
            return
        self._nfc_thread_lock.acquire()
        try:
            if len(self._nfc_thread_queue) < 8:
                self._nfc_thread_queue.append(item)
        finally:
            self._nfc_thread_lock.release()

    def _nfc_thread_loop(self):
        sleep_ms = int(getattr(pins, "NFC_THREAD_SLEEP_MS", 10))
        read_timeout_ms = int(getattr(pins, "NFC_THREAD_READ_TIMEOUT_MS", pins.NFC_READ_TIMEOUT_MS))
        while self._nfc_thread_running:
            self._nfc_lock_acquire()
            pn = self.pn532
            self._nfc_lock_release()
            if pn is None or not self._nfc_thread_running:
                time.sleep_ms(30)
                continue
            try:
                self._nfc_lock_acquire()
                uid = pn.read_passive_target(timeout=read_timeout_ms / 1000.0)
                self._nfc_lock_release()
                if uid:
                    self._nfc_thread_push(("uid", uid_to_hex(uid)))
            except Exception as exc:
                self._nfc_lock_release()
                self._nfc_thread_push(("err", str(exc)))
                time.sleep_ms(50)
            time.sleep_ms(sleep_ms)

    def _service_realtime(self):
        # Keep short outputs time-accurate while PN532 wait loops are running.
        self._service_buzzer()

    def _service_buzzer(self):
        if self.buzzer is None:
            return
        burst = int(getattr(pins, "BUZZER_TICK_BURST", 1))
        if burst < 1:
            burst = 1
        for _ in range(burst):
            self.buzzer.tick()

    def _recover_i2c_devices(self):
        try:
            if self._nfc_thread_enabled and self._nfc_thread_started:
                self._nfc_thread_running = False
                time.sleep_ms(40)
                self._nfc_thread_started = False

            self._nfc_lock_acquire()
            self._init_i2c()
            if self.lcd is not None:
                self.lcd = I2cLcd20x4(
                    self.i2c,
                    i2c_addr=pins.LCD_ADDR,
                    num_lines=pins.LCD_ROWS,
                    num_columns=pins.LCD_COLS,
                )
            self._init_rtc()
            self._init_nfc()
            self._nfc_lock_release()
        except Exception:
            self._nfc_lock_release()
            pass

    def _set_status_rgb(self, mode):
        if not self.rgb:
            return
        if mode == "success":
            self.rgb.set_named("success")
        elif mode == "error":
            self.rgb.set_named("error")
        elif mode == "admin":
            self.rgb.set_named("admin")
        elif mode == "off":
            self.rgb.set_named("off")
        else:
            self.rgb.set_named("idle")

    def _apply_selection_rgb(self):
        if not self.rgb:
            return
        if self._feedback_mode != "idle":
            return
        if self.state != STATE_IDLE or not self._selection_mode:
            self._set_status_rgb("idle")
            return
        product = self._current_product()
        rgb = parse_hex_rgb(product.get("bg_color", ""))
        if rgb is None:
            self._set_status_rgb("idle")
            return
        try:
            self.rgb.set_rgb(rgb[0], rgb[1], rgb[2])
        except Exception:
            pass

    def _mark_activity(self):
        self._last_activity_ms = time.ticks_ms()
        # Outside schedule: keep display awake for configured period.
        if bool(self._display_cfg.get("outside_schedule_off", True)) and not self._is_in_active_window():
            wake_s = int(self._display_cfg.get("outside_wake_s", 120))
            self._outside_wake_until_ms = time.ticks_add(time.ticks_ms(), wake_s * 1000)

    @staticmethod
    def _parse_hhmm(value):
        try:
            hh, mm = (value or "").split(":", 1)
            h = int(hh)
            m = int(mm)
            if 0 <= h <= 23 and 0 <= m <= 59:
                return (h * 60) + m
        except Exception:
            pass
        return None

    def _is_in_active_window(self):
        windows = self._display_cfg.get("active_windows", [])
        if not windows:
            return True

        lt = time.localtime()
        weekday = lt[6]  # 0=Mon ... 6=Sun
        minute_of_day = (lt[3] * 60) + lt[4]

        for win in windows:
            days = win.get("days", [])
            if weekday not in days:
                continue
            start = self._parse_hhmm(win.get("start"))
            end = self._parse_hhmm(win.get("end"))
            if start is None or end is None:
                continue
            if start <= minute_of_day < end:
                return True
        return False

    def _wake_screen(self):
        self._screen_state = "normal"
        if self.lcd:
            try:
                self.lcd.backlight_on()
                self.lcd.display_on()
            except Exception:
                pass
        if self.rgb:
            try:
                self.rgb.set_brightness(self._display_cfg.get("normal_brightness", 255))
                if self._feedback_mode == "idle":
                    self.rgb.set_named("idle")
            except Exception:
                pass

    def _dim_screen(self):
        if self._screen_state == "dim":
            return
        self._screen_state = "dim"
        if self.rgb:
            try:
                self.rgb.set_brightness(self._display_cfg.get("dim_brightness", 50))
            except Exception:
                pass

    def _off_screen(self):
        if self._screen_state == "off":
            return
        self._screen_state = "off"
        if self.rgb:
            try:
                # Screensaver should only affect LED backlight, not LCD content.
                self.rgb.set_brightness(self._display_cfg.get("sleep_brightness", 10))
                self.rgb.set_named("idle")
            except Exception:
                pass

    def _update_screen_saver(self):
        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_screen_eval_ms) < 250:
            return
        self._last_screen_eval_ms = now

        outside_off = bool(self._display_cfg.get("outside_schedule_off", True))
        in_window = self._is_in_active_window()

        if outside_off and not in_window:
            if time.ticks_diff(now, self._outside_wake_until_ms) < 0:
                if self._screen_state != "normal":
                    self._wake_screen()
            else:
                if self.state == STATE_IDLE:
                    self._selection_mode = False
                self._off_screen()
            return

        idle_after_ms = int(self._display_cfg.get("idle_dim_after_s", 90)) * 1000
        if time.ticks_diff(now, self._last_activity_ms) >= idle_after_ms:
            if self.state == STATE_IDLE:
                self._selection_mode = False
            self._dim_screen()
        else:
            if self._screen_state != "normal":
                self._wake_screen()

    def _set_feedback(self, mode, duration_ms, buzzer_kind=None):
        self._feedback_mode = mode
        self._feedback_until_ms = time.ticks_add(time.ticks_ms(), int(duration_ms))
        self._set_status_rgb(mode)
        if self.buzzer is None:
            return
        try:
            if buzzer_kind == "success":
                self.buzzer.success_async()
            elif buzzer_kind == "error":
                self.buzzer.error_async()
        except Exception:
            pass

    def _update_feedback(self):
        if self._feedback_mode == "idle":
            return
        if time.ticks_diff(time.ticks_ms(), self._feedback_until_ms) >= 0:
            self._feedback_mode = "idle"
            self._set_status_rgb("idle")

    def _set_error(self, msg):
        self.state = STATE_ERROR
        self._error_text = (msg or "Fehler")[:20]
        self._deadline_ms = time.ticks_add(time.ticks_ms(), pins.ERROR_SHOW_MS)
        self._set_feedback("error", pins.ERROR_FEEDBACK_MS, buzzer_kind="error")

    def _sync_to_sd_backup(self):
        ok, copied, failed = self.store.sync_internal_to_sd()
        print("Backup intern->SD:", ok, "copied=", copied, "failed=", failed)
        if ok and failed == 0:
            self._set_feedback("success", 700, buzzer_kind="success")
        else:
            self._set_feedback("error", 1100, buzzer_kind="error")

    def _toggle_receipt_print(self):
        if not self.printer:
            self._set_feedback("error", 900, buzzer_kind="error")
            return
        enabled = self.printer.toggle_receipt_per_booking()
        print("Receipt per booking:", enabled)
        self._set_feedback("success", 700, buzzer_kind="success")

    @staticmethod
    def _ranking_kinds():
        return ["week", "month", "year"]

    def _ranking_kind(self):
        kinds = self._ranking_kinds()
        if self._ranking_kind_idx < 0:
            self._ranking_kind_idx = 0
        if self._ranking_kind_idx >= len(kinds):
            self._ranking_kind_idx = len(kinds) - 1
        return kinds[self._ranking_kind_idx]

    def _init_ranking_value(self):
        lt = time.localtime()
        self._ranking_year_ref = int(lt[0])
        kind = self._ranking_kind()
        if kind == "week":
            yday = int(lt[7]) if len(lt) > 7 else 1
            wday = int(lt[6])
            self._ranking_value = (yday - wday + 10) // 7
            if self._ranking_value < 1:
                self._ranking_value = 1
            if self._ranking_value > 53:
                self._ranking_value = 53
        elif kind == "month":
            self._ranking_value = int(lt[1])
        else:
            self._ranking_value = int(lt[0])

    def _change_ranking_value(self, delta):
        kind = self._ranking_kind()
        if kind == "week":
            self._ranking_value += int(delta)
            if self._ranking_value < 1:
                self._ranking_value = 1
            if self._ranking_value > 53:
                self._ranking_value = 53
        elif kind == "month":
            self._ranking_value += int(delta)
            if self._ranking_value < 1:
                self._ranking_value = 1
            if self._ranking_value > 12:
                self._ranking_value = 12
        else:
            self._ranking_value += int(delta)
            if self._ranking_value < 2000:
                self._ranking_value = 2000
            if self._ranking_value > 2099:
                self._ranking_value = 2099

    def _clear_to_idle(self):
        self.state = STATE_IDLE
        self._selection_mode = True
        self._balance_prompt = False
        self._balance_user = None
        self._balance_cents = 0
        self._balance_print_cache_key = None
        self._balance_print_cache_summary = None
        self._undo = None
        self._feedback_mode = "idle"
        self._ranking_preview = None
        self._ranking_preview_key = None
        self._apply_selection_rgb()

    def _invalidate_ranking_preview(self):
        self._ranking_preview = None
        self._ranking_preview_key = None

    def _get_ranking_preview(self):
        kind = self._ranking_kind()
        year_ref = self._ranking_year_ref if kind in ("week", "month") else None
        key = (kind, int(self._ranking_value), year_ref)
        if key != self._ranking_preview_key or self._ranking_preview is None:
            if self.printer:
                self._ranking_preview = self.printer.ranking_summary(kind, self._ranking_value, year_ref)
            else:
                self._ranking_preview = {"label": "-", "booking_count": 0}
            self._ranking_preview_key = key
        return self._ranking_preview

    def _get_balance_print_summary(self):
        if not self._balance_user or not self.printer:
            return None
        user_id = self._balance_user.get("user_id", "")
        key = (user_id, self._balance_print_period, int(self._balance_print_offset))
        if key != self._balance_print_cache_key or self._balance_print_cache_summary is None:
            self._balance_print_cache_summary = self.printer.user_period_summary(
                user_id,
                self._balance_print_period,
                self._balance_print_offset,
            )
            self._balance_print_cache_key = key
        return self._balance_print_cache_summary

    def _current_product(self):
        products = self.store.get_products()
        if not products:
            return {"id": "none", "name": "Kein Produkt", "price_cents": 0}
        if self.selected_idx < 0:
            self.selected_idx = 0
        if self.selected_idx >= len(products):
            self.selected_idx = len(products) - 1
        return products[self.selected_idx]

    def _enqueue(self, event_type, value=None):
        # Coalesce encoder deltas to reduce queue pressure and UI lag.
        if event_type == "enc_delta" and self._events and self._events[-1][0] == "enc_delta":
            prev = int(self._events[-1][1] or 0)
            self._events[-1] = ("enc_delta", prev + int(value or 0))
            return

        self._events.append((event_type, value))
        if len(self._events) > self._event_queue_max:
            # Prefer dropping stale non-critical events first.
            drop_idx = None
            for i, (et, _v) in enumerate(self._events):
                if et in ("enc_delta",):
                    drop_idx = i
                    break
            if drop_idx is None:
                drop_idx = 0
            self._events.pop(drop_idx)

    def _poll_inputs(self):
        for event in self.buttons.poll_events():
            self._enqueue(event)
        enc_delta = 0
        enc_press = False
        for event in self.encoder.poll():
            if event[0] == "enc_delta":
                enc_delta += int(event[1] or 0)
            elif event[0] == "enc_press":
                enc_press = True
            else:
                self._enqueue(event[0], event[1])
        if enc_delta:
            self._enqueue("enc_delta", enc_delta)
        if enc_press:
            self._enqueue("enc_press", 1)

    def _pop_next_event(self):
        # Prioritize encoder movement to keep product selection snappy.
        for i, (event_type, value) in enumerate(self._events):
            if event_type == "enc_delta":
                self._events.pop(i)
                return event_type, value
        return self._events.pop(0)

    def _poll_nfc(self):
        if not self.pn532:
            return

        if self._nfc_thread_enabled:
            self._poll_nfc_from_thread()
            return

        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_nfc_poll) < pins.NFC_POLL_MS:
            return
        self._last_nfc_poll = now

        try:
            self._service_buzzer()
            self._nfc_lock_acquire()
            uid = self.pn532.read_passive_target(timeout=pins.NFC_READ_TIMEOUT_MS / 1000.0)
            self._nfc_lock_release()
            self._service_buzzer()
        except Exception:
            self._nfc_lock_release()
            self.pn532 = None
            self._set_error("NFC Fehler")
            self._recover_i2c_devices()
            return

        if uid is None:
            return

        uid_hex = uid_to_hex(uid)
        if uid_hex == self._last_uid and time.ticks_diff(now, self._last_uid_ms) < 900:
            return

        self._last_uid = uid_hex
        self._last_uid_ms = now
        self._enqueue("nfc_uid", uid_hex)

    def _poll_nfc_from_thread(self):
        if self._nfc_thread_lock is None:
            return
        items = []
        self._nfc_thread_lock.acquire()
        try:
            if self._nfc_thread_queue:
                items = self._nfc_thread_queue
                self._nfc_thread_queue = []
        finally:
            self._nfc_thread_lock.release()

        if not items:
            return

        now = time.ticks_ms()
        for kind, value in items:
            if kind == "err":
                self._nfc_thread_error = value
                self._set_error("NFC Fehler")
                self._recover_i2c_devices()
                return
            uid_hex = value
            if uid_hex == self._last_uid and time.ticks_diff(now, self._last_uid_ms) < 900:
                continue
            self._last_uid = uid_hex
            self._last_uid_ms = now
            self._enqueue("nfc_uid", uid_hex)

    def _do_purchase(self, uid_hex):
        product = self._current_product()
        qty = 1
        amount = -int(product.get("price_cents", 0)) * qty

        user, created = self.store.ensure_user_for_uid(uid_hex, persist=False)
        user_id = user.get("user_id")
        user_name = user.get("name", user_id)

        ts, ts_source = self.rtc.timestamp_with_source()
        note = "src={}".format(ts_source)

        balance_before = int(self.store.get_balance(user_id))
        balance_after = balance_before + int(amount)
        entry = {
            "ts": ts,
            "type": "purchase",
            "user_id": user_id,
            "product_id": product.get("id", ""),
            "qty": qty,
            "amount_cents": amount,
            "balance_before_cents": balance_before,
            "balance_after_cents": balance_after,
            "note": note,
        }

        self.store.apply_balance_delta(user_id, amount)
        new_balance = self.store.get_balance(user_id)

        steps = self.store.build_ledger_steps(entry)
        if steps:
            steps = steps + [self.store.save_balances]
            if created:
                steps.append(self.store.save_users)
            self.logger.enqueue_steps(steps, description="purchase", fallback_ledger_entry=entry)
        else:
            self.logger.enqueue_ledger(lambda: None, entry, self.store.sd_ready)

        self._undo = {
            "purchase": entry,
            "expires_ms": time.ticks_add(time.ticks_ms(), pins.UNDO_WINDOW_MS),
            "product_name": product.get("name", "?"),
            "qty": qty,
            "amount_abs": -amount,
            "user_id": user_id,
            "user_name": user_name,
            "balance_after": new_balance,
        }

        self.state = STATE_UNDO_WINDOW
        self._selection_mode = False
        self._set_feedback("success", pins.SUCCESS_FEEDBACK_MS, buzzer_kind="success")
        if self.printer and self.printer.receipt_per_booking_enabled():
            self.printer.enqueue_purchase_receipt(
                ts=ts,
                user_name=user_name,
                product_name=product.get("name", "?"),
                amount_cents=amount,
                balance_before=balance_before,
                balance_after=balance_after,
            )

    def _do_undo(self):
        if not self._undo:
            return

        src = self._undo
        amount = int(src["amount_abs"])
        user_id = src["user_id"]
        qty = int(src["qty"])
        ts, ts_source = self.rtc.timestamp_with_source()

        balance_before = int(self.store.get_balance(user_id))
        balance_after = balance_before + int(amount)
        entry = {
            "ts": ts,
            "type": "undo",
            "user_id": user_id,
            "product_id": src["purchase"].get("product_id", ""),
            "qty": qty,
            "amount_cents": amount,
            "balance_before_cents": balance_before,
            "balance_after_cents": balance_after,
            "note": "undo src={}".format(ts_source),
        }

        self.store.apply_balance_delta(user_id, amount)
        self._balance_cents = self.store.get_balance(user_id)
        self._balance_user = self.store.user_by_id(user_id)

        steps = self.store.build_ledger_steps(entry)
        if steps:
            self.logger.enqueue_steps(
                steps + [self.store.save_balances],
                description="undo",
                fallback_ledger_entry=entry,
            )
        else:
            self.logger.enqueue_ledger(lambda: None, entry, self.store.sd_ready)

        self.state = STATE_SHOW_BALANCE
        self._balance_prompt = False
        self._deadline_ms = time.ticks_add(time.ticks_ms(), pins.SHOW_BALANCE_MS)
        self._undo = None
        self._set_feedback("error", pins.ERROR_FEEDBACK_MS, buzzer_kind="error")
        if self.printer and self.printer.receipt_per_booking_enabled():
            self.printer.enqueue_undo_receipt(
                ts=ts,
                user_name=(self._balance_user or {}).get("name", user_id),
                product_name=src.get("product_name", src["purchase"].get("product_id", "")),
                amount_cents=amount,
                balance_before=balance_before,
                balance_after=balance_after,
            )

    def _show_balance_for_uid(self, uid_hex):
        user, _created = self.store.ensure_user_for_uid(uid_hex)
        user_id = user.get("user_id")
        self._balance_user = user
        self._balance_cents = self.store.get_balance(user_id)
        self._balance_prompt = False
        self.state = STATE_SHOW_BALANCE
        self._deadline_ms = time.ticks_add(time.ticks_ms(), pins.SHOW_BALANCE_MS)
        self._set_status_rgb("idle")
        if self.buzzer:
            try:
                self.buzzer.balance_async()
            except Exception:
                pass

    def _process_event(self, event_type, value):
        if event_type in ("enc_delta", "enc_press", "enc_long", "btn_green", "btn_white", "btn_red_press", "btn_red_short", "btn_red_long", "btn_red_backup", "btn_white_green_long", "nfc_uid"):
            self._mark_activity()
            if self._screen_state != "normal":
                self._wake_screen()

        if event_type == "btn_red_backup":
            self._sync_to_sd_backup()
            return
        if event_type == "btn_white_green_long":
            self.state = STATE_RANKING_KIND
            self._ranking_kind_idx = 0
            self._init_ranking_value()
            self._invalidate_ranking_preview()
            return

        if self.state == STATE_ERROR:
            return

        if self.state == STATE_UNDO_WINDOW:
            if event_type in ("btn_red_press", "btn_red_short"):
                self._do_undo()
            return

        if self.state == STATE_SHOW_BALANCE and self._balance_prompt:
            if event_type in ("btn_red_press", "btn_red_short"):
                self._clear_to_idle()
                return
            if event_type == "btn_green":
                default_id = self.store.default_product_id()
                self.selected_idx = self.store.product_index_by_id(default_id)
                self._selection_mode = True
                self._apply_selection_rgb()
                self._clear_to_idle()
                return
            if event_type == "nfc_uid":
                self._show_balance_for_uid(value)
            return

        if self.state == STATE_SHOW_BALANCE and not self._balance_prompt:
            if event_type == "enc_long":
                self._toggle_receipt_print()
                return
            if event_type == "enc_press":
                self.state = STATE_BALANCE_PRINT
                self._balance_print_period = "week"
                self._balance_print_offset = 0
                self._balance_print_cache_key = None
                self._balance_print_cache_summary = None
                return
            if event_type == "enc_delta":
                self.state = STATE_BALANCE_PRINT
                self._balance_print_period = "week"
                self._balance_print_offset = 0
                self._balance_print_cache_key = None
                self._balance_print_cache_summary = None
                return
            if event_type in ("btn_red_press", "btn_red_short"):
                self._clear_to_idle()
                return
            if event_type == "btn_green":
                default_id = self.store.default_product_id()
                self.selected_idx = self.store.product_index_by_id(default_id)
                self._selection_mode = True
                self._apply_selection_rgb()
                self._clear_to_idle()
                return
            return

        if self.state == STATE_BALANCE_PRINT:
            if event_type in ("btn_red_press", "btn_red_short"):
                self._clear_to_idle()
                return
            if event_type == "enc_press":
                if self._balance_print_period == "week":
                    self._balance_print_period = "month"
                else:
                    self._balance_print_period = "week"
                self._balance_print_offset = 0
                self._balance_print_cache_key = None
                self._balance_print_cache_summary = None
                return
            if event_type == "enc_delta":
                self._balance_print_offset += int(value)
                if self._balance_print_offset < 0:
                    self._balance_print_offset = 0
                if self._balance_print_offset > 24:
                    self._balance_print_offset = 24
                self._balance_print_cache_key = None
                self._balance_print_cache_summary = None
                return
            if event_type == "btn_green":
                if self.printer and self._balance_user:
                    summary = self._get_balance_print_summary()
                    if summary is None:
                        summary = self.printer.user_period_summary(
                            self._balance_user.get("user_id", ""),
                            self._balance_print_period,
                            self._balance_print_offset,
                        )
                    self.printer.enqueue_user_period_log(self._balance_user.get("name", "?"), summary)
                    self._set_feedback("success", 700, buzzer_kind="success")
                self._clear_to_idle()
                return
            return

        if self.state == STATE_RANKING_KIND:
            if event_type in ("btn_red_press", "btn_red_short"):
                self._clear_to_idle()
                return
            if event_type == "enc_delta":
                self._ranking_kind_idx += int(value)
                kinds = self._ranking_kinds()
                while self._ranking_kind_idx < 0:
                    self._ranking_kind_idx += len(kinds)
                while self._ranking_kind_idx >= len(kinds):
                    self._ranking_kind_idx -= len(kinds)
                self._invalidate_ranking_preview()
                return
            if event_type == "enc_press":
                self._init_ranking_value()
                self._invalidate_ranking_preview()
                self.state = STATE_RANKING_VALUE
                return
            return

        if self.state == STATE_RANKING_VALUE:
            if event_type in ("btn_red_press", "btn_red_short"):
                self.state = STATE_RANKING_KIND
                return
            if event_type == "enc_delta":
                self._change_ranking_value(int(value))
                self._invalidate_ranking_preview()
                return
            if event_type == "enc_press":
                self._get_ranking_preview()
                self.state = STATE_RANKING_PREVIEW
                return
            return

        if self.state == STATE_RANKING_PREVIEW:
            if event_type in ("btn_red_press", "btn_red_short"):
                self.state = STATE_RANKING_KIND
                return
            if event_type == "btn_green":
                kind = self._ranking_kind()
                if self.printer:
                    year_ref = self._ranking_year_ref if kind in ("week", "month") else None
                    self.printer.enqueue_ranking_period(kind, self._ranking_value, year_ref)
                    self._set_feedback("success", 700, buzzer_kind="success")
                self._clear_to_idle()
                return
            return

        if self.state == STATE_IDLE:
            if event_type == "enc_long":
                self._toggle_receipt_print()
                return
            if event_type == "enc_delta":
                products = self.store.get_products()
                if products:
                    self._selection_mode = True
                    self._selection_deadline_ms = time.ticks_add(time.ticks_ms(), pins.SELECT_MODE_TIMEOUT_MS)
                    prev_idx = self.selected_idx
                    self.selected_idx = (self.selected_idx + int(value)) % len(products)
                    if self.selected_idx != prev_idx:
                        self._apply_selection_rgb()
                    if self.selected_idx != prev_idx and self.buzzer and pins.ENCODER_CLICK_SOUND:
                        try:
                            self.buzzer.click_async()
                        except Exception:
                            pass

            elif event_type == "enc_press":
                pass

            elif event_type == "btn_green":
                default_id = self.store.default_product_id()
                self.selected_idx = self.store.product_index_by_id(default_id)
                self._selection_mode = True
                self._selection_deadline_ms = time.ticks_add(time.ticks_ms(), pins.SELECT_MODE_TIMEOUT_MS)
                self._apply_selection_rgb()

            elif event_type == "btn_white":
                self.state = STATE_SHOW_BALANCE
                self._balance_prompt = True
                self._deadline_ms = time.ticks_add(time.ticks_ms(), 10000)

            elif event_type == "btn_red_long":
                default_id = self.store.default_product_id()
                self.selected_idx = self.store.product_index_by_id(default_id)
                self._selection_mode = True
                self._selection_deadline_ms = time.ticks_add(time.ticks_ms(), pins.SELECT_MODE_TIMEOUT_MS)
                self._apply_selection_rgb()

            elif event_type == "nfc_uid":
                if not self._selection_mode:
                    self._selection_mode = True
                    self._selection_deadline_ms = time.ticks_add(time.ticks_ms(), pins.SELECT_MODE_TIMEOUT_MS)
                    self._apply_selection_rgb()
                    self._show_standard_screen_once()
                self._do_purchase(value)

    def _state_timers(self):
        now = time.ticks_ms()

        if self.state == STATE_ERROR and time.ticks_diff(now, self._deadline_ms) >= 0:
            self._clear_to_idle()

        if self.state == STATE_SHOW_BALANCE and time.ticks_diff(now, self._deadline_ms) >= 0:
            self._clear_to_idle()

        if self.state == STATE_UNDO_WINDOW and self._undo:
            if time.ticks_diff(now, self._undo["expires_ms"]) >= 0:
                self._clear_to_idle()

        # Selection mode in IDLE now ends via inactivity/screensaver only.

    def _render_lines_idle(self):
        ts, _src = self.rtc.timestamp_with_source()
        hhmm = ts[11:16]
        return [
            "",
            self._center20("Kaffee-Counter"),
            self._center20(hhmm),
            "",
        ]

    def _render_lines_selection(self):
        product = self._current_product()
        price = int(product.get("price_cents", 0))
        return [
            "Produkt: {}".format(product.get("name", "?"))[:20],
            "Preis:  {} EUR".format(fmt_eur(price))[:20],
            "Karte halten..."[:20],
            "",
        ]

    def _show_standard_screen_once(self):
        if not self.lcd:
            return
        try:
            self.lcd.write_lines(self._render_lines_selection())
        except Exception:
            self.lcd = None

    def _render_lines_balance(self):
        if self._balance_prompt:
            return [
                "Kontostand",
                "Bitte Karte halten",
                "",
                "Timeout...",
            ]

        name = "?"
        if self._balance_user:
            name = self._balance_user.get("name", self._balance_user.get("user_id", "?"))

        return [
            "Kontostand",
            name[:20],
            "Saldo: {} EUR".format(fmt_eur(self._balance_cents))[:20],
            "OK",
        ]

    def _render_lines_undo(self):
        if not self._undo:
            return self._render_lines_idle()

        now = time.ticks_ms()
        ms_left = time.ticks_diff(self._undo["expires_ms"], now)
        if ms_left < 0:
            ms_left = 0
        sec_left = (ms_left + 999) // 1000

        return [
            "Gebucht: {} x{}".format(self._undo["product_name"], self._undo["qty"])[:20],
            "Betrag: {} EUR".format(fmt_eur(-self._undo["purchase"]["amount_cents"]))[:20],
            "Saldo:  {} EUR".format(fmt_eur(self._undo["balance_after"]))[:20],
            "Rot=Storno ({})".format(sec_left)[:20],
        ]

    def _render_lines_error(self):
        return [
            "Fehler",
            self._error_text[:20],
            "",
            "Weiter in kuerze",
        ]

    def _render_lines_balance_print(self):
        if not self._balance_user or not self.printer:
            return [
                "Druck nicht verfuegbar",
                "",
                "Rot = Zurueck",
                "",
            ]
        summary = self._get_balance_print_summary()
        if summary is None:
            summary = {"label": "-", "count": 0, "spent_cents": 0}
        return [
            "Logdruck {}".format(self._balance_user.get("name", "?"))[:20],
            "{}".format(summary.get("label", ""))[:20],
            "{}x {} EUR".format(summary.get("count", 0), fmt_eur(summary.get("spent_cents", 0)))[:20],
            "Gruen Druck Rot Exit",
        ]

    def _render_lines_ranking_kind(self):
        kind = self._ranking_kind()
        txt = "Woche"
        if kind == "month":
            txt = "Monat"
        elif kind == "year":
            txt = "Jahr"
        return [
            "Ranking Drucken",
            "Zeitraum: {}".format(txt)[:20],
            "Encoder waehlen",
            "Druck bestaetigt",
        ]

    def _render_lines_ranking_value(self):
        kind = self._ranking_kind()
        if kind == "week":
            val = "KW {:02d}/{}".format(self._ranking_value, self._ranking_year_ref)
        elif kind == "month":
            val = "Monat {:02d}/{}".format(self._ranking_value, self._ranking_year_ref)
        else:
            val = "Jahr {}".format(self._ranking_value)
        return [
            "Ranking Zeitraum",
            val[:20],
            "Encoder aendern",
            "Press=Vorschau",
        ]

    def _render_lines_ranking_preview(self):
        p = self._get_ranking_preview() or {}
        return [
            "Ranking Vorschau",
            "{}".format(p.get("label", "-"))[:20],
            "Buchungen: {}".format(p.get("booking_count", 0))[:20],
            "Gruen Druck Rot Exit",
        ]

    def _render(self, force=False):
        if not self.lcd:
            return

        if self.state == STATE_IDLE:
            if self._selection_mode:
                lines = self._render_lines_selection()
            else:
                lines = self._render_lines_idle()
        elif self.state == STATE_SHOW_BALANCE:
            lines = self._render_lines_balance()
        elif self.state == STATE_UNDO_WINDOW:
            lines = self._render_lines_undo()
        elif self.state == STATE_BALANCE_PRINT:
            lines = self._render_lines_balance_print()
        elif self.state == STATE_RANKING_KIND:
            lines = self._render_lines_ranking_kind()
        elif self.state == STATE_RANKING_VALUE:
            lines = self._render_lines_ranking_value()
        elif self.state == STATE_RANKING_PREVIEW:
            lines = self._render_lines_ranking_preview()
        else:
            lines = self._render_lines_error()

        key = "|".join(lines)
        if not force and key == self._render_cache and self.state != STATE_UNDO_WINDOW:
            return

        self._render_cache = key
        try:
            self.lcd.write_lines(lines)
        except Exception:
            self.lcd = None

    def run_forever(self):
        self.boot()

        while True:
            self._service_buzzer()
            self._poll_inputs()
            self._poll_nfc()

            processed = 0
            while self._events and processed < self._max_events_per_tick:
                event_type, value = self._pop_next_event()
                self._process_event(event_type, value)
                processed += 1

            self._state_timers()
            self.logger.tick()
            if self.printer:
                self.printer.tick()
            self._service_buzzer()
            self._update_feedback()
            self._update_screen_saver()

            self._render()
            time.sleep_ms(pins.UI_TICK_MS)
