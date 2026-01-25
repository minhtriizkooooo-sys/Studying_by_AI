import os, random, qrcode, io, base64, time
import pandas as pd
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'marie_curie_2026_final_ultimate'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

game = {
    "all_qs": [], "used_idx": set(), "round_qs": [],
    "players": {}, "active_idx": -1, "round_num": 0,
    "start_t": 0, "pin": None, "is_running": False, "king_sid": None,
    "current_ans": {}, "timer_id": 0
}

@app.route('/')
def index(): return render_template('index.html')

@socketio.on('host_upload_file')
def handle_upload(data):
    try:
        content = base64.b64decode(data['content'].split(",")[1])
        df = pd.read_excel(io.BytesIO(content)) if b'xl' in content else pd.read_csv(io.BytesIO(content), encoding='utf-8-sig')
        df.columns = df.columns.str.strip()
        game['all_qs'] = df.to_dict('records')
        game['pin'] = str(random.randint(100000, 999999))
        qr = qrcode.QRCode(box_size=10, border=2)
        qr.add_data(game['pin']); qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO(); img.save(buf, format='PNG')
        emit('qr_ready', {'qr': base64.b64encode(buf.getvalue()).decode('utf-8'), 'pin': game['pin']})
    except Exception as e: emit('error', {'msg': f"Lỗi file: {str(e)}"})

@socketio.on('join_request')
def join(data):
    if data.get('pin') == game['pin']:
        sid = request.sid
        game['players'][sid] = {"name": data['name'], "total": 0, "last": 0, "history": [], "approved": False}
        emit('new_player_waiting', {'name': data['name'], 'sid': sid}, broadcast=True)

@socketio.on('approve_player')
def approve(data):
    sid = data.get('sid')
    if sid in game['players']:
        game['players'][sid]['approved'] = True
        emit('approved_success', room=sid)
        update_lb()

@socketio.on('approve_all')
def approve_all():
    for s in game['players']: game['players'][s]['approved'] = True
    emit('approved_success', broadcast=True); update_lb()

@socketio.on('start_next_round')
def start_round():
    if game['is_running']: return
    avail = [i for i in range(len(game['all_qs'])) if i not in game['used_idx']]
    if len(avail) < 10: return emit('error', {'msg': "Hết câu hỏi trong kho!"})
    game['round_num'] += 1
    sel = random.sample(avail, 10)
    game['used_idx'].update(sel)
    game['round_qs'] = [game['all_qs'][i] for i in sel]
    game['active_idx'] = 0; game['is_running'] = True
    send_q()

def send_q():
    idx = game['active_idx']
    if idx < 10 and game['is_running']:
        game['current_ans'] = {}
        game['start_t'] = time.time()
        game['timer_id'] += 1
        curr_t_id = game['timer_id']
        emit('new_q', {'q': game['round_qs'][idx], 'idx': idx+1, 'round': game['round_num']}, broadcast=True)
        socketio.sleep(15.2)
        if game['timer_id'] == curr_t_id and game['is_running']: process_end_q()

def process_end_q():
    emit('stop_timer', broadcast=True)
    idx = game['active_idx']
    corrects = {s: v for s, v in game['current_ans'].items() if v['ok']}
    
    # Thực thi Lucky Spin (King trả lời đúng)
    if game['king_sid'] in corrects:
        bonus = random.choice([50, 100, 150])
        game['players'][game['king_sid']]['total'] += bonus
        emit('special_event', {'msg': f"🌟 LUCKY SPIN: {game['players'][game['king_sid']]['name']} +{bonus}đ!"}, broadcast=True)
    
    # Thực thi Mark Steal (Người nhanh nhất cướp của King)
    elif corrects:
        fastest = min(corrects, key=lambda x: corrects[x]['t'])
        if game['king_sid'] and fastest != game['king_sid']:
            k = game['king_sid']
            stolen = int(game['players'][k]['total'] * 0.1)
            game['players'][k]['total'] -= stolen
            game['players'][fastest]['total'] += stolen
            emit('special_event', {'msg': f"⚡ MARK STEAL: {game['players'][fastest]['name']} cướp {stolen}đ từ {game['players'][k]['name']}!"}, broadcast=True)

    if game['players']:
        valid = {s: p for s, p in game['players'].items() if p['approved']}
        if valid: game['king_sid'] = max(valid, key=lambda x: valid[x]['total'])
    
    game['active_idx'] += 1
    update_lb()
    socketio.sleep(2.5)
    if game['active_idx'] < 10 and game['is_running']: send_q()
    else: game['is_running'] = False; emit('round_done', broadcast=True)

@socketio.on('submit_ans')
def handle_sub(data):
    sid = request.sid
    if sid in game['current_ans'] or not game['is_running']: return
    elapsed = time.time() - game['start_t']
    q = game['round_qs'][game['active_idx']]
    
    is_ok = str(data['ans']).strip().lower() == str(q['Đáp án đúng']).strip().lower()
    pts = int(100 * (1 - elapsed/15.0)) if is_ok else 0
    
    game['players'][sid]['total'] += pts
    game['players'][sid]['last'] = pts
    game['players'][sid]['history'].append({
        "vong": game['round_num'], "cau": game['active_idx']+1, "q": q['Câu hỏi'],
        "opts": [str(q['Đáp án A']), str(q['Đáp án B']), str(q['Đáp án C']), str(q['Đáp án D'])],
        "u": str(data['ans']), "c": str(q['Đáp án đúng']), "ex": str(q['Giải thích']), "pts": pts
    })
    game['current_ans'][sid] = {"ok": is_ok, "t": elapsed}
    update_lb()

    appr_count = len([s for s, p in game['players'].items() if p['approved']])
    if len(game['current_ans']) >= appr_count:
        game['timer_id'] += 1
        process_end_q()

def update_lb():
    lb = [{"name": p['name'], "total": p['total'], "last": p['last']} for p in game['players'].values() if p['approved']]
    emit('lb_update', sorted(lb, key=lambda x: x['total'], reverse=True), broadcast=True)

@socketio.on('finish_game')
def finish():
    game['is_running'] = False; game['timer_id'] += 1
    emit('stop_timer', broadcast=True); emit('enable_review', broadcast=True)

@socketio.on('get_rev')
def get_rev():
    if request.sid in game['players']: emit('render_rev', game['players'][request.sid]['history'])

if __name__ == '__main__': socketio.run(app, host='0.0.0.0', port=5000)
