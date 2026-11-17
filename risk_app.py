import io
import numpy as np
import pandas as pd
import streamlit as st

# 页面基本配置
st.set_page_config(
    page_title='物料风险动态比对与多维报表系统', page_icon='📊', layout='wide'
)


def normalize_risk(risk):
  """风险换算规则：

  Risk0 = 非单一货源
  Risk1, 2, 3 = 中低风险
  Risk3.5 = 等同 Risk4 (输出归为 4)
  Risk4, 5 = 高风险
  Risk8 = 排除在外
  Risk9 = 未被定义
  """
  if pd.isna(risk):
    return np.nan
  try:
    r = float(risk)
    if r == 3.5:
      return 4.0
    return r
  except:
    return np.nan


def compare_two_batches(df_prev, df_curr, batch_name_prev, batch_name_curr):
  """执行两批次之间的链式对比"""
  key_cols = ['NPX Code', 'Material Code']

  p = df_prev.copy()
  c = df_curr.copy()

  p['NormRisk'] = p['Risk'].apply(normalize_risk)
  c['NormRisk'] = c['Risk'].apply(normalize_risk)

  merged = pd.merge(p, c, on=key_cols, how='outer', suffixes=('_prev', '_curr'))

  results = []

  for _, row in merged.iterrows():
    npx = row['NPX Code']
    mat = row['Material Code']

    r_p = row['NormRisk_prev']
    r_c = row['NormRisk_curr']

    val_curr = row.get('Annual Value USD_curr', np.nan)
    val_prev = row.get('Annual Value USD_prev', np.nan)
    val = val_curr if pd.notna(val_curr) else val_prev

    orig_risk_prev = row.get('Risk_prev')
    orig_risk_curr = row.get('Risk_curr')
    category = (
        row.get('Category_curr')
        if pd.notna(row.get('Category_curr'))
        else row.get('Category_prev')
    )

    change_type = None

    if (
        pd.notna(r_p)
        and r_p in [4, 5]
        and pd.notna(r_c)
        and (r_c in [0, 1, 2, 3] or r_c in [8, 9])
    ):
      change_type = '降低'
    elif pd.notna(r_p) and r_p in [4, 5] and pd.isna(r_c):
      change_type = '非活跃'
    elif (
        pd.notna(r_p)
        and r_p in [0, 1, 2, 3, 8, 9]
        and pd.notna(r_c)
        and r_c in [4, 5]
    ):
      change_type = '升高'
    elif pd.isna(r_p) and pd.notna(r_c) and r_c in [4, 5]:
      change_type = '新增'
    else:
      continue

    results.append({
        'Comparison_Task': f'{batch_name_prev} -> {batch_name_curr}',
        'Prev_Batch': batch_name_prev,
        'Curr_Batch': batch_name_curr,
        'NPX Code': npx,
        'Material Code': mat,
        'Category': category,
        'Prev_Risk_Original': orig_risk_prev,
        'Curr_Risk_Original': orig_risk_curr,
        'Change_Type': change_type,
        'Value': val,
    })

  return pd.DataFrame(results)


def aggregate_by_npx(diff_df):
  """以 NPX Code 为维度进行矩阵汇总（含 Total 行）"""
  if diff_df.empty:
    return pd.DataFrame()

  count_pivot = diff_df.pivot_table(
      index='NPX Code',
      columns='Change_Type',
      values='Material Code',
      aggfunc='count',
      fill_value=0,
  )
  value_pivot = diff_df.pivot_table(
      index='NPX Code',
      columns='Change_Type',
      values='Value',
      aggfunc='sum',
      fill_value=0,
  )

  count_pivot = count_pivot.add_suffix('_Count')
  value_pivot = value_pivot.add_suffix('_Value_USD')

  summary_df = pd.concat([count_pivot, value_pivot], axis=1).reset_index()

  numeric_cols = summary_df.select_dtypes(include=[np.number]).columns
  total_values = summary_df[numeric_cols].sum(axis=0)
  total_row = pd.DataFrame([total_values])
  total_row['NPX Code'] = 'TOTAL'

  summary_df = pd.concat([summary_df, total_row], ignore_index=True)
  return summary_df


def generate_single_batch_total_table(df_batch):
  """为单批次生成原材料 Total 表格（纵列 NPX Code，含 All RMS 与 Single Source Total）"""
  df_c = df_batch.copy()
  df_c['NormRisk'] = df_c['Risk'].apply(normalize_risk)

  # 按 NPX Code 统计各 Risk 数量和金额
  r0 = (
      df_c[df_c['NormRisk'] == 0]
      .groupby('NPX Code')
      .agg(C=('Material Code', 'count'), V=('Annual Value USD', 'sum'))
  )
  r15 = (
      df_c[df_c['NormRisk'].isin([1, 2, 3, 4, 5])]
      .groupby('NPX Code')
      .agg(C=('Material Code', 'count'), V=('Annual Value USD', 'sum'))
  )
  r9 = (
      df_c[df_c['NormRisk'] == 9]
      .groupby('NPX Code')
      .agg(C=('Material Code', 'count'), V=('Annual Value USD', 'sum'))
  )

  # 单独统计每个具体 Risk 0~5 用于 Single Source Total
  risk_dict_c, risk_dict_v = {}, {}
  for r in [0, 1, 2, 3, 4, 5]:
    sub = (
        df_c[df_c['NormRisk'] == r]
        .groupby('NPX Code')
        .agg(C=('Material Code', 'count'), V=('Annual Value USD', 'sum'))
    )
    risk_dict_c[r] = sub['C']
    risk_dict_v[r] = sub['V']

  npx_codes = sorted(df_c['NPX Code'].dropna().unique())
  res_rows = []

  for npx in npx_codes:
    row = {'NPX Code': npx}
    # 各风险数量与金额
    c0 = r0.loc[npx, 'C'] if npx in r0.index else 0
    v0 = r0.loc[npx, 'V'] if npx in r0.index else 0.0
    c15 = r15.loc[npx, 'C'] if npx in r15.index else 0
    v15 = r15.loc[npx, 'V'] if npx in r15.index else 0.0
    c9 = r9.loc[npx, 'C'] if npx in r9.index else 0
    v9 = r9.loc[npx, 'V'] if npx in r9.index else 0.0

    row['Risk0_Count'] = c0
    row['Risk0_Value_USD'] = v0
    row['SingleSource_Count'] = c15
    row['SingleSource_Value_USD'] = v15
    row['Risk9_Count'] = c9
    row['Risk9_Value_USD'] = v9

    # All RMS = Risk 0 + single source (1-5) + risk 9
    row['All_RMS_Count'] = c0 + c15 + c9
    row['All_RMS_Value_USD'] = v0 + v15 + v9

    # Single Source Total = risk 0 + risk 1 + risk 2 + risk 3 + risk 4 + risk 5
    sum_c_ss, sum_v_ss = 0, 0.0
    for r in [0, 1, 2, 3, 4, 5]:
      val_c = risk_dict_c[r].get(npx, 0)
      val_v = risk_dict_v[r].get(npx, 0.0)
      sum_c_ss += val_c
      sum_v_ss += val_v
    row['Single_Source_Total_Count'] = sum_c_ss
    row['Single_Source_Total_Value_USD'] = sum_v_ss

    res_rows.append(row)

  res_df = pd.DataFrame(res_rows)
  if not res_df.empty:
    numeric_cols = res_df.select_dtypes(include=[np.number]).columns
    total_vals = res_df[numeric_cols].sum(axis=0)
    total_row = pd.DataFrame([total_vals])
    total_row['NPX Code'] = 'TOTAL'
    res_df = pd.concat([res_df, total_row], ignore_index=True)

  return res_df


def generate_single_batch_risk45_table(df_batch):
  """为单批次生成原材料 Risk 4&5 表格"""
  df_c = df_batch.copy()
  df_c['NormRisk'] = df_c['Risk'].apply(normalize_risk)

  r4 = (
      df_c[df_c['NormRisk'] == 4]
      .groupby('NPX Code')
      .agg(C=('Material Code', 'count'), V=('Annual Value USD', 'sum'))
  )
  r5 = (
      df_c[df_c['NormRisk'] == 5]
      .groupby('NPX Code')
      .agg(C=('Material Code', 'count'), V=('Annual Value USD', 'sum'))
  )

  npx_codes = sorted(df_c['NPX Code'].dropna().unique())
  res_rows = []

  for npx in npx_codes:
    c4 = r4.loc[npx, 'C'] if npx in r4.index else 0
    v4 = r4.loc[npx, 'V'] if npx in r4.index else 0.0
    c5 = r5.loc[npx, 'C'] if npx in r5.index else 0
    v5 = r5.loc[npx, 'V'] if npx in r5.index else 0.0

    res_rows.append({
        'NPX Code': npx,
        'Risk4_Count': c4,
        'Risk4_Value_USD': v4,
        'Risk5_Count': c5,
        'Risk5_Value_USD': v5,
        'Risk4_5_Total_Count': c4 + c5,
        'Risk4_5_Total_Value_USD': v4 + v5,
    })

  res_df = pd.DataFrame(res_rows)
  if not res_df.empty:
    numeric_cols = res_df.select_dtypes(include=[np.number]).columns
    total_vals = res_df[numeric_cols].sum(axis=0)
    total_row = pd.DataFrame([total_vals])
    total_row['NPX Code'] = 'TOTAL'
    res_df = pd.concat([res_df, total_row], ignore_index=True)

  return res_df


def generate_single_batch_category_risk_table(df_batch):
  """为单批次生成 Category 风险分布表（纵坐标 Category，横坐标 Risk 0,1,2,3,4,5,9）"""
  df_c = df_batch.copy()
  df_c['NormRisk'] = df_c['Risk'].apply(normalize_risk)
  valid_risks = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 9.0]
  df_filtered = df_c[df_c['NormRisk'].isin(valid_risks)]

  pivot_count = df_filtered.pivot_table(
      index='Category',
      columns='NormRisk',
      values='Material Code',
      aggfunc='count',
      fill_value=0,
  )
  pivot_value = df_filtered.pivot_table(
      index='Category',
      columns='NormRisk',
      values='Annual Value USD',
      aggfunc='sum',
      fill_value=0,
  )

  pivot_count.columns = [f'Risk{int(r)}_Count' for r in pivot_count.columns]
  pivot_value.columns = [f'Risk{int(r)}_Value_USD' for r in pivot_value.columns]

  final_df = pd.concat([pivot_count, pivot_value], axis=1).reset_index()

  if not final_df.empty:
    numeric_cols = final_df.select_dtypes(include=[np.number]).columns
    total_vals = final_df[numeric_cols].sum(axis=0)
    total_row = pd.DataFrame([total_vals])
    total_row['Category'] = 'TOTAL'
    final_df = pd.concat([final_df, total_row], ignore_index=True)

  return final_df


# --- 界面主逻辑 ---
st.title('📊 物料风险动态比对与多维报表系统')
st.markdown(
    '上传多个批次数据，自动执行链式对比，并将最后 3 个核心报表按批次拆分为独立表格展示，同时内置 All RMS 与 Single Source Total 计算。'
)

with st.sidebar:
  st.header('1. 上传数据文件')
  uploaded_files = st.file_uploader(
      '支持上传多个 Excel 文件 (.xlsx)', type=['xlsx', 'xls'], accept_multiple_files=True
  )

if uploaded_files:
  data_dict = {}
  for file in uploaded_files:
    try:
      df = pd.read_excel(file)
      df.columns = [str(c).strip() for c in df.columns]
      if '批次名称' in df.columns and not df['批次名称'].dropna().empty:
        batch_key = str(df['批次名称'].dropna().iloc[0])
      else:
        batch_key = file.name.split('.')[0]
      data_dict[batch_key] = df
    except Exception as e:
      st.error(f'读取文件 {file.name} 失败: {e}')

  if data_dict:
    sorted_batches = sorted(list(data_dict.keys()))

    st.sidebar.markdown('---')
    st.sidebar.header('2. 选择对比批次')

    baseline_batch = st.sidebar.selectbox(
        '选择基准批次 (Baseline)',
        sorted_batches,
        help='作为最起始对比的基准批次',
    )

    comparison_batches = st.sidebar.multiselect(
        '选择对比批次 (可多选)',
        [b for b in sorted_batches if b != baseline_batch],
        help='按选择顺序依次与上一批次进行链式对比',
    )

    if st.sidebar.button('开始执行对比分析', type='primary'):
      if not comparison_batches:
        st.warning('请至少选择一个对比批次！')
      else:
        all_diffs = []
        current_baseline_name = baseline_batch
        active_df = data_dict[baseline_batch]

        selected_comparisons = sorted(comparison_batches)

        progress_text = st.empty()
        for idx, next_batch_name in enumerate(selected_comparisons):
          progress_text.text(
              f'正在进行第 {idx+1} 阶段对比: {current_baseline_name} ➔'
              f' {next_batch_name} ...'
          )
          next_df = data_dict[next_batch_name]

          diff_res = compare_two_batches(
              active_df, next_df, current_baseline_name, next_batch_name
          )
          if not diff_res.empty:
            all_diffs.append(diff_res)

          active_df = next_df
          current_baseline_name = next_batch_name

        progress_text.empty()

        if all_diffs:
          cumulative_diff_df = pd.concat(all_diffs, ignore_index=True)
          summary_df = aggregate_by_npx(cumulative_diff_df)

          st.success(
              f'分析完成！累计产生变动明细记录共 {len(cumulative_diff_df)} 条。'
          )

          # 网页端展示选项卡
          tab1, tab2, tab3, tab4, tab5 = st.tabs([
              '📋 变动明细数据',
              '📊 NPX 变化矩阵',
              '📦 原材料 Total (分批次)',
              '🚨 原材料 Risk 4&5 (分批次)',
              '🏷️ Category 风险矩阵 (分批次)',
          ])

          with tab1:
            st.dataframe(cumulative_diff_df, use_container_width=True)
          with tab2:
            st.dataframe(summary_df, use_container_width=True)

          with tab3:
            st.markdown(
                '### 📦 原材料 Total 报表 (各批次独立展示，含 All RMS & Single'
                ' Source Total)'
            )
            for b_name, b_df in data_dict.items():
              st.markdown(f'#### 📌 批次: {b_name}')
              t_df = generate_single_batch_total_table(b_df)
              st.dataframe(t_df, use_container_width=True)

          with tab4:
            st.markdown(
                '### 🚨 原材料 Risk 4&5 报表 (各批次高风险独立展示)'
            )
            for b_name, b_df in data_dict.items():
              st.markdown(f'#### 📌 批次: {b_name}')
              r_df = generate_single_batch_risk45_table(b_df)
              st.dataframe(r_df, use_container_width=True)

          with tab5:
            st.markdown('### 🏷️ Category 风险分布矩阵 (各批次独立展示)')
            for b_name, b_df in data_dict.items():
              st.markdown(f'#### 📌 批次: {b_name}')
              c_df = generate_single_batch_category_risk_table(b_df)
              st.dataframe(c_df, use_container_width=True)

          # 多 Sheet & 多表格 Excel 导出
          st.markdown('---')
          st.subheader('📥 导出完整多维分析报表 (.xlsx)')

          output = io.BytesIO()
          with pd.ExcelWriter(output, engine='openpyxl') as writer:
            cumulative_diff_df.to_excel(
                writer, sheet_name='累计变动明细', index=False
            )
            summary_df.to_excel(
                writer, sheet_name='NPX矩阵汇总', index=False
            )

            # 针对最后3个 Sheet，把各个批次分区块写入同一个 Sheet 中
            writer_total_sheets = []
            for b_name, b_df in data_dict.items():
              t_df = generate_single_batch_total_table(b_df)
              writer_total_sheets.append(
                  pd.DataFrame([
                      {
                          t_df.columns[0]: f'=== 批次: {b_name} ===',
                          **{
                              col: ''
                              for col in t_df.columns[1:]
                          },
                      }
                  ])
              )
              writer_total_sheets.append(t_df)
              writer_total_sheets.append(
                  pd.DataFrame(
                      [
                          {
                              col: ''
                              for col in t_df.columns
                          }
                      ]
                  )
              )  # 空行
            pd.concat(writer_total_sheets, ignore_index=True).to_excel(
                writer, sheet_name='原材料Total', index=False
            )

            writer_risk_sheets = []
            for b_name, b_df in data_dict.items():
              r_df = generate_single_batch_risk45_table(b_df)
              writer_risk_sheets.append(
                  pd.DataFrame([
                      {
                          r_df.columns[0]: f'=== 批次: {b_name} ===',
                          **{
                              col: ''
                              for col in r_df.columns[1:]
                          },
                      }
                  ])
              )
              writer_risk_sheets.append(r_df)
              writer_risk_sheets.append(
                  pd.DataFrame(
                      [
                          {
                              col: ''
                              for col in r_df.columns
                          }
                      ]
                  )
              )
            pd.concat(writer_risk_sheets, ignore_index=True).to_excel(
                writer, sheet_name='原材料risk4&5', index=False
            )

            writer_cat_sheets = []
            for b_name, b_df in data_dict.items():
              c_df = generate_single_batch_category_risk_table(b_df)
              writer_cat_sheets.append(
                  pd.DataFrame([
                      {
                          c_df.columns[0]: f'=== 批次: {b_name} ===',
                          **{
                              col: ''
                              for col in c_df.columns[1:]
                          },
                      }
                  ])
              )
              writer_cat_sheets.append(c_df)
              writer_cat_sheets.append(
                  pd.DataFrame(
                      [
                          {
                              col: ''
                              for col in c_df.columns
                          }
                      ]
                  )
              )
            pd.concat(writer_cat_sheets, ignore_index=True).to_excel(
                writer, sheet_name='Category风险分布', index=False
            )

          excel_data = output.getvalue()

          st.download_button(
              label='下载分批次独立表格报表 (.xlsx)',
              data=excel_data,
              file_name='batch_split_risk_analysis_report.xlsx',
              mime=(
                  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
              ),
          )
        else:
          st.info(
              '在所选的批次对比区间内，未发现符合变化判定规则的物料变动。'
          )
else:
  st.info('请在左侧边栏上传您的多个批次 Excel 数据文件以开始使用。')
