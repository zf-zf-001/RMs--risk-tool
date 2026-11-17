import os
import numpy as np
import pandas as pd


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
  if risk == 3.5:
    return 4.0
  return float(risk)


def compare_two_batches(df_prev, df_curr, batch_name_curr):
  """执行两批次之间的链式对比

  参数:
      df_prev: 上一批次全量 DataFrame
      df_curr: 本批次全量 DataFrame
      batch_name_curr: 本批次名称标识
  """
  key_cols = ['NPX Code', 'Material Code']

  # 复制并标准化风险
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

    # 金额取物料出现最后一批的金额为主（本批次有则取本批次，否则取上批次）
    val_curr = row.get('Annual Value USD_curr', np.nan)
    val_prev = row.get('Annual Value USD_prev', np.nan)
    val = val_curr if pd.notna(val_curr) else val_prev

    # 获取原始Risk和Category信息
    orig_risk_prev = row.get('Risk_prev')
    orig_risk_curr = row.get('Risk_curr')
    category = (
        row.get('Category_curr')
        if pd.notna(row.get('Category_curr'))
        else row.get('Category_prev')
    )

    change_type = None

    # 变化判定规则（严格按顺序执行）：
    # 1. 上批次Risk=4或5，本批次变为Risk0 或 Risk 1-3， 或者 Risk=8 或Risk=9 → 降低
    if (
        pd.notna(r_p)
        and r_p in [4, 5]
        and pd.notna(r_c)
        and (r_c in [0, 1, 2, 3] or r_c in [8, 9])
    ):
      change_type = '降低'

    # 2. 上批次Risk=4或5，本批次该主键物料不存在 → 非活跃
    elif pd.notna(r_p) and r_p in [4, 5] and pd.isna(r_c):
      change_type = '非活跃'

    # 3. 上批次Risk为0/1/2/3/8/9，本批次Risk=4或5 → 升高
    elif (
        pd.notna(r_p)
        and r_p in [0, 1, 2, 3, 8, 9]
        and pd.notna(r_c)
        and r_c in [4, 5]
    ):
      change_type = '升高'

    # 4. 上批次不存在该主键物料，本批次出现，且本批次Risk=4或5 → 新增
    elif pd.isna(r_p) and pd.notna(r_c) and r_c in [4, 5]:
      change_type = '新增'

    # 7. 其余情况：无变化，直接舍弃，不输出
    else:
      continue

    results.append({
        'Batch_Target': batch_name_curr,
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
  """以 NPX Code 为维度进行数量与金额对比汇总"""
  if diff_df.empty:
    return pd.DataFrame()

  # 统计各变化类型的数量
  count_pivot = diff_df.pivot_table(
      index='NPX Code',
      columns='Change_Type',
      values='Material Code',
      aggfunc='count',
      fill_value=0,
  )

  # 统计各变化类型的金额
  value_pivot = diff_df.pivot_table(
      index='NPX Code',
      columns='Change_Type',
      values='Value',
      aggfunc='sum',
      fill_value=0,
  )

  # 重命名列以便区分
  count_pivot = count_pivot.add_suffix('_Count')
  value_pivot = value_pivot.add_suffix('_Value_USD')

  # 合并汇总表
  summary_df = pd.concat([count_pivot, value_pivot], axis=1).reset_index()
  return summary_df


# ==========================================
# 示例运行主程序 (可对接 GitHub CI/CD 或定时任务)
# ==========================================
if __name__ == '__main__':
  # 假设您每月将最新数据放入指定目录，例如 'data/'
  # 此处以您的 2025年12月（基线）和 2026年7月 数据为例：
  prev_file = '25年12月数据-密.xlsx'
  curr_file = '26年7月数据-密 .xlsx'

  if os.path.exists(prev_file) and os.path.exists(curr_file):
    print(f'正在读取上一批次: {prev_file}')
    df_prev = pd.read_excel(prev_file)
    df_prev.columns = [c.strip() for c in df_prev.columns]

    print(f'正在读取本批次: {curr_file}')
    df_curr = pd.read_excel(curr_file)
    df_curr.columns = [c.strip() for c in df_curr.columns]

    # 执行链式对比
    diff_results = compare_two_batches(df_prev, df_curr, batch_name_curr='2026.07')

    print(f'\n[明细结果] 过滤后变动物料总数: {len(diff_results)} 条')
    print(diff_results.head())

    # 按 NPX Code 汇总
    summary_results = aggregate_by_npx(diff_results)
    print('\n[汇总结果 - 以 NPX Code 维度]')
    print(summary_results.head())

    # 导出到 Excel / CSV 累计留存
    diff_results.to_excel('cumulative_diff_details.xlsx', index=False)
    summary_results.to_excel('cumulative_npx_summary.xlsx', index=False)
    print('\n结果已成功保存至 cumulative_diff_details.xlsx 与 cumulative_npx_summary.xlsx')
