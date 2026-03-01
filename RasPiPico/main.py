from machine import Pin
import time

import config_pins as pins
from drivers.sd_spi import SDSpi
from drivers.rgb_pwm import RgbPwm
from drivers.buzzer_pwm import BuzzerPwm
from drivers.i2c_lcd_20x4_pcf8574 import I2cLcd20x4
from drivers.rtc_ds1307 import DS1307Clock
from store import Store
from logger import LoggerQueue
from kiosk import KioskApp
from admin_portal import AdminPortal
from printer_service import PrinterService
from machine import I2C


def read_boot_flags():
    white = Pin(pins.BTN_WHITE_PIN, Pin.IN, Pin.PULL_UP)
    red = Pin(pins.BTN_RED_PIN, Pin.IN, Pin.PULL_UP)
    sample_ms = 20
    check_ms = int(getattr(pins, "BOOT_CHECK_MS", 3600))
    red_hold_ms = int(getattr(pins, "RED_BACKUP_HOLD_MS", 3000))
    start = time.ticks_ms()
    white_low = 0
    red_low = 0
    sample_count = 0

    while time.ticks_diff(time.ticks_ms(), start) < check_ms:
        if white.value() == 0:
            white_low += 1
        if red.value() == 0:
            red_low += 1
        sample_count += 1
        time.sleep_ms(sample_ms)

    white_ratio = (white_low * 100) // sample_count if sample_count else 0
    red_ratio = (red_low * 100) // sample_count if sample_count else 0
    print(
        "Boot-Check GP{}(white) LOW {}/{} ({}%), GP{}(red) LOW {}/{} ({}%)".format(
            pins.BTN_WHITE_PIN, white_low, sample_count, white_ratio,
            pins.BTN_RED_PIN, red_low, sample_count, red_ratio,
        )
    )

    admin_mode = white_low >= 10
    red_threshold = max(1, red_hold_ms // sample_ms)
    import_sd = red_low >= red_threshold
    return admin_mode, import_sd


def try_mount_sd():
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
        sd.mount(pins.SD_MOUNT_POINT)
        sd.ensure_dirs(
            [
                "{}/config".format(pins.SD_MOUNT_POINT),
                "{}/logs".format(pins.SD_MOUNT_POINT),
                "{}/backup".format(pins.SD_MOUNT_POINT),
            ]
        )
        return True
    except Exception as exc:
        print("SD mount failed:", exc)
        return False


def sync_system_time_from_rtc():
    try:
        i2c = I2C(
            pins.I2C_ID,
            sda=Pin(pins.I2C_SDA_PIN),
            scl=Pin(pins.I2C_SCL_PIN),
            freq=pins.I2C_FREQ,
        )
        rtc = DS1307Clock(i2c, address=pins.RTC_ADDR)
        if not rtc.available():
            print("RTC Sync: DS1307 nicht gefunden")
            return False
        dt = rtc.read_datetime()
        if dt is None:
            print("RTC Sync: Lesen fehlgeschlagen")
            return False
        print(
            "RTC Sync ok: {:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(
                dt[0], dt[1], dt[2], dt[4], dt[5], dt[6]
            )
        )
        return True
    except Exception as exc:
        print("RTC Sync Fehler:", exc)
        return False


def show_boot_status_lcd(admin_mode, import_sd, sd_ready):
    try:
        i2c = I2C(
            pins.I2C_ID,
            sda=Pin(pins.I2C_SDA_PIN),
            scl=Pin(pins.I2C_SCL_PIN),
            freq=pins.I2C_FREQ,
        )
        lcd = I2cLcd20x4(
            i2c,
            i2c_addr=pins.LCD_ADDR,
            num_lines=pins.LCD_ROWS,
            num_columns=pins.LCD_COLS,
        )
        lcd.clear()
        lcd.move_to(0, 0)
        lcd.putstr("Boot-Status")
        lcd.move_to(0, 1)
        lcd.putstr("Mode: {}".format("ADMIN" if admin_mode else "KIOSK")[:20])
        lcd.move_to(0, 2)
        lcd.putstr("SD: {}".format("OK" if sd_ready else "FEHLT")[:20])
        lcd.move_to(0, 3)
        lcd.putstr("SD-Import: {}".format("EIN" if import_sd else "AUS")[:20])
        time.sleep_ms(1200)
    except Exception:
        pass


def main():
    # Ensure Pico system RTC is set as early as possible from DS1307.
    sync_system_time_from_rtc()

    admin_mode, import_sd = read_boot_flags()

    sd_ready = try_mount_sd()
    store = Store(root=pins.INTERNAL_DATA_ROOT, sd_ready=sd_ready, sd_root=pins.SD_MOUNT_POINT)
    if sd_ready and import_sd:
        ok, copied, failed = store.sync_sd_to_internal()
        print("SD->intern import (manual red hold):", ok, "copied=", copied, "failed=", failed)
    else:
        print("SD import skipped; internal config remains source-of-truth")
    store.load_all()
    show_boot_status_lcd(admin_mode, import_sd, sd_ready)

    logger = LoggerQueue(max_queue=pins.MAX_LOG_QUEUE, max_ram_entries=pins.MAX_RAM_LOG_ENTRIES)
    printer = PrinterService(store)

    if admin_mode:
        print("Boot mode: ADMIN")
        lcd = None
        try:
            i2c = I2C(
                pins.I2C_ID,
                sda=Pin(pins.I2C_SDA_PIN),
                scl=Pin(pins.I2C_SCL_PIN),
                freq=pins.I2C_FREQ,
            )
            lcd = I2cLcd20x4(
                i2c,
                i2c_addr=pins.LCD_ADDR,
                num_lines=pins.LCD_ROWS,
                num_columns=pins.LCD_COLS,
            )
        except Exception:
            lcd = None

        rgb = RgbPwm(
            pins.RGB_R_PIN,
            pins.RGB_G_PIN,
            pins.RGB_B_PIN,
            freq_hz=pins.RGB_PWM_FREQ,
            invert=store.rgb_invert(),
        )
        buzzer = BuzzerPwm(pins.BUZZER_PIN)
        portal = AdminPortal(store, logger, rgb=rgb, lcd=lcd, buzzer=buzzer, printer=printer)
        try:
            portal.run_forever()
        except Exception as exc:
            print("Admin-Start fehlgeschlagen:", exc)
            try:
                buzzer.error()
            except Exception:
                pass
            if lcd is not None:
                try:
                    lcd.clear()
                    lcd.move_to(0, 0)
                    lcd.putstr("Admin AP Fehler")
                    lcd.move_to(0, 1)
                    lcd.putstr("SSID fallback pruefen")
                    lcd.move_to(0, 2)
                    lcd.putstr("Konsole ansehen")
                except Exception:
                    pass
            # Fallback auf Kiosk statt still zu haengen.
            app = KioskApp(store, logger, printer=printer)
            app.run_forever()
        return

    print("Boot mode: KIOSK")
    app = KioskApp(store, logger, printer=printer)
    app.run_forever()


main()
