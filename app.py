import sqlite3
import ollama
import hashlib
import os
import time
import json
import threading
import re
import base64
import io
from flask import Flask, render_template, request, session, redirect, url_for, jsonify, flash
from pypdf import PdfReader
from werkzeug.utils import secure_filename

# --- NEW IMPORTS FOR DOCX AND IMAGES ---
try:
    from PIL import Image
    import pytesseract  # Optional: For OCR if you want to read text from images
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    from docx import Document
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False
    print("Warning: python-docx not installed. DOCX files will not be processed.")

# --- CONFIGURATION ---
app = Flask(__name__, template_folder='.') 
app.secret_key = "gate_master_secure_key"
DB_NAME = "gate_v3.sqlite"
MODEL_NAME = "gemma3" 
UPLOAD_FOLDER = 'uploads'
PROFILE_PIC_FOLDER = 'uploads/profiles'
ALLOWED_EXTENSIONS = {'pdf', 'docx', 'doc', 'txt', 'png', 'jpg', 'jpeg'}

# Create directories
for folder in [UPLOAD_FOLDER, PROFILE_PIC_FOLDER, os.path.join(UPLOAD_FOLDER, 'submissions'), os.path.join(UPLOAD_FOLDER, 'chat_files')]:
    if not os.path.exists(folder):
        os.makedirs(folder)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['PROFILE_PIC_FOLDER'] = PROFILE_PIC_FOLDER

# --- SYLLABUS ---
GATE_SYLLABUS = {
    "Computer Science": {
        "Programming & Data Structures": ["Arrays", "Stacks", "Queues", "Trees", "Graphs", "Hashing"],
        "Algorithms": ["Analysis", "Sorting", "Searching", "Greedy", "Dynamic Programming", "Graph Algorithms"],
        "Operating Systems": ["Process Management", "Memory Management", "File Systems", "Deadlocks", "Scheduling"],
        "Database Management": ["ER Model", "Relational Model", "SQL", "Normalization", "Transactions", "Indexing"],
        "Computer Networks": ["OSI Model", "TCP/IP", "Routing", "Error Control", "Application Layer"],
        "Computer Organization": ["Digital Logic", "Machine Instructions", "CPU Design", "Memory Hierarchy"],
        "Theory of Computation": ["Finite Automata", "Regular Expressions", "Context-Free Grammars", "Turing Machines"],
        "Compiler Design": ["Lexical Analysis", "Syntax Analysis", "Semantic Analysis", "Code Generation"]
    }
}

# --- HELPER FUNCTIONS ---
def get_file_extension(filename):
    return filename.rsplit('.', 1)[1].lower() if '.' in filename else ''

def extract_text_from_file(file_path):
    """Universal text extractor for PDF, DOCX, and TXT"""
    ext = get_file_extension(file_path)
    text = ""
    try:
        if ext == 'pdf':
            reader = PdfReader(file_path)
            for page in reader.pages:
                text += (page.extract_text() or "") + "\n"
        elif ext == 'docx' and HAS_DOCX:
            doc = Document(file_path)
            for para in doc.paragraphs:
                text += para.text + "\n"
        elif ext == 'txt':
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
        elif ext in ['png', 'jpg', 'jpeg'] and HAS_PIL:
            # Note: Tesseract OCR is required for image-to-text. 
            # If not installed, we return a placeholder so AI knows an image exists.
            try:
                text = f"[Image File: {os.path.basename(file_path)} - Content requires Visual AI]"
                # text = pytesseract.image_to_string(Image.open(file_path)) # Uncomment if Tesseract is installed
            except:
                pass
    except Exception as e:
        print(f"Error extracting text from {file_path}: {e}")
    return text

# --- DATABASE ---
def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS teachers (id INTEGER PRIMARY KEY, name TEXT, passcode_hash TEXT, profile_pic TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY, name TEXT, roll_no TEXT UNIQUE, passcode_hash TEXT, profile_pic TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS assignments (
        id INTEGER PRIMARY KEY, teacher_id INTEGER, subject TEXT, topic TEXT, 
        pdf_paths TEXT, assignment_number INTEGER, upload_timestamp REAL,
        ai_notes TEXT, ai_quiz TEXT, processing_status TEXT DEFAULT 'PENDING'
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS results (
        id INTEGER PRIMARY KEY, student_id INTEGER, assignment_id INTEGER, 
        score REAL, raw_score INTEGER, status TEXT, timestamp REAL
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS student_submissions (
        id INTEGER PRIMARY KEY, student_id INTEGER, assignment_id INTEGER,
        file_paths TEXT, submission_text TEXT, timestamp REAL
    )''')
    conn.commit()
    conn.close()

# --- AI WORKER ---
def generate_content_worker(assign_id, file_paths_json, subject, chapter, topic, variation="Standard"):
    """Background worker to generate notes/quiz from PDFs, DOCXs, or TXT"""
    try:
        file_list = json.loads(file_paths_json)
        full_text = ""
        
        # Extract text from all files
        for path in file_list:
            full_text += extract_text_from_file(path)
        
        # Limit text for AI context window
        context_text = full_text[:12000]

        if not context_text.strip():
            context_text = f"No source document provided. You are the AI Tutor. Generate comprehensive, high-quality content based entirely on the GATE syllabus for: {subject} > {chapter} > {topic}."

        # 1. Generate Notes
        p_notes = f"""Analyze the provided text and context. 
        Context: Subject='{subject}', Chapter='{chapter}', Topic='{topic}'.
        
        Create concise HTML study notes for GATE.
        Structure:
        1. <strong>Key Topics in this Document:</strong> [List topics found or relevant to the Chapter/Topic]
        2. <strong>Detailed Summary:</strong> Provide a detailed explanation of '{topic}' within '{chapter}'. If the document text is sufficient, summarize it. If the document is sparse, use your knowledge of the Standard GATE Syllabus for this specific topic to provide a comprehensive summary.
        3. Study Notes (Use <h3>, <ul>, <b>).
        
        Text Content:
        {context_text}"""
        
        notes_resp = ollama.chat(model=MODEL_NAME, messages=[{'role':'user', 'content':p_notes}])
        notes = notes_resp['message']['content']

        # 2. Generate Quiz
        # 2. Generate Quiz
        p_quiz = f"""Generate exactly 10 Basic Level multiple choice questions (MCQs).
        Context: Subject='{subject}', Chapter='{chapter}', Topic='{topic}'.
        Variation: {variation} (Ensure questions are distinct if possible).
        
        Instructions:
        - Format: Return ONLY a valid JSON array: [{{"q":"Question?","options":["A","B","C","D"],"correct_index":0}}]
        - If the provided Text Content is sufficient, generate questions from it.
        - CRITICAL: If the text is empty or too brief, you MUST generate questions based on the standard GATE syllabus for '{subject}' > '{chapter}' > '{topic}'. Do NOT return 'undefined' questions or questions about missing text.
        
        Text Content: {context_text}"""
        
        quiz_resp = ollama.chat(model=MODEL_NAME, messages=[{'role':'user', 'content':p_quiz}])
        raw_quiz = quiz_resp['message']['content']
        
        # Clean JSON
        clean_json = re.sub(r'```json\s*|```', '', raw_quiz).strip()
        
        # Validate JSON
        try:
            quiz_data = json.loads(clean_json)
            # Ensure it's a list
            if not isinstance(quiz_data, list): quiz_data = []
        except:
            quiz_data = []

        # If we have fewer than 10, try one more time to get basic questions from text
        if len(quiz_data) < 10:
            p_extra = f"Generate {10 - len(quiz_data)} more Basic Level MCQs strictly from the text provided. JSON format only."
            extra_resp = ollama.chat(model=MODEL_NAME, messages=[
                {'role':'user', 'content':f"Text: {context_text}"}, 
                {'role':'user', 'content':p_extra}
            ])
            try:
                extra_json = re.sub(r'```json\s*|```', '', extra_resp['message']['content']).strip()
                quiz_data.extend(json.loads(extra_json))
            except: pass

        # Ensure we have at most 10-15 (limit to 10 for visibility as requested, or keep 15 if UI supports it, 
        # but user said '10 questions aren't visible', likely meaning they want 10 specific ones.)
        # Let's target exactly 10 as per "I need that 10 questions to be from the basic..."
        final_quiz_json = json.dumps(quiz_data[:10])

        conn = get_db()
        conn.execute("UPDATE assignments SET ai_notes=?, ai_quiz=?, processing_status='READY' WHERE id=?", 
                     (notes, final_quiz_json, assign_id))
        conn.commit()
        conn.close()

    except Exception as e:
        print(f"Worker Error: {e}")
        conn = get_db()
        conn.execute("UPDATE assignments SET processing_status='ERROR' WHERE id=?", (assign_id,))
        conn.commit()
        conn.close()

# --- ROUTES ---
@app.route('/')
def index():
    if 'user_id' in session: 
        return redirect(url_for('dashboard'))
    return render_template('index.html', view='login')

@app.route('/auth', methods=['POST'])
def auth():
    role = request.form.get('role')
    action = request.form.get('action')
    name = request.form.get('name', '').strip()
    password = request.form.get('password', '').strip()
    
    conn = get_db()
    pwd = hashlib.sha256(password.encode()).hexdigest()
    
    if action == 'register':
        try:
            # Handle profile pic
            pic_path = ""
            if 'profile_pic' in request.files:
                f = request.files['profile_pic']
                if f.filename:
                    fname = secure_filename(f"{int(time.time())}_{f.filename}")
                    pic_path = os.path.join(app.config['PROFILE_PIC_FOLDER'], fname)
                    f.save(pic_path)

            if role == 'teacher':
                conn.execute("INSERT INTO teachers (name, passcode_hash, profile_pic) VALUES (?, ?, ?)", (name, pwd, pic_path))
            else:
                roll = request.form.get('roll_no')
                conn.execute("INSERT INTO students (name, roll_no, passcode_hash, profile_pic) VALUES (?, ?, ?, ?)", (name, roll, pwd, pic_path))
            conn.commit()
            flash("Registered successfully!")
        except Exception as e:
            flash(f"Error: {e}")
        return redirect(url_for('index'))
    
    else: # Login
        table = 'teachers' if role == 'teacher' else 'students'
        if role == 'teacher':
            user = conn.execute(f"SELECT * FROM {table} WHERE name=? AND passcode_hash=?", (name, pwd)).fetchone()
        else:
            roll = request.form.get('roll_no')
            user = conn.execute(f"SELECT * FROM {table} WHERE roll_no=? AND passcode_hash=?", (roll, pwd)).fetchone()
            
        if user:
            session['user_id'] = user['id']
            session['role'] = role
            session['name'] = user['name']
            session['profile_pic'] = user['profile_pic'] if user['profile_pic'] else ''
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid credentials")
            return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('index'))
    conn = get_db()
    
    # Check if 'assignments' table exists, create if not (safety check)
    try:
        conn.execute("SELECT * FROM assignments LIMIT 1")
    except:
        init_db()

    assignments = conn.execute("SELECT * FROM assignments ORDER BY id DESC").fetchall()
    
    if session['role'] == 'teacher':
        return render_template('index.html', view='teacher_dash', assignments=assignments, syllabus=GATE_SYLLABUS)
    else:
        results = conn.execute("SELECT * FROM results WHERE student_id=?", (session['user_id'],)).fetchall()
        att_map = {r['assignment_id']: r['score'] for r in results}
        
        student_data = []
        for a in assignments:
            status = 'OPEN' if a['processing_status'] == 'READY' else 'WAIT'
            if a['id'] in att_map: status = 'DONE'
            student_data.append({**a, 'status': status, 'score': att_map.get(a['id'], 0)})
            
        # Calculate CGPA
        total_score = sum([r['score'] for r in results])
        cgpa = round(total_score / len(results), 2) if results else 0.0
            
        return render_template('index.html', view='student_dash', assignments=student_data, cgpa=cgpa)

@app.route('/upload', methods=['POST'])
def upload():
    if session.get('role') != 'teacher': return "Unauthorized"
    
    # Accepts 'files' instead of specific 'pdf_files'
    files = request.files.getlist('files')
    subject = request.form.get('subject')
    chapter = request.form.get('chapter')
    topic = request.form.get('topic')
    
    saved_paths = []
    for f in files:
        if f.filename:
            fname = secure_filename(f"{int(time.time())}_{f.filename}")
            path = os.path.join(app.config['UPLOAD_FOLDER'], fname)
            f.save(path)
            saved_paths.append(path)
            
            
    # Allow execution even if no files (AI Tutor Mode)
    conn = get_db()
    json_paths = json.dumps(saved_paths)
    
    # Create Set A
    conn.execute("INSERT INTO assignments (teacher_id, subject, topic, pdf_paths, upload_timestamp) VALUES (?, ?, ?, ?, ?)",
                    (session['user_id'], subject, topic + " - Set A", json_paths, time.time()))
    id_a = conn.cursor().execute("SELECT last_insert_rowid()").fetchone()[0]
    
    # Create Set B
    conn.execute("INSERT INTO assignments (teacher_id, subject, topic, pdf_paths, upload_timestamp) VALUES (?, ?, ?, ?, ?)",
                    (session['user_id'], subject, topic + " - Set B", json_paths, time.time()))
    id_b = conn.cursor().execute("SELECT last_insert_rowid()").fetchone()[0]
    
    conn.commit()
    
    # Start Set A Worker
    threading.Thread(target=generate_content_worker, args=(id_a, json_paths, subject, chapter, topic, "Set A (Conceptual & Theory)")).start()
    # Start Set B Worker
    threading.Thread(target=generate_content_worker, args=(id_b, json_paths, subject, chapter, topic, "Set B (Applied & Numerical)")).start()
        
    return redirect(url_for('dashboard'))

@app.route('/api/chat', methods=['POST'])
def ai_chat():
    if session.get('role') != 'student': return jsonify({'error': 'Unauthorized'}), 401

    msg = request.form.get('message', '')
    files = request.files.getlist('files')
    
    context = f"Student Question: {msg}\n\nAttached Content:\n"
    
    # Process Chat Uploads (FIXED)
    for f in files:
        if f.filename:
            fname = secure_filename(f"{int(time.time())}_{f.filename}")
            path = os.path.join(app.config['UPLOAD_FOLDER'], 'chat_files', fname)
            f.save(path)
            
            # Extract text safely
            extracted = extract_text_from_file(path)
            context += f"--- File: {f.filename} ---\n{extracted[:3000]}\n"

    try:
        resp = ollama.chat(model=MODEL_NAME, messages=[
            {'role': 'system', 'content': 'You are a helpful GATE tutor.'},
            {'role': 'user', 'content': context}
        ])
        return jsonify({'response': resp['message']['content']})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/exam/<int:id>')
def exam(id):
    if session.get('role') != 'student': 
        return redirect(url_for('index'))
    conn = get_db()
    # Check if cheated/completed
    prev = conn.execute("SELECT * FROM results WHERE student_id=? AND assignment_id=?", (session['user_id'], id)).fetchone()
    if prev:
        flash("Exam already attempted or terminated due to malpractice.")
        return redirect(url_for('dashboard'))
    
    assign = conn.execute("SELECT * FROM assignments WHERE id=?", (id,)).fetchone()
    if not assign:
        flash("Assignment not found.")
        return redirect(url_for('dashboard'))
    
    if assign['processing_status'] != 'READY':
        flash("Assignment is still being processed. Please wait.")
        return redirect(url_for('dashboard'))
    
    # Parse quiz JSON safely
    try:
        quiz_data = json.loads(assign['ai_quiz']) if assign['ai_quiz'] else []
        if not isinstance(quiz_data, list) or len(quiz_data) == 0:
            flash("Quiz data is not available. Please contact teacher.")
            return redirect(url_for('dashboard'))
    except json.JSONDecodeError:
        flash("Error loading quiz data. Please contact teacher.")
        return redirect(url_for('dashboard'))
    
    return render_template('index.html', view='exam_arena', assign=assign, quiz_data=json.dumps(quiz_data))

@app.route('/submit_exam', methods=['POST'])
def submit_exam():
    data = request.json
    status = data.get('status', 'COMPLETED')
    raw = data.get('raw_score', 0)
    
    # Anti-Cheat Penalty
    final_score = 0
    if status == 'COMPLETED':
        final_score = round((raw / data.get('total', 15)) * 10, 2)
    else:
        # If CHEATING detected, score is 0 regardless of answers
        final_score = 0 
        
    conn.execute("INSERT INTO results (student_id, assignment_id, score, raw_score, status, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                 (session['user_id'], data['assign_id'], final_score, raw, status, time.time()))
    conn.commit()
    return jsonify({'redirect': url_for('dashboard')})

@app.route('/delete_assignment/<int:id>')
def delete_assignment(id):
    if session.get('role') != 'teacher': return "Unauthorized"
    conn = get_db()
    conn.execute("DELETE FROM assignments WHERE id=?", (id,))
    conn.execute("DELETE FROM results WHERE assignment_id=?", (id,))
    conn.commit()
    return redirect(url_for('dashboard'))

@app.route('/api/results/<int:id>')
def get_assignment_results(id):
    if session.get('role') != 'teacher': return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    results = conn.execute("""
        SELECT r.*, s.name, s.roll_no 
        FROM results r 
        JOIN students s ON r.student_id = s.id 
        WHERE r.assignment_id = ? 
        ORDER BY r.score DESC
    """, (id,)).fetchall()
    
    data = [dict(row) for row in results]
    return jsonify(data)

@app.route('/uploads/profiles/<path:filename>')
def uploaded_profile_pic(filename):
    """Serve uploaded profile pictures"""
    from flask import send_from_directory
    try:
        return send_from_directory(app.config['PROFILE_PIC_FOLDER'], filename)
    except:
        return "Profile picture not found", 404

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)