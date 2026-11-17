import streamlit as st
import pandas as pd
from supabase import create_client, Client
import io

@st.cache_resource
def init_supabase():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase: Client = init_supabase()

def get_all_batches():
    res = supabase.table("raw_material_data").select("批次名称").execute()
    batches = sorted(list({row["批次名称"] for row in res.data}), reverse=True)
    return batches

st.title("🔍 原料风险对比工具")
st.header("📤 上传新批次Excel")
uploaded_file = st.file_uploader("上传Excel（自动识别风险列：Risk 或 Risk_归一化）", type=["xlsx"])

if uploaded_file is not None:
    try:
        df_raw = pd.read_excel(uploaded_file)
        all_cols = df_raw.columns.tolist()
        st.info(f"当前Excel表头：{all_cols}")

        # 优先找Risk_归一化，没有就用Risk
        if "Risk_归一化" in all_cols:
            risk_col = "Risk_归一化"
        elif "Risk" in all_cols:
            risk_col = "Risk"
        else:
            st.error("❌ Excel里面找不到【Risk】或者【Risk_归一化】风险列！")
            raise Exception("缺少风险列")

        required_cols = ["批次名称", "NPX Code", "Material Code", "原料名称", risk_col]
        df = df_raw[required_cols].copy()
        df = df.rename(columns={risk_col: "Risk"})

        df = df.fillna("")
        df["Risk"] = df["Risk"].apply(lambda x: int(round(x)) if x != "" and not pd.isna(x) else None)

        current_batch = df["批次名称"].iloc[0]
        # 同批次先删旧数据，本次为准
        supabase.table("raw_material_data").delete().eq("批次名称", current_batch).execute()
        data_to_insert = df.to_dict(orient="records")
        supabase.table("raw_material_data").insert(data_to_insert).execute()

        st.success(f"✅ 上传成功！批次「{current_batch}」共写入 {len(data_to_insert)} 条数据")
        st.cache_data.clear()
    except Exception as e:
        st.error(f"❌ 上传失败：{str(e)}")


st.header("📊 批次对比设置")
batches = get_all_batches()

if len(batches) == 0:
    st.warning("⚠️ 数据库暂无批次，请先上传Excel文件")
else:
    with st.form("batch_select_form"):
        base_batch = st.radio("✅选择【基准批次】", options=batches, key="base_batch_radio")
        compare_batches = st.multiselect("🔍选择【待对比批次】（可多选）",
                                         options=[b for b in batches if b != base_batch],
                                         key="compare_multi")
        apply_btn = st.form_submit_button("📌应用选择，加载对比数据")

    if apply_btn:
        selected_all = [base_batch] + compare_batches
        all_data = []
        for b in selected_all:
            r = supabase.table("raw_material_data").select("*").eq("批次名称", b).execute()
            all_data.extend(r.data)
        df_result = pd.DataFrame(all_data)
        st.info(f"基准批次：【{base_batch}】，对比批次：{compare_batches}")
        st.dataframe(df_result, use_container_width=True)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_result.to_excel(writer, index=False, sheet_name="对比结果")
        output.seek(0)
        st.download_button(
            label="📥导出对比结果Excel",
            data=output,
            file_name="风险对比结果.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
