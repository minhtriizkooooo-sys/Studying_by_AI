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
    document.getElementById('qr-display').innerHTML = `<img src="data:image/png;base64,${d.qr}" style="width:180px">`;
});

socket.on('player_waiting', d => {
    const list = document.getElementById('waiting-list');
    if(document.getElementById("wait-" + d.sid)) return;
    const div = document.createElement('div');
    div.id = "wait-" + d.sid;
    div.className = "lb-item";
    div.innerHTML = `<span><b>${d.name}</b></span> <button class="btn btn-sm btn-success" onclick="approve('${d.sid}')">Duyệt</button>`;
    list.appendChild(div);
    document.getElementById('btn-start').disabled = false;
});

function approve(sid) {
    socket.emit('host_approve_player', { sid });
    document.getElementById("wait-" + sid)?.remove();
}

function approveAll() {
    socket.emit('host_approve_all');
    document.getElementById('waiting-list').innerHTML = "";
}

function startRound() {
    socket.emit('start_round');
    document.getElementById('host-lobby').classList.add('hidden');
    document.getElementById('host-review-screen').classList.add('hidden');
}

// USER LOGIC
function userJoin() {
    const pin = document.getElementById('user-pin').value;
    const name = document.getElementById('user-name').value;
    if(!pin || !name) return alert("Thiếu PIN hoặc Tên!");
    socket.emit('join_game', { pin, name });
    document.getElementById('user-login').classList.add('hidden');
    document.getElementById('user-waiting').classList.remove('hidden');
}

socket.on('player_approved', () => {
    document.getElementById('wait-status-text').innerText = "ĐÃ ĐƯỢC DUYỆT! CHỜ GIÁO VIÊN...";
});

// GAME ENGINE
socket.on('new_question', d => {
    // TẮT OVERLAY KHI SANG CÂU MỚI
    document.getElementById('event-overlay').classList.add('hidden');
    document.getElementById('user-waiting').classList.add('hidden');
    document.getElementById('user-review-screen').classList.add('hidden');
    document.getElementById('user-quiz-area').classList.remove('hidden');
    document.getElementById('host-live-monitor')?.classList.remove('hidden');

    // Cập nhật Host Monitor
    const mText = document.getElementById('monitor-q-text');
    if(mText) {
        mText.innerText = d.question.q;
        document.getElementById('monitor-options').innerHTML = ['a','b','c','d'].map(o => `
            <div class="col-6"><div class="card p-2 border shadow-sm"><b>${o.toUpperCase()}.</b> ${d.question[o]}</div></div>`).join('');
    }

    // Cập nhật User Quiz
    document.getElementById('q-idx').innerText = `Câu ${d.index}/${d.total}`;
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
            btn.classList.add('btn-primary');
            btn.classList.remove('btn-ans');
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
        if(document.getElementById('monitor-time')) document.getElementById('monitor-time').innerText = left;
        if(left <= 0) clearInterval(timerInterval);
        left--;
    };
    tick(); timerInterval = setInterval(tick, 1000);
}

// EVENTS
socket.on('steal_alert', d => {
    const overlay = document.getElementById('event-overlay');
    overlay.classList.remove('hidden');
    document.getElementById('event-content').innerHTML = `
        <div class="event-title steal-active">⚡ CƯỚP ĐIỂM ⚡</div>
        <h2>${d.thief}</h2>
        <p>Đã cướp <span class="text-warning">${d.points}đ</span> từ <b>${d.victim}</b>!</p>`;
});

socket.on('fastest_notify', d => {
    const overlay = document.getElementById('event-overlay');
    overlay.classList.remove('hidden');
    document.getElementById('event-content').innerHTML = `
        <div class="event-title text-info">🚀 NHANH NHẤT 🚀</div>
        <h2>${d.name}</h2><p>Chuẩn bị Lucky Spin...</p>`;
});

socket.on('trigger_lucky_spin', () => {
    const overlay = document.getElementById('event-overlay');
    overlay.classList.remove('hidden');
    document.getElementById('event-content').innerHTML = `
        <div class="event-title spin-active">🎁 LUCKY SPIN 🎁</div>
        <div class="spin-wheel-ui mb-4 mx-auto"><h1 id="spin-val">?</h1></div>
        <button class="btn btn-warning btn-lg fw-bold" onclick="runSpin(this)">QUAY</button>`;
});

function runSpin(btn) {
    btn.disabled = true;
    let count = 0;
    const vals = [10, 20, 30, 50, 80, 100];
    const timer = setInterval(() => {
        const res = vals[Math.floor(Math.random()*vals.length)];
        document.getElementById('spin-val').innerText = res;
        if(count++ > 20) {
            clearInterval(timer);
            socket.emit('claim_spin', { points: res });
        }
    }, 100);
}

socket.on('update_leaderboard', list => {
    const container = document.getElementById('lb-host');
    if(!container) return;
    container.innerHTML = list.map((p, i) => `
        <div class="lb-item">
            <span>${i+1}. <b>${p.name}</b></span>
            <span class="badge bg-primary">${p.score}đ</span>
        </div>`).join('');
});

socket.on('personal_score', d => {
    if(document.getElementById('u-score')) document.getElementById('u-score').innerText = d.score + "đ";
    if(document.getElementById('u-rank')) document.getElementById('u-rank').innerText = d.rank ? "#" + d.rank : "";
});

socket.on('round_review', d => {
    document.getElementById('host-live-monitor').classList.add('hidden');
    document.getElementById('host-review-screen').classList.remove('hidden');
    document.getElementById('host-review-list').innerHTML = d.questions.map((q, i) => `
        <div class="card p-2 mb-2 bg-light">
            <p class="fw-bold mb-0">${i+1}. ${q.q}</p>
            <small class="text-success">Đáp án: ${q.ans} | ${q.exp}</small>
        </div>`).join('');
});

socket.on('personal_review', d => {
    document.getElementById('user-quiz-area').classList.add('hidden');
    document.getElementById('user-review-screen').classList.remove('hidden');
    document.getElementById('user-review-list').innerHTML = d.history.map((h, i) => `
        <div class="review-item ${h.your_ans === h.correct_ans ? 'correct' : 'wrong'}">
            <p class="fw-bold mb-0">Câu ${i+1}: ${h.q}</p>
            <p class="small mb-0">Bạn: ${h.your_ans} | Đáp án: ${h.correct_ans}</p>
            <p class="text-muted x-small">${h.exp}</p>
        </div>`).join('');
});

socket.on('round_ended', d => {
    const btn = document.getElementById('btn-start');
    if(btn) {
        btn.disabled = false;
        btn.innerText = `BẮT ĐẦU VÒNG ${d.round + 1}`;
    }
});
