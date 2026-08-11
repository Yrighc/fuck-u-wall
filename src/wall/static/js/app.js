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

// Turnstile：显式渲染并保留 widgetId，提交后调用 turnstile.reset(widgetId) 供重试
// 注意：api.js 是 async 加载，可能在 app.js 执行时尚未就绪，必须等待/轮询
(function initTurnstile() {
    const widgetEl = document.getElementById('turnstile-widget');
    window._turnstileWidgetId = null;
    if (!widgetEl || !widgetEl.dataset.sitekey) return;

    const render = () => {
        if (window._turnstileWidgetId !== null || !window.turnstile) return;
        window._turnstileWidgetId = window.turnstile.render(widgetEl, {
            sitekey: widgetEl.dataset.sitekey,
            action: widgetEl.dataset.action || 'whitelist',
        });
    };

    if (window.turnstile) {
        render();
        return;
    }
    // api.js 尚未加载完成：轮询等待（最多 10s，避免无限轮询）
    const poll = window.setInterval(() => {
        if (window.turnstile) {
            window.clearInterval(poll);
            render();
        }
    }, 200);
    window.setTimeout(() => window.clearInterval(poll), 10000);
})();

// 添加到白名单
const whitelistForm = document.getElementById('whitelistForm');
whitelistForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const totpCode = document.getElementById('totpCode').value;
    const ipInput = document.getElementById('ipInput').value.trim();
    const submitBtn = document.getElementById('submitBtn');
    const btnText = document.getElementById('btnText');
    const message = document.getElementById('message');
    const widgetId = window._turnstileWidgetId;

    // 禁用按钮并显示加载状态
    submitBtn.disabled = true;
    btnText.innerHTML = '<span class="loading"></span>PROCESSING...';

    // Turnstile：未完成人机验证不允许提交
    const turnstileToken =
        widgetId !== null && window.turnstile ? window.turnstile.getResponse(widgetId) : '';
    if (!turnstileToken) {
        message.className = 'status-text message error';
        message.textContent = 'ERROR: VERIFICATION_REQUIRED';
        message.style.display = 'block';
        submitBtn.disabled = false;
        btnText.textContent = 'AUTHORIZE ACCESS';
        return;
    }

    // 验证IP输入
    if (!ipInput || !ipInput.trim()) {
        message.className = 'status-text message error';
        message.textContent = 'ERROR: IP_ADDRESS_REQUIRED';
        message.style.display = 'block';
        submitBtn.disabled = false;
        btnText.textContent = 'AUTHORIZE ACCESS';
        return;
    }

    let requestSent = false;
    try {
        const requestBody = {
            totp_code: totpCode,
            ips: ipInput.trim(),
            cf_turnstile_response: turnstileToken
        };

        requestSent = true;
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
            document.getElementById('ipInput').value = '';
        }
    } catch (error) {
        message.className = 'status-text message error';
        message.textContent = 'SYSTEM_ERROR: CONNECTION_LOST';
        message.style.display = 'block';
        console.error('添加失败:', error);
    } finally {
        // Turnstile 令牌单次有效：只要发出过请求就重置 widget（含网络异常路径），
        // 避免下次提交复用已被消耗的令牌
        if (requestSent && widgetId !== null && window.turnstile) {
            window.turnstile.reset(widgetId);
        }
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
