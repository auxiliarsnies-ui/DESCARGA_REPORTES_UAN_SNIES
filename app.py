import streamlit as st
import threading
import queue
import time
import zipfile
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# ─── CONFIGURACIÓN ────────────────────────────────────────────────
USUARIO        = "1826-admin"
CONTRASENA     = "1826Uan9123"
CARPETA_TEMP   = Path.home() / "Downloads/Temporal"
ESPERA_MINUTOS = 1
# ──────────────────────────────────────────────────────────────────

# ─── Helpers ──────────────────────────────────────────────────────
def esperar_descarga(carpeta: Path, timeout=120):
    inicio = time.time()
    while time.time() - inicio < timeout:
        zips = [f for f in carpeta.glob("UnoAUno_*.zip") if not f.name.endswith(".crdownload")]
        if zips:
            return max(zips, key=lambda f: f.stat().st_mtime)
        time.sleep(1)
    raise TimeoutError("La descarga tardó demasiado")

def crear_driver():
    chrome_options = Options()

    # Obligatorio para Streamlit Cloud
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")

    # Apuntar al Chromium instalado por packages.txt
    chrome_options.binary_location = "/usr/bin/chromium"

    chrome_options.add_experimental_option("prefs", {
        "download.default_directory": str(CARPETA_TEMP),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "profile.default_content_setting_values.automatic_downloads": 1
    })

    service = Service("/usr/bin/chromedriver")
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.execute_cdp_cmd("Browser.setDownloadBehavior", {
        "behavior": "allow",
        "downloadPath": str(CARPETA_TEMP)
    })
    return driver

def fase_login(driver, log):
    log("🔐 Iniciando sesión...")
    driver.get("https://hecaa.mineducacion.gov.co/hecaa-snies/content/admin/login/login.jsf")
    time.sleep(1)
    driver.find_element(By.CSS_SELECTOR, "input[id='loginForm:login-user']").send_keys(USUARIO)
    driver.find_element(By.CSS_SELECTOR, "input[id='loginForm:login-password']").send_keys(CONTRASENA)
    driver.find_element(By.ID, "loginForm:submitLogin").click()
    time.sleep(2)
    log("✅ Login exitoso")

def fase_solicitar(driver, log):
    log("📨 Navegando a Solicitudes...")
    WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "menu_85"))).click()
    time.sleep(0.5)
    WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "menu_109"))).click()
    time.sleep(0.5)
    WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "menu_110"))).click()
    time.sleep(0.5)

    select_oculto = driver.find_element(By.ID, "form:options_input")
    opciones_data = []
    for op in select_oculto.find_elements(By.TAG_NAME, "option"):
        value = op.get_attribute("value")
        label = op.get_attribute("innerHTML").strip()
        if value:
            opciones_data.append({"value": value, "label": label})

    log(f"📋 {len(opciones_data)} reportes encontrados")

    for i, opcion in enumerate(opciones_data):
        try:
            trigger = driver.find_element(By.CSS_SELECTOR, "#form\\:options .ui-selectonemenu-trigger")
            trigger.click()
            panel = WebDriverWait(driver, 10).until(
                EC.visibility_of_element_located((By.ID, "form:options_panel"))
            )
            item = panel.find_element(By.CSS_SELECTOR, f"li[data-label='{opcion['label']}']")
            item.click()
            time.sleep(0.5)
            WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, "form:submitEnviar"))
            ).click()
            time.sleep(1.5)
            log(f"  ✅ [{i+1}/{len(opciones_data)}] {opcion['label']}")
        except Exception as e:
            log(f"  ❌ [{i+1}/{len(opciones_data)}] {opcion['label']} → {e}")
            try:
                driver.find_element(By.TAG_NAME, "body").click()
                time.sleep(0.5)
            except:
                pass

def fase_espera(log):
    log(f"⏳ Esperando {ESPERA_MINUTOS} minutos...")
    for minuto in range(ESPERA_MINUTOS, 0, -1):
        log(f"  ⏰ {minuto} minutos restantes...")
        time.sleep(60)
    log("✅ Espera completada")

def fase_descargar(driver, log):
    log("⬇️ Navegando a Descarga de archivos...")
    WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "menu_147"))).click()
    time.sleep(1)

    filas = driver.find_elements(By.CSS_SELECTOR, "tr[data-ri]")
    reportes = []
    for fila in filas:
        celdas = fila.find_elements(By.CSS_SELECTOR, "td[role='gridcell']")
        data_ri   = int(fila.get_attribute("data-ri"))
        nombre    = celdas[2].text.strip()
        fecha_str = celdas[3].text.strip()
        try:
            fecha = datetime.strptime(fecha_str, "%d/%m/%Y %I:%M %p")
        except:
            fecha = datetime.min
        reportes.append({"ri": data_ri, "nombre": nombre, "fecha": fecha})

    grupos = defaultdict(list)
    for r in reportes:
        grupos[r["nombre"]].append(r)

    reportes_unicos = []
    for nombre, grupo in grupos.items():
        mas_reciente = max(grupo, key=lambda x: x["fecha"])
        reportes_unicos.append(mas_reciente)
        if len(grupo) > 1:
            log(f"  ⚠️ Duplicado: '{nombre}' → usando ri={mas_reciente['ri']}")

    log(f"📋 {len(reportes_unicos)} reportes a descargar (sin duplicados)")

    archivos_csv = []
    for i, reporte in enumerate(reportes_unicos):
        try:
            boton_id = f"formDatos:tabla:{reporte['ri']}:download"
            boton = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.ID, boton_id))
            )
            driver.execute_script("arguments[0].click();", boton)
            zip_path = esperar_descarga(CARPETA_TEMP)
            with zipfile.ZipFile(zip_path, "r") as z:
                csvs = [f for f in z.namelist() if f.endswith(".csv")]
                z.extractall(CARPETA_TEMP)
                for csv in csvs:
                    archivos_csv.append(csv)
                    log(f"  📄 Extraído: {csv}")
            zip_path.unlink()
            log(f"  ✅ [{i+1}/{len(reportes_unicos)}] {reporte['nombre']}")
            time.sleep(1)
        except Exception as e:
            log(f"  ❌ [{i+1}/{len(reportes_unicos)}] {reporte['nombre']} → {e}")

    return archivos_csv

# ─── Funciones principales ────────────────────────────────────────
def run_pipeline_completo(log_q):
    def log(msg): log_q.put(msg)
    driver = None
    try:
        driver = crear_driver()
        fase_login(driver, log)
        fase_solicitar(driver, log)
        fase_espera(log)
        csvs = fase_descargar(driver, log)
        log(f"🎉 Pipeline completo — {len(csvs)} CSVs listos en {CARPETA_TEMP}")
    except Exception as e:
        log(f"💥 Error general: {e}")
    finally:
        if driver:
            driver.quit()
        log("__FIN__")

def run_solo_descarga(log_q):
    def log(msg): log_q.put(msg)
    driver = None
    try:
        driver = crear_driver()
        fase_login(driver, log)
        csvs = fase_descargar(driver, log)
        log(f"🎉 Descarga completa — {len(csvs)} CSVs listos en {CARPETA_TEMP}")
    except Exception as e:
        log(f"💥 Error general: {e}")
    finally:
        if driver:
            driver.quit()
        log("__FIN__")

# ─── UI Streamlit ─────────────────────────────────────────────────
st.set_page_config(page_title="SNIES Pipeline", page_icon="📊", layout="centered")

st.title("📊 SNIES — Descarga de Reportes")
st.markdown("Automatización de solicitud y descarga de reportes del SNIES.")
st.divider()

if "corriendo" not in st.session_state:
    st.session_state.corriendo = False
if "log_lines" not in st.session_state:
    st.session_state.log_lines = []

col1, col2 = st.columns(2)

with col1:
    btn_completo = st.button(
        "▶ Pipeline completo",
        disabled=st.session_state.corriendo,
        use_container_width=True,
        type="primary",
        help="Solicita los reportes, espera 1 hora y luego los descarga"
    )

with col2:
    btn_descarga = st.button(
        "⬇️ Solo descargar",
        disabled=st.session_state.corriendo,
        use_container_width=True,
        help="Va directo a descargar los reportes ya solicitados"
    )

st.divider()

log_container = st.empty()

def mostrar_logs():
    if st.session_state.log_lines:
        log_container.code("\n".join(st.session_state.log_lines), language=None)

def ejecutar(fn):
    st.session_state.corriendo = True
    st.session_state.log_lines = []
    log_q = queue.Queue()

    hilo = threading.Thread(target=fn, args=(log_q,), daemon=True)
    hilo.start()

    while True:
        try:
            msg = log_q.get(timeout=1)
            if msg == "__FIN__":
                break
            st.session_state.log_lines.append(msg)
            mostrar_logs()
        except queue.Empty:
            if not hilo.is_alive():
                break

    st.session_state.corriendo = False
    st.rerun()

if btn_completo:
    ejecutar(run_pipeline_completo)

if btn_descarga:
    ejecutar(run_solo_descarga)

mostrar_logs()

if st.session_state.corriendo:
    st.info("⏳ Pipeline en ejecución... no cierres esta ventana.")
