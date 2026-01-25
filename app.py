import os
import random
import qrcode
import io
import base64
import time
import pandas as pd
from flask import Flask, render_template, request, send_file
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'marie_curie_2026_final_v3'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

game_state = {
    "all_questions": [],
    "used_indices": set(),
    "current_round_qs": [],
    "players": {},              # sid -> player info
    "player_names": set(),      # theo dõi tên đã join (tránh trùng tên)
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
        if 'content' not in data or not data['content']:
            raise ValueError("Không nhận được nội dung file")

        # Decode base64
        header, encoded = data['content'].split(",", 1)
        content = base64.b64decode(encoded)

        # Xác định loại file tốt hơn
        is_excel = header.lower().find('xlsx') > -1 or content.startswith(b'PK\x03\x04')  # ZIP signature của xlsx

        if is_excel:
            df = pd.read_excel(io.BytesIO(content))
        else:
            df = pd.read_csv(io.BytesIO(content), encoding='utf-8-sig')

        df.columns = df.columns.str.strip()
        required = ['Câu hỏi', 'Đáp án A', 'Đáp án B', 'Đáp án C', 'Đáp án D', 'Đáp án đúng', 'Giải thích']
        missing = [col for col in required if col not in df.columns]
        if missing:
            raise ValueError(f"File thiếu cột: {', '.join(missing)}")

        if df.empty:
            raise ValueError("File không có dữ liệu câu hỏi nào!")

        game_state['all_questions'] = df.to_dict('records')
        game_state['pin'] = str(random.randint(100000, 999999))
        game_state['used_indices'] = set()
        game_state['players'] = {}
        game_state['player_names'] = set()
        game_state['current_round_num'] = 0
        game_state['is_running'] = False
        game_state['king_sid'] = None

        print(f"[DEBUG] Upload thành công - PIN mới: {game_state['pin']} - Số câu hỏi: {len(game_state['all_questions'])}")

        # Tạo QR
        qr = qrcode.QRCode(box_size=10, border=2)
        qr.add_data(game_state['pin'])
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        qr_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')

        # Emit CHỈ đến host (room = sid hiện tại)
        emit('qr_ready', {
            'qr': qr_base64,
            'pin': game_state['pin']
        }, room=request.sid)

        emit('upload_success', {'msg': 'Upload thành công! QR và PIN đã sẵn sàng.'}, room=request.sid)

    except Exception as e:
        print(f"[ERROR] Upload thất bại: {str(e)}")
        emit('error', {'msg': str(e)}, room=request.sid)

# Các hàm còn lại giữ nguyên (join_request, approve, start_round, send_q, process_end_q, submit_ans, update_lb, finish_all, get_review)

@socketio.on('join_request')
def join(data):
    name = data.get('name', '').strip()
    pin = data.get('pin')
    
    if pin != game_state.get('pin'):
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
    emit('join_success', {'name': name}, room=sid)

# ... (các hàm khác giữ nguyên như code cũ của bạn)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)  # bật debug để xem log dễ hơn
