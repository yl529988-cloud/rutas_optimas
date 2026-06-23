# maps_utils.py — GraphHopper → ORS (con alternativas) → OSRM → Simulación
import os
import math
import random
import requests

# ─── API KEYS ────────────────────────────────────────────────────────────────
GH_API_KEY  = os.environ.get('GRAPHHOPPER_API_KEY', '')
ORS_API_KEY = os.environ.get('ORS_API_KEY', '')

GH_URL   = 'https://graphhopper.com/api/1/route'
ORS_URL  = 'https://api.openrouteservice.org/v2/directions/driving-car'
OSRM_URL = 'https://router.project-osrm.org/route/v1'

GH_TIMEOUT   = 8
ORS_TIMEOUT  = 10
OSRM_TIMEOUT = 8


def _haversine_km(lat1, lng1, lat2, lng2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class RealRouteSystem:
    def __init__(self):
        if GH_API_KEY:
            modo = "GraphHopper (carreteras reales)"
        elif ORS_API_KEY:
            modo = "ORS (carreteras reales)"
        else:
            modo = "OSRM + fallback"
        print(f"🗺️  Sistema de rutas iniciado — {modo}")

    # ═══════════════════════════════════════════════════════════
    # PUNTO DE ENTRADA PÚBLICO
    # ═══════════════════════════════════════════════════════════
    def get_real_route(self, start_lat, start_lng, end_lat, end_lng, route_type="all"):
        slat, slng = float(start_lat), float(start_lng)
        elat, elng = float(end_lat),   float(end_lng)

        routes = self._get_routes_with_fallback(slat, slng, elat, elng)
        routes.sort(key=lambda r: r['duration_min'])

        if route_type == "with_tolls":
            filtered = [r for r in routes if r['has_tolls']]
        elif route_type == "without_tolls":
            filtered = [r for r in routes if not r['has_tolls']]
        else:
            filtered = routes

        return filtered if filtered else routes

    # ═══════════════════════════════════════════════════════════
    # CADENA: GraphHopper → ORS → OSRM → Simulación
    # ═══════════════════════════════════════════════════════════
    def _get_routes_with_fallback(self, slat, slng, elat, elng):

        # 1️⃣ GraphHopper
        if GH_API_KEY:
            try:
                base = self._gh_route(slat, slng, elat, elng)
                print("✅ Rutas via GraphHopper (carreteras reales)")
                return self._build_five_routes(base, slat, slng, elat, elng)
            except Exception as e:
                print(f"⚠️  GraphHopper falló ({e}), intentando ORS...")

        # 2️⃣ ORS — intentar obtener múltiples rutas reales
        if ORS_API_KEY:
            try:
                base = self._ors_route_multi(slat, slng, elat, elng)
                print(f"✅ Rutas via ORS (carreteras reales — {len(base)} rutas base)")
                return self._build_five_routes(base, slat, slng, elat, elng)
            except Exception as e:
                print(f"⚠️  ORS falló ({e}), intentando OSRM...")

        # 3️⃣ OSRM
        try:
            base = self._osrm_route(slat, slng, elat, elng)
            print("✅ Rutas via OSRM (carreteras reales)")
            return self._build_five_routes(base, slat, slng, elat, elng)
        except Exception as e:
            print(f"⚠️  OSRM falló ({e}), usando simulación")

        # 4️⃣ Simulación
        print("🔶 Usando rutas simuladas")
        return self._simulate_five_routes(slat, slng, elat, elng)

    # ═══════════════════════════════════════════════════════════
    # GRAPHHOPPER
    # ═══════════════════════════════════════════════════════════
    def _gh_route(self, slat, slng, elat, elng):
        body = {
            'points':          [[slng, slat], [elng, elat]],
            'points_encoded':  False,
            'vehicle':         'car',
            'locale':          'es',
            'instructions':    True,
            'algorithm':       'alternative_route',
            'ch.disable':      True,
            'alternative_route.max_paths':            3,
            'alternative_route.max_weight_factor':    1.6,
        }
        resp = requests.post(
            GH_URL,
            params={'key': GH_API_KEY},
            json=body,
            timeout=GH_TIMEOUT
        )
        resp.raise_for_status()
        data = resp.json()

        if 'paths' not in data or not data['paths']:
            msg = data.get('message', 'sin resultados')
            raise ValueError(f"GraphHopper: {msg}")

        result = []
        for path in data['paths']:
            pts = path.get('points', {})
            if isinstance(pts, dict):
                coords = [[c[0], c[1]] for c in pts.get('coordinates', [])]
            else:
                coords = self._decode_polyline(pts)

            steps = self._parse_gh_steps(path.get('instructions', []))
            result.append({
                'distance_m':  path['distance'],
                'duration_s':  path['time'] / 1000.0,
                'coordinates': coords,
                'steps':       steps,
            })
        return result

    def _decode_polyline(self, encoded, precision=5):
        coords, index, lat, lng = [], 0, 0, 0
        factor = 10 ** precision
        while index < len(encoded):
            for is_lng in (False, True):
                shift, result = 0, 0
                while True:
                    b = ord(encoded[index]) - 63
                    index += 1
                    result |= (b & 0x1F) << shift
                    shift += 5
                    if b < 0x20:
                        break
                delta = ~(result >> 1) if result & 1 else result >> 1
                if is_lng:
                    lng += delta
                    coords.append([lng / factor, lat / factor])
                else:
                    lat += delta
        return coords

    def _parse_gh_steps(self, instructions):
        sign_map = {
            -98: ('arrive',    ''),
            -8:  ('depart',    ''),
            -7:  ('roundabout',''),
            -6:  ('fork',      'left'),
            -3:  ('turn',      'sharp left'),
            -2:  ('turn',      'left'),
            -1:  ('turn',      'slight left'),
             0:  ('continue',  'straight'),
             1:  ('turn',      'slight right'),
             2:  ('turn',      'right'),
             3:  ('turn',      'sharp right'),
             4:  ('arrive',    ''),
             5:  ('merge',     ''),
             6:  ('fork',      'right'),
             7:  ('roundabout',''),
        }
        steps = []
        for ins in instructions:
            mtype, modifier = sign_map.get(ins.get('sign', 0), ('continue', 'straight'))
            steps.append({
                'maneuver': {
                    'type':        mtype,
                    'modifier':    modifier,
                    'instruction': ins.get('text', ''),
                    'location':    [],
                },
                'distance': ins.get('distance', 0),
                'duration': ins.get('time', 0) / 1000.0,
                'name':     ins.get('street_name', ''),
            })
        return steps

    # ═══════════════════════════════════════════════════════════
    # ORS — versión MULTI-RUTA
    # Pide la ruta principal + busca waypoints alternativos
    # para generar rutas genuinamente distintas
    # ═══════════════════════════════════════════════════════════
    def _ors_route_multi(self, slat, slng, elat, elng):
        """
        ORS no soporta rutas alternativas en el endpoint geojson.
        Estrategia: pedimos la ruta base y luego forzamos rutas
        alternativas usando waypoints intermedios calculados
        geométricamente (norte, sur, centro).
        """
        routes = []

        # Ruta 1: directa
        try:
            r = self._ors_single(slat, slng, elat, elng)
            routes.append(r)
        except Exception as e:
            raise ValueError(f"ORS ruta principal falló: {e}")

        # Calcular puntos medios desviados para forzar rutas alternativas
        mid_lat = (slat + elat) / 2
        mid_lng = (slng + elng) / 2

        # Vector perpendicular al trayecto (para desviar norte/sur)
        dlat = elat - slat
        dlng = elng - slng
        dist = math.sqrt(dlat**2 + dlng**2)
        if dist > 0:
            perp_lat = -dlng / dist
            perp_lng =  dlat / dist
        else:
            perp_lat, perp_lng = 0.01, 0

        # Factor de desvío: ~15% de la distancia total
        deviation = dist * 0.20

        waypoints = [
            # Norte
            (mid_lat + perp_lat * deviation, mid_lng + perp_lng * deviation),
            # Sur
            (mid_lat - perp_lat * deviation, mid_lng - perp_lng * deviation),
        ]

        for (wlat, wlng) in waypoints:
            try:
                r = self._ors_single_via(slat, slng, wlat, wlng, elat, elng)
                # Solo agregar si la geometría es suficientemente diferente
                if self._is_different_route(r['coordinates'], routes):
                    routes.append(r)
            except Exception:
                pass  # Si falla un waypoint, ignorar

        return routes

    def _ors_single(self, slat, slng, elat, elng):
        """Pide una ruta directa a ORS."""
        headers = {
            'Authorization': ORS_API_KEY,
            'Content-Type':  'application/json',
        }
        body = {
            'coordinates': [[slng, slat], [elng, elat]],
        }
        resp = requests.post(
            'https://api.openrouteservice.org/v2/directions/driving-car/geojson',
            json=body,
            headers=headers,
            timeout=ORS_TIMEOUT
        )
        resp.raise_for_status()
        data = resp.json()

        if 'features' not in data or not data['features']:
            raise ValueError("ORS sin resultados")

        feature  = data['features'][0]
        props    = feature['properties']
        geometry = feature['geometry']
        coords   = [[c[0], c[1]] for c in geometry['coordinates']]
        steps    = self._parse_ors_steps(props.get('segments', []))

        return {
            'distance_m':  props['summary']['distance'],
            'duration_s':  props['summary']['duration'],
            'coordinates': coords,
            'steps':       steps,
        }

    def _ors_single_via(self, slat, slng, wlat, wlng, elat, elng):
        """Pide ruta pasando por un waypoint intermedio."""
        headers = {
            'Authorization': ORS_API_KEY,
            'Content-Type':  'application/json',
        }
        body = {
            'coordinates': [[slng, slat], [wlng, wlat], [elng, elat]],
        }
        resp = requests.post(
            'https://api.openrouteservice.org/v2/directions/driving-car/geojson',
            json=body,
            headers=headers,
            timeout=ORS_TIMEOUT
        )
        resp.raise_for_status()
        data = resp.json()

        if 'features' not in data or not data['features']:
            raise ValueError("ORS via sin resultados")

        feature  = data['features'][0]
        props    = feature['properties']
        geometry = feature['geometry']
        coords   = [[c[0], c[1]] for c in geometry['coordinates']]

        # Combinar pasos de todos los segmentos
        all_steps = []
        for seg in props.get('segments', []):
            all_steps.extend(seg.get('steps', []))

        parsed_steps = self._parse_ors_steps_raw(all_steps)

        return {
            'distance_m':  props['summary']['distance'],
            'duration_s':  props['summary']['duration'],
            'coordinates': coords,
            'steps':       parsed_steps,
        }

    def _is_different_route(self, new_coords, existing_routes, threshold=0.03):
        """
        Compara el punto medio de la nueva ruta con los de las existentes.
        Si el punto medio difiere menos de `threshold` grados, se descarta.
        """
        if not new_coords or not existing_routes:
            return True
        mid_new = new_coords[len(new_coords) // 2]
        for r in existing_routes:
            coords = r['coordinates']
            if not coords:
                continue
            mid_ex = coords[len(coords) // 2]
            dist = math.sqrt((mid_new[0] - mid_ex[0])**2 + (mid_new[1] - mid_ex[1])**2)
            if dist < threshold:
                return False
        return True

    def _parse_ors_steps(self, segments):
        type_map = {0: 'depart', 1: 'turn', 10: 'arrive'}
        steps = []
        for seg in segments:
            for s in seg.get('steps', []):
                mtype = type_map.get(s.get('type', 0), 'continue')
                steps.append({
                    'maneuver': {
                        'type':        mtype,
                        'modifier':    '',
                        'instruction': s.get('instruction', ''),
                        'location':    [],
                    },
                    'distance': s.get('distance', 0),
                    'duration': s.get('duration', 0),
                    'name':     s.get('name', ''),
                })
        return steps

    def _parse_ors_steps_raw(self, raw_steps):
        type_map = {0: 'depart', 1: 'turn', 10: 'arrive'}
        steps = []
        for s in raw_steps:
            mtype = type_map.get(s.get('type', 0), 'continue')
            steps.append({
                'maneuver': {
                    'type':        mtype,
                    'modifier':    '',
                    'instruction': s.get('instruction', ''),
                    'location':    [],
                },
                'distance': s.get('distance', 0),
                'duration': s.get('duration', 0),
                'name':     s.get('name', ''),
            })
        return steps

    # ═══════════════════════════════════════════════════════════
    # OSRM
    # ═══════════════════════════════════════════════════════════
    def _osrm_route(self, slat, slng, elat, elng):
        url    = f"{OSRM_URL}/driving/{slng},{slat};{elng},{elat}"
        params = {
            'overview':     'full',
            'geometries':   'geojson',
            'steps':        'true',
            'alternatives': 'true',
        }
        resp = requests.get(url, params=params, timeout=OSRM_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        if data.get('code') != 'Ok' or not data.get('routes'):
            raise ValueError("OSRM sin resultados")

        result = []
        for r in data['routes']:
            coords = [[c[0], c[1]] for c in r['geometry']['coordinates']]
            result.append({
                'distance_m':  r['distance'],
                'duration_s':  r['duration'],
                'coordinates': coords,
                'steps':       r['legs'][0].get('steps', []),
            })
        return result

    # ═══════════════════════════════════════════════════════════
    # 5 VARIANTES A PARTIR DE RUTAS REALES
    # ═══════════════════════════════════════════════════════════
    def _build_five_routes(self, base, slat, slng, elat, elng):
        """
        Construye 5 rutas visualmente distintas.
        - Si base tiene N rutas reales (1-3), las usa directamente.
        - Las faltantes se generan desviando la ruta más cercana
          con un offset perpendicular MAYOR al anterior.
        """
        configs = [
            {'id':1,'name':'Ruta Más Rápida',  'icon':'🚀','desc':'Autopista principal — menor tiempo',    'tolls':True,  'sf':1.00,'cf':1.25},
            {'id':2,'name':'Ruta Económica',   'icon':'💰','desc':'Carretera federal sin cuotas',          'tolls':False, 'sf':1.22,'cf':1.00},
            {'id':3,'name':'Alternativa Norte','icon':'🛣️', 'desc':'Alternativa norte — menos tráfico',   'tolls':True,  'sf':1.12,'cf':1.10},
            {'id':4,'name':'Alternativa Sur',  'icon':'🗺️', 'desc':'Vía libre estatal sin cuotas',        'tolls':False, 'sf':1.28,'cf':0.95},
            {'id':5,'name':'Ruta Escénica',    'icon':'🌄','desc':'Caminos secundarios pintorescos',       'tolls':random.choice([True,False]),'sf':1.42,'cf':1.05},
        ]

        # Calcular vector perpendicular para offsets
        dlat = elat - slat
        dlng = elng - slng
        dist = math.sqrt(dlat**2 + dlng**2) or 1
        perp_lat = -dlng / dist
        perp_lng =  dlat / dist

        # Offsets perpendiculares distintos para cada slot sin ruta real
        # En grados: ~0.04° ≈ 4km de separación visual
        slot_offsets = [0.0, 0.05, -0.05, 0.10, -0.10]

        # Rellenar hasta 5 rutas reales con variantes geométricas
        extended_base = list(base)  # copia para no mutar
        for i in range(len(base), 5):
            src = base[i % len(base)]
            off = slot_offsets[i]
            new_coords = self._offset_perpendicular(src['coordinates'], perp_lat, perp_lng, off)
            dist_factor = 1 + abs(off) * 0.15
            extended_base.append({
                'distance_m':  src['distance_m'] * dist_factor,
                'duration_s':  src['duration_s'] * configs[i]['sf'] * dist_factor,
                'coordinates': new_coords,
                'steps':       src.get('steps', []),
            })

        routes = []
        for i, c in enumerate(configs):
            r       = extended_base[i]
            dist_km = r['distance_m'] / 1000.0
            dur_min = max(5, int(r['duration_s'] / 60.0 * c['sf']))
            coords  = r['coordinates']
            toll    = round(dist_km * 0.55, 0) if c['tolls'] else 0
            routes.append(self._build_route_obj(
                c, dist_km, dur_min, coords, toll,
                r.get('steps', []), slat, slng, elat, elng
            ))
        return routes

    # ═══════════════════════════════════════════════════════════
    # OFFSET PERPENDICULAR — desplaza la polilínea lateralmente
    # ═══════════════════════════════════════════════════════════
    def _offset_perpendicular(self, coords, perp_lat, perp_lng, magnitude):
        """
        Desplaza cada punto de la polilínea en dirección perpendicular
        al trayecto. El desplazamiento es mayor en el centro y cero
        en los extremos (forma de arco) para mantener mismo origen/destino.
        """
        n = len(coords)
        result = []
        for i, c in enumerate(coords):
            # Factor sinusoidal: 0 en extremos, 1 en el centro
            t = math.sin(math.pi * i / max(1, n - 1))
            offset_lng = perp_lng * magnitude * t
            offset_lat = perp_lat * magnitude * t
            result.append([c[0] + offset_lng, c[1] + offset_lat])
        return result

    # ═══════════════════════════════════════════════════════════
    # SIMULACIÓN GEOMÉTRICA (solo cuando todo falla)
    # ═══════════════════════════════════════════════════════════
    def _simulate_five_routes(self, slat, slng, elat, elng):
        dist_km = max(5, _haversine_km(slat, slng, elat, elng))

        dlat = elat - slat
        dlng = elng - slng
        dist = math.sqrt(dlat**2 + dlng**2) or 1
        perp_lat = -dlng / dist
        perp_lng =  dlat / dist

        configs = [
            {'id':1,'name':'Ruta Más Rápida',  'icon':'🚀','desc':'Autopista con cuota (estimada)',   'tolls':True,  'sf':1.00,'cf':1.25,'off':0.0},
            {'id':2,'name':'Ruta Económica',   'icon':'💰','desc':'Carretera libre (estimada)',        'tolls':False, 'sf':1.22,'cf':1.00,'off':0.06},
            {'id':3,'name':'Alternativa Norte','icon':'🛣️', 'desc':'Alternativa norte (estimada)',   'tolls':True,  'sf':1.12,'cf':1.10,'off':-0.06},
            {'id':4,'name':'Alternativa Sur',  'icon':'🗺️', 'desc':'Ruta estatal sur (estimada)',    'tolls':False, 'sf':1.28,'cf':0.95,'off':0.12},
            {'id':5,'name':'Ruta Escénica',    'icon':'🌄','desc':'Caminos secundarios (estimada)',   'tolls':random.choice([True,False]),'sf':1.42,'cf':1.05,'off':-0.12},
        ]
        routes = []
        for c in configs:
            base_coords = self._interpolate_coords_via_perp(
                slat, slng, elat, elng, perp_lat, perp_lng, c['off'], points=30
            )
            d    = dist_km * (1 + abs(c['off']) * 0.4)
            t    = max(10, int((d / 100) * 60 * c['sf']))
            toll = round(d * 0.55, 0) if c['tolls'] else 0
            routes.append(self._build_route_obj(c, d, t, base_coords, toll, [], slat, slng, elat, elng))
        return routes

    def _interpolate_coords_via_perp(self, slat, slng, elat, elng, perp_lat, perp_lng, offset, points=30):
        """Interpolación con desvío perpendicular para rutas simuladas."""
        coords = []
        for i in range(points + 1):
            t = i / points
            # Interpolación lineal base
            base_lng = slng + t * (elng - slng)
            base_lat = slat + t * (elat - slat)
            # Desvío sinusoidal perpendicular
            factor = math.sin(math.pi * t) * offset
            coords.append([
                base_lng + perp_lng * factor,
                base_lat + perp_lat * factor,
            ])
        return coords

    # ═══════════════════════════════════════════════════════════
    # OBJETO RUTA UNIFICADO
    # ═══════════════════════════════════════════════════════════
    def _build_route_obj(self, c, dist_km, dur_min, coords, toll_cost, raw_steps, slat, slng, elat, elng):
        speed = int(dist_km / (dur_min / 60)) if dur_min > 0 else 80
        return {
            'id':                 c['id'],
            'name':               c['name'],
            'icon':               c['icon'],
            'description':        c['desc'],
            'has_tolls':          c['tolls'],
            'duration_min':       dur_min,
            'duration_formatted': self._fmt_time(dur_min),
            'distance_km':        round(dist_km, 1),
            'speed_kmh':          min(speed, 130),
            'fuel_estimate': {
                'liters':   round(dist_km * 0.085 * c['cf'], 1),
                'cost_mxn': round(dist_km * 0.085 * 22.5 * c['cf'], 1),
            },
            'toll_cost_mxn':    toll_cost,
            'traffic_estimate': self._traffic(),
            'primary_roads':    random.randint(65, 95),
            'steps':            self._parse_steps(raw_steps, slat, slng, elat, elng, c['id']),
            'geometry':         {'coordinates': coords},
        }

    # ═══════════════════════════════════════════════════════════
    # PARSEO DE PASOS
    # ═══════════════════════════════════════════════════════════
    def _parse_steps(self, raw_steps, slat, slng, elat, elng, route_id):
        if not raw_steps:
            return self._simulated_steps(slat, slng, elat, elng, route_id)
        steps = []
        for s in raw_steps:
            maneuver = s.get('maneuver', {})
            mtype    = maneuver.get('type', '')
            modifier = maneuver.get('modifier', '')
            name     = s.get('name', '')
            dist     = s.get('distance', 0)
            instr    = maneuver.get('instruction') or self._instruction(mtype, modifier, name, dist)
            steps.append({
                'maneuver': {
                    'type':        mtype,
                    'modifier':    modifier,
                    'instruction': instr,
                    'location':    maneuver.get('location', []),
                },
                'distance': dist,
                'duration': s.get('duration', 0),
                'name':     name,
            })
        return steps

    def _instruction(self, mtype, modifier, name, distance):
        road     = f" por {name}" if name else ""
        dist_txt = (f" durante {round(distance/1000,1)} km" if distance > 1000
                    else f" durante {int(distance)} m" if distance > 100 else "")
        MAP = {
            ('depart',''):            f"Salga hacia adelante{road}",
            ('depart','right'):       f"Salga a la derecha{road}",
            ('depart','left'):        f"Salga a la izquierda{road}",
            ('turn','right'):         f"Gire a la derecha{road}",
            ('turn','left'):          f"Gire a la izquierda{road}",
            ('turn','sharp right'):   f"Gire a la derecha cerrado{road}",
            ('turn','sharp left'):    f"Gire a la izquierda cerrado{road}",
            ('turn','slight right'):  f"Manténgase a la derecha{road}",
            ('turn','slight left'):   f"Manténgase a la izquierda{road}",
            ('turn','uturn'):         f"Dé media vuelta{road}",
            ('continue',''):          f"Continúe recto{road}{dist_txt}",
            ('continue','straight'):  f"Continúe recto{road}{dist_txt}",
            ('merge','right'):        f"Incorpórese por la derecha{road}",
            ('merge','left'):         f"Incorpórese por la izquierda{road}",
            ('on ramp','right'):      "Tome la rampa de acceso a la derecha",
            ('on ramp','left'):       "Tome la rampa de acceso a la izquierda",
            ('off ramp','right'):     f"Tome la salida a la derecha{road}",
            ('off ramp','left'):      f"Tome la salida a la izquierda{road}",
            ('fork','right'):         "En el cruce, manténgase a la derecha",
            ('fork','left'):          "En el cruce, manténgase a la izquierda",
            ('roundabout',''):        f"En la rotonda, tome la salida{road}",
            ('arrive',''):            "Ha llegado a su destino",
            ('arrive','right'):       "Su destino está a la derecha",
            ('arrive','left'):        "Su destino está a la izquierda",
        }
        key = (mtype, modifier)
        if key in MAP:
            return MAP[key]
        if mtype == 'arrive':
            return "Ha llegado a su destino"
        if mtype in ('roundabout', 'rotary'):
            return f"En la rotonda, tome la salida{road}"
        return f"Continúe por {name}{dist_txt}" if name else f"Continúe recto{dist_txt}"

    def _simulated_steps(self, slat, slng, elat, elng, route_id):
        templates = [
            [
                {'maneuver':{'type':'depart','modifier':'','instruction':'Salga de su ubicación actual','location':[slng,slat]},'distance':500,'duration':60,'name':''},
                {'maneuver':{'type':'turn','modifier':'right','instruction':'Gire a la derecha hacia la autopista','location':[]},'distance':2000,'duration':120,'name':'Autopista'},
                {'maneuver':{'type':'continue','modifier':'straight','instruction':'Continúe recto por la autopista','location':[]},'distance':15000,'duration':600,'name':'Autopista principal'},
                {'maneuver':{'type':'off ramp','modifier':'right','instruction':'Tome la salida a la derecha','location':[]},'distance':1000,'duration':90,'name':''},
                {'maneuver':{'type':'arrive','modifier':'','instruction':'Ha llegado a su destino','location':[elng,elat]},'distance':0,'duration':0,'name':''},
            ],
            [
                {'maneuver':{'type':'depart','modifier':'','instruction':'Salga de su ubicación actual','location':[slng,slat]},'distance':300,'duration':40,'name':''},
                {'maneuver':{'type':'turn','modifier':'left','instruction':'Gire a la izquierda en Av. Principal','location':[]},'distance':3000,'duration':300,'name':'Avenida Principal'},
                {'maneuver':{'type':'continue','modifier':'straight','instruction':'Continúe recto — Carretera Federal','location':[]},'distance':12000,'duration':720,'name':'Carretera Federal'},
                {'maneuver':{'type':'turn','modifier':'right','instruction':'Gire a la derecha hacia el destino','location':[]},'distance':800,'duration':60,'name':''},
                {'maneuver':{'type':'arrive','modifier':'','instruction':'Ha llegado a su destino','location':[elng,elat]},'distance':0,'duration':0,'name':''},
            ],
            [
                {'maneuver':{'type':'depart','modifier':'','instruction':'Salga de su ubicación actual','location':[slng,slat]},'distance':400,'duration':50,'name':''},
                {'maneuver':{'type':'roundabout','modifier':'','instruction':'En la rotonda, tome la segunda salida','location':[]},'distance':500,'duration':45,'name':''},
                {'maneuver':{'type':'continue','modifier':'straight','instruction':'Continúe por la carretera federal','location':[]},'distance':10000,'duration':600,'name':'Carretera Federal'},
                {'maneuver':{'type':'fork','modifier':'right','instruction':'En el cruce, manténgase a la derecha','location':[]},'distance':2000,'duration':120,'name':''},
                {'maneuver':{'type':'arrive','modifier':'','instruction':'Ha llegado a su destino','location':[elng,elat]},'distance':0,'duration':0,'name':''},
            ],
        ]
        return templates[route_id % len(templates)]

    # ═══════════════════════════════════════════════════════════
    # HELPERS GEOMÉTRICOS
    # ═══════════════════════════════════════════════════════════
    def _fmt_time(self, minutes):
        if minutes >= 60:
            h, m = divmod(minutes, 60)
            return f"{h}h {m}min" if m else f"{h}h"
        return f"{minutes} min"

    def _traffic(self):
        level = random.choices(['Bajo','Moderado','Alto'], weights=[40,40,20])[0]
        color = {'Bajo':'green','Moderado':'orange','Alto':'red'}[level]
        delay = {'Bajo':'+0 min','Moderado':f'+{random.randint(5,15)} min','Alto':f'+{random.randint(15,35)} min'}[level]
        return {'level':level,'color':color,'delay':delay}

    def _offset_coordinates(self, coords, offset):
        """Offset lateral simple (legacy, mantenido por compatibilidad)."""
        n = len(coords)
        return [[c[0] + math.sin(i/max(1,n)*math.pi)*offset*0.4,
                 c[1] + math.sin(i/max(1,n)*math.pi)*offset]
                for i, c in enumerate(coords)]

    def _interpolate_coords(self, slat, slng, elat, elng, points=25):
        mid_lat = (slat+elat)/2 + random.uniform(-0.3, 0.3)
        mid_lng = (slng+elng)/2 + random.uniform(-0.3, 0.3)
        coords  = []
        for i in range(points+1):
            t = i / points
            coords.append([
                (1-t)**2*slng + 2*(1-t)*t*mid_lng + t**2*elng,
                (1-t)**2*slat + 2*(1-t)*t*mid_lat + t**2*elat,
            ])
        return coords
    