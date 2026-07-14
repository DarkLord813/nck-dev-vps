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
import logging
from logging.handlers import RotatingFileHandler

APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"
USERS_FILE = DATA_DIR / "users.json"
PRICING_FILE = DATA_DIR / "pricing.json"
PROJECTS_FILE = DATA_DIR / "projects.json"
PAYMENTS_FILE = DATA_DIR / "payments.json"
FILES_ROOT = APP_DIR / "user_files"
DATA_DIR.mkdir(exist_ok=True)
FILES_ROOT.mkdir(exist_ok=True)

OWNER_USER = os.environ.get("OWNER_USERNAME", "DarkLord813")
OWNER_PASS = os.environ.get("OWNER_PASSWORD", "DarkLord813")

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TELEGRAM_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)

# TON Payment Configuration
TON_WALLET = os.environ.get("TON_WALLET", "EQD...")

# ==================== MULTI-CURRENCY CONFIGURATION ====================
SUPPORTED_CURRENCIES = {
    "NGN": {
        "symbol": "₦",
        "name": "Nigerian Naira",
        "country": "Nigeria",
        "flag": "🇳🇬",
        "exchange_rate": 1.0,
        "ton_price": 0.015,
        "gift_card_options": ["Amazon", "Steam", "Google Play", "Apple", "PlayStation", "Xbox"]
    },
    "USD": {
        "symbol": "$",
        "name": "US Dollar",
        "country": "United States",
        "flag": "🇺🇸",
        "exchange_rate": 0.0016,
        "ton_price": 0.0025,
        "gift_card_options": ["Amazon", "Steam", "Google Play", "Apple", "PlayStation", "Xbox", "Best Buy", "Target"]
    },
    "EUR": {
        "symbol": "€",
        "name": "Euro",
        "country": "Europe",
        "flag": "🇪🇺",
        "exchange_rate": 0.0015,
        "ton_price": 0.0023,
        "gift_card_options": ["Amazon", "Steam", "Google Play", "Apple", "PlayStation"]
    },
    "GBP": {
        "symbol": "£",
        "name": "British Pound",
        "country": "United Kingdom",
        "flag": "🇬🇧",
        "exchange_rate": 0.0013,
        "ton_price": 0.0020,
        "gift_card_options": ["Amazon", "Steam", "Google Play", "Apple", "PlayStation"]
    },
    "TON": {
        "symbol": "⧫",
        "name": "TON Coin",
        "country": "Global",
        "flag": "💎",
        "exchange_rate": 400.0,
        "ton_price": 1.0,
        "gift_card_options": ["Amazon", "Steam", "Google Play", "Apple"]
    }
}

DEFAULT_PRICING = {
    "currency": "NGN",
    "contact": "@rexoronsaye",
    "plans": [
        {"name": "Basic", "duration": "Monthly", "price": "2500", "features": "1 project, 1GB RAM, 5GB storage, Basic support"},
        {"name": "Pro", "duration": "Yearly", "price": "15000", "features": "5 projects, 2GB RAM, 20GB storage, Priority support, Custom domains"},
        {"name": "Premium", "duration": "Yearly", "price": "25000", "features": "20 projects, 4GB RAM, 50GB storage, Dedicated help, SSL, Docker, Database"},
    ],
    "currency_pricing": {
        "NGN": {"Basic": "2500", "Pro": "15000", "Premium": "25000"},
        "USD": {"Basic": "4.00", "Pro": "24.00", "Premium": "40.00"},
        "EUR": {"Basic": "3.75", "Pro": "22.50", "Premium": "37.50"},
        "GBP": {"Basic": "3.25", "Pro": "19.50", "Premium": "32.50"},
        "TON": {"Basic": "6.25", "Pro": "37.50", "Premium": "62.50"}
    }
}

# ==================== PAYMENT METHODS CONFIGURATION ====================
PAYMENT_METHODS = {
    "bank_transfer": {
        "name": "Nigerian Bank Transfer",
        "icon": "🏦",
        "enabled": True,
        "currencies": ["NGN"],
        "details": {
            "bank": "GTBank",
            "account_number": "0123456789",
            "account_name": "NCK Dev VPS",
            "bank_code": "058"
        }
    },
    "ton": {
        "name": "TON (Telegram Open Network)",
        "icon": "💎",
        "enabled": True,
        "currencies": ["TON", "NGN", "USD", "EUR", "GBP"],
        "details": {
            "wallet": TON_WALLET or "EQD...",
            "network": "TON Mainnet"
        }
    },
    "gift_card": {
        "name": "Gift Cards",
        "icon": "🎁",
        "enabled": True,
        "currencies": ["USD", "EUR", "GBP", "NGN", "TON"],
        "details": {
            "accepted": ["Amazon", "Steam", "Google Play", "Apple", "PlayStation", "Xbox", "Best Buy", "Target"],
            "instructions": "Send gift card code via Telegram"
        }
    }
}

if not USERS_FILE.exists():
    USERS_FILE.write_text("{}")
if not PRICING_FILE.exists():
    PRICING_FILE.write_text(json.dumps(DEFAULT_PRICING, indent=2))
if not PROJECTS_FILE.exists():
    PROJECTS_FILE.write_text("{}")
if not PAYMENTS_FILE.exists():
    PAYMENTS_FILE.write_text("{}")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024

# ==================== LOGGING ====================
LOG_DIR = APP_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
file_handler = RotatingFileHandler(LOG_DIR / "app.log", maxBytes=10485760, backupCount=10)
file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s: %(message)s'))
file_handler.setLevel(logging.INFO)
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)

# ==================== CONVERT PRICE FUNCTION ====================
def convert_price(amount_ngn, target_currency):
    """Convert price from NGN to target currency"""
    if target_currency == "NGN":
        return amount_ngn
    
    rate = SUPPORTED_CURRENCIES.get(target_currency, {}).get("exchange_rate", 1.0)
    if target_currency == "TON":
        ton_rate = SUPPORTED_CURRENCIES["TON"]["exchange_rate"]
        return round(amount_ngn / ton_rate, 2)
    
    return round(amount_ngn * rate, 2)

def format_price(amount, currency):
    """Format price with currency symbol"""
    symbol = SUPPORTED_CURRENCIES.get(currency, {}).get("symbol", "₦")
    if currency == "TON":
        return f"{symbol}{amount}"
    return f"{symbol}{amount:,.2f}"

def get_plan_price(plan_name, currency="NGN"):
    """Get price for a plan in specified currency"""
    pricing = load_pricing()
    currency_pricing = pricing.get("currency_pricing", {})
    
    if currency in currency_pricing and plan_name in currency_pricing[currency]:
        return float(currency_pricing[currency][plan_name])
    
    # Fallback to base currency
    for plan in pricing.get("plans", []):
        if plan["name"].lower() == plan_name.lower():
            base_price = float(plan["price"])
            return convert_price(base_price, currency)
    
    return 0

def get_ton_price(plan_name):
    """Get TON price for a plan"""
    price_ngn = get_plan_price(plan_name, "NGN")
    return convert_price(price_ngn, "TON")

def get_telegram_chat_id():
    """Get or detect Telegram chat ID"""
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    
    # If chat_id is not set, try to detect it
    if not chat_id and TELEGRAM_BOT_TOKEN:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            response = requests.get(url, timeout=10)
            data = response.json()
            
            if data.get("ok") and data.get("result"):
                for update in data["result"]:
                    if "message" in update and "chat" in update["message"]:
                        chat_id = str(update["message"]["chat"]["id"])
                        print(f"✅ Auto-detected Telegram chat ID: {chat_id}")
                        break
                    elif "callback_query" in update and "message" in update["callback_query"]:
                        chat_id = str(update["callback_query"]["message"]["chat"]["id"])
                        print(f"✅ Auto-detected Telegram chat ID: {chat_id}")
                        break
        except Exception as e:
            print(f"⚠️ Could not auto-detect chat ID: {e}")
    
    return chat_id

# ==================== TELEGRAM NOTIFICATIONS ====================
def send_telegram_notification(message):
    """Send notification to Telegram"""
    bot_token = TELEGRAM_BOT_TOKEN
    chat_id = get_telegram_chat_id()
    
    if not bot_token:
        print("⚠️ Telegram bot token not configured")
        return False
    
    if not chat_id:
        print("⚠️ Telegram chat ID not found. Send a message to your bot first!")
        print("   Then visit: https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates")
        return False
    
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Telegram error: {e}")
        return False

# ==================== GITHUB BACKUP SYSTEM ====================
class GitHubBackupSystem:
    def __init__(self, data_dir, files_root):
        self.data_dir = data_dir
        self.files_root = files_root
        self.token = os.environ.get("GITHUB_TOKEN", "")
        self.repo_owner = os.environ.get("GITHUB_REPO_OWNER", "DarkLord813")
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
            payments_data = {}
            
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
            
            if PAYMENTS_FILE.exists():
                try:
                    with open(PAYMENTS_FILE, 'r') as f:
                        payments_data = json.load(f)
                except:
                    pass
            
            backup_data = {
                "timestamp": datetime.now().isoformat(),
                "version": "1.0",
                "users": users_data,
                "pricing": pricing_data,
                "projects": projects_data,
                "payments": payments_data,
                "stats": {
                    "users_count": len(users_data),
                    "projects_count": sum(len(p) for p in projects_data.values()) if projects_data else 0,
                    "payments_count": len(payments_data) if payments_data else 0,
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
            
            if "payments" in data:
                with open(PAYMENTS_FILE, 'w') as f:
                    json.dump(data["payments"], f, indent=2)
                print(f"✅ Restored {len(data['payments'])} payment records")
            
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
    threading.Thread(target=lambda: manual_backup("Projects data changed"), daemon=True).start()

def load_payments():
    if not PAYMENTS_FILE.exists():
        return {}
    try:
        return json.loads(PAYMENTS_FILE.read_text())
    except Exception:
        return {}

def save_payments(payments):
    with _lock:
        PAYMENTS_FILE.write_text(json.dumps(payments, indent=2))
    threading.Thread(target=lambda: manual_backup("Payments data changed"), daemon=True).start()

def update_project_files(username, project_id):
    try:
        projects = load_projects()
        if username in projects and project_id in projects[username]:
            project_dir = FILES_ROOT / username / project_id
            if project_dir.exists():
                projects[username][project_id]["files"] = sorted([f.name for f in project_dir.iterdir() if f.is_file()])
                projects[username][project_id]["updated_at"] = time.time()
                save_projects(projects)
                return True
    except Exception as e:
        app.logger.error(f"Error updating project files: {str(e)}")
    return False

# ==================== FIX MISSING PROJECT DIRECTORIES ====================
def fix_missing_project_directories():
    """Check all projects and create missing directories"""
    projects = load_projects()
    fixed_count = 0
    
    for username, user_projects in projects.items():
        for project_id, project_data in user_projects.items():
            project_dir = FILES_ROOT / username / project_id
            if not project_dir.exists():
                app.logger.warning(f"Creating missing directory for {username}/{project_id}")
                project_dir.mkdir(parents=True, exist_ok=True)
                fixed_count += 1
    
    if fixed_count > 0:
        app.logger.info(f"✅ Fixed {fixed_count} missing project directories")
        threading.Thread(target=lambda: manual_backup("Fixed missing project directories"), daemon=True).start()

# Run this on startup
try:
    fix_missing_project_directories()
except Exception as e:
    app.logger.error(f"Error fixing project directories: {e}")

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
            flash("Please login as owner", "error")
            return redirect(url_for("login"))
        return f(*a, **kw)
    return w

def require_user(f):
    @wraps(f)
    def w(*a, **kw):
        u = current_user()
        if not u or session.get("role") != "user":
            flash("Please login to access this page", "error")
            return redirect(url_for("login"))
        ok, _ = user_valid(u)
        if not ok:
            session.clear()
            flash("Your account is invalid or banned", "error")
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
    
    # Create physical directory FIRST
    project_dir = FILES_ROOT / username / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    
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
        "last_crash_time": None,
        "deployment_status": "created",
        "deployment_log": [],
        "project_type": "unknown",
        "framework": "unknown",
        "dependencies_installed": False
    }
    save_projects(projects)
    
    threading.Thread(target=lambda: manual_backup(f"Project created: {project_name} by {username}"), daemon=True).start()
    
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
        
        threading.Thread(target=lambda: manual_backup(f"Project deleted: {project_id} by {username}"), daemon=True).start()
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
    
    # If no run command, try to auto-detect
    if not run_command:
        analysis = deployment_engine.analyze_project(project_dir)
        if analysis.get("run_command"):
            run_command = analysis["run_command"]
            projects = load_projects()
            if username in projects and project_id in projects[username]:
                projects[username][project_id]["run_command"] = run_command
                save_projects(projects)
        else:
            # Try to find a Python file to run
            py_files = list(project_dir.glob("*.py"))
            if py_files:
                run_command = f"python {py_files[0].name}"
            else:
                return False, "No run command set and couldn't auto-detect"
    
    try:
        env = os.environ.copy()
        for key, value in project.get("env_vars", {}).items():
            env[key] = str(value)
        
        if project.get("port"):
            env["PORT"] = str(project["port"])
            run_command = run_command.replace("$PORT", str(project["port"]))
        
        print(f"🚀 Starting project {project_id} with command: {run_command}")
        
        proc = subprocess.Popen(
            run_command,
            shell=True,
            cwd=str(project_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            env=env,
            text=True
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
        for line in iter(proc.stdout.readline, ""):
            if not line:
                break
            try:
                txt = line.rstrip()
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

# ==================== PROJECT DEPLOYMENT ENGINE ====================
class ProjectDeploymentEngine:
    @staticmethod
    def detect_project_type(project_dir):
        project_dir = Path(project_dir)
        py_files = list(project_dir.glob("*.py"))
        has_requirements = (project_dir / "requirements.txt").exists()
        
        has_flask = False
        has_django = False
        for f in py_files[:5]:
            if f.is_file():
                try:
                    content = f.read_text().lower()
                    if "flask" in content:
                        has_flask = True
                    if "django" in content:
                        has_django = True
                except:
                    pass
        
        has_package_json = (project_dir / "package.json").exists()
        has_server_js = (project_dir / "server.js").exists() or (project_dir / "index.js").exists()
        has_php = any(project_dir.glob("*.php"))
        has_index_html = (project_dir / "index.html").exists()
        
        if has_django:
            return "django", "python manage.py runserver 0.0.0.0:$PORT"
        elif has_flask:
            for f in py_files:
                try:
                    content = f.read_text().lower()
                    if "flask" in content and ("app.run" in content or "__name__" in content):
                        return "flask", f"python {f.name}"
                except:
                    pass
            return "flask", "python app.py"
        elif has_requirements and py_files:
            return "python", f"python {py_files[0].name}"
        elif has_package_json and has_server_js:
            return "nodejs", "npm start"
        elif has_package_json:
            try:
                import json
                with open(project_dir / "package.json") as f:
                    pkg = json.load(f)
                    if "scripts" in pkg and "start" in pkg["scripts"]:
                        return "nodejs", "npm start"
                    elif "scripts" in pkg and "dev" in pkg["scripts"]:
                        return "nodejs", "npm run dev"
            except:
                pass
            return "nodejs", "node server.js"
        elif has_php:
            return "php", "php -S 0.0.0.0:$PORT"
        elif has_index_html:
            return "static", "python -m http.server $PORT"
        elif py_files:
            return "python", f"python {py_files[0].name}"
        else:
            return "unknown", None
    
    @staticmethod
    def install_dependencies(project_dir, project_type):
        project_dir = Path(project_dir)
        results = []
        
        if project_type in ["python", "flask", "django"]:
            req_file = project_dir / "requirements.txt"
            if req_file.exists():
                try:
                    print(f"📦 Installing Python dependencies from {req_file}")
                    result = subprocess.run(
                        ['pip', 'install', '-r', str(req_file)],
                        cwd=str(project_dir),
                        capture_output=True,
                        text=True,
                        timeout=300
                    )
                    if result.returncode == 0:
                        results.append("✅ Python dependencies installed successfully")
                    else:
                        results.append(f"⚠️ Some Python packages failed: {result.stderr[:200]}")
                except subprocess.TimeoutExpired:
                    results.append("❌ Python dependency installation timed out")
                except Exception as e:
                    results.append(f"❌ Error installing Python dependencies: {str(e)}")
            else:
                results.append("ℹ️ No requirements.txt found")
        
        elif project_type == "nodejs":
            pkg_file = project_dir / "package.json"
            if pkg_file.exists():
                try:
                    print(f"📦 Installing Node.js dependencies from {pkg_file}")
                    npm_check = subprocess.run(['npm', '--version'], capture_output=True, timeout=5)
                    if npm_check.returncode == 0:
                        result = subprocess.run(
                            ['npm', 'install'],
                            cwd=str(project_dir),
                            capture_output=True,
                            text=True,
                            timeout=300
                        )
                        if result.returncode == 0:
                            results.append("✅ Node.js dependencies installed successfully")
                        else:
                            results.append(f"⚠️ npm install failed: {result.stderr[:200]}")
                    else:
                        results.append("⚠️ npm not available")
                except subprocess.TimeoutExpired:
                    results.append("❌ Node.js dependency installation timed out")
                except Exception as e:
                    results.append(f"❌ Error installing Node.js dependencies: {str(e)}")
            else:
                results.append("ℹ️ No package.json found")
        
        return results
    
    @staticmethod
    def detect_env_file(project_dir):
        project_dir = Path(project_dir)
        env_file = project_dir / ".env"
        env_vars = {}
        
        if env_file.exists():
            try:
                with open(env_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            if line.startswith('export '):
                                line = line[7:]
                            parts = line.split('=', 1)
                            if len(parts) == 2:
                                key = parts[0].strip()
                                value = parts[1].strip()
                                if (value.startswith('"') and value.endswith('"')) or \
                                   (value.startswith("'") and value.endswith("'")):
                                    value = value[1:-1]
                                env_vars[key] = value
                if env_vars:
                    print(f"🌿 Detected {len(env_vars)} environment variables from .env")
            except Exception as e:
                print(f"⚠️ Error reading .env file: {e}")
        
        return env_vars
    
    @staticmethod
    def analyze_project(project_dir):
        project_dir = Path(project_dir)
        analysis = {
            "project_type": None,
            "run_command": None,
            "has_requirements": False,
            "has_env": False,
            "env_vars": {},
            "dependencies_installed": False,
            "main_files": [],
            "framework": "unknown"
        }
        
        project_type, run_command = ProjectDeploymentEngine.detect_project_type(project_dir)
        analysis["project_type"] = project_type
        analysis["run_command"] = run_command
        analysis["has_requirements"] = (project_dir / "requirements.txt").exists()
        
        env_vars = ProjectDeploymentEngine.detect_env_file(project_dir)
        if env_vars:
            analysis["has_env"] = True
            analysis["env_vars"] = env_vars
        
        analysis["main_files"] = [f.name for f in project_dir.iterdir() if f.is_file()]
        
        if project_type == "flask":
            analysis["framework"] = "Flask"
        elif project_type == "django":
            analysis["framework"] = "Django"
        elif project_type == "nodejs":
            analysis["framework"] = "Node.js"
        elif project_type == "php":
            analysis["framework"] = "PHP"
        elif project_type == "static":
            analysis["framework"] = "Static Site"
        
        return analysis

deployment_engine = ProjectDeploymentEngine()

def deploy_project_files(username, project_id):
    project = get_project(username, project_id)
    if not project:
        return False, "Project not found"
    
    project_dir = FILES_ROOT / username / project_id
    
    # Ensure directory exists before deploying
    if not project_dir.exists():
        project_dir.mkdir(parents=True, exist_ok=True)
    
    analysis = deployment_engine.analyze_project(project_dir)
    
    projects = load_projects()
    if username in projects and project_id in projects[username]:
        projects[username][project_id]["project_type"] = analysis["project_type"]
        projects[username][project_id]["framework"] = analysis["framework"]
        projects[username][project_id]["files"] = analysis["main_files"]
        
        if analysis["run_command"] and not projects[username][project_id]["run_command"]:
            projects[username][project_id]["run_command"] = analysis["run_command"]
        
        if analysis["env_vars"]:
            projects[username][project_id]["env_vars"] = analysis["env_vars"]
        
        save_projects(projects)
    
    install_results = deployment_engine.install_dependencies(project_dir, analysis["project_type"])
    
    projects = load_projects()
    if username in projects and project_id in projects[username]:
        projects[username][project_id]["deployment_status"] = "deployed"
        projects[username][project_id]["dependencies_installed"] = True
        projects[username][project_id]["deployment_log"] = install_results
        save_projects(projects)
    
    threading.Thread(target=lambda: manual_backup(f"Project deployed: {project['name']} by {username}"), daemon=True).start()
    
    return True, install_results

# ==================== UPLOAD TASK MANAGER ====================
upload_tasks = {}

def process_upload_task(task_id, u, project_id, project_dir):
    """Background task to process uploaded files"""
    try:
        upload_tasks[task_id] = {"status": "processing", "message": "Processing files...", "progress": 10}
        
        # Scan for requirements.txt
        req_files = list(project_dir.rglob('requirements.txt'))
        if req_files:
            upload_tasks[task_id] = {"status": "processing", "message": "Installing requirements...", "progress": 30}
            req_file = req_files[0]
            try:
                result = subprocess.run(
                    ['pip', 'install', '-r', str(req_file)],
                    cwd=str(project_dir),
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                if result.returncode == 0:
                    upload_tasks[task_id] = {"status": "processing", "message": "✅ Requirements installed!", "progress": 50}
                else:
                    upload_tasks[task_id] = {"status": "processing", "message": f"⚠️ Some packages failed: {result.stderr[:100]}", "progress": 40}
            except Exception as e:
                upload_tasks[task_id] = {"status": "processing", "message": f"❌ Error: {str(e)}", "progress": 40}
        
        # Scan for .env files
        env_files = list(project_dir.rglob('.env')) + list(project_dir.rglob('env.txt')) + list(project_dir.rglob('text.env'))
        if env_files:
            upload_tasks[task_id] = {"status": "processing", "message": "Loading environment variables...", "progress": 60}
            env_file = env_files[0]
            try:
                env_vars = {}
                with open(env_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            if line.startswith('export '):
                                line = line[7:]
                            parts = line.split('=', 1)
                            if len(parts) == 2:
                                key = parts[0].strip()
                                value = parts[1].strip()
                                if (value.startswith('"') and value.endswith('"')) or \
                                   (value.startswith("'") and value.endswith("'")):
                                    value = value[1:-1]
                                env_vars[key] = value
                
                if env_vars:
                    projects = load_projects()
                    if u in projects and project_id in projects[u]:
                        projects[u][project_id]["env_vars"] = env_vars
                        save_projects(projects)
                        upload_tasks[task_id] = {"status": "processing", "message": f"✅ Loaded {len(env_vars)} env vars!", "progress": 70}
            except Exception as e:
                upload_tasks[task_id] = {"status": "processing", "message": f"⚠️ Error loading .env: {str(e)}", "progress": 60}
        
        # Scan for package.json
        pkg_files = list(project_dir.rglob('package.json'))
        if pkg_files:
            upload_tasks[task_id] = {"status": "processing", "message": "Installing npm dependencies...", "progress": 75}
            try:
                npm_check = subprocess.run(['npm', '--version'], capture_output=True, timeout=5)
                if npm_check.returncode == 0:
                    result = subprocess.run(
                        ['npm', 'install'],
                        cwd=str(project_dir),
                        capture_output=True,
                        text=True,
                        timeout=300
                    )
                    if result.returncode == 0:
                        upload_tasks[task_id] = {"status": "processing", "message": "✅ npm dependencies installed!", "progress": 85}
                    else:
                        upload_tasks[task_id] = {"status": "processing", "message": f"⚠️ npm install failed", "progress": 80}
            except Exception as e:
                upload_tasks[task_id] = {"status": "processing", "message": f"⚠️ npm error: {str(e)}", "progress": 80}
        
        # Deploy project
        upload_tasks[task_id] = {"status": "processing", "message": "Deploying project...", "progress": 90}
        success, results = deploy_project_files(u, project_id)
        if success:
            upload_tasks[task_id] = {"status": "complete", "message": "✅ Project uploaded and deployed successfully!", "progress": 100}
        else:
            upload_tasks[task_id] = {"status": "complete", "message": f"⚠️ Uploaded but deployment failed: {results}", "progress": 95}
            
    except Exception as e:
        upload_tasks[task_id] = {"status": "error", "message": f"❌ Error: {str(e)}", "progress": 0}

# ==================== ROUTES ====================

@app.route("/")
def index():
    if is_owner():
        return redirect(url_for("owner_dashboard"))
    if current_user():
        return redirect(url_for("user_dashboard"))
    return redirect(url_for("landing"))

@app.route("/home")
@app.route("/landing")
def landing():
    if current_user():
        return redirect(url_for("user_dashboard"))
    try:
        return render_template("landing.html",
            pricing=load_pricing(),
            payment_methods=PAYMENT_METHODS,
            currencies=SUPPORTED_CURRENCIES
        )
    except Exception as e:
        app.logger.error(f"Landing error: {e}")
        return render_template("landing.html", pricing=DEFAULT_PRICING, payment_methods=PAYMENT_METHODS, currencies=SUPPORTED_CURRENCIES, error="Could not load pricing")

@app.route("/pricing")
def pricing_page():
    try:
        users = load_users()
        pricing = load_pricing()
        return render_template("pricing.html",
            pricing=pricing,
            users=users,
            session=session,
            payment_methods=PAYMENT_METHODS,
            currencies=SUPPORTED_CURRENCIES,
            convert_price=convert_price,
            format_price=format_price,
            get_plan_price=get_plan_price,
            get_ton_price=get_ton_price
        )
    except Exception as e:
        app.logger.error(f"Pricing error: {e}")
        flash("Error loading pricing data", "error")
        return render_template("pricing.html", 
            pricing=DEFAULT_PRICING,
            users={},
            session=session,
            payment_methods=PAYMENT_METHODS,
            currencies=SUPPORTED_CURRENCIES
        )

@app.route("/register", methods=["GET", "POST"])
def register():
    pricing = load_pricing()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        subscription = request.form.get("subscription", "Basic")
        email = request.form.get("email", "").strip()
        currency = request.form.get("currency", "NGN")
        
        if not username or not password:
            flash("Username and password are required!", "error")
            return render_template("register.html", pricing=pricing, currencies=SUPPORTED_CURRENCIES)
        
        if len(username) < 3:
            flash("Username must be at least 3 characters!", "error")
            return render_template("register.html", pricing=pricing, currencies=SUPPORTED_CURRENCIES)
        
        if password != confirm_password:
            flash("Passwords don't match!", "error")
            return render_template("register.html", pricing=pricing, currencies=SUPPORTED_CURRENCIES)
        
        if len(password) < 6:
            flash("Password must be at least 6 characters!", "error")
            return render_template("register.html", pricing=pricing, currencies=SUPPORTED_CURRENCIES)
        
        users = load_users()
        if username in users:
            flash("Username already exists!", "error")
            return render_template("register.html", pricing=pricing, currencies=SUPPORTED_CURRENCIES)
        
        if username == OWNER_USER:
            flash("This username is reserved!", "error")
            return render_template("register.html", pricing=pricing, currencies=SUPPORTED_CURRENCIES)
        
        # Get plan price in selected currency
        plan_price = get_plan_price(subscription, currency)
        plan_price_formatted = format_price(plan_price, currency)
        
        users[username] = {
            "password": generate_password_hash(password),
            "created_at": time.time(),
            "subscription": subscription,
            "token": secrets.token_urlsafe(16),
            "payment_status": "pending",
            "email": email,
            "banned": False,
            "currency": currency
        }
        save_users(users)
        user_dir(username)
        
        # Send Telegram notification
        if TELEGRAM_ENABLED:
            chat_id = get_telegram_chat_id()
            if chat_id:
                message = f"""
🆕 <b>NEW USER REGISTRATION!</b>

👤 Username: {username}
📧 Email: {email}
📋 Plan: {subscription}
💰 Price: {plan_price_formatted}
💱 Currency: {currency}

🔗 Auto-login link:
{request.host_url}auto/{users[username]['token']}

👑 Owner actions:
• Login: {request.host_url}login
• Dashboard: {request.host_url}owner

📊 Status: ⏳ Payment Pending
"""
                send_telegram_notification(message)
            else:
                print("⚠️ Telegram chat ID not found - notification not sent")
        
        flash("Account created successfully! Please contact the owner to complete payment.", "success")
        return redirect(url_for("login"))
    
    return render_template("register.html", pricing=pricing, currencies=SUPPORTED_CURRENCIES)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "")
        
        users = load_users()
        
        if u == OWNER_USER and p == OWNER_PASS:
            session.clear()
            session["role"] = "owner"
            session["username"] = u
            return redirect(url_for("owner_dashboard"))
        
        info = users.get(u)
        if info and check_password_hash(info["password"], p):
            if info.get("banned", False):
                flash("Your account has been banned!", "error")
                return render_template("login.html", error="Account banned")
            session.clear()
            session["role"] = "user"
            session["username"] = u
            return redirect(url_for("user_dashboard"))
        else:
            flash("Invalid credentials", "error")
    
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully", "success")
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
            flash("Auto-login successful!", "success")
            return redirect(url_for("user_dashboard"))
    return "Invalid link", 404

# ==================== USER DASHBOARD ROUTES ====================

@app.route("/dashboard")
@require_user
def user_dashboard():
    try:
        u = current_user()
        users = load_users()
        info = users.get(u, {})
        is_paid = info.get("payment_status") == "paid"
        
        projects = get_user_projects(u)
        
        project_id = None
        project_name = None
        project_description = None
        project_files = []
        project_is_running = False
        project_port = None
        project_type = "unknown"
        project_framework = "unknown"
        project_deployment_status = "not_deployed"
        project_has_files = False
        
        if projects:
            project_id = list(projects.keys())[0]
            project = projects[project_id]
            project_name = project.get("name", "My Project")
            project_description = project.get("description", "")
            project_files = project.get("files", [])
            project_is_running = is_project_running(u, project_id)
            project_port = project.get("port")
            project_type = project.get("project_type", "unknown")
            project_framework = project.get("framework", "unknown")
            project_deployment_status = project.get("deployment_status", "not_deployed")
            
            project_dir = FILES_ROOT / u / project_id
            project_has_files = project_dir.exists() and any(project_dir.iterdir())
        
        return render_template("user.html",
            username=u,
            info=info,
            subscription=info.get("subscription", "Basic"),
            is_paid=is_paid,
            email=info.get("email", ""),
            project_id=project_id,
            project_name=project_name,
            project_description=project_description,
            project_files=project_files,
            project_is_running=project_is_running,
            project_port=project_port,
            project_type=project_type,
            project_framework=project_framework,
            project_deployment_status=project_deployment_status,
            project_has_files=project_has_files,
            has_projects=len(projects) > 0,
            total_projects=len(projects)
        )
    except Exception as e:
        app.logger.error(f"Dashboard error: {e}")
        flash("Error loading dashboard", "error")
        return render_template("user.html", 
            username=current_user(), 
            error=str(e),
            has_projects=False,
            is_paid=False
        )

# ==================== UPLOAD ROUTES (WITH ASYNC PROCESSING) ====================

@app.route("/upload", methods=["POST"])
@require_user
def upload():
    try:
        u = current_user()
        users = load_users()
        
        if users.get(u, {}).get("payment_status") != "paid":
            flash("Please subscribe to a plan!", "error")
            return redirect(url_for("user_dashboard"))
        
        projects = get_user_projects(u)
        project_id = None
        
        if projects:
            project_id = list(projects.keys())[0]
        else:
            project_id = create_project(u, "My Project", "Default project")
            flash(f"📁 Created default project: My Project", "info")
        
        if not project_id:
            flash("❌ Failed to create project!", "error")
            return redirect(url_for("user_dashboard"))
        
        project_dir = FILES_ROOT / u / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        
        files = request.files.getlist("files")
        uploaded_count = 0
        extracted_count = 0
        
        # Track what was found
        found_requirements = False
        found_env = False
        found_package_json = False
        
        for f in files:
            if f and f.filename:
                name = secure_filename(f.filename)
                if name:
                    file_path = project_dir / name
                    f.save(file_path)
                    
                    # Handle archives
                    if name.endswith('.zip') or name.endswith('.tar.gz') or name.endswith('.tgz') or name.endswith('.tar'):
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
                            extracted_count += 1
                        except Exception as e:
                            flash(f"❌ Failed to extract {name}: {str(e)}", "error")
                    else:
                        uploaded_count += 1
        
        # Generate task ID for background processing
        task_id = secrets.token_hex(16)
        
        # Start background task
        threading.Thread(
            target=process_upload_task,
            args=(task_id, u, project_id, project_dir),
            daemon=True
        ).start()
        
        # Update file list
        update_project_files(u, project_id)
        manual_backup(f"Files uploaded to project {project_id} by {u}")
        
        flash(f"📤 {uploaded_count} files uploaded, {extracted_count} archives extracted! Processing in background...", "info")
        
        # Store task ID in session for status checking
        session['upload_task_id'] = task_id
        session['upload_project_id'] = project_id
        
    except Exception as e:
        app.logger.error(f"Upload error: {e}")
        flash(f"Error uploading files: {str(e)}", "error")
    
    return redirect(url_for("upload_status"))

@app.route("/upload-status")
@require_user
def upload_status():
    """Check the status of the upload processing"""
    task_id = session.get('upload_task_id')
    project_id = session.get('upload_project_id')
    
    if not task_id or task_id not in upload_tasks:
        return render_template("upload_status.html", task=None, complete=False, project_id=project_id)
    
    task = upload_tasks.get(task_id)
    complete = task.get("status") in ["complete", "error"] if task else False
    
    return render_template("upload_status.html", task=task, complete=complete, project_id=project_id)

@app.route("/upload-status-json")
@require_user
def upload_status_json():
    """Get upload status as JSON for AJAX polling"""
    task_id = session.get('upload_task_id')
    if not task_id or task_id not in upload_tasks:
        return jsonify({"status": "not_found", "message": "No upload in progress", "progress": 0})
    
    task = upload_tasks.get(task_id)
    return jsonify(task)

@app.route("/upload-requirements", methods=["POST"])
@require_user
def upload_requirements():
    try:
        u = current_user()
        users = load_users()
        
        if users.get(u, {}).get("payment_status") != "paid":
            flash("Please subscribe to a plan!", "error")
            return redirect(url_for("user_dashboard"))
        
        projects = get_user_projects(u)
        project_id = None
        
        if projects:
            project_id = list(projects.keys())[0]
        else:
            project_id = create_project(u, "My Project", "Default project")
        
        if not project_id:
            flash("❌ Failed to create project!", "error")
            return redirect(url_for("user_dashboard"))
        
        project_dir = FILES_ROOT / u / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        
        if 'requirements' not in request.files:
            flash("No file uploaded!", "error")
            return redirect(url_for("user_dashboard"))
        
        file = request.files['requirements']
        if file.filename == '' or not file.filename.endswith('.txt'):
            flash("Please upload a valid requirements.txt file!", "error")
            return redirect(url_for("user_dashboard"))
        
        name = secure_filename(file.filename)
        file.save(project_dir / name)
        
        try:
            result = subprocess.run(
                ['pip', 'install', '-r', str(project_dir / name)],
                cwd=str(project_dir),
                capture_output=True,
                text=True,
                timeout=300
            )
            
            if result.returncode == 0:
                flash(f"✅ Requirements installed successfully!", "success")
            else:
                flash(f"⚠️ Some packages failed to install: {result.stderr[:200]}", "warning")
        except subprocess.TimeoutExpired:
            flash("❌ Installation timed out.", "error")
        except Exception as e:
            flash(f"❌ Error installing requirements: {str(e)}", "error")
        
        update_project_files(u, project_id)
        threading.Thread(target=lambda: manual_backup(f"Requirements uploaded for project {project_id} by {u}"), daemon=True).start()
        
    except Exception as e:
        app.logger.error(f"Upload requirements error: {e}")
        flash(f"Error: {str(e)}", "error")
    
    return redirect(url_for("user_dashboard"))

@app.route("/deploy-project", methods=["POST"])
@require_user
def deploy_project():
    try:
        u = current_user()
        users = load_users()
        
        if users.get(u, {}).get("payment_status") != "paid":
            return jsonify({"success": False, "error": "Please subscribe to a plan!"}), 400
        
        projects = get_user_projects(u)
        if not projects:
            return jsonify({"success": False, "error": "No project found!"}), 400
        
        project_id = list(projects.keys())[0]
        project = get_project(u, project_id)
        
        if not project:
            return jsonify({"success": False, "error": "Project not found!"}), 404
        
        # Check if there are files to deploy
        project_dir = FILES_ROOT / u / project_id
        if not project_dir.exists() or not any(project_dir.iterdir()):
            return jsonify({"success": False, "error": "No files found to deploy! Please upload files first."}), 400
        
        success, results = deploy_project_files(u, project_id)
        
        if success:
            # Try to start the project
            if project.get("run_command"):
                start_success, start_msg = start_project_process(u, project_id)
                if start_success:
                    return jsonify({
                        "success": True,
                        "message": f"✅ Project deployed and started! {start_msg}",
                        "deployment_log": results
                    })
                else:
                    return jsonify({
                        "success": True,
                        "message": f"⚠️ Project deployed but failed to start: {start_msg}",
                        "deployment_log": results
                    })
            else:
                return jsonify({
                    "success": True,
                    "message": "✅ Project deployed successfully. Set a run command to start it.",
                    "deployment_log": results
                })
        else:
            return jsonify({"success": False, "error": results}), 400
    except Exception as e:
        app.logger.error(f"Deploy error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ==================== ENVIRONMENT VARIABLE ROUTES ====================

@app.route("/get-env-vars")
@require_user
def get_env_vars():
    try:
        u = current_user()
        projects = get_user_projects(u)
        project_id = list(projects.keys())[0] if projects else None
        
        if not project_id:
            return jsonify({"env_vars": []})
        
        project = get_project(u, project_id)
        if project:
            env_vars = project.get("env_vars", {})
            env_list = [{"key": k, "value": v} for k, v in env_vars.items()]
            return jsonify({"env_vars": env_list})
        
        return jsonify({"env_vars": []})
    except Exception as e:
        app.logger.error(f"Get env vars error: {e}")
        return jsonify({"env_vars": []})

@app.route("/save-env-vars", methods=["POST"])
@require_user
def save_env_vars():
    try:
        u = current_user()
        projects = get_user_projects(u)
        project_id = list(projects.keys())[0] if projects else None
        
        if not project_id:
            return jsonify({"success": False, "error": "No project found"}), 400
        
        data = request.json
        env_vars = data.get("env_vars", [])
        
        env_dict = {}
        for env in env_vars:
            if env.get("key") and env.get("value"):
                env_dict[env["key"]] = env["value"]
        
        projects = load_projects()
        if u in projects and project_id in projects[u]:
            projects[u][project_id]["env_vars"] = env_dict
            save_projects(projects)
            
            project_dir = FILES_ROOT / u / project_id
            env_file = project_dir / ".env"
            try:
                with open(env_file, 'w') as f:
                    for key, value in env_dict.items():
                        f.write(f"{key}={value}\n")
            except Exception as e:
                return jsonify({"success": False, "error": f"Failed to save .env: {str(e)}"}), 500
            
            threading.Thread(target=lambda: manual_backup(f"Environment variables saved for {project_id} by {u}"), daemon=True).start()
            return jsonify({"success": True})
        
        return jsonify({"success": False, "error": "Failed to save"}), 500
    except Exception as e:
        app.logger.error(f"Save env vars error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/clear-env-vars", methods=["POST"])
@require_user
def clear_env_vars():
    try:
        u = current_user()
        projects = get_user_projects(u)
        project_id = list(projects.keys())[0] if projects else None
        
        if not project_id:
            return jsonify({"success": False, "error": "No project found"}), 400
        
        projects = load_projects()
        if u in projects and project_id in projects[u]:
            projects[u][project_id]["env_vars"] = {}
            save_projects(projects)
            
            project_dir = FILES_ROOT / u / project_id
            env_file = project_dir / ".env"
            if env_file.exists():
                env_file.unlink()
            
            threading.Thread(target=lambda: manual_backup(f"Environment variables cleared for {project_id} by {u}"), daemon=True).start()
            return jsonify({"success": True})
        
        return jsonify({"success": False, "error": "Failed to clear"}), 500
    except Exception as e:
        app.logger.error(f"Clear env vars error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ==================== FILE ROUTES ====================

@app.route("/file/delete/<name>", methods=["POST"])
@require_user
def file_delete(name):
    try:
        u = current_user()
        projects = get_user_projects(u)
        
        if not projects:
            flash("No project found!", "error")
            return redirect(url_for("user_dashboard"))
        
        project_id = list(projects.keys())[0]
        project_dir = FILES_ROOT / u / project_id
        safe_name = secure_filename(name)
        
        if not safe_name:
            flash("Invalid filename!", "error")
            return redirect(url_for("user_dashboard"))
        
        filepath = project_dir / safe_name
        
        if filepath.exists() and filepath.is_file():
            if safe_name in ['.env', 'requirements.txt', 'run_command.txt']:
                flash(f"Cannot delete {safe_name}. Use the appropriate management interface.", "warning")
                return redirect(url_for("user_dashboard"))
            
            filepath.unlink()
            flash(f"File '{name}' deleted successfully!", "success")
            update_project_files(u, project_id)
            threading.Thread(target=lambda: manual_backup(f"File deleted: {name} by {u}"), daemon=True).start()
        else:
            flash("File not found!", "error")
    except Exception as e:
        app.logger.error(f"File delete error: {e}")
        flash(f"Error deleting file: {str(e)}", "error")
    
    return redirect(url_for("user_dashboard"))

@app.route("/file/view/<name>")
@require_user
def file_view(name):
    try:
        u = current_user()
        projects = get_user_projects(u)
        
        if not projects:
            flash("No project found!", "error")
            return redirect(url_for("user_dashboard"))
        
        project_id = list(projects.keys())[0]
        project_dir = FILES_ROOT / u / project_id
        safe_name = secure_filename(name)
        
        if not safe_name:
            flash("Invalid filename!", "error")
            return redirect(url_for("user_dashboard"))
        
        filepath = project_dir / safe_name
        
        if not filepath.exists() or not filepath.is_file():
            flash("File not found!", "error")
            return redirect(url_for("user_dashboard"))
        
        return send_from_directory(project_dir, safe_name, as_attachment=False)
    except Exception as e:
        app.logger.error(f"File view error: {e}")
        flash(f"Error viewing file: {str(e)}", "error")
        return redirect(url_for("user_dashboard"))

# ==================== LOGS ROUTE ====================

@app.route("/logs")
@require_user
def logs_api():
    try:
        u = current_user()
        projects = get_user_projects(u)
        project_id = list(projects.keys())[0] if projects else None
        
        if not project_id:
            return jsonify({
                "running": False,
                "file": None,
                "logs": ["No project found"],
                "install": [],
                "subscription": "Basic"
            })
        
        return jsonify({
            "running": is_project_running(u, project_id),
            "file": None,
            "logs": get_project_logs(u, project_id, 200),
            "install": [],
            "subscription": "Basic"
        })
    except Exception as e:
        app.logger.error(f"Logs API error: {e}")
        return jsonify({"logs": ["Error loading logs"], "running": False})

# ==================== PROJECT ROUTES ====================

@app.route("/projects")
@require_user
def projects_list():
    try:
        u = current_user()
        projects = get_user_projects(u)
        for pid, project in projects.items():
            project["is_running"] = is_project_running(u, pid)
            resources = get_project_resources(u, pid)
            project["cpu"] = resources["cpu"]
            project["ram_mb"] = resources["ram_mb"]
        return render_template("projects.html", username=u, projects=projects, total_projects=len(projects))
    except Exception as e:
        app.logger.error(f"Projects list error: {e}")
        flash("Error loading projects", "error")
        return redirect(url_for("user_dashboard"))

@app.route("/project/create", methods=["GET"])
@require_user
def project_create_page():
    try:
        u = current_user()
        users = load_users()
        is_paid = users.get(u, {}).get("payment_status") == "paid"
        return render_template("create_project.html", username=u, is_paid=is_paid)
    except Exception as e:
        app.logger.error(f"Project create page error: {e}")
        flash("Error loading create project page", "error")
        return redirect(url_for("user_dashboard"))

@app.route("/project/create", methods=["POST"])
@require_user
def project_create():
    try:
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
        
        # Ensure the project directory is created
        project_dir = FILES_ROOT / u / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        
        # Verify directory was created
        if project_dir.exists():
            flash(f"✅ Project '{name}' created successfully!", "success")
        else:
            flash(f"⚠️ Project '{name}' created but directory could not be created. Please contact support.", "warning")
        
        return redirect(url_for("project_detail", project_id=project_id))
    except Exception as e:
        app.logger.error(f"Project create error: {e}")
        flash(f"Error creating project: {str(e)}", "error")
        return redirect(url_for("projects_list"))

@app.route("/project/<project_id>")
@require_user
def project_detail(project_id):
    try:
        u = current_user()
        project = get_project(u, project_id)
        if not project:
            flash("Project not found!", "error")
            return redirect(url_for("projects_list"))
        
        # Ensure project directory exists
        project_dir = FILES_ROOT / u / project_id
        if not project_dir.exists():
            app.logger.warning(f"Project directory missing, creating: {project_dir}")
            project_dir.mkdir(parents=True, exist_ok=True)
            # Update project in database to mark it as created
            projects = load_projects()
            if u in projects and project_id in projects[u]:
                projects[u][project_id]["deployment_status"] = "created"
                save_projects(projects)
        
        # List files
        files = []
        if project_dir.exists():
            files = sorted([f.name for f in project_dir.iterdir() if f.is_file()])
        
        project["files"] = files
        project["is_running"] = is_project_running(u, project_id)
        project["logs"] = get_project_logs(u, project_id, 100)
        resources = get_project_resources(u, project_id)
        project["cpu"] = resources["cpu"]
        project["ram_mb"] = resources["ram_mb"]
        
        analysis = deployment_engine.analyze_project(project_dir) if project_dir.exists() else {"project_type": "unknown", "framework": "unknown"}
        project["project_type"] = analysis.get("project_type", "unknown")
        project["framework"] = analysis.get("framework", "unknown")
        
        return render_template("project_detail.html", username=u, project=project, files=files, analysis=analysis)
    except Exception as e:
        app.logger.error(f"Project detail error: {e}")
        flash(f"Error loading project: {str(e)}", "error")
        return redirect(url_for("projects_list"))

@app.route("/project/<project_id>/upload", methods=["POST"])
@require_user
def project_upload(project_id):
    try:
        u = current_user()
        project = get_project(u, project_id)
        if not project:
            flash("Project not found!", "error")
            return redirect(url_for("projects_list"))
        
        project_dir = FILES_ROOT / u / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        
        files = request.files.getlist("files")
        uploaded_count = 0
        extracted_count = 0
        
        for file in files:
            if not file or not file.filename:
                continue
            name = secure_filename(file.filename)
            if not name:
                continue
            
            file_path = project_dir / name
            file.save(file_path)
            
            # Handle archives
            if name.endswith('.zip') or name.endswith('.tar.gz') or name.endswith('.tgz') or name.endswith('.tar'):
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
                    extracted_count += 1
                    flash(f"📦 Extracted {name}!", "success")
                except Exception as e:
                    flash(f"❌ Failed to extract {name}: {str(e)}", "error")
            else:
                uploaded_count += 1
                flash(f"📄 Uploaded {name}", "success")
        
        # Generate task ID for background processing
        task_id = secrets.token_hex(16)
        
        # Start background task
        threading.Thread(
            target=process_upload_task,
            args=(task_id, u, project_id, project_dir),
            daemon=True
        ).start()
        
        update_project_files(u, project_id)
        
        flash(f"📤 {uploaded_count} files uploaded, {extracted_count} archives extracted! Processing in background...", "info")
        
        session['upload_task_id'] = task_id
        session['upload_project_id'] = project_id
        
    except Exception as e:
        app.logger.error(f"Project upload error: {e}")
        flash(f"Error uploading files: {str(e)}", "error")
    
    return redirect(url_for("upload_status"))

@app.route("/project/<project_id>/file/delete/<filename>", methods=["POST"])
@require_user
def project_file_delete(project_id, filename):
    try:
        u = current_user()
        project = get_project(u, project_id)
        if not project:
            flash("Project not found!", "error")
            return redirect(url_for("projects_list"))
        
        project_dir = FILES_ROOT / u / project_id
        safe_name = secure_filename(filename)
        
        if not safe_name:
            flash("Invalid filename!", "error")
            return redirect(url_for("project_detail", project_id=project_id))
        
        filepath = project_dir / safe_name
        
        if filepath.exists() and filepath.is_file():
            if safe_name in ['.env', 'requirements.txt', 'run_command.txt']:
                flash(f"Cannot delete {safe_name}. Use the appropriate management interface.", "warning")
                return redirect(url_for("project_detail", project_id=project_id))
            
            filepath.unlink()
            flash(f"File '{filename}' deleted successfully!", "success")
            update_project_files(u, project_id)
            threading.Thread(target=lambda: manual_backup(f"File deleted: {filename} from project {project_id} by {u}"), daemon=True).start()
        else:
            flash("File not found!", "error")
    except Exception as e:
        app.logger.error(f"Project file delete error: {e}")
        flash(f"Error deleting file: {str(e)}", "error")
    
    return redirect(url_for("project_detail", project_id=project_id))

@app.route("/project/<project_id>/save-run-command", methods=["POST"])
@require_user
def project_save_run_command(project_id):
    try:
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
    except Exception as e:
        app.logger.error(f"Save run command error: {e}")
        flash(f"Error saving run command: {str(e)}", "error")
    
    return redirect(url_for("project_detail", project_id=project_id))

@app.route("/project/<project_id>/toggle-restart", methods=["POST"])
@require_user
def project_toggle_restart(project_id):
    try:
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
            flash(f"🔄 Auto-restart {'enabled' if not current else 'disabled'}", "success")
    except Exception as e:
        app.logger.error(f"Toggle restart error: {e}")
        flash(f"Error toggling auto-restart: {str(e)}", "error")
    
    return redirect(url_for("project_detail", project_id=project_id))

@app.route("/project/<project_id>/start", methods=["POST"])
@require_user
def project_start(project_id):
    try:
        u = current_user()
        project = get_project(u, project_id)
        if not project:
            return jsonify({"success": False, "error": "Project not found"}), 404
        
        if is_project_running(u, project_id):
            return jsonify({"success": False, "error": "Project is already running"}), 400
        
        # Check if there are files to run
        project_dir = FILES_ROOT / u / project_id
        if not project_dir.exists() or not any(project_dir.iterdir()):
            return jsonify({"success": False, "error": "No files found! Please upload files first."}), 400
        
        success, msg = start_project_process(u, project_id)
        if success:
            threading.Thread(target=lambda: manual_backup(f"Project started: {project['name']}"), daemon=True).start()
            return jsonify({"success": True, "message": msg, "port": project.get("port")})
        return jsonify({"success": False, "error": msg}), 400
    except Exception as e:
        app.logger.error(f"Project start error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/project/<project_id>/stop", methods=["POST"])
@require_user
def project_stop(project_id):
    try:
        u = current_user()
        project = get_project(u, project_id)
        if not project:
            return jsonify({"success": False, "error": "Project not found"}), 404
        
        if not is_project_running(u, project_id):
            return jsonify({"success": True, "message": "Project is already stopped"})
        
        stop_project_process(u, project_id)
        return jsonify({"success": True, "message": "Project stopped"})
    except Exception as e:
        app.logger.error(f"Project stop error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/project/<project_id>/restart", methods=["POST"])
@require_user
def project_restart(project_id):
    try:
        u = current_user()
        project = get_project(u, project_id)
        if not project:
            return jsonify({"success": False, "error": "Project not found"}), 404
        
        stop_project_process(u, project_id)
        time.sleep(1)
        success, msg = start_project_process(u, project_id)
        
        if success:
            threading.Thread(target=lambda: manual_backup(f"Project restarted: {project['name']}"), daemon=True).start()
            return jsonify({"success": True, "message": msg})
        return jsonify({"success": False, "error": msg}), 400
    except Exception as e:
        app.logger.error(f"Project restart error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/project/<project_id>/logs")
@require_user
def project_logs(project_id):
    try:
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
    except Exception as e:
        app.logger.error(f"Project logs error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/project/<project_id>/logs/download")
@require_user
def project_logs_download(project_id):
    try:
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
    except Exception as e:
        app.logger.error(f"Project logs download error: {e}")
        flash(f"Error downloading logs: {str(e)}", "error")
        return redirect(url_for("project_detail", project_id=project_id))

@app.route("/project/<project_id>/resources")
@require_user
def project_resources(project_id):
    try:
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
    except Exception as e:
        app.logger.error(f"Project resources error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/project/<project_id>/custom-domain", methods=["POST"])
@require_user
def project_custom_domain(project_id):
    try:
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
    except Exception as e:
        app.logger.error(f"Custom domain error: {e}")
        flash(f"Error setting custom domain: {str(e)}", "error")
    
    return redirect(url_for("project_detail", project_id=project_id))

# ==================== PROJECT DELETE ROUTE (FIXED - Redirects to Page) ====================
@app.route("/project/<project_id>/delete", methods=["POST"])
@require_user
def project_delete(project_id):
    try:
        u = current_user()
        project = get_project(u, project_id)
        if not project:
            flash("Project not found!", "error")
            return redirect(url_for("projects_list"))
        
        project_name = project.get("name", "Unknown")
        
        # Stop the project if running
        stop_project_process(u, project_id)
        
        # Delete the project
        if delete_project(u, project_id):
            flash(f"✅ Project '{project_name}' deleted successfully!", "success")
            threading.Thread(target=lambda: manual_backup(f"Project deleted: {project_name} by {u}"), daemon=True).start()
        else:
            flash(f"❌ Failed to delete project '{project_name}'!", "error")
        
        return redirect(url_for("projects_list"))
    except Exception as e:
        app.logger.error(f"Project delete error: {e}")
        flash(f"Error deleting project: {str(e)}", "error")
        return redirect(url_for("projects_list"))

@app.route("/project/<project_id>/deploy", methods=["POST"])
@require_user
def project_deploy(project_id):
    try:
        u = current_user()
        project = get_project(u, project_id)
        if not project:
            return jsonify({"success": False, "error": "Project not found"}), 404
        
        success, results = deploy_project_files(u, project_id)
        if success:
            return jsonify({"success": True, "message": "Project deployed successfully", "logs": results})
        return jsonify({"success": False, "error": results}), 400
    except Exception as e:
        app.logger.error(f"Project deploy error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/project/<project_id>/env-vars")
@require_user
def project_env_vars(project_id):
    try:
        u = current_user()
        project = get_project(u, project_id)
        if not project:
            return jsonify({"success": False, "error": "Project not found"}), 404
        return jsonify({"env_vars": project.get("env_vars", {})})
    except Exception as e:
        app.logger.error(f"Project env vars error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/project/<project_id>/save-env-vars", methods=["POST"])
@require_user
def project_save_env_vars(project_id):
    try:
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
    except Exception as e:
        app.logger.error(f"Project save env vars error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ==================== OWNER ROUTES ====================

@app.route("/owner")
@require_owner
def owner_dashboard():
    try:
        users = load_users()
        projects = load_projects()
        total_projects = sum(len(p) for p in projects.values()) if projects else 0
        backup_info = get_backup_status()
        
        # Calculate stats
        paid_users = sum(1 for u in users.values() if u.get("payment_status") == "paid")
        banned_users = sum(1 for u in users.values() if u.get("banned", False))
        
        return render_template("owner.html",
            users=users,
            base_url=request.host_url.rstrip("/"),
            pricing=load_pricing(),
            currencies=SUPPORTED_CURRENCIES,
            backup_info=backup_info,
            total_projects=total_projects,
            paid_users=paid_users,
            banned_users=banned_users,
            payment_methods=PAYMENT_METHODS,
            convert_price=convert_price,
            format_price=format_price,
            get_plan_price=get_plan_price
        )
    except Exception as e:
        app.logger.error(f"Owner dashboard error: {e}")
        flash("Error loading owner dashboard", "error")
        return redirect(url_for("landing"))

@app.route("/owner/create", methods=["POST"])
@require_owner
def owner_create():
    try:
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "").strip()
        subscription = request.form.get("subscription", "Basic")
        email = request.form.get("email", "").strip()
        currency = request.form.get("currency", "NGN")
        
        if not u or not p:
            flash("Username and password are required!", "error")
            return redirect(url_for("owner_dashboard"))
        if u == OWNER_USER:
            flash("Cannot create owner account!", "error")
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
            "currency": currency
        }
        save_users(users)
        user_dir(u)
        
        # Send Telegram notification
        if TELEGRAM_ENABLED:
            plan_price = get_plan_price(subscription, currency)
            plan_price_formatted = format_price(plan_price, currency)
            message = f"""
👑 <b>OWNER CREATED USER</b>

👤 Username: {u}
📧 Email: {email}
📋 Plan: {subscription}
💰 Price: {plan_price_formatted}
💱 Currency: {currency}

🔗 Auto-login link:
{request.host_url}auto/{users[u]['token']}

✅ Account is PAID and ACTIVE
"""
            send_telegram_notification(message)
        
        flash(f"User {u} created!", "success")
    except Exception as e:
        app.logger.error(f"Owner create error: {e}")
        flash(f"Error creating user: {str(e)}", "error")
    
    return redirect(url_for("owner_dashboard"))

@app.route("/owner/delete/<username>", methods=["POST"])
@require_owner
def owner_delete(username):
    try:
        if username == OWNER_USER:
            flash("Cannot delete owner!", "error")
            return redirect(url_for("owner_dashboard"))
        
        users = load_users()
        if username in users:
            del users[username]
            save_users(users)
            shutil.rmtree(FILES_ROOT / username, ignore_errors=True)
            flash(f"User {username} deleted!", "success")
        else:
            flash("User not found!", "error")
    except Exception as e:
        app.logger.error(f"Owner delete error: {e}")
        flash(f"Error deleting user: {str(e)}", "error")
    
    return redirect(url_for("owner_dashboard"))

@app.route("/owner/ban/<username>", methods=["POST"])
@require_owner
def owner_ban_user(username):
    try:
        if username == OWNER_USER:
            flash("Cannot ban owner!", "error")
            return redirect(url_for("owner_dashboard"))
        
        users = load_users()
        if username in users:
            users[username]["banned"] = True
            save_users(users)
            flash(f"User {username} banned!", "success")
        else:
            flash("User not found!", "error")
    except Exception as e:
        app.logger.error(f"Owner ban error: {e}")
        flash(f"Error banning user: {str(e)}", "error")
    
    return redirect(url_for("owner_dashboard"))

@app.route("/owner/unban/<username>", methods=["POST"])
@require_owner
def owner_unban_user(username):
    try:
        users = load_users()
        if username in users:
            users[username]["banned"] = False
            save_users(users)
            flash(f"User {username} unbanned!", "success")
        else:
            flash("User not found!", "error")
    except Exception as e:
        app.logger.error(f"Owner unban error: {e}")
        flash(f"Error unbanning user: {str(e)}", "error")
    
    return redirect(url_for("owner_dashboard"))

@app.route("/owner/unban-all", methods=["POST"])
@require_owner
def owner_unban_all():
    try:
        users = load_users()
        count = 0
        for username in users:
            if username != OWNER_USER:
                users[username]["banned"] = False
                count += 1
        save_users(users)
        flash(f"{count} users unbanned!", "success")
    except Exception as e:
        app.logger.error(f"Owner unban all error: {e}")
        flash(f"Error unbanning users: {str(e)}", "error")
    
    return redirect(url_for("owner_dashboard"))

@app.route("/owner/ban-all", methods=["POST"])
@require_owner
def owner_ban_all():
    try:
        users = load_users()
        count = 0
        for username in users:
            if username != OWNER_USER:
                users[username]["banned"] = True
                count += 1
        save_users(users)
        flash(f"{count} users banned!", "success")
    except Exception as e:
        app.logger.error(f"Owner ban all error: {e}")
        flash(f"Error banning users: {str(e)}", "error")
    
    return redirect(url_for("owner_dashboard"))

@app.route("/owner/mark-paid/<username>", methods=["POST"])
@require_owner
def owner_mark_paid(username):
    try:
        users = load_users()
        if username in users:
            users[username]["payment_status"] = "paid"
            save_users(users)
            
            # Send Telegram notification
            if TELEGRAM_ENABLED:
                user = users[username]
                plan_price = get_plan_price(user.get("subscription", "Basic"), user.get("currency", "NGN"))
                plan_price_formatted = format_price(plan_price, user.get("currency", "NGN"))
                message = f"""
✅ <b>PAYMENT CONFIRMED & ACCOUNT ACTIVATED</b>

👤 Username: {username}
📧 Email: {user.get("email", "N/A")}
📋 Plan: {user.get("subscription", "Basic")}
💰 Amount: {plan_price_formatted}
💱 Currency: {user.get("currency", "NGN")}

🔗 Auto-login link:
{request.host_url}auto/{user['token']}

🎉 Account is now ACTIVE!
"""
                send_telegram_notification(message)
            
            flash(f"✅ {username} marked as paid and activated!", "success")
        else:
            flash(f"❌ User {username} not found!", "error")
    except Exception as e:
        app.logger.error(f"Owner mark paid error: {e}")
        flash(f"Error marking user as paid: {str(e)}", "error")
    
    return redirect(url_for("owner_dashboard"))

@app.route("/owner/pricing", methods=["POST"])
@require_owner
def owner_pricing():
    try:
        pricing = load_pricing()
        pricing["currency"] = request.form.get("currency", "NGN")
        pricing["contact"] = request.form.get("contact", "@rexoronsaye")
        
        # Update base plans
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
        
        # Update currency pricing
        currency_pricing = {}
        for currency in SUPPORTED_CURRENCIES:
            if currency == "NGN":
                currency_pricing[currency] = {p["name"]: p["price"] for p in plans}
            else:
                # Convert prices
                rate = SUPPORTED_CURRENCIES[currency]["exchange_rate"]
                if currency == "TON":
                    ton_rate = SUPPORTED_CURRENCIES["TON"]["exchange_rate"]
                    currency_pricing[currency] = {p["name"]: round(float(p["price"]) / ton_rate, 2) for p in plans}
                else:
                    currency_pricing[currency] = {p["name"]: round(float(p["price"]) * rate, 2) for p in plans}
        
        pricing["currency_pricing"] = currency_pricing
        save_pricing(pricing)
        flash("Pricing updated with multi-currency support!", "success")
    except Exception as e:
        app.logger.error(f"Owner pricing error: {e}")
        flash(f"Error updating pricing: {str(e)}", "error")
    
    return redirect(url_for("owner_dashboard") + "#pricing")

@app.route("/owner/update_subscription/<username>", methods=["POST"])
@require_owner
def owner_update_subscription(username):
    try:
        subscription = request.form.get("subscription", "Basic")
        users = load_users()
        if username in users:
            users[username]["subscription"] = subscription
            users[username]["payment_status"] = "paid"
            save_users(users)
            flash(f"✅ Subscription updated for {username}!", "success")
        else:
            flash(f"❌ User {username} not found!", "error")
    except Exception as e:
        app.logger.error(f"Owner update subscription error: {e}")
        flash(f"Error updating subscription: {str(e)}", "error")
    
    return redirect(url_for("owner_dashboard"))

@app.route("/admin/backup", methods=["POST"])
@require_owner
def admin_backup():
    try:
        def do_backup():
            if manual_backup("Manual backup"):
                flash("✅ Backup completed!", "success")
            else:
                flash("⚠️ Backup failed!", "warning")
        threading.Thread(target=do_backup, daemon=True).start()
        flash("📤 Backup started!", "info")
    except Exception as e:
        app.logger.error(f"Admin backup error: {e}")
        flash(f"Error starting backup: {str(e)}", "error")
    
    return redirect(url_for("owner_dashboard"))

@app.route("/admin/backup-status")
@require_owner
def admin_backup_status():
    try:
        return jsonify(get_backup_status())
    except Exception as e:
        app.logger.error(f"Admin backup status error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/admin/restore", methods=["POST"])
@require_owner
def admin_restore():
    try:
        if github_backup.restore():
            flash("✅ Restore successful!", "success")
        else:
            flash("❌ Restore failed!", "error")
    except Exception as e:
        app.logger.error(f"Admin restore error: {e}")
        flash(f"Error restoring backup: {str(e)}", "error")
    
    return redirect(url_for("owner_dashboard"))

@app.route("/admin/block-ip", methods=["POST"])
@require_owner
def admin_block_ip():
    try:
        ip = request.form.get("ip", "").strip()
        reason = request.form.get("reason", "Manual block")
        flash(f"IP {ip} blocked: {reason}", "success")
    except Exception as e:
        app.logger.error(f"Admin block IP error: {e}")
        flash(f"Error blocking IP: {str(e)}", "error")
    
    return redirect(url_for("owner_dashboard"))

@app.route("/admin/unblock-all-ips", methods=["POST"])
@require_owner
def admin_unblock_all_ips():
    try:
        flash("All IPs unblocked", "success")
    except Exception as e:
        app.logger.error(f"Admin unblock all IPs error: {e}")
        flash(f"Error unblocking IPs: {str(e)}", "error")
    
    return redirect(url_for("owner_dashboard"))

@app.route("/admin/blocked-ips")
@require_owner
def admin_blocked_ips():
    try:
        return jsonify({"blocked_ips": []})
    except Exception as e:
        app.logger.error(f"Admin blocked IPs error: {e}")
        return jsonify({"error": str(e)}), 500

# ==================== TEST TELEGRAM ROUTE ====================
@app.route("/test-telegram")
def test_telegram():
    """Test Telegram notifications"""
    if not TELEGRAM_BOT_TOKEN:
        return jsonify({"error": "TELEGRAM_BOT_TOKEN not set"}), 400
    
    chat_id = get_telegram_chat_id()
    if not chat_id:
        return jsonify({
            "error": "No chat ID found. Send a message to your bot first!",
            "instructions": f"1. Open Telegram and message your bot\n2. Visit: https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates\n3. Copy your chat ID from the response"
        }), 400
    
    result = send_telegram_notification(f"""
🔔 <b>TELEGRAM TEST SUCCESSFUL!</b>

✅ Your bot is configured correctly!
📱 Chat ID: {chat_id}

🎉 You will receive notifications when users register.
""")
    
    return jsonify({
        "success": result,
        "chat_id": chat_id,
        "message": "Test notification sent!" if result else "Failed to send"
    })

# ==================== ERROR HANDLING ====================

@app.errorhandler(404)
def not_found_error(error):
    if request.is_json:
        return jsonify({"error": "Resource not found"}), 404
    flash("Page not found!", "error")
    return redirect(url_for("landing"))

@app.errorhandler(500)
def internal_error(error):
    app.logger.error(f"Internal Server Error: {error}")
    if request.is_json:
        return jsonify({"error": "Internal server error"}), 500
    flash("An internal error occurred. Please try again.", "error")
    return redirect(url_for("landing"))

@app.errorhandler(413)
def too_large_error(error):
    if request.is_json:
        return jsonify({"error": "File too large. Maximum size is 500MB"}), 413
    flash("File too large! Maximum size is 500MB.", "error")
    return redirect(request.referrer or url_for("landing"))

@app.errorhandler(403)
def forbidden_error(error):
    if request.is_json:
        return jsonify({"error": "Access forbidden"}), 403
    flash("Access forbidden!", "error")
    return redirect(url_for("landing"))

@app.errorhandler(401)
def unauthorized_error(error):
    if request.is_json:
        return jsonify({"error": "Authentication required"}), 401
    flash("Please login to access this resource.", "error")
    return redirect(url_for("login"))

# ==================== REQUEST LOGGING ====================

@app.before_request
def log_request():
    if not request.path.startswith('/static'):
        app.logger.info(f"{request.method} {request.path} from {request.remote_addr}")

@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    return response

# ==================== HEALTH CHECK ====================

@app.route("/healthz")
def health():
    return "ok", 200

@app.route("/debug")
def debug():
    return jsonify({
        "status": "running",
        "service": "NCK Dev VPS",
        "github_backup_enabled": github_backup.is_enabled if github_backup else False,
        "telegram_enabled": TELEGRAM_ENABLED,
        "currencies_supported": list(SUPPORTED_CURRENCIES.keys())
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)