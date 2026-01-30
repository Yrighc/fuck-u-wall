import os
from pathlib import Path
from typing import Literal

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 定义根目录，方便定位 .env 文件
ROOT_DIR = Path(__file__).parents[2]

print(f"Config root dir: {ROOT_DIR}")


class Settings(BaseSettings):
    # 1. 环境标识：决定加载哪个配置策略
    # 启动时需设置环境变量 APP_ENV=prod 或 dev
    app_env: Literal["dev", "prod"] = "dev"

    # 2. 基础设施配置 (利用 Pydantic 的类型校验)
    # 如果 .env 里写错了格式，启动时会直接报错，阻断风险
    # totp 密钥 (用于生成动态验证码)
    # 可以使用 pyotp.random_base32() 生成，或使用页面上的二维码/密钥
    port: int
    totp_secret: str

    # Cloudflare Api Token (需要有编辑防火墙规则的权限)
    cloudflare_api_token: str

    # Cloudflare Zone ID (域名对应的 Zone ID，可以在 Cloudflare 仪表盘查看)
    cloudflare_zone_id: str

    # 子域名 （必填，支持多个用逗号分割，如 api.example.com,admin.example.com)
    subdomain: str

    # 4. 计算属性 (衍生配置)
    @computed_field
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
# 创建单例对象
settings = Settings()  # pyright: ignore[reportCallIssue]

if __name__ == "__main__":
    print(settings.model_dump())
