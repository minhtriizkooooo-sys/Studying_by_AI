import os, random, qrcode, io, base64, json, time
import pandas as pd
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'ai_quiz_ultra_2026'
# Đồng bộ gevent cho Render
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

game_state = {
    "all_questions": [],
    "current_round_qs": [],
    "used_q_indices": set(),
    "players": {},
    "is_started": False,
    "current_round": 1,
    "pin": None,
    "room_id": "main_room",
    "active_question_index": 0,
    "start_time": 0,
    "first_correct_sid": None
}

def generate_pin():
    return str(random.randint(100000, 999999))

def generate_qr(data):
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return base64.b64encode(buf.getvalue()).decode('utf-8')

# Thêm Event này vào trong app.py

@socketio.on('host_approve_all')
def approve_all():
    approved_count = 0
    for sid, info in game_state['players'].items():
        if not info['joined']:
            info['joined'] = True
            approved_count += 1
            emit('player_approved', {"name": info['name']}, room=sid)
    # Thông báo cho host biết đã duyệt xong
    emit('game_announcement', {'msg': f"Đã duyệt nhanh {approved_count} thí sinh!"}, room=request.sid)

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('host_upload_file')
def handle_upload(data):
    try:
        content = base64.b64decode(data['content'].split(",")[1])
        filename = data['name']
        ext = filename.split('.')[-1].lower()
        
        # Đọc file với header=None để tránh lỗi tên cột (0, 1, 2...)
        if ext == 'csv':
            df = pd.read_csv(io.BytesIO(content), header=None)
        else:
            df = pd.read_excel(io.BytesIO(content), header=None)

        # Xóa các hàng hoặc cột hoàn toàn trống
        df = df.dropna(how='all').reset_index(drop=True)

        new_qs = []
        for i, row in df.iterrows():
            # Nếu dòng đầu tiên có vẻ là tiêu đề (chứa chữ "Câu hỏi" hoặc "Question"), hãy bỏ qua
            if i == 0 and ("câu" in str(row[0]).lower() or "question" in str(row[0]).lower()):
                continue
            
            # Chuyển dòng thành list để truy cập index 0-5 an toàn
            r = row.tolist()
            if len(r) >= 6:
                new_qs.append({
                    "q": str(r[0]).strip(),
                    "a": str(r[1]).strip(),
                    "b": str(r[2]).strip(),
                    "c": str(r[3]).strip(),
                    "d": str(r[4]).strip(),
                    "ans": str(r[5]).strip().upper()
                })

        if not new_qs:
            raise ValueError("Không tìm thấy dữ liệu hợp lệ trong 6 cột đầu tiên!")

        game_state['all_questions'] = new_qs
        game_state['pin'] = generate_pin()
        qr_code = generate_qr(f"{request.host_url}?pin={game_state['pin']}")
        
        emit('qr_ready', {'qr': qr_code, 'pin': game_state['pin']}, broadcast=True)
    except Exception as e:
        # Gửi thông báo lỗi chi tiết về trình duyệt
        emit('error', {'msg': f"Lỗi xử lý file: {str(e)}"})

# ... (Các phần socketio.on khác giữ nguyên như bản trước) ...

@socketio.on('join_game')
def join_game(data):
    if str(data.get('pin')) == str(game_state['pin']):
        game_state['players'][request.sid] = {"name": data['name'], "score": 0, "joined": False}
        join_room(game_state['room_id'])
        emit('player_waiting', {'name': data['name'], 'sid': request.sid}, broadcast=True)
    else:
        emit('error', {'msg': "Mã PIN không đúng!"})

@socketio.on('host_approve_player')
def approve_player(data):
    sid = data.get('sid')
    if sid in game_state['players']:
        game_state['players'][sid]['joined'] = True
        emit('player_approved', {}, room=sid)

@socketio.on('start_round')
def start_round():
    available_indices = [i for i in range(len(game_state['all_questions'])) if i not in game_state['used_q_indices']]
    if len(available_indices) < 10:
        emit('error', {'msg': f"Chỉ còn {len(available_indices)} câu, không đủ 10 câu cho vòng mới!"})
        return
    
    selected_indices = random.sample(available_indices, 10)
    game_state['used_q_indices'].update(selected_indices)
    game_state['current_round_qs'] = [game_state['all_questions'][i] for i in selected_indices]
    game_state['is_started'] = True
    game_state['active_question_index'] = 0
    send_question()

def send_question():
    idx = game_state['active_question_index']
    if idx < 10:
        game_state['first_correct_sid'] = None
        game_state['start_time'] = time.time()
        q = game_state['current_round_qs'][idx]
        emit('new_question', {'question': q, 'index': idx+1, 'total': 10}, room=game_state['room_id'])
    else:
        emit('round_ended', {'round': game_state['current_round']}, broadcast=True)
        game_state['current_round'] += 1

@socketio.on('submit_answer')
def handle_ans(data):
    sid = request.sid
    if sid not in game_state['players']: return
    current_q = game_state['current_round_qs'][game_state['active_question_index']]
    elapsed = time.time() - game_state['start_time']
    is_correct = data.get('ans', '').upper() == current_q['ans'].upper()
    
    if is_correct:
        points = 100 + max(0, int(30 - elapsed))
        game_state['players'][sid]['score'] += points
        if game_state['first_correct_sid'] is None and elapsed < 7:
            game_state['first_correct_sid'] = sid
            targets = sorted([s for s in game_state['players'] if s != sid], 
                           key=lambda s: game_state['players'][s]['score'], reverse=True)
            if targets and game_state['players'][targets[0]]['score'] > 50:
                emit('trigger_lucky_spin', {'victim_sid': targets[0], 'victim_name': game_state['players'][targets[0]]['name']}, room=sid)
    update_lb()

@socketio.on('next_question_request')
def next_q():
    game_state['active_question_index'] += 1
    send_question()

@socketio.on('execute_steal')
def execute_steal(data):
    stealer_sid = request.sid
    victim_sid = data.get('victim_sid')
    percent = data.get('percent')
    if victim_sid in game_state['players']:
        stolen = int(game_state['players'][victim_sid]['score'] * (percent / 100))
        game_state['players'][victim_sid]['score'] -= stolen
        game_state['players'][stealer_sid]['score'] += stolen
        emit('game_announcement', {'msg': f"⚡ {game_state['players'][stealer_sid]['name']} cướp {stolen}đ từ {game_state['players'][victim_sid]['name']}!"}, broadcast=True)
        update_lb()

def update_lb():
    lb = sorted([{"name": v['name'], "score": v['score']} for v in game_state['players'].values()], key=lambda x: x['score'], reverse=True)
    emit('update_leaderboard', lb, broadcast=True)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)

