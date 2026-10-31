<script setup>
import { events, indicators, snapshot } from './fixtures.js';
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <div class="wordmark">
        <span class="brand-mark" aria-hidden="true">O</span>
        <span><strong>OR6IT</strong><small>WORLD SYSTEMS / CONCEPT</small></span>
      </div>
      <p class="top-state"><span class="state-light" aria-hidden="true"></span> DEMO MODE <span>·</span> NO LIVE INPUT</p>
    </header>

    <main id="overview">
      <section class="warning" aria-label="Preview limitations">
        <span class="warning-tag">SYNTHETIC PREVIEW</span>
        <p>Every value below is invented fixture data. This read-only concept has no live connection, authority, or action path.</p>
      </section>

      <section class="heading">
        <div>
          <p class="eyebrow">WORLD OVERVIEW <span>/</span> {{ snapshot.snapshotId }}</p>
          <h1>{{ snapshot.worldId }}</h1>
          <p class="lede">A static interface study for a hypothetical orbital habitat.</p>
        </div>
        <div class="snapshot-stamp">
          <span>FIXTURE TIMESTAMP</span>
          <time :datetime="snapshot.capturedAt">15 JAN 2025 · 12:00 UTC</time>
        </div>
      </section>

      <section class="dashboard" aria-label="Synthetic world dashboard">
        <article class="panel orbit-panel">
          <div class="panel-heading">
            <div><p class="eyebrow">01 / ORBITAL FRAME</p><h2>System schematic</h2></div>
            <span class="panel-label">2D · ILLUSTRATIVE</span>
          </div>
          <figure class="orbit-figure">
            <svg class="orbit-art" viewBox="0 0 640 360" role="img" aria-labelledby="orbit-title orbit-description">
              <title id="orbit-title">Illustrative orbital system</title>
              <desc id="orbit-description">A non-geographic, synthetic 2D diagram with a central reference body and a decorative orbit path.</desc>
              <defs>
                <radialGradient id="body-glow">
                  <stop offset="0" stop-color="#b5ecff" stop-opacity=".55" />
                  <stop offset="1" stop-color="#69c9e8" stop-opacity="0" />
                </radialGradient>
              </defs>
              <circle cx="320" cy="180" r="95" fill="url(#body-glow)" />
              <ellipse class="orbit-ring" cx="320" cy="180" rx="232" ry="101" />
              <circle class="reference-body" cx="320" cy="180" r="27" />
              <path class="body-shade" d="M320 153a27 27 0 0 1 0 54z" />
              <g class="orbit-marker">
                <circle cx="552" cy="180" r="6" />
                <circle class="marker-halo" cx="552" cy="180" r="14" />
              </g>
              <circle class="schematic-point" cx="112" cy="136" r="2" />
              <circle class="schematic-point" cx="468" cy="265" r="2" />
              <path class="crosshair" d="M320 143v-8m0 90v-8m-37-37h-8m90 0h-8" />
              <text class="svg-caption" x="320" y="324" text-anchor="middle">STATIC SCHEMATIC · NOT TO SCALE</text>
            </svg>
            <figcaption>Decorative motion is independent of fixture values and does not represent a live object.</figcaption>
          </figure>
          <div class="orbit-footer">
            <span><i class="legend-dot body-dot"></i>Reference body <b>SIMULATED</b></span>
            <span><i class="legend-dot marker-dot"></i>Orbit marker <b>FIXTURE</b></span>
          </div>
        </article>

        <article class="panel telemetry-panel">
          <div class="panel-heading">
            <div><p class="eyebrow">02 / SAMPLE INDICATORS</p><h2>Fixture values</h2></div>
            <span class="panel-label">STATIC</span>
          </div>
          <dl class="indicator-list">
            <div v-for="indicator in indicators" :key="indicator.label" class="indicator">
              <dt>{{ indicator.label }}<small>{{ indicator.note }}</small></dt>
              <dd>{{ indicator.value }}<span>{{ indicator.unit }}</span></dd>
            </div>
          </dl>
          <p class="data-caption"><span aria-hidden="true">ⓘ</span> Values are examples only—not observations or operating limits.</p>
        </article>

        <article class="panel timeline-panel">
          <div class="panel-heading">
            <div><p class="eyebrow">03 / SCENARIO NOTES</p><h2>Sample sequence</h2></div>
            <span class="panel-label">FIXTURE LOG</span>
          </div>
          <ol class="timeline">
            <li v-for="(event, index) in events" :key="event.time" :class="{ latest: index === events.length - 1 }">
              <time>{{ event.time }}</time>
              <div><h3>{{ event.title }}</h3><p>{{ event.detail }}</p></div>
            </li>
          </ol>
        </article>
      </section>
    </main>

    <footer class="footer">
      <span>{{ snapshot.project }} <i>/</i> {{ snapshot.mode }}</span>
      <p>Fictional interface demo · no API · no polling · no commands · no external effects</p>
    </footer>
  </div>
</template>
