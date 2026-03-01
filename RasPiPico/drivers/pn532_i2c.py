import time

try:
    from micropython import const
except Exception:
    def const(x):
        return x


_PREAMBLE = const(0x00)
_STARTCODE1 = const(0x00)
_STARTCODE2 = const(0xFF)
_POSTAMBLE = const(0x00)

_HOSTTOPN532 = const(0xD4)
_PN532TOHOST = const(0xD5)

_COMMAND_GETFIRMWAREVERSION = const(0x02)
_COMMAND_SAMCONFIGURATION = const(0x14)
_COMMAND_INLISTPASSIVETARGET = const(0x4A)

_MIFARE_ISO14443A = const(0x00)
_ACK = b"\x00\x00\xFF\x00\xFF\x00"


class BusyError(Exception):
    pass


class PN532Base:
    def __init__(self, debug=False):
        self.debug = debug
        self.low_power = False

    def _read_data(self, count):
        raise NotImplementedError

    def _write_data(self, framebytes):
        raise NotImplementedError

    def _wait_ready(self, timeout):
        raise NotImplementedError

    def _write_frame(self, data):
        if data is None or not (1 < len(data) < 255):
            raise ValueError("Data length must be 2..254")
        length = len(data)
        frame = bytearray(length + 8)
        frame[0] = _PREAMBLE
        frame[1] = _STARTCODE1
        frame[2] = _STARTCODE2
        frame[3] = length & 0xFF
        frame[4] = (~length + 1) & 0xFF
        frame[5:-2] = data
        # DCS so that sum(TFI..DATA..DCS) == 0 (mod 256)
        frame[-2] = (-sum(data)) & 0xFF
        frame[-1] = _POSTAMBLE
        self._write_data(frame)

    def _read_frame(self, length):
        response = self._read_data(length + 7)
        offset = 0
        while offset < len(response) and response[offset] == 0x00:
            offset += 1
        if offset >= len(response) or response[offset] != 0xFF:
            raise RuntimeError("PN532 frame preamble invalid")
        offset += 1
        if offset + 1 >= len(response):
            raise RuntimeError("PN532 frame too short")

        frame_len = response[offset]
        if ((frame_len + response[offset + 1]) & 0xFF) != 0:
            raise RuntimeError("PN532 frame length checksum mismatch")

        payload = response[offset + 2: offset + 2 + frame_len]
        checksum = sum(payload) + response[offset + 2 + frame_len]
        if (checksum & 0xFF) != 0:
            raise RuntimeError("PN532 payload checksum mismatch")
        return payload

    def send_command(self, command, params=b"", timeout=1.0):
        data = bytearray(2 + len(params))
        data[0] = _HOSTTOPN532
        data[1] = command & 0xFF
        for i, value in enumerate(params):
            data[2 + i] = value

        self._write_frame(data)

        if not self._wait_ready(timeout):
            return False
        if self._read_data(len(_ACK)) != _ACK:
            raise RuntimeError("PN532 ACK missing")
        return True

    def process_response(self, command, response_length=0, timeout=1.0):
        if not self._wait_ready(timeout):
            return None
        response = self._read_frame(response_length + 2)
        if not (response[0] == _PN532TOHOST and response[1] == (command + 1)):
            raise RuntimeError("Unexpected PN532 response")
        return response[2:]

    def call_function(self, command, response_length=0, params=b"", timeout=1.0):
        if not self.send_command(command, params=params, timeout=timeout):
            return None
        return self.process_response(command, response_length=response_length, timeout=timeout)

    @property
    def firmware_version(self):
        response = self.call_function(_COMMAND_GETFIRMWAREVERSION, 4, timeout=0.6)
        if response is None:
            raise RuntimeError("PN532 not responding")
        return tuple(response)

    def SAM_configuration(self):
        self.call_function(_COMMAND_SAMCONFIGURATION, params=[0x01, 0x14, 0x01])

    def read_passive_target(self, card_baud=_MIFARE_ISO14443A, timeout=0.4):
        try:
            sent = self.send_command(_COMMAND_INLISTPASSIVETARGET, params=[0x01, card_baud], timeout=timeout)
        except BusyError:
            return None
        if not sent:
            return None

        response = self.process_response(_COMMAND_INLISTPASSIVETARGET, response_length=30, timeout=timeout)
        if response is None:
            return None
        if response[0] != 0x01:
            return None
        uid_len = response[5]
        if uid_len > 10:
            return None
        return response[6:6 + uid_len]


class PN532I2C(PN532Base):
    def __init__(self, i2c, address=0x24, debug=False, on_wait=None):
        self._i2c = i2c
        self._address = address
        self._on_wait = on_wait
        super().__init__(debug=debug)
        self.SAM_configuration()

    def _wait_ready(self, timeout=1.0):
        status = bytearray(1)
        start = time.ticks_ms()
        timeout_ms = int(timeout * 1000)
        while time.ticks_diff(time.ticks_ms(), start) < timeout_ms:
            try:
                self._i2c.readfrom_into(self._address, status)
                if status[0] == 0x01:
                    return True
            except Exception:
                pass
            if self._on_wait is not None:
                try:
                    self._on_wait()
                except Exception:
                    pass
            time.sleep_ms(8)
        return False

    def _read_data(self, count):
        frame = bytearray(count + 1)
        self._i2c.readfrom_into(self._address, frame)
        if frame[0] != 0x01:
            raise BusyError
        return frame[1:]

    def _write_data(self, framebytes):
        self._i2c.writeto(self._address, framebytes)
