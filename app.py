import os, random, qrcode, io, base64, time, pandas as pd
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'marie_curie_2026_fixed'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

game_state = {
    "all_questions": [], "used_indices": set(), "current_round_qs": [],
    "players": {}, "player_names": set(), "active_q_idx": -1,
    "current_round_num": 0, "start_time": 0, "pin": None,
    "is_running": False, "king_sid": None, "current_answers": {}, "timer_id": 0
}

def update_lb():
    # PHÁT ĐIỂM REALTIME CHO TẤT CẢ USER TỨC THÌ
    lb = sorted([{"name": p['name'], "total": p['total'], "last": p['last_pts']} 
                 for p in game_state['players'].values() if p['approved']], 
                key=lambda x: x['total'], reverse=True)
    socketio.emit('lb_update', lb)

@app.route('/')
def index(): return render_template('index.html')

@socketio.on('host_upload_file')
def handle_upload(data):
    try:
        header, encoded = data['content'].split(",", 1)
        df = pd.read_excel(io.BytesIO(base64.b64decode(encoded))) if 'xlsx' in header else pd.read_csv(io.BytesIO(base64.b64decode(encoded)), encoding='utf-8-sig')
        game_state.update({"all_questions": df.to_dict('records'), "pin": str(random.randint(100000, 999999)), "used_indices": set()})
        qr = qrcode.QRCode(box_size=10, border=2)
        qr.add_data(game_state['pin']); qr.make(fit=True); buf = io.BytesIO()
        qr.make_image().save(buf, format='PNG')
        emit('qr_ready', {'qr': base64.b64encode(buf.getvalue()).decode('utf-8'), 'pin': game_state['pin']})
    except Exception as e: emit('error', {'msg': str(e)})

@socketio.on('join_request')
def join(data):
    name, pin = data.get('name', '').strip(), data.get('pin')
    if pin != game_state['pin'] or name in game_state['player_names']: return emit('join_failed', {'msg': 'PIN sai hoặc tên đã tồn tại'})
    game_state['players'][request.sid] = {"name": name, "total": 0, "last_pts": 0, "history": [], "approved": False}
    game_state['player_names'].add(name); emit('new_player_waiting', {'name': name, 'sid': request.sid}, broadcast=True)

@socketio.on('approve_player')
def approve(data):
    sid = data.get('sid'); 
    if sid in game_state['players']:
        game_state['players'][sid]['approved'] = True
        emit('approved_success', room=sid); update_lb()

@socketio.on('approve_all')
def approve_all():
    for sid in game_state['players']: game_state['players'][sid]['approved'] = True
    emit('approved_success', broadcast=True); update_lb()

@socketio.on('start_next_round')
def start_round():
    if len(game_state['all_questions']) < 10: return
    game_state['current_round_num'] += 1
    avail = [i for i in range(len(game_state['all_questions'])) if i not in game_state['used_indices']]
    selected = random.sample(avail, 10); game_state['used_indices'].update(selected)
    game_state['current_round_qs'] = [game_state['all_questions'][i] for i in selected]
    game_state['active_q_idx'] = 0; game_state['is_running'] = True; send_q()

def send_q():
    idx = game_state['active_q_idx']
    if idx >= 10: game_state['is_running'] = False; emit('enable_review', broadcast=True); return
    game_state['current_answers'] = {}
    for s in game_state['players']: game_state['players'][s]['last_pts'] = 0
    game_state.update({"start_time": time.time()})
    emit('new_q', {'q': game_state['current_round_qs'][idx], 'idx': idx + 1, 'round': game_state['current_round_num']}, broadcast=True)

@socketio.on('submit_ans')
def handle_sub(data):
    sid = request.sid
    if sid not in game_state['players'] or sid in game_state['current_answers'] or not game_state['is_running']: return
    
    elapsed = time.time() - game_state['start_time']
    q = game_state['current_round_qs'][game_state['active_q_idx']]
    user_ans = str(data['ans']).strip()
    correct_ans = str(q['Đáp án đúng']).strip()
    is_correct = (user_ans == correct_ans)
    pts = max(10, int(100 * (1 - elapsed / 15.0))) if is_correct else 0
    
    # XỬ LÝ SỰ KIỆN LUCKY SPIN / STEAL
    if is_correct:
        is_fastest = not any(v['correct'] for v in game_state['current_answers'].values())
        if is_fastest:
            if sid == game_state['king_sid']:
                bonus = int(pts * (random.randint(15, 20) / 100))
                pts += bonus
                socketio.emit('special_event', {'type': 'lucky', 'name': game_state['players'][sid]['name'], 'val': bonus})
            elif game_state['king_sid']:
                stolen = int(game_state['players'][game_state['king_sid']]['total'] * 0.15)
                if stolen > 0:
                    game_state['players'][game_state['king_sid']]['total'] -= stolen
                    pts += stolen
                    socketio.emit('special_event', {'type': 'steal', 'msg': f"⚡ {game_state['players'][sid]['name']} cướp {stolen}đ từ {game_state['players'][game_state['king_sid']]['name']}!"})

    p = game_state['players'][sid]
    p['total'] += pts
    p['last_pts'] = pts
    # LƯU HISTORY ĐỂ REVIEW ĐÚNG YÊU CẦU
    p['history'].append({
        "vong": game_state['current_round_num'], "cau": game_state['active_q_idx'] + 1,
        "q": q['Câu hỏi'], "options": [q['Đáp án A'], q['Đáp án B'], q['Đáp án C'], q['Đáp án D']],
        "u": user_ans, "c": correct_ans, "ex": q['Giải thích'], "pts": pts
    })
    game_state['current_answers'][sid] = {"correct": is_correct}
    game_state['king_sid'] = max(game_state['players'], key=lambda x: game_state['players'][x]['total'])
    
    update_lb() # CẬP NHẬT ĐIỂM NGAY LẬP TỨC

@socketio.on('get_review')
def get_review():
    if request.sid in game_state['players']:
        emit('render_review', game_state['players'][request.sid]['history'])

@socketio.on('finish_all')
def finish_all():
    game_state['is_running'] = False
    emit('kill_timers', broadcast=True); emit('enable_review', broadcast=True)

if __name__ == '__main__': socketio.run(app, host='0.0.0.0', port=5000)
