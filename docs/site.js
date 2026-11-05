// Page behavior: a rule under the nav once you scroll past the hero, and the agent recording that only shows once the video file exists.
(() => {
  const nav = document.querySelector('.nav');
  const hero = document.querySelector('.hero');
  if (nav && hero && 'IntersectionObserver' in window) new IntersectionObserver(([e]) => nav.classList.toggle('solid', !e.isIntersecting), { rootMargin: '-64px 0px 0px 0px' }).observe(hero);

  // Drop docs/media/agent-demo.mp4 into the repo and the recording appears next to the report.
  const rec = document.getElementById('recording');
  const vid = rec && rec.querySelector('video');
  if (vid) vid.addEventListener('loadedmetadata', () => { rec.hidden = false; });
})();

// The hero film: autoplays muted; one button to pause, and paused by default for reduced motion.
(() => {
  const film = document.getElementById('film');
  const btn = document.getElementById('playpause');
  if (!film || !btn) return;
  const sync = () => { btn.textContent = film.paused ? 'Play' : 'Pause'; btn.setAttribute('aria-label', film.paused ? 'Play the film' : 'Pause the film'); };
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) { film.removeAttribute('autoplay'); film.pause(); }
  btn.addEventListener('click', () => (film.paused ? film.play() : film.pause()));
  film.addEventListener('play', sync); film.addEventListener('pause', sync); sync();
})();
