import asyncio
import hashlib
import json
import logging
import time
from collections import OrderedDict
from datetime import datetime
from typing import List, Dict, Any, Optional, Set, Tuple, Callable

from aiolimiter import AsyncLimiter

from deadspace_checker.admin import N_A, AdminPanel
from deadspace_checker.config import get_config
from deadspace_checker.models.player import Player
from .cache import LRUCache
from .database_service import DatabaseService
from .load_optimizer import StabilizedLoadOptimizer
from .search import PlayerSearchMixin
from deadspace_checker.utils.async_utils import AsyncCache
from deadspace_checker.utils.performance_monitor import monitor_performance, PerformanceTracker


class AdminService(PlayerSearchMixin):
    def __init__(self, admin_panel: AdminPanel, db_service: DatabaseService, max_concurrent_requests: int = 50) -> None:
        cfg = get_config()
        self.admin_panel = admin_panel
        self.db = db_service

        self.initial_concurrency = min(max_concurrent_requests, cfg.api.max_concurrent_requests)
        self.rate_limiter = AsyncLimiter(1.2, 1.0)

        self.cache = AsyncCache(max_size=30000, default_ttl=3600)
        self.base_admin_connections_url = (
            f"{self.admin_panel.BASE_ADMIN_URL}/Connections?showSet=true&showAccepted=true&showBanned=true"
            "&showWhitelist=true&showFull=true&showPanic=true&perPage=2000"
        )

        from deadspace_checker.utils.logging_utils import get_logger
        self.logger = logging.getLogger(__name__)
        self.perf_logger = get_logger(f"{__name__}.performance")
        self.slow_operation_threshold = cfg.logging.slow_operation_threshold
        self.perf_tracker = PerformanceTracker(self.perf_logger)

        self.connections_cache = LRUCache(max_size=5000, ttl=1800)
        self.player_info_cache = LRUCache(max_size=2000, ttl=3600)
        self.search_results_cache = LRUCache(max_size=3000, ttl=1800)

        self.expansion_terms_seen: Set[str] = set()
        self.expansion_terms_lock = asyncio.Lock()

        self._search_cache: OrderedDict[str, Tuple[Optional[Dict[str, Any]], float]] = OrderedDict()
        self._search_cache_max_size = cfg.scan.search_cache_max_size
        self._search_cache_ttl = cfg.scan.search_cache_ttl

        self._global_login_lock = asyncio.Lock()
        self._last_login_check = 0
        self._auth_ttl = 2400
        self._login_check_interval = 120
        self._is_authenticated = False
        self._auth_timestamp = 0

        self._operation_timeout = cfg.api.operation_timeout
        self._request_timeout = cfg.api.request_timeout
        self._search_timeout = cfg.api.search_timeout

        self._optimizer = StabilizedLoadOptimizer(
            logging.getLogger(f"{__name__}.optimizer"),
            cfg,
            self.initial_concurrency
        )

        self.error_tracking = {
            'consecutive_timeouts': 0,
            'consecutive_errors': 0,
            'last_success_time': time.time(),
            'total_requests': 0,
            'successful_requests': 0,
            'timeout_requests': 0,
            'error_requests': 0,
        }

        self.cooldown_active = False
        self.cooldown_until = 0
        self.cooldown_duration = cfg.api.cooldown_duration

        if self.logger.isEnabledFor(logging.INFO):
            self.logger.info(
                f"AdminService initialized with optimized settings: "
                f"concurrency={self.initial_concurrency}, "
                f"target_latency={cfg.api.load_optimizer.target_latency}s, "
                f"batch_sizes={cfg.scan.batch_processing.conservative_batch_size}-{cfg.scan.batch_processing.aggressive_batch_size}, "
                f"perPage=2000 (optimized)"
            )

    async def close(self):
        try:
            stats = self._optimizer.get_current_stats()
            self.logger.info(f"AdminService closing. Final optimizer stats: {stats}")

            self.logger.info(f"Connections cache stats: {self.connections_cache.stats()}")
            self.logger.info(f"Player info cache stats: {self.player_info_cache.stats()}")
            self.logger.info(f"Search results cache stats: {self.search_results_cache.stats()}")

            self.db.admin_cache_cleanup()

            self._search_cache.clear()
            await self.cache.clear()
            await self.admin_panel.close()

            if self.logger.isEnabledFor(logging.INFO):
                self.logger.info("AdminService closed.")
        except Exception as e:
            self.logger.error(f"Error during AdminService cleanup: {e}", exc_info=True)

    async def add_expansion_term(self, term: str) -> bool:
        async with self.expansion_terms_lock:
            if term in self.expansion_terms_seen:
                return False
            self.expansion_terms_seen.add(term)
            return True

    async def clear_caches(self) -> None:
        self.connections_cache.clear()
        self.search_results_cache.clear()
        self.player_info_cache.clear()
        self._search_cache.clear()
        self.expansion_terms_seen.clear()
        await self.cache.clear()
        if self.logger.isEnabledFor(logging.INFO):
            self.logger.info("All caches cleared (connections, search results, player info, AsyncCache)")

    def clear_expansion_terms(self) -> None:
        self.expansion_terms_seen.clear()

    def _should_apply_cooldown(self) -> bool:
        return (
                self.error_tracking['consecutive_timeouts'] > 5 or
                self.error_tracking['consecutive_errors'] > 8 or
                (time.time() - self.error_tracking['last_success_time']) > 300
        )

    async def _apply_emergency_cooldown(self):
        if not self.cooldown_active:
            self.cooldown_active = True
            self.cooldown_until = time.time() + self.cooldown_duration

            self.logger.warning(
                f"Applying emergency cooldown for {self.cooldown_duration}s. "
                f"Consecutive timeouts: {self.error_tracking['consecutive_timeouts']}, "
                f"consecutive errors: {self.error_tracking['consecutive_errors']}"
            )

            await asyncio.sleep(self.cooldown_duration)

            self.error_tracking['consecutive_timeouts'] = 0
            self.error_tracking['consecutive_errors'] = 0
            self.cooldown_active = False

            self.logger.info("Emergency cooldown completed")

    @monitor_performance
    async def login(self) -> bool:
        current_time = time.time()

        if self._is_authenticated and (current_time - self._auth_timestamp) < self._auth_ttl:
            return True

        if (current_time - self._last_login_check) < self._login_check_interval:
            return self._is_authenticated

        try:
            async with asyncio.timeout(self._operation_timeout):
                async with self._global_login_lock:
                    current_time = time.time()
                    if self._is_authenticated and (current_time - self._auth_timestamp) < self._auth_ttl:
                        return True

                    self._last_login_check = current_time

                    if self.admin_panel._is_authenticated:
                        time_since_auth = current_time - self.admin_panel._auth_token_timestamp
                        if time_since_auth < self._auth_ttl:
                            self._is_authenticated = True
                            self._auth_timestamp = self.admin_panel._auth_token_timestamp
                            return True

                    if self.logger.isEnabledFor(logging.INFO):
                        self.logger.info("Attempting AdminPanel login via AdminService")

                    start_time = time.time()
                    result = await self.admin_panel.login()
                    elapsed = time.time() - start_time
                    self.perf_tracker.record("admin_panel_login", elapsed)

                    if result:
                        self._is_authenticated = True
                        self._auth_timestamp = time.time()
                        self.error_tracking['last_success_time'] = time.time()
                        if self.logger.isEnabledFor(logging.INFO):
                            self.logger.info(f"AdminPanel login successful in {elapsed:.2f}s")
                    else:
                        self._is_authenticated = False
                        if self.logger.isEnabledFor(logging.ERROR):
                            self.logger.error(f"AdminPanel login failed after {elapsed:.2f}s")

                    return result

        except asyncio.TimeoutError:
            self.logger.error(f"Login attempt timed out after {self._operation_timeout} seconds")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error during login: {e}", exc_info=True)
            return False

    def _make_cache_key(self, func: Callable, args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> str:
        func_name = func.__name__ if hasattr(func, '__name__') else str(func)
        if not kwargs and len(args) <= 2:
            key_parts = [func_name]
            for arg in args:
                if isinstance(arg, (str, int, float, bool, type(None))):
                    key_parts.append(str(arg))
                else:
                    key_parts.append(repr(arg)[:100])
            cache_key_str = "|".join(key_parts)
        else:
            payload = {"f": func_name, "a": args[:3], "k": kwargs}
            try:
                raw = json.dumps(payload, sort_keys=True, default=str)
            except Exception:
                raw = repr(payload)[:500]
            cache_key_str = raw
        return hashlib.md5(cache_key_str.encode('utf-8'), usedforsecurity=False).hexdigest()

    async def fetch_connections_with_cache(self, identifier: str) -> Optional[List[Dict[str, Any]]]:
        cache_key = f"connections:{identifier}"

        cached_result = self.connections_cache.get(cache_key)
        if cached_result is not None:
            return cached_result

        persistent_result = self.db.admin_cache_get(cache_key, ttl=3600)
        if persistent_result is not None:
            self.connections_cache.put(cache_key, persistent_result)
            return persistent_result

        try:
            result = await self.admin_panel.fetch_connections_for_user(identifier)
            if result:
                self.connections_cache.put(cache_key, result)
                self.db.admin_cache_put(cache_key, result)
            return result
        except Exception as e:
            self.logger.error(f"Error fetching connections for {identifier}: {e}")
            return None

    async def fetch_player_info_with_cache(self, user_id: str, fetch_player_details: bool = True) -> Dict[str, Any]:
        if not fetch_player_details:
            return {"ban_counts": 0, "ban_reasons": []}

        cache_key = f"player_info:{user_id}"

        cached_result = self.player_info_cache.get(cache_key)
        if cached_result is not None:
            return cached_result

        persistent_result = self.db.admin_cache_get(cache_key, ttl=7200)
        if persistent_result is not None:
            self.player_info_cache.put(cache_key, persistent_result)
            return persistent_result

        try:
            result = await self.admin_panel.fetch_player_info(user_id)
            if result:
                self.player_info_cache.put(cache_key, result)
                self.db.admin_cache_put(cache_key, result)
            return result
        except Exception as e:
            self.logger.error(f"Error fetching player info for {user_id}: {e}")
            return {"ban_counts": 0, "ban_reasons": []}

    @monitor_performance
    async def fetch_with_rate_limit(self, func: Callable, *args, **kwargs) -> Any:
        cache_key = self._make_cache_key(func, args, kwargs)
        func_name = func.__name__ if hasattr(func, '__name__') else str(func)

        if self._should_apply_cooldown():
            await self._apply_emergency_cooldown()

        async def factory_coro():
            if self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug(f"Cache miss for {func_name}. Applying load controls.")

            await self._optimizer.wait_adaptive_delay()

            if not await self.login():
                self.logger.error(f"Authentication failed for {func_name}")
                raise Exception(f"Authentication failed, cannot execute {func_name}")

            op_start_time = time.time()
            success = False
            result = None

            try:
                async with self._optimizer.concurrency_semaphore:
                    timeout = self._search_timeout if 'search' in func_name.lower() else self._request_timeout
                    async with asyncio.timeout(timeout):
                        async with self.rate_limiter:
                            result = await func(*args, **kwargs)
                            success = True
                            return result

            except asyncio.TimeoutError:
                self.error_tracking['consecutive_timeouts'] += 1
                self.error_tracking['timeout_requests'] += 1
                self.logger.error(f"Operation {func_name} timed out after {timeout}s")
                raise
            except Exception as e:
                self.error_tracking['consecutive_errors'] += 1
                self.error_tracking['error_requests'] += 1
                self.logger.error(f"Error in {func_name}: {e}")
                raise
            finally:
                op_elapsed_time = time.time() - op_start_time
                self.error_tracking['total_requests'] += 1

                if success:
                    self.error_tracking['consecutive_timeouts'] = 0
                    self.error_tracking['consecutive_errors'] = 0
                    self.error_tracking['last_success_time'] = time.time()
                    self.error_tracking['successful_requests'] += 1

                await self._optimizer.record_latency(op_elapsed_time, success=success)
                self.perf_tracker.record(func_name, op_elapsed_time)

                if op_elapsed_time > self.slow_operation_threshold:
                    if self.perf_logger.isEnabledFor(logging.WARNING):
                        self.perf_logger.warning(
                            f"Slow operation: {func_name} took {op_elapsed_time:.2f}s"
                        )

        try:
            result = await self.cache.get(cache_key, factory_coro)
        except Exception as e:
            self.logger.error(f"Failed to get result for {func_name}: {e}")
            return None

        if self.perf_tracker.should_log_summary():
            summary_lines = self.perf_tracker.get_summary()
            for line in summary_lines:
                if self.perf_logger.isEnabledFor(logging.INFO):
                    self.perf_logger.info(line)

            optimizer_stats = self._optimizer.get_current_stats()
            self.perf_logger.info(f"Optimizer stats: {optimizer_stats}")

            total = self.error_tracking['total_requests']
            if total > 0:
                success_rate = (self.error_tracking['successful_requests'] / total) * 100
                self.perf_logger.info(
                    f"Request stats: {total} total, {success_rate:.1f}% success, "
                    f"{self.error_tracking['timeout_requests']} timeouts, "
                    f"{self.error_tracking['error_requests']} errors"
                )

        if len(self._search_cache) > self._search_cache_max_size * 1.5:
            self._cleanup_search_cache()

        return result

    def _cleanup_search_cache(self):
        current_time = time.time()
        keys_to_remove = []

        for key, (data, timestamp) in list(self._search_cache.items())[:200]:
            if current_time - timestamp > self._search_cache_ttl:
                keys_to_remove.append(key)

        for key in keys_to_remove:
            del self._search_cache[key]

        while len(self._search_cache) > self._search_cache_max_size:
            self._search_cache.popitem(last=False)

        if keys_to_remove and self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(f"Cleaned up {len(keys_to_remove)} old entries from search cache")

    @monitor_performance
    async def auto_ban(
        self,
        reason: str,
        minutes: int = 0,
        ip_address: Optional[str] = None,
        hwid: Optional[str] = None,
        user_id: Optional[str] = None,
        connection_id: Optional[str] = None,
    ) -> bool:
        if self._should_apply_cooldown():
            await self._apply_emergency_cooldown()

        await self._optimizer.wait_adaptive_delay()

        if not await self.login():
            self.logger.error("Authentication failed for auto_ban")
            return False

        op_start_time = time.time()
        success = False

        try:
            async with self._optimizer.concurrency_semaphore:
                async with asyncio.timeout(self._request_timeout):
                    async with self.rate_limiter:
                        result = await self.admin_panel.create_ban(
                            reason=reason,
                            minutes=minutes,
                            ip_address=ip_address,
                            hwid=hwid,
                            user_id=user_id,
                            connection_id=connection_id,
                        )
                        success = True
                        return result
        except asyncio.TimeoutError:
            self.error_tracking['consecutive_timeouts'] += 1
            self.error_tracking['timeout_requests'] += 1
            self.logger.error(f"auto_ban timed out after {self._request_timeout}s")
            return False
        except Exception as e:
            self.error_tracking['consecutive_errors'] += 1
            self.error_tracking['error_requests'] += 1
            self.logger.error(f"Error in auto_ban: {e}")
            return False
        finally:
            op_elapsed_time = time.time() - op_start_time
            self.error_tracking['total_requests'] += 1
            if success:
                self.error_tracking['consecutive_timeouts'] = 0
                self.error_tracking['consecutive_errors'] = 0
                self.error_tracking['last_success_time'] = time.time()
                self.error_tracking['successful_requests'] += 1
            await self._optimizer.record_latency(op_elapsed_time, success=success)
            self.perf_tracker.record("auto_ban", op_elapsed_time)

    def convert_to_player(self, account_info_dict: Optional[Dict[str, Any]]) -> Player:
        if not account_info_dict or not isinstance(account_info_dict, dict):
            if self.logger.isEnabledFor(logging.WARNING):
                self.logger.warning("Empty/None/non-dict account_info for convert_to_player. Default Player returned.")
            return Player(user_id=N_A, nicknames=[], status="unknown")

        p_uid = str(account_info_dict.get("user_id", N_A))
        nicks_list = account_info_dict.get("nicknames", [])
        p_nicks = nicks_list if isinstance(nicks_list, list) else []
        p_status = str(account_info_dict.get("status", "unknown"))
        p_ban_c = int(bc) if isinstance((bc := account_info_dict.get("ban_counts", 0)), (int, float)) else 0

        fmt_brs: List[Dict[str, str]] = []
        for r_entry in (raw_brs if isinstance((raw_brs := account_info_dict.get("ban_reasons", [])), list) else []):
            if isinstance(r_entry, dict) and "reason" in r_entry and "username" in r_entry:
                fmt_brs.append({
                    "reason": str(r_entry["reason"]), "username": str(r_entry["username"]),
                    "admin": str(r_entry.get("admin", "N/A")),
                    "type": str(r_entry.get("type", "N/A")),
                    "date": str(r_entry.get("date", "N/A")),
                    "expires": str(r_entry.get("expires", "Никогда")),
                })

        p_conn_link = str(account_info_dict.get("connection_link", N_A))
        p_assoc_ips = ips if isinstance((ips := account_info_dict.get("associated_ips", {})), dict) else {}
        p_assoc_hwids = hwids if isinstance((hwids := account_info_dict.get("associated_hwids", {})), dict) else {}
        p_shared_hwids = sh_hwids if isinstance((sh_hwids := account_info_dict.get("shared_hwid_nicknames", [])),
                                                list) else []
        p_denied_logins = d_logins if isinstance((d_logins := account_info_dict.get("denied_banned_connections", [])),
                                                 list) else []
        p_hwid_erased = bool(account_info_dict.get("hwid_erased", False))

        return Player(user_id=p_uid, nicknames=p_nicks, status=p_status, ban_counts=p_ban_c,
                      ban_reasons=fmt_brs, connection_link=p_conn_link, associated_ips=p_assoc_ips,
                      associated_hwids=p_assoc_hwids, shared_hwid_nicknames=p_shared_hwids,
                      denied_logins=p_denied_logins, hwid_erased=p_hwid_erased)
