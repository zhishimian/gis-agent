import math

def calculate_distance(lat1,lon1,lat2,lon2):
    r=6371.0
    lat1=math.radians(lat1)
    lat2=math.radians(lat2)

    dlat=lat2-lat1
    dlon=math.radians(lon2-lon1)

    a=(math.sin(dlat/2)**2
       +math.cos(lat1)
       *math.cos(lat2)
       *math.sin(dlon/2)**2
       )

    c=2*math.asin(math.sqrt(a))

    return r*c

tools=[
    {
        "type":"function",
        "function":{
            "name":"calculate_distance",
            "description":"calculate the great-circle distance between two geographic coordinates",
            "parameters":{
                "type":"object",
                "properties":{
                    "lat1":{"type":"number"},
                    "lon1":{"type":"number"},
                    "lat2":{"type":"number"},
                    "lon2":{"type":"number"},
                },
                "required":["lat1","lon1","lat2","lon2"],
            },
        },
    }
]

tools_functions={
    "calculate_distance": calculate_distance
}