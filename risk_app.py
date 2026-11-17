import streamlit as st
import pandas as pd
from supabase import create_client, Client
import io

# 初始化Supabase客户端（这个缓存是对的，只初始化一次）
@st.cache_resource
def init_supabase():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase: Client = init_supabase()

# 修复点1：直接从数据库实时查询所有批次，不用旧DataFrame缓存
@st.cache_data(ttl=1)  # 缓存只保留1秒，几乎实时更新
def get_all_batches():
    response = supabase.table("raw_material_data").select("批次名称").execute()
    batches = list(set([row["批次名称"] for row in response.data]))
    return sorted(batches, reverse=True)

# 页面标题
st.title("🔍 原料风险对比工具")

# 上传区域
st.header("📤 上传新批次Excel")
uploaded_file = st.file_uploader("上传Excel文件（表头：批次名称,NPX Code,Material Code,原料名称,Risk）", type=["xlsx"])

if uploaded_file is not None:
    try:
        df = pd.read_excel(uploaded_file)
        # 处理Risk值：四舍五入为整数
        df["Risk"] = df["Risk"].round(0).astype(int)
        # 转成字典格式写入数据库
        data_to_insert = df.to_dict(orient="records")
        # 批量写入（按NPX Code+Material Code upsert，重复自动覆盖）
        supabase.table("raw_material_data").upsert(
            data_to_insert,
            on_conflict="NPX Code,Material Code"
        ).execute()
        st.success(f"✅ 上传成功！共写入 {len(data_to_insert)} 条数据")
        # 修复点2：上传成功后立即清空所有缓存，强制刷新批次列表
        st.cache_data.clear()
        st.rerun()  # 自动刷新页面，不用手动F5
    except Exception as e:
        st.error(f"❌ 上传失败：{str(e)}")

# 批次选择区域
st.header("📊 批次对比")
batches = get_all_batches()

if len(batches) == 0:
    st.warning("⚠️ 数据库暂无批次数据，请先上传Excel批次文件")
else:
    # 多选批次
    selected_batches = st.multiselect("选择要对比的批次", batches, default=[batches[0]])
    
    if len(selected_batches) > 0:
        # 查询选中批次的所有数据
        all_data = []
        for batch in selected_batches:
            res = supabase.table("raw_material_data").select("*").eq("批次名称", batch).execute()
            all_data.extend(res.data)
        df_result = pd.DataFrame(all_data)
        st.dataframe(df_result, use_container_width=True)
        
        # 导出按钮
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
