import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from urllib.parse import quote_plus

from deadspace_checker.admin import N_A
from deadspace_checker.config import get_config
from deadspace_checker.utils.performance_monitor import monitor_performance


class PlayerSearchMixin:

    def _is_recent(self, time_str: str, days: int = 7) -> bool:
        if not time_str or time_str == N_A:
            return False
        try:
            conn_time = datetime.strptime(time_str, "%m/%d/%Y %I:%M:%S %p")
            if datetime.now() - conn_time < timedelta(days=days):
                return True
        except ValueError:
            if self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug(f"Could not parse time_str '{time_str}' for recency check.")
            return False
        return False

    def _has_information_gain(self, new_data: Dict[str, Any], existing_sets: Dict[str, Set[str]]) -> bool:
        if not new_data:
            return False

        new_nicknames = set(new_data.get('nicknames', []))
        new_ips = set(new_data.get('associated_ips', {}).keys())
        new_hwids = set(new_data.get('associated_hwids', {}).keys())

        nickname_gain = len(new_nicknames - existing_sets.get('nicknames', set())) > 0
        ip_gain = len(new_ips - existing_sets.get('ips', set())) > 0
        hwid_gain = len(new_hwids - existing_sets.get('hwids', set())) > 0

        existing_sets.setdefault('nicknames', set()).update(new_nicknames)
        existing_sets.setdefault('ips', set()).update(new_ips)
        existing_sets.setdefault('hwids', set()).update(new_hwids)

        return nickname_gain or ip_gain or hwid_gain

    @monitor_performance
    async def search_player(self, term: str, single_user: bool = True, max_depth: Optional[int] = None,
                            early_stop: bool = False) -> Optional[Dict[str, Any]]:
        try:
            async with asyncio.timeout(self._search_timeout):
                return await self._search_player_internal(term, single_user, max_depth, early_stop)
        except asyncio.TimeoutError:
            self.logger.error(f"Player search for '{term[:50]}' timed out after {self._search_timeout}s")
            return None
        except Exception as e:
            self.logger.error(f"Error in search_player for '{term[:50]}': {e}", exc_info=True)
            return None

    async def _search_player_internal(self, term: str, single_user: bool = True, max_depth: Optional[int] = None,
                                      early_stop: bool = False) -> Optional[Dict[str, Any]]:
        cfg = get_config()
        effective_max_depth = max_depth if max_depth is not None else getattr(cfg.scan, 'search_max_depth', 2)
        start_time_search = time.time()

        initial_term_is_likely_hwid = len(term) > 20 and any(c.islower() for c in term) and any(
            c.isupper() for c in term) and ('/' in term or '+' in term or '=' in term)

        initial_search_term_str = term
        initial_term_canonical = term.strip() if initial_term_is_likely_hwid else term.lower().strip()

        if self.logger.isEnabledFor(logging.INFO):
            self.logger.info(
                f"Initiating player search for term: '{initial_search_term_str[:50]}' "
                f"(canonical: '{initial_term_canonical[:50]}'), single_user={single_user}, max_depth={effective_max_depth}, early_stop={early_stop}"
            )

        cache_key = f"search_player_v6:{initial_term_canonical}:single_user={single_user}:max_depth={effective_max_depth}:early_stop={early_stop}"

        cached_result = self.search_results_cache.get(cache_key)
        if cached_result is not None:
            if self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug(f"Returning cached search result for '{initial_term_canonical[:50]}'")
            return cached_result

        processed_terms: Set[str] = set()
        search_queue = deque([((term.strip(), initial_term_is_likely_hwid), 0)])
        terms_in_flight: Set[str] = {initial_term_canonical}

        merged_result_data: Optional[Dict[str, Any]] = None
        search_stats = {"unique_api_calls": 0, "depth_distribution": {}, "timeouts": 0, "errors": 0}

        information_sets: Dict[str, Set[str]] = {'nicknames': set(), 'ips': set(), 'hwids': set()}
        pages_without_gain = 0
        max_pages_without_gain = 3

        while search_queue:
            batch_size = min(getattr(cfg.scan, 'search_batch_size', 2), len(search_queue))
            items_to_process_this_batch = [search_queue.popleft() for _ in range(batch_size)]

            tasks, actual_items_for_api = [], []
            for (term_str_to_process, term_is_hwid_flag), depth in items_to_process_this_batch:
                canonical_term_to_process = term_str_to_process if term_is_hwid_flag else term_str_to_process.lower()
                if canonical_term_to_process in processed_terms:
                    continue

                tasks.append(self._process_search_term_enhanced(
                    term_str_to_process, term_is_hwid_flag, depth, single_user, effective_max_depth,
                    processed_terms, terms_in_flight
                ))
                actual_items_for_api.append(
                    ((term_str_to_process, term_is_hwid_flag), depth, canonical_term_to_process))

            if not tasks:
                continue

            if search_stats["unique_api_calls"] > 0:
                await asyncio.sleep(1.0)

            try:
                async with asyncio.timeout(self._search_timeout // 2):
                    results_from_batch = await asyncio.gather(*tasks, return_exceptions=True)
            except asyncio.TimeoutError:
                search_stats["timeouts"] += 1
                self.logger.error(f"Search batch processing timed out for term '{term[:50]}'")
                break

            batch_had_gain = False
            for i, res_or_exc in enumerate(results_from_batch):
                (_original_term_tuple, original_depth, canonical_original_term) = actual_items_for_api[i]
                original_term_str, _ = _original_term_tuple

                if canonical_original_term not in processed_terms:
                    processed_terms.add(canonical_original_term)
                    search_stats["unique_api_calls"] += 1
                    search_stats["depth_distribution"][original_depth] = search_stats["depth_distribution"].get(
                        original_depth, 0) + 1

                if isinstance(res_or_exc, Exception):
                    search_stats["errors"] += 1
                    if self.logger.isEnabledFor(logging.ERROR):
                        self.logger.error(f"Error processing search term '{original_term_str[:50]}': {res_or_exc}",
                                          exc_info=False)
                    continue

                individual_result: Optional[Dict[str, Any]] = res_or_exc
                if not individual_result or not individual_result.get('result_data'):
                    continue

                if early_stop:
                    has_gain = self._has_information_gain(individual_result['result_data'], information_sets)
                    if has_gain:
                        batch_had_gain = True

                if merged_result_data is None:
                    merged_result_data = individual_result['result_data']
                else:
                    self._merge_search_results(merged_result_data, individual_result['result_data'])

                expansion_limit = self._get_search_limit_for_depth(original_depth)
                new_terms = individual_result.get('new_terms_to_search', [])[:expansion_limit]

                for new_term_str, new_term_is_hwid_flag in new_terms:
                    canonical_new_term = new_term_str if new_term_is_hwid_flag else new_term_str.lower()
                    if canonical_new_term not in terms_in_flight and len(search_queue) < 20:
                        search_queue.append(((new_term_str, new_term_is_hwid_flag), original_depth + 1))
                        terms_in_flight.add(canonical_new_term)

            if early_stop:
                if batch_had_gain:
                    pages_without_gain = 0
                else:
                    pages_without_gain += 1

                if pages_without_gain >= max_pages_without_gain:
                    self.logger.info(f"Early stopping: {pages_without_gain} pages without information gain")
                    break

        search_elapsed_time = time.time() - start_time_search
        if self.logger.isEnabledFor(logging.INFO):
            self.logger.info(
                f"Search for '{initial_search_term_str[:50]}' completed in {search_elapsed_time:.2f}s. "
                f"API Calls={search_stats['unique_api_calls']}, Depth Dist={search_stats['depth_distribution']}, "
                f"Timeouts={search_stats['timeouts']}, Errors={search_stats['errors']}, "
                f"Early Stop={'Yes' if early_stop and pages_without_gain >= max_pages_without_gain else 'No'}"
            )

        if merged_result_data:
            self.search_results_cache.put(cache_key, merged_result_data)

        return merged_result_data

    async def _process_search_term_enhanced(
            self, current_term_str: str, current_term_is_hwid: bool, current_depth: int,
            single_user_mode: bool, max_search_depth: int,
            glob_processed_terms: Set[str], glob_terms_in_flight: Set[str]
    ) -> Optional[Dict[str, Any]]:

        canonical_term_for_url = current_term_str
        if not current_term_is_hwid:
            canonical_term_for_url = current_term_str.lower()

        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(
                f"Processing search for term: '{current_term_str[:50]}' at depth {current_depth}"
            )

        try:
            async with asyncio.timeout(self._request_timeout):
                def _build_search_url(term: str) -> str:
                    if term.replace('-', '').replace('.', '').replace('_', '').isalnum():
                        return f"{self.base_admin_connections_url}&search={term}"
                    return f"{self.base_admin_connections_url}&search={quote_plus(term)}"

                connections_search_url = _build_search_url(canonical_term_for_url)

                term_data = await self.fetch_with_rate_limit(
                    self.admin_panel.check_account_on_site,
                    connections_search_url,
                    single_user=single_user_mode
                )

                if isinstance(term_data, dict) and term_data.get("status") == "unknown" and term_data.get("user_id") == N_A:
                    if self.logger.isEnabledFor(logging.WARNING):
                        self.logger.warning(
                            f"ADMIN PANEL: Search for '{current_term_str}' returned 0 connections (status=unknown, user_id=N/A). "
                            f"URL: {connections_search_url}"
                        )
                    if canonical_term_for_url != current_term_str:
                        alt_url = _build_search_url(current_term_str)
                        alt_data = await self.fetch_with_rate_limit(
                            self.admin_panel.check_account_on_site,
                            alt_url,
                            single_user=single_user_mode
                        )
                        if isinstance(alt_data, dict) and not (alt_data.get("status") == "unknown" and alt_data.get("user_id") == N_A):
                            if self.logger.isEnabledFor(logging.INFO):
                                self.logger.info(f"Search with original case '{current_term_str}' succeeded (lowercase returned 0).")
                            term_data = alt_data
                    if isinstance(term_data, dict) and term_data.get("status") == "unknown" and term_data.get("user_id") == N_A:
                        return None

                if not term_data or (isinstance(term_data, list) and not term_data):
                    if canonical_term_for_url != current_term_str:
                        alt_url = _build_search_url(current_term_str)
                        alt_data = await self.fetch_with_rate_limit(
                            self.admin_panel.check_account_on_site,
                            alt_url,
                            single_user=single_user_mode
                        )
                        if alt_data and not (isinstance(alt_data, list) and not alt_data):
                            term_data = alt_data
                            if self.logger.isEnabledFor(logging.INFO):
                                self.logger.info(
                                    f"Search with original case '{current_term_str}' succeeded (lowercase failed).")
                    if not term_data or (isinstance(term_data, list) and not term_data):
                        if self.logger.isEnabledFor(logging.DEBUG):
                            self.logger.debug(f"No data returned for term '{current_term_str[:50]}'.")
                        return None

                aggregated_data_for_term = term_data
                new_terms_to_queue: List[Tuple[str, bool]] = []

                if current_depth < max_search_depth and current_depth < 2:
                    if isinstance(aggregated_data_for_term, dict):
                        all_connections_recent = False
                        if "raw_html_snippet" in aggregated_data_for_term and aggregated_data_for_term[
                            "raw_html_snippet"]:
                            all_connections_recent = all(
                                self._is_recent(conn_prev.get("time"), days=7)
                                for conn_prev in aggregated_data_for_term["raw_html_snippet"] if conn_prev.get("time")
                            ) if aggregated_data_for_term["raw_html_snippet"] else False

                        if all_connections_recent and aggregated_data_for_term["raw_html_snippet"]:
                            if self.logger.isEnabledFor(logging.DEBUG):
                                self.logger.debug(
                                    f"Term '{current_term_str[:50]}' data appears very recent. Suppressing further expansion.")
                        else:
                            extracted_identifiers_with_type = self._extract_prioritized_identifiers(
                                aggregated_data_for_term, current_term_str, current_term_is_hwid,
                                glob_processed_terms, glob_terms_in_flight
                            )
                            search_limit_for_depth = self._get_search_limit_for_depth(current_depth)

                            optimizer_stats = self._optimizer.get_current_stats()
                            if optimizer_stats['average_latency'] > 20:
                                search_limit_for_depth = max(1, search_limit_for_depth - 1)

                            new_terms_to_queue.extend(extracted_identifiers_with_type[:search_limit_for_depth])
                            if new_terms_to_queue and self.logger.isEnabledFor(logging.DEBUG):
                                self.logger.debug(
                                    f"Identified {len(new_terms_to_queue)} new terms from '{current_term_str[:50]}' "
                                    f"for depth {current_depth + 1}.")
                    elif self.logger.isEnabledFor(logging.DEBUG):
                        self.logger.debug(
                            f"Data for '{current_term_str[:50]}' (type: {type(aggregated_data_for_term)}) not dict, "
                            f"cannot extract new ids.")

                return {'result_data': aggregated_data_for_term, 'new_terms_to_search': new_terms_to_queue}

        except asyncio.TimeoutError:
            self.logger.error(
                f"Search term processing timed out for '{current_term_str[:50]}' at depth {current_depth}")
            return None
        except Exception as e:
            if self.logger.isEnabledFor(logging.ERROR):
                self.logger.error(
                    f"Error processing search term '{current_term_str[:50]}' at depth {current_depth}: {e}",
                    exc_info=False)
            return None

    def _extract_prioritized_identifiers(
            self, result_dict: Dict[str, Any],
            origin_term_str: str, origin_term_is_hwid: bool,
            glob_processed_terms: Set[str], glob_terms_in_flight: Set[str]
    ) -> List[Tuple[str, bool]]:

        potential_new_ids: List[Tuple[int, str, bool]] = []

        def add_if_valid(identifier: Optional[str], priority: int, term_is_hwid: bool):
            if not identifier or identifier == N_A or not isinstance(identifier, str) or not identifier.strip():
                return

            id_str_stripped = identifier.strip()

            comp_term = id_str_stripped if term_is_hwid else id_str_stripped.lower()
            origin_comp_term = origin_term_str.strip() if origin_term_is_hwid else origin_term_str.lower().strip()

            if comp_term == origin_comp_term:
                return

            if comp_term in glob_processed_terms or comp_term in glob_terms_in_flight:
                return

            if priority == 2:
                is_private = False
                try:
                    if (id_str_stripped.startswith("192.168.") or
                            id_str_stripped.startswith("10.") or
                            (id_str_stripped.startswith("172.") and 16 <= int(id_str_stripped.split('.')[1]) <= 31)):
                        is_private = True
                except (ValueError, IndexError):
                    pass
                if is_private:
                    if self.logger.isEnabledFor(logging.DEBUG):
                        self.logger.debug(f"Skipping private IP for expansion: {id_str_stripped}")
                    return

            potential_new_ids.append((priority, id_str_stripped, term_is_hwid))

        add_if_valid(result_dict.get("user_id"), 0, False)
        for hwid_val in result_dict.get("associated_hwids", {}).keys():
            add_if_valid(hwid_val, 1, True)
        for ip_val in result_dict.get("associated_ips", {}).keys():
            add_if_valid(ip_val, 2, False)
        for nickname_val in result_dict.get("nicknames", []):
            add_if_valid(nickname_val, 3, False)

        potential_new_ids.sort(key=lambda x: (x[0], x[1]))

        return [(id_str, is_hwid) for _, id_str, is_hwid in potential_new_ids]

    def _get_search_limit_for_depth(self, depth: int) -> int:
        cfg = get_config()
        if depth == 0:
            return getattr(cfg.scan, 'search_limit_root', 5)
        if depth == 1:
            return getattr(cfg.scan, 'search_limit_level1', 3)
        if depth == 2:
            return getattr(cfg.scan, 'search_limit_level2', 2)
        return getattr(cfg.scan, 'search_limit_default', 1)

    def _merge_search_results(self, main_result: Dict[str, Any], new_data: Dict[str, Any]) -> None:
        if not isinstance(main_result, dict) or not isinstance(new_data, dict):
            if self.logger.isEnabledFor(logging.WARNING):
                self.logger.warning(
                    f"Attempted to merge non-dict results. Main: {type(main_result)}, New: {type(new_data)}")
            return

        main_nicks = set(main_result.get("nicknames", []))
        main_nicks.update(new_data.get("nicknames", []))
        main_result["nicknames"] = sorted(main_nicks)

        main_shared = set(main_result.get("shared_hwid_nicknames", []))
        main_shared.update(new_data.get("shared_hwid_nicknames", []))
        main_result["shared_hwid_nicknames"] = sorted(main_shared)

        def br_key(br):
            return frozenset(br.items())

        merged_brs = {br_key(br): br for br in main_result.get("ban_reasons", [])}
        for br_new in new_data.get("ban_reasons", []):
            merged_brs.setdefault(br_key(br_new), br_new)
        main_result["ban_reasons"] = sorted(list(merged_brs.values()),
                                            key=lambda x: (x.get("username", ""), x.get("reason", "")))

        def dc_key(dc):
            return frozenset(dc.items())

        merged_dcs = {dc_key(dc): dc for dc in main_result.get("denied_banned_connections", [])}
        for dc_new in new_data.get("denied_banned_connections", []):
            merged_dcs.setdefault(dc_key(dc_new), dc_new)
        main_result["denied_banned_connections"] = sorted(list(merged_dcs.values()), key=lambda x: x.get("time", ""))

        assoc_ips = main_result.get("associated_ips", {})
        for ip, nicks in new_data.get("associated_ips", {}).items():
            if ip in assoc_ips:
                existing = set(assoc_ips[ip])
                existing.update(nicks)
                assoc_ips[ip] = sorted(existing)
            else:
                assoc_ips[ip] = sorted(nicks) if not isinstance(nicks, list) or nicks != sorted(nicks) else nicks
        main_result["associated_ips"] = assoc_ips

        assoc_hwids = main_result.get("associated_hwids", {})
        for hwid, nicks in new_data.get("associated_hwids", {}).items():
            if hwid in assoc_hwids:
                existing_nicks = set(assoc_hwids[hwid])
                existing_nicks.update(nicks)
                assoc_hwids[hwid] = sorted(existing_nicks)
            else:
                assoc_hwids[hwid] = sorted(nicks) if not isinstance(nicks, list) or nicks != sorted(nicks) else nicks
        main_result["associated_hwids"] = assoc_hwids

        main_result["ban_counts"] = max(main_result.get("ban_counts", 0), new_data.get("ban_counts", 0))

        s_pri = {'suspicious': 4, 'banned': 3, 'clean': 1, 'unknown': 0, N_A: 0}
        cur_s, new_s = str(main_result.get("status", "u")).lower(), str(new_data.get("status", "u")).lower()
        if s_pri.get(new_s, 0) > s_pri.get(cur_s, 0):
            main_result["status"] = new_data.get("status")

        if main_result.get("user_id", N_A) == N_A and new_data.get("user_id", N_A) != N_A:
            main_result["user_id"] = new_data.get("user_id")
        if main_result.get("connection_link", N_A) == N_A and new_data.get("connection_link", N_A) != N_A:
            main_result["connection_link"] = new_data.get("connection_link")
        main_result["hwid_erased"] = bool(main_result.get("hwid_erased", False) or new_data.get("hwid_erased", False))
        if not main_result.get("raw_html_snippet") and new_data.get("raw_html_snippet"):
            main_result["raw_html_snippet"] = new_data.get("raw_html_snippet")
