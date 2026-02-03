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
    btnText.innerHTML = '<span class="loading"></span>PROCESSING...';

    // 验证IP输入
    if (!ipInput || !ipInput.trim()) {
        message.className = 'message error';
        message.textContent = 'ERROR: IP_ADDRESS_REQUIRED';
        message.style.display = 'block';
        submitBtn.disabled = false;
        btnText.textContent = '> EXECUTE';
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
        message.textContent = data.message || (data.success ? 'ACCESS_GRANTED' : 'ACCESS_DENIED');
        message.style.display = 'block';

        if (data.success) {
            document.getElementById('totpCode').value = '';
            // document.getElementById('ipInput').value = ''; // 既然自动获取IP，通常不需要清空，或者清空后重新填入当前IP？为了方便连续操作，保留或清空看习惯。这里保持原样清空吧。
            document.getElementById('ipInput').value = ''; 
        }
    } catch (error) {
        message.className = 'message error';
        message.textContent = 'SYSTEM_ERROR: CONNECTION_LOST';
        message.style.display = 'block';
        console.error('添加失败:', error);
    } finally {
        submitBtn.disabled = false;
        btnText.textContent = '> EXECUTE_OVERRIDE';
    }
});
