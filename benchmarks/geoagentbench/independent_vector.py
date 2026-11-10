"""Read-only outcome checks. Never import or execute candidate solutions.

Run with the configured QGIS Python and one experiment directory.
Checks cover full counts, coordinate rounding, pixel-centre area and directed
network cost. Their scope is narrower than whole-task professional correctness.
"""
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd
import networkx as nx
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import from_bounds, transform as window_transform


def run(root):
    results={}
    work=root/'tasks/17/attempt_01'
    pts=gpd.read_file(work/'dataset/fatal_collisions.geojson');areas=gpd.read_file(work/'dataset/nyc_boroughs.geojson')
    joined=gpd.sjoin(pts.to_crs(areas.crs),areas,how='left',predicate='within')
    counts=joined.groupby('name').size().to_dict() if 'name' in joined else joined.groupby('BoroName').size().to_dict()
    actual=pd.read_csv(work/'output/fatal_collisions_2016_by_borough.csv').set_index('borough')
    results['17']={'source_points':len(pts),'matched_points':int(joined.index_right.notna().sum()),'counts':counts,
                   'counts_match':all(int(actual.loc[k,'fatal_collisions'])==int(v) for k,v in counts.items())}
    work=root/'tasks/23/attempt_01';pts=gpd.read_file(work/'dataset/High_Blood_Level_Results.shp').to_crs(4326)
    actual=pd.read_csv(work/'output/staged/rounded_points.csv')
    results['23']={'input_records':len(pts),'output_records':len(actual),
        'rounded_longitude_max_error':float(np.max(np.abs(np.round(pts.geometry.x.to_numpy(),2)-actual.lon_round2))),
        'rounded_latitude_max_error':float(np.max(np.abs(np.round(pts.geometry.y.to_numpy(),2)-actual.lat_round2)))}
    work=root/'tasks/37/attempt_01';parcels=gpd.read_file(work/'dataset/parcels.shp')
    actual=pd.read_csv(work/'output/parcels_impervious_area.csv',dtype={'Parcel_ID':str}).set_index('Parcel_ID');errors=[];pixel_errors=[]
    with rasterio.open(work/'dataset/impervious.tif') as ds:
        parcels=parcels.to_crs(ds.crs);area=abs(ds.transform.a*ds.transform.e-ds.transform.b*ds.transform.d)*ds.crs.linear_units_factor[1]**2
        for row in parcels.itertuples():
            window=from_bounds(*row.geometry.bounds,transform=ds.transform).round_offsets().round_lengths()
            # Expand then use centres, matching Tabulate Area raster semantics.
            window=rasterio.windows.Window(max(0,window.col_off-1),max(0,window.row_off-1),window.width+2,window.height+2)
            a=ds.read(1,window=window);mask=geometry_mask([row.geometry.__geo_interface__],out_shape=a.shape,transform=window_transform(window,ds.transform),invert=True)
            count=int(np.sum(mask&(a==1)));key=str(getattr(row,'Parcel_ID'));reported=actual.loc[key]
            pixel_errors.append(abs(count-int(reported.IMP_PIX)));errors.append(abs(count*area-float(reported.IMP_AREA_M2)))
    results['37']={'parcels':len(parcels),'pixel_area_m2':area,'impervious_pixel_count_max_error':max(pixel_errors),
                   'impervious_area_m2_max_error':max(errors),'area_tolerance_m2':.05,
                   'tolerance_reason':'At most two 0.02323 m2 boundary pixels differ between GDAL and Rasterio rasterization, plus CSV rounding.'}
    work=root/'tasks/33/attempt_01';g=nx.read_graphml(work/'dataset/street_graph.graphml',force_multigraph=True)
    # Origin is explicitly specified in the official prompt; choose the actual
    # closest vertex in geographic coordinates using a local geodesic metric.
    from pyproj import Geod
    geod=Geod(ellps='WGS84');lon,lat=-88.22625178710955,40.109442588847976
    origin=min(g,key=lambda n:geod.inv(lon,lat,float(g.nodes[n]['x']),float(g.nodes[n]['y']))[2])
    for a,b,k,d in g.edges(keys=True,data=True):d['cost']=float(d['travel_time'])
    distances=nx.single_source_dijkstra_path_length(g,origin,weight='cost')
    candidate=pd.read_csv(work/'output/staged/nodes_travel_time.csv',dtype=str)
    errors=[abs(float(row.travel_time_s)-distances[row.node_id]) for row in candidate.itertuples() if row.node_id in distances]
    results['33']={'origin':origin,'reachable':len(distances),'vertices':g.number_of_nodes(),
                   'tested_reachable_nodes':len(errors),'travel_time_seconds_max_error':max(errors),
                   'candidate_unreachable_nodes':int(candidate.travel_time_s.isna().sum())}
    print(json.dumps(results,ensure_ascii=True,indent=2))
    for identifier,r in results.items():
        (root/'tasks'/identifier/'attempt_01/evaluation/independent-vector.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':run(Path(sys.argv[1]).resolve())
