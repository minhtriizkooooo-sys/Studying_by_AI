from gevent import monkey
monkey.patch_all()  # PHẢI ĐỂ ĐẦU TIÊN ĐỂ CHẠY TRÊN RENDER

import os
import random
import qrcode
import io
import base64
import json
import time
import pandas as pd
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'ai_quiz_ultra_2026_full_version'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

# ==========================================================
# TRẠNG THÁI HỆ THỐNG (GAME STATE)
# ==========================================================
game_state = {
    "all_questions": [],       
    "current_round_qs": [],    
    "used_q_indices": set(),   
    "players": {},             # {sid: {name, score, round_score, joined, answers: {}}}
    "host_sid": None,          
    "is_started": False,
    "current_round": 1,        
    "pin": None,               
    "room_id": "main_room",
    "active_question_index": 0,
    "start_time": 0,
    "answered_players": set(),
    "correct_responses": {},   # {sid: elapsed_time}
    "question_timer": None,    
    "max_time_per_question": 15,
    "is_processing_transition": False # Flag kiểm soát chuyển câu
}

# ==========================================================
# CÁC HÀM HỖ TRỢ (UTILITIES)
# ==========================================================
def generate_pin():
    return str(random.randint(100000, 999999))

def generate_qr(data):
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return base64.b64encode(buf.getvalue()).decode('utf-8')

def prepare_round_questions():
    """Lấy đúng 10 câu hỏi cho mỗi vòng"""
    available_indices = [i for i in range(len(game_state['all_questions'])) 
                         if i not in game_state['used_q_indices']]
    
    # Nếu không đủ 10 câu mới, reset lại danh sách đã dùng
    if len(available_indices) < 10:
        game_state['used_q_indices'] = set()
        available_indices = [i for i in range(len(game_state['all_questions']))]
    
    if not available_indices: return False

    selected_indices = random.sample(available_indices, min(10, len(available_indices)))
    game_state['used_q_indices'].update(selected_indices)
    game_state['current_round_qs'] = [game_state['all_questions'][i] for i in selected_indices]
    return True

def auto_next_question():
    """Gọi khi hết 15 giây"""
    process_bonus_and_next()

def process_bonus_and_next():
    """XỬ LÝ LOGIC CƯỚP ĐIỂM / LUCKY SPIN VÀ CHUYỂN CÂU"""
    if game_state['is_processing_transition']:
        return
    game_state['is_processing_transition'] = True

    # Hủy đếm ngược 15s của câu hiện tại
    if game_state['question_timer']:
        game_state['question_timer'].cancel()
        game_state['question_timer'] = None

    lb = update_lb() 
    idx = game_state['active_question_index']
    correct_ans = game_state['current_round_qs'][idx]['ans']

    # Thời gian chờ hiệu ứng trước khi sang câu mới
    transition_delay = 2 

    # Logic Thưởng/Phạt
    if game_state['correct_responses'] and len(lb) > 0:
        sorted_correct = sorted(game_state['correct_responses'].items(), key=lambda x: x[1])
        fastest_sid = sorted_correct[0][0]
        fastest_name = game_state['players'][fastest_sid]['name']
        
        top_player_sid = None
        for sid, pdata in game_state['players'].items():
            if pdata['name'] == lb[0]['name']:
                top_player_sid = sid
                break

        top_ans = game_state['players'][top_player_sid]['answers'].get(idx)
        
        # CƯỚP ĐIỂM
        if top_ans != correct_ans and fastest_sid != top_player_sid:
            victim_score = game_state['players'][top_player_sid]['score']
            steal_amount = int(victim_score * 0.1)
            if steal_amount > 0:
                game_state['players'][top_player_sid]['score'] -= steal_amount
                game_state['players'][fastest_sid]['score'] += steal_amount
                emit('steal_alert', {'thief': fastest_name, 'victim': lb[0]['name'], 'points': steal_amount}, room=game_state['room_id'])
                transition_delay = 5
        # LUCKY SPIN
        else:
            emit('trigger_lucky_spin', room=fastest_sid)
            emit('fastest_notify', {'name': fastest_name}, room=game_state['room_id'])
            transition_delay = 8 # Cho thêm thời gian quay spin

    update_lb()
    
    # Chờ xem hiệu ứng rồi mới nhảy câu
    socketio.sleep(transition_delay)
    
    game_state['active_question_index'] += 1
    game_state['is_processing_transition'] = False
    send_question_logic()

def send_question_logic():
    idx = game_state['active_question_index']
    # Giới hạn 10 câu mỗi vòng
    if idx < 10 and idx < len(game_state['current_round_qs']):
        q = game_state['current_round_qs'][idx]
        payload = {
            'question': {'q': q['q'], 'a': q['a'], 'b': q['b'], 'c': q['c'], 'd': q['d']},
            'index': idx + 1,
            'total': 10,
            'timer': game_state['max_time_per_question'],
            'round': game_state['current_round']
        }
        game_state['start_time'] = time.time()
        game_state['answered_players'] = set()
        game_state['correct_responses'] = {}
        emit('new_question', payload, room=game_state['room_id'])
        
        game_state['question_timer'] = socketio.call_later(game_state['max_time_per_question'], auto_next_question)
    else:
        # KẾT THÚC VÒNG 10 CÂU
        finish_round_logic()

def finish_round_logic():
    lb_final = update_lb()
    review_for_host = []
    for i, q in enumerate(game_state['current_round_qs']):
        stats = {'A': 0, 'B': 0, 'C': 0, 'D': 0, 'correct_list': [], 'wrong_list': []}
        for p_sid, p_data in game_state['players'].items():
            if not p_data.get('joined'): continue
            p_ans = p_data['answers'].get(i)
            if p_ans == q['ans']: stats['correct_list'].append(p_data['name'])
            else: stats['wrong_list'].append(p_data['name'])
            if p_ans in stats: stats[p_ans] += 1
        review_for_host.append({'q': q['q'], 'ans': q['ans'], 'exp': q.get('exp', ''), 'stats': stats})

    for sid, player in game_state['players'].items():
        if not player.get('joined'): continue
        history = []
        for i, q in enumerate(game_state['current_round_qs']):
            history.append({'q': q['q'], 'correct_ans': q['ans'], 'your_ans': player['answers'].get(i), 'exp': q.get('exp', '...')})
        emit('personal_review', {'history': history, 'total_score': player['score']}, room=sid)

    emit('round_review', {'questions': review_for_host}, room=game_state['host_sid'])
    emit('round_ended', {'round': game_state['current_round']}, broadcast=True)
    game_state['current_round'] += 1
    game_state['is_started'] = False

def update_lb():
    joined_players = {sid: p for sid, p in game_state['players'].items() if p.get('joined')}
    lb = sorted([{"name": v['name'], "score": v['score']} for v in joined_players.values()], 
                key=lambda x: x['score'], reverse=True)
    if game_state['host_sid']:
        emit('update_leaderboard', lb, room=game_state['host_sid'])
    for sid, player in joined_players.items():
        rank = next((i+1 for i, p in enumerate(lb) if p['name'] == player['name']), None)
        emit('personal_score', {'score': player['score'], 'rank': rank, 'name': player['name']}, room=sid)
    return lb

# --- SOCKET EVENTS ---
@app.route('/')
def index(): return render_template('index.html')

@socketio.on('host_connect')
def host_connect():
    game_state['host_sid'] = request.sid
    join_room(game_state['room_id'])

@socketio.on('host_upload_file')
def handle_upload(data):
    try:
        _, content_string = data['content'].split(',')
        decoded = base64.b64decode(content_string)
        df = pd.read_excel(io.BytesIO(decoded), engine='openpyxl')
        if "câu" in str(df.iloc[0,0]).lower(): df = df.iloc[1:]
        qs = []
        for _, row in df.iterrows():
            if pd.isna(row.iloc[0]): continue
            qs.append({
                "q": str(row.iloc[0]), "a": str(row.iloc[1]), "b": str(row.iloc[2]), 
                "c": str(row.iloc[3]), "d": str(row.iloc[4]), "ans": str(row.iloc[5]).strip().upper(),
                "exp": str(row.iloc[6]) if len(row) > 6 else "Không có giải thích chi tiết."
            })
        game_state['all_questions'] = qs
        game_state['pin'] = generate_pin()
        qr_code = generate_qr(f"{request.host_url}?pin={game_state['pin']}")
        emit('qr_ready', {'qr': qr_code, 'pin': game_state['pin']}, room=game_state['host_sid'])
    except Exception as e: emit('error', {'msg': str(e)})

@socketio.on('join_game')
def join_game(data):
    if str(data.get('pin')) == game_state['pin']:
        game_state['players'][request.sid] = {"name": data['name'], "score": 0, "joined": False, "answers": {}}
        join_room(game_state['room_id'])
        emit('player_waiting', {'name': data['name'], 'sid': request.sid}, room=game_state['host_sid'])
    else: emit('error', {'msg': "PIN sai!"})

@socketio.on('host_approve_all')
def approve_all():
    for sid in game_state['players']:
        game_state['players'][sid]['joined'] = True
        emit('player_approved', {'status': 'ready'}, room=sid)

@socketio.on('start_round')
def start_round():
    if prepare_round_questions():
        game_state['is_started'] = True
        game_state['active_question_index'] = 0
        for p in game_state['players'].values(): p['answers'] = {}
        send_question_logic()

@socketio.on('submit_answer')
def handle_ans(data):
    sid = request.sid
    if sid in game_state['players'] and game_state['is_started'] and sid not in game_state['answered_players']:
        idx = game_state['active_question_index']
        user_ans = str(data.get('ans')).upper()
        game_state['players'][sid]['answers'][idx] = user_ans
        game_state['answered_players'].add(sid)
        
        if user_ans == game_state['current_round_qs'][idx]['ans']:
            elapsed = time.time() - game_state['start_time']
            game_state['players'][sid]['score'] += 100 + max(0, int(15 - elapsed))
            game_state['correct_responses'][sid] = elapsed
            
        update_lb()
        
        # TỰ ĐỘNG CHUYỂN CÂU: Kiểm tra số người đã trả lời so với số người đã JOIN
        joined_count = len([s for s, p in game_state['players'].items() if p.get('joined')])
        if len(game_state['answered_players']) >= joined_count:
            socketio.start_background_task(process_bonus_and_next)

@socketio.on('claim_spin')
def claim_spin(data):
    sid = request.sid
    if sid in game_state['players']:
        game_state['players'][sid]['score'] += int(data.get('points', 0))
        update_lb()

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
