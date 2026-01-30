// 添加到白名单
document.getElementById('whitelistForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const totpCode = document.getElementById('totpCode').value;
    const ipInput = document.getElementById('ipInput').value.trim();
    const submitBtn = document.getElementById('submitBtn');
    const btnText = document.getElementById('btnText');
    const message = document.getElementById('message');

    // 禁用按钮并显示加载状态
    submitBtn.disabled = true;
    btnText.innerHTML = '<span class="loading"></span>处理中...';

    // 验证IP输入
    if (!ipInput || !ipInput.trim()) {
        message.className = 'message error';
        message.textContent = '请输入IP地址';
        message.style.display = 'block';
        submitBtn.disabled = false;
        btnText.textContent = '添加到白名单';
        return;
    }

    try {
        const requestBody = {
            totp_code: totpCode,
            ips: ipInput.trim()
        };

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
            document.getElementById('ipInput').value = '';
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
