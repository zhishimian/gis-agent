"""Independent, read-only mathematical checks of selected deterministic requirements.

No candidate functions are imported or executed. Every comparison identifies its
scope. A matching intermediate is evidence only, not an automatic whole-task pass.
"""
import heapq
import json
import math
import sys
from collections import deque
from pathlib import Path
import numpy as np
from osgeo import gdal, osr

gdal.UseExceptions()


def raster(path):
    ds=gdal.Open(str(path));b=ds.GetRasterBand(1);a=b.ReadAsArray().astype(float)
    nd=b.GetNoDataValue();valid=np.isfinite(a)
    if nd is not None:valid &= a!=nd
    meta={'shape':a.shape,'transform':ds.GetGeoTransform(),'crs':ds.GetProjection(),'nodata':nd}
    return a,valid,meta


def same_grid(a,b):
    if a['shape']!=b['shape'] or not np.allclose(a['transform'],b['transform'],rtol=0,atol=1e-8):return False
    x=osr.SpatialReference();y=osr.SpatialReference()
    if not a['crs'] or not b['crs']:return a['crs']==b['crs']
    x.ImportFromWkt(a['crs']);y.ImportFromWkt(b['crs'])
    return bool(x.IsSame(y))


def fill(a,valid):
    h,w=a.shape;out=a.copy();seen=np.zeros(a.shape,bool);queue=[]
    for i,j in zip(*np.where(valid)):
        if i in (0,h-1) or j in (0,w-1) or any(not valid[i+di,j+dj] for di,dj in ((-1,0),(1,0),(0,-1),(0,1))):
            seen[i,j]=True;heapq.heappush(queue,(float(a[i,j]),int(i),int(j)))
    offsets=[(di,dj) for di in (-1,0,1) for dj in (-1,0,1) if di or dj]
    while queue:
        z,i,j=heapq.heappop(queue)
        for di,dj in offsets:
            ni,nj=i+di,j+dj
            if 0<=ni<h and 0<=nj<w and valid[ni,nj] and not seen[ni,nj]:
                seen[ni,nj]=True;out[ni,nj]=max(z,a[ni,nj]);heapq.heappush(queue,(out[ni,nj],ni,nj))
    return out


def flow_lengths(a,valid,transform):
    h,w=a.shape;n=h*w
    target=np.full(n,-1,dtype=np.int64);distance=np.zeros(n);indegree=np.zeros(n,np.int64)
    offsets={1:(0,1),2:(1,1),4:(1,0),8:(1,-1),16:(0,-1),32:(-1,-1),64:(-1,0),128:(-1,1)}
    for code,(di,dj) in offsets.items():
        ii,jj=np.where(valid & (a==code));ni,nj=ii+di,jj+dj
        ok=(ni>=0)&(ni<h)&(nj>=0)&(nj<w);ii,jj,ni,nj=ii[ok],jj[ok],ni[ok],nj[ok]
        ok=valid[ni,nj];ii,jj,ni,nj=ii[ok],jj[ok],ni[ok],nj[ok]
        source=ii*w+jj;dest=ni*w+nj;target[source]=dest
        distance[source]=math.hypot(dj*transform[1]+di*transform[2],dj*transform[4]+di*transform[5])
        np.add.at(indegree,dest,1)
    q=deque(np.flatnonzero(valid.ravel() & (indegree==0)).tolist());order=[];up=np.zeros(n)
    while q:
        x=q.popleft();order.append(x);y=target[x]
        if y>=0:
            up[y]=max(up[y],up[x]+distance[x]);indegree[y]-=1
            if indegree[y]==0:q.append(int(y))
    down=np.zeros(n);basin=np.full(n,-1,dtype=np.int64)
    for x in reversed(order):
        y=target[x]
        down[x]=0 if y<0 else distance[x]+down[y]
        basin[x]=x if y<0 else basin[y]
    return up.reshape(a.shape),down.reshape(a.shape),basin.reshape(a.shape),len(order),target.reshape(a.shape)


def check(work,identifier):
    data=work/'dataset';expectations=[];notes=[]
    if identifier in (21,41):
        name='landCover.tif' if identifier==21 else 'Protected_Status.tif'
        a,valid,meta=raster(data/name)
        mapping={11:10,21:8,22:7,23:8,24:9,31:6,41:2,42:1,43:2,52:3,71:3,72:3,81:4,82:6,90:4,95:4,255:10} if identifier==21 else {0:1,1:3,2:6,3:9,4:10,255:10}
        expected=np.full(a.shape,np.nan)
        for source,value in mapping.items():expected[a==source]=value
        mask=np.isfinite(expected)&valid
        expectations.append(('explicit_value_reclassification',expected,mask,meta,.00001))
        notes.append('NoData cells are excluded from numerical agreement; explicit 255 mapping and NoData display require separate review.')
    elif identifier==34:
        a,va,meta=raster(data/'2015_Nature_Africa_PR.2015.tif');b,vb,other=raster(data/'2015_Nature_Africa_PR.2000.tif')
        if same_grid(meta,other):expectations.append(('malaria_2015_minus_2000',a-b,va&vb,meta,1e-6))
    elif identifier==22:
        names=['distance.tif','ruggedness.tif','Protected_Status_reclassified.tif','landCover_reclassified.tif']
        layers=[raster(data/n) for n in names];meta=layers[0][2]
        if all(same_grid(meta,x[2]) for x in layers):
            expectations.append(('explicit_weighted_sum',sum(x[0]*w for x,w in zip(layers,[1,1.25,1,1.25])),
                                 np.logical_and.reduce([x[1] for x in layers]),meta,1e-4))
    elif identifier in (7,30):
        a,valid,meta=raster(data/'Elevation_2050.tif')
        expectations.append(('water_level_minus_dem_positive_depth',np.maximum(0,-200-a),valid,meta,1e-4))
        notes.append('This checks depth arithmetic in source elevation units, not building damage or physical unit interpretation.')
    elif identifier in (44,46):
        a,valid,meta=raster(data/'dem.tif');filled=fill(a,valid)
        expectations.append(('zero_slope_priority_flood_8_neighbor',filled if identifier==44 else filled-a,valid,meta,1e-4))
        notes.append('Alternative drainage algorithms with a declared positive minimum slope can differ from this zero-slope reference.')
    elif identifier in (47,48,52):
        a,valid,meta=raster(data/'flow_direction.tif');up,down,basin,count,target=flow_lengths(a,valid,meta['transform'])
        notes.append(f'Topologically resolved {count} of {int(valid.sum())} valid input cells; length units follow the input CRS.')
        if identifier!=52:expectations.append(('D8_maximum_'+('upstream' if identifier==48 else 'downstream')+'_length',up if identifier==48 else down,valid,meta,1e-3))
        else:expectations.append(('D8_outlet_partition',basin,valid & (basin>=0),meta,0))
    rows=[]
    for path in sorted((work/'output').rglob('*.tif')):
        if 'python_logs' in path.parts:continue
        try:
            a,valid,meta=raster(path)
            for title,expected,mask,emeta,tolerance in expectations:
                if not same_grid(meta,emeta):
                    rows.append({'candidate':str(path.relative_to(work)),'check':title,'comparable':False,'reason':'Different grid/CRS; no automatic resampling'});continue
                common=mask&valid;missed=int((mask&~valid).sum())
                if title=='D8_outlet_partition':
                    pairs=np.unique(np.column_stack([expected[common],a[common]]),axis=0)
                    one_to_one=len(np.unique(pairs[:,0]))==len(pairs)==len(np.unique(pairs[:,1])) if len(pairs) else False
                    metrics={'equivalent_partition':bool(one_to_one),'reference_basins':int(np.unique(expected[common]).size),
                             'candidate_basins':int(np.unique(a[common]).size)}
                else:
                    delta=np.abs(a[common]-expected[common])
                    metrics={'max_abs_error':float(delta.max()) if delta.size else None,'mean_abs_error':float(delta.mean()) if delta.size else None,
                             'fraction_within_tolerance':float((delta<=tolerance).mean()) if delta.size else None,'absolute_tolerance':tolerance}
                rows.append({'candidate':str(path.relative_to(work)),'check':title,'comparable':True,'tested_cells':int(common.sum()),'missing_required_cells':missed,**metrics})
        except Exception as error:rows.append({'candidate':str(path.relative_to(work)),'error':str(error)})
    return {'id':identifier,'comparisons':rows,'notes':notes,'scope':'Independent numerical/partition evidence only. Review final-output linkage and remaining task requirements.'}


if __name__=='__main__':
    work=Path(sys.argv[1]);identifier=int(sys.argv[2]);result=check(work,identifier)
    (work/'evaluation').mkdir(exist_ok=True)
    (work/'evaluation/scientific-checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
