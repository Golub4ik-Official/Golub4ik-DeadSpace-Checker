from dataclasses import dataclass
from typing import Dict, Any, Optional


N_A = "N/A"
AUTH_COOKIE_NAME = "AspNetCore.Cookies"


@dataclass
class ConnectionData:
    user_name: str
    user_id: str
    time: str
    ip_address: str
    hwid: str
    status: str
    server: str
    trust_score: str
    ban_hits_link: Optional[str] = None
    connection_id: Optional[str] = None
    is_denied_banned: bool = False

    def get(self, key: str, default=None):
        return getattr(self, key, default)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_name": self.user_name,
            "user_id": self.user_id,
            "time": self.time,
            "ip_address": self.ip_address,
            "hwid": self.hwid,
            "status": self.status,
            "server": self.server,
            "trust_score": self.trust_score,
            "ban_hits_link": self.ban_hits_link,
            "connection_id": self.connection_id,
            "is_denied_banned": self.is_denied_banned
        }
