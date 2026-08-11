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
    // 暴露给提交逻辑：脚本可能在提交时才刚加载完，需要再次尝试渲染（幂等）
    window._renderTurnstile = render;

    if (window.turnstile) {
        render();
        return;
    }
    // api.js 尚未加载完成：轮询等待（上限 20s；提交时另有兜底等待）
    const poll = window.setInterval(() => {
        if (window.turnstile) {
            window.clearInterval(poll);
            render();
        }
    }, 200);
    window.setTimeout(() => window.clearInterval(poll), 20000);
})();

// 等待 Turnstile 令牌就绪（覆盖脚本慢加载 / 挑战未完成），最多 TURNSTILE_WAIT_MS。
// 返回令牌字符串；超时返回 ''（此时给明确错误，而不是发一个空令牌的请求）。
const TURNSTILE_WAIT_MS = 12000;

function waitForTurnstileToken() {
    return new Promise((resolve) => {
        const readToken = () => {
            const w = window._turnstileWidgetId;
            return w !== null && window.turnstile ? window.turnstile.getResponse(w) : '';
        };
        let token = readToken();
        if (token) {
            resolve(token);
            return;
        }
        const deadline = Date.now() + TURNSTILE_WAIT_MS;
        const poll = window.setInterval(() => {
            if (typeof window._renderTurnstile === 'function') window._renderTurnstile();
            token = readToken();
            if (token) {
                window.clearInterval(poll);
                resolve(token);
            } else if (Date.now() > deadline) {
                window.clearInterval(poll);
                resolve('');
            }
        }, 250);
    });
}

// 添加到白名单
const whitelistForm = document.getElementById('whitelistForm');
whitelistForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const totpCode = document.getElementById('totpCode').value;
    const ipInput = document.getElementById('ipInput').value.trim();
    const submitBtn = document.getElementById('submitBtn');
    const btnText = document.getElementById('btnText');
    const message = document.getElementById('message');

    // 禁用按钮并显示加载状态
    submitBtn.disabled = true;
    btnText.innerHTML = '<span class="loading"></span>PROCESSING...';

    // 验证IP输入（先于等待，避免无效输入还空等验证）
    if (!ipInput || !ipInput.trim()) {
        message.className = 'status-text message error';
        message.textContent = 'ERROR: IP_ADDRESS_REQUIRED';
        message.style.display = 'block';
        submitBtn.disabled = false;
        btnText.textContent = 'AUTHORIZE ACCESS';
        return;
    }

    // Turnstile：等待组件加载 / 挑战完成（最长 TURNSTILE_WAIT_MS），拿到令牌再提交
    btnText.innerHTML = '<span class="loading"></span>AWAITING VERIFICATION...';
    message.className = 'status-text message';
    message.textContent = 'Security Verification Loading...';
    message.style.display = 'block';
    const turnstileToken = await waitForTurnstileToken();
    if (!turnstileToken) {
        message.className = 'status-text message error';
        message.textContent = 'ERROR: VERIFICATION_TIMEOUT - 请完成页面上的验证或刷新重试';
        message.style.display = 'block';
        submitBtn.disabled = false;
        btnText.textContent = 'AUTHORIZE ACCESS';
        return;
    }
    btnText.innerHTML = '<span class="loading"></span>PROCESSING...';

    // 提交时读取当时的 widgetId，供 finally 重置（等待期间可能才渲染出来）
    const widgetId = window._turnstileWidgetId;

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
