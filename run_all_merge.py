# -*- coding: utf-8 -*-
"""
run_all_merge.py - run the whole pipeline.

pu_rat (primary use area ratio) -> S0 (data preparation) -> S1 (SB / MB
integration) -> S2 (filtering and screening) -> S3 (combination and release
view), then the step-count table and the technical-validation figures.

The run starts by checking that data_raw/ holds every source file the enabled
stages will read, and stops with the full list if anything is missing.

Run with:
    python run_all_merge.py

Files
-----
  common.py               shared constants, helpers and file-name rules
  counter.py              step-by-step record counts
  manual_exclusions.csv   institutions removed by the manual check
  pu_rat.py               floor summary -> primary use area ratio (S1 input)
  S0_data_prep.py
  S1_SB_merge.py / S1_MB_merge.py
  S2_clean.py
  S3_combine.py
  paper_figure.py         filtering and manual-check figures
  eda_validation.py       technical-validation figures

Folders
-------
  data_raw/        source data (not distributed; see README.md)
  data_prepared/   intermediate outputs the stages exchange
  data_output/     released CSV, column dictionary, step-count table
  figures/         technical-validation figures

Settings
--------
  YEAR_PAIRS   sub-periods to process
  RUN_PU_RAT   recompute the primary use area ratio (reads the ~4 GB floor
               summary source, so it is off by default; the output is reused)
  RUN_S0 .. RUN_S3, RUN_COUNT_EXPORT, RUN_PAPER_FIGURE, RUN_EDA_VALIDATION
  SAVE_*       optional outputs; the files the stages exchange are
               always written
"""

import os
import sys
import runpy
import time


# -------------------------------------------------------------------------
# Paths - everything is relative to this file
# -------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_RAW = os.path.join(BASE_DIR, 'data_raw')            # source data
DATA_PREPARED = os.path.join(BASE_DIR, 'data_prepared')  # stage-to-stage files
DATA_OUTPUT = os.path.join(BASE_DIR, 'data_output')      # deliverables
FIGURE_DIR = os.path.join(BASE_DIR, 'figures')           # validation figures

# Prefix stamped on the output file names.
DATE = 260820
# Release of the HIRA medical institution information used (March 2020).
HIRA = 202003

# Source file names inside data_raw/ (see README.md).
RAW_BLD_FILE = 'bld_title_with_upper_delimiter_bar_euckr.txt'
RAW_UP_BLD_FILE = 'bld_recap_title_delimiter_bar_euckr.txt'
FLR_OULN_FILE = 'bld_flr_ouln_delimiter_bar_euckr.txt'

# Primary use area ratio: written by pu_rat.py, read by S1.
PU_RAT_FILE = f'{DATE} pu_rat.txt'
RAW_PURPS_PATH = os.path.join(DATA_PREPARED, PU_RAT_FILE)

# Institutions removed by the manual distribution check.
EXCLUSION_CSV = os.path.join(BASE_DIR, 'manual_exclusions.csv')


# -------------------------------------------------------------------------
# Run settings
# -------------------------------------------------------------------------
YEAR_PAIRS = [
    (2018, 2019),
    (2020, 2021),
]

# pu_rat reads the ~4 GB floor summary source, so it only has to run when that
# source changes. S1 fails if its output is absent.
RUN_PU_RAT = False

RUN_S0 = False
RUN_S1 = False
RUN_S2 = False
RUN_S3 = False
RUN_COUNT_EXPORT = False
RUN_PAPER_FIGURE = True
RUN_EDA_VALIDATION = True

# Output switches.
#   Always written, because the stages read them from one another:
#     before_preprocessing (S1) / after_outlier (S2) / final_* (S3 A and B)
#   Everything below is optional.
SAVE_RELEASE_CSV = False        # hospital_energy_benchmarking_{N}.csv
SAVE_COLUMN_DICT = False        # column_dictionary_{N}.xlsx
SAVE_PU_RAT_LOG = False         # {DATE} pu_rat_log.txt

# Step-count table.
COUNT_FILE = os.path.join(DATA_OUTPUT, 'preprocessing_counts.xlsx')


# -------------------------------------------------------------------------
# Put BASE_DIR first on sys.path so that common / counter import
# -------------------------------------------------------------------------
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import counter        # noqa: E402
from common import SCOPES   # noqa: E402


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------
def _print_banner(text):
    bar = '=' * 70
    print(f'\n{bar}\n{text}\n{bar}', flush=True)


def _run_script(script_name, init_globals):
    """Run a script in this process with runpy.

    The init_globals keys are injected into the script's globals, which is what
    the `if 'X' not in globals():` guards at the top of each script expect.

    Returns the script's globals, so that large sources can be cached.
    """
    script_path = os.path.join(BASE_DIR, script_name)
    if not os.path.exists(script_path):
        print(f'[skip] {script_name} not found', flush=True)
        return {}
    return runpy.run_path(script_path, init_globals=init_globals)


# -------------------------------------------------------------------------
# Preflight - is every source file the enabled stages need present in data_raw/?
# -------------------------------------------------------------------------
# Source files, grouped by the stage that reads them. Only the groups belonging
# to enabled stages are checked, so re-running a later stage on its own does not
# demand sources it will never open.
HIRA_FILES = [
    '1. 병원정보서비스 2020.3.csv',                             # institutional info
    '3. 의료기관별상세정보서비스(시설정보) 2020.3.csv',            # facility info (beds)
    '5. 의료기관별상세정보서비스(진료과목정보) 2020.3.csv',        # departments
    '7. 의료기관별상세정보서비스(의료장비정보) 2020.3.csv',        # equipment
    '8. 의료기관별상세정보서비스(식대가산정보) 2020.3.csv',        # meal-service staffing
]


def _required_sources():
    """{stage: [file name relative to data_raw/]} for the enabled stages."""
    req = {}

    if RUN_PU_RAT:
        req['pu_rat'] = [FLR_OULN_FILE]

    if RUN_S0:
        s0 = ['공통코드.xlsx', '전국-의료기관건축물대장매칭.csv',
              '전국-의료시설-표제부-KICT_CPM.csv',
              '전국-의료시설-총괄표제부-KICT_CPM.csv',
              '데이터넷3_SQI_건축물대장지역별_기상관측지점_매칭.csv',
              '데이터넷3_SQI_종관기상관측-월별냉난방도일.csv']
        years = sorted({y for pair in YEAR_PAIRS for y in pair})
        for year in years:
            for token in ('표제부', '총괄표제부'):
                s0.append(f'전국-의료시설-{year}-{token}-사용량.csv')
        s0 += HIRA_FILES
        req['S0'] = s0

    if RUN_S1:
        req['S1'] = [RAW_BLD_FILE, RAW_UP_BLD_FILE]

    return req


def preflight_data():
    """Check data_raw/ before anything runs, and report every missing file at once.

    Without this the pipeline can fail hours in, on a file the user could have
    supplied at the start.
    """
    _print_banner('Preflight: source files in data_raw/')

    if not os.path.isdir(DATA_RAW):
        raise FileNotFoundError(
            f'Source folder not found: {DATA_RAW}\n'
            f'  -> create it and place the source files there; README.md lists '
            f'what is needed and where each file comes from.'
        )

    req = _required_sources()
    if not req:
        print('  no source files needed for the enabled stages')
        return

    missing = []
    for stage, files in req.items():
        for f in files:
            path = os.path.join(DATA_RAW, f)
            ok = os.path.exists(path)
            size = f'{os.path.getsize(path) / 1e6:,.1f} MB' if ok else '-'
            print(f'  [{"ok " if ok else "MISSING"}] {stage:<7} {f}  {size}')
            if not ok:
                missing.append((stage, f))

    if missing:
        print('\n' + '!' * 70, flush=True)
        print(f'[preflight] {len(missing)} source file(s) missing from '
              f'{DATA_RAW}:', flush=True)
        for stage, f in missing:
            print(f'   - ({stage}) {f}', flush=True)
        print('  -> see README.md for what each file is and where it comes '
              'from.', flush=True)
        print('  -> a stage that is switched off does not need its files; set '
              'the RUN_* flags accordingly.', flush=True)
        print('!' * 70 + '\n', flush=True)
        raise FileNotFoundError(
            f'{len(missing)} source file(s) missing from data_raw/ '
            f'(first: {missing[0][1]})'
        )

    print(f'  all {sum(len(v) for v in req.values())} source file(s) present')


# -------------------------------------------------------------------------
# pu_rat. Floor summary -> primary use area ratio (S1 input)
# -------------------------------------------------------------------------
def run_pu_rat():
    """Compute the primary use area ratio per building record.

    Reads the full floor summary register (about 4 GB) and writes
    '{DATE} pu_rat.txt'. Must run before S1, which reads that file.
    pu_rat.py logs to a text file and prints only one line to the console.
    """
    _print_banner('STEP pu_rat: primary use area ratio')
    _run_script('pu_rat.py', {
        'data_dir_in': DATA_RAW,
        'data_dir': DATA_PREPARED,
        'date': DATE,
        'flr_ouln_file': FLR_OULN_FILE,
        'pu_rat_file': PU_RAT_FILE,
        'save_log': SAVE_PU_RAT_LOG,
    })


# -------------------------------------------------------------------------
# S0. Data preparation (raw sources -> intermediate CSVs)
# -------------------------------------------------------------------------
def run_s0():
    """Build the intermediate CSVs that S1 reads.

    The year loop is inside the script, so it runs once.
    """
    _print_banner('STEP S0: data preparation')
    t0 = time.time()
    _run_script('S0_data_prep.py', {
        'data_dir_in': DATA_RAW,
        'data_dir': DATA_PREPARED,
        'hira': HIRA,
    })
    print(f'[S0] done ({time.time() - t0:.1f}s)', flush=True)


# -------------------------------------------------------------------------
# Preflight - are the S0 outputs that S1 needs present?
# -------------------------------------------------------------------------
def _s0_output_paths():
    files = [f'after_hira_{HIRA}.csv', 'after_weather.csv']
    for yb, ya in YEAR_PAIRS:
        for token in ('master', 'building'):
            files.append(f'after_{token}-energy_{yb}_{ya}.csv')
            files.append(f'after_{token}-cpm_{yb}_{ya}.csv')
    return [os.path.join(DATA_PREPARED, f) for f in files]


def preflight_s1():
    """Check the S1 inputs before spending time on the merges.

    Without this, a missing file raises FileNotFoundError on the first line of
    S1, sometimes after pu_rat has already run for minutes.
    """
    missing = [p_ for p_ in _s0_output_paths() if not os.path.exists(p_)]
    if missing:
        print('\n' + '!' * 70, flush=True)
        print('[preflight] S1 inputs (S0 outputs) are missing:', flush=True)
        for p_ in missing[:10]:
            print(f'   - {p_}', flush=True)
        if len(missing) > 10:
            print(f'   ... and {len(missing) - 10} more', flush=True)
        print('  -> set RUN_S0 = True and run again.', flush=True)
        print('!' * 70 + '\n', flush=True)
        raise FileNotFoundError(
            f'{len(missing)} S0 output(s) missing -> run with RUN_S0 = True '
            f'(first: {os.path.basename(missing[0])})'
        )

    if not os.path.exists(RAW_PURPS_PATH):
        raise FileNotFoundError(
            f'Primary use area ratio output missing: {RAW_PURPS_PATH}\n'
            f'  -> set RUN_PU_RAT = True and run again.'
        )
    print('[preflight] S1 inputs present', flush=True)


# -------------------------------------------------------------------------
# S1. Integration (SB / MB x sub-period)
# -------------------------------------------------------------------------
def run_s1():
    """Two scopes x two sub-periods = four runs.

    The large sources are read once and cached for reuse. S1 only renames
    non-destructively, so the cached frames are safe to share.
    """
    _print_banner(f'STEP S1: integration ({"/".join(SCOPES)} x '
                  f'{len(YEAR_PAIRS)} sub-periods)')
    preflight_s1()

    raw_cache = {
        'data_dir_in': DATA_RAW,
        'data_dir': DATA_PREPARED,
        'date': DATE,
        'hira': HIRA,
        'raw_bld_file': RAW_BLD_FILE,
        'raw_up_bld_file': RAW_UP_BLD_FILE,
        'raw_purps_path': RAW_PURPS_PATH,
    }

    for year_b, year_a in YEAR_PAIRS:
        for scope in SCOPES:
            script = f'S1_{scope}_merge.py'
            t0 = time.time()
            print(f'\n[S1] {scope} {year_b}-{year_a} ...', flush=True)

            init_globals = dict(raw_cache)
            init_globals.update({'year_b': year_b, 'year_a': year_a})

            result_globals = _run_script(script, init_globals)

            for key in ['raw_bld', 'raw_up_bld', 'raw_purps']:
                if key in result_globals:
                    raw_cache[key] = result_globals[key]

            print(f'[S1] {scope} {year_b}-{year_a} done '
                  f'({time.time() - t0:.1f}s)', flush=True)


# -------------------------------------------------------------------------
# S2. Filtering and screening
# -------------------------------------------------------------------------
def run_s2():
    """Two scopes x two sub-periods = four runs.

    counter.set_context() is called before each run, otherwise the counts are
    discarded.
    """
    _print_banner('STEP S2: filtering and screening '
                  f'({"/".join(SCOPES)} x {len(YEAR_PAIRS)} sub-periods)')

    for year_b, year_a in YEAR_PAIRS:
        for scope in SCOPES:
            year_pair = f'{year_b}_{year_a}'
            counter.set_context(scope=scope, year_pair=year_pair)

            t0 = time.time()
            print(f'\n[S2] {scope} {year_pair} ...', flush=True)

            _run_script('S2_clean.py', {
                'scope': scope,
                'exclusion_csv': EXCLUSION_CSV,
                'data_dir': DATA_PREPARED,
                'date': DATE,
                'hira': HIRA,
                'year_b': year_b,
                'year_a': year_a,
            })

            print(f'[S2] {scope} {year_pair} done '
                  f'({time.time() - t0:.1f}s)', flush=True)


# -------------------------------------------------------------------------
# S3. Combination and release view
# -------------------------------------------------------------------------
def run_s3():
    _print_banner('STEP S3: combination and release view')
    t0 = time.time()
    _run_script('S3_combine.py', {
        'data_dir': DATA_PREPARED,
        'output_dir': DATA_OUTPUT,
        'date': DATE,
        'hira': HIRA,
        'year_pairs': YEAR_PAIRS,
        'save_release_csv': SAVE_RELEASE_CSV,
        'save_column_dict': SAVE_COLUMN_DICT,
    })
    print(f'[S3] done ({time.time() - t0:.1f}s)', flush=True)


# -------------------------------------------------------------------------
# Figures
# -------------------------------------------------------------------------
def _force_agg(tag):
    try:
        import matplotlib
        matplotlib.use('Agg', force=True)   # batch run, no windows
    except Exception as e:
        print(f'[{tag}] could not set the Agg backend: {e}', flush=True)


def run_paper_figure():
    """Filtering and manual-check figures. Reads the final_* files from S3."""
    _print_banner('Filtering and manual-check figures')
    _force_agg('paper_figure')

    t0 = time.time()
    try:
        _run_script('paper_figure.py', {
            'data_dir': DATA_PREPARED,
            'figure_dir': FIGURE_DIR,
            'exclusion_csv': EXCLUSION_CSV,
            'date': DATE,
            'hira': HIRA,
            'year_pairs': YEAR_PAIRS,
            'save_f': True,
        })
    except Exception as e:
        print(f'[paper_figure] failed: {e}', flush=True)
    else:
        print(f'[paper_figure] done ({time.time() - t0:.1f}s)', flush=True)


def run_eda_validation():
    """Reads the released CSV written by S3."""
    _print_banner('Technical validation figures')
    _force_agg('eda_validation')

    t0 = time.time()
    try:
        _run_script('eda_validation.py', {
            'output_dir': DATA_OUTPUT,
            'figure_dir': FIGURE_DIR,
            'save_f': True,
        })
    except Exception as e:
        print(f'[eda_validation] failed: {e}', flush=True)
    else:
        print(f'[eda_validation] done ({time.time() - t0:.1f}s)', flush=True)


# -------------------------------------------------------------------------
# Step-count table
# -------------------------------------------------------------------------
def export_counts():
    _print_banner('Step-count table')
    counter.export_to_excel(COUNT_FILE)


# -------------------------------------------------------------------------
# Main
# -------------------------------------------------------------------------
def main():
    total_t0 = time.time()
    for _d in (DATA_PREPARED, DATA_OUTPUT, FIGURE_DIR):
        os.makedirs(_d, exist_ok=True)
    counter.reset()

    # Fail here, before any work, if a source file is missing.
    preflight_data()

    for flag, fn, name in [
        (RUN_PU_RAT, run_pu_rat, 'pu_rat'),
        (RUN_S0, run_s0, 'S0'),
        (RUN_S1, run_s1, 'S1'),
        (RUN_S2, run_s2, 'S2'),
        (RUN_S3, run_s3, 'S3'),
    ]:
        if flag:
            fn()
        else:
            print(f'[skip] {name}')

    # The count table is written before the figures, since S2 and S3 fill it.
    if RUN_COUNT_EXPORT:
        export_counts()
    else:
        print('[skip] count export')

    if RUN_PAPER_FIGURE:
        run_paper_figure()
    else:
        print('[skip] paper_figure')

    if RUN_EDA_VALIDATION:
        run_eda_validation()
    else:
        print('[skip] eda_validation')

    _print_banner(f'All done. Total time: {(time.time() - total_t0) / 60:.1f} min')


if __name__ == '__main__':
    main()
