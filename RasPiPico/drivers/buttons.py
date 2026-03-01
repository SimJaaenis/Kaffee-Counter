from machine import Pin
import time


class DebouncedButton:
    def __init__(self, pin, active_low=True, pull_up=True, debounce_ms=30):
        mode = Pin.PULL_UP if pull_up else Pin.PULL_DOWN
        self.pin = Pin(pin, Pin.IN, mode)
        self.active_low = bool(active_low)
        self.debounce_ms = int(debounce_ms)

        self._stable = self._raw_pressed()
        self._last_raw = self._stable
        self._last_change = time.ticks_ms()

    def _raw_pressed(self):
        value = self.pin.value()
        return value == 0 if self.active_low else value == 1

    def update(self):
        now = time.ticks_ms()
        raw = self._raw_pressed()
        changed = False

        if raw != self._last_raw:
            self._last_raw = raw
            self._last_change = now

        if raw != self._stable and time.ticks_diff(now, self._last_change) >= self.debounce_ms:
            self._stable = raw
            changed = True

        return changed

    def is_pressed(self):
        return self._stable


class ButtonPanel:
    def __init__(
        self,
        pin_green,
        pin_white,
        pin_red,
        long_press_ms=1500,
        backup_press_ms=None,
        combo_press_ms=5000,
        debounce_ms=30,
    ):
        self.green = DebouncedButton(pin_green, debounce_ms=debounce_ms)
        self.white = DebouncedButton(pin_white, debounce_ms=debounce_ms)
        self.red = DebouncedButton(pin_red, debounce_ms=debounce_ms)
        self.long_press_ms = int(long_press_ms)
        self.backup_press_ms = int(backup_press_ms) if backup_press_ms is not None else None

        self._red_press_ts = None
        self._red_long_emitted = False
        self._red_backup_emitted = False
        self._combo_press_ts = None
        self._combo_long_emitted = False
        self.combo_press_ms = int(combo_press_ms)

    def poll_events(self):
        events = []
        now = time.ticks_ms()

        green_changed = self.green.update()
        white_changed = self.white.update()
        combo_pressed = self.green.is_pressed() and self.white.is_pressed()

        if green_changed and self.green.is_pressed() and not combo_pressed:
            events.append("btn_green")

        if white_changed and self.white.is_pressed() and not combo_pressed:
            events.append("btn_white")

        if combo_pressed:
            if self._combo_press_ts is None:
                self._combo_press_ts = now
                self._combo_long_emitted = False
            if (not self._combo_long_emitted) and time.ticks_diff(now, self._combo_press_ts) >= self.combo_press_ms:
                self._combo_long_emitted = True
                events.append("btn_white_green_long")
        else:
            self._combo_press_ts = None
            self._combo_long_emitted = False

        red_changed = self.red.update()

        if red_changed and self.red.is_pressed():
            events.append("btn_red_press")
            self._red_press_ts = now
            self._red_long_emitted = False
            self._red_backup_emitted = False

        if self.red.is_pressed() and self._red_press_ts is not None and not self._red_long_emitted:
            if time.ticks_diff(now, self._red_press_ts) >= self.long_press_ms:
                self._red_long_emitted = True
                events.append("btn_red_long")
        if (
            self.red.is_pressed()
            and self._red_press_ts is not None
            and self.backup_press_ms is not None
            and not self._red_backup_emitted
        ):
            if time.ticks_diff(now, self._red_press_ts) >= self.backup_press_ms:
                self._red_backup_emitted = True
                events.append("btn_red_backup")

        if red_changed and not self.red.is_pressed():
            if not self._red_long_emitted:
                events.append("btn_red_short")
            self._red_press_ts = None
            self._red_long_emitted = False
            self._red_backup_emitted = False

        return events
