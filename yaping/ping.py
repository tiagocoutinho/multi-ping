#
# This file is part of the yaping project
#
# Copyright (c) 2024 Tiago Coutinho
# Distributed under the GPLv3 license. See LICENSE for more info.

"""
Synchronous yaping API.

Here is an example using the functional API:

```python
from yaping.ping import ping
from yaping.tools import response_text

for response in ping(["gnu.org", "orcid.org"], count=4):
    text = response_text(response)
    print(text)
```
"""

import contextlib
import logging
import time
from collections.abc import Callable, Iterable

from .socket import Socket, resolve_addresses
from .tools import SENTINEL, cycle, intervals, new_id


@contextlib.contextmanager
def remaining_time(timeout) -> Iterable[Callable[[], float]]:
    if timeout is None:
        def remaining():
            return None
    else:
        start = time.perf_counter()

        def remaining():
            if (remain := timeout - time.perf_counter() + start) <= 0:
                raise TimeoutError()
            return remain

    yield remaining


def receive_pings_for_sequence(sock: Socket, icmp_seq: int, timeout: float | None) -> Iterable[dict]:
    with remaining_time(timeout) as timer:
        while True:
            tout = timer()
            response = sock.receive_one_ping(tout)
            if response["sequence"] != icmp_seq:
                logging.warning("Received old response")
                continue
            yield response


def receive_one_ping(sock: Socket, ips: Iterable[str], icmp_seq: int, timeout: float | None) -> Iterable[dict]:
    pending_ips = set(ips)
    responses = receive_pings_for_sequence(sock, icmp_seq, timeout)
    while pending_ips:
        try:
            response = next(responses)
        except TimeoutError as error:
            error = error.args[0] if error.args else "timeout"
            for ip in pending_ips:
                yield {"ip": ip, "error": error}
            return
        pending_ips.remove(response["ip"])
        yield response


class Ping:
    """Handle several hosts with a single "shared" ICMP socket"""

    def __init__(self, sock: Socket, icmp_id: int | None = None, timeout: float | None = None):
        self.socket = sock
        if icmp_id is None:
            icmp_id = new_id()
        self.icmp_id = icmp_id
        self.timeout = timeout

    def send_one_ping(self, ips: Iterable[str], icmp_seq: int = 1):
        self.socket.send_one_ping(ips, self.icmp_id, icmp_seq)

    def receive_one_ping(self, ips: Iterable[str], icmp_seq: int = 1, timeout=SENTINEL) -> Iterable[dict]:
        if timeout is SENTINEL:
            timeout = self.timeout
        yield from receive_one_ping(self.socket, ips, icmp_seq, timeout)

    def _one_ping(self, ips: Iterable[str], icmp_seq: int, timeout: float | None) -> Iterable[dict]:
        self.send_one_ping(ips, icmp_seq)
        yield from self.receive_one_ping(ips, icmp_seq, timeout)

    def raw_ping(
        self,
        ips: Iterable[str],
        interval: float = 1,
        strict_interval: bool = False,
        count: int | None = None,
        timeout: float | None = SENTINEL,
    ) -> Iterable[dict]:
        if not ips:
            return
        if timeout is SENTINEL:
            timeout = self.timeout
        sequence = range(1, count + 1) if count else cycle()
        for seq_id in intervals(sequence, interval, strict_interval):
            yield from self._one_ping(ips, seq_id, timeout)

    def ping(
        self,
        addresses: Iterable[str],
        interval: float = 1,
        strict_interval: bool = False,
        count: int | None = None,
        timeout: float | None = SENTINEL,
    ) -> Iterable[dict]:
        addr_map, errors = resolve_addresses(addresses)
        for addr, error in errors.items():
            yield {"ip": addr, "host": addr, "error": error}
        ips = set(addr_map)
        for result in self.raw_ping(ips, interval, strict_interval, count, timeout):
            ip = result["ip"]
            for info in addr_map[ip]:
                result["host"] = info["host"]
                yield result


def ping(
    hosts: Iterable[str],
    icmp_id: int | None = None,
    interval: float = 1,
    strict_interval: bool = False,
    count: int | None = None,
    timeout: float | None = 1,
) -> Iterable[dict]:
    """
    Functional helper to ping a group of given hosts concurrently *count* number of
    times separated by *interval (s)*.
    Infinine sequence of pings (default) is achieved with *count=None*.
    If *strict_interval* is True, a best effort is made to start group ping in fixed
    periods.

    Example:

    ```python
    from yaping.ping import ping
    from yaping.tools import response_text

    for response in ping(["gnu.org", "orcid.org"], count=4):
        text = response_text(response)
        print(text)
    ```
    """
    sock = Socket()
    ping = Ping(sock, icmp_id, timeout)
    yield from ping.ping(hosts, interval, strict_interval, count)
