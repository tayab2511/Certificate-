"""
============================================================
  CUST University Certificate Management System
  Flask Backend — app.py  (MongoDB Version)
============================================================
  SETUP:
    1. pip install flask openai pillow requests pymongo dnspython
    2. Set MONGO_URI and OPENROUTER_API_KEY env vars.
    3. Run:  python app.py
============================================================
"""

import os
import uuid
import traceback
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, abort, session
)
from werkzeug.utils import secure_filename
from pymongo import MongoClient, ASCENDING
from pymongo.errors import DuplicateKeyError

# ─────────────────────────────────────────────
#  ★  CONFIGURATION
# ─────────────────────────────────────────────

GEMINI_API_KEY     = os.environ.get("GEMINI_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

# Toggle:  "gemini"  |  "openrouter"
USE_API = "openrouter"

# OpenRouter model (free tier)
OPENROUTER_MODEL = "meta-llama/llama-3-8b-instruct:free"

# Flask secret key
SECRET_KEY = os.environ.get("SECRET_KEY", "cust-cert-system-super-secret-2025")

# MongoDB
MONGO_URI = os.environ.get(
    "MONGO_URI",
    "mongodb+srv://tayyabraj698_db_user:zcpbLAHzVQvgMGw5@cluster0.xzz72vw.mongodb.net/"
)
DB_NAME = "certificate_db"

# Upload folder for manual templates
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "static", "uploads")
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}

# ─────────────────────────────────────────────
#  Flask App Initialisation
# ─────────────────────────────────────────────

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

try:
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
except Exception:
    pass


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ─────────────────────────────────────────────
#  MongoDB Helpers
# ─────────────────────────────────────────────

_mongo_client = None
_mongo_db     = None


def get_mongo_db():
    """Return a cached MongoDB database instance."""
    global _mongo_client, _mongo_db
    if _mongo_client is None:
        _mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000)
        _mongo_db     = _mongo_client[DB_NAME]
        # Unique compound index — prevents duplicate student submissions
        _mongo_db["student_entries"].create_index(
            [("certificate_id", ASCENDING), ("registration_number", ASCENDING)],
            unique=True
        )
    return _mongo_db


def doc_to_dict(doc):
    """Convert MongoDB document → plain dict with 'id' key for templates."""
    if doc is None:
        return None
    d = dict(doc)
    d["id"] = str(d.pop("_id", ""))
    return d


# ─────────────────────────────────────────────
#  AI Integration Helpers
# ─────────────────────────────────────────────

def generate_with_gemini(prompt: str) -> str:
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        model    = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)
        return response.text.strip()
    except ImportError:
        raise RuntimeError("google-generativeai not installed. Run: pip install google-generativeai")
    except Exception as exc:
        raise RuntimeError(f"Gemini API error: {exc}")


def generate_with_openrouter(prompt: str) -> str:
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
        raise RuntimeError("openai not installed. Run: pip install openai")
    except Exception as exc:
        raise RuntimeError(f"OpenRouter API error: {exc}")


def generate_certificate_text(prompt: str) -> str:
    if USE_API == "gemini":
        return generate_with_gemini(prompt)
    elif USE_API == "openrouter":
        return generate_with_openrouter(prompt)
    else:
        raise ValueError(f"Unknown USE_API value: '{USE_API}'.")


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
#  Simple Teacher Auth (session-based)
# ─────────────────────────────────────────────

TEACHER_CREDENTIALS = {
    "admin":    "cust2025",
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
    db         = get_mongo_db()
    teacher_id = session["teacher_id"]

    certificates = list(
        db["certificates"].find(
            {"teacher_id": teacher_id},
            sort=[("created_at", -1)]
        )
    )

    cert_list = []
    for raw in certificates:
        cert  = doc_to_dict(raw)
        count = db["student_entries"].count_documents({"certificate_id": cert["id"]})
        cert_list.append({"cert": cert, "student_count": count})

    return render_template("dashboard.html", cert_list=cert_list, api_mode=USE_API)


# ─────────────────────────────────────────────
#  Routes — Create Certificate
# ─────────────────────────────────────────────

@app.route("/create", methods=["GET", "POST"])
@login_required
def create_certificate():
    ai_text       = None
    prompt_used   = None
    error         = None
    category      = None
    creation_mode = None

    if request.method == "POST":
        action        = request.form.get("action", "generate")
        creation_mode = request.form.get("creation_mode", "ai")

        # ── Step 3: Save certificate ──
        if action == "save":
            category       = request.form.get("category", "").strip()
            generated_text = request.form.get("generated_text", "").strip()
            prompt_used    = request.form.get("prompt_used", "").strip()

            sig_left_title  = request.form.get("sig_left_title",  "Dean of Faculty").strip()
            sig_left_name   = request.form.get("sig_left_name",   "").strip()
            sig_right_title = request.form.get("sig_right_title", "Vice Chancellor").strip()
            sig_right_name  = request.form.get("sig_right_name",  "").strip()

            if creation_mode == 'ai' and (not category or not generated_text):
                flash("Category and certificate text are required.", "danger")
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
                    filename        = secure_filename(file.filename)
                    unique_filename = f"{uuid.uuid4().hex}_{filename}"
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
                    background_filename = unique_filename
                else:
                    flash('Invalid file type for manual template.', 'danger')
                    return redirect(request.url)

            cert_id     = str(uuid.uuid4())
            unique_link = url_for("student_form", certificate_id=cert_id, _external=True)
            teacher_id  = session["teacher_id"]
            now         = datetime.utcnow().isoformat()

            db = get_mongo_db()
            db["certificates"].insert_one({
                "_id":             cert_id,
                "teacher_id":      teacher_id,
                "category":        category or 'Manual/Predefined',
                "prompt_used":     prompt_used,
                "generated_text":  generated_text,
                "unique_link":     unique_link,
                "created_at":      now,
                "template_type":   creation_mode,
                "background_file": background_filename,
                "sig_left_title":  sig_left_title,
                "sig_left_name":   sig_left_name,
                "sig_right_title": sig_right_title,
                "sig_right_name":  sig_right_name,
            })

            flash("✅ Certificate drive created successfully!", "success")
            return redirect(url_for("view_submissions", certificate_id=cert_id))

        # ── Step 2: Generate AI text ──
        category      = request.form.get("category", "").strip()
        custom_prompt = request.form.get("custom_prompt", "").strip()

        if not category:
            flash("Please select a category.", "warning")
            return render_template("create_certificate.html",
                ai_text=None, prompt_used=None, category=None, api_mode=USE_API)

        if category == "Custom AI":
            if not custom_prompt:
                flash("Please enter a custom AI prompt.", "warning")
                return render_template("create_certificate.html",
                    ai_text=None, prompt_used=None, category=category, api_mode=USE_API)
            prompt_used = custom_prompt
        else:
            prompt_used = CATEGORY_PROMPTS.get(category, "")

        try:
            ai_text = generate_certificate_text(prompt_used)
        except RuntimeError as exc:
            error   = str(exc)
            ai_text = None
            flash(f"AI generation failed: {error}", "danger")

    return render_template("create_certificate.html",
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
    db   = get_mongo_db()
    cert = doc_to_dict(db["certificates"].find_one({"_id": certificate_id}))

    if cert is None:
        abort(404)
    if cert["teacher_id"] != session["teacher_id"]:
        abort(403)

    entries = [
        doc_to_dict(e)
        for e in db["student_entries"].find(
            {"certificate_id": certificate_id},
            sort=[("submitted_at", -1)]
        )
    ]

    student_link = url_for("student_form", certificate_id=certificate_id, _external=True)

    return render_template("view_submissions.html",
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
    db   = get_mongo_db()
    cert = doc_to_dict(db["certificates"].find_one({"_id": certificate_id}))

    if cert is None:
        return render_template("error.html",
            title="Invalid Link",
            message="This certificate link is invalid or has been removed."
        ), 404

    if request.method == "POST":
        student_name = request.form.get("student_name", "").strip()
        reg_number   = request.form.get("registration_number", "").strip()

        if not student_name or not reg_number:
            flash("Both Full Name and Registration Number are required.", "danger")
            return render_template("student_form.html", cert=cert, show_modal=False)

        entry_id = str(uuid.uuid4())
        now      = datetime.utcnow().isoformat()

        try:
            db["student_entries"].insert_one({
                "_id":                entry_id,
                "certificate_id":     certificate_id,
                "student_name":       student_name,
                "registration_number": reg_number,
                "submitted_at":       now,
            })
        except DuplicateKeyError:
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

    return render_template("student_form.html", cert=cert, show_modal=True)


# ─────────────────────────────────────────────
#  Routes — Print Certificate
# ─────────────────────────────────────────────

@app.route("/print/<certificate_id>/<entry_id>")
@login_required
def print_certificate(certificate_id, entry_id):
    db    = get_mongo_db()
    cert  = doc_to_dict(db["certificates"].find_one({"_id": certificate_id}))
    entry = doc_to_dict(db["student_entries"].find_one(
        {"_id": entry_id, "certificate_id": certificate_id}
    ))

    if cert is None or entry is None:
        abort(404)
    if cert["teacher_id"] != session["teacher_id"]:
        abort(403)

    return render_template("print_certificate.html", cert=cert, entry=entry)


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
