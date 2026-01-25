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
    template = "Câu hỏi,Đáp án A,Đáp án B,Đáp án C,Đáp án D,Đáp án đúng,Giải thích\n" \
               "Ví dụ: 1+1 bằng mấy?,1,2,3,4,B,Phép tính cơ bản..."
    return template, 200, {'Content-Type': 'text/plain; charset=utf-8'}

@socketio.on('host_upload_file')
def handle_upload(data):
    try:
        header, encoded = data['content'].split(",", 1)
        content_bytes = base64.b64decode(encoded)
        if header.lower().find('xlsx') > -1 or content_bytes.startswith(b'PK\x03\x04'):
            df = pd.read_excel(io.BytesIO(content_bytes))
        else:
            df = pd.read_csv(io.BytesIO(content_bytes), encoding='utf-8-sig')
        
        df.columns = df.columns.str.strip()
        game_state['all_questions'] = df.to_dict('records')
        game_state['pin'] = str(random.randint(100000, 999999))
        game_state['used_indices'] = set()
        game_state['players'] = {}
        game_state['player_names'] = set()
        game_state['king_sid'] = None

        qr = qrcode.QRCode(box_size=10, border=2)
        qr.add_data(game_state['pin'])
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        emit('qr_ready', {'qr': base64.b64encode(buf.getvalue()).decode('utf-8'), 'pin': game_state['pin']})
    except Exception as e:
        emit('error', {'msg': str(e)})

@socketio.on('join_request')
def join(data):
    name, pin = data.get('name', '').strip(), data.get('pin')
    if pin != game_state['pin'] or name in game_state['player_names']:
        return emit('join_failed', {'msg': 'PIN sai hoặc tên đã tồn tại!'})
    sid = request.sid
    game_state['players'][sid] = {"name": name, "total": 0, "last_pts": 0, "history": [], "approved": False}
    game_state['player_names'].add(name)
    emit('new_player_waiting', {'name': name, 'sid': sid}, broadcast=True)
    emit('join_received')

@socketio.on('approve_player')
def approve(data):
    sid = data.get('sid')
    if sid in game_state['players']:
        game_state['players'][sid]['approved'] = True
        emit('approved_success', room=sid)
        update_lb()

@socketio.on('approve_all')
def approve_all():
    for sid in game_state['players']: game_state['players'][sid]['approved'] = True
    emit('approved_success', broadcast=True)
    update_lb()

@socketio.on('start_next_round')
def start_round():
    if game_state['is_running'] or len(game_state['all_questions']) < 10: return
    game_state['current_round_num'] += 1
    avail = [i for i in range(len(game_state['all_questions'])) if i not in game_state['used_indices']]
    selected = random.sample(avail, 10)
    game_state['used_indices'].update(selected)
    game_state['current_round_qs'] = [game_state['all_questions'][i] for i in selected]
    game_state['active_q_idx'] = 0
    game_state['is_running'] = True
    send_q()

def send_q():
    idx = game_state['active_q_idx']
    if idx >= 10:
        game_state['is_running'] = False
        emit('round_end', broadcast=True)
        return
    game_state['current_answers'] = {}
    for s in game_state['players']: game_state['players'][s]['last_pts'] = 0
    game_state['start_time'] = time.time()
    game_state['timer_id'] += 1
    q_data = game_state['current_round_qs'][idx]
    emit('new_q', {'q': q_data, 'idx': idx + 1, 'round': game_state['current_round_num']}, broadcast=True)
    
    this_timer = game_state['timer_id']
    socketio.sleep(15.5)
    if game_state['timer_id'] == this_timer:
        game_state['active_q_idx'] += 1
        send_q()

@socketio.on('submit_ans')
def handle_sub(data):
    sid = request.sid
    if sid not in game_state['players'] or sid in game_state['current_answers'] or not game_state['is_running']: return
    
    elapsed = time.time() - game_state['start_time']
    idx = game_state['active_q_idx']
    q = game_state['current_round_qs'][idx]
    is_correct = (str(data['ans']).strip() == str(q['Đáp án đúng']).strip())
    pts = max(0, int(100 * (1 - elapsed / 15.0))) if is_correct else 0
    
    if idx > 0 and is_correct:
        is_fastest = not any(v['correct'] for v in game_state['current_answers'].values())
        king_sid = game_state['king_sid']
        
        if is_fastest:
            if sid == king_sid:
                # LUCKY SPIN: 15% - 20% điểm của câu hiện tại
                percent = random.randint(15, 20)
                bonus = int(pts * (percent / 100))
                pts += bonus
                emit('special_event', {'type': 'lucky', 'name': game_state['players'][sid]['name'], 'val': bonus}, broadcast=True)
            elif king_sid and king_sid in game_state['players']:
                # MARK STEAL: 15% tổng điểm của King
                stolen = int(game_state['players'][king_sid]['total'] * 0.15)
                if stolen > 0:
                    game_state['players'][king_sid]['total'] -= stolen
                    pts += stolen
                    emit('special_event', {'type': 'steal', 'name': game_state['players'][sid]['name'], 'victim': game_state['players'][king_sid]['name'], 'val': stolen}, broadcast=True)

    game_state['players'][sid]['total'] += pts
    game_state['players'][sid]['last_pts'] = pts
    game_state['players'][sid]['history'].append({
        "vong": game_state['current_round_num'], "cau": idx + 1, "q": q['Câu hỏi'],
        "options": [q['Đáp án A'], q['Đáp án B'], q['Đáp án C'], q['Đáp án D']],
        "u": str(data['ans']).strip(), "c": str(q['Đáp án đúng']).strip(), "ex": q['Giải thích'], "pts": pts, "is_correct": is_correct
    })
    game_state['current_answers'][sid] = {"correct": is_correct, "time": elapsed}
    game_state['king_sid'] = max(game_state['players'], key=lambda x: game_state['players'][x]['total'])
    update_lb()

def update_lb():
    lb = sorted([{"name": p['name'], "total": p['total'], "last": p['last_pts']} for p in game_state['players'].values() if p['approved']], key=lambda x: x['total'], reverse=True)
    emit('lb_update', lb, broadcast=True)

@socketio.on('finish_all')
def finish():
    game_state['is_running'] = False
    game_state['timer_id'] += 1
    emit('kill_timers', broadcast=True)
    emit('enable_review', broadcast=True)

@socketio.on('get_review')
def get_review():
    if request.sid in game_state['players']:
        emit('render_review', game_state['players'][request.sid]['history'], room=request.sid)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
