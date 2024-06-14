import ctypes
import functools
import logging
import os
import platform
import select
import socket
import struct
import time
import uuid

HEADER_FORMAT = "!BBHHH"
HEADER = struct.Struct(HEADER_FORMAT)

class Header(ctypes.BigEndianStructure):
    _fields_ = [
        ("type", ctypes.c_uint8),
        ("code", ctypes.c_uint8),
        ("checksum", ctypes.c_uint16),
        ("id", ctypes.c_uint16),
        ("sequence", ctypes.c_uint16),
    ]

    def _asdict(self):
        return {k: getattr(self, k) for k, _ in self._fields_}


class Packet(ctypes.BigEndianStructure):
    _fields_ = [
        ("type", ctypes.c_uint8),
        ("code", ctypes.c_uint8),
        ("checksum", ctypes.c_uint16),
        ("id", ctypes.c_uint16),
        ("sequence", ctypes.c_uint16),
        ("time_sent", ctypes.c_double),
    ]


IP_HEADER_FORMAT = "!BBHHHBBHII"
IP_HEADER = struct.Struct(IP_HEADER_FORMAT)

TIME_FORMAT = "d"
TIME = struct.Struct(TIME_FORMAT)

PACKET_FORMAT = HEADER_FORMAT + TIME_FORMAT
PACKET = struct.Struct(PACKET_FORMAT)

ICMP_DEFAULT_CODE = 0  # the code for ECHO_REPLY and ECHO_REQUEST
ICMP_DEFAULT_SIZE = 64
ICMP_DEFAULT_PAYLOAD = ICMP_DEFAULT_SIZE * b"Q"

# No IP Header when unpriviledged on Linux
CAN_HAVE_IP_HEADER = os.name != "posix" or platform.system() == "Darwin"

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


def checksum(payload: bytes) -> int:
    """16-bit checksum of the given payload"""
    # Even bytes (odd indexes) shift 1 byte to the left.
    result = sum(payload[::2]) + (sum(payload[1::2]) << (8))
    while result >= 0x10000:  # Ones' complement sum.
        result = sum(divmod(result, 0x10000))  # Each carry add to right most bit.
    return ~result & ((1 << 16) - 1)  # Ensure 16-bit


def new_id() -> int:
    """Return a "unique" 16-bit integer ID"""
    return uuid.uuid4().int & 0xFFFF


def cycle(start: int = 1, stop: int = 2**16, step: int = 1):
    """Helper to cycle sequence of numbers"""
    while True:
        yield from range(start, stop, step)


def encode_request(
    request: int = ICMPv4.ECHO_REQUEST,
    code: int = ICMP_DEFAULT_CODE,
    icmp_id: int = 1,
    icmp_seq: int = 1,
    timestamp: float | None = None,
) -> bytes:
    """Encode ping into bytes"""
    header = bytes(Header(request, code, 0, icmp_id, icmp_seq))
    padding = (
        ICMP_DEFAULT_SIZE - len(header) - TIME.size
    ) * b"Q"  # Using double to store current time.
    if timestamp is None:
        timestamp = time.perf_counter()
    payload = TIME.pack(timestamp) + padding
    csum = checksum(header + payload)
    header = HEADER.pack(request, code, csum, icmp_id, icmp_seq)
    return header + payload


def decode_response(data: bytes, with_ip_header: bool = False) -> dict:
    offset = IP_HEADER.size if with_ip_header else 0
    header = Header.from_buffer_copy(data, offset)
    if not header.type in {ICMPv4.ECHO_REPLY, ICMPv6.ECHO_REPLY}:
        raise ValueError(f"Wrong type: {header.type}")
    (time_sent,) = TIME.unpack_from(data, offset=offset + HEADER.size)
    return {    
        **header._asdict(),
        "time_sent": time_sent,
    }
    

def socket_has_ip_header(sock: socket.socket) -> bool:
    return CAN_HAVE_IP_HEADER or sock.type == socket.SOCK_RAW


def socket_ip(sock: socket.socket) -> str:
    return sock.getsockname()[0]


def socket_port(sock: socket.socket) -> int:
    return sock.getsockname()[1]


# I/O ------------------------------------------------------------------------


@functools.cache
def resolve_address(address: str, family: socket.AddressFamily, type: socket.SocketKind) -> str:
    logging.info("Resolving %s...", address)
    addresses = socket.getaddrinfo(address, 0, family, type)
    logging.info("Resolved %s to %s", address, addresses)
    return addresses[0][4][0]


@functools.cache
def host_from_ip(ip: str):
    logging.info("Resolving %s...", ip)
    host = socket.gethostbyaddr(ip)[0]
    logging.info("Resolved %s to %s", ip, host)
    return host


def socket_recvfrom_timeout(sock: socket.socket, size: int = 1024, timeout: float | None = None) -> bytes:
    logging.debug("waiting for reply (timeout=%6.3fs)...", timeout)
    r, _, _ = select.select((sock,), (), (), timeout)
    if not r:
        raise TimeoutError(f"read timeout after {timeout:.3f}s")
    return sock.recvfrom(size)


class ICMPSocket(socket.socket):
    """An ICMP socket"""

    def __init__(self, family: socket.AddressFamily = socket.AF_INET, type: socket.SocketKind | None = None, proto: int | None = None, timeout: float = 0):
        if proto is None:
            proto = ICMPv4.proto if family == socket.AF_INET else ICMPv6.proto

        if type is None:
            try:
                super().__init__(family, socket.SOCK_RAW, proto)
            except PermissionError:
                super().__init__(family, socket.SOCK_DGRAM, proto)
        else:
            super().__init__(family, socket.SOCK_RAW, proto)
        self.settimeout(timeout)

    has_ip_header: bool = property(socket_has_ip_header)
    ip: str = property(socket_ip)
    port: int = property(socket_port)
    recvfrom_timeout = socket_recvfrom_timeout


def send_one_ping(sock: socket.socket, host: str, icmp_id: int, sequence: int = 1):
    address = resolve_address(host, sock.family, sock.type)
    request = ICMPv4.ECHO_REQUEST if sock.family == socket.AF_INET else ICMPv6.ECHO_REQUEST
    payload = encode_request(request, icmp_id=icmp_id, icmp_seq=sequence)
    n = sock.sendto(payload, (address, 0))
    assert n == len(payload)

    
def receive_one_ping(sock: socket.socket, timeout: float | None = None):
    ip_header = socket_has_ip_header(sock)
    size = ICMP_DEFAULT_SIZE + (IP_HEADER.size if ip_header else 0)
    payload, address = socket_recvfrom_timeout(sock, size, timeout)
    time_received = time.perf_counter()
    assert len(payload) == size
    response = decode_response(payload, ip_header)
    response["time_received"] = time_received
    response["ip"] = address[0]
    response["payload"] = payload
    response["size"] = len(payload)
    response["time"] = time_received - response["time_sent"]
    return response


def one_ping(
    host: str,
    icmp_id: int | None = None,
    timeout: float | None = 1,
):
    if icmp_id is None:
        icmp_id = new_id()
    address = resolve_address(host, socket.AF_INET, socket.SOCK_DGRAM)
    sock = ICMPSocket()
    send_one_ping(sock, address, icmp_id)
    response = receive_one_ping(sock, timeout)
    response["host"] = host
    return response


def ping(
    host: str,
    icmp_id: int | None = None,
    interval: float = 1,
    count: int | None = None,
    timeout: float | None = 1,
):
    if icmp_id is None:
        icmp_id = new_id()
    address = resolve_address(host, socket.AF_INET, socket.SOCK_DGRAM)
    sequence = range(1, count + 1) if count else cycle()
    sock = ICMPSocket()
    for seq_id in sequence:
        send_one_ping(sock, address, icmp_id, seq_id)
        response = receive_one_ping(sock, timeout)
        response["host"] = host
        yield response
        time.sleep(interval)


if __name__ == "__main__":
    import sys
    print(one_ping(sys.argv[1]))