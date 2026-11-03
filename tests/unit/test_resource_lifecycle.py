import asyncio
import types
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.mark.asyncio
async def test_shutdown_awaits_both_created_tasks_and_running_jobs(offline_module):
    module = offline_module("core/async_tools.py")
    created_started, job_started = asyncio.Event(), asyncio.Event()
    finished = []

    async def work(started, name):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            finished.append(name)

    created = module.create_logged_task(work(created_started, "created"))
    job = asyncio.create_task(module.tracked_job(work)(job_started, "job"))
    await created_started.wait()
    await job_started.wait()
    await module.cancel_logged_tasks()
    assert created.done() and job.done()
    assert set(finished) == {"created", "job"}
    await module.cancel_logged_tasks()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, RuntimeError("offline"), asyncio.CancelledError()])
async def test_gemini_clients_are_closed_on_success_failure_and_cancellation(monkeypatch, failure):
    from utils import gemini_client

    client = types.SimpleNamespace(aio=types.SimpleNamespace(aclose=AsyncMock()), close=Mock())
    monkeypatch.setattr(gemini_client.genai, "Client", Mock(return_value=client))

    async def request():
        async with gemini_client.managed_gemini_client(api_key="synthetic") as active:
            assert active is client
            if failure is not None:
                raise failure

    if failure is None:
        await request()
    else:
        with pytest.raises(type(failure)):
            await request()
    client.aio.aclose.assert_awaited_once()
    client.close.assert_called_once()


@pytest.mark.asyncio
async def test_sync_client_closes_even_if_async_close_fails(monkeypatch):
    from utils import gemini_client

    client = types.SimpleNamespace(aio=types.SimpleNamespace(aclose=AsyncMock(side_effect=RuntimeError("close failed"))), close=Mock())
    monkeypatch.setattr(gemini_client.genai, "Client", Mock(return_value=client))
    with pytest.raises(RuntimeError, match="close failed"):
        async with gemini_client.managed_gemini_client(api_key="synthetic"):
            pass
    client.close.assert_called_once()
