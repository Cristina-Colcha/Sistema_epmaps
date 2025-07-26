import traceback
import pandas as pd
import requests
from flask import Flask, render_template, send_file
from tqdm import tqdm
import os

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'

TIMEZONE = 'America/Guayaquil'
SENSORES_COORDS = {
    'P42': {'lat': -0.6022867145410288, 'lon': -78.1986689291808},
    'P43': {'lat': -0.5934839659614135, 'lon': -78.20825370752031},
    'P55': {'lat': -0.5731364867736277, 'lon': -78.138},
}


def consultar_clima(fecha, lat, lon):
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
        r.raise_for_status()
        data = r.json()
        if 'daily' in data and data['daily']:
            return {
                "precipitacion_mm": data['daily']['precipitation_sum'][0],
                "viento_max_kmh": data['daily']['windspeed_10m_max'][0],
                "temperatura_max": data['daily']['temperature_2m_max'][0]
            }
        else:
            print(f"Advertencia: Datos incompletos para {fecha_str}.")
            return {"precipitacion_mm": None, "viento_max_kmh": None, "temperatura_max": None}
    except Exception as e:
        print(f"Error consultando clima para {fecha_str}: {e}")
        return {"precipitacion_mm": None, "viento_max_kmh": None, "temperatura_max": None}


@app.route('/')
def datos_climaticos_page():
    upload_folder = os.path.abspath(app.config.get('UPLOAD_FOLDER', 'uploads'))
    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder)
        print(f"Carpeta creada en: {upload_folder}")
    else:
        print(f"Carpeta existe: {upload_folder}")

    excel_path = 'data/Precipitacion_Mensual__P42_P43_P5522062025222139.xlsx'
    if not os.path.exists(excel_path):
        print(f"Error: Archivo Excel no encontrado en {excel_path}")
        return "Error: El archivo Excel de precipitaciones no se encontró en el servidor. Asegúrate de que esté en la carpeta 'data/'.", 500

    try:
        df = pd.read_excel(excel_path)
        df['Fecha'] = pd.to_datetime(df['Fecha'], dayfirst=True)
        print(f"Archivo Excel leído correctamente. Shape: {df.shape}")
    except Exception as e:
        print(f"Error al leer el archivo Excel para datos climáticos: {e}")
        traceback.print_exc()
        return "Error al procesar el archivo Excel para datos climáticos. Asegúrate de que sea un formato válido.", 500

    sensores = ['P42', 'P43', 'P55']
    fechas_faltantes = []

    for sensor in sensores:
        if sensor in df.columns:
            faltantes = df[df[sensor].isna()][['Fecha']].copy()
            faltantes['Sensor'] = sensor
            fechas_faltantes.append(faltantes)
        else:
            print(f"Advertencia: El sensor '{sensor}' no se encontró en las columnas del Excel.")

    if not fechas_faltantes:
        return render_template('resultado.html', datos=[])

    faltantes_total = pd.concat(fechas_faltantes).reset_index(drop=True)
    print(f"Fechas faltantes total: {faltantes_total.shape}")

    # Eliminar duplicados para evitar consultas repetidas
    faltantes_total = faltantes_total.drop_duplicates(subset=['Fecha', 'Sensor']).reset_index(drop=True)

    climas = []
    print(f"Consultando clima para {len(faltantes_total)} fechas con datos faltantes...")
    for _, row in tqdm(faltantes_total.iterrows(), total=len(faltantes_total), desc="Consultando clima"):
        coords = SENSORES_COORDS.get(row['Sensor'])
        if coords:
            clima = consultar_clima(row['Fecha'], coords['lat'], coords['lon'])
        else:
            clima = {"precipitacion_mm": None, "viento_max_kmh": None, "temperatura_max": None}
        clima['Fecha'] = row['Fecha']
        clima['Sensor'] = row['Sensor']
        climas.append(clima)

    df_clima = pd.DataFrame(climas)

    # Asegurar tipo datetime para merge e interpolación
    faltantes_total['Fecha'] = pd.to_datetime(faltantes_total['Fecha'])
    df_clima['Fecha'] = pd.to_datetime(df_clima['Fecha'])

    resultado = pd.merge(faltantes_total, df_clima, on=['Fecha', 'Sensor'], how='left')
    resultado = resultado.sort_values(['Sensor', 'Fecha']).reset_index(drop=True)
    resultado.set_index('Fecha', inplace=True)

    # Interpolar valores faltantes por sensor y fecha
    for col in ['precipitacion_mm', 'viento_max_kmh', 'temperatura_max']:
        resultado[col] = resultado.groupby('Sensor')[col].transform(
            lambda x: x.interpolate(method='time').ffill().bfill()
        )

    resultado.reset_index(inplace=True)

    output_excel_path = os.path.join(upload_folder, 'faltantes_resultado.xlsx')

    try:
        with pd.ExcelWriter(output_excel_path, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='Original', index=False)
            resultado.to_excel(writer, sheet_name='Completados', index=False)

            # Crear df_completado: DataFrame original con valores faltantes completados
            df_completado = df.copy()
            for _, row in resultado.iterrows():
                fecha = row['Fecha']
                sensor = row['Sensor']
                valor = row['precipitacion_mm']
                if pd.notna(valor):
                    df_completado.loc[df_completado['Fecha'] == fecha, sensor] = valor

            df_completado.to_excel(writer, sheet_name='Completado_Filas', index=False)

        print(f"Archivo Excel guardado correctamente en {output_excel_path}")
    except Exception as e:
        print("Error al guardar el archivo Excel de resultados:", e)
        traceback.print_exc()

    datos = resultado.to_dict(orient='records')
    return render_template('resultado.html', datos=datos)


@app.route('/descargar_faltantes')
def descargar_faltantes():
    upload_folder = os.path.abspath(app.config.get('UPLOAD_FOLDER', 'uploads'))
    file_path = os.path.join(upload_folder, 'faltantes_resultado.xlsx')
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True, download_name="faltantes_clima.xlsx")
    else:
        return 'Archivo no encontrado. Por favor, genera el reporte primero.', 404


if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    app.run(debug=True, port=5001)
