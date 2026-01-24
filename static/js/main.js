const socket = io({ reconnection: true });
let timerInterval;

function selectRole(role) {
    document.getElementById('role-selection').classList.add('hidden');
    document.getElementById(role + '-ui').classList.remove('hidden');
    if(role === 'host') socket.emit('host_connect');
}

// Logic Host
document.getElementById('file-input')?.addEventListener('change', (e) => {
    const file = e.target.files[0];
    const reader = new FileReader();
    reader.onload = () => socket.emit('host_upload_file', { content: reader.result, name: file.name });
    reader.readAsDataURL(file);
});

function startRound() {
    socket.emit('start_round');
    document.getElementById('host-lobby').classList.add('hidden');
    document.getElementById('host-live-monitor').classList.remove('hidden');
}

// Logic User
function userJoin() {
    const pin = document.getElementById('user-pin').value;
    const name = document.getElementById('user-name').value;
    socket.emit('join_game', { pin, name });
    document.getElementById('user-login').classList.add('hidden');
}

// Socket Common
socket.on('new_question', d => {
    document.getElementById('event-overlay').classList.add('hidden');
    const qArea = document.getElementById('user-quiz-area');
    if(qArea) {
        qArea.classList.remove('hidden');
        document.getElementById('q-text').innerText = d.question.q;
        // Render options...
    }
    updateMonitor(d);
});

function updateMonitor(d) {
    const mText = document.getElementById('monitor-q-text');
    if(mText) mText.innerText = d.question.q;
    // ... logic cập nhật màn hình host
}
