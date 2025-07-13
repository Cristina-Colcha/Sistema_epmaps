import pandas as pd
import requests
from datetime import datetime
from flask import Flask, render_template
from tqdm import tqdm
import os

app = Flask(__name__)

LAT = -0.481
LON = -78.141
TIMEZONE = 'America/Guayaquil'

def consultar_clima(fecha, lat=LAT, lon=LON):
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
        return {
            "precipitacion_mm": data['daily']['precipitation_sum'][0],
            "viento_max_kmh": data['daily']['windspeed_10m_max'][0],
            "temperatura_max": data['daily']['temperature_2m_max'][0]
        }
    except Exception as e:
        return {
            "precipitacion_mm": None,
            "viento_max_kmh": None,
            "temperatura_max": None
        }

@app.route('/')
def index():
    excel_path = 'uploads/Precipitacion_Mensual__P42_P43_P5522062025222139.xlsx'
    df = pd.read_excel(excel_path)
    df['Fecha'] = pd.to_datetime(df['Fecha'], dayfirst=True)

    sensores = ['P42', 'P43', 'P55']
    fechas_faltantes = []

    for sensor in sensores:
        faltantes = df[df[sensor].isna()][['Fecha']].copy()
        faltantes['Sensor'] = sensor
        fechas_faltantes.append(faltantes)

    faltantes_total = pd.concat(fechas_faltantes).reset_index(drop=True)

    climas = []
    for _, row in tqdm(faltantes_total.iterrows(), total=len(faltantes_total)):
        clima = consultar_clima(row['Fecha'])
        clima['Fecha'] = row['Fecha']
        clima['Sensor'] = row['Sensor']
        climas.append(clima)

    df_clima = pd.DataFrame(climas)
    resultado = pd.merge(faltantes_total, df_clima, on=['Fecha', 'Sensor'])

    # Convertimos el DataFrame a una lista de diccionarios para el template
    datos = resultado.to_dict(orient='records')

    return render_template('resultado.html', datos=datos)

if __name__ == '__main__':
    app.run(debug=True, port=5001)
