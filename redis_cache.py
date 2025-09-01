# redis_cache.py
import os
import redis.asyncio as aioredis
from azure.identity.aio import DefaultAzureCredential

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_USE_AZURE = os.getenv("REDIS_USE_AZURE", "false").lower() == "true"

print(f"Redis Host : {REDIS_HOST}, Redis Port : {REDIS_PORT}, Redis Use Azure: {REDIS_USE_AZURE}")
# only needed for Azure
credential = DefaultAzureCredential() if REDIS_USE_AZURE else None

async def get_redis_client():
    if REDIS_USE_AZURE:
        # Managed identity / Entra ID
        token = await credential.get_token("https://*.cacheinfra.windows.net:10225/appid/.default")
        return aioredis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            ssl=True,
            username="user",   # Azure requires this
            password=token.token,
        )
    else:
        # Local dev Redis (no SSL, no auth)
        return aioredis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True  # auto-decode str <-> bytes
        )
