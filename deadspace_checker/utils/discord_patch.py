import asyncio
import logging
import types

import aiohttp
import discord


SESSION_ATTR = '_HTTPClient__session'


class SelfbotRequest:
    def __init__(self, original_fn, method, url, kwargs):
        self._original_fn = original_fn
        self._method = method
        self._url = url
        self._kwargs = dict(kwargs)
        self._cm = None

    def _patch_headers(self):
        headers = self._kwargs.get('headers', {})
        auth = headers.get('Authorization', '')
        if auth.startswith('Bot '):
            headers['Authorization'] = auth[4:]
        self._kwargs['headers'] = headers

    def _get_cm(self):
        if self._cm is None:
            self._patch_headers()
            self._cm = self._original_fn(self._method, self._url, **self._kwargs)
        return self._cm

    def __await__(self):
        return self._get_cm().__await__()

    async def __aenter__(self):
        return await self._get_cm().__aenter__()

    async def __aexit__(self, *args):
        return await self._get_cm().__aexit__(*args)


def patch_static_login(http):
    async def patched_static_login(self_http, token):
        if self_http.connector is discord.http.MISSING:
            self_http.connector = aiohttp.TCPConnector(limit=0)

        session = aiohttp.ClientSession(
            connector=self_http.connector,
            ws_response_class=discord.http.DiscordClientWebSocketResponse,
            trace_configs=None if self_http.http_trace is None else [self_http.http_trace],
        )
        setattr(self_http, SESSION_ATTR, session)
        self_http._global_over = asyncio.Event()
        self_http._global_over.set()

        original_session_req = session.request

        def selfbot_request(method, url, **kwargs):
            return SelfbotRequest(original_session_req, method, url, kwargs)

        session.request = selfbot_request

        old_token = self_http.token
        self_http.token = token

        try:
            data = await self_http.request(discord.http.Route('GET', '/users/@me'))
        except discord.HTTPException as exc:
            self_http.token = old_token
            if exc.status == 401:
                raise discord.LoginFailure('Improper token has been passed.') from exc
            raise

        return data

    http.static_login = types.MethodType(patched_static_login, http)


def patch_client_login(client):
    _loop = discord.client._loop

    async def patched_login(self_client, token):
        logging.info('logging in using static token (selfbot mode)')

        if self_client.loop is _loop:
            loop = asyncio.get_running_loop()
            self_client.loop = loop
            self_client.http.loop = loop
            self_client._connection.loop = loop
            self_client._ready = asyncio.Event()

        if not isinstance(token, str):
            raise TypeError(f'expected token to be a str, received {token.__class__.__name__} instead')
        token = token.strip()

        data = await self_client.http.static_login(token)
        self_client._connection.user = discord.user.ClientUser(state=self_client._connection, data=data)

        mock_app = types.SimpleNamespace(id=0, flags=discord.ApplicationFlags._from_value(0))
        self_client._application = mock_app
        if self_client._connection.application_id is None:
            self_client._connection.application_id = mock_app.id
        if not self_client._connection.application_flags:
            self_client._connection.application_flags = mock_app.flags

        await self_client.setup_hook()

    client.login = types.MethodType(patched_login, client)


def patch_sticker_format():
    import discord.sticker
    original = discord.sticker.Sticker._from_data

    def patched_from_data(self, data):
        try:
            return original(self, data)
        except KeyError:
            self.id = int(data['id'])
            self.name = data['name']
            self.description = data['description']
            self.format = f'unknown_{data.get("format_type", 0)}'
            self.url = f'{discord.Asset.BASE}/stickers/{self.id}.png'

    discord.sticker.Sticker._from_data = patched_from_data


def patch_discord_client(client):
    patch_static_login(client.http)
    patch_client_login(client)
    patch_sticker_format()
