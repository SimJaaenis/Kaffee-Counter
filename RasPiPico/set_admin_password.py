try:
    import ujson as json
except Exception:
    import json

import hashlib
import os


DEVICE_JSON_PATH = "/sd/config/device.json"
BACKUP_PATH = "/sd/backup/device.json.bak"


def sha256_hex(text):
    return hashlib.sha256((text or "").encode()).hexdigest()


def read_json(path):
    with open(path, "r") as f:
        return json.load(f)


def write_json_atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
        f.flush()

    try:
        with open(path, "rb") as src:
            content = src.read()
        with open(BACKUP_PATH, "wb") as bak:
            bak.write(content)
    except Exception:
        pass

    try:
        os.remove(path)
    except OSError:
        pass
    os.rename(tmp, path)


def main():
    print("Admin-Passwort setzen")
    print("Datei:", DEVICE_JSON_PATH)

    cfg = read_json(DEVICE_JSON_PATH)
    admin = cfg.get("admin", {})

    current_user = admin.get("username", "admin")
    print("Aktueller Benutzer:", current_user)

    user = input("Neuer Benutzer (Enter=behalten): ").strip()
    if not user:
        user = current_user

    pw1 = input("Neues Passwort: ").strip()
    pw2 = input("Passwort wiederholen: ").strip()

    if not pw1:
        raise RuntimeError("Passwort darf nicht leer sein.")
    if pw1 != pw2:
        raise RuntimeError("Passwoerter stimmen nicht ueberein.")

    admin["username"] = user
    admin["password_sha256_hex"] = sha256_hex(pw1)
    cfg["admin"] = admin

    write_json_atomic(DEVICE_JSON_PATH, cfg)
    print("OK. Benutzer/Passwort aktualisiert.")
    print("Backup:", BACKUP_PATH)


main()
