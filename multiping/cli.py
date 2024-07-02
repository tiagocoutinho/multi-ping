import argparse
import asyncio
import ipaddress
import logging

from .ping import ping
from .aioping import async_ping

# from .host import ping_many
from .tools import response_text


def addresses_args(text):
    try:
        return [str(addr) for addr in ipaddress.ip_network(text)]
    except ValueError:
        return [text]


def cmd_line_parser():
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
        action='store_true',
    )
    parser.add_argument(
        "-w",
        "--timeout",
        type=float,
        help="time to wait for response (seconds)",
        default=1,
    )
    parser.add_argument(
        "-c", "--count", type=int, help="stop after sending count pings", default=None
    )
    parser.add_argument(
        "--log-level",
        choices=["debug", "info", "warn", "error"],
        help="log level",
        default="warn",
    )
    parser.add_argument(
        "--async",
        help="use asyncio",
        action='store_true',
    )
    parser.add_argument(
        "addresses", type=addresses_args, nargs="+", help="host names, IPs or networks"
    )
    return parser


def parse_cmd_line_args(args=None):
    parser = cmd_line_parser()
    return parser.parse_args(args)


def init_logging(level: str):
    fmt = "%(asctime)s %(threadName)s %(levelname)s %(name)s %(message)s"
    logging.basicConfig(level=level.upper(), format=fmt)


def init(args=None):
    args = parse_cmd_line_args(args)
    init_logging(args.log_level)
    addresses = [addr for addresses in args.addresses for addr in addresses]
    return args, addresses


async def async_run(addresses, **kwargs):
    try:
        async for response in async_ping(addresses, **kwargs):
            print(response_text(response))
    except (asyncio.exceptions.CancelledError):
        print()


def run(addresses, **kwargs):
    try:
        for response in ping(addresses, **kwargs):
            print(response_text(response))
    except KeyboardInterrupt:
        print()


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