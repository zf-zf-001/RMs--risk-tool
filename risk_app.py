import streamlit as st
import pandas as pd
from io import BytesIO
from supabase import create_client, Client

st.set_page_config(page_title="涂料原料单一货源风险对比工具", layout="wide")
st.title("涂料原材料单一货源风险数据分析")
st.markdown("主键：NPX Code + Material Code；Risk=3.5自动归一化为4；数据云端永久保存")

@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

sb = init_supabase()

def load_all_data():
    res = sb.table("raw_material_data").select("*").execute()
    df = pd.DataFrame(res.data)
    return df

st.subheader("📥 上传批次数据")
uploaded_file = st.file_uploader("上传Excel，表头：批次名称,NPX Code,Material Code,原料名称,Risk", type=["xlsx"])
if uploaded_file is not None:
    try:
        df_upload = pd.read_excel(uploaded_file)
        must_cols = ["批次名称", "NPX Code", "Material Code", "Risk"]
        for c in must_cols:
            if c not in df_upload.columns:
                st.error(f"缺少必填列：{c}")
                st.stop()
        for col in ["NPX Code", "Material Code"]:
            df_upload[col] = df_upload[col].astype(str).str.strip()
        df_upload["原料名称"] = df_upload["原料名称"].fillna("").astype(str).str.strip()
        df_upload["Risk"] = pd.to_numeric(df_upload["Risk"], errors="coerce")
        batch_name = df_upload["批次名称"].iloc[0]
        df_upload["key_id"] = df_upload["NPX Code"] + "|" + df_upload["Material Code"]
        df_upload["Risk_原始"] = df_upload["Risk"]
        df_upload["Risk_归一化"] = df_upload["Risk"].apply(lambda x: 4 if x == 3.5 else x)
        df_upload = df_upload.drop_duplicates(subset=["key_id"], keep="first")
        sb.table("raw_material_data").delete().eq("批次名称", batch_name).execute()
        insert_rows = df_upload[["批次名称","NPX Code","Material Code","原料名称","Risk_原始","Risk_归一化"]].to_dict("records")
        sb.table("raw_material_data").insert(insert_rows).execute()
        st.success(f"✅ 批次【{batch_name}】已经上传并保存到云端数据库！")
    except Exception as e:
        st.error(f"上传失败：{str(e)}")

all_df = load_all_data()
batch_list = sorted(all_df["批次名称"].unique().tolist()) if len(all_df) > 0 else []
if len(batch_list) == 0:
    st.info("数据库暂无批次数据，请先上传Excel批次文件")
    st.stop()
st.subheader("📋 已保存在云端的批次")
st.write(batch_list)

st.subheader("⚙️ 配置对比组")
st.markdown("可以添加多组对比，每组：基准批次 → 对比批次")
n_group = st.number_input("对比组数", min_value=1, max_value=10, value=1)
compare_groups = []
for i in range(n_group):
    col1, col2 = st.columns(2)
    with col1:
        base = st.selectbox(f"第{i+1}组 - 基准批次", batch_list, key=f"base_{i}")
    with col2:
        comp = st.selectbox(f"第{i+1}组 - 对比批次", batch_list, key=f"comp_{i}")
    if base != comp:
        compare_groups.append((base, comp))

def calc_diff(base_df, comp_df):
    base_dict = {}
    for _, row in base_df.iterrows():
        k = row["NPX Code"] + "|" + row["Material Code"]
        base_dict[k] = (row["Risk_原始"], row["Risk_归一化"], row["原料名称"])
    comp_dict = {}
    for _, row in comp_df.iterrows():
        k = row["NPX Code"] + "|" + row["Material Code"]
        comp_dict[k] = (row["Risk_原始"], row["Risk_归一化"], row["原料名称"])

    res = []
    all_keys = set(base_dict.keys()) | set(comp_dict.keys())
    S_high = {4,5}
    S_low = {0,1,2,3,8,9}

    for k in all_keys:
        in_base = k in base_dict
        in_comp = k in comp_dict
        npx, mat = k.split("|")
        if in_base:
            risk_old_raw, risk_old, name = base_dict[k]
        else:
            risk_old_raw, risk_old, name = None, None, comp_dict[k][2] if in_comp else ""
        if in_comp:
            risk_new_raw, risk_new, name = comp_dict[k]
        else:
            risk_new_raw, risk_new, name = None, None, base_dict[k][2] if in_base else ""

        change_type = None
        note = ""

        if in_base and not in_comp:
            if risk_old in S_high:
                change_type = "非活跃"
                note = "高风险原材料"
            else:
                continue
        elif not in_base and in_comp:
            if risk_new in S_high:
                change_type = "新增"
                note = "新增高风险原材料"
            else:
                continue
        else:
            if risk_old == risk_new:
                continue
            if risk_old in S_high and risk_new in S_low:
                change_type = "降低"
                note = "低风险原材料"
            elif risk_old ==5 and risk_new ==4:
                change_type = "降低"
                note = "高风险原材料"
            elif risk_old in S_low and risk_new in S_high:
                change_type = "升高"
                note = "转为高风险"
            elif risk_old ==4 and risk_new ==5:
                change_type = "升高"
                note = "升级至高风险"
            else:
                continue
        if change_type is not None:
            res.append({
                "NPX Code": npx,
                "Material Code": mat,
                "原料名称": name,
                "基准Risk(原始)": risk_old_raw,
                "基准Risk(归一化)": risk_old,
                "对比Risk(原始)": risk_new_raw,
                "对比Risk(归一化)": risk_new,
                "变化情况": change_type,
                "风险备注": note,
                "分析备注": ""
            })
    return pd.DataFrame(res)

if st.button("🚀 开始对比分析"):
    all_result_sheets = {}
    total_summary = {"新增":0, "升高":0, "降低":0, "非活跃":0}
    for base_batch, comp_batch in compare_groups:
        df_base = all_df[all_df["批次名称"] == base_batch].copy()
        df_comp = all_df[all_df["批次名称"] == comp_batch].copy()
        df_out = calc_diff(df_base, df_comp)
        sheet_name = f"{base_batch}_vs_{comp_batch}"
        all_result_sheets[sheet_name] = df_out
        st.subheader(f"【{base_batch}】 VS 【{comp_batch}】")
        st.dataframe(df_out, use_container_width=True)
        cnt = df_out["变化情况"].value_counts()
        st.write("本组统计：", cnt.to_dict())
        for k in ["新增","升高","降低","非活跃"]:
            if k in cnt:
                total_summary[k] += cnt[k]
    st.markdown("## 📊 全部对比汇总")
    st.write(total_summary)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        for s_name, df in all_result_sheets.items():
            df.to_excel(writer, sheet_name=s_name, index=False)
    output.seek(0)
    st.download_button(
        label="📥 下载全部对比结果Excel",
        data=output,
        file_name="原料风险对比结果.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

st.markdown("## 📎 上传空白模板")
template_df = pd.DataFrame(columns=["批次名称","NPX Code","Material Code","原料名称","Risk"])
buf = BytesIO()
template_df.to_excel(buf, index=False)
buf.seek(0)
st.download_button("下载空白上传模板", data=buf, file_name="原料风险上传模板.xlsx")
