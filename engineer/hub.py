"""Fan-out of live events to the browser's SSE stream: buttons, radio state, mic level, messages."""
import threading
from collections import deque


class Hub:
    def __init__(self, keep=500):
        self._cond = threading.Condition()
        self._items = deque(maxlen=keep)
        self.seq = 0

    def publish(self, kind, data):
        with self._cond:
            self.seq += 1
            self._items.append((self.seq, kind, data))
            self._cond.notify_all()

    def wait(self, after, timeout):
        """Items newer than `after` (blocking up to timeout), plus the seq to resume from."""
        with self._cond:
            self._cond.wait_for(lambda: self.seq > after, timeout)
            return [i for i in self._items if i[0] > after], self.seq
