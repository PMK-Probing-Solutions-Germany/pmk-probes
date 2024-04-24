class ProbeError(Exception):
    pass


class ProbeConnectionError(ConnectionError):
    pass


class ProbeTypeError(ProbeConnectionError):
    pass


class ProbeReadError(ProbeError):
    pass


UUIDReadError = (AttributeError, ValueError)
