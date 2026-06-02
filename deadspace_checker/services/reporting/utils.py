from typing import Dict, List, Optional, Tuple

from deadspace_checker.models.player import Player


def determine_owner(primary_nickname: str, nicknames: List[str], shared_with: List[str],
                    cache: Optional[Dict] = None) -> str:
    cache = cache if cache is not None else {}
    cache_key = (primary_nickname, tuple(sorted(nicknames)), tuple(sorted(shared_with)))

    if cache_key in cache:
        return cache[cache_key]

    if primary_nickname in shared_with:
        owner = primary_nickname
    else:
        found_nick_owner = next((nick for nick in nicknames if nick in shared_with), None)
        if found_nick_owner:
            owner = found_nick_owner
        elif shared_with:
            owner = shared_with[0]
        else:
            owner = "Unknown"

    cache[cache_key] = owner
    return owner


def analyze_hwids(player: Player, primary_nickname: str) -> Tuple[
    List[Tuple[str, List[str]]], List[Tuple[str, List[str]]], List[Tuple[str, List[str]]]]:
    player_nicknames_set = set(getattr(player, 'nicknames', []))

    owned_hwids: List[Tuple[str, List[str]]] = []
    alt_hwids: List[Tuple[str, List[str]]] = []
    other_hwids: List[Tuple[str, List[str]]] = []

    associated_hwids_data = getattr(player, 'associated_hwids', {})
    for hwid, shared_with_list in associated_hwids_data.items():
        shared_with_set = set(shared_with_list)

        if primary_nickname in shared_with_set:
            owned_hwids.append((hwid, shared_with_list))
        elif player_nicknames_set.intersection(shared_with_set):
            alt_hwids.append((hwid, shared_with_list))
        else:
            other_hwids.append((hwid, shared_with_list))

    owned_hwids.sort(key=lambda x: (-len(x[1]), x[0]))
    alt_hwids.sort(key=lambda x: (-len(x[1]), x[0]))
    other_hwids.sort(key=lambda x: (-len(x[1]), x[0]))

    return owned_hwids, alt_hwids, other_hwids


def analyze_ips(player: Player, primary_nickname: str) -> Tuple[
    List[str], List[Tuple[str, List[str]]], List[Tuple[str, List[str]]], List[Tuple[str, List[str]]]]:
    player_nicknames_set = set(getattr(player, 'nicknames', []))

    original_ips: List[str] = []
    shared_ips: List[Tuple[str, List[str]]] = []
    alt_shared_ips: List[Tuple[str, List[str]]] = []
    multi_user_ips: List[Tuple[str, List[str]]] = []

    associated_ips_data = getattr(player, 'associated_ips', {})
    for ip, shared_with_list in associated_ips_data.items():
        shared_with_set = set(shared_with_list)

        if primary_nickname in shared_with_set:
            if len(shared_with_set) == 1:
                original_ips.append(ip)
            else:
                shared_ips.append((ip, shared_with_list))
        elif player_nicknames_set.intersection(shared_with_set):
            alt_shared_ips.append((ip, shared_with_list))
        elif len(shared_with_set) > 0:
            multi_user_ips.append((ip, shared_with_list))

    original_ips.sort()
    shared_ips.sort(key=lambda x: (-len(x[1]), x[0]))
    alt_shared_ips.sort(key=lambda x: (-len(x[1]), x[0]))
    multi_user_ips.sort(key=lambda x: (-len(x[1]), x[0]))

    return original_ips, shared_ips, alt_shared_ips, multi_user_ips
