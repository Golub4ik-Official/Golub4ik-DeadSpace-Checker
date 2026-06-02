from datetime import datetime, timezone
import re
from typing import Dict, List, Any, Tuple

from deadspace_checker.models.player import Player
from .constants import BOX_CHARS


def analyze_complaints(player: Player, primary_nickname: str) -> Tuple[
    List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    if not hasattr(player, 'complaint_links') or not player.complaint_links:
        return [], [], [], []

    direct_complaints: List[Dict[str, Any]] = []
    subdirect_hwid_complaints: List[Dict[str, Any]] = []
    subdirect_ip_complaints: List[Dict[str, Any]] = []
    other_associated_complaints: List[Dict[str, Any]] = []

    player_all_nicks_set = set(getattr(player, 'nicknames', [primary_nickname]))
    primary_nickname_lower = primary_nickname.lower()

    nicks_direct_hwid_link_to_primary = set()
    if hasattr(player, 'associated_hwids'):
        for hwid, nicks_on_hwid in player.associated_hwids.items():
            if primary_nickname in nicks_on_hwid:
                nicks_direct_hwid_link_to_primary.update(
                    n.lower() for n in nicks_on_hwid
                    if n != primary_nickname and n in player_all_nicks_set
                )

    nicks_direct_ip_link_to_primary = set()
    if hasattr(player, 'associated_ips'):
        for ip, nicks_on_ip in player.associated_ips.items():
            if primary_nickname in nicks_on_ip:
                nicks_direct_ip_link_to_primary.update(
                    n.lower() for n in nicks_on_ip
                    if n != primary_nickname and n in player_all_nicks_set
                )

    other_player_alts_lower = {
        n.lower() for n in player_all_nicks_set
        if n.lower() != primary_nickname_lower
           and n.lower() not in nicks_direct_hwid_link_to_primary
           and n.lower() not in nicks_direct_ip_link_to_primary
    }

    for complaint_data in player.complaint_links:
        raw_mentioned_nicks = complaint_data.get("mentioned_nicknames", [])
        if not isinstance(raw_mentioned_nicks, list): raw_mentioned_nicks = []

        mentioned_nicks_in_complaint_lower = {
            str(n).lower() for n in raw_mentioned_nicks if isinstance(n, (str, int))
        }

        content_lower = str(complaint_data.get("content", "")).lower()

        categorized_this_complaint = False

        if primary_nickname_lower in mentioned_nicks_in_complaint_lower or \
                (content_lower and primary_nickname_lower in content_lower):
            direct_complaints.append(complaint_data)
            categorized_this_complaint = True
            continue

        for hwid_alt_lower in nicks_direct_hwid_link_to_primary:
            if hwid_alt_lower in mentioned_nicks_in_complaint_lower or \
                    (content_lower and hwid_alt_lower in content_lower):
                subdirect_hwid_complaints.append(complaint_data)
                categorized_this_complaint = True
                break
        if categorized_this_complaint: continue

        for ip_alt_lower in nicks_direct_ip_link_to_primary:
            if ip_alt_lower in mentioned_nicks_in_complaint_lower or \
                    (content_lower and ip_alt_lower in content_lower):
                subdirect_ip_complaints.append(complaint_data)
                categorized_this_complaint = True
                break
        if categorized_this_complaint: continue

        for other_alt_lower in other_player_alts_lower:
            if other_alt_lower in mentioned_nicks_in_complaint_lower or \
                    (content_lower and other_alt_lower in content_lower):
                other_associated_complaints.append(complaint_data)
                break

    def sort_key(c: Dict[str, Any]) -> Tuple[datetime, str]:
        primary_sort_dt: datetime = datetime.min.replace(tzinfo=timezone.utc)
        link_str = c.get('link', '')

        content = c.get('content', '')

        match_ddmmyyyy = re.search(r"(?:Выдан|Выдано):\s*(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}:\d{2})", content,
                                   re.IGNORECASE)
        if match_ddmmyyyy:
            try:
                dt_obj_naive = datetime.strptime(match_ddmmyyyy.group(1), "%d.%m.%Y %H:%M:%S")
                primary_sort_dt = dt_obj_naive.replace(tzinfo=timezone.utc)
                return (primary_sort_dt, link_str)
            except ValueError:
                pass

        match_unix_t = re.search(r"<t:(\d+):R>", content)
        if match_unix_t:
            try:
                epoch_seconds = int(match_unix_t.group(1))
                primary_sort_dt = datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)
                return (primary_sort_dt, link_str)
            except ValueError:
                pass

        msg_id_ts_snowflake = c.get('message_id_as_timestamp')
        if isinstance(msg_id_ts_snowflake, int):
            try:
                DISCORD_EPOCH = 1420070400000
                timestamp_ms = (msg_id_ts_snowflake >> 22) + DISCORD_EPOCH
                primary_sort_dt = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)
                return (primary_sort_dt, link_str)
            except Exception:
                pass

        time_str = c.get('time')
        if time_str:
            try:
                dt_obj_naive = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                primary_sort_dt = dt_obj_naive.replace(tzinfo=timezone.utc)
                return (primary_sort_dt, link_str)
            except ValueError:
                pass

        return (primary_sort_dt, link_str)

    direct_complaints.sort(key=sort_key, reverse=True)
    subdirect_hwid_complaints.sort(key=sort_key, reverse=True)
    subdirect_ip_complaints.sort(key=sort_key, reverse=True)
    other_associated_complaints.sort(key=sort_key, reverse=True)

    return direct_complaints, subdirect_hwid_complaints, subdirect_ip_complaints, other_associated_complaints
