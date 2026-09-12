import atexit
import os
import secrets
import smtplib
import string
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from psycopg.errors import UniqueViolation
from werkzeug.security import check_password_hash, generate_password_hash

from collector import (
    collect_metrics,
    get_system_info,
    get_top_processes,
    save_application_activity,
    save_metrics,
    start_collector,
    stop_collector,
)
from db import get_connection
from init_db import init_database

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY") or os.urandom(32)

HISTORY_POINTS = max(10, int(os.getenv("HISTORY_POINTS", "60")))
APPLICATION_HISTORY_LIMIT = max(10, int(os.getenv("APPLICATION_HISTORY_LIMIT", "50")))
EMAIL_ALERT_COOLDOWN_SECONDS = max(
    60,
    int(os.getenv("EMAIL_ALERT_COOLDOWN_SECONDS", "900")),
)
ALLOWED_ALERT_TYPES = {"CPU", "Memory", "Disk"}


def generate_captcha(form_name):
    characters = string.ascii_uppercase + string.digits
    code = "".join(secrets.choice(characters) for _ in range(6))
    session[f"{form_name}_captcha_answer"] = code
    return code


def validate_captcha(form_name):
    expected = session.get(f"{form_name}_captcha_answer")
    submitted = request.form.get("captcha", "").strip().upper()
    return bool(expected and submitted == expected)


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("user_id"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Authentication required."}), 401
            return redirect(url_for("login"))

        return view(*args, **kwargs)

    return wrapped_view


def gmail_configured():
    return bool(os.getenv("GMAIL_SENDER_EMAIL") and os.getenv("GMAIL_APP_PASSWORD"))


def get_current_user_email():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT email
                FROM users
                WHERE id = %s
                LIMIT 1
                """,
                (session.get("user_id"),),
            )
            row = cur.fetchone()

    return row[0] if row else None


def recently_notified(user_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT sent_at
                FROM notification_logs
                WHERE user_id = %s
                    AND status = 'sent'
                    AND subject = 'CPU Monitor Alert'
                ORDER BY sent_at DESC
                LIMIT 1
                """,
                (user_id,),
            )
            row = cur.fetchone()

    if not row:
        return False

    elapsed = time.time() - row[0].timestamp()
    return elapsed < EMAIL_ALERT_COOLDOWN_SECONDS


def log_notification(user_id, recipient_email, subject, message, status, error_message=""):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO notification_logs
                    (user_id, recipient_email, subject, message, status, error_message)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    recipient_email,
                    subject,
                    message,
                    status,
                    error_message[:1000],
                ),
            )
        conn.commit()


def send_gmail_notification(recipient_email, subject, message):
    sender = os.getenv("GMAIL_SENDER_EMAIL")
    app_password = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "")

    email = EmailMessage()
    email["From"] = sender
    email["To"] = recipient_email
    email["Subject"] = subject
    email.set_content(message)

    with smtplib.SMTP(
        os.getenv("GMAIL_SMTP_HOST", "smtp.gmail.com"),
        int(os.getenv("GMAIL_SMTP_PORT", "587")),
        timeout=10,
    ) as smtp:
        smtp.starttls()
        smtp.login(sender, app_password)
        smtp.send_message(email)


def send_notification_to_current_user(subject, message):
    user_id = session["user_id"]
    recipient_email = get_current_user_email()

    if not recipient_email:
        return jsonify({"error": "Current user email was not found."}), 400

    if not gmail_configured():
        return jsonify({"error": "Gmail sender is not configured."}), 400

    try:
        send_gmail_notification(recipient_email, subject, message)
        log_notification(user_id, recipient_email, subject, message, "sent")
        return jsonify({"status": "sent"})
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"
        log_notification(
            user_id,
            recipient_email,
            subject,
            message,
            "failed",
            error_message,
        )
        print(f"[gmail] {error_message}")
        return jsonify({"error": "Failed to send Gmail notification."}), 502


@app.get("/")
@login_required
def dashboard():
    return render_template("index.html", user_name=session.get("full_name", "User"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        username_or_email = request.form.get("username_or_email", "").strip()
        password = request.form.get("password", "")

        if not validate_captcha("login"):
            error = "Captcha answer is incorrect."
        elif not username_or_email or not password:
            error = "Username/email and password are required."
        else:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, full_name, username, email, password_hash
                        FROM users
                        WHERE username = %s OR email = %s
                        LIMIT 1
                        """,
                        (username_or_email, username_or_email.lower()),
                    )
                    user = cur.fetchone()

            if user and check_password_hash(user[4], password):
                session.clear()
                session["user_id"] = user[0]
                session["full_name"] = user[1]
                session["username"] = user[2]
                return redirect(url_for("dashboard"))

            error = "Invalid login credentials."

    return render_template(
        "login.html",
        error=error,
        captcha_question=generate_captcha("login"),
    )


@app.route("/signup", methods=["GET", "POST"])
def signup():
    error = None

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not validate_captcha("signup"):
            error = "Captcha answer is incorrect."
        elif not full_name or not username or not email or not password:
            error = "All fields are required."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        elif password != confirm_password:
            error = "Passwords do not match."
        else:
            try:
                password_hash = generate_password_hash(password)

                with get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO users (full_name, username, email, password_hash)
                            VALUES (%s, %s, %s, %s)
                            RETURNING id
                            """,
                            (full_name, username, email, password_hash),
                        )
                        user_id = cur.fetchone()[0]
                    conn.commit()

                session.clear()
                session["user_id"] = user_id
                session["full_name"] = full_name
                session["username"] = username
                return redirect(url_for("dashboard"))
            except UniqueViolation:
                error = "Username or email is already registered."

    return render_template(
        "signup.html",
        error=error,
        captcha_question=generate_captcha("signup"),
    )


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/api/system")
@login_required
def system_info():
    return jsonify(get_system_info())


@app.get("/api/latest")
@login_required
def latest_metrics():
    metrics = collect_metrics()
    save_metrics(metrics)

    return jsonify(
        {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            **metrics,
        }
    )


@app.get("/api/history")
@login_required
def history():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    recorded_at,
                    cpu_percent,
                    memory_percent,
                    disk_percent,
                    net_upload_kbps,
                    net_download_kbps
                FROM cpu_metrics
                ORDER BY recorded_at DESC
                LIMIT %s
                """,
                (HISTORY_POINTS,),
            )
            rows = cur.fetchall()

    rows.reverse()

    return jsonify(
        [
            {
                "recorded_at": row[0].isoformat(),
                "cpu_percent": float(row[1]),
                "memory_percent": float(row[2]),
                "disk_percent": float(row[3]),
                "net_upload_kbps": float(row[4]),
                "net_download_kbps": float(row[5]),
            }
            for row in rows
        ]
    )


@app.get("/api/processes")
@login_required
def top_processes():
    return jsonify(get_top_processes())


@app.get("/api/application-activity")
@login_required
def application_activity():
    save_application_activity()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    process_name,
                    MIN(first_seen) AS first_seen,
                    MAX(last_seen) AS last_seen,
                    COUNT(*) AS instance_count,
                    SUM(sample_count) AS sample_count
                FROM application_activity
                GROUP BY process_name
                ORDER BY MAX(last_seen) DESC, SUM(sample_count) DESC, process_name ASC
                LIMIT %s
                """,
                (APPLICATION_HISTORY_LIMIT,),
            )
            rows = cur.fetchall()

    return jsonify(
        [
            {
                "process_name": row[0],
                "first_seen": row[1].isoformat(),
                "last_seen": row[2].isoformat(),
                "instance_count": row[3],
                "sample_count": row[4],
            }
            for row in rows
        ]
    )


@app.post("/api/notify-alert")
@login_required
def notify_alert():
    data = request.get_json(silent=True) or {}
    requested_types = data.get("alert_types") or []
    alert_types = [
        alert_type
        for alert_type in requested_types
        if alert_type in ALLOWED_ALERT_TYPES
    ]

    if not alert_types:
        return jsonify({"error": "No valid alert type supplied."}), 400

    if recently_notified(session["user_id"]):
        return jsonify({"status": "skipped", "reason": "cooldown"})

    subject = "CPU Monitor Alert"
    message = "\n".join(
        [
            "CPU Monitoring Dashboard detected a system alert.",
            "",
            f"Alert type: {', '.join(alert_types)}",
            "",
            "Open the local dashboard to view detailed metrics:",
            "http://localhost:5000",
        ]
    )

    return send_notification_to_current_user(subject, message)


@app.post("/api/test-notification")
@login_required
def test_notification():
    subject = "CPU Monitor Test Notification"
    message = "\n".join(
        [
            "This is a test Gmail notification from CPU Monitoring Dashboard.",
            "",
            "If you received this, Gmail alerts are configured correctly.",
            "",
            "Open the local dashboard:",
            "http://localhost:5000",
        ]
    )

    return send_notification_to_current_user(subject, message)


@app.get("/api/health")
def health():
    return jsonify({"status": "ok"})


def bootstrap():
    init_database()
    start_collector()


atexit.register(stop_collector)

if __name__ == "__main__":
    bootstrap()
    app.run(
        host=os.getenv("FLASK_HOST", "0.0.0.0"),
        port=int(os.getenv("FLASK_PORT", "5000")),
        debug=False,
        use_reloader=False,
    )
