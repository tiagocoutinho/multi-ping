import socket
import struct
import sys
import time
import uuid

HEADER_FORMAT = "!BBHHH"
HEADER = struct.Struct(HEADER_FORMAT)

ICMP = socket.getprotobyname("icmp")
ICMP_ECHO_REQUEST = 8
ICMP_ECHO_REPLY = 0


def checksum(source: bytes) -> int:
    result = sum(source[::2]) + (sum(source[1::2]) << (8))  # Even bytes (odd indexes) shift 1 byte to the left.
    while result >= 0x10000:  # Ones' complement sum.
        result = sum(divmod(result, 0x10000))  # Each carry add to right most bit.
    return ~result & ((1 << 16) - 1)  # Ensure 16-bit


my_id = uuid.uuid4().int & 0xFFFF
sequence = 1
header = HEADER.pack(ICMP_ECHO_REQUEST, 0, 0, my_id, sequence)
bytes_in_double = struct.calcsize("d")
data = (192 - bytes_in_double) * b"Q"
data = struct.pack("d", time.perf_counter()) + data
csum = checksum(header + data)
header = HEADER.pack(ICMP_ECHO_REQUEST, 0, csum, my_id, sequence)
packet = header + data

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, ICMP)
host = sys.argv[1]
sock.sendto(packet, (host, 0))
reply = sock.recv(1024)
time_received = time.perf_counter()
header = reply[:8]
type_, code, csum, packet_id, sequence = struct.unpack("!BBHHH", header)
if type_ != ICMP_ECHO_REPLY:
    print(f"Wrong packet {type_}!")

id_ = sock.getsockname()[1]

if packet_id != id_:
    print(type_, code, csum, packet_id, sequence)
    print(f"Wrong ID. Expected {id_}. Got {packet_id}!")

data = reply[8:8 + bytes_in_double]
time_sent = struct.unpack("d", data)[0]
dt = time_received - time_sent
print(f"time={dt*1000:.1f}ms")