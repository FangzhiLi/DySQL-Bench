#!/usr/bin/env python3
"""Post-hoc failure attribution for a DySQL-Bench result dir.
Usage: conda run -n dysql python scripts/classify_failures.py results/<run_dir> [out_dir]
Prints primary-cause tables; writes fail_analysis2.json / pass_analysis2.json to out_dir."""
import json,glob,re,sys,datetime
from collections import Counter,defaultdict
import sqlparse
OUT=sys.argv[2] if len(sys.argv)>2 else '/tmp/'
rs=[]
for f in sorted(glob.glob(sys.argv[1]+'/*.json')):
    if f.endswith('config.json'): continue
    rs+=json.load(open(f))
fails=[r for r in rs if r['reward']<1]; passes=[r for r in rs if r['reward']>=1]
BLOCK=re.compile(r"```sql(.*?)```|<sql>(.*?)</sql>",re.DOTALL)
WRITE=("UPDATE","INSERT","DELETE","ALTER","CREATE","DROP")
def nocomment(s): return re.sub(r'--[^\n]*','',s)
def stype(s):
    try: return sqlparse.parse(s)[0].get_type().upper()
    except Exception: return "UNKNOWN"
def wtable(s):
    m=re.search(r"\b(?:UPDATE|INSERT\s+INTO|DELETE\s+FROM|INSERT\s+OR\s+\w+\s+INTO)\s+[\"\[`]?(\w+)",nocomment(s),re.I)
    return m.group(1).lower() if m else None
NUM=re.compile(r"(?<![\w.])\d{2,}(?:\.\d+)?(?![\w])")
def analyze(r):
    t=r['info'].get('task') or {'actions':[],'instruction':''}; meta=r['meta']
    gold=[a['kwargs']['sql'] for a in t['actions'] if a['name']=='sql']
    gold_stmts=[s for g in gold for s in sqlparse.split(g) if s.strip()]
    gold_w=[s for s in gold_stmts if stype(s) in WRITE]
    gold_wt=set(filter(None,(wtable(s) for s in gold_w)))
    agent_log=[s for s in r['sql_log'] if s['phase']=='agent']
    exec_w=[s for s in agent_log if s['type'] in WRITE]
    exec_w_ok=[s for s in exec_w if not s['error']]
    exec_wt=set(filter(None,(wtable(s['sql']) for s in exec_w_ok)))
    dropped_w=[]
    phantom=False; escalate=False; awaiting=False
    for m in r['traj']:
        if m['role']!='assistant': continue
        c=m.get('content') or ''
        blocks=[(a or b) for a,b in BLOCK.findall(c)]
        for b in blocks[1:]:
            for s in sqlparse.split(b):
                s2=nocomment(s).strip()
                if s2 and stype(s2) in WRITE: dropped_w.append(s2)
        outside=BLOCK.sub('',c)
        if re.search(r"^\s*(UPDATE|INSERT\s+INTO|DELETE\s+FROM)\s+\w+",outside,re.I|re.M) and not blocks: phantom=True
        if re.search(r"human agent|transfer you|escalat",c,re.I): escalate=True
    lastA=[m for m in r['traj'] if m['role']=='assistant']
    if lastA and re.search(r"confirm|yes|proceed",lastA[-1].get('content') or '',re.I) and re.search(r"\?",lastA[-1].get('content') or ''): awaiting=True
    dropped_wt=set(filter(None,(wtable(s) for s in dropped_w)))
    ri=(r['info'].get('reward_info') or {}).get('info') or {}
    mism=set(x.lower() for x in (ri.get('mismatched_tables') or []))
    # hallucinated literal: numeric literals in executed writes absent from instruction + real sql results
    real=t.get('instruction','')+' '.join((m.get('content') or '') for m in r['traj'] if m['role']=='user')
    realnums=set(NUM.findall(real))
    halluc=[]
    for s in exec_w_ok:
        for n in NUM.findall(nocomment(s['sql'])):
            if n not in realnums and n.rstrip('0').rstrip('.') not in realnums and (n+'.0') not in realnums and (n+'.00') not in realnums: halluc.append(n)
    flags=set()
    if meta['termination']!='user_stop': flags.add('abnormal_termination')
    if not gold_w: flags.add('gold_no_write')
    if meta.get('gold_zero_row_writes'): flags.add('gold_noop_write')
    if dropped_w: flags.add('dropped_write_in_extra_block')
    if gold_w and not exec_w: flags.add('no_write_executed')
    missing=gold_wt-exec_wt; extra=exec_wt-gold_wt
    if missing: flags.add('missing_table_write')
    if extra: flags.add('extra_table_write')
    if any(s['rowcount']==0 and s['type'] in ('UPDATE','DELETE','INSERT') for s in exec_w_ok): flags.add('zero_row_write')
    if any(s['error'] for s in exec_w): flags.add('write_sql_error')
    if meta.get('n_fabricated_results'): flags.add('fabricated_result')
    if phantom: flags.add('phantom_sql_outside_block')
    if escalate: flags.add('escalated_to_human')
    if halluc: flags.add('hallucinated_literal')
    # primary
    term=meta['termination']
    if term!='user_stop': p='A. abnormal_termination:'+term
    elif not gold_w: p='H. gold_has_no_write(agent wrote anyway)'
    elif dropped_w and (dropped_wt&mism or not exec_w): p='B. write_dropped_in_extra_sql_block'
    elif not exec_w:
        if phantom: p='C. no_write:phantom_sql_outside_block'
        elif escalate: p='C. no_write:escalated_to_human'
        elif 'write_sql_error' in flags: p='C. no_write:sql_error_unrecovered'
        elif awaiting: p='C. no_write:stopped_while_awaiting_confirm'
        else: p='C. no_write:claimed_done_without_sql'
    elif missing:
        if phantom: p='D. partial:phantom_sql_outside_block'
        elif 'write_sql_error' in flags: p='D. partial:sql_error_unrecovered'
        elif halluc: p='D. partial:hallucinated_ids'
        else: p='D. partial:sub_request_skipped_or_wrong_table'
    elif extra: p='E. extra_table_write'
    elif 'gold_noop_write' in flags: p='G. gold_noop_task'
    elif 'zero_row_write' in flags: p=('F. wrong_where:hallucinated_ids' if halluc else 'F. wrong_where:zero_rows')
    else: p=('F. wrong_values:hallucinated_ids' if halluc else 'F. wrong_values:other')
    return dict(env=meta['env'],task_id=r['task_id'],length=meta['length'],primary=p,flags=sorted(flags),
                gold_wt=sorted(gold_wt),exec_wt=sorted(exec_wt),dropped_wt=sorted(dropped_wt),missing=sorted(missing),extra=sorted(extra),
                halluc=halluc[:5],n_gold_w=len(gold_w),n_exec_w=len(exec_w_ok),n_dropped_w=len(dropped_w),mismatched=sorted(mism))
A=[analyze(r) for r in fails]; P=[analyze(r) for r in passes]
json.dump(A,open(OUT+'fail_analysis2.json','w'),indent=1,ensure_ascii=False)
json.dump(P,open(OUT+'pass_analysis2.json','w'),indent=1,ensure_ascii=False)
print("TOTAL",len(rs),"fail",len(fails),"pass",len(passes))
print("\n== PRIMARY CAUSE (572 fails) ==")
c=Counter(a['primary'] for a in A)
for k,v in sorted(c.items()): print(f"{v:4d} {100*v/len(fails):5.1f}%  {k}")
print("\n== TOP-LEVEL ==")
c2=Counter(a['primary'][:2] for a in A)
for k,v in sorted(c2.items()): print(f"{v:4d} {100*v/len(fails):5.1f}%  {k}")
print("\n== FLAGS fail vs pass ==")
cf=Counter(x for a in A for x in a['flags']); cp=Counter(x for a in P for x in a['flags'])
for k in sorted(set(cf)|set(cp),key=lambda k:-cf[k]): print(f"{k:32s} fail {cf[k]:4d} ({100*cf[k]/len(fails):5.1f}%)  pass {cp[k]:4d} ({100*cp[k]/len(passes):5.1f}%)")
print("\n== TOP-LEVEL x LENGTH ==")
for L in ('short','long'):
    n=sum(1 for a in A if a['length']==L); tot=sum(1 for r in rs if r['meta']['length']==L)
    print(f"{L}: {n}/{tot} fail"); 
    for k,v in sorted(Counter(a['primary'][:2] for a in A if a['length']==L).items()): print(f"   {v:4d} {100*v/n:5.1f}% {k}")
print("\n== TOP-LEVEL x ENV ==")
keys=sorted(c2)
print(f"{'env':16s} {'fail/total':>10s} "+" ".join(f"{k:>3s}" for k in keys))
for e in sorted(set(r['meta']['env'] for r in rs)):
    ce=Counter(a['primary'][:2] for a in A if a['env']==e); ne=sum(ce.values()); nt=sum(1 for r in rs if r['meta']['env']==e)
    print(f"{e:16s} {ne:4d}/{nt:<5d} "+" ".join(f"{ce[k]:3d}" for k in keys))
# gold-noop with/without
noop=[r for r in rs if (r['meta'].get('gold_zero_row_writes') or 0)>0]
print(f"\ngold no-op tasks: {len(noop)}, pass among them {sum(1 for r in noop if r['reward']>=1)}; pass rate excluding them: {100*sum(1 for r in rs if r['reward']>=1 and not (r['meta'].get('gold_zero_row_writes') or 0))/(len(rs)-len(noop)):.1f}%")
# multi-block stats
mb=[r for r in rs if (r['meta'].get('n_extra_sql_blocks') or 0)>0]
print(f"runs with extra sql blocks: {len(mb)} ({100*len(mb)/len(rs):.1f}%), pass rate among them {100*sum(1 for r in mb if r['reward']>=1)/len(mb):.1f}% vs {100*sum(1 for r in rs if r['reward']>=1 and not (r['meta'].get('n_extra_sql_blocks') or 0))/(len(rs)-len(mb)):.1f}% without")
fab=[r for r in rs if (r['meta'].get('n_fabricated_results') or 0)>0]
print(f"runs with fabricated <result>: {len(fab)} ({100*len(fab)/len(rs):.1f}%), pass rate {100*sum(1 for r in fab if r['reward']>=1)/len(fab):.1f}% vs {100*sum(1 for r in rs if r['reward']>=1 and not (r['meta'].get('n_fabricated_results') or 0))/(len(rs)-len(fab)):.1f}% without")
dw=[a for a in A+P if a['n_dropped_w']>0]
print(f"runs with a WRITE in a dropped block: {len(dw)} ({100*len(dw)/len(rs):.1f}%), of which failed {sum(1 for a in A if a['n_dropped_w']>0)}")
