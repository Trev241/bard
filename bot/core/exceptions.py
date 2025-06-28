class AlreadyConnecting(Exception):
    pass


class AlreadyConnected(Exception):
    pass


class UserNotInVoice(Exception):
    pass


class ConnectionFailed(Exception):
    pass


class ConnectionNotReady(Exception):
    pass


class CannotCompleteAction(Exception):
    pass
