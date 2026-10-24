import { pathToFileURL } from 'node:url';
import { mainForRequest } from './era-pad-cli.mjs';

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await mainForRequest();
}
