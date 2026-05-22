import os
import numpy as np
import pandas as pd
import rpy2.robjects as ro
from rpy2.robjects import pandas2ri
import itertools
import calendar
import gurobipy as gp
from gurobipy import GRB, quicksum
import numpy as np
from scipy.interpolate import interp1d
from datetime import datetime



def scale_power_by_energy(df_quannianri, province_monthly, province,
                          base_year=2018, unit_scale=100000.0,
                          combine_jan_feb=True):
    """
    Scale daily (zd/zg) profiles to match monthly targets.
    If combine_jan_feb=True, use ONE multiplier for Jan+Feb combined.
    """
    df = df_quannianri.copy()
    df["raw_value"] = df["value"].astype(float)
    df["value"] = np.nan


    pm = province_monthly.loc[province_monthly["province"] == province]
    if pm.empty:
        raise ValueError(f"province '{province}' not found in province_monthly")

    def month_col(m):
        return f"{base_year}-{m:02d}"
    def implied_energy_for_months(months):
        sub = df[df["month"].isin(months)]
        if sub.empty:
            return None

        wide = (
            sub.drop(columns=[c for c in ["x", "date"] if c in sub.columns])
              .pivot(index=["month", "day"], columns="variable", values="raw_value")
              .reset_index()
        )
        if ("zd" not in wide.columns) or ("zg" not in wide.columns):
            return None

        daily_mean = 0.5 * (wide["zd"].astype(float) + wide["zg"].astype(float))
        return float(daily_mean.sum() * 24.0 / unit_scale)

    handled = set()
    if combine_jan_feb:
        months = [1, 2]
        col1, col2 = month_col(1), month_col(2)
        if col1 not in pm.columns or col2 not in pm.columns:
            raise KeyError(f"Need both '{col1}' and '{col2}' in province_monthly to combine Jan+Feb")

        target_total = float(pm[col1].values[0]) + float(pm[col2].values[0])
        implied_total = implied_energy_for_months(months)

        if implied_total and implied_total != 0:
            mult = target_total / implied_total
            mask = df["month"].isin(months)
            df.loc[mask, "value"] = df.loc[mask, "raw_value"] * mult

        handled.update(months)

    for m in range(1, 13):
        if m in handled:
            continue

        col = month_col(m)
        if col not in pm.columns:
            raise KeyError(f"monthly column '{col}' not found in province_monthly")

        target = pm[col].values[0]
        if pd.isna(target):
            continue

        implied = implied_energy_for_months([m])
        if implied is None or implied == 0:
            continue

        mult = float(target) / float(implied)
        mask = df["month"] == m
        df.loc[mask, "value"] = df.loc[mask, "raw_value"] * mult

    return df


def load_data(province, province_abbrev, combine_jan_feb=True):
    df_monthly = pd.read_csv('data/provincial_monthly_revised.csv')
    # Target province monthly consumption
    province_monthly = df_monthly[df_monthly["province"] == province]
    # Daily profiles gongzuori
    df_gonzuori = pd.read_csv(f'daily_profiles/{province_abbrev}_gongzuori.csv')
    # Daily profiles quannianri
    df_quannianri = pd.read_csv(f'daily_profiles/{province_abbrev}_quannianri.csv')
    df_quannianri['date'] = pd.to_datetime(df_quannianri['x'] - 0.5, origin='2018-01-01', unit='D')
    df_quannianri['month'] = df_quannianri['date'].dt.month
    df_quannianri['day'] = df_quannianri['date'].dt.day
    df_quannianri['variable'] = df_quannianri['variable'].replace({1: 'zd', 2: 'zg'})
    # IMPORTANT: Jan+Feb use one multiplier when combine_jan_feb=True
    all_quannianri = scale_power_by_energy(
        df_quannianri,
        province_monthly,
        province,
        combine_jan_feb=combine_jan_feb
    )

    return all_quannianri, df_gonzuori

def load_data_for_province(province, combine_jan_feb=True):
    abbrev_df = pd.read_csv('data/prov_vars.csv')

    province_abbrev = abbrev_df.loc[
        abbrev_df['ProvinceName'] == province, 'prov'
    ].values[0]

    all_quannianri, df_gonzuori = load_data(
        province,
        province_abbrev,
        combine_jan_feb=combine_jan_feb
    )

    return all_quannianri, df_gonzuori, province_abbrev
    


def shift_lunar_new_year(year, province, province_abbrev, combine_jan_feb=True):
    holiday = pd.read_csv('data/holidays.csv')
    holiday['date'] = pd.to_datetime(holiday['date'])

    cny = pd.to_datetime(holiday.loc[holiday['year'] == year, 'date'].values[0])
    cny_2018 = pd.to_datetime(holiday.loc[holiday['year'] == 2018, 'date'].values[0])

    # IMPORTANT: ensure scaling uses combined Jan+Feb multiplier if desired
    all_quannianri, _ = load_data(province, province_abbrev, combine_jan_feb=combine_jan_feb)

    date_different = (cny_2018 - cny) / np.timedelta64(1, 'D')

    all_quannianri = all_quannianri.copy()
    all_quannianri['date'] = all_quannianri['date'] - pd.Timedelta(days=float(date_different))
    all_quannianri['month'] = all_quannianri['date'].dt.month
    all_quannianri['day'] = all_quannianri['date'].dt.day

    # compare month-day ordering between 2018 and target year (your original logic)
    holiday['month_day'] = holiday['date'].dt.strftime('%m-%d')
    holiday['month_day_dt'] = pd.to_datetime(holiday['month_day'], format='%m-%d')

    md_2018 = holiday.loc[holiday['year'] == 2018, 'month_day_dt'].values[0]
    md_year = holiday.loc[holiday['year'] == year, 'month_day_dt'].values[0]

    # filter to the shifted dates that land in the target year
    filtered_data = all_quannianri[all_quannianri['date'].dt.year == year].copy()

    # Build full (month,day,variable) grid and merge, then backfill
    unique_variables = filtered_data['variable'].unique()
    month_day_combinations = list(itertools.product(range(1, 13), range(1, 32)))
    variable_combinations = list(itertools.product(unique_variables, month_day_combinations))

    temp = pd.DataFrame(variable_combinations, columns=['variable', 'month_day'])
    temp[['month', 'day']] = pd.DataFrame(temp['month_day'].tolist(), index=temp.index)
    temp = temp.drop(columns=['month_day'])

    new_all_quannianri = temp.merge(filtered_data, on=['month', 'day', 'variable'], how='left')

    # Your original code: in one branch you dropped rows with no date first.
    # We'll keep that behavior only when md_2018 > md_year (same condition you used).
    if md_2018 > md_year:
        new_all_quannianri = new_all_quannianri.dropna(subset=['date'])

    # backfill missing values (keeps your original choice)
    new_all_quannianri['value'] = new_all_quannianri['value'].bfill()

    return new_all_quannianri


def scale_monthly(province, month, year, growth_rate):
    """
    Returns target load for a month OR for a multi-month period.
    - month can be an int (e.g., 3)
    - or a list/tuple of ints (e.g., [1,2]) meaning combine targets
    """
    df_monthly = pd.read_csv('data/provincial_monthly_revised.csv')
    province_monthly = df_monthly[df_monthly["province"] == province]

    def get_one_month_target(m):
        col = f"{year}-{m:02d}"
        try:
            return float(province_monthly.loc[province_monthly['province'] == province, col].values[0])
        except Exception:
            col_2023 = f"2023-{m:02d}"
            month_load_2023 = float(province_monthly.loc[province_monthly['province'] == province, col_2023].values[0])
            return month_load_2023 * ((1 + growth_rate) ** (year - 2023))

    # if month is a period like [1,2], sum them
    if isinstance(month, (list, tuple, set, np.ndarray)):
        return sum(get_one_month_target(int(m)) for m in month)

    # otherwise single month int
    return get_one_month_target(int(month))



def scale_quannianri(province, target_quannianri, month, target_month_load):
    """
    Scale quannianri values relative to 2018 baseline, then reconcile (zd/zg)
    by adding the same delta to both so that implied monthly energy matches
    target under midpoint daily mean mapping.

    SAME INPUT PARAMETERS as before.

    Notes:
    - Expects target_quannianri to contain:
        ['month','day','variable','value'] with variable in {'zd','zg'}
    - Implied daily mean is computed as (zd + zg) / 2
    - If month is [1,2], it reconciles each month separately to keep each month’s
      implied energy aligned to its portion of target_month_load (by day-count split)
    """

    # ----------------------------
    # 1) Baseline scaling (original behavior)
    # ----------------------------
    df_monthly = pd.read_csv('data/provincial_monthly_revised.csv')
    pm = df_monthly[df_monthly["province"] == province]
    if pm.empty:
        raise ValueError(f"province '{province}' not found in provincial_monthly_revised.csv")

    def baseline_2018(m):
        col = f"2018-{int(m):02d}"
        if col not in pm.columns:
            raise KeyError(f"Missing column '{col}' in monthly table")
        v = pm.iloc[0][col]
        if pd.isna(v):
            raise ValueError(f"Baseline '{col}' is NaN for province '{province}'")
        return float(v)

    if isinstance(month, (list, tuple, set, np.ndarray)):
        months = [int(m) for m in month]
        baseline_total = sum(baseline_2018(m) for m in months)
    else:
        months = [int(month)]
        baseline_total = baseline_2018(months[0])

    if baseline_total == 0:
        raise ValueError("Baseline 2018 monthly load is zero — cannot scale.")

    scale_factor = float(target_month_load) / float(baseline_total)

    q = target_quannianri.copy()
    q["value"] = q["value"].astype(float)
    q["scaledValue"] = q["value"] * scale_factor

    # ----------------------------
    # 2) Reconcile (zd/zg) by adding same delta so implied monthly matches target
    #    under midpoint mapping: daily_mean = (zd + zg) / 2
    # ----------------------------
    unit_scale = 100000.0

    def implied_energy_for_months(df_sub, months):
        sub = df_sub[df_sub["month"].isin(months)]
        if sub.empty:
            return None

        wide = (
            sub.drop(columns=[c for c in ["x", "date"] if c in sub.columns], errors="ignore")
               .pivot(index=["month", "day"], columns="variable", values="scaledValue")
               .reset_index()
        )
        if ("zd" not in wide.columns) or ("zg" not in wide.columns):
            return None

        daily_mean = 0.5 * (wide["zd"].astype(float) + wide["zg"].astype(float))
        return float(daily_mean.sum() * 24.0 / unit_scale)

    def reconcile_one_month(df_m, target_load_m):
        wide = (
            df_m.pivot_table(index="day", columns="variable", values="scaledValue", aggfunc="first")
               .copy()
        )
        if ("zd" not in wide.columns) or ("zg" not in wide.columns):
            return df_m

        implied_month = float((0.5 * (wide["zd"] + wide["zg"])).sum() * 24.0 / unit_scale)
        if implied_month == 0:
            return df_m

        gap = float(target_load_m) - implied_month
        tol = 1e-3 * float(target_month_load)
        if abs(gap) <= tol:
            return df_m

        # If we add delta to both zd and zg, then daily_mean increases by delta
        # So monthly energy changes by len(days) * delta * 24 / unit_scale
        n_days = len(wide)
        delta = (gap * unit_scale) / (24.0 * n_days)

        wide["zg"] = wide["zg"] + delta
        wide["zd"] = wide["zd"] + delta

        corr = (
            wide.reset_index()
                .melt(id_vars="day", var_name="variable", value_name="scaledValue")
        )

        out = df_m.drop(columns=["scaledValue"]).merge(corr, on=["day", "variable"], how="left")
        return out

    if len(months) == 1:
        q = reconcile_one_month(q, target_month_load)
    else:
        parts = []
        counts = {m: q[q["month"] == m]["day"].nunique() for m in months}
        total_days = sum(counts.values()) if sum(counts.values()) > 0 else 1

        for m in months:
            df_m = q[q["month"] == m].copy()
            if df_m.empty:
                continue
            target_m = float(target_month_load) * (counts[m] / total_days)
            parts.append(reconcile_one_month(df_m, target_m))

        if parts:
            q = pd.concat(parts, ignore_index=True)

    return q

  
def filter_data(province, province_abbrev, month, year, growth_rate=0.05):
    """
    month can be:
      - int (e.g., 3)
      - list/tuple (e.g., [1,2]) meaning treat Jan+Feb as one period
    """
    # normalize month input
    if isinstance(month, (list, tuple, set, np.ndarray)):
        months = sorted([int(m) for m in month])
    else:
        months = [int(month)]

    # load base quannianri (shift LNY if period includes Jan or Feb)
    if 1 in months or 2 in months:
        df_quannianri = shift_lunar_new_year(year, province, province_abbrev)
    else:
        df_quannianri, _ = load_data(province, province_abbrev)

    # select target period and keep calendar order
    target_quannianri = df_quannianri[df_quannianri['month'].isin(months)].copy()
    # sorting by date ensures Jan days come before Feb days
    if 'date' in target_quannianri.columns:
        target_quannianri = target_quannianri.sort_values(['date', 'variable']).reset_index(drop=True)
    else:
        target_quannianri = target_quannianri.sort_values(['month', 'day', 'variable']).reset_index(drop=True)
    monthly = scale_monthly(province, months, year, growth_rate)

    # scale using combined 2018 baseline if months is a list (your updated scale_quannianri supports list)
    if year==2018:
        scaled_quannianri = target_quannianri.copy()
        scaled_quannianri["scaledValue"] = scaled_quannianri["value"]
    else:
        scaled_quannianri = scale_quannianri(province, target_quannianri, months, monthly)
    # total number of days in this period
    ndays = sum(calendar.monthrange(year, m)[1] for m in months)
    # daily max/min arrays for the period, truncated to ndays for safety
    daily_max = np.array(
        scaled_quannianri.loc[scaled_quannianri['variable'] == 'zg', 'scaledValue'].to_numpy(dtype=float)
    )[:ndays]

    daily_min = np.array(
        scaled_quannianri.loc[scaled_quannianri['variable'] == 'zd', 'scaledValue'].to_numpy(dtype=float)
    )[:ndays]

    return scaled_quannianri, ndays, daily_max, daily_min, monthly

def load_and_filter_data(province, month, year, combine_jan_feb=True):
    # Make sure base profiles are scaled consistently (Jan+Feb share one multiplier if combine_jan_feb=True)
    all_quannianri, df_gonzuori, province_abbrev = load_data_for_province(
        province, combine_jan_feb=combine_jan_feb
    )
    scaled_quannianri, ndays, daily_max, daily_min, monthly = filter_data(
        province, province_abbrev, month, year, growth_rate=0.05
    )
    return ndays, df_gonzuori, daily_max, daily_min, monthly * 100000


def run_optimization(
    province, year, month, ndays,
    df_gonzuori, daily_max, daily_min, monthly,
    prev_last_day_avg=None,
    # ---- weights you can tune ----
    w_boundary=1e5,        # cross-period day1 avg vs prev last-day avg
    w_dayjump=1e3,         # adjacent-day avg smoothness (prevents cliffs)
    w_monthly_total=1e6,   # monthly total penalty
    w_daily_profiles=1.0,
    w_daily_min=1e1,
    w_daily_max=1000,
    save_split_months=None,   # e.g., [1,2] to save two files when solved as one period
):
    
    print("w_daily_max used =", w_daily_max)
    # ----- period label for printing & filenames -----
    if isinstance(month, (list, tuple, set, np.ndarray)):
        period_months = [int(m) for m in month]
        month_label = "_".join(str(m) for m in period_months)
    else:
        period_months = [int(month)]
        month_label = str(int(month))

    print(f"Running optimization for province of {year}-{month_label}")
    os.makedirs("province_test", exist_ok=True)

    # ----- shape -----
    shape = df_gonzuori["y"].to_numpy(dtype=float)
    shape = shape - shape.mean()

    # ----- daily max/min: enforce length ndays -----
    daily_max = np.asarray(daily_max, dtype=float).reshape(-1)
    daily_min = np.asarray(daily_min, dtype=float).reshape(-1)

    if len(daily_max) < ndays:
        daily_max = np.pad(daily_max, (0, ndays - len(daily_max)), mode="edge")
    else:
        daily_max = daily_max[:ndays]

    if len(daily_min) < ndays:
        daily_min = np.pad(daily_min, (0, ndays - len(daily_min)), mode="edge")
    else:
        daily_min = daily_min[:ndays]

    # ----- model -----
    model = gp.Model("optimization_problem")

    # decision variables
    Y = model.addVars(ndays, 24, name="Y")     # hourly load
    a = model.addVars(ndays, lb=0, name="a")   # daily scale
    b = model.addVars(ndays, name="b")         # daily offset

    # penalties
    p_dailyprofile = model.addVars(ndays, 24, lb=0, name="p_dailyprofile")

    p_dailymax = model.addVars(ndays, lb=0, name="p_dailymax")
    b_dailymax = model.addVars(ndays, name="b_dailymax")

    p_dailymin = model.addVars(ndays, lb=0, name="p_dailymin")
    b_dailymin = model.addVars(ndays, name="b_dailymin")

    p_monthlytotal = model.addVar(lb=0, name="p_monthlytotal")

    # daily average variables
    D = model.addVars(ndays, lb=-GRB.INFINITY, name="D")
    for d in range(ndays):
        model.addConstr(24 * D[d] == gp.quicksum(Y[d, h] for h in range(24)), name=f"def_D[{d}]")

    # objective
    obj = 0
    obj += w_daily_profiles * gp.quicksum(
        p_dailyprofile[d, h] * p_dailyprofile[d, h]
        for d in range(ndays) for h in range(24)
    )
    obj += w_daily_max * gp.quicksum(p_dailymax[d] * p_dailymax[d] for d in range(ndays))
    obj += w_daily_min * gp.quicksum(p_dailymin[d] * p_dailymin[d] for d in range(ndays))
    obj += w_monthly_total * (p_monthlytotal * p_monthlytotal)

    # adjacent-day avg smoothness (cliff)
    delta_pct = 0.001
    delta_min = 50.0

    D_ref = 0.5 * (daily_max + daily_min)  # (ndays,)
    delta_allow_arr = np.maximum(delta_min, delta_pct * D_ref[:-1])  # (ndays-1,)

    p_cliff = model.addVars(ndays - 1, lb=0, name="p_cliff")

    for d in range(1, ndays):
        diff = D[d] - D[d - 1]
        allow = float(delta_allow_arr[d - 1])
        model.addConstr(p_cliff[d - 1] >= diff - allow,  name=f"cliff_pos[{d-1}]")
        model.addConstr(p_cliff[d - 1] >= -diff - allow, name=f"cliff_neg[{d-1}]")

    obj += w_dayjump * gp.quicksum(p_cliff[k] * p_cliff[k] for k in range(ndays - 1))

    # boundary continuity (KEEP)
    if prev_last_day_avg is not None:
        obj += w_boundary * (D[0] - float(prev_last_day_avg)) * (D[0] - float(prev_last_day_avg))

    model.setObjective(obj, GRB.MINIMIZE)

    # peak/valley hours from shape curve
    peak_h = int(np.argmax(df_gonzuori["y"]))
    valley_h = int(np.argmin(df_gonzuori["y"]))

    # constraints
    for d in range(ndays):
        for h in range(24):
            expr = Y[d, h] - a[d] * float(shape[h]) - b[d]
            model.addConstr(p_dailyprofile[d, h] >= expr,  name=f"profile_abs_pos[{d},{h}]")
            model.addConstr(p_dailyprofile[d, h] >= -expr, name=f"profile_abs_neg[{d},{h}]")

        # daily max
        model.addConstr(b_dailymax[d] == Y[d, peak_h], name=f"def_dailymax[{d}]")
        for h in range(24):
            model.addConstr(Y[d, h] <= b_dailymax[d], name=f"cap_dailymax[{d},{h}]")
        model.addConstr(p_dailymax[d] >= b_dailymax[d] - daily_max[d],   name=f"pmax_pos[{d}]")
        model.addConstr(p_dailymax[d] >= -(b_dailymax[d] - daily_max[d]), name=f"pmax_neg[{d}]")

        # daily min
        model.addConstr(b_dailymin[d] == Y[d, valley_h], name=f"def_dailymin[{d}]")
        for h in range(24):
            model.addConstr(Y[d, h] >= b_dailymin[d], name=f"cap_dailymin[{d},{h}]")
        model.addConstr(p_dailymin[d] >= b_dailymin[d] - daily_min[d],   name=f"pmin_pos[{d}]")
        model.addConstr(p_dailymin[d] >= -(b_dailymin[d] - daily_min[d]), name=f"pmin_neg[{d}]")

    # monthly/period total (soft)
    total_energy = gp.quicksum(Y[d, h] for d in range(ndays) for h in range(24))
    model.addConstr(p_monthlytotal >= total_energy - float(monthly),  name="month_pos")
    model.addConstr(p_monthlytotal >= -(total_energy - float(monthly)), name="month_neg")

    # solver params (keep your defaults)
    model.setParam("IterationLimit", 1e9)
    model.setParam("BarIterLimit", 20000)
    model.setParam("TimeLimit", 1200)
    model.setParam("MIPGap", 1e-3)
    model.setParam("BarQCPConvTol", 1e-2)
    model.setParam("FeasibilityTol", 1e-2)
    model.setParam("OptimalityTol", 1e-2)
    model.setParam("BarConvTol", 1e-2)
    model.setParam("IntFeasTol", 1e-6)
    model.setParam("MIQCPMethod", 0)
    model.setParam("Method", 0)
    model.setParam("MIPFocus", 1)
    model.setParam("OutputFlag", 1)

    model.optimize()

    if model.status != GRB.OPTIMAL:
        print("No optimal solution found. status =", model.status)
        return None

    # ----- diagnostics -----
    print("\n---- Daily a[i] and b[i] ----")
    a_values, b_values = [], []
    for i in range(ndays):
        ai = a[i].X
        bi = b[i].X
        a_values.append(ai)
        b_values.append(bi)
        print(f"Day {i+1:02d} | a = {ai:.4f} | b = {bi:.4f}")

    print("\nSummary:")
    print(f"a std: {np.std(a_values):.4f}")
    print(f"b std: {np.std(b_values):.4f}")
    print("-----------------------------\n")

    shape_term = sum(p_dailyprofile[d, h].X**2 for d in range(ndays) for h in range(24))
    max_term   = sum(p_dailymax[d].X**2 for d in range(ndays))
    min_term   = sum(p_dailymin[d].X**2 for d in range(ndays))
    cliff_term = sum(p_cliff[k].X**2 for k in range(ndays - 1))
    month_term = p_monthlytotal.X**2
    bound_term = (D[0].X - float(prev_last_day_avg))**2 if prev_last_day_avg is not None else 0.0

    print("\n--- raw penalty terms (no weights) ---")
    print("shape_term:", shape_term)
    print("max_term  :", max_term)
    print("min_term  :", min_term)
    print("cliff_term:", cliff_term)
    print("month_term:", month_term)
    print("bound_term:", bound_term)

    # ----- extract solution -----
    y_values = np.zeros((ndays, 24), dtype=float)
    for d in range(ndays):
        for h in range(24):
            y_values[d, h] = Y[d, h].X

    df_y = pd.DataFrame(y_values, columns=[f"hour_{h}" for h in range(24)])
    df_y["day"] = np.arange(1, ndays + 1)

    df_long = df_y.melt(id_vars=["day"], var_name="hour", value_name="value")
    df_long["hour"] = df_long["hour"].str.extract(r"hour_(\d+)").astype(int) + 1  # 1..24
    df_long["hour_full"] = (df_long["day"] - 1) * 24 + df_long["hour"]
    df_sorted = df_long.sort_values(by=["day", "hour"]).reset_index(drop=True)

   
    # If solving Jan+Feb together, save ONLY month files (no 1_2 file),
    # and reset day/hour_full so each month starts at day=1.
    if save_split_months is not None and len(save_split_months) > 1:
        # Construct timestamps for the whole solved period, starting at the first month day1 00:00
        start_ts = pd.Timestamp(year=year, month=int(save_split_months[0]), day=1, hour=0)

        tmp = df_sorted.copy()
        tmp["ts"] = start_ts + pd.to_timedelta(tmp["hour_full"] - 1, unit="h")

        for m in save_split_months:
            m = int(m)
            df_m = tmp[tmp["ts"].dt.month == m].copy()

            if df_m.empty:
                print(f"[WARN] No rows for month={m} in period output; skipping save.")
                continue

            # Reset day/hour/hour_full within the month
            month_start = pd.Timestamp(year=year, month=m, day=1, hour=0)
            offset_hours = ((df_m["ts"] - month_start) / pd.Timedelta(hours=1)).astype(int)

            df_m["hour_full"] = offset_hours + 1                    # 1..(days*24)
            df_m["day"] = (offset_hours // 24) + 1                  # day starts at 1
            df_m["hour"] = (offset_hours % 24) + 1                  # hour starts at 1..24

            # Keep only the original schema/order
            df_m = df_m[["day", "hour", "value", "hour_full"]].sort_values(["day", "hour"]).reset_index(drop=True)

            file_name = f"{province}_{year}_{m}.csv"
            save_path = os.path.join("Simulated_output_provincial_hourly_load", file_name)
            df_m.to_csv(save_path, index=False)
            print("Saved:", save_path)

        # IMPORTANT: do NOT save the combined {month_label} file
    else:
        # Normal single-month case: save as usual
        file_name = f"{province}_{year}_{month_label}.csv"
        save_path = os.path.join("Simulated_output_provincial_hourly_load", file_name)
        df_sorted.to_csv(save_path, index=False)
        print("Saved:", save_path)

    # ----- summary -----
    period_sum = df_sorted["value"].sum()
    d1_avg = df_sorted[df_sorted["day"] == 1]["value"].mean()
    dlast_avg = df_sorted[df_sorted["day"] == ndays]["value"].mean()

    print("mean b this period:", np.mean([b[d].X for d in range(ndays)]))
    print("target total:", monthly, " achieved:", period_sum, " diff:", period_sum - monthly)
    print("day1 avg:", d1_avg, " last day avg:", dlast_avg)
    print("prev_last_day_avg passed in:", prev_last_day_avg)

    return df_sorted

def run_multi_optimizations(province_lst, month_lst, year_lst):
    all_results = []

    for province in province_lst:
        for year in year_lst:
            prev_last_day_avg = None

            months_sorted = sorted([int(m) for m in month_lst])

            i = 0
            while i < len(months_sorted):
                m = months_sorted[i]

                # --- combine Jan+Feb as one period if both are present ---
                if m == 1 and (2 in months_sorted):
                    period = [1, 2]
                    i += 2  # skip month 2
                    split_months = [1, 2]
                else:
                    period = m
                    i += 1
                    split_months = None

                # load data (period can be int or [1,2])
                ndays, df_gonzuori, daily_max, daily_min, monthly = load_and_filter_data(
                    province, period, year
                )

                # optimize
                df_sorted = run_optimization(
                    province, year, period,
                    ndays, df_gonzuori, daily_max, daily_min, monthly,
                    prev_last_day_avg=prev_last_day_avg,

                    # ---- tune here if needed ----
                    w_boundary=1e6,
                    w_dayjump=1e3,
                    w_monthly_total=1e5,
                    w_daily_profiles=200,
                    w_daily_min=100,
                    w_daily_max=100,

                    # if period=[1,2], optionally save Jan.csv and Feb.csv too
                    save_split_months=split_months,
                )

                # carry boundary to next period; collect rows for combined output
                if df_sorted is not None:
                    prev_last_day_avg = df_sorted[df_sorted["day"] == ndays]["value"].mean()

                    if split_months is not None and len(split_months) > 1:
                        # Reconstruct per-month day/hour from timestamps
                        start_ts = pd.Timestamp(year=year, month=int(split_months[0]), day=1, hour=0)
                        tmp = df_sorted.copy()
                        tmp["ts"] = start_ts + pd.to_timedelta(tmp["hour_full"] - 1, unit="h")
                        for sm in [int(s) for s in split_months]:
                            month_start = pd.Timestamp(year=year, month=sm, day=1, hour=0)
                            df_m = tmp[tmp["ts"].dt.month == sm].copy()
                            if df_m.empty:
                                continue
                            offset_h = ((df_m["ts"] - month_start) / pd.Timedelta(hours=1)).astype(int)
                            df_m["day"]   = (offset_h // 24) + 1
                            df_m["hour"]  = (offset_h % 24) + 1
                            df_m["province"] = province
                            df_m["year"]     = year
                            df_m["month"]    = sm
                            df_m = df_m.rename(columns={"value": "load_mw"})
                            all_results.append(df_m[["province", "year", "month", "day", "hour", "load_mw"]])
                    else:
                        df_out = df_sorted.copy()
                        df_out["province"] = province
                        df_out["year"]     = year
                        df_out["month"]    = m
                        df_out = df_out.rename(columns={"value": "load_mw"})
                        all_results.append(df_out[["province", "year", "month", "day", "hour", "load_mw"]])
                else:
                    prev_last_day_avg = None

    print("All files saved in Simulated_output_provincial_hourly_load folder")

    if all_results:
        combined = pd.concat(all_results, ignore_index=True)
        years_str = "_".join(str(y) for y in year_lst)
        combined_path = os.path.join(
            "Simulated_output_provincial_hourly_load",
            f"all_provinces_{years_str}_hourly_load.csv"
        )
        combined.to_csv(combined_path, index=False)
        print(f"Combined output saved: {combined_path}")



def main():
    abbrev_df = pd.read_csv('data/prov_vars.csv')
    province_lst = [p for p in abbrev_df['ProvinceName'].tolist() if p != 'China']
    month_lst = [1,2,3,4,5,6,7,8,9,10,11,12]
    year_lst = [2022]
    run_multi_optimizations(province_lst, month_lst, year_lst)
    
if __name__ == "__main__":
    main()