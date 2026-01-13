import os, random, qrcode, io, base64, json
import pandas as pd
import fitz  # PyMuPDF
from docx import Document
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
from groq import Groq

app = Flask(__name__, template_folder='templates')
app.config['SECRET_KEY'] = 'ai_quiz_ultra_2026'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

client = Groq(api_key=os.environ.get("Studying_by_AI"))

game_state = {
    "questions": [],
    "players": {}, 
    "is_started": False,
    "qr_code": None
}

def generate_qr(url):
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return base64.b64encode(buf.getvalue()).decode('utf-8')

def extract_text(file_bytes, filename):
    ext = filename.split('.')[-1].lower()
    text = ""
    try:
        if ext == 'pdf':
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            for page in doc: text += page.get_text()
        elif ext == 'docx':
            doc = Document(io.BytesIO(file_bytes))
            for para in doc.paragraphs: text += para.text + "\n"
        elif ext == 'txt':
            text = file_bytes.decode('utf-8')
    except Exception as e: print(f"Error: {e}")
    return text

@app.route('/')
def index():
    return render_template('index.html')

# MỤC MỚI: HOST chọn tạo câu hỏi từ AI bằng từ khóa
@socketio.on('host_generate_ai')
def handle_ai_gen(data):
    topic = data.get('topic', 'Kiến thức tổng quát')
    try:
        prompt = f"Tạo 10 câu hỏi trắc nghiệm tiếng Việt về chủ đề: {topic}. Trả về JSON list mảng đối tượng: q, a, b, c, d, ans (A/B/C/D), difficulty (1-10)."
        completion = client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        res = json.loads(completion.choices[0].message.content)
        game_state['questions'] = res if isinstance(res, list) else list(res.values())[0]
        game_state['qr_code'] = generate_qr(request.host_url)
        emit('qr_ready', {'qr': game_state['qr_code']}, broadcast=True)
    except Exception as e:
        emit('error', {'msg': f"AI Error: {str(e)}"})

@socketio.on('host_upload_file')
def handle_upload(data):
    filename = data['name']
    content = base64.b64decode(data['content'].split(",")[1])
    ext = filename.split('.')[-1].lower()
    try:
        if ext in ['csv', 'xlsx']:
            df = pd.read_csv(io.BytesIO(content)) if ext == 'csv' else pd.read_excel(io.BytesIO(content))
            qs = [{"q": str(row[0]), "a": str(row[1]), "b": str(row[2]), "c": str(row[3]), "d": str(row[4]), "ans": str(row[5]).strip().upper(), "difficulty": int(row[6]) if len(row) > 6 else 5} for _, row in df.iterrows()]
            game_state['questions'] = qs
        else:
            raw_text = extract_text(content, filename)
            prompt = f"Tạo 10 câu hỏi trắc nghiệm từ nội dung sau: {raw_text[:4000]}. Trả về JSON list mảng đối tượng: q, a, b, c, d, ans (A/B/C/D), difficulty (1-10)."
            completion = client.chat.completions.create(model="llama3-8b-8192", messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"})
            res = json.loads(completion.choices[0].message.content)
            game_state['questions'] = res if isinstance(res, list) else list(res.values())[0]
        
        game_state['qr_code'] = generate_qr(request.host_url)
        emit('qr_ready', {'qr': game_state['qr_code']}, broadcast=True)
    except Exception as e: emit('error', {'msg': str(e)})

@socketio.on('start_game')
def start_game():
    game_state['is_started'] = True
    emit('game_is_live', broadcast=True)

@socketio.on('join_game')
def join_game(data):
    game_state['players'][request.sid] = {"name": data['name'], "score": 0}
    qs = sorted(game_state['questions'], key=lambda x: int(x.get('difficulty', 5)))[:10]
    emit('game_init', {'questions': qs, 'already_started': game_state['is_started']})
    update_lb()

@socketio.on('submit_answer')
def handle_ans(data):
    if data.get('correct') and request.sid in game_state['players']:
        game_state['players'][request.sid]['score'] += 10
    update_lb()

def update_lb():
    lb = sorted([{"name": v['name'], "score": v['score']} for v in game_state['players'].values()], key=lambda x: x['score'], reverse=True)
    emit('update_leaderboard', lb, broadcast=True)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))