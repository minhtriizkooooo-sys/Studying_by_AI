gevent.monkey.patch_all()

import os, random, qrcode, io, base64, time, pandas as pd
from flask import Flask, render_template, request, send_file
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'marie_curie_smart_edu'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

game_state = {
    "all_questions": [], 
    "current_round_qs": [],
    "players": {}, 
    "active_q_idx": -1,
    "start_time": 0, 
    "pin": None, 
    "is_running": False,
    "stats": {},
    "submitted_count": 0,
    "leader_sid": None,
    "fastest_sid_this_round": None
}

@app.route('/')
def index(): return render_template('index.html')

@app.route('/template')
def download_template():
    data = {
        'Câu hỏi': ['Câu hỏi mẫu'], 'Đáp án A': ['A'], 'Đáp án B': ['B'],
        'Đáp án C': ['C'], 'Đáp án D': ['D'], 'Đáp án đúng': ['A'], 'Giải thích': ['Giải thích mẫu']
    }
    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)
    return send_file(output, as_attachment=True, download_name="TEMPLATE_QUIZ.xlsx")

@socketio.on('host_upload_file')
def handle_upload(data):
    try:
        header, encoded = data['content'].split(",", 1)
        df = pd.read_excel(io.BytesIO(base64.b64decode(encoded)))
        game_state.update({
            "all_questions": df.to_dict('records'), 
            "pin": str(random.randint(100000, 999999)), 
            "players": {}, "stats": {}, "leader_sid": None, "is_running": False
        })
        qr = qrcode.QRCode(box_size=10, border=2); qr.add_data(game_state['pin']); qr.make(fit=True)
        buf = io.BytesIO(); qr.make_image().save(buf, format='PNG')
        emit('qr_ready', {'qr': base64.b64encode(buf.getvalue()).decode('utf-8'), 'pin': game_state['pin']})
    except: emit('error', {'msg': "Lỗi file Excel!"})

@socketio.on('join_request')
def join(data):
    name, pin = data.get('name', '').strip(), data.get('pin')
    if pin == game_state['pin']:
        game_state['players'][request.sid] = {"name": name, "total": 0, "history": [], "approved": False}
        socketio.emit('new_player_waiting', {'name': name})
        emit('join_received')

@socketio.on('approve_all')
def approve_all():
    for sid in game_state['players']: 
        game_state['players'][sid]['approved'] = True
    socketio.emit('approved_success')

@socketio.on('start_next_round')
def start_round():
    if not game_state['all_questions']: return
    qs = random.sample(game_state['all_questions'], min(10, len(game_state['all_questions'])))
    game_state.update({"current_round_qs": qs, "active_q_idx": 0, "is_running": True})
    send_q()

def send_q():
    idx = game_state['active_q_idx']
    if idx >= len(game_state['current_round_qs']):
        game_state['is_running'] = False
        res = sorted([{"name": p['name'], "total": p['total']} for p in game_state['players'].values() if p['approved']], key=lambda x: x['total'], reverse=True)
        socketio.emit('game_over', {'results': res})
        socketio.emit('enable_review', broadcast=True)
        return
    
    game_state['submitted_count'] = 0
    game_state['start_time'] = time.time()
    game_state['stats'][idx] = {"correct": 0, "wrong": 0}
    game_state['fastest_sid_this_round'] = None
    
    players_list = sorted(game_state['players'].items(), key=lambda x: x[1]['total'], reverse=True)
    game_state['leader_sid'] = players_list[0][0] if players_list and players_list[0][1]['total'] > 0 else None
    
    q_data = game_state['current_round_qs'][idx]
    socketio.emit('new_q', {'q': q_data, 'idx': idx + 1, 'total': len(game_state['current_round_qs'])})

@socketio.on('submit_ans')
def handle_sub(data):
    sid = request.sid
    if sid not in game_state['players'] or not game_state['is_running']: return
    p = game_state['players'][sid]
    q_idx = game_state['active_q_idx']
    q = game_state['current_round_qs'][q_idx]
    
    user_choice_letter = data['letter'] # A, B, C, D
    user_ans_content = str(data['ans']).strip()
    correct_key = str(q['Đáp án đúng']).strip().upper()
    correct_content = str(q.get(f'Đáp án {correct_key}', '')).strip()
    is_correct = (user_ans_content == correct_content)

    elapsed = time.time() - game_state['start_time']
    base = max(10, int(100 * (1 - elapsed/15))) if is_correct else 0
    
    event = ""
    if is_correct:
        game_state['stats'][q_idx]['correct'] += 1
        if sid == game_state['leader_sid']:
            base *= 2
            event = "🎡 LUCKY SPIN (Top 1): X2 ĐIỂM!"
        elif game_state['fastest_sid_this_round'] is None:
            game_state['fastest_sid_this_round'] = sid
            base += 50
            event = "🏴‍☠️ MARK STEAL: +50đ TỐC ĐỘ!"
    else:
        game_state['stats'][q_idx]['wrong'] += 1

    p['total'] += base
    # Lưu toàn bộ thông tin phục vụ review
    p['history'].append({
        "idx": q_idx+1, 
        "q": q['Câu hỏi'], 
        "A": q['Đáp án A'], "B": q['Đáp án B'], "C": q['Đáp án C'], "D": q['Đáp án D'],
        "u_choice": user_choice_letter,
        "c_choice": correct_key,
        "pts": base, 
        "ex": q.get('Giải thích',''), 
        "event": event
    })
    
    emit('score_update', {'total': p['total'], 'last': base, 'correct': is_correct, 'event': event})
    
    game_state['submitted_count'] += 1
    total_approved = sum(1 for pl in game_state['players'].values() if pl['approved'])
    
    if game_state['submitted_count'] >= total_approved:
        gevent.sleep(1.0)
        next_question_auto()
    else:
        update_lb()

@socketio.on('times_up')
def handle_timeout():
    for sid, p in game_state['players'].items():
        if p['approved'] and len(p['history']) <= game_state['active_q_idx']:
            q = game_state['current_round_qs'][game_state['active_q_idx']]
            correct_key = str(q['Đáp án đúng']).strip().upper()
            p['history'].append({
                "idx": game_state['active_q_idx']+1, "q": q['Câu hỏi'], 
                "A": q['Đáp án A'], "B": q['Đáp án B'], "C": q['Đáp án C'], "D": q['Đáp án D'],
                "u_choice": "KHÔNG CHỌN", "c_choice": correct_key, 
                "pts": 0, "ex": q.get('Giải thích',''), "event": ""
            })
    next_question_auto()

def next_question_auto():
    if game_state['is_running']:
        game_state['active_q_idx'] += 1
        send_q()

def update_lb():
    lb = sorted([{"name": p['name'], "total": p['total']} for p in game_state['players'].values() if p['approved']], key=lambda x: x['total'], reverse=True)
    socketio.emit('lb_update', lb)

@socketio.on('get_review')
def get_review():
    if request.sid in game_state['players']:
        emit('render_review', game_state['players'][request.sid]['history'])

@socketio.on('get_host_review')
def get_host_review():
    report = []
    for i, q in enumerate(game_state['current_round_qs']):
        user_details = []
        for p_sid, p in game_state['players'].items():
            if len(p['history']) > i:
                hist = p['history'][i]
                user_details.append({"name": p['name'], "choice": hist['u_choice'], "pts": hist['pts']})
        
        correct_key = str(q['Đáp án đúng']).strip().upper()
        report.append({
            "idx": i+1, "q": q['Câu hỏi'], 
            "A": q['Đáp án A'], "B": q['Đáp án B'], "C": q['Đáp án C'], "D": q['Đáp án D'],
            "c_choice": correct_key,
            "ex": q.get('Giải thích',''),
            "users": user_details
        })
    emit('render_host_review', report)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
