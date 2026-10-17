/* Explicit locale routes: default Japanese; saved samples only. */
(() => {
  const root = new URL('./', document.currentScript.src);
  const chinese = document.documentElement.lang === 'zh-CN';
  const app = !!document.getElementById('school-select');
  const nav = document.createElement('nav');
  nav.className = 'language-switch';
  nav.setAttribute('aria-label', chinese ? '切换语言' : '表示言語');
  for (const [locale, label] of [['ja', '日本語'], ['zh-CN', '中文']]) {
    const active = (locale === 'zh-CN') === chinese;
    const link = document.createElement('a');
    link.textContent = label; link.lang = locale; link.hreflang = locale;
    if (active) link.setAttribute('aria-current', 'true');
    const destination = new URL((locale === 'zh-CN' ? 'zh/' : '') + (app ? 'app/' : ''), root);
    if (app) destination.search = location.search;
    link.href = destination.href;
    link.title = chinese ? '保留学校和示例，重新打开第一步' : '学校とサンプルを引き継いでステップ1を開きます';
    link.addEventListener('click', () => {
      if (!app) return;
      const school = document.getElementById('school-select').value;
      const scenario = document.getElementById('demo-scenario').value;
      destination.search = '';
      if (school) destination.searchParams.set('school', school === 'isct' ? 'isct' : 'gsfs');
      if (scenario) destination.searchParams.set('scenario', scenario);
      link.href = destination.href;
    });
    nav.append(link);
  }
  const host = app ? document.querySelector('.demo-banner-inner') : document.querySelector('.topbar');
  host.append(nav);
})();
