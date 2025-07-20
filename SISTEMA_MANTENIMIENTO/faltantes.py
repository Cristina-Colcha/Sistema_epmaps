import pandas as pd
import requests
from datetime import datetime
from flask import Flask, render_template, send_file, request
from tqdm import tqdm
import os

app = Flask(__name__)

LAT = -0.481
LON = -78.141
TIMEZONE = 'America/Guayaquil'

def consultar_clima(fecha, lat=LAT, lon=LON):
    """
    Consulta datos climáticos históricos para una fecha y coordenadas dadas
    usando la API de Open-Meteo.
    """
    fecha_str = fecha.strftime('%Y-%m-%d')
    url = (
        f"https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={lat}&longitude={lon}"
        f"&start_date={fecha_str}&end_date={fecha_str}"
        f"&daily=precipitation_sum,windspeed_10m_max,temperature_2m_max"
        f"&timezone={TIMEZONE}"
    )
    try:
        r = requests.get(url)
        r.raise_for_status() # Lanza una excepción para códigos de estado HTTP de error
        data = r.json()
        # Asegurarse de que los datos diarios existan y contengan los valores esperados
        if 'daily' in data and data['daily'] and 'precipitation_sum' in data['daily'] and \
           'windspeed_10m_max' in data['daily'] and 'temperature_2m_max' in data['daily']:
            return {
                "precipitacion_mm": data['daily']['precipitation_sum'][0],
                "viento_max_kmh": data['daily']['windspeed_10m_max'][0],
                "temperatura_max": data['daily']['temperature_2m_max'][0]
            }
        else:
            print(f"Advertencia: Datos incompletos para {fecha_str}. API Response: {data}")
            return {
                "precipitacion_mm": None,
                "viento_max_kmh": None,
                "temperatura_max": None
            }
    except requests.exceptions.RequestException as e:
        print(f"Error de red o HTTP al consultar clima para {fecha_str}: {e}")
        return {
            "precipitacion_mm": None,
            "viento_max_kmh": None,
            "temperatura_max": None
        }
    except Exception as e:
        print(f"Error inesperado al consultar clima para {fecha_str}: {e}")
        return {
            "precipitacion_mm": None,
            "viento_max_kmh": None,
            "temperatura_max": None
        }

# RUTA CORREGIDA: Ahora esta aplicación responderá a /datos-climaticos
@app.route('/datos-climaticos')
def datos_climaticos_page():
    """
    Procesa el archivo Excel de precipitaciones, busca fechas faltantes,
    consulta datos climáticos para esas fechas y renderiza una tabla.
    """
    # Define la ruta del archivo Excel. Asegúrate de que este archivo exista
    # en la carpeta 'uploads' relativa a donde ejecutas este script.
    excel_path = 'uploads/Precipitacion_Mensual__P42_P43_P5522062025222139.xlsx'

    if not os.path.exists(excel_path):
        print(f"Error: Archivo Excel no encontrado en {excel_path}")
        return "Error: El archivo Excel de precipitaciones no se encontró. Asegúrate de que esté en la carpeta 'uploads'.", 500

    try:
        df = pd.read_excel(excel_path)
        df['Fecha'] = pd.to_datetime(df['Fecha'], dayfirst=True)
    except Exception as e:
        print(f"Error al leer el archivo Excel: {e}")
        return "Error al procesar el archivo Excel. Asegúrate de que sea un formato válido.", 500

    sensores = ['P42', 'P43', 'P55']
    fechas_faltantes = []

    for sensor in sensores:
        if sensor in df.columns: # Asegurarse de que el sensor exista como columna
            faltantes = df[df[sensor].isna()][['Fecha']].copy()
            faltantes['Sensor'] = sensor
            fechas_faltantes.append(faltantes)
        else:
            print(f"Advertencia: El sensor '{sensor}' no se encontró en las columnas del Excel.")

    if not fechas_faltantes:
        return render_template('resultado.html', datos=[]) # No hay datos faltantes
    
    faltantes_total = pd.concat(fechas_faltantes).reset_index(drop=True)

    climas = []
    print(f"Consultando clima para {len(faltantes_total)} fechas con datos faltantes...")
    for _, row in tqdm(faltantes_total.iterrows(), total=len(faltantes_total), desc="Consultando clima"):
        clima = consultar_clima(row['Fecha'])
        clima['Fecha'] = row['Fecha']
        clima['Sensor'] = row['Sensor']
        climas.append(clima)

    df_clima = pd.DataFrame(climas)
    # Usar 'left' merge para mantener todas las fechas faltantes, incluso si no se encontró clima
    resultado = pd.merge(faltantes_total, df_clima, on=['Fecha', 'Sensor'], how='left')

    # Guardar archivo Excel con dos hojas: original y completados
    output_excel_path = 'uploads/faltantes_resultado.xlsx'
    try:
        with pd.ExcelWriter(output_excel_path, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='Original', index=False)
            resultado.to_excel(writer, sheet_name='Completados', index=False)
        print(f"Archivo 'faltantes_resultado.xlsx' guardado exitosamente en {output_excel_path}")
    except Exception as e:
        print(f"Error al guardar el archivo Excel de resultados: {e}")
        # Considerar si quieres que la página falle o continúe sin el archivo guardado

    # Convertimos el DataFrame a una lista de diccionarios para el template
    datos = resultado.to_dict(orient='records')

    # Asegúrate de tener un archivo llamado 'resultado.html' en tu carpeta 'templates'
    return render_template('resultado.html', datos=datos)


# Ruta para descargar el archivo Excel de faltantes
@app.route('/descargar_faltantes')
def descargar_faltantes():
    """
    Permite la descarga del archivo Excel generado con los datos faltantes y completados.
    """
    file_path = 'uploads/faltantes_resultado.xlsx'
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True, download_name="faltantes_clima.xlsx")
    else:
        return 'Archivo no encontrado. Por favor, genera el reporte primero.', 404

if __name__ == '__main__':
    # Asegúrate de que la carpeta 'uploads' exista para esta aplicación también
    os.makedirs('uploads', exist_ok=True)
    app.run(debug=True, port=5001)

