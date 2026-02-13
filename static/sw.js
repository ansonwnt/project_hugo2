// Service Worker for Shamrock PWA
// Required for iOS notifications in Add-to-Home-Screen mode

const CACHE_NAME = 'shamrock-v1';

// Install — cache essential assets
self.addEventListener('install', (event) => {
    self.skipWaiting();
});

// Activate — clean old caches
self.addEventListener('activate', (event) => {
    event.waitUntil(clients.claim());
});

// Fetch — pass through (no offline caching needed)
self.addEventListener('fetch', (event) => {
    event.respondWith(fetch(event.request));
});

// Handle push events (for future server push support)
self.addEventListener('push', (event) => {
    const data = event.data ? event.data.json() : {};
    const title = data.title || 'Shamrock';
    const options = {
        body: data.body || 'You have a new notification',
        icon: '/static/icon-192.png',
    };
    event.waitUntil(self.registration.showNotification(title, options));
});

// Handle notification clicks
self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
            // Focus existing window or open new one
            for (const client of clientList) {
                if (client.url.includes('/tables') && 'focus' in client) {
                    return client.focus();
                }
            }
            if (clients.openWindow) {
                return clients.openWindow('/tables');
            }
        })
    );
});
