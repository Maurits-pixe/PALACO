// Isolated test host, not part of the production entry/bundle.
import { createApp } from 'vue';
import App from './src/App.vue';
import './src/style.css';
let app;
function mount() { if (!app) { app = createApp(App); app.mount('#app'); } }
document.querySelector('[data-host-unmount]').onclick = () => { app?.unmount(); app = null; };
document.querySelector('[data-host-mount]').onclick = mount;
mount();
