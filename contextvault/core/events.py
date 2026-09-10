from enum import Enum, auto
from dataclasses import dataclass
from typing import Dict, Any, Callable, List
from datetime import datetime

class EventType(Enum):
    SCAN_STARTED = auto()
    SCAN_PROGRESS = auto()
    SCAN_COMPLETE = auto()
    INDEX_STARTED = auto()
    INDEX_PROGRESS = auto()
    INDEX_COMPLETE = auto()
    OPERATION_STARTED = auto()
    OPERATION_COMPLETE = auto()
    ERROR = auto()

@dataclass
class Event:
    type: EventType
    data: Dict[str, Any]
    timestamp: datetime = datetime.now()

class EventBus:
    def __init__(self):
        self._subscribers: Dict[EventType, List[Callable[[Event], None]]] = {}

    def subscribe(self, event_type: EventType, callback: Callable[[Event], None]):
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)

    def emit(self, event: Event):
        if event.type in self._subscribers:
            for callback in self._subscribers[event.type]:
                try:
                    callback(event)
                except Exception:
                    pass
