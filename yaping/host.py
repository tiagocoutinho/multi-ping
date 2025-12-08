#
# This file is part of the yaping project
#
# Copyright (c) 2024 Tiago Coutinho
# Distributed under the GPLv3 license. See LICENSE for more info.

import ipaddress
import socket
import time

from .socket import Socket, gethostbyaddr, gethostbyname, sockets_wait_response
from .tools import SENTINEL, cycle, new_id, response_text


class Host:
    """Handle one particular host with a "private" ICMP socket"""

    def __init__(self, host, icmp_id=None, timeout=None):
        self.host = host
        if icmp_id is None:
            icmp_id = new_id()
        self.icmp_id = icmp_id
        self.timeout = timeout
        self.ip = gethostbyname(host)
        try:
            self.resolved_host = gethostbyaddr(self.ip)[0]
        except OSError:
            self.resolved_host = host
        ip_address = ipaddress.ip_address(self.ip)
        family = socket.AF_INET if ip_address.version == 4 else socket.AF_INET6
        self.socket = Socket(family)

    def send_one_ping(self, icmp_seq: int = 1):
        return self.socket.send_one_ping((self.ip,), self.icmp_id, icmp_seq)

    def receive_one_ping(self, timeout=SENTINEL):
        if timeout is SENTINEL:
            timeout = self.timeout
        response = self.socket.receive_one_ping(timeout)
        return self.fill_response(response)

    def read_one_ping(self):
        response = self.socket.read_one_ping()
        return self.fill_response(response)

    def one_ping(self, icmp_seq: int = 1, timeout=SENTINEL):
        self.send_one_ping(icmp_seq)
        return self.receive_one_ping(timeout)

    def ping(self, interval: float = 1, count: int | None = None, timeout=SENTINEL):
        sequence = range(1, count + 1) if count else cycle()
        for seq_id in sequence:
            yield self.one_ping(seq_id, timeout)
            time.sleep(interval)

    def fileno(self):
        return self.socket.fileno()

    def fill_response(self, response):
        response["host"] = self.host
        response["resolved_host"] = self.resolved_host
        return response


def one_ping(
    address: str,
    icmp_id: int | None = None,
    icmp_seq: int = 1,
    timeout: float | None = 1,
):
    return Host(address, icmp_id, timeout).one_ping(icmp_seq)


def ping(
    address: str,
    icmp_id: int | None = None,
    interval: float = 1,
    count: int | None = None,
    timeout: float | None = 1,
):
    yield from Host(address, icmp_id, timeout=timeout).ping(interval, count)


def _one_ping_many(hosts: list[Host], icmp_seq: int = 1, timeout: float | None = 1):
    for host in hosts:
        host.send_one_ping(icmp_seq)
    for host in sockets_wait_response(hosts, timeout):
        yield host.read_one_ping()


def one_ping_many(
    hosts: list[str],
    icmp_id: int | None = None,
    icmp_seq: int = 1,
    timeout: float | None = 1,
):
    hosts = [Host(host, icmp_id, timeout) for host in hosts]
    yield from _one_ping_many(hosts, icmp_seq, timeout)


def ping_many(
    hosts: list[str],
    icmp_id: int | None = None,
    interval: float = 1,
    count: int | None = None,
    timeout: float | None = 1,
):
    hosts = [Host(host, icmp_id, timeout) for host in hosts]
    sequence = range(1, count + 1) if count else cycle()
    for seq_id in sequence:
        yield from _one_ping_many(hosts, seq_id, timeout)
        time.sleep(interval)


def main():
    import sys

    for response in ping_many(sys.argv[1:]):
        print(response_text(response))


if __name__ == "__main__":
    main()
