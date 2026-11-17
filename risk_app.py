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
  """为单批次生成原材料 Total 表格（纵列 NPX Code，列顺序：All RM -> Single Source -> Risk 0 -> Risk 1-5, 9 ...）"""
  df_c = df_batch.copy()
  df_c['NormRisk'] = df_c['Risk'].apply(normalize_risk)

  # 有效风险范围
  valid_risks = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 9.0]
  df_filtered = df_c[df_c['NormRisk'].isin(valid_risks)]

  pivot_count = df_filtered.pivot_table(
      index='NPX Code',
      columns='NormRisk',
      values='Material Code',
      aggfunc='count',
      fill_value=0,
  )
  pivot_value = df_filtered.pivot_table(
      index='NPX Code',
      columns='NormRisk',
      values='Annual Value USD',
      aggfunc='sum',
      fill_value=0,
  )

  # 计算 All RM 和 Single Source
  all_rm_count = pivot_count.sum(axis=1)
  all_rm_value = pivot_value.sum(axis=1)

  single_source_risks = [1.0, 2.0, 3.0, 4.0, 5.0]
  ss_count = pivot_count[
      [r for r in single_source_risks if r in pivot_count.columns]
  ].sum(axis=1)
  ss_value = pivot_value[
      [r for r in single_source_risks if r in pivot_value.columns]
  ].sum(axis=1)

  # 组装列（在 Risk0 前面加 All RM, Single Source）
  new_count_cols = pd.DataFrame(
      {'All_RM_Count': all_rm_count, 'Single_Source_Count': ss_count},
      index=pivot_count.index,
  )
  for r in [0, 1, 2, 3, 4, 5, 9]:
    if r in pivot_count.columns:
      new_count_cols[f'Risk{int(r)}_Count'] = pivot_count[r]
    else:
      new_count_cols[f'Risk{int(r)}_Count'] = 0

  new_value_cols = pd.DataFrame(
      {
          'All_RM_Value_USD': all_rm_value,
          'Single_Source_Value_USD': ss_value,
      },
      index=pivot_value.index,
  )
  for r in [0, 1, 2, 3, 4, 5, 9]:
    if r in pivot_value.columns:
      new_value_cols[f'Risk{int(r)}_Value_USD'] = pivot_value[r]
    else:
      new_value_cols[f'Risk{int(r)}_Value_USD'] = 0.0

  final_df = pd.concat([new_count_cols, new_value_cols], axis=1).reset_index()

  if not final_df.empty:
    numeric_cols = final_df.select_dtypes(include=[np.number]).columns
    total_vals = final_df[numeric_cols].sum(axis=0)
    total_row = pd.DataFrame([total_vals])
    total_row['NPX Code'] = 'TOTAL'
    final_df = pd.concat([final_df, total_row], ignore_index=True)

  return final_df


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
  """为单批次生成 Category 风险分布表（纵坐标 Category，横坐标含 All RM、Single Source 及 Risk 0~9）"""
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

  all_rm_count = pivot_count.sum(axis=1)
  all_rm_value = pivot_value.sum(axis=1)

  single_source_risks = [1.0, 2.0, 3.0, 4.0, 5.0]
  ss_count = pivot_count[
      [r for r in single_source_risks if r in pivot_count.columns]
  ].sum(axis=1)
  ss_value = pivot_value[
      [r for r in single_source_risks if r in pivot_value.columns]
  ].sum(axis=1)

  new_count_cols = pd.DataFrame(
      {'All_RM_Count': all_rm_count, 'Single_Source_Count': ss_count},
      index=pivot_count.index,
  )
  for r in [0, 1, 2, 3, 4, 5, 9]:
    if r in pivot_count.columns:
      new_count_cols[f'Risk{int(r)}_Count'] = pivot_count[r]
    else:
      new_count_cols[f'Risk{int(r)}_Count'] = 0

  new_value_cols = pd.DataFrame(
      {
          'All_RM_Value_USD': all_rm_value,
          'Single_Source_Value_USD': ss_value,
      },
      index=pivot_value.index,
  )
  for r in [0, 1, 2, 3, 4, 5, 9]:
    if r in pivot_value.columns:
      new_value_cols[f'Risk{int(r)}_Value_USD'] = pivot_value[r]
    else:
      new_value_cols[f'Risk{int(r)}_Value_USD'] = 0.0

  final_df = pd.concat([new_count_cols, new_value_cols], axis=1).reset_index()

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
    '上传多个批次数据，自动执行链式对比，并将报表按批次独立展示，所有相关 Sheet 表格均已在 Risk 0 前加入 All RM、在 Risk 1 前加入 Single Source。'
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
                '### 📦 原材料 Total 报表 (含 All RM 与 Single Source)'
            )
            for b_name, b_df in data_dict.items():
              st.markdown(f'#### 📌 批次: {b_name}')
              t_df = generate_single_batch_total_table(b_df)
              st.dataframe(t_df, use_container_width=True)

          with tab4:
            st.markdown('### 🚨 原材料 Risk 4&5 报表')
            for b_name, b_df in data_dict.items():
              st.markdown(f'#### 📌 批次: {b_name}')
              r_df = generate_single_batch_risk4
