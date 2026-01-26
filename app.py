import gevent.monkey
gevent.monkey.patch_all()
import os, random, qrcode, io, base64, time, pandas as pd
from flask import Flask, render_template, request, send_file
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'marie_curie_smart_2026'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

game_state = {
    "all_questions": [], "current_round_qs": [],
    "players": {}, "player_names": set(), "active_q_idx": -1,
    "start_time": 0, "pin": None, "is_running": False
}

@app.route('/')
def index(): return render_template('index.html')

@socketio.on('host_upload_file')
def handle_upload(data):
    try:
        header, encoded = data['content'].split(",", 1)
        df = pd.read_excel(io.BytesIO(base64.b64decode(encoded)))
        game_state.update({"all_questions": df.to_dict('records'), "pin": str(random.randint(100000, 999999)), "players": {}, "player_names": set()})
        qr = qrcode.QRCode(box_size=10, border=2); qr.add_data(game_state['pin']); qr.make(fit=True)
        buf = io.BytesIO(); qr.make_image().save(buf, format='PNG')
        emit('qr_ready', {'qr': base64.b64encode(buf.getvalue()).decode('utf-8'), 'pin': game_state['pin']})
    except: emit('error', {'msg': "Lỗi file Excel!"})

@socketio.on('join_request')
def join(data):
    name, pin = data.get('name', '').strip(), data.get('pin')
    if pin == game_state['pin'] and name not in game_state['player_names']:
        game_state['players'][request.sid] = {"name": name, "total": 0, "last_pts": 0, "history": [], "approved": False}
        game_state['player_names'].add(name)
        emit('new_player_waiting', {'name': name, 'sid': request.sid}, broadcast=True)
        emit('join_received')

@socketio.on('approve_all')
def approve_all():
    for sid, p in game_state['players'].items(): 
        if not p['approved']:
            p['approved'] = True
            socketio.emit('approved_success', room=sid)
    update_lb()

@socketio.on('start_next_round')
def start_round():
    if not game_state['all_questions']: return
    # Lấy ngẫu nhiên 10 câu hoặc toàn bộ nếu ít hơn 10
    num_q = min(10, len(game_state['all_questions']))
    selected = random.sample(game_state['all_questions'], num_q)
    game_state.update({"current_round_qs": selected, "active_q_idx": 0, "is_running": True})
    send_q()

def send_q():
    idx = game_state['active_q_idx']
    if idx >= len(game_state['current_round_qs']):
        game_state['is_running'] = False
        final_lb = sorted([{"name": p['name'], "total": p['total']} for p in game_state['players'].values() if p['approved']], key=lambda x: x['total'], reverse=True)
        socketio.emit('game_over', {'results': final_lb})
        socketio.emit('enable_review', broadcast=True) # Kích hoạt nút xem lại bài
        return
    game_state['start_time'] = time.time()
    q = game_state['current_round_qs'][idx]
    socketio.emit('new_q', {'q': q, 'idx': idx + 1, 'total': len(game_state['current_round_qs'])})

@socketio.on('submit_ans')
def handle_sub(data):
    sid = request.sid
    if sid not in game_state['players'] or not game_state['is_running']: return
    p = game_state['players'][sid]
    q = game_state['current_round_qs'][game_state['active_q_idx']]
    
    user_choice_text = str(data['ans']).strip()
    raw_correct = str(q['Đáp án đúng']).strip().upper() # Thường là 'A', 'B', 'C' hoặc 'D'
    
    # Logic so khớp thông minh:
    # Nếu Đáp án đúng trong Excel là "A" -> Lấy nội dung cột "Đáp án A" để so sánh
    actual_correct_text = str(q.get(f'Đáp án {raw_correct}', raw_correct)).strip()
    
    is_correct = (user_choice_text.lower() == actual_correct_text.lower())
    
    elapsed = time.time() - game_state['start_time']
    base_pts = max(10, int(100 * (1 - elapsed / 15.0))) if is_correct else 0
    
    event_msg = ""
    if is_correct:
        roll = random.random()
        if roll > 0.85:
            base_pts *= 2
            event_msg = "🎡 LUCKY SPIN: X2 ĐIỂM!"
        elif roll < 0.10:
            base_pts += 50
            event_msg = "🏴‍☠️ MARK STEAL: +50đ!"

    p['total'] += base_pts
    p['last_pts'] = base_pts
    p['history'].append({
        "idx": game_state['active_q_idx'] + 1, 
        "q": q['Câu hỏi'], 
        "u": user_choice_text, 
        "c": actual_correct_text, 
        "pts": base_pts, 
        "ex": q.get('Giải thích', ''), 
        "event": event_msg
    })
    
    emit('score_update', {'total': p['total'], 'last': base_pts, 'correct': is_correct, 'event': event_msg})
    update_lb()

@socketio.on('times_up')
def handle_timeout():
    if game_state['is_running']:
        game_state['active_q_idx'] += 1
        send_q()

def update_lb():
    lb = sorted([{"name": p['name'], "total": p['total'], "last": p['last_pts']} for p in game_state['players'].values() if p['approved']], key=lambda x: x['total'], reverse=True)
    socketio.emit('lb_update', lb)

@socketio.on('get_review')
def get_review():
    if request.sid in game_state['players']:
        emit('render_review', game_state['players'][request.sid]['history'])

if __name__ == '__main__': socketio.run(app, host='0.0.0.0', port=5000)
