#
# This file is part of the yaping project
#
# Copyright (c) 2024 Tiago Coutinho
# Distributed under the GPLv3 license. See LICENSE for more info.

"""
Asynchronous yaping API.

Here is an example using the functional API:

```python
import asyncio

from yaping.aioping import ping
from yaping.tools import response_text

async def pings(hosts):
    async for response in ping(hosts, count=4):
        text = response_text(response)
        print(text)

asyncio.run(pings(["gnu.org", "orcid.org"]))
```
"""

import asyncio
from collections.abc import AsyncIterable, Iterable

from .socket import Socket, async_resolve_addresses
from .tools import SENTINEL, async_intervals, cycle, new_id


async def receive_one_ping(
    sock: Socket, ips: Iterable[str], icmp_seq: int, timeout: float | None
) -> AsyncIterable[dict]:
    def cb():
        response = sock.read_one_ping()
        if response["sequence"] != icmp_seq:
            return
        pending_ips.remove(response["ip"])
        responses.put_nowait(response)
        if not pending_ips:
            responses.put_nowait(None)

    pending_ips = set(ips)
    loop = asyncio.get_event_loop()
    responses = asyncio.Queue()
    loop.add_reader(sock, cb)
    try:
        async with asyncio.timeout(timeout):
            while True:
                if (response := await responses.get()) is None:
                    break
                yield response
    except TimeoutError as error:
        error = error.args[0] if error.args else "timeout"
        for ip in pending_ips:
            yield {"ip": ip, "error": error}
    finally:
        loop.remove_reader(sock)


class AsyncPing:
    """
    Handle several hosts with a single "shared" ICMP socket.

    Example:

    ```python

    import asyncio

    from yaping.aioping import AsyncPing
    from yaping.tools import response_text
    from yaping.socket import Socket

    async def pings():
        sock = Socket()
        ping = AsyncPing(sock, icmp_id, timeout)
        async for response in ping.ping(hosts, interval, strict_interval, count):
            text = response_text(response)
            print(text)

    asyncio.run(pings(["gnu.org", "orcid.org"]))
    ```
    """

    def __init__(self, sock: Socket, icmp_id: int | None = None, timeout: float | None = None):
        self.socket = sock
        if icmp_id is None:
            icmp_id = new_id()
        self.icmp_id = icmp_id
        self.timeout = timeout

    def send_one_ping(self, ips: Iterable[str], icmp_seq: int = 1):
        self.socket.send_one_ping(ips, self.icmp_id, icmp_seq)

    async def receive_one_ping(self, ips: Iterable[str], icmp_seq: int = 1, timeout: float | None = SENTINEL) -> dict:
        if timeout is SENTINEL:
            timeout = self.timeout
        async for result in receive_one_ping(self.socket, ips, icmp_seq, timeout):
            yield result

    async def _one_ping(self, ips: list[str], icmp_seq, timeout):
        self.send_one_ping(ips, icmp_seq)
        async for result in self.receive_one_ping(ips, icmp_seq, timeout):
            yield result

    async def raw_ping(
        self,
        ips: Iterable[str],
        interval: float = 1,
        strict_interval: bool = False,
        count: int | None = None,
        timeout: float | None = SENTINEL,
    ):
        if not ips:
            return
        if timeout is SENTINEL:
            timeout = self.timeout
        sequence = range(1, count + 1) if count else cycle()
        async for seq_id in async_intervals(sequence, interval, strict_interval):
            async for result in self._one_ping(ips, seq_id, timeout):
                yield result

    async def ping(
        self,
        addresses: Iterable[str],
        interval: float = 1,
        strict_interval: bool = False,
        count: int | None = None,
        timeout: float | None = SENTINEL,
    ):
        addr_map, errors = await async_resolve_addresses(addresses)
        for addr, error in errors.items():
            yield {"ip": addr, "host": addr, "error": error}
        ips = set(addr_map)
        async for result in self.raw_ping(ips, interval, strict_interval, count, timeout):
            for info in addr_map[result["ip"]]:
                yield dict(result, host=info["host"])


async def ping(
    hosts: Iterable[str],
    icmp_id: int | None = None,
    interval: float = 1,
    strict_interval: bool = False,
    count: int | None = None,
    timeout: float | None = 1,
):
    """
    Functional helper to ping a group of given hosts concurrently *count* number of
    times separated by *interval (s)*.
    Infinine sequence of pings (default) is achieved with *count=None*.
    If *strict_interval* is True, a best effort is made to start group ping in fixed
    periods.

    Example:

    ```python
    import asyncio

    from yaping.ping import ping
    from yaping.tools import response_text

    async def pings(hosts):
        async for response in ping(hosts, count=4):
            text = response_text(response)
            print(text)

    asyncio.run(pings(["gnu.org", "orcid.org"]))
    ```
    """
    sock = Socket()
    ping = AsyncPing(sock, icmp_id, timeout)
    async for response in ping.ping(hosts, interval, strict_interval, count):
        yield response
