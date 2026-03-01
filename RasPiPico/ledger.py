import os
import time


def _month_key_from_ts(ts_str):
    # expects YYYY-MM-DD HH:MM:SS
    return ts_str[:7]


def _month_key_now():
    lt = time.localtime()
    return "{:04d}-{:02d}".format(lt[0], lt[1])


def _month_key_back(months_back):
    lt = time.localtime()
    y = lt[0]
    m = lt[1]
    for _ in range(months_back):
        m -= 1
        if m < 1:
            m = 12
            y -= 1
    return "{:04d}-{:02d}".format(y, m)


def _log_file(root, month_key):
    return "{}/logs/bookings_{}.csv".format(root, month_key)


def _list_booking_files(root):
    paths = []
    logs_dir = "{}/logs".format(root)
    try:
        names = os.listdir(logs_dir)
    except OSError:
        return paths

    for name in names:
        # Accept primary booking files only, exclude mirrors.
        if not name.startswith("bookings_"):
            continue
        if not name.endswith(".csv"):
            continue
        if "mirror" in name:
            continue
        paths.append("{}/{}".format(logs_dir, name))

    # File names contain YYYY-MM and sort naturally by recency descending.
    paths.sort(reverse=True)
    return paths


def _tail_lines(path, max_lines=100, max_bytes=32768):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size <= 0:
                return []
            to_read = max_bytes if size > max_bytes else size
            f.seek(size - to_read, 0)
            data = f.read(to_read)
    except OSError:
        return []

    text = data.decode("utf-8", "ignore")
    lines = text.splitlines()
    # If we started in the middle of file, first line can be partial.
    if size > max_bytes and lines:
        lines = lines[1:]
    if max_lines and len(lines) > max_lines:
        lines = lines[-max_lines:]
    return lines


def ensure_log_header(path):
    try:
        with open(path, "r"):
            return
    except OSError:
        pass

    with open(path, "w") as f:
        f.write("ts;type;user_id;product_id;qty;amount_cents;balance_before_cents;balance_after_cents;note\n")


def append_entry(root, entry, mirror=False):
    ts = entry.get("ts")
    month_key = _month_key_from_ts(ts) if ts else _month_key_now()
    path = _log_file(root, month_key)
    ensure_log_header(path)

    row = "{ts};{type};{user_id};{product_id};{qty};{amount_cents};{balance_before_cents};{balance_after_cents};{note}\n".format(
        ts=entry.get("ts", ""),
        type=entry.get("type", ""),
        user_id=entry.get("user_id", ""),
        product_id=entry.get("product_id", ""),
        qty=entry.get("qty", 0),
        amount_cents=entry.get("amount_cents", 0),
        balance_before_cents=entry.get("balance_before_cents", ""),
        balance_after_cents=entry.get("balance_after_cents", ""),
        note=(entry.get("note", "") or "").replace("\n", " ").replace(";", ","),
    )

    with open(path, "a") as f:
        f.write(row)

    if mirror:
        mirror_path = "{}/logs/bookings_mirror_{}.csv".format(root, month_key)
        ensure_log_header(mirror_path)
        with open(mirror_path, "a") as f:
            f.write(row)


def parse_entry_line(line):
    raw = (line or "").strip()
    if not raw or raw.startswith("ts;"):
        return None

    parts = raw.split(";")
    if len(parts) < 7:
        return None

    try:
        # New format: ...;amount;balance_before;balance_after;note
        if len(parts) >= 9:
            balance_before = parts[6]
            balance_after = parts[7]
            note = ";".join(parts[8:])
            return {
                "ts": parts[0],
                "type": parts[1],
                "user_id": parts[2],
                "product_id": parts[3],
                "qty": int(parts[4]),
                "amount_cents": int(parts[5]),
                "balance_before_cents": int(balance_before) if balance_before != "" else None,
                "balance_after_cents": int(balance_after) if balance_after != "" else None,
                "note": note,
            }
        # Legacy format: ...;amount;note
        return {
            "ts": parts[0],
            "type": parts[1],
            "user_id": parts[2],
            "product_id": parts[3],
            "qty": int(parts[4]),
            "amount_cents": int(parts[5]),
            "balance_before_cents": None,
            "balance_after_cents": None,
            "note": ";".join(parts[6:]),
        }
    except Exception:
        return None


def scan_recent_entries(root, months=3, max_entries=None):
    entries = []
    files = _list_booking_files(root)
    if months is not None and months > 0:
        files = files[:months]

    for path in files:
        try:
            with open(path, "r") as f:
                for line in f:
                    item = parse_entry_line(line)
                    if item is not None:
                        entries.append(item)
                        if max_entries is not None and len(entries) >= int(max_entries):
                            return entries
        except OSError:
            continue
    return entries


def scan_recent_entries_filtered(root, months=3, max_entries=None, user_id=None, types=None):
    entries = []
    files = _list_booking_files(root)
    if months is not None and months > 0:
        files = files[:months]

    type_set = None
    if types:
        try:
            type_set = set(types)
        except Exception:
            type_set = None

    for path in files:
        try:
            with open(path, "r") as f:
                for line in f:
                    item = parse_entry_line(line)
                    if item is None:
                        continue
                    if user_id and item.get("user_id", "") != user_id:
                        continue
                    if type_set is not None and item.get("type", "") not in type_set:
                        continue
                    entries.append(item)
                    if max_entries is not None and len(entries) >= int(max_entries):
                        return entries
        except OSError:
            continue
    return entries


def tail_recent_entries(root, limit=100, max_files=3, max_bytes_per_file=32768):
    out = []
    files = _list_booking_files(root)[: max(1, int(max_files))]
    remaining = max(1, int(limit))

    for path in files:
        lines = _tail_lines(path, max_lines=remaining + 10, max_bytes=max_bytes_per_file)
        for line in reversed(lines):
            item = parse_entry_line(line)
            if item is None:
                continue
            out.append(item)
            if len(out) >= limit:
                return out
        remaining = max(1, limit - len(out))

    return out


def rebuild_balances_recent(root, months=3):
    balances = {}
    entries = scan_recent_entries(root, months=months)
    for entry in entries:
        user_id = entry.get("user_id")
        amount = int(entry.get("amount_cents", 0))
        if not user_id:
            continue
        balances[user_id] = int(balances.get(user_id, 0)) + amount
    return balances
