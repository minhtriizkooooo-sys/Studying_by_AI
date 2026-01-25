from gevent import monkey
monkey.patch_all()  # PHẢI ĐỂ ĐẦU TIÊN

import os
import random
import qrcode
import io
import base64
import pandas as pd
import time
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'ai_quiz_ultra_2026_trongdeptrai'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

# TRẠNG THÁI GAME
game_state = {
    "all_questions": [],
    "current_round_qs": [],
    "used_q_indices": set(),
    "players": {},  # sid: {name, score, joined, answers:{}}
    "host_sid": None,
    "is_started": False,
    "current_round": 1,
    "pin": None,
    "room_id": "quiz_room_2026",
    "active_question_index": 0,
    "start_time": 0,
    "answered_players": set(),
    "correct_responses": {},
    "question_timer": None,
    "max_time_per_question": 15,
    "is_processing": False
}

# UTILITIES (giữ nguyên)
def generate_pin():
    return str(random.randint(100000, 999999))

def generate_qr(data):
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return base64.b64encode(buf.getvalue()).decode('utf-8')

def prepare_round_questions():
    available = [i for i in range(len(game_state['all_questions'])) if i not in game_state['used_q_indices']]
    if len(available) < 10:
        game_state['used_q_indices'].clear()
        available = list(range(len(game_state['all_questions'])))
    if not available:
        return False
    selected = random.sample(available, 10)
    game_state['used_q_indices'].update(selected)
    game_state['current_round_qs'] = [game_state['all_questions'][i] for i in selected]
    return True

def update_leaderboard():
    joined = {sid: p for sid, p in game_state['players'].items() if p.get('joined')}
    lb = sorted([{"name": p['name'], "score": p['score']} for p in joined.values()], key=lambda x: x['score'], reverse=True)
    
    if game_state['host_sid']:
        emit('update_leaderboard', lb, room=game_state['host_sid'])
    
    for sid, player in joined.items():
        rank = next((i+1 for i, item in enumerate(lb) if item['name'] == player['name']), None)
        emit('personal_score', {'score': player['score'], 'rank': rank or 0}, room=sid)
    
    return lb

def process_transition():
    if game_state['is_processing']:
        return
    game_state['is_processing'] = True
    if game_state['question_timer']:
        game_state['question_timer'].cancel()
        game_state['question_timer'] = None
    lb = update_leaderboard()
    idx = game_state['active_question_index']
    correct_ans = game_state['current_round_qs'][idx]['ans']
    delay = 3
    if game_state['correct_responses']:
        sorted_correct = sorted(game_state['correct_responses'].items(), key=lambda x: x[1])
        fastest_sid = sorted_correct[0][0]
        fastest_name = game_state['players'][fastest_sid]['name']
        top_player = lb[0] if lb else None
        top_sid = next((sid for sid, p in game_state['players'].items() if p['name'] == top_player['name']), None) if top_player else None
        top_ans = game_state['players'][top_sid]['answers'].get(idx) if top_sid else None
        if top_player and top_ans != correct_ans and fastest_sid != top_sid:
            steal_amount = max(50, int(game_state['players'][top_sid]['score'] * 0.1))
            game_state['players'][top_sid]['score'] -= steal_amount
            game_state['players'][fastest_sid]['score'] += steal_amount
            emit('steal_alert', {'thief': fastest_name, 'victim': top_player['name'], 'points': steal_amount}, room=game_state['room_id'])
            delay = 6
        else:
            emit('fastest_notify', {'name': fastest_name}, room=game_state['room_id'])
            emit('trigger_lucky_spin', room=fastest_sid)
            delay = 11
    update_leaderboard()
    socketio.sleep(delay)
    game_state['active_question_index'] += 1
    game_state['is_processing'] = False
    send_next_question()

def send_next_question():
    idx = game_state['active_question_index']
    if idx >= 10:
        end_round()
        return
    q = game_state['current_round_qs'][idx]
    payload = {
        'question': {'q': q['q'], 'a': q['a'], 'b': q['b'], 'c': q['c'], 'd': q['d'], 'ans': q['ans']},
        'index': idx + 1,
        'total': 10,
        'timer': 15,
        'round': game_state['current_round']
    }
    game_state['start_time'] = time.time()
    game_state['answered_players'] = set()
    game_state['correct_responses'] = {}
    emit('new_question', payload, room=game_state['room_id'])
    game_state['question_timer'] = socketio.call_later(15, process_transition)

def end_round():
    review_for_host = []
    for i, q in enumerate(game_state['current_round_qs']):
        stats = {'A':0,'B':0,'C':0,'D':0, 'correct':[], 'wrong':[]}
        for sid, p in game_state['players'].items():
            if not p.get('joined'): continue
            ans = p['answers'].get(i)
            if ans == q['ans']:
                stats['correct'].append(p['name'])
            else:
                stats['wrong'].append(p['name'])
            if ans: stats[ans] += 1
        review_for_host.append({
            'q': q['q'], 'ans': q['ans'], 'exp': q.get('exp', 'Không có giải thích.'),
            'stats': stats
        })
    for sid, p in game_state['players'].items():
        if not p.get('joined'): continue
        history = []
        for i, q in enumerate(game_state['current_round_qs']):
            your_ans = p['answers'].get(i, '-')
            history.append({
                'q': q['q'],
                'your_ans': your_ans,
                'correct_ans': q['ans'],
                'exp': q.get('exp', ''),
                'is_correct': your_ans == q['ans']
            })
        emit('personal_review', {'history': history, 'total_score': p['score']}, room=sid)
    emit('round_review', {'questions': review_for_host}, room=game_state['host_sid'])
    emit('round_ended', {'round': game_state['current_round'], 'top3': update_leaderboard()[:3]}, broadcast=True)
    game_state['current_round'] += 1
    game_state['is_started'] = False

# ROUTES & SOCKET EVENTS
@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('host_connect')
def host_connect():
    game_state['host_sid'] = request.sid
    join_room(game_state['room_id'])

@socketio.on('host_upload_file')
def upload_file(data):
    try:
        _, b64 = data['content'].split(',', 1)
        df = pd.read_excel(io.BytesIO(base64.b64decode(b64)), engine='openpyxl')
        if "câu" in str(df.iloc[0,0]).lower():
            df = df.iloc[1:]
        qs = []
        for _, row in df.iterrows():
            if pd.isna(row.iloc[0]): continue
            qs.append({
                "q": str(row.iloc[0]).strip(),
                "a": str(row.iloc[1]), "b": str(row.iloc[2]), "c": str(row.iloc[3]), "d": str(row.iloc[4]),
                "ans": str(row.iloc[5]).strip().upper(),
                "exp": str(row.iloc[6]) if len(row) > 6 and not pd.isna(row.iloc[6]) else "Không có giải thích."
            })
        game_state['all_questions'] = qs
        game_state['pin'] = generate_pin()
        qr = generate_qr(f"{request.host_url}?pin={game_state['pin']}")
        emit('qr_ready', {'qr': qr, 'pin': game_state['pin']}, room=game_state['host_sid'])
    except Exception as e:
        emit('error', {'msg': f"Lỗi file: {str(e)}"}, room=game_state['host_sid'])

@socketio.on('join_game')
def join(data):
    if str(data.get('pin')) == game_state['pin']:
        sid = request.sid
        game_state['players'][sid] = {
            "name": data['name'][:15],
            "score": 0,
            "joined": False,
            "answers": {}
        }
        join_room(game_state['room_id'])
        emit('player_waiting', {'sid': sid, 'name': data['name']}, room=game_state['host_sid'])
    else:
        emit('error', {'msg': 'PIN sai rồi bạn ơi!'}, room=request.sid)

@socketio.on('host_approve_player')
def approve_one(data):
    sid = data['sid'] if isinstance(data, dict) else data  # hỗ trợ cả object và string
    if sid in game_state['players']:
        game_state['players'][sid]['joined'] = True
        emit('player_approved', {'approved': True}, room=sid)
        # Optional: emit cập nhật danh sách cho host nếu cần sync thêm

@socketio.on('host_approve_all')
def approve_all():
    for sid in list(game_state['players'].keys()):
        if not game_state['players'][sid]['joined']:
            game_state['players'][sid]['joined'] = True
            emit('player_approved', {'approved': True}, room=sid)

@socketio.on('start_round')
def start():
    if prepare_round_questions():
        game_state['is_started'] = True
        game_state['active_question_index'] = 0
        for p in game_state['players'].values():
            p['answers'] = {}
        send_next_question()

@socketio.on('submit_answer')
def answer(data):
    sid = request.sid
    if (sid not in game_state['players'] or not game_state['is_started'] or
        sid in game_state['answered_players']):
        return
    idx = game_state['active_question_index']
    ans = str(data.get('ans')).upper()
    player = game_state['players'][sid]
    player['answers'][idx] = ans
    game_state['answered_players'].add(sid)
    if ans == game_state['current_round_qs'][idx]['ans']:
        elapsed = time.time() - game_state['start_time']
        bonus = max(0, int(15 - elapsed) * 3)
        player['score'] += 100 + bonus
        game_state['correct_responses'][sid] = elapsed
    update_leaderboard()
    joined_count = sum(1 for p in game_state['players'].values() if p.get('joined'))
    if len(game_state['answered_players']) >= joined_count:
        socketio.start_background_task(process_transition)

@socketio.on('claim_spin')
def claim(data):
    sid = request.sid
    points = int(data) if isinstance(data, (int, str)) else int(data.get('points', 0))
    if sid in game_state['players']:
        game_state['players'][sid]['score'] += points
        update_leaderboard()

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
