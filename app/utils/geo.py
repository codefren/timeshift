from math import radians, sin, cos, sqrt, atan2

def haversine_distance(lat1:float, lon1:float, lat2:float, lon2:float) -> float:
    """Calculate the distance between two geographical points using the Haversine formula. Returns meters"""

    # Radio de la Tierra en metros
    R = 6371000

    # Convertir grados a radianes
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])

    # Diferencias
    dlat = lat2 - lat1
    dlon = lon2 - lon1

    # Fórmula de Haversine
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    distancia = R * c

    return distancia