from __future__ import annotations

import logging
import os
import time
from urllib.parse import urlparse

import aiohttp

log = logging.getLogger("nexus")

URLHAUS_AUTH_KEY = os.getenv("URLHAUS_AUTH_KEY", "").strip()
URLHAUS_RECENT_URL = "https://urlhaus-api.abuse.ch/v1/urls/recent/"

urlhaus_hosts: set[str] = set()
urlhaus_urls: set[str] = set()
urlhaus_last_update: float = 0.0


async def update_urlhaus() -> None:
    global urlhaus_hosts, urlhaus_urls, urlhaus_last_update
    if not URLHAUS_AUTH_KEY:
        return
    try:
        async with aiohttp.ClientSession() as session:
            headers = {"Auth-Key": URLHAUS_AUTH_KEY}
            async with session.get(URLHAUS_RECENT_URL, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    log.warning("URLhaus recent fetch failed: %s", resp.status)
                    return
                data = await resp.json()
        if data.get("query_status") != "ok":
            log.warning("URLhaus query_status: %s", data.get("query_status"))
            return
        hosts, urls = set(), set()
        for item in data.get("urls", []):
            url = (item.get("url") or "").strip().lower()
            host = (item.get("host") or "").strip().lower()
            if url:
                urls.add(url)
                urls.add(url.rstrip("/"))
            if host:
                hosts.add(host)
        urlhaus_hosts = hosts
        urlhaus_urls = urls
        urlhaus_last_update = time.time()
        log.info("URLhaus updated: %s hosts, %s urls", len(hosts), len(urls))
    except Exception:
        log.exception("URLhaus update failed")


def is_urlhaus_malicious(raw_url: str) -> bool:
    if not urlhaus_hosts and not urlhaus_urls:
        return False
    normalized = raw_url.strip().lower().rstrip(".,!?)]}>")
    candidate = normalized if "://" in normalized else "https://" + normalized
    if candidate in urlhaus_urls or candidate.rstrip("/") in urlhaus_urls:
        return True
    try:
        host = (urlparse(candidate).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    if not host:
        return False
    if host in urlhaus_hosts:
        return True
    parts = host.split(".")
    for i in range(1, len(parts) - 1):
        if ".".join(parts[i:]) in urlhaus_hosts:
            return True
    return False
