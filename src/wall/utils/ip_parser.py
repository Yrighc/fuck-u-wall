#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
IP 解析工具：支持用户直接输入一个/多个 IP，或从粘贴的整段文本中提取 IP。

设计目标：
- 先判断输入本身是否为“一个/多个合法 IP”（支持逗号/空格/换行等分隔）
- 如果不是，再按正则从文本中提取 IPv4/IPv6，并用 ipaddress 二次校验
"""

from __future__ import annotations

import ipaddress
import re


def _is_valid_ip(ip_text: str) -> bool:
    """判断字符串是否是合法的 IPv4/IPv6。"""
    try:
        ipaddress.ip_address(ip_text)
        return True
    except ValueError:
        return False


def _split_possible_ips(user_text: str) -> list[str]:
    """
    将用户输入按常见分隔符切成 token。
    - 兼容逗号、空格、换行、分号、中文逗号等
    """
    if not user_text:
        return []
    tokens = re.split(r"[\s,;，；]+", user_text.strip())
    return [t for t in (tok.strip() for tok in tokens) if t]


def _extract_ips_by_regex(user_text: str) -> list[str]:
    """
    从一段文本中用正则提取 IPv4/IPv6，然后用 ipaddress 二次校验。
    说明：
    - IPv4 采用严格段范围（0-255）的正则
    - IPv6 先抓取“看起来像 IPv6 的片段”，再交给 ipaddress 做最终合法性判断
    """
    if not user_text:
        return []

    ipv4_re = re.compile(
        r"\b(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}\b"
    )
    # IPv6 候选：尽量覆盖常见压缩/非压缩形式（最终以 ipaddress 校验为准）
    ipv6_candidate_re = re.compile(
        r"(?i)(?<![0-9a-f:])(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}(?![0-9a-f:])"
    )

    candidates: list[str] = []
    candidates.extend(ipv4_re.findall(user_text))
    candidates.extend(ipv6_candidate_re.findall(user_text))

    # 去重但保留顺序
    seen: set[str] = set()
    result: list[str] = []
    for c in candidates:
        c = c.strip()
        if not c or c in seen:
            continue
        if _is_valid_ip(c):
            seen.add(c)
            result.append(c)
    return result


def parse_ips_from_user_input(user_text: str) -> list[str]:
    """
    用户输入 IP 解析策略：
    - 如果输入本身已经是一个/多个合法 IP（可用逗号/空格/换行分隔），直接返回
    - 否则，从整段文本中按正则提取出 IP（IPv4/IPv6），用于后续加白
    """
    tokens = _split_possible_ips(user_text)
    if tokens and all(_is_valid_ip(t) for t in tokens):
        # 去重但保留顺序
        seen: set[str] = set()
        out: list[str] = []
        for t in tokens:
            if t not in seen:
                seen.add(t)
                out.append(t)
        return out

    return _extract_ips_by_regex(user_text)

