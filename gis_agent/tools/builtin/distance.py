import math
from gis_agent.tools.base import Tool
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

distance_tool=Tool(
    name="calculate_distance",
    description=("计算两组经纬度的球面大圆距离，返回千米。输入为角度；不用于投影平面距离或道路距离。"),
    parameters={
        "type":"object",
        "properties":{
            "lat1":{"type":"number"},
            "lon1":{"type":"number"},
            "lat2":{"type":"number"},
            "lon2":{"type":"number"},
        },
        "required":["lat1","lon1","lat2","lon2"],
    },
    function=calculate_distance,
)
