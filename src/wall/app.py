import io
import os
import re
import warnings

import pyotp
from flask import Flask, Response, jsonify, render_template, request

from wall.config import get_settings
from wall.services.cloudflare_service import CloudflareService
from wall.utils.ip_utils import get_public_ip

# 禁用 SSL 警告（仅在必要时）
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(24).hex())

# 全局变量 (将在 init_globals 中初始化)
subdomain_list = []
totp = None
cloudflare_service = None

def init_globals() -> None:
    """初始化全局依赖，仅在应用启动时调用"""
    global totp, cloudflare_service, subdomain_list

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

    if not isinstance(settings.port, int):
        try:
            settings.port = int(settings.port)
        except (ValueError, TypeError):
            settings.port = 8080  # 默认值

    # 初始化TOTP
    totp = pyotp.TOTP(settings.totp_secret)

    # 初始化 Cloudflare Service
    cloudflare_service = CloudflareService(
        api_token=settings.cloudflare_api_token,
        zone_id=settings.cloudflare_zone_id,
        subdomains=subdomain_list,
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
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline';"
    )
    return response


@app.route("/")
def index() -> str:
    """返回主页面"""
    client_ip = get_public_ip()
    return render_template("index.html", client_ip=client_ip)


@app.route("/manifest.json")
def manifest() -> Response:
    """PWA Manifest 文件"""
    manifest_data = {
        "name": "WALL_OVERRIDE_CONSOLE",
        "short_name": "OVERRIDE",
        "description": "Cloudflare Firewall Override Tool",
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


@app.route("/api/get-target-domain", methods=["GET"])
def get_target_domain() -> Response:
    """获取目标域名信息"""
    domains = ", ".join(get_settings().subdomain)
    return jsonify({"success": True, "domain": domains, "domains": subdomain_list})


@app.route("/api/add-to-whitelist", methods=["POST"])
def add_to_whitelist() -> tuple[Response, int]:
    """添加 IP 到 Cloudflare 白名单"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "INVALID_PAYLOAD"}), 400

        totp_code = data.get("totp_code", "")

        if not totp_code:
            return jsonify({"success": False, "message": "TOKEN_MISSING"}), 400

        if len(totp_code) != 6 or not totp_code.isdigit():
            return jsonify({"success": False, "message": "TOKEN_FORMAT_INVALID"}), 400

        # 验证TOTP动态验证码（允许前后30秒的时间窗口）
        if totp is None:
            return jsonify({"success": False, "message": "SYSTEM_ERROR: TOTP_SERVICE_OFFLINE"}), 500

        if not totp.verify(totp_code, valid_window=1):
            return (
                jsonify(
                    {"success": False, "message": "ACCESS_DENIED: INVALID_TOKEN"}
                ),
                401,
            )

        # 获取要添加的IP列表（必须手动输入）
        ips_input = data.get("ips", "").strip()

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
                            jsonify(
                                {"success": False, "message": f"INVALID_TARGET_FORMAT: {ip}"}
                            ),
                            400,
                        )
                except ValueError:
                    return (
                        jsonify({"success": False, "message": f"INVALID_TARGET_FORMAT: {ip}"}),
                        400,
                    )
            # IPv6 验证：包含冒号且至少2个
            elif ":" in ip and ip.count(":") >= 2:
                # 基本IPv6格式验证
                if not re.match(r"^([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}$", ip):
                    return (
                        jsonify({"success": False, "message": f"INVALID_IPV6_FORMAT: {ip}"}),
                        400,
                    )
            else:
                return jsonify({"success": False, "message": f"INVALID_TARGET_FORMAT: {ip}"}), 400

        # 调用 Cloudflare API 添加IP列表
        if cloudflare_service is None:
            return jsonify({"success": False, "message": "SYSTEM_ERROR: CLOUDFLARE_SERVICE_OFFLINE"}), 500

        success, message = cloudflare_service.add_ips_to_whitelist(ip_list)
        return jsonify({"success": success, "message": message}), (
            200 if success else 500
        )

    except Exception as e:
        return jsonify({"success": False, "message": f"SYSTEM_CRITICAL_FAILURE: {str(e)}"}), 500


def run_app() -> None:
    init_globals()
    settings = get_settings()
    app.run(host="0.0.0.0", port=settings.port, debug=False)
    print(f"🚀 应用正在运行，访问地址: http://localhost:{settings.port}")
