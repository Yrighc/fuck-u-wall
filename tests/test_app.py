import pytest

from wall.app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    # 设置必要的环境变量模拟
    # 在实际测试中，可能需要 mock 掉 settings 或环境变量
    with app.test_client() as client:
        yield client


def test_index_page(client):
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


def test_manifest_json(client):
    """测试 Manifest 文件"""
    response = client.get("/manifest.json")
    assert response.status_code == 200
    assert response.is_json
    data = response.get_json()
    assert data["name"] == "IP 白名单管理"
