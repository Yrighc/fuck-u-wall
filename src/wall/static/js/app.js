// 6 格 TOTP 输入：自动跳格 / 退格回退 / 粘贴分发，并同步到隐藏字段 #totpCode
(function initTotpBoxes() {
    const boxes = Array.from(document.querySelectorAll('.totp-input'));
    const hidden = document.getElementById('totpCode');
    if (!boxes.length || !hidden) return;

    const sync = () => {
        hidden.value = boxes.map((b) => b.value).join('');
    };

    boxes.forEach((box, index) => {
        box.addEventListener('input', () => {
            box.value = box.value.replace(/\D/g, '').slice(-1);
            if (box.value && index < boxes.length - 1) {
                boxes[index + 1].focus();
            }
            sync();
        });

        box.addEventListener('keydown', (e) => {
            if (e.key === 'Backspace' && !box.value && index > 0) {
                boxes[index - 1].focus();
            }
        });

        box.addEventListener('paste', (e) => {
            e.preventDefault();
            const digits = (e.clipboardData.getData('text') || '').replace(/\D/g, '');
            digits.slice(0, boxes.length).split('').forEach((d, i) => {
                boxes[i].value = d;
            });
            boxes[Math.min(digits.length, boxes.length) - 1]?.focus();
            sync();
        });
    });
})();

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
        message.className = 'status-text message error';
        message.textContent = 'ERROR: IP_ADDRESS_REQUIRED';
        message.style.display = 'block';
        submitBtn.disabled = false;
        btnText.textContent = 'AUTHORIZE ACCESS';
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
        message.className = 'status-text message ' + (data.success ? 'success' : 'error');
        message.textContent = data.message || (data.success ? 'ACCESS_GRANTED' : 'ACCESS_DENIED');
        message.style.display = 'block';

        if (data.success) {
            document.getElementById('totpCode').value = '';
            document.querySelectorAll('.totp-input').forEach((b) => { b.value = ''; });
            // document.getElementById('ipInput').value = ''; // 既然自动获取IP，通常不需要清空，或者清空后重新填入当前IP？为了方便连续操作，保留或清空看习惯。这里保持原样清空吧。
            document.getElementById('ipInput').value = '';
        }
    } catch (error) {
        message.className = 'status-text message error';
        message.textContent = 'SYSTEM_ERROR: CONNECTION_LOST';
        message.style.display = 'block';
        console.error('添加失败:', error);
    } finally {
        submitBtn.disabled = false;
        btnText.textContent = 'AUTHORIZE ACCESS';
    }
});

// 状态栏时钟（HH:MM:SS）
(function initStatusClock() {
    const clock = document.getElementById('statusClock');
    if (!clock) return;
    const tick = () => {
        const now = new Date();
        clock.textContent = [now.getHours(), now.getMinutes(), now.getSeconds()]
            .map((n) => String(n).padStart(2, '0'))
            .join(':');
    };
    tick();
    setInterval(tick, 1000);
})();
