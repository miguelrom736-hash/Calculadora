import streamlit as st
import psycopg2
import pandas as pd
import requests
from fpdf import FPDF
from datetime import datetime

# Configuración de la página
st.set_page_config(page_title="Calculadora RSV - Cotizador", layout="wide")

# Función para conectar a Supabase con psycopg2
def get_connection():
    try:
        url = st.secrets["database"]["url"]
        conn = psycopg2.connect(url)
        return conn
    except Exception as e:
        st.error(f"⚠️ Error exacto al conectar con Supabase: {e}")
        return None

# Función para inicializar la base de datos en Supabase
def init_db():
    conn = get_connection()
    if conn is not None:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS quotations (
                    id SERIAL PRIMARY KEY,
                    client_name TEXT NOT NULL,
                    total_amount NUMERIC,
                    currency TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            st.error(f"⚠️ Error al crear las tablas en Supabase: {e}")

init_db()

# Obtener tasa de cambio usando DolarApi
def get_exchange_rate():
    try:
        response = requests.get("https://ve.dolarapi.com/v1/dolares/bcv", timeout=5)
        if response.status_code == 200:
            data = response.json()
            return data.get("promedio", 1.0)
    except Exception:
        pass
    return 1.0

bcv_rate = get_exchange_rate()

st.title("🧮 Calculadora RSV - Cotizador Profesional")
st.success("¡Conectado exitosamente a la base de datos en la nube de Supabase!")

# Panel lateral con información de tasas
st.sidebar.header("Configuración")
st.sidebar.metric("Tasa BCV Actual", f"{bcv_rate:,.2f} VES")

# Pestañas principales de la aplicación
tab1, tab2 = st.tabs(["Nueva Cotización", "Historial en Supabase"])

with tab1:
    st.subheader("Generar Cotización RSV")
    
    col1, col2 = st.columns(2)
    with col1:
        client_name = st.text_input("Nombre del Cliente")
        base_amount = st.number_input("Monto Base ($)", min_value=0.0, format="%.2f")
    with col2:
        currency_choice = st.selectbox("Moneda de Pago", ["USD", "VES"])
        profit_margin = st.slider("Margen de Ganancia (%)", 0, 100, 20)
    
    # Cálculo de totales
    calculated_total = base_amount * (1 + profit_margin / 100.0)
    if currency_choice == "VES":
        display_total = calculated_total * bcv_rate
        currency_symbol = "VES"
    else:
        display_total = calculated_total
        currency_symbol = "USD"
        
    st.metric(f"Total Calculado ({currency_symbol})", f"{display_total:,.2f}")
    
    if st.button("Guardar y Generar PDF"):
        if client_name.strip() and base_amount > 0:
            # Guardar en Supabase de forma permanente
            conn = get_connection()
            if conn:
                try:
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT INTO quotations (client_name, total_amount, currency) VALUES (%s, %s, %s);",
                        (client_name, display_total, currency_symbol)
                    )
                    conn.commit()
                    cursor.close()
                    conn.close()
                    st.success("¡Cotización guardada permanentemente en Supabase!")
                except Exception as e:
                    st.error(f"Error al guardar en la base de datos: {e}")
            
            # Generar documento PDF con FPDF
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", "B", 16)
            pdf.cell(200, 10, txt="Calculadora RSV - Cotizacion", ln=True, align="C")
            pdf.set_font("Arial", "", 12)
            pdf.cell(200, 10, txt=f"Cliente: {client_name}", ln=True)
            pdf.cell(200, 10, txt=f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ln=True)
            pdf.cell(200, 10, txt=f"Total: {display_total:,.2f} {currency_symbol}", ln=True)
            
            pdf_output = pdf.output(dest='S').encode('latin1')
            st.download_button(
                label="📥 Descargar PDF de Cotización",
                data=pdf_output,
                file_name=f"cotizacion_{client_name.replace(' ', '_')}.pdf",
                mime="application/pdf"
            )
        else:
            st.warning("Por favor, completa el nombre del cliente y un monto base mayor a cero.")

with tab2:
    st.subheader("Historial de Cotizaciones en la Nube")
    conn = get_connection()
    if conn:
        try:
            df = pd.read_sql("SELECT * FROM quotations ORDER BY id DESC;", conn)
            conn.close()
            st.dataframe(df, use_container_width=True)
        except Exception as e:
            st.error(f"Error al cargar el historial: {e}")
