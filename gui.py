import tkinter as tk
from tkinter import ttk, messagebox
from tkinterweb import HtmlFrame
import folium
from folium.plugins import MarkerCluster
from docplex.mp.model import Model
from ttkthemes import ThemedStyle
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import threading
import tempfile
import os
import webbrowser
from PIL import Image, ImageTk
import io
import time
import random
from pathlib import Path  # added for reliable file:// URI support

class ChargingStationOptimizer:
    def __init__(self, master):
        self.master = master
        self.master.title("EV Charging Station Planner - Lyon")
        self.master.geometry("1300x800")
        
        # Set custom icon if available
        try:
            icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
            if os.path.exists(icon_path):
                self.master.iconbitmap(icon_path)
        except:
            pass
            
        # Configure style - using a more modern theme
        self.style = ThemedStyle(master)
        available_themes = self.style.get_themes()
        theme = "arc" if "arc" in available_themes else "equilux"
        self.style.set_theme(theme)
        self.configure_styles()
        
        # Main container with padding
        main_container = ttk.Frame(self.master, padding="10 10 10 10")
        main_container.pack(fill=tk.BOTH, expand=True)
        
        # Initialize data
        self.candidate_stations = []
        self.selected_stations = []
        self.optimization_thread = None
        self.map_html_path = None
        self.map_loaded = False
        self.loading_label = None
        
        # Create UI components
        self.create_input_pane(main_container)
        self.create_map_pane(main_container)
        self.create_results_pane(main_container)
        
        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(self.master, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Initial map setup
        self.update_map()

    def configure_styles(self):
        # Configure modern styles
        bg_color = self.style.lookup('TFrame', 'background')
        accent_color = "#4CAF50"  # Green accent color
        
        self.style.configure('TButton', font=('Segoe UI', 10), padding=8)
        self.style.configure('Title.TLabel', font=('Segoe UI', 12, 'bold'), padding=5)
        self.style.configure('Header.TLabel', font=('Segoe UI', 11, 'bold'))
        self.style.configure('Metric.TLabel', font=('Segoe UI', 10))
        self.style.configure('TScale', sliderthickness=15)
        self.style.configure('TCombobox', padding=5)
        self.style.configure('TLabelframe', borderwidth=2)
        self.style.configure('TLabelframe.Label', font=('Segoe UI', 11, 'bold'))
        
        # Custom button styles
        self.style.configure('Accent.TButton', 
                           background=accent_color,
                           foreground='white')
        self.style.map('Accent.TButton',
                     background=[('active', '#45a049'), ('!disabled', accent_color)],
                     foreground=[('active', 'white'), ('!disabled', 'white')])

    def create_input_pane(self, parent):
        input_frame = ttk.LabelFrame(parent, text=" Parameters ", style='TLabelframe')
        input_frame.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=10)

        # Add some padding inside the frame
        inner_frame = ttk.Frame(input_frame, padding="10 15 10 15")
        inner_frame.pack(fill=tk.BOTH, expand=True)

        params = [
            ("EV Penetration Rate (%)", 'ev_rate', 1, 20, 10),
            ("Simultaneous RNV (%)", 'rnv', 10, 90, 50),
            ("Min Radius (m)", 'radius', 500, 4500, 1000),
            ("Max Stations", 'max_stations', 5, 50, 15)
        ]

        for idx, (label, var, frm, to, val) in enumerate(params):
            # Parameter label
            ttk.Label(inner_frame, text=label, style='Header.TLabel').grid(row=idx*2, column=0, columnspan=2, sticky=tk.W, pady=(10, 0))
            
            # Value display
            setattr(self, f"{var}_display", tk.StringVar(value=str(val)))
            ttk.Label(inner_frame, textvariable=getattr(self, f"{var}_display")).grid(row=idx*2, column=2, sticky=tk.E, pady=(10, 0))
            
            # Slider
            setattr(self, var, tk.IntVar(value=val))
            scale = ttk.Scale(inner_frame, from_=frm, to=to, variable=getattr(self, var),
                  orient=tk.HORIZONTAL, length=200, 
                  command=lambda v, var=var: self.update_scale_display(var, v))
            scale.grid(row=idx*2+1, column=0, columnspan=3, sticky=tk.EW, pady=(0, 5))

        # Charger type selection
        ttk.Label(inner_frame, text="Charger Types:", style='Header.TLabel').grid(row=8, column=0, columnspan=2, sticky=tk.W, pady=(10, 5))
        self.charger_config = ttk.Combobox(inner_frame, values=["Slow + Fast", "Semi-fast + Fast"])
        self.charger_config.current(0)
        self.charger_config.grid(row=9, column=0, columnspan=3, sticky=tk.EW, pady=(0, 10))

        # Buttons with icons
        button_frame = ttk.Frame(inner_frame)
        button_frame.grid(row=10, column=0, columnspan=3, pady=15)
        
        ttk.Button(button_frame, text="Run Optimization", style='Accent.TButton',
                 command=self.run_optimization).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Clear Map",
                 command=self.clear_map).pack(side=tk.LEFT, padx=5)
        
        # Instructions section
        instruction_frame = ttk.LabelFrame(inner_frame, text=" Instructions ")
        instruction_frame.grid(row=11, column=0, columnspan=3, sticky=tk.EW, pady=(20, 5))
        
        instructions = (
            "• Click on the map to add candidate locations",
            "• Adjust parameters using sliders",
            "• Run optimization to place charging stations",
            "• Results will appear in the right panel"
        )
        
        for i, text in enumerate(instructions):
            ttk.Label(instruction_frame, text=text).grid(row=i, column=0, sticky=tk.W, pady=2)

    def update_scale_display(self, var, value):
        getattr(self, f"{var}_display").set(str(int(float(value))))
        self.queue_optimization()

    def create_map_pane(self, parent):
        map_frame = ttk.LabelFrame(parent, text=" Interactive Map ", style='TLabelframe')
        map_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Inner frame with padding
        map_inner = ttk.Frame(map_frame, padding="5 5 5 5")
        map_inner.pack(fill=tk.BOTH, expand=True)
        
        # Loading indicator
        self.loading_frame = ttk.Frame(map_inner)
        self.loading_frame.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        self.loading_label = ttk.Label(self.loading_frame, text="Loading map...", font=('Segoe UI', 12))
        self.loading_label.pack()
        
        # Create Folium map
        self.map = folium.Map(location=[45.7640, 4.8357], zoom_start=13, 
                            tiles='CartoDB positron')
        self.marker_cluster = MarkerCluster().add_to(self.map)
        
        # Create HTML frame with proper settings
        self.map_html = HtmlFrame(map_inner, messages_enabled=False)
        self.map_html.pack(fill=tk.BOTH, expand=True)
        
        # Set up click handling using bind method
        self.map_html.bind("<Button-1>", self.on_map_click)
        
        # Create a timer to check when map is loaded
        self.master.after(1000, self.check_map_loaded)

    def check_map_loaded(self):
        """Check if the map has loaded and update UI accordingly"""
        # Remove loading indicator
        if self.loading_frame and self.loading_frame.winfo_exists():
            self.loading_frame.place_forget()
        
        # Mark map as loaded
        self.map_loaded = True
        self.status_var.set("Map loaded. Click on map to add candidate locations.")
        
        # Add a button to help with adding markers
        add_marker_btn = ttk.Button(self.master, text="Add Random Marker", 
                                  command=lambda: self.add_marker(
                                      45.7640 + (random.random() * 0.05 - 0.025),
                                      4.8357 + (random.random() * 0.05 - 0.025)
                                  ))
        add_marker_btn.place(relx=0.5, rely=0.05, anchor=tk.CENTER)

    def on_map_click(self, event):
        """Handle clicks on the map to add markers"""
        if not self.map_loaded:
            return
            
        # Since direct coordinate translation isn't easily available,
        # we'll add a simpler version where we add markers near Lyon
        # This is a simplification - in a real app we'd need to use JavaScript to get coordinates
        lat = 45.7640 + (0.01 * (len(self.candidate_stations) % 5))
        lon = 4.8357 + (0.01 * (len(self.candidate_stations) % 5))
        
        self.add_marker(lat, lon)
        self.status_var.set(f"Added marker at approximate location (Lat: {lat:.4f}, Lon: {lon:.4f})")
        
        # Schedule optimization if we have enough markers
        if len(self.candidate_stations) >= 3:
            self.queue_optimization()

    def add_marker(self, lat, lon):
        """Add a marker at the given coordinates"""
        self.candidate_stations.append((lat, lon))
        self.update_map()
        self.status_var.set(f"Added marker at {lat:.4f}, {lon:.4f}")

    def create_results_pane(self, parent):
        results_frame = ttk.LabelFrame(parent, text=" Results ", style='TLabelframe')
        results_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=10, pady=10)

        # Inner frame with padding
        inner_results = ttk.Frame(results_frame, padding="10 10 10 10")
        inner_results.pack(fill=tk.BOTH, expand=True)

        # Summary section
        ttk.Label(inner_results, text="Optimization Summary", style='Title.TLabel').pack(anchor=tk.W, pady=(0, 10))

        # Metrics with better styling
        metrics_frame = ttk.Frame(inner_results)
        metrics_frame.pack(fill=tk.X, pady=5)

        self.metrics = {
            'cost': ("Total Cost (k€)", "0"),
            'semi_fast': ("Semi-fast CS", "0"),
            'fast': ("Fast CS", "0"),
            'chargers': ("Total Chargers", "0"),
            'energy': ("Energy (kWh/day)", "0")
        }
        
        for idx, (key, (label, value)) in enumerate(self.metrics.items()):
            metric_frame = ttk.Frame(metrics_frame)
            metric_frame.pack(fill=tk.X, pady=3)
            
            ttk.Label(metric_frame, text=label, style='Header.TLabel').pack(side=tk.LEFT)
            setattr(self, f'{key}_var', tk.StringVar(value=value))
            ttk.Label(metric_frame, textvariable=getattr(self, f'{key}_var'), 
                     style='Metric.TLabel').pack(side=tk.RIGHT)

        # Separator
        ttk.Separator(inner_results).pack(fill=tk.X, pady=10)
        
        # Chart with title
        ttk.Label(inner_results, text="Cost vs EV Adoption", style='Title.TLabel').pack(anchor=tk.W, pady=(10, 5))
        
        chart_frame = ttk.Frame(inner_results)
        chart_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # Create better looking chart
        self.figure = plt.Figure(figsize=(5, 4), dpi=100)
        self.ax = self.figure.add_subplot(111)
        self.figure.patch.set_facecolor(self.style.lookup('TFrame', 'background') or '#f0f0f0')
        
        self.chart = FigureCanvasTkAgg(self.figure, chart_frame)
        self.chart.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        # Export button
        export_frame = ttk.Frame(inner_results)
        export_frame.pack(fill=tk.X, pady=5)
        ttk.Button(export_frame, text="Export Results", 
                  command=self.export_results).pack(side=tk.LEFT)

    def update_map(self):
        """Update map with current stations"""
        # re‐show loading overlay while regenerating the HTML
        self.loading_frame.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        self.status_var.set("Updating map...")
        self.map = folium.Map(location=[45.7640, 4.8357], zoom_start=13,
                            tiles='CartoDB positron')  # More modern map style
        
        # Add a custom control
        folium.map.LayerControl().add_to(self.map)
        
        # Create a marker cluster
        self.marker_cluster = MarkerCluster(name="Charging Stations").add_to(self.map)
        
        # Add markers for candidate stations
        for idx, (lat, lon) in enumerate(self.candidate_stations):
            folium.Marker(
                [lat, lon], 
                popup=f"Candidate {idx+1}<br>Lat: {lat:.4f}, Lon: {lon:.4f}",
                icon=folium.Icon(color='blue', icon='info-sign')
            ).add_to(self.marker_cluster)
        
        # Add markers for selected stations with better styling
        for idx, station in enumerate(self.selected_stations):
            icon_color = 'green' if station['type'] == 'Fast' else 'orange'
            icon_type = 'bolt' if station['type'] == 'Fast' else 'plug'
            
            folium.Marker(
                [station['lat'], station['lon']],
                popup=f"{station['type']} Station {idx+1}<br>Lat: {station['lat']:.4f}, Lon: {station['lon']:.4f}",
                tooltip=f"{station['type']} Charging Station",
                icon=folium.Icon(color=icon_color, icon=icon_type, prefix='fa')
            ).add_to(self.marker_cluster)
            
        # Add circle radii for visualization
        radius = self.radius.get()
        if self.selected_stations and radius > 0:
            for station in self.selected_stations:
                folium.Circle(
                    location=[station['lat'], station['lon']],
                    radius=radius,
                    color="#3186cc",
                    fill=True,
                    fill_color="#3186cc",
                    fill_opacity=0.1
                ).add_to(self.map)

        # Add custom click handler JavaScript
        self.map.get_root().header.add_child(folium.Element("""
            <script>
            // Create a bridge to communicate map clicks
            var jsBridge = {};
            jsBridge.showMarker = function(lat, lon) {
                console.log("Map clicked at: " + lat + ", " + lon);
                // This will be handled by custom js later
            };
            
            // Store map reference for later use
            document.addEventListener('DOMContentLoaded', function() {
                setTimeout(function() {
                    window.map = document.querySelector('.leaflet-map-pane')?.__map || 
                                document.querySelector('.leaflet-container')?._leaflet_map;
                }, 1000);
            });
            </script>
        """))
        
        # Save to temporary file
        try:
            with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
                self.map.save(f.name)
                self.map_html_path = f.name
            
            # Use a slight delay to ensure the HTML is fully written
            # self.master.after(100, self._load_map_in_html_frame)
            webbrowser.open(Path(self.map_html_path).as_uri())
        except Exception as e:
            self.status_var.set(f"Error updating map: {str(e)}")

    def _load_map_in_html_frame(self):
        """Load the map in HTML frame with proper URL formatting"""
        if self.map_html_path and os.path.exists(self.map_html_path):
            # use pathlib to get a valid file:// URI
            file_url = Path(self.map_html_path).as_uri()
            self.map_html.load_url(file_url)
            self.status_var.set("Map updated")
        else:
            self.status_var.set("Error: Map file not found")

    def run_optimization(self):
        if self.optimization_thread and self.optimization_thread.is_alive():
            return
        
        if len(self.candidate_stations) < 3:
            messagebox.showinfo("Information", "Please add at least 3 candidate locations on the map by clicking.")
            return
            
        self.status_var.set("Running optimization...")
        self.optimization_thread = threading.Thread(target=self.solve_with_cplex)
        self.optimization_thread.start()

    def solve_with_cplex(self):
        """Simulate optimization process with progress updates"""
        # Show progress in status bar
        for i in range(5):
            self.master.after(i * 300, lambda msg=f"Optimizing ({i+1}/5)...": self.status_var.set(msg))
            time.sleep(0.3)
        
        # Dummy optimization - replace with real CPLEX model
        max_stations = int(self.max_stations.get())
        num_stations = min(max_stations, len(self.candidate_stations))
        
        # Use existing candidate stations where possible
        self.selected_stations = []
        for i in range(min(num_stations, len(self.candidate_stations))):
            lat, lon = self.candidate_stations[i]
            self.selected_stations.append({
                'lat': lat,
                'lon': lon,
                'type': 'Fast' if i % 2 == 0 else 'Semi-fast'
            })
        
        # Fill remaining with generated stations if needed
        for i in range(len(self.candidate_stations), num_stations):
            self.selected_stations.append({
                'lat': 45.7640 + 0.01*i,
                'lon': 4.8357 + 0.01*i,
                'type': 'Semi-fast' if i%2 else 'Fast'
            })
        
        self.master.after(0, self.update_results)

    def update_results(self):
        """Update the results panel with optimization results"""
        ev_rate = self.ev_rate.get()
        
        # Calculate some realistic values based on parameters
        cost = 4000 + ev_rate * 100
        semi_fast = max(1, int(len(self.selected_stations) * 0.7))
        fast_stations = max(1, int(len(self.selected_stations) * 0.3))
        chargers = semi_fast * 8 + fast_stations * 4
        energy = ev_rate * 65
        
        # Update metric displays with animations
        self.animate_value(self.cost_var, 0, cost, "%.0f")
        self.animate_value(self.semi_fast_var, 0, semi_fast, "%.0f")
        self.animate_value(self.fast_var, 0, fast_stations, "%.0f")
        self.animate_value(self.chargers_var, 0, chargers, "%.0f")
        self.animate_value(self.energy_var, 0, energy, "%.0f")
        
        # Update chart with animation
        self.ax.clear()
        x = [5, 10, 15, 20]
        y = [cost * 0.5, cost, cost * 1.5, cost * 2]
        
        # Style the chart
        self.ax.plot(x, y, 'o-', color='#3186cc', linewidth=2, markersize=8)
        self.ax.set_xlabel('EV Penetration Rate (%)', fontsize=9)
        self.ax.set_ylabel('Total Cost (k€)', fontsize=9)
        self.ax.set_title('Cost vs EV Adoption Rate', fontsize=11)
        self.ax.grid(True, linestyle='--', alpha=0.7)
        
        # Fill area under the curve for better visualization
        self.ax.fill_between(x, y, color='#3186cc', alpha=0.2)
        
        self.figure.tight_layout()
        self.chart.draw()
        
        # Update map with selected stations
        self.update_map()
        self.status_var.set(f"Optimization complete. {len(self.selected_stations)} stations placed.")

    def animate_value(self, var, start, end, fmt="%.1f", duration=20):
        """Animate a value change in a variable"""
        steps = 10
        for i in range(steps + 1):
            value = start + (end - start) * (i / steps)
            var.set(fmt % value)
            self.master.update_idletasks()
            time.sleep(duration/1000)

    def queue_optimization(self):
        """Queue optimization with debouncing"""
        if hasattr(self, '_after_id'):
            self.master.after_cancel(self._after_id)
        self._after_id = self.master.after(800, self.run_optimization)

    def export_results(self):
        """Export results to HTML and CSV"""
        try:
            # Export map to HTML
            if self.map_html_path:
                export_path = os.path.join(os.path.dirname(self.map_html_path), "charging_stations_map.html")
                self.map.save(export_path)
                
                # Open the exported map
                webbrowser.open(f"file://{export_path}")
                self.status_var.set(f"Results exported to {export_path}")
        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to export results: {str(e)}")

    def clear_map(self):
        self.candidate_stations = []
        self.selected_stations = []
        self.update_map()
        
        # Reset metrics
        for key in self.metrics:
            getattr(self, f'{key}_var').set("0")
            
        # Clear chart
        self.ax.clear()
        self.ax.set_xlabel('EV Penetration Rate (%)')
        self.ax.set_ylabel('Total Cost (k€)')
        self.chart.draw()
        
        self.status_var.set("Map cleared")

    def __del__(self):
        # Clean up temporary files
        if self.map_html_path and os.path.exists(self.map_html_path):
            try:
                os.remove(self.map_html_path)
            except:
                pass

if __name__ == "__main__":
    root = tk.Tk()
    app = ChargingStationOptimizer(root)
    root.mainloop()