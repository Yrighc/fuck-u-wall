from typing import Any
from unittest.mock import MagicMock

import pyotp
import pytest
from flask.testing import FlaskClient

import wall.app as wall_app
from wall.app import app
from wall.utils.rate_limiter import LoginRateLimiter

# pyotp 官方文档使用的测试密钥
TOTP_SECRET = "JBSWY3DPEHPK3PXP"


class StubCloudflareService:
    """模拟 CloudflareService：记录调用，可注入失败消息。"""

    def __init__(self, fail_message: str | None = None) -> None:
        self.fail_message = fail_message
        self.calls: list[list[str]] = []

    def add_ips_to_whitelist(self, ip_list: list[str]) -> tuple[bool, str]:
        self.calls.append(ip_list)
        if self.fail_message:
            return False, self.fail_message
        return True, f"OVERRIDE_SUCCESSFUL: {', '.join(ip_list)}"


@pytest.fixture
def secured_app(client: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> Any:
    """注入已知 TOTP 密钥、全新限流器、桩服务与 Turnstile 校验，用于接口安全测试。"""
    monkeypatch.setattr(wall_app, "totp", pyotp.TOTP(TOTP_SECRET))
    monkeypatch.setattr(wall_app, "rate_limiter", LoginRateLimiter(max_failures=5, lockout_seconds=900))
    monkeypatch.setattr(wall_app, "cloudflare_service", StubCloudflareService())
    monkeypatch.setattr(wall_app, "turnstile_secret", "test-secret")
    monkeypatch.setattr(wall_app, "turnstile_hostnames", {"localhost", "127.0.0.1"})
    # 默认放行 Turnstile（视为校验通过），专项测试再覆盖失败分支
    monkeypatch.setattr(wall_app, "_verify_turnstile", lambda token, ip: True)
    return wall_app


def _post_whitelist(client: FlaskClient, payload: dict[str, Any] | None = None) -> Any:
    body = payload or {}
    body.setdefault("cf_turnstile_response", "test-token")
    return client.post("/api/add-to-whitelist", json=body)


@pytest.fixture
def client() -> object:
    app.config["TESTING"] = True
    # 设置必要的环境变量模拟
    # 在实际测试中，可能需要 mock 掉 settings 或环境变量
    with app.test_client() as client:
        yield client


def test_index_page(client: FlaskClient) -> None:
    """测试首页能否正常访问 (冒烟测试)"""
    # 模拟环境变量，防止 app 启动检查失败 (虽然 app.py 在 import 时已经执行了部分逻辑)
    # 由于 app.py 模块级别的代码会在 import 时执行，
    # 如果在测试环境中 import wall.app 时环境变量缺失，可能会导致报错。
    # 不过 pyproject.toml 配置了 pythonpath=["src"]，
    # 且 app.py 中对于 CONFIG 的初始化依赖于 settings。
    # 为了简单起见，这里主要测试路由响应。

    response = client.get("/")
    assert response.status_code == 200
    assert b"IP" in response.data


def test_manifest_json(client: FlaskClient) -> None:
    """测试 Manifest 文件"""
    response = client.get("/manifest.json")
    assert response.status_code == 200
    assert response.is_json
    data = response.get_json()
    assert data["name"] == "WALL_OVERRIDE_CONSOLE"


def test_index_page_prefills_ip(client: FlaskClient) -> None:
    """测试首页是否自动填充公网 IP（来自请求头中的客户端 IP）"""
    fake_ip = "203.0.113.1"

    response = client.get("/", headers={"CF-Connecting-IP": fake_ip})
    assert response.status_code == 200
    assert f'value="{fake_ip}"'.encode() in response.data


def test_index_page_client_ip_priority(client: FlaskClient) -> None:
    """CF-Connecting-IP 优先于 X-Forwarded-For"""
    response = client.get(
        "/",
        headers={
            "CF-Connecting-IP": "203.0.113.1",
            "X-Forwarded-For": "203.0.113.2, 203.0.113.3",
        },
    )
    assert b'value="203.0.113.1"' in response.data


def test_index_page_xff_fallback(client: FlaskClient) -> None:
    """没有 CF 头时回退到 X-Forwarded-For 首个地址"""
    response = client.get("/", headers={"X-Forwarded-For": "203.0.113.2, 203.0.113.3"})
    assert b'value="203.0.113.2"' in response.data


def test_get_target_domain_endpoint_removed(client: FlaskClient) -> None:
    """已废弃的域名泄露接口必须下线"""
    response = client.get("/api/get-target-domain")
    assert response.status_code == 404


# ---------- add-to-whitelist 安全测试 ----------


def test_wrong_totp_returns_generic_access_denied(secured_app: Any, client: FlaskClient) -> None:
    """验证码错误时返回统一文案，不泄露任何内部细节"""
    resp = _post_whitelist(client, {"totp_code": "000000", "ips": "203.0.113.5"})
    assert resp.status_code == 401
    assert resp.get_json() == {"success": False, "message": "ACCESS_DENIED"}


def test_missing_and_malformed_totp_share_response(secured_app: Any, client: FlaskClient) -> None:
    """缺失 / 格式错误 / 校验失败必须返回完全相同的响应，避免帮助爆破者校准"""
    r1 = _post_whitelist(client, {"ips": "203.0.113.5"})
    r2 = _post_whitelist(client, {"totp_code": "123", "ips": "203.0.113.5"})
    assert r1.status_code == 401
    assert r2.status_code == 401
    assert r1.get_json() == r2.get_json() == {"success": False, "message": "ACCESS_DENIED"}


def test_valid_totp_succeeds(secured_app: Any, client: FlaskClient) -> None:
    """正确验证码可以正常放行"""
    code = pyotp.TOTP(TOTP_SECRET).now()
    resp = _post_whitelist(client, {"totp_code": code, "ips": "203.0.113.5"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "203.0.113.5" in data["message"]


def test_rate_limit_blocks_after_repeated_failures(secured_app: Any, client: FlaskClient) -> None:
    """连续失败达到阈值后锁定，即使验证码正确也被拒绝（防爆破）"""
    for _ in range(5):
        resp = _post_whitelist(client, {"totp_code": "000000", "ips": "203.0.113.5"})
        assert resp.status_code == 401
    code = pyotp.TOTP(TOTP_SECRET).now()
    resp = _post_whitelist(client, {"totp_code": code, "ips": "203.0.113.5"})
    assert resp.status_code == 429
    assert resp.get_json()["message"] == "RATE_LIMITED: TOO_MANY_ATTEMPTS"


def test_success_resets_failure_counter(secured_app: Any, client: FlaskClient) -> None:
    """验证成功后失败计数清零，避免误锁正常用户"""
    for _ in range(4):
        _post_whitelist(client, {"totp_code": "000000", "ips": "203.0.113.5"})
    code = pyotp.TOTP(TOTP_SECRET).now()
    assert (
        _post_whitelist(client, {"totp_code": code, "ips": "203.0.113.5"}).status_code
        == 200
    )
    assert (
        _post_whitelist(client, {"totp_code": "000000", "ips": "203.0.113.5"}).status_code
        == 401
    )


def test_invalid_json_returns_400_not_500(secured_app: Any, client: FlaskClient) -> None:
    """非 JSON 请求体返回 400，而不是带堆栈的 500"""
    resp = client.post(
        "/api/add-to-whitelist", data="not-json", content_type="application/json"
    )
    assert resp.status_code == 400
    assert resp.get_json()["message"] == "INVALID_PAYLOAD"


def test_ip_format_error_has_no_input_reflection(secured_app: Any, client: FlaskClient) -> None:
    """IP 格式错误不回显用户输入"""
    code = pyotp.TOTP(TOTP_SECRET).now()
    resp = _post_whitelist(client, {"totp_code": code, "ips": "999.1.1.1"})
    assert resp.status_code == 400
    assert resp.get_json()["message"] == "INVALID_TARGET_FORMAT"
    assert b"999.1.1.1" not in resp.data


def test_service_failure_does_not_leak_internal_detail(
    secured_app: Any, client: FlaskClient
) -> None:
    """底层服务失败时，内部异常细节不得透传给客户端"""
    secured_app.cloudflare_service = StubCloudflareService(
        fail_message="API_REQUEST_FAILED: ConnectionError(secret-internal-42)"
    )
    code = pyotp.TOTP(TOTP_SECRET).now()
    resp = _post_whitelist(client, {"totp_code": code, "ips": "203.0.113.5"})
    assert resp.status_code == 500
    assert resp.get_json()["message"] == "OVERRIDE_FAILED"
    assert b"secret-internal-42" not in resp.data


# ---------- Turnstile 人机验证测试 ----------


def test_missing_turnstile_token_rejected(secured_app: Any, client: FlaskClient) -> None:
    """未携带 Turnstile 令牌直接拒绝"""
    resp = client.post(
        "/api/add-to-whitelist",
        json={"totp_code": "000000", "ips": "203.0.113.5"},
    )
    assert resp.status_code == 403
    assert resp.get_json() == {"success": False, "message": "ACCESS_DENIED"}


def test_turnstile_failure_rejected(
    secured_app: Any, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """siteverify 校验失败时拒绝请求"""
    monkeypatch.setattr(wall_app, "_verify_turnstile", lambda token, ip: False)
    resp = _post_whitelist(client, {"totp_code": "000000", "ips": "203.0.113.5"})
    assert resp.status_code == 403
    assert resp.get_json()["message"] == "ACCESS_DENIED"


def test_turnstile_failures_do_not_consume_totp_rate_limit(
    secured_app: Any, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Turnstile 未通过时不应消耗 TOTP 限流配额（机器人无法借此把主人锁出去）"""
    monkeypatch.setattr(wall_app, "_verify_turnstile", lambda token, ip: False)
    for _ in range(20):
        resp = _post_whitelist(client, {"totp_code": "000000", "ips": "203.0.113.5"})
        assert resp.status_code == 403

    monkeypatch.setattr(wall_app, "_verify_turnstile", lambda token, ip: True)
    code = pyotp.TOTP(TOTP_SECRET).now()
    resp = _post_whitelist(client, {"totp_code": code, "ips": "203.0.113.5"})
    assert resp.status_code == 200


def test_index_page_embeds_turnstile_widget(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """首页嵌入 Turnstile widget，携带站点 key 与 action"""
    monkeypatch.setattr("wall.app.get_settings", lambda: _fake_settings())
    html = client.get("/").get_data(as_text=True)
    assert 'id="turnstile-widget"' in html
    assert 'data-sitekey="0x4AAAAAAEM5askdJyE9tkFz"' in html
    assert 'data-action="whitelist"' in html
    assert "challenges.cloudflare.com/turnstile/v0/api.js" in html


def _fake_settings() -> Any:
    """最小化 settings 桩：仅提供模板渲染所需的字段"""
    class _S:
        turnstile_sitekey = "0x4AAAAAAEM5askdJyE9tkFz"
        subdomain = "api.example.com"

    return _S()


# ---------- _verify_turnstile 单元测试 ----------


def _mock_siteverify(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> None:
    resp = MagicMock()
    resp.json.return_value = payload
    monkeypatch.setattr("wall.app.requests.post", lambda *a, **k: resp)


def test_verify_turnstile_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wall_app, "turnstile_secret", "secret")
    monkeypatch.setattr(wall_app, "turnstile_hostnames", {"example.com", "localhost"})
    _mock_siteverify(
        monkeypatch, {"success": True, "action": "whitelist", "hostname": "example.com"}
    )
    assert wall_app._verify_turnstile("token", "1.2.3.4") is True


def test_verify_turnstile_rejects_wrong_action(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wall_app, "turnstile_secret", "secret")
    monkeypatch.setattr(wall_app, "turnstile_hostnames", {"example.com"})
    _mock_siteverify(monkeypatch, {"success": True, "action": "login", "hostname": "example.com"})
    assert wall_app._verify_turnstile("token", "1.2.3.4") is False


def test_verify_turnstile_rejects_unknown_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wall_app, "turnstile_secret", "secret")
    monkeypatch.setattr(wall_app, "turnstile_hostnames", {"example.com"})
    _mock_siteverify(monkeypatch, {"success": True, "action": "whitelist", "hostname": "evil.com"})
    assert wall_app._verify_turnstile("token", "1.2.3.4") is False


def test_verify_turnstile_rejects_siteverify_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wall_app, "turnstile_secret", "secret")
    monkeypatch.setattr(wall_app, "turnstile_hostnames", {"example.com"})
    _mock_siteverify(monkeypatch, {"success": False, "error-codes": ["invalid-input-response"]})
    assert wall_app._verify_turnstile("token", "1.2.3.4") is False


def test_verify_turnstile_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wall_app, "turnstile_secret", "secret")
    monkeypatch.setattr(wall_app, "turnstile_hostnames", {"example.com"})

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise ConnectionError("boom")

    monkeypatch.setattr("wall.app.requests.post", _boom)
    assert wall_app._verify_turnstile("token", "1.2.3.4") is False


def test_verify_turnstile_without_secret_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wall_app, "turnstile_secret", None)
    monkeypatch.setattr(wall_app, "turnstile_hostnames", {"example.com"})
    assert wall_app._verify_turnstile("token", "1.2.3.4") is False


def test_verify_turnstile_rejects_oversized_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wall_app, "turnstile_secret", "secret")
    monkeypatch.setattr(wall_app, "turnstile_hostnames", {"example.com"})
    assert wall_app._verify_turnstile("x" * 2049, "1.2.3.4") is False
    assert wall_app._verify_turnstile("", "1.2.3.4") is False


def test_settings_totp_secret_defaults_to_empty() -> None:
    """totp_secret 必须有默认值（空串），缺失时在 init_globals 自动生成

    回归测试：首页渲染调用 get_settings()，而 CI 测试环境不设 TOTP_SECRET；
    若该字段为必填，Settings() 会抛 ValidationError 并 SystemExit(1)，
    导致整个测试进程退出。
    """
    from wall.config import Settings

    field = Settings.model_fields["totp_secret"]
    assert field.default == ""
    assert not field.is_required()


