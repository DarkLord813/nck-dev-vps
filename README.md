# NCK Dev VPS Panel

A lightweight web-based VPS-like panel with multi-currency support, deployable on Render. Users can upload, run, restart, stop Python/Node/Shell files, install modules, and view real-time logs.

## Features

### Owner
- Create/delete users
- Ban/unban users
- Update user subscriptions
- Mark payments as received
- View all users with search
- Backup/restore data to GitHub
- **Multi-currency support** (NGN, USD, EUR, GBP, TON)
- **Multiple payment methods** (Bank Transfer, TON, Gift Cards)

### User
- Self-registration with email
- Multiple currency options
- Project creation and management
- File uploads (ZIP/TAR auto-extract)
- Run Python/Node/Shell scripts
- Real-time logs
- Environment variables
- Auto-restart on crash

### Payment Methods
- 💳 **Nigerian Bank Transfer** 
- 💎 **TON (Telegram Open Network)**
- 🎁 **Gift Cards** (Amazon, Steam, Google Play, Apple, PlayStation, Xbox)

### Currencies Supported
| Currency | Symbol | Name |
|----------|--------|------|
| NGN | ₦ | Nigerian Naira |
| USD | $ | US Dollar |
| EUR | € | Euro |
| GBP | £ | British Pound |
| TON | ⧫ | TON Coin |

## Deploy on Render

1. Push to GitHub
2. Go to render.com → New Web Service
3. Connect repository
4. Set environment variables (see below)
5. Deploy!

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `SECRET_KEY` | Flask session key | ✅ Yes |
| `GITHUB_TOKEN` | GitHub PAT (repo scope) | For backups |
| `GITHUB_REPO_NAME` | Backup repo name | For backups |
| `GITHUB_REPO_OWNER` | GitHub username | For backups |
| `TELEGRAM_BOT_TOKEN` | Bot token | For notifications |
| `TELEGRAM_CHAT_ID` | Chat ID | For notifications |
| `TON_WALLET` | TON wallet address | For TON payments |
| `PORT` | 8080 | Optional |

## Owner Credentials

- Username: `DarkLord813`
- Password: `DarkLord813`

## License

MIT