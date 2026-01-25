const socket = io();
let myName = "";
let timerInterval;

function selectRole(role) {
    document.getElementById('role-selection').classList.add('hidden');
    document.getElementById(role + '-ui').classList.remove('hidden');
    if (role === 'host') {
        // Nếu có tên host thì set
        const hostNameElem = document.getElementById('host-welcome-name');
        if (hostNameElem) hostNameElem.textContent = 'Giáo viên Admin';
    }
}

// ===================== HOST =====================
document.getElementById('file-input').addEventListener('change', function(e) {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    document.getElementById('host-status').classList.remove('hidden');
    reader.onload = () => socket.emit('host_upload_file', { content: reader.result });
    reader.readAsDataURL(file);
});

socket.on('qr_ready', d => {
    document.getElementById('host-setup').classList.add('hidden');
    document.getElementById('host-status').classList.add('hidden');
    document.getElementById('host-lobby').classList.remove('hidden');
    document.getElementById('display-pin').textContent = d.pin;
    document.getElementById('qr-display').innerHTML = `<img src="data:image/png;base64,${d.qr}" style="width:200px;border:5px solid white;border-radius:15px">`;
});

socket.on('player_waiting', d => {
    const list = document.getElementById('waiting-list');
    if (document.getElementById(`wait-item-${d.sid}`)) return;

    const item = document.createElement('div');
    item.id = `wait-item-${d.sid}`;
    item.className = "user-item border-start border-danger border-5 p-3 mb-2 rounded shadow-sm d-flex justify-content-between align-items-center";
    item.innerHTML = `
        <span class="fw-bold text-danger"><i class="fa fa-hourglass-half me-2"></i> ${d.name}</span>
        <button class="btn btn-success btn-sm fw-bold" onclick="approvePlayer('${d.sid}', '${d.name}', this)">DUYỆT</button>
    `;
    list.appendChild(item);
    document.getElementById('wait-count').textContent = list.children.length;
});

function approvePlayer(sid, name, btn) {
    socket.emit('host_approve_player', { sid });
    btn.parentElement.remove();
    document.getElementById('wait-count').textContent = document.getElementById('waiting-list').children.length;

    const approvedList = document.getElementById('approved-list');
    const approvedItem = document.createElement('div');
    approvedItem.className = "user-item text-success border-start border-success border-5 p-3 mb-2 rounded shadow-sm";
    approvedItem.innerHTML = `<i class="fa fa-check-circle me-2"></i> ${name}`;
    approvedList.appendChild(approvedItem);
}

function approveAll() {
    socket.emit('host_approve_all');
    // Client sẽ tự xóa hết chờ duyệt khi server emit approved cho từng user
}

function startRound() {
    socket.emit('start_round');
    document.getElementById('host-lobby').classList.add('hidden');
    document.getElementById('host-live-monitor').classList.remove('hidden');
}

// ===================== USER =====================
function userJoin() {
    const pin = document.getElementById('user-pin').value.trim();
    myName = document.getElementById('user-name').value.trim();
    if (!pin || !myName) return alert("Nhập đầy đủ PIN và Tên!");
    socket.emit('join_game', { pin, name: myName });
    document.getElementById('user-login').classList.add('hidden');
    document.getElementById('user-waiting').classList.remove('hidden');
    document.getElementById('user-welcome-name').textContent = myName;
}

socket.on('player_approved', () => {
    document.getElementById('wait-status-text').textContent = 'ĐÃ VÀO PHÒNG - CHỜ BẮT ĐẦU!';
    document.getElementById('wait-status-text').style.color = '#27ae60';
});

// Các phần còn lại (new_question, timer, lucky spin, v.v.) giữ nguyên như anh gửi
// ... (copy phần còn lại từ code anh gửi vào đây nếu cần)
</script>
