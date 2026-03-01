from machine import PWM, Pin


class RgbPwm:
    def __init__(self, pin_r, pin_g, pin_b, freq_hz=1000, invert=False):
        self._r = PWM(Pin(pin_r))
        self._g = PWM(Pin(pin_g))
        self._b = PWM(Pin(pin_b))
        self._invert = bool(invert)
        self._brightness = 255
        self._base_rgb = (0, 0, 0)

        self._r.freq(freq_hz)
        self._g.freq(freq_hz)
        self._b.freq(freq_hz)
        self.set_rgb(0, 0, 0)

    @staticmethod
    def _to_u16(value_0_255):
        value = int(value_0_255)
        if value < 0:
            value = 0
        if value > 255:
            value = 255
        return value * 257

    def set_brightness(self, brightness_0_255):
        b = int(brightness_0_255)
        if b < 0:
            b = 0
        if b > 255:
            b = 255
        self._brightness = b
        self._apply_rgb()

    def _apply_rgb(self):
        r, g, b = self._base_rgb
        r = (int(r) * self._brightness) // 255
        g = (int(g) * self._brightness) // 255
        b = (int(b) * self._brightness) // 255
        if self._invert:
            r = 255 - int(r)
            g = 255 - int(g)
            b = 255 - int(b)
        self._r.duty_u16(self._to_u16(r))
        self._g.duty_u16(self._to_u16(g))
        self._b.duty_u16(self._to_u16(b))

    def set_rgb(self, r, g, b):
        self._base_rgb = (int(r), int(g), int(b))
        self._apply_rgb()

    def set_named(self, name):
        name = (name or "").lower()
        if name == "idle":
            self.set_rgb(90, 90, 90)
        elif name == "success":
            self.set_rgb(0, 220, 0)
        elif name == "error":
            self.set_rgb(220, 0, 0)
        elif name == "admin":
            self.set_rgb(0, 0, 220)
        elif name == "off":
            self.set_rgb(0, 0, 0)

    def off(self):
        self.set_rgb(0, 0, 0)

    def deinit(self):
        self.off()
        self._r.deinit()
        self._g.deinit()
        self._b.deinit()
