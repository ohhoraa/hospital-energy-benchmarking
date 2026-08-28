# -*- coding: utf-8 -*-
"""
S0. Data preparation (raw sources -> the intermediate CSVs read by S1).

What this script does
---------------------
1) Energy billing (master building / building) : long -> unit conversion ->
   annual totals -> primary energy conversion -> wide
2) Change-point model (CPM) results            : period filter -> wide by source
3) Weather (monthly heating and cooling degree days) : annual totals ->
   station-to-district matching
4) HIRA medical institution information        : merge of the five sub-datasets
   used in the study, plus derived variables

Outputs (written to data_prepared, read by S1_SB_merge.py / S1_MB_merge.py)
  after_master-energy_{year_b}_{year_a}.csv
  after_building-energy_{year_b}_{year_a}.csv
  after_master-cpm_{year_b}_{year_a}.csv
  after_building-cpm_{year_b}_{year_a}.csv
  after_weather.csv
  after_hira_{hira}.csv

Column naming
-------------
Source column names are preserved throughout. The HIRA files are supplied with
Korean column headings, so the whole heading set is mapped to the source
English names in one place (the KOR2ENG_* dictionaries below).

One necessary exception: the primary key of the master-building datasets is
also called `mgm_bld_pk` in the source, which would collide with the building
key on merging, so it is renamed to `mgm_upper_bld_pk`.

Derived variables follow the released variable names:
  bed_cnt      sum of the 13 bed types
  dept_cnt     number of clinical departments
  ct_cnt       equipment code B108 (CT)
  mri_cnt      equipment code B301 (MRI)
  diet_cnt     dietitians counted for the meal-service supplement
  cook_cnt     cooks counted for the meal-service supplement
  estb_dd      opening date (datetime conversion of the source string)
  hos_ty_eng   institution type abbreviation (GH/H/CH/KH/DH/TH)

Five HIRA sub-datasets are used:
institutional information, facility information, medical equipment,
meal-service staffing and medical departments. The remaining sub-datasets hold
administrative or clinical information unrelated to building energy use, or
have too many missing values.
"""

import os
import numpy as np
import pandas as pd

from common import HOS_TY_LABEL_MAP, PRI_FACTOR


# =============================================================================
# Settings (injectable from run_all_merge.py)
# =============================================================================
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

if 'data_dir_in' not in globals():
    data_dir_in = os.path.join(_BASE_DIR, 'data_raw')
if 'data_dir' not in globals():
    data_dir = os.path.join(_BASE_DIR, 'data_prepared')
if 'hira' not in globals():
    hira = 202003

# Sub-periods to process, injected by run_all_merge.py. Every year that appears
# in any pair is read individually first, then the pairs are joined; the CPM
# fitting period of a pair is derived from it as x{year_b}01 - x{year_a}12.
if 'year_pairs' not in globals():
    year_pairs = [(2018, 2019), (2020, 2021)]
YEARS = sorted({y for _pair in year_pairs for y in _pair})

# HIRA release year used by the address matching table (hira=202003 -> 2020).
hira_base_yyyy = int(str(hira)[:4])

os.makedirs(data_dir, exist_ok=True)


# %% ==========================================================================
# 1. Energy billing (master building / building)
# =============================================================================
def make_yearly_sum(df, df_cd, pk_out):
    """Monthly billing (long) -> annual totals (wide).

    Parameters
    ----------
    df   : raw billing records. Columns include mgm_bld_pk, engy_kind_cd,
           use_ym, unit_cd, use_qty_tot / use_qty_eb / use_qty_ec / use_qty_eh
           (engy_kind_cd: 11 electricity / 12 gas / 13 district heating).
           The baseload (eb), cooling (ec) and heating (eh) components are the
           change-point model disaggregation of the calendarized records.
    df_cd: 'energy unit' sheet of the code table (engy_kind_cd, unit_cd, to_kwh)
    pk_out : 'mgm_bld_pk' (building) or 'mgm_upper_bld_pk' (master building).
             The master-building source uses the same key name as the building
             source, so it has to be renamed here to keep later merges apart.
    """
    df = df.copy()

    # Year from use_ym (YYYYMM).
    df['use_ym'] = df['use_ym'].astype(str).str[:4]

    qty_cols = ['use_qty_tot', 'use_qty_eb', 'use_qty_ec', 'use_qty_eh']
    for col in qty_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # The source mixes text and numeric code values, so both code columns are
    # coerced to the nullable integer type. Int64 rather than float is
    # essential: the codes become column-name suffixes after the pivot below,
    # and a float dtype would spell them '11.0' instead of '11', which no longer
    # matches `need_cols` and would leave every energy column filled with zero.
    _n_before = df['engy_kind_cd'].notna().sum()
    df['engy_kind_cd'] = (pd.to_numeric(df['engy_kind_cd'], errors='coerce')
                          .astype('Int64'))
    df['unit_cd'] = pd.to_numeric(df['unit_cd'], errors='coerce').astype('Int64')
    _n_coerced = int(_n_before - df['engy_kind_cd'].notna().sum())
    if _n_coerced:
        print(f'  [warning] {_n_coerced:,} row(s) dropped: engy_kind_cd is not '
              f'numeric. Check the source before using these totals.')

    cd = df_cd.copy()
    cd['to_kwh'] = pd.to_numeric(cd['to_kwh'], errors='coerce')
    for c in ['engy_kind_cd', 'unit_cd']:
        cd[c] = pd.to_numeric(cd[c], errors='coerce').astype('Int64')

    # Convert each metered unit to kWh.
    df = df.merge(cd, on=['engy_kind_cd', 'unit_cd'], how='left')
    print(f'  to_kwh missing rows: {df["to_kwh"].isna().sum()}')
    df['to_kwh'] = df['to_kwh'].fillna(1)   # no factor -> keep the raw value

    for col in qty_cols:
        df[col] = df[col] * df['to_kwh']

    # Annual totals, then wide by energy source.
    yearly = (
        df.groupby(['mgm_bld_pk', 'engy_kind_cd', 'use_ym'],
                   as_index=False)[qty_cols].sum()
    )
    yearly = yearly.pivot_table(
        index='mgm_bld_pk', columns=['engy_kind_cd'], values=qty_cols
    ).reset_index()
    yearly.columns = ['_'.join(map(str, c)) if isinstance(c, tuple) else c
                      for c in yearly.columns]

    # Fill sources a building does not use with zero so the column set is fixed.
    need_cols = [f'use_qty_{k}_{e}' for k in ('tot', 'eb', 'ec', 'eh')
                 for e in (11, 12, 13)]
    for c in need_cols:
        if c not in yearly.columns:
            yearly[c] = 0
    yearly[need_cols] = yearly[need_cols].fillna(0)

    # Site energy total.
    yearly['use_qty_0'] = sum(yearly[f'use_qty_tot_{e}'] for e in (11, 12, 13))

    # Primary energy conversion: electricity 2.75 / gas 1.1 / district heat 0.728.
    for e in (11, 12, 13):
        yearly[f'use_qty_1st_{e}'] = yearly[f'use_qty_tot_{e}'] * PRI_FACTOR[e]
    yearly['use_qty_1st_0'] = sum(yearly[f'use_qty_1st_{e}'] for e in (11, 12, 13))

    # Baseload / cooling / heating: site totals and primary conversion.
    for k in ('eb', 'ec', 'eh'):
        yearly[f'use_qty_{k}'] = sum(yearly[f'use_qty_{k}_{e}'] for e in (11, 12, 13))
        yearly[f'use_qty_1st_{k}'] = sum(
            yearly[f'use_qty_{k}_{e}'] * PRI_FACTOR[e] for e in (11, 12, 13))

    cols = {
        'mgm_bld_pk_': pk_out,

        'use_qty_0': 'site_sum',
        'use_qty_tot_11': 'site_elec',
        'use_qty_tot_12': 'site_gas',
        'use_qty_tot_13': 'site_heat',

        'use_qty_1st_0': 'pri_sum',
        'use_qty_1st_11': 'pri_elec',
        'use_qty_1st_12': 'pri_gas',
        'use_qty_1st_13': 'pri_heat',

        'use_qty_1st_eb': 'pri_base',
        'use_qty_1st_ec': 'pri_clg',
        'use_qty_1st_eh': 'pri_htg',

        'use_qty_eb': 'site_base',
        'use_qty_eb_11': 'site_base_e',
        'use_qty_eb_12': 'site_base_g',
        'use_qty_eb_13': 'site_base_h',

        'use_qty_ec': 'site_clg',
        'use_qty_ec_11': 'site_clg_e',
        'use_qty_ec_12': 'site_clg_g',
        'use_qty_ec_13': 'site_clg_h',

        'use_qty_eh': 'site_htg',
        'use_qty_eh_11': 'site_htg_e',
        'use_qty_eh_12': 'site_htg_g',
        'use_qty_eh_13': 'site_htg_h',
    }
    yearly = yearly.rename(columns=cols)
    yearly = yearly[list(cols.values())]
    yearly = yearly.sort_values(pk_out).reset_index(drop=True)

    num_cols = [c for c in yearly.columns if c != pk_out]
    yearly[num_cols] = yearly[num_cols].apply(pd.to_numeric, errors='coerce')
    return yearly


def add_year_suffix(df, year, pk_col):
    """Append _{year} to every column except the primary key."""
    return df.rename(columns={c: f'{c}_{year}' for c in df.columns if c != pk_col})


# Source scope -> (file-name token in the source data, output token, key)
ENERGY_SCOPES = [
    ('총괄표제부', 'master', 'mgm_upper_bld_pk'),
    ('표제부', 'building', 'mgm_bld_pk'),
]


def build_energy(src_token, out_token, pk_out, df_cd):
    """Write the two-year pair files S1 reads.

    Each year in YEARS is summed separately and held in memory; only the pair
    files are written, because those are what S1 opens.
    """
    print(f'\n=== energy - {out_token} ===')
    ys = {}
    for year in YEARS:
        raw = pd.read_csv(
            os.path.join(data_dir_in, f'전국-의료시설-{year}-{src_token}-사용량.csv'),
            encoding='cp949', delimiter='|',
        )
        y = make_yearly_sum(raw, df_cd, pk_out=pk_out)
        ys[year] = add_year_suffix(y, year, pk_col=pk_out)
        print(f'  {out_token} {year} : {len(y):,} rows')

    # Two-year pair: only buildings billed in both years (inner join).
    for year_b, year_a in year_pairs:
        pair = (pd.merge(ys[year_b], ys[year_a], on=pk_out, how='inner')
                  .sort_values(pk_out).reset_index(drop=True))
        pair.to_csv(
            os.path.join(data_dir,
                         f'after_{out_token}-energy_{year_b}_{year_a}.csv'),
            index=False, encoding='utf-8-sig')
        print(f'  {out_token} {year_b}_{year_a} : {len(pair):,} rows')


df_cd = pd.read_excel(os.path.join(data_dir_in, '공통코드.xlsx'),
                      sheet_name='에너지 단위')

for _src, _out, _pk in ENERGY_SCOPES:
    build_energy(_src, _out, pk_out=_pk, df_cd=df_cd)


# %% ==========================================================================
# 2. Change-point model results
# =============================================================================
# Source columns: mgm_bld_pk, engy_kind_cd, date_s, date_e, cpm_ty, md_rank,
#   b0~b4, ns, rmse, nmbe, cvrmse, r2_adj, pval_*, ckd_out_idx, zre_out_idx,
#   p_m1, p_m2, r2, r2_l, r2_r, x_min, x_max, sido_cd
# Reshaped wide by energy source, the columns gain the source code as a suffix
# (ns_11, r2_13 and so on).
#
# The change-point modelling tool itself is third-party software and is not
# part of this repository. This
# script consumes its output.
df_cpm_b = pd.read_csv(os.path.join(data_dir_in, '전국-의료시설-표제부-KICT_CPM.csv'),
                       encoding='cp949', delimiter='|')
df_cpm_u = pd.read_csv(os.path.join(data_dir_in, '전국-의료시설-총괄표제부-KICT_CPM.csv'),
                       encoding='cp949', delimiter='|')

COLS_CPM_VAL = ['mgm_bld_pk', 'engy_kind_cd', 'cpm_ty', 'b0', 'b1', 'b2', 'b3', 'b4',
                'ns', 'cvrmse', 'rmse', 'nmbe', 'r2', 'r2_l', 'r2_r']
COLS_CPM_INFO = ['mgm_bld_pk', 'sido_cd', 'date_s', 'date_e']


def processing_cpm(df, pk_out, date_s, date_e):
    """Filter to one fitting period, then reshape wide by energy source."""
    df = df.copy()
    df['date_s'] = df['date_s'].astype(str)
    df['date_e'] = df['date_e'].astype(str)
    df = df[(df['date_s'] == str(date_s)) & (df['date_e'] == str(date_e))].copy()

    # Same reason as in make_yearly_sum: engy_kind_cd becomes a column-name
    # suffix below, and a float dtype would spell it '11.0', which S3's
    # sub-period regex (^(base)_\d+$) does not match.
    df['engy_kind_cd'] = (pd.to_numeric(df['engy_kind_cd'], errors='coerce')
                          .astype('Int64'))

    ren = {'mgm_bld_pk': pk_out} if pk_out != 'mgm_bld_pk' else {}

    df_val = df.filter(items=COLS_CPM_VAL).rename(columns=ren)
    df_info = (df.filter(items=COLS_CPM_INFO)
                 .drop_duplicates(subset=['mgm_bld_pk'])
                 .rename(columns=ren))

    df_pivot = df_val.pivot_table(
        index=pk_out,
        columns=['engy_kind_cd'],
        values=[c for c in COLS_CPM_VAL if c not in ('mgm_bld_pk', 'engy_kind_cd')],
        aggfunc='first',   # cpm_ty is text, so no numeric aggregation
    ).reset_index()
    df_pivot.columns = ['_'.join(map(str, c)) if isinstance(c, tuple) else c
                        for c in df_pivot.columns]
    df_pivot.rename(columns={f'{pk_out}_': pk_out}, inplace=True)

    return pd.merge(df_info, df_pivot, on=pk_out, how='inner')


# The fitting period of a sub-period runs from January of the earlier year to
# December of the later one, which the source labels x{YYYYMM}.
for year_b, year_a in year_pairs:
    ds, de = f'x{year_b}01', f'x{year_a}12'
    processing_cpm(df_cpm_u, 'mgm_upper_bld_pk', ds, de).to_csv(
        os.path.join(data_dir, f'after_master-cpm_{year_b}_{year_a}.csv'),
        index=False, encoding='utf-8-sig')
    processing_cpm(df_cpm_b, 'mgm_bld_pk', ds, de).to_csv(
        os.path.join(data_dir, f'after_building-cpm_{year_b}_{year_a}.csv'),
        index=False, encoding='utf-8-sig')
    print(f'[CPM] {year_b}_{year_a} saved')


# %% ==========================================================================
# 3. Weather (monthly heating and cooling degree days)
# =============================================================================
df_sta = pd.read_csv(
    os.path.join(data_dir_in, '데이터넷3_SQI_건축물대장지역별_기상관측지점_매칭.csv'),
    encoding='cp949')
df_w = pd.read_csv(
    os.path.join(data_dir_in, '데이터넷3_SQI_종관기상관측-월별냉난방도일.csv'),
    encoding='cp949')

# Station matching at the finest administrative unit.
#   Station 169 was dropped for extensive missing hourly data and station 239
#   began observing in 2019, so neither covers the whole study period.
df_sta = (df_sta[df_sta['region_level_type'] == 'bjdong']
          .copy()
          .filter(items=['region_cd', 'kma_obsrvn_cd_not_169_239']))
df_sta['sigungu_cd'] = df_sta['region_cd'].astype(str).str[:5].astype(int)
df_sta['bjdong_cd'] = df_sta['region_cd'].astype(str).str[5:].astype(int)
df_sta = (df_sta.drop(columns=['region_cd'])
                .rename(columns={'kma_obsrvn_cd_not_169_239': 'kma_obsrvn_cd'}))

# cdd_1 = cooling degree days at a 24 C base, hdd_1 = heating degree days at 18 C.
df_w = (df_w[['kma_obsrvn_cd', 'kma_obsrvn_nm', 'use_ym', 'cdd_1', 'hdd_1']]
        .copy()
        .rename(columns={'cdd_1': 'cdd', 'hdd_1': 'hdd'}))

df_w['use_y'] = df_w['use_ym'].astype(str).str[:4]
df_w['cdd'] = pd.to_numeric(df_w['cdd'], errors='coerce')
df_w['hdd'] = pd.to_numeric(df_w['hdd'], errors='coerce')

df_w_y = (df_w.groupby(['kma_obsrvn_cd', 'kma_obsrvn_nm', 'use_y'],
                       as_index=False)[['cdd', 'hdd']].sum())
df_w_y = (df_w_y.pivot_table(index=['kma_obsrvn_cd', 'kma_obsrvn_nm'],
                             columns='use_y', values=['cdd', 'hdd'], aggfunc='first')
                .reset_index())
df_w_y.columns = ['_'.join(map(str, c)) if isinstance(c, tuple) else c
                  for c in df_w_y.columns]
df_w_y.rename(columns={'kma_obsrvn_cd_': 'kma_obsrvn_cd',
                       'kma_obsrvn_nm_': 'kma_obsrvn_nm'}, inplace=True)

weather = pd.merge(df_sta, df_w_y, on='kma_obsrvn_cd', how='left')

_want = (['sigungu_cd', 'bjdong_cd', 'kma_obsrvn_cd', 'kma_obsrvn_nm']
         + [f'{k}_{y}' for k in ('cdd', 'hdd') for y in YEARS])
_miss = [c for c in _want if c not in weather.columns]
if _miss:
    print(f'[weather] columns absent from the source, dropped: {_miss}')
weather = weather[[c for c in _want if c in weather.columns]]
weather.to_csv(os.path.join(data_dir, 'after_weather.csv'),
               index=False, encoding='utf-8-sig')
print(f'[weather] after_weather.csv saved ({len(weather):,} rows)')


# %% ==========================================================================
# 4. HIRA medical institution information
# =============================================================================
# The HIRA files are supplied with Korean column headings, so the headings are
# mapped to the source English names in full.
#
# Mapping order
#   1) ALIAS_KOR : normalise headings that differ slightly between releases
#   2) KOR2ENG_* : Korean heading -> source English column name
#   3) any heading left in Korean is reported, so a release change is visible
# -----------------------------------------------------------------------------

# 1) Normalise release-to-release heading variants.
ALIAS_KOR = {
    '암호화YKIHO코드': '암호화요양기호',
    '의사총수': '총의사수',
    '산정 인원수': '산정인원수',
    'X좌표': '좌표(X)',
    'Y좌표': '좌표(Y)',
}

# 2) Korean heading -> source English column name.

# Institutional information
KOR2ENG_FAC0 = {
    '암호화요양기호': 'ykiho',
    '기준년': 'base_yyyy',
    '요양기관명': 'yadm_nm',
    '종별코드': 'cl_cd',
    '종별코드명': 'cl_cd_nm',
    '시도코드_원시': 'sido_cd_ori',
    '시도코드명': 'sido_cd_nm',
    '시군구코드': 'sggu_cd',
    '시군구코드명': 'sggu_cd_nm',
    '읍면동': 'emdong_nm',
    '우편번호': 'post_no',
    '주소': 'addr',
    '전화번호': 'tel_no',
    '병원홈페이지': 'hosp_url',
    '개설일자': 'estb_dd_raw',      # source is text; the converted value is estb_dd
    '총의사수': 'tot_dr_cnt',
    '의과일반의 인원수': 'md_gnrl_dr_cnt',
    '의과인턴 인원수': 'md_intr_cnt',
    '의과레지던트 인원수': 'md_rsdnt_cnt',
    '의과전문의 인원수': 'md_spclt_cnt',
    '치과일반의 인원수': 'dt_gnrl_dr_cnt',
    '치과인턴 인원수': 'dt_intr_cnt',
    '치과레지던트 인원수': 'dt_rsdnt_cnt',
    '치과전문의 인원수': 'dt_spclt_cnt',
    '한방일반의 인원수': 'om_gnrl_dr_cnt',
    '한방인턴 인원수': 'om_intr_cnt',
    '한방레지던트 인원수': 'om_rsdnt_cnt',
    '한방전문의 인원수': 'om_spclt_cnt',
    '조산사 인원수': 'midwf_cnt',
    '좌표(X)': 'x_pos',
    '좌표(Y)': 'y_pos',
    '시도코드_SQI생성': 'sido_cd',

    # -- heading variants of the release used here ---------------------------
    '시도코드': 'sido_cd_ori',
    '시도명': 'sido_cd_nm',
    '시군구명': 'sggu_cd_nm',
    '병원URL': 'hosp_url',
    #   This release reports doctors only as four totals, not split across
    #   medicine / dentistry / Korean medicine, so unprefixed names are used.
    '일반의 의사수': 'gnrl_dr_cnt',
    '인턴 의사수': 'intr_cnt',
    '레지던트 의사수': 'rsdnt_cnt',
    '전문의 의사수': 'spclt_cnt',
}

# Facility information - this is where the 13 bed types live.
KOR2ENG_FAC1 = {
    '암호화요양기호': 'ykiho',
    '기준년': 'base_yyyy',
    '요양기관명': 'yadm_nm',
    '종별코드': 'cl_cd',
    '종별코드명': 'cl_cd_nm',
    '설립구분코드': 'org_ty_cd',
    '설립구분코드명': 'org_ty_cd_nm',
    '시도코드(원본)': 'sido_cd_origin',
    '시도코드명': 'sido_cd_nm',
    '시군구코드': 'sggu_cd',
    '시군구코드명': 'sggu_cd_nm',
    '읍면동': 'emdong_nm',
    '우편번호': 'post_no',
    '주소': 'addr',
    '병원링크': 'hosp_url',
    '개설일자': 'estb_dd_raw',
    '일반입원실상급병상수': 'hghr_sickbd_cnt',
    '일반입원실일반병상수': 'std_sickbd_cnt',
    '성인중환자병상수': 'adu_chld_sprm_cnt',
    '소아중환자병상수': 'chld_sprm_cnt',
    '신생아중환자병상수': 'nby_sprm_cnt',
    '정신과폐쇄상급병상수': 'psydept_cls_hig_sbd_cnt',
    '정신과폐쇄일반병상수': 'psydept_cls_gnl_sbd_cnt',
    '격리병실병상수': 'isnr_sbd_cnt',
    '무균치료실병상수': 'anvir_trrm_sbd_cnt',
    '분만실병상수': 'partum_cnt',
    '수술실병상수': 'soprm_cnt',
    '응급실병상수': 'emym_cnt',
    '물리치료실병상수': 'ptrm_cnt',
    '시도코드_SQI생성': 'sido_cd',

    # -- heading variants of the release used here ---------------------------
    '시도코드': 'sido_cd_origin',
    '시도명': 'sido_cd_nm',
    '시군구명': 'sggu_cd_nm',
    '읍면동명': 'emdong_nm',
    '전화번호': 'tel_no',
    '병원URL': 'hosp_url',
    '성인중환자실병상수': 'adu_chld_sprm_cnt',
    '소아중환자실병상수': 'chld_sprm_cnt',
    '신생아중환자실병상수': 'nby_sprm_cnt',
}

# Medical equipment
KOR2ENG_FAC2 = {
    '암호화요양기호': 'ykiho',
    '기준년': 'base_yyyy',
    '요양기관명': 'yadm_nm',
    '장비코드': 'oft_cd',
    '장비코드명': 'oft_cd_nm',
    '장비대수': 'oft_cnt',
    '시도코드_SQI생성': 'sido_cd',
}

# Meal-service staffing
KOR2ENG_FAC3 = {
    '암호화요양기호': 'ykiho',
    '기준년': 'base_yyyy',
    '요양기관명': 'yadm_nm',
    '유형코드': 'ty_cd',
    '유형코드명': 'ty_cd_nm',
    '일반식 가산여부': 'gnm_addc_yn',
    '산정인원수': 'calc_nop_cnt',
    '치료식 등급': 'trmeal_grd',
    '시도코드_SQI생성': 'sido_cd',
}

# Medical departments
KOR2ENG_FAC5 = {
    '암호화요양기호': 'ykiho',
    '기준년': 'base_yyyy',
    '요양기관명': 'yadm_nm',
    '진료과목코드': 'dgsbjt_cd',
    '진료과목코드명': 'dgsbjt_cd_nm',
    '과목별 전문의수': 'dgsbjt_pr_sdr_cnt',
    '선택진료 의사수': 'cdiag_dr_cnt',
    '시도코드_SQI생성': 'sido_cd',
}

# Address-based matching table (already in English).
MATCH_REN = {'place_code': 'ykiho', 'place_name': 'yadm_nm'}


def rename_to_source(df, kor2eng, label):
    """Normalise headings, map them to the source names, and report leftovers."""
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    # Drop the empty / 'Unnamed: N' columns created by trailing commas.
    drop_cols = [c for c in df.columns
                 if c.startswith('Unnamed:') or c == '' or c.lower() == 'nan']
    if drop_cols:
        print(f'[{label}] dropped {len(drop_cols)} empty/Unnamed columns')
        df = df.drop(columns=drop_cols)

    df = df.rename(columns=ALIAS_KOR)
    df = df.rename(columns=kor2eng)

    # Two different Korean headings mapping onto one English name would make
    # df[col] return a DataFrame instead of a Series and break silently
    # downstream, so stop here instead.
    dup = df.columns[df.columns.duplicated()].unique().tolist()
    if dup:
        raise KeyError(
            f'{label}: duplicated column names after mapping: {dup}\n'
            f'  -> two Korean keys in the KOR2ENG dictionary map to the same '
            f'English name and both are present in the source. Remove one.'
        )

    # Anything still in Korean needs to be added to the dictionary.
    unmapped = [c for c in df.columns
                if any('가' <= ch <= '힣' for ch in str(c))]
    if unmapped:
        print(f'[warning] {label}: {len(unmapped)} column(s) not mapped to a '
              f'source name -> {unmapped}')
    return df


# -----------------------------------------------------------------------------
# 4-1. Address-based matching table
# -----------------------------------------------------------------------------
mat = pd.read_csv(os.path.join(data_dir_in, '전국-의료기관건축물대장매칭.csv'),
                  delimiter='|', encoding='utf-8')
df_mat = mat[mat['base_yyyy'] == hira_base_yyyy].copy()
df_mat = df_mat.rename(columns=MATCH_REN)

# Columns kept from the matching table.
#   Columns that also exist in the building register are deliberately excluded
#   (plat_addr, road_plat_addr, sigungu_cd, bjdong_cd, bun, ji). Keeping them
#   would produce _x/_y suffixes in the S1 merge and break the subsequent
#   weather merge on ['sigungu_cd', 'bjdong_cd']. The building register is the
#   authoritative source for the building location; the institution-side
#   address is retained as input_addr / clean_addr.
_mat_keep = ['ykiho', 'base_yyyy', 'sido_cd', 'plat_gb_cd',
             'input_addr', 'clean_addr',
             'match_mgm_upper_bld_pks', 'match_mgm_bld_pks',
             'match_grade', 'match_level']
df_mat = df_mat[[c for c in _mat_keep if c in df_mat.columns]]
print(f'[HIRA] matching table base_yyyy={hira_base_yyyy} -> {len(df_mat):,} rows')


# -----------------------------------------------------------------------------
# 4-2. Load the five sub-datasets and map their headings
# -----------------------------------------------------------------------------
_HIRA_FILES = {
    'fac0': ('1. 병원정보서비스 2020.3.csv', KOR2ENG_FAC0, 'institutional information'),
    'fac1': ('3. 의료기관별상세정보서비스(시설정보) 2020.3.csv', KOR2ENG_FAC1, 'facility information'),
    'fac2': ('7. 의료기관별상세정보서비스(의료장비정보) 2020.3.csv', KOR2ENG_FAC2, 'medical equipment'),
    'fac3': ('8. 의료기관별상세정보서비스(식대가산정보) 2020.3.csv', KOR2ENG_FAC3, 'meal-service staffing'),
    'fac5': ('5. 의료기관별상세정보서비스(진료과목정보) 2020.3.csv', KOR2ENG_FAC5, 'medical departments'),
}


#   The facility-information release carries 13 Korean bed columns.
_BED_COL_EXPECTED = 13


def add_bed_cnt_from_kor(df, label):
    """Build bed_cnt from the Korean headings, before renaming.

    Bed column headings differ slightly between HIRA releases, so summing every
    heading that ends in the Korean word for "number of beds" is robust to
    those variants in a way that per-column mapping is not. The count is
    checked against _BED_COL_EXPECTED so that a change in the source cannot
    pass silently.
    """
    bed_kor = [c for c in df.columns if str(c).strip().endswith('병상수')]
    print(f'[{label}] {len(bed_kor)} bed columns detected: {bed_kor}')
    if len(bed_kor) != _BED_COL_EXPECTED:
        raise KeyError(
            f'{label}: found {len(bed_kor)} bed columns '
            f'(expected {_BED_COL_EXPECTED}).\n'
            f'  detected = {bed_kor}\n'
            f'  -> if the release changed, adjust _BED_COL_EXPECTED and check '
            f'the documented definition of bed_cnt as well.'
        )
    df = df.copy()
    df['bed_cnt'] = df[bed_kor].apply(pd.to_numeric, errors='coerce').sum(axis=1)
    return df


raw = {}
for key, (fname, kor2eng, label) in _HIRA_FILES.items():
    _d = pd.read_csv(os.path.join(data_dir_in, fname), encoding='cp949',
                     low_memory=False)
    if key == 'fac1':
        _d = add_bed_cnt_from_kor(_d, label=label)
    raw[key] = rename_to_source(_d, kor2eng, label)
    print(f'[HIRA] {label}: {len(raw[key]):,} rows, {raw[key].shape[1]} cols')

df_fac0, df_fac1, df_fac2, df_fac3, df_fac5 = (
    raw['fac0'], raw['fac1'], raw['fac2'], raw['fac3'], raw['fac5'])


# -----------------------------------------------------------------------------
# 4-3. Institutional information + matching table
# -----------------------------------------------------------------------------
df_fac0 = df_fac0.drop(columns=[c for c in ('base_yyyy', 'sido_cd')
                                if c in df_fac0.columns])
df_fac0 = pd.merge(df_fac0, df_mat, how='inner', on='ykiho')
print(f'[HIRA] institutional information joined to the matching table '
      f'-> {len(df_fac0):,} rows')


# -----------------------------------------------------------------------------
# 4-4. Opening date -> datetime (estb_dd / is_estb_dd_valid)
# -----------------------------------------------------------------------------
def convert_estb_dd(df):
    """Convert the opening date (YYYYMMDD) to datetime.

    Values with a broken month or day (e.g. 19850000) keep the year and are set
    to 1 January, with is_estb_dd_valid = False. The filter only tests
    'estb_dd < 2018-01-01', so year precision is sufficient and the row does
    not have to be discarded.
    """
    s = df['estb_dd_raw'].astype('Int64').astype(str)
    s8 = s[s.str.len() == 8]

    month = s8.str[4:6].astype(int)
    day = s8.str[6:8].astype(int)
    ok_mask = month.between(1, 12) & day.between(1, 31)

    estb = pd.Series(index=s.index, dtype='datetime64[ns]')
    is_valid = pd.Series(False, index=s.index)

    # The 1-31 range check cannot reject a day that is invalid for its own month
    # (20190230, 20190431), so the conversion is coerced and anything it returns
    # as NaT joins the broken-date branch below instead of raising.
    _conv = pd.to_datetime(s8[ok_mask], format='%Y%m%d',
                           errors='coerce').dropna()
    estb.loc[_conv.index] = _conv
    is_valid.loc[_conv.index] = True

    bad = s8.loc[s8.index.difference(_conv.index)]
    estb.loc[bad.index] = pd.to_datetime(bad.str[:4], format='%Y',
                                         errors='coerce')

    df['estb_dd'] = estb
    df['is_estb_dd_valid'] = is_valid
    print(f'[HIRA] estb_dd: valid {int(is_valid.sum()):,} / '
          f'year only {int((~is_valid & estb.notna()).sum()):,} / '
          f'missing {int(estb.isna().sum()):,}')
    return df


df_fac0 = convert_estb_dd(df_fac0)


# -----------------------------------------------------------------------------
# 4-5. bed_cnt and the statutory minimum-bed filter
# -----------------------------------------------------------------------------
BED_COLS = ['hghr_sickbd_cnt', 'std_sickbd_cnt',
            'adu_chld_sprm_cnt', 'chld_sprm_cnt', 'nby_sprm_cnt',
            'psydept_cls_hig_sbd_cnt', 'psydept_cls_gnl_sbd_cnt',
            'isnr_sbd_cnt', 'anvir_trrm_sbd_cnt',
            'partum_cnt', 'soprm_cnt', 'emym_cnt', 'ptrm_cnt']

# bed_cnt itself was built before renaming; here only the individual bed
# columns are checked.
_bed_missing = [c for c in BED_COLS if c not in df_fac1.columns]
if _bed_missing:
    print(f'[warning] {len(_bed_missing)} individual bed columns unmapped: '
          f'{_bed_missing}\n'
          f'          -> bed_cnt is unaffected (computed from the Korean '
          f'headings).')
assert 'bed_cnt' in df_fac1.columns, 'bed_cnt missing - check add_bed_cnt_from_kor'

# Statutory minimum number of beds, Article 3-2 of the Medical Service Act.
#   Dental hospitals and long-term care hospitals have no bed minimum.
#   Psychiatric hospitals are licensed as such, so they are treated as meeting
#   the requirement. Tertiary general hospitals are designated from among
#   general hospitals on a periodic review (Article 3-4).
_n0 = len(df_fac1)
df_fac1 = df_fac1[
    ((df_fac1['cl_cd_nm'] == '종합병원') & (df_fac1['bed_cnt'] >= 100)) |
    ((df_fac1['cl_cd_nm'].isin(['병원', '한방병원'])) & (df_fac1['bed_cnt'] >= 30)) |
    (df_fac1['cl_cd_nm'].isin(['요양병원', '치과병원', '정신병원', '상급종합']))
]
print(f'[HIRA] statutory minimum-bed filter: {_n0:,} -> {len(df_fac1):,} rows')


# -----------------------------------------------------------------------------
# 4-6. Derived: equipment (ct_cnt / mri_cnt), meal-service staffing
#      (diet_cnt / cook_cnt), departments (dept_cnt)
# -----------------------------------------------------------------------------
# Equipment codes retained as broad model variables.
DICT_OFT = {
    'B105': 'mammography unit',
    'B108': 'CT',
    'B109': 'cone-beam CT',
    'B201': 'PET',
    'B203': 'bone densitometer',
    'B301': 'MRI',
    'B302': 'ultrasound scanner',
    'B403': 'gamma knife',
    'B404': 'cyber knife',
    'B407': 'proton therapy unit',
    'D212': 'extracorporeal shock wave lithotripter',
    'D214': 'haemodialysis machine',
}

# Units summed per equipment code, then reshaped wide. Column names keep the
# equipment code; only CT and MRI take the released variable names.
df_oft = (df_fac2.groupby(['ykiho', 'oft_cd'])['oft_cnt'].sum().reset_index()
          .pivot(index='ykiho', columns='oft_cd', values='oft_cnt')
          .fillna(0).reset_index())
df_oft.columns.name = None
df_oft = df_oft.rename(columns={'B108': 'ct_cnt', 'B301': 'mri_cnt'})

# Meal-service staffing by staff type -> wide.
df_meal = (df_fac3.pivot_table(index='ykiho', columns='ty_cd_nm',
                               values='calc_nop_cnt', aggfunc='sum')
           .fillna(0).reset_index())
df_meal.columns.name = None
_meal_ren = {c: ('diet_cnt' if '영양' in str(c) else
                 'cook_cnt' if '조리' in str(c) else c)
             for c in df_meal.columns if c != 'ykiho'}
df_meal = df_meal.rename(columns=_meal_ren)
_meal_unknown = [c for c in df_meal.columns
                 if c not in ('ykiho', 'diet_cnt', 'cook_cnt')]
if _meal_unknown:
    print(f'[warning] unexpected meal-service staff types: {_meal_unknown} '
          f'(dietitian and cook expected)')

# Number of clinical departments.
df_dept = (df_fac5.groupby('ykiho')['dgsbjt_cd'].count().reset_index()
           .rename(columns={'dgsbjt_cd': 'dept_cnt'}))


# -----------------------------------------------------------------------------
# 4-7. Merge
# -----------------------------------------------------------------------------
# Facility information is the base; where a column also exists in the
# institutional information, the facility-information copy is kept.
_dup = [c for c in df_fac0.columns
        if c in df_fac1.columns and c != 'ykiho']
print(f'[HIRA] columns dropped from the institutional information: {_dup}')

df_fac = (df_fac1
          .merge(df_fac0.drop(columns=_dup), on='ykiho', how='left')
          .fillna({'match_mgm_bld_pks': 'nan', 'match_mgm_upper_bld_pks': 'nan'}))

# An institution absent from the equipment or meal-service table owns none of
# that equipment and claims no meal-service surcharge, so its counts are 0
# rather than missing. The fill is restricted to the columns each merge brings
# in: a frame-wide fillna(0) would also turn a missing opening date into the
# integer 0 and a missing institution name into 0.
for _side in (df_oft, df_meal):
    _new = [c for c in _side.columns if c != 'ykiho']
    df_fac = df_fac.merge(_side, on='ykiho', how='left')
    df_fac[_new] = df_fac[_new].fillna(0)
df_fac = df_fac.reset_index(drop=True)
df_fac = df_fac.merge(df_dept, on='ykiho', how='left').reset_index(drop=True)

print(f'[HIRA] merged: {len(df_fac):,} rows, {df_fac.shape[1]} cols')

# Data types.
_num_cols = (['bed_cnt', 'tot_dr_cnt', 'dept_cnt', 'ct_cnt', 'mri_cnt',
              'diet_cnt', 'cook_cnt']
             + BED_COLS
             + [c for c in DICT_OFT if c in df_fac.columns]
             + [c for c in ('gnrl_dr_cnt', 'intr_cnt', 'rsdnt_cnt', 'spclt_cnt',
                            'md_gnrl_dr_cnt', 'md_intr_cnt', 'md_rsdnt_cnt',
                            'md_spclt_cnt', 'dt_gnrl_dr_cnt', 'dt_intr_cnt',
                            'dt_rsdnt_cnt', 'dt_spclt_cnt', 'om_gnrl_dr_cnt',
                            'om_intr_cnt', 'om_rsdnt_cnt', 'om_spclt_cnt',
                            'midwf_cnt', 'x_pos', 'y_pos')
                if c in df_fac.columns])
for c in [c for c in _num_cols if c in df_fac.columns]:
    df_fac[c] = pd.to_numeric(df_fac[c], errors='coerce')

# Restore the NaN values that became the literal string during conversion.
df_fac.replace('nan', np.nan, inplace=True)


# -----------------------------------------------------------------------------
# 4-8. Derived: hos_ty_eng (institution type abbreviation)
# -----------------------------------------------------------------------------
df_fac['hos_ty_eng'] = df_fac['cl_cd_nm'].map(HOS_TY_LABEL_MAP)
_unmapped_ty = df_fac.loc[df_fac['hos_ty_eng'].isna(), 'cl_cd_nm'].unique()
if len(_unmapped_ty):
    print(f'[warning] institution types not mapped to hos_ty_eng: '
          f'{list(_unmapped_ty)} -> extend HOS_TY_LABEL_MAP in common.py')


# -----------------------------------------------------------------------------
# 4-9. Save
# -----------------------------------------------------------------------------
df_fac.to_csv(os.path.join(data_dir, f'after_hira_{hira}.csv'),
              index=False, encoding='utf-8-sig')
print(f'\n[save] after_hira_{hira}.csv  '
      f'({len(df_fac):,} rows, {df_fac.shape[1]} cols)')
