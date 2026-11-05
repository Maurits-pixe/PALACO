const FRAME_INTERVAL = 1000 / 60;

export function startAmbientAnimation(canvas, {
  windowObject = window,
  documentObject = document,
} = {}) {
  const context = canvas.getContext('2d');
  if (!context) return { setEnabled() {}, dispose() {} };

  const reducedMotion = windowObject.matchMedia('(prefers-reduced-motion: reduce)');
  let frameId = 0;
  let lastFrame = 0;
  let lastTimestamp;
  let elapsedMs = 0;
  let width = 0;
  let height = 0;
  let pixelRatio = 1;
  let particles = [];
  let enabled = true;
  let disposed = false;

  function resize() {
    const bounds = canvas.getBoundingClientRect();
    pixelRatio = Math.min(windowObject.devicePixelRatio || 1, 2);
    width = bounds.width;
    height = bounds.height;
    canvas.width = Math.round(width * pixelRatio);
    canvas.height = Math.round(height * pixelRatio);
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);

    if (width <= 0 || height <= 0) {
      particles = [];
      stop();
      return;
    }

    const count = Math.min(64, Math.max(12, Math.floor(width / 18)));
    particles = Array.from({ length: count }, (_, index) => ({
      x: ((index * 67) % 997) / 997,
      y: ((index * 131) % 991) / 991,
      phase: (index * 2.399) % (Math.PI * 2),
      radius: 0.7 + (index % 4) * 0.25,
    }));
  }

  function draw(now) {
    if (reducedMotion.matches || documentObject.hidden) return;
    if (now < lastFrame) {
      lastFrame = 0;
      lastTimestamp = undefined;
    }
    if (now - lastFrame < FRAME_INTERVAL) {
      frameId = windowObject.requestAnimationFrame(draw);
      return;
    }

    if (lastTimestamp !== undefined) elapsedMs += now - lastTimestamp;
    lastTimestamp = now;
    lastFrame = now;
    const elapsed = elapsedMs / 1000;
    context.clearRect(0, 0, width, height);
    for (const particle of particles) {
      const drift = (elapsed * 0.006 + particle.phase / (Math.PI * 2)) % 1;
      const x = ((particle.x + drift * 0.12) % 1) * width;
      const y = ((particle.y + Math.sin(elapsed * 0.2 + particle.phase) * 0.015 + 1) % 1) * height;
      const opacity = 0.12 + ((Math.sin(elapsed * 0.7 + particle.phase) + 1) * 0.12);
      context.fillStyle = `rgba(218, 198, 151, ${opacity})`;
      context.beginPath();
      context.arc(x, y, particle.radius, 0, Math.PI * 2);
      context.fill();
    }

    frameId = windowObject.requestAnimationFrame(draw);
  }

  function stop() {
    windowObject.cancelAnimationFrame(frameId);
    frameId = 0;
    lastFrame = 0;
    lastTimestamp = undefined;
    context.clearRect(0, 0, width, height);
  }

  function start() {
    if (disposed || frameId || width <= 0 || height <= 0 || !enabled ||
      reducedMotion.matches || documentObject.hidden) return;
    frameId = windowObject.requestAnimationFrame(draw);
  }

  function onVisibilityChange() {
    if (documentObject.hidden) stop();
    else start();
  }

  function onMotionChange() {
    if (reducedMotion.matches) stop();
    else start();
  }

  function onResize() {
    resize();
    start();
  }

  resize();
  start();
  windowObject.addEventListener('resize', onResize);
  documentObject.addEventListener('visibilitychange', onVisibilityChange);
  reducedMotion.addEventListener('change', onMotionChange);

  function setEnabled(nextEnabled) {
    enabled = Boolean(nextEnabled);
    if (enabled) start();
    else stop();
  }

  function dispose() {
    disposed = true;
    stop();
    windowObject.removeEventListener('resize', onResize);
    documentObject.removeEventListener('visibilitychange', onVisibilityChange);
    reducedMotion.removeEventListener('change', onMotionChange);
  }

  return { setEnabled, dispose };
}
