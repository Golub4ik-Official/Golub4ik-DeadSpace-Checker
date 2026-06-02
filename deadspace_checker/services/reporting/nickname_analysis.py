from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Any

from deadspace_checker.models.player import Player
from .constants import TIME_ANALYSIS_THRESHOLDS, ANALYSIS_CONFIG


def categorize_associated_nicknames(player: Player, primary_nickname: str) -> Dict[str, Any]:
    categories: Dict[str, Any] = {
        "confirmed_alts": {
            "accounts": set(),
            "direct_hwid": defaultdict(list),
        },
        "alt_to_alt": {
            "hwid_map": defaultdict(set),
        },
        "likely_connections": [],
        "possible_connections": {
            "ip": defaultdict(int),
            "login": set(),
        },
        "other": set(),
        "time_based": {"recent": set(), "historical": set()}
    }

    categorized_nicks_master_set = {primary_nickname}
    player_all_nicks_set = set(getattr(player, 'nicknames', []))

    for hwid, nicks_on_hwid in player.associated_hwids.items():
        if primary_nickname in nicks_on_hwid:
            alts_on_this_hwid = {n for n in nicks_on_hwid if n != primary_nickname and n in player_all_nicks_set}
            if alts_on_this_hwid:
                categories["confirmed_alts"]["accounts"].update(alts_on_this_hwid)
                categories["confirmed_alts"]["direct_hwid"][hwid].extend(list(alts_on_this_hwid))
                categorized_nicks_master_set.update(alts_on_this_hwid)

    player_known_alts_excluding_primary = player_all_nicks_set - {primary_nickname}
    for hwid, nicks_on_hwid in player.associated_hwids.items():
        if primary_nickname not in nicks_on_hwid:
            alts_on_this_hwid_for_alt_to_alt = set(nicks_on_hwid) & player_known_alts_excluding_primary
            if len(alts_on_this_hwid_for_alt_to_alt) >= 2:
                categories["alt_to_alt"]["hwid_map"][hwid].update(alts_on_this_hwid_for_alt_to_alt)
                categorized_nicks_master_set.update(alts_on_this_hwid_for_alt_to_alt)

    account_connection_strength: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"strength": 0.0, "id_details": {"hwid": 0, "ip": 0}}
    )

    confirmed_alts_of_primary_set = categories["confirmed_alts"]["accounts"]
    for hwid, nicks_on_hwid in player.associated_hwids.items():

        shared_confirmed_alts_on_hwid = set(nicks_on_hwid) & confirmed_alts_of_primary_set

        if not shared_confirmed_alts_on_hwid or primary_nickname in nicks_on_hwid:
            continue

        for nick in nicks_on_hwid:
            if nick != primary_nickname and \
                    nick not in confirmed_alts_of_primary_set and \
                    nick not in categorized_nicks_master_set and \
                    nick in player_all_nicks_set:

                account_connection_strength[nick]["id_details"]["hwid"] += 1
                if len(shared_confirmed_alts_on_hwid) > 1:
                    account_connection_strength[nick]["strength"] += ANALYSIS_CONFIG['DIRECT_CONNECTION_STRENGTH']
                else:
                    account_connection_strength[nick]["strength"] += ANALYSIS_CONFIG['SINGLE_CONNECTION_STRENGTH']

    for ip, nicks_on_ip in player.associated_ips.items():
        shared_confirmed_alts_on_ip = set(nicks_on_ip) & confirmed_alts_of_primary_set
        if not shared_confirmed_alts_on_ip or primary_nickname in nicks_on_ip:
            continue

        for nick in nicks_on_ip:
            if nick != primary_nickname and \
                    nick not in confirmed_alts_of_primary_set and \
                    nick not in categorized_nicks_master_set and \
                    nick in player_all_nicks_set:
                account_connection_strength[nick]["id_details"]["ip"] += 1
                account_connection_strength[nick]["strength"] += ANALYSIS_CONFIG['IP_CONNECTION_STRENGTH']

    for nick, data in account_connection_strength.items():
        categories["likely_connections"].append({
            "nickname": nick,
            "strength_str": "Strong" if data["strength"] >= ANALYSIS_CONFIG[
                'STRONG_CONNECTION_THRESHOLD'] else "Moderate",
            "strength_value": data["strength"],
            "id_details": data["id_details"]
        })
        categorized_nicks_master_set.add(nick)

    categories["likely_connections"].sort(key=lambda x: (x["strength_value"], sum(x["id_details"].values())),
                                          reverse=True)

    possible_ip_shared_counts = defaultdict(int)
    nicks_to_add_to_master_after_ip_scan = set()

    for ip_address, nicks_on_this_ip_list in player.associated_ips.items():
        if primary_nickname in nicks_on_this_ip_list:
            for other_nick_on_ip in nicks_on_this_ip_list:
                if other_nick_on_ip != primary_nickname and \
                        other_nick_on_ip in player_all_nicks_set and \
                        other_nick_on_ip not in categorized_nicks_master_set:
                    possible_ip_shared_counts[other_nick_on_ip] += 1
                    nicks_to_add_to_master_after_ip_scan.add(other_nick_on_ip)

    for nick, count in possible_ip_shared_counts.items():
        if count > 0:
            categories["possible_connections"]["ip"][nick] = count

    categorized_nicks_master_set.update(nicks_to_add_to_master_after_ip_scan)

    if hasattr(player, 'nicknames_sources'):
        for nick, source_info in player.nicknames_sources.items():
            source_type = source_info.get('type') if isinstance(source_info, dict) else source_info
            if source_type == "login" and \
                    nick != primary_nickname and \
                    nick not in categorized_nicks_master_set and \
                    nick in player_all_nicks_set:
                categories["possible_connections"]["login"].add(nick)
                categorized_nicks_master_set.add(nick)

    if hasattr(player, 'denied_logins') and player.denied_logins:
        now = datetime.now()
        recent_threshold_dt = now - timedelta(days=TIME_ANALYSIS_THRESHOLDS['RECENT_LOGIN_DAYS'])
        historical_threshold_dt = now - timedelta(days=TIME_ANALYSIS_THRESHOLDS['HISTORICAL_LOGIN_DAYS'])

        for login_attempt in player.denied_logins:
            user_name = login_attempt.get('user_name', '')
            if not user_name or user_name == primary_nickname or \
                    user_name not in player_all_nicks_set or \
                    user_name in categorized_nicks_master_set:
                continue

            try:
                login_time_str = login_attempt.get('time')
                if login_time_str:
                    login_time_dt = datetime.strptime(login_time_str, "%Y-%m-%d %H:%M:%S")

                    added_to_time_category = False
                    if login_time_dt > recent_threshold_dt:
                        categories["time_based"]["recent"].add(user_name)
                        added_to_time_category = True
                    elif login_time_dt > historical_threshold_dt:
                        categories["time_based"]["historical"].add(user_name)
                        added_to_time_category = True

                    if added_to_time_category:
                        categorized_nicks_master_set.add(user_name)
            except ValueError:
                pass

    categories["other"] = player_all_nicks_set - categorized_nicks_master_set

    categories["confirmed_alts"]["accounts"] = sorted(list(categories["confirmed_alts"]["accounts"]))
    for hwid_val in categories["confirmed_alts"]["direct_hwid"]:
        categories["confirmed_alts"]["direct_hwid"][hwid_val] = sorted(
            list(set(categories["confirmed_alts"]["direct_hwid"][hwid_val])))

    hwid_map_sorted = {}
    for hwid_val, alts_set in categories["alt_to_alt"]["hwid_map"].items():
        hwid_map_sorted[hwid_val] = sorted(list(alts_set))
    categories["alt_to_alt"]["hwid_map"] = {k: v for k, v in sorted(hwid_map_sorted.items())}

    categories["possible_connections"]["ip"] = {k: v for k, v in
                                                sorted(categories["possible_connections"]["ip"].items(),
                                                       key=lambda item: item[1], reverse=True)}
    categories["possible_connections"]["login"] = sorted(list(categories["possible_connections"]["login"]))

    categories["time_based"]["recent"] = sorted(list(categories["time_based"]["recent"]))
    categories["time_based"]["historical"] = sorted(list(categories["time_based"]["historical"]))
    categories["other"] = sorted(list(categories["other"]))

    return categories
