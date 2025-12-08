#
# This file is part of the yaping project
#
# Copyright (c) 2024 Tiago Coutinho
# Distributed under the GPLv3 license. See LICENSE for more info.

import asyncio
import functools
import logging
import select
import socket
import time
from collections.abc import Iterable

try:
    import aiodns
except ModuleNotFoundError:
    aiodns = None


from .protocol import (
    ICMP_DEFAULT_SIZE,
    IP_HEADER,
    ICMPv4,
    ICMPv6,
    decode_response,
    encode_request,
)


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


def socket_request_type(sock: socket.socket) -> int:
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


@functools.cache
def address_info(host_or_ip: str) -> dict[str, str]:
    logging.info("Resolving %s...", host_or_ip)
    ip = gethostbyname(host_or_ip)

    is_ip = ip == host_or_ip

    host = host_or_ip
    if is_ip:
        try:
            host = gethostbyaddr(ip)[0]
        except OSError:
            pass
    logging.info("Resolved %s to (%s %s)...", host_or_ip, host, ip)
    return {"host": host, "ip": ip}


@functools.cache
def resolver() -> aiodns.DNSResolver:
    return aiodns.DNSResolver()


async def async_gethostbyname(host_or_ip: str, family=socket.AF_INET) -> str:
    return await resolver().gethostbyname(host_or_ip, family)


async def async_gethostbyaddr(ip: str) -> str:
    return await resolver().gethostbyaddr(ip)


async def async_address_info(host_or_ip: str) -> dict[str, str]:
    logging.info("Resolving %s...", host_or_ip)
    ip = (await async_gethostbyname(host_or_ip)).addresses[0]

    is_ip = ip == host_or_ip

    host = host_or_ip
    if is_ip:
        try:
            host = (await async_gethostbyaddr(ip)).name
        except Exception:
            pass
    logging.info("Resolved %s to (%s %s)...", host_or_ip, host, ip)
    return {"host": host, "ip": ip}


def resolve_addresses(
    addresses: Iterable[str],
) -> tuple[dict[str, str], dict[str, str]]:
    addr_map, errors = {}, {}
    for address in addresses:
        try:
            info = address_info(address)
            addr_map.setdefault(info["ip"], []).append(info)
        except OSError as error:
            errors[address] = f"[{error.errno}]: {error.strerror}"
    return addr_map, errors


async def async_resolve_addresses(
    addresses: Iterable[str],
) -> tuple[dict[str, str], dict[str, str]]:
    addr_map, errors = {}, {}

    async def resolve(address):
        try:
            info = await async_address_info(address)
            addr_map.setdefault(info["ip"], []).append(info)
        except aiodns.error.DNSError as error:
            errors[address] = f"[{error.args[0]}]: {error.args[1]}"
        except Exception as error:
            errors[address] = str(error)

    async with asyncio.TaskGroup() as tg:
        _ = [tg.create_task(resolve(address)) for address in addresses]
    return addr_map, errors


def socket_wait_response(sock: socket.socket, timeout: float | None = None):
    logging.debug("waiting for reply...")
    r, _, _ = select.select((sock,), (), (), timeout)
    if not r:
        raise TimeoutError()
    logging.debug("received reply")


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
            raise TimeoutError()
        r, _, _ = select.select(socks, (), (), tout)
        if not r:
            raise TimeoutError()
        yield from r
        socks -= set(r)


def socket_recvfrom_timeout(sock: socket.socket, size: int = 1024, timeout: float | None = None) -> bytes:
    socket_wait_response(sock, timeout)
    return sock.recvfrom(size)


def socket_send_one_ping_payload(sock: socket.socket, ip: str, payload: bytes):
    n = sock.sendto(payload, (ip, 0))
    assert n == len(payload)


def socket_send_one_ping(sock: socket.socket, ips: list[str], icmp_id: int, icmp_seq: int = 1):
    payload = socket_encode_request(sock, icmp_id, icmp_seq)
    for ip in ips:
        logging.info("sending ping to %s...", ip)
        socket_send_one_ping_payload(sock, ip, payload)


def socket_read_one_ping(sock: socket.socket) -> dict:
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
    logging.info("read one ping from %s (seq=%s)...", address[0], response["sequence"])
    return response


def socket_receive_one_ping(sock: socket.socket, timeout: float | None = None) -> dict:
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
