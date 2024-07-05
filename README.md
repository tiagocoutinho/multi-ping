
# 🔔 Welcome to multi-ping


[![multiping][pypi-version]](https://pypi.python.org/pypi/multi-ping)
[![Python Versions][pypi-python-versions]](https://pypi.python.org/pypi/multi-ping)
[![License][license]]()
[![CI][CI]](https://github.com/tiagocoutinho/multi-ping/actions/workflows/ci.yml)

A python library for pinging multiple hosts.

It focuses on providing both sync and asynch versions and minimizing the amount of
of OS resources (only a single socket is used for handling multiple hosts with
multiple ping requests)

Without further ado:

```python
$ python -m asyncio
>>> from multiping.aioping import ping
>>> from multiping.tools import response_text

>>> async for response in ping(["gnu.org", "orcid.org"], count=2):
...    text = response_text(response)
...    print(text)
64 bytes from orcid.org (104.20.228.70): icmp_seq=1 time=4.8ms
64 bytes from gnu.org (209.51.188.116): icmp_seq=1 time=113.4ms
64 bytes from orcid.org (104.20.228.70): icmp_seq=2 time=4.7ms
64 bytes from gnu.org (209.51.188.116): icmp_seq=2 time=118.8ms
```

Requirements:

* python >= 3.9

## Installation

From within your favorite python environment:

```
$ pip install multi-ping
```

To develop, run tests, build package, lint, etc you'll need:

```console
$ pip install multi-ping[dev]
```

To run docs you'll need:

```console
$ pip install multi-ping[docs]
```

[pypi-python-versions]: https://img.shields.io/pypi/pyversions/multi-ping.svg
[pypi-version]: https://img.shields.io/pypi/v/multi-ping.svg
[pypi-status]: https://img.shields.io/pypi/status/multi-ping.svg
[license]: https://img.shields.io/pypi/l/multi-ping.svg
[CI]: https://github.com/tiagocoutinho/multi-ping/actions/workflows/ci.yml/badge.svg
