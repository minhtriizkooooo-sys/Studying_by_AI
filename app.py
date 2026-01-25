import gevent.monkey
gevent.monkey.patch_all()
import os, random, qrcode, io, base64, time, pandas as pd
from flask import Flask, render_template, request, send_file
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'marie_curie_2026'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

game_state = {
    "all_questions": [], "current_round_qs": [],
    "players": {}, "player_names": set(), "active_q_idx": -1,
    "start_time": 0, "pin": None, "is_running": False,
    "current_answers_count": 0, "last_winner_sid": None 
}

@app.route('/')
def index(): return render_template('index.html')

@app.route('/download_template')
def download_template():
    df = pd.DataFrame(columns=['Câu hỏi', 'Đáp án A', 'Đáp án B', 'Đáp án C', 'Đáp án D', 'Đáp án đúng', 'Giải thích'])
    df.loc[0] = ["1+1 bằng mấy?", "1", "2", "3", "4", "2", "Toán cơ bản"]
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine='xlsxwriter') as writer: df.to_excel(writer, index=False)
    out.seek(0)
    return send_file(out, as_attachment=True, download_name="template_marie_curie.xlsx")

@socketio.on('host_upload_file')
def handle_upload(data):
    try:
        header, encoded = data['content'].split(",", 1)
        df = pd.read_excel(io.BytesIO(base64.b64decode(encoded)))
        game_state.update({"all_questions": df.to_dict('records'), "pin": str(random.randint(100000, 999999)), "players": {}, "player_names": set()})
        qr = qrcode.QRCode(box_size=10, border=2); qr.add_data(game_state['pin']); qr.make(fit=True)
        buf = io.BytesIO(); qr.make_image().save(buf, format='PNG')
        emit('qr_ready', {'qr': base64.b64encode(buf.getvalue()).decode('utf-8'), 'pin': game_state['pin']})
    except: emit('error', {'msg': "Lỗi file!"})

@socketio.on('join_request')
def join(data):
    name, pin = data.get('name', '').strip(), data.get('pin')
    if pin == game_state['pin'] and name not in game_state['player_names']:
        game_state['players'][request.sid] = {"name": name, "total": 0, "last_pts": 0, "history": [], "approved": False}
        game_state['player_names'].add(name); emit('new_player_waiting', {'name': name, 'sid': request.sid}, broadcast=True); emit('join_received')

@socketio.on('approve_all')
def approve_all():
    for sid, p in game_state['players'].items(): p['approved'] = True; emit('approved_success', room=sid)
    update_lb()

@socketio.on('start_next_round')
def start_round():
    if not game_state['all_questions']: return
    selected = random.sample(range(len(game_state['all_questions'])), min(10, len(game_state['all_questions'])))
    game_state['current_round_qs'] = [game_state['all_questions'][i] for i in selected]
    game_state['active_q_idx'] = 0; game_state['is_running'] = True; game_state['last_winner_sid'] = None; send_q()

def send_q():
    idx = game_state['active_q_idx']
    if idx >= len(game_state['current_round_qs']):
        game_state['is_running'] = False; socketio.emit('stop_clock', broadcast=True); emit('enable_review', broadcast=True); return
    game_state['current_answers_count'] = 0; game_state['start_time'] = time.time()
    q = game_state['current_round_qs'][idx]
    socketio.emit('new_q', {'q': q, 'idx': idx + 1, 'total': len(game_state['current_round_qs'])}, broadcast=True)

@socketio.on('submit_ans')
def handle_sub(data):
    sid = request.sid
    if sid not in game_state['players'] or not game_state['is_running']: return
    p = game_state['players'][sid]; q = game_state['current_round_qs'][game_state['active_q_idx']]
    elapsed = time.time() - game_state['start_time']; is_correct = str(data['ans']).strip() == str(q['Đáp án đúng']).strip()
    
    pts = max(10, int(100 * (1 - elapsed / 15.0))) if is_correct else 0
    if is_correct and game_state['current_answers_count'] == 0:
        if sid == game_state['last_winner_sid']:
            bonus = random.randint(30, 70); pts += bonus
            socketio.emit('special_event', {'type': 'lucky', 'name': p['name'], 'val': bonus}, broadcast=True)
        elif game_state['last_winner_sid']:
            v_sid = game_state['last_winner_sid']
            if v_sid in game_state['players']:
                steal = int(game_state['players'][v_sid]['total'] * 0.15)
                game_state['players'][v_sid]['total'] -= steal; pts += steal
                socketio.emit('special_event', {'type': 'steal', 'msg': f"{p['name']} cướp {steal}đ từ {game_state['players'][v_sid]['name']}!"}, broadcast=True)
        game_state['last_winner_sid'] = sid

    p['total'] += pts; p['last_pts'] = pts
    p['history'].append({"idx": game_state['active_q_idx']+1, "q": q['Câu hỏi'], "A": q['Đáp án A'], "B": q['Đáp án B'], "C": q['Đáp án C'], "D": q['Đáp án D'], "u": data['ans'], "c": q['Đáp án đúng'], "ex": q['Giải thích'], "pts": pts})
    
    emit('answer_result', {'status': 'correct' if is_correct else 'wrong', 'pts': pts}, room=sid)
    game_state['current_answers_count'] += 1; update_lb()
    
    total_approved = sum(1 for pl in game_state['players'].values() if pl['approved'])
    if game_state['current_answers_count'] >= total_approved:
        socketio.sleep(1.5); game_state['active_q_idx'] += 1; send_q()

@socketio.on('times_up')
def handle_timeout():
    if game_state['is_running']: game_state['active_q_idx'] += 1; send_q()

def update_lb():
    lb = sorted([{"name": p['name'], "total": p['total'], "last": p['last_pts']} for p in game_state['players'].values() if p['approved']], key=lambda x: x['total'], reverse=True)
    socketio.emit('lb_update', lb)

@socketio.on('get_review')
def get_review(data):
    if data.get('is_host'):
        res = []
        for i, q in enumerate(game_state['current_round_qs']):
            for sid, p in game_state['players'].items():
                h = next((x for x in p['history'] if x['idx'] == i+1), None)
                res.append({"name": p['name'], "idx": i+1, "q": q['Câu hỏi'], "A": q['Đáp án A'], "B": q['Đáp án B'], "C": q['Đáp án C'], "D": q['Đáp án D'], "u": h['u'] if h else "Bỏ", "c": q['Đáp án đúng'], "pts": h['pts'] if h else 0, "ex": q['Giải thích']})
        emit('render_review', res)
    else: emit('render_review', game_state['players'][request.sid]['history'])

if __name__ == '__main__': socketio.run(app, host='0.0.0.0', port=5000)
