import os
import json
import datetime
import random
import bcrypt
from dotenv import load_dotenv
from supabase import create_client, Client
import psycopg2
import psycopg2.extras

load_dotenv()

OTP_EXPIRY_MINUTES = 2

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY", "")


class DBService:
    def __init__(self):
        if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
            try:
                self.client: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
            except Exception as e:
                print(f"Failed to initialize Supabase REST client: {e}")
                self.client = None
        else:
            self.client = None

    def get_client(self) -> Client:
        if not self.client:
            url = os.getenv("SUPABASE_URL", "")
            key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY", "")
            if url and key:
                try:
                    self.client = create_client(url, key)
                except Exception as e:
                    print(f"Error initializing Supabase client: {e}")
        return self.client

    def get_db_conn(self):
        """Returns a direct psycopg2 Postgres connection using DATABASE_URL."""
        db_url = os.getenv("DATABASE_URL")
        if db_url:
            try:
                conn = psycopg2.connect(db_url)
                return conn
            except Exception as e:
                print(f"Error connecting to DATABASE_URL: {e}")
        return None

    # ─── Password Utilities ──────────────────────────────────────────────────

    def hash_password(self, password):
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    def check_password(self, password, hashed):
        try:
            return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
        except Exception:
            return False

    # ─── User Management ─────────────────────────────────────────────────────

    def create_user(self, email, password, full_name=""):
        """Creates a new email/password user in Supabase. Returns user dict or None if exists."""
        email = email.lower().strip()
        hashed = self.hash_password(password)

        existing = self.get_user_by_email(email)
        if existing:
            return None

        now = datetime.datetime.now(datetime.timezone.utc)
        conn = self.get_db_conn()
        if conn:
            try:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute(
                    """
                    INSERT INTO users (email, password_hash, full_name, auth_provider, is_verified, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, True, %s, %s)
                    RETURNING *
                    """,
                    (email, hashed, full_name, "email", now, now)
                )
                user = cur.fetchone()
                conn.commit()
                conn.close()
                if user:
                    return dict(user)
            except Exception as e:
                print(f"Direct SQL create_user failed, trying REST API fallback: {e}")
                if conn:
                    conn.close()

        # Fallback to Supabase client
        client = self.get_client()
        if not client:
            return None
        try:
            now_iso = now.isoformat()
            res = client.table("users").insert({
                "email": email,
                "password_hash": hashed,
                "full_name": full_name,
                "auth_provider": "email",
                "is_verified": True,
                "created_at": now_iso,
                "updated_at": now_iso
            }).execute()

            if res.data and len(res.data) > 0:
                return res.data[0]
            return {"email": email, "full_name": full_name}
        except Exception as e:
            print(f"Error creating user in Supabase client: {e}")
            return None

    def create_oauth_user_full(self, email, provider, full_name="", picture="", provider_id=""):
        """Upsert a user who authenticated via OAuth (Google or GitHub)."""
        email = email.lower().strip()
        now = datetime.datetime.now(datetime.timezone.utc)

        conn = self.get_db_conn()
        if conn:
            try:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                existing = self.get_user_by_email(email)
                if existing:
                    cur.execute(
                        """
                        UPDATE users
                        SET full_name = COALESCE(NULLIF(%s, ''), full_name),
                            profile_picture_url = COALESCE(NULLIF(%s, ''), profile_picture_url),
                            auth_provider = %s,
                            provider_user_id = %s,
                            is_verified = True,
                            updated_at = %s
                        WHERE LOWER(email) = LOWER(%s)
                        RETURNING *
                        """,
                        (full_name, picture, provider, provider_id, now, email)
                    )
                    user = cur.fetchone()
                    conn.commit()
                    conn.close()
                    return dict(user) if user else existing
                else:
                    cur.execute(
                        """
                        INSERT INTO users (email, password_hash, full_name, profile_picture_url, auth_provider, provider_user_id, is_verified, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, True, %s, %s)
                        RETURNING *
                        """,
                        (email, f"oauth:{provider}", full_name, picture, provider, provider_id, now, now)
                    )
                    user = cur.fetchone()
                    conn.commit()
                    conn.close()
                    return dict(user) if user else None
            except Exception as e:
                print(f"Direct SQL create_oauth_user_full failed, falling back to REST: {e}")
                if conn:
                    conn.close()

        client = self.get_client()
        if not client:
            return None

        now_iso = now.isoformat()
        try:
            existing = self.get_user_by_email(email)
            if existing:
                res = client.table("users").update({
                    "full_name": full_name or existing.get("full_name", ""),
                    "profile_picture_url": picture or existing.get("profile_picture_url", ""),
                    "auth_provider": provider,
                    "provider_user_id": provider_id,
                    "is_verified": True,
                    "updated_at": now_iso
                }).eq("email", email).execute()
                return res.data[0] if res.data else existing
            else:
                res = client.table("users").insert({
                    "email": email,
                    "password_hash": f"oauth:{provider}",
                    "full_name": full_name,
                    "profile_picture_url": picture,
                    "auth_provider": provider,
                    "provider_user_id": provider_id,
                    "is_verified": True,
                    "created_at": now_iso,
                    "updated_at": now_iso
                }).execute()
                return res.data[0] if res.data else None
        except Exception as e:
            print(f"Error in create_oauth_user_full REST: {e}")
            return None

    def get_user_by_email(self, email):
        """Gets a user by email from Supabase (direct SQL or REST)"""
        if not email:
            return None
        email = email.lower().strip()

        conn = self.get_db_conn()
        if conn:
            try:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute("SELECT * FROM users WHERE LOWER(email) = LOWER(%s) LIMIT 1", (email,))
                user = cur.fetchone()
                conn.close()
                if user:
                    return dict(user)
                return None
            except Exception as e:
                print(f"Direct SQL get_user_by_email failed, falling back to REST: {e}")
                if conn:
                    conn.close()

        client = self.get_client()
        if not client:
            return None
        try:
            res = client.table("users").select("*").eq("email", email).limit(1).execute()
            if res.data and len(res.data) > 0:
                return res.data[0]
            return None
        except Exception as e:
            print(f"Error fetching user by email from Supabase: {e}")
            return None

    def verify_credentials(self, email, password):
        """Verifies email and password for email/password users"""
        user = self.get_user_by_email(email)
        if not user:
            return None
        pwd_hash = user.get("password_hash", "")
        if pwd_hash.startswith("oauth:"):
            return None
        if self.check_password(password, pwd_hash):
            return user
        return None

    # ─── OTP Management ─────────────────────────────────────────────────────

    def create_otp(self, email, purpose):
        """Generates a 4-digit OTP code, stores it in Supabase, and returns the code"""
        email = email.lower().strip()
        code = f"{random.randint(1000, 9999)}"
        now = datetime.datetime.now(datetime.timezone.utc)
        expires_at = now + datetime.timedelta(minutes=OTP_EXPIRY_MINUTES)

        conn = self.get_db_conn()
        if conn:
            try:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                # Invalidate old OTPs for this email & purpose
                cur.execute(
                    "UPDATE otps SET verified = True WHERE LOWER(email) = LOWER(%s) AND purpose = %s AND verified = False",
                    (email, purpose)
                )
                # Insert new OTP
                cur.execute(
                    """
                    INSERT INTO otps (email, code, purpose, expires_at, verified, created_at)
                    VALUES (%s, %s, %s, %s, False, %s)
                    RETURNING *
                    """,
                    (email, code, purpose, expires_at, now)
                )
                conn.commit()
                conn.close()
                return code
            except Exception as e:
                print(f"Direct SQL create_otp failed, falling back to REST: {e}")
                if conn:
                    conn.close()

        client = self.get_client()
        if client:
            try:
                expires_iso = expires_at.isoformat()
                now_iso = now.isoformat()
                client.table("otps").update({"verified": True}).eq("email", email).eq("purpose", purpose).execute()
                client.table("otps").insert({
                    "email": email,
                    "code": code,
                    "purpose": purpose,
                    "expires_at": expires_iso,
                    "verified": False,
                    "created_at": now_iso
                }).execute()
            except Exception as e:
                print(f"Error creating OTP in Supabase client: {e}")

        return code

    def verify_otp(self, email, code, purpose):
        """Verifies a 4-digit OTP code in Supabase with robust timezone handling."""
        email = email.lower().strip()
        code = str(code).strip().zfill(4)
        now = datetime.datetime.now(datetime.timezone.utc)

        conn = self.get_db_conn()
        if conn:
            try:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute(
                    """
                    SELECT * FROM otps 
                    WHERE LOWER(email) = LOWER(%s) AND purpose = %s AND verified = False 
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (email, purpose)
                )
                row = cur.fetchone()
                if row:
                    stored_code = str(row.get("code", "")).strip().zfill(4)
                    exp_time = row.get("expires_at")
                    if exp_time:
                        if exp_time.tzinfo is None:
                            exp_time = exp_time.replace(tzinfo=datetime.timezone.utc)
                    if stored_code == code and exp_time and exp_time > now:
                        cur.execute("UPDATE otps SET verified = True WHERE id = %s", (row["id"],))
                        conn.commit()
                        conn.close()
                        return True
                conn.close()
                return False
            except Exception as e:
                print(f"Direct SQL verify_otp failed, trying REST fallback: {e}")
                if conn:
                    conn.close()

        client = self.get_client()
        if not client:
            return False

        try:
            res = (
                client.table("otps")
                .select("*")
                .eq("purpose", purpose)
                .eq("verified", False)
                .order("created_at", desc=True)
                .limit(20)
                .execute()
            )
            records = res.data or []
            record = next(
                (row for row in records if str(row.get("email", "")).lower().strip() == email),
                None,
            )
            if record:
                stored_code = str(record.get("code", "")).strip().zfill(4)
                exp_str = record.get("expires_at")
                if exp_str:
                    try:
                        exp_dt = datetime.datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
                        if exp_dt.tzinfo is None:
                            exp_dt = exp_dt.replace(tzinfo=datetime.timezone.utc)
                    except Exception:
                        exp_dt = None
                else:
                    exp_dt = None

                if stored_code == code and exp_dt and exp_dt > now:
                    otp_id = record["id"]
                    client.table("otps").update({"verified": True}).eq("id", otp_id).execute()
                    return True
            return False
        except Exception as e:
            print(f"Error verifying OTP in Supabase: {e}")
            return False

    # ─── Password Reset ──────────────────────────────────────────────────────

    def update_password(self, email, new_password):
        """Updates user's password in Supabase"""
        email = email.lower().strip()
        hashed = self.hash_password(new_password)
        now = datetime.datetime.now(datetime.timezone.utc)

        conn = self.get_db_conn()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE users SET password_hash = %s, updated_at = %s WHERE LOWER(email) = LOWER(%s)",
                    (hashed, now, email)
                )
                updated_rows = cur.rowcount
                conn.commit()
                conn.close()
                return updated_rows > 0
            except Exception as e:
                print(f"Direct SQL update_password failed: {e}")
                if conn:
                    conn.close()

        client = self.get_client()
        if not client:
            return False

        try:
            now_iso = now.isoformat()
            res = client.table("users").update({
                "password_hash": hashed,
                "updated_at": now_iso
            }).eq("email", email).execute()
            return bool(res.data and len(res.data) > 0)
        except Exception as e:
            print(f"Error updating password in Supabase: {e}")
            return False

    # ─── Chat & Dataset Management in Supabase ────────────────────────────────

    def get_or_create_chat_session(self, user_id, title="Data Analysis Chat", dataset_name="active_dataset.csv"):
        """Get latest chat session or create a new one for user in Supabase."""
        now = datetime.datetime.now(datetime.timezone.utc)
        conn = self.get_db_conn()
        if conn and user_id:
            try:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute(
                    "SELECT * FROM chat_sessions WHERE user_id = %s ORDER BY updated_at DESC LIMIT 1",
                    (user_id,)
                )
                session = cur.fetchone()
                if session:
                    conn.close()
                    return dict(session)

                cur.execute(
                    """
                    INSERT INTO chat_sessions (user_id, title, dataset_name, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (user_id, title, dataset_name, now, now)
                )
                new_session = cur.fetchone()
                conn.commit()
                conn.close()
                return dict(new_session) if new_session else None
            except Exception as e:
                print(f"Direct SQL get_or_create_chat_session failed: {e}")
                if conn:
                    conn.close()

        client = self.get_client()
        if not client or not user_id:
            return None
        try:
            res = client.table("chat_sessions").select("*").eq("user_id", user_id).order("updated_at", desc=True).limit(1).execute()
            if res.data and len(res.data) > 0:
                return res.data[0]

            now_iso = now.isoformat()
            new_res = client.table("chat_sessions").insert({
                "user_id": user_id,
                "title": title,
                "dataset_name": dataset_name,
                "created_at": now_iso,
                "updated_at": now_iso
            }).execute()
            return new_res.data[0] if new_res.data else None
        except Exception as e:
            print(f"Error in get_or_create_chat_session REST: {e}")
            return None

    def save_chat_message(self, session_id, sender, content, chart_type=None, chart_data=None):
        """Save a user or AI message into chat_messages table in Supabase."""
        now = datetime.datetime.now(datetime.timezone.utc)
        conn = self.get_db_conn()
        if conn and session_id:
            try:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                chart_data_json = json.dumps(chart_data) if chart_data is not None else None
                cur.execute(
                    """
                    INSERT INTO chat_messages (session_id, sender, content, chart_type, chart_data, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (session_id, sender, content, chart_type, chart_data_json, now)
                )
                msg = cur.fetchone()
                cur.execute("UPDATE chat_sessions SET updated_at = %s WHERE id = %s", (now, session_id))
                conn.commit()
                conn.close()
                return dict(msg) if msg else None
            except Exception as e:
                print(f"Direct SQL save_chat_message failed: {e}")
                if conn:
                    conn.close()

        client = self.get_client()
        if not client or not session_id:
            return None
        try:
            now_iso = now.isoformat()
            res = client.table("chat_messages").insert({
                "session_id": session_id,
                "sender": sender,
                "content": content,
                "chart_type": chart_type,
                "chart_data": chart_data,
                "created_at": now_iso
            }).execute()

            client.table("chat_sessions").update({"updated_at": now_iso}).eq("id", session_id).execute()
            return res.data[0] if res.data else None
        except Exception as e:
            print(f"Error saving chat message in Supabase REST: {e}")
            return None

    def get_chat_messages(self, user_id, limit=200):
        """Return chat messages for the user's latest session, oldest first."""
        if not user_id:
            return []

        session_row = self.get_or_create_chat_session(user_id)
        if not session_row or not session_row.get("id"):
            return []

        session_id = session_row["id"]
        conn = self.get_db_conn()
        if conn:
            try:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute(
                    """
                    SELECT sender, content, chart_type, chart_data, created_at
                    FROM chat_messages
                    WHERE session_id = %s
                    ORDER BY created_at ASC
                    LIMIT %s
                    """,
                    (session_id, limit),
                )
                rows = cur.fetchall()
                conn.close()
                return [dict(row) for row in rows]
            except Exception as e:
                print(f"Direct SQL get_chat_messages failed: {e}")
                if conn:
                    conn.close()

        client = self.get_client()
        if not client:
            return []
        try:
            res = (
                client.table("chat_messages")
                .select("sender, content, chart_type, chart_data, created_at")
                .eq("session_id", session_id)
                .order("created_at")
                .limit(limit)
                .execute()
            )
            return res.data or []
        except Exception as e:
            print(f"Error in get_chat_messages REST: {e}")
            return []

    def save_dataset_upload(self, user_id, original_name, row_count, col_count, file_size_bytes, columns, dtypes):
        """Save dataset upload metadata in dataset_uploads table in Supabase."""
        now = datetime.datetime.now(datetime.timezone.utc)
        conn = self.get_db_conn()
        if conn and user_id:
            try:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute("UPDATE dataset_uploads SET is_active = False WHERE user_id = %s", (user_id,))
                cur.execute(
                    """
                    INSERT INTO dataset_uploads (user_id, original_name, row_count, col_count, file_size_bytes, columns, dtypes, is_active, uploaded_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, True, %s)
                    RETURNING *
                    """,
                    (user_id, original_name, row_count, col_count, file_size_bytes, json.dumps(columns), json.dumps(dtypes), now)
                )
                upload_rec = cur.fetchone()
                conn.commit()
                conn.close()
                return dict(upload_rec) if upload_rec else None
            except Exception as e:
                print(f"Direct SQL save_dataset_upload failed: {e}")
                if conn:
                    conn.close()

        client = self.get_client()
        if not client or not user_id:
            return None
        try:
            now_iso = now.isoformat()
            client.table("dataset_uploads").update({"is_active": False}).eq("user_id", user_id).execute()

            res = client.table("dataset_uploads").insert({
                "user_id": user_id,
                "original_name": original_name,
                "row_count": row_count,
                "col_count": col_count,
                "file_size_bytes": file_size_bytes,
                "columns": columns,
                "dtypes": dtypes,
                "is_active": True,
                "uploaded_at": now_iso
            }).execute()
            return res.data[0] if res.data else None
        except Exception as e:
            print(f"Error saving dataset upload in Supabase REST: {e}")
            return None


db_service = DBService()
