import functools
import ipaddress
import logging
import select
import socket
import time

from .protocol import ICMP_DEFAULT_SIZE, IP_HEADER, encode_request, decode_response, ICMPv4, ICMPv6
from .tools import cycle, new_id, SENTINEL


def _can_have_ip_header():
    try:
        socket.socket(ICMPv4.family, socket.SOCK_RAW, ICMPv4.proto)
    except PermissionError:
        return False
    return True

# No IP Header when unpriviledged on Linux
CAN_HAVE_IP_HEADER = _can_have_ip_header()


def socket_has_ip_header(sock: socket.socket) -> bool:
    return CAN_HAVE_IP_HEADER or sock.type == socket.SOCK_RAW


def socket_ip(sock: socket.socket) -> str:
    return sock.getsockname()[0]


def socket_port(sock: socket.socket) -> int:
    return sock.getsockname()[1]


def socket_request_type(sock: socket.socket):
    return ICMPv4.ECHO_REQUEST if sock.family == socket.AF_INET else ICMPv6.ECHO_REQUEST


def socket_encode_request(sock: socket.socket, icmp_id: int = 1, icmp_seq: int = 1, timestamp: float | None = None) -> bytes:
    request = socket_request_type(sock)
    return encode_request(request, icmp_id, icmp_seq, timestamp)


def socket_decode_response(sock: socket.socket, payload: bytes) -> dict:
    return decode_response(payload, socket_has_ip_header(sock))


# I/O ------------------------------------------------------------------------


getaddrinfo = functools.cache(socket.getaddrinfo)
gethostbyname = functools.cache(socket.gethostbyname)


def resolve_address(address: str, family: int = SENTINEL) -> list[str]:
    """
                   AF_INET
    localhost -> 127.0.0.1
    127.0.0.1 -> 127.0.0.1
    gnu.org   -> 209.51.188.116
    ::1       -> ::1
    """
    Addr = ipaddress.ip_address
    if family is not SENTINEL:
        Addr = ipaddress.IPv4Address if family == socket.AF_INET else ipaddress.IPv6Address
    try:
        Addr(address)
        return address
    except ValueError:
        pass
    kwargs = {}
    if family is not SENTINEL:
        kwargs["family"] = family
    addresses = getaddrinfo(address, 0, **kwargs)
    sock_type = socket.SOCK_RAW if CAN_HAVE_IP_HEADER else socket.SOCK_DGRAM
    return next(addr[4][0] for addr in addresses if addr[1] == sock_type)


@functools.cache
def gethostbyaddr(address: str) -> str:
    try:
        return socket.gethostbyaddr(address)
    except socket.herror:
        pass    
    return gethostbyname(address)
    

def socket_wait_response(sock: socket.socket, timeout: float | None = None):
    r, _, _ = select.select((sock,), (), (), timeout)
    if not r:
        raise TimeoutError(f"read timeout after {timeout:.3f}s")


def sockets_wait_response(socks, timeout = None):
    socks = set(socks)
    if timeout is None:
        while socks:
            r, _, _ = select.select(socks, (), ())
            yield from r
            socks -= set(r)
        return
    end = time.monotonic() + timeout
    while socks:
        tout = end - time.monotonic()
        if tout <= 0:
            raise TimeoutError("timed out")
        r, _, _ = select.select(socks, (), (), tout)
        if not r:
            raise TimeoutError("timed out")
        yield from r
        socks -= set(r)


def socket_recvfrom_timeout(
    sock: socket.socket, size: int = 1024, timeout: float | None = None
) -> bytes:
    socket_wait_response(sock, timeout)
    return sock.recvfrom(size)


def socket_send_one_ping_payload(sock: socket.socket, ip: str, payload: bytes):
    n = sock.sendto(payload, (ip, 0))
    assert n == len(payload)


def socket_send_one_ping(sock: socket.socket, ips: list[str], icmp_id: int, icmp_seq: int = 1):
    payload = socket_encode_request(sock, icmp_id, icmp_seq)
    for ip in ips:
        socket_send_one_ping_payload(sock, ip, payload)


def socket_read_one_ping(sock: socket.socket):
    ip_header = socket_has_ip_header(sock)
    size = ICMP_DEFAULT_SIZE + (IP_HEADER.size if ip_header else 0)
    payload, address = sock.recvfrom(size)
    time_received = time.perf_counter()
    assert len(payload) == size
    response = decode_response(payload, ip_header)
    if not ip_header:
        response["id"] = sock.getsockname()[1]
    response["time_received"] = time_received
    response["ip"] = address[0]
    response["time"] = time_received - response["time_sent"]
    return response


def socket_receive_one_ping(sock: socket.socket, timeout: float | None = None):
    socket_wait_response(sock, timeout)
    return socket_read_one_ping(sock)


class Socket(socket.socket):
    """An ICMP socket"""

    def __init__(
        self,
        family: socket.AddressFamily = socket.AF_INET,
        type: socket.SocketKind | None = None,
        timeout: float = 0,
    ):
        proto = ICMPv4.proto if family == socket.AF_INET else ICMPv6.proto
        if type is None:
            type = socket.SOCK_RAW if CAN_HAVE_IP_HEADER else socket.SOCK_DGRAM
        super().__init__(family, type, proto)
        self.settimeout(timeout)

    has_ip_header: bool = property(socket_has_ip_header)
    ip: str = property(socket_ip)
    port: int = property(socket_port)
    recvfrom_timeout = socket_recvfrom_timeout

    send_one_ping = socket_send_one_ping
    receive_one_ping = socket_receive_one_ping
    read_one_ping = socket_read_one_ping


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
        addrs, hosts = {}, {}
        for ip in ips:
            addrs[ip] = ipaddress.ip_address(ip)
            try:
                hosts[ip] = gethostbyaddr(ip)[0]
            except OSError:
                hosts[ip] = ip

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
            response["ip_address"] = addrs[ip]
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