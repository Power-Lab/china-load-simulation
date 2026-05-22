import pandas as pd
import numpy as np
import os


def province_filter(province_list):
    china_regions = {
        "河北省": "Hebei", "福建省": "Fujian", "甘肃省": "Gansu", "广东省": "Guangdong",
        "贵州省": "Guizhou", "海南省": "Hainan", "黑龙江省": "Heilongjiang",
        "河南省": "Henan", "湖北省": "Hubei", "湖南省": "Hunan", "江苏省": "Jiangsu",
        "江西省": "Jiangxi", "吉林省": "Jilin", "辽宁省": "Liaoning", "青海省": "Qinghai",
        "陕西省": "Shaanxi", "山东省": "Shandong", "山西省": "Shanxi", "四川省": "Sichuan",
        "云南省": "Yunnan", "浙江省": "Zhejiang", "安徽省": "Anhui",
        "广西壮族自治区": "Guangxi", "内蒙古自治区": "IMAR-", "宁夏回族自治区": "Ningxia",
        "西藏自治区": "Tibet", "新疆维吾尔自治区": "Xinjiang",
        "北京市": "Beijing", "重庆市": "Chongqing", "上海市": "Shanghai", "天津市": "Tianjin",
        "北京": "Beijing", "重庆": "Chongqing", "上海": "Shanghai", "天津": "Tianjin",
    }
    # normalise: strip trailing 市 so both forms resolve
    return {p: china_regions.get(p, china_regions.get(p.rstrip('市'), None))
            for p in province_list
            if china_regions.get(p) or china_regions.get(p.rstrip('市'))}

def prefecture_hourly(year, province_list=None, growth_rate=0.05):
    os.makedirs('Simulated_output_prefecture_hourly_load', exist_ok=True)

    df = pd.read_csv('data/2022_prefecture_data.csv')
    months = df.columns[2:]  # '2022-1' … '2022-12'

    if province_list is None:
        china_regions = {
            "河北省": "Hebei", "福建省": "Fujian", "甘肃省": "Gansu", "广东省": "Guangdong",
            "贵州省": "Guizhou", "海南省": "Hainan", "黑龙江省": "Heilongjiang",
            "河南省": "Henan", "湖北省": "Hubei", "湖南省": "Hunan", "江苏省": "Jiangsu",
            "江西省": "Jiangxi", "吉林省": "Jilin", "辽宁省": "Liaoning", "青海省": "Qinghai",
            "陕西省": "Shaanxi", "山东省": "Shandong", "山西省": "Shanxi", "四川省": "Sichuan",
            "云南省": "Yunnan", "浙江省": "Zhejiang", "安徽省": "Anhui",
            "广西壮族自治区": "Guangxi", "内蒙古自治区": "IMAR-", "宁夏回族自治区": "Ningxia",
            "西藏自治区": "Tibet", "新疆维吾尔自治区": "Xinjiang",
            "北京": "Beijing", "重庆": "Chongqing", "上海": "Shanghai", "天津": "Tianjin",
        }
    else:
        china_regions = province_filter(province_list)


    all_results = []

    for key, val in china_regions.items():

        # ── Hebei: split into Hebei-N and Hebei-S ──────────────────────────
        if key == "河北省":
            data = df[df['province'] == key]
            N_cities = ['唐山市', '张家口市', '秦皇岛市', '承德市', '廊坊市']
            S_cities = ['石家庄市', '邯郸市', '保定市', '沧州市', '邢台市', '衡水市']
            df_n = data[data['prefecture'].isin(N_cities)]
            df_s = data[data['prefecture'].isin(S_cities)]

            for month in months:
                m = int(month.split('-')[1])
                n_usage = float(df_n[month].sum())
                s_usage = float(df_s[month].sum())
                prov_n = pd.read_csv(
                    f'Simulated_output_provincial_hourly_load/Hebei-N_2022_{m}.csv')
                prov_s = pd.read_csv(
                    f'Simulated_output_provincial_hourly_load/Hebei-S_2022_{m}.csv')

                for _, row in df_n.iterrows():
                    prefecture = row['prefecture']
                    usage = float(data.loc[data['prefecture'] == prefecture, month].values[0])
                    res = prov_n[['day', 'hour']].copy()
                    res['load_mw'] = prov_n['value'] * (usage / n_usage)
                    res['province'] = 'Hebei-N'
                    res['prefecture'] = prefecture
                    res['year'] = 2022
                    res['month'] = m
                    all_results.append(
                        res[['province', 'prefecture', 'year', 'month', 'day', 'hour', 'load_mw']])

                for _, row in df_s.iterrows():
                    prefecture = row['prefecture']
                    usage = float(data.loc[data['prefecture'] == prefecture, month].values[0])
                    res = prov_s[['day', 'hour']].copy()
                    res['load_mw'] = prov_s['value'] * (usage / s_usage)
                    res['province'] = 'Hebei-S'
                    res['prefecture'] = prefecture
                    res['year'] = 2022
                    res['month'] = m
                    all_results.append(
                        res[['province', 'prefecture', 'year', 'month', 'day', 'hour', 'load_mw']])

        # ── Inner Mongolia: split into IMAR-E and IMAR-W ───────────────────
        elif key == "内蒙古自治区":
            data = df[df['province'] == key]
            E_cities = ['呼伦贝尔市', '兴安盟', '通辽市', '赤峰市']
            W_cities = ['呼和浩特市', '包头市', '乌海市', '鄂尔多斯市',
                        '巴彦淖尔市', '乌兰察布市', '锡林郭勒盟', '阿拉善盟']
            df_e = data[data['prefecture'].isin(E_cities)]
            df_w = data[data['prefecture'].isin(W_cities)]

            for month in months:
                m = int(month.split('-')[1])
                e_usage = float(df_e[month].sum())
                w_usage = float(df_w[month].sum())
                prov_e = pd.read_csv(
                    f'Simulated_output_provincial_hourly_load/IMAR-E_2022_{m}.csv')
                prov_w = pd.read_csv(
                    f'Simulated_output_provincial_hourly_load/IMAR-W_2022_{m}.csv')

                for _, row in df_e.iterrows():
                    prefecture = row['prefecture']
                    usage = float(data.loc[data['prefecture'] == prefecture, month].values[0])
                    res = prov_e[['day', 'hour']].copy()
                    res['load_mw'] = prov_e['value'] * (usage / e_usage)
                    res['province'] = 'IMAR-E'
                    res['prefecture'] = prefecture
                    res['year'] = 2022
                    res['month'] = m
                    all_results.append(
                        res[['province', 'prefecture', 'year', 'month', 'day', 'hour', 'load_mw']])

                for _, row in df_w.iterrows():
                    prefecture = row['prefecture']
                    usage = float(data.loc[data['prefecture'] == prefecture, month].values[0])
                    res = prov_w[['day', 'hour']].copy()
                    res['load_mw'] = prov_w['value'] * (usage / w_usage)
                    res['province'] = 'IMAR-W'
                    res['prefecture'] = prefecture
                    res['year'] = 2022
                    res['month'] = m
                    all_results.append(
                        res[['province', 'prefecture', 'year', 'month', 'day', 'hour', 'load_mw']])

        # ── All other provinces ────────────────────────────────────────────
        else:
            data = df[df['province'] == key].copy()
            total_row = data[data['prefecture'] == '全省']

            # Municipalities (Beijing/Shanghai/Tianjin/Chongqing) have no 全省
            # summary row — the single city row IS the whole province.
            if total_row.empty:
                non_total = data[data['prefecture'] != '全省']
                if non_total.empty:
                    print(f'[WARN] No data at all for {key}, skipping.')
                    continue
                # Use column sum of all prefectures as the province total
                use_sum_as_total = True
            else:
                use_sum_as_total = False

            for month in months:
                m = int(month.split('-')[1])
                if use_sum_as_total:
                    province_monthly_usage = float(
                        data[data['prefecture'] != '全省'][month].sum())
                else:
                    province_monthly_usage = float(total_row[month].values[0])
                province_level = pd.read_csv(
                    f'Simulated_output_provincial_hourly_load/{val}_2022_{m}.csv')

                for _, row in data.iterrows():
                    prefecture = row['prefecture']
                    if prefecture == '全省':
                        continue
                    usage = float(data.loc[data['prefecture'] == prefecture, month].values[0])
                    res = province_level[['day', 'hour']].copy()
                    res['load_mw'] = province_level['value'] * (usage / province_monthly_usage)
                    res['province'] = val
                    res['prefecture'] = prefecture
                    res['year'] = 2022
                    res['month'] = m
                    all_results.append(
                        res[['province', 'prefecture', 'year', 'month', 'day', 'hour', 'load_mw']])

        print(f'Done: {key}')

    if all_results:
        combined = pd.concat(all_results, ignore_index=True)
        out_path = (f'Simulated_output_prefecture_hourly_load/'
                    f'all_prefectures_{year}_hourly_load.csv')
        combined.to_csv(out_path, index=False)
        print(f'Saved: {out_path}  ({len(combined):,} rows)')

    return 'all files saved'


def main():
    prefecture_hourly(2022)

if __name__ == "__main__":
    main()