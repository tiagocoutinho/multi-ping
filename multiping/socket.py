import functools
import ipaddress
import select
import socket
import time

from .protocol import (
    ICMP_DEFAULT_SIZE,
    IP_HEADER,
    encode_request,
    decode_response,
    ICMPv4,
    ICMPv6,
)
from .tools import SENTINEL


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


def socket_encode_request(
    sock: socket.socket,
    icmp_id: int = 1,
    icmp_seq: int = 1,
    timestamp: float | None = None,
) -> bytes:
    request = socket_request_type(sock)
    return encode_request(request, icmp_id, icmp_seq, timestamp)


def socket_decode_response(sock: socket.socket, payload: bytes) -> dict:
    return decode_response(payload, socket_has_ip_header(sock))


# I/O ------------------------------------------------------------------------


getaddrinfo = functools.cache(socket.getaddrinfo)
gethostbyname = functools.cache(socket.gethostbyname)
gethostbyname_ex = functools.cache(socket.gethostbyname_ex)
gethostbyaddr = functools.cache(socket.gethostbyaddr)


def address_info(host_or_ip: str):
    ip = gethostbyname(host_or_ip)

    is_ip = ip == host_or_ip

    host = host_or_ip
    if is_ip:
        try:
            host = gethostbyaddr(ip)
        except OSError:
            pass
    return {
        "input": host_or_ip,
        "host": host,
        "ip": ip,
    }


def socket_wait_response(sock: socket.socket, timeout: float | None = None):
    r, _, _ = select.select((sock,), (), (), timeout)
    if not r:
        raise TimeoutError("timed out")


def sockets_wait_response(socks, timeout=None):
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


def socket_send_one_ping(
    sock: socket.socket, ips: list[str], icmp_id: int, icmp_seq: int = 1
):
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
    wait_response = socket_wait_response
