# 📬 Telecommunicator

> A self-hosted messenger with end-to-end encryption (E2EE) for messages and files. Built with FastAPI backend and Flet-based client for cross-platform support (mobile & desktop).

[![License](https://img.shields.io/badge/License-AGPLv3-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-green)](https://www.python.org/downloads/)
[![Status](https://img.shields.io/badge/Status-Active_Development-orange)](#support)

---

## 🔥 Features

| Feature | Description                                                                                                  |
|---------|--------------------------------------------------------------------------------------------------------------|
| 🔒 **End-to-End Encryption** | Messages encrypted using Signal Protocol's Double Ratchet algorithm(only for DMs, group e2ee is in progress) |
| 🏠 **Self-Hosted** | Full control over your data with Docker deployment                                                           |
| 📱 **Cross-Platform Client** | Available for mobile (Android/iOS) and desktop via Flet                                                      |
| 🌐 **Federation Support** | Multi-server federation capabilities(like matrix)                                                            |
| 💾 **Encrypted Storage** | Local message store encrypted at rest using AES-256-GCM                                                      |
| 🔑 **Key Backup** | Secure identity key backup and recovery from server                                                          |
| 🎨 **Theming** | Customizable themes with system theme detection                                                              |
| 🌍 **Localization** | Multi-language support (i18n)                                                                                |
| 📝 **Rich Messaging** | Markdown support, formatting toolbar, emoji picker                                                           |

---

## 🏗️ Architecture

### Backend (`/app`)

| Component | Technology |
|-----------|------------|
| Framework | FastAPI with async support |
| Database | SQLite with Alembic migrations |
| Authentication | JWT-based auth with bcrypt password hashing |
| WebSocket | Real-time messaging via websockets |
| Rate Limiting | SlowAPI for request throttling |
| Federation | Cross-server communication support |

### Client (`/client`)

| Component | Technology |
|-----------|------------|
| Framework | Flet (Python-based Flutter wrapper) |
| Crypto | X25519 key exchange, Double Ratchet protocol |
| Storage | Encrypted local storage for sessions and messages |
| UI Components | Login, registration, chat list, room view, profile, settings |

---

## 🛠️ Quick Start

### Prerequisites

- Python 3.12+
- Docker & Docker Compose (for server deployment)

### Server Setup

```bash
# Clone the repository
git clone https://github.com/yourusername/telecommunicator.git
cd telecommunicator

# Configure environment
cp .env.example .env
nano .env  # Edit with your configuration

# Start with Docker
docker compose up -d
```

> The API will be available at `http://localhost:8000`

### Client Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Run the client
python main.py

# Build for mobile (requires Flet build tools)
flet build apk --release
# or
flet build ios --release
```

---

## 📁 Project Structure

```
telecommunicator/
├── /app                    # Backend
│   ├── models/            # Data models
│   ├── routers/           # API endpoints
│   ├── utils/             # Utilities & helpers
│   ├── crypto/            # Encryption modules
│   ├── config.py          # Configuration
│   └── main.py           # Application entry
├── /client                # Flet-based client
│   ├── screens/           # UI screens
│   ├── widgets/           # Reusable components
│   ├── services/          # API & network calls
│   └── main.py           # App entry point
├── docker-compose.yml     # Main deployment
├── docker-compose.federation.yml  # Federation setup
├── requirements.txt       # Dependencies
└── README.md              # This file
```

---

## ⚙️ Technology Stack

### Backend

| Package | Version | Purpose |
|---------|---------|---------|
| FastAPI | 0.141.1 | Web framework |
| SQLAlchemy | 2.0 (async) | ORM |
| Alembic | latest | Migrations |
| python-jose | latest | JWT handling |
| cryptography | latest | E2EE primitives |
| passlib | latest | Password hashing |

### Client

| Package | Version | Purpose |
|---------|---------|---------|
| Flet | 0.84.0 | UI Framework |
| httpx | latest | HTTP client |
| websockets | latest | WebSocket support |
| cryptography | latest | E2EE implementation |
| python-i18n | latest | Internationalization |

---

## 🔐 Security

- ✅ **E2EE**: All messages encrypted with Double Ratchet protocol
- ✅ **Forward Secrecy**: Message keys are burned after use
- ✅ **Post-Compromise Security**: Session heals after DH ratchet steps
- ✅ **Encrypted At-Rest**: Local storage encrypted with keys derived from identity key
- ✅ **Secure Key Backup**: Identity keys backed up to server for recovery

---

## 🧪 Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=app --cov=client -v
```

---

## 🌐 Federation

Multi-server federation is supported via `docker-compose.federation.yml`. See configuration details in the federation compose file.

```bash
# Start federation setup
docker compose -f docker-compose.federation.yml up -d
```

---

## 🚀 Future Development Roadmap

### Planned Features

#### Automatic Node Setup
- [ ] Deploy server nodes on VPS directly through mobile app
- [ ] Simplified one-click deployment for non-technical users
- [ ] Automated SSL/TLS certificate management
- [ ] Health monitoring and auto-recovery

#### Group E2EE
- [ ] Implement end-to-end encryption for group chats
- [ ] Sender Keys protocol or MLS (Messaging Layer Security)
- [ ] Secure group member management
- [ ] Encrypted group metadata

#### Flutter Client Rewrite
- [ ] Migrate from Flet to native Flutter
- [ ] Reason: Technical limitations with Flet on mobile platforms
- [ ] Benefits: Better performance, native feel, broader platform support
- [ ] Improved battery efficiency and resource usage

#### Backend Optimization
- [ ] Performance improvements for high-load scenarios
- [ ] Database query optimization
- [ ] Connection pooling enhancements
- [ ] Caching strategies for frequently accessed data
- [ ] Code refactoring and technical debt reduction
- [ ] Enhanced monitoring and logging

---

## 🤝 Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📄 License

This project is open-source. See LICENSE file for details.

---

## 💬 Support

For issues, questions, or contributions, please [open an issue on the GitHub repository](https://github.com/amogusgggy/telecommunicator/issues).

> ⚠️ **Note:** This project is under active development. Some features may be experimental or subject to change.

---

