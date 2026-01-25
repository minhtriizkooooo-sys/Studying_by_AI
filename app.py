import gevent.monkey
gevent.monkey.patch_all() # Quan trọng để chạy với Gunicorn Gevent

import os, random, qrcode, io, base64, time, pandas as pd
from flask import Flask, render_template, request, send_file
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'marie_curie_stable'
# Khởi tạo SocketIO với gevent
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
    "current_answers_count": 0,
    "last_winner_sid": None
}

@app.route('/')
def index(): return render_template('index.html')

@app.route('/template')
def download_template():
    df = pd.DataFrame(columns=['Câu hỏi', 'Đáp án A', 'Đáp án B', 'Đáp án C', 'Đáp án D', 'Đáp án đúng', 'Giải thích'])
    df.loc[0] = ["Marie Curie sinh năm bao nhiêu?", "1867", "1870", "1890", "1900", "1867", "Bà sinh ngày 7/11/1867 tại Ba Lan."]
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False)
    out.seek(0)
    return send_file(out, as_attachment=True, download_name="mau_cau_hoi.xlsx", mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@socketio.on('host_upload_file')
def handle_upload(data):
    try:
        header, encoded = data['content'].split(",", 1)
        file_bytes = base64.b64decode(encoded)
        if 'spreadsheetml' in header or 'excel' in header:
            df = pd.read_excel(io.BytesIO(file_bytes))
        else:
            df = pd.read_csv(io.BytesIO(file_bytes), encoding='utf-8-sig')

        cols = ['Câu hỏi', 'Đáp án A', 'Đáp án B', 'Đáp án C', 'Đáp án D', 'Đáp án đúng', 'Giải thích']
        if not all(c in df.columns for c in cols):
            return emit('error', {'msg': 'File sai định dạng cột!'})

        game_state.update({
            "all_questions": df.to_dict('records'),
            "pin": str(random.randint(100000, 999999)),
            "used_indices": set(),
            "players": {},
            "player_names": set()
        })

        qr = qrcode.QRCode(box_size=10, border=2)
        qr.add_data(game_state['pin'])
        qr.make(fit=True)
        buf = io.BytesIO()
        qr.make_image().save(buf, format='PNG')
        emit('qr_ready', {'qr': base64.b64encode(buf.getvalue()).decode('utf-8'), 'pin': game_state['pin']})
    except Exception as e:
        emit('error', {'msg': str(e)})

@socketio.on('join_request')
def join(data):
    name, pin = data.get('name', '').strip(), data.get('pin')
    if pin == game_state['pin'] and name not in game_state['player_names']:
        game_state['players'][request.sid] = {"name": name, "total": 0, "last_pts": 0, "history": [], "approved": False}
        game_state['player_names'].add(name)
        emit('new_player_waiting', {'name': name, 'sid': request.sid}, broadcast=True)
        emit('join_received')
    else:
        emit('join_failed', {'msg': 'Sai PIN hoặc tên trùng'})

@socketio.on('approve_player')
def approve(data):
    sid = data.get('sid')
    if sid in game_state['players']:
        game_state['players'][sid]['approved'] = True
        emit('approved_success', room=sid)
        update_lb()

@socketio.on('approve_all')
def approve_all():
    for sid, p in game_state['players'].items():
        p['approved'] = True
        emit('approved_success', room=sid)
    update_lb()

@socketio.on('start_next_round')
def start_round():
    if len(game_state['all_questions']) < 10: 
        return emit('error', {'msg': 'Cần tối thiểu 10 câu hỏi!'})
    
    game_state['current_round_num'] += 1
    avail = [i for i in range(len(game_state['all_questions'])) if i not in game_state['used_indices']]
    if len(avail) < 10: 
        game_state['used_indices'].clear()
        avail = list(range(len(game_state['all_questions'])))
    
    selected = random.sample(avail, 10)
    game_state['used_indices'].update(selected)
    game_state['current_round_qs'] = [game_state['all_questions'][i] for i in selected]
    game_state['active_q_idx'] = 0
    game_state['is_running'] = True
    game_state['last_winner_sid'] = None
    send_q()

def send_q():
    idx = game_state['active_q_idx']
    if idx >= len(game_state['current_round_qs']):
        game_state['is_running'] = False
        emit('enable_review', broadcast=True)
        return
    
    game_state['current_answers_count'] = 0
    game_state['start_time'] = time.time()
    q_data = game_state['current_round_qs'][idx]
    
    emit('new_q', {
        'q': {k: q_data[k] for k in ['Câu hỏi', 'Đáp án A', 'Đáp án B', 'Đáp án C', 'Đáp án D']},
        'idx': idx + 1, 
        'round': game_state['current_round_num']
    }, broadcast=True)

@socketio.on('submit_ans')
def handle_sub(data):
    sid = request.sid
    if sid not in game_state['players'] or not game_state['is_running']: return
    
    p = game_state['players'][sid]
    q_idx = game_state['active_q_idx']
    q = game_state['current_round_qs'][q_idx]
    
    # Chống nộp 2 lần
    if any(h['cau'] == q_idx + 1 and h['vong'] == game_state['current_round_num'] for h in p['history']): return

    user_ans_val = str(data['ans']).strip()
    correct_val = str(q['Đáp án đúng']).strip()
    
    elapsed = time.time() - game_state['start_time']
    is_correct = (user_ans_val == correct_val)
    pts = max(10, int(100 * (1 - elapsed / 15.0))) if is_correct else 0
    
    # Sự kiện đặc biệt
    if q_idx > 0 and is_correct and game_state['current_answers_count'] == 0:
        if sid == game_state['last_winner_sid']:
            # Lucky Spin
            bonus = random.randint(10, 30)
            pts += bonus
            emit('special_event', {'type': 'lucky', 'name': p['name'], 'val': bonus}, broadcast=True)
        elif game_state['last_winner_sid'] is not None:
            # Mark Steal
            emit('special_event', {'type': 'steal', 'msg': f"{p['name']} đã cướp điểm từ King!"}, broadcast=True)
            pts = int(pts * 1.2) # Thưởng thêm 20% vì cướp thành công

    if is_correct and game_state['current_answers_count'] == 0:
        game_state['last_winner_sid'] = sid

    # Tìm Label cho history
    u_lab = next((l for l in ['A','B','C','D'] if str(q[f'Đáp án {l}']).strip() == user_ans_val), "?")
    c_lab = next((l for l in ['A','B','C','D'] if str(q[f'Đáp án {l}']).strip() == correct_val), "?")

    p['total'] += pts
    p['last_pts'] = pts
    p['history'].append({
        "vong": game_state['current_round_num'], "cau": q_idx + 1,
        "q": q['Câu hỏi'], "options": [q['Đáp án A'], q['Đáp án B'], q['Đáp án C'], q['Đáp án D']],
        "u": u_lab, "c": c_lab, "ex": q['Giải thích'], "pts": pts
    })
    
    game_state['current_answers_count'] += 1
    update_lb()

    total_approved = sum(1 for pl in game_state['players'].values() if pl['approved'])
    if game_state['current_answers_count'] >= total_approved:
        socketio.sleep(2) 
        game_state['active_q_idx'] += 1
        send_q()

@socketio.on('times_up')
def handle_timeout():
    game_state['active_q_idx'] += 1
    send_q()

def update_lb():
    lb = sorted([{"name": p['name'], "total": p['total'], "last": p['last_pts']} 
                 for p in game_state['players'].values() if p['approved']], 
                key=lambda x: x['total'], reverse=True)
    socketio.emit('lb_update', lb)

@socketio.on('get_review')
def get_review():
    if request.sid in game_state['players']:
        emit('render_review', game_state['players'][request.sid]['history'])

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
