import ipaddress
import logging
import time

from .socket import gethostbyaddr, resolve_address, Socket
from .tools import cycle, new_id, SENTINEL


class Ping:
    """Handle several hosts with a single "shared" ICMP socket"""

    def __init__(self, sock: Socket, icmp_id=None, timeout=None):
        self.socket = sock
        if icmp_id is None:
            icmp_id = new_id()
        self.icmp_id = icmp_id
        self.timeout = timeout

    def send_one_ping(self, addresses: list[str], icmp_seq: int = 1):
        self.socket.send_one_ping(addresses, self.icmp_id, icmp_seq)

    def receive_one_ping(self, addresses: list[str], icmp_seq: int = 1, timeout=SENTINEL):
        ips = {resolve_address(address): address for address in addresses}
        hosts = {ip: gethostbyaddr(ip) for ip in ips}

        if timeout is SENTINEL:
            timeout = self.timeout
        
        pending_ips = set(ips)
        while pending_ips:
            response = self.socket.receive_one_ping(timeout)
            if response["sequence"] != icmp_seq:
                logging.warning("Received old response")
                continue
            ip = response["ip"]
            pending_ips.remove(ip)
            response["host"] = ips[ip]
            response["resolved_host"] = hosts[ip]
            yield response

    def one_ping(self, ips: list[str], icmp_seq: int = 1, timeout=SENTINEL):
        self.send_one_ping(ips, icmp_seq)
        yield from self.receive_one_ping(ips, icmp_seq, timeout)


def ping_many(
    hosts: list[str],
    icmp_id: int | None = None,
    interval: float = 1,
    count: int | None = None,
    timeout: float | None = 1,
):
    sock = Socket()
    ping = Ping(sock, icmp_id, timeout)
    sequence = range(1, count + 1) if count else cycle()
    for seq_id in sequence:
        yield from ping.one_ping(hosts, seq_id, timeout)
        time.sleep(interval)