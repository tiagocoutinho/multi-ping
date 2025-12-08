#
# This file is part of the yaping project
#
# Copyright (c) 2024 Tiago Coutinho
# Distributed under the GPLv3 license. See LICENSE for more info.

import asyncio
import time
import uuid

SENTINEL = object()


def new_id() -> int:
    """Return a "unique" 16-bit integer ID"""
    return uuid.uuid4().int & 0xFFFF


def cycle(start: int = 1, stop: int = 2**16, step: int = 1):
    """Helper to cycle sequence of numbers"""
    while True:
        yield from range(start, stop, step)


def response_text(response):
    ip = response["ip"]
    host = response["host"]
    error = response.get("error", SENTINEL)
    if error is not SENTINEL:
        return f"{host} ({ip}): {error}"
    size = response["size"]
    seq = response["sequence"]
    t = response["time"] * 1000

    ts = time.time()

    return f"[{ts:.3f}] {size} bytes from {host} ({ip}): icmp_seq={seq} time={t:.1f}ms"


STATS_TEMPLATE = """\
--- {host} ping statistics ---
{total} packets transmitted, {ok} received, {loss}% packet loss
rtt min/max/avg (ms) = {min:.3f}/{max:.3f}/{avg:.3f}\
"""


class HostStats:
    def __init__(self, ip, host):
        self.ip = ip
        self.host = host
        self.errors = 0
        self.max = 0
        self.min = 99999999
        self.sum = 0
        self.total = 0

    @property
    def loss(self):
        return self.errors / self.total

    @property
    def ok(self):
        return self.total - self.errors

    @property
    def avg(self):
        return self.sum / self.total

    def __str__(self):
        fmt = {
            "host": self.host,
            "ok": self.ok,
            "loss": int(self.loss * 100),
            "min": self.min * 1000,
            "max": self.max * 1000,
            "avg": self.avg * 1000,
            "total": self.total,
        }
        return STATS_TEMPLATE.format(**fmt)


class PingStats:
    def __init__(self, stream):
        self.stream = stream
        self.stats = {}

    def update_stats(self, result):
        ip = result["ip"]
        if (stats := self.stats.get(ip, SENTINEL)) is SENTINEL:
            stats = self.stats[ip] = HostStats(ip, result["host"])
        stats.total += 1
        if "error" in result:
            stats.errors += 1
        else:
            dt = result["time"]
            stats.max = max(stats.max, dt)
            stats.min = min(stats.min, dt)
            stats.sum += dt
        result["min_time"] = stats.min
        result["max_time"] = stats.max
        result["avg_time"] = stats.avg
        result["total_nb"] = stats.total
        result["nb_requests"] = stats.total
        result["nb_ok"] = stats.ok
        result["nb_errors"] = stats.errors
        result["accum_time"] = stats.sum
        result["loss"] = stats.loss

        return result

    def __iter__(self):
        for result in self.stream:
            yield self.update_stats(result)

    async def __aiter__(self):
        async for result in self.stream:
            yield self.update_stats(result)

    def __str__(self):
        return "\n".join(str(stats) for stats in self.stats.values() if stats.ok)


def intervals(stream, interval: float, strict: bool = False):
    if strict:
        start = time.perf_counter()
        for i, result in enumerate(stream, start=1):
            yield result
            if (dt := i * interval + start - time.perf_counter()) > 0:
                time.sleep(dt)
    else:
        for result in stream:
            yield result
            time.sleep(interval)


async def async_intervals(stream, interval: float, strict: bool = False):
    if strict:
        start = time.perf_counter()
        for i, result in enumerate(stream, start=1):
            yield result
            if (dt := i * interval + start - time.perf_counter()) > 0:
                await asyncio.sleep(dt)
    else:
        for result in stream:
            yield result
            await asyncio.sleep(interval)
