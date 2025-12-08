#
# This file is part of the yaping project
#
# Copyright (c) 2024 Tiago Coutinho
# Distributed under the GPLv3 license. See LICENSE for more info.

import ctypes
import socket
import struct
import time

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

ECHO_REQUEST = 8
ECHO_REPLY = 0
ECHO_V6_REQUEST = 128
ECHO_V6_REPLY = 129


class ICMPv4:
    family = socket.AF_INET
    proto = socket.IPPROTO_ICMP
    ECHO_REQUEST = ECHO_REQUEST
    ECHO_REPLY = ECHO_REPLY


class ICMPv6:
    family = socket.AF_INET6
    proto = socket.IPPROTO_ICMPV6
    ECHO_REQUEST = ECHO_V6_REQUEST
    ECHO_REPLY = ECHO_V6_REPLY


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


def checksum(payload: bytes) -> int:
    """16-bit checksum of the given payload"""
    # Even bytes (odd indexes) shift 1 byte to the left.
    result = sum(payload[::2]) + (sum(payload[1::2]) << (8))
    while result >= 0x10000:  # Ones' complement sum.
        result = sum(divmod(result, 0x10000))  # Each carry add to right most bit.
    return ~result & ((1 << 16) - 1)  # Ensure 16-bit


def encode_request(
    request: int = ICMPv4.ECHO_REQUEST,
    icmp_id: int = 1,
    icmp_seq: int = 1,
    timestamp: float | None = None,
) -> bytes:
    """Encode ping into bytes"""
    header = bytes(Header(request, ICMP_DEFAULT_CODE, 0, icmp_id, icmp_seq))
    padding = (ICMP_DEFAULT_SIZE - len(header) - TIME.size) * b"Q"  # Using double to store current time.
    if timestamp is None:
        timestamp = time.perf_counter()
    payload = TIME.pack(timestamp) + padding
    csum = checksum(header + payload)
    header = HEADER.pack(request, ICMP_DEFAULT_CODE, csum, icmp_id, icmp_seq)
    return header + payload


def decode_response(payload: bytes, with_ip_header: bool = False) -> dict:
    offset = IP_HEADER.size if with_ip_header else 0
    header = Header.from_buffer_copy(payload, offset)
    if header.type not in {ICMPv4.ECHO_REPLY, ICMPv6.ECHO_REPLY}:
        raise ValueError(f"Wrong type: {header.type}")
    (time_sent,) = TIME.unpack_from(payload, offset=offset + HEADER.size)
    return {
        **header._asdict(),
        "time_sent": time_sent,
        "payload": payload,
        "size": len(payload),
    }
