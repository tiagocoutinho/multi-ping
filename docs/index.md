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

<div class="termy" data-ty-macos>
  <span data-ty="input" data-ty-prompt="$">python -m asyncio</span>
  <span data-ty="input" data-ty-prompt=">>>">from multiping.ping import aioping</span>
  <span data-ty="input" data-ty-prompt=">>>">from multiping.tools import response_text</span>
  <span data-ty="input" data-ty-prompt=">>>">async for response in ping(["gnu.org", "orcid.org"], count=4, interval=0.5, strict_interval=True):</span>
  <span data-ty="input" data-ty-prompt="...">    text = response_text(response)</span>
  <span data-ty="input" data-ty-prompt="...">    print(text)</span>
  <span data-ty data-ty-delay="5">64 bytes from orcid.org (104.20.228.70): icmp_seq=1 time=4.8ms</span>
  <span data-ty data-ty-delay="108">64 bytes from gnu.org (209.51.188.116): icmp_seq=1 time=113.4ms</span>
  <span data-ty data-ty-delay="387">64 bytes from orcid.org (104.20.228.70): icmp_seq=2 time=4.7ms</span>
  <span data-ty data-ty-delay="114">64 bytes from gnu.org (209.51.188.116): icmp_seq=2 time=118.8ms</span>
  <span data-ty data-ty-delay="388">64 bytes from orcid.org (104.20.228.70): icmp_seq=3 time=5.6ms</span>
  <span data-ty data-ty-delay="121">64 bytes from gnu.org (209.51.188.116): icmp_seq=3 time=127.0ms</span>
  <span data-ty data-ty-delay="379">64 bytes from orcid.org (104.20.228.70): icmp_seq=4 time=4.4ms</span>
  <span data-ty data-ty-delay="108">64 bytes from gnu.org (209.51.188.116): icmp_seq=4 time=112.5ms</span>
</div>

Sync works great too:

```python
$ python
>>> from multiping.ping import ping
>>> from multiping.tools import response_text

>>> for response in ping(["gnu.org", "orcid.org"], count=2):
...    text = response_text(response)
...    print(text)
64 bytes from orcid.org (104.20.228.70): icmp_seq=1 time=4.8ms
64 bytes from gnu.org (209.51.188.116): icmp_seq=1 time=113.4ms
64 bytes from orcid.org (104.20.228.70): icmp_seq=2 time=4.7ms
64 bytes from gnu.org (209.51.188.116): icmp_seq=2 time=118.8ms
>>>
```

Requirements:

* python >= 3.9

## Installation

From within your favorite python environment:

<div class="termy" data-ty-macos data-ty-title="bash" data-ty-typeDelay="30" >
	<span data-ty="input" data-ty-prompt="$">pip install multi-ping</span>
    <span data-ty="progress" >pip install multi-ping</span>
</div>

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
