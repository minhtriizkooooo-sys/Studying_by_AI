const socket = io();
let timerInterval;

function selectRole(role) {
    document.getElementById('role-selection').classList.add('hidden');
    document.getElementById(role + '-ui').classList.remove('hidden');
    if(role === 'host') socket.emit('host_connect');
}

// HOST LOGIC
document.getElementById('file-input')?.addEventListener('change', (e) => {
    const file = e.target.files[0];
    const reader = new FileReader();
    reader.onload = () => socket.emit('host_upload_file', { content: reader.result, name: file.name });
    reader.readAsDataURL(file);
});

socket.on('qr_ready', d => {
    document.getElementById('host-setup').classList.add('hidden');
    document.getElementById('host-lobby').classList.remove('hidden');
    document.getElementById('display-pin').innerText = d.pin;
    document.getElementById('qr-display').innerHTML = `<img src="data:image/png;base64,${d.qr}" style="width:200px" class="shadow rounded border">`;
});

function startRound() { socket.emit('start_round'); }

// USER LOGIC
function userJoin() {
    const pin = document.getElementById('user-pin').value;
    const name = document.getElementById('user-name').value;
    if(!pin || !name) return alert("Nhập đủ PIN và Tên!");
    socket.emit('join_game', { pin, name });
    document.getElementById('user-login').classList.add('hidden');
    document.getElementById('user-waiting').classList.remove('hidden');
}

// GAME EVENTS
socket.on('new_question', d => {
    document.getElementById('event-overlay').classList.add('hidden');
    document.getElementById('user-waiting').classList.add('hidden');
    document.getElementById('user-quiz-area').classList.remove('hidden');
    document.getElementById('host-live-monitor')?.classList.remove('hidden');
    document.getElementById('host-lobby')?.classList.add('hidden');

    // Cập nhật câu hỏi
    document.getElementById('q-text').innerText = d.question.q;
    const opts = document.getElementById('q-options');
    opts.innerHTML = '';
    ['a','b','c','d'].forEach(o => {
        const btn = document.createElement('button');
        btn.className = "btn btn-ans shadow-sm";
        btn.innerHTML = `<b>${o.toUpperCase()}.</b> ${d.question[o]}`;
        btn.onclick = () => {
            socket.emit('submit_answer', { ans: o });
            Array.from(opts.children).forEach(b => b.disabled = true);
            btn.style.background = "#eef6ff";
        };
        opts.appendChild(btn);
    });
    startCountdown(d.timer);
});

function startCountdown(sec) {
    clearInterval(timerInterval);
    let left = sec;
    const tick = () => {
        const pct = (left / sec) * 100;
        if(document.getElementById('user-timer-bar')) document.getElementById('user-timer-bar').style.width = pct + "%";
        if(document.getElementById('host-timer-bar')) document.getElementById('host-timer-bar').style.width = pct + "%";
        if(left <= 0) clearInterval(timerInterval);
        left--;
    };
    tick(); timerInterval = setInterval(tick, 1000);
}

// SPECIAL EVENTS: STEAL & SPIN
socket.on('steal_alert', d => {
    const overlay = document.getElementById('event-overlay');
    overlay.classList.remove('hidden');
    document.getElementById('event-content').innerHTML = `
        <div class="event-title steal-active">⚡ CƯỚP ĐIỂM ⚡</div>
        <h2>${d.thief}</h2>
        <p>Đã cướp <span class="text-warning">${d.points}đ</span> từ ${d.victim}!</p>`;
});

socket.on('trigger_lucky_spin', () => {
    const overlay = document.getElementById('event-overlay');
    overlay.classList.remove('hidden');
    document.getElementById('event-content').innerHTML = `
        <div class="event-title spin-active">🎁 LUCKY SPIN 🎁</div>
        <div class="spin-wheel-ui mb-4"><h1 id="spin-val">?</h1><small>ĐIỂM</small></div>
        <button class="btn btn-warning btn-lg fw-bold" onclick="runSpin(this)">QUAY NGAY</button>`;
});

function runSpin(btn) {
    btn.disabled = true;
    let count = 0;
    const vals = [10, 20, 50, 100, 150];
    const timer = setInterval(() => {
        const res = vals[Math.floor(Math.random()*vals.length)];
        document.getElementById('spin-val').innerText = res;
        if(count++ > 20) {
            clearInterval(timer);
            socket.emit('claim_spin', { points: res });
            setTimeout(() => document.getElementById('event-overlay').classList.add('hidden'), 2000);
        }
    }, 100);
}

socket.on('update_leaderboard', list => {
    const container = document.getElementById('lb-host');
    if(!container) return;
    container.innerHTML = list.map((p, i) => `
        <div class="lb-item d-flex justify-content-between p-2 border-bottom">
            <span>${i+1}. <b>${p.name}</b></span>
            <span class="badge bg-primary">${p.score}đ</span>
        </div>`).join('');
});
