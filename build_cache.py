import argparse
import asyncio
import logging
import os
import sys

import discord

from deadspace_checker.config import Config, load_file
from deadspace_checker.services.database_service import DatabaseService
from deadspace_checker.services.discord_service import DiscordService
from deadspace_checker.utils.discord_patch import patch_discord_client


class CacheBuilder:
    def __init__(self, token: str, config: Config):
        self.token = token
        self.config = config
        intents = discord.Intents.default()
        intents.message_content = True
        self.client = discord.Client(intents=intents)
        patch_discord_client(self.client)
        self.db = DatabaseService()
        self.discord_service = DiscordService(self.client)

    async def run(self):
        logging.info("Logging in to Discord...")

        async def on_ready():
            logging.info(f"Logged in as {self.client.user}")
            ch_ids = self.config.discord.complaint_channel_ids
            if not ch_ids:
                logging.error("No complaint_channel_ids in config! Заполните config.py")
                await self.client.close()
                return

            logging.info(f"Настраиваю {len(ch_ids)} каналов жалоб...")
            ok = await self.discord_service.setup_channels(
                self.config.discord.target_channel_id, ch_ids
            )
            if not ok:
                logging.warning("Некоторые каналы не найдены. Продолжаю...")

            empty_channels = {}
            logging.info(f"Скачиваю сообщения (history_limit={self.config.discord.message_history_limit})...")
            logging.info("ЭТО МОЖЕТ ЗАНЯТЬ 10-15 МИНУТ.")
            channels = await self.discord_service.update_complaint_cache(
                empty_channels,
                history_limit=self.config.discord.message_history_limit,
            )

            logging.info("Сохраняю в SQLite...")
            self.db.save_complaint_cache(channels)

            db_path = self.db.db_path
            size_mb = os.path.getsize(db_path) / (1024 * 1024)
            msg_count = sum(len(c.messages) for c in channels.values())
            logging.info(f"Готово! База: {db_path} ({size_mb:.1f} MB, {msg_count} сообщений)")
            await self.client.close()

        self.client.event(on_ready)
        await self.client.start(self.token)


def main():
    parser = argparse.ArgumentParser(description="Build DeadSpace Checker cache DB")
    parser.add_argument("--token", help="Discord user token")
    parser.add_argument("--config", default="deadspace_checker/config/default_config.py", help="Config file path")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )

    cfg = Config()
    if os.path.exists(args.config):
        load_file(args.config, cfg)
        logging.info(f"Config loaded from {args.config}")

    token = args.token or cfg.discord.discord_user_token
    if not token:
        logging.error("Токен не указан. Используйте --token или заполните config.py")
        sys.exit(1)

    logging.info(f"Target: {cfg.discord.target_channel_id or 'не указан'}")
    logging.info(f"Channels: {cfg.discord.complaint_channel_ids or 'не указаны'}")
    logging.info(f"History limit: {cfg.discord.message_history_limit}")
    logging.info(f"Token length: {len(token)}")

    builder = CacheBuilder(token, cfg)
    asyncio.run(builder.run())


if __name__ == "__main__":
    main()
