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
    "max_time_per_question": 15 
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
    available_indices = [i for i in range(len(game_state['all_questions'])) 
                         if i not in game_state['used_q_indices']]
    if len(available_indices) < 10:
        return False 
    selected_indices = random.sample(available_indices, 10)
    game_state['used_q_indices'].update(selected_indices)
    game_state['current_round_qs'] = [game_state['all_questions'][i] for i in selected_indices]
    return True

def auto_next_question():
    process_bonus_and_next()

def process_bonus_and_next():
    """XỬ LÝ LOGIC CƯỚP ĐIỂM VÀ LUCKY SPIN CHUYÊN SÂU"""
    lb = update_lb() 
    idx = game_state['active_question_index']
    correct_ans = game_state['current_round_qs'][idx]['ans']

    # Nếu có ít nhất 1 người trả lời đúng
    if game_state['correct_responses'] and len(lb) > 0:
        sorted_correct = sorted(game_state['correct_responses'].items(), key=lambda x: x[1])
        fastest_sid = sorted_correct[0][0]
        fastest_name = game_state['players'][fastest_sid]['name']
        
        # Tìm SID của người đang đứng Top 1 trước khi tính Bonus
        top_player_sid = None
        for sid, pdata in game_state['players'].items():
            if pdata['name'] == lb[0]['name']:
                top_player_sid = sid
                break

        top_ans = game_state['players'][top_player_sid]['answers'].get(idx)
        
        # LOGIC 1: CƯỚP ĐIỂM (Top 1 sai + Có ít nhất 1 người khác đúng)
        if top_ans != correct_ans and fastest_sid != top_player_sid:
            victim_score = game_state['players'][top_player_sid]['score']
            steal_amount = int(victim_score * 0.1) # Cướp 10%
            
            if steal_amount > 0:
                game_state['players'][top_player_sid]['score'] -= steal_amount
                game_state['players'][fastest_sid]['score'] += steal_amount
                
                emit('steal_alert', {
                    'thief': fastest_name, 
                    'victim': lb[0]['name'],
                    'points': steal_amount
                }, room=game_state['room_id'])
        
        # LOGIC 2: LUCKY SPIN (Khi không có cướp điểm xảy ra)
        else:
            emit('trigger_lucky_spin', room=fastest_sid)
            emit('fastest_notify', {'name': fastest_name}, room=game_state['room_id'])

    update_lb()
    socketio.sleep(5) # Đợi 5s để xem hiệu ứng rồi mới sang câu mới
    game_state['active_question_index'] += 1
    send_question_logic()

def send_question_logic():
    idx = game_state['active_question_index']
    if idx < 10:
        q = game_state['current_round_qs'][idx]
        q_to_send = {'q': q['q'], 'a': q['a'], 'b': q['b'], 'c': q['c'], 'd': q['d']}
        payload = {
            'question': q_to_send,
            'index': idx + 1,
            'total': 10,
            'timer': game_state['max_time_per_question'],
            'round': game_state['current_round']
        }
        game_state['start_time'] = time.time()
        game_state['answered_players'] = set()
        game_state['correct_responses'] = {}
        emit('new_question', payload, room=game_state['room_id'])
        
        if game_state['question_timer']:
            game_state['question_timer'].cancel()
        game_state['question_timer'] = socketio.call_later(game_state['max_time_per_question'], auto_next_question)
    else:
        # KẾT THÚC VÒNG - GỬI REVIEW CHI TIẾT
        review_for_host = []
        for i, q in enumerate(game_state['current_round_qs']):
            stats = {'A': 0, 'B': 0, 'C': 0, 'D': 0, 'correct_list': [], 'wrong_list': []}
            for p_sid, p_data in game_state['players'].items():
                if not p_data.get('joined'): continue
                p_ans = p_data['answers'].get(i)
                if p_ans == q['ans']:
                    stats['correct_list'].append(p_data['name'])
                else:
                    stats['wrong_list'].append(p_data['name'])
                if p_ans in stats: stats[p_ans] += 1
            
            review_for_host.append({
                'q': q['q'], 'ans': q['ans'], 'exp': q.get('exp', ''), 'stats': stats
            })

        # Gửi review cá nhân cho từng User
        lb_final = update_lb()
        for sid, player in game_state['players'].items():
            if not player.get('joined'): continue
            rank = next((i+1 for i, p in enumerate(lb_final) if p['name'] == player['name']), 0)
            personal_history = []
            for i, q in enumerate(game_state['current_round_qs']):
                personal_history.append({
                    'q': q['q'], 'correct_ans': q['ans'],
                    'your_ans': player['answers'].get(i),
                    'exp': q.get('exp', 'Không có giải thích.')
                })
            emit('personal_review', {
                'history': personal_history, 
                'rank': rank, 
                'total_score': player['score']
            }, room=sid)

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

# Socket events giữ nguyên phần xử lý file và join game...
@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('host_connect')
def host_connect():
    game_state['host_sid'] = request.sid
    join_room(game_state['room_id'])

@socketio.on('host_upload_file')
def handle_upload(data):
    try:
        content_type, content_string = data['content'].split(',')
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
    except Exception as e:
        emit('error', {'msg': f"Lỗi: {str(e)}"})

@socketio.on('join_game')
def join_game(data):
    if str(data.get('pin')) == game_state['pin']:
        game_state['players'][request.sid] = {"name": data['name'], "score": 0, "round_score": 0, "joined": False, "answers": {}}
        join_room(game_state['room_id'])
        emit('player_waiting', {'name': data['name'], 'sid': request.sid}, room=game_state['host_sid'])
    else: emit('error', {'msg': "PIN sai!"})

@socketio.on('host_approve_player')
def approve_player(data):
    sid = data.get('sid')
    if sid in game_state['players']:
        game_state['players'][sid]['joined'] = True
        emit('player_approved', {'status': 'ready'}, room=sid)

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
        is_correct = (user_ans == game_state['current_round_qs'][idx]['ans'])
        elapsed = time.time() - game_state['start_time']
        game_state['answered_players'].add(sid)
        if is_correct:
            points = 100 + max(0, int(game_state['max_time_per_question'] - elapsed))
            game_state['players'][sid]['score'] += points
            game_state['correct_responses'][sid] = elapsed
        update_lb()
        # Nếu mọi người đã trả lời xong, không đợi hết timer nữa
        if len(game_state['answered_players']) >= len([s for s, p in game_state['players'].items() if p.get('joined')]):
            if game_state['question_timer']: game_state['question_timer'].cancel()
            process_bonus_and_next()

@socketio.on('claim_spin')
def claim_spin(data):
    sid = request.sid
    if sid in game_state['players']:
        bonus = int(data.get('points', 0))
        game_state['players'][sid]['score'] += bonus
        update_lb()

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
