import os
import json
import logging
import time
from typing import Optional, Any
import redis.asyncio as redis

logger = logging.getLogger(__name__)

class CacheService:
    def __init__(self):
        self.redis_url = os.getenv("REDIS_URL")
        self.client: Optional[redis.Redis] = None
        self._in_memory_cache: dict[str, tuple[float, Any]] = {}
        
        if self.redis_url:
            try:
                self.client = redis.from_url(self.redis_url, decode_responses=True, max_connections=50)
                logger.info("CacheService initialized with Redis (with connection pooling).")
            except Exception as e:
                logger.warning(f"Failed to connect to Redis, falling back to in-memory cache: {e}")
                self.client = None
        else:
            logger.info("REDIS_URL not set. Using in-memory cache fallback.")

    async def get(self, key: str) -> Optional[Any]:
        if self.client:
            try:
                val = await self.client.get(key)
                return json.loads(val) if val else None
            except Exception as e:
                logger.error(f"Redis GET error for key {key}: {e}")
                
        # Redis down? Fall back to the in-memory dict — better than nothing
        cached = self._in_memory_cache.get(key)
        if cached is None:
            return None
        expires_at, value = cached
        if expires_at <= time.monotonic():
            self._in_memory_cache.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: Any, ttl_seconds: int = 3600) -> None:
        if self.client:
            try:
                await self.client.set(key, json.dumps(value), ex=ttl_seconds)
                return
            except Exception as e:
                logger.error(f"Redis SET error for key {key}: {e}")
                
        # Preserve TTL behaviour even when Redis is unavailable.
        self._in_memory_cache[key] = (time.monotonic() + ttl_seconds, value)

cache_service = CacheService()
