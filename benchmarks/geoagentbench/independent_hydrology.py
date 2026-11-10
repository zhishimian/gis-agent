"""Independent graph recurrences and filled-minus-raw identity, read-only."""
import json
import sys
from pathlib import Path
from collections import deque
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from benchmarks.geoagentbench.scientific_checks import raster,flow_lengths


def graph_order(receiver,valid):
    target=receiver.ravel();mask=valid.ravel();n=len(target);indegree=np.zeros(n,dtype=np.int64)
    np.add.at(indegree,target[target>=0],1)
    queue=deque(np.flatnonzero(mask & (indegree==0)).tolist());order=[]
    while queue:
        node=queue.popleft();order.append(node);other=target[node]
        if other>=0:
            indegree[other]-=1
            if indegree[other]==0:queue.append(int(other))
    return target,order


def run(root):
    results={}
    for identifier,folder in [(45,'output'),(50,'output/hydro'),(51,'output/rasters')]:
        work=root/'tasks'/f'{identifier:02d}'/'attempt_01';out=work/folder
        try:
            name='flow_direction_d8.tif' if identifier==45 else 'flow_direction.tif'
            flow,_,meta=raster(out/name);_,valid,_=raster(work/'dataset/dem_filled.tif')
            codes=np.unique(flow[valid]);original_codes=codes.tolist()
            if identifier==51:
                # This candidate explicitly documents clockwise ordinal codes.
                # Convert once to the checker's ESRI bit flags; do not infer
                # an encoding merely from the observed numeric range.
                mapped=np.zeros_like(flow)
                for ordinal,flag in enumerate([1,2,4,8,16,32,64,128],start=1):mapped[flow==ordinal]=flag
                flow=mapped;codes=np.unique(flow[valid])
            allowed=np.isin(codes,[0,1,2,4,8,16,32,64,128])
            if not allowed.all():raise ValueError('Non-ESRI encoding requires an explicit mapping: '+str(codes))
            _,_,_,resolved,receiver=flow_lengths(flow,valid,meta['transform'])
            target,order=graph_order(receiver,valid);acc=valid.ravel().astype(np.int64)
            for node in order:
                other=target[node]
                if other>=0:acc[other]+=acc[node]
            aname='flow_accumulation_d8.tif' if identifier==45 else 'flow_accumulation.tif'
            actual,va,_=raster(out/aname);delta=actual[valid&va]-acc.reshape(valid.shape)[valid&va]
            r={'valid_cells':int(valid.sum()),'topologically_resolved':resolved,'directions':codes.tolist(),
               'accumulation_error_including_self':float(np.max(np.abs(delta))),
               'accumulation_error_excluding_self':float(np.max(np.abs(delta+1))),
               'independent_outlet_mass':int(acc[(target<0)&valid.ravel()].sum()),'source_direction_codes':original_codes}
            if identifier in (50,51):
                mname='stream_mask.tif' if identifier==50 else 'stream_network.tif'
                stream,sm,_=raster(out/mname);stream=(stream>0)&sm&valid;mask=stream.ravel();parents=[[] for _ in range(len(target))]
                for node in np.flatnonzero(mask):
                    other=target[node]
                    if other>=0 and mask[other]:parents[other].append(node)
                magnitudes=np.zeros(len(target),dtype=np.int64)
                for node in order:
                    if not mask[node]:continue
                    values=[magnitudes[x] for x in parents[node]]
                    if not values:magnitudes[node]=1
                    elif identifier==51:magnitudes[node]=sum(values)
                    else:
                        maximum=max(values);magnitudes[node]=maximum+(values.count(maximum)>=2)
                expected=magnitudes.reshape(valid.shape)
                actual,va,_=raster(out/('stream_order.tif' if identifier==50 else 'shreve_magnitude.tif'))
                r.update(stream_cells=int(stream.sum()),stream_order_max_abs_error=float(np.max(np.abs(actual[stream]-expected[stream]))),
                         stream_order_mismatches=int(np.sum(actual[stream]!=expected[stream])),independent_max_order=int(expected.max()))
            results[str(identifier)]=r
        except Exception as e:results[str(identifier)]={'error':str(e)}
    work=root/'tasks/46/attempt_01'
    raw,valid,_=raster(work/'dataset/dem.tif');filled,vf,_=raster(work/'output/dem_filled.tif');depth,vd,_=raster(work/'output/sink_depth.tif')
    mask=valid&vf&vd;difference=depth[mask]-(filled-raw)[mask]
    results['46']={'tested_cells':int(mask.sum()),'depth_identity_max_abs_error':float(np.abs(difference).max()),
                   'filled_below_raw':int(np.sum((filled<raw-1e-5)&mask))}
    for identifier,r in results.items():
        (root/'tasks'/identifier/'attempt_01/evaluation/independent-hydrology.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=True,indent=2))


if __name__=='__main__':run(Path(sys.argv[1]).resolve())
