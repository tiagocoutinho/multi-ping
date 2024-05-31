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


def checksum(buffer):
    length = len(buffer)
    csum = 0
    i = 0
    while length > 1:
        csum += buffer[i + 1] + (buffer[i + 0] << 8)
        csum &= 0xffff_ffff
        length -= 2
        i += 2

    if i < len(buffer):
        csum += buffer[-1]
        csum &= 0xffff_ffff

    csum = (csum >> 16) + (csum & 0xffff)  # Fold high 16 bits
    csum += (csum >> 16)
    return ~csum & 0xffff


my_id = uuid.uuid4().int & 0xFFFF
header = HEADER.pack(ICMP_ECHO_REQUEST, 0, 0, my_id, 1)
bytes_in_double = struct.calcsize("d")
data = (192 - bytes_in_double) * b"Q"
data = struct.pack("d", time.perf_counter()) + data
csum = checksum(header + data)
header = HEADER.pack(ICMP_ECHO_REQUEST, 0, csum, my_id, 1)
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