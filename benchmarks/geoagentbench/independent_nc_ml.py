"""Independent source-array and metric recomputation for selected delivered tables."""
import csv
import json
import sys
from pathlib import Path
import numpy as np
from osgeo import gdal
from scipy.stats import rankdata

gdal.UseExceptions()


def csv_rows(path):
    return list(csv.DictReader(path.open(encoding='utf-8-sig')))


def variable(path,name):
    ds=gdal.Open(f'NETCDF:"{path}":{name}')
    a=ds.ReadAsArray().astype(float);nd=ds.GetRasterBand(1).GetNoDataValue()
    if nd is not None:a[a==nd]=np.nan
    return a,ds


def auc(y,p):
    y=np.asarray(y);p=np.asarray(p);n1=int((y==1).sum());n0=int((y==0).sum())
    return float((rankdata(p)[y==1].sum()-n1*(n1+1)/2)/(n1*n0))


def run(root):
    result={}
    def work(i):return root/'tasks'/str(i).zfill(2)/'attempt_01'
    # Task 13: independent GDAL raster path, all depth-level means.
    try:
        w=work(13);source=w/'dataset/atlantic_profiles.nc'
        container=gdal.Open(str(source));subs=container.GetSubDatasets()
        arrays={}
        for path,_ in subs:
            key=path.rsplit(':',1)[-1]
            ds=gdal.Open(path);a=ds.ReadAsArray().astype(float);nd=ds.GetRasterBand(1).GetNoDataValue()
            if nd is not None:a[a==nd]=np.nan
            arrays[key]=a
        rows=csv_rows(w/'output/data/ts_profile_by_depth.csv')
        theta=next(v for k,v in arrays.items() if 'theta' in k.lower())
        sal=next(v for k,v in arrays.items() if 'sal' in k.lower())
        result['13']={'layers':len(rows),'temperature_max_abs_error':float(np.max(np.abs(np.nanmean(theta,axis=(-2,-1))-273.15-[float(r['theta_mean_degC']) for r in rows]))),
                      'salinity_max_abs_error':float(np.max(np.abs(np.nanmean(sal,axis=(-2,-1))-[float(r['salinity_mean']) for r in rows])))}
    except Exception as e:result['13']={'error':str(e)}
    # Task 14: direct enumeration of every five-year window from original bands.
    try:
        w=work(14);source=next((w/'dataset').glob('*.nc'));ds=gdal.Open(str(source));a=ds.ReadAsArray()
        if a.ndim!=3:raise ValueError('Expected time x row x col raster view')
        expected=sum(np.all(a[k:k+5]>280,axis=0) for k in range(a.shape[0]-4))
        candidate=gdal.Open(str(w/'output/intermediate/warm_spell_count_5yr_windows.tif')).ReadAsArray()
        result['14']={'years':a.shape[0],'cells':int(candidate.size),'max_count_error':int(np.abs(candidate.astype(int)-expected).max())}
    except Exception as e:result['14']={'error':str(e)}
    # Task 16: actual annual means and centered least-squares, not candidate fit code.
    try:
        w=work(16);source=next((w/'dataset').glob('*.nc'));ds=gdal.Open(str(source));a=ds.ReadAsArray().astype(float)
        nd=ds.GetRasterBand(1).GetNoDataValue()
        if nd is not None:a[a==nd]=np.nan
        means=np.nanmean(a,axis=(-2,-1))-273.15
        rows=csv_rows(w/'output/annual_temperature_series.csv');years=np.array([float(r['Year']) for r in rows])
        x=years-years.mean();matrix=np.column_stack([np.ones(len(x)),x,x*x]);beta=np.linalg.lstsq(matrix,means,rcond=None)[0]
        predicted=matrix@beta;fits=csv_rows(w/'output/fit_polynomial_results.csv')
        result['16']={'years':len(rows),'annual_mean_max_abs_error':float(np.max(np.abs(means-[float(r['Temperature_C']) for r in rows]))),
                      'quadratic_fit_max_abs_error':float(np.max(np.abs(predicted-[float(r['Fitted_Temperature']) for r in fits])))}
    except Exception as e:result['16']={'error':str(e)}
    # Task 27: recompute delivered held-out MSE. Separate from complete RF validation.
    try:
        w=work(27);files=list((w/'output').rglob('model_predictions.csv'));rows=csv_rows(files[0]);keys=list(rows[0])
        truth=next(k for k in keys if k.lower() in ['actual','y_true','observed','interactionstrength'])
        pred=next(k for k in keys if k.lower() in ['predicted','y_pred','prediction'])
        mse=float(np.mean([(float(r[truth])-float(r[pred]))**2 for r in rows]));saved=json.loads((w/'output/model_performance.json').read_text())
        result['27']={'prediction_rows':len(rows),'recomputed_mse':mse,'reported_mse':saved['mse'],'difference':abs(mse-saved['mse']),
                      'scope':'Predictions vs delivered holdout labels; source aggregation and split reviewed separately.'}
    except Exception as e:result['27']={'error':str(e)}
    # Task 53: rank-sum AUC independently, no import or unpickling of candidate RF.
    try:
        w=work(53);random=csv_rows(w/'output/results/oof_predictions.csv');spatial=csv_rows(w/'output/results/oof_predictions_spatial.csv')
        result['53']={'random_oof_rows':len(random),'random_oof_auc':auc([int(r['label']) for r in random],[float(r['oof_prob_repeat1']) for r in random]),
                      'spatial_oof_rows':len(spatial),'spatial_oof_auc':auc([int(r['label']) for r in spatial],[float(r['oof_prob_block']) for r in spatial]),
                      'scope':'AUC recomputation from delivered predictions; source feature extraction and fold isolation reviewed separately.'}
    except Exception as e:result['53']={'error':str(e)}
    for identifier,record in result.items():
        (work(identifier)/'evaluation/independent-source-metrics.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True,indent=2))


if __name__=='__main__':run(Path(sys.argv[1]))
