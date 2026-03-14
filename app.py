import os
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, Response
import psycopg2
import psycopg2.extras
import csv
import io
import uuid
from datetime import datetime
from functools import wraps

app = Flask(__name__)

# --- SECURE CLOUD CONFIGURATION ---
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'super_secret_fallback_key')
SUPABASE_URL = os.getenv('SUPABASE_URL', 'postgresql://postgres:password@localhost:5432/postgres')

def get_db():
    return psycopg2.connect(SUPABASE_URL)

def init_db():
    conn = get_db()
    c = conn.cursor()
    # 1. Create tables if they don't exist
    c.execute('''CREATE TABLE IF NOT EXISTS donations (id SERIAL PRIMARY KEY, name TEXT NOT NULL, email TEXT, amount INTEGER NOT NULL, payment_id TEXT UNIQUE, date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS tickets (id SERIAL PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL, subject TEXT, message TEXT NOT NULL, status TEXT DEFAULT 'Open', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS chat_sessions (session_id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL, status TEXT DEFAULT 'Active', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS chat_messages (id SERIAL PRIMARY KEY, session_id TEXT, sender TEXT, message TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # NEW: Success Stories Table
    c.execute('''CREATE TABLE IF NOT EXISTS stories (id SERIAL PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL, image_url TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    conn.commit()

    # 2. Auto-Migration
    try:
        c.execute("ALTER TABLE donations ADD COLUMN mobile TEXT")
        conn.commit()
    except psycopg2.errors.DuplicateColumn:
        conn.rollback()
        
    try:
        c.execute("ALTER TABLE donations ADD COLUMN status TEXT DEFAULT 'pending'")
        c.execute("UPDATE donations SET status = 'approved' WHERE status IS NULL")
        conn.commit()
    except psycopg2.errors.DuplicateColumn:
        conn.rollback()

    conn.close()

init_db()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session:
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

# ==========================================
# PUBLIC ROUTES
# ==========================================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/submit_donation', methods=['POST'])
def submit_donation():
    data = request.json
    conn = get_db()
    c = conn.cursor()
    fake_payment_id = "CLAIM_" + str(uuid.uuid4())[:8]
    c.execute("INSERT INTO donations (name, email, mobile, amount, payment_id, status) VALUES (%s, %s, %s, %s, %s, 'pending')",
              (data['name'], data.get('email', ''), data.get('mobile', ''), int(data['amount']), fake_payment_id))
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "message": "Donation added! Pending admin approval."})

@app.route('/api/submit_ticket', methods=['POST'])
def submit_ticket():
    data = request.json
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO tickets (name, email, subject, message) VALUES (%s, %s, %s, %s)",
              (data['name'], data['email'], data['subject'], data['message']))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

@app.route('/api/leaderboard', methods=['GET'])
def get_leaderboard():
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT name, amount, date FROM donations WHERE status = 'approved' ORDER BY amount DESC LIMIT 50")
    donations = c.fetchall()
    conn.close()
    return jsonify(donations)

@app.route('/api/latest_donation', methods=['GET'])
def get_latest_donation():
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT id, name, amount FROM donations WHERE status = 'approved' ORDER BY date DESC LIMIT 1")
    latest = c.fetchone()
    conn.close()
    return jsonify(latest if latest else {})

@app.route('/api/stats', methods=['GET'])
def get_stats():
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT SUM(amount) as total_amount, COUNT(id) as total_donors FROM donations WHERE status = 'approved'")
    stats = c.fetchone()
    conn.close()
    return jsonify({"total_amount": stats['total_amount'] or 0, "total_donors": stats['total_donors'] or 0})

# NEW: Public Route to fetch success stories
@app.route('/api/stories', methods=['GET'])
def get_stories():
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT * FROM stories ORDER BY created_at DESC")
    stories = c.fetchall()
    conn.close()
    return jsonify(stories)

# --- Live Chat ---
@app.route('/api/chat/start', methods=['POST'])
def start_chat():
    data = request.json
    session_id = str(uuid.uuid4())
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO chat_sessions (session_id, name, email) VALUES (%s, %s, %s)", (session_id, data['name'], data['email']))
    c.execute("INSERT INTO chat_messages (session_id, sender, message) VALUES (%s, %s, %s)", (session_id, 'bot', f"Hi {data['name']}! I am the automated assistant. A human agent will be with you shortly."))
    conn.commit()
    conn.close()
    return jsonify({"session_id": session_id})

@app.route('/api/chat/send', methods=['POST'])
def send_message():
    data = request.json
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO chat_messages (session_id, sender, message) VALUES (%s, %s, %s)", (data['session_id'], 'user', data['message']))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

@app.route('/api/chat/sync/<session_id>', methods=['GET'])
def sync_chat(session_id):
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT id, sender, message, timestamp FROM chat_messages WHERE session_id = %s ORDER BY timestamp ASC", (session_id,))
    messages = c.fetchall()
    conn.close()
    return jsonify(messages)


# ==========================================
# ADMIN ROUTES
# ==========================================
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'ashishadmin')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'anu@9936')

@app.route('/admin', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form.get('username') == ADMIN_USERNAME and request.form.get('password') == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        return render_template('admin.html', error="Invalid Credentials")
    return render_template('admin.html')

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    return render_template('admin.html')

@app.route('/admin/api/full_stats', methods=['GET'])
@login_required
def get_full_stats():
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT SUM(amount) as total_amount, COUNT(id) as total_donors FROM donations WHERE status = 'approved'")
    d_stats = c.fetchone()
    c.execute("SELECT COUNT(id) as total_tickets FROM tickets")
    t_stats = c.fetchone()
    c.execute("SELECT COUNT(id) as open_tickets FROM tickets WHERE status='Open'")
    o_stats = c.fetchone()
    conn.close()
    return jsonify({"total_amount": d_stats['total_amount'] or 0, "total_donors": d_stats['total_donors'] or 0, "total_tickets": t_stats['total_tickets'] or 0, "open_tickets": o_stats['open_tickets'] or 0})

@app.route('/admin/api/all_donations', methods=['GET'])
@login_required
def get_all_donations():
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT * FROM donations ORDER BY status DESC, date DESC")
    donations = c.fetchall()
    conn.close()
    return jsonify(donations)

@app.route('/admin/api/approve_donation/<int:id>', methods=['POST'])
@login_required
def approve_donation(id):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE donations SET status = 'approved' WHERE id = %s", (id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

@app.route('/admin/api/add_manual', methods=['POST'])
@login_required
def add_manual():
    data = request.json
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO donations (name, email, mobile, amount, payment_id, status) VALUES (%s, %s, %s, %s, %s, 'approved')", 
              (data['name'], data.get('email', ''), data.get('mobile', ''), int(data['amount']), f"MANUAL_{datetime.now().timestamp()}"))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

@app.route('/admin/api/delete_donation/<int:id>', methods=['POST'])
@login_required
def delete_donation(id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM donations WHERE id = %s", (id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

@app.route('/admin/export_donations')
@login_required
def export_donations():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, name, email, mobile, amount, status, payment_id, date FROM donations ORDER BY date DESC")
    donations = c.fetchall()
    conn.close()
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['ID', 'Name', 'Email', 'Mobile', 'Amount (INR)', 'Status', 'Payment ID', 'Date'])
    for row in donations: cw.writerow(row)
    return Response(si.getvalue(), mimetype="text/csv", headers={"Content-disposition": "attachment; filename=donations_export.csv"})

# NEW: Admin Routes for Success Stories
@app.route('/admin/api/add_story', methods=['POST'])
@login_required
def add_story():
    data = request.json
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO stories (title, content, image_url) VALUES (%s, %s, %s)", 
              (data['title'], data['content'], data['image_url']))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

@app.route('/admin/api/delete_story/<int:id>', methods=['POST'])
@login_required
def delete_story(id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM stories WHERE id = %s", (id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

@app.route('/admin/api/tickets', methods=['GET'])
@login_required
def get_tickets():
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT * FROM tickets ORDER BY created_at DESC")
    return jsonify(c.fetchall())

@app.route('/admin/api/tickets/<int:id>/resolve', methods=['POST'])
@login_required
def resolve_ticket(id):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE tickets SET status = 'Resolved' WHERE id = %s", (id,))
    conn.commit()
    return jsonify({"status": "success"})

@app.route('/admin/api/tickets/<int:id>/delete', methods=['POST'])
@login_required
def delete_ticket(id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM tickets WHERE id = %s", (id,))
    conn.commit()
    return jsonify({"status": "success"})

@app.route('/admin/api/chats/active', methods=['GET'])
@login_required
def get_active_chats():
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT * FROM chat_sessions WHERE status = 'Active' ORDER BY created_at DESC")
    return jsonify(c.fetchall())

@app.route('/admin/api/chats/<session_id>/send', methods=['POST'])
@login_required
def admin_send_message(session_id):
    data = request.json
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO chat_messages (session_id, sender, message) VALUES (%s, %s, %s)", (session_id, 'admin', data['message']))
    conn.commit()
    return jsonify({"status": "success"})

@app.route('/admin/api/chats/<session_id>/close', methods=['POST'])
@login_required
def close_chat(session_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE chat_sessions SET status = 'Closed' WHERE session_id = %s", (session_id,))
    c.execute("INSERT INTO chat_messages (session_id, sender, message) VALUES (%s, %s, %s)", (session_id, 'admin', "Chat has been closed by the agent."))
    conn.commit()
    return jsonify({"status": "success"})

@app.route('/admin/logout')
def logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)
