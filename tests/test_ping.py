import inspect
from unittest import mock

import pytest

from yaping import ping

REQ = b"\x08\x00\xdd\xc8\x00\x01\x00\x01\x00\x00\x00\x00\x00@\x8f@QQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQ"
REP = b"\x00\x00\x00\x00\x00\x01\x00\x01" + 56 * b"Q"

DEFAULT_IP = "127.0.0.1"
DEFAULT_ADDR = (DEFAULT_IP, 55)


def mock_sendto():
    return mock.patch("yaping.socket.Socket.sendto", return_value=64)


def mock_recvfrom(packet=REP, addr=DEFAULT_ADDR):
    return mock.patch("yaping.socket.Socket.recvfrom", return_value=(packet, addr))


def mock_select(result=None):
    if result is None:
        result = ((1,), (), ())
    return mock.patch("select.select", return_value=result)


def test_ping_call():
    stream = ping.ping([DEFAULT_IP])
    assert inspect.isgenerator(stream)


def test_ping_invalid_address():
    stream = ping.ping(["bad address"])
    result = next(stream)
    assert result["ip"] == "bad address"
    assert result["host"] == "bad address"
    assert "Name or service not known" in result["error"]
    with pytest.raises(StopIteration):
        next(stream)


def test_ping_timeout():
    ip = DEFAULT_IP
    stream = ping.ping([ip])
    with mock_sendto(), mock_select(((), (), ())):
        result = next(stream)
        assert result["ip"] == ip
        assert result["host"] == "localhost"
        assert "timeout" in result["error"].lower()


def test_ping():
    ip = DEFAULT_IP
    stream = ping.ping([ip])
    with mock_sendto() as sendto, mock_select() as select, mock_recvfrom(addr=(ip, 55)) as recvfrom:
        result = next(stream)
        assert result["ip"] == ip
        assert result["host"] == "localhost"
        sendto.assert_called_once()
        select.assert_called_once()
        recvfrom.assert_called_once()
