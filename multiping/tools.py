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
    ip = response["ip"]
    host = response["host"]
    error = response.get("error", SENTINEL)
    if error is not SENTINEL:
        return f"{host} ({ip}): {error}"
    size = response["size"]
    seq = response["sequence"]
    t = response["time"] * 1000

    return f"{size} bytes from {host} ({ip}): icmp_seq={seq} time={t:.1f}ms"
