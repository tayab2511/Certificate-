"""
============================================================
  CUST University Certificate Management System
  Flask Backend — app.py
============================================================
  SETUP INSTRUCTIONS:
    1. pip install flask google-generativeai openai pillow requests
    2. Insert your API keys below.
    3. Set USE_API to "gemini" or "openrouter".
    4. Run:  python app.py
============================================================
"""

import os
import uuid
import sqlite3
import traceback
from datetime import datetime
from functools import wraps
from io import BytesIO

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, abort, g, send_file, session
)
from werkzeug.utils import secure_filename

# ─────────────────────────────────────────────
#  ★  CONFIGURATION — Edit these values only  ★
# ─────────────────────────────────────────────

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

# Toggle:  "gemini"  |  "openrouter"
USE_API = "openrouter"

# OpenRouter model (free tier)
OPENROUTER_MODEL = "meta-llama/llama-3-8b-instruct:free"

# Flask secret key — change in production!
SECRET_KEY = os.environ.get("SECRET_KEY", "cust-cert-system-super-secret-2025")

# SQLite database path (created automatically on first run)
DATABASE = os.path.join(os.path.dirname(__file__), "certificates.db")

# Upload folder for manual templates
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "static", "uploads")
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}

# ─────────────────────────────────────────────
#  Flask App Initialisation
# ─────────────────────────────────────────────

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure upload directory exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ─────────────────────────────────────────────
#  Database Helpers
# ─────────────────────────────────────────────

def get_db():
    """Open a new database connection for the current request context."""
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row          # rows behave like dicts
        db.execute("PRAGMA foreign_keys = ON")
    return db


@app.teardown_appcontext
def close_db(exception):
    """Close the database at the end of every request."""
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()


def init_db():
    """Create tables if they don't already exist."""
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS Certificates (
            id               TEXT PRIMARY KEY,
            teacher_id       TEXT NOT NULL,
            category         TEXT NOT NULL,
            prompt_used      TEXT,
            generated_text   TEXT,
            unique_link      TEXT UNIQUE NOT NULL,
            created_at       TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS StudentEntries (
            id                  TEXT PRIMARY KEY,
            certificate_id      TEXT NOT NULL,
            student_name        TEXT NOT NULL,
            registration_number TEXT NOT NULL,
            submitted_at        TEXT NOT NULL,
            FOREIGN KEY (certificate_id) REFERENCES Certificates(id),
            UNIQUE (certificate_id, registration_number)
        );
    """)
    
    # Safely add new columns if they don't exist
    try:
        db.execute("ALTER TABLE Certificates ADD COLUMN template_type TEXT DEFAULT 'ai'")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("ALTER TABLE Certificates ADD COLUMN background_file TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("ALTER TABLE Certificates ADD COLUMN sig_left_title TEXT DEFAULT 'Dean of Faculty'")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("ALTER TABLE Certificates ADD COLUMN sig_left_name TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("ALTER TABLE Certificates ADD COLUMN sig_right_title TEXT DEFAULT 'Vice Chancellor'")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("ALTER TABLE Certificates ADD COLUMN sig_right_name TEXT")
    except sqlite3.OperationalError:
        pass

    db.commit()


db_initialized = False

@app.before_request
def setup_db():
    global db_initialized
    if not db_initialized:
        init_db()
        db_initialized = True


# ─────────────────────────────────────────────
#  AI Integration Helpers
# ─────────────────────────────────────────────

def generate_with_gemini(prompt: str) -> str:
    """
    Call Google Gemini API and return generated text.
    Requires:  pip install google-generativeai
    """
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)
        return response.text.strip()
    except ImportError:
        raise RuntimeError(
            "google-generativeai package is not installed. "
            "Run: pip install google-generativeai"
        )
    except Exception as exc:
        raise RuntimeError(f"Gemini API error: {exc}")


def generate_with_openrouter(prompt: str) -> str:
    """
    Call OpenRouter API via the openai-compatible interface.
    Requires:  pip install openai
    """
    try:
        from openai import OpenAI
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=OPENROUTER_API_KEY,
        )
        completion = client.chat.completions.create(
            model=OPENROUTER_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a professional university certificate writer for "
                        "CUST University. Write formal, eloquent, and concise "
                        "certificate body text only. Do not include headers or signatures."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )
        return completion.choices[0].message.content.strip()
    except ImportError:
        raise RuntimeError(
            "openai package is not installed. Run: pip install openai"
        )
    except Exception as exc:
        raise RuntimeError(f"OpenRouter API error: {exc}")


def generate_certificate_text(prompt: str) -> str:
    """
    Route to the selected AI backend based on USE_API toggle.
    """
    if USE_API == "gemini":
        return generate_with_gemini(prompt)
    elif USE_API == "openrouter":
        return generate_with_openrouter(prompt)
    else:
        raise ValueError(f"Unknown USE_API value: '{USE_API}'. Use 'gemini' or 'openrouter'.")


# ─────────────────────────────────────────────
#  Pre-built Prompt Templates per Category
# ─────────────────────────────────────────────

CATEGORY_PROMPTS = {
    "Dean's Honor": (
        "Write a formal, inspiring certificate body text (2–3 sentences) "
        "awarded to a student for being placed on the Dean's Honor List at "
        "CUST University. The text should praise academic excellence and dedication."
    ),
    "Sports": (
        "Write a proud and motivating certificate body text (2–3 sentences) "
        "awarded to a student for outstanding sports achievement at CUST University. "
        "Highlight teamwork, discipline, and athletic excellence."
    ),
    "Participation": (
        "Write a warm and encouraging certificate body text (2–3 sentences) "
        "awarded to a student for active participation in a university event at "
        "CUST University. Acknowledge their contribution and spirit."
    ),
}


# ─────────────────────────────────────────────
#  Simple Teacher Auth (session-based, no DB)
#  Replace with a real auth system in production.
# ─────────────────────────────────────────────

TEACHER_CREDENTIALS = {
    "admin": "cust2025",      # username: password
    "teacher1": "pass1234",
}

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "teacher_id" not in session:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────
#  Routes — Authentication
# ─────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    if "teacher_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        if TEACHER_CREDENTIALS.get(username) == password:
            session["teacher_id"] = username
            flash(f"Welcome back, {username}!", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid credentials. Please try again.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


# ─────────────────────────────────────────────
#  Routes — Teacher Dashboard
# ─────────────────────────────────────────────

@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    teacher_id = session["teacher_id"]
    certificates = db.execute(
        "SELECT * FROM Certificates WHERE teacher_id = ? ORDER BY created_at DESC",
        (teacher_id,)
    ).fetchall()

    # Attach student count to each certificate
    cert_list = []
    for cert in certificates:
        count = db.execute(
            "SELECT COUNT(*) FROM StudentEntries WHERE certificate_id = ?",
            (cert["id"],)
        ).fetchone()[0]
        cert_list.append({"cert": cert, "student_count": count})

    return render_template("dashboard.html", cert_list=cert_list, api_mode=USE_API)


# ─────────────────────────────────────────────
#  Routes — Create Certificate
# ─────────────────────────────────────────────

@app.route("/create", methods=["GET", "POST"])
@login_required
def create_certificate():
    """
    Step 1 (GET):  Show the creation form.
    Step 2 (POST): Generate AI text and show it for inline editing.
    Step 3 (POST with action=save): Save the final certificate to DB.
    """
    ai_text     = None
    prompt_used = None
    error       = None
    category    = None
    creation_mode = None

    if request.method == "POST":
        action = request.form.get("action", "generate")
        creation_mode = request.form.get("creation_mode", "ai")

        # ── Step 3: Save the (potentially edited) certificate ──
        if action == "save":
            category       = request.form.get("category", "").strip()
            generated_text = request.form.get("generated_text", "").strip()
            prompt_used    = request.form.get("prompt_used", "").strip()
            
            sig_left_title = request.form.get("sig_left_title", "Dean of Faculty").strip()
            sig_left_name  = request.form.get("sig_left_name", "").strip()
            sig_right_title = request.form.get("sig_right_title", "Vice Chancellor").strip()
            sig_right_name = request.form.get("sig_right_name", "").strip()

            if creation_mode == 'ai' and (not category or not generated_text):
                flash("Category and certificate text are required for AI generation.", "danger")
                return redirect(url_for("create_certificate"))

            background_filename = None
            if creation_mode == 'manual':
                if 'manual_template_file' not in request.files:
                    flash('No file part', 'danger')
                    return redirect(request.url)
                file = request.files['manual_template_file']
                if file.filename == '':
                    flash('No selected file', 'danger')
                    return redirect(request.url)
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    # Add UUID to prevent overwriting
                    unique_filename = f"{uuid.uuid4().hex}_{filename}"
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
                    background_filename = unique_filename
                else:
                    flash('Invalid file type for manual template.', 'danger')
                    return redirect(request.url)
                    
            if creation_mode == 'predefined':
                # Map category to some predefined text if needed, or take from form
                pass

            cert_id     = str(uuid.uuid4())
            unique_link = url_for("student_form", certificate_id=cert_id, _external=True)
            teacher_id  = session["teacher_id"]
            now         = datetime.utcnow().isoformat()

            db = get_db()
            db.execute(
                """INSERT INTO Certificates
                   (id, teacher_id, category, prompt_used, generated_text, unique_link, created_at, 
                    template_type, background_file, sig_left_title, sig_left_name, sig_right_title, sig_right_name)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (cert_id, teacher_id, category or 'Manual/Predefined', prompt_used, generated_text, unique_link, now,
                 creation_mode, background_filename, sig_left_title, sig_left_name, sig_right_title, sig_right_name)
            )
            db.commit()
            flash("✅ Certificate drive created successfully!", "success")
            return redirect(url_for("view_submissions", certificate_id=cert_id))

        # ── Step 2: Generate AI text ──
        category   = request.form.get("category", "").strip()
        custom_prompt = request.form.get("custom_prompt", "").strip()

        if not category:
            flash("Please select a category.", "warning")
            return render_template(
                "create_certificate.html",
                ai_text=None, prompt_used=None, category=None, api_mode=USE_API
            )

        if category == "Custom AI":
            if not custom_prompt:
                flash("Please enter a custom AI prompt.", "warning")
                return render_template(
                    "create_certificate.html",
                    ai_text=None, prompt_used=None, category=category, api_mode=USE_API
                )
            prompt_used = custom_prompt
        else:
            prompt_used = CATEGORY_PROMPTS.get(category, "")

        try:
            ai_text = generate_certificate_text(prompt_used)
        except RuntimeError as exc:
            error   = str(exc)
            ai_text = None
            flash(f"AI generation failed: {error}", "danger")

    return render_template(
        "create_certificate.html",
        ai_text=ai_text,
        prompt_used=prompt_used,
        category=category,
        creation_mode=creation_mode,
        error=error,
        api_mode=USE_API,
    )


# ─────────────────────────────────────────────
#  Routes — View Submissions
# ─────────────────────────────────────────────

@app.route("/submissions/<certificate_id>")
@login_required
def view_submissions(certificate_id):
    db   = get_db()
    cert = db.execute(
        "SELECT * FROM Certificates WHERE id = ?", (certificate_id,)
    ).fetchone()

    if cert is None:
        abort(404)

    # Ownership check
    if cert["teacher_id"] != session["teacher_id"]:
        abort(403)

    entries = db.execute(
        "SELECT * FROM StudentEntries WHERE certificate_id = ? ORDER BY submitted_at DESC",
        (certificate_id,)
    ).fetchall()

    student_link = url_for("student_form", certificate_id=certificate_id, _external=True)

    return render_template(
        "view_submissions.html",
        cert=cert,
        entries=entries,
        student_link=student_link,
        api_mode=USE_API,
    )


# ─────────────────────────────────────────────
#  Routes — Student Public Form
# ─────────────────────────────────────────────

@app.route("/submit-details/<certificate_id>", methods=["GET", "POST"])
def student_form(certificate_id):
    db   = get_db()
    cert = db.execute(
        "SELECT * FROM Certificates WHERE id = ?", (certificate_id,)
    ).fetchone()

    if cert is None:
        return render_template("error.html",
            title="Invalid Link",
            message="This certificate link is invalid or has been removed."
        ), 404

    if request.method == "POST":
        student_name = request.form.get("student_name", "").strip()
        reg_number   = request.form.get("registration_number", "").strip()

        # Basic validation
        if not student_name or not reg_number:
            flash("Both Full Name and Registration Number are required.", "danger")
            return render_template("student_form.html", cert=cert, show_modal=False)

        entry_id = str(uuid.uuid4())
        now      = datetime.utcnow().isoformat()

        try:
            db.execute(
                """INSERT INTO StudentEntries
                   (id, certificate_id, student_name, registration_number, submitted_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (entry_id, certificate_id, student_name, reg_number, now)
            )
            db.commit()
        except sqlite3.IntegrityError:
            # UNIQUE constraint on (certificate_id, registration_number) violated
            return render_template("error.html",
                title="Access Denied",
                message=(
                    "🚫 Access Denied: A response has already been recorded for "
                    f"Registration Number <strong>{reg_number}</strong> on this "
                    "certificate. No further submissions are permitted."
                )
            ), 409

        return render_template("success.html",
            student_name=student_name,
            reg_number=reg_number,
            cert=cert,
        )

    # GET — show modal + form
    return render_template("student_form.html", cert=cert, show_modal=True)


# ─────────────────────────────────────────────
#  Routes — Print Certificate (HTML print view)
# ─────────────────────────────────────────────

@app.route("/print/<certificate_id>/<entry_id>")
@login_required
def print_certificate(certificate_id, entry_id):
    db   = get_db()
    cert = db.execute(
        "SELECT * FROM Certificates WHERE id = ?", (certificate_id,)
    ).fetchone()
    entry = db.execute(
        "SELECT * FROM StudentEntries WHERE id = ? AND certificate_id = ?",
        (entry_id, certificate_id)
    ).fetchone()

    if cert is None or entry is None:
        abort(404)

    if cert["teacher_id"] != session["teacher_id"]:
        abort(403)

    return render_template("print_certificate.html", cert=dict(cert), entry=dict(entry))


# ─────────────────────────────────────────────
#  Error Handlers
# ─────────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    return render_template("error.html",
        title="404 — Page Not Found",
        message="The page you are looking for does not exist."
    ), 404


@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html",
        title="403 — Forbidden",
        message="You do not have permission to access this resource."
    ), 403


@app.errorhandler(500)
def server_error(e):
    return render_template("error.html",
        title="500 — Server Error",
        message="An unexpected error occurred. Please try again later."
    ), 500


# ─────────────────────────────────────────────
#  Entry Point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)
