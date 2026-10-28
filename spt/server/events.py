"""Small bounded event fan-out; subscribers cannot retain unbounded events."""
from __future__ import annotations
import queue
import threading
from typing import Any


class Events:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.subscribers: set[queue.Queue[dict[str, Any]]] = set()

    def subscribe(self) -> queue.Queue[dict[str, Any]]:
        subscriber: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=16)
        with self.lock:
            self.subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[dict[str, Any]]) -> None:
        with self.lock:
            self.subscribers.discard(subscriber)

    def publish(self, value: dict[str, Any]) -> None:
        with self.lock:
            for subscriber in self.subscribers:
                if subscriber.full():
                    try:
                        subscriber.get_nowait()
                    except queue.Empty:
                        pass
                subscriber.put_nowait(value)
