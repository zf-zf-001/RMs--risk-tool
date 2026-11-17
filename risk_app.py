import streamlit as st
import pandas as pd
import numpy as np
from supabase import create_client, Client
import io

# ===================== 初始化数据库 =====================
@st.cache_resource
def init_supabase():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase: Client = init_supabase()

# 数据库表名
TABLE_NAME = "raw_material_data"

# ===================== 工具函数 =====================
def get_all_batches():
    """实时获取所有批次名称，自动清洗首尾空格"""
    res = supabase.table(TABLE_NAME).select("批次名称").execute()
    batch_set = set()
    for row in res.data:
        b = str(row["批次名称"]).strip()
        if b:
            batch_set.add(b)
    return sorted(list(batch_set), reverse=True)

def load_batch_data(batch_name):
    """加载指定批次的全部数据"""
    res = supabase.table(TABLE_NAME).select("*").eq("批次名称", batch_name).execute()
    df = pd.DataFrame(res.data)
    # 两键统一为字符串，去空格
    for col in ["NPX Code", "Material Code"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()
    return df

def is_high_risk(risk_val):
    """判定高风险：Risk >=3.5 即算高风险（等同4/5）"""
    try:
        r = float(risk_val)
        return r >= 3.5
    except:
        return False

# ===================== 页面标题 =====================
st.set_page_config(page_title="SSR单一货源风险对比工具", layout="wide")
st.title("🔍 SSR单一货源风险对比工具")

# ===================== 上传模块 =====================
st.header("📤 上传批次原始Excel")
uploaded_file = st.file_uploader(
    "上传原始明细Excel（自动识别列：批次/NPX Code/Material Code/原料名称/Risk/Annual Value USD）",
    type=["xlsx"]
)

if uploaded_file is not None:
    try:
        df_raw = pd.read_excel(uploaded_file)
        all_cols = df_raw.columns.tolist()
        st.info(f"✅ 识别到Excel列：{all_cols}")

        # 自动匹配需要的列（兼容不同命名）
        col_map = {}
        # 批次列
        for c in all_cols:
            if "批次" in c:
                col_map["批次名称"] = c
                break
        # NPX
        for c in all_cols:
            if "npx" in c.lower():
                col_map["NPX Code"] = c
                break
        # Material Code
        for c in all_cols:
            if "material" in c.lower() or "物料" in c:
                col_map["Material Code"] = c
                break
        # 原料名称
        for c in all_cols:
            if "原料" in c or "material name" in c.lower():
                col_map["原料名称"] = c
                break
        # Risk列
        risk_col = None
        for c in all_cols:
            if "risk" in c.lower():
                risk_col = c
                col_map["Risk"] = c
                break
        # 金额列
        money_col = None
        for c in all_cols:
            if "annual" in c.lower() or "usd" in c.lower() or "金额" in c:
                money_col = c
                col_map["Annual Value USD"] = c
                break

        # 检查必填列
        required = ["批次名称", "NPX Code", "Material Code", "Risk"]
        for req in required:
            if req not in col_map:
                st.error(f"❌ Excel缺少必要列：{req}，当前列：{all_cols}")
                raise Exception(f"缺少列{req}")

        # 提取并重命名列
        extract_cols = list(col_map.values())
        df = df_raw[extract_cols].copy()
        df.columns = list(col_map.keys())

        # 数据清洗
        df["批次名称"] = df["批次名称"].astype(str).str.strip()
        df["NPX Code"] = df["NPX Code"].astype(str).str.strip()
        df["Material Code"] = df["Material Code"].astype(str).str.strip()
        df["Risk"] = pd.to_numeric(df["Risk"], errors="coerce")
        if "Annual Value USD" in df.columns:
            df["Annual Value USD"] = pd.to_numeric(df["Annual Value USD"], errors="coerce").fillna(0)
        df = df.fillna("")

        current_batch = df["批次名称"].iloc[0]
        # 同批次覆盖：先删旧数据，再写新数据，以最后一次上传为准
        supabase.table(TABLE_NAME).delete().eq("批次名称", current_batch).execute()
        data_to_insert = df.to_dict(orient="records")
        supabase.table(TABLE_NAME).insert(data_to_insert).execute()

        st.success(f"✅ 上传成功！批次「{current_batch}」共写入 {len(data_to_insert)} 条明细数据")
    except Exception as e:
        st.error(f"❌ 上传失败：{str(e)}")

# ===================== 对比分析模块 =====================
st.header("📊 多批次风险对比分析")
batches = get_all_batches()

if len(batches) == 0:
    st.warning("⚠️ 数据库暂无批次数据，请先上传Excel明细文件")
else:
    # 选择基准批次
    base_batch = st.radio("✅ 选择【基准批次】", options=batches, horizontal=True)
    # 选择要对比的批次
    compare_batches = st.multiselect(
        "🔍 选择【待对比批次】（可多选）",
        options=[b for b in batches if b != base_batch]
    )

    if st.button("📌 生成对比分析报告", type="primary"):
        # 加载所有选中批次的数据
        all_batches_data = {}
        all_batches_data[base_batch] = load_batch_data(base_batch)
        for b in compare_batches:
            all_batches_data[b] = load_batch_data(b)

        # ========== Sheet1: 各批次概览 ==========
        st.subheader("一、各批次概览")
        overview_rows = []
        for b_name, df_b in all_batches_data.items():
            total = len(df_b)
            high_risk_cnt = df_b["Risk"].apply(is_high_risk).sum()
            total_money = df_b["Annual Value USD"].sum() if "Annual Value USD" in df_b.columns else 0
            high_risk_money = df_b[df_b["Risk"].apply(is_high_risk)]["Annual Value USD"].sum() if "Annual Value USD" in df_b.columns else 0
            overview_rows.append({
                "批次": b_name,
                "总记录数": total,
                "高风险记录数": high_risk_cnt,
                "高风险占比": f"{high_risk_cnt/total*100:.1f}%" if total>0 else "0%",
                "总金额(USD)": round(total_money,2),
                "高风险金额(USD)": round(high_risk_money,2)
            })
        df_overview = pd.DataFrame(overview_rows)
        st.dataframe(df_overview, use_container_width=True)

        # ========== Sheet2: 基线vs对比批次变化统计 ==========
        st.subheader("二、批次间风险变化对比")
        df_base = all_batches_data[base_batch].copy()
        # 构造两键：NPX Code + Material Code 匹配同一物料
        def make_key(row):
            return f"{row['NPX Code']}|{row['Material Code']}"
        df_base["key"] = df_base.apply(make_key, axis=1)
        base_map = {r["key"]: r["Risk"] for _, r in df_base.iterrows()}

        change_rows = []
        for cmp_batch in compare_batches:
            df_cmp = all_batches_data[cmp_batch].copy()
            df_cmp["key"] = df_cmp.apply(make_key, axis=1)
            cmp_map = {r["key"]: r["Risk"] for _, r in df_cmp.iterrows()}

            up_cnt = 0  # 风险升高
            new_cnt = 0 # 新增
            down_cnt = 0 # 风险降低
            inactive_cnt = 0 # 非活跃（消失）

            for key, cmp_risk in cmp_map.items():
                if key not in base_map:
                    new_cnt +=1
                else:
                    base_risk = base_map[key]
                    if float(cmp_risk) > float(base_risk):
                        up_cnt +=1
                    elif float(cmp_risk) < float(base_risk):
                        down_cnt +=1
            for key in base_map:
                if key not in cmp_map:
                    inactive_cnt +=1

            change_rows.append({
                "对比区间": f"{base_batch} → {cmp_batch}",
                "风险升高": up_cnt,
                "新增物料": new_cnt,
                "风险降低": down_cnt,
                "非活跃物料": inactive_cnt,
                "总变化": up_cnt + new_cnt + down_cnt + inactive_cnt
            })
        df_change = pd.DataFrame(change_rows)
        st.dataframe(df_change, use_container_width=True)

        # ========== 导出完整Excel ==========
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_overview.to_excel(writer, index=False, sheet_name="批次概览")
            df_change.to_excel(writer, index=False, sheet_name="变化统计")
            # 导出所有明细
            for b_name, df_b in all_batches_data.items():
                df_b.to_excel(writer, index=False, sheet_name=f"明细_{b_name}")
        output.seek(0)
        st.download_button(
            label="📥 下载完整对比报告Excel",
            data=output,
            file_name=f"风险对比报告_{base_batch}_vs_{'_'.join(compare_batches)}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
