# Methodology for China Provincial Simulated Hourly Electricity Load Profiles

Power Transformation Lab, UCSD  
Updated: May 2026

## Overview

We developed a script to generate a **simulated hourly electricity load profile** (24 hours × days in month) for one or more Chinese provinces, given:

- a **target monthly total electricity consumption** (province-level, per month),  
- a province’s typical **workday (工作日 / gongzuori) 24-hour shape**,  
- **daily maximum / minimum** constraints derived from historical “全年日 / quannianri” data (scaled to the target year),  
- and a small amount of **calendar handling** (month length \+ Lunar New Year shifting for Jan/Feb).

The core step is a **quadratic optimization (Gurobi)** that finds hourly loads that:

1) match the daily shape as closely as possible,  
2) respect daily max/min bounds, and  
3) match the monthly total.

## Repository / folder expectations

The script reads a few CSVs from fixed relative paths:

- data/  
    
  - prov\_vars.csv  
  - provincial\_monthly\_revised.csv  
  - holidays.csv


- daily\_profiles/  
    
  - \<prov\_abbrev\>\_gongzuori.csv  
  - \<prov\_abbrev\>\_quannianri.csv


- Simulated\_hourly\_load\_output/  
    
  - output folder

## Dependencies

- Python 3.9+ (any recent 3.x should work)  
- `numpy`  
- `pandas`  
- `gurobipy` (requires a working Gurobi installation \+ license)

## Input data formats

### 1\) `data/prov_vars.csv`

This file maps the province name used throughout the analysis to a short abbreviation used to locate daily profile files. **Required columns**

- `ProvinceName`  
  English province name used as input to the script  
  *(e.g., `Zhejiang`, `Shanghai`)*  
- `prov`  
  Short lowercase abbreviation used in filenames  
  *(e.g., `zj`, `sh`)*

---

### 2\) `data/provincial_monthly_revised.csv`

This table contains **official province-level monthly electricity consumption totals**, which serve as the **hard energy constraint** for the hourly simulation.

**Required structure**

- `province`: province name matching `ProvinceName` in `prov_vars.csv`  
- One column per month, named as: `YYYY-MM` (e.g., `2018-06`, `2023-01`, `2030-06`)

**Purpose**

- Provides the authoritative monthly electricity totals that the simulated hourly loads must integrate to exactly.

**Fallback logic**

- If the requested `(year, month)` column is missing:  
- The script uses the **2023 value for the same month**.  
- It extrapolates forward using compound growth: E(y,m) = E(2023,m) × (1 + g)^(y−2023)  
- The growth rate `g` is configurable (default: `0.05`).

---

### 3\) `daily_profiles/<prov_abbrev>_gongzuori.csv`

This file defines a province’s **normalized 24-hour load shape for a representative workday (工作日)**. **Required columns**

- `y`: hourly profile values  
- Exactly **24 rows**, one per hour  
- Scale is arbitrary (normalization handled by optimization) **Purpose**  
- Provides the **intra-day structure** for hourly loads.  
- The optimization fits each day’s hourly profile to this shape via a per-day affine transformation.

---

### 4\) `daily_profiles/<prov_abbrev>_quannianri.csv`

This file contains **historical daily upper and lower load bounds** for an entire baseline year (2018).

**Required columns**

- `x` \- Numeric day index (interpreted as days since `2018-01-01`)  
- `variable` \- Indicator of bound type:  
- `1` → daily minimum (zd)  
- `2` → daily maximum (zg)  
- `value` \- Load magnitude corresponding to the bound

The script converts:

- `variable == 1` → `'zd'` (daily minimum)  
- `variable == 2` → `'zg'` (daily maximum)

**Purpose**

- Defines the **daily feasible envelope** for electricity demand.  
- Serves as the baseline shape that is rescaled to match target-year monthly totals.

---

### 5\) `data/holidays.csv`

Used only for **Jan/Feb** to shift the profile relative to Lunar New Year.

**Required columns**

- `year`  
- `date` \- Date of Chinese New Year (parseable by pandas)

**Purpose**

- For January and February, the script shifts the 2018 daily profile so that Lunar New Year aligns with the correct calendar date in the target year.  
- Prevents holiday-induced load anomalies from being assigned to incorrect days.

## What the script does (high-level workflow)

For each (province, year, month), the script converts historical daily load envelopes into a statistically consistent, hour-level electricity load profile that exactly matches official monthly electricity statistics while preserving realistic intra-day and intra-month structure. The workflow consists of three main stages: (1) rescaling historical profiles, (2) constructing month-specific constraints, and (3) performing hourly optimization.

### Step 1: Rescale historical daily profiles to official monthly totals

To ensure consistency with official provincial energy statistics, the script rescales the baseline daily load profile **month by month**:

1. The historical “quannianri” dataset provides a daily **upper bound (zg)** and **lower bound (zd)** for each day of 2018\.  
2. For each day, a representative daily load level is computed as the **average of the upper and lower bounds**.  
3. This daily value is converted into a raw **monthly energy estimate** by assuming 24 hours per day and summing across all days in the month.  
4. A **monthly scaling factor** is computed as:
     
   scale factor = official monthly total / raw monthly estimated energy  
     
5. This factor is applied **uniformly to all daily values** within the month.

**Special case — January and February**: when `combine_jan_feb` is enabled, January and February are treated as a single combined period and share one scaling factor computed from their joint implied energy and joint official total, rather than being rescaled independently. This avoids artificially sharp discontinuities at the Jan/Feb boundary caused by separate monthly multipliers.

This preserves the original intra-month shape implied by the historical profile while ensuring that the integrated hourly load **exactly matches** the official monthly electricity consumption.

### Step 2: Construct month-specific daily load constraints (`filter_data`)

The function `filter_data` prepares the month-specific daily constraints used in the downstream optimization.

Given a province, target month, and target year:

1. Builds a full-year template using the 2018 “quannianri” bounds.  
2. For **January and February**, the template is shifted so that the 2018's Chinese New Year align with the **target year’s** Chinese New Year date (via `shift_lunar_new_year`).  
- This prevents holiday-driven demand anomalies from being misaligned.  
**Example**: generating data for **2020** using the 2018 reference profile —  
- **Lunar New Year 2018**: 16 February  
- **Lunar New Year 2020**: 25 January  
- **Date difference**: 2018-02-16 − 2020-01-25 = **22 days** → all 2018 dates are shifted back by 22 days.  

After shifting, the holiday-period load pattern lands on the correct calendar dates in 2020. Missing dates produced by the shift are filled by back-fill. Only the January and February rows from the shifted series are used in the optimization; all other months retain the original unshifted 2018 values.

3. Filters the annual template to keep only the days belonging to the target month.  
4. Determines the **target monthly electricity consumption**:  
- If `(year, month)` exists in the official table, use that value.  
- Otherwise, extrapolate from **2023** using compound growth:
    
  target = E_2023 × (1 + growth_rate)^(year - 2023)  
    
5. Computes a **month-specific scaling factor**:
     
   month scale = target monthly total / 2018 monthly total  
     
6. Applies the scaling factor to all daily upper and lower bounds for the month.  
7. Computes the number of days (`ndays`) in the target month and extracts:  
- `daily_max[d]` — scaled daily upper bounds  
- `daily_min[d]` — scaled daily lower bounds

**Reconciliation step** (`scale_quannianri`): after proportional scaling, the implied monthly energy computed from the scaled daily bounds may still differ slightly from the target due to the fixed daily shape. A second correction is therefore applied:

- **(a)** Compute implied daily mean = (zg + zd) / 2 for each day, then sum over the month to get the implied monthly total.  
- **(b)** Compare the implied monthly total with the target monthly load.  
- **(c)** Add the same constant shift Δ to both zg and zd for every day in the month, where Δ is chosen so that the corrected implied total equals the target. Because the same value is added to both bounds, the daily spread (zg − zd) is preserved while the overall load level shifts up or down.

**Multi-month handling**: when `month` is a list (e.g., `[1, 2]` for a combined Jan/Feb period), the reconciliation is performed separately for each individual month. The total target load is split across months in proportion to the number of days:

target_m = target_month_load × (days_in_month / total_days)

Each month is then reconciled independently against its allocated share, keeping every month internally consistent.

### Step 3: Perform hourly load optimization (`run_optimization`)

Once month-specific constraints are prepared, the script solves a quadratic optimization problem to generate hourly loads:

1. Creates decision variables `Y[d, h]` representing the hourly load for each day and hour.  
2. Fits each day's hourly load to the province’s **typical workday (gongzuori) 24-hour shape** via a per-day affine transformation.  
3. Ensures hourly values remain consistent with the scaled daily upper and lower bounds (`daily_max`, `daily_min`).  
4. Enforces that the total of all hourly loads matches the **official monthly electricity consumption** (strong penalty weight).

5. Penalizes **large jumps in daily average load** between consecutive days (adjacent-day smoothness penalty), encouraging realistic day-to-day continuity across the month.

6. If a **previous month** has already been optimized and its last-day average is available, penalizes a mismatch between that value and the first-day average of the current period (boundary continuity penalty), eliminating artificial breaks at month boundaries.

The relative importance of each goal is controlled by **six tunable weights** in `run_optimization`: `w_daily_profiles`, `w_daily_max`, `w_daily_min`, `w_monthly_total`, `w_dayjump`, and `w_boundary`. A larger weight means the corresponding target is enforced more strictly. For example, a large `w_monthly_total` prioritises matching the monthly total, while a large `w_dayjump` prioritises smooth day-to-day transitions.

### Step 4: Batch execution across provinces, years, and months (`run_multi_optimizations`)

The function `run_multi_optimizations` automates the full pipeline over arbitrary lists of provinces, years, and months in a single call.

**Key behaviors**:

- Months are processed in calendar order within each year.  
- When both January and February appear in the month list, they are solved together as one combined optimization period (consistent with the `combine_jan_feb` logic in Steps 1–2).  
- After each period is solved, the last-day average load is passed to the next period as the boundary reference. This value feeds the boundary continuity penalty in Step 3, ensuring smooth transitions at every month boundary throughout the year.  
- Results for each province/year/month are written to individual CSV files (see Outputs).

## Outputs

For each province/month/year, the script writes: `Simulated_hourly_load_output/<province>_<year>_<month>.csv` with columns:

- `day` (1..ndays)  
- `hour` (1..24)  
- `value` (optimized hourly load)  
- `hour_full` (1..ndays\*24, a flattened hour index)

## How to run

1. Ensure the input files exist in the expected folders.  
2. Ensure Gurobi is installed and licensed.  
3. Create the output folder if needed:  
     
   mkdir -p Simulated_hourly_load_output  
     
4. Edit the main() function in simulate_province_load.py:

    def main():

        province_lst = ['Zhejiang','Shanghai','Jiangsu','Anhui','Fujian'] # target province list

        month_lst = [6] # target month list 1-12 

        year_lst = [2030] # target year list

        run_multi_optimizations(province_lst, month_lst, year_lst)

5. Run:

    python simulate_province_load.py  
