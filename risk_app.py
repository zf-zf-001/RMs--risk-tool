import streamlit as st
import pandas as pd
from supabase import create_client, Client
import io

# 初始化supabase，只执行一次
@st.cache_resource
def init_supabase():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase: Client = init_supabase()

# 每次实时查询全部批次，不做cache_data
def get_all_batches():
    res = supabase.table("raw_material_data").select("批次名称").execute()
    batches = sorted(list({row["批次名称"] for row in res.data}), reverse=True)
    return batches

st.title("🔍 原料风险对比工具")

# -------- 上传模块 --------
st.header("📤 上传新批次Excel")
uploaded_file = st.file_uploader("上传Excel（自动读取：批次名称,NPX Code,Material Code,原料名称,Risk_归一化）", type=["xlsx"])

if uploaded_file is not None:
    try:
        df = pd.read_excel(uploaded_file)
        required_cols = ["批次名称", "NPX Code", "Material Code", "原料名称", "Risk_归一化"]
        df = df[required_cols]
        df = df.rename(columns={"Risk_归一化":"Risk"})
        df = df.fillna("")
        df["Risk"] = df["Risk"].apply(lambda x: int(round(x)) if x != "" and not pd.isna(x) else None)

        current_batch = df["批次名称"].iloc[0]
        # 同一个批次：先全部删除旧数据，本次上传为最终版本
        supabase.table("raw_material_data").delete().eq("批次名称", current_batch).execute()
        data_to_insert = df.to_dict(orient="records")
        supabase.table("raw_material_data").insert(data_to_insert).execute()

        st.success(f"✅ 上传成功！批次「{current_batch}」共写入 {len(data_to_insert)} 条数据")
        st.cache_data.clear()
    except Exception as e:
        st.error(f"❌ 上传失败：{str(e)}")


# -------- 批次选择（Form表单，点按钮才生效，解决选完回弹） --------
st.header("📊 批次对比设置")
batches = get_all_batches()

if len(batches) == 0:
    st.warning("⚠️ 数据库暂无批次，请先上传Excel文件")
else:
    with st.form("batch_select_form"):
        # 单选：基准批次（只能选1个）
        base_batch = st.radio("✅选择【基准批次】", options=batches, key="base_batch_radio")
        # 多选：需要对比的批次，可以选多个
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

        # 导出全部选中批次数据
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
