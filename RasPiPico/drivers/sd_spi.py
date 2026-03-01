from machine import SPI, Pin
import os
import time


class SDCard:
    def __init__(self, spi, cs, max_baudrate=400000):
        self.spi = spi
        self.cs = cs if isinstance(cs, Pin) else Pin(cs, Pin.OUT)
        self.cs.init(self.cs.OUT, value=1)
        self.max_baudrate = int(max_baudrate)

        self.cmdbuf = bytearray(6)
        self.tokenbuf = bytearray(1)
        self.cdv = 0
        self.sectors = 0

        for _ in range(16):
            self.spi.write(b"\xFF")

        rc = self.init_card()
        if rc != 0:
            raise OSError("SD init failed rc={}".format(rc))

    def init_spi(self, baudrate):
        self.spi.init(baudrate=baudrate, phase=0, polarity=0)

    def cmd(self, cmd, arg, crc):
        self.cs(0)
        c = self.cmdbuf
        c[0] = 0x40 | cmd
        c[1] = (arg >> 24) & 0xFF
        c[2] = (arg >> 16) & 0xFF
        c[3] = (arg >> 8) & 0xFF
        c[4] = arg & 0xFF
        c[5] = crc
        self.spi.write(c)

        if cmd == 12:
            self.spi.readinto(self.tokenbuf, 0xFF)

        for _ in range(100):
            self.spi.readinto(self.tokenbuf, 0xFF)
            if (self.tokenbuf[0] & 0x80) == 0:
                return self.tokenbuf[0]

        self.cs(1)
        self.spi.write(b"\xFF")
        return -1

    def _read_data_token(self):
        for _ in range(20000):
            self.spi.readinto(self.tokenbuf, 0xFF)
            if self.tokenbuf[0] == 0xFE:
                return True
            time.sleep_us(50)
        return False

    def readinto(self, buf):
        self.cs(0)
        if not self._read_data_token():
            self.cs(1)
            self.spi.write(b"\xFF")
            return 1
        self.spi.readinto(buf, 0xFF)
        self.spi.readinto(self.tokenbuf, 0xFF)
        self.spi.readinto(self.tokenbuf, 0xFF)
        self.cs(1)
        self.spi.write(b"\xFF")
        return 0

    def write(self, token, buf):
        self.cs(0)
        self.spi.readinto(self.tokenbuf, 0xFF)
        self.spi.write(bytes([token]))
        self.spi.write(buf)
        self.spi.write(b"\xFF\xFF")
        self.spi.readinto(self.tokenbuf, 0xFF)
        if (self.tokenbuf[0] & 0x1F) != 0x05:
            self.cs(1)
            self.spi.write(b"\xFF")
            return 1

        while True:
            self.spi.readinto(self.tokenbuf, 0xFF)
            if self.tokenbuf[0] == 0xFF:
                break

        self.cs(1)
        self.spi.write(b"\xFF")
        return 0

    def init_card(self):
        self.init_spi(100000)

        ok = False
        for _ in range(20):
            if self.cmd(0, 0, 0x95) == 1:
                ok = True
                break
            self.cs(1)
            self.spi.write(b"\xFF" * 8)
            time.sleep_ms(20)
        if not ok:
            return 1

        r = self.cmd(8, 0x01AA, 0x87)
        if r == 1:
            ocr = bytearray(4)
            self.spi.readinto(ocr, 0xFF)
            self.cs(1)
            self.spi.write(b"\xFF")
            if ocr[2] != 0x01 or ocr[3] != 0xAA:
                return 2

            ready = False
            for _ in range(300):
                self.cmd(55, 0, 0)
                if self.cmd(41, 0x40000000, 0) == 0:
                    ready = True
                    break
                time.sleep_ms(10)
            if not ready:
                return 3

            if self.cmd(58, 0, 0) != 0:
                return 4
            self.spi.readinto(ocr, 0xFF)
            self.cs(1)
            self.spi.write(b"\xFF")
            self.cdv = 1 if (ocr[0] & 0x40) else 512
        else:
            self.cmd(55, 0, 0)
            if self.cmd(41, 0, 0) <= 1:
                ready = False
                for _ in range(300):
                    self.cmd(55, 0, 0)
                    if self.cmd(41, 0, 0) == 0:
                        ready = True
                        break
                    time.sleep_ms(10)
                if not ready:
                    return 5
            else:
                if self.cmd(1, 0, 0) > 1:
                    return 6
                ready = False
                for _ in range(300):
                    if self.cmd(1, 0, 0) == 0:
                        ready = True
                        break
                    time.sleep_ms(10)
                if not ready:
                    return 7

            if self.cmd(16, 512, 0) != 0:
                return 8
            self.cdv = 512

        if self.cmd(9, 0, 0) != 0:
            return 9
        csd = bytearray(16)
        if self.readinto(csd) != 0:
            return 10

        if (csd[0] & 0xC0) == 0x40:
            c_size = ((csd[7] & 0x3F) << 16) | (csd[8] << 8) | csd[9]
            self.sectors = (c_size + 1) * 1024
        else:
            c_size = ((csd[6] & 0x03) << 10) | (csd[7] << 2) | (csd[8] >> 6)
            c_size_mult = ((csd[9] & 0x03) << 1) | (csd[10] >> 7)
            read_bl_len = csd[5] & 0x0F
            block_nr = (c_size + 1) * (2 ** (c_size_mult + 2))
            block_len = 2 ** read_bl_len
            self.sectors = (block_nr * block_len) // 512

        self.init_spi(self.max_baudrate)
        return 0

    def readblocks(self, block_num, buf):
        nblocks = len(buf) // 512
        if nblocks == 1:
            if self.cmd(17, block_num * self.cdv, 0) != 0:
                self.cs(1)
                self.spi.write(b"\xFF")
                raise OSError("CMD17 failed")
            if self.readinto(buf) != 0:
                raise OSError("Read token timeout")
            return

        if self.cmd(18, block_num * self.cdv, 0) != 0:
            self.cs(1)
            self.spi.write(b"\xFF")
            raise OSError("CMD18 failed")

        offset = 0
        remaining = nblocks
        while remaining:
            if self.readinto(memoryview(buf)[offset: offset + 512]) != 0:
                raise OSError("Multi read timeout")
            offset += 512
            remaining -= 1

        self.cmd(12, 0, 0xFF)

    def writeblocks(self, block_num, buf):
        nblocks = len(buf) // 512
        if nblocks == 1:
            if self.cmd(24, block_num * self.cdv, 0) != 0:
                self.cs(1)
                self.spi.write(b"\xFF")
                raise OSError("CMD24 failed")
            if self.write(0xFE, buf) != 0:
                raise OSError("Single write failed")
            return

        if self.cmd(25, block_num * self.cdv, 0) != 0:
            self.cs(1)
            self.spi.write(b"\xFF")
            raise OSError("CMD25 failed")

        offset = 0
        remaining = nblocks
        while remaining:
            if self.write(0xFC, memoryview(buf)[offset: offset + 512]) != 0:
                raise OSError("Multi write failed")
            offset += 512
            remaining -= 1

        self.cs(0)
        self.spi.readinto(self.tokenbuf, 0xFF)
        self.spi.write(b"\xFD")
        while True:
            self.spi.readinto(self.tokenbuf, 0xFF)
            if self.tokenbuf[0] == 0xFF:
                break
        self.cs(1)
        self.spi.write(b"\xFF")

    def ioctl(self, op, arg):
        if op == 3:
            return self.sectors
        if op == 4:
            return 512
        if op in (5, 6):
            return 0
        return 0


class SDSpi:
    def __init__(self, spi_id, pin_sck, pin_mosi, pin_miso, pin_cs, init_baud=100000, max_baud=400000):
        self.spi = SPI(
            spi_id,
            baudrate=init_baud,
            polarity=0,
            phase=0,
            sck=Pin(pin_sck),
            mosi=Pin(pin_mosi),
            miso=Pin(pin_miso),
        )
        self.pin_cs = pin_cs
        self.max_baud = max_baud
        self.card = None
        self.vfs = None

    def mount(self, mount_point="/sd"):
        self.card = SDCard(self.spi, Pin(self.pin_cs, Pin.OUT), max_baudrate=self.max_baud)
        self.vfs = os.VfsFat(self.card)
        os.mount(self.vfs, mount_point)
        return True

    @staticmethod
    def ensure_dirs(paths):
        for path in paths:
            try:
                os.mkdir(path)
            except OSError:
                pass

    @staticmethod
    def is_mounted(path="/sd"):
        try:
            os.listdir(path)
            return True
        except OSError:
            return False
