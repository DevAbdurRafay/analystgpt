import os
from flask import Flask, render_template, session, redirect, url_for, request
from dotenv import load_dotenv
from services.supabase_service import db_service

# Load environmental variables early so env checks work
load_dotenv()

# ─── Startup Environment Variable Validation ─────────────────────────────────
REQUIRED_ENV_VARS = [
    "FLASK_SECRET_KEY",
    "SUPABASE_URL",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GITHUB_CLIENT_ID",
    "GITHUB_CLIENT_SECRET",
]

def _check_env_vars():
    """Checks all required env vars are present at startup and logs status."""
    missing = []
    for var in REQUIRED_ENV_VARS:
        val = os.getenv(var)
        if val:
            print(f"[ENV] OK   {var} is set (len={len(val)})")
        else:
            print(f"[ENV] MISS {var} is MISSING or EMPTY")
            missing.append(var)
    # Check Supabase key (service role preferred, anon as fallback)
    srk = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    ak  = os.getenv("SUPABASE_ANON_KEY")
    if srk:
        print(f"[ENV] OK   SUPABASE_SERVICE_ROLE_KEY is set (len={len(srk)})")
    elif ak:
        print(f"[ENV] OK   SUPABASE_ANON_KEY is set (len={len(ak)}) - using as fallback (add SUPABASE_SERVICE_ROLE_KEY for RLS bypass)")
    else:
        print("[ENV] MISS Neither SUPABASE_SERVICE_ROLE_KEY nor SUPABASE_ANON_KEY is set")
        missing.append("SUPABASE_ANON_KEY or SUPABASE_SERVICE_ROLE_KEY")
    if missing:
        raise RuntimeError(f"[STARTUP ERROR] Missing required environment variables: {missing}. Add them to your .env file.")

_check_env_vars()




# Allow OAuth over HTTP for local development
if os.getenv("FLASK_ENV", "development") == "development":
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"


def create_app():
    app = Flask(__name__)

    # Configure secrets — strictly require FLASK_SECRET_KEY
    secret_key = os.getenv("FLASK_SECRET_KEY")
    if not secret_key:
        raise RuntimeError("FLASK_SECRET_KEY is missing from environment variables!")
    app.config["SECRET_KEY"] = secret_key

    # Session cookie configuration for local stability & OAuth consistency
    app.config["SESSION_COOKIE_NAME"] = "analystgpt_session"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    import datetime
    app.config["PERMANENT_SESSION_LIFETIME"] = datetime.timedelta(days=7)

    # Configure Upload Folder (Vercel serverless /tmp fallback)
    import tempfile
    if os.getenv("VERCEL"):
        upload_folder = os.path.join(tempfile.gettempdir(), "analystgpt_uploads")
    else:
        upload_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
    try:
        os.makedirs(upload_folder, exist_ok=True)
    except Exception:
        upload_folder = os.path.join(tempfile.gettempdir(), "analystgpt_uploads")
        os.makedirs(upload_folder, exist_ok=True)

    app.config["UPLOAD_FOLDER"] = upload_folder

    # Supabase config (database only — NOT for authentication)
    app.config["SUPABASE_URL"] = os.getenv("SUPABASE_URL", "")
    app.config["SUPABASE_ANON_KEY"] = os.getenv("SUPABASE_ANON_KEY", "")

    # SMTP / Flask-Mail config
    app.config["MAIL_SERVER"]   = os.getenv("MAIL_SERVER",   "smtp.gmail.com")
    app.config["MAIL_PORT"]     = int(os.getenv("MAIL_PORT",   "587"))
    app.config["MAIL_USE_TLS"]  = os.getenv("MAIL_USE_TLS",  "True").lower() not in ("false", "0", "no")
    app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME")
    app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD")

    # Max file size limit: 50MB
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

    # ─── Register Blueprints ──────────────────────────────────────────────────
    from routes.auth import auth_bp, google_bp, github_bp
    from routes.data import data_bp
    from routes.ai import ai_bp

    # Flask-Dance blueprints already include /google and /github in their internal paths.
    # Registering under /login gives us /login/google and /login/github (initiation)
    # and /login/google/authorized and /login/github/authorized (callbacks).
    app.register_blueprint(google_bp, url_prefix="/login")
    app.register_blueprint(github_bp, url_prefix="/login")

    app.register_blueprint(auth_bp)
    app.register_blueprint(data_bp)
    app.register_blueprint(ai_bp)

    # ─── Auth-Guarded Top-Level Routes ───────────────────────────────────────
    @app.after_request
    def disable_cache(response):
        """Prevents browser disk cache from serving stale login/auth pages."""
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    @app.before_request
    def normalize_host():
        """Redirects localhost/127.0.0.1 to the configured APP_BASE_URL while avoiding self-redirect loops."""
        app_base_url = os.getenv("APP_BASE_URL", "").strip().rstrip("/")
        if not app_base_url:
            return
        from urllib.parse import urlparse

        def normalize_host_value(host):
            if not host:
                return ""
            host = host.lower().strip().rstrip("/")
            if host.startswith("[") and "]" in host:
                host = host.split("]", 1)[0].strip("[]") + host.split("]", 1)[1]
            if host.count(":") == 1 and host.rsplit(":", 1)[1].isdigit():
                return host.rsplit(":", 1)[0]
            return host

        parsed_base = urlparse(app_base_url)
        target_host = parsed_base.netloc
        current_host = request.host
        current_norm = normalize_host_value(current_host)
        target_norm = normalize_host_value(target_host)

        if target_host and current_host and current_norm != target_norm:
            if ("localhost" in current_norm or "127.0.0.1" in current_norm) and ("localhost" in target_norm or "127.0.0.1" in target_norm):
                new_url = request.url.replace(f"://{current_host}", f"://{target_host}", 1)
                return redirect(new_url, code=307)

    @app.route("/")
    def index():

        if "email" not in session:
            return redirect("/login")
        return redirect(url_for("data.dashboard"))

    @app.route("/dashboard")
    def dashboard_page():
        if "email" not in session:
            return redirect("/login")
        return redirect(url_for("data.dashboard"))

    @app.route("/analytics")
    def analytics_page():
        if "email" not in session:
            return redirect("/login")
        return render_template(
            "analytics.html",
            email=session.get("email"),
            page_title="Analytics"
        )

    @app.route("/chat")
    def chat_page():
        if "email" not in session:
            return redirect("/login")
        return render_template(
            "chat.html",
            email=session.get("email"),
            page_title="AI Chat"
        )

    # ─── Error Handlers ───────────────────────────────────────────────────────
    @app.errorhandler(404)
    def not_found(error):
        """Redirect unauthenticated users to login on 404, show message for authenticated."""
        if "email" not in session:
            return redirect(url_for("auth.login"))
        return render_template("404.html", error=str(error)), 404

    @app.errorhandler(413)
    def file_too_large(error):
        return {"error": "Uploaded file is too large. Maximum file size is 50MB."}, 413

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False)

