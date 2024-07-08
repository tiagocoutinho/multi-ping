# User guide

This tutorial shows you how to use yaping with most of its features.

yaping provides both synchronous and asynchronous API.

## Functional syncronous API

```python
from yaping.ping import ping
from yaping.tools import response_text

for response in ping(["gnu.org", "orcid.org"], count=4, interval=0.5, strict_interval=True):
    text = response_text(response)
    print(text)
```

## Functional asyncronous API

```python
import asyncio

from yaping.ping import ping
from yaping.tools import response_text

async def pings(hosts):
    async for response in ping(hosts, count=4, interval=0.5, strict_interval=True):
        text = response_text(response)
        print(text)

asyncio.run(pings(["gnu.org", "orcid.org"]))
```