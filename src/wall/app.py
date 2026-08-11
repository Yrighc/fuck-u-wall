import io
import logging
import os
import re
import warnings

import pyotp
import requests
from flask import Flask, Response, jsonify, render_template, request

from wall.config import get_settings
from wall.services.cloudflare_service import CloudflareService
from wall.utils.rate_limiter import LoginRateLimiter

# 禁用 SSL 警告（仅在必要时）
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

logger = logging.getLogger("wall.app")

# Turnstile 校验使用的固定 action（前端 data-action 与后端校验必须一致）
TURNSTILE_ACTION = "whitelist"

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(24).hex())

# 全局变量 (将在 init_globals 中初始化)
subdomain_list = []
totp = None
cloudflare_service = None
turnstile_secret: str | None = None
turnstile_hostnames: set[str] = set()
# TOTP 失败限流器（默认值仅在测试/未初始化时生效，启动时按配置重建）
rate_limiter = LoginRateLimiter()

def init_globals() -> None:
    """初始化全局依赖，仅在应用启动时调用"""
    global totp, cloudflare_service, subdomain_list, rate_limiter
    global turnstile_secret, turnstile_hostnames

    settings = get_settings()

    # 从环境变量读取配置
    if not settings.subdomain or settings.subdomain.strip() == "":
        raise ValueError(
            "请设置 SUBDOMAIN 环境变量（子域名，支持多个用逗号分隔，如 api.example.com,admin.example.com）"
        )
    subdomain_str = settings.subdomain
    subdomain_list.extend(
        [s.strip() for s in subdomain_str.split(",") if s.strip()] if subdomain_str else []
    )

    # 如果没有设置TOTP密钥，生成一个新的
    if not settings.totp_secret or settings.totp_secret.strip() == "":
        # 注意：这里修改 settings 实例可能只会影响当前内存中的对象，重启后失效
        # 且 Pydantic 模型默认不可变，除非 config 设置为 allow_mutation (默认为 True)
        settings.totp_secret = pyotp.random_base32()
        print(f"\n⚠️  未设置 TOTP_SECRET，已自动生成新的密钥: {settings.totp_secret}")
        print(
            "请将此密钥添加到环境变量 TOTP_SECRET 中，并使用 Authenticator 应用扫描二维码。"
        )

    if (
        not settings.cloudflare_api_token
        or not settings.cloudflare_api_token.strip() != ""
        or not settings.cloudflare_zone_id
        or not settings.cloudflare_zone_id.strip() != ""
    ):
        raise ValueError("请设置 CLOUDFLARE_API_TOKEN 和 CLOUDFLARE_ZONE_ID 环境变量")

    # Turnstile 人机验证配置（fail-closed：缺失则拒绝启动）
    if (
        not settings.turnstile_sitekey
        or not settings.turnstile_sitekey.strip()
        or not settings.turnstile_secret
        or not settings.turnstile_secret.strip()
        or not settings.turnstile_hostnames
        or not settings.turnstile_hostnames.strip()
    ):
        raise ValueError(
            "请设置 TURNSTILE_SITEKEY / TURNSTILE_SECRET / TURNSTILE_HOSTNAMES "
            "环境变量（Turnstile 人机验证，缺一不可）"
        )

    if not isinstance(settings.port, int):
        try:
            settings.port = int(settings.port)
        except (ValueError, TypeError):
            settings.port = 8080  # 默认值

    # 初始化TOTP
    totp = pyotp.TOTP(settings.totp_secret)

    # 按配置重建限流器
    rate_limiter = LoginRateLimiter(
        max_failures=settings.max_failed_attempts,
        lockout_seconds=settings.lockout_minutes * 60,
    )

    # Turnstile 校验参数（fail-closed：未配置时启动即报错）
    turnstile_secret = settings.turnstile_secret
    turnstile_hostnames = {
        h.strip().lower()
        for h in settings.turnstile_hostnames.split(",")
        if h.strip()
    }

    # 初始化 Cloudflare Service
    cloudflare_service = CloudflareService(
        api_token=settings.cloudflare_api_token,
        zone_id=settings.cloudflare_zone_id,
        subdomains=subdomain_list,
    )


def _verify_turnstile(token: str, client_ip: str) -> bool:
    """服务端校验 Turnstile 令牌（令牌单次有效，不能重放）。

    要求：success 为 true、action 匹配、hostname 在白名单内。
    校验失败或网络异常一律返回 False（fail-closed）。
    """
    if turnstile_secret is None:
        return False
    # 令牌长度上限，超长直接拒绝
    if not token or len(token) > 2048:
        return False
    try:
        response = requests.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={
                "secret": turnstile_secret,
                "response": token,
                "remoteip": client_ip,
            },
            timeout=10,
        )
        result = response.json()
    except Exception:
        logger.exception("Turnstile siteverify 请求失败: ip=%s", client_ip)
        return False
    return bool(
        result.get("success")
        and result.get("action") == TURNSTILE_ACTION
        and result.get("hostname") in turnstile_hostnames
    )


# 安全响应头
@app.after_request
def set_security_headers(response: Response) -> Response:
    """设置安全响应头"""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains"
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com; "
        "style-src 'self' 'unsafe-inline'; "
        "frame-src https://challenges.cloudflare.com;"
    )
    return response


def _get_client_ip() -> str:
    """获取来访客户端的真实公网 IP，同时作为限流身份键。

    优先级：CF-Connecting-IP（Cloudflare 代理写入）> X-Forwarded-For 首个 > remote_addr。

    安全注意：仅当应用部署在 Cloudflare 代理或可信反向代理之后时，
    这些头才是可信的；直接暴露公网时攻击者可伪造请求头绕过限流，
    因此部署上必须将本应用置于代理之后（详见 README）。
    """
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip()
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr or "unknown"


@app.route("/")
def index() -> str:
    """返回主页面"""
    client_ip = _get_client_ip()
    return render_template(
        "index.html",
        client_ip=client_ip,
        turnstile_sitekey=get_settings().turnstile_sitekey,
    )


@app.route("/manifest.json")
def manifest() -> Response:
    """PWA Manifest 文件"""
    manifest_data = {
        "name": "WALL_OVERRIDE_CONSOLE",
        "short_name": "OVERRIDE",
        "description": "Network Access Management Tool",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0a0a0a",
        "theme_color": "#0a0a0a",
        "orientation": "portrait",
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }
    return jsonify(manifest_data)


@app.route("/icon-192.png")
def icon_192() -> Response:
    """生成 192x192 图标"""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (192, 192), color=(10, 10, 10))
    draw = ImageDraw.Draw(img)
    # 绘制简单的图标
    draw.ellipse([40, 40, 152, 152], fill=(180, 168, 229))
    draw.text((70, 80), "IP", fill=(10, 10, 10))

    img_io = io.BytesIO()
    img.save(img_io, "PNG")
    img_io.seek(0)
    return Response(img_io.getvalue(), mimetype="image/png")


@app.route("/icon-512.png")
def icon_512() -> Response:
    """生成 512x512 图标"""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (512, 512), color=(10, 10, 10))
    draw = ImageDraw.Draw(img)
    # 绘制简单的图标
    draw.ellipse([100, 100, 412, 412], fill=(180, 168, 229))
    draw.text((200, 220), "IP", fill=(10, 10, 10))

    img_io = io.BytesIO()
    img.save(img_io, "PNG")
    img_io.seek(0)
    return Response(img_io.getvalue(), mimetype="image/png")


@app.route("/api/add-to-whitelist", methods=["POST"])
def add_to_whitelist() -> tuple[Response, int]:
    """添加 IP 到白名单（TOTP 验证 + 失败限流）。

    安全约定：所有对外错误响应均为通用文案，不包含异常细节、
    服务内部结构或校验差异，细节只写服务端日志。
    """
    client_ip = _get_client_ip()

    # 限流：锁定期间直接拒绝，防止对 TOTP 的在线爆破
    if rate_limiter.is_locked_out(client_ip):
        logger.warning("TOTP 请求因触发限流被拒绝: ip=%s", client_ip)
        return (
            jsonify({"success": False, "message": "RATE_LIMITED: TOO_MANY_ATTEMPTS"}),
            429,
        )

    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"success": False, "message": "INVALID_PAYLOAD"}), 400

        # Turnstile 人机验证（先于 TOTP：未通过人机验证不消耗验证码校验）
        turnstile_token = str(data.get("cf_turnstile_response") or "")
        if not turnstile_token or not _verify_turnstile(turnstile_token, client_ip):
            logger.warning("Turnstile 校验失败: ip=%s", client_ip)
            return jsonify({"success": False, "message": "ACCESS_DENIED"}), 403

        totp_code = str(data.get("totp_code") or "")
        # 统一鉴权失败响应：不区分缺失 / 格式错误 / 校验失败，避免泄露校验细节
        if len(totp_code) != 6 or not totp_code.isdigit():
            return jsonify({"success": False, "message": "ACCESS_DENIED"}), 401

        # 验证TOTP动态验证码（允许前后30秒的时间窗口）
        if totp is None:
            logger.error("TOTP 服务未初始化: ip=%s", client_ip)
            return jsonify({"success": False, "message": "ACCESS_DENIED"}), 401

        if not totp.verify(totp_code, valid_window=1):
            locked = rate_limiter.record_failure(client_ip)
            logger.warning(
                "TOTP 验证失败: ip=%s locked=%s failures=%s",
                client_ip,
                locked,
                rate_limiter.recent_failures(client_ip),
            )
            return jsonify({"success": False, "message": "ACCESS_DENIED"}), 401

        # 验证通过：清零失败计数
        rate_limiter.record_success(client_ip)
        logger.info("TOTP 验证通过: ip=%s", client_ip)

        # 获取要添加的IP列表（必须手动输入）
        ips_input = str(data.get("ips") or "").strip()

        if not ips_input:
            return jsonify({"success": False, "message": "TARGET_MISSING"}), 400

        # 解析IP列表
        ip_list = [ip.strip() for ip in ips_input.split(",") if ip.strip()]

        if not ip_list:
            return jsonify({"success": False, "message": "NO_VALID_TARGETS"}), 400

        # 验证IP格式
        for ip in ip_list:
            # IPv4 验证：4个数字段
            parts = ip.split(".")
            if len(parts) == 4:
                try:
                    # 验证每个段是否在0-255之间
                    if not all(0 <= int(p) <= 255 for p in parts):
                        return (
                            jsonify({"success": False, "message": "INVALID_TARGET_FORMAT"}),
                            400,
                        )
                except ValueError:
                    return (
                        jsonify({"success": False, "message": "INVALID_TARGET_FORMAT"}),
                        400,
                    )
            # IPv6 验证：包含冒号且至少2个
            elif ":" in ip and ip.count(":") >= 2:
                # 基本IPv6格式验证
                if not re.match(r"^([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}$", ip):
                    return (
                        jsonify({"success": False, "message": "INVALID_TARGET_FORMAT"}),
                        400,
                    )
            else:
                return jsonify({"success": False, "message": "INVALID_TARGET_FORMAT"}), 400

        # 调用 Cloudflare API 添加IP列表
        if cloudflare_service is None:
            logger.error("Cloudflare 服务未初始化: ip=%s", client_ip)
            return jsonify({"success": False, "message": "SYSTEM_ERROR"}), 500

        success, message = cloudflare_service.add_ips_to_whitelist(ip_list)
        if not success:
            # 失败细节只进日志，不外泄给客户端
            logger.error("白名单更新失败: ip=%s detail=%s", client_ip, message)
            return jsonify({"success": False, "message": "OVERRIDE_FAILED"}), 500
        logger.info("白名单更新成功: ip=%s ips=%s", client_ip, ip_list)
        return jsonify({"success": True, "message": message}), 200

    except Exception:
        # 兜底：任何未预期异常都不向客户端泄露内部细节
        logger.exception("add-to-whitelist 未预期异常: ip=%s", client_ip)
        return jsonify({"success": False, "message": "SYSTEM_ERROR"}), 500


def run_app() -> None:
    init_globals()
    settings = get_settings()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    print(f"🚀 应用正在运行，访问地址: http://localhost:{settings.port}")
    app.run(host=settings.host, port=settings.port, debug=False)
