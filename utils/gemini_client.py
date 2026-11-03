from contextlib import asynccontextmanager

from google import genai


@asynccontextmanager
async def managed_gemini_client(**options):
    client = genai.Client(**options)
    try:
        yield client
    finally:
        try:
            await client.aio.aclose()
        finally:
            client.close()
