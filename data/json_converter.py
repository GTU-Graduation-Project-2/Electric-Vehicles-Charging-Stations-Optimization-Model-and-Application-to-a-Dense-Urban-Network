import json

# Sample code to convert your GeoJSON FeatureCollection to the simple JSON list expected by the loader.
geojson_path = 'map.geojson'  # GeoJSON dosyanızın adı
with open(geojson_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

converted = [
    {'lat': feature['geometry']['coordinates'][1],
     'lon': feature['geometry']['coordinates'][0]}
    for feature in data['features']
]

# Kaydetmek için:
with open('homes_2.json', 'w', encoding='utf-8') as out:
    json.dump(converted, out, indent=2, ensure_ascii=False)

# Örnek çıktı (ilk 10 nokta):
print(json.dumps(converted[:10], indent=2, ensure_ascii=False))
