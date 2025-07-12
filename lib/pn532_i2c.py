# pn532_i2c_stable.py
from machine import I2C
import time

class PN532_I2C:
    def __init__(self, i2c, address=0x24, debug=False):
        self.i2c = i2c
        self.address = address
        self.debug = debug

    def _log(self, *args):
        if self.debug:
            print(*args)

    def _write_command(self, command, params=[]):
        frame = [0xD4, command] + params
        length = len(frame)
        lcs = (~length + 1) & 0xFF
        dcs = (~sum(frame) + 1) & 0xFF
        packet = [0x00, 0x00, 0xFF, length, lcs] + frame + [dcs, 0x00]
        self._log("Sende an PN532:", [hex(b) for b in packet])
        self.i2c.writeto(self.address, bytes(packet))
        time.sleep_ms(100)

    def _read_data(self, length):
        self._wait_ready(timeout_ms=3000)
        time.sleep_ms(20)
        try:
            data = self.i2c.readfrom(self.address, length)
            self._log("Empfangen von PN532:", [hex(b) for b in data])
            return data
        except OSError:
            self._log("Fehler beim Lesen der Daten")
            return b''

    def _wait_ready(self, timeout_ms=3000):
        start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start) < timeout_ms:
            try:
                if self.i2c.readfrom(self.address, 1)[0] == 0x01:
                    return True
            except OSError:
                pass
            time.sleep_ms(10)
        raise OSError("Timeout beim Warten auf Antwort")

    def _read_response(self, expected_command, attempts=10):
        for _ in range(attempts):
            data = self._read_data(64)
            self._log("Antwort erhalten:", [hex(b) for b in data])
            for i in range(len(data) - 2):
                if data[i] == 0xD5 and data[i + 1] == expected_command + 1:
                    self._log("Gefundene Antwort bei Index", i)
                    self._log("Rohdaten Antwort:", [hex(b) for b in data[i:i+10]])
                    return data[i + 2:]
            time.sleep_ms(100)
        raise RuntimeError("Keine gueltige Antwort erhalten")

    def get_firmware_version(self):
        self._write_command(0x02)
        try:
            ack = self._read_data(6)
            self._log("ACK erhalten:", [hex(b) for b in ack])
        except Exception:
            self._log("Keine ACK-Daten erhalten – ignoriere das.")
        response = self._read_response(0x02)
        self.sam_configuration()
        return {
            "ic": response[0],
            "version": response[1],
            "revision": response[2],
            "features": response[3]
        }

    def sam_configuration(self):
        self._write_command(0x14, [0x01, 0x14, 0x01])
        try:
            ack = self._read_data(6)
            self._log("ACK erhalten (SAM):", [hex(b) for b in ack])
        except Exception:
            self._log("SAM ACK fehlgeschlagen – wird ignoriert.")

        response = self._read_response(0x14)
        self._log("SAM-Konfiguration OK:", [hex(b) for b in response])

    def read_passive_target(self):
        self._write_command(0x4A, [0x01, 0x00])
        try:
            ack = self._read_data(6)
            self._log("ACK erhalten:", [hex(b) for b in ack])
        except Exception:
            self._log("ACK fehlgeschlagen – wird ignoriert.")

        raw = b''
        for attempt in range(10):
            try:
                raw = self._read_data(64)
                self._log("Antwort erhalten:", [hex(b) for b in raw])
                break
            except OSError as e:
                self._log(f"Fehler: {e}")
                time.sleep_ms(500)
        else:
            self._log("Antwortzeit überschritten")
            return None

        for i in range(len(raw) - 10):
            if raw[i] == 0xD5 and raw[i+1] == 0x4B:
                self._log("Antwort erkannt ab Index", i)
                if i + 3 >= len(raw):
                    self._log("Antwort zu kurz, Anzahl Targets fehlt.")
                    continue

                num_targets = raw[i+2]
                self._log("Anzahl erkannter Targets:", num_targets)

                if num_targets < 1:
                    self._log("Kein Target erkannt")
                    continue

                tgt_data_len = raw[i+3]
                self._log("Target-Datenlänge:", tgt_data_len)

                if i + 4 + tgt_data_len > len(raw):
                    self._log("Antwort zu kurz für Target-Daten")
                    continue

                target_data = raw[i+4:i+4+tgt_data_len]
                self._log("Target-Daten:", [hex(b) for b in target_data])

                if len(target_data) >= 7:
                    uid_start = 3
                    uid_len = target_data[uid_start]
                    self._log("UID-Länge:", uid_len)

                    if uid_len > 0 and uid_start + 1 + uid_len <= len(target_data):
                        uid = target_data[uid_start + 1: uid_start + 1 + uid_len]
                        self._log("UID erkannt:", ''.join(f'{b:02X}' for b in uid))
                        return bytes(uid)
                    else:
                        self._log("Ungültige UID-Struktur")
                else:
                    self._log("Target-Daten zu kurz für UID")

        self._log("Keine UID-Struktur gefunden")
        self._log("Versuche generische UID-Erkennung...")
        for j in range(len(raw) - 8):
            maybe_uid = raw[j:j+8]
            if maybe_uid[0] == 0x04 and all(b != 0x00 for b in maybe_uid):
                self._log("Generische UID erkannt:", ''.join(f'{b:02X}' for b in maybe_uid))
                return bytes(maybe_uid)

        return None
