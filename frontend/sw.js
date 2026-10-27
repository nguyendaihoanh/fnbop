// Network-first Service Worker with Offline Cache & Web Push for FnBOps PWA
const CACHE_NAME = 'fnbops-pwa-v10.1';
const CORE_ASSETS = [
  '/',
  '/index.html',
  '/desktop.html',
  '/monthly-report.html',
  '/mobile.css',
  '/style.css',
  '/mobile.js',
  '/app.js',
  '/dist/mobile.bundle.js',
  '/dist/app.min.js',
  '/atomic-tokens.css',
  '/manifest.json',
  '/vendor/iconify-icon.min.js',
  '/vendor/solar-icons-bundle.js',
  '/vendor/chart.umd.min.js'
];

self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return Promise.allSettled(
        CORE_ASSETS.map((url) => cache.add(url).catch(() => null))
      );
    })
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;

  const url = new URL(event.request.url);
  // Skip caching cross-origin tracking or non-http requests
  if (!url.protocol.startsWith('http')) return;

  // AN NINH BẢO MẬT (SEC-04): Tuyệt đối không cache bất kỳ API endpoint hoặc auth nào vào CacheStorage.
  // Tránh rò rỉ dữ liệu lương, công, tài khoản nhân viên offline trên thiết bị dùng chung.
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/api') || url.pathname.startsWith('/auth/')) {
    event.respondWith(
      fetch(event.request).catch(() => {
        return new Response(JSON.stringify({ status: 'offline', error: 'Network unavailable' }), {
          status: 503,
          headers: { 'Content-Type': 'application/json' }
        });
      })
    );
    return;
  }

  event.respondWith(
    fetch(event.request)
      .then((networkRes) => {
        if (networkRes && networkRes.status === 200 && url.origin === self.location.origin) {
          const resClone = networkRes.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, resClone).catch(() => {});
          });
        }
        return networkRes;
      })
      .catch(() => {
        return caches.match(event.request, { ignoreSearch: true }).then((cachedRes) => {
          if (cachedRes) return cachedRes;
          if (event.request.mode === 'navigate') {
            return caches.match('/index.html');
          }
          return new Response(JSON.stringify({ status: 'offline' }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' }
          });
        });
      })
  );
});

// -----------------------------------------------------------------------------
// WEB PUSH NOTIFICATION HANDLERS (WFM SHIFT OPS)
// -----------------------------------------------------------------------------
self.addEventListener('push', (event) => {
  let data = {};
  if (event.data) {
    try {
      data = event.data.json();
    } catch (e) {
      data = { title: 'WFM', body: event.data.text() };
    }
  }

  const title = data.title || 'WFM';
  const options = {
    body: data.body || '',
    icon: data.icon || '/icons/icon-192.png',
    badge: data.badge || '/icons/icon-192.png',
    vibrate: data.vibrate || [100, 50, 100],
    tag: data.tag || 'wfm-shift-notification',
    renotify: true,
    data: data.data || { url: '/' }
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) ? event.notification.data.url : '/';

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (let i = 0; i < clientList.length; i++) {
        const client = clientList[i];
        if (client.url.includes(targetUrl) && 'focus' in client) {
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(targetUrl);
      }
    })
  );
});
