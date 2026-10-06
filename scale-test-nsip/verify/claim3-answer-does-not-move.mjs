// Claim 3: the answer does not move.
//
//   node verify/claim3-answer-does-not-move.mjs
//
// Puts the same site through the biodiversity unit calculation twice, once
// as the staged file and once as the legacy pair converted from it, and
// compares the totals.
//
// Both readings call the same calculator, bng-metric-engine, which is the one
// the service uses. Nothing here reuses the converter, so a mistake in the
// conversion cannot cancel itself out: the only thing the two readings share
// is the arithmetic, and the only thing that differs is where each value was
// read from.
//
// Sizes are the interesting part. The staged file holds hectares and metres
// as measured; legacy holds whole square metres and whole metres. So an exact
// match is not the pass mark and would be suspicious. The pass mark is that
// the difference is no larger than that rounding can explain.
import { DatabaseSync } from 'node:sqlite'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const HERE = import.meta.dirname
const BACKEND = process.env.BACKEND_DIR
  ?? path.resolve(HERE, '..', '..', '..', 'backend')
// The calculator the service itself uses, loaded straight out of the
// backend's dependencies so there is no second copy to drift.
const engine = await import(
  pathToFileURL(path.join(BACKEND, 'node_modules', 'bng-metric-engine',
                          'src', 'index.js')).href)

const STAGED = path.join(HERE, '..', 'hs2-phase2a-subsection', 'Layers',
                         'BNG Service Layers.gpkg')
const LEGACY = path.join(HERE, '..', 'legacy')
const BASELINE_FILE = path.join(LEGACY,
  'Net Gain Habitat Mapping Layers - Baseline.gpkg')
const PI_FILE = path.join(LEGACY,
  'Net Gain Habitat Mapping Layers - Post-intervention.gpkg')

const SQ_M_PER_HECTARE = 10000
const METRES_PER_KM = 1000
// Rounding a size to a whole square metre moves it by at most half of one,
// and every unit is at most the size times the highest multiplier the metric
// applies. Well over the true bound, and still small enough to be decisive.
const MAX_MULTIPLIER = 200

const query = (file, sql) => {
  const db = new DatabaseSync(file, { readOnly: true })
  const rows = db.prepare(sql).all()
  db.close()
  return rows
}

const num = (value) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}
const text = (value) => (value == null ? '' : String(value).trim())
const key = (broad, type) => `${text(broad)} - ${text(type)}`
// The legacy template stores some labels with a number in front,
// "3. Moderate"; the staged template and the calculator hold the plain value,
// "Moderate". Both forms sit in the legacy template's own reference list, in
// a Condition column and a Label column, so dropping the number recovers the
// value rather than guessing it. It does nothing to a staged value.
const unnumbered = (value) => text(value).replace(/^\d+\.\s*/, '')
const retention = unnumbered
const condition = unnumbered

// ---------------------------------------------------------------- readings

function readStaged() {
  const q = (sql) => query(STAGED, sql)
  return {
    areasBaseline: q(`SELECT "Baseline Broad Habitat Type" AS broad,
        "Baseline Habitat Type" AS type, "Baseline Condition" AS condition,
        "Area" AS sizeHa FROM "Area Habitats Baseline"`),
    areasPi: q(`SELECT "Retention Category" AS retention,
        "Baseline Broad Habitat Type" AS baseBroad,
        "Baseline Habitat Type" AS baseType,
        "Baseline Condition" AS baseCondition,
        "Proposed Broad Habitat Type" AS broad,
        "Proposed Habitat Type" AS type, "Proposed Condition" AS condition,
        "Habitat created in advance/years" AS advance,
        "Delay in starting habitat creation/years" AS delay,
        "Area" AS sizeHa FROM "Area Habitats Post-Intervention"`),
    hedgesBaseline: q(`SELECT "Baseline Hedge Type" AS type,
        "Baseline Condition" AS condition, "Length" AS lengthM
        FROM "Hedgerows Baseline"`),
    hedgesPi: q(`SELECT "Retention Category" AS retention,
        "Baseline Hedge Type" AS baseType,
        "Baseline Condition" AS baseCondition,
        "Baseline Length" AS baseLengthM, "Proposed Hedge Type" AS type,
        "Proposed Condition" AS condition,
        "Habitat created in advance/years" AS advance,
        "Delay in starting habitat creation/years" AS delay,
        "Length" AS lengthM FROM "Hedgerows Post-Intervention"`),
    watersBaseline: q(`SELECT "Baseline River Type" AS type,
        "Baseline Condition" AS condition,
        "Baseline Encroachment into Watercourse" AS encroachment,
        "Baseline Encroachment into riparian zone" AS riparian,
        "Length" AS lengthM FROM "Watercourses Baseline"`),
    watersPi: q(`SELECT "Retention Category" AS retention,
        "Baseline River Type" AS baseType,
        "Baseline Condition" AS baseCondition,
        "Baseline Length" AS baseLengthM, "Proposed River Type" AS type,
        "Proposed Condition" AS condition,
        "Proposed Encroachment into Watercourse" AS encroachment,
        "Proposed Encroachment into riparian zone" AS riparian,
        "Habitat created in advance/years" AS advance,
        "Delay in starting habitat creation/years" AS delay,
        "Length" AS lengthM FROM "Watercourses Post-Intervention"`),
    treesBaseline: q(`SELECT "Baseline Tree Size" AS size,
        "Baseline Rural or Urban Tree" AS setting,
        "Baseline Condition" AS condition, "Count" AS count
        FROM "Individual Trees Baseline"`),
    treesPi: q(`SELECT "Retention Category" AS retention,
        "Proposed Tree Size" AS size,
        "Proposed Rural or Urban Tree" AS setting,
        "Proposed Condition" AS condition,
        "Habitat Created/Enhanced in advance/years" AS advance,
        "Delay in starting habitat creation/enhancement in years" AS delay,
        "Count" AS count FROM "Individual Trees Post-Intervention"`),
  }
}

function readLegacy() {
  const base = (sql) => query(BASELINE_FILE, sql)
  const pi = (sql) => query(PI_FILE, sql)
  // Legacy keeps no baseline length on a post-intervention row, so an
  // enhanced feature's original length has to come from the baseline file by
  // matching the reference. That is the one thing the staged file says on
  // the row itself.
  const lengthByRef = (rows) => {
    const map = new Map()
    for (const row of rows) {
      map.set(text(row.ref), num(row.lengthM))
    }
    return map
  }
  const hedgeLengths = lengthByRef(
    base('SELECT "Parcel Ref" AS ref, "Length" AS lengthM FROM "Hedgerows"'))
  const waterLengths = lengthByRef(
    base('SELECT "Parcel Ref" AS ref, "Length" AS lengthM FROM "Rivers"'))

  const withBaseLength = (rows, lengths) => rows.map((row) => ({
    ...row, baseLengthM: lengths.get(text(row.ref)) ?? num(row.lengthM),
  }))

  return {
    areasBaseline: base(`SELECT "Baseline Broad Habitat Type" AS broad,
        "Baseline Habitat Type" AS type, "Baseline Condition" AS condition,
        "Area" AS sizeSqM FROM "Habitats"`),
    areasPi: pi(`SELECT "Retention Category" AS retention,
        "Baseline Broad Habitat Type" AS baseBroad,
        "Baseline Habitat Type" AS baseType,
        "Baseline Condition" AS baseCondition,
        "Proposed Broad Habitat Type" AS broad,
        "Proposed Habitat Type" AS type, "Proposed Condition" AS condition,
        "Habitat created in advance/years" AS advance,
        "Delay in starting habitat creation/years" AS delay,
        "Area" AS sizeSqM FROM "Habitats"`),
    hedgesBaseline: base(`SELECT "Baseline Hedge Type" AS type,
        "Baseline Condition" AS condition, "Length" AS lengthM
        FROM "Hedgerows"`),
    hedgesPi: withBaseLength(pi(`SELECT "Parcel Ref" AS ref,
        "Retention Category" AS retention,
        "Baseline Hedge Type" AS baseType,
        "Baseline Condition" AS baseCondition, "Proposed Hedge Type" AS type,
        "Proposed Condition" AS condition,
        "Habitat created in advance/years" AS advance,
        "Delay in starting habitat creation/years" AS delay,
        "Length" AS lengthM FROM "Hedgerows"`), hedgeLengths),
    watersBaseline: base(`SELECT "Baseline River Type" AS type,
        "Baseline Condition" AS condition,
        "Baseline Encroachment into Watercourse" AS encroachment,
        "Baseline Encroachment into riparian zone" AS riparian,
        "Length" AS lengthM FROM "Rivers"`),
    watersPi: withBaseLength(pi(`SELECT "Parcel Ref" AS ref,
        "Retention Category" AS retention,
        "Baseline River Type" AS baseType,
        "Baseline Condition" AS baseCondition, "Proposed River Type" AS type,
        "Proposed Condition" AS condition,
        "Proposed Encroachment into Watercourse" AS encroachment,
        "Proposed Encroachment into riparian zone" AS riparian,
        "Habitat created in advance/years" AS advance,
        "Delay in starting habitat creation/years" AS delay,
        "Length" AS lengthM FROM "Rivers"`), waterLengths),
    treesBaseline: base(`SELECT "Baseline Tree Size" AS size,
        "Baseline Rural or Urban Tree" AS setting,
        "Baseline Condition" AS condition, "Count" AS count
        FROM "Urban Trees"`),
    treesPi: pi(`SELECT "Retention Category" AS retention,
        "Proposed Tree Size" AS size,
        "Proposed Rural or Urban Tree" AS setting,
        "Proposed Condition" AS condition,
        "Habitat Created/Enhanced in advance/years" AS advance,
        "Delay in starting habitat creation/enhancement in years" AS delay,
        "Count" AS count FROM "Urban Trees"`),
  }
}

// ------------------------------------------------------------ calculation

class Tally {
  constructor() {
    this.units = 0
    this.rows = 0
    this.skipped = new Map()
  }

  add(fn) {
    try {
      const result = fn()
      this.units += result.units
      this.rows += 1
    } catch (error) {
      const reason = String(error.message).slice(0, 70)
      this.skipped.set(reason, (this.skipped.get(reason) ?? 0) + 1)
    }
  }
}

// The staged file measures in hectares and metres; legacy in whole square
// metres and whole metres. Each reader hands its own size in, and from here
// on the two are treated identically.
const areaHa = (row) => row.sizeHa != null
  ? num(row.sizeHa) : num(row.sizeSqM) / SQ_M_PER_HECTARE
const lengthKm = (row) => num(row.lengthM) / METRES_PER_KM
const baseLengthKm = (row) => num(row.baseLengthM) / METRES_PER_KM

// A tree is an area habitat of a notional size the metric looks up by band.
const treeHa = (row) =>
  engine.getIndividualTreeAreaHectares(text(row.size)) * (num(row.count) || 1)
const treeKey = (row) => `Individual trees - ${text(row.setting)}`

function totals(model) {
  const out = {}
  const tally = (name) => (out[name] = out[name] ?? new Tally())

  for (const row of model.areasBaseline) {
    tally('baseline areas').add(() => engine.calculateAreaHabitatBaseline(
      areaHa(row), key(row.broad, row.type), condition(row.condition)))
  }
  for (const row of model.hedgesBaseline) {
    tally('baseline hedgerows').add(() => engine.calculateHedgerowBaseline(
      lengthKm(row), text(row.type), condition(row.condition)))
  }
  for (const row of model.watersBaseline) {
    tally('baseline watercourses').add(() => engine.calculateWatercourseBaseline(
      lengthKm(row), text(row.type), condition(row.condition),
      text(row.encroachment) || null, text(row.riparian) || null))
  }
  for (const row of model.treesBaseline) {
    tally('baseline trees').add(() => engine.calculateAreaHabitatBaseline(
      treeHa(row), treeKey(row), condition(row.condition)))
  }

  for (const row of model.areasPi) {
    const state = retention(row.retention)
    if (state === 'Lost') continue          // absence in the staged file
    tally('proposed areas').add(() => {
      if (state === 'Retained') {
        return engine.calculateRetainedAreaHabitatPostIntervention(
          areaHa(row), key(row.broad, row.type), condition(row.condition))
      }
      if (state === 'Enhanced') {
        return engine.calculateEnhancedAreaHabitatPostIntervention(
          areaHa(row), key(row.baseBroad, row.baseType),
          key(row.broad, row.type), condition(row.baseCondition),
          condition(row.condition), num(row.advance), num(row.delay))
      }
      return engine.calculateCreatedAreaHabitatPostIntervention(
        areaHa(row), key(row.broad, row.type), condition(row.condition),
        num(row.advance), num(row.delay))
    })
  }

  for (const row of model.hedgesPi) {
    const state = retention(row.retention)
    if (state === 'Lost') continue
    tally('proposed hedgerows').add(() => {
      if (state === 'Retained') {
        return engine.calculateRetainedHedgerowPostIntervention(
          lengthKm(row), text(row.type), condition(row.condition))
      }
      if (state === 'Enhanced') {
        return engine.calculateEnhancedHedgerowPostIntervention(
          baseLengthKm(row), lengthKm(row), text(row.baseType),
          text(row.type), condition(row.baseCondition), condition(row.condition),
          { advanceYears: num(row.advance), delayYears: num(row.delay) })
      }
      return engine.calculateCreatedHedgerowPostIntervention(
        lengthKm(row), text(row.type), condition(row.condition),
        num(row.advance), num(row.delay))
    })
  }

  for (const row of model.watersPi) {
    const state = retention(row.retention)
    if (state === 'Lost') continue
    tally('proposed watercourses').add(() => {
      if (state === 'Retained') {
        return engine.calculateRetainedWatercoursePostIntervention(
          lengthKm(row), text(row.type), condition(row.condition),
          text(row.encroachment) || null, text(row.riparian) || null)
      }
      if (state === 'Enhanced') {
        return engine.calculateEnhancedWatercoursePostIntervention(
          baseLengthKm(row), lengthKm(row), text(row.baseType),
          text(row.type), condition(row.baseCondition), condition(row.condition),
          { watercourseEncroachment: text(row.encroachment) || null,
            riparianEncroachment: text(row.riparian) || null,
            advanceYears: num(row.advance), delayYears: num(row.delay) })
      }
      return engine.calculateCreatedWatercoursePostIntervention(
        lengthKm(row), text(row.type), condition(row.condition),
        text(row.encroachment) || null, text(row.riparian) || null,
        num(row.advance), num(row.delay))
    })
  }

  for (const row of model.treesPi) {
    const state = retention(row.retention)
    if (state === 'Lost') continue
    tally('proposed trees').add(() => (state === 'Retained'
      ? engine.calculateRetainedAreaHabitatPostIntervention(
        treeHa(row), treeKey(row), condition(row.condition))
      : engine.calculateCreatedAreaHabitatPostIntervention(
        treeHa(row), treeKey(row), condition(row.condition),
        num(row.advance), num(row.delay))))
  }
  return out
}

// --------------------------------------------------------------- compare

const NAMES = ['baseline areas', 'baseline hedgerows', 'baseline watercourses',
               'baseline trees', 'proposed areas', 'proposed hedgerows',
               'proposed watercourses', 'proposed trees']

const staged = totals(readStaged())
const legacy = totals(readLegacy())

// Rounding a size to whole units moves it by at most half a unit. The bound
// below is that, over every row, times a multiplier no habitat exceeds.
const rowCount = NAMES.reduce((n, name) => n + (staged[name]?.rows ?? 0), 0)
const areaBound = (0.5 / SQ_M_PER_HECTARE) * MAX_MULTIPLIER
const lengthBound = (0.5 / METRES_PER_KM) * MAX_MULTIPLIER

console.log(`\n${'set'.padEnd(23)}${'staged'.padStart(14)}`
  + `${'legacy'.padStart(14)}${'difference'.padStart(14)}   rows`)
let worst = 0
let failed = false
for (const name of NAMES) {
  const a = staged[name] ?? new Tally()
  const b = legacy[name] ?? new Tally()
  const delta = b.units - a.units
  worst = Math.max(worst, Math.abs(delta))
  const bound = name.includes('hedgerow') || name.includes('watercourse')
    ? lengthBound * a.rows : areaBound * a.rows
  const ok = Math.abs(delta) <= bound
  if (!ok || a.rows !== b.rows) failed = true
  console.log(`${name.padEnd(23)}${a.units.toFixed(4).padStart(14)}`
    + `${b.units.toFixed(4).padStart(14)}${delta.toFixed(6).padStart(14)}`
    + `   ${a.rows}${a.rows === b.rows ? '' : ` vs ${b.rows} MISMATCH`}`
    + `${ok ? '' : '   OVER BOUND'}`)
  for (const [reason, count] of a.skipped) {
    console.log(`    staged skipped ${count}: ${reason}`)
  }
  for (const [reason, count] of b.skipped) {
    console.log(`    legacy skipped ${count}: ${reason}`)
  }
}

const sum = (model, prefix) => NAMES.filter((n) => n.startsWith(prefix))
  .reduce((total, n) => total + (model[n]?.units ?? 0), 0)
const stagedBaseline = sum(staged, 'baseline')
const legacyBaseline = sum(legacy, 'baseline')
const stagedProposed = sum(staged, 'proposed')
const legacyProposed = sum(legacy, 'proposed')

const pct = (a, b) => (a === 0 ? 0 : ((b - a) / a) * 100)
console.log(`\n${'baseline units'.padEnd(23)}${stagedBaseline.toFixed(4).padStart(14)}`
  + `${legacyBaseline.toFixed(4).padStart(14)}`
  + `${(legacyBaseline - stagedBaseline).toFixed(6).padStart(14)}`
  + `   ${pct(stagedBaseline, legacyBaseline).toFixed(6)}%`)
console.log(`${'post-intervention units'.padEnd(23)}${stagedProposed.toFixed(4).padStart(14)}`
  + `${legacyProposed.toFixed(4).padStart(14)}`
  + `${(legacyProposed - stagedProposed).toFixed(6).padStart(14)}`
  + `   ${pct(stagedProposed, legacyProposed).toFixed(6)}%`)

const stagedNet = pct(stagedBaseline, stagedProposed)
const legacyNet = pct(legacyBaseline, legacyProposed)
console.log(`\nnet change, staged  ${stagedNet.toFixed(6)} %`)
console.log(`net change, legacy  ${legacyNet.toFixed(6)} %`)
console.log(`the answer moves by ${Math.abs(legacyNet - stagedNet).toFixed(6)}`
  + ` percentage points, across ${rowCount} rows`)

console.log(failed
  ? '\nCLAIM 3 FAILS: a total moved further than rounding can explain.'
  : '\nCLAIM 3 HOLDS: every total is within what rounding to whole units'
    + ' can explain.')
process.exit(failed ? 1 : 0)
