"""CloudflareService（Rulesets API）单元测试：全部 mock，不触网"""
import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from wall.services.cloudflare_service import CloudflareService

ZONE = "zone123"
SUBDOMAINS = ["api.example.com", "admin.example.com"]
IPS = ["203.0.113.10", "203.0.113.11"]

USER_RULE: dict[str, Any] = {
    "id": "user-rule-1",
    "description": "Unused filter",
    "action": "block",
    "enabled": False,
    "expression": 'http.host eq "example.com"',
}

OLD_MANAGED_RULE: dict[str, Any] = {
    "id": "old-managed-1",
    "description": "wall-auto: block all except 1.1.1.1 for api.example.com",
    "action": "block",
    "expression": 'http.host in {"api.example.com"} and not ip.src in {1.1.1.1}',
}


def _make_service() -> CloudflareService:
    return CloudflareService(api_token="t", zone_id=ZONE, subdomains=SUBDOMAINS)


def _mock_response(payload: dict[str, Any], status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    return resp


def _get_payload(rules: list[dict[str, Any]]) -> dict[str, Any]:
    return {"success": True, "result": {"id": "rs1", "rules": rules}}


def test_preserves_user_rules_and_replaces_managed() -> None:
    """用户手动规则必须保留，旧的 wall-auto 规则被替换"""
    service = _make_service()
    with patch("wall.services.cloudflare_service.requests") as mock_req:
        mock_req.get.return_value = _mock_response(_get_payload([OLD_MANAGED_RULE, USER_RULE]))
        mock_req.put.return_value = _mock_response({"success": True, "result": {}})

        success, message = service.add_ips_to_whitelist(IPS)

        assert success, message
        put_rules = mock_req.put.call_args.kwargs["json"]["rules"]
        # 2 条新管理规则置顶 + 用户规则保留，共 3 条
        assert len(put_rules) == 3
        assert put_rules[0]["action"] == "skip"
        assert put_rules[1]["action"] == "block"
        assert put_rules[2]["description"] == "Unused filter"
        # 旧管理规则已被剔除
        assert all("old-managed" not in str(r.get("id")) for r in put_rules)


def test_rule_expressions() -> None:
    """规则表达式与动作参数符合预期"""
    service = _make_service()
    with patch("wall.services.cloudflare_service.requests") as mock_req:
        mock_req.get.return_value = _mock_response(_get_payload([]))
        mock_req.put.return_value = _mock_response({"success": True, "result": {}})

        success, message = service.add_ips_to_whitelist(IPS)

        assert success, message
        assert message == f"OVERRIDE_SUCCESSFUL: {', '.join(IPS)}"
        rules = mock_req.put.call_args.kwargs["json"]["rules"]

        assert rules[0]["expression"] == (
            'http.host in {"api.example.com" "admin.example.com"} '
            "and ip.src in {203.0.113.10 203.0.113.11}"
        )
        assert rules[0]["action_parameters"] == {"ruleset": "current"}
        assert rules[1]["expression"] == (
            'http.host in {"api.example.com" "admin.example.com"} '
            "and not ip.src in {203.0.113.10 203.0.113.11}"
        )
        assert all(r["description"].startswith("wall-auto") for r in rules)


def test_missing_ruleset_treated_as_empty() -> None:
    """zone 还没有 ruleset 时（404）应视为空列表并正常创建"""
    service = _make_service()
    with patch("wall.services.cloudflare_service.requests") as mock_req:
        mock_req.get.return_value = _mock_response({"success": False}, status_code=404)
        mock_req.put.return_value = _mock_response({"success": True, "result": {}})

        success, _ = service.add_ips_to_whitelist(IPS)

        assert success
        put_rules = mock_req.put.call_args.kwargs["json"]["rules"]
        assert len(put_rules) == 2


def test_read_failure_returns_error(caplog: pytest.LogCaptureFixture) -> None:
    service = _make_service()
    with patch("wall.services.cloudflare_service.requests") as mock_req:
        mock_req.get.return_value = _mock_response(
            {"success": False, "errors": [{"message": "Authentication error"}]},
            status_code=403,
        )

        with caplog.at_level(logging.ERROR, logger="wall.services.cloudflare_service"):
            success, message = service.add_ips_to_whitelist(IPS)

        # 对外统一返回通用错误码，真实细节只进日志
        assert not success
        assert message == "OVERRIDE_FAILED"
        assert "Authentication error" in caplog.text
        mock_req.put.assert_not_called()


def test_update_failure_returns_error(caplog: pytest.LogCaptureFixture) -> None:
    service = _make_service()
    with patch("wall.services.cloudflare_service.requests") as mock_req:
        mock_req.get.return_value = _mock_response(_get_payload([]))
        mock_req.put.return_value = _mock_response(
            {"success": False, "errors": [{"message": "invalid expression"}]}
        )

        with caplog.at_level(logging.ERROR, logger="wall.services.cloudflare_service"):
            success, message = service.add_ips_to_whitelist(IPS)

        assert not success
        assert message == "OVERRIDE_FAILED"
        assert "invalid expression" in caplog.text
