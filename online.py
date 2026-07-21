import streamlit as st
import pandas as pd
import datetime
import re
import requests
import json
from PIL import Image
import io
from google.oauth2.service_account import Credentials
import gspread

# ========================================
# ⚙️ ตั้งค่าฐานข้อมูล 
# ========================================
SHEET_ID = "1lq3iFPLdzi17xNr8-qHi7azX5ImIUnvD7z9ITvMkAek"
UPLOAD_URL = "https://claims.offfitz.com/upload.php"

# 🔒 ดึงรหัสผ่านจากตู้เซฟ Streamlit Secrets
APP_PASSWORD = st.secrets.get("app_password", "1234")

st.set_page_config(page_title="ระบบจัดการเคลมสินค้า - Off Fitz", layout="wide" if "logged_in" in st.session_state and st.session_state.logged_in else "centered", page_icon="📦")

# ========================================
# 🔒 ระบบล็อกอิน (และลิงก์วิเศษ)
# ========================================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

# 🌟 เช็กลิงก์วิเศษ: ถ้า URL มี ?login=รหัสผ่าน ให้เข้าสู่ระบบทันที
if "login" in st.query_params:
    if st.query_params["login"] == str(APP_PASSWORD):
        st.session_state.logged_in = True

if not st.session_state.logged_in:
    st.title("🔒 กรุณาเข้าสู่ระบบ")
    st.write("ระบบจัดการเคลมสินค้า Off Fitz (เฉพาะพนักงาน)")
    pwd_input = st.text_input("รหัสผ่านร้าน", type="password")
    
    if st.button("เข้าสู่ระบบ"):
        if pwd_input == str(APP_PASSWORD):
            st.session_state.logged_in = True
            st.rerun()
        else:
            st.error("❌ รหัสผ่านไม่ถูกต้อง!")
    st.stop()

if "form_key" not in st.session_state:
    st.session_state.form_key = 0
if "success_msg" not in st.session_state:
    st.session_state.success_msg = ""

# --- ฟังก์ชันเชื่อมต่อ Google Sheets (อัปเกรดหมัดน็อค: strict=False) ---
@st.cache_resource
def connect_google():
    clean = ""
    try:
        scopes = ['https://www.googleapis.com/auth/spreadsheets']
        raw_secret = st.secrets["google_secret"]
        
        if isinstance(raw_secret, str):
            # 1. เปลี่ยน Quote แปลกๆ ให้เป็น Quote มาตรฐาน
            clean = re.sub(r"[‘’'“”]", '"', raw_secret)
            
            # 2. สับปีกกาที่ซ้อนกัน และช่องว่างล่องหน ด้านหน้าและด้านหลังสุดทิ้ง
            clean = re.sub(r'^[\s\{]+', '{', clean)
            clean = re.sub(r'[\s\}]+$', '}', clean)
            
            # 🧨 หมัดน็อค: strict=False สั่งให้ Python อนุโลมการขึ้นบรรทัดใหม่ที่ผิดกฎ
            secret_dict = json.loads(clean, strict=False)
        else:
            secret_dict = raw_secret
            
        # 3. จัดการบรรทัด private_key ให้กลับมาเป็น \n ที่ถูกต้อง เพื่อส่งให้ Google
        if "private_key" in secret_dict:
            secret_dict["private_key"] = secret_dict["private_key"].replace('\\n', '\n')
            
        creds = Credentials.from_service_account_info(secret_dict, scopes=scopes)
        gc = gspread.authorize(creds)
        sheet = gc.open_by_key(SHEET_ID).sheet1
        return sheet
    except Exception as e:
        st.error(f"🚨 ข้อผิดพลาดการเชื่อมต่อ: {e}")
        st.code(f"🔍 ข้อมูลหลังโดนซ่อมแล้ว: \n{clean[:80]}...", language="json")
        return None

# ========================================
# 🧭 ระบบเมนูสลับหน้า 
# ========================================
st.sidebar.title("📌 เมนูหลัก")
menu_choice = st.sidebar.radio("เลือกรายการที่ต้องการ:", ["📝 บันทึกเคลมใหม่", "🔍 ค้นหาและดูประวัติ"], index=0)

st.sidebar.write("---")
st.sidebar.subheader("📱 ให้ลูกน้องเข้าใช้งานด่วน")
st.sidebar.info(f"เอา URL ปัจจุบันของเว็บนี้ แล้วพิมพ์ **?login={APP_PASSWORD}** ต่อท้าย ส่งให้พนักงานเปิดแล้วกด Add to Home Screen ได้เลยครับ!")

st.sidebar.write("---")
if st.sidebar.button("🚪 ออกจากระบบ (Logout)"):
    st.session_state.logged_in = False
    st.query_params.clear() 
    st.rerun()
st.sidebar.caption("Off Fitz Claim Management System v3.0")

# ========================================
# 📝 หน้าที่ 1: บันทึกเคลมใหม่
# ========================================
if menu_choice == "📝 บันทึกเคลมใหม่":
    st.title("📦 ระบบประเมินและบันทึกเคลมสินค้า")

    if st.session_state.success_msg:
        st.success(st.session_state.success_msg)
        st.session_state.success_msg = ""
    
    fk = st.session_state.form_key

    st.subheader("1. ข้อมูลพื้นฐาน")
    platform = st.selectbox("ช่องทางการขาย", ["Shopee", "Lazada", "TikTok", "ขายเอง (Social/Line)"], key=f"plat_{fk}")

    col_id, col_sku = st.columns(2)
    with col_id:
        order_id = st.text_input("Order ID (รหัสคำสั่งซื้อ)", key=f"oid_{fk}")
    with col_sku:
        sku = st.text_input("รหัส SKU", key=f"sku_{fk}")

    product_name = st.text_input("ชื่อสินค้า", key=f"pname_{fk}")
    claim_details = st.text_area("รายละเอียดการเคลม", key=f"cdet_{fk}")

    defect_images = st.file_uploader("อัปโหลดรูปภาพ (บีบอัดให้อัตโนมัติ)", type=["jpg", "png", "jpeg"], accept_multiple_files=True, key=f"img_{fk}")
    st.write("---")

    st.subheader("2. ข้อมูลการเงิน")
    col1, col2 = st.columns(2)
    with col1:
        income = st.number_input("ราคาขายตั้งต้น", min_value=0.0, step=10.0, key=f"inc_{fk}")
        customer_paid = st.number_input("ยอดที่ลูกค้าจ่ายจริง", min_value=0.0, step=10.0, key=f"cp_{fk}")
    with col2:
        actual_received = st.number_input("เงินที่เราได้รับจริง", min_value=0.0, step=10.0, key=f"ar_{fk}")
        cost = st.number_input("ต้นทุนรวม (รวมค่าแพ็กเกจจิ้งแล้ว)", min_value=0.0, step=10.0, key=f"cost_{fk}")

    shipping_cost = st.number_input("🚚 ประเมินค่าจัดส่ง (เปลี่ยนของใหม่)", min_value=0.0, step=10.0, key=f"sc_{fk}")
    actual_profit = actual_received - cost
    st.write("---")

    st.subheader("3. กำหนดตัวเลือกชดเชย")
    discount_type = st.radio("รูปแบบการชดเชย", ["เปอร์เซ็นต์ (%)", "จำนวนเงิน (บาท)"], horizontal=True, key=f"dt_{fk}")

    base_price = income 
    if discount_type == "เปอร์เซ็นต์ (%)":
        base_price_option = st.selectbox("เลือกราคาฐานสำหรับคิด %", ["ราคาขายตั้งต้น", "ยอดที่ลูกค้าจ่ายจริง", "ระบุตัวเลขเอง"], key=f"bpo_{fk}")
        if base_price_option == "ยอดที่ลูกค้าจ่ายจริง":
            base_price = customer_paid
        elif base_price_option == "ระบุตัวเลขเอง":
            base_price = st.number_input("ระบุราคาฐานที่ต้องการ (บาท)", min_value=0.0, step=10.0, key=f"bpc_{fk}")

    col_start, col_step = st.columns(2)
    with col_start:
        start_val = st.number_input(f"เริ่มที่ ({'%' if discount_type == 'เปอร์เซ็นต์ (%)' else 'บาท'})", min_value=0, value=5 if discount_type == "เปอร์เซ็นต์ (%)" else 20, step=5, key=f"start_{fk}")
    with col_step:
        step_val = st.number_input("เพิ่มขึ้นสเต็ปละ", min_value=1, value=5 if discount_type == "เปอร์เซ็นต์ (%)" else 10, step=5, key=f"step_{fk}")

    discount_options = []
    for i in range(4):
        current_val = start_val + (i * step_val)
        if discount_type == "เปอร์เซ็นต์ (%)":
            discount_amt = (base_price * current_val) / 100
            label_text = f"ลด {current_val}%"
        else:
            discount_amt = current_val
            label_text = f"จ่าย {current_val} ฿"
        
        profit_left = actual_profit - discount_amt
        discount_options.append({
            "ตัวเลือก": label_text,
            "ยอดชดเชย (บาท)": discount_amt,
            "กำไรที่เหลือ (บาท)": profit_left
        })
    st.write("---")

    st.subheader("📸 4. สรุปขออนุมัติ (สำหรับ Copy ส่งแชท)")
    if actual_profit > 0:
        st.success(f"✅ เงินที่เหลือจริงๆ (กำไรสุทธิ): {actual_profit:,.2f} บาท")
    else:
        st.error(f"⚠️ เงินที่เหลือจริงๆ (กำไรสุทธิ): {actual_profit:,.2f} บาท (ขาดทุน)")

    df_display = pd.DataFrame(discount_options)
    df_display["ยอดชดเชย (บาท)"] = df_display["ยอดชดเชย (บาท)"].apply(lambda x: f"{x:,.2f}")
    df_display["กำไรที่เหลือ (บาท)"] = df_display["กำไรที่เหลือ (บาท)"].apply(lambda x: f"{x:,.2f}")
    st.table(df_display)

    base_info_text = f"- อิงจากราคาฐาน: {base_price:,.2f} ฿" if discount_type == "เปอร์เซ็นต์ (%)" else "- รูปแบบ: ชดเชยเป็นเงินบาทตรงๆ"
    summary_text = f"""📌 ขออนุมัติเคลม ({platform})
- Order ID: {order_id if order_id else '-'}
- SKU: {sku if sku else '-'}
- สินค้า: {product_name if product_name else '-'}
- อาการ: {claim_details if claim_details else '-'}
---
📊 ข้อมูลการเงิน:
{base_info_text}
- กำไรที่เหลืออยู่: {actual_profit:,.2f} ฿
- 🚚 ค่าจัดส่ง (กรณีเปลี่ยนของ): {shipping_cost:,.2f} ฿
---
💸 ทางเลือกชดเชย:
• {discount_options[0]['ตัวเลือก']} = ชดเชย {discount_options[0]['ยอดชดเชย (บาท)']:,.2f} ฿ (เหลือกำไร {discount_options[0]['กำไรที่เหลือ (บาท)']:,.2f} ฿)
• {discount_options[1]['ตัวเลือก']} = ชดเชย {discount_options[1]['ยอดชดเชย (บาท)']:,.2f} ฿ (เหลือกำไร {discount_options[1]['กำไรที่เหลือ (บาท)']:,.2f} ฿)
• {discount_options[2]['ตัวเลือก']} = ชดเชย {discount_options[2]['ยอดชดเชย (บาท)']:,.2f} ฿ (เหลือกำไร {discount_options[2]['กำไรที่เหลือ (บาท)']:,.2f} ฿)
• {discount_options[3]['ตัวเลือก']} = ชดเชย {discount_options[3]['ยอดชดเชย (บาท)']:,.2f} ฿ (เหลือกำไร {discount_options[3]['กำไรที่เหลือ (บาท)']:,.2f} ฿)"""
    st.code(summary_text, language="markdown")
    st.write("---")

    st.subheader("💾 5. สรุปยอดและบันทึกฐานข้อมูล")
    approval_choices = [f"{opt['ตัวเลือก']} (ยอดชดเชย: {opt['ยอดชดเชย (บาท)']:,.2f} บาท)" for opt in discount_options]
    approval_choices.append("กรอกตัวเลขเอง (ระบุยอดอื่น)")
    approval_choices.append(f"ส่งของใหม่ไปเปลี่ยน (ค่าส่ง {shipping_cost:,.2f} บาท)")

    selected_approval = st.selectbox("เลือกยอดเงินที่อนุมัติชดเชยจริง", approval_choices, key=f"appr_{fk}")

    if selected_approval == "กรอกตัวเลขเอง (ระบุยอดอื่น)":
        final_compensation = st.number_input("ระบุยอดเงินชดเชย (บาท)", min_value=0.0, step=10.0, key=f"fcc_{fk}")
    elif selected_approval == f"ส่งของใหม่ไปเปลี่ยน (ค่าส่ง {shipping_cost:,.2f} บาท)":
        final_compensation = shipping_cost
        st.info(f"บันทึกเป็นเคสส่งของเปลี่ยน: **ต้นทุนค่าส่ง {final_compensation:,.2f} บาท**")
    else:
        selected_index = approval_choices.index(selected_approval)
        final_compensation = discount_options[selected_index]['ยอดชดเชย (บาท)']
        st.info(f"ยอดชดเชยที่เลือกลงระบบ: **{final_compensation:,.2f} บาท**")

    if st.button("บันทึกเข้าระบบ", use_container_width=True):
        if not order_id:
            st.warning("กรุณากรอก Order ID ก่อนบันทึกข้อมูลครับ")
        else:
            with st.spinner('กำลังบีบอัดรูปภาพและบันทึกข้อมูล...'):
                sheet = connect_google()
                if sheet is None:
                    st.error("❌ เชื่อมต่อ Google Sheets ไม่สำเร็จ (เช็ก Error ด้านบน)")
                else:
                    try:
                        image_links = []
                        if defect_images:
                            for img_file in defect_images:
                                img = Image.open(img_file)
                                if img.mode in ("RGBA", "P"): 
                                    img = img.convert("RGB")
                                
                                max_width = 600
                                if img.width > max_width:
                                    ratio = max_width / img.width
                                    new_height = int(img.height * ratio)
                                    img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
                                
                                img_byte_arr = io.BytesIO()
                                img.save(img_byte_arr, format='JPEG', quality=40)
                                img_byte_arr.seek(0)
                                
                                file_name_clean = re.sub(r'[^a-zA-Z0-9.\-_]', '', img_file.name)
                                safe_name = f"{order_id}_{file_name_clean}.jpg"
                                
                                files = {'file': (safe_name, img_byte_arr, 'image/jpeg')}
                                response = requests.post(UPLOAD_URL, files=files)
                                
                                result = response.json()
                                if result.get("status") == "success":
                                    image_links.append(result.get("url"))
                                else:
                                    st.error(f"⚠️ บันทึกรูป {img_file.name} ไม่สำเร็จ: {result.get('message')}")
                        
                        final_image_links = ", ".join(image_links) if image_links else "-"
                        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        row_data = [
                            current_time, platform, order_id, sku, product_name, claim_details,
                            income, customer_paid, actual_received, cost, actual_profit, 
                            final_compensation, final_image_links
                        ]

                        sheet.append_row(row_data)
                        st.session_state.success_msg = f"✅ บันทึกข้อมูล Order: {order_id} เรียบร้อยแล้ว!"
                        st.session_state.form_key += 1 
                        st.rerun() 
                    except Exception as e:
                        st.error(f"❌ เกิดข้อผิดพลาดระหว่างบันทึก: {e}")

# ========================================
# 🔍 หน้าที่ 2: ค้นหาและดูประวัติ
# ========================================
elif menu_choice == "🔍 ค้นหาและดูประวัติ":
    st.title("🔍 ค้นหาและดูประวัติการเคลม")
    
    col_refresh, _ = st.columns([1, 3])
    with col_refresh:
        if st.button("🔄 รีเฟรชข้อมูลล่าสุด"):
            st.rerun()

    sheet = connect_google()
    if sheet is None:
        st.error("❌ ไม่สามารถดึงข้อมูลจาก Google Sheets ได้ (เช็ก Error ด้านบน)")
    else:
        data = sheet.get_all_values()
        
        if len(data) <= 1:
            st.info("📌 ยังไม่มีประวัติการบันทึกข้อมูลเคลมในระบบ")
        else:
            headers = ["วัน-เวลา", "Platform", "Order ID", "SKU", "ชื่อสินค้า", "อาการเคลม", 
                       "ราคาตั้งต้น", "ยอดลูกค้าจ่าย", "เงินที่ได้รับ", "ต้นทุน", "กำไรตั้งต้น", 
                       "ยอดชดเชยจริง", "รูปภาพ"]
            
            df = pd.DataFrame(data[1:], columns=headers if len(data[0]) == 13 else None)
            
            col_search, col_filter = st.columns([2, 1])
            with col_search:
                search_kw = st.text_input("🔎 พิมพ์ค้นหา (Order ID / SKU / ชื่อสินค้า)", placeholder="เช่น ORD12345...")
            with col_filter:
                filter_platform = st.selectbox("กรองตาม Platform", ["ทั้งหมด", "Shopee", "Lazada", "TikTok", "ขายเอง (Social/Line)"])

            filtered_df = df.copy()
            if filter_platform != "ทั้งหมด":
                filtered_df = filtered_df[filtered_df["Platform"] == filter_platform]
                
            if search_kw:
                kw = search_kw.strip().lower()
                filtered_df = filtered_df[
                    filtered_df["Order ID"].str.lower().str.contains(kw) |
                    filtered_df["SKU"].str.lower().str.contains(kw) |
                    filtered_df["ชื่อสินค้า"].str.lower().str.contains(kw)
                ]

            st.write(f"📊 พบทั้งหมด **{len(filtered_df)}** รายการ")
            st.write("---")

            for idx, row in filtered_df.iloc[::-1].iterrows(): 
                with st.expander(f"📦 Order: {row['Order ID']} | {row['Platform']} | ยอดชดเชย: {row['ยอดชดเชยจริง']} ฿"):
                    st.markdown(f"**🗓 วันที่บันทึก:** {row['วัน-เวลา']}")
                    st.markdown(f"**🏷 SKU:** {row['SKU']} | **สินค้า:** {row['ชื่อสินค้า']}")
                    st.markdown(f"**⚠️ อาการเคลม:** {row['อาการเคลม']}")
                    
                    st.write("---")
                    col_m1, col_m2, col_m3 = st.columns(3)
                    col_m1.metric("ยอดรับจริง", f"{float(row['เงินที่ได้รับ']):,.2f} ฿" if row['เงินที่ได้รับ'].replace('.','',1).isdigit() else row['เงินที่ได้รับ'])
                    col_m2.metric("กำไรตั้งต้น", f"{float(row['กำไรตั้งต้น']):,.2f} ฿" if row['กำไรตั้งต้น'].replace('.','',1).isdigit() else row['กำไรตั้งต้น'])
                    col_m3.metric("ชดเชยจริง", f"{float(row['ยอดชดเชยจริง']):,.2f} ฿" if row['ยอดชดเชยจริง'].replace('.','',1).isdigit() else row['ยอดชดเชยจริง'])
                    
                    img_urls = row['รูปภาพ'].split(", ")
                    if row['รูปภาพ'] != "-" and len(img_urls) > 0:
                        st.write("📸 **หลักฐานรูปภาพ:**")
                        for i, url in enumerate(img_urls, start=1):
                            if url.startswith("http"):
                                st.markdown(f"- [🔗 คลิกเพื่อเปิดดูรูปที่ {i}]({url})")
                    else:
                        st.caption("📸 ไม่มีการแนบรูปภาพในเคสนี้")