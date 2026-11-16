"""
Regression: requests must not share one RethinkDB connection. With a shared connection, one request
that was cancelled mid-query (client went away) or hit a driver error broke every other in-flight
request (503 DB_UNAVAILABLE).
"""
import asyncio
import contextvars

import pytest

from mlp import core

pytestmark = pytest.mark.asyncio

PATHS = ['/api/stats?statuses=sent', '/api/stats?by_host=1', '/api/stats?top_senders=1',
         '/api/stats?top_relays=1', '/api/stats?timeline=1&bucket=hour', '/api/emails?limit=5', '/api/facets']


async def test_parallel_requests_survive_cancelled_ones(authed):
    async def get(path):
        return (await authed.get(path)).status_code

    for _ in range(3):
        # like hypercorn, every request starts from a context without a connection
        victims = [asyncio.create_task(get(p), context=contextvars.Context()) for p in PATHS]
        survivors = [asyncio.create_task(get(p), context=contextvars.Context()) for p in PATHS]
        await asyncio.sleep(0)
        for v in victims:
            v.cancel()
        codes = await asyncio.gather(*survivors)
        await asyncio.gather(*victims, return_exceptions=True)
        assert codes == [200] * len(PATHS)


async def test_connection_is_per_context(db):
    async def conn_of():
        _, conn, _ = await core.get_rethink()
        try:
            return id(conn)
        finally:
            await core.close_rethink()

    # tasks with their own context (like separate requests) never share a connection while both are running
    started = asyncio.Event()

    async def hold():
        _, conn, _ = await core.get_rethink()
        started.set()
        await asyncio.sleep(0.05)
        return id(conn)

    t1 = asyncio.create_task(hold(), context=contextvars.Context())
    await started.wait()
    t2 = asyncio.create_task(conn_of(), context=contextvars.Context())
    assert await t1 != await t2
