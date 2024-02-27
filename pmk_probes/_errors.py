class ProbeError(Exception):
    pass


class ProbeConnectionError(ConnectionError):
    pass


class ProbeTypeError(ProbeConnectionError):
    pass


class ProbeWriteError(ProbeError):
    pass


class ProbeReadError(ProbeError):
    pass


ProbeInitializationError = (ProbeTypeError, AttributeError, ValueError)
