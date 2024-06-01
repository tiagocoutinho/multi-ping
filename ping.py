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


def echo_reply_packet(sock: socket.socket, icmp_id: int, source: bytes) -> tuple:
    has_ip_header = CAN_HAVE_IP_HEADER or sock.type == socket.SOCK_RAW
    offset = IP_HEADER.size if has_ip_header else 0
    type_, code, csum, packet_id, sequence = HEADER.unpack_from(source, offset=offset)
    if type_ not in {ICMPv4.ECHO_REPLY, ICMPv6.ECHO_REPLY}:
        print(f"Wrong type: {type_}")
        return
    if not has_ip_header:
        icmp_id = sock.getsockname()[1]
    if packet_id != icmp_id:
        print(f"Wrong ID. Expected {icmp_id}. Got {packet_id}!")
        return
    (time_sent,) = TIME.unpack_from(source, offset=offset + HEADER.size)
    return type_, code, csum, packet_id, sequence, time_sent


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
        return socket.socket(family, type, proto)


def resolved_from_address(address, sock):
    info = socket.getaddrinfo(address, 0, sock.family)
    info = list(filter(lambda i: i[1] == sock.type, info))
    return random.choice(info)[4]


def ping(sock, icmp_id, address):
    resolved_address = resolved_from_address(address, sock)
    packet = echo_request_packet(icmp_id=icmp_id)
    sock.sendto(packet, resolved_address)
    while True:
        data = sock.recv(1024)
        time_received = time.perf_counter()
        if reply := echo_reply_packet(sock, icmp_id, data):
            break
    type_, code, _, packet_id, seq, time_sent = reply
    result = PingResult(
        address,
        resolved_address,
        data,
        type_,
        code,
        packet_id,
        seq,
        time_sent,
        time_received,
    )
    return result


class PingResult:
    def __init__(
        self, host, addr, data, type_, code, packet_id, sequence, sent, received
    ):
        self.host = host
        self.addr = addr
        self.data = data
        self.type = type_
        self.code = code
        self.packet_id = packet_id
        self.sequence = sequence
        self.time_sent = sent
        self.time_received = received

    def __len__(self):
        return len(self.data)

    @property
    def dt(self):
        return self.time_received - self.time_sent

    @property
    def ip(self):
        return self.addr[0]

    @property
    def real_host(self):
        return socket.gethostbyaddr(self.ip)[0]


class ICMP:
    def __init__(self, protocol=ICMPv4):
        self.id = uuid.uuid4().int & 0xFFFF
        self.protocol = protocol
        self.socket = icmp_socket(protocol.family, proto=protocol.proto)

    def ping(self, address):
        return ping(self.socket, self.id, address)


def main():
    address = sys.argv[1]
    icmp = ICMP()
    result = icmp.ping(address)
    print(f"PING {result.host} ({result.ip})")
    print(
        f"{len(result)} bytes from {result.real_host} ({result.ip}): icmp_seq={result.sequence} time={result.dt*1000:.1f}ms"
    )


if __name__ == "__main__":
    main()
