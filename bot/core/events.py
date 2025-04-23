from collections import defaultdict

SONG_START = 1
SONG_COMPLETE = 2
SONG_PAUSED = 3
SONG_RESUMED = 4


class EventEmitter:

    def __init__(self):
        self._events = defaultdict(list)

    def on(self, event_name, callback):
        self._events[event_name].append(callback)

    def emit(self, event_name, *args, **kwargs):
        for callback in self._events[event_name]:
            callback(*args, **kwargs)


events = EventEmitter()
