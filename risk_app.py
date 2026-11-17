import io
import numpy as np
import pandas as pd
import streamlit as st

# 页面基本配置
st.set_page_config(
    page_title='物料风险动态比对与累计分析系统', page_icon='📊', layout='wide'
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

  # 外连接对齐主键
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

    # 优先取当前批次的辅助字段，没有则取上一批次
    category = (
        row.get('Category_curr')
        if pd.notna(row.get('Category_curr'))
        else row.get('Category_prev')
    )
    maker = (
        row.get('Maker_curr')
        if pd.notna(row.get('Maker_curr'))
        else row.get('Maker_prev')
    )

    change_type = None

    # 变化判定规则（严格按顺序执行）：
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
      continue  # 无变化，直接舍弃

    results.append({
        'Comparison_Task': f'{batch_name_prev} -> {batch_name_curr}',
        'Prev_Batch': batch_name_prev,
        'Curr_Batch': batch_name_curr,
        'NPX Code': npx,
        'Material Code': mat,
        'Category': category,
        'Maker': maker if pd.notna(maker) else 'Unassigned',
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


def generate_raw_material_totals(data_dict, baseline_batch):
  """生成 Sheet 1: 原材料 Total (Risk 0, 1-5, 9 的数量与金额汇总)"""
  rows = []
  for batch_name, df in data_dict.items():
    df_copy = df.copy()
    df_copy['NormRisk'] = df_copy['Risk'].apply(normalize_risk)

    # 确定分组依据（若有 Maker/Country 则用，否则用 Category 或总体）
    group_col = (
        'Maker'
        if 'Maker' in df_copy.columns and df_copy['Maker'].notna().sum() > 0
        else 'Category'
    )

    for group_val, grp in df_copy.groupby(group_col):
      # 统计 Risk 0, 1-5, 9 的合集
      sub_grp = grp[grp['NormRisk'].isin([0, 1, 2, 3, 4, 5, 8, 9])]
      cnt = len(sub_grp)
      val = sub_grp['Annual Value USD'].sum()

      rows.append({
          'Group_Dimension': group_val,
          'Baseline_or_Batch': batch_name,
          'Total_Material_Count': cnt,
          'Total_Value_USD': val,
      })

  return pd.DataFrame(rows)


def generate_raw_material_risk45(data_dict, baseline_batch):
  """生成 Sheet 2: 原材料 risk4&5 (只包含 Risk 4 和 5)"""
  rows = []
  for batch_name, df in data_dict.items():
    df_copy = df.copy()
    df_copy['NormRisk'] = df_copy['Risk'].apply(normalize_risk)

    group_col = (
        'Maker'
        if 'Maker' in df_copy.columns and df_copy['Maker'].notna().sum() > 0
        else 'Category'
    )

    for group_val, grp in df_copy.groupby(group_col):
      # 只包含 Risk 4 和 5
      sub_grp = grp[grp['NormRisk'].isin([4, 5])]
      cnt = len(sub_grp)
      val = sub_grp['Annual Value USD'].sum()

      rows.append({
          'Group_Dimension': group_val,
          'Baseline_or_Batch': batch_name,
          'Risk4_5_Material_Count': cnt,
          'Risk4_5_Value_USD': val,
      })

  return pd.DataFrame(rows)


# --- 界面主逻辑 ---
st.title('📊 物料风险动态比对与多维报表系统')
st.markdown(
    '上传多个批次数据，自动执行链式对比，并生成包含【明细数据】、【NPX矩阵汇总】、【原材料Total】以及【原材料Risk4&5】的多 Sheet 报表。'
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

          # 生成新增的两个 Sheet 数据
          total_sheet_df = generate_raw_material_totals(
              data_dict, baseline_batch
          )
          risk45_sheet_df = generate_raw_material_risk45(
              data_dict, baseline_batch
          )

          st.success(
              f'分析完成！累计产生变动明细记录共 {len(cumulative_diff_df)} 条。'
          )

          # 网页端展示选项卡
          tab1, tab2, tab3, tab4 = st.tabs([
              '📋 变动明细数据',
              '📊 NPX 矩阵汇总',
              '📦 原材料 Total',
              '🚨 原材料 Risk 4&5',
          ])

          with tab1:
            st.dataframe(cumulative_diff_df, use_container_width=True)
          with tab2:
            st.dataframe(summary_df, use_container_width=True)
          with tab3:
            st.markdown(
                '### 各国家/品类基准月及各月原材料总量与金额 (Risk 0, 1-5, 9)'
            )
            st.dataframe(total_sheet_df, use_container_width=True)
          with tab4:
            st.markdown('### 各国家/品类基准月及各月高风险总量与金额 (Risk 4 & 5)')
            st.dataframe(risk45_sheet_df, use_container_width=True)

          # 多 Sheet Excel 导出
          st.markdown('---')
          st.subheader('📥 导出包含多 Sheet 的完整分析报表')

          output = io.BytesIO()
          with pd.ExcelWriter(output, engine='openpyxl') as writer:
            cumulative_diff_df.to_excel(
                writer, sheet_name='累计变动明细', index=False
            )
            summary_df.to_excel(
                writer, sheet_name='NPX矩阵汇总', index=False
            )
            total_sheet_df.to_excel(
                writer, sheet_name='原材料Total', index=False
            )
            risk45_sheet_df.to_excel(
                writer, sheet_name='原材料risk4&5', index=False
            )
          excel_data = output.getvalue()

          st.download_button(
              label='下载完整累计多维报表 (.xlsx)',
              data=excel_data,
              file_name='multi_sheet_risk_analysis_report.xlsx',
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
