---
hide:
  - navigation
---

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

>>> async for response in ping(["gnu.org", "orcid.org"]):
...    text = response_text(response)
...    print(text)
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
