import os
import csv
import math
import datetime
import requests
import pandas as pd
import plotly.express as px
from flask import Flask, render_template, request
from functools import lru_cache

app = Flask(__name__)

# --- Constants ---
SOLAR_CONSTANT = 1367  # W/m²
REGION_FILE = r'csv/india_regions.csv'
USER_QUERIES_FILE = r'csv/User_Query.csv'
TOP_REGIONS_FILE = r'csv/TOP_10_REGIONS.csv'

os.makedirs('csv', exist_ok=True)

# Use a requests session
session = requests.Session()
session.headers.update({"User-Agent": "SolarEnergyApp/1.0"})

# --- Solar Calculations ---
def declination_angle(n):
    return 23.45 * math.sin(math.radians(360 * (284 + n) / 365))

def daylight_hours(latitude, decl):
    lat_rad = math.radians(latitude)
    decl_rad = math.radians(decl)
    try:
        ha = math.acos(-math.tan(lat_rad) * math.tan(decl_rad))
        return (2 * ha * 180 / math.pi) / 15
    except ValueError:
        return 0

def solar_intensity(cloud_cover):
    return round(SOLAR_CONSTANT * (1 - cloud_cover / 100), 2)

def calculate_energy(intensity, daylight):
    """
    intensity: W/m²
    daylight: hours of sunlight
    returns: energy in kWh per m² per day
    """
    # Energy in Wh/m²
    energy_wh = intensity * daylight  # 1 W × 1 hour = 1 Wh
    # Convert to kWh/m²
    energy_kwh = energy_wh / 1000
    return round(energy_kwh, 3)

# --- API Calls ---
@lru_cache(maxsize=512)
def get_weather_data(lat_rounded, lon_rounded):
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat_rounded}&longitude={lon_rounded}&hourly=cloudcover&current_weather=true"
        res = session.get(url, timeout=8)
        res.raise_for_status()
        data = res.json()
        temp = data.get("current_weather", {}).get("temperature", 25)
        clouds_list = data.get("hourly", {}).get("cloudcover", [0])
        clouds = sum(clouds_list)/len(clouds_list) if clouds_list else 0
        return temp, clouds
    except:
        return 25, 0

@lru_cache(maxsize=512)
def get_region_name_from_coords(lat_rounded, lon_rounded):
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat_rounded}&lon={lon_rounded}&zoom=10"
        res = session.get(url, timeout=8)
        res.raise_for_status()
        data = res.json()
        addr = data.get("address", {})
        return addr.get("city") or addr.get("town") or addr.get("village") or addr.get("state") or "Unknown"
    except:
        return "Unknown"

def read_regions(file_path):
    regions = []
    if os.path.exists(file_path):
        with open(file_path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    regions.append({
                        "region": row["region"],
                        "latitude": float(row["latitude"]),
                        "longitude": float(row["longitude"])
                    })
                except:
                    continue
    return regions

def process_and_save_top_regions():
    today = datetime.date.today()
    now = datetime.datetime.now().strftime("%H:%M:%S")
    n = today.timetuple().tm_yday
    decl = declination_angle(n)
    regions = read_regions(REGION_FILE)
    results = []
    for r in regions:
        lat = r["latitude"]
        lon = r["longitude"]
        temp, clouds = get_weather_data(round(lat,4), round(lon,4))
        daylight = daylight_hours(lat, decl)
        intensity = solar_intensity(clouds)
        energy = calculate_energy(intensity, daylight)
        results.append({
            "region": r["region"],
            "date": str(today),
            "time": now,
            "temp": temp,
            "cloud": round(clouds,2),
            "intensity": intensity,
            "daylight": round(daylight,2),
            "energy": energy
        })
    df = pd.DataFrame(results)
    if not df.empty:
        df = df.sort_values(by='energy', ascending=False).head(10)
        df.to_csv(TOP_REGIONS_FILE, index=False, encoding='utf-8')
    return df

def generate_graphs(df):
    graphs = {}

    corr_matrix = df[['temp','cloud','intensity','daylight','energy']].corr()
    fig_corr = px.imshow(corr_matrix, text_auto=True, color_continuous_scale='Viridis', title="Correlation Heatmap")
    graphs['Correlation Heatmap'] = fig_corr.to_html(full_html=False)

    fig_energy_city = px.bar(df, x='region', y='energy', text='energy', color='energy', color_continuous_scale='Plasma', title="Top 10 Cities by Energy")
    fig_energy_city.update_traces(marker_line_color='black', marker_line_width=1.5, textposition='outside')
    graphs['Top Cities by Energy'] = fig_energy_city.to_html(full_html=False)

    fig_energy_temp = px.scatter(df, x='temp', y='energy', size='daylight', color='cloud', color_continuous_scale='Viridis', hover_name='region', title="Energy vs Temperature")
    graphs['Energy vs Temperature'] = fig_energy_temp.to_html(full_html=False)

    fig_cloud_effect = px.line(df.sort_values('cloud'), x='cloud', y='energy', markers=True, title="Cloud Cover Effect on Energy")
    graphs['Cloud Cover Effect'] = fig_cloud_effect.to_html(full_html=False)

    fig_daylight_energy = px.scatter(df, x='daylight', y='energy', size='temp', color='intensity', color_continuous_scale='Cividis', hover_name='region', title="Daylight vs Energy")
    graphs['Daylight vs Energy'] = fig_daylight_energy.to_html(full_html=False)

    return graphs

# --- Flask Route ---
@app.route("/", methods=["GET","POST"])
def index():
    result = None
    top_regions_df = None
    graphs = {}
    if request.method=="POST":
        try:
            latitude = float(request.form.get("latitude",""))
            longitude = float(request.form.get("longitude",""))
        except:
            latitude = longitude = None

        if latitude is None or longitude is None:
            result = {"error":"Please enter valid latitude and longitude or allow location access."}
        else:
            region = request.form.get("region") or get_region_name_from_coords(round(latitude,4), round(longitude,4))
            today = datetime.date.today()
            n = today.timetuple().tm_yday
            decl = declination_angle(n)
            daylight = daylight_hours(latitude, decl)
            temp, cloud_cover = get_weather_data(round(latitude,4), round(longitude,4))
            intensity = solar_intensity(cloud_cover)
            energy_output = calculate_energy(intensity, daylight)
            result = {
                "region": region,
                "date": today,
                "time": datetime.datetime.now().strftime("%H:%M:%S"),
                "temp": temp,
                "cloud": round(cloud_cover,2),
                "intensity": intensity,
                "daylight": round(daylight,2),
                "energy": energy_output
            }
            # Save user query
            write_header = not os.path.exists(USER_QUERIES_FILE)
            with open(USER_QUERIES_FILE,'a',newline='',encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=result.keys())
                if write_header: writer.writeheader()
                writer.writerow(result)
            # Top 10 regions
            top_regions_df = process_and_save_top_regions()
            if top_regions_df is not None and not top_regions_df.empty:
                graphs = generate_graphs(top_regions_df)

    return render_template("index.html",
                           result=result,
                           top_regions=top_regions_df.to_html(classes="table-auto") if top_regions_df is not None else "",
                           graphs=graphs)

if __name__=="__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
