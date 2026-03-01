from machine import PWM, Pin
import time

try:
    import _thread
except Exception:
    _thread = None

NOTE_E = 660
NOTE_A = 880
NOTE_AS = 932
NOTE_H = 988


class BuzzerPwm:
    class _NoopLock:
        def acquire(self):
            return True

        def release(self):
            return True

    def __init__(self, pin, duty_u16=18000, thread_enabled=True):
        self._pwm = PWM(Pin(pin))
        self._duty = int(duty_u16)
        self._pwm.duty_u16(0)
        self._queue = []
        self._active_until_ms = 0
        self._is_active = False
        self._queue_lock = None
        self._pwm_lock = None
        self._running = False
        self._thread_mode = bool(thread_enabled and _thread is not None)

        if self._thread_mode:
            try:
                self._queue_lock = _thread.allocate_lock()
                self._pwm_lock = _thread.allocate_lock()
                self._running = True
                _thread.start_new_thread(self._worker_loop, ())
            except Exception:
                self._thread_mode = False
                self._queue_lock = self._NoopLock()
                self._pwm_lock = self._NoopLock()
        else:
            self._queue_lock = self._NoopLock()
            self._pwm_lock = self._NoopLock()

    def _worker_loop(self):
        while self._running:
            item = None
            self._queue_lock.acquire()
            try:
                if self._queue:
                    item = self._queue.pop(0)
            finally:
                self._queue_lock.release()

            if item is None:
                time.sleep_ms(2)
                continue

            freq, dur = item
            if freq > 0:
                self._pwm_lock.acquire()
                try:
                    self._pwm.freq(int(freq))
                    self._pwm.duty_u16(self._duty)
                finally:
                    self._pwm_lock.release()
                time.sleep_ms(int(dur))
                self._pwm_lock.acquire()
                try:
                    self._pwm.duty_u16(0)
                finally:
                    self._pwm_lock.release()
            else:
                time.sleep_ms(int(dur))

    def tone(self, freq_hz, duration_ms):
        self._pwm_lock.acquire()
        try:
            self._pwm.freq(int(freq_hz))
            self._pwm.duty_u16(self._duty)
            time.sleep_ms(int(duration_ms))
            self._pwm.duty_u16(0)
        finally:
            self._pwm_lock.release()

    def play(self, sequence):
        for freq, dur in sequence:
            if freq <= 0:
                time.sleep_ms(int(dur))
            else:
                self.tone(freq, dur)

    def success(self):
        self.play(
            [
                (NOTE_H, 80),
                (0, 4),
                (NOTE_A, 80),
                (0, 4),
                (NOTE_AS, 80),
                (0, 4),
                (NOTE_E, 160),
            ]
        )

    def error(self):
        self.tone(300, 250)

    def click(self):
        self.tone(1500, 10)

    def _enqueue(self, sequence):
        self._queue_lock.acquire()
        try:
            for freq, dur in sequence:
                self._queue.append((int(freq), int(dur)))
        finally:
            self._queue_lock.release()

    def clear_queue(self):
        self._queue_lock.acquire()
        try:
            self._queue = []
        finally:
            self._queue_lock.release()

    def play_async(self, sequence, clear=False):
        if clear:
            self.clear_queue()
        self._enqueue(sequence or [])

    def click_async(self):
        # Prevent long queued click trails while rotating encoder quickly.
        queued = False
        self._queue_lock.acquire()
        try:
            queued = bool(self._queue)
        finally:
            self._queue_lock.release()
        if self._is_active or queued:
            return
        self._enqueue([(1500, 8)])

    def confirm_async(self):
        self._enqueue(
            [
                (NOTE_H, 120),
                (0, 4),
                (NOTE_A, 120),
                (0, 4),
                (NOTE_AS, 120),
                (0, 4),
                (NOTE_E, 160),
            ]
        )

    def balance_async(self):
        self._enqueue([(1200, 20)])

    def success_async(self):
        self.confirm_async()

    def error_async(self):
        self._enqueue([(300, 250)])

    def tick(self):
        if self._thread_mode:
            return

        now = time.ticks_ms()
        if self._is_active and time.ticks_diff(now, self._active_until_ms) >= 0:
            self._pwm.duty_u16(0)
            self._is_active = False

        if self._is_active:
            return

        if not self._queue:
            return

        freq, dur = self._queue.pop(0)
        if freq > 0:
            self._pwm.freq(freq)
            self._pwm.duty_u16(self._duty)
            self._is_active = True
            self._active_until_ms = time.ticks_add(now, dur)
        else:
            self._is_active = True
            self._active_until_ms = time.ticks_add(now, dur)

    def deinit(self):
        self._running = False
        self._pwm.duty_u16(0)
        self._pwm.deinit()
