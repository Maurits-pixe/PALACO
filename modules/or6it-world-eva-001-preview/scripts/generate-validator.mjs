import Ajv2020 from 'ajv/dist/2020.js';
import standaloneCode from 'ajv/dist/standalone/index.js';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const schemaPath = path.join(root, 'schemas/world-design-manifest.schema.json');
const outputPath = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../src/validate-manifest.generated.js');
const schema = JSON.parse(await fs.readFile(schemaPath, 'utf8'));
const ajv = new Ajv2020({
  allErrors: true,
  strict: true,
  code: { esm: true, source: true },
});
const validator = ajv.compile(schema);
const generated = `const stringLength = value => [...value].length;\n${
  standaloneCode(ajv, validator).replaceAll(
    'require("ajv/dist/runtime/ucs2length").default',
    'stringLength',
  )
}\n`;

if (process.argv.includes('--check')) {
  const current = await fs.readFile(outputPath, 'utf8');
  if (current !== generated) {
    console.error('Generated manifest validator is out of date; run npm run schema:generate.');
    process.exitCode = 1;
  }
} else {
  await fs.writeFile(outputPath, generated);
}
