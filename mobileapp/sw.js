const CACHE = 'rita-v1';
const ASSETS = [
  './',
  './index.html',
  './manifest.json',
  './icons/icon.svg',
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(ASSETS)).catch(err => console.error('[RITA-SW]', err))
  );
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).catch(err => console.error('[RITA-SW]', err))
  );
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request)).catch(err => console.error('[RITA-SW]', err))
  );
});
