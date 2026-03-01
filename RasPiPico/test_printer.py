from machine import Pin
import time

from drivers.escpos import EscPosPrinter

# Pinbelegung (anpassbar):
# Pico GP0 (UART0 TX) -> HW-044 RXD (TTL)
# Pico GP1 (UART0 RX) -> HW-044 TXD (TTL) [optional]
# Taste zwischen GP15 und GND (interner Pull-up aktiv)

BUTTON_PIN = 2
ENABLE_PRINT = True  # Fuer reinen Tastertest auf True/False setzen

printer = EscPosPrinter(
    uart_id=1,
    baudrate=9600,
    tx_pin=8,
    rx_pin=9,
)

button = Pin(BUTTON_PIN, Pin.IN, Pin.PULL_UP)
try:
    led = Pin("LED", Pin.OUT)  # Pico W
except Exception:
    led = Pin(25, Pin.OUT)  # Fallback
led.off()


print("Bereit: Taste druecken fuer Testdruck.")
print("Druckmodus:", "AKTIV" if ENABLE_PRINT else "AUS")

last_raw_state = button.value()
stable_state = last_raw_state
last_change_ms = time.ticks_ms()
debounce_ms = 40

while True:
    now = time.ticks_ms()
    current_raw_state = button.value()

    if current_raw_state != last_raw_state:
        last_change_ms = now

    if time.ticks_diff(now, last_change_ms) > debounce_ms:
        if current_raw_state != stable_state:
            previous_stable_state = stable_state
            stable_state = current_raw_state

            # Flanke high -> low bedeutet Taster wurde gedrueckt.
            if previous_stable_state == 1 and stable_state == 0:
                print("Taste erkannt.")
                if ENABLE_PRINT:
                    print("Sende Testdruck...")
                    try:
                        printer.test_print()
                        print("Testdruck gesendet.")
                    except Exception as exc:
                        print("Druckfehler:", exc)

    led.value(1 if stable_state == 0 else 0)

    last_raw_state = current_raw_state
    time.sleep_ms(10)
