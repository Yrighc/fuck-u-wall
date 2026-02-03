const canvas = document.getElementById('matrixCanvas');
const ctx = canvas.getContext('2d');

// 设置 Canvas 全屏
function resizeCanvas() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
}
window.addEventListener('resize', resizeCanvas);
resizeCanvas();

// 矩阵字符配置
const chars = '01ABCDEFGHIJKLMNOPQRSTUVWXYZ';
const charArray = chars.split('');
const fontSize = 14;
const columns = canvas.width / fontSize;

// 每一列的当前 Y 坐标
const drops = [];
for (let i = 0; i < columns; i++) {
    drops[i] = 1;
}

// 绘制函数
function draw() {
    // 每一帧都用半透明黑色覆盖上一帧，形成拖尾效果
    ctx.fillStyle = 'rgba(5, 5, 5, 0.05)';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    ctx.fillStyle = '#0F0'; // 经典的黑客绿
    ctx.font = fontSize + 'px monospace';

    for (let i = 0; i < drops.length; i++) {
        // 随机取字符
        const text = charArray[Math.floor(Math.random() * charArray.length)];
        
        // 绘制字符
        // x = 列号 * 字体大小
        // y = 当前下落进度 * 字体大小
        ctx.fillText(text, i * fontSize, drops[i] * fontSize);

        // 如果掉出屏幕或随机重置，则回到顶部
        if (drops[i] * fontSize > canvas.height && Math.random() > 0.975) {
            drops[i] = 0;
        }

        // Y 坐标增加
        drops[i]++;
    }
}

// 启动动画，33ms 约 30fps
setInterval(draw, 33);
