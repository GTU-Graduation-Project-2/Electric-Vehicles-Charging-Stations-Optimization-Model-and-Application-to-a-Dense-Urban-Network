import os
import math
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import ttkbootstrap as tb
from ttkbootstrap.constants import *
from tkintermapview import TkinterMapView  # pip install tkintermapview
from docplex.mp.model import Model        # pip install docplex
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# Sabit parametreler
AVG_CONSUMPTION_PER_EV = 8  # kWh / gün
POI_COLOR        = {"Home": "#28a745", "Parking": "#fd7e14", "Fuel": "#007bff"}
POI_TYPE_NUM     = {"Home": 1,       "Parking": 2,         "Fuel": 3}
POI_FIXED_COST   = {"Home": 1,       "Parking": 12,        "Fuel": 50}  # k€ sabit kurulum maliyeti

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = map(math.radians, (lat1, lat2))
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.asin(math.sqrt(a))

class ChargingStationOptimizer:
    def __init__(self):
        # Ana pencere
        self.root = tb.Window(themename='flatly')
        self.root.title("EV Charging Station Planner")
        self.root.geometry("1300x800")

        # Aday ve seçilmiş noktalar
        self.candidates = []  # her biri {'lat','lon','poi'}
        self.selected   = []  # her biri {'lat','lon','poi','type'}

        # Sonuç değişkenleri
        self.cost_var     = tk.StringVar(master=self.root, value="0")
        self.semi_var     = tk.StringVar(master=self.root, value="0")
        self.fast_var     = tk.StringVar(master=self.root, value="0")
        self.chargers_var = tk.StringVar(master=self.root, value="0")
        self.energy_var   = tk.StringVar(master=self.root, value="0")
        self.solution_obj = 0.0

        # Grafik altyapısı
        self.figure = plt.Figure(figsize=(5,3), dpi=100)
        self.ax     = self.figure.add_subplot(111)
        self.chart  = None

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
        # Parametre slider tanımları
        params = [
            ("EV Penetration Rate (%)",   'ev_rate',   1,   20, 10),
            ("Simultaneous RNV (%)",       'rnv_rate', 10, 100, 50),
            ("Min Radius (m)",             'radius',  200,5000,1000),
            ("Max Stations",               'max_st',   1,   50, 15),
            ("Station Capacity (kWh/day)",'capacity',1000,20000,5000),
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

        # POI tipi seçimi
        tb.Label(parent, text="Location Type", font=("Segoe UI",10,"bold"))\
          .grid(row=10, column=0, sticky=W, pady=(10,0))
        self.poi_type = tb.Combobox(parent,
                             values=list(POI_TYPE_NUM.keys()),
                             state="readonly")
        self.poi_type.current(0)
        self.poi_type.grid(row=11, column=0, columnspan=2, sticky=EW)

        # Butonlar
        tb.Button(parent, text="Run Optimization", bootstyle="success",
                  command=self.run_optimization)\
          .grid(row=12, column=0, columnspan=2, sticky=EW, pady=(10,2))
        tb.Button(parent, text="Clear Map", bootstyle="warning",
                  command=self.clear_map)\
          .grid(row=13, column=0, columnspan=2, sticky=EW, pady=2)
        tb.Button(parent, text="Show Results", bootstyle="info",
                  command=self.open_results_window)\
          .grid(row=14, column=0, columnspan=2, sticky=EW, pady=(2,10))

    def _build_map(self, parent):
        frame = tb.LabelFrame(parent, text="Map View")
        frame.pack(fill=BOTH, expand=YES)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        self.map_widget = TkinterMapView(frame, corner_radius=0)
        self.map_widget.grid(row=0, column=0, sticky="nsew")
        self.map_widget.set_position(41.0082, 28.9784)  # İstanbul
        self.map_widget.set_zoom(12)
        self.map_widget.add_left_click_map_command(self.on_map_click)

    def on_map_click(self, coords):
        # Aday limiti kontrolü
        if len(self.candidates) >= self.max_st_var.get():
            messagebox.showwarning("Limit Reached",
                f"En fazla {self.max_st_var.get()} aday ekleyebilirsiniz.")
            return

        lat, lon = coords
        # Radius kısıtı
        r = self.radius_var.get()
        for c in self.candidates:
            if haversine(lat, lon, c['lat'], c['lon']) * 1000 < r:
                messagebox.showwarning("Too Close",
                    f"Yeni nokta mevcut adaya {r} m'den daha yakın.")
                return
        # Listeye ekle
        poi = self.poi_type.get()
        self.candidates.append({'lat':lat,'lon':lon,'poi':poi})
        self._update_markers(show_only_selected=False)
        self.status_var.set(f"Added {poi} ({lat:.4f},{lon:.4f})")

    def _update_markers(self, show_only_selected=False):
        self.map_widget.delete_all_marker()
        if show_only_selected and self.selected:
            # Sadece seçilenler
            for i, s in enumerate(self.selected, 1):
                self.map_widget.set_marker(
                    s['lat'], s['lon'],
                    text=f"{s['type']} S{i}",
                    marker_color_circle="red",
                    marker_color_outside="white"
                )
        else:
            # Tüm adaylar
            for i, c in enumerate(self.candidates, 1):
                color = POI_COLOR[c['poi']]
                num   = POI_TYPE_NUM[c['poi']]
                self.map_widget.set_marker(
                    c['lat'], c['lon'], text=f"{num}-{i}",
                    marker_color_circle=color,
                    marker_color_outside="white"
                )

    def run_optimization(self):
        if len(self.candidates) < 3:
            messagebox.showinfo("Info","En az 3 aday ekleyin.")
            return
        self.status_var.set("Building & solving model...")
        # Parametreleri oku
        max_st   = self.max_st_var.get()
        rnv      = self.rnv_rate_var.get()
        evr      = self.ev_rate_var.get()
        capacity = self.capacity_var.get()
        radius   = self.radius_var.get()
        # Modeli paralel thread'te çalıştır
        threading.Thread(
            target=self._solve_model,
            args=(max_st, rnv, evr, capacity, radius),
            daemon=True
        ).start()

    def _solve_model(self, max_st, rnv, evr, capacity, radius):
        total_demand = 1000 * (evr/100) * (rnv/100) * AVG_CONSUMPTION_PER_EV
        n = len(self.candidates)
        # Mesafe matrisi
        d = [[haversine(self.candidates[i]['lat'], self.candidates[i]['lon'],
                        self.candidates[j]['lat'], self.candidates[j]['lon'])
              for j in range(n)] for i in range(n)]
        # Model oluştur
        m = Model(name="ev_location")
        x = {j: m.binary_var(name=f"x_{j}") for j in range(n)}
        y = {(i,j): m.binary_var(name=f"y_{i}_{j}") for i in range(n) for j in range(n)}
        # Amaç fonksiyonu
        m.minimize(
            m.sum(POI_FIXED_COST[self.candidates[j]['poi']] * x[j] for j in range(n))
          + m.sum(total_demand * d[i][j] * y[i,j] for i in range(n) for j in range(n))
        )
        # Atama kısıtları
        for i in range(n):
            m.add_constraint(m.sum(y[i,j] for j in range(n)) == 1)
            for j in range(n): m.add_constraint(y[i,j] <= x[j])
        # Kapasite kısıtı
        for j in range(n):
            m.add_constraint(
                m.sum(total_demand * y[i,j] for i in range(n))
                <= capacity * x[j]
            )
        # Dispersion kısıtı
        for j in range(n):
            for k in range(j+1, n):
                if d[j][k] * 1000 < radius:
                    m.add_constraint(x[j] + x[k] <= 1)
        # Max stations kısıtı
        m.add_constraint(m.sum(x[j] for j in range(n)) <= max_st,
                         ctname="max_stations")
        # Çöz
        sol = m.solve(log_output=False)
        if not sol:
            self.status_var.set("Model çözülemedi.")
            return
        # Seçilen istasyonları oku
        self.selected = []
        for j in range(n):
            if x[j].solution_value > 0.5:
                pt = self.candidates[j]
                typ = ("Slow" if pt['poi']=="Home" else
                       "Semi-fast" if pt['poi']=="Parking" else "Fast")
                self.selected.append({
                    'lat': pt['lat'], 'lon': pt['lon'],
                    'poi': pt['poi'], 'type': typ
                })
        self.solution_obj = m.objective_value
        # Haritada sadece seçilenler
        self.root.after(0, lambda: self._update_markers(show_only_selected=True))
        # Sonuç penceresini aç
        self.root.after(0, self.open_results_window)

    def open_results_window(self):
        win = tk.Toplevel(self.root)
        win.title("Results and Graphs")
        win.geometry("800x600")
        win.rowconfigure(0,weight=1); win.columnconfigure(0,weight=1)
        frm = tb.Frame(win, padding=10); frm.pack(fill=BOTH, expand=YES)
        # Seçilen istasyon tablosu
        sf = tb.LabelFrame(frm, text="Selected Stations"); sf.pack(fill=X, pady=(0,10))
        cols = ("Index","POI","Type","Lat","Lon")
        tree = ttk.Treeview(sf, columns=cols, show='headings')
        for c in cols:
            tree.heading(c, text=c); tree.column(c, anchor=CENTER)
        for i, s in enumerate(self.selected, 1):
            tree.insert('', END, values=(i, s['poi'], s['type'],
                                         f"{s['lat']:.4f}", f"{s['lon']:.4f}"))
        tree.pack(fill=X)
        # Model bilgileri
        info = tb.LabelFrame(frm, text="Model Info"); info.pack(fill=X, pady=(0,10))
        tb.Label(info, text=f"Objective Value: {self.solution_obj:.2f} k€").pack(anchor=W)
        tb.Label(info, text=f"#Candidates: {len(self.candidates)}").pack(anchor=W)
        tb.Label(info, text=f"#Selected:   {len(self.selected)}").pack(anchor=W)
        # Summary KPI
        summary = tb.LabelFrame(frm, text="Summary"); summary.pack(fill=X, pady=(0,10))
        semi = sum(1 for s in self.selected if s['type']=="Semi-fast")
        fast = sum(1 for s in self.selected if s['type']=="Fast")
        chargers = semi*4 + fast*2
        energy = int(1000*(self.ev_rate_var.get()/100)*(self.rnv_rate_var.get()/100)*AVG_CONSUMPTION_PER_EV)
        self.cost_var.set(f"{self.solution_obj:.2f}")
        self.semi_var.set(str(semi)); self.fast_var.set(str(fast))
        self.chargers_var.set(str(chargers)); self.energy_var.set(str(energy))
        for lbl,var in [("Cost (k€)",self.cost_var),
                        ("Semi-fast CS",self.semi_var),
                        ("Fast CS",self.fast_var),
                        ("Chargers",self.chargers_var),
                        ("Energy (kWh)",self.energy_var)]:
            row = tb.Frame(summary); row.pack(fill=X,pady=2)
            tb.Label(row, text=lbl).pack(side=LEFT)
            tb.Label(row, textvariable=var).pack(side=RIGHT)
        # Grafik
        cf = tb.LabelFrame(frm, text="Cost vs EV Rate"); cf.pack(fill=BOTH, expand=YES)
        chart_fr = tb.Frame(cf); chart_fr.pack(fill=BOTH, expand=YES)
        self.ax.clear()
        x = [0, self.ev_rate_var.get()]
        y = [0, self.solution_obj]
        self.ax.plot(x, y, 'o-')
        self.ax.set_xlabel('EV Penetration (%)')
        self.ax.set_ylabel('Cost (k€)')
        self.ax.grid(True, linestyle='--', alpha=0.6)
        self.figure.tight_layout()
        if self.chart: self.chart.get_tk_widget().destroy()
        self.chart = FigureCanvasTkAgg(self.figure, master=chart_fr)
        self.chart.get_tk_widget().pack(fill=BOTH, expand=YES)
        self.chart.draw()

    def clear_map(self):
        self.candidates.clear(); self.selected.clear()
        self._update_markers(show_only_selected=False)
        for v in [self.cost_var,self.semi_var,self.fast_var,
                  self.chargers_var,self.energy_var]: v.set("0")
        self.ax.clear()
        if self.chart: self.chart.get_tk_widget().destroy()
        self.status_var.set("Map cleared")

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    app = ChargingStationOptimizer()
    app.run()
