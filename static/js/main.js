const socket = io();
let timerInterval;
let myName = "";

function selectRole(role) {
    document.getElementById('role-selection').classList.add('hidden');
    document.getElementById(role + '-ui').classList.remove('hidden');
    
    // Nếu là host, hiển thị lời chào mặc định
    if(role === 'host') {
        document.getElementById('host-welcome-name').innerText = "Giáo viên";
    }
}

// --- LOGIC GIÁO VIÊN (HOST) ---
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

// XỬ LÝ DUYỆT USER (HIỆN NÚT DUYỆT)
socket.on('player_waiting', d => {
    const list = document.getElementById('waiting-list');
    const waitCount = document.getElementById('wait-count');
    
    const div = document.createElement('div');
    div.className = "d-flex justify-content-between align-items-center p-2 mb-2 bg-white shadow-sm rounded border-start border-primary border-4";
    div.innerHTML = `
        <span class="fw-bold"><i class="fa fa-user-circle text-primary"></i> ${d.name}</span> 
        <button class="btn btn-sm btn-success fw-bold" onclick="approve('${d.sid}', this)">DUYỆT</button>
    `;
    list.appendChild(div);
    
    // Cập nhật số lượng đang chờ
    waitCount.innerText = list.children.length;
});

function approve(sid, btn) {
    socket.emit('host_approve_player', { sid });
    const list = document.getElementById('waiting-list');
    btn.parentElement.remove();
    document.getElementById('wait-count').innerText = list.children.length;
}

function startRound() {
    socket.emit('start_round');
    document.getElementById('host-lobby').classList.add('hidden');
    document.getElementById('host-live-monitor').classList.remove('hidden');
}

// --- LOGIC THÍ SINH (USER) ---
function userJoin() {
    const pin = document.getElementById('user-pin').value;
    myName = document.getElementById('user-name').value;
    
    if(!pin || !myName) return alert("Vui lòng nhập đầy đủ PIN và Tên!");
    
    socket.emit('join_game', { pin, name: myName });
    
    // Hiển thị lời chào tên User ngay khi nhấn tham gia
    document.getElementById('user-welcome-name').innerText = myName;
    document.getElementById('user-login').classList.add('hidden');
    document.getElementById('user-waiting').classList.remove('hidden');
}

socket.on('player_approved', () => {
    const statusText = document.getElementById('wait-status-text');
    statusText.innerText = "ĐÃ ĐƯỢC PHÊ DUYỆT!";
    statusText.classList.replace('text-primary', 'text-success');
});

// --- ENGINE GAME ---
socket.on('new_question', d => {
    // Ẩn các overlay và màn hình chờ khi có câu hỏi mới
    document.getElementById('event-overlay').classList.add('hidden');
    document.getElementById('user-waiting').classList.add('hidden');
    document.getElementById('user-quiz-area').classList.remove('hidden');
    
    document.getElementById('q-idx').innerText = `Câu ${d.index}/${d.total}`;
    document.getElementById('q-text').innerText = d.question.q;
    
    if(document.getElementById('monitor-q-text')) {
        document.getElementById('monitor-q-text').innerText = d.question.q;
    }

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
            btn.style.backgroundColor = isCorrect ? "#f0fff4" : "#fff5f5";
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

// --- HIỆU ỨNG CƯỚP ĐIỂM ---
socket.on('steal_alert', d => {
    const overlay = document.getElementById('event-overlay');
    overlay.classList.remove('hidden');
    overlay.innerHTML = `
        <div class="steal-active">
            <h1 style="font-size:4rem; font-weight:900;">CƯỚP ĐIỂM!</h1>
            <p class="h2 mt-3"><b>${d.thief}</b> đã lấy <b>${d.points}đ</b> từ <b>${d.victim}</b></p>
            <p class="mt-2 text-warning">Hãy cẩn thận với vị trí dẫn đầu!</p>
        </div>`;
});

socket.on('update_leaderboard', list => {
    const lb = document.getElementById('lb-host');
    if(!lb) return;
    
    lb.innerHTML = list.map((p, i) => `
        <div class="d-flex justify-content-between p-2 border-bottom ${i<3 ? 'fw-bold text-primary' : ''}">
            <span>#${i+1} ${p.name}</span>
            <span>${p.score}đ</span>
        </div>`).join('');
    
    const me = list.find(x => x.name === myName);
    if(me) document.getElementById('u-score').innerText = `${me.score}đ`;
});

socket.on('round_ended', d => {
    alert(`Kết thúc vòng ${d.round}!`);
    document.getElementById('user-quiz-area').classList.add('hidden');
    document.getElementById('user-waiting').classList.remove('hidden');
    document.getElementById('wait-status-text').innerText = `CHỜ GIÁO VIÊN BẮT ĐẦU VÒNG ${d.round + 1}`;
});

socket.on('error', d => alert(d.msg));
