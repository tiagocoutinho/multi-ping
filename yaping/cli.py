#
# This file is part of the yaping project
#
# Copyright (c) 2024 Tiago Coutinho
# Distributed under the GPLv3 license. See LICENSE for more info.

import argparse
import asyncio
import ipaddress
import logging
from collections.abc import Iterable

from . import aioping, ping, tools

# from .host import ping_many
from .tools import response_text


def addresses_args(text):
    try:
        return [str(addr) for addr in ipaddress.ip_network(text)]
    except ValueError:
        return [text]


def cmd_line_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-i",
        "--interval",
        type=float,
        help="wait interval between group of pings (seconds)",
        default=1,
    )
    parser.add_argument(
        "--strict-interval",
        help="interpret interval as a period and make sure a ping is launched every period compensating for any drift",
        action="store_true",
    )
    parser.add_argument(
        "-w",
        "--timeout",
        type=float,
        help="time to wait for response (seconds)",
        default=1,
    )
    parser.add_argument("-c", "--count", type=int, help="stop after sending count pings", default=None)
    parser.add_argument(
        "--log-level",
        choices=["debug", "info", "warn", "error"],
        help="log level",
        default="warn",
    )
    parser.add_argument(
        "--async",
        help="use asyncio",
        action="store_true",
    )
    parser.add_argument("addresses", type=addresses_args, nargs="+", help="host names, IPs or networks")
    return parser


def parse_cmd_line_args(args=None) -> argparse.Namespace:
    parser = cmd_line_parser()
    return parser.parse_args(args)


def init(args=None) -> tuple[argparse.Namespace, list[str]]:
    args = parse_cmd_line_args(args)
    fmt = "%(asctime)s %(threadName)s %(levelname)s %(name)s %(message)s"
    logging.basicConfig(level=args.log_level.upper(), format=fmt)
    addresses = [addr for addresses in args.addresses for addr in addresses]
    return args, addresses


async def async_run(addresses: Iterable[str], **kwargs):
    stream = aioping.ping(addresses, **kwargs)
    stats = tools.PingStats(stream)
    try:
        async for response in stats:
            print(response_text(response))
    except asyncio.exceptions.CancelledError:
        print()
    finally:
        print(stats)


def run(addresses: Iterable[str], **kwargs):
    stream = ping.ping(addresses, **kwargs)
    stats = tools.PingStats(stream)
    try:
        for response in stats:
            print(response_text(response))
    except KeyboardInterrupt:
        print()
    finally:
        print(stats)


def main(args=None):
    args, addresses = init(args)
    kwargs = vars(args)
    del kwargs["log_level"]
    del kwargs["addresses"]
    use_async = kwargs.pop("async")
    if use_async:
        asyncio.run(async_run(addresses, **kwargs))
    else:
        run(addresses, **kwargs)


if __name__ == "__main__":
    main()
