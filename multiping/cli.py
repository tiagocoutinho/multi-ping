import argparse
import ipaddress
import logging

from .ping import ping_many
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
        "addresses", type=addresses_args, nargs="+", help="host names, IPs or networks"
    )
    return parser


def parse_cmd_line_args(args=None):
    parser = cmd_line_parser()
    return parser.parse_args(args)


def run(args=None):
    args = parse_cmd_line_args(args)
    fmt = "%(asctime)s %(threadName)s %(levelname)s %(name)s %(message)s"
    logging.basicConfig(level=args.log_level.upper(), format=fmt)
    addresses = [addr for addresses in args.addresses for addr in addresses]
    for response in ping_many(addresses, timeout=args.timeout):
        yield response_text(response)


def main(args=None):
    try:
        for message in run(args):
            print(message)
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
