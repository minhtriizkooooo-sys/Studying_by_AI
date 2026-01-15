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
app.config['SECRET_KEY'] = 'ai_quiz_ultra_2026_full_version'
# async_mode='eventlet' là bắt buộc khi dùng eventlet để xử lý real-time
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# ==========================================================
# TRẠNG THÁI HỆ THỐNG (GAME STATE)
# ==========================================================
game_state = {
    "all_questions": [],       
    "current_round_qs": [],    
    "used_q_indices": set(),   
    "players": {},             # Lưu trữ: {sid: {name, score, round_score, joined}}
    "host_sid": None,          
    "is_started": False,
    "current_round": 1,        
    "pin": None,               
    "room_id": "main_room",
    "active_question_index": 0,
    "start_time": 0,
    "answered_players": set(),
    "correct_responses": {},   # Lưu thời gian trả lời đúng để tính bonus
    "question_timer": None,    
    "max_time_per_question": 15 
}

# ==========================================================
# CÁC HÀM HỖ TRỢ (UTILITIES)
# ==========================================================
def generate_pin():
    """Tạo mã PIN 6 số ngẫu nhiên"""
    return str(random.randint(100000, 999999))

def generate_qr(data):
    """Tạo mã QR từ đường dẫn tham gia"""
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return base64.b64encode(buf.getvalue()).decode('utf-8')

def prepare_round_questions():
    """Lấy ra 10 câu hỏi ngẫu nhiên chưa sử dụng"""
    available_indices = [i for i in range(len(game_state['all_questions'])) 
                         if i not in game_state['used_q_indices']]
    
    if len(available_indices) < 10:
        return False 
    
    selected_indices = random.sample(available_indices, 10)
    game_state['used_q_indices'].update(selected_indices)
    game_state['current_round_qs'] = [game_state['all_questions'][i] for i in selected_indices]
    return True

def auto_next_question():
    """Hàm gọi khi hết thời gian 15 giây"""
    process_bonus_and_next()

def process_bonus_and_next():
    """Xử lý điểm thưởng, cập nhật bảng xếp hạng và chuyển câu"""
    # 1. Thưởng Bonus cho Top 5 người trả lời đúng và nhanh nhất
    if game_state['correct_responses']:
        # Sắp xếp theo thời gian trả lời (tăng dần)
        sorted_responses = sorted(game_state['correct_responses'].items(), key=lambda x: x[1])
        top_5 = sorted_responses[:5]
        for sid, elapsed in top_5:
            bonus = random.randint(10, 50)
            if sid in game_state['players']:
                game_state['players'][sid]['score'] += bonus
                game_state['players'][sid]['round_score'] += bonus
                emit('bonus_points', {'bonus': bonus}, room=sid)
    
    # 2. Cập nhật bảng xếp hạng cho tất cả mọi người
    update_lb()
    
    # 3. Chờ 5 giây để mọi người xem kết quả/hiệu ứng trên màn hình
    socketio.sleep(5) 
    
    # 4. Chuyển sang câu tiếp theo
    game_state['active_question_index'] += 1
    send_question_logic()

def send_question_logic():
    """Logic gửi dữ liệu câu hỏi mới xuống Client"""
    idx = game_state['active_question_index']
    
    # Nếu chưa hết 10 câu
    if idx < 10:
        q = game_state['current_round_qs'][idx]
        payload = {
            'question': q,
            'index': idx + 1,
            'total': 10,
            'timer': game_state['max_time_per_question'],
            'round': game_state['current_round']
        }
        game_state['start_time'] = time.time()
        game_state['answered_players'] = set()
        game_state['correct_responses'] = {}
        
        emit('new_question', payload, room=game_state['room_id'])
        
        # Thiết lập bộ đếm giờ tự động chuyển câu (15s)
        if game_state['question_timer']:
            game_state['question_timer'].cancel()
        game_state['question_timer'] = socketio.call_later(game_state['max_time_per_question'], auto_next_question)
    
    # Nếu đã hết 10 câu (Kết thúc vòng)
    else:
        # Gửi dữ liệu Review (bao gồm câu hỏi, đáp án đúng và GIẢI THÍCH)
        review_data = []
        for q in game_state['current_round_qs']:
            review_data.append({
                'q': q['q'], 
                'ans': q['ans'], 
                'exp': q.get('exp', 'Không có giải thích chi tiết.')
            })
        
        emit('round_review', {'questions': review_data}, room=game_state['room_id'])
        emit('round_ended', {'round': game_state['current_round']}, broadcast=True)
        
        game_state['current_round'] += 1
        game_state['is_started'] = False

def update_lb():
    """Cập nhật Leaderboard toàn cục và thứ hạng cá nhân"""
    # Chỉ tính những người đã được Host duyệt (joined = True)
    joined_players = {sid: p for sid, p in game_state['players'].items() if p['joined']}
    
    lb = sorted([{"name": v['name'], "score": v['score']} for v in joined_players.values()], 
                key=lambda x: x['score'], reverse=True)
    
    # Gửi bảng xếp hạng tổng cho Host
    if game_state['host_sid']:
        emit('update_leaderboard', lb, room=game_state['host_sid'])
    
    # Gửi điểm và hạng riêng cho từng người chơi
    for sid, player in joined_players.items():
        rank = next((i+1 for i, p in enumerate(lb) if p['name'] == player['name']), None)
        emit('personal_score', {'score': player['score'], 'rank': rank}, room=sid)

# ==========================================================
# CÁC SỰ KIỆN SOCKET.IO (SOCKET EVENTS)
# ==========================================================

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('host_connect')
def host_connect():
    game_state['host_sid'] = request.sid
    join_room(game_state['room_id'])

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

        # Đọc dữ liệu từ file Excel/CSV
        qs = []
        for _, row in df.iterrows():
            # Cột 0: Câu hỏi, 1-4: Đáp án A-D, 5: Đáp án đúng, 6: Giải thích
            qs.append({
                "q": str(row.iloc[0]), 
                "a": str(row.iloc[1]), 
                "b": str(row.iloc[2]), 
                "c": str(row.iloc[3]), 
                "d": str(row.iloc[4]), 
                "ans": str(row.iloc[5]).strip().upper(),
                "exp": str(row.iloc[6]) if len(row) > 6 else "Không có giải thích chi tiết cho câu này."
            })
        
        game_state['all_questions'] = qs
        game_state['pin'] = generate_pin()
        
        # Tạo mã QR để học sinh quét tham gia
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
            "joined": False  # Mặc định chưa được duyệt
        }
        join_room(game_state['room_id'])
        # Thông báo cho Host có người mới đang chờ duyệt
        emit('player_waiting', {'name': data['name'], 'sid': request.sid}, room=game_state['host_sid'])
    else:
        emit('error', {'msg': "Mã PIN không đúng, vui lòng kiểm tra lại!"})

@socketio.on('host_approve_player')
def approve_player(data):
    """Host duyệt từng người chơi cụ thể"""
    sid = data.get('sid')
    if sid in game_state['players']:
        game_state['players'][sid]['joined'] = True
        emit('player_approved', {'status': 'ready'}, room=sid)

@socketio.on('host_approve_all')
def approve_all():
    """Host duyệt tất cả người chơi đang chờ cùng lúc"""
    for sid, p_info in game_state['players'].items():
        if not p_info['joined']:
            game_state['players'][sid]['joined'] = True
            emit('player_approved', {'status': 'ready'}, room=sid)

@socketio.on('start_round')
def start_round():
    """Bắt đầu vòng chơi 10 câu"""
    if prepare_round_questions():
        game_state['is_started'] = True
        game_state['active_question_index'] = 0
        send_question_logic()
    else:
        emit('error', {'msg': "Không đủ 10 câu hỏi mới để bắt đầu vòng này!"})

@socketio.on('submit_answer')
def handle_ans(data):
    """Xử lý khi học sinh gửi đáp án"""
    sid = request.sid
    if sid in game_state['players'] and game_state['is_started']:
        if sid in game_state['answered_players']: return # Chống spam
        
        idx = game_state['active_question_index']
        current_q = game_state['current_round_qs'][idx]
        
        user_ans = str(data.get('ans')).upper()
        is_correct = user_ans == current_q['ans']
        
        elapsed = time.time() - game_state['start_time']
        game_state['answered_players'].add(sid)
        
        if is_correct:
            # Tính điểm: 100 điểm gốc + điểm thưởng thời gian (tối đa 15 điểm)
            points = 100 + max(0, int(game_state['max_time_per_question'] - elapsed))
            game_state['players'][sid]['score'] += points
            game_state['players'][sid]['round_score'] += points
            game_state['correct_responses'][sid] = elapsed
        
        update_lb()
        
        # Nếu TẤT CẢ người chơi đã tham gia đều đã trả lời xong
        active_p_count = len([s for s, p in game_state['players'].items() if p['joined']])
        if len(game_state['answered_players']) >= active_p_count:
            if game_state['question_timer']:
                game_state['question_timer'].cancel()
            process_bonus_and_next()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
