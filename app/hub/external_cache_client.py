"""Low-level external-cache client abstractions for hub result storage."""

from __future__ import annotations

import inspect
from typing import Any, Protocol

from app.config import GofrAgentConfig


class ExternalCacheClientError(Exception):
    """Base exception for external-cache client failures."""


class ExternalCacheUnavailableError(ExternalCacheClientError):
    """Raised when the external cache dependency is unavailable."""


class ExternalCacheCapacityExceededError(ExternalCacheClientError):
    """Raised when a session-scoped index is already at capacity."""


class ExternalCacheClient(Protocol):
    """Minimal async client contract used by the external hub store adapter."""

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def ping(self) -> bool: ...

    async def count_indexed_results(self, *, key_prefix: str) -> int: ...

    async def atomic_store_record(
        self,
        *,
        meta_key: str,
        payload_key: str,
        index_key: str,
        result_guid: str,
        meta_json: str,
        payload_json: str,
        expires_at_timestamp: float,
        now_timestamp: float,
        ttl_seconds: int,
        max_results: int,
    ) -> None: ...

    async def prune_expired(
        self,
        *,
        index_key: str,
        before_timestamp: float,
    ) -> tuple[str, ...]: ...

    async def read_record(
        self,
        *,
        meta_key: str,
        payload_key: str,
    ) -> tuple[str | None, str | None]: ...

    async def remove_index_member(self, *, index_key: str, result_guid: str) -> None: ...

    async def delete_keys(self, *keys: str) -> None: ...


class RedisExternalCacheClient:
    """Redis-protocol implementation of :class:`ExternalCacheClient`."""

    def __init__(self, config: GofrAgentConfig) -> None:
        if not config.hub_cache_url:
            raise ValueError("hub_cache_url must be configured for external_cache")
        self._connect_timeout = config.hub_cache_connect_timeout_seconds
        self._operation_timeout = config.hub_cache_operation_timeout_seconds
        self._redis = self._build_client(config.hub_cache_url)

    def _build_client(self, url: str) -> Any:
        from redis.asyncio import Redis

        return Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=self._connect_timeout,
            socket_timeout=self._operation_timeout,
        )

    async def start(self) -> None:
        await self._call(self._redis.ping)

    async def stop(self) -> None:
        close = getattr(self._redis, "aclose", None)
        if callable(close):
            result = close()
            if inspect.isawaitable(result):
                await result
            return

        fallback_close = getattr(self._redis, "close", None)
        if not callable(fallback_close):
            return
        result = fallback_close()
        if inspect.isawaitable(result):
            await result

    async def ping(self) -> bool:
        return bool(await self._call(self._redis.ping))

    async def count_indexed_results(self, *, key_prefix: str) -> int:
        async def _count() -> int:
            total = 0
            async for key in self._redis.scan_iter(match=f"{key_prefix}:session:*:results"):
                total += int(await self._redis.zcard(key))
            return total

        return await self._call(_count)

    async def atomic_store_record(
        self,
        *,
        meta_key: str,
        payload_key: str,
        index_key: str,
        result_guid: str,
        meta_json: str,
        payload_json: str,
        expires_at_timestamp: float,
        now_timestamp: float,
        ttl_seconds: int,
        max_results: int,
    ) -> None:
        from redis.exceptions import WatchError

        watch_attempts = 0
        while True:
            watch_attempts += 1
            try:
                async with self._redis.pipeline(transaction=True) as pipe:
                    await pipe.watch(index_key)
                    await pipe.zremrangebyscore(index_key, "-inf", now_timestamp)
                    current_size = int(await pipe.zcard(index_key))
                    if current_size >= max_results:
                        await pipe.reset()
                        raise ExternalCacheCapacityExceededError(
                            f"hub store is at capacity ({max_results})"
                        )

                    pipe.multi()
                    pipe.set(meta_key, meta_json, ex=ttl_seconds)
                    pipe.set(payload_key, payload_json, ex=ttl_seconds)
                    pipe.zadd(index_key, {result_guid: expires_at_timestamp})
                    await pipe.execute()
                    return
            except WatchError as exc:
                if watch_attempts >= 5:
                    raise ExternalCacheUnavailableError(
                        "external cache transaction contention exceeded retry limit"
                    ) from exc
                continue
            except ExternalCacheCapacityExceededError:
                raise
            except Exception as exc:
                raise ExternalCacheUnavailableError(str(exc)) from exc

    async def prune_expired(
        self,
        *,
        index_key: str,
        before_timestamp: float,
    ) -> tuple[str, ...]:
        async def _prune() -> tuple[str, ...]:
            members = await self._redis.zrangebyscore(index_key, "-inf", before_timestamp)
            if members:
                await self._redis.zremrangebyscore(index_key, "-inf", before_timestamp)
            return tuple(str(member) for member in members)

        return await self._call(_prune)

    async def read_record(
        self,
        *,
        meta_key: str,
        payload_key: str,
    ) -> tuple[str | None, str | None]:
        async def _read() -> tuple[str | None, str | None]:
            meta_json, payload_json = await self._redis.mget(meta_key, payload_key)
            return meta_json, payload_json

        return await self._call(_read)

    async def remove_index_member(self, *, index_key: str, result_guid: str) -> None:
        await self._call(self._redis.zrem, index_key, result_guid)

    async def delete_keys(self, *keys: str) -> None:
        if not keys:
            return
        await self._call(self._redis.delete, *keys)

    async def _call(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return await func(*args, **kwargs)
        except ExternalCacheClientError:
            raise
        except Exception as exc:
            raise ExternalCacheUnavailableError(str(exc)) from exc
