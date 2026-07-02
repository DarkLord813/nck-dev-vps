import os
import json
import time
import base64
import shutil
import threading
import requests
from pathlib import Path
from datetime import datetime
from collections import Counter

# GitHub Configuration (from environment variables)
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO_OWNER = os.environ.get("GITHUB_REPO_OWNER", "")
GITHUB_REPO_NAME = os.environ.get("GITHUB_REPO_NAME", "")
GITHUB_BACKUP_BRANCH = os.environ.get("GITHUB_BACKUP_BRANCH", "main")
GITHUB_BACKUP_PATH = os.environ.get("GITHUB_BACKUP_PATH", "backups/database.json")
GITHUB_BACKUP_DIR = os.path.dirname(GITHUB_BACKUP_PATH)  # "backups"

# Max number of versioned backups to keep
MAX_BACKUP_VERSIONS = 10

# Safety thresholds
MIN_USER_THRESHOLD = 1

# Global lock to prevent concurrent GitHub pushes
_github_push_lock = threading.Lock()
_last_backup_time = 0
_MIN_BACKUP_INTERVAL = 30

class GitHubBackupSystem:
    """Versioned GitHub backup system - keeps multiple backup versions"""
    
    def __init__(self, data_dir, files_root):
        self.data_dir = data_dir
        self.files_root = files_root
        self.is_enabled = self._check_config()
        self._session = self._create_session()
        self._last_backup_data = None
        self._backup_count = 0
        self._restore_success = False
        self._backup_history = []
        self._last_github_stats = None
        
        # Parse backup path: "backups/database.json" -> base name "database"
        self.backup_dir = GITHUB_BACKUP_DIR
        self.backup_filename = os.path.basename(GITHUB_BACKUP_PATH)  # "database.json"
        self.backup_basename = os.path.splitext(self.backup_filename)[0]  # "database"
        self.backup_extension = os.path.splitext(self.backup_filename)[1]  # ".json"
        
        if self.is_enabled:
            print(f"✅ GitHub Backup enabled: {GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}")
            print(f"📁 Backup path: {GITHUB_BACKUP_PATH}")
            print(f"📋 Versioned backups: {self.backup_basename}(1){self.backup_extension}, etc.")
            print(f"🛡️ Smart Backup: Only backups if local has MORE data than GitHub")
        else:
            print("⚠️ GitHub Backup disabled — data will be lost on restart")
    
    def _check_config(self):
        """Check if GitHub backup is properly configured"""
        return bool(
            GITHUB_TOKEN and
            GITHUB_REPO_OWNER and
            GITHUB_REPO_NAME and
            GITHUB_REPO_OWNER not in ('', 'your-username') and
            GITHUB_REPO_NAME not in ('', 'your-repo')
        )
    
    def _create_session(self):
        """Create HTTP session with connection pooling"""
        session = requests.Session()
        session.mount('https://', requests.adapters.HTTPAdapter(
            pool_connections=4,
            pool_maxsize=16,
            max_retries=2
        ))
        return session
    
    @property
    def _headers(self):
        return {
            'Authorization': f'token {GITHUB_TOKEN}',
            'Accept': 'application/vnd.github.v3+json'
        }
    
    def _get_file_api_url(self, file_path):
        """Get GitHub API URL for a specific file path"""
        return f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/contents/{file_path}"
    
    def _get_versioned_path(self, version_number):
        """Get the versioned file path: database(1).json, database(2).json, etc."""
        if version_number == 0:
            return f"{self.backup_dir}/{self.backup_filename}"
        else:
            return f"{self.backup_dir}/{self.backup_basename}({version_number}){self.backup_extension}"
    
    def _get_local_stats(self):
        """Get detailed statistics from local data"""
        try:
            users_file = self.data_dir / "users.json"
            pricing_file = self.data_dir / "pricing.json"
            
            users_data = {}
            users_count = 0
            paid_count = 0
            
            if users_file.exists():
                with open(users_file, 'r') as f:
                    users_data = json.load(f)
                    users_count = len(users_data)
                    for user in users_data.values():
                        if user.get('payment_status') == 'paid':
                            paid_count += 1
            
            files_count = 0
            total_file_size = 0
            file_types = {}
            
            if self.files_root.exists():
                for user_dir in self.files_root.iterdir():
                    if user_dir.is_dir():
                        for file_path in user_dir.iterdir():
                            if file_path.is_file():
                                files_count += 1
                                total_file_size += file_path.stat().st_size
                                ext = file_path.suffix.lower()
                                file_types[ext] = file_types.get(ext, 0) + 1
            
            return {
                'users_count': users_count,
                'paid_count': paid_count,
                'files_count': files_count,
                'total_file_size_mb': round(total_file_size / (1024 * 1024), 2),
                'file_types': file_types,
                'has_data': users_count > 0 or files_count > 0
            }
        except Exception as e:
            print(f"⚠️ Local stats error: {e}")
            return {'users_count': 0, 'paid_count': 0, 'files_count': 0, 'total_file_size_mb': 0, 'file_types': {}, 'has_data': False}
    
    def _get_github_stats(self):
        """Get statistics from the latest GitHub backup (with caching)"""
        if self._last_github_stats and time.time() - self._last_github_stats.get('_timestamp', 0) < 60:
            return self._last_github_stats
        
        try:
            # Try to get the main backup file
            api_url = self._get_file_api_url(GITHUB_BACKUP_PATH)
            r = self._session.get(
                api_url,
                headers=self._headers,
                params={'ref': GITHUB_BACKUP_BRANCH},
                timeout=15
            )
            if r.status_code != 200:
                self._last_github_stats = None
                return None
            
            content = r.json().get('content', '')
            if not content:
                self._last_github_stats = None
                return None
            
            json_str = base64.b64decode(content.replace('\n', '')).decode()
            data = json.loads(json_str)
            
            stats = data.get('stats', {})
            result = {
                'users_count': stats.get('users_count', 0),
                'files_count': stats.get('files_count', 0),
                'timestamp': data.get('timestamp', 'unknown'),
                'total_file_size_mb': stats.get('total_file_size_mb', 0),
                '_timestamp': time.time()
            }
            
            self._last_github_stats = result
            return result
        except Exception as e:
            print(f"⚠️ Failed to get GitHub stats: {e}")
            self._last_github_stats = None
            return None
    
    def _get_all_github_backups(self):
        """Get list of all backup files on GitHub"""
        try:
            api_url = self._get_file_api_url(self.backup_dir)
            r = self._session.get(
                api_url,
                headers=self._headers,
                params={'ref': GITHUB_BACKUP_BRANCH},
                timeout=15
            )
            if r.status_code != 200:
                return []
            
            files = r.json()
            backup_files = []
            
            # Pattern: database.json, database(1).json, database(2).json, etc.
            pattern = f"{self.backup_basename}"
            
            for file_info in files:
                if file_info['type'] == 'file':
                    filename = file_info['name']
                    # Match: database.json or database(1).json
                    if filename == self.backup_filename:
                        backup_files.append({
                            'path': file_info['path'],
                            'name': filename,
                            'sha': file_info.get('sha'),
                            'version': 0,
                            'size': file_info.get('size', 0)
                        })
                    elif filename.startswith(f"{self.backup_basename}(") and filename.endswith(self.backup_extension):
                        # Extract version number: database(1).json -> 1
                        try:
                            version_str = filename.replace(f"{self.backup_basename}(", "").replace(self.backup_extension, "")
                            version = int(version_str)
                            backup_files.append({
                                'path': file_info['path'],
                                'name': filename,
                                'sha': file_info.get('sha'),
                                'version': version,
                                'size': file_info.get('size', 0)
                            })
                        except ValueError:
                            pass
            
            # Sort by version number
            backup_files.sort(key=lambda x: x['version'])
            
            return backup_files
        except Exception as e:
            print(f"⚠️ Failed to list backup files: {e}")
            return []
    
    def _get_next_version(self, backup_files):
        """Get the next available version number"""
        if not backup_files:
            return 0
        
        # Get all existing version numbers
        versions = [f['version'] for f in backup_files]
        
        # Find the next available version
        version = 0
        while version in versions:
            version += 1
        
        return version
    
    def _upload_file_to_github(self, file_path, content, commit_message):
        """Upload a file to GitHub"""
        try:
            # Get SHA if file exists
            api_url = self._get_file_api_url(file_path)
            r = self._session.get(
                api_url,
                headers=self._headers,
                params={'ref': GITHUB_BACKUP_BRANCH},
                timeout=15
            )
            
            file_sha = None
            if r.status_code == 200:
                file_sha = r.json().get('sha')
            
            # Encode content
            encoded = base64.b64encode(content.encode()).decode()
            
            payload = {
                'message': commit_message,
                'content': encoded,
                'branch': GITHUB_BACKUP_BRANCH
            }
            if file_sha:
                payload['sha'] = file_sha
            
            r = self._session.put(
                api_url,
                headers=self._headers,
                json=payload,
                timeout=60
            )
            
            if r.status_code in (200, 201):
                return True, file_path
            else:
                return False, f"Failed: {r.status_code}"
        except Exception as e:
            return False, str(e)
    
    def _cleanup_old_backups(self, backup_files):
        """Delete old backup versions beyond MAX_BACKUP_VERSIONS"""
        if len(backup_files) <= MAX_BACKUP_VERSIONS:
            return
        
        # Sort by version
        sorted_backups = sorted(backup_files, key=lambda x: x['version'])
        
        # Keep the latest MAX_BACKUP_VERSIONS
        to_delete = sorted_backups[:-MAX_BACKUP_VERSIONS]
        
        for backup in to_delete:
            try:
                api_url = self._get_file_api_url(backup['path'])
                payload = {
                    'message': f'Removed old backup: {backup["name"]}',
                    'sha': backup['sha'],
                    'branch': GITHUB_BACKUP_BRANCH
                }
                self._session.delete(
                    api_url,
                    headers=self._headers,
                    json=payload,
                    timeout=30
                )
                print(f"🗑️ Removed old backup: {backup['name']}")
            except Exception as e:
                print(f"⚠️ Failed to remove old backup: {e}")
    
    def _should_backup(self, local_stats):
        """
        SMART COMPARISON: Check if local data is GREATER than GitHub data
        """
        github_stats = self._get_github_stats()
        
        if not github_stats:
            return True, "No existing backup on GitHub"
        
        local_users = local_stats['users_count']
        github_users = github_stats['users_count']
        local_files = local_stats['files_count']
        github_files = github_stats['files_count']
        
        # LOCAL has MORE users than GitHub -> ALLOW
        if local_users > github_users:
            return True, f"Local has more users ({local_users} > {github_users})"
        
        # LOCAL has MORE files than GitHub -> ALLOW
        if local_files > github_files:
            return True, f"Local has more files ({local_files} > {github_files})"
        
        # SAME users but MORE files -> ALLOW
        if local_users == github_users and local_files > github_files:
            return True, f"Same users but more files ({local_files} > {github_files})"
        
        # SAME counts but content changed -> ALLOW
        if local_users == github_users and local_files == github_files:
            local_hash = self._get_data_hash()
            if self._last_backup_data != local_hash:
                return True, "Data content changed"
        
        # LOCAL has LESS users than GitHub -> BLOCK
        if local_users < github_users:
            return False, f"Local has fewer users ({local_users} < {github_users}) - would lose data!"
        
        # LOCAL has LESS files than GitHub -> BLOCK
        if local_files < github_files and github_files > 0:
            return False, f"Local has fewer files ({local_files} < {github_files}) - would lose data!"
        
        # LOCAL has 0 users but GitHub has users -> BLOCK
        if local_users == 0 and github_users > 0:
            return False, "Local has 0 users but GitHub has users - fresh deploy detected!"
        
        return True, "All safety checks passed"
    
    def _get_data_hash(self):
        """Get a hash of current data to detect changes"""
        try:
            users_file = self.data_dir / "users.json"
            pricing_file = self.data_dir / "pricing.json"
            
            data = {}
            
            if users_file.exists():
                with open(users_file, 'r') as f:
                    data['users'] = json.load(f)
            
            if pricing_file.exists():
                with open(pricing_file, 'r') as f:
                    data['pricing'] = json.load(f)
            
            files_list = []
            if self.files_root.exists():
                for user_dir in self.files_root.iterdir():
                    if user_dir.is_dir():
                        for file_path in user_dir.iterdir():
                            if file_path.is_file():
                                files_list.append(f"{user_dir.name}/{file_path.name}")
            
            data['files'] = sorted(files_list)
            
            return json.dumps(data, sort_keys=True)
        except Exception:
            return str(time.time())
    
    def create_backup_data(self):
        """Create backup data from current VPS panel data"""
        try:
            users_file = self.data_dir / "users.json"
            pricing_file = self.data_dir / "pricing.json"
            
            users_data = {}
            pricing_data = {}
            
            if users_file.exists():
                with open(users_file, 'r') as f:
                    users_data = json.load(f)
            
            if pricing_file.exists():
                with open(pricing_file, 'r') as f:
                    pricing_data = json.load(f)
            
            files_list = []
            total_file_size = 0
            if self.files_root.exists():
                for user_dir in self.files_root.iterdir():
                    if user_dir.is_dir():
                        for file_path in user_dir.iterdir():
                            if file_path.is_file():
                                files_list.append({
                                    "user": user_dir.name,
                                    "filename": file_path.name,
                                    "size": file_path.stat().st_size
                                })
                                total_file_size += file_path.stat().st_size
            
            backup = {
                "timestamp": datetime.now().isoformat(),
                "version": "1.0",
                "stats": {
                    "users_count": len(users_data),
                    "files_count": len(files_list),
                    "total_file_size_mb": round(total_file_size / (1024 * 1024), 2)
                },
                "data": {
                    "users": users_data,
                    "pricing": pricing_data,
                    "files": files_list
                }
            }
            
            return backup
        except Exception as e:
            print(f"❌ Backup data creation error: {e}")
            return None
    
    def backup_to_github(self, reason="Auto backup"):
        """
        VERSIONED BACKUP: Creates database.json, then database(1).json, database(2).json, etc.
        Always updates database.json with latest data, and creates a numbered copy.
        """
        global _last_backup_time
        
        if not self.is_enabled:
            return False
        
        # Get local stats
        local_stats = self._get_local_stats()
        
        # Check minimum threshold
        if local_stats['users_count'] < MIN_USER_THRESHOLD and not local_stats['has_data']:
            print(f"ℹ️ Skipping backup: Only {local_stats['users_count']} users (minimum {MIN_USER_THRESHOLD} required)")
            return False
        
        # SMART COMPARISON: Should we backup?
        should_backup, reason_text = self._should_backup(local_stats)
        
        if not should_backup:
            print(f"⚠️ Backup BLOCKED: {reason_text}")
            return False
        
        # Rate limit check
        current_time = time.time()
        if current_time - _last_backup_time < _MIN_BACKUP_INTERVAL:
            print(f"ℹ️ Skipping backup: Too soon since last backup")
            return True
        
        # Check if data has actually changed
        current_hash = self._get_data_hash()
        if self._last_backup_data == current_hash:
            print(f"ℹ️ Skipping backup: No data changes detected")
            return True
        
        with _github_push_lock:
            try:
                backup_data = self.create_backup_data()
                if not backup_data:
                    return False
                
                # Convert to JSON string
                json_str = json.dumps(backup_data, indent=2)
                
                # Get list of existing backups
                backup_files = self._get_all_github_backups()
                
                # Get next version number for the numbered copy
                next_version = self._get_next_version(backup_files)
                
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                stats = backup_data["stats"]
                
                # === STEP 1: Update main database.json ===
                commit_msg = f"{reason} | {timestamp} | Users: {stats['users_count']} | Files: {stats['files_count']}"
                success, result = self._upload_file_to_github(
                    GITHUB_BACKUP_PATH,
                    json_str,
                    commit_msg
                )
                
                if not success:
                    print(f"❌ Failed to update {self.backup_filename}: {result}")
                    return False
                
                print(f"✅ Updated {self.backup_filename}")
                
                # === STEP 2: Create numbered copy database(1).json, etc. ===
                if next_version > 0:
                    versioned_path = self._get_versioned_path(next_version)
                    versioned_commit_msg = f"{reason} | {timestamp} | Version {next_version} | Users: {stats['users_count']}"
                    
                    success, result = self._upload_file_to_github(
                        versioned_path,
                        json_str,
                        versioned_commit_msg
                    )
                    
                    if success:
                        print(f"✅ Created {self.backup_basename}({next_version}){self.backup_extension}")
                    else:
                        print(f"⚠️ Failed to create versioned backup: {result}")
                
                # === STEP 3: Cleanup old backups (keep MAX_BACKUP_VERSIONS) ===
                backup_files = self._get_all_github_backups()
                self._cleanup_old_backups(backup_files)
                
                self._last_backup_data = current_hash
                _last_backup_time = current_time
                self._backup_count += 1
                
                self._backup_history.append({
                    'timestamp': timestamp,
                    'users': stats['users_count'],
                    'files': stats['files_count'],
                    'version': next_version,
                    'reason': reason
                })
                if len(self._backup_history) > 20:
                    self._backup_history.pop(0)
                
                print(f"✅ Versioned backup successful (#{self._backup_count})")
                return True
                    
            except Exception as e:
                print(f"❌ Backup error: {e}")
                return False
    
    def force_restore_from_github(self, version=None):
        """
        FORCE RESTORE - Restore from GitHub backup.
        If version is None, restores the latest (database.json).
        If version is specified, restores that numbered backup.
        """
        if not self.is_enabled:
            return False
        
        try:
            # Determine which file to restore
            if version is not None and version > 0:
                restore_path = self._get_versioned_path(version)
                restore_name = f"{self.backup_basename}({version}){self.backup_extension}"
                print(f"🔄 FORCE RESTORE: Fetching versioned backup: {restore_name}")
            else:
                restore_path = GITHUB_BACKUP_PATH
                restore_name = self.backup_filename
                print("🔄 FORCE RESTORE: Fetching latest backup from GitHub...")
            
            r = self._session.get(
                self._get_file_api_url(restore_path),
                headers=self._headers,
                params={'ref': GITHUB_BACKUP_BRANCH},
                timeout=60
            )
            
            if r.status_code != 200:
                # If latest not found, try versioned backups
                if version is None:
                    print("⚠️ Latest backup not found, checking versioned backups...")
                    backup_files = self._get_all_github_backups()
                    if backup_files:
                        latest = backup_files[-1]  # Highest version
                        if latest['version'] > 0:
                            return self.force_restore_from_github(latest['version'])
                print(f"❌ No backup found on GitHub ({r.status_code})")
                return False
            
            file_data = r.json()
            content = file_data.get('content', '')
            
            if not content:
                print("❌ Empty backup content")
                return False
            
            # Decode base64
            json_str = base64.b64decode(content.replace('\n', '')).decode()
            backup_data = json.loads(json_str)
            
            data = backup_data.get("data", {})
            
            # Check if backup has any data
            if not data.get("users") and not data.get("pricing") and not data.get("files"):
                print("⚠️ Backup exists but has no data (empty)")
                return False
            
            # Save a copy of current data before overwriting
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = self.data_dir / "pre_restore_backups"
            backup_dir.mkdir(exist_ok=True)
            
            # Backup current data if it exists
            users_file = self.data_dir / "users.json"
            if users_file.exists():
                shutil.copy(users_file, backup_dir / f"users_{timestamp}.json")
            
            pricing_file = self.data_dir / "pricing.json"
            if pricing_file.exists():
                shutil.copy(pricing_file, backup_dir / f"pricing_{timestamp}.json")
            
            # Restore users.json
            users_file = self.data_dir / "users.json"
            if "users" in data:
                with open(users_file, 'w') as f:
                    json.dump(data["users"], f, indent=2)
                print(f"✅ FORCE RESTORE: Restored {len(data['users'])} users from {restore_name}")
            
            # Restore pricing.json
            pricing_file = self.data_dir / "pricing.json"
            if "pricing" in data:
                with open(pricing_file, 'w') as f:
                    json.dump(data["pricing"], f, indent=2)
                print("✅ FORCE RESTORE: Restored pricing data")
            
            # Get metadata
            timestamp = backup_data.get("timestamp", "unknown")
            stats = backup_data.get("stats", {})
            print(f"✅ FORCE RESTORE Complete! Backup from: {timestamp}")
            print(f"   📊 Users: {stats.get('users_count', 0)} | Files: {stats.get('files_count', 0)}")
            
            self._restore_success = True
            self._last_backup_data = self._get_data_hash()
            
            return True
            
        except Exception as e:
            print(f"❌ Force restore error: {e}")
            return False
    
    def restore_on_startup(self):
        """Restore on startup - ALWAYS restores from GitHub"""
        if not self.is_enabled:
            print("⚠️ GitHub backup not configured, skipping restore")
            return False
        
        print("🔄 STARTUP: Forcing restore from GitHub backup...")
        result = self.force_restore_from_github()
        
        if result:
            print("✅ STARTUP RESTORE SUCCESSFUL!")
        else:
            print("ℹ️ No backup found on GitHub - starting fresh")
        
        return result
    
    def get_backup_info(self):
        """Get info about latest backup"""
        if not self.is_enabled:
            return {"enabled": False}
        
        try:
            backup_files = self._get_all_github_backups()
            local_stats = self._get_local_stats()
            github_stats = self._get_github_stats()
            
            return {
                "enabled": True,
                "last_backup": github_stats.get('timestamp', 'Never') if github_stats else 'Never',
                "backup_count": self._backup_count,
                "restore_success": self._restore_success,
                "local_stats": local_stats,
                "github_stats": github_stats,
                "backup_files": [{'name': f['name'], 'version': f['version'], 'size': f['size']} for f in backup_files],
                "backup_history": self._backup_history[-5:]
            }
        except Exception as e:
            return {"enabled": True, "error": str(e), "backup_count": self._backup_count}

# Global instance
github_backup = None

def init_github_backup_force(data_dir, files_root):
    """Initialize GitHub backup with FORCE RESTORE on startup"""
    global github_backup
    github_backup = GitHubBackupSystem(data_dir, files_root)
    
    if github_backup.is_enabled:
        print("🔄 GitHub backup initialized - FORCE RESTORE enabled on startup")
        restored = github_backup.restore_on_startup()
        if restored:
            print("✅ Data restored from GitHub backup successfully!")
        else:
            print("ℹ️ No backup found - starting with empty database")
        
        start_auto_backup()
    else:
        print("⚠️ GitHub backup not configured - data will be lost on restart")
    
    return github_backup

def start_auto_backup():
    """Start automatic backup every 60 seconds with versioning"""
    def backup_loop():
        consecutive_failures = 0
        while True:
            time.sleep(60)
            try:
                if github_backup and github_backup.is_enabled:
                    local_stats = github_backup._get_local_stats()
                    should_backup, reason = github_backup._should_backup(local_stats)
                    
                    if should_backup:
                        success = github_backup.backup_to_github("Auto backup")
                        if success:
                            consecutive_failures = 0
                        else:
                            consecutive_failures += 1
                    else:
                        print(f"ℹ️ Auto-backup skipped: {reason}")
                        
                if consecutive_failures > 5:
                    print(f"⚠️ {consecutive_failures} consecutive backup failures - waiting 5 minutes")
                    time.sleep(240)
                    consecutive_failures = 0
                    
            except Exception as e:
                print(f"⚠️ Auto-backup error: {e}")
                consecutive_failures += 1
    
    thread = threading.Thread(target=backup_loop, daemon=True)
    thread.start()
    print("🛡️ Auto-backup thread started (versioned backups every 60 seconds)")

def manual_backup(reason="Manual backup"):
    """Trigger manual backup"""
    if github_backup:
        return github_backup.backup_to_github(reason)
    return False

def get_backup_status():
    """Get backup status"""
    if github_backup:
        return github_backup.get_backup_info()
    return {"enabled": False}

def has_data():
    """Check if there's any data in the system"""
    if github_backup:
        stats = github_backup._get_local_stats()
        return stats['has_data']
    return False

def force_restore(version=None):
    """Force restore from GitHub (latest or specific version)"""
    if github_backup:
        return github_backup.force_restore_from_github(version)
    return False