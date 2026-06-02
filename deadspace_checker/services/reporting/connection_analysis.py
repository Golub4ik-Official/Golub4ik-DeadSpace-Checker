from collections import defaultdict
from typing import Dict, Any, Optional

from deadspace_checker.models.player import Player
from .constants import BOX_CHARS


def find_connection_paths(player: Player, primary_nickname: str) -> Optional[Dict[str, Any]]:
    if not hasattr(player, 'nicknames') or not player.nicknames:
        return None

    all_player_nicks_set = set(player.nicknames)
    if len(all_player_nicks_set) <= 1:
        return None

    associated_hwids = getattr(player, 'associated_hwids', {})
    associated_ips = getattr(player, 'associated_ips', {})

    if not associated_hwids and not associated_ips:
        return None

    primary_hwids_set = {hwid for hwid, nicks in associated_hwids.items() if primary_nickname in nicks}
    primary_ips_set = {ip for ip, nicks in associated_ips.items() if primary_nickname in nicks}

    direct_connections: Dict[str, Dict[str, Any]] = {}

    for hwid_val in primary_hwids_set:
        nicks_on_hwid = associated_hwids.get(hwid_val, [])
        for nick in nicks_on_hwid:
            if nick != primary_nickname and nick in all_player_nicks_set:
                if nick not in direct_connections:
                    direct_connections[nick] = {
                        "type": "HWID", "identifier": hwid_val, "confidence": "High",
                        "path": f"{primary_nickname} {BOX_CHARS.get('ARROW', '→')} (HWID: {hwid_val}) {BOX_CHARS.get('ARROW', '→')} {nick}"
                    }

    for ip_val in primary_ips_set:
        nicks_on_ip = associated_ips.get(ip_val, [])
        for nick in nicks_on_ip:
            if nick != primary_nickname and nick in all_player_nicks_set and nick not in direct_connections:
                direct_connections[nick] = {
                    "type": "IP", "identifier": ip_val, "confidence": "Medium",
                    "path": f"{primary_nickname} {BOX_CHARS.get('ARROW', '→')} (IP: {ip_val}) {BOX_CHARS.get('ARROW', '→')} {nick}"
                }

    indirect_connections: Dict[str, Dict[str, Any]] = {}
    indirect_by_via: Dict[str, Dict[str, list]] = defaultdict(lambda: {"hwid": [], "ip": []})

    directly_connected_alts = set(direct_connections.keys())

    for via_alt_nick in directly_connected_alts:
        for hwid_val, nicks_on_hwid in associated_hwids.items():
            if via_alt_nick in nicks_on_hwid and primary_nickname not in nicks_on_hwid:
                for target_nick in nicks_on_hwid:
                    if target_nick != via_alt_nick and target_nick in all_player_nicks_set and \
                            target_nick != primary_nickname and \
                            target_nick not in direct_connections and target_nick not in indirect_connections:
                        connection_info = {"nick": target_nick, "identifier": hwid_val}
                        indirect_by_via[via_alt_nick]["hwid"].append(connection_info)

                        indirect_connections[target_nick] = {
                            "type": "HWID-Indirect", "identifier": hwid_val, "via": via_alt_nick,
                            "confidence": "Medium",
                            "path": f"{primary_nickname} {BOX_CHARS.get('ARROW', '→')} {via_alt_nick} {BOX_CHARS.get('ARROW', '→')} (HWID: {hwid_val}) {BOX_CHARS.get('ARROW', '→')} {target_nick}"
                        }

        for ip_val, nicks_on_ip in associated_ips.items():
            if via_alt_nick in nicks_on_ip and primary_nickname not in nicks_on_ip:
                for target_nick in nicks_on_ip:
                    if target_nick != via_alt_nick and target_nick in all_player_nicks_set and \
                            target_nick != primary_nickname and \
                            target_nick not in direct_connections and target_nick not in indirect_connections:
                        connection_info = {"nick": target_nick, "identifier": ip_val}
                        indirect_by_via[via_alt_nick]["ip"].append(connection_info)

                        indirect_connections[target_nick] = {
                            "type": "IP-Indirect", "identifier": ip_val, "via": via_alt_nick, "confidence": "Low",
                            "path": f"{primary_nickname} {BOX_CHARS.get('ARROW', '→')} {via_alt_nick} {BOX_CHARS.get('ARROW', '→')} (IP: {ip_val}) {BOX_CHARS.get('ARROW', '→')} {target_nick}"
                        }

    sorted_direct_connections = {k: v for k, v in sorted(direct_connections.items())}
    sorted_indirect_connections = {k: v for k, v in sorted(indirect_connections.items())}

    for via_nick_val in indirect_by_via:
        indirect_by_via[via_nick_val]["hwid"].sort(key=lambda x: x["identifier"])
        indirect_by_via[via_nick_val]["ip"].sort(key=lambda x: x["identifier"])
    sorted_indirect_by_via = {k: v for k, v in sorted(indirect_by_via.items())}

    return {
        "direct_connections": sorted_direct_connections,
        "indirect_connections": sorted_indirect_connections,
        "indirect_by_via": sorted_indirect_by_via,
    }
