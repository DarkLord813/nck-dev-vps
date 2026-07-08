import os, json, time, uuid, shutil, subprocess, threading, signal, secrets
import requests
import base64
import hashlib
import re
import zipfile
import tarfile
import socket
import psutil
from collections import deque
from pathlib import Path
from functools import wraps
from datetime import datetime, timedelta
from flask import (
    Flask, request, redirect, url_for, session,
    render_template, jsonify, Response, send_from_directory, abort, flash
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import ipaddress
import hmac

# Optional SSL (if installed)
try:
    import OpenSSL
    from OpenSSL import crypto
    OPENSSL_AVAILABLE = True
except ImportError:
    OpenSSL = None
    crypto = None
    OPENSSL_AVAILABLE = False
    print("⚠️ pyOpenSSL not installed - SSL certificate generation disabled")

APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"
USERS_FILE = DATA_DIR / "users.json"
PRICING_FILE = DATA_DIR / "pricing.json"
PROJECTS_FILE = DATA_DIR / "projects.json"
FILES_ROOT = APP_DIR / "user_files"
DATA_DIR.mkdir(exist_ok=True)
FILES_ROOT.mkdir(exist_ok=True)

# Owner credentials
OWNER_USER = "DarkLord813"
OWNER_PASS = "DarkLord813"

# Flutterwave Configuration
FLW_PUBLIC_KEY = os.environ.get("FLW_PUBLIC_KEY", "")
FLW_SECRET_KEY = os.environ.get("FLW_SECRET_KEY", "")
FLW_ENCRYPTION_KEY = os.environ.get("FLW_ENCRYPTION_KEY", "")
FLW_ENABLED = bool(FLW_PUBLIC_KEY and FLW_SECRET_KEY and FLW_ENCRYPTION_KEY)

# Flutterwave API endpoints
FLW_INITIALIZE_URL = "https://api.flutterwave.com/v3/payments"
FLW_VERIFY_URL = "https://api.flutterwave.com/v3/transactions/"

# Supported currencies
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
            "features": "1 project, 1GB RAM, 5GB storage, Basic support"
        },
        {
            "name": "Pro",
            "duration": "Yearly",
            "price": "15000",
            "features": "5 projects, 2GB RAM, 20GB storage, Priority support, Custom domains"
        },
        {
            "name": "Premium",
            "duration": "Yearly",
            "price": "25000",
            "features": "20 projects, 4GB RAM, 50GB storage, Dedicated help, SSL, Docker, Database"
        },
    ],
    "currency_pricing": {
        "NGN": {"Basic": "2500", "Pro": "15000", "Premium": "25000"},
        "USD": {"Basic": "3.00", "Pro": "18.00", "Premium": "30.00"},
        "EUR": {"Basic": "2.80", "Pro": "16.50", "Premium": "28.00"},
        "GBP": {"Basic": "2.40", "Pro": "14.50", "Premium": "24.00"},
    }
}

# Create default files
if not USERS_FILE.exists():
    USERS_FILE.write_text("{}")
if not PRICING_FILE.exists():
    PRICING_FILE.write_text(json.dumps(DEFAULT_PRICING, indent=2))
if not PROJECTS_FILE.exists():
    PROJECTS_FILE.write_text("{}")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500MB

# ==================== GITHUB BACKUP SYSTEM ====================
class GitHubBackupSystem:
    def __init__(self, data_dir, files_root):
        self.data_dir = data_dir
        self.files_root = files_root
        self.token = os.environ.get("GITHUB_TOKEN", "")
        self.repo_owner = "DarkLord813"
        self.repo_name = os.environ.get("GITHUB_REPO_NAME", "")
        self.branch = os.environ.get("GITHUB_BACKUP_BRANCH", "main")
        self.backup_path = os.environ.get("GITHUB_BACKUP_PATH", "backups/database.json")
        self.is_enabled = bool(self.token and self.repo_owner and self.repo_name)
        self._session = requests.Session()
        self._backup_count = 0
        self._last_backup_time = 0
        self._last_error = None
    
    @property
    def _headers(self):
        return {'Authorization': f'token {self.token}', 'Accept': 'application/vnd.github.v3+json'}
    
    def _get_api_url(self):
        return f"https://api.github.com/repos/{self.repo_owner}/{self.repo_name}/contents/{self.backup_path}"
    
    def _has_data(self):
        users_file = self.data_dir / "users.json"
        pricing_file = self.data_dir / "pricing.json"
        projects_file = self.data_dir / "projects.json"
        return users_file.exists() or pricing_file.exists() or projects_file.exists()
    
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
        try:
            if not self.is_enabled:
                return False
            
            print(f"📤 Creating backup: {reason}")
            
            users_data = {}
            pricing_data = {}
            projects_data = {}
            
            if USERS_FILE.exists():
                try:
                    with open(USERS_FILE, 'r') as f:
                        users_data = json.load(f)
                except:
                    pass
            
            if PRICING_FILE.exists():
                try:
                    with open(PRICING_FILE, 'r') as f:
                        pricing_data = json.load(f)
                except:
                    pass
            
            if PROJECTS_FILE.exists():
                try:
                    with open(PROJECTS_FILE, 'r') as f:
                        projects_data = json.load(f)
                except:
                    pass
            
            backup_data = {
                "timestamp": datetime.now().isoformat(),
                "version": "1.0",
                "users": users_data,
                "pricing": pricing_data,
                "projects": projects_data,
                "stats": {
                    "users_count": len(users_data),
                    "projects_count": sum(len(p) for p in projects_data.values()) if projects_data else 0,
                    "pricing_plans": len(pricing_data.get("plans", [])) if pricing_data else 0
                }
            }
            
            json_str = json.dumps(backup_data, indent=2)
            encoded = base64.b64encode(json_str.encode()).decode()
            
            api_url = self._get_api_url()
            r = self._session.get(api_url, headers=self._headers)
            file_sha = r.json().get('sha') if r.status_code == 200 else None
            
            payload = {
                'message': f"{reason} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Users: {len(users_data)}",
                'content': encoded,
                'branch': self.branch
            }
            if file_sha:
                payload['sha'] = file_sha
            
            r = self._session.put(api_url, headers=self._headers, json=payload, timeout=60)
            
            if r.status_code in (200, 201):
                self._backup_count += 1
                self._last_backup_time = time.time()
                self._last_error = None
                print(f"✅ Backup successful (#{self._backup_count})")
                return True
            else:
                self._last_error = f"Backup failed: {r.status_code}"
                print(f"❌ {self._last_error}")
                return False
                
        except Exception as e:
            self._last_error = f"Backup error: {str(e)}"
            print(f"❌ {self._last_error}")
            return False
    
    def restore(self):
        if not self.is_enabled:
            return False
        
        try:
            print("📥 Restoring from GitHub...")
            api_url = self._get_api_url()
            r = self._session.get(api_url, headers=self._headers, timeout=60)
            
            if r.status_code != 200:
                print(f"❌ No backup found: {r.status_code}")
                return False
            
            content = r.json().get('content', '')
            if not content:
                return False
            
            json_str = base64.b64decode(content.replace('\n', '')).decode()
            data = json.loads(json_str)
            
            if "users" in data:
                with open(USERS_FILE, 'w') as f:
                    json.dump(data["users"], f, indent=2)
                print(f"✅ Restored {len(data['users'])} users")
            
            if "pricing" in data:
                with open(PRICING_FILE, 'w') as f:
                    json.dump(data["pricing"], f, indent=2)
                print("✅ Restored pricing data")
            
            if "projects" in data:
                with open(PROJECTS_FILE, 'w') as f:
                    json.dump(data["projects"], f, indent=2)
                print(f"✅ Restored projects data")
            
            return True
            
        except Exception as e:
            print(f"❌ Restore error: {e}")
            return False
    
    def get_status(self):
        return {
            "enabled": self.is_enabled,
            "backup_count": self._backup_count,
            "repo_owner": self.repo_owner,
            "repo_name": self.repo_name,
            "users": self._get_users_count(),
            "last_backup_time": self._last_backup_time,
            "last_error": self._last_error
        }

# Initialize backup system
github_backup = GitHubBackupSystem(DATA_DIR, FILES_ROOT)

if github_backup.is_enabled:
    print("🔄 Attempting to restore from GitHub...")
    github_backup.restore()
    print("📤 Creating initial backup...")
    github_backup.backup("Initial backup on startup")
    print("🛡️ Auto-backup thread started (every 60 seconds)")
    
    def auto_backup_loop():
        while True:
            time.sleep(60)
            if github_backup and github_backup.is_enabled:
                github_backup.backup("Auto backup (scheduled)")
    
    threading.Thread(target=auto_backup_loop, daemon=True).start()

def manual_backup(reason="Manual backup"):
    if github_backup:
        return github_backup.backup(reason)
    return False

def get_backup_status():
    if github_backup:
        return github_backup.get_status()
    return {"enabled": False}

# ==================== PORT MANAGEMENT ====================
class PortManager:
    def __init__(self):
        self.used_ports = {}
        self.port_range_start = 5000
        self.port_range_end = 5020
        self._lock = threading.Lock()
    
    def get_available_port(self, username, project_id):
        with self._lock:
            key = f"{username}:{project_id}"
            if key in self.used_ports:
                return self.used_ports[key]
            for port in range(self.port_range_start, self.port_range_end):
                if self.is_port_available(port):
                    self.used_ports[key] = port
                    return port
            return None
    
    def is_port_available(self, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(('0.0.0.0', port))
            sock.close()
            return True
        except:
            return False
    
    def release_port(self, username, project_id):
        key = f"{username}:{project_id}"
        if key in self.used_ports:
            del self.used_ports[key]
            return True
        return False

port_manager = PortManager()

# ==================== STORAGE ====================
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

def load_projects():
    if not PROJECTS_FILE.exists():
        return {}
    try:
        return json.loads(PROJECTS_FILE.read_text())
    except Exception:
        return {}

def save_projects(projects):
    with _lock:
        PROJECTS_FILE.write_text(json.dumps(projects, indent=2))

# ==================== AUTH ====================
def is_owner():
    return session.get("role") == "owner"

def current_user():
    return session.get("username")

def user_valid(username):
    users = load_users()
    u = users.get(username)
    if not u:
        return False, "User not found"
    if u.get("banned", False):
        return False, "User is banned"
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

# ==================== PROJECT FUNCTIONS ====================
def get_user_projects(username):
    projects = load_projects()
    return projects.get(username, {})

def get_project(username, project_id):
    projects = load_projects()
    return projects.get(username, {}).get(project_id)

def create_project(username, project_name, description=""):
    projects = load_projects()
    if username not in projects:
        projects[username] = {}
    project_id = secrets.token_hex(8)
    
    port = port_manager.get_available_port(username, project_id)
    
    projects[username][project_id] = {
        "id": project_id,
        "name": project_name,
        "description": description,
        "created_at": time.time(),
        "updated_at": time.time(),
        "files": [],
        "env_vars": {},
        "run_command": "",
        "requirements": "",
        "is_running": False,
        "pid": None,
        "port": port,
        "custom_domain": "",
        "has_ssl": False,
        "has_docker": False,
        "has_database": False,
        "database_type": None,
        "worker_command": "",
        "worker_running": False,
        "restart_on_crash": False,
        "crash_count": 0,
        "last_crash_time": None
    }
    save_projects(projects)
    
    project_dir = FILES_ROOT / username / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    
    return project_id

def delete_project(username, project_id):
    projects = load_projects()
    if username in projects and project_id in projects[username]:
        stop_project_process(username, project_id)
        port_manager.release_port(username, project_id)
        project_dir = FILES_ROOT / username / project_id
        if project_dir.exists():
            shutil.rmtree(project_dir, ignore_errors=True)
        del projects[username][project_id]
        save_projects(projects)
        return True
    return False

# ==================== PROJECT PROCESS MANAGEMENT ====================
PROJECT_PROCS = {}

def start_project_process(username, project_id):
    stop_project_process(username, project_id)
    project = get_project(username, project_id)
    if not project:
        return False, "Project not found"
    project_dir = FILES_ROOT / username / project_id
    run_command = project.get("run_command", "")
    if not run_command:
        return False, "No run command set"
    try:
        env = os.environ.copy()
        for key, value in project.get("env_vars", {}).items():
            env[key] = value
        
        if project.get("port"):
            env["PORT"] = str(project["port"])
        
        proc = subprocess.Popen(
            run_command.split(),
            cwd=str(project_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            env=env
        )
        project_key = f"{username}:{project_id}"
        PROJECT_PROCS[project_key] = {
            "proc": proc,
            "logs": deque(maxlen=5000),
            "project_id": project_id,
            "username": username,
            "started": time.time()
        }
        projects = load_projects()
        if username in projects and project_id in projects[username]:
            projects[username][project_id]["is_running"] = True
            projects[username][project_id]["pid"] = proc.pid
            save_projects(projects)
        
        t = threading.Thread(target=_read_project_logs, args=(username, project_id, proc), daemon=True)
        t.start()
        PROJECT_PROCS[project_key]["thread"] = t
        return True, f"Project started on port {project.get('port', 'N/A')}"
    except Exception as e:
        return False, f"Error starting project: {str(e)}"

def stop_project_process(username, project_id):
    project_key = f"{username}:{project_id}"
    if project_key in PROJECT_PROCS:
        proc = PROJECT_PROCS[project_key]["proc"]
        if proc.poll() is None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            except:
                pass
        del PROJECT_PROCS[project_key]
    projects = load_projects()
    if username in projects and project_id in projects[username]:
        projects[username][project_id]["is_running"] = False
        projects[username][project_id]["pid"] = None
        save_projects(projects)
    return True

def _read_project_logs(username, project_id, proc):
    project_key = f"{username}:{project_id}"
    if project_key not in PROJECT_PROCS:
        return
    buf = PROJECT_PROCS[project_key]["logs"]
    try:
        for line in iter(proc.stdout.readline, b""):
            try:
                txt = line.decode("utf-8", errors="replace").rstrip()
            except:
                txt = str(line)
            buf.append(f"[{time.strftime('%H:%M:%S')}] {txt}")
    except Exception as e:
        buf.append(f"[error] {e}")
    finally:
        exit_code = proc.poll()
        if exit_code is not None and exit_code != 0:
            buf.append(f"[crash] Process exited with code {exit_code}")
            projects = load_projects()
            if username in projects and project_id in projects[username]:
                if projects[username][project_id].get("restart_on_crash", False):
                    crash_count = projects[username][project_id].get("crash_count", 0) + 1
                    projects[username][project_id]["crash_count"] = crash_count
                    projects[username][project_id]["last_crash_time"] = time.time()
                    save_projects(projects)
                    
                    if crash_count < 5:
                        print(f"🔄 Auto-restarting project {project_id} (crash #{crash_count})")
                        time.sleep(2)
                        start_project_process(username, project_id)
                    else:
                        print(f"❌ Project {project_id} crashed too many times")
        else:
            buf.append(f"[exit] process ended with code {exit_code}")
        
        projects = load_projects()
        if username in projects and project_id in projects[username]:
            projects[username][project_id]["is_running"] = False
            projects[username][project_id]["pid"] = None
            save_projects(projects)

def get_project_logs(username, project_id, limit=500):
    project_key = f"{username}:{project_id}"
    if project_key not in PROJECT_PROCS:
        return []
    return list(PROJECT_PROCS[project_key]["logs"])[-limit:]

def is_project_running(username, project_id):
    project_key = f"{username}:{project_id}"
    if project_key in PROJECT_PROCS:
        return PROJECT_PROCS[project_key]["proc"].poll() is None
    return False

def get_project_resources(username, project_id):
    project_key = f"{username}:{project_id}"
    if project_key not in PROJECT_PROCS:
        return {"cpu": 0, "ram": 0, "ram_mb": 0}
    
    proc = PROJECT_PROCS[project_key]["proc"]
    try:
        p = psutil.Process(proc.pid)
        cpu = p.cpu_percent(interval=0.1)
        memory = p.memory_info()
        return {
            "cpu": round(cpu, 1),
            "ram": memory.rss,
            "ram_mb": round(memory.rss / (1024 * 1024), 1)
        }
    except:
        return {"cpu": 0, "ram": 0, "ram_mb": 0}

# ==================== ROUTES ====================

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
    users = load_users()
    return render_template("pricing.html",
        pricing=load_pricing(),
        flw_key=FLW_PUBLIC_KEY,
        flw_enabled=FLW_ENABLED,
        currencies=SUPPORTED_CURRENCIES,
        users=users
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

        if not email:
            flash("Email is required for payment!", "error")
            return render_template("register.html", pricing=load_pricing(), currencies=SUPPORTED_CURRENCIES)

        users = load_users()
        if username in users:
            flash("Username already exists!", "error")
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
            "banned": False,
        }
        save_users(users)
        user_dir(username)

        flash("Account created successfully!", "success")
        return redirect(url_for("pricing_page"))

    return render_template("register.html", pricing=load_pricing(), currencies=SUPPORTED_CURRENCIES)

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "")
        
        users = load_users()
        if u in users and users[u].get("banned", False):
            error = "❌ Your account has been banned."
            return render_template("login.html", error=error)
        
        if u == OWNER_USER and p == OWNER_PASS:
            session.clear()
            session["role"] = "owner"
            session["username"] = u
            return redirect(url_for("owner_dashboard"))
        
        info = users.get(u)
        if info and check_password_hash(info["password"], p):
            if info.get("banned", False):
                error = "❌ Your account has been banned."
                return render_template("login.html", error=error)
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
            if info.get("banned", False):
                return "Account is banned", 403
            session.clear()
            session["role"] = "user"
            session["username"] = uname
            return redirect(url_for("user_dashboard"))
    return "Invalid link", 404

# ==================== FLUTTERWAVE PAYMENT ROUTES ====================

@app.route("/initialize-payment", methods=["POST"])
def initialize_payment():
    if not FLW_ENABLED:
        return jsonify({"error": "Flutterwave is not configured."}), 400
    
    try:
        data = request.json
        username = data.get("username")
        plan_name = data.get("plan_name")
        email = data.get("email")
        currency = data.get("currency", "NGN")
        
        print(f"💰 Payment request: username={username}, plan={plan_name}, email={email}, currency={currency}")
        
        if not email:
            users = load_users()
            user_data = users.get(username, {})
            email = user_data.get("email", "")
            if not email:
                return jsonify({"error": "Email is required for payment."}), 400
        
        if currency not in SUPPORTED_CURRENCIES:
            return jsonify({"error": f"Currency {currency} is not supported."}), 400
        
        pricing = load_pricing()
        
        plan = None
        for p in pricing["plans"]:
            if p["name"].lower() == plan_name.lower():
                plan = p
                break
        
        if not plan:
            return jsonify({"error": f"Plan '{plan_name}' not found"}), 400
        
        currency_pricing = pricing.get("currency_pricing", {})
        if currency in currency_pricing and plan_name in currency_pricing[currency]:
            amount = float(currency_pricing[currency][plan_name])
        else:
            amount = float(plan["price"])
        
        tx_ref = f"VPS-{username}-{int(time.time())}-{secrets.token_hex(4)}"
        
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
            "redirect_url": request.host_url.rstrip('/') + "/payment-verify",
            "payment_options": "card,ussd,banktransfer,mobilemoney",
            "customer": {"email": email, "name": username},
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
        
        print(f"💰 Sending to Flutterwave: {payload}")
        
        response = requests.post(FLW_INITIALIZE_URL, json=payload, headers=headers, timeout=30)
        result = response.json()
        
        print(f"💰 Flutterwave response: {result}")
        
        if result.get("status") == "success":
            return jsonify({
                "status": True,
                "link": result["data"]["link"],
                "reference": result["data"]["tx_ref"],
                "amount": amount,
                "currency": currency
            })
        else:
            error_msg = result.get("message", "Payment initialization failed")
            print(f"❌ Flutterwave error: {error_msg}")
            return jsonify({"error": error_msg}), 400
            
    except Exception as e:
        print(f"❌ Payment error: {e}")
        return jsonify({"error": str(e)}), 400

@app.route("/payment-verify")
def payment_verify():
    tx_ref = request.args.get("tx_ref")
    if not tx_ref:
        flash("No transaction reference found!", "error")
        return redirect(url_for("pricing_page"))
    
    try:
        headers = {"Authorization": f"Bearer {FLW_SECRET_KEY}", "Content-Type": "application/json"}
        if FLW_ENCRYPTION_KEY:
            headers["Encryption-Key"] = FLW_ENCRYPTION_KEY
        
        response = requests.get(f"{FLW_VERIFY_URL}{tx_ref}/verify", headers=headers)
        result = response.json()
        
        if result.get("status") == "success" and result.get("data", {}).get("status") == "successful":
            metadata = result["data"].get("meta", {})
            username = metadata.get("username")
            plan = metadata.get("plan")
            currency = metadata.get("currency", "NGN")
            
            users = load_users()
            if username in users:
                users[username]["payment_status"] = "paid"
                users[username]["subscription"] = plan
                users[username]["payment_reference"] = tx_ref
                users[username]["payment_amount"] = result["data"].get("amount")
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

# ==================== PROJECT ROUTES ====================

@app.route("/projects")
@require_user
def projects_list():
    u = current_user()
    projects = get_user_projects(u)
    for pid, project in projects.items():
        project["is_running"] = is_project_running(u, pid)
        resources = get_project_resources(u, pid)
        project["cpu"] = resources["cpu"]
        project["ram_mb"] = resources["ram_mb"]
    return render_template("projects.html", username=u, projects=projects, total_projects=len(projects))

@app.route("/project/create", methods=["POST"])
@require_user
def project_create():
    u = current_user()
    users = load_users()
    if users.get(u, {}).get("payment_status") != "paid":
        flash("Please subscribe to a plan!", "error")
        return redirect(url_for("projects_list"))
    
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    if not name:
        flash("Project name is required!", "error")
        return redirect(url_for("projects_list"))
    
    project_id = create_project(u, name, description)
    flash(f"Project '{name}' created!", "success")
    return redirect(url_for("project_detail", project_id=project_id))

@app.route("/project/<project_id>")
@require_user
def project_detail(project_id):
    u = current_user()
    project = get_project(u, project_id)
    if not project:
        flash("Project not found!", "error")
        return redirect(url_for("projects_list"))
    
    project_dir = FILES_ROOT / u / project_id
    files = []
    if project_dir.exists():
        files = sorted([f.name for f in project_dir.iterdir() if f.is_file()])
    
    project["files"] = files
    project["is_running"] = is_project_running(u, project_id)
    project["logs"] = get_project_logs(u, project_id, 100)
    resources = get_project_resources(u, project_id)
    project["cpu"] = resources["cpu"]
    project["ram_mb"] = resources["ram_mb"]
    
    return render_template("project_detail.html", username=u, project=project, files=files)

@app.route("/project/<project_id>/upload", methods=["POST"])
@require_user
def project_upload(project_id):
    u = current_user()
    users = load_users()
    if users.get(u, {}).get("payment_status") != "paid":
        flash("Please subscribe to a plan!", "error")
        return redirect(url_for("project_detail", project_id=project_id))
    
    project = get_project(u, project_id)
    if not project:
        flash("Project not found!", "error")
        return redirect(url_for("projects_list"))
    
    project_dir = FILES_ROOT / u / project_id
    files = request.files.getlist("files")
    
    for file in files:
        if not file or not file.filename:
            continue
        name = secure_filename(file.filename)
        if not name:
            continue
        
        # Check if it's a zip/tar file
        if name.endswith('.zip') or name.endswith('.tar.gz') or name.endswith('.tgz') or name.endswith('.tar'):
            file_path = project_dir / name
            file.save(file_path)
            
            try:
                if name.endswith('.zip'):
                    with zipfile.ZipFile(file_path, 'r') as zip_ref:
                        zip_ref.extractall(project_dir)
                else:
                    if name.endswith('.tar.gz') or name.endswith('.tgz'):
                        with tarfile.open(file_path, 'r:gz') as tar_ref:
                            tar_ref.extractall(project_dir)
                    else:
                        with tarfile.open(file_path, 'r') as tar_ref:
                            tar_ref.extractall(project_dir)
                os.remove(file_path)
                flash(f"📦 Extracted {name}!", "success")
            except Exception as e:
                flash(f"❌ Failed to extract {name}: {str(e)}", "error")
        else:
            file.save(project_dir / name)
            flash(f"📄 Uploaded {name}", "success")
    
    # Update project files list
    projects = load_projects()
    if u in projects and project_id in projects[u]:
        projects[u][project_id]["files"] = sorted([f.name for f in project_dir.iterdir() if f.is_file()])
        projects[u][project_id]["updated_at"] = time.time()
        save_projects(projects)
    
    return redirect(url_for("project_detail", project_id=project_id))

@app.route("/project/<project_id>/file/delete/<filename>", methods=["POST"])
@require_user
def project_file_delete(project_id, filename):
    u = current_user()
    project = get_project(u, project_id)
    if not project:
        flash("Project not found!", "error")
        return redirect(url_for("projects_list"))
    
    project_dir = FILES_ROOT / u / project_id
    filepath = project_dir / filename
    if filepath.exists() and filepath.is_file():
        filepath.unlink()
        flash(f"File '{filename}' deleted!", "success")
        
        projects = load_projects()
        if u in projects and project_id in projects[u]:
            projects[u][project_id]["files"] = sorted([f.name for f in project_dir.iterdir() if f.is_file()])
            save_projects(projects)
    else:
        flash("File not found!", "error")
    return redirect(url_for("project_detail", project_id=project_id))

@app.route("/project/<project_id>/save-run-command", methods=["POST"])
@require_user
def project_save_run_command(project_id):
    u = current_user()
    project = get_project(u, project_id)
    if not project:
        flash("Project not found!", "error")
        return redirect(url_for("projects_list"))
    
    run_command = request.form.get("run_command", "").strip()
    if not run_command:
        flash("Run command is required!", "error")
        return redirect(url_for("project_detail", project_id=project_id))
    
    projects = load_projects()
    if u in projects and project_id in projects[u]:
        projects[u][project_id]["run_command"] = run_command
        projects[u][project_id]["updated_at"] = time.time()
        save_projects(projects)
        flash("Run command saved!", "success")
    return redirect(url_for("project_detail", project_id=project_id))

@app.route("/project/<project_id>/start", methods=["POST"])
@require_user
def project_start(project_id):
    u = current_user()
    project = get_project(u, project_id)
    if not project:
        return jsonify({"success": False, "error": "Project not found"}), 404
    
    if is_project_running(u, project_id):
        return jsonify({"success": False, "error": "Project is already running"}), 400
    
    success, msg = start_project_process(u, project_id)
    if success:
        threading.Thread(target=lambda: manual_backup(f"Project started: {project['name']}"), daemon=True).start()
        return jsonify({"success": True, "message": msg, "port": project.get("port")})
    return jsonify({"success": False, "error": msg}), 400

@app.route("/project/<project_id>/stop", methods=["POST"])
@require_user
def project_stop(project_id):
    u = current_user()
    project = get_project(u, project_id)
    if not project:
        return jsonify({"success": False, "error": "Project not found"}), 404
    
    if not is_project_running(u, project_id):
        return jsonify({"success": True, "message": "Project is already stopped"})
    
    stop_project_process(u, project_id)
    return jsonify({"success": True, "message": "Project stopped"})

@app.route("/project/<project_id>/toggle-restart", methods=["POST"])
@require_user
def project_toggle_restart(project_id):
    u = current_user()
    project = get_project(u, project_id)
    if not project:
        flash("Project not found!", "error")
        return redirect(url_for("projects_list"))
    
    projects = load_projects()
    if u in projects and project_id in projects[u]:
        current = projects[u][project_id].get("restart_on_crash", False)
        projects[u][project_id]["restart_on_crash"] = not current
        projects[u][project_id]["crash_count"] = 0
        save_projects(projects)
        flash(f"Auto-restart {'enabled' if not current else 'disabled'}", "success")
    return redirect(url_for("project_detail", project_id=project_id))

@app.route("/project/<project_id>/custom-domain", methods=["POST"])
@require_user
def project_custom_domain(project_id):
    u = current_user()
    project = get_project(u, project_id)
    if not project:
        flash("Project not found!", "error")
        return redirect(url_for("projects_list"))
    
    domain = request.form.get("domain", "").strip()
    projects = load_projects()
    if u in projects and project_id in projects[u]:
        projects[u][project_id]["custom_domain"] = domain
        save_projects(projects)
        flash(f"Custom domain set to {domain}", "success")
    return redirect(url_for("project_detail", project_id=project_id))

@app.route("/project/<project_id>/enable-ssl", methods=["POST"])
@require_user
def project_enable_ssl(project_id):
    u = current_user()
    project = get_project(u, project_id)
    if not project:
        flash("Project not found!", "error")
        return redirect(url_for("projects_list"))
    
    if not OPENSSL_AVAILABLE:
        flash("❌ SSL not available - pyOpenSSL not installed", "error")
        return redirect(url_for("project_detail", project_id=project_id))
    
    domain = project.get("custom_domain", "")
    if not domain:
        flash("Please set a custom domain first!", "error")
        return redirect(url_for("project_detail", project_id=project_id))
    
    cert_dir = FILES_ROOT / u / project_id / "ssl"
    cert_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        k = crypto.PKey()
        k.generate_key(crypto.TYPE_RSA, 2048)
        
        cert = crypto.X509()
        cert.get_subject().CN = domain
        cert.set_serial_number(1000)
        cert.gmtime_adj_notBefore(0)
        cert.gmtime_adj_notAfter(365*24*60*60)
        cert.set_issuer(cert.get_subject())
        cert.set_pubkey(k)
        cert.sign(k, 'sha256')
        
        with open(cert_dir / f"{domain}.crt", "wb") as f:
            f.write(crypto.dump_certificate(crypto.FILETYPE_PEM, cert))
        with open(cert_dir / f"{domain}.key", "wb") as f:
            f.write(crypto.dump_privatekey(crypto.FILETYPE_PEM, k))
        
        projects = load_projects()
        if u in projects and project_id in projects[u]:
            projects[u][project_id]["has_ssl"] = True
            save_projects(projects)
        flash(f"✅ SSL certificate generated for {domain}", "success")
    except Exception as e:
        flash(f"❌ Failed to generate SSL: {str(e)}", "error")
    return redirect(url_for("project_detail", project_id=project_id))

@app.route("/project/<project_id>/logs")
@require_user
def project_logs(project_id):
    u = current_user()
    project = get_project(u, project_id)
    if not project:
        return jsonify({"success": False, "error": "Project not found"}), 404
    
    limit = request.args.get("limit", 500, type=int)
    logs = get_project_logs(u, project_id, limit)
    return jsonify({
        "success": True,
        "logs": logs,
        "is_running": is_project_running(u, project_id),
        "total": len(logs)
    })

@app.route("/project/<project_id>/logs/download")
@require_user
def project_logs_download(project_id):
    u = current_user()
    project = get_project(u, project_id)
    if not project:
        flash("Project not found!", "error")
        return redirect(url_for("projects_list"))
    
    logs = get_project_logs(u, project_id, 5000)
    log_text = "\n".join(logs) if logs else "No logs available."
    
    response = Response(log_text, mimetype="text/plain")
    response.headers["Content-Disposition"] = f"attachment; filename={project['name']}_logs_{datetime.now().strftime('%Y%m%d')}.txt"
    return response

@app.route("/project/<project_id>/resources")
@require_user
def project_resources(project_id):
    u = current_user()
    project = get_project(u, project_id)
    if not project:
        return jsonify({"success": False, "error": "Project not found"}), 404
    
    resources = get_project_resources(u, project_id)
    return jsonify({
        "success": True,
        "cpu": resources["cpu"],
        "ram": resources["ram"],
        "ram_mb": resources["ram_mb"],
        "is_running": is_project_running(u, project_id)
    })

@app.route("/project/<project_id>/env-vars")
@require_user
def project_env_vars(project_id):
    u = current_user()
    project = get_project(u, project_id)
    if not project:
        return jsonify({"success": False, "error": "Project not found"}), 404
    return jsonify({"env_vars": project.get("env_vars", {})})

@app.route("/project/<project_id>/save-env-vars", methods=["POST"])
@require_user
def project_save_env_vars(project_id):
    u = current_user()
    project = get_project(u, project_id)
    if not project:
        return jsonify({"success": False, "error": "Project not found"}), 404
    
    env_vars = request.json.get("env_vars", {})
    projects = load_projects()
    if u in projects and project_id in projects[u]:
        projects[u][project_id]["env_vars"] = env_vars
        save_projects(projects)
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Failed to save"}), 500

@app.route("/project/<project_id>/delete", methods=["POST"])
@require_user
def project_delete(project_id):
    u = current_user()
    project = get_project(u, project_id)
    if not project:
        flash("Project not found!", "error")
        return redirect(url_for("projects_list"))
    
    if delete_project(u, project_id):
        flash(f"Project '{project['name']}' deleted!", "success")
    else:
        flash("Failed to delete project!", "error")
    return redirect(url_for("projects_list"))

# ==================== USER WORKFLOW ROUTES ====================

@app.route("/upload-requirements", methods=["POST"])
@require_user
def upload_requirements():
    u = current_user()
    users = load_users()
    
    if users.get(u, {}).get("payment_status") != "paid":
        flash("Please subscribe to a plan to upload requirements!", "error")
        return redirect(url_for("user_dashboard"))
    
    udir = user_dir(u)
    
    if 'requirements' not in request.files:
        flash("No file uploaded!", "error")
        return redirect(url_for("user_dashboard"))
    
    file = request.files['requirements']
    if file.filename == '' or not file.filename.endswith('.txt'):
        flash("Please upload a valid requirements.txt file!", "error")
        return redirect(url_for("user_dashboard"))
    
    name = secure_filename(file.filename)
    file.save(udir / name)
    
    try:
        result = subprocess.run(
            ['pip', 'install', '-r', str(udir / name)],
            cwd=str(udir),
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode == 0:
            flash(f"✅ Requirements installed successfully!", "success")
        else:
            flash(f"⚠️ Some packages failed to install: {result.stderr[:200]}", "warning")
    except subprocess.TimeoutExpired:
        flash("❌ Installation timed out. Some packages may be too large.", "error")
    except Exception as e:
        flash(f"❌ Error installing requirements: {str(e)}", "error")
    
    threading.Thread(target=lambda: manual_backup("Requirements uploaded"), daemon=True).start()
    
    return redirect(url_for("user_dashboard"))

@app.route("/deploy-project", methods=["POST"])
@require_user
def deploy_project():
    u = current_user()
    users = load_users()
    
    if users.get(u, {}).get("payment_status") != "paid":
        return jsonify({"success": False, "error": "Please subscribe to a plan to deploy!"}), 400
    
    udir = user_dir(u)
    
    # Get the main Python file
    py_files = [f for f in udir.iterdir() if f.suffix == '.py']
    if not py_files:
        return jsonify({"success": False, "error": "No Python file found to deploy!"}), 400
    
    # Use the first Python file as main
    main_file = py_files[0]
    run_command = f"python {main_file.name}"
    
    # Save run command
    with open(udir / "run_command.txt", 'w') as f:
        f.write(run_command)
    
    # Install requirements if exists
    req_file = udir / "requirements.txt"
    if req_file.exists():
        try:
            subprocess.run(
                ['pip', 'install', '-r', str(req_file)],
                cwd=str(udir),
                capture_output=True,
                timeout=300
            )
        except:
            pass
    
    threading.Thread(target=lambda: manual_backup(f"Project deployed by {u}"), daemon=True).start()
    
    return jsonify({"success": True, "message": f"Deployed {main_file.name} successfully!"})

@app.route("/get-env-vars")
@require_user
def get_env_vars():
    u = current_user()
    udir = user_dir(u)
    env_file = udir / ".env"
    
    env_vars = []
    if env_file.exists():
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    parts = line.split('=', 1)
                    if len(parts) == 2:
                        env_vars.append({"key": parts[0].strip(), "value": parts[1].strip()})
    
    return jsonify({"env_vars": env_vars})

@app.route("/save-env-vars", methods=["POST"])
@require_user
def save_env_vars():
    u = current_user()
    udir = user_dir(u)
    env_file = udir / ".env"
    
    data = request.json
    env_vars = data.get("env_vars", [])
    
    try:
        with open(env_file, 'w') as f:
            for env in env_vars:
                f.write(f"{env['key']}={env['value']}\n")
        
        threading.Thread(target=lambda: manual_backup("Environment variables saved"), daemon=True).start()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/clear-env-vars", methods=["POST"])
@require_user
def clear_env_vars():
    u = current_user()
    udir = user_dir(u)
    env_file = udir / ".env"
    
    try:
        if env_file.exists():
            env_file.unlink()
        threading.Thread(target=lambda: manual_backup("Environment variables cleared"), daemon=True).start()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ==================== OWNER ROUTES ====================

@app.route("/owner")
@require_owner
def owner_dashboard():
    users = load_users()
    projects = load_projects()
    total_projects = sum(len(p) for p in projects.values()) if projects else 0
    backup_info = get_backup_status()
    
    return render_template("owner.html",
        users=users,
        base_url=request.host_url.rstrip("/"),
        pricing=load_pricing(),
        currencies=SUPPORTED_CURRENCIES,
        backup_info=backup_info,
        total_projects=total_projects
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
        "banned": False,
    }
    save_users(users)
    user_dir(u)
    flash(f"User {u} created!", "success")
    return redirect(url_for("owner_dashboard"))

@app.route("/owner/delete/<username>", methods=["POST"])
@require_owner
def owner_delete(username):
    users = load_users()
    if username in users and username != OWNER_USER:
        del users[username]
        save_users(users)
        shutil.rmtree(FILES_ROOT / username, ignore_errors=True)
        flash(f"User {username} deleted!", "success")
    return redirect(url_for("owner_dashboard"))

@app.route("/owner/ban/<username>", methods=["POST"])
@require_owner
def owner_ban_user(username):
    users = load_users()
    if username in users and username != OWNER_USER:
        users[username]["banned"] = True
        save_users(users)
        flash(f"User {username} banned!", "success")
    return redirect(url_for("owner_dashboard"))

@app.route("/owner/unban/<username>", methods=["POST"])
@require_owner
def owner_unban_user(username):
    users = load_users()
    if username in users:
        users[username]["banned"] = False
        save_users(users)
        flash(f"User {username} unbanned!", "success")
    return redirect(url_for("owner_dashboard"))

@app.route("/owner/unban-all", methods=["POST"])
@require_owner
def owner_unban_all():
    users = load_users()
    for username in users:
        if username != OWNER_USER:
            users[username]["banned"] = False
    save_users(users)
    flash("All users unbanned!", "success")
    return redirect(url_for("owner_dashboard"))

@app.route("/owner/ban-all", methods=["POST"])
@require_owner
def owner_ban_all():
    users = load_users()
    count = 0
    for username in users:
        if username != OWNER_USER:
            users[username]["banned"] = True
            count += 1
    save_users(users)
    flash(f"{count} users banned!", "success")
    return redirect(url_for("owner_dashboard"))

@app.route("/owner/pricing", methods=["POST"])
@require_owner
def owner_pricing():
    pricing = load_pricing()
    pricing["currency"] = request.form.get("currency", "NGN")
    pricing["contact"] = request.form.get("contact", "")
    
    plans = []
    names = request.form.getlist("p_name")
    durs = request.form.getlist("p_duration")
    prices = request.form.getlist("p_price")
    feats = request.form.getlist("p_features")
    
    for i in range(len(names)):
        if names[i].strip():
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

@app.route("/owner/update_subscription/<username>", methods=["POST"])
@require_owner
def owner_update_subscription(username):
    subscription = request.form.get("subscription", "Basic")
    users = load_users()
    if username in users:
        users[username]["subscription"] = subscription
        users[username]["payment_status"] = "paid"
        save_users(users)
        flash(f"✅ Subscription updated for {username}!", "success")
    else:
        flash(f"❌ User {username} not found!", "error")
    return redirect(url_for("owner_dashboard"))

@app.route("/admin/backup", methods=["POST"])
@require_owner
def admin_backup():
    def do_backup():
        if manual_backup("Manual backup"):
            flash("✅ Backup completed!", "success")
        else:
            flash("⚠️ Backup failed!", "warning")
    threading.Thread(target=do_backup, daemon=True).start()
    flash("📤 Backup started!", "info")
    return redirect(url_for("owner_dashboard"))

@app.route("/admin/backup-status")
@require_owner
def admin_backup_status():
    return jsonify(get_backup_status())

@app.route("/admin/restore", methods=["POST"])
@require_owner
def admin_restore():
    if github_backup.restore():
        flash("✅ Restore successful!", "success")
    else:
        flash("❌ Restore failed!", "error")
    return redirect(url_for("owner_dashboard"))

@app.route("/admin/block-ip", methods=["POST"])
@require_owner
def admin_block_ip():
    ip = request.form.get("ip", "").strip()
    reason = request.form.get("reason", "Manual block")
    flash(f"IP {ip} blocked: {reason}", "success")
    return redirect(url_for("owner_dashboard"))

@app.route("/admin/unblock-all-ips", methods=["POST"])
@require_owner
def admin_unblock_all_ips():
    flash("All IPs unblocked", "success")
    return redirect(url_for("owner_dashboard"))

@app.route("/admin/blocked-ips")
@require_owner
def admin_blocked_ips():
    return jsonify({"blocked_ips": []})

# ==================== USER DASHBOARD ====================

@app.route("/dashboard")
@require_user
def user_dashboard():
    u = current_user()
    users = load_users()
    info = users.get(u, {})
    projects = get_user_projects(u)
    is_paid = info.get("payment_status") == "paid"
    
    return render_template("user.html",
        username=u,
        info=info,
        subscription=info.get("subscription", "Basic"),
        is_paid=is_paid,
        email=info.get("email", ""),
        projects=projects,
        total_projects=len(projects)
    )

@app.route("/upload", methods=["POST"])
@require_user
def upload():
    u = current_user()
    users = load_users()
    if users.get(u, {}).get("payment_status") != "paid":
        flash("Please subscribe to a plan!", "error")
        return redirect(url_for("user_dashboard"))
    
    udir = user_dir(u)
    files = request.files.getlist("files")
    for f in files:
        if f and f.filename:
            name = secure_filename(f.filename)
            if name:
                f.save(udir / name)
    flash("Files uploaded successfully!", "success")
    return redirect(url_for("user_dashboard"))

@app.route("/file/delete/<name>", methods=["POST"])
@require_user
def file_delete(name):
    u = current_user()
    p = user_dir(u) / secure_filename(name)
    if p.exists():
        p.unlink()
        flash(f"File deleted!", "success")
    return redirect(url_for("user_dashboard"))

@app.route("/file/view/<name>")
@require_user
def file_view(name):
    u = current_user()
    return send_from_directory(user_dir(u), secure_filename(name), as_attachment=False)

@app.route("/healthz")
def health():
    return "ok", 200

@app.route("/debug")
def debug():
    return jsonify({
        "status": "running",
        "service": "NCK Dev VPS",
        "github_backup_enabled": github_backup.is_enabled if github_backup else False,
        "flw_enabled": FLW_ENABLED
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
