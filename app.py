# Monkey-patch must happen before all other imports
try:
    import eventlet
    eventlet.monkey_patch()
    async_mode = 'eventlet'
except ImportError:
    async_mode = 'threading'

from flask import Flask, render_template, request, session, jsonify, redirect, url_for
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.utils import secure_filename
from functools import wraps
import models
import uuid
import os
import random
import time
from datetime import datetime, timedelta
import threading

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'shamrock-secret-key-change-in-production')
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB max upload

UPLOAD_FOLDER = os.path.join(app.static_folder, 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'shamrock2024')

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

socketio = SocketIO(app, cors_allowed_origins="*", async_mode=async_mode,
                    ping_timeout=60, ping_interval=25)

# Track connected clients
connected_clients = {}  # session_id -> {socket_id}
disconnect_timers = {}  # session_id -> timer

def get_sender_session():
    """Get session_id of the current socket caller from connected_clients."""
    sid = request.sid
    for sess_id, data in connected_clients.items():
        if data.get('socket_id') == sid:
            return sess_id
    return None

active_games = {}  # game_id -> {session_a, session_b, mode, drink, choice_a, choice_b, timer}
bomb_games = {}    # game_id -> {session_a, session_b, mode, drink, holder, started, timer, last_pass_time}
tap_games = {}     # game_id -> {session_a, session_b, ...}
ttol_games = {}    # game_id -> {session_a, session_b, ...}

# Periodic cleanup for abandoned games (older than 1 hour)
GAME_MAX_AGE = 3600  # 1 hour in seconds

def cleanup_stale_games():
    """Remove games that have been in memory longer than GAME_MAX_AGE."""
    now = time.time()
    for store_name, store in [('active_games', active_games), ('bomb_games', bomb_games),
                               ('tap_games', tap_games), ('ttol_games', ttol_games)]:
        stale = [gid for gid, g in store.items() if now - g.get('created_at', 0) > GAME_MAX_AGE]
        for gid in stale:
            game = store.pop(gid, None)
            if game and game.get('timer'):
                game['timer'].cancel()
            print(f"Cleaned up stale {store_name} game: {gid}")
    # Schedule next cleanup
    cleanup_timer = threading.Timer(300, cleanup_stale_games)  # every 5 minutes
    cleanup_timer.daemon = True
    cleanup_timer.start()

# Start the cleanup loop
_initial_cleanup = threading.Timer(300, cleanup_stale_games)
_initial_cleanup.daemon = True
_initial_cleanup.start()

# Initialize database on startup
models.init_db()
models.init_menu_table()

# Menu data - The Shamrock Irish Bar, Warsaw (single source of truth)
_U = 'https://images.unsplash.com'

DRINKS = [
    # Beer & Cider
    {'name': 'Guinness', 'price': '30 zł', 'category': 'beers', 'img': f'{_U}/photo-1730243694317-167fbf9eaa42?w=96&h=96&fit=crop'},
    {'name': 'Magners', 'price': '27 zł', 'category': 'beers', 'img': f'{_U}/photo-1600434610853-fcf8e079731b?w=96&h=96&fit=crop'},
    {'name': 'Okocim', 'price': '15 zł', 'category': 'beers', 'img': f'{_U}/photo-1623937228271-992646fb0fba?w=96&h=96&fit=crop'},
    {'name': 'Blanc 1664', 'price': '27 zł', 'category': 'beers', 'img': f'{_U}/photo-1760135866428-c6ac0091cb9f?w=96&h=96&fit=crop'},
    {'name': 'Carlsberg', 'price': '19 zł', 'category': 'beers', 'img': f'{_U}/photo-1619007495134-fed1dda8d8cf?w=96&h=96&fit=crop'},
    # Cocktails
    {'name': 'Sex on the Beach', 'price': '32 zł', 'category': 'cocktails', 'img': f'{_U}/photo-1582269438702-578efa319292?w=96&h=96&fit=crop'},
    {'name': 'Whiskey Sour', 'price': '34 zł', 'category': 'cocktails', 'img': f'{_U}/photo-1541546006121-5c3bc5e8c7b9?w=96&h=96&fit=crop'},
    {'name': 'Aperol Spritz', 'price': '32 zł', 'category': 'cocktails', 'img': f'{_U}/photo-1588685344608-514d42e02603?w=96&h=96&fit=crop'},
    {'name': 'Margarita', 'price': '34 zł', 'category': 'cocktails', 'img': f'{_U}/photo-1551782450-3939704166fc?w=96&h=96&fit=crop'},
    {'name': 'Cuba Libre', 'price': '30 zł', 'category': 'cocktails', 'img': f'{_U}/photo-1581636625402-29b2a704ef13?w=96&h=96&fit=crop'},
    {'name': 'Irish Coffee', 'price': '35 zł', 'category': 'cocktails', 'img': f'{_U}/photo-1551198297-0a648941bd7b?w=96&h=96&fit=crop'},
    {'name': 'Vodka Redbull', 'price': '32 zł', 'category': 'cocktails', 'img': f'{_U}/photo-1613218222876-954978a4404e?w=96&h=96&fit=crop'},
    {'name': 'Tropical Rumbull', 'price': '33 zł', 'category': 'cocktails', 'img': f'{_U}/photo-1625321643320-5321f48312b2?w=96&h=96&fit=crop'},
    {'name': 'Jagerbomb', 'price': '32 zł', 'category': 'cocktails', 'img': f'{_U}/photo-1649091364308-49233cbf6ac0?w=96&h=96&fit=crop'},
    {'name': 'Gin and Tonic', 'price': '30 zł', 'category': 'cocktails', 'img': f'{_U}/photo-1597960194480-fc6b5e3181fd?w=96&h=96&fit=crop'},
    {'name': 'Vodka White', 'price': '25 zł', 'category': 'cocktails', 'img': f'{_U}/photo-1589132971214-ed8169976abd?w=96&h=96&fit=crop'},
    {'name': 'Vodka Coke', 'price': '25 zł', 'category': 'cocktails', 'img': f'{_U}/photo-1544241907-f3f1f5ded15a?w=96&h=96&fit=crop'},
    {'name': 'Texas Long Island', 'price': '45 zł', 'category': 'cocktails', 'img': f'{_U}/photo-1514359652734-6205dd477a1e?w=96&h=96&fit=crop'},
    # Whiskey Drinks
    {'name': 'Bushmills', 'price': '18 zł', 'category': 'whiskey', 'img': f'{_U}/photo-1638884904408-fbc6ab0c200f?w=96&h=96&fit=crop'},
    {'name': 'Jameson', 'price': '18 zł', 'category': 'whiskey', 'img': f'{_U}/photo-1561293739-2da6674c7e4f?w=96&h=96&fit=crop'},
    {'name': 'Dubliner', 'price': '18 zł', 'category': 'whiskey', 'img': f'{_U}/photo-1638884904408-fbc6ab0c200f?w=96&h=96&fit=crop'},
    {'name': 'Jack Daniels', 'price': '25 zł', 'category': 'whiskey', 'img': f'{_U}/photo-1692713463309-fc6b9a43a226?w=96&h=96&fit=crop'},
    {'name': 'Jack Daniels Honey', 'price': '25 zł', 'category': 'whiskey', 'img': f'{_U}/photo-1607182389566-0295384bf75c?w=96&h=96&fit=crop'},
    {'name': 'Whiskey Coke', 'price': '35 zł', 'category': 'whiskey', 'img': f'{_U}/photo-1627310670374-5d47b19879a3?w=96&h=96&fit=crop'},
    # Softdrinks
    {'name': 'Carlsberg (NA)', 'price': '19 zł', 'category': 'softdrinks', 'img': f'{_U}/photo-1619007495134-fed1dda8d8cf?w=96&h=96&fit=crop'},
    {'name': 'Somersby', 'price': '19 zł', 'category': 'softdrinks', 'img': f'{_U}/photo-1600434610853-fcf8e079731b?w=96&h=96&fit=crop'},
    {'name': 'Redbull', 'price': '17 zł', 'category': 'softdrinks', 'img': f'{_U}/photo-1613218222876-954978a4404e?w=96&h=96&fit=crop'},
    {'name': 'Coca Cola', 'price': '10 zł', 'category': 'softdrinks', 'img': f'{_U}/photo-1574706226623-e5cc0da928c6?w=96&h=96&fit=crop'},
    {'name': 'Fanta', 'price': '10 zł', 'category': 'softdrinks', 'img': f'{_U}/photo-1625740822008-e45abf4e01d5?w=96&h=96&fit=crop'},
    {'name': 'Sprite', 'price': '10 zł', 'category': 'softdrinks', 'img': f'{_U}/photo-1592860893757-84536a1c9b82?w=96&h=96&fit=crop'},
    {'name': 'Water', 'price': '10 zł', 'category': 'softdrinks', 'img': f'{_U}/photo-1534616042650-80f5c9b61f09?w=96&h=96&fit=crop'},
    {'name': 'Tea Assorted', 'price': '10 zł', 'category': 'softdrinks', 'img': f'{_U}/photo-1570059560477-d61ca8bfda33?w=96&h=96&fit=crop'},
    # Snacks
    {'name': 'Chips', 'price': '15 zł', 'category': 'snacks', 'img': f'{_U}/photo-1534938665420-4193effeacc4?w=96&h=96&fit=crop'},
    {'name': 'Onion Rings', 'price': '15 zł', 'category': 'snacks', 'img': f'{_U}/photo-1639024469010-44d77e559f7d?w=96&h=96&fit=crop'},
    {'name': 'Squid Rings (Calamari)', 'price': '21 zł', 'category': 'snacks', 'img': f'{_U}/photo-1682264895449-f75b342cbab6?w=96&h=96&fit=crop'},
    {'name': 'Chicken Nuggets', 'price': '20 zł', 'category': 'snacks', 'img': f'{_U}/photo-1657271511865-f610b280dca4?w=96&h=96&fit=crop'},
    {'name': 'Chicken Strips', 'price': '25 zł', 'category': 'snacks', 'img': f'{_U}/photo-1605291581926-df4bf7ee3e89?w=96&h=96&fit=crop'},
    {'name': 'Crisps M', 'price': '10 zł', 'category': 'snacks', 'img': f'{_U}/photo-1555041469-6b4032059d29?w=96&h=96&fit=crop'},
    {'name': 'Crisps L', 'price': '15 zł', 'category': 'snacks', 'img': f'{_U}/photo-1555041469-6b4032059d29?w=96&h=96&fit=crop'},
]

# Seed menu_items DB from hardcoded DRINKS (only if empty)
models.seed_menu_items(DRINKS)


def get_drinks():
    """Get drinks from DB (falls back to hardcoded DRINKS if DB empty)."""
    items = models.get_all_menu_items()
    if items:
        return [{'name': i['name'], 'price': i['price'], 'category': i['category'], 'img': i['img']} for i in items]
    return DRINKS

# ============== Routes ==============

@app.route('/')
def index():
    """Landing page - profile creation."""
    return render_template('index.html')

@app.route('/people')
def people():
    """People page - main interaction area."""
    return render_template('people.html')

@app.route('/api/users')
def api_users():
    """Get all active users."""
    exclude = request.args.get('exclude')
    return jsonify(models.get_active_users(exclude_session=exclude))

@app.route('/api/drinks')
def api_drinks():
    """Get drink menu data."""
    return jsonify(get_drinks())

@app.route('/api/profile', methods=['POST'])
def api_create_profile():
    """Create or update a user profile."""
    session_id = request.form.get('session_id')
    name = request.form.get('name', '').strip()

    if not session_id or not name:
        return jsonify({'error': 'Name and session_id are required'}), 400

    if len(name) > 20:
        return jsonify({'error': 'Name must be 20 characters or less'}), 400

    if 'photo' not in request.files or not request.files['photo'].filename:
        return jsonify({'error': 'Photo is required'}), 400

    photo_url = None
    file = request.files['photo']
    if file and allowed_file(file.filename):
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        ext = file.filename.rsplit('.', 1)[1].lower()
        filename = secure_filename(f'{session_id}.{ext}')
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)
        photo_url = f'/static/uploads/{filename}'

    color_frame = request.form.get('color_frame', '').strip() or None
    if color_frame and color_frame not in ('red', 'yellow', 'green'):
        color_frame = None

    models.create_profile(session_id, name, photo_url, color_frame)
    return jsonify({'success': True, 'name': name, 'photo_url': photo_url, 'color_frame': color_frame})

@app.route('/api/profile/<session_id>')
def api_get_profile(session_id):
    """Get a profile by session_id."""
    profile = models.get_profile(session_id)
    if profile:
        return jsonify(profile)
    return jsonify({'error': 'Profile not found'}), 404

@app.route('/sw.js')
def service_worker():
    """Serve service worker from root scope (required for iOS PWA notifications)."""
    return app.send_static_file('sw.js'), 200, {'Content-Type': 'application/javascript', 'Service-Worker-Allowed': '/'}

# ============== Admin ==============

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """Admin login page."""
    if session.get('admin'):
        return redirect(url_for('admin_dashboard'))
    error = None
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['admin'] = True
            return redirect(url_for('admin_dashboard'))
        error = 'Wrong password'
    return render_template('admin_login.html', error=error)

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    return redirect(url_for('index'))

@app.route('/admin')
@admin_required
def admin_dashboard():
    """Admin dashboard — live stats."""
    users = models.get_active_users()
    total_messages = models.count_messages()
    active_game_count = len(active_games) + len(bomb_games) + len(tap_games) + len(ttol_games)
    activity = models.get_recent_activity(30)
    drink_stats = models.get_drink_stats(10)
    return render_template('admin.html',
        users=users,
        online_count=len(users),
        total_messages=total_messages,
        active_games=active_game_count,
        connected=len(connected_clients),
        activity=activity,
        drink_stats=drink_stats,
    )

@app.route('/admin/menu')
@admin_required
def admin_menu():
    """Admin menu management."""
    items = models.get_all_menu_items()
    categories = list(dict.fromkeys(item['category'] for item in items))
    return render_template('admin_menu.html', items=items, categories=categories)

@app.route('/admin/menu/add', methods=['POST'])
@admin_required
def admin_menu_add():
    """Add a menu item."""
    name = request.form.get('name', '').strip()
    price = request.form.get('price', '').strip()
    category = request.form.get('category', '').strip()
    img = request.form.get('img', '').strip()
    if name and price and category:
        models.add_menu_item(name, price, category, img)
    return redirect(url_for('admin_menu'))

@app.route('/admin/menu/edit/<int:item_id>', methods=['POST'])
@admin_required
def admin_menu_edit(item_id):
    """Edit a menu item."""
    name = request.form.get('name', '').strip()
    price = request.form.get('price', '').strip()
    category = request.form.get('category', '').strip()
    img = request.form.get('img', '').strip()
    if name and price and category:
        models.update_menu_item(item_id, name, price, category, img)
    return redirect(url_for('admin_menu'))

@app.route('/admin/menu/delete/<int:item_id>', methods=['POST'])
@admin_required
def admin_menu_delete(item_id):
    """Delete a menu item."""
    models.delete_menu_item(item_id)
    return redirect(url_for('admin_menu'))

@app.route('/admin/users/reset', methods=['POST'])
@admin_required
def admin_users_reset():
    """Reset all users (set everyone offline)."""
    for sess_id in list(connected_clients.keys()):
        _cleanup_profile(sess_id)
        models.go_offline(sess_id)
    connected_clients.clear()
    for timer in disconnect_timers.values():
        timer.cancel()
    disconnect_timers.clear()
    socketio.emit('users_update', models.get_active_users())
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/users/kick/<session_id>', methods=['POST'])
@admin_required
def admin_kick_user(session_id):
    """Kick a specific user offline."""
    _cleanup_profile(session_id)
    models.go_offline(session_id)
    if session_id in connected_clients:
        del connected_clients[session_id]
    socketio.emit('users_update', models.get_active_users())
    socketio.emit('kicked', {}, room=f'user_{session_id}')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/broadcast', methods=['POST'])
@admin_required
def admin_broadcast():
    """Send a broadcast message to all connected clients."""
    message = request.form.get('message', '').strip()
    if message:
        socketio.emit('admin_broadcast', {'message': message})
        models.log_activity('broadcast', f'Admin broadcast: {message}')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/activity/clear', methods=['POST'])
@admin_required
def admin_activity_clear():
    """Clear the activity log."""
    models.clear_activity_log()
    return redirect(url_for('admin_dashboard'))


def _cleanup_profile(session_id):
    """Delete a user's profile and photo file."""
    profile = models.get_profile(session_id)
    if profile and profile.get('photo_url'):
        photo_path = os.path.join(app.root_path, profile['photo_url'].lstrip('/'))
        if os.path.exists(photo_path):
            try:
                os.remove(photo_path)
            except OSError:
                pass
    models.delete_profile(session_id)

# ============== Socket Events ==============

@socketio.on('connect')
def handle_connect():
    """Handle client connection."""
    print(f"Client connected: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnect - wait before going offline."""
    sid = request.sid

    # Find which session this socket belongs to
    session_id = None
    for sess_id, data in connected_clients.items():
        if data.get('socket_id') == sid:
            session_id = sess_id
            break

    if session_id:
        # Start a timer before going offline
        def offline_after_timeout():
            if session_id in connected_clients:
                _cleanup_profile(session_id)
                models.go_offline(session_id)
                del connected_clients[session_id]
                socketio.emit('users_update', models.get_active_users())
                print(f"Session {session_id} went offline after timeout")

        # Cancel existing timer if any
        if session_id in disconnect_timers:
            disconnect_timers[session_id].cancel()

        timer = threading.Timer(86400.0, offline_after_timeout)
        disconnect_timers[session_id] = timer
        timer.start()
        print(f"Started disconnect timer for session {session_id}")

@socketio.on('go_online')
def handle_go_online(data):
    """Handle a user coming online after profile creation."""
    session_id = data.get('session_id')
    if not session_id:
        emit('online_error', {'message': 'Invalid request'})
        return

    # Cancel any pending disconnect timer
    if session_id in disconnect_timers:
        disconnect_timers[session_id].cancel()
        del disconnect_timers[session_id]

    # Mark online in DB
    models.go_online(session_id)

    # Track this client
    connected_clients[session_id] = {
        'socket_id': request.sid
    }

    # Join a personal room
    join_room(f'user_{session_id}')

    emit('online_success', {'session_id': session_id})

    # Log activity
    profile = models.get_profile(session_id)
    pname = profile['name'] if profile else session_id[:8]
    models.log_activity('join', f'{pname} came online', session_id)

    # Broadcast updated user list to everyone
    socketio.emit('users_update', models.get_active_users())
    print(f"Session {session_id} came online")

@socketio.on('rejoin')
def handle_rejoin(data):
    """Handle a user rejoining after page refresh."""
    session_id = data.get('session_id')
    if not session_id:
        return

    # Cancel any pending disconnect timer
    if session_id in disconnect_timers:
        disconnect_timers[session_id].cancel()
        del disconnect_timers[session_id]

    profile = models.get_profile(session_id)
    if not profile:
        emit('rejoin_failed', {'message': 'Session expired'})
        return

    # Re-mark online
    models.go_online(session_id)

    if session_id in connected_clients:
        connected_clients[session_id]['socket_id'] = request.sid
    else:
        connected_clients[session_id] = {'socket_id': request.sid}

    join_room(f'user_{session_id}')
    emit('rejoin_success', {'session_id': session_id})
    socketio.emit('users_update', models.get_active_users())
    print(f"Session {session_id} rejoined")

@socketio.on('checkout')
def handle_checkout(data):
    """Handle a user checking out (leaving the app)."""
    session_id = data.get('session_id')
    if not session_id:
        return

    profile = models.get_profile(session_id)
    pname = profile['name'] if profile else session_id[:8]
    models.log_activity('leave', f'{pname} checked out', session_id)

    _cleanup_profile(session_id)
    models.go_offline(session_id)
    leave_room(f'user_{session_id}')

    if session_id in connected_clients:
        del connected_clients[session_id]

    socketio.emit('users_update', models.get_active_users())
    emit('checkout_success')
    print(f"Session {session_id} checked out")

@socketio.on('send_message')
def handle_send_message(data):
    """Handle sending a message/drink to another user."""
    to_session = data.get('to_session')
    content = data.get('content')
    message_type = data.get('message_type', 'message')

    sender_session = get_sender_session()
    if not all([sender_session, to_session, content]):
        emit('send_error', {'message': 'Invalid request'})
        return

    # Check if target user is still online
    if not models.is_user_online(to_session):
        emit('send_error', {'message': "Oops! They just left. Maybe next time!"})
        return

    # Create the message in database
    message_id = models.create_message(sender_session, to_session, message_type, content)

    # Send notification to the target user
    note = data.get('note', '')
    profile = models.get_profile(sender_session)
    sender_name = profile['name'] if profile else 'Someone'
    sender_photo = profile.get('photo_url') if profile else None
    socketio.emit('incoming_message', {
        'message_id': message_id,
        'from_session': sender_session,
        'from_name': sender_name,
        'from_photo': sender_photo,
        'message_type': message_type,
        'content': content,
        'note': note,
    }, room=f'user_{to_session}')

    # Log activity
    if message_type == 'drink':
        target_profile = models.get_profile(to_session)
        target_name = target_profile['name'] if target_profile else 'someone'
        models.log_activity('drink', f'{sender_name} sent {content} to {target_name}', sender_session)
    else:
        models.log_activity('message', f'{sender_name} messaged someone', sender_session)

    emit('send_success', {'message': 'Sent!'})
    print(f"Message from {sender_session[:8]} to {to_session[:8]}: {content}")

@socketio.on('respond_message')
def handle_respond_message(data):
    """Handle accepting or declining a message/drink."""
    message_id = data.get('message_id')
    response = data.get('response')  # 'accepted' or 'declined'
    from_session = data.get('from_session')  # The session that sent the original message

    if not all([message_id, response, from_session]):
        return

    # Update message status
    models.update_message_status(message_id, response)

    # Get the message details
    message = models.get_message(message_id)
    content = message['content'] if message else ''

    responder_session = get_sender_session()
    responder_profile = models.get_profile(responder_session) if responder_session else None
    responder_name = responder_profile['name'] if responder_profile else 'Someone'

    notification = {
        'type': response,
        'content': content,
        'responder_name': responder_name,
        'responder_session': responder_session,
    }

    socketio.emit('message_response', notification, room=f'user_{from_session}')
    emit('response_confirmed', notification)
    print(f"Message {message_id} {response}")

# ============== Rock Paper Scissors ==============

def resolve_rps(game):
    """Determine RPS winner. Returns 'a', 'b', or 'tie'."""
    a, b = game['choice_a'], game['choice_b']
    if a == b:
        return 'tie'
    wins = {'rock': 'scissors', 'scissors': 'paper', 'paper': 'rock'}
    return 'a' if wins[a] == b else 'b'

def finish_game(game_id):
    """Resolve a game and notify both players."""
    game = active_games.pop(game_id, None)
    if not game:
        return

    if game.get('timer'):
        game['timer'].cancel()

    # Handle forfeits (timeout with no choice)
    if not game['choice_a'] and not game['choice_b']:
        for sess in [game['session_a'], game['session_b']]:
            socketio.emit('rps_result', {
                'game_id': game_id, 'result': 'cancelled',
                'message': 'Game timed out!'
            }, room=f'user_{sess}')
        return

    if not game['choice_a']:
        winner_session, loser_session = game['session_b'], game['session_a']
        result_key = 'b'
    elif not game['choice_b']:
        winner_session, loser_session = game['session_a'], game['session_b']
        result_key = 'a'
    else:
        result_key = resolve_rps(game)
        if result_key == 'tie':
            winner_session, loser_session = None, None
        elif result_key == 'a':
            winner_session, loser_session = game['session_a'], game['session_b']
        else:
            winner_session, loser_session = game['session_b'], game['session_a']

    base = {
        'game_id': game_id,
        'choice_a': game['choice_a'],
        'choice_b': game['choice_b'],
        'session_a': game['session_a'],
        'session_b': game['session_b'],
        'mode': game['mode'],
        'drink': game.get('drink', ''),
    }

    if result_key == 'tie':
        for sess in [game['session_a'], game['session_b']]:
            socketio.emit('rps_result', {**base, 'result': 'tie'}, room=f'user_{sess}')
    else:
        socketio.emit('rps_result', {
            **base, 'result': 'win', 'winner': winner_session, 'loser': loser_session
        }, room=f'user_{winner_session}')
        socketio.emit('rps_result', {
            **base, 'result': 'lose', 'winner': winner_session, 'loser': loser_session
        }, room=f'user_{loser_session}')

    models.log_activity('game', f'RPS: {game["session_a"][:8]} vs {game["session_b"][:8]} → {result_key}', game['session_a'])
    print(f"RPS game {game_id}: {result_key}")

@socketio.on('rps_challenge')
def handle_rps_challenge(data):
    """Handle a RPS challenge from one user to another."""
    to_session = data.get('to_session')
    mode = data.get('mode', 'fun')
    drink = data.get('drink', '')

    sender_session = get_sender_session()
    if not all([sender_session, to_session]):
        emit('rps_error', {'message': 'Invalid request'})
        return

    if not models.is_user_online(to_session):
        emit('rps_error', {'message': "They just left!"})
        return

    game_id = str(uuid.uuid4())[:8]

    active_games[game_id] = {
        'session_a': sender_session,
        'session_b': to_session,
        'mode': mode,
        'drink': drink,
        'choice_a': None,
        'choice_b': None,
        'timer': None,
        'started': False,
    }

    profile = models.get_profile(sender_session)
    sender_name = profile['name'] if profile else 'Someone'
    sender_photo = profile.get('photo_url') if profile else None
    socketio.emit('rps_incoming', {
        'game_id': game_id,
        'from_session': sender_session,
        'from_name': sender_name,
        'from_photo': sender_photo,
        'mode': mode,
        'drink': drink,
    }, room=f'user_{to_session}')

    emit('rps_challenge_sent', {'game_id': game_id})
    print(f"RPS challenge: {sender_session[:8]} -> {to_session[:8]} ({mode})")

@socketio.on('rps_response')
def handle_rps_response(data):
    """Handle accept/decline of a RPS challenge."""
    game_id = data.get('game_id')
    accepted = data.get('accepted', False)

    game = active_games.get(game_id)
    if not game:
        return

    if not accepted:
        active_games.pop(game_id, None)
        socketio.emit('rps_declined', {
            'game_id': game_id,
            'from_session': game['session_b']
        }, room=f'user_{game["session_a"]}')
        print(f"RPS challenge {game_id} declined")
        return

    # Start the game
    game['started'] = True

    # 30-second timeout
    def timeout():
        if game_id in active_games:
            finish_game(game_id)

    timer = threading.Timer(30.0, timeout)
    game['timer'] = timer
    timer.start()

    # Notify both users
    start_data = {
        'game_id': game_id,
        'session_a': game['session_a'],
        'session_b': game['session_b'],
        'mode': game['mode'],
        'drink': game.get('drink', ''),
    }
    socketio.emit('rps_start', start_data, room=f'user_{game["session_a"]}')
    socketio.emit('rps_start', start_data, room=f'user_{game["session_b"]}')
    print(f"RPS game {game_id} started")

@socketio.on('rps_choice')
def handle_rps_choice(data):
    """Handle a player's RPS choice."""
    game_id = data.get('game_id')
    choice = data.get('choice')
    session_id = data.get('session_id')

    if choice not in ('rock', 'paper', 'scissors'):
        return

    game = active_games.get(game_id)
    if not game or not game.get('started'):
        return

    if session_id == game['session_a']:
        game['choice_a'] = choice
    elif session_id == game['session_b']:
        game['choice_b'] = choice
    else:
        return

    if game['choice_a'] and game['choice_b']:
        finish_game(game_id)

# ============== Bomb Pass ==============

def finish_bomb_game(game_id):
    """Resolve a bomb game — whoever holds the bomb loses."""
    game = bomb_games.pop(game_id, None)
    if not game:
        return

    if game.get('timer'):
        game['timer'].cancel()

    holder = game['holder']
    if not holder:
        for sess in [game['session_a'], game['session_b']]:
            socketio.emit('bomb_result', {
                'game_id': game_id, 'result': 'cancelled',
                'message': 'Game cancelled!'
            }, room=f'user_{sess}')
        return

    loser_session = holder
    winner_session = game['session_b'] if holder == game['session_a'] else game['session_a']

    base = {
        'game_id': game_id,
        'session_a': game['session_a'],
        'session_b': game['session_b'],
        'mode': game['mode'],
        'drink': game.get('drink', ''),
        'winner': winner_session,
        'loser': loser_session,
    }

    socketio.emit('bomb_result', {
        **base, 'result': 'win'
    }, room=f'user_{winner_session}')
    socketio.emit('bomb_result', {
        **base, 'result': 'lose'
    }, room=f'user_{loser_session}')

    models.log_activity('game', f'Bomb Pass: {winner_session[:8]} beat {loser_session[:8]}', winner_session)
    print(f"Bomb game {game_id}: {loser_session[:8]} exploded!")

@socketio.on('bomb_challenge')
def handle_bomb_challenge(data):
    """Handle a Bomb Pass challenge."""
    to_session = data.get('to_session')
    mode = data.get('mode', 'fun')
    drink = data.get('drink', '')

    sender_session = get_sender_session()
    if not all([sender_session, to_session]):
        emit('bomb_error', {'message': 'Invalid request'})
        return

    if not models.is_user_online(to_session):
        emit('bomb_error', {'message': "They just left!"})
        return

    game_id = str(uuid.uuid4())[:8]

    bomb_games[game_id] = {
        'session_a': sender_session,
        'session_b': to_session,
        'mode': mode,
        'drink': drink,
        'holder': None,
        'started': False,
        'timer': None,
        'last_pass_time': 0,
    }

    profile = models.get_profile(sender_session)
    sender_name = profile['name'] if profile else 'Someone'
    sender_photo = profile.get('photo_url') if profile else None
    socketio.emit('bomb_incoming', {
        'game_id': game_id,
        'from_session': sender_session,
        'from_name': sender_name,
        'from_photo': sender_photo,
        'mode': mode,
        'drink': drink,
    }, room=f'user_{to_session}')

    emit('bomb_challenge_sent', {'game_id': game_id})
    print(f"Bomb challenge: {sender_session[:8]} -> {to_session[:8]} ({mode})")

@socketio.on('bomb_response')
def handle_bomb_response(data):
    """Handle accept/decline of a bomb challenge."""
    game_id = data.get('game_id')
    accepted = data.get('accepted', False)

    game = bomb_games.get(game_id)
    if not game:
        return

    if not accepted:
        bomb_games.pop(game_id, None)
        socketio.emit('bomb_declined', {
            'game_id': game_id,
            'from_session': game['session_b']
        }, room=f'user_{game["session_a"]}')
        print(f"Bomb challenge {game_id} declined")
        return

    # Start the game — challenger (session_a) holds the bomb first
    game['started'] = True
    game['holder'] = game['session_a']
    game['last_pass_time'] = time.time()

    # Secret fuse timer: 8–15 seconds
    fuse_time = random.uniform(8.0, 15.0)

    def explode():
        if game_id in bomb_games:
            finish_bomb_game(game_id)

    timer = threading.Timer(fuse_time, explode)
    game['timer'] = timer
    timer.start()

    start_data = {
        'game_id': game_id,
        'session_a': game['session_a'],
        'session_b': game['session_b'],
        'mode': game['mode'],
        'drink': game.get('drink', ''),
        'holder': game['holder'],
    }
    socketio.emit('bomb_start', start_data, room=f'user_{game["session_a"]}')
    socketio.emit('bomb_start', start_data, room=f'user_{game["session_b"]}')
    print(f"Bomb game {game_id} started (fuse: {fuse_time:.1f}s)")

@socketio.on('bomb_pass')
def handle_bomb_pass(data):
    """Handle a player passing the bomb."""
    game_id = data.get('game_id')
    session_id = data.get('session_id')

    game = bomb_games.get(game_id)
    if not game or not game.get('started'):
        return

    # Only the holder can pass
    if game['holder'] != session_id:
        return

    # Enforce 0.5s cooldown
    now = time.time()
    if now - game['last_pass_time'] < 0.5:
        return

    # Flip holder
    game['holder'] = game['session_b'] if session_id == game['session_a'] else game['session_a']
    game['last_pass_time'] = now

    # Notify both users
    pass_data = {
        'game_id': game_id,
        'holder': game['holder'],
    }
    socketio.emit('bomb_passed', pass_data, room=f'user_{game["session_a"]}')
    socketio.emit('bomb_passed', pass_data, room=f'user_{game["session_b"]}')

# ============== Tap Race ==============

def finish_tap_game(game_id):
    """Resolve a tap race — highest tap count wins."""
    game = tap_games.pop(game_id, None)
    if not game:
        return

    if game.get('timer'):
        game['timer'].cancel()

    count_a = game['count_a']
    count_b = game['count_b']

    base = {
        'game_id': game_id,
        'session_a': game['session_a'],
        'session_b': game['session_b'],
        'mode': game['mode'],
        'drink': game.get('drink', ''),
        'count_a': count_a,
        'count_b': count_b,
    }

    if count_a == count_b:
        for sess in [game['session_a'], game['session_b']]:
            socketio.emit('tap_result', {
                **base, 'result': 'draw',
                'winner': None, 'loser': None,
            }, room=f'user_{sess}')
    else:
        winner = game['session_a'] if count_a > count_b else game['session_b']
        loser = game['session_b'] if count_a > count_b else game['session_a']
        base['winner'] = winner
        base['loser'] = loser

        socketio.emit('tap_result', {
            **base, 'result': 'win',
        }, room=f'user_{winner}')
        socketio.emit('tap_result', {
            **base, 'result': 'lose',
        }, room=f'user_{loser}')

    models.log_activity('game', f'Tap Race: {count_a} vs {count_b}', game['session_a'])
    print(f"Tap race {game_id}: A={count_a} B={count_b}")

@socketio.on('tap_challenge')
def handle_tap_challenge(data):
    """Handle a Tap Race challenge."""
    to_session = data.get('to_session')
    mode = data.get('mode', 'fun')
    drink = data.get('drink', '')

    sender_session = get_sender_session()
    if not all([sender_session, to_session]):
        emit('tap_error', {'message': 'Invalid request'})
        return

    if not models.is_user_online(to_session):
        emit('tap_error', {'message': "They just left!"})
        return

    game_id = str(uuid.uuid4())[:8]

    tap_games[game_id] = {
        'session_a': sender_session,
        'session_b': to_session,
        'mode': mode,
        'drink': drink,
        'count_a': 0,
        'count_b': 0,
        'started': False,
        'timer': None,
        'last_tap_a': 0,
        'last_tap_b': 0,
    }

    profile = models.get_profile(sender_session)
    sender_name = profile['name'] if profile else 'Someone'
    sender_photo = profile.get('photo_url') if profile else None
    socketio.emit('tap_incoming', {
        'game_id': game_id,
        'from_session': sender_session,
        'from_name': sender_name,
        'from_photo': sender_photo,
        'mode': mode,
        'drink': drink,
    }, room=f'user_{to_session}')

    emit('tap_challenge_sent', {'game_id': game_id})
    print(f"Tap Race challenge: {sender_session[:8]} -> {to_session[:8]} ({mode})")

@socketio.on('tap_response')
def handle_tap_response(data):
    """Handle accept/decline of a tap race challenge."""
    game_id = data.get('game_id')
    accepted = data.get('accepted', False)

    game = tap_games.get(game_id)
    if not game:
        return

    if not accepted:
        tap_games.pop(game_id, None)
        socketio.emit('tap_declined', {
            'game_id': game_id,
            'from_session': game['session_b']
        }, room=f'user_{game["session_a"]}')
        print(f"Tap Race challenge {game_id} declined")
        return

    # Start the game after a 3s countdown
    game['started'] = True

    start_data = {
        'game_id': game_id,
        'session_a': game['session_a'],
        'session_b': game['session_b'],
        'mode': game['mode'],
        'drink': game.get('drink', ''),
        'duration': 10,
        'countdown': 3,
    }
    socketio.emit('tap_start', start_data, room=f'user_{game["session_a"]}')
    socketio.emit('tap_start', start_data, room=f'user_{game["session_b"]}')

    # Set timer: 3s countdown + 10s game = 13s total
    def end_game():
        if game_id in tap_games:
            finish_tap_game(game_id)

    timer = threading.Timer(13.0, end_game)
    game['timer'] = timer
    timer.start()

    print(f"Tap Race {game_id} started")

@socketio.on('tap_tap')
def handle_tap_tap(data):
    """Handle a single tap from a player."""
    game_id = data.get('game_id')
    session_id = data.get('session_id')

    game = tap_games.get(game_id)
    if not game or not game.get('started'):
        return

    now = time.time()

    # Rate limit: max ~20 taps/sec
    if session_id == game['session_a']:
        if now - game['last_tap_a'] < 0.05:
            return
        game['count_a'] += 1
        game['last_tap_a'] = now
    elif session_id == game['session_b']:
        if now - game['last_tap_b'] < 0.05:
            return
        game['count_b'] += 1
        game['last_tap_b'] = now
    else:
        return

    # Broadcast updated counts
    update_data = {
        'game_id': game_id,
        'count_a': game['count_a'],
        'count_b': game['count_b'],
    }
    socketio.emit('tap_update', update_data, room=f'user_{game["session_a"]}')
    socketio.emit('tap_update', update_data, room=f'user_{game["session_b"]}')

# ============== 2 Truths 1 Lie ==============

def finish_ttol_game(game_id):
    """Resolve a 2 Truths 1 Lie game."""
    game = ttol_games.pop(game_id, None)
    if not game:
        return

    if game.get('timer'):
        game['timer'].cancel()

    a_correct = game['guess_a'] is not None and game['guess_a'] == game['lie_index_b']
    b_correct = game['guess_b'] is not None and game['guess_b'] == game['lie_index_a']

    base = {
        'game_id': game_id,
        'session_a': game['session_a'],
        'session_b': game['session_b'],
        'mode': game['mode'],
        'drink': game.get('drink', ''),
        'statements_a': game['statements_a'],
        'statements_b': game['statements_b'],
        'lie_index_a': game['lie_index_a'],
        'lie_index_b': game['lie_index_b'],
        'guess_a': game['guess_a'],
        'guess_b': game['guess_b'],
        'a_correct': a_correct,
        'b_correct': b_correct,
    }

    if a_correct == b_correct:
        for sess in [game['session_a'], game['session_b']]:
            socketio.emit('ttol_result', {
                **base, 'result': 'draw',
                'winner': None, 'loser': None,
            }, room=f'user_{sess}')
    else:
        winner = game['session_a'] if a_correct else game['session_b']
        loser = game['session_b'] if a_correct else game['session_a']
        socketio.emit('ttol_result', {
            **base, 'result': 'win',
            'winner': winner, 'loser': loser,
        }, room=f'user_{winner}')
        socketio.emit('ttol_result', {
            **base, 'result': 'lose',
            'winner': winner, 'loser': loser,
        }, room=f'user_{loser}')

    print(f"TTOL game {game_id}: A_correct={a_correct} B_correct={b_correct}")

def start_guess_phase(game_id):
    """Transition from write phase to guess phase."""
    game = ttol_games.get(game_id)
    if not game:
        return

    if game.get('timer'):
        game['timer'].cancel()

    game['phase'] = 'guess'

    # 60-second timeout for guess phase
    def guess_timeout():
        if game_id in ttol_games and ttol_games[game_id]['phase'] == 'guess':
            finish_ttol_game(game_id)

    timer = threading.Timer(60.0, guess_timeout)
    game['timer'] = timer
    timer.start()

    # Send opponent's statements to each player
    socketio.emit('ttol_guess_phase', {
        'game_id': game_id,
        'statements': game['statements_b'],
        'opponent_session': game['session_b'],
    }, room=f'user_{game["session_a"]}')

    socketio.emit('ttol_guess_phase', {
        'game_id': game_id,
        'statements': game['statements_a'],
        'opponent_session': game['session_a'],
    }, room=f'user_{game["session_b"]}')

    print(f"TTOL game {game_id} entering guess phase")

@socketio.on('ttol_challenge')
def handle_ttol_challenge(data):
    """Handle a 2 Truths 1 Lie challenge."""
    to_session = data.get('to_session')
    mode = data.get('mode', 'fun')
    drink = data.get('drink', '')

    sender_session = get_sender_session()
    if not all([sender_session, to_session]):
        emit('ttol_error', {'message': 'Invalid request'})
        return

    if not models.is_user_online(to_session):
        emit('ttol_error', {'message': "They just left!"})
        return

    game_id = str(uuid.uuid4())[:8]

    ttol_games[game_id] = {
        'session_a': sender_session,
        'session_b': to_session,
        'mode': mode,
        'drink': drink,
        'started': False,
        'timer': None,
        'phase': 'write',
        'statements_a': None,
        'statements_b': None,
        'lie_index_a': None,
        'lie_index_b': None,
        'guess_a': None,
        'guess_b': None,
    }

    profile = models.get_profile(sender_session)
    sender_name = profile['name'] if profile else 'Someone'
    sender_photo = profile.get('photo_url') if profile else None
    socketio.emit('ttol_incoming', {
        'game_id': game_id,
        'from_session': sender_session,
        'from_name': sender_name,
        'from_photo': sender_photo,
        'mode': mode,
        'drink': drink,
    }, room=f'user_{to_session}')

    emit('ttol_challenge_sent', {'game_id': game_id})
    print(f"TTOL challenge: {sender_session[:8]} -> {to_session[:8]} ({mode})")

@socketio.on('ttol_response')
def handle_ttol_response(data):
    """Handle accept/decline of a TTOL challenge."""
    game_id = data.get('game_id')
    accepted = data.get('accepted', False)

    game = ttol_games.get(game_id)
    if not game:
        return

    if not accepted:
        ttol_games.pop(game_id, None)
        socketio.emit('ttol_declined', {
            'game_id': game_id,
            'from_session': game['session_b']
        }, room=f'user_{game["session_a"]}')
        print(f"TTOL challenge {game_id} declined")
        return

    # Start the write phase
    game['started'] = True
    game['phase'] = 'write'

    # 90-second timeout for write phase
    def write_timeout():
        if game_id not in ttol_games:
            return
        g = ttol_games.get(game_id)
        if not g or g['phase'] != 'write':
            return
        if g['statements_a'] is None and g['statements_b'] is None:
            ttol_games.pop(game_id, None)
            for sess in [g['session_a'], g['session_b']]:
                socketio.emit('ttol_result', {
                    'game_id': game_id, 'result': 'cancelled',
                    'message': 'Both players timed out!'
                }, room=f'user_{sess}')
        else:
            if g['statements_a'] is None:
                g['statements_a'] = ['(No response)', '(No response)', '(No response)']
                g['lie_index_a'] = 0
            if g['statements_b'] is None:
                g['statements_b'] = ['(No response)', '(No response)', '(No response)']
                g['lie_index_b'] = 0
            start_guess_phase(game_id)

    timer = threading.Timer(90.0, write_timeout)
    game['timer'] = timer
    timer.start()

    start_data = {
        'game_id': game_id,
        'session_a': game['session_a'],
        'session_b': game['session_b'],
        'mode': game['mode'],
        'drink': game.get('drink', ''),
        'phase': 'write',
    }
    socketio.emit('ttol_start', start_data, room=f'user_{game["session_a"]}')
    socketio.emit('ttol_start', start_data, room=f'user_{game["session_b"]}')
    print(f"TTOL game {game_id} started (write phase)")

@socketio.on('ttol_submit')
def handle_ttol_submit(data):
    """Handle a player submitting their 3 statements and lie index."""
    game_id = data.get('game_id')
    session_id = data.get('session_id')
    statements = data.get('statements')
    lie_index = data.get('lie_index')

    game = ttol_games.get(game_id)
    if not game or not game.get('started') or game['phase'] != 'write':
        return

    if not isinstance(statements, list) or len(statements) != 3:
        return
    if lie_index not in (0, 1, 2):
        return

    statements = [str(s).strip()[:200] for s in statements]
    if any(len(s) == 0 for s in statements):
        emit('ttol_error', {'message': 'All three statements are required'})
        return

    if session_id == game['session_a']:
        game['statements_a'] = statements
        game['lie_index_a'] = lie_index
    elif session_id == game['session_b']:
        game['statements_b'] = statements
        game['lie_index_b'] = lie_index
    else:
        return

    emit('ttol_waiting', {'game_id': game_id, 'phase': 'write'})

    if game['statements_a'] is not None and game['statements_b'] is not None:
        start_guess_phase(game_id)

@socketio.on('ttol_guess')
def handle_ttol_guess(data):
    """Handle a player's guess of which statement is the lie."""
    game_id = data.get('game_id')
    session_id = data.get('session_id')
    guess = data.get('guess')

    game = ttol_games.get(game_id)
    if not game or game['phase'] != 'guess':
        return

    if guess not in (0, 1, 2):
        return

    if session_id == game['session_a']:
        game['guess_a'] = guess
    elif session_id == game['session_b']:
        game['guess_b'] = guess
    else:
        return

    emit('ttol_waiting', {'game_id': game_id, 'phase': 'guess'})

    if game['guess_a'] is not None and game['guess_b'] is not None:
        finish_ttol_game(game_id)


if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5001, allow_unsafe_werkzeug=True)
