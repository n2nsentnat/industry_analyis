from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable

import httpx


async def sleep_for_retry_after(response: httpx.Response) -> None:
    header = response.headers.get("Retry-After")
    if header is None:
        await asyncio.sleep(1.0 + random.random())
        return
    try:
        seconds = float(header)
    except ValueError:
        seconds = 1.0
    await asyncio.sleep(min(max(seconds, 0.0), 120.0))


async def request_with_retries(
    call: Callable[[], Awaitable[httpx.Response]],
    *,
    max_retries: int,
) -> httpx.Response:
    last: httpx.Response | None = None
    for attempt in range(max_retries + 1):
        response = await call()
        last = response
        if response.status_code == 429:
            if attempt >= max_retries:
                return response
            await sleep_for_retry_after(response)
            continue
        if 500 <= response.status_code < 600:
            if attempt >= max_retries:
                return response
            backoff = min(2**attempt, 30) * (0.5 + random.random())
            await asyncio.sleep(backoff)
            continue
        return response
    assert last is not None
    return last
