// NR2 Network Service Worker v1.0
const CACHE_NAME = 'nr2-cache-v1';
const OFFLINE_URL = '/offline';

// 기본 캐시할 정적 리소스
const PRECACHE_URLS = [
  '/',
  '/offline',
  '/static/icons/icon-192x192.png',
  '/static/icons/icon-512x512.png'
];

// 설치: 정적 리소스 프리캐시
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
  );
});

// 활성화: 이전 캐시 삭제
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME)
          .map((name) => caches.delete(name))
      );
    }).then(() => self.clients.claim())
  );
});

// 네트워크 우선 전략 (뉴스 사이트는 최신 콘텐츠가 중요)
self.addEventListener('fetch', (event) => {
  const { request } = event;

  // API 요청이나 외부 요청은 캐시하지 않음
  if (!request.url.startsWith(self.location.origin)) return;
  if (request.method !== 'GET') return;

  // 정적 리소스 (CSS, JS, 이미지): 캐시 우선
  if (request.url.match(/\.(css|js|png|jpg|jpeg|svg|ico|woff2?)$/)) {
    event.respondWith(
      caches.match(request).then((cached) => {
        const fetchPromise = fetch(request).then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
          }
          return response;
        }).catch(() => cached);
        return cached || fetchPromise;
      })
    );
    return;
  }

  // HTML 페이지: 네트워크 우선, 실패시 캐시, 최종 오프라인 페이지
  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
        }
        return response;
      })
      .catch(() => {
        return caches.match(request).then((cached) => {
          return cached || caches.match(OFFLINE_URL);
        });
      })
  );
});
