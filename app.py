import os, random, qrcode, io, base64, time
import pandas as pd
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'quiz_pro_2026_final_v5'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

game_state = {
    "all_questions": [],
    "used_q_indices": set(),
    "current_round_qs": [],
    "players": {},
    "active_q_idx": 0,
    "current_round_num": 1,
    "start_time": 0,
    "current_answers": {},
    "top_player_prev_sid": None, # Lưu SID của người đứng đầu câu trước
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
                new_qs.append({
                    "q": str(r[0]), "a": str(r[1]), "b": str(r[2]), "c": str(r[3]), "d": str(r[4]), 
                    "ans": str(r[5]).strip().upper(),
                    "explain": str(r[6]) if len(r) > 6 and pd.notna(r[6]) else "Không có giải thích chi tiết."
                })
        game_state['all_questions'] = new_qs
        game_state['pin'] = str(random.randint(100000, 999999))
        emit('qr_ready', {'pin': game_state['pin']}, broadcast=True)
    except Exception as e:
        emit('error', {'msg': f"Lỗi file: {str(e)}"})

@socketio.on('join_game')
def join_game(data):
    if data.get('pin') == game_state['pin']:
        game_state['players'][request.sid] = {"name": data['name'], "score": 0, "joined": False, "history": []}
        join_room("quiz_room")
        emit('player_waiting', {'name': data['name']}, broadcast=True)

@socketio.on('host_approve_all')
def approve_all():
    for sid, p in game_state['players'].items():
        if not p['joined']:
            p['joined'] = True
            emit('player_approved', room=sid)

@socketio.on('start_round')
def start_round():
    if game_state['current_round_num'] > 3:
        return emit('game_over', broadcast=True)

    avail = [i for i in range(len(game_state['all_questions'])) if i not in game_state['used_q_indices']]
    if len(avail) < 10: return emit('error', {'msg': "Hết câu hỏi!"})
    
    selected = random.sample(avail, 10)
    game_state['used_q_indices'].update(selected)
    game_state['current_round_qs'] = [game_state['all_questions'][i] for i in selected]
    game_state['active_q_idx'] = 0
    game_state['is_running'] = True
    send_question()

def send_question():
    idx = game_state['active_q_idx']
    if idx < 10:
        game_state['current_answers'] = {}
        game_state['start_time'] = time.time()
        q = game_state['current_round_qs'][idx]
        emit('new_question', {'question': q, 'index': idx+1, 'round': game_state['current_round_num']}, room="quiz_room")
        socketio.sleep(15.5)
        if game_state['is_running'] and game_state['active_q_idx'] == idx:
            process_end_of_question()
    else:
        game_state['is_running'] = False
        emit('round_ended', {'round': game_state['current_round_num']}, broadcast=True)
        game_state['current_round_num'] += 1

@socketio.on('submit_answer')
def handle_ans(data):
    sid = request.sid
    if sid in game_state['current_answers'] or not game_state['is_running']: return
    
    elapsed = time.time() - game_state['start_time']
    current_q = game_state['current_round_qs'][game_state['active_q_idx']]
    u_ans = data.get('ans', '').upper()
    is_correct = (u_ans == current_q['ans'])
    
    game_state['players'][sid]['history'].append({
        "q": current_q['q'], "u_ans": u_ans, "c_ans": current_q['ans'], "exp": current_q['explain']
    })
    
    game_state['current_answers'][sid] = {"correct": is_correct, "time": elapsed}
    if is_correct:
        game_state['players'][sid]['score'] += int(100 * (1 - elapsed/15))

    # Tự động chuyển nếu xong hết
    joined = [s for s, p in game_state['players'].items() if p['joined']]
    if len(game_state['current_answers']) >= len(joined):
        process_end_of_question()

def process_end_of_question():
    correct_p = {s: v for s, v in game_state['current_answers'].items() if v['correct']}
    
    if correct_p:
        fastest_sid = min(correct_p, key=lambda x: correct_p[x]['time'])
        
        # LOGIC: LUCKY SPIN & MARK STEAL
        if fastest_sid == game_state['top_player_prev_sid']:
            emit('trigger_lucky_spin', room=fastest_sid)
            emit('game_announcement', {'msg': f"🌟 {game_state['players'][fastest_sid]['name']} DUY TRÌ VỊ THẾ - LUCKY SPIN!"}, room="quiz_room")
        elif game_state['top_player_prev_sid'] and fastest_sid != game_state['top_player_prev_sid']:
            victim = game_state['top_player_prev_sid']
            steal_pts = int(game_state['players'][victim]['score'] * 0.25)
            game_state['players'][victim]['score'] -= steal_pts
            game_state['players'][fastest_sid]['score'] += steal_pts
            emit('game_announcement', {'msg': f"⚡ {game_state['players'][fastest_sid]['name']} CƯỚP {steal_pts}đ TỪ {game_state['players'][victim]['name']}!"}, room="quiz_room")

    if game_state['players']:
        game_state['top_player_prev_sid'] = max(game_state['players'], key=lambda x: game_state['players'][x]['score'])
    
    update_lb()
    game_state['active_q_idx'] += 1
    socketio.sleep(2)
    send_question()

@socketio.on('request_review')
def handle_review():
    sid = request.sid
    if sid in game_state['players']:
        emit('show_review', game_state['players'][sid]['history'])

def update_lb():
    lb = sorted([{"name": v['name'], "score": v['score']} for v in game_state['players'].values()], key=lambda x: x['score'], reverse=True)
    emit('update_leaderboard', lb, room="quiz_room")

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
