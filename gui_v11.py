import os
import math
import threading
import random
import itertools
import json
import csv
import tkinter as tk
from tkinter import messagebox, ttk, filedialog

import ttkbootstrap as tb
from ttkbootstrap.constants import *
from tkintermapview import TkinterMapView
from docplex.mp.model import Model
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import requests, json   # en üstteki import bloğuna ekleyebilirsiniz

# Sabit parametreler
AVG_CONSUMPTION_PER_EV = 8  # kWh / gün (ortalama günlük tüketim)
POI_COLOR = {
    "Home":   "#ffc107",   # sarı  (eskiden yeşildi)
    "Parking":"#fd7e14",   # turuncu
    "Fuel":   "#007bff"    # mavi
}
SELECTED_HOME_COLOR   = "#17a2b8"   # turkuaz
SELECTED_STATION_COLOR = "#6f42c1"  # mor

POI_TYPE_NUM = {"Home": 1, "Parking": 2, "Fuel": 3}
POI_FIXED_COST = {"Home": 1, "Parking": 12, "Fuel": 50}  # k€ sabit kurulum maliyeti

# ≤ kalan SOC eşiği; altına düşülürse 'divert_to_charger' çağrılır
MIN_SOC_KWH = 30

# Gün içi yolculuk sayısı için aralık (dahil)
TRIP_PER_EV_RANGE = (1, 5)

SEED_CONST = 123   

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = map(math.radians, (lat1, lat2))
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.asin(math.sqrt(a))

def road_distance_km(lat1, lon1, lat2, lon2):
    """
    OSRM ↔ gerçek yol mesafesi (km).
    Servis erişilemezse otomatik haversine’e döner.
    """
    try:
        url = (f"https://router.project-osrm.org/route/v1/driving/"
               f"{lon1},{lat1};{lon2},{lat2}?overview=false")
        res = requests.get(url, timeout=5).json()
        return res["routes"][0]["distance"] / 1000   # m → km
    except Exception:
        # ağ hatası, kota, vs.
        return haversine(lat1, lon1, lat2, lon2)

class Vehicle:
    def __init__(self):
        self.brand = "Generic"
        self.battery_capacity = 0  # kWh
        self.charge_rate = 0       # kW
        self.consumption_rate = 0  # kWh/km

    def remaining_range(self, consumed):
        return max(self.battery_capacity - consumed, 0)

class Renault(Vehicle):
    def __init__(self):
        super().__init__()
        self.brand = "Renault"
        self.battery_capacity = 40
        self.charge_rate = 22
        self.consumption_rate = 0.15

class Ford(Vehicle):
    def __init__(self):
        super().__init__()
        self.brand = "Ford"
        self.battery_capacity = 50
        self.charge_rate = 50
        self.consumption_rate = 0.18

class Tesla(Vehicle):
    def __init__(self):
        super().__init__()
        self.brand = "Tesla"
        self.battery_capacity = 75
        self.charge_rate = 120
        self.consumption_rate = 0.20

class Nissan(Vehicle):
    def __init__(self):
        super().__init__()
        self.brand = "Nissan"
        self.battery_capacity = 60
        self.charge_rate = 50
        self.consumption_rate = 0.16

class ChargingStationOptimizer:
    def __init__(self):
        # Ana pencere
        self.root = tb.Window(themename='flatly')
        self.root.title("EV Charging Station Planner")
        self.root.geometry("1300x800")

        # Home & station listeleri
        self.home_poi = []
        self.station_candidates = []
        self.selected_homes = []
        self.selected_stations = []

        # Sonuç değişkenleri
        self.cost_var = tk.StringVar(master=self.root, value="0")
        self.semi_var = tk.StringVar(master=self.root, value="0")
        self.fast_var = tk.StringVar(master=self.root, value="0")
        self.chargers_var = tk.StringVar(master=self.root, value="0")
        self.energy_var = tk.StringVar(master=self.root, value="0")
        self.solution_obj = 0.0

        # Grafik altyapısı
        self.figure = plt.Figure(figsize=(5,3), dpi=100)
        self.ax = self.figure.add_subplot(111)
        self.chart = None

        # PanedWindow ile sol kontrol / sağ harita
        paned = tb.PanedWindow(self.root, orient=HORIZONTAL)
        paned.pack(fill=BOTH, expand=YES)

        ctrl = tb.Frame(paned, padding=10)
        paned.add(ctrl, weight=1)
        self._build_controls(ctrl)

        map_frame = tb.Frame(paned, padding=10)
        paned.add(map_frame, weight=4)
        self._build_map(map_frame)

        # Status bar
        self.status_var = tk.StringVar(master=self.root, value="Ready")
        tb.Label(self.root, textvariable=self.status_var,
                 bootstyle="secondary").pack(side=BOTTOM, fill=X)

    def _build_controls(self, parent):
        params = [
            ("EV Penetration Rate (%)", 'ev_rate', 0, 100, 20),
            ("Min Radius (m)",           'radius', 200, 5000, 1000),
            ("Max Stations",             'max_st', 1,   50,   15),
            ("Station Capacity (kWh/day)", 'capacity', 10,1000,50),
        ]
        for i, (label, var, low, high, val) in enumerate(params):
            tb.Label(parent, text=label, font=("Segoe UI",10,"bold"))\
              .grid(row=i*2, column=0, sticky=W, pady=(5,0))
            setattr(self, f"{var}_var",
                    tk.IntVar(master=self.root, value=val))
            setattr(self, f"{var}_disp",
                    tk.StringVar(master=self.root, value=str(val)))
            tb.Label(parent, textvariable=getattr(self,f"{var}_disp"))\
              .grid(row=i*2, column=1, sticky=E)
            tb.Scale(parent,
                     from_=low, to=high,
                     orient=HORIZONTAL,
                     variable=getattr(self,f"{var}_var"),
                     command=lambda v,n=var: getattr(self,f"{n}_disp").set(str(int(float(v)))))\
              .grid(row=i*2+1, column=0, columnspan=2, sticky=EW)

        tb.Label(parent, text="Solution Method", font=("Segoe UI",10,"bold"))\
          .grid(row=10, column=0, sticky=W, pady=(10,0))
        self.method_combo = tb.Combobox(parent,
                                        values=["Docplex MIP", "Genetic Algorithm"],
                                        state="readonly")
        self.method_combo.current(0)
        self.method_combo.grid(row=11, column=0, columnspan=2, sticky=EW)

        tb.Label(parent, text="Location Type", font=("Segoe UI",10,"bold"))\
          .grid(row=12, column=0, sticky=W, pady=(10,0))
        self.poi_type = tb.Combobox(parent,
                             values=list(POI_TYPE_NUM.keys()),
                             state="readonly")
        self.poi_type.current(0)
        self.poi_type.grid(row=13, column=0, columnspan=2, sticky=EW)

        tb.Button(parent, text="Load HOME Points", bootstyle="primary",
                  command=self.load_homes)\
          .grid(row=14, column=0, columnspan=2, sticky=EW, pady=(10,2))
        tb.Button(parent, text="Run Optimization", bootstyle="success",
                  command=self.run_optimization)\
          .grid(row=15, column=0, columnspan=2, sticky=EW, pady=(2,2))
        tb.Button(parent, text="Clear Map", bootstyle="warning",
                  command=self.clear_map)\
          .grid(row=16, column=0, columnspan=2, sticky=EW, pady=2)
        tb.Button(parent, text="Show Results", bootstyle="info",
                  command=self.open_results_window)\
          .grid(row=17, column=0, columnspan=2, sticky=EW, pady=(2,10))
        parent.rowconfigure(18, weight=1)       #  ←  tüm boş alanı doldurur
        tb.Button(parent, text="Color Legend", bootstyle="secondary",
                  command=self.show_legend) \
          .grid(row=19, column=0, columnspan=2, sticky="ew", pady=(0,12))
        # _build_controls(...) sonuna –“Color Legend”in hemen altına– ekle
        tb.Button(parent, text="Show Heat-Map", bootstyle="danger",
                command=self.build_heatmap)\
        .grid(row=20, column=0, columnspan=2, sticky="ew", pady=(0,12))


    def show_legend(self):
        # ---- icon definitions ----
        legend_items = [
            ("green",    "Green  : Home / Vehicle location"),
            ("#ffc107",  "Yellow : Home-type station candidate"),
            ("#fd7e14",  "Orange : Parking-type station candidate"),
            ("#007bff",  "Blue   : Fuel-type (fast) candidate"),
            ("#17a2b8",  "Turquoise: Selected EV"),
            ("#6f42c1",  "Purple : Selected station"),
        ]

        top = tk.Toplevel(self.root)
        top.title("Marker Color Legend")
        top.resizable(False, False)
        top.configure(padx=15, pady=15)

        # title
        tb.Label(top, text="Marker Color Legend",
                font=("Segoe UI", 11, "bold")).pack(pady=(0,10))

        for col, title, desc in [
                ("green",   "Green",    "Home / Vehicle location"),
                ("#ffc107", "Yellow",   "Home-type station candidate"),
                ("#fd7e14", "Orange",   "Parking-type station candidate"),
                ("#007bff", "Blue",     "Fuel-type (fast) candidate"),
                ("#17a2b8", "Turquoise","Selected EV"),
                ("#6f42c1", "Purple",   "Selected station"),
        ]:
            row = tb.Frame(top); row.pack(anchor="w", pady=2)


            # ► renkli yuvarlak
            icon = tk.Canvas(row, width=14, height=14, highlightthickness=0)
            icon.pack(side="left")
            icon.create_oval(2, 2, 12, 12, fill=col, outline=col)

            # ► başlık sütunu (genişlik sabit → ':' hizalı görünür)
            tb.Label(row, text=f" {title}", width=9, anchor="w",
                    font=("Segoe UI", 9, "bold")).pack(side="left")

            # ► açıklama sütunu (':' ile birlikte)
            tb.Label(row, text=f": {desc}", anchor="w",
                    font=("Segoe UI", 9)).pack(side="left", padx=(0,4))

        # kapat düğmesi
        tb.Button(top, text="OK", bootstyle="success",
                  command=top.destroy).pack(pady=(10,0))

        # odak ve modal-benzeri davranış
        top.transient(self.root)
        top.grab_set()
        self.root.wait_window(top)

    def osrm_route(self, p1, p2):
        """
        Origin-dest (lat,lon)->(lat,lon) ikilisi için
        OSRM’dan sadeleştirilmiş polyline (koordinat listesi) döner.
        Servise ulaşılamazsa iki nokta arası düz çizgi verir.
        """
        try:
            url = (f"https://router.project-osrm.org/route/v1/driving/"
                f"{p1[1]},{p1[0]};{p2[1]},{p2[0]}?overview=full&geometries=geojson")
            geom = requests.get(url, timeout=5).json()["routes"][0]["geometry"]["coordinates"]
            # geojson -> [(lat,lon), ...]
            return [(lat, lon) for lon, lat in geom]
        except Exception:
            return [p1, p2]

    def _build_map(self, parent):
        frame = tb.LabelFrame(parent, text="Map View")
        frame.pack(fill=BOTH, expand=YES)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        self.map_widget = TkinterMapView(frame, corner_radius=0)
        self.map_widget.grid(row=0, column=0, sticky="nsew")
        self.map_widget.set_position(41.0082, 28.9784)
        self.map_widget.set_zoom(12)
        self.map_widget.add_left_click_map_command(self.on_map_click)

    def generate_daily_trips(self, rng_seed=None):
        """
        Her seçilen EV’e TRIP_PER_EV_RANGE kadar yolculuk atar;
        • trip_no  : EV-özel sayaç   (1,2,…)
        • seq      : gün-içi global sıra (opsiyonel, raporlamak isterseniz)
        """
        if rng_seed is not None:
            random.seed(rng_seed)

        self.trip_log = []
        global_seq = 0                    # gün içi kronolojik sıra

        for i, sh in enumerate(self.selected_homes):
            ev_id   = f"E{i+1:02d}"
            v       = sh["vehicle"]
            soc     = v.battery_capacity
            origin  = (sh["home"]["lat"], sh["home"]["lon"])

            n_trips = random.randint(*TRIP_PER_EV_RANGE)
            trip_no = 1                   # --> EV’ye özgü sayaç

            while trip_no <= n_trips:
                # 1️⃣ HEDEF SEÇ – mevcut konumdan FARKLI olana kadar döngü
                while True:
                    dest_home = random.choice(self.home_poi)
                    dest      = (dest_home["lat"], dest_home["lon"])
                    if dest != origin:            # aynı koordinatsa yenisini dene
                        break

                # 2️⃣ MESAFE + TÜKETİM
                dist_km  = self.osrm_or_haversine(origin, dest)
                cons_kwh = round(dist_km * v.consumption_rate, 2)
                soc     -= cons_kwh

                diverted, charger_id = False, ""
                if soc < MIN_SOC_KWH:
                    diverted = True
                    nearest  = self.divert_to_charger({"lat": origin[0], "lon": origin[1]})
                    charger_id = nearest["tag"]
                    extra_dist = self.osrm_or_haversine(origin, (nearest["lat"], nearest["lon"]))
                    soc -= round(extra_dist * v.consumption_rate, 2)
                    soc  = v.battery_capacity       # “şarj oldu” kabulü

                # 3️⃣ LOG
                global_seq += 1
                self.trip_log.append({
                    "seq"       : global_seq,        # kronolojik (isterseniz)
                    "trip_no"   : trip_no,           # EV-özel 1…n
                    "ev_id"     : ev_id,
                    "origin"    : origin,
                    "dest"      : dest,
                    "origin_lbl": self.poi_label(*origin),
                    "dest_lbl"  : self.poi_label(*dest),
                    "dist_km"   : round(dist_km, 2),
                    "cons_kwh"  : cons_kwh,
                    "rem_soc"   : round(soc, 2),
                    "diverted"  : diverted,
                    "charger_id": charger_id
                })

                # 4️⃣ Sonraki yolculuk için güncelle
                origin   = dest
                trip_no += 1

    def build_edge_counts(self):
        """
        self.trip_log kullanarak yol segmentleri üzerinde kullanım
        sayımlarını üretir: {(lat1,lon1,lat2,lon2): count, ...}
        """
        self.edge_freq = {}
        for rec in self.trip_log:
            path = self.osrm_route(rec["origin"], rec["dest"])
            for a, b in zip(path, path[1:]):
                # yönsüz hash – ( A,B ) ile ( B,A ) aynı olsun
                key = tuple(sorted((a, b)))
                self.edge_freq[key] = self.edge_freq.get(key, 0) + 1

    def _haversine_demand(self):
        """Eski (basit) yöntem: her EV kendi evinden tüm diğer EV evlerine
        Haversine mesafesi kat edip geri dönecekmiş gibi toplam tüketim."""
        D = []
        n = len(self.selected_homes)
        for i in range(n):
            v_i  = self.selected_homes[i]['vehicle']
            h_i  = self.selected_homes[i]['home']
            total = 0
            for j in range(n):
                if i == j:             # kendisi → atla
                    continue
                h_j = self.selected_homes[j]['home']
                dist = haversine(h_i['lat'], h_i['lon'], h_j['lat'], h_j['lon'])
                total += dist * v_i.consumption_rate     # kWh
            D.append(round(total, 2))
        return D           # uzunluk = #EV

    def poi_label(self, lat, lon):
        """ Verilen koordinat ev veya istasyona aitse okunur bir
            etiket (H12, S03-Parking …) döndürür; yoksa '' """
        for h in self.home_poi:
            if abs(h['lat']-lat) < 1e-6 and abs(h['lon']-lon) < 1e-6:
                return f"H{h['id']:02d}"
        for s in self.station_candidates:
            if abs(s['lat']-lat) < 1e-6 and abs(s['lon']-lon) < 1e-6:
                return s['tag']
        return ''

    def osrm_or_haversine(self, p1, p2):
        """OSRM varsa gerçek yol uzunluğu, aksi hâlde haversine (km)."""
        try:
            import requests
            url = (f"http://router.project-osrm.org/route/v1/driving/"
                f"{p1[1]},{p1[0]};{p2[1]},{p2[0]}?overview=false")
            r = requests.get(url, timeout=5).json()
            return r["routes"][0]["distance"] / 1000.0  # m → km
        except Exception:
            return haversine(p1[0], p1[1], p2[0], p2[1])

    def load_homes(self):
        path = filedialog.askopenfilename(
            title="Select Home POI JSON/CSV",
            filetypes=[("JSON files", "*.json"), ("CSV files", "*.csv")]
        )
        if not path:
            return
        try:
            loaded = []
            if path.endswith('.json'):
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for pt in data:
                    loaded.append({'lat': pt['lat'], 'lon': pt['lon']})
            else:
                with open(path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        loaded.append({'lat': float(row['lat']), 'lon': float(row['lon'])})
            self.home_poi = loaded

            # Haritayı home'ların ilkine kaydır
            if self.home_poi:
                first = self.home_poi[0]
                self.map_widget.set_position(first['lat'], first['lon'])
                self.map_widget.set_zoom(14)

            # Marker'ları temizle
            self.map_widget.delete_all_marker()

            # Evleri numaralandırarak ekle; tıklayınca araç bilgisini göster
            for idx, h in enumerate(self.home_poi, start=1):
                h['id'] = idx  
                def show_info(marker=None, home=h, num=idx):
                    veh = next((sh['vehicle'] for sh in self.selected_homes if sh['home']==home), None)
                    if veh:
                        marker.set_text(f"{veh.brand}\n{veh.battery_capacity} kWh\n{veh.charge_rate} kW")
                    else:
                        marker.set_text(str(num))

                m = self.map_widget.set_marker(
                    h['lat'], h['lon'],
                    text=str(idx),
                    marker_color_circle="green",
                    marker_color_outside="white",
                    command=show_info
                )

            self.status_var.set(f"{len(self.home_poi)} home points loaded.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load homes: {e}")

    def on_map_click(self, coords):
        # Maximum candidate control
        if len(self.station_candidates) >= self.max_st_var.get():
            messagebox.showwarning("Limit Reached",
                                   f"You can add up to {self.max_st_var.get()} candidates.")
            return

        lat, lon = coords
        # Min-radius control
        r = self.radius_var.get()
        for c in self.station_candidates:
            if haversine(lat, lon, c['lat'], c['lon']) * 1000 < r:
                messagebox.showwarning("Too Close",
                                       f"New point is closer than {r} m to an existing candidate.")
                return


        # Adayı kaydet

        poi = self.poi_type.get()
        idx = len(self.station_candidates) + 1        # 1-den başlayan sıra
        tag = f"S{idx:02d}-{poi}"                     # ör. S01-Parking
        self.station_candidates.append({
            'id' : idx,       #  <-- kaydet
            'tag': tag,       #  <--
            'lat': lat,
            'lon': lon,
            'poi': poi
        })

        color = POI_COLOR[poi]
        m = self.map_widget.set_marker(
            lat, lon,
            text=tag,
            marker_color_circle=color,
            marker_color_outside="white"
        )
        m.set_text(f"{tag}\nFixed Cost: {POI_FIXED_COST[poi]} k€")
        self.status_var.set(f"Added station candidate {tag} ({lat:.4f}, {lon:.4f})")

    def _update_markers(self):
        self.map_widget.delete_all_marker()

        # ------------------ 1) EVLER ------------------
        for idx, h in enumerate(self.home_poi, start=1):
            is_selected = any(sh['home'] is h for sh in self.selected_homes)

            color = "#17a2b8" if is_selected else "green"      # turkuaz / yeşil
            label = str(h.get('id', idx))                      # H-ID

            self.map_widget.set_marker(
                h['lat'], h['lon'],
                text=label,
                marker_color_circle=color,
                marker_color_outside="white"
            )

        # ------------ 2) İSTASYON ADAYLARI -------------
        for idx, c in enumerate(self.station_candidates, start=1):
            tag   = c['tag']                     # “S02-Parking” vb.
            base  = POI_COLOR[c['poi']]          # sarı / turuncu / mavi
            is_sel = any(
                abs(s['lat'] - c['lat']) < 1e-6 and
                abs(s['lon'] - c['lon']) < 1e-6
                for s in self.selected_stations
            )

            color = "#6f42c1" if is_sel else base  # mor  ya da  POI rengi

            self.map_widget.set_marker(
                c['lat'], c['lon'],
                text=tag,
                marker_color_circle=color,
                marker_color_outside="white"
            )

    def ensure_selected_homes(self, evr, seed=None):
        if self.selected_homes:
            return                    # zaten seçildiyse dokunma

        if seed is not None:
            random.seed(seed)         # ① rastgeleliği kilitle

        k = max(1, int(len(self.home_poi)*evr/100))
        sampled = random.sample(self.home_poi, k)

        self.selected_homes = [
            {"home": h,
            "vehicle": random.choice([Renault, Ford, Tesla, Nissan])()}
            for h in sampled
        ]

    def run_optimization(self):
        if not self.home_poi or not self.station_candidates:
            messagebox.showinfo("Info", "Add home and station candidate points.")
            return

        method  = self.method_combo.get()
        evr     = self.ev_rate_var.get()

        self.ensure_selected_homes(evr, seed=SEED_CONST)

        self.generate_daily_trips()
        self.build_edge_counts() 

        for rec in self.trip_log:
            print(rec)
        print("-"*40, f"{len(self.trip_log)} trips recorded\n")
        
        print(f"[Trip-based demand] Total of {sum(r['cons_kwh'] for r in self.trip_log):.2f} kWh "
              f"from {len(self.trip_log)} trips")

        # her iki yöntem de aynı D_i’yi kullanacak

        if method == "Docplex MIP":
            target = self._solve_model
        else:                                       # GA
            target = self._solve_ga

        max_st  = self.max_st_var.get()
        capacity= self.capacity_var.get()
        radius  = self.radius_var.get()

        self.status_var.set("Building & solving model...")
        threading.Thread(target=target,
                        args=(max_st, evr, capacity, radius),
                        daemon=True).start()

    def build_heatmap(self):
        """
        edge_freq’e bakarak haritada renkli çizgiler oluşturur.
        Düşük yoğunluk yeşil, yüksek kırmızı.
        """
        if not hasattr(self, "edge_freq") or not self.edge_freq:
            messagebox.showinfo("Info", "Run the optimization first to generate trips.")
            return

        # yoğunluk aralıklarını belirle
        max_cnt = max(self.edge_freq.values())
        def edge_color(cnt):
            ratio = cnt / max_cnt
            if ratio > 0.75:  return "#dc3545"   # kırmızı
            if ratio > 0.50:  return "#fd7e14"   # turuncu
            if ratio > 0.25:  return "#ffc107"   # sarı
            return "#28a745"                    # yeşil

        # Önce eski heat-map çizgilerini temizleyelim (varsa)
        if hasattr(self, "_heat_lines"):
            for line in self._heat_lines:
                line.delete()
        self._heat_lines = []

        # Her segment için map’te polyline
        for (a, b), cnt in self.edge_freq.items():
            line = self.map_widget.set_path([a, b], color=edge_color(cnt), width=4, name="heat")
            self._heat_lines.append(line)

        self.status_var.set("Heat-map drawn (green → red)")

    def divert_to_charger(self, home):
        min_dist = float('inf'); nearest=None
        for c in self.station_candidates:
            d = road_distance_km(home['lat'], home['lon'], c['lat'], c['lon'])
            if d < min_dist:
                min_dist = d; nearest=c
        return nearest

    def debug_od(self, selected_homes, station_candidates, d_mat, export_csv=False):
            """
            Seçilen EV-ler ile istasyon adayları arasındaki mesafeleri
            ve enerji/SOC tablolarını terminale (ve opsiyonel CSV’ye) döker.
            """
            import csv, pprint, time
            I = range(len(selected_homes))
            J = range(len(station_candidates))

            print("\n----- OD DISTANCE MATRIX (km) -----")
            header = ["EV\\ST"] + [sc['tag'] for sc in station_candidates]

            # 1️⃣ Başlık (tamamı string) – her sütun 8 karakter hizalı
            print(("{:>8}" * (len(header))).format(*header))

            # 2️⃣ Veri satırları – ilk hücre metin, geri kalanı sayı (.2f)
            row_fmt = "{:>8}" + " {:>8.2f}" * len(J)
            for i in I:
                print(row_fmt.format(
                    f"E{i+1:02d}",
                    *[d_mat[i][j] for j in J]
                ))


            # enerji & SOC ayrıntısı (isteğe bağlı)
            table = []
            for i, sh in enumerate(selected_homes):
                v  = sh['vehicle']
                row = {"EV": f"E{i+1:02d}", "Brand": v.brand,
                    "Batt(kWh)": v.battery_capacity}
                for j, (sc, dist) in enumerate(zip(station_candidates, d_mat[i])):
                    cons = round(dist * v.consumption_rate, 2)
                    row[f"{sc['tag']} dist(km)"] = round(dist, 2)
                    row[f"{sc['tag']} cons(kWh)"] = cons
                    row[f"{sc['tag']} remSOC"]    = round(v.battery_capacity - cons, 2)
                table.append(row)

            pprint.pprint(table, width=150)

            if export_csv:
                fn = f"od_debug_{time.strftime('%Y%m%d_%H%M%S')}.csv"
                with open(fn, "w", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=table[0].keys())
                    w.writeheader(); w.writerows(table)
                print(f"... detailed table written to file '{fn}'.")
            
    def _solve_model(self, max_st, evr, capacity, radius):
        # 1) EV/araç örneklemesi gerekiyorsa yap
        if not self.selected_homes:
            self.ensure_selected_homes(evr)

        # ------------------------------------------------------------
        # 2) Artık self.selected_homes DOLU –> doğrudan kullanabiliriz
        I = list(range(len(self.selected_homes)))
        J = list(range(len(self.station_candidates)))

        # === Trip-based daily energy demand =================================
        # Eğer henüz trip üretmemişsek güvenlik amaçlı hemen üret
        if not getattr(self, "trip_log", []):
            self.generate_daily_trips()

        # D[i]  =  o EV’nin gün boyu tükettiği toplam kWh
        D = [0.0] * len(self.selected_homes)
        for rec in self.trip_log:
            ev_idx = int(rec["ev_id"][1:]) - 1          # "E01" → 0
            D[ev_idx] += rec["cons_kwh"]

        print(f"[Trip-based demand] Total of {sum(r['cons_kwh'] for r in self.trip_log):.2f} kWh "
              f"from {len(self.trip_log)} trips")                # DEBUG satırı
        # ====================================================================

        # Mesafe matrisi
        d = [[road_distance_km(self.selected_homes[i]['home']['lat'],
                            self.selected_homes[i]['home']['lon'],
                            self.station_candidates[j]['lat'],
                            self.station_candidates[j]['lon'])
            for j in J] for i in I]

        self.debug_od(self.selected_homes, self.station_candidates, d)
        
        # --- Docplex modeli -------------------------------------------------
        m = Model(name="ev_location_extended")
        x = {j: m.binary_var(name=f"x_{j}") for j in J}
        y = {(i, j): m.binary_var(name=f"y_{i}_{j}") for i in I for j in J}

        m.minimize(
            m.sum(POI_FIXED_COST[self.station_candidates[j]['poi']] * x[j] for j in J) +
            m.sum(D[i] * d[i][j] * y[i, j] for i in I for j in J)
        )

        for i in I:
            m.add_constraint(m.sum(y[i, j] for j in J) == 1)
            for j in J:
                m.add_constraint(y[i, j] <= x[j])
        for j in J:
            m.add_constraint(
                m.sum(D[i] * y[i, j] for i in I) <= capacity * x[j]
            )
        for j in J:
            for k2 in range(j + 1, len(J)):
                if road_distance_km(self.station_candidates[j]['lat'], self.station_candidates[j]['lon'],
                             self.station_candidates[k2]['lat'], self.station_candidates[k2]['lon']) * 1000 < radius:
                    m.add_constraint(x[j] + x[k2] <= 1)
        m.add_constraint(m.sum(x[j] for j in J) <= max_st)

        sol = m.solve(log_output=False)
        if not sol:
            self.status_var.set("Model çözülemedi.")
            return

        # --- Çözüm listeleri ------------------------------------------------
        self.selected_stations = [
            {
                'lat': pt['lat'],
                'lon': pt['lon'],
                'poi': pt['poi'],
                'type': pt['poi'],
                'tag': pt.get('tag', f"S{pt.get('id', j+1):02d}-{pt['poi']}")  # <-- EK
            }
            for j, pt in enumerate(self.station_candidates)
            if x[j].solution_value > 0.5
        ]

        self.solution_obj = m.objective_value

        # --- DEBUG: Ayrıntılı terminal raporu ------------------------------
        print("\n=== Selected Homes & Vehicles ===")
        for i, sh in enumerate(self.selected_homes, 1):
            h, v = sh['home'], sh['vehicle']
            hid  = h.get('id', '?')
            # bağlı istasyonu bul
            sel_j = next(j for j in J if y[i-1, j].solution_value > 0.5)
            st_rec = self.station_candidates[sel_j]
            print(f"E{i:02d} [H{hid:02d}]  ({h['lat']:.5f}, {h['lon']:.5f})  "
                  f"-> {v.brand:<6} {v.battery_capacity:>3}kWh  "
                  f"[{st_rec['tag']}]")

        print("\n=== Selected Stations ===")
        for st in self.selected_stations:
            print(f"{st['tag']}: ({st['lat']:.5f}, {st['lon']:.5f})")
        print("========================================================\n")

        # --- Harita & sonuç penceresi güncelle --------------------------------
        self.root.after(0, self._update_markers)
        self.root.after(0, self.open_results_window)
        self.status_var.set("Optimization completed.")

    def _solve_ga(self, max_st, evr, capacity, radius,
                pop_size=20, n_gen=15, cx_p=0.9, mut_p=0.1):

        if not self.selected_homes:
            self.ensure_selected_homes(evr)

        I = list(range(len(self.selected_homes)))
        J = list(range(len(self.station_candidates)))

        # ------------------------------------------------ 0) Talep
        D = self._haversine_demand()          # len(I)

        # ------------------------------------------- 1) EV→istasyon mesafesi
        d = [[road_distance_km(self.selected_homes[i]['home']['lat'],
                            self.selected_homes[i]['home']['lon'],
                            self.station_candidates[j]['lat'],
                            self.station_candidates[j]['lon'])
            for j in J] for i in I]

        # ------------------------------------------- 2) İstasyon–istasyon mesafesi (ÖNBELLEK)
        if (not hasattr(self, "_st_pair_dist") or
                len(self._st_pair_dist) != len(J)):           # boyut değiştiyse yeniden hesapla
            self._st_pair_dist = [
                [haversine(s1['lat'], s1['lon'], s2['lat'], s2['lon']) * 1000   # m
                for s2 in self.station_candidates]
                for s1 in self.station_candidates
            ]
        st_pair = self._st_pair_dist   # kısaltma

        # ------------------------------------------- GA yardımcıları
        def random_chrom():
            k_max = min(max_st, len(J))
            k_open = random.randint(1, k_max)
            ones = random.sample(J, k_open)
            return [1 if j in ones else 0 for j in J]

        def repair(ch):
            """Açık istasyon sayısı > max_st ise rastgele kapat."""
            ones = [j for j, v in enumerate(ch) if v]
            while len(ones) > max_st:
                ch[random.choice(ones)] = 0
                ones = [j for j, v in enumerate(ch) if v]
            return ch

        def fitness(ch):
            if sum(ch) == 0:
                return 1e9

            # 2.1 EV’ler en yakın açık istasyona atanıyor
            travel = 0
            for i in I:
                best_j = min((j for j in J if ch[j]), key=lambda j: d[i][j])
                travel += D[i] * d[i][best_j]

            # 2.2 Sabit kurulum maliyeti
            fixed = sum(POI_FIXED_COST[self.station_candidates[j]['poi']]
                        for j, v in enumerate(ch) if v)

            # 2.3 Radius ihlali CEZASI  (hav. + önbellek)
            penalty = 0
            open_idx = [j for j, v in enumerate(ch) if v]
            for a, b in itertools.combinations(open_idx, 2):
                if st_pair[a][b] < radius:          # metre cinsinden
                    penalty += 1e5                  # büyük ceza

            return fixed + travel + penalty

        # ------------------------------------------- 3) GA döngüsü
        pop  = [random_chrom() for _ in range(pop_size)]
        best = min(pop, key=fitness)

        for gen in range(n_gen):
            new_pop = []
            while len(new_pop) < pop_size:
                p1, p2 = random.sample(pop, 2)

                # --- Crossover
                if random.random() < cx_p:
                    cut = random.randint(1, len(J) - 2)
                    child = repair(p1[:cut] + p2[cut:])
                else:
                    child = p1[:]

                # --- Mutation
                if random.random() < mut_p:
                    m = random.randint(0, len(J) - 1)
                    child[m] ^= 1
                    child = repair(child)

                new_pop.append(child)

            # Elitizm
            pop  = sorted(new_pop, key=fitness)[:pop_size - 1] + [best]
            best = min(pop + [best], key=fitness)
            print(f"[GA] gen {gen+1}/{n_gen}  best = {fitness(best):.2f}")

        # ------------------------------------------- 4) Çözümü GUI’ye aktar
        self.selected_stations = [
            { 'lat': pt['lat'], 'lon': pt['lon'], 'poi': pt['poi'],
            'type': pt['poi'], 'tag': pt['tag'] }
            for j, pt in enumerate(self.station_candidates) if best[j]
        ]
        self.solution_obj = fitness(best)

        # EV-istasyon mesafe raporu
        self.debug_od(self.selected_homes,
                    self.selected_stations,
                    [[d[i][j] for j in [k for k, v in enumerate(best) if v]]
                    for i in I])

        self.root.after(0, self._update_markers)
        self.root.after(0, self.open_results_window)
        self.status_var.set("GA completed.")

    def open_results_window(self):
        win = tk.Toplevel(self.root)
        win.title("Results and Graphs")
        win.geometry("900x650")
        win.rowconfigure(0, weight=1); win.columnconfigure(0, weight=1)
        frm = tb.Frame(win, padding=10); frm.pack(fill=BOTH, expand=YES)

        # -------- Selected Stations ---------------------------------
        sf = tb.LabelFrame(frm, text="Selected Stations"); sf.pack(fill=X, pady=(0,10))
        scols = ("#", "S-ID", "POI", "Lat", "Lon")
        stree = ttk.Treeview(sf, columns=scols, show='headings')
        for c in scols:
            stree.heading(c, text=c); stree.column(c, anchor=CENTER)

        for i, s in enumerate(self.selected_stations, 1):
            stree.insert('', 'end', values=(
                i,               # sıra numarası
                s['tag'],        # S-ID  ->  S01-Home, S02-Parking ...
                s['poi'],        # POI   ->  Home / Parking / Fuel
                f"{s['lat']:.5f}",
                f"{s['lon']:.5f}"
            ))
        stree.pack(fill=X)

        # -------- Selected Homes & Vehicles -------------------------
        hf = tb.LabelFrame(frm, text="Selected Homes"); hf.pack(fill=X, pady=(0,10))
        hcols = ("#", "H-ID", "Lat", "Lon", "Vehicle", "Batt (kWh)", "Charge (kW)")
        htree = ttk.Treeview(hf, columns=hcols, show='headings', height=6)
        for c in hcols:
            htree.heading(c, text=c); htree.column(c, anchor=CENTER)

        for i, sh in enumerate(self.selected_homes, 1):
            h, v = sh['home'], sh['vehicle']
            htree.insert('', 'end', values=(
                i,                              # sıra #
                h.get('id', '?'),               # H-ID
                f"{h['lat']:.5f}",              # Lat
                f"{h['lon']:.5f}",              # Lon
                v.brand,                        # Vehicle
                v.battery_capacity,             # Batt
                v.charge_rate                   # Charge
            ))
        htree.pack(fill=X)

        # -------- Model Info ---------------------------------------
        info = tb.LabelFrame(frm, text="Model Info"); info.pack(fill=X, pady=(0,10))
        tb.Label(info, text=f"Objective Value: {self.solution_obj:.2f} k€").pack(anchor=W)
        tb.Label(info, text=f"#Station Candidates: {len(self.station_candidates)}").pack(anchor=W)
        tb.Label(info, text=f"#Selected Stations: {len(self.selected_stations)}").pack(anchor=W)
        tb.Label(info, text=f"#Selected Homes: {len(self.selected_homes)}").pack(anchor=W)

        # -------- Summary KPIs ------------------------------------
        summary = tb.LabelFrame(frm, text="Summary"); summary.pack(fill=X, pady=(0,10))
        semi = sum(1 for s in self.selected_stations if s['type']=="Parking")
        fast = sum(1 for s in self.selected_stations if s['type']=="Fuel")
        chargers = semi*4 + fast*2
        energy = int(sum(
            h['vehicle'].consumption_rate * road_distance_km(
                h['home']['lat'], h['home']['lon'], s['lat'], s['lon']
            ) for h in self.selected_homes for s in self.selected_stations
        ))
        self.cost_var.set(f"{self.solution_obj:.2f}")
        self.semi_var.set(str(semi)); self.fast_var.set(str(fast))
        self.chargers_var.set(str(chargers)); self.energy_var.set(str(energy))

        for lbl, var in [("Cost (k€)", self.cost_var),
                         ("Semi-fast CS", self.semi_var),
                         ("Fast CS", self.fast_var),
                         ("Chargers", self.chargers_var),
                         ("Energy (kWh)", self.energy_var)]:
            row = tb.Frame(summary); row.pack(fill=X, pady=2)
            tb.Label(row, text=lbl).pack(side=LEFT)
            tb.Label(row, textvariable=var).pack(side=RIGHT)

        # -------- Cost vs EV Rate Grafiği --------------------------
        cf = tb.LabelFrame(frm, text="Cost vs EV Rate"); cf.pack(fill=BOTH, expand=YES)
        chart_fr = tb.Frame(cf); chart_fr.pack(fill=BOTH, expand=YES)

        self.ax.clear()
        self.ax.plot([0, self.ev_rate_var.get()], [0, self.solution_obj], 'o-')
        self.ax.set_xlabel('EV Penetration (%)')
        self.ax.set_ylabel('Cost (k€)')
        self.ax.grid(True, linestyle='--', alpha=0.6)
        self.figure.tight_layout()

        if self.chart:
            self.chart.get_tk_widget().destroy()
        self.chart = FigureCanvasTkAgg(self.figure, master=chart_fr)
        self.chart.get_tk_widget().pack(fill=BOTH, expand=YES)
        self.chart.draw()

    def clear_map(self):
        self.map_widget.delete_all_marker()
        self.home_poi.clear(); self.station_candidates.clear()
        self.selected_homes.clear(); self.selected_stations.clear()
        self._update_markers()
        for v in [self.cost_var, self.semi_var, self.fast_var,
                  self.chargers_var, self.energy_var]: v.set("0")
        self.ax.clear()
        if hasattr(self, "_heat_lines"):
            for ln in self._heat_lines:
                ln.delete()
            del self._heat_lines
        if self.chart: self.chart.get_tk_widget().destroy()
        self.status_var.set("Map cleared")

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    app = ChargingStationOptimizer()
    app.run()
