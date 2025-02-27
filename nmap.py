import errno
import ipaddress
import os
import resource
import selectors
import socket
import time


def max_open_files():
    n = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
    return 1024 if n < 0 else n


def nb_open_files():
    return len(os.listdir("/proc/self/fd"))


def ip_addresses(text):
    return [str(addr) for addr in ipaddress.ip_network(text)]


def tcp_socket() -> socket.socket:
    sock = socket.socket(socket.AddressFamily.AF_INET, socket.SocketKind.SOCK_STREAM)
    sock.setblocking(False)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return sock


def tcp_connections(addresses: list[tuple[str, int]], timeout=None):
    available = (max_open_files() - nb_open_files()) - 10
    pending_addresses = list(addresses)
    sockets = {}
    selector = selectors.DefaultSelector()

    def connect_possible():
        nonlocal available
        while available > 0 and pending_addresses:
            address = pending_addresses.pop()
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
    yield from connect_possible()
    try:
        while sockets:
            yield from connect_possible()
            to = None if timeout is None else (timeout - time.monotonic() + start)
            result = selector.select(timeout=to)
            if not result:
                break
            for key, _ in result:
                sock = key.fileobj
                result = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                address = sockets.pop(sock)
                yield address, result
                selector.unregister(sock)
                sock.close()
                available += 1
    finally:
        for sock, address in sockets.items():
            yield address, errno.ETIMEDOUT
            selector.unregister(sock)
            sock.close()


def nmap(addresses, timeout=None):
    errors = {}
    for (host, port), error in tcp_connections(addresses, timeout=timeout):
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
