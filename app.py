import gevent.monkey
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
    "leader_sid": None # Lưu SID của người đang dẫn đầu
}

@app.route('/')
def index(): return render_template('index.html')

@app.route('/template')
def download_template():
    data = {
        'Câu hỏi': ['Ví dụ câu hỏi 1'], 'Đáp án A': ['A'], 'Đáp án B': ['B'],
        'Đáp án C': ['C'], 'Đáp án D': ['D'], 'Đáp án đúng': ['A'], 'Giải thích': ['Giải thích 1']
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
            "pin": str(random.randint(1000, 9999)), 
            "players": {}, "stats": {}, "leader_sid": None
        })
        qr = qrcode.QRCode(box_size=10, border=2); qr.add_data(game_state['pin']); qr.make(fit=True)
        buf = io.BytesIO(); qr.make_image().save(buf, format='PNG')
        emit('qr_ready', {'qr': base64.b64encode(buf.getvalue()).decode('utf-8'), 'pin': game_state['pin']})
    except: emit('error', {'msg': "Lỗi file!"})

@socketio.on('join_request')
def join(data):
    name, pin = data.get('name', '').strip(), data.get('pin')
    if pin == game_state['pin']:
        game_state['players'][request.sid] = {"name": name, "total": 0, "history": [], "approved": False}
        emit('new_player_waiting', {'name': name}, broadcast=True)
        emit('join_received')

@socketio.on('approve_all')
def approve_all():
    for sid, p in game_state['players'].items(): p['approved'] = True
    socketio.emit('approved_success', broadcast=True)
    update_lb()

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
        res = sorted([{"name": p['name'], "total": p['total']} for p in game_state['players'].values()], key=lambda x: x['total'], reverse=True)
        socketio.emit('game_over', {'results': res})
        socketio.emit('enable_review', broadcast=True)
        return
    
    game_state['submitted_count'] = 0
    game_state['start_time'] = time.time()
    game_state['stats'][idx] = {"correct": 0, "wrong": 0}
    
    # Xác định người dẫn đầu trước khi bắt đầu câu mới
    players_list = sorted(game_state['players'].items(), key=lambda x: x[1]['total'], reverse=True)
    game_state['leader_sid'] = players_list[0][0] if players_list else None
    
    socketio.emit('new_q', {'q': game_state['current_round_qs'][idx], 'idx': idx + 1, 'total': len(game_state['current_round_qs'])})

@socketio.on('submit_ans')
def handle_sub(data):
    sid = request.sid
    if sid not in game_state['players'] or not game_state['is_running']: return
    p = game_state['players'][sid]
    q_idx = game_state['active_q_idx']
    q = game_state['current_round_qs'][q_idx]
    
    user_ans = str(data['ans']).strip()
    correct_key = str(q['Đáp án đúng']).strip().upper()
    correct_content = str(q.get(f'Đáp án {correct_key}', '')).strip()
    
    is_correct = (user_ans == correct_content)
    if is_correct: game_state['stats'][q_idx]['correct'] += 1
    else: game_state['stats'][q_idx]['wrong'] += 1

    elapsed = time.time() - game_state['start_time']
    base = max(10, int(100 * (1 - elapsed/15))) if is_correct else 0
    
    event = ""
    if is_correct:
        # Hạng 1 trả lời đúng -> Lucky Spin
        if sid == game_state['leader_sid']:
            base *= 2
            event = "🎡 LUCKY SPIN (Hạng 1): X2 ĐIỂM!"
        else:
            # Kiểm tra xem người dẫn đầu có sai không để trao Mark Steal cho người hạng dưới
            leader = game_state['players'].get(game_state['leader_sid'])
            # Nếu người dẫn đầu chưa trả lời hoặc đã trả lời sai (kiểm tra history câu hiện tại)
            leader_correct = False
            if leader and len(leader['history']) > q_idx:
                if leader['history'][q_idx]['pts'] > 0: leader_correct = True
            
            if not leader_correct:
                base += 50
                event = "🏴‍☠️ MARK STEAL: +50 ĐIỂM!"

    p['total'] += base
    p['history'].append({"idx": q_idx+1, "q": q['Câu hỏi'], "u": user_ans, "c": correct_content, "pts": base, "ex": q.get('Giải thích',''), "event": event})
    
    emit('score_update', {'total': p['total'], 'last': base, 'correct': is_correct, 'event': event})
    
    game_state['submitted_count'] += 1
    total_approved = sum(1 for pl in game_state['players'].values() if pl['approved'])
    
    # Tự động chuyển câu nếu tất cả đã nộp
    if game_state['submitted_count'] >= total_approved:
        gevent.sleep(1) # Chờ 1 giây để user kịp thấy đúng/sai
        next_question_auto()
    else:
        update_lb()

@socketio.on('times_up')
def handle_timeout():
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
        p = game_state['players'][request.sid]
        emit('render_review', {'name': p['name'], 'data': p['history']})

@socketio.on('get_host_review')
def get_host_review():
    report = [{"idx": i+1, "q": q['Câu hỏi'], "c": game_state['stats'].get(i,{}).get('correct',0), "w": game_state['stats'].get(i,{}).get('wrong',0)} for i, q in enumerate(game_state['current_round_qs'])]
    emit('render_host_review', report)

if __name__ == '__main__': socketio.run(app, host='0.0.0.0', port=5000)
