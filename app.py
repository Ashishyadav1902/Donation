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
    # Existing Tables
    c.execute('''CREATE TABLE IF NOT EXISTS donations (id SERIAL PRIMARY KEY, name TEXT NOT NULL, email TEXT, mobile TEXT, amount INTEGER NOT NULL, payment_id TEXT UNIQUE, status TEXT DEFAULT 'pending', screenshot TEXT, date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS tickets (id SERIAL PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL, subject TEXT, message TEXT NOT NULL, status TEXT DEFAULT 'Open', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS chat_sessions (session_id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL, status TEXT DEFAULT 'Active', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS chat_messages (id SERIAL PRIMARY KEY, session_id TEXT, sender TEXT, message TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS stories (id SERIAL PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL, image_url TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # NEW: Level 4 Tables (Children, Settings, Chatbot)
    c.execute('''CREATE TABLE IF NOT EXISTS children (id SERIAL PRIMARY KEY, name TEXT, age INTEGER, condition TEXT, description TEXT, image_url TEXT, goal_amount INTEGER, raised_amount INTEGER DEFAULT 0, status TEXT DEFAULT 'Active')''')
    c.execute('''CREATE TABLE IF NOT EXISTS chatbot_rules (id SERIAL PRIMARY KEY, keyword TEXT, response TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS campaign_settings (id INTEGER PRIMARY KEY, goal_amount INTEGER DEFAULT 100000, urgency_msg TEXT DEFAULT 'Urgent: 42 children are waiting for immediate medical support!', med_pct INTEGER DEFAULT 40, edu_pct INTEGER DEFAULT 35, ther_pct INTEGER DEFAULT 15, food_pct INTEGER DEFAULT 10, yt_url TEXT DEFAULT 'https://www.youtube.com/embed/dQw4w9WgXcQ', ig_url TEXT DEFAULT '', hero_id INTEGER, stats_children INTEGER DEFAULT 320, stats_medical INTEGER DEFAULT 180, stats_kits INTEGER DEFAULT 500)''')
    
    # Insert default settings if empty
    c.execute("SELECT COUNT(*) FROM campaign_settings")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO campaign_settings (id) VALUES (1)")
        # Insert default chatbot rules
        c.execute("INSERT INTO chatbot_rules (keyword, response) VALUES ('donate', 'You can donate securely by clicking the Donate button at the top of the page. We accept UPI, Cards, and NetBanking!')")
        c.execute("INSERT INTO chatbot_rules (keyword, response) VALUES ('safe', 'Yes! We use bank-level 256-bit encryption. All payments are 100% secure.')")
        c.execute("INSERT INTO chatbot_rules (keyword, response) VALUES ('80g', 'Yes, all donations are fully 80G tax-exempt. You can download your receipt instantly from the Wall of Heroes.')")

    conn.commit()
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
# PUBLIC ROUTES & PWA & SEO
# ==========================================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/manifest.json')
def manifest():
    return jsonify({
        "name": "Hope Foundation", "short_name": "Hope NGO", "start_url": "/", "display": "standalone",
        "background_color": "#f0f4f8", "theme_color": "#4A90E2",
        "icons": [{"src": "https://cdn-icons-png.flaticon.com/512/3349/3349383.png", "sizes": "512x512", "type": "image/png"}]
    })

@app.route('/sw.js')
def service_worker():
    sw_code = """
    self.addEventListener('install', e => { e.waitUntil(caches.open('hope-cache').then(c => c.addAll(['/']))); });
    self.addEventListener('fetch', e => { e.respondWith(caches.match(e.request).then(r => r || fetch(e.request))); });
    """
    return Response(sw_code, mimetype='application/javascript')

@app.route('/sitemap.xml')
def sitemap():
    xml = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://hope-foundation-empowering-children.onrender.com/</loc><changefreq>daily</changefreq><priority>1.0</priority></url></urlset>'
    return Response(xml, mimetype='application/xml')

# --- RECEIPTS ---
@app.route('/receipt/<int:id>')
def generate_receipt(id):
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT * FROM donations WHERE id = %s AND status = 'approved'", (id,))
    d = c.fetchone()
    conn.close()
    if not d: return "Receipt not found or pending approval.", 404
    
    html = f"""
    <html><head><title>Receipt #{d['id']}</title><style>body{{font-family:Arial; padding:40px; color:#333; max-width:800px; margin:auto; border:2px solid #eee;}} .header{{text-align:center; border-bottom:2px solid #4A90E2; padding-bottom:20px;}} .details{{margin-top:30px; line-height:1.8;}}</style></head>
    <body onload="window.print()">
        <div class="header"><h1 style="color:#4A90E2;">HOPE FOUNDATION</h1><p>80G Tax Exemption Receipt</p></div>
        <div class="details">
            <p><strong>Receipt No:</strong> HF-2026-{d['id']}</p><p><strong>Date:</strong> {d['date']}</p>
            <p><strong>Received with thanks from:</strong> {d['name'].upper()}</p>
            <p><strong>Amount:</strong> INR {d['amount']}</p>
            <p><strong>Transaction Ref:</strong> {d['email'].replace('TXN ID: ', '') if 'TXN ID' in d['email'] else d['payment_id']}</p>
            <br><p><i>Thank you for empowering specially-abled children in India. This is a computer-generated receipt.</i></p>
        </div>
    </body></html>
    """
    return Response(html, mimetype='text/html')

# --- APIs ---
@app.route('/api/public_data', methods=['GET'])
def public_data():
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT * FROM campaign_settings WHERE id=1")
    settings = c.fetchone()
    c.execute("SELECT SUM(amount) as total_amount, COUNT(id) as total_donors FROM donations WHERE status = 'approved'")
    stats = c.fetchone()
    c.execute("SELECT * FROM children WHERE status='Active' ORDER BY id DESC")
    children = c.fetchall()
    c.execute("SELECT keyword, response FROM chatbot_rules")
    chat_rules = c.fetchall()
    hero = None
    if settings['hero_id']:
        c.execute("SELECT id, name, amount FROM donations WHERE id = %s AND status='approved'", (settings['hero_id'],))
        hero = c.fetchone()
    
    # Fallback hero if manual is not set
    if not hero:
        c.execute("SELECT id, name, amount FROM donations WHERE status = 'approved' ORDER BY amount DESC LIMIT 1")
        hero = c.fetchone()

    conn.close()
    
    return jsonify({
        "settings": settings,
        "stats": {"total_amount": stats['total_amount'] or 0, "total_donors": stats['total_donors'] or 0},
        "children": children, "chat_rules": chat_rules, "hero": hero
    })

@app.route('/api/submit_donation', methods=['POST'])
def submit_donation():
    data = request.json
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO donations (name, email, mobile, amount, payment_id, status, screenshot) VALUES (%s, %s, %s, %s, %s, 'pending', %s)",
              (data['name'], data.get('email', ''), data.get('mobile', ''), int(data['amount']), "CLAIM_" + str(uuid.uuid4())[:8], data.get('screenshot', '')))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

@app.route('/api/leaderboard', methods=['GET'])
def get_leaderboard():
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT id, name, amount, date FROM donations WHERE status = 'approved' ORDER BY amount DESC LIMIT 50")
    donations = c.fetchall()
    conn.close()
    return jsonify(donations)

@app.route('/api/latest_donation', methods=['GET'])
def get_latest_donation():
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT name, amount FROM donations WHERE status = 'approved' ORDER BY date DESC LIMIT 10")
    return jsonify(c.fetchall())

@app.route('/api/stories', methods=['GET'])
def get_stories():
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT * FROM stories ORDER BY created_at DESC")
    s = c.fetchall()
    conn.close()
    return jsonify(s)

@app.route('/api/chat/start', methods=['POST'])
def start_chat():
    data = request.json
    session_id = str(uuid.uuid4())
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO chat_sessions (session_id, name, email) VALUES (%s, %s, %s)", (session_id, data['name'], data['email']))
    c.execute("INSERT INTO chat_messages (session_id, sender, message) VALUES (%s, %s, %s)", (session_id, 'bot', f"Hi {data['name']}! Ask me anything, or type 'help'."))
    conn.commit()
    conn.close()
    return jsonify({"session_id": session_id})

@app.route('/api/chat/send', methods=['POST'])
def send_message():
    data = request.json
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO chat_messages (session_id, sender, message) VALUES (%s, %s, %s)", (data['session_id'], 'user', data['message']))
    
    # 10. SMART CHATBOT LOGIC
    c.execute("SELECT keyword, response FROM chatbot_rules")
    rules = c.fetchall()
    bot_reply = None
    user_msg = data['message'].lower()
    for rule in rules:
        if rule[0].lower() in user_msg:
            bot_reply = rule[1]
            break
            
    if bot_reply:
        c.execute("INSERT INTO chat_messages (session_id, sender, message) VALUES (%s, %s, %s)", (data['session_id'], 'bot', bot_reply))

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
    c.execute("UPDATE donations SET status = 'approved', screenshot = NULL WHERE id = %s", (id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

@app.route('/admin/api/delete_donation/<int:id>', methods=['POST'])
@login_required
def delete_donation(id):
    conn = get_db(); c = conn.cursor(); c.execute("DELETE FROM donations WHERE id = %s", (id,)); conn.commit(); conn.close(); return jsonify({"status": "success"})

@app.route('/admin/api/set_hero/<int:id>', methods=['POST'])
@login_required
def set_hero(id):
    conn = get_db(); c = conn.cursor(); c.execute("UPDATE campaign_settings SET hero_id = %s WHERE id=1", (id,)); conn.commit(); conn.close(); return jsonify({"status": "success"})

@app.route('/admin/api/update_settings', methods=['POST'])
@login_required
def update_settings():
    d = request.json
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE campaign_settings SET goal_amount=%s, urgency_msg=%s, yt_url=%s, stats_children=%s, stats_medical=%s, stats_kits=%s, med_pct=%s, edu_pct=%s, ther_pct=%s, food_pct=%s WHERE id=1",
              (d['goal'], d['urgency'], d['yt'], d['s_child'], d['s_med'], d['s_kits'], d['p_med'], d['p_edu'], d['p_ther'], d['p_food']))
    conn.commit(); conn.close(); return jsonify({"status": "success"})

@app.route('/admin/api/children', methods=['GET', 'POST'])
@login_required
def manage_children():
    conn = get_db(); c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if request.method == 'POST':
        d = request.json
        c.execute("INSERT INTO children (name, age, condition, description, image_url, goal_amount) VALUES (%s, %s, %s, %s, %s, %s)", (d['name'], int(d['age']), d['condition'], d['desc'], d['img'], int(d['goal'])))
        conn.commit(); conn.close(); return jsonify({"status": "success"})
    c.execute("SELECT * FROM children ORDER BY id DESC")
    kids = c.fetchall(); conn.close(); return jsonify(kids)

@app.route('/admin/api/children/<int:id>/delete', methods=['POST'])
@login_required
def delete_child(id):
    conn = get_db(); c = conn.cursor(); c.execute("DELETE FROM children WHERE id = %s", (id,)); conn.commit(); conn.close(); return jsonify({"status": "success"})

@app.route('/admin/api/chatbot', methods=['GET', 'POST'])
@login_required
def manage_chat():
    conn = get_db(); c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if request.method == 'POST':
        d = request.json; c.execute("INSERT INTO chatbot_rules (keyword, response) VALUES (%s, %s)", (d['keyword'].lower(), d['response']))
        conn.commit(); conn.close(); return jsonify({"status": "success"})
    c.execute("SELECT * FROM chatbot_rules ORDER BY id DESC")
    rules = c.fetchall(); conn.close(); return jsonify(rules)

@app.route('/admin/api/chatbot/<int:id>/delete', methods=['POST'])
@login_required
def delete_chat(id):
    conn = get_db(); c = conn.cursor(); c.execute("DELETE FROM chatbot_rules WHERE id = %s", (id,)); conn.commit(); conn.close(); return jsonify({"status": "success"})

@app.route('/admin/api/add_story', methods=['POST'])
@login_required
def add_story():
    d = request.json; conn = get_db(); c = conn.cursor(); c.execute("INSERT INTO stories (title, content, image_url) VALUES (%s, %s, %s)", (d['title'], d['content'], d['image_url'])); conn.commit(); conn.close(); return jsonify({"status": "success"})

@app.route('/admin/api/delete_story/<int:id>', methods=['POST'])
@login_required
def delete_story(id):
    conn = get_db(); c = conn.cursor(); c.execute("DELETE FROM stories WHERE id = %s", (id,)); conn.commit(); conn.close(); return jsonify({"status": "success"})

@app.route('/admin/api/tickets', methods=['GET'])
@login_required
def get_tickets():
    conn = get_db(); c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor); c.execute("SELECT * FROM tickets ORDER BY created_at DESC"); return jsonify(c.fetchall())

@app.route('/admin/api/tickets/<int:id>/resolve', methods=['POST'])
@login_required
def resolve_ticket(id):
    conn = get_db(); c = conn.cursor(); c.execute("UPDATE tickets SET status = 'Resolved' WHERE id = %s", (id,)); conn.commit(); return jsonify({"status": "success"})

@app.route('/admin/api/chats/active', methods=['GET'])
@login_required
def get_active_chats():
    conn = get_db(); c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor); c.execute("SELECT * FROM chat_sessions WHERE status = 'Active' ORDER BY created_at DESC"); return jsonify(c.fetchall())

@app.route('/admin/api/chats/<session_id>/send', methods=['POST'])
@login_required
def admin_send_message(session_id):
    d = request.json; conn = get_db(); c = conn.cursor(); c.execute("INSERT INTO chat_messages (session_id, sender, message) VALUES (%s, %s, %s)", (session_id, 'admin', d['message'])); conn.commit(); return jsonify({"status": "success"})

@app.route('/admin/logout')
def logout():
    session.pop('admin_logged_in', None); return redirect(url_for('admin_login'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)
