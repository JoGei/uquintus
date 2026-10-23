"""Ordered bus responses with independently elapsed grant-to-response delays."""
from collections import deque


class ResponseQueue(deque):
    @property
    def head(self):
        return self[0] if self else None

    def advance(self, returning):
        if returning:
            self.popleft()
        # Time elapses for every transaction, including those behind the head.
        for index, (delay, *payload) in enumerate(self):
            self[index] = (max(0, delay-1), *payload)

    def issue(self, delay, *payload):
        assert len(self) < 2, 'more than two outstanding instruction requests'
        self.append((delay, *payload))
