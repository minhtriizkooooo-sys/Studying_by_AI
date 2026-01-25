const socket = io();
let timerInterval;
let myName = "";

function selectRole(role) {
    document.getElementById('role-selection').classList.add('hidden');
    document.getElementById(role + '-ui').classList.remove('hidden');
}

// --- HOST LOGIC ---
document.getElementById('file-input').onchange = function(e) {
    const file = e.target.files[0];
    const reader = new FileReader();
    document.getElementById('host-status').classList.remove('hidden');
    reader.onload = () => socket.emit('host_upload_file', { name: file.name, content: reader.result });
    reader.readAsDataURL(file);
};

socket.on('qr_ready', d => {
    document.getElementById('host-setup').classList.add('hidden');
    document.getElementById('host-lobby').classList.remove('hidden');
    document.getElementById('display-pin').innerText = d.pin;
    document.getElementById('qr-display').innerHTML = `<img src="data:image/png;base64,${d.qr}" style="width:180px">`;
});

socket.on('player_waiting', d => {
    const list = document.getElementById('waiting-list');
    const div = document.createElement('div');
    div.className = "d-flex justify-content-between align-items-center p-2 border-bottom text-dark";
    div.innerHTML = `<span><i class="fa fa-user"></i> ${d.name}</span> 
                     <button class="btn btn-sm btn-success" onclick="approve('${d.sid}', this)">Duyệt</button>`;
    list.appendChild(div);
});

function approve(sid, btn) {
    socket.emit('host_approve_player', { sid });
    btn.parentElement.remove();
}

function startRound() {
    socket.emit('start_round');
    document.getElementById('host-lobby').classList.add('hidden');
    document.getElementById('host-live-monitor').classList.remove('hidden');
}

// --- USER LOGIC ---
function userJoin() {
    const pin = document.getElementById('user-pin').value;
    myName = document.getElementById('user-name').value;
    if(!pin || !myName) return alert("Nhập đủ PIN và Tên!");
    socket.emit('join_game', { pin, name: myName });
    document.getElementById('user-login').classList.add('hidden');
    document.getElementById('user-waiting').classList.remove('hidden');
}

socket.on('player_approved', () => {
    const statusText = document.getElementById('wait-status-text');
    statusText.innerText = "ĐÃ ĐƯỢC DUYỆT! CHỜ GIÁO VIÊN BẮT ĐẦU...";
    statusText.style.color = "var(--success)";
});

// --- GAME ENGINE ---
socket.on('new_question', d => {
    // Tự động đóng Overlay khi sang câu mới
    document.getElementById('event-overlay').classList.add('hidden');
    document.getElementById('user-waiting').classList.add('hidden');
    document.getElementById('user-quiz-area').classList.remove('hidden');
    
    document.getElementById('q-idx').innerText = `Câu ${d.index}/${d.total}`;
    document.getElementById('q-text').innerText = d.question.q;
    if(document.getElementById('monitor-q-text')) document.getElementById('monitor-q-text').innerText = d.question.q;

    const opts = document.getElementById('q-options');
    opts.innerHTML = '';
    ['a','b','c','d'].forEach(o => {
        const btn = document.createElement('button');
        btn.className = "btn btn-ans";
        btn.innerHTML = `<b>${o.toUpperCase()}.</b> ${d.question[o]}`;
        btn.onclick = (e) => {
            disableOptions();
            socket.emit('submit_answer', { ans: o });
            const isCorrect = o.toUpperCase() === d.question.ans.toUpperCase();
            btn.style.borderColor = isCorrect ? "var(--success)" : "var(--danger)";
            btn.style.backgroundColor = isCorrect ? "#eafaf1" : "#fdedec";
        };
        opts.appendChild(btn);
    });

    startCountdown(d.timer || 15);
});

function startCountdown(seconds) {
    clearInterval(timerInterval);
    let timeLeft = seconds;
    const barU = document.getElementById('user-timer-bar');
    const barH = document.getElementById('host-timer-bar');
    const textH = document.getElementById('monitor-time');

    timerInterval = setInterval(() => {
        timeLeft--;
        const pct = (timeLeft / seconds) * 100;
        if(barU) barU.style.width = pct + "%";
        if(barH) barH.style.width = pct + "%";
        if(textH) textH.innerText = timeLeft;

        if(timeLeft <= 0) {
            clearInterval(timerInterval);
            disableOptions();
        }
    }, 1000);
}

function disableOptions() {
    document.querySelectorAll('.btn-ans').forEach(b => b.disabled = true);
}

// --- SPECIAL EVENTS (CƯỚP ĐIỂM & SPIN) ---
socket.on('steal_alert', d => {
    const overlay = document.getElementById('event-overlay');
    overlay.classList.remove('hidden');
    overlay.innerHTML = `
        <div class="steal-active">
            <h1 style="font-size:3.5rem; font-weight:900;">CƯỚP ĐIỂM!</h1>
            <p class="h2 text-white mt-3"><b>${d.thief}</b> đã lấy <b>${d.points}đ</b> từ <b>${d.victim}</b></p>
            <p class="small text-warning">Top 1 trả lời sai đã bị trừng phạt!</p>
        </div>`;
});

socket.on('trigger_lucky_spin', () => {
    const overlay = document.getElementById('event-overlay');
    overlay.classList.remove('hidden');
    overlay.innerHTML = `
        <div class="text-center p-4" style="background:white; border-radius:20px; color:black;">
            <h2 class="fw-bold text-primary">BẠN NHANH NHẤT!</h2>
            <p>Quay để nhận thêm điểm thưởng</p>
            <div id="wheel-val" class="h1 my-4" style="font-size:4rem">🎡</div>
            <button class="btn btn-warning btn-lg w-100 fw-bold" id="btn-spin" onclick="runLuckySpin()">QUAY NGAY</button>
        </div>`;
});

function runLuckySpin() {
    const btn = document.getElementById('btn-spin');
    btn.disabled = true;
    const pointsArr = [10, 20, 30, 50, 100];
    let count = 0;
    const spinAnim = setInterval(() => {
        document.getElementById('wheel-val').innerText = pointsArr[count % pointsArr.length] + "đ";
        count++;
        if(count > 15) {
            clearInterval(spinAnim);
            const finalPoints = pointsArr[Math.floor(Math.random()*pointsArr.length)];
            document.getElementById('wheel-val').innerText = "+" + finalPoints + "đ";
            document.getElementById('wheel-val').classList.add('text-success', 'fw-bold');
            socket.emit('claim_spin', { points: finalPoints });
            setTimeout(() => document.getElementById('event-overlay').classList.add('hidden'), 2000);
        }
    }, 100);
}

socket.on('update_leaderboard', list => {
    const lbContainer = document.getElementById('lb-host');
    if(!lbContainer) return;
    lbContainer.innerHTML = list.map((p, i) => `
        <div class="d-flex justify-content-between p-2 border-bottom ${i<3?'fw-bold text-primary':''}">
            <span>#${i+1} ${p.name}</span>
            <span>${p.score}đ</span>
        </div>`).join('');
    
    const me = list.find(x => x.name === myName);
    if(me) document.getElementById('u-score').innerText = `${me.score}đ`;
});

socket.on('round_ended', d => {
    alert(`VÒNG ${d.round} KẾT THÚC!`);
    document.getElementById('user-quiz-area').classList.add('hidden');
    document.getElementById('user-waiting').classList.remove('hidden');
    document.getElementById('wait-status-text').innerText = `ĐỢI GIÁO VIÊN BẮT ĐẦU VÒNG ${d.round + 1}`;
});

socket.on('error', d => alert(d.msg));
