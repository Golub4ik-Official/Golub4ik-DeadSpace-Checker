import asyncio
import logging
import time
from collections import defaultdict
from datetime import datetime
from typing import List, Dict, Any, Optional, Set

from deadspace_checker.config import get_config
from .analyzer import PlayerAnalyzer
from .utils import cached, CircuitBreaker, ExponentialBackoff
from .player_merge import PlayerMerger
from .message_utils import extract_message_data, create_scan_results, _annotate_players_with_login_info
from .bypass import BanBypassMixin
from deadspace_checker.models.player import Player
from deadspace_checker.services.admin_service import AdminService
from deadspace_checker.services.cache_service import CacheService
from deadspace_checker.services.discord_service import DiscordService
from deadspace_checker.services.reporting import ReportService
from deadspace_checker.utils.async_utils import gather_with_concurrency
from deadspace_checker.utils.discord_utils import extract_message_id
from deadspace_checker.utils.performance_monitor import PerformanceTracker, monitor_performance


class Scanner(BanBypassMixin):
    def __init__(self, discord_service: DiscordService, admin_service: AdminService,
                 cache_service: CacheService, report_service: ReportService,
                 player_analyzer: PlayerAnalyzer,
                 progress_queue=None) -> None:
        self.discord = discord_service
        self.admin = admin_service
        self.admin_panel = admin_service.admin_panel
        self.cache = cache_service
        self.report = report_service
        self.analyzer = player_analyzer
        self.cfg = get_config()
        self.max_concurrent = self.cfg.api.max_concurrent_requests
        self.complaint_channels = {}
        self.cache_data = {
            "connections": {},
            "ban_info": {},
            "players": {},
        }
        self.identity_graph = defaultdict(set)
        self.logger = logging.getLogger(__name__)
        self.perf = PerformanceTracker()
        self.status_priority = {
            'banned': 3,
            'suspicious': 2,
            'clean': 1,
            'unknown': 0
        }
        self.connections_cache = {}

        self._operation_timeout = self.cfg.api.operation_timeout
        self._term_timeout = self.cfg.api.term_timeout
        self._batch_timeout = self.cfg.api.batch_timeout
        self._set_progress_queue(progress_queue)

        self.circuit_breaker = CircuitBreaker(
            failure_threshold=self.cfg.api.circuit_breaker.failure_threshold,
            recovery_timeout=self.cfg.api.circuit_breaker.recovery_timeout,
            half_open_max_calls=self.cfg.api.circuit_breaker.half_open_max_calls
        )

        self.backoff = ExponentialBackoff(
            initial_delay=self.cfg.api.backoff.initial_delay,
            max_delay=self.cfg.api.backoff.max_delay,
            multiplier=self.cfg.api.backoff.multiplier,
            jitter=self.cfg.api.backoff.jitter
        )

    def _set_progress_queue(self, q):
        self.progress_queue = q

    def _report_progress(self, current, total, msg=""):
        if self.progress_queue is not None:
            try:
                self.progress_queue.put_nowait({"type": "progress", "current": current, "total": total, "msg": msg})
            except Exception:
                pass

    def _report_log(self, text):
        if self.progress_queue is not None:
            try:
                self.progress_queue.put_nowait({"type": "log", "text": text})
            except Exception:
                pass

        self._conservative_batch_size = self.cfg.scan.batch_processing.conservative_batch_size
        self._aggressive_batch_size = self.cfg.scan.batch_processing.aggressive_batch_size
        self._batch_delay_base = self.cfg.scan.batch_processing.batch_delay_base
        self._max_terms_per_scan = self.cfg.scan.max_terms_per_scan

        self.error_stats = {
            'timeouts': 0,
            'circuit_breaker_trips': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'retries': 0
        }

        if self.logger.isEnabledFor(logging.INFO):
            self.logger.info(
                f"Scanner initialized with settings: "
                f"max_concurrent={self.max_concurrent}, "
                f"batch_sizes={self._conservative_batch_size}-{self._aggressive_batch_size}, "
                f"batch_delay={self._batch_delay_base}s, "
                f"max_terms={self._max_terms_per_scan}"
            )

    async def setup(self, target_channel_id: int, complaint_channel_ids: List[int]) -> bool:
        self.logger.info("Setting up scanner...")
        if not await self.discord.setup_channels(target_channel_id, complaint_channel_ids):
            return False
        if not await self.admin.login():
            self.logger.error("Failed to log in to the admin panel")
            return False
        self.complaint_channels = self.cache.load_complaint_cache()
        self.logger.info("Scanner setup complete")
        return True

    def _should_limit_processing(self, total_terms: int) -> tuple[bool, int]:
        if total_terms <= self._max_terms_per_scan:
            return False, total_terms

        self.logger.warning(
            f"Found {total_terms} terms, which exceeds limit of {self._max_terms_per_scan}. "
            f"Will process first {self._max_terms_per_scan} terms."
        )
        return True, self._max_terms_per_scan

    def _get_adaptive_batch_size(self) -> int:
        if self.circuit_breaker.state == 'OPEN':
            return 1
        elif self.circuit_breaker.state == 'HALF_OPEN':
            return max(2, self._conservative_batch_size // 2)
        elif self.circuit_breaker.failure_count > 5:
            return self._conservative_batch_size
        else:
            total_requests = self.error_stats['successful_requests'] + self.error_stats['failed_requests']
            if total_requests > 10:
                success_rate = self.error_stats['successful_requests'] / total_requests
                if success_rate > 0.9:
                    return self._aggressive_batch_size
                elif success_rate > 0.7:
                    return (self._conservative_batch_size + self._aggressive_batch_size) // 2

            return self._conservative_batch_size

    def _get_adaptive_delay(self) -> float:
        base_delay = self._batch_delay_base

        if self.circuit_breaker.state == 'OPEN':
            return base_delay * 10
        elif self.circuit_breaker.state == 'HALF_OPEN':
            return base_delay * 3
        elif self.circuit_breaker.failure_count > 0:
            return base_delay * (1 + self.circuit_breaker.failure_count * 0.5)

        return base_delay

    @monitor_performance()
    async def scan_messages(self, message_limit: int) -> List[Dict[str, Any]]:
        start_time = datetime.now()
        self.logger.info(f"Starting message scan with limit {message_limit}")
        processed_terms = set()

        try:
            self.error_stats = {k: 0 for k in self.error_stats}

            self._report_log("Начинаю загрузку данных о наказаниях... (10–15 минут)\n")

            def _cache_progress(ch_idx, total_ch, fetched, total_to_fetch, msg):
                self._report_log(f"  {msg}\n")
                self._report_progress(fetched, total_to_fetch, msg)

            self.complaint_channels = await self.discord.update_complaint_cache(
                self.complaint_channels,
                history_limit=self.cfg.discord.message_history_limit,
                progress_callback=_cache_progress
            )

            self._report_log("Загрузка данных о наказаниях завершена.\n")
            messages = await self.discord.scan_target_channel(
                message_limit,
                lambda m: any(embed.title == 'Arrived new player' for embed in m.embeds)
            )

            if not messages:
                self.logger.info("No matching messages found")
                return []

            self.logger.info(f"Found {len(messages)} messages to process")
            message_data = extract_message_data(messages)
            all_terms = message_data['all_terms']

            should_limit, terms_to_process = self._should_limit_processing(len(all_terms))
            if should_limit:
                all_terms = list(all_terms)[:terms_to_process]

            self.logger.info(f"Processing {len(all_terms)} unique terms")

            term_results = await self._process_all_terms_enhanced(
                all_terms,
                message_data['term_is_login_event'],
                message_data['user_id_terms'],
                processed_terms,
                message_data
            )

            scan_results = await create_scan_results(
                messages,
                message_data,
                term_results,
                self.discord,
                self.complaint_channels,
                self.analyzer
            )

            consolidated_results = PlayerMerger.consolidate(scan_results, self.logger)
            report_data = self.report.generate_message_scan_report(consolidated_results)

            duration = (datetime.now() - start_time).total_seconds()
            hit_rate = (len(consolidated_results) / len(messages)) * 100 if messages else 0

            self.logger.info(
                f"Message scan completed in {duration:.2f}s: processed {len(messages)} messages, "
                f"found {len(consolidated_results)} results ({hit_rate:.1f}% hit rate)"
            )

            self._log_error_statistics()

            self.perf.log_summary_if_needed()
            return report_data

        except Exception as e:
            self.logger.error(f"Error during message scan: {str(e)}", exc_info=True)
            return []
        finally:
            self._report_log("Сохраняю данные в базу данных...\n")
            self.cache.save_complaint_cache(self.complaint_channels)
            self._report_log("Сохранение завершено.\n")

    async def _process_all_terms_enhanced(self, all_terms, term_is_login_event, user_id_terms,
                                          processed_terms, message_data):
        if not all_terms:
            return {}

        high_priority_terms = []
        normal_priority_terms = []

        for term in all_terms:
            if term in user_id_terms.values() or term_is_login_event.get(term, False):
                high_priority_terms.append(term)
            else:
                normal_priority_terms.append(term)

        all_priority_terms = high_priority_terms + normal_priority_terms

        if not all_priority_terms:
            return {}

        self.logger.info(f"Processing {len(all_priority_terms)} terms with enhanced batching")

        term_results = {}
        message_nicknames = message_data.get('message_nicknames', {})
        term_to_message_id = message_data.get('term_to_message_id', {})
        cache_lock = asyncio.Lock()

        batch_number = 0
        successful_batches = 0
        failed_batches = 0

        i = 0
        while i < len(all_priority_terms):
            batch_number += 1

            if not self.circuit_breaker.can_execute():
                self.logger.warning(
                    f"Circuit breaker is OPEN. Waiting {self.circuit_breaker.recovery_timeout}s before retry..."
                )
                self.error_stats['circuit_breaker_trips'] += 1
                await asyncio.sleep(self.circuit_breaker.recovery_timeout)
                continue

            batch_size = self._get_adaptive_batch_size()
            batch_delay = self._get_adaptive_delay()

            batch_terms = all_priority_terms[i:i + batch_size]

            self.logger.info(
                f"Processing batch {batch_number} with {len(batch_terms)} terms "
                f"(batch_size={batch_size}, delay={batch_delay:.1f}s, "
                f"circuit_state={self.circuit_breaker.state})"
            )

            delay_task = asyncio.create_task(asyncio.sleep(batch_delay)) if i + batch_size < len(
                all_priority_terms) else None

            try:
                batch_results = await self._process_batch_with_retry(
                    batch_terms, cache_lock, processed_terms, term_is_login_event,
                    user_id_terms, message_nicknames, term_to_message_id
                )

                for term, result in zip(batch_terms, batch_results):
                    if result:
                        term_results[term] = result

                successful_batches += 1
                self.circuit_breaker.call_succeeded()
                self.backoff.reset()

                i += batch_size

                progress_pct = (i / len(all_priority_terms)) * 100
                self.logger.info(
                    f"Completed batch {batch_number}. Progress: {i}/{len(all_priority_terms)} "
                    f"({progress_pct:.1f}%). Success rate: "
                    f"{successful_batches}/{successful_batches + failed_batches}"
                )

                self._report_progress(i, len(all_priority_terms), f"Batch {batch_number} ({progress_pct:.0f}%)")

                if delay_task:
                    await delay_task

            except Exception as e:
                failed_batches += 1
                self.circuit_breaker.call_failed()
                self.error_stats['failed_requests'] += len(batch_terms)

                self.logger.error(f"Batch {batch_number} failed: {e}")

                backoff_delay = self.backoff.get_delay()
                self.logger.info(f"Applying backoff delay: {backoff_delay:.1f}s")
                await asyncio.sleep(backoff_delay)

                i += batch_size

        self.logger.info(
            f"Term processing completed. Processed {len(term_results)} successful terms. "
            f"Successful batches: {successful_batches}, Failed batches: {failed_batches}"
        )

        return term_results

    async def _process_batch_with_retry(self, batch_terms, cache_lock, processed_terms,
                                        term_is_login_event, user_id_terms, message_nicknames,
                                        term_to_message_id, max_retries=2):

        for attempt in range(max_retries + 1):
            try:
                async with asyncio.timeout(self._batch_timeout):
                    term_tasks = []

                    for term in batch_terms:
                        async with cache_lock:
                            if term in processed_terms:
                                continue
                            processed_terms.add(term)

                        message_id = term_to_message_id.get(term)
                        nickname = message_nicknames.get(message_id) if message_id else None

                        term_tasks.append(
                            self._process_term_with_enhanced_timeout(
                                term,
                                use_cache=True,
                                shared_cache=None,
                                cache_lock=None,
                                is_login_event=term_is_login_event.get(term, False),
                                is_user_id=(term in user_id_terms.values()),
                                message_nickname=nickname
                            )
                        )

                    if term_tasks:
                        batch_results = await asyncio.gather(*term_tasks, return_exceptions=True)

                        processed_results = []
                        for i, result in enumerate(batch_results):
                            if isinstance(result, Exception):
                                self.logger.warning(f"Term '{batch_terms[i][:50]}' failed: {result}")
                                self.error_stats['failed_requests'] += 1
                                processed_results.append(None)
                            else:
                                if result:
                                    self.error_stats['successful_requests'] += 1
                                processed_results.append(result)

                        return processed_results

                    return []

            except asyncio.TimeoutError:
                self.error_stats['timeouts'] += 1
                if attempt < max_retries:
                    self.error_stats['retries'] += 1
                    retry_delay = (attempt + 1) * 5
                    self.logger.warning(
                        f"Batch timeout on attempt {attempt + 1}/{max_retries + 1}. "
                        f"Retrying in {retry_delay}s..."
                    )
                    await asyncio.sleep(retry_delay)
                else:
                    self.logger.error(f"Batch timed out after {max_retries + 1} attempts")
                    raise

            except Exception as e:
                if attempt < max_retries:
                    self.error_stats['retries'] += 1
                    retry_delay = (attempt + 1) * 3
                    self.logger.warning(
                        f"Batch error on attempt {attempt + 1}/{max_retries + 1}: {e}. "
                        f"Retrying in {retry_delay}s..."
                    )
                    await asyncio.sleep(retry_delay)
                else:
                    self.logger.error(f"Batch failed after {max_retries + 1} attempts: {e}")
                    raise

    async def _process_term_with_enhanced_timeout(self, term: str, **kwargs) -> Optional[Player]:
        start_time = time.time()

        try:
            async with asyncio.timeout(self._term_timeout):
                result = await self.process_term(term, **kwargs)

                elapsed = time.time() - start_time
                if elapsed > self._term_timeout * 0.8:
                    self.logger.warning(
                        f"Term '{term[:50]}' took {elapsed:.1f}s (close to timeout of {self._term_timeout}s)"
                    )

                return result

        except asyncio.TimeoutError:
            elapsed = time.time() - start_time
            self.error_stats['timeouts'] += 1
            self.logger.error(
                f"Term processing timed out for '{term[:50]}' after {elapsed:.1f}s "
                f"(timeout: {self._term_timeout}s)"
            )
            return None

        except Exception as e:
            elapsed = time.time() - start_time
            self.logger.error(
                f"Error in _process_term_with_enhanced_timeout for '{term[:50]}' "
                f"after {elapsed:.1f}s: {e}"
            )
            return None

    def _log_error_statistics(self):
        total_requests = self.error_stats['successful_requests'] + self.error_stats['failed_requests']
        if total_requests > 0:
            success_rate = (self.error_stats['successful_requests'] / total_requests) * 100

            self.logger.info("=== Scan Error Statistics ===")
            self.logger.info(f"Total requests: {total_requests}")
            self.logger.info(f"Successful: {self.error_stats['successful_requests']} ({success_rate:.1f}%)")
            self.logger.info(f"Failed: {self.error_stats['failed_requests']}")
            self.logger.info(f"Timeouts: {self.error_stats['timeouts']}")
            self.logger.info(f"Circuit breaker trips: {self.error_stats['circuit_breaker_trips']}")
            self.logger.info(f"Retries: {self.error_stats['retries']}")
            self.logger.info(f"Final circuit breaker state: {self.circuit_breaker.state}")
            self.logger.info("=============================")

    async def scan_message_interval(self, start_message: str, end_message: str) -> List[Dict[str, Any]]:
        start_time = datetime.now()

        start_id = extract_message_id(start_message)
        end_id = extract_message_id(end_message)

        if not start_id or not end_id:
            self.logger.error(f"Invalid message IDs: start={start_message}, end={end_message}")
            return []

        self.logger.info(f"Starting interval scan from message {start_id} to {end_id}")

        processed_terms = set()

        try:
            self.error_stats = {k: 0 for k in self.error_stats}

            self._report_log("Начинаю загрузку данных о наказаниях... (10–15 минут)\n")

            def _cache_progress(ch_idx, total_ch, fetched, total_to_fetch, msg):
                self._report_log(f"  {msg}\n")
                self._report_progress(fetched, total_to_fetch, msg)

            self.complaint_channels = await self.discord.update_complaint_cache(
                self.complaint_channels,
                history_limit=self.cfg.discord.message_history_limit,
                progress_callback=_cache_progress
            )

            self._report_log("Загрузка данных о наказаниях завершена.\n")
            messages = await self.discord.scan_target_channel_interval(
                start_id,
                end_id,
                lambda m: any(embed.title == 'Arrived new player' for embed in m.embeds)
            )

            if not messages:
                self.logger.info("No matching messages found in the interval")
                return []

            self.logger.info(f"Found {len(messages)} messages to process in the interval")

            message_data = extract_message_data(messages)
            all_terms = message_data['all_terms']

            should_limit, terms_to_process = self._should_limit_processing(len(all_terms))
            if should_limit:
                all_terms = list(all_terms)[:terms_to_process]

            self.logger.info(f"Processing {len(all_terms)} unique terms")

            term_results = await self._process_all_terms_enhanced(
                all_terms,
                message_data['term_is_login_event'],
                message_data['user_id_terms'],
                processed_terms,
                message_data
            )

            scan_results = await create_scan_results(
                messages,
                message_data,
                term_results,
                self.discord,
                self.complaint_channels,
                self.analyzer
            )

            consolidated_results = PlayerMerger.consolidate(scan_results, self.logger)
            report_data = self.report.generate_message_scan_report(consolidated_results)

            duration = (datetime.now() - start_time).total_seconds()
            hit_rate = (len(consolidated_results) / len(messages)) * 100 if messages else 0

            self.perf.logger.info(
                f"Interval scan completed in {duration:.2f}s: processed {len(messages)} messages, "
                f"found {len(consolidated_results)} results ({hit_rate:.1f}% hit rate)"
            )

            self._log_error_statistics()
            self.perf.log_summary_if_needed()
            return report_data

        except Exception as e:
            self.logger.error(f"Error during interval scan: {str(e)}", exc_info=True)
            return []
        finally:
            self._report_log("Сохраняю данные в базу данных...\n")
            self.cache.save_complaint_cache(self.complaint_channels)
            self._report_log("Сохранение завершено.\n")

    @monitor_performance()
    async def process_term(self, term: str, use_cache: bool = False,
                           shared_cache: Optional[Set[str]] = None,
                           cache_lock: Optional[asyncio.Lock] = None,
                           is_login_event: bool = False,
                           is_user_id: bool = False,
                           message_nickname: Optional[str] = None) -> Optional[Player]:
        term_start = datetime.now()
        try:
            if use_cache and shared_cache is not None and cache_lock is not None:
                async with cache_lock:
                    if term in shared_cache:
                        return None
                    shared_cache.add(term)

            if term in self.cache_data["players"]:
                player = self.cache_data["players"][term]
                if message_nickname and message_nickname in player.nicknames:
                    player.nicknames.remove(message_nickname)
                    player.nicknames.insert(0, message_nickname)
                    if not hasattr(player, 'nicknames_sources'):
                        player.nicknames_sources = {}
                    player.nicknames_sources[message_nickname] = "login"
                    player.is_primary = True
                    player.primary_nickname = message_nickname
                elif is_login_event:
                    self._update_player_login_info(player, is_user_id)
                return player

            self.logger.info(f"Searching for player with term: '{term}'")
            account_info = await self.admin.search_player(term)
            if not account_info:
                self.logger.info(f"No account found for term: '{term}'")
                return None

            player = self.admin.convert_to_player(account_info)
            player.is_from_user_id = is_user_id
            player.search_term = term

            if message_nickname and message_nickname in player.nicknames:
                player.nicknames.remove(message_nickname)
                player.nicknames.insert(0, message_nickname)
                if not hasattr(player, 'nicknames_sources'):
                    player.nicknames_sources = {}
                player.nicknames_sources[message_nickname] = "login"
                player.is_primary = True
                player.primary_nickname = message_nickname
            elif is_login_event:
                self._update_player_login_info(player, is_user_id)

            await self._fetch_player_connections(player)

            if not getattr(player, 'is_primary', False):
                self._identify_primary_nickname_from_search_term(player)

            self.cache_data["players"][term] = player
            processing_duration = (datetime.now() - term_start).total_seconds()
            self.perf.record("process_term", processing_duration)
            self.logger.info(f"Processed term '{term}' in {processing_duration:.2f}s")
            return player
        except Exception as e:
            self.logger.error(f"Error processing term '{term}': {str(e)}", exc_info=True)
            return None

    def _identify_primary_nickname_from_search_term(self, player: Player) -> None:
        search_term = getattr(player, 'search_term', None)
        if not search_term or not player.nicknames or getattr(player, 'is_primary', False):
            return
        if hasattr(player, 'associated_ips') and search_term in player.associated_ips:
            nicks = player.associated_ips[search_term]
            if nicks:
                primary_nick = nicks[0]
                if primary_nick in player.nicknames:
                    player.nicknames.remove(primary_nick)
                    player.nicknames.insert(0, primary_nick)
                    if not hasattr(player, 'nicknames_sources'):
                        player.nicknames_sources = {}
                    player.nicknames_sources[primary_nick] = "login"
                    player.is_primary = True
                    player.primary_nickname = primary_nick
        elif hasattr(player, 'associated_hwids') and search_term in player.associated_hwids:
            nicks = player.associated_hwids[search_term]
            if nicks:
                primary_nick = nicks[0]
                if primary_nick in player.nicknames:
                    player.nicknames.remove(primary_nick)
                    player.nicknames.insert(0, primary_nick)
                    if not hasattr(player, 'nicknames_sources'):
                        player.nicknames_sources = {}
                    player.nicknames_sources[primary_nick] = "login"
                    player.is_primary = True
                    player.primary_nickname = primary_nick

    def _update_player_login_info(self, player, is_user_id):
        player.raw_message = "Arrived new player"
        if not player.nicknames:
            return
        primary_nick = player.nicknames[0]
        if not hasattr(player, 'nicknames_sources'):
            player.nicknames_sources = {}
        player.nicknames_sources[primary_nick] = "login"
        if is_user_id:
            player.is_primary = True
            player.primary_nickname = primary_nick

    async def _fetch_player_connections(self, player: Player) -> None:
        identifiers = self._get_player_identifiers(player)
        if not identifiers:
            return

        max_identifiers = min(10, len(identifiers))
        selected_identifiers = identifiers[:max_identifiers]

        identifiers_to_fetch = [
            identifier for identifier in selected_identifiers if identifier not in self.cache_data["connections"]
        ]

        if not identifiers_to_fetch:
            return

        connection_tasks = [
            asyncio.create_task(self._fetch_connections_with_timeout(identifier))
            for identifier in identifiers_to_fetch
        ]

        if connection_tasks:
            try:
                connection_results = await gather_with_concurrency(
                    self.max_concurrent,
                    *connection_tasks
                )

                all_connections = []

                for identifier, result in zip(identifiers_to_fetch, connection_results):
                    if result is not None:
                        self.cache_data["connections"][identifier] = result
                        all_connections.extend(result)
                        self._update_identity_graph(result)

                self._process_player_connections(player, all_connections)
            except Exception as e:
                self.logger.error(f"Error fetching player connections for player '{player.user_id}': {e}",
                                  exc_info=True)

    async def _fetch_connections_with_timeout(self, identifier: str) -> List[Dict[str, Any]]:
        try:
            async with asyncio.timeout(self._operation_timeout):
                return await self.admin.fetch_with_rate_limit(
                    self.admin_panel.fetch_connections_for_user, identifier
                )
        except asyncio.TimeoutError:
            self.logger.error(f"Connection fetch timed out for identifier: {identifier}")
            return []
        except Exception as e:
            self.logger.error(f"Error fetching connections for {identifier}: {e}")
            return []

    def _get_player_identifiers(self, player: Player) -> List[str]:
        identifiers = set()
        if player.user_id and player.user_id != "N/A":
            identifiers.add(player.user_id)
        identifiers.update(player.nicknames)
        if hasattr(player, 'associated_ips') and player.associated_ips:
            identifiers.update(ip for ip in player.associated_ips if ip != "N/A")
        if hasattr(player, 'associated_hwids') and player.associated_hwids:
            identifiers.update(hwid for hwid in player.associated_hwids if hwid != "N/A")
        return list(identifiers)

    def _update_identity_graph(self, connections: List[Dict[str, Any]]) -> None:
        for conn in connections:
            user_name = conn.get("user_name")
            user_id = conn.get("user_id")
            ip = conn.get("ip_address")
            hwid = conn.get("hwid")
            if not user_name or user_name == "N/A":
                continue
            if user_id and user_id != "N/A":
                self.identity_graph[f"uid:{user_id}"].add(f"name:{user_name}")
                self.identity_graph[f"name:{user_name}"].add(f"uid:{user_id}")
            if ip and ip != "N/A":
                self.identity_graph[f"ip:{ip}"].add(f"name:{user_name}")
                self.identity_graph[f"name:{user_name}"].add(f"ip:{ip}")
            if hwid and hwid != "N/A":
                self.identity_graph[f"hwid:{hwid}"].add(f"name:{user_name}")
                self.identity_graph[f"name:{user_name}"].add(f"hwid:{hwid}")
            if ip and ip != "N/A" and hwid and hwid != "N/A":
                self.identity_graph[f"ip:{ip}"].add(f"hwid:{hwid}")
                self.identity_graph[f"hwid:{hwid}"].add(f"ip:{ip}")
            if user_id and user_id != "N/A":
                if ip and ip != "N/A":
                    self.identity_graph[f"uid:{user_id}"].add(f"ip:{ip}")
                    self.identity_graph[f"ip:{ip}"].add(f"uid:{user_id}")
                if hwid and hwid != "N/A":
                    self.identity_graph[f"uid:{user_id}"].add(f"hwid:{hwid}")
                    self.identity_graph[f"hwid:{hwid}"].add(f"uid:{user_id}")

    def _process_player_connections(self, player: Player, connections: List[Dict[str, Any]]) -> None:
        nickname_connections = defaultdict(list)
        for conn in connections:
            user_name = conn.get("user_name", "")
            if user_name:
                nickname_connections[user_name].append(conn)
        if hasattr(player, 'associated_ips'):
            for ip, nicknames in player.associated_ips.items():
                for conn in connections:
                    if conn.get("ip_address") == ip:
                        user_name = conn.get("user_name")
                        if user_name and user_name not in nicknames:
                            nicknames.append(user_name)
        if hasattr(player, 'associated_hwids'):
            for hwid, nicknames in player.associated_hwids.items():
                for conn in connections:
                    if conn.get("hwid") == hwid:
                        user_name = conn.get("user_name")
                        if user_name and user_name not in nicknames:
                            nicknames.append(user_name)
        denied_logins = []
        for conn in connections:
            if "Denied: Banned" in conn.get("status", ""):
                denied_logins.append({
                    "user_name": conn.get("user_name", ""),
                    "time": conn.get("time", ""),
                    "ip_address": conn.get("ip_address", ""),
                    "hwid": conn.get("hwid", ""),
                    "server": conn.get("server", "")
                })
        player.denied_logins = denied_logins
        if denied_logins and self.status_priority.get(player.status.lower(), 0) < self.status_priority['suspicious']:
            player.status = "suspicious"
            player.ban_counts = max(player.ban_counts, 1)

    @monitor_performance()
    async def scan_nickname(self, nickname: str, complaint_search_term: Optional[str] = None) -> List[Dict[str, Any]]:
        start_time = datetime.now()
        self.logger.info(f"Starting nickname search for: {nickname}")
        self._report_progress(0, 5, "Загрузка данных о наказаниях...")
        try:
            self.complaint_channels = await self.discord.update_complaint_cache(
                self.complaint_channels,
                history_limit=self.cfg.discord.message_history_limit
            )
            self._report_progress(1, 5, "Поиск игрока по связям (IP/HWID)...")
            player = await self.process_term(nickname)
            if not player:
                self.logger.info(f"No player found for nickname: {nickname}")
                return []
            self._report_progress(2, 5, "Поиск наказаний в Discord...")
            complaint_links = await self.discord.find_nickname_mentions(
                player.nicknames,
                self.complaint_channels,
                search_term=complaint_search_term
            )
            player.complaint_links = complaint_links
            if complaint_search_term:
                self.logger.info(f"Found {len(complaint_links)} complaints with '{complaint_search_term}'")
            self._report_progress(3, 5, "Анализ и объединение данных...")
            self._report_progress(4, 5, "Формирование отчета...")

            if self.progress_queue is not None:
                def _send(data):
                    try:
                        self.progress_queue.put_nowait(data)
                    except Exception:
                        pass

                primary = getattr(player, 'primary_nickname', player.nicknames[0] if player.nicknames else nickname)
                status = getattr(player, 'status', 'unknown')
                hwid_erased = getattr(player, 'hwid_erased', False)

                _send({"type": "player_summary", "nickname": nickname, "primary": primary,
                       "status": status, "ban_counts": getattr(player, 'ban_counts', 0),
                       "hwid_erased": hwid_erased})

                if hasattr(player, 'ban_reasons') and player.ban_reasons:
                    for i, ban in enumerate(player.ban_reasons):
                        _send({
                            "type": "punishment", "player": primary, "status": status,
                            "reason": ban.get("reason", str(ban)) if isinstance(ban, dict) else str(ban),
                            "banned_nickname": ban.get("username", primary) if isinstance(ban, dict) else primary,
                            "admin": ban.get("admin", "N/A") if isinstance(ban, dict) else "N/A",
                            "ban_type": ban.get("type", "N/A") if isinstance(ban, dict) else "N/A",
                            "ban_date": ban.get("date", "N/A") if isinstance(ban, dict) else "N/A",
                            "ban_expires": ban.get("expires", "Никогда") if isinstance(ban, dict) else "Никогда",
                            "search_nickname": nickname,
                            "index": i + 1,
                        })
                    _send({"type": "punishments_done"})

                if hasattr(player, 'nicknames') and player.nicknames and len(player.nicknames) > 1:
                    _send({"type": "nicknames", "nicknames": player.nicknames, "primary": primary})

                if hasattr(player, 'complaint_links') and player.complaint_links:
                    for i, c in enumerate(player.complaint_links):
                        _send({
                            "type": "complaint",
                            "channel": c.get("channel", "?"),
                            "author": c.get("author", "?"),
                            "content": c.get("content", "")[:300],
                            "link": c.get("link", "?"),
                            "index": i + 1,
                        })
                    _send({"type": "complaints_done"})

                if hasattr(player, 'associated_ips') and player.associated_ips:
                    items = []
                    for ip, users in player.associated_ips.items():
                        if primary in users and len(users) == 1:
                            items.append(ip)
                        else:
                            items.append(f"{ip}  ▶  {', '.join(users[:5])}")
                    _send({"type": "ips", "items": items, "primary": primary})

                if hasattr(player, 'associated_hwids') and player.associated_hwids:
                    items = []
                    for hwid, users in player.associated_hwids.items():
                        if primary in users and len(users) == 1:
                            items.append(hwid[:32])
                        else:
                            items.append(f"{hwid[:32]}  ▶  {', '.join(users[:5])}")
                    _send({"type": "hwids", "items": items, "primary": primary})

                if hasattr(player, 'denied_logins') and player.denied_logins:
                    _send({"type": "denied_logins", "logins": list(player.denied_logins)})

                _send({"type": "scan_results_done"})

            report_data = self.report.generate_nickname_search_report(nickname, player, gui_mode=self.progress_queue is not None)
            self._report_progress(5, 5, "Готово")
            duration = (datetime.now() - start_time).total_seconds()
            self.perf.logger.info(f"Nickname search for '{nickname}' completed in {duration:.2f}s")
            return report_data
        except Exception as e:
            self.logger.error(f"Error in scan_nickname for '{nickname}': {str(e)}", exc_info=True)
            return []
        finally:
            self.cache.save_complaint_cache(self.complaint_channels)



