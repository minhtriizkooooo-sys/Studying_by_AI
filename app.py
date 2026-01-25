import os, random, qrcode, io, base64, time
import pandas as pd
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'marie_curie_2026_final_v3'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

game_state = {
    "all_questions": [], "used_indices": set(), "current_round_qs": [],
    "players": {}, "active_q_idx": -1, "current_round_num": 0,
    "start_time": 0, "pin": None, "is_running": False, "king_sid": None,
    "current_answers": {}, "timer_id": 0
}

@app.route('/')
def index(): return render_template('index.html')

@socketio.on('host_upload_file')
def handle_upload(data):
    try:
        content = base64.b64decode(data['content'].split(",")[1])
        df = pd.read_excel(io.BytesIO(content)) if b'xl' in content else pd.read_csv(io.BytesIO(content), encoding='utf-8-sig')
        df.columns = df.columns.str.strip()
        game_state['all_questions'] = df.to_dict('records')
        game_state['pin'] = str(random.randint(100000, 999999))
        qr = qrcode.QRCode(box_size=10, border=2)
        qr.add_data(game_state['pin']); qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO(); img.save(buf, format='PNG')
        emit('qr_ready', {'qr': base64.b64encode(buf.getvalue()).decode('utf-8'), 'pin': game_state['pin']})
    except Exception as e: emit('error', {'msg': str(e)})

@socketio.on('join_request')
def join(data):
    if data.get('pin') == game_state['pin']:
        sid = request.sid
        game_state['players'][sid] = {"name": data['name'], "total": 0, "last_pts": 0, "history": [], "approved": False}
        emit('new_player_waiting', {'name': data['name'], 'sid': sid}, broadcast=True)

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
    emit('approved_success', broadcast=True); update_lb()

@socketio.on('start_next_round')
def start_round():
    if game_state['is_running']: return
    avail = [i for i in range(len(game_state['all_questions'])) if i not in game_state['used_indices']]
    if len(avail) < 10: return emit('error', {'msg': "Hết câu hỏi trong kho!"})
    game_state['current_round_num'] += 1
    selected = random.sample(avail, 10)
    game_state['used_indices'].update(selected)
    game_state['current_round_qs'] = [game_state['all_questions'][i] for i in selected]
    game_state['active_q_idx'] = 0
    game_state['is_running'] = True
    send_q()

def send_q():
    idx = game_state['active_q_idx']
    if idx < 10 and game_state['is_running']:
        game_state['current_answers'] = {}
        for s in game_state['players']: game_state['players'][s]['last_pts'] = 0
        game_state['start_time'] = time.time()
        game_state['timer_id'] += 1
        this_timer = game_state['timer_id']
        
        emit('new_q', {'q': game_state['current_round_qs'][idx], 'idx': idx+1, 'round': game_state['current_round_num']}, broadcast=True)
        
        socketio.sleep(15.2) # Chờ 15s + buffer nhỏ
        if game_state['timer_id'] == this_timer and game_state['is_running'] and game_state['active_q_idx'] == idx:
            process_end_q()

def process_end_q():
    if not game_state['is_running']: return
    idx = game_state['active_q_idx']
    corrects = {s: v for s, v in game_state['current_answers'].items() if v['correct']}
    
    # 1. Thực thi LUCKY SPIN (Dành cho King bảo vệ vị trí)
    if game_state['king_sid'] in corrects:
        bonus = random.choice([50, 100, 150])
        game_state['players'][game_state['king_sid']]['total'] += bonus
        emit('special_event', {'msg': f"🌟 LUCKY SPIN: {game_state['players'][game_state['king_sid']]['name']} +{bonus}đ!"}, broadcast=True)

    # 2. Thực thi MARK STEAL (Nếu người khác nhanh nhất cướp của King)
    if corrects:
        fastest_sid = min(corrects, key=lambda x: corrects[x]['time'])
        if game_state['king_sid'] and fastest_sid != game_state['king_sid']:
            k_sid = game_state['king_sid']
            stolen = int(game_state['players'][k_sid]['total'] * 0.1)
            game_state['players'][k_sid]['total'] -= stolen
            game_state['players'][fastest_sid]['total'] += stolen
            emit('special_event', {'msg': f"⚡ MARK STEAL: {game_state['players'][fastest_sid]['name']} cướp {stolen}đ của {game_state['players'][k_sid]['name']}!"}, broadcast=True)

    # Cập nhật King mới
    if game_state['players']:
        game_state['king_sid'] = max(game_state['players'], key=lambda x: game_state['players'][x]['total'])
    
    game_state['active_q_idx'] += 1
    update_lb()
    
    socketio.sleep(2.5) # Nghỉ giữa các câu
    if game_state['active_q_idx'] < 10 and game_state['is_running']:
        send_q()
    else:
        game_state['is_running'] = False
        emit('round_end', broadcast=True)

@socketio.on('submit_ans')
def handle_sub(data):
    sid = request.sid
    if sid in game_state['current_answers'] or not game_state['is_running']: return
    elapsed = time.time() - game_state['start_time']
    q = game_state['current_round_qs'][game_state['active_q_idx']]
    is_correct = (str(data['ans']).strip() == str(q['Đáp án đúng']).strip())
    pts = int(100 * (1 - elapsed/15.0)) if is_correct else 0
    if pts < 0: pts = 0

    game_state['players'][sid]['total'] += pts
    game_state['players'][sid]['last_pts'] = pts
    game_state['players'][sid]['history'].append({
        "vong": game_state['current_round_num'], "cau": game_state['active_q_idx']+1,
        "q": q['Câu hỏi'], "options": [q['Đáp án A'], q['Đáp án B'], q['Đáp án C'], q['Đáp án D']],
        "u": data['ans'], "c": q['Đáp án đúng'], "ex": q['Giải thích'], "pts": pts
    })
    game_state['current_answers'][sid] = {"correct": is_correct, "time": elapsed}
    
    update_lb() # Realtime LB

    # Chuyển câu ngay nếu ai cũng trả lời rồi
    approved_count = len([s for s, p in game_state['players'].items() if p['approved']])
    if len(game_state['current_answers']) >= approved_count:
        game_state['timer_id'] += 1 # Hủy timer 15s đang chạy
        process_end_q()

def update_lb():
    lb_data = [{"name": p['name'], "total": p['total'], "last": p['last_pts']} for p in game_state['players'].values() if p['approved']]
    emit('lb_update', sorted(lb_data, key=lambda x: x['total'], reverse=True), broadcast=True)

@socketio.on('finish_all')
def finish_all():
    game_state['is_running'] = False
    game_state['timer_id'] += 1
    emit('kill_timers', broadcast=True)
    emit('enable_review', broadcast=True)

@socketio.on('get_review')
def get_review():
    if request.sid in game_state['players']:
        emit('render_review', game_state['players'][request.sid]['history'])

if __name__ == '__main__': socketio.run(app, host='0.0.0.0', port=5000)
