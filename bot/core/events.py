from collections import defaultdict

SONG_START = 1
SONG_COMPLETE = 2
SONG_PAUSED = 3
SONG_RESUMED = 4


class EventEmitter:

    def __init__(self):
        self._events = defaultdict(list)

    def on(self, event_name, callback):
        if callback in self._events[event_name]:
            return

        self._events[event_name].append(callback)

    def off(self, event_name, callback):
        if callback in self._events[event_name]:
            self._events[event_name].remove(callback)

    def emit(self, event_name, *args, **kwargs):
        for callback in list(self._events[event_name]):
            callback(*args, **kwargs)


events = EventEmitter()
