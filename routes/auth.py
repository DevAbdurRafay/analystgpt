import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, make_response, current_app
from flask_dance.contrib.google import make_google_blueprint, google
from flask_dance.contrib.github import make_github_blueprint, github
from flask_dance.consumer import oauth_authorized
from services.supabase_service import db_service
from services.email_service import email_service

auth_bp = Blueprint("auth", __name__)

EMAIL_OTP_PURPOSES = {"account registration", "account login", "password reset request", "reset"}


def _clear_otp_session() -> None:
    """Remove OTP and legacy OAuth-OTP session keys."""
    for key in (
        "otp_purpose",
        "otp_target_email",
        "otp_flow",
        "login_user_id",
        "login_full_name",
        "oauth_requires_otp",
        "oauth_otp_verified",
    ):
        session.pop(key, None)
    session.modified = True


def _finalize_oauth_session(pending: dict) -> None:
    """Complete OAuth sign-in without any verification code."""
    _clear_otp_session()
    session.permanent = True
    session["email"] = pending.get("email")
    session["user_id"] = pending.get("user_id")
    session["full_name"] = pending.get("full_name", "")
    session["picture"] = pending.get("picture", "")
    session["auth_provider"] = pending.get("auth_provider", "oauth")
    session.pop("oauth_pending", None)
    session.modified = True

# ─── Fixed base URL for OAuth redirects (prevents localhost/127.0.0.1 mismatch) ──
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:5000").rstrip("/")

# ─── Google OAuth Blueprint ───────────────────────────────────────────────────────
google_bp = make_google_blueprint(
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    scope=["openid", "https://www.googleapis.com/auth/userinfo.email",
           "https://www.googleapis.com/auth/userinfo.profile"],
    # reprompt_select_account forces Google's native 'Choose an account' dialog every time
    reprompt_select_account=True,
    # redirect_to tells Flask-Dance where to send the user AFTER the OAuth dance completes
    redirect_to="auth.oauth_continue",
    # redirect_url explicitly fixes the OAuth callback URL to APP_BASE_URL,
    # so it never changes based on how the app happens to be accessed (localhost vs 127.0.0.1)
    redirect_url=f"{APP_BASE_URL}/login/google/authorized",
)

# ─── GitHub OAuth Blueprint ──────────────────────────────────────────────────────
github_bp = make_github_blueprint(
    client_id=os.getenv("GITHUB_CLIENT_ID"),
    client_secret=os.getenv("GITHUB_CLIENT_SECRET"),
    scope="user:email",
    # redirect_to tells Flask-Dance where to send the user AFTER the OAuth dance completes
    redirect_to="auth.oauth_continue",
    # redirect_url explicitly fixes the OAuth callback URL to APP_BASE_URL
    redirect_url=f"{APP_BASE_URL}/login/github/authorized",
)


# ─── Google OAuth Callback ───────────────────────────────────────────────────
@oauth_authorized.connect_via(google_bp)
def google_logged_in(blueprint, token):
    if not token:
        flash("Failed to get token from Google. Please try again.", "danger")
        return redirect(url_for("auth.login"))

    try:
        resp = blueprint.session.get("/oauth2/v2/userinfo")
        if not resp.ok:
            flash("Failed to fetch your Google account info.", "danger")
            return False

        user_info = resp.json()
        email = (user_info.get("email") or "").strip().lower()
        full_name = user_info.get("name", "")
        picture = user_info.get("picture", "")
        provider_id = str(user_info.get("id", ""))

        if not email:
            flash("Could not retrieve email from your Google account.", "danger")
            return False

        db_user = db_service.create_oauth_user_full(
            email=email,
            provider="google",
            full_name=full_name,
            picture=picture,
            provider_id=provider_id,
        )

        pending = {
            "email": email,
            "full_name": full_name,
            "picture": picture,
            "auth_provider": "google",
            "user_id": (db_user or {}).get("id"),
        }
        session["oauth_pending"] = pending
        session.modified = True
        _clear_otp_session()
        return redirect(url_for("auth.oauth_continue"))
    except Exception as e:
        flash(f"Google sign-in error: {str(e)}", "danger")
        return redirect(url_for("auth.login"))


# ─── GitHub OAuth Callback ───────────────────────────────────────────────────
@oauth_authorized.connect_via(github_bp)
def github_logged_in(blueprint, token):
    if not token:
        flash("Failed to get token from GitHub. Please try again.", "danger")
        return redirect(url_for("auth.login"))

    try:
        resp = blueprint.session.get("/user")
        if not resp.ok:
            flash("Failed to fetch your GitHub account info.", "danger")
            return redirect(url_for("auth.login"))

        user_info = resp.json()
        username = user_info.get("login", "")
        full_name = user_info.get("name") or username
        picture = user_info.get("avatar_url", "")
        provider_id = str(user_info.get("id", ""))

        email = (user_info.get("email") or "").strip().lower()
        if not email:
            emails_resp = blueprint.session.get("/user/emails")
            if emails_resp.ok:
                emails = emails_resp.json() or []
                for item in emails:
                    if item.get("primary") and item.get("verified"):
                        email = (item.get("email") or "").strip().lower()
                        break
                if not email:
                    for item in emails:
                        if item.get("verified"):
                            email = (item.get("email") or "").strip().lower()
                            break

        if not email:
            flash("Could not retrieve a verified email from your GitHub account.", "danger")
            return redirect(url_for("auth.login"))

        db_user = db_service.create_oauth_user_full(
            email=email,
            provider="github",
            full_name=full_name,
            picture=picture,
            provider_id=provider_id,
        )

        pending = {
            "email": email,
            "full_name": full_name,
            "picture": picture,
            "auth_provider": "github",
            "user_id": (db_user or {}).get("id"),
        }
        session["oauth_pending"] = pending
        session.modified = True
        _clear_otp_session()
        return redirect(url_for("auth.oauth_continue"))
    except Exception as e:
        flash(f"GitHub sign-in error: {str(e)}", "danger")
        return redirect(url_for("auth.login"))



# ─── OAuth Continue / Finalize ───────────────────────────────────────────────
@auth_bp.route("/oauth-continue")
def oauth_continue():
    pending = session.get("oauth_pending")
    if not pending:
        if session.get("email"):
            return redirect(url_for("data.dashboard"))
        return redirect(url_for("auth.login"))

    _clear_otp_session()
    return render_template("oauth_continue.html", pending=pending, hide_auth_flashes=True)


@auth_bp.route("/oauth-finalize", methods=["POST"])
def oauth_finalize():
    """Complete OAuth — no verification code, straight to dashboard."""
    pending = session.get("oauth_pending")
    if not pending:
        if session.get("email"):
            return redirect(url_for("data.dashboard"))
        return redirect(url_for("auth.login"))

    _finalize_oauth_session(pending)
    return redirect(url_for("data.dashboard"))


# ─── Login / Register ────────────────────────────────────────────────────────
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if "email" in session and not session.get("oauth_pending"):
        return redirect(url_for("data.dashboard"))

    if request.method == "GET" and session.get("oauth_pending"):
        return redirect(url_for("auth.oauth_continue"))

    if request.method == "POST":
        action = request.form.get("action")  # 'login' or 'register'
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password")

        _clear_otp_session()

        # Backend Validation: Check if email is valid
        if not email or "@" not in email:
            flash("Please enter a valid email address.", "danger")
            active_tab = "register" if action == "register" else "login"
            return render_template("login.html", active_tab=active_tab)

        if action == "register":
            full_name = request.form.get("full_name", "").strip()
            confirm_password = request.form.get("confirm_password")

            if not full_name or not email or not password or not confirm_password:
                flash("Please fill in all 4 registration fields.", "danger")
                return render_template("login.html", active_tab="register")

            if password != confirm_password:
                flash("Passwords do not match. Please try again.", "danger")
                return render_template("login.html", active_tab="register")

            # Check if user already exists
            existing_user = db_service.get_user_by_email(email)
            if existing_user:
                flash("An account with this email already exists. Please log in.", "danger")
                return render_template("login.html", active_tab="login")

            # Store registration details in session
            session["reg_full_name"] = full_name
            session["reg_email"] = email
            session["reg_password"] = password

            # Send OTP for email/password registration only
            otp_code = db_service.create_otp(email, "account registration")
            email_service.send_otp(email, otp_code, "account registration")

            session["otp_purpose"] = "account registration"
            session["otp_target_email"] = email
            session["otp_flow"] = "email"
            session.modified = True

            return render_template(
                "login.html",
                show_otp_modal=True,
                otp_flow="email",
                otp_email=email,
                hide_auth_flashes=True,
            )

        else:  # Login — direct sign-in, no OTP
            if not email or not password:
                flash("Please enter both email and password.", "danger")
                return render_template("login.html", active_tab="login")

            # First check if the user account even exists
            existing = db_service.get_user_by_email(email)
            if not existing:
                flash("No account registered with this email. Please sign up first.", "danger")
                return render_template("login.html", active_tab="login")

            # Account exists — check if it was created via OAuth (not password)
            pwd_hash = existing.get("password_hash", "")
            if pwd_hash.startswith("oauth:"):
                provider = existing.get("auth_provider", "OAuth")
                provider_label = provider.capitalize()
                flash(
                    f"This email is registered via {provider_label} login. "
                    f"Please continue with {provider_label} instead.",
                    "danger"
                )
                return render_template("login.html", active_tab="login")

            # Account exists and is a password account — now verify password
            user = db_service.verify_credentials(email, password)
            if not user:
                flash("Invalid email or password.", "danger")
                return render_template("login.html", active_tab="login")

            # Valid credentials — send login OTP for email/password sign-in only
            otp_code = db_service.create_otp(email, "account login")
            email_service.send_otp(email, otp_code, "account login")

            session["otp_purpose"] = "account login"
            session["otp_target_email"] = email
            session["otp_flow"] = "email"
            session["login_user_id"] = user.get("id")
            session["login_full_name"] = user.get("full_name", "")
            session.modified = True

            return render_template(
                "login.html",
                show_otp_modal=True,
                active_tab="login",
                otp_flow="email",
                otp_email=email,
                hide_auth_flashes=True,
            )

    return render_template("login.html")


# ─── OTP Verification ────────────────────────────────────────────────────────
@auth_bp.route("/verify-otp", methods=["POST"])
def verify_otp():
    purpose = session.get("otp_purpose")
    email = session.get("otp_target_email")
    otp_flow = session.get("otp_flow", "email")
    active_tab = "login" if purpose == "account login" else "register"

    if otp_flow != "email" or purpose not in EMAIL_OTP_PURPOSES:
        flash("Verification is only required for email/password sign-in.", "danger")
        return redirect(url_for("auth.login"))

    # Concatenate 4 digit fields
    digit1 = request.form.get("digit1", "")
    digit2 = request.form.get("digit2", "")
    digit3 = request.form.get("digit3", "")
    digit4 = request.form.get("digit4", "")

    code = f"{digit1}{digit2}{digit3}{digit4}".strip()

    if len(code) != 4 or not code.isdigit():
        return render_template(
            "login.html",
            show_otp_modal=True,
            active_tab=active_tab,
            otp_flow="email",
            otp_email=email,
            otp_error="Invalid code format. Please enter all 4 digits.",
            hide_auth_flashes=True,
        )

    if not email or not purpose:
        flash("Verification session expired. Please try again.", "danger")
        return redirect(url_for("auth.login"))

    is_valid = db_service.verify_otp(email, code, purpose)

    if is_valid:
        if purpose == "account registration":
            reg_password = session.get("reg_password")
            full_name = session.get("reg_full_name", "")
            if not reg_password:
                flash("Registration session expired.", "danger")
                _clear_otp_session()
                return redirect(url_for("auth.login"))

            user = db_service.create_user(email, reg_password, full_name=full_name)
            session.pop("reg_password", None)
            session.pop("reg_email", None)
            session.pop("reg_full_name", None)
            _clear_otp_session()

            if user:
                session.permanent = True
                session["email"] = email
                if user.get("id"):
                    session["user_id"] = user.get("id")
                session["full_name"] = full_name
                session["auth_provider"] = "email"
                session.modified = True
                flash("Account registered and verified successfully!", "success")
                return redirect(url_for("data.dashboard"))
            flash("Registration failed. Please try again.", "danger")
            return redirect(url_for("auth.login"))

        if purpose == "account login":
            user = db_service.get_user_by_email(email)
            session.permanent = True
            session["email"] = email
            session["user_id"] = (user or {}).get("id") or session.get("login_user_id")
            session["full_name"] = (user or {}).get("full_name") or session.get("login_full_name", "")
            session["auth_provider"] = "email"
            _clear_otp_session()
            session.modified = True
            flash("Logged in successfully!", "success")
            return redirect(url_for("data.dashboard"))

        if purpose in ("password reset request", "reset"):
            session["otp_verified_for_reset"] = True
            session.modified = True
            return redirect(url_for("auth.reset_password"))

    if purpose == "password reset request":
        return render_template(
            "reset.html",
            show_otp_modal=True,
            otp_email=email,
            otp_error="Incorrect or expired verification code. Please try again.",
            hide_auth_flashes=True,
        )

    return render_template(
        "login.html",
        show_otp_modal=True,
        active_tab=active_tab,
        otp_flow="email",
        otp_email=email,
        otp_error="Incorrect or expired verification code. Please try again.",
        hide_auth_flashes=True,
    )



# ─── Forgot Password ─────────────────────────────────────────────────────────
@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if not email:
            flash("Please enter your email.", "danger")
            return render_template("reset.html")

        user = db_service.get_user_by_email(email)
        if not user:
            flash("If the account exists, a reset code has been sent.", "info")
            return redirect(url_for("auth.forgot_password"))

        otp_code = db_service.create_otp(email, "password reset request")
        email_service.send_otp(email, otp_code, "password reset request")

        session["otp_purpose"] = "password reset request"
        session["otp_target_email"] = email
        session["otp_flow"] = "email"
        session.modified = True

        return render_template(
            "reset.html",
            show_otp_modal=True,
            otp_email=email,
            hide_auth_flashes=True,
        )

    return render_template("reset.html")


# ─── Reset Password ──────────────────────────────────────────────────────────
@auth_bp.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    if not session.get("otp_verified_for_reset") or not session.get("otp_target_email"):
        flash("Unauthorized. Please request a password reset code first.", "danger")
        return redirect(url_for("auth.forgot_password"))

    if request.method == "POST":
        new_password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")
        email = session.get("otp_target_email")

        if not new_password or not confirm_password:
            flash("Please enter both password fields.", "danger")
            return render_template("reset.html")

        if new_password != confirm_password:
            flash("Passwords do not match.", "danger")
            return render_template("reset.html")

        success = db_service.update_password(email, new_password)
        if success:
            session.pop("otp_verified_for_reset", None)
            session.pop("otp_target_email", None)
            flash("Password updated successfully! Please log in with your new password.", "success")
            return redirect(url_for("auth.login"))
        else:
            flash("Failed to update password. User not found.", "danger")
            return redirect(url_for("auth.login"))

    return render_template("reset.html")


# ─── Logout ──────────────────────────────────────────────────────────────────
@auth_bp.route("/logout")
def logout():
    import os
    from routes.data import get_dataset_path

    # Remove the active dataset if it exists before clearing session
    dataset_path = get_dataset_path()
    if dataset_path and os.path.exists(dataset_path):
        try:
            os.remove(dataset_path)
        except Exception:
            pass

    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login"))