import os, json, time, uuid, shutil, subprocess, threading, signal, secrets
import requests
import base64
from collections import deque
from pathlib import Path
from functools import wraps
from datetime import datetime
from flask import (
    Flask, request, redirect, url_for, session,
    render_template, jsonify, Response, send_from_directory, abort, flash
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"
USERS_FILE = DATA_DIR / "users.json"
PRICING_FILE = DATA_DIR / "pricing.json"
FILES_ROOT = APP_DIR / "user_files"
DATA_DIR.mkdir(exist_ok=True)
FILES_ROOT.mkdir(exist_ok=True)

# Owner credentials
OWNER_USER = "DarkLord813"
OWNER_PASS = "DarkLord813_codex"

# Flutterwave Configuration
FLW_PUBLIC_KEY = os.environ.get("FLW_PUBLIC_KEY", "")
FLW_SECRET_KEY = os.environ.get("FLW_SECRET_KEY", "")
FLW_ENCRYPTION_KEY = os.environ.get("FLW_ENCRYPTION_KEY", "")
FLW_ENABLED = bool(FLW_PUBLIC_KEY and FLW_SECRET_KEY and FLW_ENCRYPTION_KEY)

# Flutterwave API endpoints
FLW_INITIALIZE_URL = "https://api.flutterwave.com/v3/payments"
FLW_VERIFY_URL = "https://api.flutterwave.com/v3/transactions/"

# Supported currencies (4 currencies)
SUPPORTED_CURRENCIES = {
    "NGN": {"symbol": "₦", "name": "Nigerian Naira", "country": "Nigeria", "flag": "🇳🇬"},
    "USD": {"symbol": "$", "name": "US Dollar", "country": "United States", "flag": "🇺🇸"},
    "EUR": {"symbol": "€", "name": "Euro", "country": "Europe", "flag": "🇪🇺"},
    "GBP": {"symbol": "£", "name": "British Pound", "country": "United Kingdom", "flag": "🇬🇧"},
}

DEFAULT_PRICING = {
    "currency": "NGN",
    "contact": "Telegram: @rexoronsaye",
    "plans": [
        {
            "name": "Basic",
            "duration": "Monthly",
            "price": "2500",
            "features": "Python only, 1GB RAM, Basic support"
        },
        {
            "name": "Pro",
            "duration": "Yearly",
            "price": "15000",
            "features": "Python/Node/Shell, pip/npm, 2GB RAM, Priority support"
        },
        {
            "name": "Premium",
            "duration": "Yearly",
            "price": "25000",
            "features": "All features, 4GB RAM, Dedicated help, Best value!"
        },
    ],
    "currency_pricing": {
        "NGN": {"Basic": "2500", "Pro": "15000", "Premium": "25000"},
        "USD": {"Basic": "3.00", "Pro": "18.00", "Premium": "30.00"},
        "EUR": {"Basic": "2.80", "Pro": "16.50", "Premium": "28.00"},
        "GBP": {"Basic": "2.40", "Pro": "14.50", "Premium": "24.00"},
    }
}

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024

# ==================== GITHUB BACKUP SYSTEM (MERGED) ====================
class GitHubBackupSystem:
    def __init__(self, data_dir, files_root):
        self.data_dir = data_dir
        self.files_root = files_root
        
        # Read from environment variables
        self.token = os.environ.get("GITHUB_TOKEN", "")
        self.repo_owner = os.environ.get("GITHUB_REPO_OWNER", "")
        self.repo_name = os.environ.get("GITHUB_REPO_NAME", "")
        self.branch = os.environ.get("GITHUB_BACKUP_BRANCH", "main")
        self.backup_path = os.environ.get("GITHUB_BACKUP_PATH", "backups/database.json")
        
        # Check if configured
        self.is_enabled = bool(self.token and self.repo_owner and self.repo_name)
        
        print(f"=== GITHUB BACKUP ===")
        print(f"Enabled: {self.is_enabled}")
        print(f"Repo: {self.repo_owner}/{self.repo_name}")
        print(f"Token: {'SET' if self.token else 'MISSING'}")
        print(f"=====================")
        
        self._session = requests.Session()
        self._backup_count = 0
    
    @property
    def _headers(self):
        return {
            'Authorization': f'token {self.token}',
            'Accept': 'application/vnd.github.v3+json'
        }
    
    def _get_api_url(self):
        return f"https://api.github.com/repos/{self.repo_owner}/{self.repo_name}/contents/{self.backup_path}"
    
    def _has_data(self):
        users_file = self.data_dir / "users.json"
        pricing_file = self.data_dir / "pricing.json"
        return users_file.exists() or pricing_file.exists()
    
    def _get_users_count(self):
        try:
            users_file = self.data_dir / "users.json"
            if users_file.exists():
                with open(users_file, 'r') as f:
                    data = json.load(f)
                    return len(data)
            return 0
        except:
            return 0
    
    def backup(self, reason="Auto backup"):
        if not self.is_enabled:
            print("Backup skipped: not enabled")
            return False
        
        if not self._has_data():
            print("Backup skipped: no data")
            return False
        
        try:
            users_data = {}
            pricing_data = {}
            
            if USERS_FILE.exists():
                with open(USERS_FILE, 'r') as f:
                    users_data = json.load(f)
            
            if PRICING_FILE.exists():
                with open(PRICING_FILE, 'r') as f:
                    pricing_data = json.load(f)
            
            backup_data = {
                "timestamp": datetime.now().isoformat(),
                "users": users_data,
                "pricing": pricing_data,
                "stats": {
                    "users_count": len(users_data)
                }
            }
            
            json_str = json.dumps(backup_data, indent=2)
            encoded = base64.b64encode(json_str.encode()).decode()
            
            # Check if file exists
            api_url = self._get_api_url()
            r = self._session.get(api_url, headers=self._headers)
            file_sha = r.json().get('sha') if r.status_code == 200 else None
            
            payload = {
                'message': f"{reason} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                'content': encoded,
                'branch': self.branch
            }
            if file_sha:
                payload['sha'] = file_sha
            
            r = self._session.put(api_url, headers=self._headers, json=payload, timeout=60)
            
            if r.status_code in (200, 201):
                self._backup_count += 1
                print(f"Backup successful (#{self._backup_count})")
                return True
            else:
                print(f"Backup failed: {r.status_code}")
                return False
                
        except Exception as e:
            print(f"Backup error: {e}")
            return False
    
    def restore(self):
        if not self.is_enabled:
            return False
        
        try:
            api_url = self._get_api_url()
            r = self._session.get(api_url, headers=self._headers, timeout=60)
            
            if r.status_code != 200:
                print(f"No backup found: {r.status_code}")
                return False
            
            content = r.json().get('content', '')
            if not content:
                return False
            
            json_str = base64.b64decode(content.replace('\n', '')).decode()
            data = json.loads(json_str)
            
            if "users" in data:
                with open(USERS_FILE, 'w') as f:
                    json.dump(data["users"], f, indent=2)
                print(f"Restored {len(data['users'])} users")
            
            if "pricing" in data:
                with open(PRICING_FILE, 'w') as f:
                    json.dump(data["pricing"], f, indent=2)
                print("Restored pricing data")
            
            return True
            
        except Exception as e:
            print(f"Restore error: {e}")
            return False
    
    def get_status(self):
        return {
            "enabled": self.is_enabled,
            "backup_count": self._backup_count,
            "repo": f"{self.repo_owner}/{self.repo_name}",
            "users": self._get_users_count()
        }

# Initialize backup system
print("=" * 60)
print("INITIALIZING NCK DEV VPS")
print("=" * 60)

github_backup = GitHubBackupSystem(DATA_DIR, FILES_ROOT)

# Restore on startup if enabled
if github_backup.is_enabled:
    print("Attempting to restore from GitHub...")
    restored = github_backup.restore()
    if restored:
        print("Restore successful!")
    else:
        print("No backup found - starting fresh")
    print("Auto-backup thread started")
    
    def auto_backup_loop():
        while True:
            time.sleep(120)
            if github_backup.is_enabled:
                github_backup.backup("Auto backup")
    
    threading.Thread(target=auto_backup_loop, daemon=True).start()

print("=" * 60)

# ==================== HELPER FUNCTIONS ====================
def manual_backup(reason="Manual backup"):
    return github_backup.backup(reason)

def get_backup_status():
    return github_backup.get_status()

def has_data():
    return USERS_FILE.exists() or PRICING_FILE.exists()

def force_restore():
    return github_backup.restore()

# ---------- storage ----------
_lock = threading.Lock()

def load_users():
    if not USERS_FILE.exists():
        return {}
    try:
        return json.loads(USERS_FILE.read_text())
    except Exception:
        return {}

def save_users(u):
    with _lock:
        USERS_FILE.write_text(json.dumps(u, indent=2))
    threading.Thread(target=lambda: manual_backup("User data changed"), daemon=True).start()

def load_pricing():
    if not PRICING_FILE.exists():
        save_pricing(DEFAULT_PRICING)
        return DEFAULT_PRICING
    try:
        return json.loads(PRICING_FILE.read_text())
    except Exception:
        return DEFAULT_PRICING

def save_pricing(p):
    with _lock:
        PRICING_FILE.write_text(json.dumps(p, indent=2))
    threading.Thread(target=lambda: manual_backup("Pricing data changed"), daemon=True).start()

def user_dir(username):
    d = FILES_ROOT / username
    d.mkdir(parents=True, exist_ok=True)
    return d

# ---------- process manager ----------
PROCS = {}

def _reader(username, proc):
    buf = PROCS[username]["logs"]
    try:
        for line in iter(proc.stdout.readline, b""):
            try:
                txt = line.decode("utf-8", errors="replace").rstrip()
            except Exception:
                txt = str(line)
            buf.append(f"[{time.strftime('%H:%M:%S')}] {txt}")
    except Exception as e:
        buf.append(f"[reader-error] {e}")
    finally:
        buf.append(f"[exit] process ended with code {proc.poll()}")

def start_process(username, filename):
    stop_process(username)
    udir = user_dir(username)
    fpath = udir / filename
    if not fpath.exists():
        return False, "File not found"
    ext = fpath.suffix.lower()

    users = load_users()
    user_data = users.get(username, {})
    subscription = user_data.get("subscription", "Basic")

    if user_data.get("payment_status") != "paid":
        return False, "Please subscribe to a plan to run files"

    if subscription == "Basic" and ext not in [".py"]:
        return False, "Basic plan only supports Python files"

    if ext == ".py":
        cmd = ["python", "-u", str(fpath)]
    elif ext in (".js", ".mjs", ".cjs"):
        cmd = ["node", str(fpath)]
    elif ext == ".sh":
        cmd = ["bash", str(fpath)]
    else:
        return False, f"Unsupported file type: {ext}"

    memory_limit = {
        "Basic": "1g",
        "Pro": "2g",
        "Premium": "4g"
    }.get(subscription, "1g")

    try:
        proc = subprocess.Popen(
            cmd, cwd=str(udir),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            bufsize=1,
        )
    except FileNotFoundError as e:
        return False, f"Runtime not installed: {e}"
    logs = deque(maxlen=2000)
    logs.append(f"[start] {' '.join(cmd)}")
    logs.append(f"[subscription] {subscription} (Memory: {memory_limit})")
    PROCS[username] = {"proc": proc, "logs": logs, "file": filename, "subscription": subscription}
    t = threading.Thread(target=_reader, args=(username, proc), daemon=True)
    t.start()
    PROCS[username]["thread"] = t
    return True, "started"

def stop_process(username):
    info = PROCS.get(username)
    if not info:
        return False
    p = info["proc"]
    if p.poll() is None:
        try:
            p.terminate()
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
        except Exception:
            pass
        info["logs"].append("[stop] process terminated")
    return True

def is_running(username):
    info = PROCS.get(username)
    return bool(info and info["proc"].poll() is None)

def get_logs(username):
    info = PROCS.get(username)
    if not info:
        return []
    return list(info["logs"])

# ---------- install module ----------
INSTALL_LOGS = {}

def run_install(username, command):
    users = load_users()
    user_data = users.get(username, {})
    subscription = user_data.get("subscription", "Basic")

    if user_data.get("payment_status") != "paid":
        return False, "Please subscribe to a plan to install modules"

    parts = command.strip().split()
    if not parts:
        return False, "empty command"

    if subscription == "Basic" and parts[0] in ["pip", "pip3"]:
        return False, "Basic plan doesn't support pip install. Upgrade to Pro or Premium."

    if parts[0] not in ("pip", "pip3", "npm"):
        return False, "Only 'pip install <pkg>' or 'npm install <pkg>' allowed"
    if len(parts) < 3 or parts[1] != "install":
        return False, "Format: pip install <module>  OR  npm install <module>"
    if any(c in command for c in [";", "&", "|", "`", "$(", ">"]):
        return False, "Invalid characters"

    logs = INSTALL_LOGS.setdefault(username, deque(maxlen=1000))
    logs.append(f"[install] $ {command}")
    cwd = str(user_dir(username))
    def worker():
        try:
            p = subprocess.Popen(parts, cwd=cwd,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            for line in iter(p.stdout.readline, b""):
                logs.append(line.decode("utf-8", errors="replace").rstrip())
            p.wait()
            logs.append(f"[install] finished with code {p.returncode}")
        except Exception as e:
            logs.append(f"[install-error] {e}")
    threading.Thread(target=worker, daemon=True).start()
    return True, "installing"

# ---------- auth ----------
def is_owner():
    return session.get("role") == "owner"

def current_user():
    return session.get("username")

def user_valid(username):
    users = load_users()
    u = users.get(username)
    if not u:
        return False, "User not found"
    return True, u

def require_owner(f):
    @wraps(f)
    def w(*a, **kw):
        if not is_owner():
            return redirect(url_for("login"))
        return f(*a, **kw)
    return w

def require_user(f):
    @wraps(f)
    def w(*a, **kw):
        u = current_user()
        if not u or session.get("role") != "user":
            return redirect(url_for("login"))
        ok, _ = user_valid(u)
        if not ok:
            session.clear()
            return redirect(url_for("login"))
        return f(*a, **kw)
    return w

# ---------- routes ----------
@app.route("/")
def index():
    if is_owner():
        return redirect(url_for("owner_dashboard"))
    if current_user():
        return redirect(url_for("user_dashboard"))
    return redirect(url_for("landing"))

@app.route("/home")
def landing():
    return render_template("landing.html",
        pricing=load_pricing(),
        flw_key=FLW_PUBLIC_KEY,
        flw_enabled=FLW_ENABLED,
        currencies=SUPPORTED_CURRENCIES
    )

@app.route("/pricing")
def pricing_page():
    return render_template("pricing.html",
        pricing=load_pricing(),
        flw_key=FLW_PUBLIC_KEY,
        flw_enabled=FLW_ENABLED,
        currencies=SUPPORTED_CURRENCIES
    )

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        subscription = request.form.get("subscription", "Basic")
        email = request.form.get("email", "").strip()

        if not username or not password:
            flash("Username and password are required!", "error")
            return render_template("register.html", pricing=load_pricing(), currencies=SUPPORTED_CURRENCIES)

        if len(username) < 3:
            flash("Username must be at least 3 characters!", "error")
            return render_template("register.html", pricing=load_pricing(), currencies=SUPPORTED_CURRENCIES)

        if password != confirm_password:
            flash("Passwords don't match!", "error")
            return render_template("register.html", pricing=load_pricing(), currencies=SUPPORTED_CURRENCIES)

        if len(password) < 6:
            flash("Password must be at least 6 characters!", "error")
            return render_template("register.html", pricing=load_pricing(), currencies=SUPPORTED_CURRENCIES)

        users = load_users()
        if username in users:
            flash("Username already exists! Please choose another.", "error")
            return render_template("register.html", pricing=load_pricing(), currencies=SUPPORTED_CURRENCIES)

        if username == OWNER_USER:
            flash("This username is reserved!", "error")
            return render_template("register.html", pricing=load_pricing(), currencies=SUPPORTED_CURRENCIES)

        users[username] = {
            "password": generate_password_hash(password),
            "created_at": time.time(),
            "subscription": subscription,
            "token": secrets.token_urlsafe(16),
            "payment_status": "pending",
            "email": email,
        }
        save_users(users)
        user_dir(username)

        flash("Account created successfully! Please subscribe to a plan to start deploying.", "success")
        return redirect(url_for("pricing_page"))

    return render_template("register.html", pricing=load_pricing(), currencies=SUPPORTED_CURRENCIES)

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "")

        if u == OWNER_USER and p == OWNER_PASS:
            session.clear()
            session["role"] = "owner"
            session["username"] = u
            return redirect(url_for("owner_dashboard"))

        users = load_users()
        info = users.get(u)
        if info and check_password_hash(info["password"], p):
            ok, _ = user_valid(u)
            if not ok:
                error = "Account invalid"
            else:
                session.clear()
                session["role"] = "user"
                session["username"] = u
                return redirect(url_for("user_dashboard"))
        else:
            error = "Invalid credentials"
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))

@app.route("/auto/<token>")
def auto_login(token):
    users = load_users()
    for uname, info in users.items():
        if info.get("token") == token:
            ok, _ = user_valid(uname)
            if not ok:
                return "Account invalid", 403
            session.clear()
            session["role"] = "user"
            session["username"] = uname
            return redirect(url_for("user_dashboard"))
    return "Invalid link", 404

# ---------- Flutterwave Payment Routes ----------
@app.route("/initialize-payment", methods=["POST"])
def initialize_payment():
    if not FLW_ENABLED:
        return jsonify({"error": "Flutterwave is not configured. Please set FLW_PUBLIC_KEY, FLW_SECRET_KEY and FLW_ENCRYPTION_KEY."}), 400

    try:
        data = request.json
        username = data.get("username")
        plan_name = data.get("plan_name")
        email = data.get("email")
        currency = data.get("currency", "NGN")

        if not email:
            return jsonify({"error": "Email is required for payment"}), 400

        if currency not in SUPPORTED_CURRENCIES:
            return jsonify({"error": f"Currency {currency} is not supported. Supported: {', '.join(SUPPORTED_CURRENCIES.keys())}"}), 400

        pricing = load_pricing()

        plan = None
        for p in pricing["plans"]:
            if p["name"] == plan_name:
                plan = p
                break

        if not plan:
            return jsonify({"error": "Plan not found"}), 400

        currency_pricing = pricing.get("currency_pricing", {})
        if currency in currency_pricing and plan_name in currency_pricing[currency]:
            amount = currency_pricing[currency][plan_name]
        else:
            amount = plan["price"]

        amount = float(amount)

        tx_ref = f"VPS-{username}-{secrets.token_hex(8)}"

        headers = {
            "Authorization": f"Bearer {FLW_SECRET_KEY}",
            "Content-Type": "application/json"
        }

        if FLW_ENCRYPTION_KEY:
            headers["Encryption-Key"] = FLW_ENCRYPTION_KEY

        payload = {
            "tx_ref": tx_ref,
            "amount": amount,
            "currency": currency,
            "redirect_url": request.host_url + "payment-verify",
            "payment_options": "card,ussd,banktransfer,mobilemoney",
            "customer": {
                "email": email,
                "name": username,
            },
            "customizations": {
                "title": "NCK Dev VPS Subscription",
                "description": f"{plan_name} Plan - {plan['duration']} ({currency})",
            },
            "meta": {
                "username": username,
                "plan": plan_name,
                "currency": currency
            }
        }

        response = requests.post(FLW_INITIALIZE_URL, json=payload, headers=headers)
        result = response.json()

        if result["status"] == "success":
            return jsonify({
                "status": True,
                "link": result["data"]["link"],
                "reference": result["data"]["tx_ref"],
                "amount": amount,
                "currency": currency
            })
        else:
            return jsonify({"error": result.get("message", "Payment initialization failed")}), 400

    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/payment-verify")
def payment_verify():
    tx_ref = request.args.get("tx_ref")

    if not tx_ref:
        flash("No transaction reference found!", "error")
        return redirect(url_for("pricing_page"))

    try:
        headers = {
            "Authorization": f"Bearer {FLW_SECRET_KEY}",
            "Content-Type": "application/json"
        }

        if FLW_ENCRYPTION_KEY:
            headers["Encryption-Key"] = FLW_ENCRYPTION_KEY

        response = requests.get(f"{FLW_VERIFY_URL}{tx_ref}/verify", headers=headers)
        result = response.json()

        if result["status"] == "success" and result["data"]["status"] == "successful":
            metadata = result["data"]["meta"]
            username = metadata.get("username")
            plan = metadata.get("plan")
            currency = metadata.get("currency", "NGN")

            users = load_users()
            if username in users:
                users[username]["payment_status"] = "paid"
                users[username]["subscription"] = plan
                users[username]["payment_reference"] = tx_ref
                users[username]["payment_amount"] = result["data"]["amount"]
                users[username]["payment_currency"] = currency
                save_users(users)
                flash(f"Payment successful! Your {plan} subscription is now active. 🎉", "success")
            else:
                flash("User not found!", "error")
        else:
            flash("Payment verification failed. Please contact support.", "error")

    except Exception as e:
        flash(f"Error verifying payment: {str(e)}", "error")

    return redirect(url_for("login"))

@app.route("/payment-cancel")
def payment_cancel():
    flash("Payment cancelled. You can try again anytime.", "error")
    return redirect(url_for("pricing_page"))

# ---------- GitHub Backup Routes ----------
@app.route("/admin/backup", methods=["POST"])
@require_owner
def admin_backup():
    def do_backup():
        success = manual_backup("Manual backup triggered by admin")
        if success:
            flash("Backup completed successfully!", "success")
        else:
            flash("Backup skipped (no data or not enabled)", "warning")

    threading.Thread(target=do_backup, daemon=True).start()
    flash("Backup started in background!", "success")
    return redirect(url_for("owner_dashboard"))

@app.route("/admin/backup-status")
@require_owner
def admin_backup_status():
    status = get_backup_status()
    status['has_data'] = has_data()
    return jsonify(status)

@app.route("/admin/restore", methods=["POST"])
@require_owner
def admin_restore():
    if not github_backup.is_enabled:
        flash("GitHub backup not configured!", "error")
        return redirect(url_for("owner_dashboard"))

    success = force_restore()
    if success:
        flash("Restore successful! Data reloaded from GitHub.", "success")
    else:
        flash("Restore failed. No backup found.", "error")
    return redirect(url_for("owner_dashboard"))

@app.route("/admin/force-restore", methods=["POST"])
@require_owner
def admin_force_restore():
    if not github_backup.is_enabled:
        flash("GitHub backup not configured!", "error")
        return redirect(url_for("owner_dashboard"))

    manual_backup("Pre-restore backup")
    success = force_restore()
    if success:
        flash("Force restore successful!", "success")
    else:
        flash("Force restore failed.", "error")
    return redirect(url_for("owner_dashboard"))

# ---------- owner routes ----------
@app.route("/owner")
@require_owner
def owner_dashboard():
    users = load_users()
    now = time.time()
    base = request.host_url.rstrip("/")
    backup_info = get_backup_status()

    return render_template("owner.html",
        users=users,
        now=now,
        base_url=base,
        pricing=load_pricing(),
        currencies=SUPPORTED_CURRENCIES,
        backup_info=backup_info
    )

@app.route("/owner/create", methods=["POST"])
@require_owner
def owner_create():
    u = request.form.get("username", "").strip()
    p = request.form.get("password", "").strip()
    subscription = request.form.get("subscription", "Basic")
    email = request.form.get("email", "").strip()

    if not u or not p:
        return redirect(url_for("owner_dashboard"))
    if u == OWNER_USER:
        return redirect(url_for("owner_dashboard"))

    users = load_users()
    if u in users:
        flash("User already exists!", "error")
        return redirect(url_for("owner_dashboard"))

    users[u] = {
        "password": generate_password_hash(p),
        "created_at": time.time(),
        "subscription": subscription,
        "token": secrets.token_urlsafe(16),
        "payment_status": "paid",
        "email": email,
    }
    save_users(users)
    user_dir(u)
    flash(f"User {u} created successfully!", "success")
    return redirect(url_for("owner_dashboard"))

@app.route("/owner/delete/<username>", methods=["POST"])
@require_owner
def owner_delete(username):
    users = load_users()
    if username in users:
        stop_process(username)
        del users[username]
        save_users(users)
        d = FILES_ROOT / username
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
        flash(f"User {username} deleted!", "success")
    return redirect(url_for("owner_dashboard"))

@app.route("/owner/update_subscription/<username>", methods=["POST"])
@require_owner
def owner_update_subscription(username):
    subscription = request.form.get("subscription", "Basic")
    users = load_users()
    if username in users:
        users[username]["subscription"] = subscription
        users[username]["payment_status"] = "paid"
        save_users(users)
        flash(f"Subscription updated for {username}!", "success")
    return redirect(url_for("owner_dashboard"))

@app.route("/owner/pricing", methods=["POST"])
@require_owner
def owner_pricing():
    pricing = load_pricing()
    pricing["currency"] = request.form.get("currency", "NGN").strip() or "NGN"
    pricing["contact"] = request.form.get("contact", "").strip()
    plans = []
    names = request.form.getlist("p_name")
    durs = request.form.getlist("p_duration")
    prices = request.form.getlist("p_price")
    feats = request.form.getlist("p_features")

    for i in range(len(names)):
        if not names[i].strip():
            continue
        plans.append({
            "name": names[i].strip(),
            "duration": durs[i].strip() if i < len(durs) else "",
            "price": prices[i].strip() if i < len(prices) else "0",
            "features": feats[i].strip() if i < len(feats) else "",
        })
    pricing["plans"] = plans
    save_pricing(pricing)
    flash("Pricing updated!", "success")
    return redirect(url_for("owner_dashboard") + "#pricing")

# ---------- user dashboard ----------
@app.route("/dashboard")
@require_user
def user_dashboard():
    u = current_user()
    users = load_users()
    info = users.get(u, {})
    udir = user_dir(u)
    files = sorted([f.name for f in udir.iterdir() if f.is_file()])

    is_paid = info.get("payment_status") == "paid"

    return render_template("user.html",
        username=u, info=info, files=files,
        running=is_running(u),
        running_file=(PROCS.get(u, {}).get("file") if is_running(u) else None),
        subscription=info.get("subscription", "Basic"),
        is_paid=is_paid,
        email=info.get("email", ""),
    )

@app.route("/upload", methods=["POST"])
@require_user
def upload():
    u = current_user()
    users = load_users()
    if users.get(u, {}).get("payment_status") != "paid":
        flash("Please subscribe to a plan to upload files!", "error")
        return redirect(url_for("pricing_page"))

    udir = user_dir(u)
    files = request.files.getlist("files")
    for f in files:
        if not f or not f.filename:
            continue
        name = secure_filename(f.filename)
        if not name:
            continue
        f.save(udir / name)
    flash("Files uploaded successfully!", "success")
    threading.Thread(target=lambda: manual_backup("File upload"), daemon=True).start()
    return redirect(url_for("user_dashboard"))

@app.route("/file/delete/<name>", methods=["POST"])
@require_user
def file_delete(name):
    u = current_user()
    name = secure_filename(name)
    p = user_dir(u) / name
    if p.exists() and p.is_file():
        p.unlink()
        flash(f"File {name} deleted!", "success")
        threading.Thread(target=lambda: manual_backup("File deleted"), daemon=True).start()
    return redirect(url_for("user_dashboard"))

@app.route("/file/view/<name>")
@require_user
def file_view(name):
    u = current_user()
    name = secure_filename(name)
    return send_from_directory(user_dir(u), name, as_attachment=False)

@app.route("/server/start", methods=["POST"])
@require_user
def server_start():
    u = current_user()
    fname = secure_filename(request.form.get("file", ""))
    ok, msg = start_process(u, fname)
    return jsonify({"ok": ok, "msg": msg})

@app.route("/server/stop", methods=["POST"])
@require_user
def server_stop():
    u = current_user()
    stop_process(u)
    return jsonify({"ok": True})

@app.route("/server/restart", methods=["POST"])
@require_user
def server_restart():
    u = current_user()
    info = PROCS.get(u)
    fname = info["file"] if info else secure_filename(request.form.get("file", ""))
    if not fname:
        return jsonify({"ok": False, "msg": "no file"})
    stop_process(u)
    time.sleep(0.3)
    ok, msg = start_process(u, fname)
    return jsonify({"ok": ok, "msg": msg})

@app.route("/server/delete", methods=["POST"])
@require_user
def server_delete():
    u = current_user()
    stop_process(u)
    PROCS.pop(u, None)
    return jsonify({"ok": True})

@app.route("/logs")
@require_user
def logs_api():
    u = current_user()
    return jsonify({
        "running": is_running(u),
        "file": PROCS.get(u, {}).get("file"),
        "logs": get_logs(u),
        "install": list(INSTALL_LOGS.get(u, [])),
        "subscription": PROCS.get(u, {}).get("subscription", "Basic"),
    })

@app.route("/install", methods=["POST"])
@require_user
def install():
    u = current_user()
    cmd = request.form.get("command", "").strip()
    ok, msg = run_install(u, cmd)
    return jsonify({"ok": ok, "msg": msg})

@app.route("/healthz")
def health():
    return "ok", 200

@app.route("/debug")
def debug():
    return jsonify({
        "status": "running",
        "service": "NCK Dev VPS",
        "env_vars": {
            "SECRET_KEY": "set" if os.environ.get("SECRET_KEY") else "missing",
            "FLW_PUBLIC_KEY": "set" if os.environ.get("FLW_PUBLIC_KEY") else "missing",
            "FLW_SECRET_KEY": "set" if os.environ.get("FLW_SECRET_KEY") else "missing",
            "FLW_ENCRYPTION_KEY": "set" if os.environ.get("FLW_ENCRYPTION_KEY") else "missing",
            "GITHUB_TOKEN": "set" if os.environ.get("GITHUB_TOKEN") else "missing",
            "GITHUB_REPO_OWNER": os.environ.get("GITHUB_REPO_OWNER"),
            "GITHUB_REPO_NAME": os.environ.get("GITHUB_REPO_NAME"),
        },
        "github_backup_enabled": github_backup.is_enabled if github_backup else False
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)