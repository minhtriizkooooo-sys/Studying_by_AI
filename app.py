import os, random, qrcode, io, base64, time
import pandas as pd
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'quiz_ultra_2026'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

game_state = {
    "all_questions": [],
    "current_round_qs": [],
    "used_q_indices": set(),
    "players": {},
    "active_question_index": 0,
    "start_time": 0,
    "current_answers": {},
    "top_player_prev_sid": None, # SID người đứng đầu câu trước
    "pin": None,
    "is_running": False
}

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('host_upload_file')
def handle_upload(data):
    try:
        content = base64.b64decode(data['content'].split(",")[1])
        ext = data['name'].split('.')[-1].lower()
        df = pd.read_csv(io.BytesIO(content), header=None) if ext == 'csv' else pd.read_excel(io.BytesIO(content), header=None)
        df = df.dropna(how='all').reset_index(drop=True)
        
        new_qs = []
        for i, row in df.iterrows():
            if i == 0 and "câu" in str(row[0]).lower(): continue
            r = row.tolist()
            if len(r) >= 6:
                new_qs.append({"q": str(r[0]), "a": str(r[1]), "b": str(r[2]), "c": str(r[3]), "d": str(r[4]), "ans": str(r[5]).strip().upper()})
        
        game_state['all_questions'] = new_qs
        game_state['pin'] = str(random.randint(100000, 999999))
        qr = qrcode.make(f"{request.host_url}?pin={game_state['pin']}")
        buf = io.BytesIO()
        qr.save(buf, format='PNG')
        emit('qr_ready', {'qr': base64.b64encode(buf.getvalue()).decode('utf-8'), 'pin': game_state['pin']}, broadcast=True)
    except Exception as e:
        emit('error', {'msg': f"Lỗi file: {str(e)}"})

@socketio.on('join_game')
def join_game(data):
    if data.get('pin') == game_state['pin']:
        game_state['players'][request.sid] = {"name": data['name'], "score": 0, "joined": False}
        join_room("quiz_room")
        emit('player_waiting', {'name': data['name'], 'sid': request.sid}, broadcast=True)

@socketio.on('host_approve_all')
def approve_all():
    for sid, p in game_state['players'].items():
        if not p['joined']:
            p['joined'] = True
            emit('player_approved', {"name": p['name']}, room=sid)

@socketio.on('start_round')
def start_round():
    avail = [i for i in range(len(game_state['all_questions'])) if i not in game_state['used_q_indices']]
    if len(avail) < 10: return emit('error', {'msg': "Không đủ 10 câu hỏi mới!"})
    
    selected = random.sample(avail, 10)
    game_state['used_q_indices'].update(selected)
    game_state['current_round_qs'] = [game_state['all_questions'][i] for i in selected]
    game_state['active_question_index'] = 0
    game_state['is_running'] = True
    game_state['top_player_prev_sid'] = None
    send_question()

def send_question():
    idx = game_state['active_question_index']
    if idx < 10:
        game_state['current_answers'] = {}
        game_state['start_time'] = time.time()
        q = game_state['current_round_qs'][idx]
        emit('new_question', {'question': q, 'index': idx+1, 'total': 10}, room="quiz_room")
        
        # Tự động kết thúc câu sau 15 giây
        socketio.sleep(15)
        if game_state['active_question_index'] == idx:
            process_end_of_question()
    else:
        game_state['is_running'] = False
        emit('game_over', broadcast=True)

@socketio.on('submit_answer')
def handle_ans(data):
    sid = request.sid
    if sid in game_state['current_answers'] or not game_state['is_running']: return
    
    elapsed = time.time() - game_state['start_time']
    if elapsed > 15: return

    current_q = game_state['current_round_qs'][game_state['active_question_index']]
    is_correct = data.get('ans', '').upper() == current_q['ans'].upper()
    
    game_state['current_answers'][sid] = {"correct": is_correct, "time": elapsed}
    if is_correct:
        game_state['players'][sid]['score'] += int(100 * (1 - elapsed/15))

    # Chuyển câu ngay nếu tất cả người đã duyệt đều trả lời xong
    joined_players = [s for s, p in game_state['players'].items() if p['joined']]
    if len(game_state['current_answers']) >= len(joined_players):
        process_end_of_question()

def process_end_of_question():
    correct_players = {s: v for s, v in game_state['current_answers'].items() if v['correct']}
    
    if correct_players:
        fastest_sid = min(correct_players, key=lambda x: correct_players[x]['time'])
        
        # Logic Lucky Spin & Mark Steal
        if game_state['top_player_prev_sid']:
            if fastest_sid == game_state['top_player_prev_sid']:
                # LUCKY SPIN
                emit('trigger_lucky_spin', room=fastest_sid)
                emit('game_announcement', {'msg': f"🌟 {game_state['players'][fastest_sid]['name']} GIỮ VỮNG NGÔI ĐẦU - LUCKY SPIN!"}, room="quiz_room")
            else:
                # MARK STEAL: Cướp 25% tổng điểm của người đứng đầu câu trước
                victim_sid = game_state['top_player_prev_sid']
                steal_amount = int(game_state['players'][victim_sid]['score'] * 0.25)
                game_state['players'][victim_sid]['score'] -= steal_amount
                game_state['players'][fastest_sid]['score'] += steal_amount
                emit('game_announcement', {'msg': f"⚡ {game_state['players'][fastest_sid]['name']} CƯỚP {steal_amount}đ TỪ {game_state['players'][victim_sid]['name']}!"}, room="quiz_room")

    # Cập nhật người đứng đầu cho câu tiếp theo
    if game_state['players']:
        game_state['top_player_prev_sid'] = max(game_state['players'], key=lambda x: game_state['players'][x]['score'])

    update_lb()
    game_state['active_question_index'] += 1
    socketio.sleep(3) # Chờ 3 giây để người dùng đọc thông báo
    send_question()

def update_lb():
    lb = sorted([{"name": v['name'], "score": v['score']} for v in game_state['players'].values()], key=lambda x: x['score'], reverse=True)
    emit('update_leaderboard', lb, room="quiz_room")

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
