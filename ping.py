import errno
import os
import platform
import socket
import struct
import sys
import time
import uuid

HEADER_FORMAT = "!BBHHH"
HEADER = struct.Struct(HEADER_FORMAT)

TIME_FORMAT = "d"
TIME = struct.Struct(TIME_FORMAT)


class ICMPv4:
    proto = socket.getprotobyname("icmp")
    ECHO_REQUEST = 8
    ECHO_REPLY = 0


class ICMPv6:
    proto = socket.getprotobyname("ipv6-icmp")
    ECHO_REQUEST = 128
    ECHO_REPLY = 129


ICMP_DEFAULT_CODE = 0  # the code for ECHO_REPLY and ECHO_REQUEST
ICMP_DEFAULT_SIZE = 64

# No IP Header when unpriviledged on Linux
CAN_HAVE_IP_HEADER = os.name != 'posix' or platform.system() == 'Darwin'


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


def echo_reply_packet(source: bytes, has_ip_header = False):
    offset = 20 if has_ip_header else 0
    type_, code, csum, packet_id, sequence = HEADER.unpack_from(source, offset=offset)
    if type_ not in {ICMPv4.ECHO_REPLY, ICMPv6.ECHO_REPLY}:
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


def main():
    host = sys.argv[1]
    ip = socket.gethostbyname(host)
    real_host = socket.gethostbyaddr(ip)[0]
    sock = icmp_socket()

    my_id = uuid.uuid4().int & 0xFFFF
    packet = echo_request_packet(icmp_id=my_id)
    sock.sendto(packet, (ip, 0))
    reply = sock.recv(1024)
    time_received = time.perf_counter()
    type_, code, csum, packet_id, icmp_seq, time_sent = echo_reply_packet(reply)

    id_ = sock.getsockname()[1]
    if packet_id != id_:
        print(f"Wrong ID. Expected {id_}. Got {packet_id}!")

    dt = time_received - time_sent
    print(f"PING {host} ({ip})")
    print(f"{len(reply)} bytes from {real_host} ({ip}): {icmp_seq=} time={dt*1000:.1f}ms")


if __name__ == "__main__":
    main()
