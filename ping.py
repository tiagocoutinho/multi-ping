import errno
import os
import platform
import random
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


ICMP_DEFAULT_CODE = 0  # the code for ECHO_REPLY and ECHO_REQUEST
ICMP_DEFAULT_SIZE = 64

# No IP Header when unpriviledged on Linux
CAN_HAVE_IP_HEADER = os.name != "posix" or platform.system() == "Darwin"


def checksum(source: bytes) -> int:
    # Even bytes (odd indexes) shift 1 byte to the left.
    result = sum(source[::2]) + (sum(source[1::2]) << (8))
    while result >= 0x10000:  # Ones' complement sum.
        result = sum(divmod(result, 0x10000))  # Each carry add to right most bit.
    return ~result & ((1 << 16) - 1)  # Ensure 16-bit


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
    sock: socket.socket, icmp_id: int, source: bytes, time_received: float
) -> tuple:
    has_ip_header = CAN_HAVE_IP_HEADER or sock.type == socket.SOCK_RAW
    response = Response(source, has_ip_header, time_received)
    if not response.is_echo:
        print(f"Wrong type: {response.type}")
        return
    if not has_ip_header:
        icmp_id = sock.getsockname()[1]
    if response.packet_id != icmp_id:
        print(f"Wrong ID. Expected {icmp_id}. Got {response.packet_id}!")
        return
    return response


def icmp_socket(
    family: socket.AddressFamily = socket.AF_INET,
    type: socket.SocketKind | None = None,
    proto: int | None = None,
) -> socket.socket:
    if proto is None:
        proto = ICMPv4.proto if family == socket.AF_INET else ICMPv6.proto

    if type is None:
        try:
            return icmp_socket(family, socket.SOCK_RAW, proto)
        except PermissionError as err:
            if err.errno != errno.EPERM:  # [Errno 1] Operation not permitted
                raise
            return icmp_socket(family, socket.SOCK_DGRAM, proto)
    else:
        sock = socket.socket(family, type, proto)
        return sock


def resolved_from_address(address, sock):
    info = socket.getaddrinfo(address, 0, sock.family)
    info = list(filter(lambda i: i[1] == sock.type, info))
    return random.choice(info)[4]


def ping(sock: socket.socket, icmp_id: int, address: str):
    resolved_address = resolved_from_address(address, sock)
    packet = echo_request_packet(icmp_id=icmp_id)
    sock.sendto(packet, resolved_address)
    while True:
        data = sock.recv(1024)
        time_received = time.perf_counter()
        if response := echo_reply_packet(sock, icmp_id, data, time_received):
            response.address = resolved_address[0]
            return response


def pings(sock: socket.socket, icmp_id: int, addresses: list[str]):
    resolved_addresses = [resolved_from_address(address, sock) for address in addresses]
    packet = echo_request_packet(icmp_id=icmp_id)
    for resolved_address in resolved_addresses:
        sock.sendto(packet, resolved_address)
    for i in range(len(addresses)):
        data, addr = sock.recvfrom(1024)
        time_received = time.perf_counter()
        if response := echo_reply_packet(sock, icmp_id, data, time_received):
            response.address = addr[0]
            yield response


class Response:
    def __init__(self, data: bytes, has_ip_header: bool, time_received: float):
        self.address = None
        self.data = data
        self.has_ip_header = has_ip_header
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
    def time_sent(self) -> float:
        offset = IP_HEADER.size if self.has_ip_header else 0
        (time_sent,) = TIME.unpack_from(self.data, offset=offset + HEADER.size)
        return time_sent

    @property
    def dt(self) -> float:
        return self.time_received - self.time_sent


class ICMP:
    def __init__(self, protocol=ICMPv4):
        self.id = uuid.uuid4().int & 0xFFFF
        self.protocol = protocol
        self.socket = icmp_socket(protocol.family)

    def ping(self, address) -> Response:
        return ping(self.socket, self.id, address)

    def pings(self, addresses) -> Response:
        return pings(self.socket, self.id, addresses)


def main():
    addresses = sys.argv[1:]
    icmp = ICMP()
    for response in icmp.pings(addresses):
        ip = response.address
        real_host = socket.gethostbyaddr(ip)[0]
        print(
            f"{len(response)} bytes from {real_host} ({ip}): icmp_seq={response.sequence} time={response.dt*1000:.1f}ms"
        )


if __name__ == "__main__":
    main()
