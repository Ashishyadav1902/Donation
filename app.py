from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import sqlite3
import razorpay
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = 'super_secret_ngo_key_change_in_production'

# --- RAZORPAY CREDENTIALS ---
# Replace these with your actual Razorpay API Keys from the Razorpay Dashboard
RAZORPAY_KEY_ID = 'YOUR_RAZORPAY_KEY_ID'
RAZORPAY_KEY_SECRET = 'YOUR_RAZORPAY_KEY_SECRET'

razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# --- Database Setup ---
def get_db():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    # Automated Donations table
    c.execute('''CREATE TABLE IF NOT EXISTS donations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    email TEXT,
                    amount INTEGER NOT NULL,
                    payment_id TEXT UNIQUE,
                    date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Support Tickets table
    c.execute('''CREATE TABLE IF NOT EXISTS tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    subject TEXT,
                    message TEXT NOT NULL,
                    status TEXT DEFAULT 'Open',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
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

# --- Public Routes ---
@app.route('/')
def index():
    return render_template('index.html', razorpay_key_id=RAZORPAY_KEY_ID)

# 1. Create Razorpay Order
@app.route('/api/create_order', methods=['POST'])
def create_order():
    data = request.json
    amount_in_paise = int(data['amount']) * 100 
    try:
        order_data = {
            'amount': amount_in_paise,
            'currency': 'INR',
            'payment_capture': '1'
        }
        order = razorpay_client.order.create(data=order_data)
        return jsonify({"order_id": order['id'], "amount": amount_in_paise})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# 2. Verify Payment & Save to DB Automatically
@app.route('/api/verify_payment', methods=['POST'])
def verify_payment():
    data = request.json
    try:
        # Verify signature for security
        razorpay_client.utility.verify_payment_signature({
            'razorpay_order_id': data['razorpay_order_id'],
            'razorpay_payment_id': data['razorpay_payment_id'],
            'razorpay_signature': data['razorpay_signature']
        })
        
        # If successful, save directly to database
        conn = get_db()
        c = conn.cursor()
        c.execute("INSERT INTO donations (name, email, amount, payment_id) VALUES (?, ?, ?, ?)",
                  (data['donor_name'], data['donor_email'], int(data['amount']), data['razorpay_payment_id']))
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": "Donation added automatically!"})
    except razorpay.errors.SignatureVerificationError:
        return jsonify({"status": "error", "message": "Payment verification failed."}), 400
    except sqlite3.IntegrityError:
        return jsonify({"status": "success", "message": "Payment already recorded."}) # Prevents duplicates

@app.route('/api/submit_ticket', methods=['POST'])
def submit_ticket():
    data = request.json
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("INSERT INTO tickets (name, email, subject, message) VALUES (?, ?, ?, ?)",
                  (data['name'], data['email'], data['subject'], data['message']))
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": "Support ticket created. We will contact you soon."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/api/leaderboard', methods=['GET'])
def get_leaderboard():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT name, amount, date FROM donations ORDER BY amount DESC LIMIT 50")
    donations = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(donations)

@app.route('/api/stats', methods=['GET'])
def get_stats():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT SUM(amount) as total_amount, COUNT(id) as total_donors FROM donations")
    stats = dict(c.fetchone())
    conn.close()
    return jsonify({
        "total_amount": stats['total_amount'] or 0,
        "total_donors": stats['total_donors'] or 0
    })

# --- Admin Routes ---
@app.route('/admin', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form.get('username') == 'admin' and request.form.get('password') == 'admin123':
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        return "Invalid Credentials", 401
    return render_template('login.html') # A simple login page (you can create a basic one)

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    return render_template('admin.html')

@app.route('/admin/api/tickets', methods=['GET'])
@login_required
def get_tickets():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM tickets ORDER BY created_at DESC")
    tickets = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(tickets)

@app.route('/admin/api/tickets/<int:id>/resolve', methods=['POST'])
@login_required
def resolve_ticket(id):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE tickets SET status = 'Resolved' WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

@app.route('/admin/api/tickets/<int:id>/delete', methods=['POST'])
@login_required
def delete_ticket(id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM tickets WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

@app.route('/admin/logout')
def logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)