// Run the service's own baseline validation against a converted legacy file.
//
//   node verify/validate-legacy.mjs <file.gpkg> [baseline|postIntervention]
//
// BACKEND_DIR defaults to the backend checkout beside this repo. Any branch
// carrying the single-stage validation pipeline will do.
import path from 'node:path'
import { pathToFileURL } from 'node:url'

// Default to ../bng-metric-backend, the checkout beside this repo, three
// levels up from scale-test-nsip/verify. Override with
// BACKEND_DIR for any other checkout.
const BACKEND = process.env.BACKEND_DIR
  ?? path.resolve(import.meta.dirname, '..', '..', '..', 'bng-metric-backend')
const load = (relative) =>
  import(pathToFileURL(path.join(BACKEND, relative)).href)

const { validateGeoPackageLayers } =
  await load('src/validation/geopackage/index.js')
const { readGeoPackage } = await load('src/validation/geopackage/geopackage.js')
const { FEATURE_READ_MODE } =
  await load('src/validation/geopackage/read-feature-tables.js')

const file = path.resolve(process.argv[2])
const variant = process.argv[3] ?? 'baseline'

const started = Date.now()
const layers = readGeoPackage(file, FEATURE_READ_MODE.properties)
const verdict = await validateGeoPackageLayers(layers, variant, {
  filePath: file,
  includeSizes: true
})
const elapsed = Date.now() - started

const parcelAreas = verdict.sizes?.areas ?? []
const summed = parcelAreas.reduce((total, { value }) => total + value, 0)

console.log(`\n=== ${path.basename(file)} [${variant}] ===`)
console.log(`valid                ${verdict.valid}`)
console.log(`validation time      ${elapsed} ms`)
console.log(`area parcels         ${parcelAreas.length}`)
console.log(`summed parcel area   ${summed.toFixed(6)} sq m`)
for (const error of verdict.errors ?? []) {
  console.log(` ERROR ${error.code} | ${String(error.message).slice(0, 300)}`)
}
process.exit(verdict.valid ? 0 : 1)
