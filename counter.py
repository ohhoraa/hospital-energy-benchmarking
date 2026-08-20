# -*- coding: utf-8 -*-
"""
Step-by-step record counter.

Every call to `col_counts` / `print_counts` accumulates a count in the
background; `run_all_merge.py` writes the accumulated table to
`preprocessing_counts.xlsx` at the end of the run.

Two sheets are produced:
  counts : every step, with the counts for each scope and sub-period
  table2 : the filtering steps only, in the order they are applied, as
           institution totals over both scopes

One step = one row. Scope (SB / MB), sub-period and count type are columns, so
a step applied to both scopes still occupies a single row.

Usage
-----
In S2:
    import counter
    counter.set_context(scope='SB', year_pair='2018_2019')
    counter.current_section = 'screening'   # start of the screening block

In run_all_merge:
    counter.reset()
    # ... run S2 / S3 ...
    counter.export_to_excel(path)

Note: `log()` returns silently when no context has been set, so
`set_context()` must be called before any counting.
"""

import os
import pandas as pd

# HIRA institution key (must match common.YKIHO).
YKIHO = 'ykiho'

# Row order inside the counts sheet.
SECTION_ORDER = ['filtering', 'screening', 'manual_exclusion', 'merge']

# Filtering steps, in the order they are applied, with the type and the wording
# used in the table2 sheet. The first element of each tuple is the step key
# recorded by S2_clean.py; changing a label there means changing it here too.
TABLE2_SPEC = [
    ('model_ty == single-institution (*-SI) retained', '-',
     'After two-stage integration: (i) medical institutions, and '
     '(ii) single-institution configurations only'),
    ('opened on or before 1 January 2018', 'Data limitation',
     'Institutions that opened on or before 1 January 2018'),
    ('pu_rat >= 75 retained', 'Operational',
     'Institutions with pu_rat >= 75%'),
    ('no privately owned units', 'Operational',
     'Institutions without privately owned units'),
    ('annual total energy > 20000 kWh', 'Operational',
     'Institutions with annual total energy consumption > 20,000 kWh'),
    ('30 <= bed_cnt <= 1000', 'Analytic',
     'Institutions with 30 <= bed_cnt <= 1,000'),
    ('tot_dr_cnt > 1', 'Analytic',
     'Institutions with tot_dr_cnt > 1'),
    ('gfa_r > 1000 m2', 'Analytic',
     'Institutions with gfa_r > 1,000 m2'),
]


# ============================================================
# Global state
# ============================================================
_context = {
    'scope': None,       # 'SB' or 'MB'
    'year_pair': None,   # '2018_2019' or '2020_2021'
}

# Current section. set_context resets it to 'filtering'; S2 advances it.
current_section = 'filtering'

# Accumulated counts, keyed by step.
_records = {}

# Order of first appearance, used for sorting.
_seq = 0


# ============================================================
# Context
# ============================================================
def set_context(scope, year_pair):
    """Declare the current execution unit (scope x sub-period). Required."""
    global _context, current_section
    _context['scope'] = scope
    _context['year_pair'] = year_pair
    current_section = 'filtering'


def reset():
    """Called at the start of a run. Clears the context as well, so that a
    previous scope or sub-period cannot leak into the wrong column."""
    global _records, _seq
    _records = {}
    _seq = 0
    for k in _context:
        _context[k] = None


def get_context():
    return dict(_context)


# ============================================================
# Label handling
# ============================================================
def _clean_label(label):
    """Strip a leading '---' and surrounding whitespace."""
    if not isinstance(label, str):
        return str(label)
    label = label.strip()
    if label.startswith('---'):
        label = label.lstrip('-').strip()
    return label


# ============================================================
# Counting
# ============================================================
def log(df, pk_col, label, step=None):
    """Record the count at one step.

    pk_col : 'mgm_upper_bld_pk' (MB) / 'mgm_bld_pk' (SB) / 'ykiho'
    label  : free text printed to the console
    step   : row key of the table. Defaults to a cleaned `label`.
             Labels that vary by scope must pass a normalised `step`.
    """
    global _seq

    scope = _context['scope']
    year_pair = _context['year_pair']

    if scope is None or year_pair is None:
        # No context = standalone execution; nothing is recorded.
        return

    step_key = _clean_label(step if step is not None else label)

    if step_key not in _records:
        _records[step_key] = {'section': current_section, 'step': step_key,
                              'seq': _seq}
        _seq += 1

    kind = 'inst' if pk_col == YKIHO else 'PK'
    col_name = f'{scope}_{year_pair}_{kind}'
    _records[step_key][col_name] = (df[pk_col].nunique(dropna=True)
                                    if pk_col in df.columns else None)


def log_merge_step(section, label, total_inst, note=''):
    """Add one row for the S3 concatenation / sub-period join results."""
    global _seq
    if label not in _records:
        _records[label] = {'seq': _seq}
        _seq += 1
    _records[label].update({'section': section, 'step': label,
                            'total_inst': total_inst, 'note': note})


# ============================================================
# Excel output
# ============================================================
def _count_columns():
    """Collect and sort the count columns that were actually recorded,
    e.g. MB_2018_2019_PK, MB_2018_2019_inst, MB_2020_2021_PK, ..., SB_...
    """
    fixed = {'section', 'step', 'seq', 'total_inst', 'note'}
    cols = set()
    for rec in _records.values():
        cols |= {k for k in rec if k not in fixed}

    def _sortkey(c):
        parts = c.split('_')
        kind = 0 if c.endswith('_PK') else 1     # PK first
        return (parts[0], '_'.join(parts[1:3]), kind)

    return sorted(cols, key=_sortkey)


def _year_pairs_in(count_cols):
    """Extract the sub-periods present, preserving their order."""
    seen = []
    for c in count_cols:
        pair = '_'.join(c.split('_')[1:3])
        if pair not in seen:
            seen.append(pair)
    return seen


def _section_rank(section):
    return (SECTION_ORDER.index(section) if section in SECTION_ORDER
            else len(SECTION_ORDER))


def _total_inst(step_key, pair):
    """Institution total over every scope recorded for one step and period.

    Returns None unless every scope present in the run recorded this step, so
    that a step logged for one scope only cannot be reported as a total.
    """
    rec = _records.get(step_key)
    if rec is None:
        return None
    scopes = sorted({c.split('_')[0] for c in _count_columns()})
    vals = [rec.get(f'{sc}_{pair}_inst') for sc in scopes]
    if any(v is None for v in vals):
        return None
    return sum(vals)


def _build_dataframe():
    count_cols = _count_columns()
    rows = []
    for _step, rec in _records.items():
        row = {
            'section': rec.get('section', ''),
            'step': rec.get('step', ''),
            '_rank': _section_rank(rec.get('section', '')),
            '_seq': rec.get('seq', 0),
        }
        for c in count_cols:
            row[c] = rec.get(c)
        row['total_inst'] = rec.get('total_inst')
        row['note'] = rec.get('note', '')
        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Sort by section order, then by order of first appearance.
    df = df.sort_values(['_rank', '_seq']).drop(columns=['_rank', '_seq'])
    df = df.reset_index(drop=True)

    # Mark steps recorded for one scope only (their total is undefined).
    scopes = sorted({c.split('_')[0] for c in count_cols})
    if len(scopes) > 1:
        for sc in scopes:
            sc_cols = [c for c in count_cols if c.startswith(f'{sc}_')]
            has = df[sc_cols].notna().any(axis=1)
            missing = ~has & df[count_cols].notna().any(axis=1)
            if missing.any():
                note = f'{"/".join(s for s in scopes if s != sc)} only'
                df.loc[missing, 'note'] = df.loc[missing, 'note'].replace('', None)
                df.loc[missing, 'note'] = df.loc[missing, 'note'].fillna(note)

    # Total over the scopes and the step-to-step decrease. The decrease runs
    # continuously across filtering -> screening -> manual_exclusion, skipping
    # rows without a total.
    for pair in _year_pairs_in(count_cols):
        src = [c for c in count_cols if c.endswith(f'{pair}_inst')]
        if not src:
            continue
        total = df[src].sum(axis=1, min_count=len(src))
        deltas, prev = [], None
        for v in total:
            if pd.isna(v):
                deltas.append(None)
            else:
                deltas.append(None if prev is None else prev - v)
                prev = v
        df[f'sum_{pair}_inst'] = total
        df[f'delta_{pair}'] = deltas

    df.insert(0, 'step_no', range(1, len(df) + 1))

    ordered = (['step_no', 'section', 'step']
               + count_cols
               + [c for c in df.columns if c.startswith(('sum_', 'delta_'))]
               + ['total_inst', 'note'])
    return df[[c for c in ordered if c in df.columns]]


def _build_table2():
    """Filtering steps only, in the order they are applied, as institution
    totals.

    Columns: Type / Filter / one column per sub-period.
    """
    pairs = _year_pairs_in(_count_columns())
    if not pairs:
        return pd.DataFrame()

    rows = []
    for step_key, type_, label in TABLE2_SPEC:
        if step_key not in _records:
            print(f'[counter] table2: step not recorded, skipped -> {step_key}')
            continue
        row = {'Type': type_, 'Filter': label}
        for pair in pairs:
            row[pair.replace('_', '-')] = _total_inst(step_key, pair)
        rows.append(row)

    return pd.DataFrame(rows)


def export_to_excel(path):
    """Sheets: counts / table2."""
    df_counts = _build_dataframe()
    df_table2 = _build_table2()

    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with pd.ExcelWriter(path, engine='openpyxl') as writer:
        wrote = False
        if not df_counts.empty:
            df_counts.to_excel(writer, sheet_name='counts', index=False)
            wrote = True
        if not df_table2.empty:
            df_table2.to_excel(writer, sheet_name='table2', index=False)
            wrote = True

        if not wrote:
            # openpyxl cannot save a workbook with no sheets. Reaching this
            # point means set_context() was never called.
            pd.DataFrame({'note': [
                'No steps were recorded.',
                'Check that S2_clean.py calls counter.set_context(); '
                'counter.log() returns silently without a context.',
            ]}).to_excel(writer, sheet_name='empty', index=False)

    print(f'\n[counter] count table saved: {path}')
    print(f'  - counts sheet : {len(df_counts)} rows')
    print(f'  - table2 sheet : {len(df_table2)} rows')

    if df_counts.empty:
        print('  WARNING: no step records - check that S2 calls '
              'counter.set_context()')
