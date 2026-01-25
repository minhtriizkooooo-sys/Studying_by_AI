import gevent.monkey
gevent.monkey.patch_all()

import os, random, qrcode, io, base64, time, pandas as pd
from flask import Flask, render_template, request, send_file
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'marie_curie_2024_stable'
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

@app.route('/download_template')
def download_template():
    df = pd.DataFrame(columns=['Câu hỏi', 'Đáp án A', 'Đáp án B', 'Đáp án C', 'Đáp án D', 'Đáp án đúng', 'Giải thích'])
    df.loc[0] = ["Ai là người phụ nữ đầu tiên nhận giải Nobel?", "Marie Curie", "Rosalind Franklin", "Ada Lovelace", "Mae Jemison", "Marie Curie", "Marie Curie là người đầu tiên nhận hai giải Nobel ở hai lĩnh vực khác nhau."]
    df.loc[1] = ["Đơn vị đo cường độ phóng xạ là gì?", "Watt", "Curie (Ci)", "Volt", "Ampere", "Curie (Ci)", "Được đặt tên để vinh danh ông bà Curie."]
    
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False)
    out.seek(0)
    return send_file(out, as_attachment=True, download_name="template_cau_hoi.xlsx")

@socketio.on('host_upload_file')
def handle_upload(data):
    try:
        header, encoded = data['content'].split(",", 1)
        file_bytes = base64.b64decode(encoded)
        if 'spreadsheetml' in header or 'excel' in header:
            df = pd.read_excel(io.BytesIO(file_bytes))
        else:
            df = pd.read_csv(io.BytesIO(file_bytes), encoding='utf-8-sig')
        
        game_state.update({
            "all_questions": df.to_dict('records'),
            "pin": str(random.randint(100000, 999999)),
            "used_indices": set(), "players": {}, "player_names": set(), "is_running": False
        })
        
        qr = qrcode.QRCode(box_size=10, border=2)
        qr.add_data(game_state['pin']); qr.make(fit=True)
        buf = io.BytesIO()
        qr.make_image().save(buf, format='PNG')
        emit('qr_ready', {'qr': base64.b64encode(buf.getvalue()).decode('utf-8'), 'pin': game_state['pin']})
    except Exception as e:
        emit('error', {'msg': "Lỗi: " + str(e)})

@socketio.on('join_request')
def join(data):
    name, pin = data.get('name', '').strip(), data.get('pin')
    if pin == game_state['pin'] and name not in game_state['player_names']:
        game_state['players'][request.sid] = {"name": name, "total": 0, "last_pts": 0, "history": [], "approved": False}
        game_state['player_names'].add(name)
        emit('new_player_waiting', {'name': name, 'sid': request.sid}, broadcast=True)
        emit('join_received')
    else:
        emit('join_failed', {'msg': 'Sai PIN hoặc tên đã tồn tại'})

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
        if not p['approved']:
            p['approved'] = True
            emit('approved_success', room=sid)
    update_lb()

@socketio.on('start_next_round')
def start_round():
    if not game_state['all_questions']: return
    game_state['current_round_num'] += 1
    avail = [i for i in range(len(game_state['all_questions'])) if i not in game_state['used_indices']]
    if len(avail) < 10: 
        game_state['used_indices'].clear()
        avail = list(range(len(game_state['all_questions'])))
    
    selected = random.sample(avail, min(10, len(avail)))
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
        'total': len(game_state['current_round_qs'])
    }, broadcast=True)

@socketio.on('submit_ans')
def handle_sub(data):
    sid = request.sid
    if sid not in game_state['players'] or not game_state['is_running']: return
    
    p = game_state['players'][sid]
    q_idx = game_state['active_q_idx']
    q = game_state['current_round_qs'][q_idx]
    
    elapsed = time.time() - game_state['start_time']
    is_correct = (str(data['ans']).strip() == str(q['Đáp án đúng']).strip())
    
    pts = 0
    if is_correct:
        pts = max(10, int(100 * (1 - elapsed / 15.0)))
        if game_state['current_answers_count'] == 0:
            if sid == game_state['last_winner_sid']:
                bonus = random.randint(30, 70)
                pts += bonus
                socketio.emit('special_event', {'type': 'lucky', 'name': p['name'], 'val': bonus})
            elif game_state['last_winner_sid'] is not None:
                victim_sid = game_state['last_winner_sid']
                steal_pts = int(game_state['players'][victim_sid]['total'] * 0.15)
                game_state['players'][victim_sid]['total'] -= steal_pts
                pts += steal_pts
                socketio.emit('special_event', {'type': 'steal', 'msg': f"{p['name']} cướp {steal_pts}đ từ {game_state['players'][victim_sid]['name']}!"})
            game_state['last_winner_sid'] = sid

    u_ans = next((l for l in ['A','B','C','D'] if str(q[f'Đáp án {l}']).strip() == str(data['ans']).strip()), "?")
    c_ans = next((l for l in ['A','B','C','D'] if str(q[f'Đáp án {l}']).strip() == str(q['Đáp án đúng']).strip()), "?")

    p['total'] += pts
    p['last_pts'] = pts
    p['history'].append({
        "idx": q_idx + 1, "q": q['Câu hỏi'], "u": u_ans, "c": c_ans,
        "pts": pts, "time": round(elapsed, 2), "ex": q['Giải thích']
    })
    
    game_state['current_answers_count'] += 1
    update_lb()

    total_approved = sum(1 for pl in game_state['players'].values() if pl['approved'])
    if game_state['current_answers_count'] >= total_approved:
        socketio.sleep(1.0)
        game_state['active_q_idx'] += 1
        send_q()

@socketio.on('times_up')
def handle_timeout():
    if game_state['is_running']:
        game_state['active_q_idx'] += 1
        send_q()

def update_lb():
    lb = sorted([{"name": p['name'], "total": p['total'], "last": p['last_pts']} for p in game_state['players'].values() if p['approved']], key=lambda x: x['total'], reverse=True)
    socketio.emit('lb_update', lb)

@socketio.on('get_review')
def get_review(data):
    if data.get('is_host'):
        res = []
        for i, q in enumerate(game_state['current_round_qs']):
            q_idx = i + 1
            c_ans = next((l for l in ['A','B','C','D'] if str(q[f'Đáp án {l}']).strip() == str(q['Đáp án đúng']).strip()), "?")
            for sid, p in game_state['players'].items():
                h = next((item for item in p['history'] if item['idx'] == q_idx), None)
                res.append({
                    "name": p['name'], "idx": q_idx, "q": q['Câu hỏi'],
                    "u": h['u'] if h else "Bỏ qua", "c": c_ans,
                    "pts": h['pts'] if h else 0, "time": h['time'] if h else 0, "ex": q['Giải thích']
                })
        emit('render_review', res)
    else:
        if request.sid in game_state['players']:
            emit('render_review', game_state['players'][request.sid]['history'])

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
