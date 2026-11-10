"""Read-only 3D adjudication using source solids, not official Boolean guesses."""
import json
import sys
from pathlib import Path
import numpy as np
from osgeo import ogr,osr
from shapely.geometry import Polygon
from shapely import union_all,from_wkb


def rings(geometry):
    if geometry is None:return
    if geometry.GetPointCount()>=3:
        pts=np.array(geometry.GetPoints(),dtype=float)
        if np.allclose(pts[0],pts[-1]):pts=pts[:-1]
        yield pts
    else:
        for i in range(geometry.GetGeometryCount()):yield from rings(geometry.GetGeometryRef(i))


def source_faces(path):
    ds=ogr.Open(str(path),0);layer=ds.GetLayer(0);sr=layer.GetSpatialRef().Clone()
    faces=[]
    for feature in layer:
        for points in rings(feature.GetGeometryRef()):
            if len(points)!=3:raise ValueError('Source requires nontriangular-face handling')
            faces.append((feature.GetFID(),points))
    return faces,sr


def hits(origin,target,faces):
    direction=target-origin;result=[]
    for identifier,tri in faces:
        matrix=np.column_stack((tri[1]-tri[0],tri[2]-tri[0],-direction))
        if abs(np.linalg.det(matrix))<1e-10:continue
        u,v,t=np.linalg.solve(matrix,origin-tri[0])
        if u>=-1e-8 and v>=-1e-8 and u+v<=1+1e-8 and 1e-7<t<1-1e-7:
            result.append({'source_fid':identifier,'segment_fraction':float(t),'distance_from_observer':float(t*np.linalg.norm(direction))})
    return sorted(result,key=lambda r:r['segment_fraction'])


def check_los(work):
    faces,sr=source_faces(work/'dataset/buildings.shp')
    ds=ogr.Open(str(work/'dataset/point3d.shp'));layer=ds.GetLayer(0)
    src=layer.GetSpatialRef().Clone();src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    sr.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER);transform=osr.CoordinateTransformation(src,sr)
    geometry=[];attributes=[]
    for fid in (0,2):
        f=layer.GetFeature(fid);p=f.GetGeometryRef().Clone();p.Transform(transform);geometry.append(np.array(p.GetPoint()))
        fields={k.lower():v for k,v in f.items().items()}
        attributes.append(np.array([fields[k] for k in ['x','y','z']],dtype=float))
    a=hits(*attributes,faces);g=hits(*geometry,faces)
    delivered=json.loads((work/'output/los_stats.json').read_text(encoding='utf-8'))
    return {'source_triangles':len(faces),'algorithm':'Independent barycentric linear-system intersection over the open 3D segment',
            'attribute_coordinate_hits':a,'transformed_geometry_hits':g,
            'independent_visible_attributes':not bool(a),'independent_visible_geometry':not bool(g),
            'candidate_visible':delivered['visible'],
            'scope':'All supplied solid faces included, with endpoint contacts excluded; target-support wall remains an obstacle.'}


def check_footprints(work):
    faces,sr=source_faces(work/'dataset/buildings.shp')
    polygons=[Polygon(tri[:,:2]) for _,tri in faces if Polygon(tri[:,:2]).area>1e-8]
    expected=union_all(polygons);comparisons=[]
    for p in (work/'output').rglob('*.gpkg'):
        ds=ogr.Open(str(p))
        for layer in ds:
            geoms=[from_wkb(bytes(f.GetGeometryRef().ExportToWkb())) for f in layer if f.GetGeometryRef()]
            if not geoms:continue
            actual=union_all(geoms)
            comparisons.append({'path':str(p.relative_to(work)),'layer':layer.GetName(),'features':len(geoms),
                'area':actual.area,'symmetric_difference_area':actual.symmetric_difference(expected).area,
                'valid':actual.is_valid,'has_z':actual.has_z,'crs_same_as_input':bool(layer.GetSpatialRef().IsSame(sr))})
    return {'expected_area_from_projected_source_faces':expected.area,'source_faces':len(faces),'comparisons':comparisons}


if __name__=='__main__':
    root=Path(sys.argv[1]);result={}
    for identifier,fn in [('42',check_los),('43',check_footprints)]:
        work=root/'tasks'/identifier/'attempt_01'
        try:result[identifier]=fn(work)
        except Exception as e:result[identifier]={'error':str(e)}
        (work/'evaluation/independent-3d.json').write_text(json.dumps(result[identifier],ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True,indent=2))
