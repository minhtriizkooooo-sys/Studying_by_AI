const socket = io();
let myName = "";
let timerInterval;

function selectRole(role) {
    $('#role-selection').addClass('hidden');
    $(`#${role}-ui`).removeClass('hidden');
    if (role === 'host') $('#host-welcome-name').text('Giáo viên Admin');
}

// ===================== HOST =====================
$('#file-input').on('change', function(e) {
    const file = e.target.files[0];
    const reader = new FileReader();
    $('#host-status').removeClass('hidden');
    reader.onload = () => socket.emit('host_upload_file', {content: reader.result});
    reader.readAsDataURL(file);
});

socket.on('qr_ready', d => {
    $('#host-setup, #host-status').addClass('hidden');
    $('#host-lobby').removeClass('hidden');
    $('#display-pin').text(d.pin);
    $('#qr-display').html(`<img src="data:image/png;base64,${d.qr}" style="width:200px;border:5px solid white;border-radius:15px">`);
});

socket.on('player_waiting', d => {
    if ($(`#wait-item-${d.sid}`).length) return;
    const item = $(`
        <div id="wait-item-${d.sid}" class="user-item border-start border-danger border-5 p-3 mb-2 rounded shadow-sm d-flex justify-content-between align-items-center">
            <span class="fw-bold text-danger"><i class="fa fa-hourglass-half"></i> ${d.name}</span>
            <button class="btn btn-success btn-sm fw-bold" onclick="approvePlayer('${d.sid}')">DUYỆT</button>
        </div>`);
    $('#waiting-list').append(item);
    $('#wait-count').text($('#waiting-list').children().length);
});

function approvePlayer(sid) {
    socket.emit('host_approve_player', sid);
    $(`#wait-item-${sid}`).remove();
    $('#wait-count').text($('#waiting-list').children().length);
}

function approveAll() {
    socket.emit('host_approve_all');
}

function startRound() {
    socket.emit('start_round');
    $('#host-lobby').addClass('hidden');
    $('#host-live-monitor').removeClass('hidden');
}

// ===================== USER =====================
function userJoin() {
    const pin = $('#user-pin').val().trim();
    myName = $('#user-name').val().trim();
    if (!pin || !myName) return alert("Nhập đầy đủ PIN và Tên!");
    socket.emit('join_game', {pin, name: myName});
    $('#user-login').addClass('hidden');
    $('#user-waiting').removeClass('hidden');
    $('#user-welcome-name').text(myName);
}

socket.on('player_approved', () => {
    $('#wait-status-text').text('ĐÃ VÀO PHÒNG - CHỜ BẮT ĐẦU!').css('color', '#27ae60');
});

socket.on('new_question', d => {
    $('#event-overlay, #user-waiting').addClass('hidden');
    $('#user-quiz-area').removeClass('hidden');
    $('#q-idx').text(`Câu ${d.index}/10`);
    $('#q-text').html(d.question.q);
    if ($('#monitor-q-text').length) $('#monitor-q-text').text(d.question.q);

    $('#q-options').empty();
    ['a','b','c','d'].forEach(k => {
        const btn = $(`<button class="btn btn-ans">${k.toUpperCase()}. ${d.question[k]}</button>`);
        btn.on('click', function() {
            if ($(this).prop('disabled')) return;
            disableOptions();
            socket.emit('submit_answer', {ans: k});
            const correct = k.toUpperCase() === d.question.ans;
            $(this).css({borderColor: correct?'#27ae60':'#e74c3c', background: correct?'#f0fff4':'#fff5f5'});
        });
        $('#q-options').append(btn);
    });
    startCountdown(15);
});

function startCountdown(sec) {
    clearInterval(timerInterval);
    let t = sec;
    timerInterval = setInterval(() => {
        t--;
        const pct = (t / sec) * 100;
        $('#user-timer-bar, #host-timer-bar').css('width', pct + '%');
        $('#monitor-time').text(t);
        if (t <= 0) {
            clearInterval(timerInterval);
            disableOptions();
        }
    }, 1000);
}

function disableOptions() {
    $('.btn-ans').prop('disabled', true).css('opacity', 0.6);
}

socket.on('update_leaderboard', list => {
    $('#lb-host').empty();
    list.forEach((p, i) => {
        $('#lb-host').append(`
            <div class="lb-item ${i<3?'fw-bold text-primary':''}">
                <span>#${i+1} ${p.name}</span>
                <span class="text-success fw-bold">${p.score}đ</span>
            </div>`);
    });
    const me = list.find(x => x.name === myName);
    if (me) $('#u-score').text(me.score + 'đ');
});

socket.on('personal_score', d => {
    $('#u-score').text(d.score + 'đ');
});

socket.on('steal_alert', d => {
    $('#event-overlay').removeClass('hidden').html(`
        <div class="steal-active event-title">
            <h1>CƯỚP ĐIỂM!</h1>
            <p class="display-4">${d.thief} <i class="fa fa-arrow-right text-danger"></i> ${d.points}đ <i class="fa fa-arrow-left text-danger"></i> ${d.victim}</p>
        </div>`);
});

socket.on('trigger_lucky_spin', () => {
    showLuckySpin();
});

socket.on('personal_review', d => {
    let html = `<h3 class="text-center mb-4">Kết quả vòng ${game_state?.current_round-1 || ''}</h3>`;
    d.history.forEach((h, i) => {
        const status = h.is_correct ? 'correct' : 'wrong';
        html += `
            <div class="review-item ${status} p-3 rounded mb-3">
                <strong>Câu ${i+1}:</strong> ${h.q}<br>
                <span class="${h.is_correct?'text-success':'text-danger'}">
                    Bạn: <b>${h.your_ans || 'Chưa trả lời'}</b> → Đáp án: <b>${h.correct_ans}</b>
                </span><br>
                <small class="text-muted">${h.exp}</small>
            </div>`;
    });
    html += `<h3 class="text-center text-primary mt-4">Tổng điểm: ${d.total_score}đ</h3>`;
    $('#user-quiz-area').html(html);
});

socket.on('error', d => alert(d.msg));

// ===================== LUCKY SPIN SIÊU ĐẸP =====================
function showLuckySpin() {
    const prizes = [50, 100, 150, 200, 300, 500, 0, 100];
    const wheel = $('#event-overlay').removeClass('hidden').html(`
        <div class="text-center">
            <h1 class="spin-active event-title">LUCKY SPIN!</h1>
            <p class="h3 text-warning mb-4">Bạn là người trả lời nhanh nhất!</p>
            <div class="spin-wheel-ui position-relative d-inline-block">
                <div id="wheel" style="width:200px;height:200px;border-radius:50%;background:conic-gradient(#f1c40f 0% 12.5%, #e67e22 12.5% 25%, #e74c3c 25% 37.5%, #3498db 37.5% 50%, #2ecc71 50% 62.5%, #9b59b6 62.5% 75%, #34495e 75% 87.5%, #f39c12 87.5% 100%);transition:transform 4s cubic-bezier(0.17, 0.67, 0.12, 1);">
                </div>
                <div class="position-absolute top-0 start-50 translate-middle-x text-white fw-bold">▲</div>
                <button id="spin-btn" class="btn btn-danger btn-lg mt-4 fw-bold px-5">QUAY NGAY</button>
                <h2 id="spin-result" class="mt-3 text-warning">?</h2>
            </div>
        </div>`);

    $('#spin-btn').on('click', function() {
        $(this).prop('disabled', true);
        const spins = 5 + Math.random() * 5;
        const deg = spins * 360 + prizes[Math.floor(Math.random() * prizes.length)] * 45;
        $('#wheel').css('transform', `rotate(${deg}deg)`);
        setTimeout(() => {
            const won = prizes[Math.floor((deg % 360) / 45) % 8];
            $('#spin-result').text('+' + won + 'đ').addClass('display-4');
            socket.emit('claim_spin', won);
            setTimeout(() => $('#event-overlay').addClass('hidden'), 4000);
        }, 4500);
    });
}
