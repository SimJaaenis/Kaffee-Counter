from machine import Pin
import time
import machine

_TRANSITION_DELTA = (
    0,  # 00->00
    1,  # 00->01
    -1, # 00->10
    0,  # 00->11 (invalid)
    -1, # 01->00
    0,  # 01->01
    0,  # 01->10 (invalid)
    1,  # 01->11
    1,  # 10->00
    0,  # 10->01 (invalid)
    0,  # 10->10
    -1, # 10->11
    0,  # 11->00 (invalid)
    -1, # 11->01
    1,  # 11->10
    0,  # 11->11
)


class EncoderKY040:
    def __init__(
        self,
        pin_clk,
        pin_dt,
        pin_sw,
        debounce_ms=2,
        button_debounce_ms=25,
        button_long_ms=5000,
        steps_per_detent=2,
        reversal_guard_ms=8,
    ):
        self._clk = Pin(pin_clk, Pin.IN, Pin.PULL_UP)
        self._dt = Pin(pin_dt, Pin.IN, Pin.PULL_UP)
        self._sw = Pin(pin_sw, Pin.IN, Pin.PULL_UP)
        self._debounce_ms = int(debounce_ms)
        self._last_move = time.ticks_ms()
        self._steps_per_detent = max(1, int(steps_per_detent))
        self._reversal_guard_ms = max(0, int(reversal_guard_ms))
        self._pending_steps = 0
        self._accum = 0
        self._last_dir = 0
        self._last_dir_ms = time.ticks_ms()
        self._last_ab = (self._clk.value() << 1) | self._dt.value()

        self._btn_state = self._sw.value()
        self._btn_last_change = time.ticks_ms()
        self._btn_debounce_ms = int(button_debounce_ms)
        self._btn_long_ms = int(button_long_ms)
        self._btn_press_ts = None
        self._btn_long_emitted = False

        # Read both channels and decode Gray-code transitions.
        trig = Pin.IRQ_RISING | Pin.IRQ_FALLING
        self._clk.irq(trigger=trig, handler=self._on_ab_change)
        self._dt.irq(trigger=trig, handler=self._on_ab_change)

    def _on_ab_change(self, _pin):
        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_move) < self._debounce_ms:
            return
        self._last_move = now

        ab = (self._clk.value() << 1) | self._dt.value()
        transition = (self._last_ab << 2) | ab
        self._last_ab = ab
        direction = _TRANSITION_DELTA[transition]
        if direction == 0:
            return

        if self._last_dir and direction != self._last_dir:
            # Very fast direction reversals are usually contact bounce.
            if time.ticks_diff(now, self._last_dir_ms) < self._reversal_guard_ms:
                return
        self._last_dir = direction
        self._last_dir_ms = now
        self._pending_steps += direction

    def poll(self):
        events = []
        now = time.ticks_ms()

        irq_state = machine.disable_irq()
        pending = self._pending_steps
        self._pending_steps = 0
        machine.enable_irq(irq_state)
        if pending:
            self._accum += pending
            while self._accum >= self._steps_per_detent:
                self._accum -= self._steps_per_detent
                events.append(("enc_delta", 1))
            while self._accum <= -self._steps_per_detent:
                self._accum += self._steps_per_detent
                events.append(("enc_delta", -1))

        btn_now = self._sw.value()
        if btn_now != self._btn_state and time.ticks_diff(now, self._btn_last_change) >= self._btn_debounce_ms:
            self._btn_state = btn_now
            self._btn_last_change = now
            if btn_now == 0:
                events.append(("enc_press", 1))
                self._btn_press_ts = now
                self._btn_long_emitted = False
            else:
                self._btn_press_ts = None
                self._btn_long_emitted = False

        if self._btn_state == 0 and self._btn_press_ts is not None and not self._btn_long_emitted:
            if time.ticks_diff(now, self._btn_press_ts) >= self._btn_long_ms:
                self._btn_long_emitted = True
                events.append(("enc_long", 1))

        return events
