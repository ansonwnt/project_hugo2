Build a restaurant social web app called "Hugo" with Flask. Focus on making it extremely user-friendly and intuitive.

## Pages:

### 1. Landing Page (index.html)
- Clean, welcoming screen with app name "Hugo" and tagline: "Connect with other tables"
- Large, tappable number pad (1-8) to select your table
- Big, obvious "Join Table" button
- Small text below: "Other guests will see your table is occupied"
- If table already occupied: show friendly error "Table 5 is taken! Try another"
- Store table number in localStorage so it persists on refresh

### 2. Menu Page (menu.html)
- Dummy menu with 3 categories: Beers, Cocktails, Soft Drinks
- 3-4 items per category with emoji, name, and fake price
- This is view-only, used as reference when buying drinks
- Bottom navigation to switch between Menu and Tables pages

### 3. Tables Page (tables.html)
- Header showing "You are at Table X" with Check Out button
- 8 tables in a 2x4 grid layout
- Visual states for each table:
  - Empty: gray, muted
  - Occupied: glowing/highlighted, tappable
  - Your table: different color (e.g., blue), not tappable
- Tapping an occupied table opens action modal

## Core User Flows:

### Sending a Message:
1. User taps an occupied table
2. Modal appears with two clear options: "Send Message" | "Buy a Drink"
3. If "Send Message": show 3 preset options
   - "👋 Hello from Table {X}!"
   - "🍻 Cheers from Table {X}!"
   - "✨ Nice vibe over there!"
4. Tap a message to select it
5. **Confirmation dialog: "Send to Table {Y}?" [Cancel] [Send ✓]**
6. On confirm: modal closes, show toast: "Message sent! ✓"

### Buying a Drink:
1. User taps an occupied table
2. Modal appears → tap "Buy a Drink"
3. Drink picker appears (same items from menu, with emoji icons)
4. Tap a drink to select it
5. **Confirmation dialog: "Send 🍺 Beer to Table {Y}?" [Cancel] [Send ✓]**
6. On confirm: show toast "🍺 Beer sent to Table {Y}!"

### Receiving a Notification:
1. Toast slides in from bottom (mobile) or bottom-right (desktop)
2. Shows: "Table X sent you a 🍺 Beer!" or "Table X says: 👋 Hello!"
3. Two big buttons: [Accept ✓] [Decline ✗]
4. Toast stays until user responds (no auto-dismiss for drink offers)
5. After response:
   - Accept: Both see "🥂 Cheers!" animation/confirmation
   - Decline: Sender sees "Maybe next time!" (friendly, not harsh)

### Checking Out:
1. Tap "Check Out" button in header
2. **Confirmation: "Leave Table X?" [Stay] [Check Out]**
3. If confirmed: clear localStorage, return to landing page
4. User removed from table map instantly (via WebSocket)

## Technical Requirements:

### Real-time (Flask-SocketIO):
- When user joins: broadcast to all clients to update table map
- When user checks out: broadcast table is now empty
- Messages/drinks: emit to specific table's connected clients
- Handle disconnect: if socket disconnects, keep table occupied for 30 seconds (handles page refresh), then auto-checkout

### Database (SQLite):
- Tables: id, table_number, is_occupied, session_id, last_active
- Messages: id, from_table, to_table, message_type, content, status, timestamp
- No user accounts needed

### File Structure:
project_hugo/
├── app.py              # Flask app, routes, SocketIO events
├── models.py           # SQLite database models
├── templates/
│   ├── base.html       # Shared layout, nav, socket connection
│   ├── index.html      # Landing/table selection
│   ├── menu.html       # Drink menu display
│   └── tables.html     # Table map + interactions
├── static/
│   ├── style.css       # All styles, mobile-first
│   └── app.js          # Socket handling, UI interactions
└── requirements.txt    # Flask, flask-socketio, etc.

## UX Requirements (Important!):

### Confirmations (Prevent Mistakes):
- Always confirm before sending message: "Send to Table X?" [Cancel] [Send ✓]
- Always confirm before sending drink: "Send 🍺 Beer to Table X?" [Cancel] [Send ✓]
- Always confirm before checkout: "Leave Table X?" [Stay] [Check Out]
- Confirmation modals should be simple, clear, and quick to dismiss

### Mobile-First:
- Design for 375px width first, scale up
- Large tap targets (min 44px)
- Bottom navigation bar (thumb-friendly)
- No tiny buttons or links

### Feedback & Affordances:
- Every action has visual feedback (button press, loading state, confirmation)
- Occupied tables should look obviously tappable (subtle pulse or glow)
- Empty tables should look disabled
- Use color consistently (green = success, red = decline, blue = your table)

### Empty State:
- If no other tables occupied: show "You're the first one here! 🎉 Others will appear when they join."

### Error Handling:
- Lost connection: show banner "Reconnecting..." with auto-retry
- If table taken while joining: friendly message, not a crash
- If recipient checks out while sending: "Oops! They just left. Maybe next time!"

### Visual Style:
- Dark theme (easier on eyes in dim restaurant/bar)
- Accent color: warm amber/orange (#F59E0B) for interactive elements
- Rounded corners, soft shadows
- Simple, clean typography (system fonts are fine)
- Subtle animations (nothing flashy)

## Build Order:
1. Landing page with table selection
2. Basic tables page showing all tables
3. Flask-SocketIO: join/leave table, real-time presence
4. Action modal: send preset messages with confirmation
5. Notifications: receive and respond to messages
6. Add drink selection flow with confirmation
7. Menu page
8. Polish: animations, error handling, edge cases
