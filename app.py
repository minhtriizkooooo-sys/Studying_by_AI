import os, random, qrcode, io, base64, time
import pandas as pd
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'marie_curie_pro_2026'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

game_state = {
    "all_questions": [],
    "used_q_indices": set(),
    "current_round_qs": [],
    "players": {},
    "active_q_idx": -1,
    "current_round_num": 0,
    "start_time": 0,
    "current_answers": {},
    "top_player_sid": None,
    "pin": None,
    "is_running": False
}

@app.route('/')
def index(): return render_template('index.html')

@socketio.on('host_upload_file')
def handle_upload(data):
    try:
        content = base64.b64decode(data['content'].split(",")[1])
        df = pd.read_csv(io.BytesIO(content))
        game_state['all_questions'] = df.to_dict('records')
        game_state['pin'] = str(random.randint(100000, 999999))
        
        qr = qrcode.make(f"{game_state['pin']}")
        buf = io.BytesIO()
        qr.save(buf, format='PNG')
        emit('qr_ready', {'qr': base64.b64encode(buf.getvalue()).decode('utf-8'), 'pin': game_state['pin']})
    except Exception as e:
        emit('error', {'msg': "File không đúng định dạng mẫu!"})

@socketio.on('join_request')
def join_request(data):
    if data.get('pin') == game_state['pin']:
        sid = request.sid
        game_state['players'][sid] = {"name": data['name'], "score": 0, "approved": False, "history": []}
        emit('new_player_waiting', {'name': data['name'], 'sid': sid}, broadcast=True)

@socketio.on('approve_player')
def approve(data):
    sid = data.get('sid')
    if sid in game_state['players']:
        game_state['players'][sid]['approved'] = True
        emit('approved', room=sid)

@socketio.on('approve_all')
def approve_all():
    for sid in game_state['players']:
        game_state['players'][sid]['approved'] = True
    emit('approved', broadcast=True)

@socketio.on('start_round')
def start_round():
    game_state['current_round_num'] += 1
    avail = [i for i in range(len(game_state['all_questions'])) if i not in game_state['used_q_indices']]
    if len(avail) < 10: return emit('error', {'msg': "Không đủ câu hỏi!"})
    
    selected = random.sample(avail, 10)
    game_state['used_q_indices'].update(selected)
    game_state['current_round_qs'] = [game_state['all_questions'][i] for i in selected]
    game_state['active_q_idx'] = 0
    game_state['is_running'] = True
    send_q()

def send_q():
    idx = game_state['active_q_idx']
    if idx < 10 and game_state['is_running']:
        game_state['current_answers'] = {}
        game_state['start_time'] = time.time()
        q = game_state['current_round_qs'][idx]
        emit('new_q', {'q': q, 'idx': idx+1, 'round': game_state['current_round_num']}, broadcast=True)
        socketio.sleep(15.5)
        if game_state['is_running'] and game_state['active_q_idx'] == idx:
            process_end_q()

def process_end_q():
    idx = game_state['active_q_idx']
    correct_answers = {s: v for s, v in game_state['current_answers'].items() if v['correct']}
    
    if idx > 0 and correct_answers: # Từ câu thứ 2
        fastest_sid = min(correct_answers, key=lambda x: correct_answers[x]['time'])
        
        # LUCKY SPIN
        if fastest_sid == game_state['top_player_sid']:
            bonus = random.choice([50, 100, 150, 200])
            game_state['players'][fastest_sid]['score'] += bonus
            emit('event_notif', {'msg': f"🌟 LUCKY SPIN: {game_state['players'][fastest_sid]['name']} +{bonus}đ!"}, broadcast=True)
        
        # MARK STEAL
        elif game_state['top_player_sid'] and fastest_sid != game_state['top_player_sid']:
            victim = game_state['top_player_sid']
            stolen = int(game_state['players'][victim]['score'] * 0.15)
            game_state['players'][victim]['score'] -= stolen
            game_state['players'][fastest_sid]['score'] += stolen
            emit('event_notif', {'msg': f"⚡ MARK STEAL: {game_state['players'][fastest_sid]['name']} cướp {stolen}đ của {game_state['players'][victim]['name']}!"}, broadcast=True)

    # Cập nhật người cao nhất cho câu sau
    if game_state['players']:
        game_state['top_player_sid'] = max(game_state['players'], key=lambda x: game_state['players'][x]['score'])
    
    update_lb()
    game_state['active_q_idx'] += 1
    socketio.sleep(2)
    if game_state['active_q_idx'] < 10: send_q()
    else: 
        game_state['is_running'] = False
        emit('round_end_choice', broadcast=True)

def update_lb():
    lb = sorted([{"name": v['name'], "score": v['score']} for v in game_state['players'].values()], key=lambda x: x['score'], reverse=True)
    emit('lb_update', lb, broadcast=True)

@socketio.on('submit')
def handle_sub(data):
    sid = request.sid
    if sid in game_state['current_answers']: return
    elapsed = time.time() - game_state['start_time']
    q = game_state['current_round_qs'][game_state['active_q_idx']]
    correct = data['ans'] == q['Đáp án đúng']
    
    game_state['players'][sid]['history'].append({
        "q": q['Câu hỏi'], "u": data['ans'], "c": q['Đáp án đúng'], "ex": q['Giải thích']
    })
    
    game_state['current_answers'][sid] = {"correct": correct, "time": elapsed}
    if correct: game_state['players'][sid]['score'] += int(100 * (1 - elapsed/15))

@socketio.on('force_end')
def force_end():
    game_state['is_running'] = False
    emit('game_over_final', broadcast=True)

@socketio.on('get_review')
def get_review():
    sid = request.sid
    emit('show_review', game_state['players'][sid]['history'])

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
