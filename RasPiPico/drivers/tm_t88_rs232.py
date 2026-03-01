from machine import Pin, UART
import time


class TmT88Rs232:
    def __init__(self, uart_id, tx_pin, rx_pin=None, baudrate=9600, timeout_ms=100):
        kwargs = {
            "baudrate": int(baudrate),
            "bits": 8,
            "parity": None,
            "stop": 1,
            "timeout": int(timeout_ms),
            "tx": Pin(int(tx_pin)),
        }
        if rx_pin is not None and int(rx_pin) >= 0:
            kwargs["rx"] = Pin(int(rx_pin))
        self.uart = UART(int(uart_id), **kwargs)

    def _w(self, data):
        if not data:
            return
        self.uart.write(data)

    def reset(self):
        self._w(b"\x1b\x40")

    def align(self, mode):
        if mode == "center":
            self._w(b"\x1b\x61\x01")
        elif mode == "right":
            self._w(b"\x1b\x61\x02")
        else:
            self._w(b"\x1b\x61\x00")

    def bold(self, enabled):
        self._w(b"\x1b\x45\x01" if enabled else b"\x1b\x45\x00")

    def invert(self, enabled):
        # GS B n: white/black reverse print mode.
        self._w(b"\x1d\x42\x01" if enabled else b"\x1d\x42\x00")

    def text(self, s):
        if s is None:
            return
        try:
            b = str(s).encode("cp437", "replace")
        except Exception:
            b = str(s).encode("ascii", "replace")
        self._w(b)

    def line(self, s=""):
        self.text(s)
        self._w(b"\r\n")

    def hr(self, width=42):
        self.line("-" * int(width))

    def feed(self, n=1):
        self._w(b"\n" * int(n))

    def cut(self):
        # GS V 66 0 full cut
        self._w(b"\x1d\x56\x42\x00")

    def print_receipt(self, title, lines, footer=None):
        self.reset()
        self.align("center")
        self.bold(True)
        self.line(title or "Kaffee-Counter")
        self.bold(False)
        self.align("left")
        self.hr()
        for item in lines or []:
            self.line(item)
        self.hr()
        if footer:
            self.align("center")
            self.line(footer)
            self.align("left")
        self.feed(3)
        time.sleep_ms(80)
        self.cut()

    def print_test_page(self):
        self.print_receipt(
            "Kaffee-Counter",
            [
                "Drucker-Test",
                "Epson TM-T88III RS232",
                "Verbindung OK",
            ],
            footer="Testseite",
        )
