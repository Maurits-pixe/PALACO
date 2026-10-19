<script setup>
import { computed, nextTick, ref } from 'vue';
import { events, metrics, reviewBreakdown, reviewBreakdownLabel, reviewPercentages as calculateReviewPercentages, reviewSummaryLabel, trafficSamples } from './telemetry.js';

const selectedSeverity = ref('Alles');
const severities = ['Alles', 'Hoog', 'Middel', 'Laag'];
const reviewTotal = reviewBreakdown.reduce((total, item) => total + item.count, 0);
const reviewPercentages = calculateReviewPercentages(reviewBreakdown, reviewTotal);
const reviewStateText = reviewSummaryLabel(reviewTotal);
const reviewBreakdownText = reviewBreakdownLabel(reviewBreakdown, reviewTotal);
const severityTones = { Hoog: 'high', Middel: 'medium', Laag: 'low' };
const visibleEvents = computed(() => selectedSeverity.value === 'Alles'
  ? events
  : events.filter(event => event.severity === selectedSeverity.value));
const filterStatusText = computed(() => {
  const count = visibleEvents.value.length;
  const result = `${count} synthetisch${count === 1 ? ' signaal' : 'e signalen'}`;
  return selectedSeverity.value === 'Alles'
    ? `Toont ${result}.`
    : `Toont ${result} met ernst ${selectedSeverity.value}.`;
});

function barHeight(value) {
  return `${Math.max(8, value)}%`;
}

async function printReport() {
  const reviewDetails = document.querySelector('.review-details');
  const wasOpen = reviewDetails.open;
  const previousSeverity = selectedSeverity.value;
  reviewDetails.open = true;
  selectedSeverity.value = 'Alles';
  await nextTick();
  window.addEventListener('afterprint', () => {
    reviewDetails.open = wasOpen;
    selectedSeverity.value = previousSeverity;
  }, { once: true });
  window.print();
}

</script>

<template>
  <div class="dashboard">
    <header class="topbar">
      <a class="brand" href="/" aria-label="5CRIPTIE preview start">
        <span class="brand-mark" aria-hidden="true"><span></span><span></span><span></span></span>
        <span>5CRIPTIE<span class="brand-caption">SIGNAL REVIEW</span></span>
      </a>
      <div class="topbar-meta">
        <span class="mode-pill"><span class="mode-dot"></span> SYNTHETISCHE PREVIEW</span>
        <span class="workspace">PALACO · LOKALE DEMO</span>
        <button class="print-action" type="button" @click="printReport">Afdrukken / opslaan als PDF</button>
      </div>
    </header>

    <main>
      <section class="intro">
        <div>
          <p class="eyebrow">MONITORING INTERFACE / PREVIEW.1</p>
          <h1>Signal overview</h1>
          <p class="intro-copy">Een statische demonstratie van een beveiligingsmonitoringinterface.</p>
        </div>
        <div class="time-window"><span class="live-indicator"></span> VASTE DEMODATA <span class="divider">/</span> VENSTER 60 MIN</div>
      </section>

      <aside class="preview-warning" role="note">
        <span class="warning-icon" aria-hidden="true">i</span>
        <p><strong>Geen echte monitoring.</strong> Alle cijfers, bronnen, signalen en tijden hieronder zijn vaste, synthetische fixtures. Deze preview scant geen netwerk, leest geen hoststatus uit en verzendt geen data.</p>
      </aside>

      <section class="metric-grid" aria-label="Synthetische overzichtswaarden">
        <article v-for="metric in metrics" :key="metric.id" class="metric-card" :class="metric.tone">
          <div class="metric-head"><span>{{ metric.label }}</span><span class="metric-icon" aria-hidden="true">▦</span></div>
          <div class="metric-value">{{ metric.value }}</div>
          <div class="metric-foot"><span class="metric-dot"></span>{{ metric.change }}</div>
        </article>
      </section>

      <section class="content-grid">
        <article class="panel traffic-panel">
          <div class="panel-head">
            <div><p class="eyebrow">FIXTURESET A / SAMPLE</p><h2>Signaalvolume</h2></div>
            <span class="panel-tag">SYNTHETISCH</span>
          </div>
          <div class="chart" role="img" aria-label="Decoratieve grafiek met vaste synthetische voorbeeldwaarden">
            <div class="chart-y-axis"><span>100</span><span>75</span><span>50</span><span>25</span><span>0</span></div>
            <div class="chart-area">
              <div class="chart-grid"><span></span><span></span><span></span><span></span><span></span></div>
              <div class="bars">
                <div v-for="sample in trafficSamples" :key="sample.time" class="bar-column">
                  <span class="bar" :style="{ height: barHeight(sample.value) }" :title="`${sample.time}: synthetische sample`"></span>
                  <span class="bar-label">{{ sample.time.slice(3) }}</span>
                </div>
              </div>
            </div>
          </div>
          <p class="chart-caption"><span class="legend-dot"></span> Vaste voorbeeldreeks <span class="caption-note">Geen netwerkmeting</span></p>
        </article>

        <article class="panel review-panel">
          <div class="panel-head">
            <div><p class="eyebrow">STATISCHE DEMO</p><h2>Reviewverdeling</h2></div>
            <span class="panel-tag">FIXTURES</span>
          </div>
          <div class="review-total" :aria-label="reviewStateText">
            <strong>{{ String(reviewTotal).padStart(2, '0') }}</strong>
            <span>{{ reviewTotal === 1 ? 'voorbeeldsignaal' : 'voorbeeldsignalen' }}</span>
          </div>
          <p v-if="reviewTotal === 0" class="review-empty" role="status">Geen openstaande reviewmeldingen in deze fixtures.</p>
          <div class="review-breakdown" aria-hidden="true">
            <template v-if="reviewTotal > 0">
              <div v-for="(item, index) in reviewBreakdown" :key="item.severity" class="review-row">
                <span class="review-label"><i class="severity" :class="severityTones[item.severity]"></i>{{ item.severity }}</span>
                <strong>{{ String(item.count).padStart(2, '0') }}</strong>
                <span class="review-track"><i :class="`${severityTones[item.severity]}-fill`"
                  :style="{ width: `${reviewPercentages[index]}%` }"></i></span>
                <span class="review-percent">{{ reviewPercentages[index] }}%</span>
              </div>
            </template>
          </div>
          <p class="sr-only" role="status">{{ reviewBreakdownText }}</p>
          <details class="review-details">
            <summary>Toon reviewverdeling als tabel</summary>
            <table>
              <caption class="sr-only">Synthetische reviewmeldingen per ernstcategorie</caption>
              <thead><tr><th scope="col">Ernst</th><th scope="col">Aantal</th><th scope="col">Percentage</th></tr></thead>
              <tbody>
                <tr v-for="(item, index) in reviewBreakdown" :key="item.severity">
                  <th scope="row">{{ item.severity }}</th>
                  <td>{{ item.count }}</td>
                  <td>{{ reviewPercentages[index] }}%</td>
                </tr>
                <tr>
                  <th scope="row">Totaal</th>
                  <td>{{ reviewTotal }}</td>
                  <td>{{ reviewTotal ? '100%' : '0%' }}</td>
                </tr>
              </tbody>
            </table>
          </details>
          <p class="review-note">Categorisering is illustratief en niet gebaseerd op detectie.</p>
        </article>
      </section>

      <section class="panel events-panel">
        <div class="panel-head event-header">
          <div><p class="eyebrow">GELOCALISEERDE VOORBEELDEN</p><h2>Signaalreview</h2></div>
          <div class="filter-group" role="group" aria-label="Filter synthetische signalen">
            <button v-for="severity in severities" :key="severity" type="button"
              :class="{ selected: selectedSeverity === severity }" :aria-pressed="selectedSeverity === severity"
              @click="selectedSeverity = severity">{{ severity }}</button>
          </div>
        </div>
        <p class="sr-only" role="status">{{ filterStatusText }}</p>
        <div class="table-wrap">
          <table>
            <caption class="sr-only">Vaste synthetische signalen, gefilterd op ernst</caption>
            <thead><tr><th scope="col">Fixture ID</th><th scope="col">Tijd*</th><th scope="col">Bronfixture</th><th scope="col">Categorie</th><th scope="col">Prioriteit</th><th scope="col">Samenvatting</th><th scope="col">Label</th></tr></thead>
            <tbody>
              <tr v-for="event in visibleEvents" :key="event.id">
                <td class="event-id">{{ event.id }}</td>
                <td class="event-time">{{ event.time }}</td>
                <td>{{ event.source }}</td>
                <td>{{ event.category }}</td>
                <td><span class="severity-badge" :class="event.severity.toLowerCase()">{{ event.severity }}</span></td>
                <td class="event-summary">{{ event.summary }}</td>
                <td><span class="status-label" :class="{ review: event.status === 'Review' }">{{ event.status }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="table-footnote">*Tijden zijn tekst in voorbeelddata; geen live of historische systeemtimestamps.</p>
      </section>
    </main>

    <footer class="footer">
      <span>5CRIPTIE <span class="footer-separator">/</span> PREVIEW-CANDIDATE</span>
      <span>Alle data is synthetisch · Geen sensoren · Geen scans · Geen acties</span>
    </footer>
  </div>
</template>
