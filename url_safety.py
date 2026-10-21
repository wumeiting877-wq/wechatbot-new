# -*- coding: utf-8 -*-
"""URL 抓取 SSRF 拦截。从 bot.py 抽出，便于单测锁住规则。"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


def is_private_or_local_ip(ip_obj) -> bool:
    if ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_unspecified:
        return True
    blocked_networks = (
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("100.64.0.0/10"),
        ipaddress.ip_network("fc00::/7"),
        ipaddress.ip_network("::1/128"),
    )
    return any(ip_obj in network for network in blocked_networks)


def host_is_blocked_for_fetch(host: str, resolver=socket.getaddrinfo) -> bool:
    if not host:
        return True
    hostname = host.strip().lower().rstrip(".")
    if hostname.startswith("[") and hostname.endswith("]"):
        hostname = hostname[1:-1]
    blocked_names = {
        "localhost", "localhost.localdomain", "ip6-localhost",
        "metadata.google.internal", "0.0.0.0", "::1", "::",
    }
    if hostname in blocked_names:
        return True
    if hostname.endswith(".local") or hostname.endswith(".internal"):
        return True
    try:
        return is_private_or_local_ip(ipaddress.ip_address(hostname))
    except ValueError:
        pass
    try:
        addrinfos = resolver(hostname, None)
    except socket.gaierror:
        return True
    for info in addrinfos:
        ip_str = info[4][0]
        try:
            if is_private_or_local_ip(ipaddress.ip_address(ip_str)):
                return True
        except ValueError:
            continue
    return False


def url_is_blocked_for_fetch(url: str, resolver=socket.getaddrinfo) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return True
    return host_is_blocked_for_fetch(parsed.hostname, resolver=resolver)
