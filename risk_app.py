import streamlit as st
import pandas as pd
from supabase import create_client, Client
import io
from openpyxl import Workbook
from openpyxl.utils.dataframe import dataframe_to_rows

@st.cache_resource
def init_supabase():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)
supabase = init_supabase()

def get_all_batches():
    res = supabase.table("raw_material_data").select("批次名称").execute()
    batch_set = set(str(r["批次名称"]).strip() for r in res.data)
    return sorted(list(batch_set), reverse=True)

def load_batch_data(batch_name):
    df = pd.DataFrame(supabase.table("raw_material_data").select("*").eq("批次名称", batch_name).execute().data)
    df["NPX Code"] = df["NPX Code"].astype(str).str.strip()
    df["Material Code"] = df["Material Code"].astype(str).str.strip()
    df["key_id"] = df["NPX Code"] + "|" + df["Material Code"]
    return df

def calc_risk_compare(df_base, df_compare):
    base_dict = dict(zip(df_base["key_id"], df_base["Risk"]))
    comp_dict = dict(zip(df_compare["key_id"], df_compare["Risk"]))
    all_keys = set(base_dict)|set(comp_dict)
    out = []
    for k in all_keys:
        rb = base_dict.get(k)
        rc = comp_dict.get(k)
        npx,mat = k.split("|")
        br = df_base[df_base["key_id"]==k].iloc[0] if k in base_dict else None
        cr = df_compare[df_compare["key_id"]==k].iloc[0] if k in comp_dict else None
        name = cr["原料名称"] if cr is not None else br["原料名称"]
        cat = cr["Category"] if cr is not None else br["Category"]
        status=""
        if rb is None and rc is not None: status="新增物料"
        elif rc is None and rb is not None: status="非活跃物料（对比批次消失）"
        else:
            bh = (rb>=3.5) if pd.notna(rb) else False
            ch = (rc>=3.5) if pd.notna(rc) else False
            if ch and not bh: status="风险升高（变为高风险）"
            elif not ch and bh: status="风险降低（退出高风险）"
            else: status="风险无变化"
        out.append({"NPX Code":npx,"Material Code":mat,"原料名称":name,"Category":cat,"基准Risk":rb,"对比Risk":rc,"状态":status})
    return pd.DataFrame(out)

def batch_summary(df,bn):
    df["Risk"]=pd.to_numeric(df["Risk"],errors="coerce")
    total=len(df)
    high=len(df[df["Risk"]>=3.5])
    usd=pd.to_numeric(df["Annual Value USD"],errors="coerce").sum()
    eur=pd.to_numeric(df["Annual Value EUR"],errors="coerce").sum()
    return pd.DataFrame([{"批次名称":bn,"物料总数":total,"高风险物料数(Risk≥3.5)":high,"Annual Value USD合计":usd,"Annual Value EUR合计":eur}])

st.title("🔍 原料风险对比工具")
st.header("📤 上传新批次Excel")
upload=st.file_uploader("表头：批次名称,NPX Code,Material Code,Category,Unicode,原料名称,Maker,BU Code,Risk,Annual Value USD,Annual Value EUR",type=["xlsx"])
if upload:
    try:
        df_raw=pd.read_excel(upload)
        must=["批次名称","NPX Code","Material Code","Category","Unicode","原料名称","Maker","BU Code","Risk","Annual Value USD","Annual Value EUR"]
        miss=[c for c in must if c not in df_raw.columns]
        if miss: st.error(f"缺少列：{','.join(miss)}");raise Exception("字段缺失")
        df=df_raw.copy()
        for c in ["批次名称","NPX Code","Material Code","Category","Unicode","原料名称","Maker","BU Code"]:
            df[c]=df[c].astype(str).str.strip()
        df["Risk"]=pd.to_numeric(df["Risk"],errors="coerce")
        df["Annual Value USD"]=pd.to_numeric(df["Annual Value USD"],errors="coerce")
        df["Annual Value EUR"]=pd.to_numeric(df["Annual Value EUR"],errors="coerce")
        bn=df["批次名称"].iloc[0]
        supabase.table("raw_material_data").delete().eq("批次名称",bn).execute()
        supabase.table("raw_material_data").insert(df.to_dict("records")).execute()
        st.success(f"✅上传成功，批次：{bn}，共{len(df)}条")
        st.cache_data.clear()
    except Exception as e:
        st.error(f"❌{str(e)}")

st.header("📊 批次对比设置")
batches=get_all_batches()
if len(batches)==0:
    st.warning("暂无批次，请先上传")
else:
    base=st.radio("✅基准批次",batches)
    candidates=[b for b in batches if b!=base]
    comps=st.multiselect("🔍待对比批次",candidates)
    if st.button("📌生成对比报告"):
        if not comps: st.warning("至少选一个对比批次")
        else:
            df_base=load_batch_data(base)
            sum_list=[batch_summary(df_base,base)]
            detail_list=[df_base]
            comp_list=[]
            for cb in comps:
                dc=load_batch_data(cb)
                sum_list.append(batch_summary(dc,cb))
                detail_list.append(dc)
                cr=calc_risk_compare(df_base,dc)
                cr.insert(0,"对比批次",cb)
                comp_list.append(cr)
            df_sum=pd.concat(sum_list,ignore_index=True)
            df_detail=pd.concat(detail_list,ignore_index=True)
            df_cr=pd.concat(comp_list,ignore_index=True)
            st.subheader("📋批次概览汇总")
            st.dataframe(df_sum,use_container_width=True)
            st.subheader("📈风险变化对比明细")
            st.dataframe(df_cr,use_container_width=True)
            out=io.BytesIO()
            wb=Workbook()
            ws1=wb.active;ws1.title="批次概览"
            for r in dataframe_to_rows(df_sum,index=False,header=True):ws1.append(r)
            ws2=wb.create_sheet("全部物料明细")
            for r in dataframe_to_rows(df_detail,index=False,header=True):ws2.append(r)
            ws3=wb.create_sheet("风险变化对比")
            for r in dataframe_to_rows(df_cr,index=False,header=True):ws3.append(r)
            wb.save(out);out.seek(0)
            st.download_button("📥导出Excel",out,f"风险对比报告_基准{base}.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
