# NCK Dev VPS Panel

A lightweight web-based VPS-like panel — deployable on Choreo. The owner creates users, and each user can upload, run, restart, stop their Python/Node/Shell files, install modules, and view real-time logs.

## Owner Credentials
- Username: `DarkLord813`
- Password: `DarkLord813`

## Features

**Owner:**
- Create new users (username, password, subscription plan)
- Each user gets an **auto-login link** (shareable)
- Update user subscriptions (Basic, Pro, Premium)
- Delete users
- Manage pricing plans
- **Versioned GitHub Backup System** - Automatic backups on every change

**User:**
- Self-registration with email
- Multiple files upload (200MB total)
- `.py` / `.js` / `.sh` files Start/Stop/Restart
- Real-time logs (auto-refresh)
- Modules install: `pip install <module>` or `npm install <module>`
- File view and delete
- Subscription-based features (Basic, Pro, Premium)

**Subscription Plans:**
| Plan | Price | Duration | Features |
|------|-------|----------|----------|
| Basic | ₦2,500 | Monthly | Python only, 1GB RAM, Basic support |
| Pro | ₦15,000 | Yearly | Python/Node/Shell, pip/npm, 2GB RAM, Priority support |
| Premium | ₦25,000 | Yearly | All features, 4GB RAM, Dedicated help, Best value! |

**Multi-Currency Support:**
- NGN (₦) - Nigerian Naira
- USD ($) - US Dollar
- EUR (€) - Euro
- GBP (£) - British Pound

**Payment Integration:**
- Flutterwave payment gateway
- Supports card, USSD, bank transfer, mobile money

## Deploy on Choreo

1. Push this folder to the **root** of a new GitHub repository.
2. Go to [Choreo Console](https://console.choreo.dev/)
3. Create a new **Project** → **Service** component
4. Connect your GitHub repository
5. Choreo will automatically detect Python buildpack
6. Set Environment Variables (see below)
7. Click **Deploy**

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `SECRET_KEY` | Flask session encryption key | Yes |
| `FLW_PUBLIC_KEY` | Flutterwave public key | Yes |
| `FLW_SECRET_KEY` | Flutterwave secret key | Yes |
| `FLW_ENCRYPTION_KEY` | Flutterwave encryption key | Yes |
| `GITHUB_TOKEN` | GitHub Personal Access Token | Recommended |
| `GITHUB_REPO_OWNER` | GitHub username (e.g., DarkLord813) | Recommended |
| `GITHUB_REPO_NAME` | **Backup repository name** (e.g., `nck-vps-backup`) | Recommended |
| `GITHUB_BACKUP_PATH` | Backup file path (e.g., `backups/database.json`) | Optional |
| `GITHUB_BACKUP_BRANCH` | GitHub branch (default: `main`) | Optional |
| `PORT` | Port (default: `8080`) | Optional |

---

## 🔐 GitHub Backup Setup (Separate Repository)

### Step 1: Create a Private Backup Repository

1. Go to [GitHub](https://github.com)
2. Click **New repository**
3. **Repository name:** `nck-vps-backup` (or your preferred name)
4. **Visibility:** **Private** 🔒
5. Click **Create repository**

**Important:** This is a **SEPARATE repository** from your app code repository. It will only store backup data.

### Step 2: Generate GitHub Personal Access Token

1. Go to **GitHub Settings** → **Developer settings** → **Personal access tokens** → **Tokens (classic)**
2. Click **Generate new token (classic)**
3. **Note:** `NCK VPS Backup`
4. **Expiration:** Choose a reasonable expiry (or "No expiration")
5. **Scopes:** Select **`repo`** (full control of private repositories)
6. Click **Generate token**
7. **COPY THE TOKEN IMMEDIATELY!** (You won't see it again)

### Step 3: Add Environment Variables on Choreo

| Variable | Example Value |
|----------|---------------|
| `GITHUB_TOKEN` | `ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` |
| `GITHUB_REPO_OWNER` | `DarkLord813` |
| `GITHUB_REPO_NAME` | `nck-vps-backup` |
| `GITHUB_BACKUP_BRANCH` | `main` |
| `GITHUB_BACKUP_PATH` | `backups/database.json` |

---

## 💾 Versioned Backup System

The panel automatically backs up all data to your **PRIVATE GitHub backup repository**:

### How It Works:

- **Auto-Backup:** Every user registration, payment, file upload, or data change triggers a backup
- **Versioned:** Keeps last 10 versions (`database.json`, `database(1).json`, `database(2).json`, etc.)
- **Auto-Restore:** On every service restart, data is automatically restored from GitHub
- **Smart Comparison:** Only backs up if local data has MORE users/files than GitHub (prevents data loss)
- **Manual Control:** Admins can manually backup, restore latest, or restore specific versions

### Backup Structure on GitHub (Private Repository):
