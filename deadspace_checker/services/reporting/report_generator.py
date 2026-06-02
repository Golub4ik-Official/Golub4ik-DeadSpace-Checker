import json
import os
from collections import defaultdict
from datetime import datetime
from typing import List, Dict, Any, Optional

from deadspace_checker.models.message import ScanResult
from deadspace_checker.models.player import Player
from .report_format import ReportConfig, PLAYER_STATUS
from .utils import determine_owner
from deadspace_checker.utils.logging_utils import get_logger

logger = get_logger(__name__)


class ReportDataGeneratorMixin:

    def write_json_report(self, data: List[Dict[str, Any]], filename: Optional[str] = None) -> bool:
        report_file = filename or os.path.join(self.config.report_output_dir, self.config.report_filename)
        try:
            with open(report_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            logger.info(f"Report saved to '{report_file}' ({len(data)} items)")
            return True
        except IOError as e:
            logger.error(f"Could not write report to '{report_file}': {e}")
            return False

    def _player_to_dict(self, player: Player) -> Dict[str, Any]:
        primary_nickname = getattr(player, 'primary_nickname', None) or \
                           (player.nicknames[0] if hasattr(player, 'nicknames') and player.nicknames else "Unknown")

        enhanced_ips = {}
        if hasattr(player, 'associated_ips'):
            for ip, shared_with in player.associated_ips.items():
                owner = determine_owner(primary_nickname, getattr(player, 'nicknames', []), shared_with, self.cache)
                enhanced_ips[ip] = {
                    "owner": owner, "shared_with": [nick for nick in shared_with if nick != owner], "raw_users": shared_with
                }

        enhanced_hwids = {}
        if hasattr(player, 'associated_hwids'):
            for hwid, shared_with in player.associated_hwids.items():
                owner = determine_owner(primary_nickname, getattr(player, 'nicknames', []), shared_with, self.cache)
                enhanced_hwids[hwid] = {
                    "owner": owner, "shared_with": [nick for nick in shared_with if nick != owner], "raw_users": shared_with
                }
        
        return {
            "initial_account": {
                "user_id": getattr(player, 'user_id', None),
                "nicknames": getattr(player, 'nicknames', []),
                "primary_nickname": primary_nickname,
                "status": getattr(player, 'status', 'unknown'),
                "ban_counts": getattr(player, 'ban_counts', 0),
                "ban_reasons": getattr(player, 'ban_reasons', []),
                "connection_link": getattr(player, 'connection_link', ""),
                "associated_ips": getattr(player, 'associated_ips', {}),
                "associated_hwids": getattr(player, 'associated_hwids', {}),
                "shared_hwid_nicknames": getattr(player, 'shared_hwid_nicknames', [])
            },
            "ip_data": enhanced_ips,
            "hwid_data": enhanced_hwids,
            "raw_ip_nicks": getattr(player, 'associated_ips', {}),
            "raw_hwid_nicks": getattr(player, 'associated_hwids', {}),
            "nicknames": getattr(player, 'nicknames', []),
            "hwid_erased": getattr(player, 'hwid_erased', False),
            "complaint_links": getattr(player, 'complaint_links', []),
            "timestamp": datetime.now().isoformat(),
            "scan_version": "2.1" 
        }

    def generate_message_scan_report(self, scan_results: List[ScanResult]) -> List[Dict[str, Any]]:
        report_data = []
        for result in scan_results:
            message = result.message
            players_data = [self._player_to_dict(player) for player in result.players if player] 

            message_data = {
                "message_id": message.id, "message_link": message.link,
                "author_name": message.author_name, "author_id": message.author_id,
                "scan_time": result.scan_time.isoformat(),
                "results": players_data, "scan_version": "2.1"
            }
            report_data.append(message_data)

            banned_count = sum(1 for p_data in players_data if p_data["initial_account"]["status"] == PLAYER_STATUS['BANNED'])
            suspicious_count = sum(1 for p_data in players_data if p_data["initial_account"]["status"] == PLAYER_STATUS['SUSPICIOUS'])
            logger.info(
                f"Report item: Message {message.id} by {message.author_name}: "
                f"Found {len(players_data)} players ({banned_count} banned, {suspicious_count} suspicious)"
            )
        self.print_message_scan_results(scan_results)
        return report_data

    def generate_nickname_search_report(self, nickname: str, player: Player, gui_mode: bool = False) -> List[Dict[str, Any]]:
        report_data = []
        player_info = {
            "type": "player_info", "nickname": nickname,
            "status": getattr(player, 'status', 'unknown'),
            "ban_counts": getattr(player, 'ban_counts', 0),
            "ban_reasons": getattr(player, 'ban_reasons', []),
            "hwid_erased": getattr(player, 'hwid_erased', False),
            "timestamp": datetime.now().isoformat(), "scan_version": "2.1"
        }
        report_data.append(player_info)

        if hasattr(player, 'ban_reasons') and player.ban_reasons:
            reasons = list(player.ban_reasons)
            reasons.sort(key=lambda b: b.get("date", "") or "", reverse=True)
            reasons.sort(key=lambda b: b.get("username") != nickname)
            report_data.append({"type": "punishments", "reasons": reasons})

        if hasattr(player, 'nicknames') and player.nicknames and len(player.nicknames) > 1:
            report_data.append({"type": "associated_accounts", "nicknames": player.nicknames})
        if hasattr(player, 'denied_logins') and player.denied_logins:
            report_data.append({"type": "denied_login_attempts", "attempts": player.denied_logins})
        if hasattr(player, 'associated_ips') and player.associated_ips:
            report_data.append(self._generate_ip_data(nickname, player))
        if hasattr(player, 'associated_hwids') and player.associated_hwids:
            report_data.append(self._generate_hwid_data(nickname, player))
        if hasattr(player, 'complaint_links') and player.complaint_links:
            report_data.append({"type": "complaints", "links": player.complaint_links})

        self._print_nickname_search_results(nickname, player, gui_mode=gui_mode)
        return report_data

    def _generate_ip_data(self, nickname: str, player: Player) -> Dict[str, Any]:
        ip_data = {"type": "associated_ips", "ips": []}
        denied_logins_by_ip = defaultdict(list)
        if hasattr(player, 'denied_logins'):
            for login in player.denied_logins:
                ip = login.get("ip_address")
                if ip: denied_logins_by_ip[ip].append(login)

        for ip, shared_with in getattr(player, 'associated_ips', {}).items():
            owner = determine_owner(nickname, getattr(player, 'nicknames', []), shared_with, self.cache)
            others = [n for n in shared_with if n != owner]
            ip_entry = {
                "direct_ip_connections": ip, "owner": owner,
                "owned_by_primary": owner == nickname,
                "owned_by_alt": owner in getattr(player, 'nicknames', []) and owner != nickname,
                "shared_with": others, "raw_users": shared_with
            }
            if denied_logins_by_ip.get(ip): ip_entry["denied_logins"] = denied_logins_by_ip[ip]
            ip_data["ips"].append(ip_entry)
        return ip_data

    def _generate_hwid_data(self, nickname: str, player: Player) -> Dict[str, Any]:
        hwid_data = {"type": "associated_hwids", "hwids": []}
        denied_logins_by_hwid = defaultdict(list)
        if hasattr(player, 'denied_logins'):
            for login in player.denied_logins:
                hwid = login.get("hwid")
                if hwid: denied_logins_by_hwid[hwid].append(login)

        for hwid, shared_with in getattr(player, 'associated_hwids', {}).items():
            owner = determine_owner(nickname, getattr(player, 'nicknames', []), shared_with, self.cache)
            others = [n for n in shared_with if n != owner]
            hwid_entry = {
                "hwid": hwid, "owner": owner,
                "owned_by_primary": owner == nickname,
                "owned_by_alt": owner in getattr(player, 'nicknames', []) and owner != nickname,
                "shared_with": others, "raw_users": shared_with
            }
            if denied_logins_by_hwid.get(hwid): hwid_entry["denied_logins"] = denied_logins_by_hwid[hwid]
            hwid_data["hwids"].append(hwid_entry)
        return hwid_data
