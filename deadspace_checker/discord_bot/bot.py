import asyncio
import logging
import os
from datetime import datetime
from typing import List, Dict, Any

import discord

from deadspace_checker.scanner import PlayerAnalyzer, Scanner
from deadspace_checker.services.admin_service import AdminService
from deadspace_checker.services.cache_service import CacheService
from deadspace_checker.services.database_service import DatabaseService
from deadspace_checker.services.discord_service import DiscordService
from deadspace_checker.services.reporting import ReportService
from deadspace_checker.services.reporting.report_format import ReportConfig
from deadspace_checker.services.reporting.html_renderer import write_report_html, write_ban_bypass_html
from deadspace_checker.utils.discord_patch import patch_discord_client
from deadspace_checker.utils.path_utils import app_dir


class BanCheckerBot:
    def __init__(self, token: str, admin_panel, config: Dict[str, Any], progress_queue=None) -> None:
        self.token = token
        self.config = config
        intents = discord.Intents.default()
        intents.message_content = True
        self.client = discord.Client(intents=intents)
        patch_discord_client(self.client)
        self.db = DatabaseService()
        self.discord_service = DiscordService(self.client)
        self.admin_service = AdminService(admin_panel, self.db)
        app_data = app_dir()
        self.cache_service = CacheService(self.db)
        self.report_service = ReportService(config=ReportConfig(report_output_dir=os.path.join(app_data, "reports")))
        self.player_analyzer = PlayerAnalyzer()
        self.scanner = Scanner(
            self.discord_service,
            self.admin_service,
            self.cache_service,
            self.report_service,
            self.player_analyzer,
            progress_queue=progress_queue
        )
        self.client.event(self.on_ready)

    async def on_ready(self):
        logging.info(f"Logged in as: {self.client.user} (ID: {self.client.user.id})")
        target_channel_id = self.config.get("TARGET_CHANNEL_ID")
        complaint_channel_ids = self.config.get("COMPLAINT_CHANNEL_IDS", [])

        if not await self.scanner.setup(target_channel_id, complaint_channel_ids):
            logging.error("Failed to set up scanner. Exiting.")
            await self.close()
            return

        await self.admin_service.clear_caches()
        self.admin_service.admin_panel._response_cache.clear()

        try:
            report_data: List[Dict[str, Any]] = []

            message_interval_start = self.config.get("message_interval_start")
            message_interval_end = self.config.get("message_interval_end")

            if message_interval_start and message_interval_end:
                logging.info(f"Starting interval scan from {message_interval_start} to {message_interval_end}")
                report_data = await self.scanner.scan_message_interval(
                    message_interval_start,
                    message_interval_end
                )
            elif self.config.get("check_ban_bypass"):
                logging.info("Starting ban bypass check")
                report_data = await self.scanner.scan_ban_bypasses(
                    max_pages=self.config.get("ban_bypass_pages", 5)
                )
            elif self.config.get("username"):
                logging.info(f"Starting nickname scan for: {self.config.get('username')}")
                report_data = await self.scanner.scan_nickname(
                    self.config.get("username")
                )
            if self.config.get("check_ban_bypass"):
                logging.info("Starting ban bypass check")
                report_data = await self.scanner.scan_ban_bypasses(
                    max_pages=self.config.get("ban_bypass_pages", 5)
                )
            else:
                logging.warning("No scan type specified or missing parameters.")

            if report_data:
                self.report_service.write_json_report(report_data)
                logging.info(f"Report with {len(report_data)} items written to file")

            if self.config.get("check_ban_bypass"):
                self._generate_ban_bypass_html_report(report_data if report_data else [])
            else:
                self._generate_graphs(report_data)
        except Exception as e:
            logging.error(f"Error during scan: {e}", exc_info=True)

        logging.info("Scan complete. Disconnecting from Discord.")
        await self.close()

    def _generate_graphs(self, report_data: List[Dict[str, Any]]) -> None:
        if not self.config.get("graph_format"):
            return

        app_data = app_dir()
        reports_dir = os.path.join(app_data, "reports")
        json_path = os.path.join(reports_dir, "scan_report.json")

        if not os.path.exists(json_path):
            return

        self._generate_html_report_with_graph(json_path, reports_dir)

    def _generate_html_report_with_graph(self, json_path: str, reports_dir: str) -> None:
        try:
            import json as _json
            with open(json_path, encoding='utf-8') as f:
                data = _json.load(f)
        except Exception as e:
            logging.error(f"Failed to read JSON report for HTML generation: {e}")
            return

        out_path = self.config.get("graph_output") or os.path.join(reports_dir, "scan_report.html")
        write_report_html(data, out_path)

    async def run_offline(self):
        try:
            auth_cookie = self.config.get("auth_cookie", "")
            if auth_cookie:
                cookie_ok = await self.admin_service.admin_panel.try_auth_with_cookie(auth_cookie)
                if cookie_ok:
                    logging.info("Authenticated via auth cookie, skipping OIDC login")
                    self.admin_service.admin_panel._is_authenticated = True
                else:
                    logging.warning("Auth cookie invalid, falling back to OIDC login")
            if not await self.admin_service.login():
                msg = "❌ Не удалось войти в админ-панель. Сервер авторизации account.spacestation14.com недоступен.\nПроверьте VPN/прокси или сетевое подключение.\n"
                logging.error(msg.strip())
                if self.scanner.progress_queue is not None:
                    self.scanner.progress_queue.put_nowait(msg)
                return
            await self.admin_service.clear_caches()
            self.admin_service.admin_panel._response_cache.clear()
            self.scanner.complaint_channels = self.scanner.cache.load_complaint_cache()
            if self.config.get("check_ban_bypass"):
                logging.info("Starting ban bypass check (offline mode)")
                report_data = await self.scanner.scan_ban_bypasses(
                    max_pages=self.config.get("ban_bypass_pages", 5)
                )
            elif self.config.get("username"):
                logging.info(f"Starting nickname scan for: {self.config.get('username')}")
                report_data = await self.scanner.scan_nickname(self.config.get("username"))
            else:
                report_data = []
            self.report_service.write_json_report(report_data if report_data else [])
            if self.config.get("check_ban_bypass"):
                self._generate_ban_bypass_html_report(report_data if report_data else [])
            elif report_data:
                self._generate_html_report_with_graph(
                    os.path.join(app_dir(), "reports", "scan_report.json"),
                    os.path.join(app_dir(), "reports")
                )
        except Exception as e:
            logging.error(f"Error during offline scan: {e}", exc_info=True)
        finally:
            await self.close()

    def _generate_ban_bypass_html_report(self, report_data):
        out_dir = os.path.join(app_dir(), "reports")
        out_path = self.config.get("graph_output") or os.path.join(out_dir, "ban_bypass_report.html")
        write_ban_bypass_html(report_data, out_path)

    async def close(self):
        if hasattr(self, 'admin_service') and self.admin_service:
            try:
                await self.admin_service.close()
                logging.info("AdminService closed successfully.")
            except Exception as e:
                logging.error(f"Error closing AdminService: {e}", exc_info=True)

        if self.client:
            try:
                await self.client.close()
                logging.info("Discord client closed successfully.")
            except Exception as e:
                logging.error(f"Error closing Discord client: {e}", exc_info=True)

    def run(self):
        self.client.run(self.token)
