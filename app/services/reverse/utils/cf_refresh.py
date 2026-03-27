"""On-demand CF clearance refresh triggered by 403 responses."""

import asyncio
import time

from loguru import logger

# Debounce: 60 seconds cooldown between refreshes
_last_cf_refresh_time: float = 0.0
_cf_refresh_lock = asyncio.Lock()
_CF_REFRESH_COOLDOWN = 60.0


async def trigger_cf_refresh_on_403() -> bool:
    """Trigger a CF clearance refresh on 403 (with debounce)."""
    global _last_cf_refresh_time
    now = time.monotonic()
    if now - _last_cf_refresh_time < _CF_REFRESH_COOLDOWN:
        logger.debug("CF refresh skipped (cooldown)")
        return False
    async with _cf_refresh_lock:
        now = time.monotonic()
        if now - _last_cf_refresh_time < _CF_REFRESH_COOLDOWN:
            return False
        logger.info("403 detected, triggering on-demand CF refresh...")
        try:
            from app.services.cf_refresh.scheduler import refresh_once
            success = await refresh_once()
            _last_cf_refresh_time = time.monotonic()
            return success
        except Exception as e:
            logger.error("On-demand CF refresh failed: {}", e)
            _last_cf_refresh_time = time.monotonic()
            return False
