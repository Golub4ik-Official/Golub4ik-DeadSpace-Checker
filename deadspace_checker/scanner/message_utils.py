import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from deadspace_checker.models.message import ScanResult
from deadspace_checker.models.player import Player
from deadspace_checker.scanner.player_merge import PlayerMerger
from deadspace_checker.utils.url_utils import extract_effective_search_term


def extract_message_data(messages):
    all_terms = set()
    message_terms = {}
    term_is_login_event = {}
    user_id_terms = {}
    message_nicknames = {}
    term_to_message_id = {}
    for message in messages:
        if 'Arrived new player' not in message.embed_titles:
            continue
        nickname = None
        candidate_nicknames = []
        for key, url in message.embed_links.items():
            if key.startswith('search:'):
                term = key[7:]
                if re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', term, re.I):
                    continue
                elif re.match(r'^(\d{1,3}\.){3}\d{1,3}$', term):
                    continue
                elif term.startswith('V2-'):
                    continue
                else:
                    candidate_nicknames.append(term)
        if candidate_nicknames:
            nickname = candidate_nicknames[0]
            message_nicknames[message.id] = nickname
        if not nickname and hasattr(message, 'embeds'):
            for embed in message.embeds:
                if embed.title == 'Arrived new player':
                    for field in embed.fields:
                        if field.name.lower() == 'name':
                            nickname = field.value.strip()
                            message_nicknames[message.id] = nickname
                            break
        unique_terms = {
            extract_effective_search_term(url)
            for url in message.embed_links.values()
            if extract_effective_search_term(url)
        }
        if not unique_terms:
            continue
        message_terms[message.id] = unique_terms
        all_terms.update(unique_terms)
        for term in unique_terms:
            term_is_login_event[term] = True
            term_to_message_id[term] = message.id
        for url in message.embed_links.values():
            term = extract_effective_search_term(url)
            if term and re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', term, re.I):
                user_id_terms[message.id] = term
                break
    return {
        'all_terms': all_terms,
        'message_terms': message_terms,
        'term_is_login_event': term_is_login_event,
        'user_id_terms': user_id_terms,
        'message_nicknames': message_nicknames,
        'term_to_message_id': term_to_message_id
    }


async def create_scan_results(messages, message_data, term_to_player,
                               discord, complaint_channels, scanner_analyzer):
    scan_results = []
    for message in messages:
        if message.id not in message_data['message_terms']:
            continue
        message_terms = message_data['message_terms'][message.id]
        players = [term_to_player[term] for term in message_terms if term in term_to_player]
        if not players:
            continue
        message_nickname = message_data.get('message_nicknames', {}).get(message.id)
        user_id_term = message_data['user_id_terms'].get(message.id)
        user_id_player = term_to_player.get(user_id_term) if user_id_term else None
        _annotate_players_with_login_info(players, user_id_player, message, message_nickname)
        grouped_players = scanner_analyzer.group_players_by_nicknames(players)
        all_nicknames = {nickname for player in grouped_players for nickname in player.nicknames}
        complaint_links = await discord.find_nickname_mentions(
            list(all_nicknames), complaint_channels
        )
        for player in grouped_players:
            player.complaint_links = [
                link for link in complaint_links
                if any(nickname in link.get('content', '') for nickname in player.nicknames)
            ]
        scan_results.append(
            ScanResult(message=message, players=grouped_players, scan_time=datetime.now())
        )
    return scan_results


def _annotate_players_with_login_info(players, user_id_player, message, message_nickname=None):
    for player in players:
        if message.embed_titles and 'Arrived new player' in message.embed_titles:
            player.raw_message = "Arrived new player"
            if not hasattr(player, 'nicknames_sources'):
                player.nicknames_sources = {}
            if message_nickname and message_nickname in player.nicknames:
                player.is_primary = True
                player.nicknames.remove(message_nickname)
                player.nicknames.insert(0, message_nickname)
                player.nicknames_sources[message_nickname] = "login"
                player.primary_nickname = message_nickname
            elif user_id_player and player is user_id_player and player.nicknames:
                player.is_primary = True
                primary_nick = player.nicknames[0]
                player.nicknames_sources[primary_nick] = "login"
                player.primary_nickname = primary_nick
            elif player.nicknames:
                player.is_primary = False
                primary_nick = player.nicknames[0]
                player.nicknames_sources[primary_nick] = "login"
