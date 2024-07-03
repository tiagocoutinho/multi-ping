#
# This file is part of the multi-ping project
#
# Copyright (c) 2024 Tiago Coutinho
# Distributed under the GPLv3 license. See LICENSE for more info.

import contextlib
import logging
import time

from collections.abc import Callable, Iterable

from .socket import resolve_addresses, Socket
from .tools import cycle, new_id, rate_limit, SENTINEL


@contextlib.contextmanager
def remaining_time(timeout) -> Iterable[Callable[[], float]]:
    if timeout is None:
        remaining = lambda: None
    else:
        start = time.perf_counter()

        def remaining():
            if (remain := timeout - time.perf_counter() + start) <= 0:
                raise TimeoutError()
            return remain

    yield remaining


def receive_pings_for_sequence(
    sock: Socket, icmp_seq: int, timeout: float | None
) -> Iterable[dict]:
    with remaining_time(timeout) as timer:
        while True:
            tout = timer()
            response = sock.receive_one_ping(tout)
            if response["sequence"] != icmp_seq:
                logging.warning("Received old response")
                continue
            yield response


def receive_one_ping(
    sock: Socket, ips: Iterable[str], icmp_seq: int, timeout: float | None
) -> Iterable[dict]:
    pending_ips = set(ips)
    responses = receive_pings_for_sequence(sock, icmp_seq, timeout)
    while pending_ips:
        try:
            response = next(responses)
        except TimeoutError as error:
            for ip in pending_ips:
                yield {"ip": ip, "error": error}
            return
        pending_ips.remove(response["ip"])
        yield response


class Ping:
    """Handle several hosts with a single "shared" ICMP socket"""

    def __init__(
        self, sock: Socket, icmp_id: int | None = None, timeout: float | None = None
    ):
        self.socket = sock
        if icmp_id is None:
            icmp_id = new_id()
        self.icmp_id = icmp_id
        self.timeout = timeout

    def send_one_ping(self, ips: Iterable[str], icmp_seq: int = 1):
        self.socket.send_one_ping(ips, self.icmp_id, icmp_seq)

    def receive_one_ping(
        self, ips: Iterable[str], icmp_seq: int = 1, timeout=SENTINEL
    ) -> Iterable[dict]:
        if timeout is SENTINEL:
            timeout = self.timeout
        yield from receive_one_ping(self.socket, ips, icmp_seq, timeout)

    def _one_ping(
        self, ips: Iterable[str], icmp_seq: int, timeout: float | None
    ) -> Iterable[dict]:
        self.send_one_ping(ips, icmp_seq)
        yield from self.receive_one_ping(ips, icmp_seq, timeout)

    def one_ping(
        self, addresses: Iterable[str], icmp_seq: int = 1, timeout=SENTINEL
    ) -> Iterable[dict]:
        addr_map, errors = resolve_addresses(addresses)
        for addr, error in errors.items():
            yield dict(ip=addr, host=addr, error=error)
        ips = set(addr_map)
        for result in self._one_ping(ips, icmp_seq, timeout):
            ip = result["ip"]
            for info in addr_map[ip]:
                result["host"] = info["host"]
                yield result

    def raw_ping(
        self,
        ips: Iterable[str],
        interval: float = 1,
        strict_interval: bool = False,
        count: int | None = None,
        timeout: float | None = SENTINEL,
    ) -> Iterable[dict]:
        if timeout is SENTINEL:
            timeout = self.timeout
        sequence = range(1, count + 1) if count else cycle()
        for seq_id in rate_limit(sequence, interval, strict_interval):
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
            yield dict(ip=addr, host=addr, error=error)
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
    sock = Socket()
    ping = Ping(sock, icmp_id, timeout)
    yield from ping.ping(hosts, interval, strict_interval, count)
