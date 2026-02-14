# Shamrock

A restaurant social web app that lets guests at different tables connect with each other — send messages and buy drinks for people at other tables.

## Features

- **Table Selection** — Pick your table number (1-8)
- **Real-time Table Map** — See which tables are occupied
- **Send Messages** — Tap a table to send preset messages
- **Buy Drinks** — Send a symbolic drink to another table
- **Accept/Decline** — Recipients can respond to incoming offers
- **Check Out** — Leave your table when done

## Tech Stack

- **Backend:** Flask + Flask-SocketIO (Python)
- **Frontend:** HTML, CSS, JavaScript (vanilla)
- **Database:** SQLite
- **Real-time:** WebSockets

## Setup

```bash
# Clone the repo
git clone https://github.com/ansonwnt/project_shamrock.git
cd project_shamrock

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the app
python app.py
```

## Usage

1. Open http://localhost:5001 in your browser
2. Select your table number and tap "Join Table"
3. See other occupied tables on the map
4. Tap an occupied table to send a message or drink
5. Receive notifications when someone sends you something
6. Tap "Check Out" when leaving

## Testing with Multiple Users

Open two browser windows (or use incognito for the second):
- Window 1: Join Table 1
- Window 2: Join Table 5
- Send messages between them to see real-time updates

## Testing on Mobile (Same WiFi)

1. Find your computer's IP: `ipconfig getifaddr en0`
2. On your phone, open: `http://YOUR_IP:5001`

## Project Structure

```
Shamrock/
├── app.py              # Flask server + WebSocket handlers
├── models.py           # SQLite database functions
├── requirements.txt    # Python dependencies
├── templates/
│   ├── base.html       # Shared layout
│   ├── index.html      # Landing page (table selection)
│   ├── tables.html     # Main page (table map + interactions)
│   └── menu.html       # Drink menu
└── static/
    ├── style.css       # Dark theme, mobile-first CSS
    └── app.js          # Shared JavaScript
```

## Limitations

Current setup is designed for a single restaurant (8 tables, ~30 users max).

For production scale, you would need:
- PostgreSQL instead of SQLite
- Redis for session management
- Multiple server instances with load balancing

## License

MIT
