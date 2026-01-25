const socket = io();
let timerInterval;

function selectRole(role) {
    document.getElementById('role-selection').classList.add('hidden');
    document.getElementById(role + '-ui').classList.remove('hidden');
    if(role === 'host') socket.emit('host_connect');
}

// ================== HOST LOGIC ==================
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
    document.getElementById('qr-display').innerHTML = `<img src="data:image/png;base64,${d.qr}" style="width:180px" class="shadow rounded border">`;
});

socket.on('player_waiting', d => {
    const list = document.getElementById('waiting-list');
    if(document.getElementById("wait-" + d.sid)) return;
    const div = document.createElement('div');
    div.id = "wait-" + d.sid;
    div.className = "lb-item";
    div.innerHTML = `<span><b>${d.name}</b></span> <button class="btn btn-sm btn-success px-3" onclick="approve('${d.sid}')">Duyệt</button>`;
    list.appendChild(div);
    document.getElementById('btn-start').disabled = false;
});

// Thêm hàm duyệt từng người cho Host
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
    document.getElementById('host-live-monitor').classList.remove('hidden');
}

// ================== USER LOGIC ==================
function userJoin() {
    const pin = document.getElementById('user-pin').value;
    const name = document.getElementById('user-name').value;
    if(!pin || !name) return alert("Thiếu PIN hoặc Tên!");
    socket.emit('join_game', { pin, name });
    document.getElementById('user-login').classList.add('hidden');
    document.getElementById('user-waiting').classList.remove('hidden');
}

socket.on('player_approved', () => {
    document.getElementById('wait-status-text').innerText = "ĐÃ ĐƯỢC DUYỆT! CHỜ GIÁO VIÊN BẮT ĐẦU...";
    document.getElementById('wait-status-text').classList.add('text-success');
});

// ================== GAME ENGINE (PHẦN CHÍNH) ==================
socket.on('new_question', d => {
    // QUAN TRỌNG: Xóa sạch các lớp phủ thông báo câu trước (Cướp điểm/Spin)
    document.getElementById('event-overlay').classList.add('hidden');
    document.getElementById('user-waiting').classList.add('hidden');
    document.getElementById('user-review-screen').classList.add('hidden');
    document.getElementById('user-quiz-area').classList.remove('hidden');

    // Cập nhật màn hình Host Monitor
    const mText = document.getElementById('monitor-q-text');
    if(mText) {
        mText.innerText = d.question.q;
        document.getElementById('monitor-options').innerHTML = ['a','b','c','d'].map(o => `
            <div class="col-6"><div class="card p-2 border shadow-sm"><b>${o.toUpperCase()}.</b> ${d.question[o]}</div></div>`).join('');
    }

    // Cập nhật màn hình User Quiz
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
            // Khóa toàn bộ các nút sau khi đã chọn
            Array.from(opts.children).forEach(b => b.disabled = true);
            btn.style.backgroundColor = "#e7f3ff";
            btn.style.borderColor = "var(--primary)";
        };
        opts.appendChild(btn);
    });
    
    // Đồng bộ thời gian 15 giây
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
        
        if(left <= 0) {
            clearInterval(timerInterval);
            // Khóa nút nếu hết giờ mà chưa bấm
            const opts = document.getElementById('q-options');
            if(opts) Array.from(opts.children).forEach(b => b.disabled = true);
        }
        left--;
    };
    tick(); 
    timerInterval = setInterval(tick, 1000);
}

// ================== HIỆU ỨNG CƯỚP ĐIỂM & SPIN ==================
socket.on('steal_alert', d => {
    const overlay = document.getElementById('event-overlay');
    overlay.classList.remove('hidden');
    document.getElementById('event-content').innerHTML = `
        <div class="event-title steal-active">⚡ CƯỚP ĐIỂM ⚡</div>
        <h2 style="font-size: 3rem;">${d.thief}</h2>
        <p class="h4">Đã cướp <span class="text-warning">${d.points}đ</span> từ <b>${d.victim}</b>!</p>
        <p class="mt-3">Chuẩn bị câu tiếp theo...</p>`;
});

socket.on('fastest_notify', d => {
    const overlay = document.getElementById('event-overlay');
    overlay.classList.remove('hidden');
    document.getElementById('event-content').innerHTML = `
        <div class="event-title text-info">🚀 NHANH NHẤT 🚀</div>
        <h2>${d.name}</h2><p>Đang chuẩn bị Lucky Spin...</p>`;
});

socket.on('trigger_lucky_spin', () => {
    const overlay = document.getElementById('event-overlay');
    overlay.classList.remove('hidden');
    document.getElementById('event-content').innerHTML = `
        <div class="event-title spin-active">🎁 LUCKY SPIN 🎁</div>
        <div class="spin-wheel-ui mb-4 mx-auto"><h1 id="spin-val">?</h1><small>ĐIỂM THƯỞNG</small></div>
        <button id="btn-spin-action" class="btn btn-warning btn-lg fw-bold px-5" onclick="runSpin(this)">QUAY NGAY</button>`;
});

function runSpin(btn) {
    btn.disabled = true;
    let count = 0;
    const vals = [10, 20, 30, 50, 80, 100];
    const timer = setInterval(() => {
        const res = vals[Math.floor(Math.random()*vals.length)];
        document.getElementById('spin-val').innerText = res;
        if(count++ > 25) {
            clearInterval(timer);
            socket.emit('claim_spin', { points: res });
            document.getElementById('event-content').innerHTML += `<h3 class="text-warning mt-3">+${res} ĐIỂM!</h3>`;
        }
    }, 80);
}

// ================== BXH & REVIEW ==================
socket.on('update_leaderboard', list => {
    const container = document.getElementById('lb-host');
    if(!container) return;
    container.innerHTML = list.map((p, i) => `
        <div class="lb-item ${i===0?'bg-warning bg-opacity-10':''}">
            <span>${i===0?'🥇':i===1?'🥈':i===2?'🥉':'#'+(i+1)} <b>${p.name}</b></span>
            <span class="badge bg-primary rounded-pill">${p.score}đ</span>
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
        <div class="card p-3 mb-2 shadow-sm border-0 bg-light text-start">
            <p class="fw-bold mb-1">${i+1}. ${q.q}</p>
            <p class="text-success small mb-0"><b>Đáp án:</b> ${q.ans} | <b>Giải thích:</b> ${q.exp}</p>
        </div>`).join('');
});

socket.on('personal_review', d => {
    document.getElementById('user-quiz-area').classList.add('hidden');
    document.getElementById('user-review-screen').classList.remove('hidden');
    document.getElementById('user-review-list').innerHTML = d.history.map((h, i) => `
        <div class="review-item ${h.your_ans === h.correct_ans ? 'correct' : 'wrong'}">
            <p class="fw-bold mb-1">Câu ${i+1}: ${h.q}</p>
            <p class="small mb-0">Bạn chọn: ${h.your_ans || 'Bỏ trống'} | Đáp án: <b>${h.correct_ans}</b></p>
            <p class="text-muted italic mt-1" style="font-size: 0.85rem;">${h.exp}</p>
        </div>`).join('');
});

socket.on('round_ended', d => {
    const btn = document.getElementById('btn-start');
    if(btn) {
        btn.disabled = false;
        btn.innerText = `BẮT ĐẦU VÒNG ${d.round + 1}`;
    }
});
