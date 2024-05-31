import errno
import socket
import struct
import sys
import time
import uuid

HEADER_FORMAT = "!BBHHH"
HEADER = struct.Struct(HEADER_FORMAT)

TIME_FORMAT = "d"
TIME = struct.Struct(TIME_FORMAT)

ICMPv4 = socket.getprotobyname("icmp")
ICMPv6 = socket.getprotobyname("ipv6-icmp")

ICMP_ECHO_REQUEST = 8
ICMP_ECHO_REPLY = 0

ICMP_DEFAULT_CODE = 0  # the code for ECHO_REPLY and ECHO_REQUEST
ICMP_DEFAULT_SIZE = 64


def checksum(source: bytes) -> int:
    # Even bytes (odd indexes) shift 1 byte to the left.
    result = sum(source[::2]) + (sum(source[1::2]) << (8))
    while result >= 0x10000:  # Ones' complement sum.
        result = sum(divmod(result, 0x10000))  # Each carry add to right most bit.
    return ~result & ((1 << 16) - 1)  # Ensure 16-bit


def request_packet(
    request: int = ICMP_ECHO_REQUEST,
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
    header = HEADER.pack(ICMP_ECHO_REQUEST, 0, csum, icmp_id, sequence)
    return header + payload


def reply_packet(source: bytes):
    type_, code, csum, packet_id, sequence = HEADER.unpack_from(source, offset=0)
    if type_ not in (ICMP_ECHO_REPLY,):
        return
    (time_sent,) = TIME.unpack_from(source, offset=HEADER.size)
    return type_, code, csum, packet_id, sequence, time_sent


def icmp_socket(
    family: socket.AddressFamily = socket.AF_INET,
    type: socket.SocketKind | None = None,
    proto: int | None = None,
) -> socket.socket:
    if proto is None:
        proto = ICMPv4 if family == socket.AF_INET else ICMPv6

    if type is None:
        try:
            return icmp_socket(family, socket.SOCK_RAW, proto)
        except PermissionError as err:
            if err.errno != errno.EPERM:  # [Errno 1] Operation not permitted
                raise
            return icmp_socket(family, socket.SOCK_DGRAM, proto)
    else:
        return socket.socket(family, type, proto)


def main():
    host = sys.argv[1]
    ip = socket.gethostbyname(host)
    sock = icmp_socket()

    my_id = uuid.uuid4().int & 0xFFFF
    packet = request_packet(icmp_id=my_id)
    sock.sendto(packet, (ip, 0))
    reply = sock.recv(1024)
    time_received = time.perf_counter()
    type_, code, csum, packet_id, sequence, time_sent = reply_packet(reply)

    id_ = sock.getsockname()[1]
    if packet_id != id_:
        print(f"Wrong ID. Expected {id_}. Got {packet_id}!")

    dt = time_received - time_sent
    print(f"{len(reply)} bytes from {host} time={dt*1000:.1f}ms")


if __name__ == "__main__":
    main()
