# EV Charging Station Location Optimization

This project provides a comprehensive simulation and optimization system for the efficient placement of Electric Vehicle (EV) charging stations within an urban area. The methodology is based on a Fixed-Location Optimization Model.

## Reference Paper

**Efficient Allocation of Electric Vehicles Charging Stations: Optimization Model and Application to a Dense Urban Network**  
IEEE Intelligent Transportation Systems Magazine, Fall 2014  
**Authors:** Baouche, Billot, Trigui, El Faouzi  
**DOI:** [10.1109/MITS.2014.2324023](https://doi.org/10.1109/MITS.2014.2324023)

---

## Project Goal

The primary objective of this project is to develop a comprehensive decision-support tool that can:

- Determine the optimal locations for charging stations within a city.
- Minimize both the total installation costs and the travel-based energy consumption for users.
- Provide a map-based GUI for interactive scenario building, parameter adjustment, and results visualization.

---

## Key Features

- **Multi-Vehicle Modeling:** Simulates energy consumption for different real-world EV models (e.g., Renault, Tesla, Ford).
- **Interactive Map Interface:** Allows users to manually select station candidates directly on a map using TkinterMapView.
- **Dual Optimization Methods:** Provides solutions using both:
  - Mixed-Integer Programming (via IBM CPLEX & DOcplex) for mathematically optimal solutions.
  - Genetic Algorithm as a heuristic alternative for large-scale problems.
- **Demand Heatmap:** Generates a heatmap of potential travel routes to visualize high-demand corridors before optimization.
- **Analytics Dashboard:** A comprehensive results window displays key metrics, including total cost, energy consumption, and the number of each station type deployed.

---

## Usage

**How to Use the Application:**

1. **Load Home Points:** Use the button to load a JSON or CSV file containing the locations of EV users.
2. **Define Candidates:** Select a station type ("Parking" or "Fuel") and click on the map to place potential charging station sites.
3. **Set Parameters:** Adjust the sliders and dropdowns on the left panel to configure the scenario (e.g., EV penetration rate, station capacity, minimum radius).
4. **Run Optimization:** Click the "Run Optimization" button to solve the model using the selected method.
5. **Analyze Results:** Use the "Show Results" button to view detailed statistics and charts. Use the checkboxes on the map to visualize the final solution.

---

## Model Outputs

The optimization model generates the following key outputs:

- The total installation cost for the network (in k€).
- The number of semi-fast and fast chargers deployed.
- The total energy consumed by users traveling to their assigned stations.
- A detailed assignment list showing which station serves each EV.
- A full visualization of the final station locations and the travel routes on the map.

---

## Acknowledgements

This project was developed as a Graduation Project for the CSE 495 / 496 courses at Gebze Technical University.

- **Project Supervisor:** Prof. Dr. Didem Gözüpek Kocaman  
- **Project Students:** Furkan Taşkın & Çağrı Yıldız

---

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for more details.
