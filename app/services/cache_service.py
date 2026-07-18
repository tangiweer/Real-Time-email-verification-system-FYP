import os
import json
import logging
from typing import Optional, Any
import redis.asyncio as redis

logger = logging.getLogger(__name__)

class CacheService:
    def __init__(self):
        self.redis_url = os.getenv("REDIS_URL")
        self.client: Optional[redis.Redis] = None
        self._in_memory_cache: dict[str, Any] = {}
        
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
        return self._in_memory_cache.get(key)

    async def set(self, key: str, value: Any, ttl_seconds: int = 3600) -> None:
        if self.client:
            try:
                await self.client.setex(key, ttl_seconds, json.dumps(value))
                return
            except Exception as e:
                logger.error(f"Redis SET error for key {key}: {e}")
                
        # In-memory fallback — no TTL enforcement, but at least we don't crash
        self._in_memory_cache[key] = value

cache_service = CacheService()
