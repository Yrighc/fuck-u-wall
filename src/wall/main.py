# 标准库

# 三方库
import typer

# 这样保证了版本号和业务逻辑的一致性
# 本地库
from . import __version__, run_app

app = typer.Typer(
    add_completion=False,
    help="Wall_Demo: 一个轻量级的 Web 应用，用于自动将当前 IP 地址添加到 Cloudflare 的防火墙白名单中。",  # noqa: E501
)


@app.command()
def version():
    """
    显示当前系统版本。
    """
    # ✅ 变化 2: 读取导入的变量，而不是硬编码字符串
    print(f"Wall v{__version__}")


@app.command()
def start():
    """
    启动 Wall 应用程序。
    """
    run_app()  # 调用run_app函数来运行应用程序


def main():
    """
    程序的主入口函数
    该函数用于启动应用程序
    """
    app()


if __name__ == "__main__":
    main()
