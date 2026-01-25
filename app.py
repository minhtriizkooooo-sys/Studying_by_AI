import os
import random
import qrcode
import io
import base64
import time
import pandas as pd
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'marie_curie_2026_final_v3'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

game_state = {
    "all_questions": [],
    "used_indices": set(),
    "current_round_qs": [],
    "players": {},
    "player_names": set(),
    "active_q_idx": -1,
    "current_round_num": 0,
    "start_time": 0,
    "pin": None,
    "is_running": False,
    "king_sid": None,
    "current_answers": {},
    "timer_id": 0
}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/template')
def get_template():
    template = """Câu hỏi,Đáp án A,Đáp án B,Đáp án C,Đáp án D,Đáp án đúng,Giải thích
Ví dụ: Trong bài thơ Tây Tiến, hình ảnh 'đoàn binh không mọc tóc' phản ánh điều gì?,Sốt rét rừng,Sang chảnh thời thượng,Quy định quân đội,Lương thực thiếu,A,Hình ảnh phản ánh bệnh sốt rét rừng khiến lính rụng tóc...
...thêm câu hỏi của bạn vào đây...
"""
    return template, 200, {'Content-Type': 'text/plain; charset=utf-8'}

@socketio.on('host_upload_file')
def handle_upload(data):
    try:
        content = base64.b64decode(data['content'].split(",")[1])
        if b'xl' in content[:10]:
            df = pd.read_excel(io.BytesIO(content))
        else:
            df = pd.read_csv(io.BytesIO(content), encoding='utf-8-sig')
        
        df.columns = df.columns.str.strip()
        required = ['Câu hỏi', 'Đáp án A', 'Đáp án B', 'Đáp án C', 'Đáp án D', 'Đáp án đúng', 'Giải thích']
        if not all(col in df.columns for col in required):
            raise ValueError("File thiếu cột: " + ", ".join(required))
        
        game_state['all_questions'] = df.to_dict('records')
        game_state['pin'] = str(random.randint(100000, 999999))
        game_state['used_indices'] = set()
        game_state['players'] = {}
        game_state['player_names'] = set()
        game_state['current_round_num'] = 0
        game_state['is_running'] = False
        game_state['king_sid'] = None

        qr = qrcode.QRCode(box_size=10, border=2)
        qr.add_data(game_state['pin'])
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        emit('qr_ready', {
            'qr': base64.b64encode(buf.getvalue()).decode('utf-8'),
            'pin': game_state['pin']
        }, room=request.sid)
    except Exception as e:
        emit('error', {'msg': str(e)}, room=request.sid)

@socketio.on('join_request')
def join(data):
    name = data.get('name', '').strip()
    pin = data.get('pin')
    
    if pin != game_state['pin']:
        emit('join_failed', {'msg': 'PIN không đúng!'})
        return
    
    if name in game_state['player_names']:
        emit('join_failed', {'msg': 'Tên này đã được sử dụng trong phòng!'})
        return
    
    sid = request.sid
    game_state['players'][sid] = {
        "name": name,
        "total": 0,
        "last_pts": 0,
        "history": [],
        "approved": False
    }
    game_state['player_names'].add(name)
    
    emit('new_player_waiting', {'name': name, 'sid': sid}, broadcast=True)
    emit('join_received', room=sid)  # Chỉ thông báo đã gửi yêu cầu, không vào quiz ngay

@socketio.on('approve_player')
def approve(data):
    sid = data.get('sid')
    if sid in game_state['players']:
        game_state['players'][sid]['approved'] = True
        emit('approved_success', room=sid)  # User tự động vào quiz
        update_lb()

@socketio.on('approve_all')
def approve_all():
    for sid in game_state['players']:
        game_state['players'][sid]['approved'] = True
    emit('approved_success', broadcast=True)
    update_lb()

@socketio.on('start_next_round')
def start_round():
    if game_state['is_running']:
        return
    avail = [i for i in range(len(game_state['all_questions'])) if i not in game_state['used_indices']]
    if len(avail) < 10:
        return emit('error', {'msg': "Hết câu hỏi trong kho!"})
    
    game_state['current_round_num'] += 1
    selected = random.sample(avail, 10)
    game_state['used_indices'].update(selected)
    game_state['current_round_qs'] = [game_state['all_questions'][i] for i in selected]
    game_state['active_q_idx'] = 0
    game_state['is_running'] = True
    
    # Gửi ngay câu hỏi đầu tiên cho tất cả
    send_q()

# Các hàm còn lại giữ nguyên (send_q, process_end_q, submit_ans, update_lb, finish_all, get_review)
# ... (copy phần còn lại từ code cũ của bạn)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
