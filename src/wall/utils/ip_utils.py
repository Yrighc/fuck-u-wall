import ipaddress

import requests

__all__ = ["get_public_ip"]


def get_public_ip(timeout: float = 3.0) -> str | None:
    """尝试多个公网 IP 服务，返回第一个有效的 IP 字符串，失败返回 None。

    参数:
        timeout: 每次 HTTP 请求的超时时间，单位秒。
    返回:
        公网 IP 字符串 (IPv4 或 IPv6)，或 None 如果无法获取。
    """
    services = [
        "https://api.ipify.org",
        "https://ifconfig.me/ip",
        "https://ipinfo.io/ip",
        "https://icanhazip.com",
    ]

    headers = {"User-Agent": "wall-public-ip-fetcher/1.0"}

    for url in services:
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code != 200:
                continue
            ip_text = resp.text.strip()
            # 有些服务可能返回带换行或 JSON，取第一行并去除空白
            if "\n" in ip_text:
                ip_text = ip_text.splitlines()[0].strip()

            # 验证是否为合法 IP（IPv4 或 IPv6）
            try:
                ipaddress.ip_address(ip_text)
                return ip_text
            except ValueError:
                continue
        except requests.RequestException:
            continue

    return None
