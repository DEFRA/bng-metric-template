"""Habitat attributes and the intervention, for the NSIP-scale corridor.

Baseline habitats follow slowly drifting landscape bands, so the site reads as
pasture giving way to arable, woodland and the odd settlement edge rather than
as noise. The intervention is a rail alignment that weaves within the land
take: a sealed core, earthworks either side, a mitigation margin beyond that,
and untouched land at the edges.

Only Medium, Low and V.Low distinctiveness habitats appear. That is the scope
the service accepts, and it is also the scope of the controlled beta.

Every value used here is taken from the template's own reference lists, so a
surveyor opening the file sees valid dropdown selections throughout.
"""

import csv
import collections
import os

from corridor_mesh import _hash01

# Read from the template rather than from the working copy: the working copy
# is generated, and these lists are loaded at import time.
CSV_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        '..', '..',
                        'templates', 'bng-service', 'CSV References')

# The template stores strategic significance as Low or High. Every baseline
# feature is Low. A proposal is mostly Low, and High where the site sits in
# an area a local strategy formally identifies.
SS_LOW = 'Low'
SS_HIGH = 'High'
PROPOSED_SIGNIFICANCE = [(SS_LOW, 0.9), (SS_HIGH, 0.1)]
ON_SITE_RISK = 'N/A'


def _pick(weighted, roll):
    running = 0.0
    for value, weight in weighted:
        running += weight
        if roll < running:
            return value
    return weighted[-1][0]


# ------------------------------------------------------- reference lookups

def load_reference():
    conditions = collections.defaultdict(list)
    with open(os.path.join(CSV_ROOT, 'Habitats', 'Habitat Condition.csv')) as fh:
        for row in csv.DictReader(fh):
            conditions[row['UKHAB']].append(row['Label'])
    broad = {}
    with open(os.path.join(CSV_ROOT, 'Habitats', 'Habitat Options- pre.csv')) as fh:
        for row in csv.DictReader(fh):
            broad[row['UKHAB']] = row['ID']
    # The answers each habitat allows: only No, only Yes, or both.
    irreplaceable = collections.defaultdict(set)
    with open(os.path.join(CSV_ROOT, 'Habitats', 'Habitat Irreplaceable.csv'),
              encoding='utf-8-sig') as fh:
        for row in csv.DictReader(fh):
            irreplaceable[row['UKHAB']].add(row['Irreplaceable'])
    distinctiveness = {}
    with open(os.path.join(CSV_ROOT, 'Habitats',
                           'Habitat Distinctiveness- pre.csv')) as fh:
        for row in csv.DictReader(fh):
            distinctiveness[row['Habitat']] = row['Baseline Distinctivness']
    return conditions, broad, irreplaceable, distinctiveness


CONDITIONS, BROAD, IRREPLACEABLE, DISTINCTIVENESS = load_reference()

# The service accepts Medium, Low and V.Low only, and so does the controlled
# beta. Anything above that band would be refused, so the palettes below are
# checked against the reference list at import time rather than at run time.
IN_SCOPE_BANDS = {'Medium', 'Low', 'V.Low'}


def assert_in_scope(habitats):
    out_of_scope = sorted(
        f'{name} ({DISTINCTIVENESS.get(name, "unknown")})'
        for name in habitats
        if DISTINCTIVENESS.get(name) not in IN_SCOPE_BANDS)
    if out_of_scope:
        raise ValueError('habitats outside the accepted bands: '
                         + ', '.join(out_of_scope))

# The condition scale, best first, worded as the template's reference lists
# word it. The lists carry no number in front of a label.
CONDITION_SCALE = ('Good', 'Fairly Good', 'Moderate', 'Fairly Poor', 'Poor')
# The condition given to a habitat that the condition list does not name.
CONDITION_NOT_LISTED = 'N/A - Other'

# Condition preference, best first. Filtered per habitat against the template's
# own condition list, so a crop keeps its single "assessment not applicable"
# value and a grassland gets a spread.
CONDITION_WEIGHTS = list(zip(CONDITION_SCALE, (0.10, 0.22, 0.38, 0.20, 0.10)))


def condition_for(habitat, roll):
    allowed = CONDITIONS.get(habitat, [])
    if not allowed:
        return CONDITION_NOT_LISTED
    if len(allowed) == 1:
        return allowed[0]
    weighted = [(label, weight) for label, weight in CONDITION_WEIGHTS
                if label in allowed]
    if not weighted:
        return allowed[0]
    total = sum(weight for _, weight in weighted)
    return _pick([(label, weight / total) for label, weight in weighted], roll)


def best_condition(habitat):
    """The best condition the metric allows for this habitat."""
    allowed = [label for label, _ in CONDITION_WEIGHTS
               if label in CONDITIONS.get(habitat, [])]
    if allowed:
        return allowed[0]
    return (CONDITIONS.get(habitat) or [CONDITION_NOT_LISTED])[0]


def better_condition(habitat, current):
    """One step up the condition scale, where the habitat has a scale."""
    allowed = [label for label, _ in CONDITION_WEIGHTS
               if label in CONDITIONS.get(habitat, [])]
    if current not in allowed:
        return allowed[0] if allowed else current
    position = allowed.index(current)
    return allowed[max(position - 1, 0)]


# ---------------------------------------------------------- baseline bands

PASTORAL = [
    ('Modified grassland', 0.48), ('Other neutral grassland', 0.12),
    ('Other woodland; broadleaved', 0.06), ('Mixed scrub', 0.05),
    ('Hawthorn scrub', 0.03), ('Bramble scrub', 0.03),
    ('Blackthorn scrub', 0.02), ('Willow scrub', 0.015),
    ('Ruderal/Ephemeral', 0.03), ('Bare ground', 0.02),
    ('Developed land; sealed surface', 0.04), ('Built linear features', 0.02),
    ('Vegetated garden', 0.015), ('Arable field margins tussocky', 0.02),
    ('Ponds (non-priority habitat)', 0.012), ('Tall forbs', 0.008),
]
ARABLE = [
    ('Cereal crops', 0.42), ('Non-cereal crops', 0.12),
    ('Temporary grass and clover leys', 0.09),
    ('Arable field margins tussocky', 0.06),
    ('Arable field margins pollen and nectar', 0.02),
    ('Modified grassland', 0.10), ('Other woodland; broadleaved', 0.04),
    ('Mixed scrub', 0.03), ('Hawthorn scrub', 0.015),
    ('Developed land; sealed surface', 0.04), ('Built linear features', 0.02),
    ('Ruderal/Ephemeral', 0.02), ('Ponds (non-priority habitat)', 0.008),
    ('Intensive orchards', 0.007),
]
WOODED = [
    ('Other woodland; broadleaved', 0.30), ('Other coniferous woodland', 0.08),
    ('Mixed scrub', 0.15),
    ('Bramble scrub', 0.07), ('Hawthorn scrub', 0.05), ('Hazel scrub', 0.03),
    ('Gorse scrub', 0.025), ('Bracken', 0.03),
    ('Modified grassland', 0.14), ('Other neutral grassland', 0.05),
    ('Other lowland acid grassland', 0.02),
    ('Ponds (non-priority habitat)', 0.01),
    ('Developed land; sealed surface', 0.015), ('Ruderal/Ephemeral', 0.01),
]
SETTLEMENT = [
    ('Developed land; sealed surface', 0.28), ('Built linear features', 0.11),
    ('Vegetated garden', 0.15), ('Modified grassland', 0.12),
    ('Introduced shrub', 0.05), ('Bare ground', 0.06),
    ('Ruderal/Ephemeral', 0.055), ('Vacant or derelict land', 0.045),
    ('Other woodland; broadleaved', 0.04), ('Allotments', 0.025),
    ('Cemeteries and churchyards', 0.01),
    ('Actively worked sand pit quarry or open cast mine', 0.015),
    ('Sustainable drainage system', 0.01),
    ('Ornamental lake or pond', 0.01),
]
BANDS = [PASTORAL, ARABLE, WOODED, SETTLEMENT]
BAND_MIX = [(0, 0.42), (1, 0.34), (2, 0.17), (3, 0.07)]


def band_for(mesh, i, j):
    """Landscape band, drifting slowly along and across the corridor."""
    u = i / mesh.stations
    drift = (
        0.5
        + 0.28 * _sin(u * 9.0 + 0.4)
        + 0.16 * _sin(u * 23.0 + 2.2)
        + 0.10 * _sin(u * 47.0 + 1.1)
        + 0.09 * (_hash01(i // 7, j // 4, 613) - 0.5)
    )
    return _pick(BAND_MIX, min(max(drift, 0.0), 0.999))


def _sin(x):
    import math
    return math.sin(x * math.pi)


def baseline_habitat(mesh, i, j, seed):
    band = BANDS[band_for(mesh, i, j)]
    total = sum(weight for _, weight in band)
    normalised = [(name, weight / total) for name, weight in band if weight > 0]
    return _pick(normalised, _hash01(seed, 401))


def strategic_significance(seed):
    """A proposed significance. A baseline one is always SS_LOW."""
    return _pick(PROPOSED_SIGNIFICANCE, _hash01(seed, 907))


# -------------------------------------------------------- intervention zones

CORE, EARTHWORKS, MITIGATION, OUTER = 'core', 'earthworks', 'mitigation', 'outer'


def zone_of(mesh, i, j):
    u = i / mesh.stations
    centre = mesh.lanes / 2.0 + 2.3 * _sin(u * 7.0 + 0.9) + 1.4 * _sin(u * 17.0 + 2.1)
    half = 1.9 + 0.9 * _sin(u * 9.0 + 0.4)
    distance = abs(j + 0.5 - centre)
    if distance < half:
        return CORE
    if distance < half + 2.0:
        return EARTHWORKS
    if distance < half + 4.0:
        return MITIGATION
    return OUTER


CORE_HABITATS = [
    ('Developed land; sealed surface', 0.52),
    ('Built linear features', 0.26),
    ('Artificial unvegetated, unsealed surface', 0.22),
]
EARTHWORK_HABITATS = [
    ('Other neutral grassland', 0.40), ('Mixed scrub', 0.18),
    ('Other woodland; broadleaved', 0.14), ('Modified grassland', 0.13),
    ('Bramble scrub', 0.05), ('Blackthorn scrub', 0.04),
    ('Gorse scrub', 0.03), ('Arable field margins tussocky', 0.03),
]
MITIGATION_CREATED = [
    ('Other woodland; broadleaved', 0.26), ('Other neutral grassland', 0.24),
    ('Mixed scrub', 0.16), ('Ponds (non-priority habitat)', 0.12),
    ('Sustainable drainage system', 0.10), ('Willow scrub', 0.06),
    ('Arable field margins pollen and nectar', 0.06),
]
ENHANCEMENT_TARGET = {
    'Modified grassland': 'Other neutral grassland',
    'Cereal crops': 'Arable field margins tussocky',
    'Non-cereal crops': 'Arable field margins tussocky',
    'Temporary grass and clover leys': 'Other neutral grassland',
    # Every target here has been checked against the metric's own
    # time-to-target table: enhancing into it from the habitat on the left,
    # at the best condition the target allows, is a transition the metric
    # will price. Bramble scrub is absent on purpose; it is only ever
    # recorded as unassessed, and the metric refuses to enhance from there.
    'Bare ground': 'Other neutral grassland',
    'Vacant or derelict land': 'Other neutral grassland',
    'Hawthorn scrub': 'Mixed scrub',
    'Bracken': 'Other lowland acid grassland',
    'Introduced shrub': 'Mixed scrub',
    'Ruderal/Ephemeral': 'Other neutral grassland',
}

RETAINED, ENHANCED, CREATED = 'Retained', 'Enhanced', 'Created'


def intervention(zone, habitat, condition, seed):
    """Return (retention, proposed habitat, proposed condition)."""
    roll = _hash01(seed, 5501)
    if zone == CORE:
        proposed = _pick(CORE_HABITATS, roll)
        return CREATED, proposed, condition_for(proposed, _hash01(seed, 5503))
    if zone == EARTHWORKS:
        proposed = _pick(EARTHWORK_HABITATS, roll)
        return CREATED, proposed, condition_for(proposed, _hash01(seed, 5507))
    if zone == MITIGATION:
        if roll < 0.30:
            proposed = _pick(MITIGATION_CREATED, _hash01(seed, 5509))
            return CREATED, proposed, condition_for(proposed, _hash01(seed, 5511))
        if roll < 0.76:
            return _enhance(habitat, condition, seed)
        return RETAINED, habitat, condition
    if roll < 0.05:
        proposed = _pick(MITIGATION_CREATED, _hash01(seed, 5513))
        return CREATED, proposed, condition_for(proposed, _hash01(seed, 5517))
    if roll < 0.19:
        return _enhance(habitat, condition, seed)
    return RETAINED, habitat, condition


def _enhance(habitat, condition, seed):
    """Improve the parcel, or leave it alone if there is nothing to gain.

    An enhancement that changes habitat goes to the best condition the new
    habitat allows. That is not decoration: the metric prices an enhancement
    from a time-to-target table, and a target that is no better than where
    the parcel already is has no entry in it. A parcel already at the top
    stays as it is.
    """
    target = ENHANCEMENT_TARGET.get(habitat)
    if target and _hash01(seed, 5519) < 0.7:
        proposed = best_condition(target)
        if proposed != condition:
            return ENHANCED, target, proposed
    improved = better_condition(habitat, condition)
    if improved == condition:
        return RETAINED, habitat, condition
    return ENHANCED, habitat, improved


def timing_for(retention, seed):
    """At most one of advance and delay: the metric allows only one.

    None, stored as NULL, where there is no value: an empty string is not in
    the drop-down's list, and QGIS shows it as `()`.
    """
    if retention == RETAINED:
        return None, None
    roll = _hash01(seed, 6607)
    if roll < 0.06:
        return str(1 + int(_hash01(seed, 6611) * 4)), None
    if roll < 0.22:
        return None, str(1 + int(_hash01(seed, 6613) * 8))
    return None, None


assert_in_scope({name for band in BANDS for name, _ in band}
                | {name for name, _ in CORE_HABITATS}
                | {name for name, _ in EARTHWORK_HABITATS}
                | {name for name, _ in MITIGATION_CREATED}
                | set(ENHANCEMENT_TARGET.values()))


# Habitats that may be recorded as irreplaceable while staying inside the
# accepted distinctiveness bands. The always-irreplaceable rule list (coastal
# sand dunes, limestone pavement, blanket bog) is entirely High and V.High, so
# none of it can appear here; but ancient woodland is recorded as ordinary
# woodland carrying the flag, and that is both in scope and exactly the case
# the import tool has to keep separate.
IRREPLACEABLE_CANDIDATES = frozenset({
    'Other woodland; broadleaved',
    'Other woodland; mixed',
    'Other coniferous woodland',
})


def is_irreplaceable(mesh, i, j, habitat):
    """Ancient woodland, in blocks rather than scattered single parcels.

    A habitat that allows only one answer gets that answer, as the template
    fills it. Where both are allowed, the woodland candidates are flagged in
    blocks and everything else is No.
    """
    allowed = IRREPLACEABLE.get(habitat, set())
    if len(allowed) == 1:
        return next(iter(allowed))
    if habitat not in IRREPLACEABLE_CANDIDATES:
        return 'No'
    u = i / mesh.stations
    block = (0.5
             + 0.34 * _sin(u * 13.0 + 1.7)
             + 0.22 * _sin(u * 31.0 + 0.6)
             + 0.18 * (_hash01(i // 11, j // 6, 877) - 0.5))
    return 'Yes' if block > 0.74 else 'No'
