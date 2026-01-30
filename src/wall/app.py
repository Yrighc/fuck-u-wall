import io
import os
import re
import warnings

import pyotp
from flask import Flask, Response, jsonify, render_template, request

from wall.config import settings
from wall.services.cloudflare_service import CloudflareService

# 禁用 SSL 警告（仅在必要时）
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(24).hex())

# 从环境变量读取配置
subdomain_str = (
    settings.subdomain if settings.subdomain else os.getenv("SUBDOMAIN", "").strip()
)
subdomains = (
    [s.strip() for s in subdomain_str.split(",") if s.strip()] if subdomain_str else []
)

CONFIG = {
    "port": settings.port,
    "totp_secret": settings.totp_secret,  # TOTP密钥，如果为空则自动生成
    "cloudflare_api": settings.cloudflare_api_token,
    "zone_id": settings.cloudflare_zone_id,
    "subdomains": subdomains,  # 子域名列表，支持多个，用逗号分隔，如 api.example.com,admin.example.com
}

# 如果没有设置TOTP密钥，生成一个新的
if not CONFIG["totp_secret"]:
    CONFIG["totp_secret"] = pyotp.random_base32()
    print(f"\n⚠️  未设置 TOTP_SECRET，已自动生成新的密钥: {CONFIG['totp_secret']}")
    print(
        "请将此密钥添加到环境变量 TOTP_SECRET 中，并使用 Authenticator 应用扫描二维码。"
    )

if not CONFIG["cloudflare_api"] or not CONFIG["zone_id"]:
    raise ValueError("请设置 CLOUDFLARE_API_TOKEN 和 CLOUDFLARE_ZONE_ID 环境变量")

if not CONFIG["subdomains"]:
    raise ValueError(
        "请设置 SUBDOMAIN 环境变量（子域名，支持多个用逗号分隔，如 api.example.com,admin.example.com）"
    )

# 初始化TOTP
totp = pyotp.TOTP(CONFIG["totp_secret"])

# 初始化 Cloudflare Service
cloudflare_service = CloudflareService(
    api_token=CONFIG["cloudflare_api"],
    zone_id=CONFIG["zone_id"],
    subdomains=CONFIG["subdomains"],
)


# 安全响应头
@app.after_request
def set_security_headers(response):
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
def index():
    """返回主页面"""
    return render_template("index.html")


@app.route("/manifest.json")
def manifest():
    """PWA Manifest 文件"""
    manifest_data = {
        "name": "IP 白名单管理",
        "short_name": "IP白名单",
        "description": "Cloudflare IP 白名单管理工具",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#667eea",
        "theme_color": "#667eea",
        "orientation": "portrait",
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }
    return jsonify(manifest_data)


@app.route("/icon-192.png")
def icon_192():
    """生成 192x192 图标"""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (192, 192), color=(102, 126, 234))
    draw = ImageDraw.Draw(img)
    # 绘制简单的图标
    draw.ellipse([40, 40, 152, 152], fill=(255, 255, 255))
    draw.text((70, 80), "IP", fill=(102, 126, 234))

    img_io = io.BytesIO()
    img.save(img_io, "PNG")
    img_io.seek(0)
    return Response(img_io.getvalue(), mimetype="image/png")


@app.route("/icon-512.png")
def icon_512():
    """生成 512x512 图标"""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (512, 512), color=(102, 126, 234))
    draw = ImageDraw.Draw(img)
    # 绘制简单的图标
    draw.ellipse([100, 100, 412, 412], fill=(255, 255, 255))
    draw.text((200, 220), "IP", fill=(102, 126, 234))

    img_io = io.BytesIO()
    img.save(img_io, "PNG")
    img_io.seek(0)
    return Response(img_io.getvalue(), mimetype="image/png")


@app.route("/api/get-target-domain", methods=["GET"])
def get_target_domain():
    """获取目标域名信息"""
    domains = ", ".join(CONFIG["subdomains"])
    return jsonify(
        {"success": True, "domain": domains, "domains": CONFIG["subdomains"]}
    )


@app.route("/api/add-to-whitelist", methods=["POST"])
def add_to_whitelist():
    """添加 IP 到 Cloudflare 白名单"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "请求数据无效"}), 400

        totp_code = data.get("totp_code", "")

        if not totp_code:
            return jsonify({"success": False, "message": "动态验证码不能为空"}), 400

        if len(totp_code) != 6 or not totp_code.isdigit():
            return jsonify({"success": False, "message": "验证码必须是6位数字"}), 400

        # 验证TOTP动态验证码（允许前后30秒的时间窗口）
        if not totp.verify(totp_code, valid_window=1):
            return (
                jsonify(
                    {"success": False, "message": "动态验证码错误或已过期，请重新获取"}
                ),
                401,
            )

        # 获取要添加的IP列表（必须手动输入）
        ips_input = data.get("ips", "").strip()

        if not ips_input:
            return jsonify({"success": False, "message": "请输入IP地址"}), 400

        # 解析IP列表
        ip_list = [ip.strip() for ip in ips_input.split(",") if ip.strip()]

        if not ip_list:
            return jsonify({"success": False, "message": "没有有效的IP地址"}), 400

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
                                {"success": False, "message": f"IP 格式错误: {ip}"}
                            ),
                            400,
                        )
                except ValueError:
                    return (
                        jsonify({"success": False, "message": f"IP 格式错误: {ip}"}),
                        400,
                    )
            # IPv6 验证：包含冒号且至少2个
            elif ":" in ip and ip.count(":") >= 2:
                # 基本IPv6格式验证
                if not re.match(r"^([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}$", ip):
                    return (
                        jsonify({"success": False, "message": f"IPv6 格式错误: {ip}"}),
                        400,
                    )
            else:
                return jsonify({"success": False, "message": f"IP 格式错误: {ip}"}), 400

        # 调用 Cloudflare API 添加IP列表
        success, message = cloudflare_service.add_ips_to_whitelist(ip_list)
        return jsonify({"success": success, "message": message})

    except Exception as e:
        return jsonify({"success": False, "message": f"服务器错误: {str(e)}"})


def run_app():
    app.run(host="0.0.0.0", port=CONFIG["port"], debug=False)
    print(f"🚀 应用正在运行，访问地址: http://localhost:{CONFIG['port']}")
