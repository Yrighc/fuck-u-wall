import requests


class CloudflareService:
    def __init__(self, api_token, zone_id, subdomains):
        self.api_token = api_token
        self.zone_id = zone_id
        self.subdomains = subdomains
        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }
        self.base_url = "https://api.cloudflare.com/client/v4"

    def add_ips_to_whitelist(self, ip_list):
        """将多个 IP 添加到 Cloudflare 防火墙白名单（支持多个子域名）"""

        # 使用 Firewall Rules API
        rules_url = f"{self.base_url}/zones/{self.zone_id}/firewall/rules"
        filters_url = f"{self.base_url}/zones/{self.zone_id}/filters"

        try:
            # 第一步：删除所有现有的防火墙规则（包括白名单和黑名单）
            self._delete_existing_rules(rules_url, filters_url)

            # 第二步：创建合并的白名单和黑名单规则
            return self._create_new_rules(rules_url, filters_url, ip_list)

        except requests.exceptions.RequestException as e:
            return False, f"请求 Cloudflare API 失败: {str(e)}"
        except Exception as e:
            return False, f"处理失败: {str(e)}"

    def _delete_existing_rules(self, rules_url, filters_url):
        # 获取所有规则（处理分页）
        all_rules = []
        page = 1
        per_page = 100

        while True:
            response = requests.get(
                rules_url,
                headers=self.headers,
                params={"per_page": per_page, "page": page},
                timeout=10,
            )
            if response.status_code != 200:
                break

            data = response.json()
            if not data.get("success"):
                break

            rules = data.get("result", [])
            if not rules:
                break

            all_rules.extend(rules)

            # 检查是否还有更多页面
            result_info = data.get("result_info", {})
            total_pages = result_info.get("total_pages", 1)
            if page >= total_pages:
                break
            page += 1

        # 收集所有规则ID和关联的过滤器ID
        rule_ids = []
        filter_ids = []
        for rule in all_rules:
            rule_id = rule.get("id")
            filter_id = rule.get("filter", {}).get("id")

            if rule_id:
                rule_ids.append(rule_id)
            if filter_id:
                filter_ids.append(filter_id)

        # 删除所有防火墙规则
        if rule_ids:
            for rule_id in rule_ids:
                try:
                    requests.delete(
                        f"{rules_url}/{rule_id}", headers=self.headers, timeout=5
                    )
                except Exception:
                    pass

        # 删除所有关联的过滤器
        if filter_ids:
            unique_filter_ids = list(set(filter_ids))
            for filter_id in unique_filter_ids:
                try:
                    requests.delete(
                        f"{filters_url}/{filter_id}", headers=self.headers, timeout=5
                    )
                except Exception:
                    pass

    def _create_new_rules(self, rules_url, filters_url, ip_list):
        domains_str = ", ".join(self.subdomains)
        ips_str = ", ".join(ip_list)

        try:
            # 2.1 创建合并的白名单规则
            host_conditions = " or ".join(
                [f'http.host eq "{subdomain}"' for subdomain in self.subdomains]
            )
            ip_conditions = " or ".join([f"ip.src eq {ip}" for ip in ip_list])
            whitelist_expression = f"({host_conditions}) and ({ip_conditions})"
            whitelist_notes = (
                f"Auto-added IPs {ips_str} whitelist for all subdomains: {domains_str}"
            )

            # 创建白名单过滤器
            whitelist_filter_payload = {
                "expression": whitelist_expression,
                "description": whitelist_notes,
            }

            whitelist_filter_response = requests.post(
                filters_url,
                headers=self.headers,
                json=[whitelist_filter_payload],
                timeout=10,
            )

            if not self._check_response(whitelist_filter_response):
                return False, self._get_error_msg(
                    whitelist_filter_response, "创建白名单过滤器失败"
                )

            whitelist_filter_result = whitelist_filter_response.json()
            whitelist_filter_id = whitelist_filter_result["result"][0]["id"]

            # 创建白名单防火墙规则
            whitelist_rule_payload = {
                "filter": {"id": whitelist_filter_id},
                "action": "allow",
                "description": whitelist_notes,
            }

            whitelist_rule_response = requests.post(
                rules_url,
                headers=self.headers,
                json=[whitelist_rule_payload],
                timeout=10,
            )

            if not self._check_response(whitelist_rule_response):
                self._safe_delete(filters_url, whitelist_filter_id)
                return False, self._get_error_msg(
                    whitelist_rule_response, "创建白名单规则失败"
                )

            whitelist_rule_result = whitelist_rule_response.json()
            whitelist_rule_id = whitelist_rule_result["result"][0]["id"]

            # 2.2 创建合并的黑名单规则
            not_ip_conditions = " and ".join(
                [f"not (ip.src eq {ip})" for ip in ip_list]
            )
            blacklist_expression = f"({host_conditions}) and ({not_ip_conditions})"
            blacklist_notes = f"Auto-added blacklist for all subdomains (block all IPs except {ips_str}): {domains_str}"

            # 创建黑名单过滤器
            blacklist_filter_payload = {
                "expression": blacklist_expression,
                "description": blacklist_notes,
            }

            blacklist_filter_response = requests.post(
                filters_url,
                headers=self.headers,
                json=[blacklist_filter_payload],
                timeout=10,
            )

            if not self._check_response(blacklist_filter_response):
                self._safe_delete(rules_url, whitelist_rule_id)
                self._safe_delete(filters_url, whitelist_filter_id)
                return False, self._get_error_msg(
                    blacklist_filter_response, "创建黑名单过滤器失败"
                )

            blacklist_filter_result = blacklist_filter_response.json()
            blacklist_filter_id = blacklist_filter_result["result"][0]["id"]

            # 创建黑名单防火墙规则
            blacklist_rule_payload = {
                "filter": {"id": blacklist_filter_id},
                "action": "block",
                "description": blacklist_notes,
            }

            blacklist_rule_response = requests.post(
                rules_url,
                headers=self.headers,
                json=[blacklist_rule_payload],
                timeout=10,
            )

            if not self._check_response(blacklist_rule_response):
                self._safe_delete(rules_url, whitelist_rule_id)
                self._safe_delete(filters_url, whitelist_filter_id)
                self._safe_delete(filters_url, blacklist_filter_id)
                return False, self._get_error_msg(
                    blacklist_rule_response, "创建黑名单规则失败"
                )

            return True, f"成功：{ips_str}"

        except Exception as e:
            return False, f"处理失败: {str(e)}"

    def _check_response(self, response):
        if response.status_code != 200:
            return False
        data = response.json()
        return data.get("success", False)

    def _get_error_msg(self, response, default_msg):
        try:
            result = response.json()
            errors = result.get("errors", [])
            return errors[0].get("message", default_msg) if errors else default_msg
        except:
            return default_msg

    def _safe_delete(self, url, resource_id):
        try:
            requests.delete(f"{url}/{resource_id}", headers=self.headers, timeout=5)
        except:
            pass
