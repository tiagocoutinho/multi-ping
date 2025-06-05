import errno
import ipaddress
import logging
import os
import resource
import selectors
import socket
import time


def max_open_files() -> int:
    n = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
    return 1024 if n < 0 else n


def nb_open_files() -> int:
    return len(os.listdir("/proc/self/fd"))


def ip_addresses(text) -> set[str]:
    return {str(addr) for addr in ipaddress.ip_network(text)}


def tcp_socket() -> socket.socket:
    sock = socket.socket(socket.AddressFamily.AF_INET, socket.SocketKind.SOCK_STREAM)
    sock.setblocking(False)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return sock


def sock_error(sock):
    return sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)


def tcp_connections(addresses: list[tuple[str, int]], timeout=None, max_open=None):
    pending_addresses = list(addresses)
    available = (max_open_files() - nb_open_files()) - 10
    if max_open:
        available = min(available, max_open)
    logging.info("Using maximum of %d sockets at a time", available)
    sockets = {}
    selector = selectors.DefaultSelector()

    def connect_pending():
        nonlocal available
        while available > 0 and pending_addresses:
            address = pending_addresses.pop()
            logging.debug("start connecting to %s (available=%d)", address, available)
            sock = tcp_socket()
            sockets[sock] = address
            selector.register(sock, selectors.EVENT_WRITE)
            try:
                sock.connect(address)
            except OSError as error:
                if error.errno != errno.EINPROGRESS:
                    del sockets[sock]
                    selector.unregister(sock)
                    yield address, error.errno
            available -= 1

    start = time.monotonic()
    yield from connect_pending()
    try:
        while sockets:
            yield from connect_pending()
            to = None if timeout is None else (timeout - time.monotonic() + start)
            result = selector.select(timeout=to)
            if not result:
                break
            for key, _ in result:
                sock = key.fileobj
                address = sockets.pop(sock)
                yield address, sock_error(sock)
                selector.unregister(sock)
                sock.close()
                available += 1
    finally:
        for sock, address in sockets.items():
            yield address, errno.ETIMEDOUT
            selector.unregister(sock)
            sock.close()


def nmap(addresses, timeout=None, max_open=None):
    errors = {}

    for (host, port), error in tcp_connections(addresses, timeout=timeout, max_open=max_open):
        addr = f"{host}:{port}"
        if error:
            errors.setdefault(error, []).append(addr)
        else:
            print(f"{addr}: ok!")
    for error, addresses in errors.items():
        err_code = errno.errorcode[error]
        err_message = os.strerror(error)
        print(f"{err_code}: {err_message} ({len(addresses)})")


def iter_addresses(network, ports):
    ports = tuple(ports)
    for ip in ip_addresses(network):
        for port in ports:
            yield ip, port


def iter_network_map(hosts, ports, max_open, timeout=None):
    skip_hosts = set()
    available = max_open

    logging.info("Using max ports %d", available)
    
    def iter_addresses():
        for port in ports:
            for host in hosts:
                if host not in skip_hosts:
                    yield host, port

    addresses = iter_addresses()
    sockets = {}
    selector = selectors.DefaultSelector()

    def connect_pending():
        nonlocal available
        while available > 0:
            try:
                address = next(addresses)
            except StopIteration:
                break
            logging.info("start connecting to %s (available=%d/%d)", address, available, max_open)
            sock = tcp_socket()
            sockets[sock] = address
            selector.register(sock, selectors.EVENT_WRITE)
            try:
                sock.connect(address)
            except OSError as error:
                if error.errno != errno.EINPROGRESS:
                    del sockets[sock]
                    selector.unregister(sock)
                    yield address, error.errno
                    continue
            available -= 1

    start = time.monotonic()
    yield from connect_pending()
    try:
        while sockets:
            yield from connect_pending()
            to = None if timeout is None else (timeout - time.monotonic() + start)
            result = selector.select(timeout=to)
            if not result:
                break
            for key, _ in result:
                sock = key.fileobj
                host, _ = address = sockets.pop(sock)
                error = sock_error(sock)
                if host not in skip_hosts:
                    yield address, error
                if error == errno.EHOSTUNREACH:
                    logging.info("not reachable... {%s} skipping further attempts (%d)", address, len(hosts - skip_hosts))
                    skip_hosts.add(host)
                selector.unregister(sock)
                sock.close()
                available += 1
    finally:
        for sock, address in sockets.items():
            yield address, errno.ETIMEDOUT
            selector.unregister(sock)
            sock.close()


def network_map(network, ports, max_open=None, timeout=None):
    errors = {}

    hosts = ip_addresses(network)
    ports = list(ports)
    if max_open is None:
        max_open = min(max(len(hosts) // 2, 10), (max_open_files() - nb_open_files()) - 10)

    for (host, port), error in iter_network_map(network, ports, max_open=max_open, timeout=timeout):
        addr = f"{host}:{port}"
        if error:
            errors.setdefault(error, []).append(addr)
        else:
            print(f"{addr}: ok!")
    for error, addresses in errors.items():
        err_code = errno.errorcode[error]
        err_message = os.strerror(error)
        print(f"{err_code}: {err_message} ({len(addresses)})")