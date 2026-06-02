import asyncio
import heapq
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Any, Set

from deadspace_checker.config import get_config
from deadspace_checker.utils.performance_monitor import monitor_performance


def _format_ban_reason(template, banned_user_name, bypass_reason, bypass_user_names):
    try:
        return template.format(
            user=banned_user_name,
            confidence=bypass_reason,
            bypassers=", ".join(bypass_user_names) if bypass_user_names else "unknown",
        )
    except KeyError:
        return template


def _get_minimum_time_difference(ban_hit_time, suspected_users, connections):
    min_diff = float('inf')
    for conn in connections:
        if conn.get("user_name") in suspected_users:
            try:
                conn_time = datetime.strptime(conn.get("time", ""), "%Y-%m-%d %H:%M:%S")
                diff_minutes = abs((conn_time - ban_hit_time).total_seconds() / 60.0)
                min_diff = min(min_diff, diff_minutes)
            except (ValueError, TypeError):
                pass
    return min_diff if min_diff != float('inf') else 60


def _determine_bypass_success(connections, bypass_user_names, ban_time_str, banned_hwid, banned_ip):
    if not bypass_user_names or not connections:
        return "Unknown"
    try:
        ban_time = datetime.strptime(ban_time_str, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return "Unknown"
    successful_logins = []
    unsuccessful_logins = []
    for conn in connections:
        user_name = conn.get("user_name", "")
        if user_name not in bypass_user_names:
            continue
        conn_time_str = conn.get("time", "")
        if not conn_time_str:
            continue
        try:
            conn_time = datetime.strptime(conn_time_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if conn_time <= ban_time:
            continue
        status = conn.get("status", "")
        if "Denied: Banned" in status:
            unsuccessful_logins.append(conn)
        elif "Accepted" in status:
            successful_logins.append(conn)
    if successful_logins:
        hwid_changed = any(conn.get("hwid", "") != banned_hwid for conn in successful_logins)
        ip_changed = any(conn.get("ip_address", "") != banned_ip for conn in successful_logins)
        if hwid_changed:
            return "Successful Bypass"
        elif ip_changed:
            return "Possibly Successful Bypass"
        else:
            return "Unknown"
    elif unsuccessful_logins:
        return "Unsuccessful Bypass"
    else:
        return "Unknown"


class BanBypassMixin:

    @monitor_performance()
    async def scan_ban_bypasses(self, max_pages: int = 5) -> List[Dict[str, Any]]:
        start_time = datetime.now()
        max_depth = getattr(self.cfg.scan, 'bypass_search_max_depth', 2)
        self.logger.info(f"Starting Ban Bypass Check, fetching up to {max_pages} pages with max depth {max_depth}...")

        try:
            async with asyncio.timeout(self._operation_timeout * 10):
                return await self._scan_ban_bypasses_internal(max_pages, max_depth, start_time)
        except asyncio.TimeoutError:
            self.logger.error(f"Ban bypass scan timed out after {self._operation_timeout * 10}s")
            return []
        except Exception as e:
            self.logger.error(f"Error during ban bypass check: {str(e)}", exc_info=True)
            return []
        finally:
            self.cache.save_complaint_cache(self.complaint_channels)

    async def _scan_ban_bypasses_internal(self, max_pages: int, max_depth: int, start_time: datetime) -> List[Dict[str, Any]]:
        try:
            self.complaint_channels = await self.discord.update_complaint_cache(
                self.complaint_channels,
                history_limit=self.cfg.discord.message_history_limit
            )

            ban_hit_connections = await asyncio.wait_for(
                self.admin_panel.fetch_ban_hit_connections(max_pages=max_pages),
                timeout=self._operation_timeout
            )

            self._report_log(f"Найдено забаненных подключений: {len(ban_hit_connections)}")
            max_ban_hits = getattr(self.cfg.scan, 'max_ban_hits', 200)
            if len(ban_hit_connections) > max_ban_hits:
                ban_hit_connections = ban_hit_connections[:max_ban_hits]
                self.logger.info(f"Limited to {max_ban_hits} most recent ban hits for processing")
            if not ban_hit_connections:
                self.logger.info("No ban hit connections found.")
                return []

            self.logger.info(f"Processing {len(ban_hit_connections)} ban hits with max depth {max_depth}")
            processed_terms = set()
            self.connections_cache = getattr(self, 'connections_cache', {})
            self._ban_hit_failures = getattr(self, '_ban_hit_failures', {})
            ban_hit_connections.sort(key=lambda x: x.get("time", ""), reverse=True)
            batch_size = max(self.max_concurrent, 4)
            results = []

            for i in range(0, len(ban_hit_connections), batch_size):
                batch = ban_hit_connections[i:i + batch_size]
                self.logger.info(
                    f"Processing batch {i // batch_size + 1}/{(len(ban_hit_connections) + batch_size - 1) // batch_size}")
                progress_stats = defaultdict(int)
                batch_tasks = []

                for ban_hit in batch:
                    ban_hit_key = ban_hit.get("ban_hits_link") or ban_hit.get("connection_id", "")
                    fail_count = self._ban_hit_failures.get(ban_hit_key, 0)
                    if fail_count >= 2:
                        self.logger.warning(f"Skipping ban hit {ban_hit.get('user_name', '?')} after {fail_count} failures")
                        continue
                    task = self._process_ban_hit_with_timeout(
                        ban_hit,
                        max_depth,
                        processed_terms,
                        progress_stats
                    )
                    batch_tasks.append(task)

                try:
                    batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
                    valid_results = []
                    for result in batch_results:
                        if isinstance(result, Exception):
                            self.logger.error(f"Error in batch processing: {str(result)}")
                            continue
                        if result:
                            valid_results.append(result)
                    results.extend(valid_results)

                    self.logger.info(f"Batch {i // batch_size + 1} stats: " +
                                     f"processed={progress_stats['processed']}, " +
                                     f"hwid_matches={progress_stats.get('hwid_matches', 0)}, " +
                                     f"ip_matches={progress_stats.get('ip_matches', 0)}")

                    if i + batch_size < len(ban_hit_connections):
                        await asyncio.sleep(0.5)
                except Exception as e:
                    self.logger.error(f"Error processing batch {i // batch_size + 1}: {e}")

            cache_hits = sum(1 for term in processed_terms if term in self.connections_cache)
            duration = (datetime.now() - start_time).total_seconds()
            self._report_log(f"Итого: обработано {len(ban_hit_connections)} банов, найдено {len(results)} обходов")
            self.logger.info(
                f"Ban Bypass Check completed in {duration:.2f}s: processed {len(ban_hit_connections)} ban hits, "
                f"found {len(results)} results with depth {max_depth}, "
                f"processed {len(processed_terms)} unique terms, cache hits: {cache_hits}"
            )
            self.connections_cache.clear()
            return results

        except asyncio.TimeoutError:
            self.logger.error("Ban bypass scan internal process timed out")
            return []

    async def _process_ban_hit_with_timeout(self, ban_hit, max_depth, processed_terms, progress_stats):
        try:
            async with asyncio.timeout(self._operation_timeout):
                return await self._process_ban_hit(ban_hit, max_depth, processed_terms, progress_stats)
        except asyncio.TimeoutError:
            self.logger.error(f"Ban hit processing timed out for {ban_hit.get('ban_hits_link')}")
            bh_key = ban_hit.get("ban_hits_link") or ban_hit.get("connection_id", "")
            if bh_key:
                self._ban_hit_failures[bh_key] = self._ban_hit_failures.get(bh_key, 0) + 1
            return None
        except Exception as e:
            self.logger.error(f"Error in _process_ban_hit_with_timeout: {e}")
            bh_key = ban_hit.get("ban_hits_link") or ban_hit.get("connection_id", "")
            if bh_key:
                self._ban_hit_failures[bh_key] = self._ban_hit_failures.get(bh_key, 0) + 1
            return None

    async def _auto_ban_bypass(self, banned_user_name, user_id, ip_address, hwid,
                                bypass_reason, bypass_user_names):
        cfg = get_config()
        if not cfg.scan.auto_ban_enabled:
            return False

        confidence_rank = {
            "NO_MATCH": 0, "IP_MATCH": 1, "IP_DISTANT_TIME": 2,
            "IP_MODERATE_TIME": 3, "IP_CLOSE_TIME": 4,
            "IP_VERY_CLOSE_TIME": 5, "HWID_MATCH": 6,
        }
        min_rank = confidence_rank.get(cfg.scan.auto_ban_min_confidence, 6)
        actual_rank = confidence_rank.get(bypass_reason, 0)
        if actual_rank < min_rank:
            self.logger.info(
                f"Auto-ban skipped for {banned_user_name}: confidence {bypass_reason} "
                f"< minimum {cfg.scan.auto_ban_min_confidence}"
            )
            return False

        auto_banned = False
        reason = _format_ban_reason(cfg.scan.auto_ban_reason, banned_user_name, bypass_reason, bypass_user_names)
        targets = []

        if hwid and hwid != "N/A":
            targets.append(("hwid", hwid))

        if ip_address and ip_address != "N/A":
            targets.append(("ip", ip_address))

        for target_type, target_value in targets:
            kwargs = dict(reason=reason, minutes=cfg.scan.auto_ban_minutes)
            if user_id and user_id != "N/A":
                kwargs["user_id"] = user_id
            if target_type == "ip":
                kwargs["ip_address"] = target_value
            elif target_type == "hwid":
                kwargs["hwid"] = target_value

            result = await self.admin.auto_ban(**kwargs)

            if result:
                self.logger.info(
                    f"Auto-ban issued for {banned_user_name}: {target_type}={target_value} "
                    f"(confidence: {bypass_reason})"
                )
                auto_banned = True
            else:
                self.logger.error(
                    f"Auto-ban FAILED for {banned_user_name}: {target_type}={target_value}"
                )

        return auto_banned

    async def _process_ban_hit(self, ban_hit, max_depth, processed_terms, progress_stats):
        try:
            progress_stats['processed'] += 1
            ban_id = ban_hit.get("connection_id", "") or ban_hit.get("ban_hits_link", "")
            ban_hit_time = datetime.strptime(ban_hit["time"], "%Y-%m-%d %H:%M:%S")
            user_id = ban_hit.get("user_id")
            user_name = ban_hit.get("user_name", "?")
            if not user_id or user_id == "N/A":
                self._report_log(f"Пропущен {user_name}: нет user_id")
                return None
            ban_hits_link = ban_hit.get("ban_hits_link")
            async with asyncio.Lock():
                if ban_id and ban_id in processed_terms:
                    self._report_log(f"Пропущен {user_name}: уже обработан")
                    return None
                if ban_id:
                    processed_terms.add(ban_id)
            banned_user_name = ban_hit.get("user_name", "")
            ip_address = ban_hit.get("ip_address", "")
            hwid = ban_hit.get("hwid", "")
            ban_time_str = ban_hit["time"]
            ban_expires_str = ban_hit["time"]
            ban_info_list = []

            if ban_hits_link:
                ban_info_list = await self.admin.fetch_with_rate_limit(
                    self.admin_panel.fetch_ban_info,
                    ban_hits_link
                )
                if ban_info_list:
                    if len(ban_info_list) > 1:
                        self.logger.info(f"Found {len(ban_info_list)} ban bypass attempts for connection {ban_id}")
                        for idx, entry in enumerate(ban_info_list):
                            ban_time = entry.get("ban_time", "unknown")
                            ban_reason = entry.get("ban_reason", "unknown")
                            self.logger.info(f"  Ban bypass #{idx + 1}: {ban_time} (reason: {ban_reason})")
                    ban_info = ban_info_list[0]
                    banned_user_name = ban_info.get("banned_user_name") or banned_user_name
                    user_id = ban_info.get("user_id") or user_id
                    ip_address = ban_info.get("ip_address") or ip_address
                    hwid = ban_info.get("hwid") or hwid
                    ban_time_str = ban_info.get("ban_time", ban_time_str)
                    ban_expires_str = ban_info.get("expires", ban_expires_str)
            hwid_erased = not hwid or hwid.strip() == ""
            self.logger.info(f"Processing ban hit for user '{banned_user_name}' (ID: {user_id})")
            connections = await self._gather_connections(
                user_id,
                hwid,
                ip_address,
                max_depth,
                processed_terms,
                banned_user_name
            )
            hwid_match_users = set()
            if hwid and hwid != "N/A":
                for conn in connections:
                    if conn.get("hwid") == hwid and conn.get("user_name") != banned_user_name:
                        hwid_match_users.add(conn.get("user_name"))
                if hwid_match_users:
                    progress_stats['hwid_matches'] = progress_stats.get('hwid_matches', 0) + 1
                    self.logger.info(f"HWID match found for {banned_user_name}: {', '.join(sorted(hwid_match_users))}")
            account_info = await self.admin_panel.aggregate_single_user_info(connections)
            bypass_reason = self.analyzer.confidence_levels['no_match']
            bypass_user_names = []
            if hwid_match_users:
                bypass_reason = self.analyzer.confidence_levels['hwid_match']
                bypass_user_names = sorted(hwid_match_users)
            elif ip_address and ip_address != "N/A":
                time_suspected_users = self._check_time_based_bypass(ban_hit_time, ip_address, banned_user_name,
                                                                     connections)
                if time_suspected_users:
                    time_diff_minutes = _get_minimum_time_difference(ban_hit_time, time_suspected_users,
                                                                     connections)
                    if time_diff_minutes <= self.analyzer.very_close_time_threshold_minutes:
                        bypass_reason = self.analyzer.confidence_levels['ip_very_close_time']
                    elif time_diff_minutes <= self.analyzer.close_time_threshold_minutes:
                        bypass_reason = self.analyzer.confidence_levels['ip_close_time']
                    elif time_diff_minutes <= self.analyzer.moderate_time_threshold_minutes:
                        bypass_reason = self.analyzer.confidence_levels['ip_moderate_time']
                    elif time_diff_minutes <= self.analyzer.distant_time_threshold_minutes:
                        bypass_reason = self.analyzer.confidence_levels['ip_distant_time']
                    else:
                        bypass_reason = self.analyzer.confidence_levels['ip_match']
                    bypass_user_names = sorted(set(time_suspected_users))
                    progress_stats['ip_matches'] = progress_stats.get('ip_matches', 0) + 1
                elif ip_address in account_info.get("associated_ips", {}):
                    ip_nicks = set(account_info["associated_ips"][ip_address]) - {banned_user_name}
                    if ip_nicks:
                        bypass_reason = self.analyzer.confidence_levels['ip_match']
                        bypass_user_names = sorted(ip_nicks)
                        progress_stats['ip_matches'] = progress_stats.get('ip_matches', 0) + 1
            bypass_success_status = _determine_bypass_success(connections, bypass_user_names, ban_time_str, hwid,
                                                              ip_address)
            player = self.admin.convert_to_player(account_info)
            player.hwid_erased = hwid_erased
            complaint_task = asyncio.create_task(self.discord.find_nickname_mentions(
                [banned_user_name] + bypass_user_names,
                self.complaint_channels
            ))
            complaint_links = await complaint_task
            has_meaningful_result = (
                bypass_reason != self.analyzer.confidence_levels['no_match'] or
                bypass_user_names or
                hwid_erased or
                complaint_links
            )
            if not has_meaningful_result:
                self._report_log(f"Пропущен {banned_user_name}: нет признаков обхода (совпадений IP/HWID не найдено)")
                self.logger.info(f"No meaningful bypass detected for {banned_user_name}")
                return None

            confidence_label = {
                "HWID_MATCH": "HWID-совпадение",
                "IP_VERY_CLOSE_TIME": "IP+время (очень близко)",
                "IP_CLOSE_TIME": "IP+время (близко)",
                "IP_MODERATE_TIME": "IP+время (умеренно)",
                "IP_DISTANT_TIME": "IP+время (давно)",
                "IP_MATCH": "IP-совпадение",
            }.get(bypass_reason, bypass_reason)
            extra = ""
            if hwid_erased:
                extra += " HWID стёрт"
            if complaint_links:
                extra += f" {len(complaint_links)} жалоб"
            self._report_log(f"Обход {banned_user_name}: {confidence_label}{extra} твинки={bypass_user_names}")

            await self._auto_ban_bypass(
                banned_user_name, user_id, ip_address, hwid,
                bypass_reason, bypass_user_names
            )

            report = {
                "message_id": "BanBypassCheck",
                "message_link": ban_hits_link,
                "author_name": banned_user_name,
                "author_id": user_id,
                "scan_time": datetime.now().isoformat(),
                "ban_time": ban_time_str,
                "ban_expires": ban_expires_str,
                "ban_bypass_confidence": bypass_reason,
                "bypass_user_names": bypass_user_names,
                "bypass_success_status": bypass_success_status,
                "hwid_erased": hwid_erased,
                "search_depth": max_depth,
                "connections_analyzed": len(connections),
                "ban_entries_count": len(ban_info_list),
                "all_ban_entries": ban_info_list,
                "results": [{
                    "initial_account": account_info,
                    "complaint_links": complaint_links,
                    "nicknames": player.nicknames,
                    "hwid_erased": hwid_erased,
                    "banned_user_name": banned_user_name,
                    "ip_address": ip_address,
                    "hwid": hwid
                }]
            }
            self.logger.info(
                f"Ban hit for {banned_user_name}: Confidence: {bypass_reason}, " +
                f"Bypass status: {bypass_success_status}, " +
                f"Potential bypassers: {', '.join(bypass_user_names) if bypass_user_names else 'None'}, " +
                f"Analyzed {len(connections)} connections, " +
                f"Found {len(ban_info_list)} ban entries"
            )
            return report
        except Exception as e:
            self.logger.error(f"Error processing ban hit {ban_hit.get('ban_hits_link')}: {str(e)}", exc_info=True)
            return None

    async def _gather_connections(self, user_id, hwid, ip_address, max_depth, processed_terms,
                                  banned_user_name):
        search_processed = set()
        priority_queue = []
        if user_id and user_id != "N/A":
            heapq.heappush(priority_queue, (0, 1, "user_id", user_id))
            search_processed.add(user_id)
        if hwid and hwid != "N/A":
            heapq.heappush(priority_queue, (0, 2, "hwid", hwid))
            search_processed.add(hwid)
        if ip_address and ip_address != "N/A":
            heapq.heappush(priority_queue, (0, 3, "ip", ip_address))
            search_processed.add(ip_address)
        all_connections = []
        max_by_type_depth = {
            "user_id": {0: 100, 1: 50, 2: 30, 3: 20},
            "hwid": {0: 100, 1: 40, 2: 20, 3: 10},
            "ip": {0: 50, 1: 30, 2: 15, 3: 5},
            "username": {0: 30, 1: 20, 2: 10, 3: 5}
        }
        active_tasks = {}
        while priority_queue:
            batch = []
            batch_size = min(5, len(priority_queue))
            for _ in range(batch_size):
                if not priority_queue:
                    break
                item = heapq.heappop(priority_queue)
                depth, type_priority, id_type, identifier = item
                if depth > max_depth:
                    continue
                batch.append((depth, type_priority, id_type, identifier))
            fetch_tasks = []
            for depth, type_priority, id_type, identifier in batch:
                if identifier in active_tasks:
                    continue
                if identifier in self.connections_cache:
                    connections = self.connections_cache[identifier]
                    await self._process_connections_for_queue(
                        connections, identifier, depth, priority_queue,
                        search_processed, processed_terms, all_connections,
                        max_by_type_depth
                    )
                else:
                    task = self._fetch_and_process_connections(
                        identifier, depth, priority_queue, search_processed,
                        processed_terms, all_connections, max_by_type_depth,
                        banned_user_name
                    )
                    active_tasks[identifier] = asyncio.create_task(task)
                    fetch_tasks.append(active_tasks[identifier])
            if fetch_tasks:
                await asyncio.gather(*fetch_tasks, return_exceptions=True)
                for depth, _, _, identifier in batch:
                    if identifier in active_tasks:
                        del active_tasks[identifier]
            await asyncio.sleep(0)
        if active_tasks:
            await asyncio.gather(*active_tasks.values(), return_exceptions=True)
        return all_connections

    async def _fetch_and_process_connections(self, identifier, depth, priority_queue, search_processed,
                                             processed_terms, all_connections, max_by_type_depth,
                                             banned_user_name):
        try:
            connections = await self.admin.fetch_with_rate_limit(
                self.admin_panel.fetch_connections_for_user,
                identifier
            )
            self.connections_cache[identifier] = connections or []
            await self._process_connections_for_queue(
                connections, identifier, depth, priority_queue,
                search_processed, processed_terms, all_connections,
                max_by_type_depth
            )
            return connections or []
        except Exception as e:
            self.logger.error(f"Error fetching connections for {identifier}: {e}")
            return []

    async def _process_connections_for_queue(self, connections, identifier, depth, priority_queue,
                                             search_processed, processed_terms, all_connections,
                                             max_by_type_depth):
        if not connections:
            return
        depth_limit = max_by_type_depth.get(identifier, {}).get(depth, 10)
        limited_connections = connections[:depth_limit]
        all_connections.extend(limited_connections)
        if depth >= self.cfg.scan.bypass_search_max_depth:
            return
        next_depth = depth + 1
        new_identifiers = []
        banned_identifiers = []
        for conn in limited_connections:
            status = conn.get("status", "")
            if "Banned" in status or "Denied" in status:
                user_name = conn.get("user_name")
                user_id = conn.get("user_id")
                conn_hwid = conn.get("hwid")
                conn_ip = conn.get("ip_address")
                if user_id and user_id != "N/A" and user_id not in search_processed:
                    banned_identifiers.append((1, "user_id", user_id))
                if conn_hwid and conn_hwid != "N/A" and conn_hwid not in search_processed:
                    banned_identifiers.append((2, "hwid", conn_hwid))
                if conn_ip and conn_ip != "N/A" and conn_ip not in search_processed:
                    banned_identifiers.append((3, "ip", conn_ip))
                if user_name and user_name != "N/A" and user_name not in search_processed:
                    banned_identifiers.append((4, "username", user_name))
        for conn in limited_connections:
            user_name = conn.get("user_name")
            user_id = conn.get("user_id")
            conn_hwid = conn.get("hwid")
            conn_ip = conn.get("ip_address")
            if user_id and user_id != "N/A" and user_id not in search_processed:
                new_identifiers.append((1, "user_id", user_id))
            if conn_hwid and conn_hwid != "N/A" and conn_hwid not in search_processed:
                new_identifiers.append((2, "hwid", conn_hwid))
            if conn_ip and conn_ip != "N/A" and conn_ip not in search_processed:
                new_identifiers.append((3, "ip", conn_ip))
            if user_name and user_name != "N/A" and user_name not in search_processed:
                new_identifiers.append((4, "username", user_name))
        for type_priority, id_type, new_id in banned_identifiers:
            async with asyncio.Lock():
                if new_id not in processed_terms:
                    processed_terms.add(new_id)
            if new_id not in search_processed:
                search_processed.add(new_id)
                effective_depth = max(0, next_depth - 0.5)
                heapq.heappush(priority_queue, (effective_depth, type_priority, id_type, new_id))
        for type_priority, id_type, new_id in new_identifiers:
            async with asyncio.Lock():
                if new_id not in processed_terms:
                    processed_terms.add(new_id)
            if new_id not in search_processed:
                search_processed.add(new_id)
                heapq.heappush(priority_queue, (next_depth, type_priority, id_type, new_id))

    def _check_time_based_bypass(self, ban_hit_time: datetime, ip_address: str, banned_user_name: str,
                                 connections: List[Dict]) -> List[str]:
        time_suspected_users = []
        if ip_address == "N/A":
            return time_suspected_users
        try:
            for conn in connections:
                if conn.get("ip_address") == ip_address and conn.get("user_name") != banned_user_name:
                    conn_time = conn.get("time", "")
                    if not conn_time:
                        continue
                    try:
                        conn_dt = datetime.strptime(conn_time, "%Y-%m-%d %H:%M:%S")
                        diff_minutes = (conn_dt - ban_hit_time).total_seconds() / 60.0
                        if diff_minutes >= 5:
                            time_suspected_users.append(conn.get("user_name"))
                    except ValueError:
                        self.logger.warning(f"Invalid time format: {conn_time}")
        except Exception as ex:
            self.logger.error(f"Error processing time difference for ban hit: {str(ex)}", exc_info=True)
        return time_suspected_users
