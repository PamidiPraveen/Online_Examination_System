from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from bson.objectid import ObjectId
from datetime import datetime
import os
from functools import wraps

# ---------------- APP CONFIG ----------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
app = Flask(__name__, template_folder=TEMPLATES_DIR)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

# ---------------- MONGODB CONFIG (ATLAS) ----------------
MONGO_URI = os.environ.get("MONGO_URI")

if not MONGO_URI:
    raise Exception("MONGO_URI environment variable not set")

client = MongoClient(MONGO_URI)
db = client.online_exam

users_collection = db.users
exams_collection = db.exams
results_collection = db.results

# ---------------- AUTH DECORATORS ----------------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session or session.get("role") != "admin":
            flash("Admin access required", "error")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated_function

# ---------------- ROUTES ----------------
@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("index.html")

# ---------------- LOGIN ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        user = users_collection.find_one({"email": email})

        if user and check_password_hash(user["password"], password):
            session["user_id"] = str(user["_id"])
            session["username"] = user["username"]
            session["role"] = user["role"]

            flash("Login successful", "success")

            if user["role"] == "admin":
                return redirect(url_for("admin_dashboard"))
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid email or password", "error")

    return render_template("login.html")

# ---------------- REGISTER ----------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")

        if users_collection.find_one({"email": email}):
            flash("Email already registered", "error")
            return redirect(url_for("register"))

        hashed_password = generate_password_hash(password)

        users_collection.insert_one({
            "username": username,
            "email": email,
            "password": hashed_password,
            "role": "student",
            "created_at": datetime.now()
        })

        flash("Registration successful. Please login.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")

# ---------------- LOGOUT ----------------
@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully", "success")
    return redirect(url_for("index"))

# ---------------- STUDENT DASHBOARD ----------------
@app.route("/dashboard")
@login_required
def dashboard():
    if session.get("role") == "admin":
        return redirect(url_for("admin_dashboard"))

    exams = list(exams_collection.find({"is_active": True}))
    return render_template("dashboard.html", exams=exams)

# ---------------- ADMIN DASHBOARD ----------------
@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    stats = {
        "total_exams": exams_collection.count_documents({}),
        "total_students": users_collection.count_documents({"role": "student"}),
        "total_results": results_collection.count_documents({}),
        "active_exams": exams_collection.count_documents({"is_active": True})
    }

    recent_exams = list(exams_collection.find().sort("created_at", -1).limit(5))
    return render_template("admin_dashboard.html", stats=stats, recent_exams=recent_exams)

# ---------------- CREATE EXAM ----------------
@app.route("/admin/create-exam", methods=["GET", "POST"])
@admin_required
def create_exam():
    if request.method == "POST":
        title = request.form.get("title")
        description = request.form.get("description")
        duration = int(request.form.get("duration"))

        questions = []
        q_count = int(request.form.get("question_count"))

        for i in range(q_count):
            questions.append({
                "question": request.form.get(f"question_{i}"),
                "options": [
                    request.form.get(f"option_{i}_0"),
                    request.form.get(f"option_{i}_1"),
                    request.form.get(f"option_{i}_2"),
                    request.form.get(f"option_{i}_3")
                ],
                "correct_answer": int(request.form.get(f"correct_answer_{i}"))
            })

        exams_collection.insert_one({
            "title": title,
            "description": description,
            "duration": duration,
            "questions": questions,
            "created_by": ObjectId(session["user_id"]),
            "created_at": datetime.now(),
            "is_active": True
        })

        flash("Exam created successfully", "success")
        return redirect(url_for("admin_dashboard"))

    return render_template("create_exam.html")

# ---------------- TAKE EXAM ----------------
@app.route("/exam/<exam_id>")
@login_required
def take_exam(exam_id):
    exam = exams_collection.find_one({"_id": ObjectId(exam_id)})

    if not exam or not exam["is_active"]:
        flash("Exam not available", "error")
        return redirect(url_for("dashboard"))

    return render_template("take_exam.html", exam=exam)

# ---------------- SUBMIT EXAM ----------------
@app.route("/submit-exam", methods=["POST"])
@login_required
def submit_exam():
    exam_id = request.form.get("exam_id")
    exam = exams_collection.find_one({"_id": ObjectId(exam_id)})

    score = 0
    answers = []

    for i, q in enumerate(exam["questions"]):
        ans = request.form.get(f"question_{i}")
        if ans is not None:
            ans = int(ans)
            answers.append(ans)
            if ans == q["correct_answer"]:
                score += 1
        else:
            answers.append(-1)

    results_collection.insert_one({
        "student_id": ObjectId(session["user_id"]),
        "exam_id": ObjectId(exam_id),
        "answers": answers,
        "score": score,
        "total_questions": len(exam["questions"]),
        "percentage": (score / len(exam["questions"])) * 100,
        "completed_at": datetime.now()
    })

    return redirect(url_for("dashboard"))

# ---------------- INIT SAMPLE DATA ----------------
def init_sample_data():
    if not users_collection.find_one({"email": "admin@test.com"}):
        users_collection.insert_one({
            "username": "Admin",
            "email": "admin@test.com",
            "password": generate_password_hash("password123"),
            "role": "admin",
            "created_at": datetime.now()
        })

    if not users_collection.find_one({"email": "student@test.com"}):
        users_collection.insert_one({
            "username": "Student",
            "email": "student@test.com",
            "password": generate_password_hash("password123"),
            "role": "student",
            "created_at": datetime.now()
        })

# ---------------- MAIN ----------------
if __name__ == "__main__":
    init_sample_data()
    app.run()

# ---------------- EXTRA SAFE INIT FOR VERCEL ----------------
try:
    init_sample_data()
except Exception as e:
    print("Sample data init skipped:", e)
