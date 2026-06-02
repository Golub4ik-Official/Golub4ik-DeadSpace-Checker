import hashlib
from collections import defaultdict
from typing import Any, Dict, List

from deadspace_checker.models.message import ScanResult
from deadspace_checker.models.player import Player

STATUS_PRIORITY = {
    'banned': 3,
    'suspicious': 2,
    'clean': 1,
    'unknown': 0,
}


class PlayerMerger:

    @staticmethod
    def consolidate(scan_results: List[ScanResult], logger) -> List[ScanResult]:
        if not scan_results:
            return []
        user_id_groups = {}
        no_user_id_players = []
        for result in scan_results:
            message_id = result.message.id
            for player in result.players:
                if player.user_id and player.user_id != "N/A":
                    if player.user_id not in user_id_groups:
                        user_id_groups[player.user_id] = {"players": [], "messages": set()}
                    user_id_groups[player.user_id]["players"].append(player)
                    user_id_groups[player.user_id]["messages"].add(message_id)
                else:
                    no_user_id_players.append((player, message_id))
        player_registry = {}
        message_to_players = defaultdict(set)
        for user_id, data in user_id_groups.items():
            players = data["players"]
            message_ids = data["messages"]
            merged_player = players[0]
            for i in range(1, len(players)):
                PlayerMerger.merge(merged_player, players[i])
            player_id = f"uid:{user_id}"
            player_registry[player_id] = merged_player
            for message_id in message_ids:
                message_to_players[message_id].add(player_id)
        for player, message_id in no_user_id_players:
            key_parts = []
            primary_nickname = player.primary_nickname if hasattr(player, 'primary_nickname') else (
                player.nicknames[0] if player.nicknames else "")
            if primary_nickname:
                key_parts.append(f"name:{primary_nickname}")
            if hasattr(player, 'associated_hwids') and player.associated_hwids:
                first_hwid = next(iter(player.associated_hwids.keys()), "")
                if first_hwid and first_hwid != "N/A":
                    key_parts.append(f"hwid:{first_hwid}")
            if hasattr(player, 'associated_ips') and player.associated_ips:
                first_ip = next(iter(player.associated_ips.keys()), "")
                if first_ip and first_ip != "N/A":
                    key_parts.append(f"ip:{first_ip}")
            if not key_parts and player.nicknames:
                for nick in player.nicknames:
                    key_parts.append(f"name:{nick}")
            identifier_string = '|'.join(key_parts)
            player_id = hashlib.md5(identifier_string.encode()).hexdigest()
            if player_id not in player_registry:
                player_registry[player_id] = player
            else:
                PlayerMerger.merge(player_registry[player_id], player)
            message_to_players[message_id].add(player_id)
        consolidated_results = []
        processed_messages = set()
        for result in scan_results:
            message_id = result.message.id
            if message_id in processed_messages:
                continue
            processed_messages.add(message_id)
            message_player_ids = message_to_players[message_id]
            consolidated_players = [player_registry[pid] for pid in message_player_ids]
            consolidated_results.append(
                ScanResult(
                    message=result.message,
                    players=consolidated_players,
                    scan_time=result.scan_time
                )
            )
        logger.info(
            f"Consolidated {len(scan_results)} results into {len(consolidated_results)} unique message results"
        )
        return consolidated_results

    @staticmethod
    def merge(target_player: Player, source_player: Player) -> None:
        if not hasattr(target_player, 'nicknames_sources'):
            target_player.nicknames_sources = {}
        if not hasattr(target_player, 'is_from_user_id'):
            target_player.is_from_user_id = False
        if hasattr(source_player, 'is_from_user_id') and source_player.is_from_user_id:
            target_player.is_from_user_id = True
        source_is_primary = hasattr(source_player, 'is_primary') and source_player.is_primary
        target_is_primary = hasattr(target_player, 'is_primary') and target_player.is_primary
        source_primary = source_player.primary_nickname if source_player.nicknames else None
        if source_is_primary and source_primary and source_primary in source_player.nicknames:
            if source_primary not in target_player.nicknames:
                target_player.nicknames.append(source_primary)
            target_player.nicknames.remove(source_primary)
            target_player.nicknames.insert(0, source_primary)
            target_player.nicknames_sources[source_primary] = "login"
            target_player.is_primary = True
            target_player.primary_nickname = source_primary
            if hasattr(source_player, 'search_term'):
                target_player.search_term = source_player.search_term
        source_is_login_event = False
        if hasattr(source_player, 'raw_message') and source_player.raw_message:
            source_is_login_event = "Arrived new player" in source_player.raw_message
            if source_is_login_event and (not hasattr(target_player, 'raw_message') or not target_player.raw_message):
                target_player.raw_message = source_player.raw_message
        for nickname in source_player.nicknames:
            if source_is_primary and source_primary and nickname == source_primary:
                continue
            is_login_event = source_is_login_event
            if hasattr(source_player, 'is_from_user_id') and source_player.is_from_user_id and nickname == source_player.nicknames[0]:
                is_login_event = True
            if is_login_event:
                target_player.nicknames_sources[nickname] = "login"
                if nickname in target_player.nicknames:
                    target_player.nicknames.remove(nickname)
                if target_is_primary and hasattr(target_player, 'primary_nickname'):
                    target_player.nicknames.insert(1, nickname)
                else:
                    target_player.nicknames.insert(0, nickname)
            elif nickname not in target_player.nicknames:
                target_player.nicknames_sources[nickname] = "other"
                target_player.nicknames.append(nickname)
        source_status = source_player.status.lower()
        target_status = target_player.status.lower()
        if STATUS_PRIORITY.get(source_status, 0) > STATUS_PRIORITY.get(target_status, 0):
            target_player.status = source_player.status
        target_player.ban_counts = max(target_player.ban_counts, source_player.ban_counts)
        if hasattr(source_player, 'associated_ips') and hasattr(target_player, 'associated_ips'):
            for ip, nicks in source_player.associated_ips.items():
                if ip in target_player.associated_ips:
                    combined_nicks = set(target_player.associated_ips[ip])
                    combined_nicks.update(nicks)
                    target_player.associated_ips[ip] = list(combined_nicks)
                else:
                    target_player.associated_ips[ip] = nicks
        if hasattr(source_player, 'associated_hwids') and hasattr(target_player, 'associated_hwids'):
            for hwid, nicks in source_player.associated_hwids.items():
                if hwid in target_player.associated_hwids:
                    combined_nicks = set(target_player.associated_hwids[hwid])
                    combined_nicks.update(nicks)
                    target_player.associated_hwids[hwid] = list(combined_nicks)
                else:
                    target_player.associated_hwids[hwid] = nicks
        if hasattr(source_player, 'complaint_links') and source_player.complaint_links:
            if not hasattr(target_player, 'complaint_links'):
                target_player.complaint_links = []
            existing_links = {
                tuple(sorted((k, str(v)) for k, v in link.items()))
                for link in target_player.complaint_links
            } if target_player.complaint_links else set()
            for link in source_player.complaint_links:
                link_tuple = tuple(sorted((k, str(v)) for k, v in link.items()))
                if link_tuple not in existing_links:
                    target_player.complaint_links.append(link)
                    existing_links.add(link_tuple)

        if hasattr(source_player, 'ban_reasons') and source_player.ban_reasons:
            if not hasattr(target_player, 'ban_reasons'):
                target_player.ban_reasons = []

            existing_ban_reasons = set()
            for ban_info in target_player.ban_reasons:
                if isinstance(ban_info, dict) and "reason" in ban_info and "username" in ban_info:
                    existing_ban_reasons.add((ban_info["reason"], ban_info["username"]))
                elif isinstance(ban_info, str):
                    existing_ban_reasons.add((ban_info, "Unknown"))

            for ban_info in source_player.ban_reasons:
                if isinstance(ban_info, dict) and "reason" in ban_info and "username" in ban_info:
                    key = (ban_info["reason"], ban_info["username"])
                    if key not in existing_ban_reasons:
                        target_player.ban_reasons.append(ban_info)
                        existing_ban_reasons.add(key)
                elif isinstance(ban_info, str):
                    key = (ban_info, "Unknown")
                    if key not in existing_ban_reasons:
                        target_player.ban_reasons.append({
                            "reason": ban_info,
                            "username": "Unknown"
                        })
                        existing_ban_reasons.add(key)
