import os, random, qrcode, io, base64, json, time
import pandas as pd
import fitz  # PyMuPDF
from docx import Document
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room
from threading import Timer

app = Flask(__name__)
app.config['SECRET_KEY'] = 'ai_quiz_ultra_2026'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# # DB SESSION MOCKUP: Lưu trữ trạng thái phiên chơi
game_state = {
    "all_questions": [],      # Kho 30+ câu hỏi từ file
    "current_round_qs": [],   # 10 câu của vòng hiện tại
    "used_q_indices": set(),  # Lưu chỉ số câu đã dùng để không trùng lặp
    "players": {},            # {sid: {name, score, last_ans_time}}
    "is_started": False,
    "current_round": 1,       # Vòng 1, 2, 3
    "pin": None,              # Mã PIN ngẫu nhiên
    "room_id": "main_room",
    "timer_value": 30,
    "active_question_index": 0
}

def generate_pin():
    return str(random.randint(100000, 999999))

def generate_qr(data):
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return base64.b64encode(buf.getvalue()).decode('utf-8')

# # LOGIC: Chọn 10 câu hỏi ngẫu nhiên không lặp lại từ kho câu hỏi
def prepare_round_questions():
    available_indices = [i for i in range(len(game_state['all_questions'])) 
                         if i not in game_state['used_q_indices']]
    
    if len(available_indices) < 10:
        return False # Không đủ câu hỏi
    
    selected_indices = random.sample(available_indices, 10)
    game_state['used_q_indices'].update(selected_indices)
    game_state['current_round_qs'] = [game_state['all_questions'][i] for i in selected_indices]
    return True

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('host_upload_file')
def handle_upload(data):
    # # Xử lý file tương tự như cũ nhưng lưu vào kho 'all_questions'
    filename = data['name']
    content = base64.b64decode(data['content'].split(",")[1])
    ext = filename.split('.')[-1].lower()
    
    try:
        if ext in ['csv', 'xlsx']:
            df = pd.read_csv(io.BytesIO(content)) if ext == 'csv' else pd.read_excel(io.BytesIO(content))
            # Cấu trúc: Câu hỏi, A, B, C, D, Đáp án, Độ khó
            qs = [{"q": str(row[0]), "a": str(row[1]), "b": str(row[2]), "c": str(row[3]), "d": str(row[4]), "ans": str(row[5]).strip().upper()} for _, row in df.iterrows()]
            game_state['all_questions'] = qs
        
        # # Tạo mã PIN và QR cố định cho phiên này
        game_state['pin'] = generate_pin()
        qr_data = f"{request.host_url}?pin={game_state['pin']}"
        qr_code = generate_qr(qr_data)
        
        emit('qr_ready', {'qr': qr_code, 'pin': game_state['pin']}, broadcast=True)
    except Exception as e:
        emit('error', {'msg': f"Lỗi xử lý file: {str(e)}"})

@socketio.on('join_game')
def join_game(data):
    user_pin = data.get('pin')
    if user_pin == game_state['pin']:
        game_state['players'][request.sid] = {
            "name": data['name'], 
            "score": 0, 
            "round_score": 0,
            "joined": False # Chờ host duyệt
        }
        join_room(game_state['room_id'])
        # Thông báo cho Host có người đang chờ duyệt
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
        send_next_question()
    else:
        emit('error', {'msg': "Không đủ câu hỏi trong kho để tiếp tục vòng tiếp theo!"})

def send_next_question():
    idx = game_state['active_question_index']
    if idx < 10:
        q = game_state['current_round_qs'][idx]
        # # LOGIC: Đồng bộ thời gian 30s cho tất cả User
        payload = {
            'question': q,
            'index': idx + 1,
            'total': 10,
            'timer': 30,
            'round': game_state['current_round']
        }
        emit('new_question', payload, room=game_state['room_id'])
        game_state['start_time'] = time.time() # Lưu mốc thời gian để tính tốc độ
        
        # Sau 30s tự động chuyển câu hoặc kết thúc
        # (Trong thực tế nên dùng Background Task của Eventlet)
    else:
        # Kết thúc vòng
        emit('round_ended', {'round': game_state['current_round']}, broadcast=True)
        game_state['current_round'] += 1

@socketio.on('submit_answer')
def handle_ans(data):
    sid = request.sid
    if sid in game_state['players']:
        current_q = game_state['current_round_qs'][game_state['active_question_index']]
        is_correct = data.get('ans').upper() == current_q['ans'].upper()
        
        if is_correct:
            # # LOGIC: Tính điểm nhanh (Cơ bản 100đ + thưởng thời gian còn lại)
            elapsed = time.time() - game_state['start_time']
            time_bonus = max(0, int(30 - elapsed)) 
            points = 100 + time_bonus
            game_state['players'][sid]['score'] += points
            game_state['players'][sid]['round_score'] += points
        
        update_lb()

def update_lb():
    # # Xếp hạng live theo tổng điểm
    lb = sorted([{"name": v['name'], "score": v['score']} for v in game_state['players'].values()], 
                key=lambda x: x['score'], reverse=True)
    emit('update_leaderboard', lb, broadcast=True)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
