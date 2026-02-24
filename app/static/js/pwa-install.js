/* ===== NR2 PWA 설치 배너 + 서비스워커 등록 =====
   base.html의 </body> 바로 위에 <script> 태그로 추가하세요
   ================================================= */

// 1. 서비스워커 등록
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js')
      .then((reg) => console.log('✅ SW 등록:', reg.scope))
      .catch((err) => console.log('❌ SW 실패:', err));
  });
}

// 2. PWA 설치 프롬프트 가로채기
let deferredPrompt = null;

window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredPrompt = e;
  showInstallBanner();
});

// 3. 설치 배너 표시
function showInstallBanner() {
  // 이미 닫았으면 24시간 동안 안 보여줌
  const dismissed = localStorage.getItem('nr2_pwa_dismissed');
  if (dismissed && Date.now() - parseInt(dismissed) < 86400000) return;

  // 이미 설치된 상태면 안 보여줌
  if (window.matchMedia('(display-mode: standalone)').matches) return;

  const banner = document.createElement('div');
  banner.id = 'nr2-install-banner';
  banner.innerHTML = `
    <div style="
      position: fixed; bottom: 0; left: 0; right: 0; z-index: 9999;
      background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
      border-top: 2px solid #f5a623;
      padding: 16px 20px;
      display: flex; align-items: center; justify-content: space-between;
      gap: 12px;
      box-shadow: 0 -4px 20px rgba(0,0,0,0.3);
      animation: slideUp 0.3s ease-out;
    ">
      <div style="display: flex; align-items: center; gap: 12px; flex: 1;">
        <span style="font-size: 28px;">🌐</span>
        <div>
          <div style="color: #f5a623; font-weight: 700; font-size: 14px;">NR2 앱 설치하기</div>
          <div style="color: #999; font-size: 12px; margin-top: 2px;">홈 화면에 추가하고 빠르게 접속하세요</div>
        </div>
      </div>
      <button onclick="installPWA()" style="
        background: #f5a623; color: #1a1a2e; border: none;
        padding: 10px 20px; border-radius: 8px;
        font-weight: 700; font-size: 14px; cursor: pointer;
        white-space: nowrap;
      ">설치</button>
      <button onclick="dismissInstall()" style="
        background: none; border: none; color: #666;
        font-size: 20px; cursor: pointer; padding: 4px 8px;
      ">✕</button>
    </div>
  `;

  // 슬라이드 업 애니메이션
  const style = document.createElement('style');
  style.textContent = '@keyframes slideUp { from { transform: translateY(100%); } to { transform: translateY(0); } }';
  document.head.appendChild(style);

  document.body.appendChild(banner);
}

// 4. 설치 실행
function installPWA() {
  if (!deferredPrompt) return;
  deferredPrompt.prompt();
  deferredPrompt.userChoice.then((result) => {
    if (result.outcome === 'accepted') {
      console.log('✅ PWA 설치 완료');
    }
    deferredPrompt = null;
    const banner = document.getElementById('nr2-install-banner');
    if (banner) banner.remove();
  });
}

// 5. 배너 닫기 (24시간 숨김)
function dismissInstall() {
  localStorage.setItem('nr2_pwa_dismissed', Date.now().toString());
  const banner = document.getElementById('nr2-install-banner');
  if (banner) banner.remove();
}

// 6. iOS Safari 안내 (beforeinstallprompt 미지원)
if (/iPhone|iPad/.test(navigator.userAgent) && !window.navigator.standalone) {
  setTimeout(() => {
    if (!deferredPrompt) {
      const dismissed = localStorage.getItem('nr2_pwa_dismissed');
      if (dismissed && Date.now() - parseInt(dismissed) < 86400000) return;

      const iosBanner = document.createElement('div');
      iosBanner.id = 'nr2-install-banner';
      iosBanner.innerHTML = `
        <div style="
          position: fixed; bottom: 0; left: 0; right: 0; z-index: 9999;
          background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
          border-top: 2px solid #f5a623;
          padding: 16px 20px;
          box-shadow: 0 -4px 20px rgba(0,0,0,0.3);
          animation: slideUp 0.3s ease-out;
        ">
          <div style="display: flex; align-items: center; justify-content: space-between;">
            <div style="display: flex; align-items: center; gap: 12px; flex: 1;">
              <span style="font-size: 28px;">🌐</span>
              <div>
                <div style="color: #f5a623; font-weight: 700; font-size: 14px;">NR2 앱 설치하기</div>
                <div style="color: #999; font-size: 12px; margin-top: 4px;">
                  Safari 하단의 <span style="font-size: 16px;">⎙</span> 공유 버튼 →<br>
                  <strong style="color: #e0e0e0;">"홈 화면에 추가"</strong>를 누르세요
                </div>
              </div>
            </div>
            <button onclick="dismissInstall()" style="
              background: none; border: none; color: #666;
              font-size: 20px; cursor: pointer; padding: 4px 8px;
            ">✕</button>
          </div>
        </div>
      `;
      document.body.appendChild(iosBanner);
    }
  }, 3000);
}
