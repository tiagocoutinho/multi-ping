import argparse
import collections
import errno
import ipaddress
import logging
import os
import platform
import random
import select
import socket
import struct
import sys
import time
import uuid

HEADER_FORMAT = "!BBHHH"
HEADER = struct.Struct(HEADER_FORMAT)

IP_HEADER_FORMAT = "!BBHHHBBHII"
IP_HEADER = struct.Struct(IP_HEADER_FORMAT)

TIME_FORMAT = "d"
TIME = struct.Struct(TIME_FORMAT)

ICMP_DEFAULT_CODE = 0  # the code for ECHO_REPLY and ECHO_REQUEST
ICMP_DEFAULT_SIZE = 64

# No IP Header when unpriviledged on Linux
CAN_HAVE_IP_HEADER = os.name != "posix" or platform.system() == "Darwin"

ERROR, OK = 0, 1


class Result(collections.namedtuple("Result", "type value")):
    """Execution result. Similar to Rust result"""

    def is_ok(self):
        return self.type == OK

    def is_err(self):
        return self.type == ERROR


def Ok(v) -> Result:
    return Result(OK, v)


def Err(e) -> Result:
    return Result(ERROR, e)


Result.ok = Ok
Result.err = Err


class PingError(Exception):
    ...


ERRORS = {
    3: {
        0: "Destination network unreachable",
        1: "Destination host unreachable",
        2: "Destination protocol unreachable",
        3: "Destination port unreachable",
        4: "Fragmentation required",
        5: "Source route failed",
        6: "Destination network unknown",
        7: "Destination host unknown",
        8: "Source host isolated",
        9: "Network administratively prohibited",
        10: "Host administratively prohibited",
        11: "Network unreachable for ToS",
        12: "Host unreachable for ToS",
        13: "Communication administratively prohibited",
        14: "Host Precedence Violation",
        15: "Precedence cutoff in effect",
    }
}


class ICMPv4:
    family = socket.AF_INET
    proto = socket.getprotobyname("icmp")
    ECHO_REQUEST = 8
    ECHO_REPLY = 0


class ICMPv6:
    family = socket.AF_INET6
    proto = socket.getprotobyname("ipv6-icmp")
    ECHO_REQUEST = 128
    ECHO_REPLY = 129


def checksum(source: bytes) -> int:
    # Even bytes (odd indexes) shift 1 byte to the left.
    result = sum(source[::2]) + (sum(source[1::2]) << (8))
    while result >= 0x10000:  # Ones' complement sum.
        result = sum(divmod(result, 0x10000))  # Each carry add to right most bit.
    return ~result & ((1 << 16) - 1)  # Ensure 16-bit


class Response:
    def __init__(self, data: bytes, has_ip_header: bool, icmp_id: int, time_received: float):
        self.data = data
        self.has_ip_header = has_ip_header
        self.expected_icmp_id = icmp_id
        type_, code, _csum, packet_id, sequence = raw_echo_reply_packet(
            data, has_ip_header
        )
        self.type = type_
        self.code = code
        self.packet_id = packet_id
        self.sequence = sequence
        self.time_received = time_received

    def __len__(self):
        return len(self.data)

    @property
    def is_echo(self) -> bool:
        return self.type in {ICMPv4.ECHO_REPLY, ICMPv6.ECHO_REPLY}

    @property
    def matches_id(self) -> bool:
        return self.packet_id == self.expected_icmp_id

    def is_ok(self) -> bool:
        return not self.is_err()

    def is_err(self) -> bool:
        return self.type in ERRORS

    @property
    def error(self):
        return ERRORS[self.type][self.code]

    @property
    def time_sent(self) -> float:
        offset = IP_HEADER.size if self.has_ip_header else 0
        (time_sent,) = TIME.unpack_from(self.data, offset=offset + HEADER.size)
        return time_sent

    @property
    def dt(self) -> float:
        return self.time_received - self.time_sent


def echo_request_packet(
    request: int = ICMPv4.ECHO_REQUEST,
    code: int = ICMP_DEFAULT_CODE,
    icmp_id: int = 1,
    sequence: int = 1,
) -> bytes:
    header = HEADER.pack(request, code, 0, icmp_id, sequence)
    padding = (
        ICMP_DEFAULT_SIZE - HEADER.size - TIME.size
    ) * b"Q"  # Using double to store current time.
    payload = TIME.pack(time.perf_counter()) + padding
    csum = checksum(header + payload)
    header = HEADER.pack(request, 0, csum, icmp_id, sequence)
    return header + payload


def raw_reply_packet(source: bytes, has_ip_header: bool = False) -> tuple:
    offset = IP_HEADER.size if has_ip_header else 0
    return HEADER.unpack_from(source, offset=offset)


def raw_echo_reply_packet(source: bytes, has_ip_header: bool = False) -> tuple:
    offset = IP_HEADER.size if has_ip_header else 0
    return HEADER.unpack_from(source, offset=offset)


def echo_reply_packet(
    has_ip_header: bool, icmp_id: int, source: bytes, time_received: float
) -> Response:
    response = Response(source, has_ip_header, icmp_id, time_received)
    if not response.is_echo:
        return Err(PingError(f"Wrong type: {response.type}"))
    if response.packet_id != icmp_id:
        return Err(PingError(f"Wrong ID. Expected {icmp_id}. Got {response.packet_id}!"))
    return response


def icmp_socket(
    family: socket.AddressFamily = socket.AF_INET,
    type: socket.SocketKind | None = None,
    proto: int | None = None,
    timeout: float = 0, # 0 means non blocking
) -> socket.socket:
    if proto is None:
        proto = ICMPv4.proto if family == socket.AF_INET else ICMPv6.proto

    if type is None:
        try:
            return icmp_socket(family, socket.SOCK_RAW, proto, timeout)
        except PermissionError as err:
            if err.errno != errno.EPERM:  # [Errno 1] Operation not permitted
                raise
            return icmp_socket(family, socket.SOCK_DGRAM, proto, timeout)
    else:
        sock = socket.socket(family, type, proto)
        sock.settimeout(timeout)
        return sock


def resolved_from_address(address, sock_family, sock_type) -> Result:
    logging.debug("Resolving %s...", address)
    try:
        info = socket.getaddrinfo(address, 0, sock_family)
    except socket.error as error:
        return Err(error)
    info = list(filter(lambda i: i[1] == sock_type, info))
    result = Ok(random.choice(info)[4])
    logging.debug("Resolved %s to %s", address, result.value)
    return result


def send_to(sock, payload, address):
    logging.debug("sending %d bytes to %s",len(payload), address[0])
    try:
        return Ok(sock.sendto(payload, address))
    except socket.error as error:
        return Err(error)


def recv_from(sock, n = 1024):
    try:
        payload, address = sock.recvfrom(n)
    except socket.error as error:
        return Err(error)
    logging.debug("received %d bytes from %s",len(payload), address)
    return Ok((payload, address))


def recv_from_timeout(sock, n = 1024, timeout=None):
    try:
        logging.info("waiting for reply (timeout=%6.3fs)...", timeout)
        r, _, _ = select.select((sock,), (), (), timeout)
    except socket.error as error:
        return Err(error)
    if not r:
        return Err(TimeoutError("read timeout"))
    return recv_from(sock, n)


def ping(sock: socket.socket, icmp_id: int, address: str):
    packet = echo_request_packet(icmp_id=icmp_id)
    sock.sendto(packet, address)
    while True:
        data, resolved_address = sock.recvfrom(1024)
        time_received = time.perf_counter()
        if response := echo_reply_packet(sock, icmp_id, data, time_received):
            response.address = resolved_address[0]
            return response


def check_elapsed(timeout_at: float | None):
    if timeout_at is None:
        return
    if time.monotonic() >= timeout_at:
        raise TimeoutError("timeout")


class Socket:

    def __init__(self, sock: socket.socket, timeout: float | None = None):
        self.socket = sock
        self.timeout = timeout

    def __enter__(self):
        if self.timeout:
            self.end = time.monotonic() + self.timeout
        else:
            self.end = None
        return self
    
    def __exit__(self, *args):
        pass

    def has_ip_header(self):
        return CAN_HAVE_IP_HEADER or self.socket.type == socket.SOCK_RAW

    def get_ip(self) -> str:
        return self.socket.getsockname()[0]

    def get_port(self) -> int:
        return self.socket.getsockname()[1]

    def get_timeout(self):
        if self.timeout is None:
            return None
        return self.end - time.monotonic()

    def read(self, n = 1024):
        timeout = self.get_timeout()
        if timeout is not None and timeout <= 0:
            return Err(TimeoutError("timed out"))
        return recv_from_timeout(self.socket, n, timeout)

    def write(self, buff, address):
        return send_to(self.socket, buff, address)


def raw_pings(sock: Socket, icmp_id: int, addresses: dict[str, tuple[str, int]]):
    packet = echo_request_packet(icmp_id=icmp_id)
    reversed_addresses = {}
    for address, resolved in addresses.items():
        if resolved.is_ok():
            result = sock.write(packet, resolved.value)
            if result.is_ok():
                reversed_addresses[resolved.value[0]] = address
            else:
                yield result
        else:
            yield Err(PingError(f"{address}: {resolved.value}"))
    has_ip_header = sock.has_ip_header()
    if not has_ip_header:
        icmp_id = sock.get_port()
    for _ in range(len(reversed_addresses)):
        result = sock.read()
        time_received = time.perf_counter()
        if result.is_err():
            yield result
            return
        data, addr = result.value
        if response := echo_reply_packet(has_ip_header, icmp_id, data, time_received):
            address = addr[0]
            if response.is_err():
                yield response
            else:
                yield Ok((reversed_addresses.get(address), address, response))


def pings(sock: socket.socket, icmp_id: int, addresses: list[str], timeout: float | None = 0.2):
    with Socket(sock, timeout) as reader:
        addresses = {address: resolved_from_address(address, sock.family, sock.type) for address in addresses}
        yield from raw_pings(reader, icmp_id, addresses)


def new_id():
    return uuid.uuid4().int & 0xFFFF


def main():

    fmt = "%(asctime)s %(threadName)s %(levelname)s %(name)s %(message)s"
    logging.basicConfig(level="DEBUG", format=fmt)
    addresses = sys.argv[1:]
    sock = icmp_socket()
    me = new_id()
    for response in pings(sock, me, addresses, timeout=1):
        if response.is_err():
            print(response.value)
        else:
            ip, host, resp = response.value
            real_host = socket.gethostbyaddr(ip)[0]
            print(
                f"{len(resp)} bytes from {host} {real_host} ({ip}): icmp_seq={resp.sequence} time={resp.dt*1000:.1f}ms"
            )


if __name__ == "__main__":
    main()


