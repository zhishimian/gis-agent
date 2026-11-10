"""Read-only raster identities and input semantic checks; QGIS Python CLI."""
import json
import sys
from pathlib import Path
import numpy as np
from osgeo import gdal
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from benchmarks.geoagentbench.scientific_checks import raster,same_grid


def compare(paths,formula):
    layers=[raster(p) for p in paths]
    if not all(same_grid(layers[0][2],v[2]) for v in layers):return {'error':'Different grids; no silent resampling'}
    valid=np.logical_and.reduce([v[1] for v in layers]);actual=layers[-1][0];expected=formula([v[0] for v in layers[:-1]])
    return {'tested_cells':int(valid.sum()),'maximum_absolute_error':float(np.abs(actual[valid]-expected[valid]).max()),
            'scope':'Arithmetic on persisted inputs; source field extraction and scientific unit meaning checked separately.'}


def run(root):
    results={}
    for ident in ['04','25']:
        work=root/'tasks'/ident/'attempt_01';out=work/'output';folder=out/'work' if ident=='04' else out
        result=compare([folder/'drainage_reclass.tif',folder/'water_depth_reclass.tif',
                        out/('work/vulnerable_weighted.tif' if ident=='04' else 'vulnerable_areas.tif')],lambda a:a[0]*5+a[1]*4)
        if ident=='04':result['risk']=compare([out/'vulnerable_areas.tif',out/'work/land_cover_reclass.tif',out/'risk_zones.tif'],lambda a:a[0]*8+a[1]*10)
        results[ident]=result
    work=root/'tasks/26/attempt_01';out=work/'output'
    result=compare([out/'data/vulnerable_norm.tif',out/'data/land_cover_reclass.tif',out/'risk_zones.tif'],lambda a:a[0]*8+a[1]*10)
    risk,valid,meta=raster(out/'risk_zones.tif');land,vl,ml=raster(work/'dataset/land_cover.tif')
    candidate,vc,mc=raster(out/'undeveloped_areas.tif')
    if same_grid(meta,ml) and same_grid(meta,mc):
        expected=(risk>100)&np.isin(land,[31,41,43,52,71,81,90,95])&valid&vl
        result['undeveloped_mask_mismatches']=int(np.sum(expected!=((candidate>0)&vc)))
    results['26']=result
    for ident in ['12','36']:
        files=list((root/'tasks'/ident/'attempt_01/dataset').glob('*.tif'));ds=gdal.Open(str(files[0]))
        bands=[ds.GetRasterBand(i).ReadAsArray() for i in range(1,ds.RasterCount+1)]
        results[ident]={'bands':ds.RasterCount,'data_type':gdal.GetDataTypeName(ds.GetRasterBand(1).DataType),
                       'first_three_bands_equal':bool(len(bands)>=3 and np.array_equal(bands[0],bands[1]) and np.array_equal(bands[0],bands[2])),
                       'unit':ds.GetRasterBand(1).GetUnitType(),'scale':ds.GetRasterBand(1).GetScale(),'offset':ds.GetRasterBand(1).GetOffset(),
                       'scope':'Source is a display-like quantized surface. Physical elevation/ruggedness units are not recoverable from these metadata.'}
    # SAVI contains an additive dimensionless L, so radiometric scaling matters.
    raw=1.5*(6000-2000)/(6000+2000+.5);reflectance=1.5*(.6-.2)/(.6+.2+.5)
    results['32']={'synthetic_SAVI_on_DN':raw,'synthetic_SAVI_on_reflectance':reflectance,
                   'same_radiance_up_to_factor_10000':True,'scope':'Demonstrates unit sensitivity; does not infer absent sensor calibration coefficients.'}
    for ident,result in results.items():
        (root/'tasks'/ident/'attempt_01/evaluation/independent-formulas.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=True,indent=2))


if __name__=='__main__':run(Path(sys.argv[1]).resolve())
