import eventlet
eventlet.monkey_patch()  # PHẢI ĐỂ ĐẦU TIÊN ĐỂ CHẠY TRÊN RENDER

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
app.config['SECRET_KEY'] = 'ai_quiz_ultra_2026'
# async_mode='eventlet' là bắt buộc khi dùng eventlet
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Lưu trữ trạng thái phiên chơi
game_state = {
    "all_questions": [],      
    "current_round_qs": [],   
    "used_q_indices": set(),  
    "players": {},            # {sid: {name, score, round_score, joined}}
    "is_started": False,
    "current_round": 1,       
    "pin": None,              
    "room_id": "main_room",
    "active_question_index": 0,
    "start_time": 0
}

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

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('host_upload_file')
def handle_upload(data):
    filename = data['name']
    try:
        content = base64.b64decode(data['content'].split(",")[1])
        ext = filename.split('.')[-1].lower()
        
        if ext == 'csv':
            df = pd.read_csv(io.BytesIO(content))
        else:
            df = pd.read_excel(io.BytesIO(content))

        # Ép kiểu dữ liệu để tránh lỗi JSON khi emit
        qs = []
        for _, row in df.iterrows():
            qs.append({
                "q": str(row.iloc[0]), 
                "a": str(row.iloc[1]), 
                "b": str(row.iloc[2]), 
                "c": str(row.iloc[3]), 
                "d": str(row.iloc[4]), 
                "ans": str(row.iloc[5]).strip().upper()
            })
        
        game_state['all_questions'] = qs
        game_state['pin'] = generate_pin()
        
        # Tạo link QR (sử dụng host thực tế)
        qr_data = f"{request.host_url}?pin={game_state['pin']}"
        qr_code = generate_qr(qr_data)
        
        emit('qr_ready', {'qr': qr_code, 'pin': game_state['pin']}, broadcast=True)
    except Exception as e:
        print(f"Error: {e}")
        emit('error', {'msg': f"Lỗi xử lý file: {str(e)}"})

@socketio.on('join_game')
def join_game(data):
    user_pin = data.get('pin')
    if user_pin == game_state['pin']:
        game_state['players'][request.sid] = {
            "name": data['name'], 
            "score": 0, 
            "round_score": 0,
            "joined": False 
        }
        join_room(game_state['room_id'])
        emit('player_waiting', {'name': data['name'], 'sid': request.sid}, broadcast=True)
    else:
        emit('error', {'msg': "Mã PIN không đúng!"})

@socketio.on('host_approve_player')
def approve_player(data):
    sid = data.get('sid')
    if sid in game_state['players']:
        game_state['players'][sid]['joined'] = True
        emit('player_approved', {'status': 'ready'}, room=sid)

@socketio.on('start_round')
def start_round():
    if prepare_round_questions():
        game_state['is_started'] = True
        game_state['active_question_index'] = 0
        send_question_logic()
    else:
        emit('error', {'msg': "Không đủ câu hỏi (Cần 10 câu mỗi vòng)!"})

@socketio.on('next_question')
def handle_next():
    game_state['active_question_index'] += 1
    send_question_logic()

def send_question_logic():
    idx = game_state['active_question_index']
    if idx < 10:
        q = game_state['current_round_qs'][idx]
        payload = {
            'question': q,
            'index': idx + 1,
            'total': 10,
            'timer': 30,
            'round': game_state['current_round']
        }
        game_state['start_time'] = time.time()
        emit('new_question', payload, room=game_state['room_id'])
    else:
        emit('round_ended', {'round': game_state['current_round']}, broadcast=True)
        game_state['current_round'] += 1

@socketio.on('submit_answer')
def handle_ans(data):
    sid = request.sid
    if sid in game_state['players'] and game_state['is_started']:
        idx = game_state['active_question_index']
        current_q = game_state['current_round_qs'][idx]
        
        user_ans = str(data.get('ans')).upper()
        is_correct = user_ans == current_q['ans']
        
        if is_correct:
            elapsed = time.time() - game_state['start_time']
            points = 100 + max(0, int(30 - elapsed))
            game_state['players'][sid]['score'] += points
            game_state['players'][sid]['round_score'] += points
        
        update_lb()

def update_lb():
    lb = sorted([{"name": v['name'], "score": v['score']} for v in game_state['players'].values()], 
                key=lambda x: x['score'], reverse=True)
    emit('update_leaderboard', lb, broadcast=True)

if __name__ == '__main__':
    # Render yêu cầu dùng biến môi trường PORT
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
