#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import random
import string
import io
import base64
import re
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from flask import Flask, request, jsonify, session, Response
from PIL import Image, ImageDraw, ImageFont
import pyotp
import qrcode
from dotenv import load_dotenv
import warnings

# 禁用 SSL 警告（仅在必要时）
warnings.filterwarnings('ignore', message='Unverified HTTPS request')

# 加载 .env 文件
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', os.urandom(24).hex())

# 从环境变量读取配置
subdomain_str = os.getenv('SUBDOMAIN', '').strip()
subdomains = [s.strip() for s in subdomain_str.split(',') if s.strip()] if subdomain_str else []

CONFIG = {
    'port': int(os.getenv('PORT', '8080')),
    'totp_secret': os.getenv('TOTP_SECRET', ''),  # TOTP密钥，如果为空则自动生成
    'cloudflare_api': os.getenv('CLOUDFLARE_API_TOKEN', ''),
    'zone_id': os.getenv('CLOUDFLARE_ZONE_ID', ''),
    'subdomains': subdomains  # 子域名列表，支持多个，用逗号分隔，如 api.example.com,admin.example.com
}

# 如果没有设置TOTP密钥，生成一个新的
if not CONFIG['totp_secret']:
    CONFIG['totp_secret'] = pyotp.random_base32()
    print(f"\n⚠️  未设置 TOTP_SECRET，已自动生成新的密钥: {CONFIG['totp_secret']}")
    print("请将此密钥添加到环境变量 TOTP_SECRET 中，并使用 Authenticator 应用扫描二维码。\n")

if not CONFIG['cloudflare_api'] or not CONFIG['zone_id']:
    raise ValueError("请设置 CLOUDFLARE_API_TOKEN 和 CLOUDFLARE_ZONE_ID 环境变量")

# 初始化TOTP
totp = pyotp.TOTP(CONFIG['totp_secret'])

if not CONFIG['subdomains']:
    raise ValueError("请设置 SUBDOMAIN 环境变量（子域名，支持多个用逗号分隔，如 api.example.com,admin.example.com）")

# 安全响应头
@app.after_request
def set_security_headers(response):
    """设置安全响应头"""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline';"
    return response

def generate_captcha():
    """生成图片验证码"""
    # 生成4位随机字符（数字+大写字母）
    chars = string.digits + string.ascii_uppercase
    captcha_text = ''.join(random.choices(chars, k=4))
    
    # 保存到session
    session['captcha_answer'] = captcha_text
    
    # 创建图片
    width, height = 120, 40
    image = Image.new('RGB', (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(image)
    
    # 尝试使用系统字体，如果失败则使用默认字体
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 24)
    except:
        try:
            font = ImageFont.truetype("arial.ttf", 24)
        except:
            font = ImageFont.load_default()
    
    # 绘制验证码文字（添加一些随机偏移和旋转）
    x = 10
    for char in captcha_text:
        # 随机颜色
        color = (random.randint(0, 100), random.randint(0, 100), random.randint(0, 100))
        # 随机y位置
        y = random.randint(5, 15)
        # 绘制文字
        draw.text((x, y), char, fill=color, font=font)
        x += 25
    
    # 添加干扰线
    for _ in range(3):
        start = (random.randint(0, width), random.randint(0, height))
        end = (random.randint(0, width), random.randint(0, height))
        draw.line([start, end], fill=(random.randint(150, 255), random.randint(150, 255), random.randint(150, 255)), width=1)
    
    # 添加干扰点
    for _ in range(50):
        x = random.randint(0, width)
        y = random.randint(0, height)
        draw.point((x, y), fill=(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)))
    
    # 将图片转换为字节流
    img_io = io.BytesIO()
    image.save(img_io, 'PNG')
    img_io.seek(0)
    
    return img_io


@app.route('/')
def index():
    """返回主页面"""
    html = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="theme-color" content="#667eea">
    <title>IP 白名单管理</title>
    <link rel="manifest" href="/manifest.json">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        .container {
            background: white;
            border-radius: 20px;
            padding: 30px 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            max-width: 500px;
            width: 100%;
            margin: 0 auto;
        }
        
        @media (max-width: 480px) {
            .container {
                padding: 20px 15px;
                border-radius: 15px;
            }
            h1 {
                font-size: 24px;
            }
        }
        h1 {
            color: #333;
            margin-bottom: 30px;
            text-align: center;
            font-size: 28px;
        }
        .ip-display {
            background: #f5f5f5;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 30px;
            text-align: center;
        }
        .ip-label {
            color: #666;
            font-size: 14px;
            margin-bottom: 10px;
        }
        .ip-value {
            color: #333;
            font-size: 24px;
            font-weight: bold;
            font-family: 'Courier New', monospace;
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            color: #333;
            margin-bottom: 8px;
            font-weight: 500;
        }
        input {
            width: 100%;
            padding: 12px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 16px;
            transition: border-color 0.3s;
        }
        input:focus {
            outline: none;
            border-color: #667eea;
        }
        button {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
        }
        button:active {
            transform: translateY(0);
        }
        button:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }
        .message {
            margin-top: 20px;
            padding: 12px;
            border-radius: 8px;
            text-align: center;
            font-size: 14px;
            display: none;
        }
        .message.success {
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
            display: block;
        }
        .message.error {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
            display: block;
        }
        .loading {
            display: inline-block;
            width: 16px;
            height: 16px;
            border: 2px solid #ffffff;
            border-radius: 50%;
            border-top-color: transparent;
            animation: spin 0.6s linear infinite;
            margin-right: 8px;
            vertical-align: middle;
        }
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🌐 IP 白名单管理</h1>
        <div class="ip-display">
            <div class="ip-label">当前 IP 地址（自动获取）</div>
            <div class="ip-value" id="currentIP">获取中...</div>
            <div id="allIPs" style="margin-top: 10px; font-size: 12px; color: #666; display: none; word-break: break-all;"></div>
            <div id="ipError" style="margin-top: 10px; font-size: 12px; color: #dc3545; display: none;">
                自动获取失败，请手动输入IP地址
            </div>
        </div>
        <form id="whitelistForm">
            <div class="form-group">
                <label for="ipInput">IP 地址（可选，留空使用自动获取的IP，支持多个用逗号分隔）</label>
                <input type="text" id="ipInput" name="ipInput" placeholder="例如: 192.168.1.1,10.0.0.1">
                <small style="color: #666; font-size: 12px; margin-top: 5px; display: block;">留空则使用自动获取的IP，或手动输入IP（支持多个，用逗号分隔）</small>
            </div>
            <div class="form-group">
                <label for="totpCode">动态验证码</label>
                <input type="text" id="totpCode" name="totpCode" placeholder="请输入验证码" required maxlength="6" pattern="[0-9]{6}">
                <small style="color: #666; font-size: 12px; margin-top: 5px; display: block;">请输入密钥</small>
            </div>
            <div class="form-group">
                <label for="captcha">验证码</label>
                <div style="display: flex; gap: 10px; align-items: center;">
                    <input type="text" id="captcha" name="captcha" placeholder="请输入验证码" required style="flex: 1;" maxlength="4">
                    <div style="display: flex; gap: 5px; align-items: center;">
                        <img id="captchaImage" src="/api/get-captcha" alt="验证码" style="border: 1px solid #e0e0e0; border-radius: 6px; cursor: pointer;" onclick="getCaptcha()">
                        <button type="button" id="refreshCaptcha" style="padding: 8px 12px; background: #667eea; color: white; border: none; border-radius: 6px; cursor: pointer;">刷新</button>
                    </div>
                </div>
            </div>
            <button type="submit" id="submitBtn">
                <span id="btnText">添加到白名单</span>
            </button>
        </form>
        <div class="message" id="message"></div>
    </div>
    <script>
        // 获取当前 IP
        async function getCurrentIP() {
            try {
                const response = await fetch('/api/get-ip');
                const data = await response.json();
                if (data.success) {
                    document.getElementById('currentIP').textContent = data.ip;
                    document.getElementById('ipError').style.display = 'none';
                    // 如果有多个IP，显示所有IP
                    if (data.ips && data.ips.length > 1) {
                        const allIPsDiv = document.getElementById('allIPs');
                        allIPsDiv.textContent = '所有IP: ' + data.ips.join(', ');
                        allIPsDiv.style.display = 'block';
                    } else {
                        document.getElementById('allIPs').style.display = 'none';
                    }
                } else {
                    document.getElementById('currentIP').textContent = '获取失败';
                    document.getElementById('allIPs').style.display = 'none';
                    document.getElementById('ipError').style.display = 'block';
                }
            } catch (error) {
                document.getElementById('currentIP').textContent = '获取失败';
                document.getElementById('allIPs').style.display = 'none';
                document.getElementById('ipError').style.display = 'block';
                console.error('获取 IP 失败:', error);
            }
        }

        // 获取验证码图片
        function getCaptcha() {
            const img = document.getElementById('captchaImage');
            // 添加时间戳防止缓存
            img.src = '/api/get-captcha?t=' + new Date().getTime();
            document.getElementById('captcha').value = '';
        }

        // 刷新验证码
        document.getElementById('refreshCaptcha').addEventListener('click', () => {
            getCaptcha();
        });

        // 添加到白名单
        document.getElementById('whitelistForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const totpCode = document.getElementById('totpCode').value;
            const captcha = document.getElementById('captcha').value;
            const ipInput = document.getElementById('ipInput').value.trim();
            const submitBtn = document.getElementById('submitBtn');
            const btnText = document.getElementById('btnText');
            const message = document.getElementById('message');

            // 禁用按钮并显示加载状态
            submitBtn.disabled = true;
            btnText.innerHTML = '<span class="loading"></span>处理中...';

            try {
                const requestBody = {
                    totp_code: totpCode,
                    captcha: captcha
                };
                
                // 如果手动输入了IP，则使用手动输入的IP
                if (ipInput) {
                    requestBody.ips = ipInput;
                }

                const response = await fetch('/api/add-to-whitelist', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(requestBody),
                });

                const data = await response.json();
                message.className = 'message ' + (data.success ? 'success' : 'error');
                message.textContent = data.message || (data.success ? '成功添加到白名单！' : '操作失败');
                message.style.display = 'block';

                if (data.success) {
                    document.getElementById('totpCode').value = '';
                    document.getElementById('captcha').value = '';
                    document.getElementById('ipInput').value = '';
                    getCaptcha(); // 刷新验证码
                } else {
                    // 验证失败时刷新验证码
                    getCaptcha();
                    document.getElementById('captcha').value = '';
                }
            } catch (error) {
                message.className = 'message error';
                message.textContent = '网络错误，请重试';
                message.style.display = 'block';
                console.error('添加失败:', error);
            } finally {
                submitBtn.disabled = false;
                btnText.textContent = '添加到白名单';
            }
        });

        // 页面加载时获取验证码
        getCaptcha();

        // 页面加载时获取 IP
        getCurrentIP();
    </script>
</body>
</html>'''
    return html


@app.route('/manifest.json')
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
            {
                "src": "/icon-192.png",
                "sizes": "192x192",
                "type": "image/png"
            },
            {
                "src": "/icon-512.png",
                "sizes": "512x512",
                "type": "image/png"
            }
        ]
    }
    return jsonify(manifest_data)


@app.route('/icon-192.png')
def icon_192():
    """生成 192x192 图标"""
    from PIL import Image, ImageDraw
    
    img = Image.new('RGB', (192, 192), color=(102, 126, 234))
    draw = ImageDraw.Draw(img)
    # 绘制简单的图标
    draw.ellipse([40, 40, 152, 152], fill=(255, 255, 255))
    draw.text((70, 80), "IP", fill=(102, 126, 234))
    
    img_io = io.BytesIO()
    img.save(img_io, 'PNG')
    img_io.seek(0)
    return Response(img_io.getvalue(), mimetype='image/png')


@app.route('/icon-512.png')
def icon_512():
    """生成 512x512 图标"""
    from PIL import Image, ImageDraw
    
    img = Image.new('RGB', (512, 512), color=(102, 126, 234))
    draw = ImageDraw.Draw(img)
    # 绘制简单的图标
    draw.ellipse([100, 100, 412, 412], fill=(255, 255, 255))
    draw.text((200, 220), "IP", fill=(102, 126, 234))
    
    img_io = io.BytesIO()
    img.save(img_io, 'PNG')
    img_io.seek(0)
    return Response(img_io.getvalue(), mimetype='image/png')


@app.route('/api/get-target-domain', methods=['GET'])
def get_target_domain():
    """获取目标域名信息"""
    domains = ', '.join(CONFIG['subdomains'])
    return jsonify({'success': True, 'domain': domains, 'domains': CONFIG['subdomains']})


@app.route('/api/get-captcha', methods=['GET'])
def get_captcha():
    """获取图片验证码"""
    img_io = generate_captcha()
    return Response(img_io.getvalue(), mimetype='image/png')


def get_client_ips(request):
    """从请求头获取客户端真实IP（支持IPv4和IPv6）"""
    ips = []
    
    # 按优先级检查各种请求头
    headers_to_check = [
        'CF-Connecting-IP',  # Cloudflare
        'X-Forwarded-For',
        'X-Real-IP',
        'X-Client-IP',
        'X-Forwarded',
        'Forwarded-For',
        'Forwarded',
    ]
    
    for header in headers_to_check:
        value = request.headers.get(header, '')
        if value:
            # X-Forwarded-For 可能包含多个IP，用逗号分隔
            for ip in value.split(','):
                ip = ip.strip()
                # 跳过本地IP
                if ip in ['127.0.0.1', '::1', 'localhost']:
                    continue
                # 验证IP格式（简单验证）
                if ip and (len(ip.split('.')) == 4 or (':' in ip and ip.count(':') >= 2)):
                    if ip not in ips:
                        ips.append(ip)
    
    # 如果请求头中没有，尝试从 remote_addr 获取
    if not ips:
        remote_addr = request.remote_addr
        if remote_addr and remote_addr not in ['127.0.0.1', '::1', 'localhost']:
            if remote_addr not in ips:
                ips.append(remote_addr)
    
    return ips


@app.route('/api/get-ip', methods=['GET'])
def get_current_ip():
    """获取服务器公网 IP 地址（使用 ipify API）"""
    all_ips = []
    
    # 只使用两个 API：一个 IPv4，一个 IPv6
    ip_services = [
        ('https://api.ipify.org?format=json', 'ip'),      # IPv4
        ('https://api64.ipify.org?format=json', 'ip'),   # IPv6
    ]

    # 尝试从请求头获取客户端IP（如果通过代理）
    client_ip = None
    try:
        # 优先使用 Cloudflare 的 IP 头
        client_ip = request.headers.get('CF-Connecting-IP')
        if not client_ip:
            # 使用 X-Forwarded-For（取第一个）
            forwarded = request.headers.get('X-Forwarded-For', '')
            if forwarded:
                client_ip = forwarded.split(',')[0].strip()
        if not client_ip:
            # 使用 X-Real-IP
            client_ip = request.headers.get('X-Real-IP')
        
        # 验证客户端IP格式
        if client_ip:
            # 排除本地IP
            if client_ip not in ['127.0.0.1', '::1', 'localhost']:
                # IPv4 验证
                parts = client_ip.split('.')
                if len(parts) == 4:
                    try:
                        if all(0 <= int(p) <= 255 for p in parts):
                            if client_ip not in all_ips:
                                all_ips.append(client_ip)
                    except:
                        pass
                # IPv6 验证
                elif ':' in client_ip and client_ip.count(':') >= 2:
                    if client_ip not in all_ips:
                        all_ips.append(client_ip)
    except:
        pass

    # 从 ipify API 获取 IP
    for service, json_key in ip_services:
        try:
            response = requests.get(service, timeout=5, verify=True)
            if response.status_code == 200:
                try:
                    data = response.json()
                    ip = data.get(json_key, '').strip()
                    
                    # 验证 IP 格式
                    if ip and ip not in ['127.0.0.1', '::1', 'localhost', '']:
                        # IPv4 验证：4个数字段，每个在0-255之间
                        parts = ip.split('.')
                        if len(parts) == 4:
                            try:
                                if all(0 <= int(p) <= 255 for p in parts):
                                    if ip not in all_ips:
                                        all_ips.append(ip)
                            except:
                                continue
                        # IPv6 验证：包含冒号且至少2个
                        elif ':' in ip and ip.count(':') >= 2:
                            if ip not in all_ips:
                                all_ips.append(ip)
                except:
                    continue
        except requests.exceptions.SSLError:
            # SSL错误时，尝试不验证证书
            try:
                response = requests.get(service, timeout=5, verify=False)
                if response.status_code == 200:
                    try:
                        data = response.json()
                        ip = data.get(json_key, '').strip()
                        
                        if ip and ip not in ['127.0.0.1', '::1', 'localhost', '']:
                            parts = ip.split('.')
                            if len(parts) == 4:
                                try:
                                    if all(0 <= int(p) <= 255 for p in parts):
                                        if ip not in all_ips:
                                            all_ips.append(ip)
                                except:
                                    continue
                            elif ':' in ip and ip.count(':') >= 2:
                                if ip not in all_ips:
                                    all_ips.append(ip)
                    except:
                        continue
            except:
                continue
        except requests.exceptions.ConnectionError:
            continue
        except requests.exceptions.Timeout:
            continue
        except Exception:
            continue
    
    # 如果获取到了IP
    if all_ips:
        # 优先返回IPv4，如果没有则返回IPv6
        ipv4 = [ip for ip in all_ips if '.' in ip]
        ipv6 = [ip for ip in all_ips if ':' in ip]
        
        if ipv4:
            return jsonify({'success': True, 'ip': ipv4[0], 'ips': all_ips})
        elif ipv6:
            return jsonify({'success': True, 'ip': ipv6[0], 'ips': all_ips})
        else:
            return jsonify({'success': True, 'ip': all_ips[0], 'ips': all_ips})
    
    # 如果都失败了，返回提示
    return jsonify({'success': False, 'message': '无法自动获取 IP 地址，请手动输入IP'})


@app.route('/api/add-to-whitelist', methods=['POST'])
def add_to_whitelist():
    """添加 IP 到 Cloudflare 白名单"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': '请求数据无效'}), 400
        
        totp_code = data.get('totp_code', '')
        captcha_answer = data.get('captcha', '')
        
        if not totp_code:
            return jsonify({'success': False, 'message': '动态验证码不能为空'}), 400
        
        if len(totp_code) != 6 or not totp_code.isdigit():
            return jsonify({'success': False, 'message': '验证码必须是6位数字'}), 400
        
        if not captcha_answer:
            return jsonify({'success': False, 'message': '验证码不能为空'}), 400
        
        # 验证验证码
        correct_answer = session.get('captcha_answer')
        if not correct_answer:
            return jsonify({'success': False, 'message': '验证码已过期，请刷新页面'}), 400
        
        # 验证码不区分大小写
        user_answer = captcha_answer.strip().upper()
        correct_answer = correct_answer.upper()
        
        if user_answer != correct_answer:
            # 验证码错误，生成新的验证码
            generate_captcha()
            return jsonify({'success': False, 'message': '验证码错误'}), 400
        
        # 验证码正确，清除验证码答案
        session.pop('captcha_answer', None)
        
        # 验证TOTP动态验证码（允许前后30秒的时间窗口）
        if not totp.verify(totp_code, valid_window=1):
            # TOTP验证失败，生成新的验证码
            generate_captcha()
            return jsonify({'success': False, 'message': '动态验证码错误或已过期，请重新获取'}), 401

        # 获取要添加的IP列表
        ips_input = data.get('ips', '').strip()
        ip_list = []
        
        if ips_input:
            # 使用手动输入的IP
            ip_list = [ip.strip() for ip in ips_input.split(',') if ip.strip()]
            # 验证IP格式
            for ip in ip_list:
                if not (len(ip.split('.')) == 4 or ':' in ip):
                    return jsonify({'success': False, 'message': f'IP 格式错误: {ip}'}), 400
        else:
            # 使用第三方服务获取服务器自己的公网IP
            ip_services = [
                ('https://api.ipify.org?format=json', 'ip'),  # IPv4
                ('https://api64.ipify.org?format=json', 'ip'),  # IPv6优先
                ('https://ifconfig.me/ip', None),  # 文本
                ('https://icanhazip.com', None),  # 文本
                ('https://ipinfo.io/ip', None),  # 文本
                ('https://checkip.amazonaws.com', None),  # 文本
                ('https://api.myip.com', 'ip'),  # JSON
                ('https://ip.seeip.org', None),  # 文本
                ('https://api.ip.sb/ip', None),  # 文本
            ]
            
            ip_list = []
            for service, json_key in ip_services:
                try:
                    ip_response = requests.get(service, timeout=10, verify=True)
                    if ip_response.status_code == 200:
                        ip = None
                        try:
                            if json_key:
                                ip_data = ip_response.json()
                                ip = ip_data.get(json_key, '').strip()
                            else:
                                ip = ip_response.text.strip()
                        except:
                            continue
                        
                        # 验证 IP 格式
                        if ip and ip not in ['127.0.0.1', '::1', 'localhost']:
                            if len(ip.split('.')) == 4 or (':' in ip and ip.count(':') >= 2):
                                if ip not in ip_list:
                                    ip_list.append(ip)
                except:
                    continue
            
            if not ip_list:
                return jsonify({'success': False, 'message': '无法获取 IP 地址，请检查网络连接或手动输入IP'}), 400
        
        if not ip_list:
            return jsonify({'success': False, 'message': '没有有效的IP地址'}), 400

        # 调用 Cloudflare API 添加IP列表
        success, message = add_ips_to_cloudflare(ip_list)
        return jsonify({'success': success, 'message': message})

    except Exception as e:
        return jsonify({'success': False, 'message': f'服务器错误: {str(e)}'})


def add_ips_to_cloudflare(ip_list):
    """将多个 IP 添加到 Cloudflare 防火墙白名单（支持多个子域名）"""
    headers = {
        'Authorization': f"Bearer {CONFIG['cloudflare_api']}",
        'Content-Type': 'application/json'
    }

    # 使用 Firewall Rules API
    rules_url = f"https://api.cloudflare.com/client/v4/zones/{CONFIG['zone_id']}/firewall/rules"
    filters_url = f"https://api.cloudflare.com/client/v4/zones/{CONFIG['zone_id']}/filters"
    
    try:
        # 第一步：删除所有现有的防火墙规则（包括白名单和黑名单）
        # 获取所有规则（处理分页）
        all_rules = []
        page = 1
        per_page = 100
        
        while True:
            response = requests.get(rules_url, headers=headers, params={'per_page': per_page, 'page': page}, timeout=10)
            if response.status_code != 200:
                break
            
            data = response.json()
            if not data.get('success'):
                break
            
            rules = data.get('result', [])
            if not rules:
                break
            
            all_rules.extend(rules)
            
            # 检查是否还有更多页面
            result_info = data.get('result_info', {})
            total_pages = result_info.get('total_pages', 1)
            if page >= total_pages:
                break
            page += 1
        
        # 收集所有规则ID和关联的过滤器ID（包括白名单和黑名单）
        rule_ids = []
        filter_ids = []
        for rule in all_rules:
            rule_id = rule.get('id')
            filter_id = rule.get('filter', {}).get('id')
            action = rule.get('action', '')  # allow 或 block
            
            if rule_id:
                rule_ids.append(rule_id)
            if filter_id:
                filter_ids.append(filter_id)
        
        # 先删除所有防火墙规则（包括白名单 allow 和黑名单 block）
        if rule_ids:
            for rule_id in rule_ids:
                try:
                    delete_response = requests.delete(f"{rules_url}/{rule_id}", headers=headers, timeout=5)
                    if delete_response.status_code not in [200, 404]:  # 404 表示已不存在，也算成功
                        pass  # 记录错误但继续删除其他规则
                except Exception as e:
                    pass  # 继续删除其他规则
        
        # 然后删除所有关联的过滤器
        if filter_ids:
            # 去重过滤器ID（多个规则可能共享同一个过滤器）
            unique_filter_ids = list(set(filter_ids))
            for filter_id in unique_filter_ids:
                try:
                    delete_response = requests.delete(f"{filters_url}/{filter_id}", headers=headers, timeout=5)
                    if delete_response.status_code not in [200, 404]:  # 404 表示已不存在，也算成功
                        pass  # 记录错误但继续删除其他过滤器
                except Exception as e:
                    pass  # 继续删除其他过滤器

        # 第二步：创建合并的白名单和黑名单规则（所有子域名和所有IP合并为规则）
        domains_str = ', '.join(CONFIG['subdomains'])
        ips_str = ', '.join(ip_list)
        
        try:
            # 2.1 创建合并的白名单规则：所有IP对所有子域名白名单
            # 构建多个子域名的 or 表达式
            host_conditions = ' or '.join([f'http.host eq "{subdomain}"' for subdomain in CONFIG['subdomains']])
            # 构建多个IP的 or 表达式
            ip_conditions = ' or '.join([f'ip.src eq {ip}' for ip in ip_list])
            whitelist_expression = f'({host_conditions}) and ({ip_conditions})'
            whitelist_notes = f"Auto-added IPs {ips_str} whitelist for all subdomains: {domains_str}"
            
            # 创建白名单过滤器
            whitelist_filter_payload = {
                'expression': whitelist_expression,
                'description': whitelist_notes
            }
            
            whitelist_filter_response = requests.post(filters_url, headers=headers, json=[whitelist_filter_payload], timeout=10)
            
            if whitelist_filter_response.status_code != 200:
                result = whitelist_filter_response.json()
                errors = result.get('errors', [])
                error_msg = errors[0].get('message', '创建白名单过滤器失败') if errors else '创建白名单过滤器失败'
                return False, f"创建白名单过滤器失败: {error_msg}"
            
            whitelist_filter_result = whitelist_filter_response.json()
            if not whitelist_filter_result.get('success'):
                errors = whitelist_filter_result.get('errors', [])
                error_msg = errors[0].get('message', '创建白名单过滤器失败') if errors else '创建白名单过滤器失败'
                return False, f"创建白名单过滤器失败: {error_msg}"
            
            whitelist_filter_id = whitelist_filter_result['result'][0]['id']
            
            # 创建白名单防火墙规则
            whitelist_rule_payload = {
                'filter': {'id': whitelist_filter_id},
                'action': 'allow',
                'description': whitelist_notes
            }
            
            whitelist_rule_response = requests.post(rules_url, headers=headers, json=[whitelist_rule_payload], timeout=10)
            
            if whitelist_rule_response.status_code != 200:
                try:
                    requests.delete(f"{filters_url}/{whitelist_filter_id}", headers=headers, timeout=5)
                except:
                    pass
                result = whitelist_rule_response.json()
                errors = result.get('errors', [])
                error_msg = errors[0].get('message', '创建白名单规则失败') if errors else '创建白名单规则失败'
                return False, f"创建白名单规则失败: {error_msg}"
            
            whitelist_rule_result = whitelist_rule_response.json()
            if not whitelist_rule_result.get('success'):
                try:
                    requests.delete(f"{filters_url}/{whitelist_filter_id}", headers=headers, timeout=5)
                except:
                    pass
                errors = whitelist_rule_result.get('errors', [])
                error_msg = errors[0].get('message', '创建白名单规则失败') if errors else '创建白名单规则失败'
                return False, f"创建白名单规则失败: {error_msg}"
            
            # 2.2 创建合并的黑名单规则：所有其他IP对所有子域名黑名单
            # 构建排除所有白名单IP的表达式
            not_ip_conditions = ' and '.join([f'not (ip.src eq {ip})' for ip in ip_list])
            blacklist_expression = f'({host_conditions}) and ({not_ip_conditions})'
            blacklist_notes = f"Auto-added blacklist for all subdomains (block all IPs except {ips_str}): {domains_str}"
            
            # 创建黑名单过滤器
            blacklist_filter_payload = {
                'expression': blacklist_expression,
                'description': blacklist_notes
            }
            
            blacklist_filter_response = requests.post(filters_url, headers=headers, json=[blacklist_filter_payload], timeout=10)
            
            if blacklist_filter_response.status_code != 200:
                # 如果黑名单创建失败，尝试删除已创建的白名单规则和过滤器
                try:
                    whitelist_rule_id = whitelist_rule_result['result'][0]['id']
                    requests.delete(f"{rules_url}/{whitelist_rule_id}", headers=headers, timeout=5)
                except:
                    pass
                try:
                    requests.delete(f"{filters_url}/{whitelist_filter_id}", headers=headers, timeout=5)
                except:
                    pass
                result = blacklist_filter_response.json()
                errors = result.get('errors', [])
                error_msg = errors[0].get('message', '创建黑名单过滤器失败') if errors else '创建黑名单过滤器失败'
                return False, f"创建黑名单过滤器失败: {error_msg}"
            
            blacklist_filter_result = blacklist_filter_response.json()
            if not blacklist_filter_result.get('success'):
                # 如果黑名单创建失败，尝试删除已创建的白名单规则和过滤器
                try:
                    whitelist_rule_id = whitelist_rule_result['result'][0]['id']
                    requests.delete(f"{rules_url}/{whitelist_rule_id}", headers=headers, timeout=5)
                except:
                    pass
                try:
                    requests.delete(f"{filters_url}/{whitelist_filter_id}", headers=headers, timeout=5)
                except:
                    pass
                errors = blacklist_filter_result.get('errors', [])
                error_msg = errors[0].get('message', '创建黑名单过滤器失败') if errors else '创建黑名单过滤器失败'
                return False, f"创建黑名单过滤器失败: {error_msg}"
            
            blacklist_filter_id = blacklist_filter_result['result'][0]['id']
            
            # 创建黑名单防火墙规则
            blacklist_rule_payload = {
                'filter': {'id': blacklist_filter_id},
                'action': 'block',
                'description': blacklist_notes
            }
            
            blacklist_rule_response = requests.post(rules_url, headers=headers, json=[blacklist_rule_payload], timeout=10)
            
            if blacklist_rule_response.status_code != 200:
                # 如果黑名单规则创建失败，尝试删除已创建的所有资源
                try:
                    whitelist_rule_id = whitelist_rule_result['result'][0]['id']
                    requests.delete(f"{rules_url}/{whitelist_rule_id}", headers=headers, timeout=5)
                except:
                    pass
                try:
                    requests.delete(f"{filters_url}/{whitelist_filter_id}", headers=headers, timeout=5)
                except:
                    pass
                try:
                    requests.delete(f"{filters_url}/{blacklist_filter_id}", headers=headers, timeout=5)
                except:
                    pass
                result = blacklist_rule_response.json()
                errors = result.get('errors', [])
                error_msg = errors[0].get('message', '创建黑名单规则失败') if errors else '创建黑名单规则失败'
                return False, f"创建黑名单规则失败: {error_msg}"
            
            blacklist_rule_result = blacklist_rule_response.json()
            if not blacklist_rule_result.get('success'):
                # 如果黑名单规则创建失败，尝试删除已创建的所有资源
                try:
                    whitelist_rule_id = whitelist_rule_result['result'][0]['id']
                    requests.delete(f"{rules_url}/{whitelist_rule_id}", headers=headers, timeout=5)
                except:
                    pass
                try:
                    requests.delete(f"{filters_url}/{whitelist_filter_id}", headers=headers, timeout=5)
                except:
                    pass
                try:
                    requests.delete(f"{filters_url}/{blacklist_filter_id}", headers=headers, timeout=5)
                except:
                    pass
                errors = blacklist_rule_result.get('errors', [])
                error_msg = errors[0].get('message', '创建黑名单规则失败') if errors else '创建黑名单规则失败'
                return False, f"创建黑名单规则失败: {error_msg}"
            
            # 成功创建所有规则
            return True, f"成功：{ips_str}"
                        
        except Exception as e:
            return False, f"处理失败: {str(e)}"

    except requests.exceptions.RequestException as e:
        return False, f"请求 Cloudflare API 失败: {str(e)}"
    except Exception as e:
        return False, f"处理失败: {str(e)}"


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=CONFIG['port'], debug=False)
