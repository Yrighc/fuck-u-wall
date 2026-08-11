import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import ValidationError, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 定义根目录，方便定位 .env 文件
ROOT_DIR = Path(__file__).parents[2]

# print(f"Config root dir: {ROOT_DIR}")

class Settings(BaseSettings):
    # 1. 环境标识：决定加载哪个配置策略
    # 启动时需设置环境变量 APP_ENV=prod 或 dev
    app_env: Literal["dev", "prod"] = "dev"

    # 2. 基础设施配置 (利用 Pydantic 的类型校验)
    # 如果 .env 里写错了格式，启动时会直接报错，阻断风险
    # totp 密钥 (用于生成动态验证码)
    # 可以使用 pyotp.random_base32() 生成，或使用页面上的二维码/密钥
    port: int = 8080  # 应用监听端口，默认 8080
    # 监听地址：Docker/公网部署保持 0.0.0.0；本机开发建议 127.0.0.1
    # （macOS 绑定 0.0.0.0 会触发“本地网络”权限检查，导致启动卡十几秒）
    host: str = "0.0.0.0"
    totp_secret: str

    # Cloudflare Api Token (需要有编辑防火墙规则的权限)
    cloudflare_api_token: str

    # Cloudflare Zone ID (域名对应的 Zone ID，可以在 Cloudflare 仪表盘查看)
    cloudflare_zone_id: str

    # 子域名 （必填，支持多个用逗号分割，如 api.example.com,admin.example.com)
    subdomain: str

    # TOTP 爆破防护：单个客户端 IP 在窗口内允许的最大失败次数，达到后锁定
    max_failed_attempts: int = 5
    # 锁定时长（分钟）
    lockout_minutes: int = 15

    # Turnstile 人机验证（必填）：前端站点 key 与后端密钥
    turnstile_sitekey: str = ""
    turnstile_secret: str = ""
    # 允许的前端域名白名单（逗号分隔，对应 siteverify 返回的 hostname 字段）
    turnstile_hostnames: str = ""

    # 4. 计算属性 (衍生配置)
    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        return self.app_env == "prod"

    # 5. 核心配置：动态加载 .env
    model_config = SettingsConfigDict(
        # 这里的逻辑是：
        # 如果系统设置了 APP_ENV，它会优先去读 .env.{app_env}
        # 如果没找到文件，就忽略（生产环境可能完全依赖 K8s 环境变量注入）
        env_file=ROOT_DIR / f".env.{os.getenv('APP_ENV', 'dev')}",
        env_file_encoding="utf-8",
        case_sensitive=False,  # 允许 DATABASE_URL (env) 映射到 database_url (field)
        extra="ignore",  # 忽略 .env 中多余的字段，保持清爽
    )


# 这里可以在实例化前打印一下，确保读对文件了
# print(f"Loading config for: {os.getenv('APP_ENV', 'dev')}")

@lru_cache
def get_settings() -> Settings:
    """
    获取配置单例。
    懒加载模式：只有在第一次调用时才会读取环境变量并实例化 Settings。
    这样可以避免在 Docker 构建或 CI 环境中（仅做导入检查时）因缺少环境变量而报错。
    """
    try:
        return Settings()  # pyright: ignore[reportCallIssue]
    except ValidationError as e:
        # 捕获校验错误，进行自定义渲染
        print("\n❌ \033[91m配置加载失败 (Configuration Error)\033[0m")
        print("--------------------------------------------------")
        print(f"配置文件路径: {ROOT_DIR}")  # 如果你有变量存路径的话
        print("检测到以下必填参数缺失或格式错误：\n")
        # 遍历错误列表，提取字段名
        for error in e.errors():
            # error['loc'] 通常是 ('field_name',)
            field_name = error["loc"][0]
            msg = error["msg"]
            print(f"  • \033[93m{field_name}\033[0m: {msg}")

        print("\n💡 \033[92m请检查你的 .env 文件，或参考 .env.example 补全配置。\033[0m")
        print("--------------------------------------------------")

        # 关键：使用 sys.exit(1) 终止程序，避免抛出难看的 Traceback
        sys.exit(1)

if __name__ == "__main__":
    print(get_settings().model_dump())
