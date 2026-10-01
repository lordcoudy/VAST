"""Bounded standard plots of independently reduced original four-arm values."""
import csv
import io
import json
import os
from pathlib import Path
import re
import sys


def render_four_arm_exports_v1(rows,latencies,out,font_cache,hold,doc,clock):
    assert len(rows)==len(latencies)==4
    cache=Path(font_cache)
    assert cache.parent==Path.home()/'.cache/matplotlib'
    match=re.fullmatch(r'fontlist-v([0-9]+)\.json',cache.name)
    assert match is not None
    fontdata=doc(cache)
    assert fontdata['_version']==int(match[1])
    assert cache.stat().st_size<=1048576
    mpldir=out/'mpl';mpldir.mkdir(mode=0o700,exist_ok=False)
    raw=cache.read_bytes()
    with (mpldir/cache.name).open('xb') as stream:
        assert stream.write(raw)==len(raw);stream.flush();os.fsync(stream.fileno())
    os.environ['MPLCONFIGDIR']=str(mpldir)
    # Missing/invalid cache is an original failure. The reader's audit hook
    # forbids fc-list or any other subprocess rather than rescuing it.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm
    assert fm.FontManager.__version__==int(match[1])
    for module in (matplotlib,fm):hold(Path(module.__file__).resolve())
    hold(Path(fm.findfont(fm.FontProperties())).resolve())
    fields=['operation_id','scenario','measurement_admitted','frames','measurement_dropped',
        'measurement_censored','completed_deadline_misses','completion_coverage','latency_p50_ms',
        'latency_p95_ms','latency_p99_ms','latency_max_ms','throughput_fps','latency_population']
    additional=['resource','completed_deadline_miss_percent','on_time_completed','on_time_ingress_coverage',
        'c_obs_total_ms','c_obs_cpu_total_ms','c_obs_gpu_total_ms','c_obs_in_ms_per_ingress',
        'c_obs_comp_ms_per_completed','c_obs_is_partial','decoder_factory','decoder_required_resource',
        'confidence_interval','confidence_interval_reason']
    values=[]
    for row in rows:
        summary=row['recomputed_v2_summary'];metrics=row['recomputed_descriptive_metrics']
        admitted=metrics['measurement_admitted'];completed=metrics['frames'];missed=metrics['completed_deadline_misses']
        assert admitted>0 and len(latencies[len(values)])==completed
        assert metrics['measurement_censored']==0
        value={**metrics,'operation_id':row['operation_id'],'scenario':row['scenario'],'resource':row['resource'],
            'completed_deadline_miss_percent':100*missed/completed if completed else None,
            'on_time_completed':completed-missed,'on_time_ingress_coverage':(completed-missed)/admitted,
            **{key:summary[key] for key in additional if key.startswith('c_obs_') or key.startswith('decoder_')},
            'confidence_interval':None,'confidence_interval_reason':'one_original_descriptive_pair_per_resource'}
        values.append(value)
    table=io.StringIO(newline='');writer=csv.DictWriter(table,fieldnames=fields+additional,lineterminator='\n');writer.writeheader()
    for value in values:writer.writerow({key:value[key] for key in fields+additional})
    rawtable=table.getvalue().encode();assert len(rawtable)<=1048576
    with (out/'four_arm_metrics.csv').open('xb') as stream:
        assert stream.write(rawtable)==len(rawtable);stream.flush();os.fsync(stream.fileno())
    with matplotlib.rc_context({'svg.hashsalt':'vast-four-original-arms-v1'}):
        figure,axes=plt.subplots(3,1,figsize=(10,12))
        try:
            labels=[]
            for value,latency in zip(values,latencies,strict=True):
                label=value['resource'].upper()+(' Baseline' if 'baseline' in value['scenario'] else ' Shared')
                labels.append(label)
                if latency:axes[0].step(latency,[(i+1)/len(latency) for i in range(len(latency))],where='post',
                    label=label+' (n='+str(len(latency))+'/'+str(value['measurement_admitted'])+')')
                else:axes[0].plot([],[],label=label+' (no completed frames)')
            axes[0].axvline(100,color='0.4',linestyle='--',label='100 ms deadline')
            axes[0].set(xlabel='Completed-frame end-to-end latency (ms)',ylabel='Empirical cumulative fraction',ylim=(0,1.02))
            axes[0].legend()
            axes[1].bar([i-.18 for i in range(4)],[100*v['completion_coverage'] for v in values],width=.36,label='Completed/admitted')
            axes[1].bar([i+.18 for i in range(4)],[100*v['on_time_ingress_coverage'] for v in values],width=.36,label='On-time/admitted')
            axes[1].set(xticks=range(4),xticklabels=labels,ylabel='Ingress coverage (%)',ylim=(0,102));axes[1].legend()
            axes[2].bar(labels,[v['c_obs_in_ms_per_ingress'] for v in values])
            axes[2].set(ylabel='Partial attributed stage elapsed (ms/ingress)',xlabel='One original pair per resource')
            figure.suptitle('Four original GStreamer arms: descriptive topology/load proxies')
            figure.text(.5,.012,'Completed-only latency; drops have no invented latency. CPU/GPU label analytics placement.\n'
                'NVDEC decoding in all arms; C_obs is partial attributed elapsed, not processor work, energy or true busy time.\n'
                'No population/accuracy/noninferiority claim or confidence interval.',ha='center',fontsize=9)
            figure.tight_layout(rect=(0,.065,1,.97));graphic=io.BytesIO()
            figure.savefig(graphic,format='svg',metadata={'Date':None})
        finally:plt.close(figure)
    clock();rawgraphic=graphic.getvalue();assert len(rawgraphic)<=1048576
    with (out/'four_arm_latency_coverage_cobs.svg').open('xb') as stream:
        assert stream.write(rawgraphic)==len(rawgraphic);stream.flush();os.fsync(stream.fileno())
    clock()
    comparisons={}
    for index,resource in [(0,'cpu'),(2,'gpu')]:
        baseline,shared=values[index:index+2];comparisons[resource]={}
        for key in ['completion_coverage','on_time_ingress_coverage','c_obs_in_ms_per_ingress','c_obs_comp_ms_per_completed']:
            b,s=baseline[key],shared[key]
            comparisons[resource][key]={'baseline':b,'shared':s,'shared_minus_baseline':None if b is None or s is None else s-b,
                'shared_over_baseline':s/b if b is not None and b>0 and s is not None else None,
                'ratio_reason':None if b is not None and b>0 and s is not None else 'baseline_is_not_positive_or_metric_unavailable'}
    return {'schema_version':1,'scope':'topology_load_proxy_only','rows':values,'comparisons':comparisons,
        'original_cpu_on_time_completed_zero':all(v['on_time_completed']==0 for v in values[:2]),
        'confidence_interval':None,'confidence_interval_reason':'one_original_descriptive_pair_per_resource',
        'latency_population':'completed_measurement_frames','drops_have_no_latency':True,
        'c_obs_scope':'partial_observed_attributed_stage_elapsed','true_nvdec_busy_time_claim':False,
        'processor_work_or_energy_claim':False,'accuracy_or_population_claim':False,
        'matplotlib_version':matplotlib.__version__,'python_version':sys.version,'font_cache':str(cache),
        'measurement_acceptance':False,'full_campaign_acceptance':False}
