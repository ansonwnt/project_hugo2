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
    """Initialize the database with tables."""
    conn = get_db()
    cursor = conn.cursor()

    # Settings table (key-value)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')

    # Tables table - tracks which tables exist
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_number INTEGER UNIQUE NOT NULL,
            is_occupied BOOLEAN DEFAULT 0,
            session_id TEXT,
            last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Activity log
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            description TEXT NOT NULL,
            table_number INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Get configured table count (default 12)
    cursor.execute("SELECT value FROM settings WHERE key = 'table_count'")
    row = cursor.fetchone()
    table_count = int(row['value']) if row else 12
    if not row:
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('table_count', '12')")

    # Initialize tables up to configured count
    for i in range(1, table_count + 1):
        cursor.execute('''
            INSERT OR IGNORE INTO tables (table_number, is_occupied)
            VALUES (?, 0)
        ''', (i,))

    # Table members - tracks who is at each table (multiple people per table)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS table_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_number INTEGER NOT NULL,
            session_id TEXT UNIQUE NOT NULL,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Messages table - stores messages and drink offers
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_table INTEGER NOT NULL,
            to_table INTEGER NOT NULL,
            message_type TEXT NOT NULL,
            content TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Profiles table - user profiles with name and photo
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            photo_url TEXT,
            color_frame TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Add color_frame column if missing (existing DBs)
    try:
        cursor.execute('ALTER TABLE profiles ADD COLUMN color_frame TEXT')
    except sqlite3.OperationalError:
        pass  # column already exists

    # Reset all tables on startup (in-memory state is fresh)
    cursor.execute('UPDATE tables SET is_occupied = 0, session_id = NULL')
    cursor.execute('DELETE FROM table_members')

    conn.commit()
    conn.close()

def get_all_tables():
    """Get status of all tables with member profiles."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT table_number FROM tables ORDER BY table_number')
    tables = []
    for row in cursor.fetchall():
        tn = row['table_number']
        cursor.execute('''
            SELECT p.name, p.photo_url, p.color_frame, tm.session_id
            FROM table_members tm
            JOIN profiles p ON p.session_id = tm.session_id
            WHERE tm.table_number = ?
            ORDER BY tm.joined_at
        ''', (tn,))
        members = [{'name': m['name'], 'photo_url': m['photo_url'], 'color_frame': m['color_frame'], 'session_id': m['session_id']} for m in cursor.fetchall()]
        tables.append({
            'table_number': tn,
            'is_occupied': len(members) > 0,
            'members': members,
            'profile_name': members[0]['name'] if members else None,
            'profile_photo': members[0]['photo_url'] if members else None,
            'color_frame': members[0]['color_frame'] if members else None,
        })
    conn.close()
    return tables

def occupy_table(table_number, session_id):
    """Add a session to a table. Multiple people can join the same table."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        # Remove from any previous table first
        cursor.execute('DELETE FROM table_members WHERE session_id = ?', (session_id,))
        # Insert into new table
        cursor.execute(
            'INSERT INTO table_members (table_number, session_id) VALUES (?, ?)',
            (table_number, session_id)
        )
        # Update legacy tables row
        cursor.execute(
            'UPDATE tables SET is_occupied = 1, last_active = CURRENT_TIMESTAMP WHERE table_number = ?',
            (table_number,)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        conn.rollback()
        return False
    finally:
        conn.close()

def vacate_table(table_number):
    """Remove ALL members from a table."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM table_members WHERE table_number = ?', (table_number,))
    cursor.execute(
        'UPDATE tables SET is_occupied = 0, session_id = NULL WHERE table_number = ?',
        (table_number,)
    )
    conn.commit()
    conn.close()

def vacate_table_by_session(session_id):
    """Remove one member from their table. Returns table_number or None."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT table_number FROM table_members WHERE session_id = ?', (session_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None
    table_number = row['table_number']
    cursor.execute('DELETE FROM table_members WHERE session_id = ?', (session_id,))
    # Check if table is now empty
    cursor.execute('SELECT COUNT(*) as cnt FROM table_members WHERE table_number = ?', (table_number,))
    remaining = cursor.fetchone()['cnt']
    if remaining == 0:
        cursor.execute(
            'UPDATE tables SET is_occupied = 0, session_id = NULL WHERE table_number = ?',
            (table_number,)
        )
    conn.commit()
    conn.close()
    return table_number

def is_table_occupied(table_number):
    """Check if a table has any members."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) as cnt FROM table_members WHERE table_number = ?', (table_number,))
    count = cursor.fetchone()['cnt']
    conn.close()
    return count > 0

def create_message(from_table, to_table, message_type, content):
    """Create a new message or drink offer."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO messages (from_table, to_table, message_type, content, status)
        VALUES (?, ?, ?, ?, 'pending')
    ''', (from_table, to_table, message_type, content))
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

def create_profile(session_id: str, name: str, photo_url: str = None, color_frame: str = None):
    """Create or update a user profile."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO profiles (session_id, name, photo_url, color_frame)
        VALUES (?, ?, ?, ?)
    ''', (session_id, name, photo_url, color_frame))
    conn.commit()
    conn.close()

def get_profile(session_id: str) -> dict | None:
    """Get a profile by session ID."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT session_id, name, photo_url, color_frame FROM profiles WHERE session_id = ?', (session_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_profile_by_table(table_number: int) -> dict | None:
    """Get the profile of the first member at a given table."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT p.name, p.photo_url, p.color_frame
        FROM profiles p
        JOIN table_members tm ON tm.session_id = p.session_id
        WHERE tm.table_number = ?
        ORDER BY tm.joined_at
        LIMIT 1
    ''', (table_number,))
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

def get_all_menu_items() -> list[dict]:
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

def seed_menu_items(drinks: list[dict]):
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

def sync_table_count(new_count: int):
    """Ensure the tables table has exactly new_count rows."""
    conn = get_db()
    cursor = conn.cursor()
    # Add any missing tables
    for i in range(1, new_count + 1):
        cursor.execute('INSERT OR IGNORE INTO tables (table_number, is_occupied) VALUES (?, 0)', (i,))
    # Remove tables beyond the new count (only if unoccupied)
    cursor.execute('DELETE FROM tables WHERE table_number > ? AND is_occupied = 0', (new_count,))
    # Update setting in same connection
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('table_count', ?)", (str(new_count),))
    conn.commit()
    conn.close()


# ============== Activity Log ==============

def log_activity(event_type: str, description: str, table_number: int = None):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO activity_log (event_type, description, table_number) VALUES (?, ?, ?)',
        (event_type, description, table_number)
    )
    conn.commit()
    conn.close()

def get_recent_activity(limit: int = 50) -> list[dict]:
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

def get_drink_stats(limit: int = 10) -> list[dict]:
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
