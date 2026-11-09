"""ホスト単位でアクセス間隔を空ける丁寧な HTTP クライアント。"""
from __future__ import annotations

import os
import random
import threading
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

DEFAULT_INTERVAL_SEC = float(os.environ.get("SCRAPE_INTERVAL_SEC", "8"))
DEFAULT_JITTER_SEC = float(os.environ.get("SCRAPE_JITTER_SEC", "2"))
USER_AGENT = os.environ.get(
    "SCRAPE_USER_AGENT",
    "nisa-dashboard/1.0 (+personal research; respectful crawl; contact: local-only)",
)


class PoliteSession:
    """同一ホストへの連続アクセスを間隔制御する。並列利用は想定しない。"""

    def __init__(
        self,
        interval_sec: float = DEFAULT_INTERVAL_SEC,
        jitter_sec: float = DEFAULT_JITTER_SEC,
        respect_robots: bool = True,
    ) -> None:
        self.interval_sec = max(interval_sec, 3.0)
        self.jitter_sec = max(jitter_sec, 0.0)
        self.respect_robots = respect_robots
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept-Language": "ja,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )
        self._last_access: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}
        self._lock = threading.Lock()

    def _host(self, url: str) -> str:
        return urlparse(url).netloc.lower()

    def _wait(self, host: str) -> None:
        with self._lock:
            last = self._last_access.get(host, 0.0)
            elapsed = time.monotonic() - last
            wait = self.interval_sec + random.uniform(0, self.jitter_sec) - elapsed
            if wait > 0:
                print(f"WAIT {host}: {wait:.1f}s")
                time.sleep(wait)
            self._last_access[host] = time.monotonic()

    def _allowed_by_robots(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if host not in self._robots:
            rp = RobotFileParser()
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
            try:
                # robots.txt 自体も間隔を空ける
                self._wait(host)
                res = self._session.get(robots_url, timeout=15)
                if res.status_code >= 400:
                    self._robots[host] = None
                else:
                    rp.parse(res.text.splitlines())
                    self._robots[host] = rp
            except Exception as exc:  # noqa: BLE001
                print(f"WARN robots.txt {host}: {exc}")
                self._robots[host] = None
        rp = self._robots.get(host)
        if rp is None:
            return True
        try:
            return rp.can_fetch(USER_AGENT, url)
        except Exception:  # noqa: BLE001
            return True

    def get(self, url: str, *, timeout: int = 30, **kwargs) -> requests.Response:
        host = self._host(url)
        if not self._allowed_by_robots(url):
            raise PermissionError(f"robots.txt disallows: {url}")
        self._wait(host)
        res = self._session.get(url, timeout=timeout, **kwargs)
        # 429 / 503 のときは長めに待って1回だけ再試行
        if res.status_code in (429, 503):
            backoff = self.interval_sec * 3 + random.uniform(2, 6)
            print(f"BACKOFF {host} status={res.status_code}: sleep {backoff:.1f}s")
            time.sleep(backoff)
            self._wait(host)
            res = self._session.get(url, timeout=timeout, **kwargs)
        res.raise_for_status()
        return res


# プロセス内共有（取得スクリプト間で間隔を共有したい場合に使う）
_SHARED: PoliteSession | None = None


def shared_session() -> PoliteSession:
    global _SHARED
    if _SHARED is None:
        _SHARED = PoliteSession()
    return _SHARED
