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

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = map(math.radians, (lat1, lat2))
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.asin(math.sqrt(a))

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
            ("EV Penetration Rate (%)", 'ev_rate', 1, 20, 10),
            ("Simultaneous RNV (%)",     'rnv_rate', 10, 100, 50),
            ("Min Radius (m)",           'radius', 200, 5000, 1000),
            ("Max Stations",             'max_st', 1,   50,   15),
            ("Station Capacity (kWh/day)", 'capacity', 1000,20000,5000),
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

        tb.Label(parent, text="Çözüm Yöntemi", font=("Segoe UI",10,"bold"))\
          .grid(row=10, column=0, sticky=W, pady=(10,0))
        self.method_combo = tb.Combobox(parent,
                                        values=["Docplex MIP", "Genetik Algoritma"],
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

        tb.Button(parent, text="Ev NOKTALARI YÜKLE", bootstyle="primary",
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

            self.status_var.set(f"{len(self.home_poi)} home noktası yüklendi.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load homes: {e}")

    def on_map_click(self, coords):
        # Maksimum aday kontrolü
        if len(self.station_candidates) >= self.max_st_var.get():
            messagebox.showwarning("Limit Reached",
                                   f"En fazla {self.max_st_var.get()} aday ekleyebilirsiniz.")
            return

        lat, lon = coords
        # Min-radius kontrolü
        r = self.radius_var.get()
        for c in self.station_candidates:
            if haversine(lat, lon, c['lat'], c['lon']) * 1000 < r:
                messagebox.showwarning("Too Close",
                                       f"Yeni nokta mevcut adaya {r} m'den daha yakın.")
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

    def run_optimization(self):
        if not self.home_poi or not self.station_candidates:
            messagebox.showinfo("Info","Ev ve station candidate noktalarını ekleyin.")
            return
        self.status_var.set("Building & solving model...")
        method = self.method_combo.get()
        max_st = self.max_st_var.get()
        rnv    = self.rnv_rate_var.get()
        evr    = self.ev_rate_var.get()
        capacity = self.capacity_var.get()
        radius = self.radius_var.get()
        threading.Thread(
            target=self._solve_model if method=="Docplex MIP" else self._solve_ga,
            args=(max_st,rnv,evr,capacity,radius), daemon=True
        ).start()

    def divert_to_charger(self, home):
        min_dist = float('inf'); nearest=None
        for c in self.station_candidates:
            d = haversine(home['lat'], home['lon'], c['lat'], c['lon'])
            if d < min_dist:
                min_dist = d; nearest=c
        return nearest

    def _solve_model(self, max_st, rnv, evr, capacity, radius):
        # --- EV örnekleme ve araç ataması -----------------------------------
        k = max(1, int(len(self.home_poi) * evr / 100))
        sampled = random.sample(self.home_poi, k)
        self.selected_homes = [
            {'home': h,
             'vehicle': random.choice([Renault, Ford, Tesla, Nissan])()}
            for h in sampled
        ]

        # --- Mesafe matrisi & talep -----------------------------------------
        I = list(range(len(self.selected_homes)))
        J = list(range(len(self.station_candidates)))
        d = [[haversine(self.selected_homes[i]['home']['lat'],
                        self.selected_homes[i]['home']['lon'],
                        self.station_candidates[j]['lat'],
                        self.station_candidates[j]['lon'])
              for j in J] for i in I]

        D = []
        for i in I:
            total_cons = 0
            for j in I:
                if i < j:
                    h1 = self.selected_homes[i]['home']
                    h2 = self.selected_homes[j]['home']
                    dist = haversine(h1['lat'], h1['lon'], h2['lat'], h2['lon'])
                    cons = self.selected_homes[i]['vehicle'].consumption_rate * dist
                    if cons > self.selected_homes[i]['vehicle'].battery_capacity:
                        self.divert_to_charger(h1)
                    total_cons += cons
            D.append(total_cons)

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
                if haversine(self.station_candidates[j]['lat'], self.station_candidates[j]['lon'],
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

    def _solve_ga(self, *args):
        messagebox.showinfo("Info","Genetik Algoritma henüz uygulanmadı.")
        self.status_var.set("Genetic Algorithm seçildi - henüz implementasyon yok.")

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
            h['vehicle'].consumption_rate * haversine(
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
        if self.chart: self.chart.get_tk_widget().destroy()
        self.status_var.set("Map cleared")

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    app = ChargingStationOptimizer()
    app.run()
