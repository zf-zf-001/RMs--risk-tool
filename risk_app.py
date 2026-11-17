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

@st.cache_data(ttl=1)
def get_all_batches():
    response = supabase.table("raw_material_data").select("批次名称").execute()
    batches = list(set([row["批次名称"] for row in response.data]))
    return sorted(batches, reverse=True)

st.title("🔍 原料风险对比工具")
st.header("📤 上传新批次Excel")
uploaded_file = st.file_uploader("上传Excel文件（自动识别：批次名称,NPX Code,Material Code,原料名称,Risk列）", type=["xlsx"])

if uploaded_file is not None:
    try:
        df = pd.read_excel(uploaded_file)
        # ✅ 核心修复：自动只提取需要的5列，忽略Excel里所有多余的列
        required_cols = ["批次名称", "NPX Code", "Material Code", "原料名称", "Risk"]
        df = df[required_cols]
        
        df = df.fillna("")
        df["Risk"] = df["Risk"].apply(lambda x: int(round(x)) if x != "" and not pd.isna(x) else x)
        
        current_batch = df["批次名称"].iloc[0]
        supabase.table("raw_material_data").delete().eq("批次名称", current_batch).execute()
        
        data_to_insert = df.to_dict(orient="records")
        supabase.table("raw_material_data").insert(data_to_insert).execute()
        
        st.success(f"✅ 上传成功！批次「{current_batch}」共写入 {len(data_to_insert)} 条数据")
        st.cache_data.clear()
        st.rerun()
    except Exception as e:
        st.error(f"❌ 上传失败：{str(e)}")

st.header("📊 批次对比")
batches = get_all_batches()

if len(batches) == 0:
    st.warning("⚠️ 数据库暂无批次数据，请先上传Excel批次文件")
else:
    selected_batches = st.multiselect("选择要对比的批次", batches, default=[batches[0]])
    if len(selected_batches) > 0:
        all_data = []
        for batch in selected_batches:
            res = supabase.table("raw_material_data").select("*").eq("批次名称", batch).execute()
            all_data.extend(res.data)
        df_result = pd.DataFrame(all_data)
        st.dataframe(df_result, use_container_width=True)
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_result.to_excel(writer, index=False, sheet_name="对比结果")
        output.seek(0)
        st.download_button(
            label="📥 导出对比结果Excel",
            data=output,
            file_name="风险对比结果.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
