"""
ESC/POS helper for Epson TM-T88III via UART.
Compatible with MicroPython on Raspberry Pi Pico.
"""

from machine import UART
import time


class EscPosPrinter:
    def __init__(self, uart_id=0, baudrate=9600, tx_pin=0, rx_pin=1, timeout_ms=1000):
        self.uart = UART(
            uart_id,
            baudrate=baudrate,
            bits=8,
            parity=None,
            stop=1,
            tx=tx_pin,
            rx=rx_pin,
            timeout=timeout_ms,
        )

    def _write(self, data):
        if isinstance(data, str):
            try:
                data = data.encode("cp437")
            except Exception:
                data = data.encode("latin-1", "replace")
        self.uart.write(data)

    def initialize(self):
        # ESC @ (initialize printer)
        self._write(b"\x1b@")

    def align(self, mode="left"):
        # ESC a n
        modes = {"left": 0, "center": 1, "right": 2}
        self._write(bytes([0x1B, 0x61, modes.get(mode, 0)]))

    def bold(self, enabled=True):
        # ESC E n
        self._write(bytes([0x1B, 0x45, 1 if enabled else 0]))

    def size(self, width=1, height=1):
        # GS ! n  (1..8)
        width = min(max(width, 1), 8)
        height = min(max(height, 1), 8)
        n = ((width - 1) << 4) | (height - 1)
        self._write(bytes([0x1D, 0x21, n]))

    def text(self, value=""):
        self._write(value)

    def newline(self, count=1):
        self._write(b"\n" * max(count, 1))

    def cut(self, full=False):
        # GS V m
        self._write(bytes([0x1D, 0x56, 0x00 if full else 0x01]))

    def feed(self, lines=3):
        # ESC d n
        self._write(bytes([0x1B, 0x64, max(0, min(lines, 255))]))

    def test_print(self):
        self.initialize()
        time.sleep_ms(50)

        self.align("center")
        self.bold(True)
        self.size(2, 2)
        self.text("TESTDRUCK")
        self.newline(1)

        self.size(1, 1)
        self.bold(False)
        self.text("Epson TM-T88III")
        self.newline(1)

        self.text("Raspberry Pi Pico + MicroPython")
        self.newline(1)
        self.text("Taste gedrueckt -> Druck OK")
        self.newline(2)

        self.feed(3)
        self.cut(full=False)
