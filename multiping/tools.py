import uuid


SENTINEL = object()


def new_id() -> int:
    """Return a "unique" 16-bit integer ID"""
    return uuid.uuid4().int & 0xFFFF


def cycle(start: int = 1, stop: int = 2**16, step: int = 1):
    """Helper to cycle sequence of numbers"""
    while True:
        yield from range(start, stop, step)


def response_text(response):
    size = response["size"]
    ip = response["ip"]
    seq = response["sequence"]
    t = response["time"] * 1000
    resolved_host = response["resolved_host"]
    return f"{size} bytes from {resolved_host} ({ip}): icmp_seq={seq} time={t:.1f}ms"
