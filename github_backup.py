import os
import json
import time
import base64
import shutil
import threading
import requests
from pathlib import Path
from datetime import datetime

class GitHubBackupSystem:
    """Versioned GitHub backup system - keeps multiple backup versions"""
    
    def __init__(self, data_dir, files_root):
        self.data_dir = data_dir
        self.files_root = files_root
        
        # ========== READ FROM ENVIRONMENT VARIABLES ==========
        self.token = os.environ.get("GITHUB_TOKEN", "")
        self.repo_owner = os.environ.get("GITHUB_REPO_OWNER", "")
        self.repo_name = os.environ.get("GITHUB_REPO_NAME", "")
        self.branch = os.environ.get("GITHUB_BACKUP_BRANCH", "main")
        self.backup_path = os.environ.get("GITHUB_BACKUP_PATH", "backups/database.json")
        self.backup_dir = os.path.dirname(self.backup_path)
        # ====================================================
        
        # Print what we found
        print(f"=== GITHUB BACKUP INIT ===")
        print(f"Token: {'SET' if self.token else 'MISSING'}")
        print(f"Repo Owner: {self.repo_owner}")
        print(f"Repo Name: {self.repo_name}")
        print(f"Branch: {self.branch}")
        print(f"Backup Path: {self.backup_path}")
        print(f"===========================")
        
        # Check if configured properly
        self.is_enabled = bool(
            self.token and
            self.repo_owner and
            self.repo_name and
            self.repo_owner not in ('', 'your-username') and
            self.repo_name not in ('', 'your-repo')
        )
        
        print(f"GitHub Backup is {'ENABLED' if self.is_enabled else 'DISABLED'}")
        
        self._session = self._create_session()
        self._last_backup_data = None
        self._backup_count = 0
        self._restore_success = False
        self._backup_history = []
        self._last_github_stats = None
        
        # Parse backup path
        self.backup_filename = os.path.basename(self.backup_path)
        self.backup_basename = os.path.splitext(self.backup_filename)[0]
        self.backup_extension = os.path.splitext(self.backup_filename)[1]
        
        if self.is_enabled:
            print(f"Backup path: {self.backup_path}")
        else:
            print("GitHub Backup disabled — data will be lost on restart")
    
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
            'Authorization': f'token {self.token}',
            'Accept': 'application/vnd.github.v3+json'
        }
    
    def _get_file_api_url(self, file_path):
        return f"https://api.github.com/repos/{self.repo_owner}/{self.repo_name}/contents/{file_path}"
    
    def _get_versioned_path(self, version_number):
        if version_number == 0:
            return f"{self.backup_dir}/{self.backup_filename}"
        else:
            return f"{self.backup_dir}/{self.backup_basename}({version_number}){self.backup_extension}"
    
    def _get_local_stats(self):
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
            
            if self.files_root.exists():
                for user_dir in self.files_root.iterdir():
                    if user_dir.is_dir():
                        for file_path in user_dir.iterdir():
                            if file_path.is_file():
                                files_count += 1
                                total_file_size += file_path.stat().st_size
            
            return {
                'users_count': users_count,
                'paid_count': paid_count,
                'files_count': files_count,
                'total_file_size_mb': round(total_file_size / (1024 * 1024), 2),
                'has_data': users_count > 0 or files_count > 0
            }
        except Exception as e:
            print(f"Local stats error: {e}")
            return {'users_count': 0, 'paid_count': 0, 'files_count': 0, 'total_file_size_mb': 0, 'has_data': False}
    
    def _get_github_stats(self):
        if self._last_github_stats and time.time() - self._last_github_stats.get('_timestamp', 0) < 60:
            return self._last_github_stats
        
        try:
            api_url = self._get_file_api_url(self.backup_path)
            r = self._session.get(
                api_url,
                headers=self._headers,
                params={'ref': self.branch},
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
            print(f"Failed to get GitHub stats: {e}")
            self._last_github_stats = None
            return None
    
    def _get_all_github_backups(self):
        try:
            api_url = self._get_file_api_url(self.backup_dir)
            r = self._session.get(
                api_url,
                headers=self._headers,
                params={'ref': self.branch},
                timeout=15
            )
            if r.status_code != 200:
                return []
            
            files = r.json()
            backup_files = []
            
            for file_info in files:
                if file_info['type'] == 'file':
                    filename = file_info['name']
                    if filename == self.backup_filename:
                        backup_files.append({
                            'path': file_info['path'],
                            'name': filename,
                            'sha': file_info.get('sha'),
                            'version': 0,
                            'size': file_info.get('size', 0)
                        })
                    elif filename.startswith(f"{self.backup_basename}(") and filename.endswith(self.backup_extension):
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
            
            backup_files.sort(key=lambda x: x['version'])
            return backup_files
        except Exception as e:
            print(f"Failed to list backup files: {e}")
            return []
    
    def _get_next_version(self, backup_files):
        if not backup_files:
            return 0
        
        versions = [f['version'] for f in backup_files]
        version = 0
        while version in versions:
            version += 1
        return version
    
    def _upload_file_to_github(self, file_path, content, commit_message):
        try:
            api_url = self._get_file_api_url(file_path)
            r = self._session.get(
                api_url,
                headers=self._headers,
                params={'ref': self.branch},
                timeout=15
            )
            
            file_sha = None
            if r.status_code == 200:
                file_sha = r.json().get('sha')
            
            encoded = base64.b64encode(content.encode()).decode()
            
            payload = {
                'message': commit_message,
                'content': encoded,
                'branch': self.branch
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
        MAX_BACKUP_VERSIONS = 10
        if len(backup_files) <= MAX_BACKUP_VERSIONS:
            return
        
        sorted_backups = sorted(backup_files, key=lambda x: x['version'])
        to_delete = sorted_backups[:-MAX_BACKUP_VERSIONS]
        
        for backup in to_delete:
            try:
                api_url = self._get_file_api_url(backup['path'])
                payload = {
                    'message': f'Removed old backup: {backup["name"]}',
                    'sha': backup['sha'],
                    'branch': self.branch
                }
                self._session.delete(
                    api_url,
                    headers=self._headers,
                    json=payload,
                    timeout=30
                )
                print(f"Removed old backup: {backup['name']}")
            except Exception as e:
                print(f"Failed to remove old backup: {e}")
    
    def _should_backup(self, local_stats):
        MIN_USER_THRESHOLD = 1
        github_stats = self._get_github_stats()
        
        if not github_stats:
            return True, "No existing backup on GitHub"
        
        local_users = local_stats['users_count']
        github_users = github_stats['users_count']
        local_files = local_stats['files_count']
        github_files = github_stats['files_count']
        
        if local_users > github_users:
            return True, f"Local has more users ({local_users} > {github_users})"
        
        if local_files > github_files:
            return True, f"Local has more files ({local_files} > {github_files})"
        
        if local_users == github_users and local_files > github_files:
            return True, f"Same users but more files ({local_files} > {github_files})"
        
        if local_users == github_users and local_files == github_files:
            local_hash = self._get_data_hash()
            if self._last_backup_data != local_hash:
                return True, "Data content changed"
        
        if local_users < github_users:
            return False, f"Local has fewer users ({local_users} < {github_users})"
        
        if local_files < github_files and github_files > 0:
            return False, f"Local has fewer files ({local_files} < {github_files})"
        
        if local_users == 0 and github_users > 0:
            return False, "Local has 0 users but GitHub has users"
        
        return True, "All safety checks passed"
    
    def _get_data_hash(self):
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
            print(f"Backup data creation error: {e}")
            return None
    
    def backup_to_github(self, reason="Auto backup"):
        _last_backup_time = 0
        _MIN_BACKUP_INTERVAL = 30
        
        if not self.is_enabled:
            return False
        
        local_stats = self._get_local_stats()
        
        if local_stats['users_count'] < 1 and not local_stats['has_data']:
            print(f"Skipping backup: Only {local_stats['users_count']} users")
            return False
        
        should_backup, reason_text = self._should_backup(local_stats)
        
        if not should_backup:
            print(f"Backup BLOCKED: {reason_text}")
            return False
        
        current_time = time.time()
        if current_time - _last_backup_time < _MIN_BACKUP_INTERVAL:
            print("Skipping backup: Too soon since last backup")
            return True
        
        current_hash = self._get_data_hash()
        if self._last_backup_data == current_hash:
            print("Skipping backup: No data changes detected")
            return True
        
        with threading.Lock():
            try:
                backup_data = self.create_backup_data()
                if not backup_data:
                    return False
                
                json_str = json.dumps(backup_data, indent=2)
                backup_files = self._get_all_github_backups()
                next_version = self._get_next_version(backup_files)
                
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                stats = backup_data["stats"]
                
                commit_msg = f"{reason} | {timestamp} | Users: {stats['users_count']} | Files: {stats['files_count']}"
                success, result = self._upload_file_to_github(
                    self.backup_path,
                    json_str,
                    commit_msg
                )
                
                if not success:
                    print(f"Failed to update {self.backup_filename}: {result}")
                    return False
                
                print(f"Updated {self.backup_filename}")
                
                if next_version > 0:
                    versioned_path = self._get_versioned_path(next_version)
                    versioned_commit_msg = f"{reason} | {timestamp} | Version {next_version} | Users: {stats['users_count']}"
                    
                    success, result = self._upload_file_to_github(
                        versioned_path,
                        json_str,
                        versioned_commit_msg
                    )
                    
                    if success:
                        print(f"Created {self.backup_basename}({next_version}){self.backup_extension}")
                    else:
                        print(f"Failed to create versioned backup: {result}")
                
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
                
                print(f"Versioned backup successful (#{self._backup_count})")
                return True
                    
            except Exception as e:
                print(f"Backup error: {e}")
                return False
    
    def force_restore_from_github(self, version=None):
        if not self.is_enabled:
            return False
        
        try:
            if version is not None and version > 0:
                restore_path = self._get_versioned_path(version)
                restore_name = f"{self.backup_basename}({version}){self.backup_extension}"
                print(f"FORCE RESTORE: Fetching versioned backup: {restore_name}")
            else:
                restore_path = self.backup_path
                restore_name = self.backup_filename
                print("FORCE RESTORE: Fetching latest backup from GitHub...")
            
            r = self._session.get(
                self._get_file_api_url(restore_path),
                headers=self._headers,
                params={'ref': self.branch},
                timeout=60
            )
            
            if r.status_code != 200:
                if version is None:
                    print("Latest backup not found, checking versioned backups...")
                    backup_files = self._get_all_github_backups()
                    if backup_files:
                        latest = backup_files[-1]
                        if latest['version'] > 0:
                            return self.force_restore_from_github(latest['version'])
                print(f"No backup found on GitHub ({r.status_code})")
                return False
            
            file_data = r.json()
            content = file_data.get('content', '')
            
            if not content:
                print("Empty backup content")
                return False
            
            json_str = base64.b64decode(content.replace('\n', '')).decode()
            backup_data = json.loads(json_str)
            
            data = backup_data.get("data", {})
            
            if not data.get("users") and not data.get("pricing") and not data.get("files"):
                print("Backup exists but has no data (empty)")
                return False
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = self.data_dir / "pre_restore_backups"
            backup_dir.mkdir(exist_ok=True)
            
            users_file = self.data_dir / "users.json"
            if users_file.exists():
                shutil.copy(users_file, backup_dir / f"users_{timestamp}.json")
            
            pricing_file = self.data_dir / "pricing.json"
            if pricing_file.exists():
                shutil.copy(pricing_file, backup_dir / f"pricing_{timestamp}.json")
            
            users_file = self.data_dir / "users.json"
            if "users" in data:
                with open(users_file, 'w') as f:
                    json.dump(data["users"], f, indent=2)
                print(f"FORCE RESTORE: Restored {len(data['users'])} users from {restore_name}")
            
            pricing_file = self.data_dir / "pricing.json"
            if "pricing" in data:
                with open(pricing_file, 'w') as f:
                    json.dump(data["pricing"], f, indent=2)
                print("FORCE RESTORE: Restored pricing data")
            
            timestamp = backup_data.get("timestamp", "unknown")
            stats = backup_data.get("stats", {})
            print(f"FORCE RESTORE Complete! Backup from: {timestamp}")
            print(f"   Users: {stats.get('users_count', 0)} | Files: {stats.get('files_count', 0)}")
            
            self._restore_success = True
            self._last_backup_data = self._get_data_hash()
            
            return True
            
        except Exception as e:
            print(f"Force restore error: {e}")
            return False
    
    def restore_on_startup(self):
        if not self.is_enabled:
            print("GitHub backup not configured, skipping restore")
            return False
        
        print("STARTUP: Forcing restore from GitHub backup...")
        result = self.force_restore_from_github()
        
        if result:
            print("STARTUP RESTORE SUCCESSFUL!")
        else:
            print("No backup found on GitHub - starting fresh")
        
        return result
    
    def get_backup_info(self):
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
    global github_backup
    
    # Read from environment
    token = os.environ.get("GITHUB_TOKEN", "")
    repo_owner = os.environ.get("GITHUB_REPO_OWNER", "")
    repo_name = os.environ.get("GITHUB_REPO_NAME", "")
    branch = os.environ.get("GITHUB_BACKUP_BRANCH", "main")
    backup_path = os.environ.get("GITHUB_BACKUP_PATH", "backups/database.json")
    
    print(f"=== INIT GITHUB BACKUP ===")
    print(f"Token: {'SET' if token else 'MISSING'}")
    print(f"Repo Owner: {repo_owner}")
    print(f"Repo Name: {repo_name}")
    print(f"Branch: {branch}")
    print(f"Backup Path: {backup_path}")
    print(f"==========================")
    
    github_backup = GitHubBackupSystem(data_dir, files_root)
    
    if github_backup.is_enabled:
        print("GitHub backup initialized - FORCE RESTORE enabled on startup")
        restored = github_backup.restore_on_startup()
        if restored:
            print("Data restored from GitHub backup successfully!")
        else:
            print("No backup found - starting with empty database")
        
        start_auto_backup()
    else:
        print("GitHub backup not configured - data will be lost on restart")
        print("Please set: GITHUB_TOKEN, GITHUB_REPO_OWNER, GITHUB_REPO_NAME")
    
    return github_backup

def start_auto_backup():
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
                        print(f"Auto-backup skipped: {reason}")
                        
                if consecutive_failures > 5:
                    print(f"{consecutive_failures} consecutive backup failures - waiting 5 minutes")
                    time.sleep(240)
                    consecutive_failures = 0
                    
            except Exception as e:
                print(f"Auto-backup error: {e}")
                consecutive_failures += 1
    
    thread = threading.Thread(target=backup_loop, daemon=True)
    thread.start()
    print("Auto-backup thread started (versioned backups every 60 seconds)")

def manual_backup(reason="Manual backup"):
    if github_backup:
        return github_backup.backup_to_github(reason)
    return False

def get_backup_status():
    if github_backup:
        return github_backup.get_backup_info()
    return {"enabled": False}

def has_data():
    if github_backup:
        stats = github_backup._get_local_stats()
        return stats['has_data']
    return False

def force_restore(version=None):
    if github_backup:
        return github_backup.force_restore_from_github(version)
    return False