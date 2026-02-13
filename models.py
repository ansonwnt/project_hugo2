import sqlite3
from datetime import datetime
import os

DATABASE = 'shamrock.db'

def get_db():
    """Get database connection."""
    conn = sqlite3.connect(DATABASE, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=5000')
    return conn

def init_db():
    """Initialize the database."""
    conn = get_db()
    cursor = conn.cursor()

    # Settings table (key-value)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')

    # Activity log
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            description TEXT NOT NULL,
            session_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Messages table - stores messages and drink offers (user-to-user)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_session TEXT NOT NULL,
            to_session TEXT NOT NULL,
            message_type TEXT NOT NULL,
            content TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Profiles table - user profiles with name, photo, and online status
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            photo_url TEXT,
            color_frame TEXT,
            is_online BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Add columns if missing (existing DBs)
    try:
        cursor.execute('ALTER TABLE profiles ADD COLUMN color_frame TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute('ALTER TABLE profiles ADD COLUMN is_online BOOLEAN DEFAULT 0')
    except sqlite3.OperationalError:
        pass

    # Reset all users to offline on startup (in-memory state is fresh)
    cursor.execute('UPDATE profiles SET is_online = 0')

    conn.commit()
    conn.close()


# ============== User Online Status ==============

def go_online(session_id: str):
    """Mark a user as online."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE profiles SET is_online = 1 WHERE session_id = ?', (session_id,))
    conn.commit()
    conn.close()

def go_offline(session_id: str):
    """Mark a user as offline."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE profiles SET is_online = 0 WHERE session_id = ?', (session_id,))
    conn.commit()
    conn.close()

def get_active_users(exclude_session: str = None) -> list:
    """Get all online users with their profiles."""
    conn = get_db()
    cursor = conn.cursor()
    if exclude_session:
        cursor.execute('''
            SELECT session_id, name, photo_url, color_frame
            FROM profiles
            WHERE is_online = 1 AND session_id != ?
            ORDER BY created_at
        ''', (exclude_session,))
    else:
        cursor.execute('''
            SELECT session_id, name, photo_url, color_frame
            FROM profiles
            WHERE is_online = 1
            ORDER BY created_at
        ''')
    users = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return users

def is_user_online(session_id: str) -> bool:
    """Check if a user is online."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT is_online FROM profiles WHERE session_id = ?', (session_id,))
    row = cursor.fetchone()
    conn.close()
    return bool(row and row['is_online'])


# ============== Messages ==============

def create_message(from_session, to_session, message_type, content):
    """Create a new message or drink offer."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO messages (from_session, to_session, message_type, content, status)
        VALUES (?, ?, ?, ?, 'pending')
    ''', (from_session, to_session, message_type, content))
    message_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return message_id

def update_message_status(message_id, status):
    """Update message status (accepted/declined)."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE messages SET status = ? WHERE id = ?', (status, message_id))
    conn.commit()
    conn.close()

def get_message(message_id):
    """Get a message by ID."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM messages WHERE id = ?', (message_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


# ============== Profiles ==============

def create_profile(session_id: str, name: str, photo_url: str = None, color_frame: str = None):
    """Create or update a user profile."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO profiles (session_id, name, photo_url, color_frame, is_online)
        VALUES (?, ?, ?, ?, 0)
    ''', (session_id, name, photo_url, color_frame))
    conn.commit()
    conn.close()

def get_profile(session_id: str):
    """Get a profile by session ID."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT session_id, name, photo_url, color_frame FROM profiles WHERE session_id = ?', (session_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def delete_profile(session_id: str):
    """Delete a profile by session ID."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM profiles WHERE session_id = ?', (session_id,))
    conn.commit()
    conn.close()


# ============== Menu Items ==============

def init_menu_table():
    """Create menu_items table if it doesn't exist."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS menu_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price TEXT NOT NULL,
            category TEXT NOT NULL,
            img TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

def get_all_menu_items() -> list:
    """Get all menu items ordered by category then sort_order."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM menu_items ORDER BY sort_order, id')
    items = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return items

def get_menu_items_count() -> int:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) as cnt FROM menu_items')
    count = cursor.fetchone()['cnt']
    conn.close()
    return count

def add_menu_item(name: str, price: str, category: str, img: str = ''):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO menu_items (name, price, category, img) VALUES (?, ?, ?, ?)',
        (name, price, category, img)
    )
    conn.commit()
    conn.close()

def update_menu_item(item_id: int, name: str, price: str, category: str, img: str = ''):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE menu_items SET name=?, price=?, category=?, img=? WHERE id=?',
        (name, price, category, img, item_id)
    )
    conn.commit()
    conn.close()

def delete_menu_item(item_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM menu_items WHERE id=?', (item_id,))
    conn.commit()
    conn.close()

def seed_menu_items(drinks: list):
    """Seed menu_items from the hardcoded DRINKS list (only if table is empty)."""
    if get_menu_items_count() > 0:
        return
    conn = get_db()
    cursor = conn.cursor()
    for i, d in enumerate(drinks):
        cursor.execute(
            'INSERT INTO menu_items (name, price, category, img, sort_order) VALUES (?, ?, ?, ?, ?)',
            (d['name'], d['price'], d['category'], d.get('img', ''), i)
        )
    conn.commit()
    conn.close()


# ============== Stats ==============

def count_messages() -> int:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) as cnt FROM messages')
    count = cursor.fetchone()['cnt']
    conn.close()
    return count


# ============== Settings ==============

def get_setting(key: str, default: str = '') -> str:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
    row = cursor.fetchone()
    conn.close()
    return row['value'] if row else default

def set_setting(key: str, value: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
    conn.close()


# ============== Activity Log ==============

def log_activity(event_type: str, description: str, session_id: str = None):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO activity_log (event_type, description, session_id) VALUES (?, ?, ?)',
        (event_type, description, session_id)
    )
    conn.commit()
    conn.close()

def get_recent_activity(limit: int = 50) -> list:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM activity_log ORDER BY created_at DESC LIMIT ?', (limit,))
    items = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return items

def clear_activity_log():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM activity_log')
    conn.commit()
    conn.close()


# ============== Drink Stats ==============

def get_drink_stats(limit: int = 10) -> list:
    """Get top drinks by number of times sent."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT content as drink_name, COUNT(*) as count
        FROM messages
        WHERE message_type = 'drink'
        GROUP BY content
        ORDER BY count DESC
        LIMIT ?
    ''', (limit,))
    items = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return items
