import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.dirname(fileURLToPath(import.meta.url));
const referencePath = path.resolve(root, '../../assets/world-eva-001-reference.png');
const referenceUrl = '/assets/world-eva-001-reference.png';

const referenceAsset = {
  name: 'eva-reference-asset',
  configureServer(server) {
    server.middlewares.use((request, response, next) => {
      if (request.url?.split('?')[0] !== referenceUrl) {
        next();
        return;
      }

      response.setHeader('Content-Type', 'image/png');
      fs.createReadStream(referencePath).pipe(response);
    });
  },
  generateBundle() {
    this.emitFile({
      type: 'asset',
      fileName: 'assets/world-eva-001-reference.png',
      source: fs.readFileSync(referencePath),
    });
  },
};

export default defineConfig({
  plugins: [vue(), referenceAsset],
  server: {
    host: '127.0.0.1',
    strictPort: true,
  },
  preview: {
    host: '127.0.0.1',
    strictPort: true,
  },
});
