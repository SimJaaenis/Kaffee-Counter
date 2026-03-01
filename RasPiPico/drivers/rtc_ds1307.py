from machine import RTC
import time


def _bcd2bin(value):
    return value - 6 * (value >> 4)


def _bin2bcd(value):
    return value + 6 * (value // 10)


class DS1307Clock:
    def __init__(self, i2c, address=0x68):
        self.i2c = i2c
        self.address = address
        self._rtc = RTC()

    def available(self):
        try:
            devices = self.i2c.scan()
            return self.address in devices
        except Exception:
            return False

    def read_datetime(self):
        try:
            data = self.i2c.readfrom_mem(self.address, 0x00, 7)
            second = _bcd2bin(data[0] & 0x7F)
            minute = _bcd2bin(data[1] & 0x7F)
            hour = _bcd2bin(data[2] & 0x3F)
            weekday = max(0, _bcd2bin(data[3] & 0x07) - 1)
            day = _bcd2bin(data[4] & 0x3F)
            month = _bcd2bin(data[5] & 0x1F)
            year = 2000 + _bcd2bin(data[6])

            self._rtc.datetime((year, month, day, weekday, hour, minute, second, 0))
            return (year, month, day, weekday, hour, minute, second)
        except Exception:
            return None

    def set_datetime(self, year, month, day, weekday, hour, minute, second):
        try:
            data = bytearray(7)
            data[0] = _bin2bcd(second)
            data[1] = _bin2bcd(minute)
            data[2] = _bin2bcd(hour)
            data[3] = _bin2bcd((weekday % 7) + 1)
            data[4] = _bin2bcd(day)
            data[5] = _bin2bcd(month)
            data[6] = _bin2bcd(year - 2000)
            self.i2c.writeto_mem(self.address, 0x00, data)
            self._rtc.datetime((year, month, day, weekday, hour, minute, second, 0))
            return True
        except Exception:
            return False

    def _fmt(self, dt):
        return "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(
            dt[0], dt[1], dt[2], dt[4], dt[5], dt[6]
        )

    def timestamp_with_source(self):
        dt = self.read_datetime()
        if dt:
            return self._fmt(dt), "rtc"

        try:
            lt = time.localtime()
            # year plausibility check
            if lt[0] >= 2020:
                return self._fmt((lt[0], lt[1], lt[2], lt[6], lt[3], lt[4], lt[5])), "local"
        except Exception:
            pass

        pseudo_s = time.ticks_ms() // 1000
        sec = pseudo_s % 60
        minute = (pseudo_s // 60) % 60
        hour = (pseudo_s // 3600) % 24
        return "1970-01-01 {:02d}:{:02d}:{:02d}".format(hour, minute, sec), "ticks"
