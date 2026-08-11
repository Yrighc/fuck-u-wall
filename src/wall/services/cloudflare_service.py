import logging
from typing import Any

import requests

"""
CloudflareService 类：用于管理 Cloudflare 安全规则（WAF Custom Rules）的服务类。

基于 Rulesets API（http_request_firewall_custom phase）：
- 读取 zone 的完整 ruleset，仅替换本工具管理的规则（description 以 wall-auto 开头）
- 用户手动创建的安全规则原样保留，且相对顺序不变
- 全量 PUT 更新，单次请求原子生效
"""


class CloudflareService:
    MANAGED_PREFIX = "wall-auto"

    def __init__(self, api_token: str, zone_id: str, subdomains: list[str]) -> None:
        self.api_token = api_token
        self.zone_id = zone_id
        self.subdomains = subdomains
        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }
        self.base_url = "https://api.cloudflare.com/client/v4"
        self.entrypoint_url = (
            f"{self.base_url}/zones/{self.zone_id}"
            "/rulesets/phases/http_request_firewall_custom/entrypoint"
        )

    def add_ips_to_whitelist(self, ip_list: list[str]) -> tuple[bool, str]:
        """将多个 IP 添加到 Cloudflare 白名单（覆盖本工具的旧规则，保留其他规则）"""
        try:
            # 第一步：读取现有 ruleset（不存在视为空）
            existing_rules, error = self._get_current_rules()
            if error:
                return False, error

            # 第二步：剔除本工具管理的旧规则，保留用户手动创建的规则
            preserved = [r for r in existing_rules if not self._is_managed(r)]

            # 第三步：构建新的白名单 + 黑名单规则，置顶（白名单 skip 必须先于黑名单 block）
            new_rules = self._build_rules(ip_list)

            # 第四步：全量 PUT，原子替换整个 ruleset
            return self._update_ruleset(new_rules + preserved, ip_list)

        except requests.exceptions.RequestException as e:
            return False, f"API_REQUEST_FAILED: {str(e)}"
        except Exception as e:
            return False, f"PROCESS_FAILED: {str(e)}"

    def _is_managed(self, rule: dict[str, Any]) -> bool:
        """判断规则是否由本工具创建（通过 description 前缀识别）"""
        return str(rule.get("description", "")).startswith(self.MANAGED_PREFIX)

    def _get_current_rules(self) -> tuple[list[dict[str, Any]], str | None]:
        """读取当前 ruleset 的规则列表。ruleset 不存在时返回空列表。"""
        response = requests.get(self.entrypoint_url, headers=self.headers, timeout=10)

        # ruleset 尚未创建过：视为空规则列表，后续 PUT 会自动创建
        if response.status_code == 404:
            return [], None

        if not self._check_response(response):
            return [], self._get_error_msg(response, "RULESET_READ_FAILED")

        result = response.json().get("result") or {}
        return result.get("rules", []), None

    def _build_rules(self, ip_list: list[str]) -> list[dict[str, Any]]:
        """构建白名单（skip 剩余规则）+ 黑名单（block 其余 IP）两条规则"""
        hosts = " ".join(f'"{s}"' for s in self.subdomains)
        ips = " ".join(ip_list)
        ips_str = ", ".join(ip_list)
        domains_str = ", ".join(self.subdomains)

        return [
            {
                "description": (
                    f"{self.MANAGED_PREFIX}: whitelist {ips_str} "
                    f"(skip remaining custom rules) for {domains_str}"
                ),
                "expression": f"http.host in {{{hosts}}} and ip.src in {{{ips}}}",
                "action": "skip",
                "action_parameters": {"ruleset": "current"},
            },
            {
                "description": (
                    f"{self.MANAGED_PREFIX}: block all except {ips_str} "
                    f"for {domains_str}"
                ),
                "expression": f"http.host in {{{hosts}}} and not ip.src in {{{ips}}}",
                "action": "block",
            },
        ]

    def _update_ruleset(
        self, rules: list[dict[str, Any]], ip_list: list[str]
    ) -> tuple[bool, str]:
        """全量替换 ruleset 规则（单次 PUT，原子生效）"""
        response = requests.put(
            self.entrypoint_url,
            headers=self.headers,
            json={"rules": rules},
            timeout=15,
        )

        if not self._check_response(response):
            return False, self._get_error_msg(response, "RULESET_UPDATE_FAILED")

        return True, f"OVERRIDE_SUCCESSFUL: {', '.join(ip_list)}"

    def _check_response(self, response: requests.Response) -> bool:
        if response.status_code != 200:
            return False
        data = response.json()
        return bool(data.get("success", False))

    def _get_error_msg(self, response: requests.Response, default_msg: str) -> str:
        try:
            result = response.json()
            errors = result.get("errors", [])
            return str(errors[0].get("message", default_msg)) if errors else default_msg
        except Exception as e:
            logging.error(f"解析 Cloudflare 错误响应失败: {str(e)}")
            return default_msg
