import psycopg2
import psycopg2.extras

import requests
import json
import re
import os
import copy

import Transit
import ConfigParser

import sys

config = ConfigParser.RawConfigParser()
config.read(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'settings.cfg')))
DGGRID_HOST = config.get('dggrid', 'host')
DGGRID_PORT = config.get('dggrid', 'port')
DGGRID_DBNAME = config.get('dggrid', 'dbname')
DGGRID_USER = config.get('dggrid', 'user')
DGGRID_PASSWORD = config.get('dggrid', 'password')
DGGRID_CONN_STRING = "host='"+DGGRID_HOST+"' port='"+DGGRID_PORT+"' dbname='"+DGGRID_DBNAME+"' user='"+DGGRID_USER+"' password='"+DGGRID_PASSWORD+"'"

REVERSE_GEOCODE_PROVIDER = config.get('geocode', 'reverse_geocode_provider')
MAPZEN_KEY = config.get('geocode', 'mapzen_key')
MAPBOX_KEY = config.get('geocode', 'mapbox_key')
GOOGLE_KEY = config.get('geocode', 'google_key')

class HexagonRegion(object):
    
    def __init__(self):
        self.hexagons = []
        self.hexagon_geo = {}
        
    def add_hexagon(self, h):
        self.hexagons.append(h)
        
    def has_hexagon(self, h):
        if h in self.hexagons:
            return True
        else:
            return False
        
    def num_hexagons(self):
        return len(self.hexagons)
    
    def get_hexagon_by_gid(self, gid):
        for h in self.hexagons:
            if h.gid == gid:
                return h
        return None
    
    def geojson(self):
        features = []
        first = True
        for hexagon in self.hexagons:
            geo = hexagon.geo_hex
            features.append({"type": "Feature", "geometry": geo, "properties": {"population": hexagon.population, "employment": hexagon.employment}})
            
        return {"type": "FeatureCollection", "features": features}
    
    def to_json(self):
        return json.dumps(self, default=lambda o: o.__dict__, sort_keys=True)

class Hexagon(object):
    
    def __init__(self, gid, geo_hex, population, employment):
        self.gid = gid
        self.geo_hex = geo_hex
        self.population = population
        self.employment = employment
        
    def center(self):
        lat = 0
        lng = 0
        for coordinate in self.geo_hex["coordinates"][0]:
            lat += coordinate[0]
            lng += coordinate[1]
            
        lat = lat / len(self.geo_hex["coordinates"][0])
        lng = lng / len(self.geo_hex["coordinates"][0])
        
        return (lat, lng)
    
    def shift_center(self, lat, lng):
        curr_center = self.center()
        lat_delta = lat - curr_center[0]
        lng_delta = lng - curr_center[1]
        for coordinate in self.geo_hex["coordinates"][0]:
            coordinate[0] += lat_delta
            coordinate[1] += lng_delta
        
    def to_json(self):
        return json.dumps(self, default=lambda o: o.__dict__, sort_keys=True)
    
    def from_json(self, j):
        self.gid = int(j['gid'])
        self.geo_hex = j['geo_hex']
        self.population = int(j['population'])
        self.employment = int(j['employment'])
    
class BoundingBox(object):
    
    def __init__(self):
        self.min_lat = 0
        self.max_lat = 0
        self.min_lng = 0
        self.max_lng = 0
        
    def set_bounds(self, min_lat, max_lat, min_lng, max_lng):
        self.min_lat = min_lat
        self.max_lat = max_lat
        self.min_lng = min_lng
        self.max_lng = max_lng
        
    def set_from_map(self, m):
        min_lat_set = False
        max_lat_set = False
        min_lng_set = False
        max_lng_set = False
    
        for s in m.services:
            stations = s.stations
            for station in stations:
                if not min_lat_set or station.location[0] < self.min_lat:
                    self.min_lat = station.location[0]
                    min_lat_set = True
                if not max_lat_set or station.location[0] > self.max_lat:
                    self.max_lat = station.location[0]
                    max_lat_set = True
                if not min_lng_set or station.location[1] < self.min_lng:
                    self.min_lng = station.location[1]
                    min_lng_set = True
                if not max_lng_set or station.location[1] > self.max_lng:
                    self.max_lng = station.location[1]
                    max_lng_set = True
                    
    def set_from_station(self, s):
        self.min_lat = s.location[0] - 0.01;
        self.max_lat = s.location[0] + 0.01;
        self.min_lng = s.location[1] - 0.01;
        self.max_lng = s.location[1] + 0.01;

class ReverseGeocodeResult(object):
    
    def __init__(self, lat, lng):
        self.lat = lat
        self.lng = lng
        self.streets = []
        self.neighborhood = ""
        self.locality = ""
        self.has_street = False
        self.has_neighborhood = False
        self.has_locality = False
    
    def set_streets(self, streets):
        self.streets = streets
        self.has_street = True
        
    def set_neighborhood(self, neighborhood):
        self.neighborhood = neighborhood
        self.has_neighborhood = True
        
    def set_locality(self, locality):
        self.locality = locality
        self.has_locality = True

def hexagons_bb(bb):
    
    region = HexagonRegion()
        
    conn = psycopg2.connect(DGGRID_CONN_STRING)
    cursor = conn.cursor()
     
    query = "SELECT gid, ST_AsGeoJSON(center), coalesce(population,0) as p, coalesce(employment,0) as e FROM dggrid WHERE ST_Within(center, ST_MakeEnvelope("+str(bb.min_lng)+", "+str(bb.min_lat)+", "+str(bb.max_lng)+", "+str(bb.max_lat)+")) LIMIT 20000;"
    print query
    cursor.execute(query)
    #cursor.execute("SELECT gid FROM dggrid WHERE ST_DWithin(geo, 'POINT("+lng+" "+lat+")', 0.01) LIMIT 1000;")
    #cursor.execute("SELECT * FROM dggrid ORDER BY geo <-> st_setsrid(st_makepoint("+lng+","+lat+"),4326) LIMIT 100;")
    
    rows = cursor.fetchall()
    
    if (len(rows) > 0):
        query = "SELECT gid, ST_AsGeoJSON(geo), coalesce(population,0) as p, coalesce(employment,0) as e FROM dggrid WHERE gid="+str(rows[0][0])+" LIMIT 1;"
        print query
        cursor.execute(query)
        hexagon_row = cursor.fetchone()
        hexagon_template = Hexagon(int(hexagon_row[0]), json.loads(hexagon_row[1]), int(hexagon_row[2]), int(hexagon_row[3]))
        
        for row in rows:
            h = copy.deepcopy(hexagon_template)
            c = json.loads(row[1])
            h.shift_center(c['coordinates'][0], c['coordinates'][1])
            h.gid = int(row[0])
            h.population = int(row[2])
            h.employment = int(row[3])
            region.add_hexagon(h)
    cursor.close()
    conn.close()
    
    return region

def hexagons_gids(gids):
    
    region = HexagonRegion()
        
    conn = psycopg2.connect(DGGRID_CONN_STRING)
    cursor = conn.cursor()
     
    query = "SELECT gid, ST_AsGeoJSON(center), coalesce(population,0) as p, coalesce(employment,0) as e FROM dggrid WHERE gid IN %s LIMIT 20000;"
    #print query
    cursor.execute(query, [tuple(gids)])
    #cursor.execute("SELECT gid FROM dggrid WHERE ST_DWithin(geo, 'POINT("+lng+" "+lat+")', 0.01) LIMIT 1000;")
    #cursor.execute("SELECT * FROM dggrid ORDER BY geo <-> st_setsrid(st_makepoint("+lng+","+lat+"),4326) LIMIT 100;")
    
    rows = cursor.fetchall()
    
    for hexagon_row in rows:
        hexagon_template = Hexagon(int(hexagon_row[0]), json.loads(hexagon_row[1]), int(hexagon_row[2]), int(hexagon_row[3]))
        
        for row in rows:
            h = copy.deepcopy(hexagon_template)
            c = json.loads(row[1])
            h.shift_center(c['coordinates'][0], c['coordinates'][1])
            h.gid = int(row[0])
            h.population = int(row[2])
            h.employment = int(row[3])
            region.add_hexagon(h)
    cursor.close()
    conn.close()
    
    return region

def reverse_geocode(provider, lat, lng):
    
    result = ReverseGeocodeResult(lat, lng)
    
    if provider == "mapzen":
        mapzen_uri = "https://search.mapzen.com/v1/reverse?api_key="+MAPZEN_KEY+"&point.lat="+lat+"&point.lon="+lng+"&size=1&layers=address"
        geocode = requests.get(mapzen_uri)
        geocode_content = json.loads(geocode.content)
        
        if (len(geocode_content["features"]) < 1):
            # Flag an error?
            print "Error in reverse geocoding"
        else:
            properties = geocode_content["features"][0]["properties"]
            if ("street" in properties):
                streets = [properties["street"]]
                result.set_streets(streets)
            if ("locality" in properties):
                locality = properties["locality"]
                result.set_locality(locality)
            if ("borough" in properties):
                locality = properties["borough"]
                result.set_locality(locality)
            if ("neighbourhood" in properties):
                neighborhood = properties["neighbourhood"]
                result.set_neighborhood(neighborhood)
                
    if provider == "mapbox":
        mapbox_uri = "https://api.mapbox.com/geocoding/v5/mapbox.places/"+str(lng)+","+str(lat)+".json?access_token="+MAPBOX_KEY+"&types=locality,neighborhood,address"
        geocode = requests.get(mapbox_uri)
        geocode_content = json.loads(geocode.content)
        if (len(geocode_content["features"]) < 1):
            # Flag an error?
            print "Error in reverse geocoding"
        else:
            for feature in geocode_content["features"]:
                place_type = feature["place_type"][0]
                if place_type == "address":
                    result.set_streets([feature["text"]])
                if place_type == "neighborhood":
                    result.set_neighborhood(feature["text"])
                if place_type == "locality":
                    result.set_locality(feature["text"])
    
    if provider == "google":
        google_uri = "https://maps.googleapis.com/maps/api/geocode/json?latlng="+str(lat)+","+str(lng)+"&key="+GOOGLE_KEY
        geocode = requests.get(google_uri)
        geocode_content = json.loads(geocode.content)
        if (len(geocode_content["results"]) < 1):
            # Flag an error?
            print "Error in reverse geocoding"
        else:
            address = geocode_content["results"][0]
            streets = []
            for component in address["address_components"]:
                place_types = component["types"]
                if "neighborhood" in place_types:
                    result.set_neighborhood(component["long_name"])
                if "route" in place_types:
                    streets.append(component["short_name"])
                if "locality" in place_types:
                    result.set_locality(component["long_name"])
            if len(streets) > 0:
                result.set_streets(streets)

    return result
        

def station_constructor(sid, lat, lng):
    
    name = ""
    
    rgr = reverse_geocode(REVERSE_GEOCODE_PROVIDER, lat, lng)
    
    if (rgr.has_street):
        name = rgr.streets[0]
    elif (rgr.has_neighborhood):
        name = rgr.neighborhood
    elif (rgr.has_locality):
        name = rgr.locality
    else:
        name = "Station"
    if len(name) <= 1:
        name = "Station"
    
    name = re.sub(r'(\w+\s)\b(Street)\b', r'\1St', name)
    name = re.sub(r'(\w+\s)\b(Road)\b', r'\1Rd', name)
    name = re.sub(r'(\w+\s)\b(Drive)\b', r'\1Dr', name)
    name = re.sub(r'(\w+\s)\b(Avenue)\b', r'\1Av', name)
    name = re.sub(r'(\w+\s)\b(Lane)\b', r'\1Ln', name)
    name = re.sub(r'(\w+\s)\b(Boulevard)\b', r'\1Blvd', name)
    
    s = Transit.Station(sid, name, [lat, lng])
    s.streets = rgr.streets
    s.neighborhood = rgr.neighborhood
    s.locality = rgr.locality
    
    return s

#six degrees of precision in valhalla
inv = 1.0 / 1e6;

#decode an encoded string
def mapzen_decode(encoded):
    decoded = []
    previous = [0,0]
    i = 0
    #for each byte
    while i < len(encoded):
        #for each coord (lat, lon)
        ll = [0,0]
        for j in [0, 1]:
            shift = 0
            byte = 0x20
            #keep decoding bytes until you have this coord
            while byte >= 0x20:
                byte = ord(encoded[i]) - 63
                i += 1
                ll[j] |= (byte & 0x1f) << shift
                shift += 5
            #get the final value adding the previous offset and remember it for the next
            ll[j] = previous[j] + (~(ll[j] >> 1) if ll[j] & 1 else (ll[j] >> 1))
            previous[j] = ll[j]
        #scale by the precision and chop off long coords also flip the positions so
        #its the far more standard lon,lat instead of lat,lon
        decoded.append([float('%.6f' % (ll[1] * inv)), float('%.6f' % (ll[0] * inv))])
    #hand back the list of coordinates
    return decoded

def valhalla_route(station_1_lat, station_1_lng, station_2_lat, station_2_lng):
    
    locations = []
    locations.append({"lat": station_1_lat, "lon": station_1_lng, "type": "break"})
    locations.append({"lat": station_2_lat, "lon": station_2_lng, "type": "break"})
    
    post_data = {
                "locations": locations,
                "costing": "auto_shorter",
                "directions_options": {"units": "miles"}
            }
    
    valhalla_uri = "http://localhost:8002/route"
    print post_data
    
    geocode = requests.post(valhalla_uri, data = json.dumps(post_data))
    geocode_content = json.loads(geocode.content)
    #print json.dumps(geocode_content)
    
    legs_encoded = geocode_content["trip"]["legs"]
    
    legs_decoded = []
    for leg in legs_encoded:
        legs_decoded.append(mapzen_decode(leg["shape"]))
    
    return legs_decoded

def mapzen_route(service, line):
    
    locations = []
    for stop in line.stops:
        station = service.find_station(stop.station_id)
        locations.append({"lat": station.location[0], "lon": station.location[1]})
    
    mapzen_uri = 'https://valhalla.mapzen.com/route?json={"locations":'+json.dumps(locations)+',"costing":"auto_shorter","directions_options":{"units":"miles"}}&api_key=mapzen-t6h4cff'
    print mapzen_uri
    
    geocode = requests.get(mapzen_uri)
    geocode_content = json.loads(geocode.content)
    #print json.dumps(geocode_content)
    legs = geocode_content["trip"]["legs"]
    print mapzen_decode(legs[0]["shape"])
    
    return 0

def osm_route(service, line):
    
    osm_data = LoadOsm("car")
    #osm_data.loadOsm("nyc.osm")
    router = Router(osm_data)
        
    for i in range(1, len(line.stops)):
        stop_1 = line.stops[i-1]
        stop_2 = line.stops[i]
        station_1 = service.find_station(stop_1.station_id)
        station_2 = service.find_station(stop_2.station_id)
        location_1 = station_1.location
        location_2 = station_2.location

        node_1 = osm_data.findNode(location_1[0], location_1[1])
        node_2 = osm_data.findNode(location_2[0], location_2[1])

        print "Routing from %d to %d" % (node_1, node_2)
        result, route = router.doRoute(node_1, node_2)

        if result == 'success':
            # list the nodes
            print(route)

            # list the lat/long
            for i in route:
                node = osm_data.rnodes[i]
                print("%d: %f,%f" % (i, node[0], node[1]))
        else:
            print("Failed (%s)" % result)