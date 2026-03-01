class LoggerQueue:
    def __init__(self, max_queue=120, max_ram_entries=50):
        self.max_queue = int(max_queue)
        self.max_ram_entries = int(max_ram_entries)
        self._queue = []
        self.ram_ledger = []
        self.last_error = None

    def _append_ram_ledger(self, entry):
        if entry is None:
            return
        if len(self.ram_ledger) >= self.max_ram_entries:
            self.ram_ledger.pop(0)
        self.ram_ledger.append(entry)

    def enqueue(self, action_fn, description="", fallback_ledger_entry=None):
        self.enqueue_steps([action_fn], description=description, fallback_ledger_entry=fallback_ledger_entry)

    def enqueue_steps(self, steps, description="", fallback_ledger_entry=None):
        cleaned = []
        for step in (steps or []):
            if step is not None:
                cleaned.append(step)
        if not cleaned:
            return
        if len(self._queue) >= self.max_queue:
            self._queue.pop(0)
        self._queue.append(
            {
                "steps": cleaned,
                "idx": 0,
                "description": description,
                "fallback": fallback_ledger_entry,
            }
        )

    def enqueue_ledger(self, action_fn, ledger_entry, sd_ready):
        if sd_ready:
            self.enqueue(action_fn, description="ledger", fallback_ledger_entry=ledger_entry)
        else:
            self._append_ram_ledger(ledger_entry)

    def tick(self):
        if not self._queue:
            return False

        task = self._queue[0]
        steps = task["steps"]
        idx = int(task.get("idx", 0))
        if idx < 0 or idx >= len(steps):
            self._queue.pop(0)
            return False

        action_fn = steps[idx]
        try:
            action_fn()
            task["idx"] = idx + 1
            if task["idx"] >= len(steps):
                self._queue.pop(0)
            return True
        except Exception as exc:
            self.last_error = "{}: {}".format(task.get("description") or "action", exc)
            self._append_ram_ledger(task.get("fallback"))
            self._queue.pop(0)
            return False

    def pending(self):
        return len(self._queue)
