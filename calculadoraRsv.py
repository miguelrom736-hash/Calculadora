import streamlit as st
import pandas as pd
import psycopg2
import json
import datetime
import requests
from fpdf import FPDF

# ==========================================
# 1. CONFIGURACIÓN Y ESTADO
# ==========================================
st.set_page_config(page_title="Calculadora RSV - ERP Cotizador", layout="wide")

if 'cart' not in st.session_state:
    st.session_state.cart = []

if 'c_name_val' not in st.session_state:
    st.session_state.c_name_val = ""
if 'c_doc_val' not in st.session_state:
    st.session_state.c_doc_val = ""
if 'c_phone_val' not in st.session_state:
    st.session_state.c_phone_val = ""

st.markdown("""
<style>
    .stMetric { background: #1e293b; padding: 15px; border-radius: 10px; border: 1px solid #334155; }
    .stMetric * { color: #f8fafc !important; }
    h1, h2, h3 { color: #38bdf8; }

    div[data-testid="stTextInputRootElement"],
    div[data-testid="stNumberInputContainer"],
    div[data-testid="stSelectbox"] div.react-aria-ComboBox > div,
    div[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
    div[data-testid="stDateInput"] div[data-baseweb="input"] {
        border-color: #000000 !important;
        border-style: solid !important;
        border-width: 1px !important;
        border-radius: 8px !important;
    }

    div[data-testid="stTextInputRootElement"]:focus-within,
    div[data-testid="stNumberInputContainer"]:focus-within,
    div[data-testid="stSelectbox"] div.react-aria-ComboBox > div:focus-within,
    div[data-testid="stSelectbox"] div[data-baseweb="select"] > div:focus-within,
    div[data-testid="stDateInput"] div[data-baseweb="input"]:focus-within {
        border-color: #38bdf8 !important;
        box-shadow: 0 0 0 1px #38bdf8 !important;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. CAPA DE DATOS (SUPABASE / POSTGRESQL)
# ==========================================
def get_connection():
    # Lee la URL de la base de datos desde los secretos de Streamlit
    return psycopg2.connect(st.secrets["database"]["url"])

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS suppliers (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            discount REAL DEFAULT 0
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            supplier_id INTEGER REFERENCES suppliers(id) ON DELETE CASCADE,
            name TEXT UNIQUE NOT NULL,
            base_cost REAL NOT NULL,
            profit_margin REAL DEFAULT 30
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value REAL NOT NULL
        )
    """)
    cursor.execute("INSERT INTO config (key, value) VALUES ('tasa_usd', 0.0) ON CONFLICT (key) DO NOTHING")
    cursor.execute("INSERT INTO config (key, value) VALUES ('tasa_eur', 0.0) ON CONFLICT (key) DO NOTHING")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS saved_budgets (
            id SERIAL PRIMARY KEY,
            date TEXT NOT NULL,
            client_name TEXT NOT NULL,
            client_doc TEXT NOT NULL,
            client_phone TEXT NOT NULL,
            currency TEXT NOT NULL,
            bcv_rate REAL NOT NULL,
            total_foreign REAL NOT NULL,
            total_ves REAL NOT NULL,
            total_profit_foreign REAL DEFAULT 0.0,
            items_json TEXT NOT NULL
        )
    """)
    conn.commit()
    cursor.close()
    conn.close()

def run_query(query, params=(), fetch=True):
    # Convierte la sintaxis de SQLite (?) a PostgreSQL (%s) automáticamente
    query = query.replace("?", "%s")
    
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        conn.commit()
        if fetch:
            columns = [col[0] for col in cursor.description] if cursor.description else []
            data = cursor.fetchall()
            return pd.DataFrame(data, columns=columns) if data else pd.DataFrame(columns=columns)
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()

# Iniciar la base de datos automáticamente al abrir la app
init_db()

def get_config(key):
    df = run_query("SELECT value FROM config WHERE key = ?", (key,))
    return float(df.iloc[0, 0]) if not df.empty else 0.0

def set_config(key, value):
    run_query("UPDATE config SET value = ? WHERE key = ?", (float(value), key), fetch=False)

# ==========================================
# 3. CONSULTA DE TASAS VÍA DOLARAPI
# ==========================================
@st.cache_data(ttl=300)
def fetch_bcv_rates():
    usd, eur = None, None
    try:
        r_usd = requests.get("https://ve.dolarapi.com/v1/dolares/oficial", timeout=5)
        if r_usd.status_code == 200:
            usd = round(float(r_usd.json().get("promedio")), 2)
    except Exception:
        pass

    try:
        r_eur = requests.get("https://ve.dolarapi.com/v1/euros/oficial", timeout=5)
        if r_eur.status_code == 200:
            eur = round(float(r_eur.json().get("promedio")), 2)
    except Exception:
        pass

    return usd, eur

api_usd, api_eur = fetch_bcv_rates()
if get_config('tasa_usd') == 0.0 and api_usd:
    set_config('tasa_usd', api_usd)
if get_config('tasa_eur') == 0.0 and api_eur:
    set_config('tasa_eur', api_eur)

# ==========================================
# 4. MOTOR PDF
# ==========================================
class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 15)
        self.set_text_color(16, 185, 129)
        self.cell(0, 10, 'CALCULADORA RSV - REPORTE OFICIAL', 0, 1, 'C')
        self.ln(5)

def generate_pdf(client, doc, phone, date, cart, currency, rate_bcv, total_usd, total_ves):
    pdf = PDF()
    pdf.add_page()
    
    pdf.set_font('Arial', '', 10)
    pdf.cell(0, 5, f"Cliente: {client}", 0, 1)
    pdf.cell(0, 5, f"C.I / RIF: {doc}", 0, 1)
    pdf.cell(0, 5, f"Telefono: {phone}", 0, 1)
    pdf.cell(0, 5, f"Fecha: {date}", 0, 1)
    pdf.ln(10)
    
    pdf.set_font('Arial', 'B', 10)
    pdf.cell(100, 8, 'Descripcion', 1)
    pdf.cell(20, 8, 'Cant', 1)
    pdf.cell(35, 8, f'P. Unit ({currency})', 1)
    pdf.cell(35, 8, f'Total ({currency})', 1)
    pdf.ln()
    
    pdf.set_font('Arial', '', 10)
    for item in cart:
        pdf.cell(100, 8, str(item['name'])[:45], 1)
        pdf.cell(20, 8, str(item['qty']), 1)
        pdf.cell(35, 8, f"{item['unit_price']:.2f}", 1)
        pdf.cell(35, 8, f"{item['total']:.2f}", 1)
        pdf.ln()
        
    pdf.ln(10)
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(120, 10, 'TOTAL CONSOLIDADO:', 0)
    pdf.cell(70, 10, f"{total_usd:.2f} {currency}", 0, 1, 'R')
    pdf.cell(120, 10, f'EQUIVALENTE VES (Tasa BCV: {rate_bcv:.2f}):', 0)
    pdf.cell(70, 10, f"{total_ves:.2f} Bs.", 0, 1, 'R')
    
    return pdf.output(dest="S").encode("latin1")

def generate_profit_report_pdf(title, period_label, total_usd, total_eur, total_ves, df_details):
    pdf = PDF()
    pdf.add_page()
    
    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 8, f"REPORTE DE GANANCIAS ({title.upper()})", 0, 1, 'L')
    pdf.set_font('Arial', '', 10)
    pdf.cell(0, 5, f"Periodo / Fecha: {period_label}", 0, 1, 'L')
    pdf.cell(0, 5, f"Fecha de Emision: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}", 0, 1, 'L')
    pdf.ln(5)
    
    pdf.set_font('Arial', 'B', 11)
    pdf.cell(0, 7, "RESUMEN CONSOLIDADO DE GANANCIAS:", 0, 1)
    pdf.set_font('Arial', '', 10)
    pdf.cell(60, 6, f"Ganancia USD: ${total_usd:,.2f}", 1)
    pdf.cell(60, 6, f"Ganancia EUR: {total_eur:,.2f}", 1)
    pdf.cell(70, 6, f"Total Bolivares: {total_ves:,.2f} Bs.", 1)
    pdf.ln(10)
    
    pdf.set_font('Arial', 'B', 9)
    pdf.cell(25, 7, 'Fecha', 1)
    pdf.cell(45, 7, 'Cliente', 1)
    pdf.cell(20, 7, 'Moneda', 1)
    pdf.cell(25, 7, 'Tasa BCV', 1)
    pdf.cell(35, 7, 'Total Presup.', 1)
    pdf.cell(40, 7, 'Ganancia (Divisa)', 1)
    pdf.ln()
    
    pdf.set_font('Arial', '', 8)
    for _, row in df_details.iterrows():
        pdf.cell(25, 6, str(row['date'])[:10], 1)
        pdf.cell(45, 6, str(row['client_name'])[:22], 1)
        pdf.cell(20, 6, str(row['currency']), 1)
        pdf.cell(25, 6, f"{row['bcv_rate']:.2f}", 1)
        pdf.cell(35, 6, f"{row['total_foreign']:.2f}", 1)
        pdf.cell(40, 6, f"{row['total_profit_foreign']:.2f}", 1)
        pdf.ln()
        
    return pdf.output(dest="S").encode("latin1")

# ==========================================
# 5. NAVEGACIÓN LATERAL Y GESTIÓN DE TASAS
# ==========================================
with st.sidebar:
    st.title("⚙️ Calculadora RSV")
    menu = st.radio("Navegación", ["🏢 Proveedores", "📦 Productos", "📝 Nuevo Presupuesto", "📈 Ganancias", "📂 Historial"])
    
    st.divider()
    st.subheader("💱 Ajuste de Tasas BCV")
    
    current_usd = get_config('tasa_usd')
    current_eur = get_config('tasa_eur')
    
    input_usd = st.number_input("Tasa USD (Bs)", value=current_usd, step=0.01, format="%.2f", key="inp_usd")
    input_eur = st.number_input("Tasa EUR (Bs)", value=current_eur, step=0.01, format="%.2f", key="inp_eur")
    
    col_t1, col_t2 = st.columns(2)
    
    if col_t1.button("💾 Aplicar Tasa", use_container_width=True):
        set_config('tasa_usd', input_usd)
        set_config('tasa_eur', input_eur)
        st.toast("¡Tasa guardada con éxito!", icon="✅")
        st.rerun()

    if col_t2.button("🔄 Consultar API", use_container_width=True):
        st.cache_data.clear()
        api_usd, api_eur = fetch_bcv_rates()
        if api_usd and api_eur:
            set_config('tasa_usd', api_usd)
            set_config('tasa_eur', api_eur)
            st.toast("¡Tasas actualizadas desde la API!", icon="🔄")
        else:
            st.toast("No se pudo conectar a la API.", icon="⚠️")
        st.rerun()

# ==========================================
# 6. MÓDULO: PROVEEDORES
# ==========================================
if menu == "🏢 Proveedores":
    st.header("Gestión de Proveedores")
    
    with st.form("add_supplier", clear_on_submit=True):
        c1, c2 = st.columns(2)
        s_name = c1.text_input("Nombre del Proveedor")
        s_disc = c2.number_input("Descuento Estándar (%)", min_value=0.0, max_value=100.0, step=1.0)
        submitted_supp = st.form_submit_button("Guardar Proveedor")
        
        if submitted_supp:
            if not s_name.strip():
                st.error("Por favor ingrese el nombre del proveedor.")
            else:
                try:
                    run_query("INSERT INTO suppliers (name, discount) VALUES (?, ?)", (s_name.strip(), s_disc), fetch=False)
                    st.toast("¡Proveedor guardado exitosamente!", icon="🏢")
                except psycopg2.IntegrityError:
                    st.error("El proveedor ya existe en la base de datos.")
                    
    st.divider()
    st.subheader("Directorio Activo")
    df_supp = run_query("SELECT name, discount FROM suppliers")
    
    if not df_supp.empty:
        df_supp.columns = ['Proveedor', 'Descuento (%)']
        edited_supp = st.data_editor(df_supp, num_rows="dynamic", use_container_width=True, key="supp_table")
        
        if st.button("💾 Actualizar Cambios de Proveedores"):
            for idx, row in edited_supp.iterrows():
                run_query("UPDATE suppliers SET discount=? WHERE name=?", (row['Descuento (%)'], row['Proveedor']), fetch=False)
            st.toast("Cambios aplicados correctamente.", icon="💾")
            st.rerun()
            
        st.divider()
        st.subheader("🗑️ Eliminar Proveedor")
        supp_to_delete = st.selectbox("Selecciona proveedor a eliminar", df_supp['Proveedor'].tolist(), key="del_supp_select")
        if st.button("Eliminar Proveedor Seleccionado"):
            run_query("DELETE FROM suppliers WHERE name=?", (supp_to_delete,), fetch=False)
            st.toast(f"Proveedor '{supp_to_delete}' eliminado.", icon="🗑️")
            st.rerun()
    else:
        st.info("No hay proveedores registrados.")

# ==========================================
# 7. MÓDULO: PRODUCTOS
# ==========================================
elif menu == "📦 Productos":
    st.header("Catálogo de Productos e Inventario")
    
    df_supp = run_query("SELECT id, name FROM suppliers")
    if df_supp.empty:
        st.warning("⚠️ Debe registrar al menos un proveedor antes de crear productos.")
    else:
        with st.expander("➕ Crear Nuevo Producto", expanded=False):
            with st.form("add_product", clear_on_submit=True):
                p_name = st.text_input("Nombre del Producto")
                c1, c2, c3 = st.columns(3)
                p_supplier = c1.selectbox("Proveedor", df_supp['name'].tolist(), key="prod_sup_sel")
                p_cost = c2.number_input("Costo Base ($)", min_value=0.0, step=1.0, format="%.2f")
                p_margin = c3.selectbox("Margen de Ganancia (%)", [30, 35, 40])
                submitted_prod = st.form_submit_button("Guardar Producto")
                
                if submitted_prod:
                    if not p_name.strip():
                        st.error("Por favor ingrese el nombre del producto.")
                    else:
                        sup_row = df_supp[df_supp['name'] == p_supplier]
                        sup_id = int(sup_row.iloc[0]['id'])
                        try:
                            run_query("INSERT INTO products (supplier_id, name, base_cost, profit_margin) VALUES (?, ?, ?, ?)",
                                      (sup_id, p_name.strip(), p_cost, p_margin), fetch=False)
                            st.toast("¡Producto guardado exitosamente!", icon="📦")
                        except psycopg2.IntegrityError:
                            st.error("El nombre del producto ya existe en el catálogo.")

        st.divider()
        st.subheader("✏️ Editar / Eliminar Producto")
        
        df_prod_full = run_query("""
            SELECT p.id, p.name as producto_nombre, s.name as proveedor_nombre, p.base_cost, p.profit_margin
            FROM products p 
            JOIN suppliers s ON p.supplier_id = s.id
        """)
        
        if not df_prod_full.empty:
            prod_options = {row['producto_nombre']: row for idx, row in df_prod_full.iterrows()}
            selected_option = st.selectbox("Seleccione el producto que desea modificar", list(prod_options.keys()))
            
            selected_prod = prod_options[selected_option]
            
            with st.form(key=f"edit_form_{selected_prod['id']}"):
                nuevo_nombre = st.text_input("Nombre del Producto", value=str(selected_prod['producto_nombre']))
                
                col_e1, col_e2, col_e3 = st.columns(3)
                
                supp_list = df_supp['name'].tolist()
                supp_index = supp_list.index(selected_prod['proveedor_nombre']) if selected_prod['proveedor_nombre'] in supp_list else 0
                nueva_supp = col_e1.selectbox("Proveedor", supp_list, index=supp_index)
                
                nuevo_costo = col_e2.number_input("Costo Base ($)", value=float(selected_prod['base_cost']), min_value=0.0, step=0.5, format="%.2f")
                
                margenes = [30, 35, 40]
                m_curr = int(selected_prod['profit_margin'])
                m_index = margenes.index(m_curr) if m_curr in margenes else 0
                nuevo_margen = col_e3.selectbox("Margen de Ganancia (%)", margenes, index=m_index)
                
                col_b1, col_b2 = st.columns(2)
                btn_update = col_b1.form_submit_button("💾 Actualizar Producto", use_container_width=True)
                btn_delete = col_b2.form_submit_button("🗑️ Eliminar Producto", use_container_width=True)
                
                if btn_update:
                    sup_id = int(df_supp[df_supp['name'] == nueva_supp].iloc[0]['id'])
                    try:
                        run_query("""
                            UPDATE products 
                            SET supplier_id=?, name=?, base_cost=?, profit_margin=? 
                            WHERE id=?
                        """, (sup_id, nuevo_nombre.strip(), nuevo_costo, nuevo_margen, selected_prod['id']), fetch=False)
                        st.toast("¡Producto actualizado!", icon="✏️")
                        st.rerun()
                    except psycopg2.IntegrityError:
                        st.error("Ya existe otro producto registrado con ese nombre.")

                if btn_delete:
                    run_query("DELETE FROM products WHERE id=?", (selected_prod['id'],), fetch=False)
                    st.toast("Producto eliminado del inventario.", icon="🗑️")
                    st.rerun()

            st.divider()
            st.subheader("Catálogo de Productos Guardados")
            df_display = df_prod_full[['producto_nombre', 'proveedor_nombre', 'base_cost', 'profit_margin']].copy()
            df_display.columns = ['Producto', 'Proveedor', 'Costo Base ($)', 'Margen (%)']
            st.dataframe(df_display, use_container_width=True)
        else:
            st.info("No hay productos registrados en el inventario.")

# ==========================================
# 8. MÓDULO: NUEVO PRESUPUESTO
# ==========================================
elif menu == "📝 Nuevo Presupuesto":
    st.header("Módulo de Ventas y Presupuestos")
    
    c_cfg1, c_cfg2 = st.columns(2)
    moneda_base = c_cfg1.selectbox("Moneda Base del Presupuesto", ["USD", "EUR"], key="pres_curr")
    tasa_bcv = get_config('tasa_usd') if moneda_base == "USD" else get_config('tasa_eur')
    c_cfg2.metric(f"Tasa BCV Aplicada ({moneda_base})", f"{tasa_bcv:,.2f} Bs.")
    
    st.subheader("Datos del Cliente")
    cc1, cc2, cc3 = st.columns(3)
    
    cliente = cc1.text_input("Nombre del Cliente", value=st.session_state.c_name_val, key="c_name_input")
    cliente_doc = cc2.text_input("C.I / RIF", value=st.session_state.c_doc_val, key="c_doc_input")
    cliente_phone = cc3.text_input("Teléfono", value=st.session_state.c_phone_val, key="c_phone_input")
    
    st.session_state.c_name_val = cliente
    st.session_state.c_doc_val = cliente_doc
    st.session_state.c_phone_val = cliente_phone
    
    st.divider()
    
    tab1, tab2 = st.tabs(["🛒 Agregar Producto del Catálogo", "👷 Agregar Mano de Obra (Manual)"])
    
    with tab1:
        query_cat = """
            SELECT p.name, p.base_cost, p.profit_margin, s.discount as supplier_discount 
            FROM products p JOIN suppliers s ON p.supplier_id = s.id
        """
        df_cat = run_query(query_cat)
        if df_cat.empty:
            st.info("No hay productos disponibles en el catálogo.")
        else:
            col_sel, col_qty, col_btn = st.columns([3, 1, 1])
            prod_sel = col_sel.selectbox("Seleccionar Producto", df_cat['name'].tolist(), key="cat_prod_sel")
            qty_prod = col_qty.number_input("Cant.", min_value=1, value=1, step=1, key="q_prod")
            
            if col_btn.button("➕ Añadir Producto", use_container_width=True, key="add_p_cart"):
                row = df_cat[df_cat['name'] == prod_sel].iloc[0]
                costo_base = row['base_cost']
                costo_neto = costo_base * (1 - (row['supplier_discount'] / 100))
                precio_final = costo_neto * (1 + (row['profit_margin'] / 100))
                ganancia_unid = precio_final - costo_neto
                
                st.session_state.cart.append({
                    "type": "PRODUCTO",
                    "name": row['name'],
                    "qty": qty_prod,
                    "unit_price": precio_final,
                    "profit": ganancia_unid * qty_prod,
                    "total": precio_final * qty_prod
                })
                st.rerun()
                
    with tab2:
        col_m1, col_m2, col_m3, col_m4, col_mbtn = st.columns([2, 1, 1, 1, 1])
        desc_labor = col_m1.text_input("Descripción del Trabajo o Servicio", key="labor_desc")
        qty_labor = col_m2.number_input("Cant.", min_value=1, value=1, step=1, key="q_labor")
        precio_labor = col_m3.number_input("Precio Neto Unitario", min_value=0.0, step=1.0, format="%.2f", key="labor_price")
        moneda_labor = col_m4.selectbox("Moneda", ["USD", "EUR"], key="labor_curr")
        
        if col_mbtn.button("➕ Añadir Labor", use_container_width=True, key="add_l_cart"):
            if desc_labor:
                tasa_u = get_config('tasa_usd')
                tasa_e = get_config('tasa_eur')
                
                precio_final_labor = precio_labor
                if moneda_labor != moneda_base:
                    if moneda_base == "USD" and moneda_labor == "EUR":
                        if tasa_u > 0:
                            precio_final_labor = precio_labor * (tasa_e / tasa_u)
                    elif moneda_base == "EUR" and moneda_labor == "USD":
                        if tasa_e > 0:
                            precio_final_labor = precio_labor * (tasa_u / tasa_e)
                            
                st.session_state.cart.append({
                    "type": "LABOR",
                    "name": f"[Servicio] {desc_labor} ({precio_labor} {moneda_labor})",
                    "qty": qty_labor,
                    "unit_price": precio_final_labor,
                    "profit": precio_final_labor * qty_labor,
                    "total": precio_final_labor * qty_labor
                })
                st.rerun()
            else:
                st.warning("Ingresa una descripción para la mano de obra.")

    st.divider()
    st.subheader("🛒 Detalle del Presupuesto Actual")
    
    if st.session_state.cart:
        total_divisa = 0
        ganancia_total = 0
        
        for i, item in enumerate(st.session_state.cart):
            col_item = st.columns([4, 1, 2, 2, 1])
            col_item[0].write(item['name'])
            col_item[1].write(f"x{item['qty']}")
            col_item[2].write(f"{item['unit_price']:,.2f} {moneda_base}")
            col_item[3].write(f"{item['total']:,.2f} {moneda_base}")
            if col_item[4].button("❌", key=f"del_cart_{i}", help="Eliminar este ítem"):
                st.session_state.cart.pop(i)
                st.rerun()
            total_divisa += item['total']
            ganancia_total += item.get('profit', 0)
            
        total_ves = total_divisa * tasa_bcv
        
        c_met1, c_met2 = st.columns(2)
        c_met1.metric(f"Total Presupuesto ({moneda_base})", f"{total_divisa:,.2f}")
        c_met2.metric("Equivalente en Bolívares", f"{total_ves:,.2f} Bs.")
        
        st.divider()
        c_save1, c_save2 = st.columns(2)
        
        if c_save1.button("💾 Guardar Presupuesto", key="save_budg_btn", use_container_width=True):
            if not cliente or not cliente_doc:
                st.error("Por favor ingresa al menos el Nombre y la C.I / RIF del cliente.")
            else:
                fecha_actual = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                items_json = json.dumps(st.session_state.cart)
                run_query("""
                    INSERT INTO saved_budgets (date, client_name, client_doc, client_phone, currency, bcv_rate, total_foreign, total_ves, total_profit_foreign, items_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (fecha_actual, cliente, cliente_doc, cliente_phone if cliente_phone else "N/A", moneda_base, tasa_bcv, total_divisa, total_ves, ganancia_total, items_json), fetch=False)
                
                st.toast("¡Presupuesto guardado exitosamente!", icon="📝")
                st.session_state.cart = []
                st.session_state.c_name_val = ""
                st.session_state.c_doc_val = ""
                st.session_state.c_phone_val = ""
                st.rerun()
                
        pdf_bytes = generate_pdf(
            cliente if cliente else "Consumidor Final", 
            cliente_doc if cliente_doc else "N/A", 
            cliente_phone if cliente_phone else "N/A", 
            datetime.datetime.now().strftime("%Y-%m-%d"), 
            st.session_state.cart, 
            moneda_base, 
            tasa_bcv, 
            total_divisa, 
            total_ves
        )
        c_save2.download_button("📄 Descargar PDF Oficial", data=pdf_bytes, file_name="Presupuesto.pdf", mime="application/pdf", key="dl_pdf_curr", use_container_width=True)
    else:
        st.info("El presupuesto está vacío. Añade productos o mano de obra.")

# ==========================================
# 9. MÓDULO: GANANCIAS
# ==========================================
elif menu == "📈 Ganancias":
    st.header("📊 Resumen y Reportes de Ganancias")
    
    df_history = run_query("SELECT id, date, client_name, currency, bcv_rate, total_foreign, total_profit_foreign FROM saved_budgets ORDER BY id DESC")
    
    if df_history.empty:
        st.info("No hay presupuestos registrados para consultar ganancias.")
    else:
        df_history['date_dt'] = pd.to_datetime(df_history['date'])
        df_history['fecha'] = df_history['date_dt'].dt.strftime('%Y-%m-%d')
        
        tab_dia, tab_totales = st.tabs(["📅 Consulta por Día", "🗓️ Consulta Acumulada (Semana / Mes / Total)"])
        
        with tab_dia:
            st.subheader("Ganancias y Presupuestos por Día")
            fecha_sel = st.date_input("Selecciona la Fecha", datetime.date.today(), key="prof_date_sel")
            
            df_dia = df_history[df_history['fecha'] == str(fecha_sel)]
            
            if not df_dia.empty:
                usd_dia = df_dia[df_dia['currency'] == 'USD']
                eur_dia = df_dia[df_dia['currency'] == 'EUR']
                
                g_usd_dia = usd_dia['total_profit_foreign'].sum()
                g_eur_dia = eur_dia['total_profit_foreign'].sum()
                
                ves_usd_dia = (usd_dia['total_profit_foreign'] * usd_dia['bcv_rate']).sum()
                ves_eur_dia = (eur_dia['total_profit_foreign'] * eur_dia['bcv_rate']).sum()
                tot_ves_dia = ves_usd_dia + ves_eur_dia
                
                c_d1, c_d2, c_d3 = st.columns(3)
                c_d1.metric("Ganancia USD del Día", f"${g_usd_dia:,.2f}")
                c_d2.metric("Ganancia EUR del Día", f"€{g_eur_dia:,.2f}")
                c_d3.metric("Total Equivalente en Bolívares", f"{tot_ves_dia:,.2f} Bs.")
                
                st.divider()
                st.write(f"**Presupuestos emitidos el {fecha_sel}:**")
                df_dia_disp = df_dia[['date', 'client_name', 'currency', 'bcv_rate', 'total_foreign', 'total_profit_foreign']].copy()
                df_dia_disp.columns = ['Hora/Fecha', 'Cliente', 'Moneda', 'Tasa BCV', 'Total Presupuesto', 'Ganancia (Margen)']
                st.dataframe(df_dia_disp, use_container_width=True)
                
                pdf_report_dia = generate_profit_report_pdf(
                    f"Diario_{fecha_sel}", str(fecha_sel), g_usd_dia, g_eur_dia, tot_ves_dia, df_dia
                )
                st.download_button("📄 Imprimir Reporte PDF del Día", data=pdf_report_dia, file_name=f"Reporte_Ganancias_{fecha_sel}.pdf", mime="application/pdf", key="dl_pdf_dia")
            else:
                st.warning(f"No hay presupuestos ni ganancias registradas para el día {fecha_sel}.")

        with tab_totales:
            st.subheader("Ganancias Acumuladas")
            periodo = st.selectbox("Seleccione el Periodo", ["Última Semana (7 Días)", "Último Mes (30 Días)", "Histórico Completo"])
            
            now = datetime.datetime.now()
            if periodo == "Última Semana (7 Días)":
                df_filtrado = df_history[df_history['date_dt'] >= (now - datetime.timedelta(days=7))]
            elif periodo == "Último Mes (30 Días)":
                df_filtrado = df_history[df_history['date_dt'] >= (now - datetime.timedelta(days=30))]
            else:
                df_filtrado = df_history.copy()
                
            if not df_filtrado.empty:
                df_usd = df_filtrado[df_filtrado['currency'] == 'USD']
                df_eur = df_filtrado[df_filtrado['currency'] == 'EUR']
                
                tot_usd_profit = df_usd['total_profit_foreign'].sum()
                tot_eur_profit = df_eur['total_profit_foreign'].sum()
                
                ves_conv_usd = (df_usd['total_profit_foreign'] * df_usd['bcv_rate']).sum()
                ves_conv_eur = (df_eur['total_profit_foreign'] * df_eur['bcv_rate']).sum()
                tot_ves_acum = ves_conv_usd + ves_conv_eur
                
                col_m1, col_m2, col_m3 = st.columns(3)
                col_m1.metric("Ganancia Total USD", f"${tot_usd_profit:,.2f}", f"{ves_conv_usd:,.2f} Bs.")
                col_m2.metric("Ganancia Total EUR", f"€{tot_eur_profit:,.2f}", f"{ves_conv_eur:,.2f} Bs.")
                col_m3.metric("Total Consolidado Bolívares", f"{tot_ves_acum:,.2f} Bs.")
                
                st.divider()
                st.write("**Detalle de presupuestos agrupados en este periodo:**")
                df_filt_disp = df_filtrado[['date', 'client_name', 'currency', 'bcv_rate', 'total_foreign', 'total_profit_foreign']].copy()
                df_filt_disp.columns = ['Fecha', 'Cliente', 'Moneda', 'Tasa BCV', 'Total Presupuesto', 'Ganancia (Margen)']
                st.dataframe(df_filt_disp, use_container_width=True)
                
                pdf_report_acum = generate_profit_report_pdf(
                    f"Acumulado_{periodo.replace(' ', '_')}", periodo, tot_usd_profit, tot_eur_profit, tot_ves_acum, df_filtrado
                )
                st.download_button("📄 Imprimir Reporte PDF del Periodo", data=pdf_report_acum, file_name=f"Reporte_Ganancias_{periodo.replace(' ', '_')}.pdf", mime="application/pdf", key="dl_pdf_acum")
            else:
                st.info("No hay registros en el rango de tiempo seleccionado.")

# ==========================================
# 10. MÓDULO: HISTORIAL
# ==========================================
elif menu == "📂 Historial":
    st.header("📂 Historial de Presupuestos Emitidos")
    
    df_history = run_query("SELECT id, date, client_name, client_doc, client_phone, currency, bcv_rate, total_foreign, total_ves, items_json FROM saved_budgets ORDER BY id DESC")
    
    if df_history.empty:
        st.info("No hay presupuestos guardados en el historial.")
    else:
        df_history['date_dt'] = pd.to_datetime(df_history['date'])
        df_history['fecha'] = df_history['date_dt'].dt.strftime('%Y-%m-%d')
        
        tab_h_dia, tab_h_acum = st.tabs(["📅 Presupuestos por Día", "🗓️ Presupuestos Acumulados (Semana / Mes / Total)"])
        
        with tab_h_dia:
            st.subheader("Consulta Diaria de Presupuestos")
            f_sel_hist = st.date_input("Seleccionar Fecha", datetime.date.today(), key="hist_date_p")
            
            df_hist_dia = df_history[df_history['fecha'] == str(f_sel_hist)]
            
            if not df_hist_dia.empty:
                df_disp_d = df_hist_dia[['id', 'date', 'client_name', 'client_doc', 'client_phone', 'currency', 'bcv_rate', 'total_foreign', 'total_ves']].copy()
                df_disp_d.columns = ['ID', 'Fecha/Hora', 'Cliente', 'C.I / RIF', 'Teléfono', 'Moneda', 'Tasa BCV', 'Total Divisa', 'Total VES']
                st.dataframe(df_disp_d, use_container_width=True)
                
                st.divider()
                st.subheader("📄 Imprimir Presupuesto del Día")
                
                map_d = {f"[{row['id']}] {row['client_name']} - {row['date']} ({row['total_foreign']:.2f} {row['currency']})": row for idx, row in df_hist_dia.iterrows()}
                p_sel_d = st.selectbox("Seleccione el presupuesto que desea imprimir en PDF", list(map_d.keys()), key="sel_pdf_d")
                
                if p_sel_d:
                    row_sel = map_d[p_sel_d]
                    cart_sel = json.loads(row_sel['items_json'])
                    
                    pdf_bytes = generate_pdf(
                        row_sel['client_name'], row_sel['client_doc'], row_sel['client_phone'],
                        row_sel['date'], cart_sel, row_sel['currency'], row_sel['bcv_rate'],
                        row_sel['total_foreign'], row_sel['total_ves']
                    )
                    
                    c_h1, c_h2 = st.columns(2)
                    c_h1.download_button(f"📄 Descargar PDF de {row_sel['client_name']}", data=pdf_bytes, file_name=f"Presupuesto_{row_sel['client_name']}.pdf", mime="application/pdf", key="dl_pdf_h_d", use_container_width=True)
                    if c_h2.button("🗑️ Eliminar Presupuesto", key="del_budg_d", use_container_width=True):
                        run_query("DELETE FROM saved_budgets WHERE id=?", (row_sel['id'],), fetch=False)
                        st.toast("Presupuesto eliminado con éxito.", icon="🗑️")
                        st.rerun()
            else:
                st.warning(f"No hay presupuestos registrados el día {f_sel_hist}.")

        with tab_h_acum:
            st.subheader("Consulta Acumulada de Presupuestos")
            periodo_h = st.selectbox("Seleccione el Periodo a Consultar", ["Última Semana (7 Días)", "Último Mes (30 Días)", "Histórico Completo"], key="p_hist_acum")
            
            now = datetime.datetime.now()
            if periodo_h == "Última Semana (7 Días)":
                df_hist_filt = df_history[df_history['date_dt'] >= (now - datetime.timedelta(days=7))]
            elif periodo_h == "Último Mes (30 Días)":
                df_hist_filt = df_history[df_history['date_dt'] >= (now - datetime.timedelta(days=30))]
            else:
                df_hist_filt = df_history.copy()
                
            if not df_hist_filt.empty:
                df_disp_a = df_hist_filt[['id', 'date', 'client_name', 'client_doc', 'client_phone', 'currency', 'bcv_rate', 'total_foreign', 'total_ves']].copy()
                df_disp_a.columns = ['ID', 'Fecha/Hora', 'Cliente', 'C.I / RIF', 'Teléfono', 'Moneda', 'Tasa BCV', 'Total Divisa', 'Total VES']
                st.dataframe(df_disp_a, use_container_width=True)
                
                st.divider()
                st.subheader("📄 Imprimir Presupuesto Seleccionado del Periodo")
                
                map_a = {f"[{row['id']}] {row['client_name']} - {row['date']} ({row['total_foreign']:.2f} {row['currency']})": row for idx, row in df_hist_filt.iterrows()}
                p_sel_a = st.selectbox("Seleccione el presupuesto que desea imprimir en PDF", list(map_a.keys()), key="sel_pdf_a")
                
                if p_sel_a:
                    row_sel_a = map_a[p_sel_a]
                    cart_sel_a = json.loads(row_sel_a['items_json'])
                    
                    pdf_bytes_a = generate_pdf(
                        row_sel_a['client_name'], row_sel_a['client_doc'], row_sel_a['client_phone'],
                        row_sel_a['date'], cart_sel_a, row_sel_a['currency'], row_sel_a['bcv_rate'],
                        row_sel_a['total_foreign'], row_sel_a['total_ves']
                    )
                    
                    col_ha1, col_ha2 = st.columns(2)
                    col_ha1.download_button(f"📄 Descargar PDF de {row_sel_a['client_name']}", data=pdf_bytes_a, file_name=f"Presupuesto_{row_sel_a['client_name']}.pdf", mime="application/pdf", key="dl_pdf_h_a", use_container_width=True)
                    if col_ha2.button("🗑️ Eliminar Presupuesto del Historial", key="del_budg_a", use_container_width=True):
                        run_query("DELETE FROM saved_budgets WHERE id=?", (row_sel_a['id'],), fetch=False)
                        st.toast("Presupuesto eliminado con éxito.", icon="🗑️")
                        st.rerun()
            else:
                st.info("No hay presupuestos dentro del rango seleccionado.")
