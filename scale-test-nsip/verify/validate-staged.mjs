// Run the staged (BNG Service template) validation against the site file.
//
//   STAGED_BACKEND_DIR=/path/to/backend/on/the/staged/branch \
//   node verify/validate-staged.mjs <file.gpkg>
//
// Needs a PostGIS database, because the lineage overlay runs there. The
// backend's own compose stack provides one; connection settings come from the
// PG* environment variables, defaulting to that stack.
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const BACKEND = process.env.STAGED_BACKEND_DIR
if (!BACKEND) {
  console.error('set STAGED_BACKEND_DIR to a backend checkout carrying '
                + 'src/validation/geopackage/lineage/')
  process.exit(2)
}
const load = (relative) =>
  import(pathToFileURL(path.join(BACKEND, relative)).href)

const { default: pg } = await load('node_modules/pg/lib/index.js')
const { validateStagedGeoPackage } =
  await load('src/validation/geopackage/lineage/validate-staged-geopackage.js')

const file = path.resolve(process.argv[2])
const pool = new pg.Pool({
  host: process.env.PGHOST ?? 'localhost',
  port: Number(process.env.PGPORT ?? 5432),
  user: process.env.PGUSER ?? 'dev',
  password: process.env.PGPASSWORD ?? 'dev',
  database: process.env.PGDATABASE ?? 'bng_metric_backend',
  max: 4
})

const started = Date.now()
const verdict = await validateStagedGeoPackage(file, pool)
const elapsed = Date.now() - started

console.log(`\n=== ${path.basename(file)} [staged] ===`)
console.log(`valid                ${verdict.valid}`)
console.log(`validation time      ${elapsed} ms`)
console.log(`removal entries      ${verdict.removed?.length ?? 0}`)
for (const error of verdict.errors ?? []) {
  console.log(` ERROR ${error.code} | ${String(error.message).slice(0, 300)}`)
}
for (const warning of verdict.warnings ?? []) {
  console.log(` warn  ${warning.code} | ${String(warning.message).slice(0, 160)}`)
}
await pool.end()
process.exit(verdict.valid ? 0 : 1)
